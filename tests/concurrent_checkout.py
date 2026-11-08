#!/usr/bin/env python3
"""Create a one-unit demo product and race 20 distinct customers against it."""

import argparse
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from threading import Barrier
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CUSTOMERS = 20


class LoginFailure(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Login failed with HTTP {status}. Check the actual database credentials.")


def request(base, method, path, body=None, token=None, content_type="application/json"):
    payload = json.dumps(body).encode() if isinstance(body, dict) else body
    headers = {"Accept": "application/json", "Content-Type": content_type}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(base + "/api/v1" + path, data=payload, method=method, headers=headers)
    try:
        response = urlopen(req, timeout=20)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read()), response.headers


def expect(base, method, path, expected, **kwargs):
    status, body, headers = request(base, method, path, **kwargs)
    if status != expected:
        raise RuntimeError(f"{method} {path} expected HTTP {expected}, received {status}: "
                           + body.get("userMessage", "Unexpected API response"))
    return body


def login(base, credentials):
    for _ in range(8):
        status, body, headers = request(base, "POST", "/auth/login", credentials)
        if status == 200:
            return body["accessToken"]
        if status != 429:
            raise LoginFailure(status)
        delay = min(60, max(1, int(headers.get("Retry-After", "60"))))
        print(f"Login rate limit reached. Waiting {delay}s before preparing the next customer.", flush=True)
        time.sleep(delay)
    raise RuntimeError("Login rate limit did not clear. Retry after other sign-in tests have stopped.")


def prepare_race(base):
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    if not email or not password:
        values = subprocess.check_output(
            ["docker", "compose", "exec", "-T", "api", "printenv", "ADMIN_EMAIL", "ADMIN_PASSWORD"],
            cwd=ROOT, text=True, timeout=15,
        ).splitlines()
        if len(values) != 2:
            raise RuntimeError("Could not read demo administrator settings.")
        email, password = values
    admin = login(base, {"email": email, "password": password})
    suffix = uuid4().hex[:10]
    category = expect(base, "GET", "/categories", 200)[0]["id"]
    boundary = uuid4().hex
    fields = {"name": "Last unit race " + suffix, "description": "Prepared concurrency demonstration",
              "price": "10.00", "categoryId": category}
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
             for key, value in fields.items()]
    image = (ROOT / "tests/fixtures/demo-product.png").read_bytes()
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="race.png"\r\n'
                 f'Content-Type: image/png\r\n\r\n'.encode() + image + f"\r\n--{boundary}--\r\n".encode())
    product = expect(base, "POST", "/products", 201, body=b"".join(parts), token=admin,
                     content_type="multipart/form-data; boundary=" + boundary)
    product_id = product["id"]
    expect(base, "POST", f"/products/{product_id}/stock-additions", 200, token=admin,
           body={"quantity": 1, "operationId": str(uuid4())})
    if expect(base, "GET", "/products/" + product_id, 200)["availableQuantity"] != 1:
        raise RuntimeError("The prepared product must have exactly one available unit.")

    customers = []
    print("Preparing 20 distinct customers. Login protection may make this step take several minutes.", flush=True)
    for index in range(CUSTOMERS):
        credentials = {"email": f"race-{suffix}-{index + 1}@shop.test",
                       "password": "Race1!" + secrets.token_urlsafe(12)}
        expect(base, "POST", "/auth/register", 201, body=credentials)
        customers.append({**credentials, "token": login(base, credentials)})
        print(f"Customer {index + 1}/{CUSTOMERS} ready.", flush=True)

    directory = ROOT / ".demo" / ("race-" + suffix)
    directory.mkdir(parents=True, mode=0o700)
    private = directory / "prepared-private.json"
    private.write_text(json.dumps({"baseUrl": base, "productId": product_id, "productName": product["name"],
                                   "customers": customers}, indent=2) + "\n", encoding="utf-8")
    private.chmod(0o600)
    latest = ROOT / "Postman-Ready" / "race-latest.txt"
    latest.parent.mkdir(exist_ok=True, mode=0o700)
    latest.write_text(str(private.relative_to(ROOT)) + "\n", encoding="utf-8")
    print(f"Prepared race: {private.relative_to(ROOT)}", flush=True)
    print("Run Test-Race.ps1 -Prepared with that path to start the race immediately. Tokens last 15 minutes.", flush=True)
    return private


