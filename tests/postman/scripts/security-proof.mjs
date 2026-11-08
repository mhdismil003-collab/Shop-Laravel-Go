export const requiredOperations = [
    'POST /api/v1/auth/register', 'POST /api/v1/auth/login', 'GET /api/v1/users/me',
    'GET /api/v1/categories', 'GET /api/v1/products', 'GET /api/v1/products/{}',
    'POST /api/v1/products', 'POST /api/v1/orders', 'GET /api/v1/orders',
    'GET /api/v1/orders/{}', 'PATCH /api/v1/orders/{}/status',
];

export function operations(document)
{
    return Object.entries(document.paths ?? {}).flatMap(([path, methods]) =>
        Object.keys(methods).filter(method => /^(get|post|put|patch|delete|head|options|trace)$/.test(method))
            .map(method => `${method.toUpperCase()} ${path.replace(/\{[^}]+\}/g, '{}')}`));
}

const script = (listen, source) => ({ listen, script: { type: 'text/javascript', exec: source.trim().split('\n') } });
const bearer = key => ({ type: 'bearer', bearer: [{ key: 'token', value: `{{${key}}}`, type: 'string' }] });

const commonTests = `
pm.test('Baseline security headers', () => {
    pm.expect(pm.response.headers.get('X-Content-Type-Options')).to.equal('nosniff');
    pm.expect(pm.response.headers.get('X-Frame-Options')).to.equal('DENY');
    pm.expect(pm.response.headers.get('Referrer-Policy')).to.equal('no-referrer');
    pm.expect(pm.response.headers.has('Server')).to.equal(false);
});
if (pm.request.headers.has('Authorization') || pm.request.auth?.type === 'bearer') {
    pm.test('Bearer responses are not stored', () => pm.expect(pm.response.headers.get('Cache-Control')).to.match(/(?:^|,)\\s*no-store(?:,|$)/i));
}
if (pm.response.code >= 400) {
    pm.test('Errors use Problem Details with code and traceId', () => {
        pm.expect(pm.response.headers.get('Content-Type')).to.match(/^application\\/problem\\+json(?:;|$)/i);
        const problem = pm.response.json();
        pm.expect(problem.status).to.equal(pm.response.code);
        for (const key of ['type', 'title', 'instance', 'code', 'traceId']) {
            pm.expect(problem[key], key).to.be.a('string').and.not.empty;
        }
        pm.expect(problem).not.to.have.property('exception');
    });
}`;

function request(name, method, path, { token, body, form, status = 200, tests = '', before = '' } = {})
{
    return {
        name,
        request: {
            method,
            auth: token ? bearer(token) : { type: 'noauth' },
            header: body ? [{ key: 'Content-Type', value: 'application/json' }] : [],
            url: `{{baseUrl}}${path}`,
            ...(body ? { body: { mode: 'raw', raw: typeof body === 'string' ? body : JSON.stringify(body, null, 2) } } : {}),
            ...(form ? { body: { mode: 'formdata', formdata: form } } : {}),
        },
        event: [
            ...(before ? [script('prerequest', before)] : []),
            script('test', `pm.test('HTTP ${status}', () => pm.response.to.have.status(${status}));\n${tests}\n${commonTests}`),
        ],
    };
}

const captureId = key => `
pm.test('201 has a resource Location and UUID', () => {
    const location = pm.response.headers.get('Location');
    pm.expect(location).to.be.a('string').and.not.empty;
    const id = location.split('?')[0].replace(/\\/$/, '').split('/').pop();
    pm.expect(id).to.match(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
    pm.collectionVariables.set('${key}', id);
});`;

function login(who, email, password)
{
    return request(`Login ${who}`, 'POST', '/api/v1/auth/login', {
        body: { email, password },
        tests: `
pm.test('Login supplies a JWT', () => {
    const token = pm.variables.get('tokenProperty').split('.').reduce((value, key) => value?.[key], pm.response.json());
    pm.expect(typeof token === 'string', 'Adjust tokenProperty to the task 10 response contract').to.equal(true);
    pm.expect(/^[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+$/.test(token), 'JWT syntax').to.equal(true);
    pm.collectionVariables.set('${who}Token', token);
});`,
    });
}

