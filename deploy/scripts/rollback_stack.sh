#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="${TARGET_HOST:?Set TARGET_HOST, for example root@1.2.3.4}"
TARGET_DIR="${TARGET_DIR:-/opt/strategyos}"
SSH_OPTS="${SSH_OPTS:-}"
COMPOSE_FILES="${COMPOSE_FILES:-deploy/docker-compose.yml}"

COMPOSE_FILE_ARGS=""
for compose_file in ${COMPOSE_FILES}; do
  COMPOSE_FILE_ARGS="${COMPOSE_FILE_ARGS} -f ${compose_file}"
done

ssh ${SSH_OPTS} "${TARGET_HOST}" "TARGET_DIR='${TARGET_DIR}' COMPOSE_FILE_ARGS='${COMPOSE_FILE_ARGS}' bash -s" <<'REMOTE'
set -euo pipefail
latest="$(ls -td "${TARGET_DIR}"/backups/app-* 2>/dev/null | head -1 || true)"
if [ -z "${latest}" ]; then
  echo "No rollback backup found under ${TARGET_DIR}/backups."
  exit 1
fi
if [ -d "${TARGET_DIR}/app" ]; then
  mv "${TARGET_DIR}/app" "${TARGET_DIR}/app.failed.$(date +%Y%m%d%H%M%S)"
fi
cp -a "${latest}" "${TARGET_DIR}/app"
cd "${TARGET_DIR}/app"
if grep -Eq '^STRATEGYOS_API_IMAGE=.' deploy/.env; then
  docker compose${COMPOSE_FILE_ARGS} --env-file deploy/.env --env-file deploy/.env.secrets up -d --no-build
else
  docker compose${COMPOSE_FILE_ARGS} --env-file deploy/.env --env-file deploy/.env.secrets up -d --build
fi
echo "Rolled back to ${latest}"
REMOTE
