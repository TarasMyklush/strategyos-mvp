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

if [[ "${TARGET_DIR}" == /opt/strategyos-branch ]]; then
  IDP_CONTAINER="strategyos-branch-strategyos-idp-1"
else
  IDP_CONTAINER="strategyos-strategyos-idp-1"
fi

ssh ${SSH_OPTS} "${TARGET_HOST}" \
  "docker exec -i '${IDP_CONTAINER}' env STRATEGYOS_IDP_TOKEN_ROLE='${ROLE}' python -" <<'PY'
from __future__ import annotations

import json
import os
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError

role = os.environ["STRATEGYOS_IDP_TOKEN_ROLE"].upper()
token_url = "http://127.0.0.1:9000/oauth/token"

payload = urlencode(
    {
        "grant_type": "password",
        "client_id": os.environ["STRATEGYOS_IDP_CLIENT_ID"],
        "client_secret": os.environ["STRATEGYOS_IDP_CLIENT_SECRET"],
        "username": os.environ[f"STRATEGYOS_IDP_{role}_USERNAME"],
        "password": os.environ[f"STRATEGYOS_IDP_{role}_PASSWORD"],
    }
).encode("utf-8")

request = Request(
    token_url,
    data=payload,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    method="POST",
)

for attempt in range(10):
    try:
        with urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
        break
    except URLError:
        if attempt == 9:
            raise
        time.sleep(1)

print(body["access_token"])
PY
