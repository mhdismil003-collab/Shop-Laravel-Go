import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import newman from 'newman';
import { root } from './generate.mjs';

try
{
    const collection = JSON.parse(await readFile(resolve(root, 'shop.postman_collection.json'), 'utf8'));
    const environment = process.argv[2] ? JSON.parse(await readFile(resolve(process.argv[2]), 'utf8')) : undefined;
    const target = new URL(process.env.SHOP_BASE_URL ?? environment?.values?.find(value => value.key === 'baseUrl' && value.enabled !== false)?.value ?? 'http://localhost:8080');
    if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password || target.search || target.hash || target.pathname !== '/')
    {
        throw new Error('baseUrl must be an HTTP(S) origin without credentials, query or path.');
    }
    if (process.env.SHOP_PROOF_ALLOW_WRITES !== '1')
    {
        throw new Error('This proof creates users, an image, a product and an order, then changes order status. Use a disposable database and set SHOP_PROOF_ALLOW_WRITES=1.');
    }
    const seedCompose = process.env.SHOP_PROOF_SEED_COMPOSE === '1';
    if (seedCompose && !['localhost', '127.0.0.1', '[::1]'].includes(target.hostname))
    {
        throw new Error('Compose stock seeding requires a local baseUrl.');
    }
    let stockSeedFailed = false;
    // No JSON reporter: Newman reports can contain bearer tokens and request passwords.
    newman.run({
        collection, environment, folder: 'Security proof',
        envVar: [{ key: 'baseUrl', value: target.origin }],
        workingDir: root, insecureFileRead: false,
        iterationCount: 1, bail: ['failure', 'folder'],
        timeout: 120000, timeoutRequest: 10000, timeoutScript: 3000,
        reporters: ['cli'], reporter: { cli: { noConsole: true } },
    }, (error, summary) => {
        if (error)
        {
            console.error(error.message);
            process.exitCode = 1;
            return;
        }
        const expected = collection.item.find(item => item.name === 'Security proof').item.length;
        const requests = summary.run.stats.requests;
        const failures = summary.run.failures.length;
        if (stockSeedFailed || failures || requests.failed || requests.total !== expected)
        {
            console.error(`Proof incomplete/failed: ${requests.total}/${expected} requests, ${failures} failure(s).`);
            process.exitCode = 1;
        }
    }).on('request', (error, args) => {
        if (!seedCompose || error || args.item.name !== 'Admin creates product' || args.response.code !== 201)
        {
            return;
        }
        const productId = args.response.headers.get('Location')?.split('/').at(-1);
        if (!productId || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(productId))
        {
            stockSeedFailed = true;
            console.error('Cannot seed stock: product Location is missing its UUID.');
            return;
        }
        const seed = spawnSync('docker', ['compose', 'exec', '-T', 'warehouse', '/usr/local/bin/warehouse',
            'stock-add', productId, '1', randomUUID()],
        { cwd: resolve(root, '../..'), stdio: 'inherit', timeout: 15000 });
        if (seed.status !== 0)
        {
            stockSeedFailed = true;
            console.error('Failed to seed the disposable warehouse.');
        }
    });
}
catch (error)
{
    console.error(error.message);
    process.exitCode = 1;
}
