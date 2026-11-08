#!/usr/bin/env python3
"""Disposable Laravel acceptance run. Creates its own users/products and stock.
Default: Docker Compose. Optional SHOP_DEMO_PSQL_JSON supplies an argv prefix
for local psql (database name is appended). SHOP_WAREHOUSE_<ACTION>_JSON
overrides each Compose command (stop, start, pause or unpause).
"""
import base64
import concurrent.futures
import json
import os
import subprocess
import time
from threading import Barrier
import urllib.error
import urllib.request
import uuid
from collections import Counter

BASE = os.environ.get("SHOP_BASE_URL", "http://localhost:8080").rstrip("/")

def http(method, path, body=None, token=None, content_type="application/json"):
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    headers = {"Content-Type": content_type}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + "/api/v1" + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())

def sql(statement):
    database = os.environ.get("POSTGRES_DB", "shop_laravel")
    override = os.environ.get("SHOP_DEMO_PSQL_JSON")
    if override:
        command = json.loads(override) + ["-d", database]
    else:
        user = os.environ.get("POSTGRES_USER", "shop")
        command = ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", user, "-d", database]
    return subprocess.check_output(command + ["-v", "ON_ERROR_STOP=1", "-Atc", statement], text=True).strip()

def control(action):
    env = "SHOP_WAREHOUSE_" + action.upper() + "_JSON"
    subprocess.run(json.loads(os.environ[env]) if env in os.environ else ["docker", "compose", action, "warehouse"], check=True)

def check(condition, detail):
    if not condition:
        raise AssertionError(detail)
    print("PASS:", detail, flush=True)

for attempt in range(60):
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=2) as response:
            if response.status == 200:
                break
    except (urllib.error.URLError, TimeoutError):
        time.sleep(0.5)
else:
    raise RuntimeError("API did not become healthy within 30 seconds")

status, auth = http("POST", "/auth/login", {"email": os.environ.get("ADMIN_EMAIL", "admin@shop.local"), "password": os.environ.get("ADMIN_PASSWORD", "Admin123!")})
check(status == 200, "admin login" if status == 200 else
      f"admin login failed (HTTP {status}): {auth.get('userMessage', 'Check the actual database password or login rate limit.')}")
admin = auth["accessToken"]
email = f"req2-{uuid.uuid4().hex}@shop.test"
status, registered = http("POST", "/auth/register", {"email": email, "password": "DemoCustomer123!"})
check(status == 201, "customer registration")
customer_id = str(uuid.UUID(registered["id"]))
status, auth = http("POST", "/auth/login", {"email": email, "password": "DemoCustomer123!"})
check(status == 200, "customer login")
customer = auth["accessToken"]
status, categories = http("GET", "/categories")
check(status == 200 and categories, "catalog categories")
with urllib.request.urlopen(BASE + "/", timeout=5) as response:
    check(response.status == 200 and b'/shop.js' in response.read(), "storefront loads from the same application")
boundary = "req2" + uuid.uuid4().hex
parts = []
for key, value in {"name": "Requirement 2 demo", "description": "Disposable integration test", "price": "10.00", "categoryId": categories[0]["id"]}.items():
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aFacAAAAASUVORK5CYII=")
parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="demo.png"\r\nContent-Type: image/png\r\n\r\n'.encode() + image + b"\r\n", f"--{boundary}--\r\n".encode()]
status, product = http("POST", "/products", b"".join(parts), admin, "multipart/form-data; boundary=" + boundary)
check(status == 201, f"admin product creation ({status})")
status, problem = http("POST", "/products", {"name": "wrong media type"}, admin)
check(status == 415 and problem["code"] == "common.unsupported_media_type", "non-multipart product request returns 415")
oversized = b"".join(parts).replace(image, image + b"0" * (3 * 1024 * 1024))
status, problem = http("POST", "/products", oversized, admin, "multipart/form-data; boundary=" + boundary)
check(status == 413 and problem["code"] == "products.image_too_large" and "2 ميغابايت" in problem["userMessage"], "oversized multipart image returns 413")
invalid_image = b"".join(parts).replace(image, b"not an image")
status, problem = http("POST", "/products", invalid_image, admin, "multipart/form-data; boundary=" + boundary)
check(status == 415 and problem["code"] == "products.unsupported_image_type", "declared PNG with invalid content returns 415")
pid = str(uuid.UUID(product["id"]))
stock_command = os.environ.get("SHOP_WAREHOUSE_STOCK_JSON")
stock_argv = json.loads(stock_command) if stock_command else ["docker", "compose", "exec", "-T", "warehouse", "/usr/local/bin/warehouse"]
adjustment_id = str(uuid.uuid4())
for _ in range(2):
    subprocess.run(stock_argv + ["stock-add", pid, "1", adjustment_id], check=True)
