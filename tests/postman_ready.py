"""Publish locally bound Postman scenarios; no user credentials ship in the ZIP."""
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def bound(collection, variables):
    collection = json.loads(json.dumps(collection).replace('pm.environment', 'pm.collectionVariables'))
    collection['variable'] = [{'key': key, 'value': value, 'type': 'string'} for key, value in variables.items()]
    collection.setdefault('event', []).append({'listen': 'prerequest', 'script': {
        'type': 'text/javascript', 'exec': [
            '// Local request variables take precedence over unrelated active environments.',
            'for (const [key, value] of Object.entries(pm.collectionVariables.toObject())) {',
            '  pm.variables.set(key, value);',
            '}',
        ]}})
    return collection


def operation_collection(variables, image):
    items = []
    def add(name, method, path, status=200, token=None, body=None, tests=(), before=()):
        request = {'method': method, 'url': '{{baseUrl}}/api/v1' + path,
                   'header': [{'key': 'Accept', 'value': 'application/json'}]}
        if token:
            request['auth'] = {'type': 'bearer', 'bearer': [{'key': 'token', 'value': '{{' + token + '}}', 'type': 'string'}]}
        if isinstance(body, dict):
            request['body'] = {'mode': 'raw', 'raw': json.dumps(body), 'options': {'raw': {'language': 'json'}}}
            request['header'].append({'key': 'Content-Type', 'value': 'application/json'})
        elif isinstance(body, list):
            request['body'] = {'mode': 'formdata', 'formdata': body}
        events = [{'listen': 'test', 'script': {'type': 'text/javascript', 'exec': [
            f'pm.test("HTTP {status}", () => pm.response.to.have.status({status}));', *tests]}}]
        if before:
            events.insert(0, {'listen': 'prerequest', 'script': {'type': 'text/javascript', 'exec': list(before)}})
        items.append({'name': f'{len(items)+1:02} - {name}', 'request': request, 'event': events})
    def capture(key, field):
        return f'if (pm.response.code < 300) pm.collectionVariables.set("{key}", pm.response.json().{field});'
    def check_stock(quantity):
        return f'pm.test("Available quantity = {quantity}", () => pm.expect(pm.response.json().availableQuantity).to.equal({quantity}));'
    def login(role):
        add(role.title() + ' login', 'POST', '/auth/login', body={
            'email': '{{' + role + 'Email}}', 'password': '{{' + role + 'Password}}'},
            tests=[capture(role + 'Token', 'accessToken')], before=[
                'pm.request.body.update(JSON.stringify({email: pm.collectionVariables.get("' + role + 'Email"), password: pm.collectionVariables.get("' + role + 'Password")}));'])
    login('admin')
    add('Categories', 'GET', '/categories', tests=[
        'pm.collectionVariables.set("categoryId", pm.response.json()[0].id);'])
    add('Create product with image', 'POST', '/products', 201, 'adminToken', body=[
        {'key': 'name', 'value': 'Postman live product {{$timestamp}}', 'type': 'text'},
        {'key': 'description', 'value': 'Interview product with a real PNG image', 'type': 'text'},
        {'key': 'price', 'value': '10.00', 'type': 'text'},
        {'key': 'categoryId', 'value': '{{categoryId}}', 'type': 'text'},
        {'key': 'image', 'type': 'file', 'src': str(image.resolve())},
    ], tests=[capture('managedProductId', 'id')])
    add('Admin adds 10 units', 'POST', '/products/{{managedProductId}}/stock-additions', token='adminToken',
        body={'quantity': 10, 'operationId': '{{stockOperationId}}'}, before=[
            'pm.collectionVariables.set("stockOperationId", pm.variables.replaceIn("{{$guid}}"));',
            'pm.variables.set("stockOperationId", pm.collectionVariables.get("stockOperationId"));'])
    add('Retry same addition - no duplicate', 'POST', '/products/{{managedProductId}}/stock-additions', token='adminToken',
        body={'quantity': 10, 'operationId': '{{stockOperationId}}'})
    add('Product has 10 units', 'GET', '/products/{{managedProductId}}', tests=[check_stock(10)])
    add('Filter category and paginate', 'GET', '/products?category={{categoryId}}&page=1&pageSize=5')
    login('owner')
    add('Customer profile', 'GET', '/users/me', token='ownerToken')
    add('Customer cannot add inventory', 'POST', '/products/{{managedProductId}}/stock-additions', 403, 'ownerToken',
        {'quantity': 1, 'operationId': '{{$guid}}'})
    add('Create Pending order for 2 units', 'POST', '/orders', 201, 'ownerToken',
        {'lines': [{'productId': '{{managedProductId}}', 'quantity': 2}]}, tests=[capture('managedOrderId', 'id')])
    add('Pending already reserves - 8 available', 'GET', '/products/{{managedProductId}}', tests=[check_stock(8)])
    add('Owner reads order', 'GET', '/orders/{{managedOrderId}}', token='ownerToken')
    add('Owner lists own orders', 'GET', '/orders', token='ownerToken')
    add('Customer cannot change status', 'PATCH', '/orders/{{managedOrderId}}/status', 403, 'ownerToken', {'status': 'Confirmed'})
    login('visitor')
    add('Other customer cannot read order', 'GET', '/orders/{{managedOrderId}}', 404, 'visitorToken')
    add('Reject shortage of 99 units', 'POST', '/orders', 409, 'ownerToken',
        {'lines': [{'productId': '{{managedProductId}}', 'quantity': 99}]})
    add('Stock unchanged after rejection', 'GET', '/products/{{managedProductId}}', tests=[check_stock(8)])
    add('Admin confirms order', 'PATCH', '/orders/{{managedOrderId}}/status', token='adminToken', body={'status': 'Confirmed'})
    add('Admin cancels order', 'PATCH', '/orders/{{managedOrderId}}/status', token='adminToken', body={'status': 'Cancelled'})
    add('Cancel returns 2 units', 'GET', '/products/{{managedProductId}}', tests=[check_stock(10)])
    add('Owner sees notification', 'GET', '/notifications', token='ownerToken', tests=[
        'pm.test("Cancellation notification exists", () => pm.expect(pm.response.json().items.some(x => x.orderId === pm.collectionVariables.get("managedOrderId") && x.status === "Cancelled")).to.equal(true));'])
    return bound({'info': {'name': 'Shop Ready - Operations', 'schema': 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
                         'description': 'Run all requests in order. Contains local demo credentials. Keep private. Choose the included PNG if Postman asks for file access.'},
                  'item': items}, variables)