export function securityProof()
{
    const preflight = request('Prerequisites - all eleven operations must exist', 'GET', '/openapi/v1.json', {
        tests: `
let prerequisitesReady = false;
let inputsReady = false;
pm.test('Tasks 10, 11, 15, 16 and 19-21 must be integrated', () => {
    const document = pm.response.json();
    const present = Object.entries(document.paths || {}).flatMap(([path, methods]) =>
        Object.keys(methods).map(method => method.toUpperCase() + ' ' + path.replace(/\\{[^}]+\\}/g, '{}')));
    const missing = ${JSON.stringify(requiredOperations)}.filter(operation => !present.includes(operation));
    pm.expect(missing, 'Missing API operations: ' + missing.join(', ')).to.deep.equal([]);
    prerequisitesReady = true;
});
pm.test('Local proof inputs are configured before creating any data', () => {
    for (const key of ['adminEmail', 'adminPassword', 'orderBody', 'statusBody', 'tokenProperty']) {
        pm.expect(pm.variables.get(key), 'Set ' + key + ' in your local environment').to.be.a('string').and.not.empty;
    }
    for (const key of ['orderBody', 'statusBody']) {
        pm.expect(JSON.parse(pm.variables.get(key))).to.be.an('object');
    }
    pm.expect(pm.variables.get('orderBody'), 'Use {{productId}} in orderBody').to.include('{{productId}}');
    inputsReady = true;
});
if (!prerequisitesReady || !inputsReady) pm.execution.setNextRequest(null);`,
        before: `
for (const key of ['AdminToken', 'CustomerAToken', 'CustomerBToken', 'productId', 'orderId', 'categoryId', 'ownerSnapshot']) {
    pm.collectionVariables.unset(key);
}
const run = pm.variables.replaceIn('{{$guid}}');
pm.collectionVariables.set('customerAEmail', 'proof-a-' + run + '@shop.test');
pm.collectionVariables.set('customerBEmail', 'proof-b-' + run + '@shop.test');
pm.collectionVariables.set('customerPassword', 'Proof1!' + run);`,
    });
    const items = [preflight];
    for (const who of ['A', 'B'])
    {
        items.push(request(`Register Customer${who}`, 'POST', '/api/v1/auth/register', {
            body: { email: `{{customer${who}Email}}`, password: '{{customerPassword}}' }, status: 201,
        }));
        items.push(login(`Customer${who}`, `{{customer${who}Email}}`, '{{customerPassword}}'));
    }
    items.push(login('Admin', '{{adminEmail}}', '{{adminPassword}}'));
    items.push(request('Authenticated profile', 'GET', '/api/v1/users/me', { token: 'CustomerAToken' }));
    items.push(request('Anonymous profile rejected', 'GET', '/api/v1/users/me', { status: 401 }));
    items.push(request('Malformed bearer rejected', 'GET', '/api/v1/users/me', { token: 'invalidToken', status: 401 }));
    items.push(request('Anonymous categories', 'GET', '/api/v1/categories', {
        tests: `pm.test('Seeded category exists', () => {
    const categories = pm.response.json();
    pm.expect(categories).to.be.an('array').and.not.empty;
    pm.expect(categories[0].id).to.be.a('string');
    pm.collectionVariables.set('categoryId', categories[0].id);
});`,
    }));
    const form = [
        { key: 'name', value: 'Security proof product', type: 'text' },
        { key: 'description', value: 'Created by the local Newman proof run', type: 'text' },
        { key: 'price', value: '12.50', type: 'text' },
        { key: 'categoryId', value: '{{categoryId}}', type: 'text' },
        { key: 'image', src: 'fixtures/product.png', type: 'file', contentType: 'image/png' },
    ];
    items.push(request('Anonymous product creation rejected', 'POST', '/api/v1/products', { form, status: 401 }));
    items.push(request('Customer product creation rejected', 'POST', '/api/v1/products', { token: 'CustomerAToken', form, status: 403 }));
    items.push(request('Admin creates product', 'POST', '/api/v1/products', { token: 'AdminToken', form, status: 201, tests: captureId('productId') }));
    items.push(request('Anonymous catalog', 'GET', '/api/v1/products?page=1&pageSize=50'));
    items.push(request('Anonymous product detail', 'GET', '/api/v1/products/{{productId}}'));
    const order = { body: '{{resolvedOrderBody}}', before: `pm.variables.set('resolvedOrderBody', pm.variables.replaceIn(pm.variables.get('orderBody')));` };
    items.push(request('Anonymous order creation rejected', 'POST', '/api/v1/orders', { ...order, status: 401 }));
    items.push(request('Admin order creation rejected', 'POST', '/api/v1/orders', { ...order, token: 'AdminToken', status: 403 }));
    items.push(request('CustomerA creates own order', 'POST', '/api/v1/orders', { ...order, token: 'CustomerAToken', status: 201, tests: captureId('orderId') }));
    items.push(request('Owner reads order', 'GET', '/api/v1/orders/{{orderId}}', {
        token: 'CustomerAToken', tests: `pm.collectionVariables.set('ownerSnapshot', JSON.stringify(pm.response.json()));`,
    }));
    items.push(request('Anonymous order read rejected', 'GET', '/api/v1/orders/{{orderId}}', { status: 401 }));
    items.push(request('PROOF 1 - CustomerB cannot read CustomerA order', 'GET', '/api/v1/orders/{{orderId}}', {
        token: 'CustomerBToken', status: 404,
        tests: `pm.test('Non-owner gets the hidden-resource error', () => pm.expect(pm.response.json().code).to.equal('orders.not_found'));`,
    }));
    items.push(request('Admin can read the same existing order', 'GET', '/api/v1/orders/{{orderId}}', { token: 'AdminToken' }));
    for (const who of ['CustomerA', 'CustomerB', 'Admin'])
    {
        items.push(request(`${who} order list`, 'GET', '/api/v1/orders?page=1&pageSize=50', {
            token: `${who}Token`, tests: who === 'CustomerB'
                ? `pm.test('Other customer list does not expose the order', () => pm.expect(pm.response.text()).not.to.include(pm.variables.get('orderId')));`
                : `pm.test('Order appears in allowed list', () => pm.expect(pm.response.text()).to.include(pm.variables.get('orderId')));`,
        }));
    }
    items.push(request('Anonymous status edit rejected', 'PATCH', '/api/v1/orders/{{orderId}}/status', { body: '{{statusBody}}', status: 401 }));
    items.push(request('PROOF 2 - Customer cannot change own order status', 'PATCH', '/api/v1/orders/{{orderId}}/status', {
        token: 'CustomerAToken', body: '{{statusBody}}', status: 403,
    }));
    items.push(request('Rejected customer edit left order unchanged', 'GET', '/api/v1/orders/{{orderId}}', {
        token: 'CustomerAToken', tests: `pm.test('Order is unchanged', () => pm.expect(pm.response.json()).to.deep.equal(JSON.parse(pm.variables.get('ownerSnapshot'))));`,
    }));
    items.push(request('Admin can perform the requested status change', 'PATCH', '/api/v1/orders/{{orderId}}/status', { token: 'AdminToken', body: '{{statusBody}}' }));
    items.push(request('Unsupported API version is rejected', 'POST', '/api/v999/auth/register', {
        status: 404, body: { email: '{{customerAEmail}}', password: '{{customerPassword}}' },
    }));
    return {
        name: 'Security proof',
        description: 'Hand-authored proof scenarios from the Requirement 1 plan. Run the whole folder in order, once, against a disposable database. The first request fails if prerequisite operations or local inputs are missing.',
        item: items,
    };
}
