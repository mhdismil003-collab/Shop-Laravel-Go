'use strict';

const byId = (id) => document.getElementById(id);
const money = new Intl.NumberFormat('ar-SY-u-nu-latn', { maximumFractionDigits: 2 });
const clock = new Intl.DateTimeFormat('ar-SY', { dateStyle: 'short', timeStyle: 'short' });
const cart = new Map();
const pending = new WeakSet();
const labels = {
    Pending: 'قيد الانتظار', Confirmed: 'مؤكّد', Shipped: 'مشحون',
    Delivered: 'مسلّم', Cancelled: 'ملغى',
};
const transitions = {
    Pending: ['Confirmed', 'Cancelled'], Confirmed: ['Shipped', 'Cancelled'], Shipped: ['Delivered'],
};
const fieldMessages = {
    email: 'أدخل بريدًا إلكترونيًا صحيحًا.',
    password: 'أدخل كلمة مرور من 8 أحرف على الأقل، فيها أحرف كبيرة وصغيرة ورقم ورمز.',
    name: 'أدخل اسم المنتج بما لا يتجاوز 160 حرفًا.',
    description: 'أدخل وصف المنتج بما لا يتجاوز 4000 حرف.',
    price: 'أدخل سعرًا موجبًا بدقة منزلتين عشريتين على الأكثر.',
    categoryId: 'اختر تصنيفًا من القائمة.',
    image: 'اختر صورة JPG أو PNG أو WebP لا تتجاوز 2 ميغابايت.',
    initialQuantity: 'أدخل كمية ابتدائية صحيحة بين 0 و2147483647.',
};
let token = null;
let user = null;
let page = 1;
let orderPage = 1;
let catalogRequest = 0;
let productRequest = 0;
let orderRequest = 0;
let orderListRequest = 0;
let notificationTask = null;
let notificationSnapshot = '';

class ApiError extends Error {
    constructor(response, problem, session) {
        super(problem.userMessage ?? 'تعذّر إتمام العملية. حاول مجددًا.');
        this.status = response.status;
        this.code = problem.code;
        this.traceId = problem.traceId;
        this.errors = problem.errors ?? {};
        this.shortages = problem.shortages ?? [];
        this.retryAfter = Number(response.headers.get('Retry-After'));
        this.session = session;
    }
}

function element(tag, text, className) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
}

function notice(text, { error = false, traceId } = {}) {
    const box = byId('feedback-box');
    box.hidden = !text;
    box.toggleAttribute('data-error', error);
    byId('feedback').textContent = text;
    const ref = byId('feedback-ref');
    ref.hidden = !traceId;
    ref.textContent = traceId ? 'رقم التتبع: ' + traceId : '';
}

function button(text, action) {
    const result = element('button', text);
    result.type = 'button';
    result.addEventListener('click', () => run(action, { control: result }));
    return result;
}

function sessionExpired(error) {
    if (error instanceof ApiError && error.code === 'common.unauthorized'
        && error.session !== null && error.session === token) {
        token = null;
        user = null;
        renderSession();
        return true;
    }
    return false;
}

async function run(action, { control, form } = {}) {
    if (control && pending.has(control)) return;
    const controls = form ? Array.from(form.querySelectorAll('button:not(:disabled)'))
        : control && !control.disabled ? [control] : [];
    if (control) {
        pending.add(control);
        control.setAttribute('aria-busy', 'true');
    }
    if (control?.id === 'checkout') renderCart();
    controls.forEach(item => { item.disabled = true; });
    try {
        await action();
    } catch (error) {
        sessionExpired(error);
        if (form && error instanceof ApiError) {
            const fields = Object.fromEntries(Object.keys(error.errors).map(field => [field, fieldMessages[field]]));
            if (error.code === 'users.duplicate_email') fields.email = error.message;
            if (form.id === 'new-product' && [413, 415].includes(error.status)) fields.image = error.message;
            showFieldErrors(form, fields);
        }
        let message = error instanceof ApiError || error instanceof ShopMessage
            ? error.message : 'حدث خطأ غير متوقع. حدّث الصفحة وحاول مجددًا.';
        if (error instanceof ApiError && error.shortages.length) {
            const lines = error.shortages.map(item => {
                const name = cart.get(item.productId)?.name ?? 'منتج في السلة';
                return name + ' — المطلوب ' + money.format(item.requested) + '، المتوفر ' + money.format(item.available);
            });
            message += ' ' + lines.join('، ');
        }
        if (error.status === 429 && error.retryAfter > 0) {
            message += ' يمكنك المحاولة بعد ' + money.format(error.retryAfter) + ' ثانية.';
        }
        notice(message, { error: true, traceId: error.status >= 500 ? error.traceId : undefined });
    } finally {
        if (control) {
            pending.delete(control);
            control.removeAttribute('aria-busy');
        }
        controls.forEach(item => { item.disabled = false; });
        if (control?.id === 'checkout') renderCart();
    }
}

