import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import test from 'node:test';
import newman from 'newman';
import { generate, httpFile, root } from '../scripts/generate.mjs';

const productId = '019a0000-0000-7000-8000-000000000001';
const orderId = '019a0000-0000-7000-8000-000000000002';
const categoryId = '019a0000-0000-7000-8000-000000000003';
const routes = [
    ['post', '/api/v1/auth/register'], ['post', '/api/v1/auth/login'], ['get', '/api/v1/users/me'],
    ['get', '/api/v1/categories'], ['get', '/api/v1/products'], ['post', '/api/v1/products'],
    ['get', '/api/v1/products/{id}'], ['post', '/api/v1/orders'], ['get', '/api/v1/orders'],
    ['get', '/api/v1/orders/{id}'], ['patch', '/api/v1/orders/{id}/status'],
];
function spec(complete = true)
{
    const paths = {};
    for (const [method, path] of complete ? routes : routes.slice(0, 1))
    {
        (paths[path] ??= {})[method] = { responses: { 200: { description: 'Harness response' } } };
        if (path.includes('{id}')) paths[path][method].parameters = [{ name: 'id', in: 'path', required: true, schema: { type: 'string', format: 'uuid' } }];
    }
    return { openapi: '3.0.3', info: { title: 'Test-only protocol harness, not the Shop API', version: 'v1' }, paths };
}

async function harness(options = {})
{
    const observed = { requests: [], writes: 0, uploaded: false };
    let status = 'Pending';
    const server = createServer(async (request, response) => {
        const chunks = [];
        for await (const chunk of request) chunks.push(chunk);
        const body = Buffer.concat(chunks);
        const path = request.url.split('?')[0];
        const role = /^Bearer (CustomerA|CustomerB|Admin)\./.exec(request.headers.authorization ?? '')?.[1];
        observed.requests.push(`${request.method} ${path}`);
        response.setHeader('X-Content-Type-Options', 'nosniff');
        response.setHeader('X-Frame-Options', 'DENY');
        response.setHeader('Referrer-Policy', 'no-referrer');
        if (request.headers.authorization) response.setHeader('Cache-Control', 'no-store');
        function send(code, value)
        {
            response.statusCode = code;
            response.setHeader('Content-Type', code >= 400 ? 'application/problem+json' : 'application/json');
            response.end(JSON.stringify(code >= 400 ? {
                type: 'https://shop.test/errors/rejected', title: 'Rejected', status: code, instance: path,
                code: path.includes('/orders/') && code === 404 ? 'orders.not_found' : 'common.rejected', traceId: 'harness-trace',
            } : value));
        }
        if (path === '/openapi/v1.json') return send(200, spec(options.complete !== false));
        if (path.startsWith('/api/v999/')) return send(404);
        if (path === '/api/v1/auth/register') { observed.writes++; return send(201, {}); }
        if (path === '/api/v1/auth/login')
        {
            const email = JSON.parse(body).email;
            const who = email.startsWith('proof-a-') ? 'CustomerA' : email.startsWith('proof-b-') ? 'CustomerB' : 'Admin';
            return send(200, { accessToken: `${who}.${who}.signature` });
        }
        if (path === '/api/v1/categories') return send(200, [{ id: categoryId }]);
        if (path === '/api/v1/products' && request.method === 'POST')
        {
            if (!role) return send(401);
            if (role !== 'Admin') return send(403);
            assert.match(request.headers['content-type'], /^multipart\/form-data; boundary=/);
            observed.uploaded = body.includes(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
            observed.writes++;
            response.setHeader('Location', `/api/v1/products/${productId}`);
            return send(201, { id: productId });
        }
        if (path.startsWith('/api/v1/products')) return send(200, {});
        if (!role) return send(401);
        if (path === '/api/v1/users/me') return send(200, { id: role });
        if (path === '/api/v1/orders' && request.method === 'POST')
        {
            if (role === 'Admin') return send(403);
            assert.deepEqual(JSON.parse(body), { lines: [{ productId, quantity: 1 }] });
            observed.writes++;
            response.setHeader('Location', `/api/v1/orders/${orderId}`);
            return send(201, { id: orderId });
        }
        if (path === '/api/v1/orders') return send(200, { items: role === 'CustomerB' ? [] : [{ id: orderId, status }] });
        if (path.endsWith('/status'))
        {
            if (role !== 'Admin' && !options.allowCustomerEdit) return send(403);
            observed.writes++;
            status = 'Confirmed';
            return send(200, { id: orderId, status });
        }
        if (role === 'CustomerB' && !options.allowOtherCustomerRead) return send(404);
        return send(200, { id: orderId, status });
    });
    await new Promise(accept => server.listen(0, '127.0.0.1', accept));
    return { observed, url: `http://127.0.0.1:${server.address().port}`, close: () => new Promise(accept => server.close(accept)) };
}

async function run(options = {})
{
    const app = await harness(options);
    try
    {
        const collection = await generate(spec());
        const values = {
            baseUrl: app.url, adminEmail: 'admin@shop.test', adminPassword: 'HarnessOnly123!',
            orderBody: JSON.stringify({ lines: [{ productId: '{{productId}}', quantity: 1 }] }),
            statusBody: JSON.stringify({ status: 'Confirmed' }),
        };
        if (options.missingInputs) delete values.orderBody;
        const summary = await new Promise((accept, reject) => newman.run({
            collection, folder: 'Security proof', envVar: Object.entries(values).map(([key, value]) => ({ key, value })),
            workingDir: root, insecureFileRead: false, bail: ['failure', 'folder'],
            timeout: 30000, timeoutRequest: 2000, timeoutScript: 2000, reporters: [],
        }, (error, result) => result ? accept(result) : reject(error)));
        return { summary, observed: app.observed, expected: collection.item[1].item.length };
    }
    finally { await app.close(); }
}

test('Actual checked-in OpenAPI converts without inventing future endpoints; HTTP requests match it', async () => {
    const document = JSON.parse(await readFile(resolve(root, 'openapi.v1.json'), 'utf8'));
    const collection = await generate(document);
    function flatten(items) { return items.flatMap(item => item.item ? flatten(item.item) : [item]); }
    const generated = flatten(collection.item[0].item);
    const expected = Object.values(document.paths).reduce((count, methods) => count + Object.keys(methods).filter(method => /^(get|post|put|patch|delete|head|options|trace)$/.test(method)).length, 0);
    assert.equal(generated.length, expected);
    for (const item of generated) assert.ok(item.request.url.raw.startsWith('{{baseUrl}}/'));
    assert.equal(httpFile(collection).split('\n').filter(line => /^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE) /.test(line)).length, expected);
    const checkedIn = JSON.parse(await readFile(resolve(root, 'shop.postman_collection.json'), 'utf8'));
    assert.deepEqual(collection.item[1], checkedIn.item[1]);
    assert.deepEqual(collection['x-shop-source'], checkedIn['x-shop-source']);
    assert.equal(httpFile(collection), await readFile(resolve(root, '../http/generated.http'), 'utf8'));
    assert.deepEqual(document, JSON.parse(await readFile(resolve(root, 'openapi.v1.json'), 'utf8')));
});