check(http("GET", "/products/" + pid)[1]["availableQuantity"] == 1, "live gRPC availability")
with urllib.request.urlopen(BASE + product["imageUrl"], timeout=5) as response:
    check(response.status == 200 and response.headers.get_content_type() == "image/png"
          and response.read(8) == b"\x89PNG\r\n\x1a\n", "uploaded image is served as PNG")
status, other_product = http("POST", "/products", b"".join(parts), admin, "multipart/form-data; boundary=" + boundary)
check(status == 201, "second catalog product created without stock")
other_pid = str(uuid.UUID(other_product["id"]))
status, page = http("GET", f"/products?category={categories[0]['id']}&page=1&pageSize=1")
check(status == 200 and len(page["items"]) == 1 and page["totalCount"] >= 2
      and page["items"][0]["categoryId"] == categories[0]["id"], "catalog category filtering and pagination")
status, shortage = http("POST", "/orders", {"lines": [{"productId": pid, "quantity": 1},
                                                      {"productId": other_pid, "quantity": 1}]}, customer)
check(status == 409 and shortage["code"] == "orders.insufficient_stock"
      and "لم يُنشأ الطلب" in shortage["userMessage"]
      and shortage["shortages"] == [{"productId": other_pid, "requested": 1, "available": 0}],
      "multi-product shortage is reported")
check(http("GET", "/products/" + pid)[1]["availableQuantity"] == 1,
      "rejected multi-product order leaves the other product unchanged")

stock_path = "/products/" + other_pid + "/stock-additions"
stock_change = {"quantity": 3, "operationId": str(uuid.uuid4())}
check(http("POST", stock_path, stock_change)[0] == 401, "anonymous user cannot add stock")
check(http("POST", stock_path, stock_change, customer)[0] == 403, "customer cannot add stock")
check(http("POST", stock_path, {**stock_change, "quantity": 0}, admin)[0] == 422, "stock addition rejects zero")
check(http("POST", stock_path, stock_change, admin)[0] == 200, "administrator adds stock through gRPC")
check(http("POST", stock_path, stock_change, admin)[0] == 200, "stock retry succeeds with the same ID")
check(http("POST", stock_path, {**stock_change, "quantity": 4}, admin)[0] == 409,
      "stock retry rejects changed quantity")
check(http("GET", "/products/" + other_pid)[1]["availableQuantity"] == 3, "stock retry did not duplicate the balance")

def place(_=0):
    return http("POST", "/orders", {"lines": [{"productId": pid, "quantity": 1}]}, customer)

# Pause the live warehouse with its TCP socket still open. Unlike stop, this tests a deadline.
control("pause")
try:
    for action in (lambda: http("GET", "/products/" + pid), place):
        start = time.monotonic()
        status, problem = action()
        duration = time.monotonic() - start
        check(status == 503 and problem["detail"] == "Inventory warehouse did not respond in time."
              and "تأخر رد المستودع" in problem["userMessage"] and 1.5 <= duration < 5, f"silent warehouse returns 503 after {duration:.2f} seconds")
finally:
    control("unpause")
check(http("GET", "/products/" + pid)[1]["availableQuantity"] == 1, "timed-out order did not consume stock")

start_race = Barrier(20)

def race(_):
    start_race.wait(timeout=10)
    return place()

with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
    responses = list(pool.map(race, range(20)))
counts = Counter(status for status, _ in responses)
check(counts == {201: 1, 409: 19}, f"last unit: {dict(counts)}")
check(http("GET", "/products/" + pid)[1]["availableQuantity"] == 0, "stock never negative")
order_id = next(body["id"] for status, body in responses if status == 201)
check(sql(f"SELECT count(*) FROM orders WHERE id='{uuid.UUID(order_id)}'") == "1", "winner saved")
check(http("GET", f"/orders/{order_id}", token=customer)[0] == 200, "owner can read order")
status, notifications = http("GET", "/notifications", token=customer)
check(status == 200 and any(item["orderId"] == order_id and item["status"] == "Pending"
                            for item in notifications["items"]), "owner receives order creation notification")
