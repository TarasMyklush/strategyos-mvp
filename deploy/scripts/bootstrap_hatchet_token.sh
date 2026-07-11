#!/usr/bin/env bash
set -euo pipefail

if [ "${ALLOW_HATCHET_TOKEN_BOOTSTRAP:-false}" != "true" ]; then
  echo "Set ALLOW_HATCHET_TOKEN_BOOTSTRAP=true to create a token for the persisted Hatchet tenant." >&2
  exit 1
fi

COMPOSE_FILES="${COMPOSE_FILES:-deploy/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-deploy/.env}"
SECRETS_FILE="${SECRETS_FILE:-deploy/.env.secrets}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
HATCHET_TENANT_ID="${HATCHET_TENANT_ID:-707d0855-80ab-4e1f-a156-f1c4546cbf52}"
HATCHET_TOKEN_NAME="${HATCHET_TOKEN_NAME:-strategyos-$(date -u +%Y%m%dT%H%M%SZ)}"
HATCHET_TOKEN_EXPIRES_IN="${HATCHET_TOKEN_EXPIRES_IN:-8760h}"

compose_args=()
for compose_file in ${COMPOSE_FILES}; do
  compose_args+=(-f "${compose_file}")
done
compose_args+=(--profile hatchet)
if [ -n "${COMPOSE_PROJECT_NAME}" ]; then
  compose_args+=(--project-name "${COMPOSE_PROJECT_NAME}")
fi
compose_args+=(--env-file "${ENV_FILE}" --env-file "${SECRETS_FILE}")

echo "Starting the persisted Hatchet control plane without resetting volumes." >&2
docker compose "${compose_args[@]}" up -d --wait --wait-timeout 180 hatchet-postgres hatchet-lite >&2

container_id="$(docker compose "${compose_args[@]}" ps -q hatchet-lite)"
if [ -z "${container_id}" ]; then
  echo "Hatchet Lite container was not created." >&2
  exit 1
fi

config_value() {
  local key="${1}"
  docker exec "${container_id}" sh -lc \
    "grep -m1 '^[[:space:]]*${key}:' /config/server.yaml | sed 's/^[^:]*: //'"
}

hatchet_cookie_secrets="$(config_value secrets)"
hatchet_master_keyset="$(config_value masterKeyset)"
hatchet_private_keyset="$(config_value privateJWTKeyset)"
hatchet_public_keyset="$(config_value publicJWTKeyset)"
if [ -z "${hatchet_cookie_secrets}" ] \
  || [ -z "${hatchet_master_keyset}" ] \
  || [ -z "${hatchet_private_keyset}" ] \
  || [ -z "${hatchet_public_keyset}" ]; then
  echo "Hatchet generated config did not contain the required persistent key material." >&2
  exit 1
fi

HATCHET_SERVER_AUTH_COOKIE_SECRETS="${hatchet_cookie_secrets}" \
HATCHET_SERVER_ENCRYPTION_MASTER_KEYSET="${hatchet_master_keyset}" \
HATCHET_SERVER_ENCRYPTION_JWT_PRIVATE_KEYSET="${hatchet_private_keyset}" \
HATCHET_SERVER_ENCRYPTION_JWT_PUBLIC_KEYSET="${hatchet_public_keyset}" \
python3 - "${SECRETS_FILE}" <<'PY'
from pathlib import Path
import os
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
keys = (
    "HATCHET_SERVER_AUTH_COOKIE_SECRETS",
    "HATCHET_SERVER_ENCRYPTION_MASTER_KEYSET",
    "HATCHET_SERVER_ENCRYPTION_JWT_PRIVATE_KEYSET",
    "HATCHET_SERVER_ENCRYPTION_JWT_PUBLIC_KEYSET",
)
lines = [line for line in lines if not any(line.startswith(f"{key}=") for key in keys)]
lines.extend(f"{key}={os.environ[key]}" for key in keys)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

token="$(
  docker exec "${container_id}" /hatchet-admin --config /config token create \
    --tenant-id "${HATCHET_TENANT_ID}" \
    --name "${HATCHET_TOKEN_NAME}" \
    --expiresIn "${HATCHET_TOKEN_EXPIRES_IN}"
)"
token="$(printf '%s\n' "${token}" | tail -n 1)"
if [ -z "${token}" ]; then
  echo "Hatchet did not return a token." >&2
  exit 1
fi

HATCHET_CLIENT_TOKEN="${token}" python3 - "${SECRETS_FILE}" <<'PY'
from pathlib import Path
import os
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
lines = [line for line in lines if not line.startswith("HATCHET_CLIENT_TOKEN=")]
lines.append(f"HATCHET_CLIENT_TOKEN={os.environ['HATCHET_CLIENT_TOKEN']}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

# The token is deliberately the only stdout output so callers can pipe it
# directly into a secret manager without writing it to disk.
printf '%s' "${token}"