def execute(base, private):
    private = Path(private).resolve()
    if not private.is_relative_to(ROOT / ".demo"):
        raise RuntimeError("The prepared scenario must be inside this project's .demo directory.")
    saved = json.loads(private.read_text(encoding="utf-8"))
    if saved["baseUrl"] != base or len(saved["customers"]) != CUSTOMERS:
        raise RuntimeError("The saved race does not match this server or does not contain 20 customers.")
    product_id = saved["productId"]
    if expect(base, "GET", "/products/" + product_id, 200)["availableQuantity"] != 1:
        raise RuntimeError("This race was already used, or its stock changed. Prepare a new race for one unit.")
    tokens = []
    for credentials in saved["customers"]:
        token = credentials["token"]
        claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        if claims["exp"] < time.time() + 30:
            print("A prepared token expired. Refreshing sign-ins with login protection enabled.", flush=True)
            token = login(base, {"email": credentials["email"], "password": credentials["password"]})
        tokens.append(token)
    start = Barrier(CUSTOMERS)
    order = {"lines": [{"productId": product_id, "quantity": 1}]}

    def checkout(token):
        start.wait(timeout=15)
        try:
            status, body, headers = request(base, "POST", "/orders", order, token)
            return {"status": status, "body": body}
        except (OSError, ValueError) as error:
            return {"status": 0, "body": {"error": str(error)}}

    print("Starting 20 checkout requests together...", flush=True)
    with ThreadPoolExecutor(max_workers=CUSTOMERS) as pool:
        responses = list(pool.map(checkout, tokens))
    counts = Counter(reply["status"] for reply in responses)
    remaining = expect(base, "GET", "/products/" + product_id, 200)["availableQuantity"]
    winners = [reply["body"] for reply in responses if reply["status"] == 201]
    winner_index = next((index for index, reply in enumerate(responses) if reply["status"] == 201), None)
    winner = expect(base, "GET", "/orders/" + winners[0]["id"], 200, token=tokens[winner_index]) if len(winners) == 1 else None
    passed = counts == {201: 1, 409: 19} and remaining == 0 and winner is not None and winner["status"] == "Pending"
    report = {"passed": passed, "customers": CUSTOMERS, "productId": product_id,
              "productName": saved["productName"], "responses": responses,
              "httpCounts": dict(counts), "availableAfter": remaining,
              "winningOrder": winner}
    directory = private.parent
    (directory / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "Postman-Ready" / "race-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"HTTP results: {dict(counts)}. Available units after the race: {remaining}.")
    print(f"Results saved to {directory.relative_to(ROOT) / 'results.json'}")
    if not passed:
        raise RuntimeError("Race verification failed. Inspect results.json before retrying.")
    print("PASS: 20 customers, 1 successful order, 19 stock conflicts, zero available, winner Pending.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("SHOP_BASE_URL", "http://localhost:8080"))
    parser.add_argument("--prepare-only", action="store_true", help="Create accounts now; run the race later")
    parser.add_argument("--prepared", type=Path, help="Use an existing .demo/race-.../prepared-private.json")
    args = parser.parse_args()
    origin = urlsplit(args.base_url)
    if (origin.scheme != "http" or origin.hostname not in {"localhost", "127.0.0.1"}
            or origin.username or origin.password or origin.path not in {"", "/"} or origin.query or origin.fragment):
        parser.error("--base-url must be a local HTTP origin")
    try:
        base = args.base_url.rstrip("/")
        if args.prepared:
            execute(base, args.prepared)
        else:
            prepared = prepare_race(base)
            if not args.prepare_only:
                execute(base, prepared)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Concurrency demo failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