test('Newman runs the complete proof, uploads the fixture, and resolves captured IDs (protocol harness only)', async () => {
    const { summary, observed, expected } = await run();
    assert.deepEqual(summary.run.failures.map(failure => ({ name: failure.error.name, message: failure.error.message, at: failure.source?.name })), []);
    assert.equal(summary.run.stats.requests.total, expected);
    assert.equal(observed.uploaded, true);
    assert.equal(observed.writes, 5); // Two accounts, product, order and admin status change.
});

test('Absent endpoint prerequisites stop Newman before any writes', async () => {
    const { summary, observed } = await run({ complete: false });
    assert.ok(summary.run.failures.some(failure => failure.error.message.includes('Missing API operations')));
    assert.equal(observed.requests.length, 1);
    assert.equal(observed.writes, 0);
});

test('Missing local order contract stops Newman before any writes', async () => {
    const { summary, observed } = await run({ missingInputs: true });
    assert.ok(summary.run.failures.some(failure => failure.error.message.includes('Set orderBody')));
    assert.equal(observed.requests.length, 1);
    assert.equal(observed.writes, 0);
});

test('Proof fails if another customer can read the existing order', async () => {
    const { summary } = await run({ allowOtherCustomerRead: true });
    assert.ok(summary.run.failures.some(failure => failure.source?.name.startsWith('PROOF 1')));
});

test('Proof fails if a customer can change an order status', async () => {
    const { summary } = await run({ allowCustomerEdit: true });
    assert.ok(summary.run.failures.some(failure => failure.source?.name.startsWith('PROOF 2')));
});
