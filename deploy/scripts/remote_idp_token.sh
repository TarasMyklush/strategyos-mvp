#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="${TARGET_HOST:?Set TARGET_HOST, for example root@1.2.3.4}"
TARGET_DIR="${TARGET_DIR:-/opt/strategyos}"
SSH_OPTS="${SSH_OPTS:-}"
ROLE="${ROLE:-operator}"

case "${ROLE}" in
  operator|reviewer) ;;
  *)
    echo "ROLE must be operator or reviewer." >&2
    exit 2
    ;;
esac

ssh ${SSH_OPTS} "${TARGET_HOST}" "cd '${TARGET_DIR}/app' && STRATEGYOS_IDP_TOKEN_ROLE='${ROLE}' python3 -" <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


config = load_env(Path("deploy/.env"))
secrets = load_env(Path("deploy/.env.secrets"))
role = os.environ["STRATEGYOS_IDP_TOKEN_ROLE"].upper()
token_port = config.get("STRATEGYOS_IDP_HTTP_PORT", "8089")
token_url = config.get("STRATEGYOS_IDP_HOST_TOKEN_URL", f"http://127.0.0.1:{token_port}/oauth/token")

payload = urlencode(
    {
        "grant_type": "password",
        "client_id": config["STRATEGYOS_IDP_CLIENT_ID"],
        "client_secret": secrets["STRATEGYOS_IDP_CLIENT_SECRET"],
        "username": config[f"STRATEGYOS_IDP_{role}_USERNAME"],
        "password": secrets[f"STRATEGYOS_IDP_{role}_PASSWORD"],
    }
).encode("utf-8")

request = Request(
    token_url,
    data=payload,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    method="POST",
)

with urlopen(request, timeout=10) as response:
    body = json.loads(response.read().decode("utf-8"))

print(body["access_token"])
PY
