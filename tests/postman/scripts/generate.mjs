import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import converter from 'openapi-to-postmanv2';
import { operations, requiredOperations, securityProof } from './security-proof.mjs';

export const root = fileURLToPath(new URL('../', import.meta.url));

export async function generate(document)
{
    const spec = structuredClone(document);
    // Use one environment variable for the target, regardless of the exporting host.
    spec.servers = [{ url: 'http://localhost:8080' }];
    const result = await new Promise((accept, reject) => converter.convert({ type: 'json', data: spec }, {
        folderStrategy: 'Tags', requestParametersResolution: 'Schema', exampleParametersResolution: 'Schema',
    }, (error, value) => error ? reject(error) : accept(value)));
    if (!result.result)
    {
        throw new Error(`OpenAPI conversion failed: ${result.reason}`);
    }
    const generated = result.output.find(output => output.type === 'collection')?.data;
    if (!generated)
    {
        throw new Error('Converter returned no collection.');
    }
    function normalizeRequest(request)
    {
        const url = request.url;
        if (typeof url === 'string') throw new Error('Expected a structured converter URL.');
        const query = url.query?.filter(parameter => !parameter.disabled) ?? [];
        url.raw = '{{baseUrl}}/' + (url.path ?? []).join('/') +
            (query.length ? '?' + query.map(parameter => `${parameter.key}=${parameter.value}`).join('&') : '');
        url.host = ['{{baseUrl}}'];
        delete url.protocol;
        delete url.port;
    }
    function normalize(items)
    {
        for (const item of items)
        {
            delete item.id;
            if (item.item) normalize(item.item);
            if (item.request)
            {
                normalizeRequest(item.request);
            }
            for (const example of item.response ?? [])
            {
                delete example.id;
                if (example.originalRequest) normalizeRequest(example.originalRequest);
            }
        }
    }
    normalize(generated.item);
    const present = operations(document).sort();
    const missing = requiredOperations.filter(operation => !present.includes(operation));
    return {
        info: {
            name: 'Shop API - Requirement 1',
            schema: 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
            description: 'The OpenAPI folder is generated from the accompanying snapshot. Security proof is authored from the plan. ' +
                `Snapshot contains ${present.length} operation(s). Missing proof prerequisites: ${missing.join(', ') || 'none'}. ` +
                'Generated requests are examples, not a test suite. Run only Security proof with the supplied runner.',
        },
        ...(generated.auth ? { auth: generated.auth } : {}),
        variable: [
            ...(generated.variable ?? []).filter(variable => variable.key !== 'baseUrl'),
            { key: 'baseUrl', value: 'http://localhost:8080' },
            { key: 'tokenProperty', value: 'accessToken' },
            { key: 'invalidToken', value: 'invalid.jwt.signature' },
        ],
        item: [{ name: 'OpenAPI - generated', item: generated.item }, securityProof()],
        'x-shop-source': { sha256: createHash('sha256').update(JSON.stringify(document)).digest('hex'), operations: present, missingProofPrerequisites: missing },
    };
}

export function httpFile(collection)
{
    const lines = [
        '# Generated from tests/postman/openapi.v1.json. Run npm run generate to refresh.',
        '# Examples only: review bodies before sending. For executable assertions use npm run proof.',
        '@baseUrl = http://localhost:8080', '@bearerToken = REPLACE_LOCALLY', '',
    ];
    function render(items)
    {
        for (const item of items)
        {
            if (item.item) { render(item.item); continue; }
            const request = item.request;
            const url = typeof request.url === 'string' ? request.url : request.url.raw;
            lines.push(`### ${item.name}`, `${request.method} ${url.replace(/:([A-Za-z][A-Za-z0-9_]*)/g, '{{$1}}')}`);
            if ((request.auth ?? collection.auth)?.type === 'bearer') lines.push('Authorization: Bearer {{bearerToken}}');
            for (const header of request.header ?? [])
            {
                if (!header.disabled) lines.push(`${header.key}: ${header.value}`);
            }
            if (request.body?.mode === 'raw') lines.push('', request.body.raw);
            else if (request.body?.mode === 'formdata')
            {
                lines.push('Content-Type: multipart/form-data; boundary=ShopBoundary', '');
                for (const field of request.body.formdata.filter(field => !field.disabled))
                {
                    lines.push('--ShopBoundary');
                    if (field.type === 'file') lines.push(`Content-Disposition: form-data; name="${field.key}"; filename="product.png"`, 'Content-Type: image/png', '', '< ../postman/fixtures/product.png');
                    else lines.push(`Content-Disposition: form-data; name="${field.key}"`, '', field.value ?? '');
                }
                lines.push('--ShopBoundary--');
            }
            else if (request.body && !['raw', 'formdata'].includes(request.body.mode))
            {
                throw new Error(`HTTP rendering does not support ${request.body.mode}; update the renderer before exporting.`);
            }
            lines.push('');
        }
    }
    render(collection.item.find(item => item.name === 'OpenAPI - generated').item);
    return lines.join('\n');
}

export async function main(source = process.argv[2] ?? 'http://localhost:8080/openapi/v1.json')
{
    const content = /^https?:\/\//.test(source)
        ? await (async () => {
            const response = await fetch(source, { signal: AbortSignal.timeout(15000) });
            if (!response.ok) throw new Error(`OpenAPI export returned HTTP ${response.status}.`);
            return response.text();
        })()
        : await readFile(resolve(source), 'utf8');
    const document = JSON.parse(content);
    const collection = await generate(document);
    await writeFile(resolve(root, 'openapi.v1.json'), JSON.stringify(document, null, 2) + '\n');
    await writeFile(resolve(root, 'shop.postman_collection.json'), JSON.stringify(collection, null, 2) + '\n');
    await writeFile(resolve(root, '../http/generated.http'), httpFile(collection));
    console.log(`Generated ${operations(document).length} OpenAPI operation(s).`);
    if (collection['x-shop-source'].missingProofPrerequisites.length)
    {
        console.log('Full proof is blocked by: ' + collection['x-shop-source'].missingProofPrerequisites.join(', '));
    }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href)
{
    main().catch(error => { console.error(error.message); process.exitCode = 1; });
}
