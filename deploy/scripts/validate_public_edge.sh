#!/usr/bin/env bash
set -euo pipefail

TARGET_URL="${TARGET_URL:?Set TARGET_URL, for example https://strategyos.example.com}"
ROOT_PATH="${ROOT_PATH:-/}"

TARGET_URL="${TARGET_URL}" ROOT_PATH="${ROOT_PATH}" python3 - <<'PY'
from __future__ import annotations

import ssl
import sys
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlparse


target_url = sys.argv[1] if len(sys.argv) > 1 else None
if target_url is None:
    import os

    target_url = os.environ["TARGET_URL"]
    root_path = os.environ["ROOT_PATH"]
else:
    import os

    root_path = os.environ.get("ROOT_PATH", "/")

parsed = urlparse(target_url)
if parsed.scheme not in {"http", "https"}:
    raise SystemExit(f"TARGET_URL must be http(s), got: {target_url}")

path = root_path if root_path.startswith("/") else f"/{root_path}"
path = path or "/"

if parsed.scheme == "https":
    conn = HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=10, context=ssl.create_default_context())
else:
    conn = HTTPConnection(parsed.hostname, parsed.port or 80, timeout=10)

conn.request("GET", path)
response = conn.getresponse()
headers = {k.lower(): v for k, v in response.getheaders()}
body_preview = response.read(200).decode("utf-8", "replace")
conn.close()

errors: list[str] = []

def require(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


require(200 <= response.status < 400, f"Expected {path} to return 2xx/3xx, got HTTP {response.status}.")
require(headers.get("x-content-type-options", "").lower() == "nosniff", "Missing X-Content-Type-Options: nosniff header.")
require(headers.get("x-frame-options", "").upper() == "DENY", "Missing X-Frame-Options: DENY header.")
require(headers.get("referrer-policy", "").lower() == "no-referrer", "Missing Referrer-Policy: no-referrer header.")
require(bool(headers.get("permissions-policy", "").strip()), "Missing Permissions-Policy header.")
require(not headers.get("server"), f"Server header should be stripped at the public edge, got: {headers.get('server')!r}.")
if parsed.scheme == "https":
    hsts = headers.get("strict-transport-security", "")
    require(bool(hsts.strip()), "Missing Strict-Transport-Security header on HTTPS edge.")
    require("max-age=" in hsts.lower(), f"Strict-Transport-Security must include max-age, got: {hsts!r}.")

if errors:
    for message in errors:
        print(f"PUBLIC EDGE VALIDATION FAILED: {message}", file=sys.stderr)
    print(body_preview, file=sys.stderr)
    raise SystemExit(1)

print(f"Public edge validation passed for {target_url}{path} (HTTP {response.status}).")
PY