def publish_ready(demo, variables, admin_email, admin_password, grpc_port):
    target = ROOT / 'Postman-Ready'
    target.mkdir(exist_ok=True, mode=0o700)
    rest = json.loads((ROOT / 'tests/postman/shop-interview.postman_collection.json').read_text())
    rest['info']['name'] = 'Shop Ready - REST ' + demo.name
    rest['info']['description'] = 'Ready local scenarios; no environment selection needed. Contains disposable account credentials. Keep private.'
    rest = bound(rest, variables)
    (target / 'shop-rest-ready.postman_collection.json').write_text(json.dumps(rest, indent=2) + '\n', encoding='utf-8')
    image = target / 'demo-product.png'
    shutil.copyfile(ROOT / 'tests/fixtures/demo-product.png', image)
    operations = operation_collection({**variables, 'adminEmail': admin_email, 'adminPassword': admin_password,
                                      'adminToken': '', 'categoryId': '', 'managedProductId': '', 'managedOrderId': '', 'stockOperationId': ''}, image)
    (target / 'shop-operations-ready.postman_collection.json').write_text(json.dumps(operations, indent=2) + '\n', encoding='utf-8')
    shutil.copyfile(demo / 'shop-interview.postman_environment.json', target / 'shop-interview.postman_environment.json')
    shutil.copyfile(demo / 'scenario.json', target / 'scenario.json')
    shutil.copyfile(ROOT / 'contracts/inventory/v1/inventory.proto', target / 'inventory.proto')
    for folder in ('grpc-rehearsal', 'grpc'):
        shutil.copytree(demo / folder, target / folder, dirs_exist_ok=True)
    (target / 'README.txt').write_text(
        'LOCAL INTERVIEW FILES - keep private; collections contain local credentials.\n'
        f'Store: {variables["baseUrl"]}\nSwagger: {variables["baseUrl"]}/docs\ngRPC: 127.0.0.1:{grpc_port}\n'
        f'Scenario: .demo/{demo.name}\n\n'
        '1. Import shop-rest-ready.postman_collection.json. No environment needed. Run all 8 requests: 13 checks.\n'
        '2. Wait 60 seconds between collection runs (login protection remains enabled).\n'
        '3. Import shop-operations-ready.postman_collection.json. Run all 23 requests.\n'
        '   If asked, allow access to demo-product.png or select it in request 03 > Body > image.\n'
        '4. New > gRPC. Import inventory.proto. TLS off. Select GetStock / Reserve / Release.\n'
        '   Paste the matching JSON from grpc-rehearsal for practice, or grpc for the interview.\n'
        '5. Run Test-Race.ps1 for a real barrier-synchronized 20-customer last-unit test.\n'
        'See docs/INTERVIEW_GUIDE_AR.md for the full Arabic walkthrough.\n', encoding='utf-8')
    for path in target.rglob('*'):
        if path.is_file():
            path.chmod(0o600)
    return target