other_email = f"req1-{uuid.uuid4().hex}@shop.test"
check(http("POST", "/auth/register", {"email": other_email, "password": "DemoCustomer123!"})[0] == 201, "second customer registration")
status, auth = http("POST", "/auth/login", {"email": other_email, "password": "DemoCustomer123!"})
check(status == 200, "second customer login")
check(http("GET", f"/orders/{order_id}", token=auth["accessToken"])[0] == 404, "customer cannot read another customer's order")
status, notifications = http("GET", "/notifications", token=auth["accessToken"])
check(status == 200 and notifications["items"] == [], "another customer cannot see the owner's notifications")
check(http("PATCH", f"/orders/{order_id}/status", {"status": "Cancelled"}, customer)[0] == 403, "customer cannot change order status")
check(http("PATCH", f"/orders/{order_id}/status", {"status": "Cancelled"}, admin)[0] == 200, "order cancellation")
check(http("GET", "/products/" + pid)[1]["availableQuantity"] == 1, "cancellation releases stock")
status, notifications = http("GET", "/notifications", token=customer)
check(status == 200 and notifications["items"][0]["status"] == "Cancelled", "status update creates a notification")

# Force the Orders save to fail AFTER Reserve, without changing application code.
sql(f"""CREATE FUNCTION req2_fail_save() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN IF NEW.customer_id='{customer_id}' THEN
RAISE EXCEPTION 'requirement2 forced order save failure'; END IF; RETURN NEW; END $$;
CREATE TRIGGER req2_fail_save BEFORE INSERT ON orders FOR EACH ROW EXECUTE FUNCTION req2_fail_save();""")
try:
    status, problem = place()
    check(status == 500 and "traceId" in problem, "forced order persistence failure returns a unified error")
    check(sql(f"SELECT count(*) FROM orders WHERE customer_id='{customer_id}'") == "1",
          "failed persistence leaves no new order")
    check(http("GET", "/products/" + pid)[1]["availableQuantity"] == 1, "failed save compensates reservation")
finally:
    sql("DROP TRIGGER req2_fail_save ON orders; DROP FUNCTION req2_fail_save();")

status, retry_order = place()
check(status == 201, "order prepared for cancellation during outage")
retry_id = str(uuid.UUID(retry_order["id"]))
control("stop")
try:
    start = time.monotonic()
    status, problem = http("GET", "/products/" + pid)
    check(status == 503 and "code" in problem and "traceId" in problem and time.monotonic()-start < 6, "warehouse outage returns bounded 503 Problem Details")
    check(place()[0] == 503, "order blocked when warehouse is down")
    check(http("PATCH", f"/orders/{retry_id}/status", {"status": "Cancelled"}, admin)[0] == 200, "cancellation commits during outage")
    check(sql(f"SELECT count(*) FROM inventory_recovery WHERE order_id='{retry_id}'") == "1", "failed release persisted for durable retry")
finally:
    control("start")
for _ in range(60):
    status, recovered = http("GET", "/products/" + pid)
    if status == 200 and recovered["availableQuantity"] == 1:
        break
    time.sleep(1)
check(http("GET", "/products/" + pid)[1]["availableQuantity"] == 1, "background recovery releases cancelled stock after outage")
status, malformed = http("POST", "/auth/register", b'{"email":')
check(status == 400 and malformed["code"] == "common.bad_request", "malformed JSON returns 400 Problem Details")
status, rejected = http("GET", "/users/me", token="bad.jwt.signature")
check(status == 401 and rejected["code"] == "common.unauthorized", "malformed JWT rejected")
bad_header = base64.urlsafe_b64encode(b'{"alg":["HS256"]}').decode().rstrip("=")
status, rejected = http("GET", "/users/me", token=bad_header + ".e30.bad")
check(status == 401 and rejected["code"] == "common.unauthorized", "JWT with a non-string algorithm returns 401")
status, rejected = http("POST", "/auth/login", {"email": "bad\0address@example.test", "password": "DemoCustomer123!"})
check(status == 401 and rejected["code"] == "users.invalid_credentials", "invalid email bytes do not cause a database error")
if os.environ.get("SHOP_TEST_LOGIN_PROTECTION") == "1":
    lock_email = f"lock-{uuid.uuid4().hex}@shop.test"
    check(http("POST", "/auth/register", {"email": lock_email, "password": "DemoCustomer123!"})[0] == 201, "lockout test account created")
    for _ in range(5):
        assert http("POST", "/auth/login", {"email": lock_email, "password": "Incorrect123!"})[0] == 401
    check(http("POST", "/auth/login", {"email": lock_email, "password": "DemoCustomer123!"})[0] == 401,
          "correct credentials rejected after five failures")
    for _ in range(35):
        status, limited = http("POST", "/auth/login", {"email": lock_email, "password": "Incorrect123!"})
        if status == 429:
            break
    check(status == 429 and limited["code"] == "common.too_many_requests" and "حاول مجددًا" in limited["userMessage"], "login rate limiting returns 429")
print("All Laravel acceptance checks passed.")
