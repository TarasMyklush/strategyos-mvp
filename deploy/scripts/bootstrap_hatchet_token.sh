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

# The token is deliberately the only stdout output so callers can pipe it
# directly into a secret manager without writing it to disk.
printf '%s' "${token}"
