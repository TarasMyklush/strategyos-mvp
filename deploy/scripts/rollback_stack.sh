#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="${TARGET_HOST:?Set TARGET_HOST, for example root@1.2.3.4}"
TARGET_DIR="${TARGET_DIR:-/opt/strategyos}"
SSH_OPTS="${SSH_OPTS:-}"
COMPOSE_FILES="${COMPOSE_FILES:-deploy/docker-compose.yml}"
COMPOSE_PROFILES="${COMPOSE_PROFILES:-}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"

COMPOSE_FILE_ARGS=""
for compose_file in ${COMPOSE_FILES}; do
  COMPOSE_FILE_ARGS="${COMPOSE_FILE_ARGS} -f ${compose_file}"
done

COMPOSE_PROFILE_ARGS=""
for compose_profile in ${COMPOSE_PROFILES}; do
  COMPOSE_PROFILE_ARGS="${COMPOSE_PROFILE_ARGS} --profile ${compose_profile}"
done

PROJECT_NAME_ARG=""
if [ -n "${COMPOSE_PROJECT_NAME}" ]; then
  PROJECT_NAME_ARG=" --project-name ${COMPOSE_PROJECT_NAME}"
fi

ssh ${SSH_OPTS} "${TARGET_HOST}" "TARGET_DIR='${TARGET_DIR}' COMPOSE_FILE_ARGS='${COMPOSE_FILE_ARGS}' COMPOSE_PROFILE_ARGS='${COMPOSE_PROFILE_ARGS}' PROJECT_NAME_ARG='${PROJECT_NAME_ARG}' bash -s" <<'REMOTE'
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
  docker compose${COMPOSE_FILE_ARGS}${COMPOSE_PROFILE_ARGS}${PROJECT_NAME_ARG} --env-file deploy/.env --env-file deploy/.env.secrets up -d --no-build
else
  docker compose${COMPOSE_FILE_ARGS}${COMPOSE_PROFILE_ARGS}${PROJECT_NAME_ARG} --env-file deploy/.env --env-file deploy/.env.secrets up -d --build
fi
echo "Rolled back to ${latest}"
REMOTE