class ShopMessage extends Error {}

async function api(path, { method = 'GET', body } = {}) {
    const session = token;
    const headers = { Accept: 'application/json' };
    if (session) headers.Authorization = 'Bearer ' + session;
    if (body && !(body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
        body = JSON.stringify(body);
    }
    let response;
    try {
        response = await fetch('/api/v1' + path, { method, headers, body, signal: AbortSignal.timeout(10000) });
    } catch {
        const message = method === 'POST' && path === '/orders'
            ? 'انقطع الاتصال قبل تأكيد نتيجة الطلب. راجع طلباتك قبل إعادة المحاولة.'
            : 'تعذّر الاتصال بالمتجر. تحقّق من اتصالك وحاول مجددًا.';
        throw new ShopMessage(message);
    }
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new ApiError(response, data ?? {}, session);
    if (!data) {
        throw new ShopMessage(method === 'POST' && path === '/orders'
            ? 'لم تصل نتيجة واضحة. راجع طلباتك قبل إعادة المحاولة.'
            : 'تعذّر قراءة رد المتجر. حدّث الصفحة وحاول مجددًا.');
    }
    return data;
}

function showFieldErrors(form, errors = {}) {
    let first;
    for (const marker of form.querySelectorAll('[data-field-error]')) {
        const name = marker.dataset.fieldError;
        const input = form.elements.namedItem(name);
        const message = errors[name] ?? '';
        marker.id ||= form.id + '-' + name + '-error';
        marker.textContent = message;
        marker.hidden = !message;
        if (message) {
            input.setAttribute('aria-invalid', 'true');
            input.setAttribute('aria-describedby', marker.id);
            first ??= input;
        } else {
            input.removeAttribute('aria-invalid');
            input.removeAttribute('aria-describedby');
        }
    }
    if (first) first.focus();
    return first === undefined;
}

function validateForm(form, registering = false) {
    const errors = {};
    for (const marker of form.querySelectorAll('[data-field-error]')) {
        const name = marker.dataset.fieldError;
        const input = form.elements.namedItem(name);
        if (!input.validity.valid || (input.type !== 'file' && input.value.trim() === '')) {
            errors[name] = fieldMessages[name];
        }
    }
    if (form.id === 'account') {
        const password = form.elements.password.value;
        if (!password) errors.password = 'أدخل كلمة المرور.';
        else if (new TextEncoder().encode(password).length > 72) errors.password = 'كلمة المرور طويلة جدًا. استخدم 72 بايت أو أقل.';
        else if (registering && ([...password].length < 8 || !/\p{Lu}/u.test(password)
            || !/\p{Ll}/u.test(password) || !/\p{N}/u.test(password) || !/[^\p{L}\p{N}\s]/u.test(password))) {
            errors.password = fieldMessages.password;
        }
    }
    if (form.id === 'new-product') {
        const file = form.elements.image.files[0];
        if (file?.size > 2 * 1024 * 1024) errors.image = 'حجم الصورة يتجاوز 2 ميغابايت. اختر صورة أصغر.';
        else if (file?.type && !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) errors.image = fieldMessages.image;
    }
    return showFieldErrors(form, errors);
}

async function loadCategories() {
    const categories = await api('/categories');
    for (const select of [byId('category'), byId('new-product').elements.categoryId]) {
        for (const category of categories) select.add(new Option(category.name, category.id));
    }
}

async function loadCatalog(nextPage = page) {
    const request = ++catalogRequest;
    const target = byId('catalog');
    target.setAttribute('aria-busy', 'true');
    if (!target.children.length) target.append(element('p', 'جارٍ تحميل المنتجات…', 'empty'));
    const params = new URLSearchParams({ page: nextPage, pageSize: 8 });
    const category = byId('category').value;
    if (category) params.set('category', category);
    try {
        const result = await api('/products?' + params);
        if (request !== catalogRequest) return;
        page = nextPage;
        target.replaceChildren(...result.items.map((item) => {
            const card = element('article', undefined, 'card');
            const image = element('img');
            image.src = item.imageUrl;
            image.alt = item.name;
            image.loading = 'lazy';
            image.addEventListener('error', () => image.replaceWith(element('p', 'الصورة غير متاحة', 'image-empty')));
            const content = element('div', undefined, 'card-content');
            content.append(element('span', item.categoryName, 'kicker'), element('h3', item.name),
                element('p', money.format(item.price), 'price'),
                button('تفاصيل المنتج', () => showProduct(item.id)));
            card.append(image, content);
            return card;
        }));
        if (!result.items.length) target.append(element('p', 'لا توجد منتجات في هذا التصنيف.', 'empty'));
        byId('catalog-count').textContent = money.format(result.totalCount) + ' منتج';
        byId('page').textContent = 'صفحة ' + money.format(page);
        byId('previous').disabled = page <= 1;
        byId('next').disabled = page * result.pageSize >= result.totalCount;
    } catch (error) {
        if (request !== catalogRequest) return;
        byId('catalog-count').textContent = '';
        byId('page').textContent = '';
        byId('previous').disabled = true;
        byId('next').disabled = true;
        target.replaceChildren(element('p', 'تعذّر تحميل المنتجات.', 'empty'),
            button('إعادة التحميل', () => loadCatalog(nextPage)));
        throw error;
    } finally {
        if (request === catalogRequest) target.removeAttribute('aria-busy');
    }
}

async function showProduct(id) {
    const target = byId('product');
    const request = ++productRequest;
    const session = token;
    target.hidden = false;
    target.replaceChildren(element('p', 'جارٍ التحقق من توفر المنتج…'));
    try {
        const item = await api('/products/' + id);
        if (request !== productRequest || token !== session) return;
        target.replaceChildren(element('h3', item.name), element('p', item.description),
            element('p', 'الكمية المتوفرة: ' + money.format(item.availableQuantity), 'price'));
        if (user?.roles.includes('Customer') && item.availableQuantity > 0) {
            target.append(button('أضف وحدة إلى السلة', () => addCartUnit(item)));
        } else if (item.availableQuantity === 0) {
            target.append(element('p', 'هذا المنتج غير متوفر حاليًا.', 'muted'));
        } else if (!user) {
            target.append(element('p', 'سجّل الدخول لإضافة المنتج إلى السلة.', 'muted'));
        }
        if (user?.roles.includes('Admin')) renderStockForm(target, id);
        target.focus();
    } catch (error) {
        if (request !== productRequest || token !== session) return;
        target.replaceChildren(element('p', 'تعذّر عرض الكمية المتوفرة.'),
            button('تحقّق مجددًا', () => showProduct(id)));
        if (user?.roles.includes('Admin') && pendingStock(id)) renderStockForm(target, id);
        throw error;
    }
}

const stockKey = (id) => 'shop.stock-addition.' + id;

function pendingStock(id) {
    return JSON.parse(sessionStorage.getItem(stockKey(id)));
}

async function addStock(id, change) {
    const key = stockKey(id);
    const clear = () => {
        if (pendingStock(id)?.operationId === change.operationId) sessionStorage.removeItem(key);
    };
    sessionStorage.setItem(key, JSON.stringify(change));
    try {
        await api('/products/' + id + '/stock-additions', { method: 'POST', body: change });
    } catch (error) {
        if (error instanceof ApiError && [404, 409, 422].includes(error.status)) clear();
        throw error;
    }
    clear();
}

function renderStockForm(target, id) {
    const form = element('form', undefined, 'form-grid stock-form');
    const label = element('label', 'الكمية المراد إضافتها');
    const input = element('input');
    input.type = 'number';
    input.dir = 'ltr';
    input.min = '1';
    input.max = '2147483647';
    input.step = '1';
    input.required = true;
    const submit = element('button', 'إضافة رصيد', 'primary');
    submit.type = 'submit';
    const refreshDraft = () => {
        const draft = pendingStock(id);
        input.readOnly = Boolean(draft);
        if (draft) input.value = draft.quantity;
        submit.textContent = draft ? 'إعادة محاولة إضافة الرصيد' : 'إضافة رصيد';
    };
    refreshDraft();
    label.append(input);
    form.append(label, submit);
    target.append(form);
    form.addEventListener('submit', (event) => {
        event.preventDefault();
        run(async () => {
            const session = token;
            const change = pendingStock(id) ?? { quantity: input.valueAsNumber, operationId: crypto.randomUUID() };
            try {
                await addStock(id, change);
            } finally {
                refreshDraft();
            }
            if (token !== session || !form.isConnected) return;
            input.value = '';
            await showProduct(id).catch(() => {});
            notice('تمت إضافة ' + money.format(change.quantity) + ' وحدة إلى المخزون.');
        }, { control: form, form });
    });
}

function addCartUnit(item) {
    if (pending.has(byId('checkout'))) return;
    const line = cart.get(item.id) ?? { id: item.id, name: item.name, price: item.price, quantity: 0 };
    line.availableQuantity = item.availableQuantity;
    if (line.quantity >= Math.min(line.availableQuantity, 1000)) {
        throw new ShopMessage('الكمية في السلة بلغت الحد المتوفر لهذا المنتج.');
    }
    if (!cart.has(item.id) && cart.size === 50) {
        throw new ShopMessage('الحد الأقصى للسلة هو 50 منتجًا مختلفًا.');
    }
    line.quantity++;
    cart.set(item.id, line);
    renderCart();
    notice('أُضيفت وحدة من «' + item.name + '» إلى السلة.');
}

function renderCart() {
    const checkout = byId('checkout');
    const submitting = pending.has(checkout);
    checkout.disabled = cart.size === 0 || submitting;
    byId('clear-cart').disabled = cart.size === 0 || submitting;
    const lines = Array.from(cart, ([id, line]) => {
        const li = element('li', undefined, 'cart-item');
        const details = element('div', undefined, 'cart-item-info');
        details.append(element('strong', line.name),
            element('small', money.format(line.price) + ' للوحدة', 'muted'));
        const controls = element('div', undefined, 'cart-item-controls');
        const counter = element('div', undefined, 'quantity-control');
        counter.setAttribute('role', 'group');
        counter.setAttribute('aria-label', 'كمية ' + line.name);
        const decrease = button('−', () => {
            line.quantity--;
            renderCart();
        });
        decrease.setAttribute('aria-label', 'إنقاص كمية ' + line.name);
        decrease.disabled = submitting || line.quantity <= 1;
        const quantity = element('output', money.format(line.quantity));
        quantity.setAttribute('aria-label', 'الكمية');
        const increase = button('+', () => addCartUnit(line));
        increase.setAttribute('aria-label', 'زيادة كمية ' + line.name);
        increase.disabled = submitting || line.quantity >= Math.min(line.availableQuantity, 1000);
        counter.append(decrease, quantity, increase);
        const remove = button('حذف المنتج', () => {
            cart.delete(id);
            renderCart();
            notice('حُذف «' + line.name + '» من السلة.');
        });
        remove.setAttribute('aria-label', 'حذف ' + line.name + ' من السلة');
        remove.disabled = submitting;
        controls.append(counter, remove);
        li.append(details, element('strong', money.format(line.price * line.quantity), 'cart-item-total'), controls);
        return li;
    });
    byId('cart').replaceChildren(...(lines.length ? lines : [element('li', 'سلتك فارغة. أضف منتجًا من الكتالوج.', 'empty')]));
    const entries = [...cart.values()];
    byId('cart-count').textContent = money.format(entries.reduce((sum, line) => sum + line.quantity, 0));
    byId('cart-total').textContent = 'الإجمالي التقريبي: ' + money.format(entries.reduce((sum, line) => sum + line.quantity * line.price, 0));
}

function statusPill(status) {
    const pill = element('span', labels[status] ?? status, 'status-pill');
    pill.dataset.state = status;
    return pill;
}

async function loadOrders(nextPage = orderPage) {
    const request = ++orderListRequest;
    const session = token;
    const result = await api('/orders?pageSize=20&page=' + nextPage);
    if (token !== session || request !== orderListRequest) return;
    orderPage = nextPage;
    byId('orders').replaceChildren(...result.items.map((item) => {
        const li = element('li');
        li.dataset.orderId = item.id;
        li.append(statusPill(item.status), document.createTextNode(' · ' + money.format(item.total) + ' '),
            button('تفاصيل الطلب', () => showOrder(item.id)),
            element('p', 'رقم الطلب: ' + item.id, 'muted'));
        return li;
    }));
    if (!result.items.length) byId('orders').append(element('li', 'لا توجد طلبات للعرض.', 'empty'));
    byId('order-page').textContent = 'صفحة ' + money.format(orderPage);
    byId('newer-orders').disabled = orderPage <= 1;
    byId('older-orders').disabled = orderPage * result.pageSize >= result.totalCount;
}

async function showOrder(id) {
    const request = ++orderRequest;
    const session = token;
    const item = await api('/orders/' + id);
    if (token !== session || request !== orderRequest) return;
    const target = byId('order');
    target.hidden = false;
    target.replaceChildren(element('h3', 'تفاصيل الطلب'), statusPill(item.status),
        element('p', 'رقم الطلب: ' + item.id, 'muted'));
    const lines = element('ul', undefined, 'list');
    for (const line of item.lines) lines.append(element('li', line.productName + ' × ' + money.format(line.quantity)));
    target.append(lines, element('strong', 'الإجمالي: ' + money.format(item.total)));
    if (user.roles.includes('Admin')) {
        const actions = element('p');
        for (const status of transitions[item.status] ?? []) {
            actions.append(button('تغيير الحالة إلى ' + labels[status], async () => {
                await api('/orders/' + id + '/status', { method: 'PATCH', body: { status } });
                if (token !== session) return;
                notice('تم تحديث حالة الطلب.');
                await Promise.all([loadOrders(), showOrder(id)]);
            }));
        }
        target.append(actions);
    }
    target.focus();
}

async function loadNotifications() {
    const session = token;
    if (!user?.roles.includes('Customer')) return;
    if (notificationTask?.session === session) return notificationTask.promise;
    const task = (async () => {
        try {
            const result = await api('/notifications');
            if (token !== session) return;
            const snapshot = JSON.stringify(result.items);
            if (snapshot !== notificationSnapshot) {
                notificationSnapshot = snapshot;
                byId('notifications').replaceChildren(...result.items.map((item) => {
                    const li = element('li');
                    li.append(statusPill(item.status), document.createTextNode(' '),
                        button('عرض الطلب', () => showOrder(item.orderId)),
                        element('p', clock.format(new Date(item.createdAt)), 'muted'));
                    return li;
                }));
                if (!result.items.length) {
                    byId('notifications').append(element('li', 'تظهر هنا إشعارات إنشاء طلباتك وتحديث حالتها.', 'empty'));
                }
            }
            byId('notification-status').textContent = 'آخر تحديث: ' + clock.format(new Date());
        } catch (error) {
            if (token === session) byId('notification-status').textContent = 'تعذّر تحديث الإشعارات. يمكنك إعادة المحاولة.';
            throw error;
        }
    })();
    notificationTask = { session, promise: task };
    try {
        await task;
    } finally {
        if (notificationTask?.promise === task) notificationTask = null;
    }
}

function refreshNotificationsQuietly() {
    if (document.hidden) return;
    loadNotifications().catch(error => {
        if (sessionExpired(error)) notice(error.message, { error: true });
    });
}

function renderSession() {
    byId('account-title').textContent = user ? 'حساب المتجر' : 'الدخول إلى المتجر';
    byId('account').hidden = user !== null;
    byId('session').hidden = user === null;
    byId('orders-nav').hidden = user === null;
    byId('identity').textContent = user?.email ?? '';
    const admin = user?.roles.includes('Admin');
    const customer = user?.roles.includes('Customer');
    byId('role-label').textContent = admin ? 'مسؤول المتجر' : 'حساب زبون';
    byId('admin-tools').hidden = !admin;
    byId('customer-tools').hidden = !customer;
    byId('cart-nav').hidden = !customer;
    byId('order-tools').hidden = user === null;
    for (const id of ['order', 'product']) {
        byId(id).hidden = true;
        byId(id).replaceChildren();
    }
    byId('orders').replaceChildren();
    byId('notifications').replaceChildren();
    byId('notification-status').textContent = '';
    notificationSnapshot = '';
    cart.clear();
    orderPage = 1;
    renderCart();
}

byId('account').addEventListener('submit', (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const registering = event.submitter?.value === 'register';
    if (!validateForm(form, registering)) {
        notice('راجع الحقول المحددة وصحّح بياناتها.', { error: true });
        return;
    }
    run(async () => {
        const body = Object.fromEntries(new FormData(form));
        if (registering) {
            await api('/auth/register', { method: 'POST', body });
        }
        token = (await api('/auth/login', { method: 'POST', body })).accessToken;
        try {
            user = await api('/users/me');
        } catch (error) {
            token = null;
            throw error;
        }
        form.reset();
        renderSession();
        notice('تم تسجيل الدخول.');
        await Promise.all([loadOrders(), loadNotifications()]);
    }, { control: form, form });
});

byId('logout').onclick = () => { token = null; user = null; renderSession(); notice('تم تسجيل الخروج.'); };
byId('category').onchange = () => run(() => loadCatalog(1));
byId('previous').onclick = () => run(() => loadCatalog(page - 1));
byId('next').onclick = () => run(() => loadCatalog(page + 1));
byId('refresh-orders').onclick = () => run(() => loadOrders(1), { control: byId('refresh-orders') });
byId('newer-orders').onclick = () => run(() => loadOrders(orderPage - 1));
byId('older-orders').onclick = () => run(() => loadOrders(orderPage + 1));
byId('refresh-notifications').onclick = () => run(loadNotifications, { control: byId('refresh-notifications') });
byId('checkout').onclick = () => run(async () => {
    const session = token;
    const lines = Array.from(cart, ([productId, line]) => ({ productId, quantity: line.quantity }));
    const order = await api('/orders', { method: 'POST', body: { lines } });
    if (token !== session) return;
    cart.clear();
    renderCart();
    notice('تم إنشاء الطلب.');
    await Promise.all([loadOrders(1), loadNotifications(), showOrder(order.id)]);
}, { control: byId('checkout') });

byId('clear-cart').onclick = () => {
    if (pending.has(byId('checkout'))) return;
    cart.clear();
    renderCart();
    notice('تم إفراغ السلة.');
};

byId('new-product').addEventListener('submit', (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!validateForm(form)) {
        notice('راجع الحقول المحددة وصحّح بياناتها.', { error: true });
        return;
    }
    run(async () => {
        const session = token;
        const quantity = form.elements.initialQuantity.valueAsNumber;
        const body = new FormData(form);
        body.delete('initialQuantity');
        const result = await api('/products', { method: 'POST', body });
        form.reset();
        byId('category').value = '';
        let stockAdded = quantity === 0;
        let stockError;
        if (quantity > 0) {
            const change = { quantity, operationId: result.id };
            try {
                if (token === session) {
                    await addStock(result.id, change);
                    stockAdded = true;
                } else {
                    sessionStorage.setItem(stockKey(result.id), JSON.stringify(change));
                }
            } catch (error) {
                stockError = error;
                sessionExpired(error);
            }
        }
        await loadCatalog(1);
        if (quantity > 0 && token === session) await showProduct(result.id).catch(() => {});
        if (!stockAdded) {
            notice('تم إنشاء المنتج. تعذّر تأكيد إضافة الكمية. افتح تفاصيل المنتج من حساب المسؤول لاستكمال العملية.'
                + (stockError?.message ? ' ' + stockError.message : ''),
                { error: true, traceId: stockError?.traceId });
        } else {
            notice(quantity > 0 ? 'تمت إضافة المنتج ورصيده الابتدائي.'
                : 'تمت إضافة المنتج. معرّفه: ' + result.id);
        }
    }, { control: form, form });
});

for (const form of [byId('account'), byId('new-product')]) {
    form.addEventListener('input', ({ target }) => {
        if (target.getAttribute('aria-invalid') !== 'true') return;
        target.removeAttribute('aria-invalid');
        const marker = byId(target.getAttribute('aria-describedby'));
        if (marker) marker.hidden = true;
        target.removeAttribute('aria-describedby');
    });
}
document.addEventListener('visibilitychange', refreshNotificationsQuietly);
setInterval(refreshNotificationsQuietly, 10000);
renderSession();
run(() => Promise.all([loadCategories(), loadCatalog()]));
