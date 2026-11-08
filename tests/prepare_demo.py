#!/usr/bin/env python3
"""Prepare disposable interview data on an already running local Shop stack."""

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.postman.yaml"]


class DemoHttpError(RuntimeError):
    def __init__(self, method, path, status):
        self.status = status
        super().__init__(f"{method} {path}: HTTP {status}")


def request(base, method, path, status=200, body=None, token=None, mime="application/json"):
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    headers = {"Accept": "application/json", "Content-Type": mime}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(base + path, data=body, method=method, headers=headers)
    for attempt in range(6):
        try:
            with urlopen(req, timeout=8) as response:
                if response.status != status:
                    raise RuntimeError(f"{method} {path}: expected {status}, got {response.status}")
                return response.read()
        except HTTPError as error:
            if error.code == status:
                return error.read()
            if error.code == 429 and path.endswith("/auth/login") and attempt < 5:
                delay = min(60, max(1, int(error.headers.get("Retry-After", "60"))))
                print(f"Login protection: waiting {delay}s before retrying.", flush=True)
                time.sleep(delay)
                continue
            raise DemoHttpError(method, path, error.code) from error


def prepare(base, grpc_port, admin_email, admin_password, warehouse):
    request(base, "GET", "/health")
    spec = json.loads(request(base, "GET", "/openapi/v1.json"))
    if "/api/v1/orders" not in spec["paths"]:
        raise RuntimeError("Shop OpenAPI is missing the orders endpoint")
    with socket.create_connection(("127.0.0.1", grpc_port), timeout=3):
        pass
    subprocess.run([*warehouse, "healthcheck"], cwd=ROOT, check=True, timeout=8)

    def api(method, path, status=200, body=None, token=None, mime="application/json"):
        return json.loads(request(base, method, "/api/v1" + path, status, body, token, mime))

    def seed(product_id, quantity):
        subprocess.run([*warehouse, "stock-add", product_id, str(quantity), str(uuid4())],
                       cwd=ROOT, check=True, timeout=30)

    # Validate the existing administrator before creating any disposable accounts.
    admin = api("POST", "/auth/login", body={"email": admin_email, "password": admin_password})["accessToken"]
    suffix = uuid4().hex[:8]
    password = "Demo1!" + secrets.token_urlsafe(12)
    accounts = {}
    for role in ("owner", "visitor"):
        accounts[role] = {"email": f"{role}-{suffix}@shop.test", "password": password}
        api("POST", "/auth/register", 201, accounts[role])
    owner = api("POST", "/auth/login", body=accounts["owner"])["accessToken"]
    visitor = api("POST", "/auth/login", body=accounts["visitor"])["accessToken"]

    category = api("GET", "/categories")[0]
    boundary = uuid4().hex
    name = f"حقيبة رِف للعرض {suffix}"
    fields = {"name": name, "description": "حقيبة يومية خفيفة مخصصة لتجربة المتجر.",
              "price": "29.00", "categoryId": category["id"]}
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
             for key, value in fields.items()]
    image = (ROOT / "tests/fixtures/demo-product.png").read_bytes()
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="demo.png"\r\n'
                 f'Content-Type: image/png\r\n\r\n'.encode() + image + f"\r\n--{boundary}--\r\n".encode())
    product = api("POST", "/products", 201, b"".join(parts), admin, f"multipart/form-data; boundary={boundary}")
    product_id = product["id"]
    seed(product_id, 4)
    order = api("POST", "/orders", 201, {"lines": [{"productId": product_id, "quantity": 1}]}, owner)
    order_path = "/orders/" + order["id"]
    api("GET", order_path, token=owner)
    api("GET", order_path, 404, token=visitor)
    api("PATCH", order_path + "/status", 403, {"status": "Confirmed"}, owner)
    if api("GET", "/products/" + product_id)["availableQuantity"] != 3:
        raise RuntimeError("Unexpected stock after preparing the order")
    if not any(item["orderId"] == order["id"] and item["status"] == "Pending"
               for item in api("GET", "/notifications", token=owner)["items"]):
        raise RuntimeError("The owner's order notification is missing")

    demo = ROOT / ".demo" / suffix
    demo.mkdir(parents=True, mode=0o700)
    for folder in ("grpc-rehearsal", "grpc"):
        grpc = demo / folder
        grpc.mkdir(mode=0o700)
        grpc_product = str(uuid4())
        grpc_order = str(uuid4())
        seed(grpc_product, 3)
        # Use the .proto field names for Postman's imported gRPC definition.
        values = {
            "GetStock": {"product_id": grpc_product},
            "Reserve": {"order_id": grpc_order, "items": [{"product_id": grpc_product, "quantity": 1}]},
            "Release": {"order_id": grpc_order},
            "Insufficient": {"order_id": str(uuid4()), "items": [{"product_id": grpc_product, "quantity": 99}]},
            "AtomicShortage": {"order_id": str(uuid4()), "items": [
                {"product_id": grpc_product, "quantity": 1},
                {"product_id": str(uuid4()), "quantity": 1},
            ]},
        }
        for method, payload in values.items():
            (grpc / f"{method}.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    handoff = {"store": base, "swagger": base + "/docs", "grpcServer": f"127.0.0.1:{grpc_port}",
               "adminEmail": admin_email, "productName": name, "productId": product_id, "orderId": order["id"],
               "productApi": base + "/api/v1/products/" + product_id, "orderApi": base + "/api/v1" + order_path,
               **accounts}
    with (demo / "scenario.json").open("x", encoding="utf-8") as output:
        output.write(json.dumps(handoff, ensure_ascii=False, indent=2) + "\n")
    variables = {
        "baseUrl": base, "productId": product_id, "orderId": order["id"], "expectedStock": "3",
        "ownerEmail": accounts["owner"]["email"], "ownerPassword": accounts["owner"]["password"],
        "visitorEmail": accounts["visitor"]["email"], "visitorPassword": accounts["visitor"]["password"],
        "ownerToken": "", "visitorToken": "",
    }
    environment = {
        "id": str(uuid4()), "name": f"Shop Interview {suffix}", "_postman_variable_scope": "environment",
        "values": [{"key": key, "value": value, "enabled": True,
                    "type": "secret" if key.endswith(("Password", "Token")) else "default"}
                   for key, value in variables.items()],
    }
    (demo / "shop-interview.postman_environment.json").write_text(
        json.dumps(environment, indent=2) + "\n", encoding="utf-8")
    # Bound collections carry their own freshly generated demo data. They work
    # with "No environment" and ignore unrelated, stale workspace environments.
    from postman_ready import publish_ready
    publish_ready(demo, variables, admin_email, admin_password, grpc_port)
    print("PASS: owner 200, visitor 404, customer status change 403, notification, stock = 3")
    print(f"Demo directory: {demo.relative_to(ROOT)}")
    print("Open Postman-Ready and import the two *ready.postman_collection.json files.")
    print("No environment is required for the ready collections. Use grpc-rehearsal/ for practice.")
    return demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--grpc-port", type=int, default=50051)
    args = parser.parse_args()
    url = urlsplit(args.base_url)
    if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost"} or (
        url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment
    ):
        parser.error("--base-url must be a local HTTP origin")
    if not 1 <= args.grpc_port <= 65535:
        parser.error("--grpc-port must be between 1 and 65535")
    try:
        admin_email = os.getenv("ADMIN_EMAIL")
        admin_password = os.getenv("ADMIN_PASSWORD")
        if not admin_email or not admin_password:
            admin_email, admin_password = subprocess.check_output(
                [*COMPOSE, "exec", "-T", "api", "printenv", "ADMIN_EMAIL", "ADMIN_PASSWORD"],
                cwd=ROOT, text=True, timeout=15,
            ).splitlines()
        stock_command = os.getenv("SHOP_WAREHOUSE_STOCK_JSON")
        warehouse = (json.loads(stock_command) if stock_command
                     else [*COMPOSE, "exec", "-T", "warehouse", "/usr/local/bin/warehouse"])
        if not admin_password:
            raise RuntimeError("ADMIN_PASSWORD is empty")
        prepare(args.base_url.rstrip("/"), args.grpc_port, admin_email, admin_password, warehouse)
    except (OSError, URLError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Demo preparation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
