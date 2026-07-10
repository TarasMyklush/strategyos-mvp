#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="${TARGET_HOST:?Set TARGET_HOST, for example root@1.2.3.4}"
TARGET_DIR="${TARGET_DIR:-/opt/strategyos}"
SSH_OPTS="${SSH_OPTS:-}"
LOCAL_ENV="${LOCAL_ENV:-deploy/.env}"
LOCAL_SECRETS_ENV="${LOCAL_SECRETS_ENV:-deploy/.env.secrets}"
COMPOSE_FILES="${COMPOSE_FILES:-deploy/docker-compose.yml}"
COMPOSE_PROFILES="${COMPOSE_PROFILES:-}"
COMPOSE_WAIT_TIMEOUT_SECONDS="${COMPOSE_WAIT_TIMEOUT_SECONDS:-180}"
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

RSYNC_SSH_ARGS=()
if [ -n "${SSH_OPTS}" ]; then
  RSYNC_SSH_ARGS=(-e "ssh ${SSH_OPTS}")
fi

if [ ! -f "${LOCAL_ENV}" ]; then
  echo "Missing ${LOCAL_ENV}. Run deploy/scripts/generate_env.sh first or create it from deploy/.env.example."
  exit 1
fi

if [ ! -f "${LOCAL_SECRETS_ENV}" ]; then
  echo "Missing ${LOCAL_SECRETS_ENV}. Run deploy/scripts/generate_env.sh first or inject it from your secret manager."
  exit 1
fi

ENV_FILE="${LOCAL_ENV}" \
SECRETS_FILE="${LOCAL_SECRETS_ENV}" \
TARGET_ENVIRONMENT="${TARGET_ENVIRONMENT:-}" \
TARGET_PUBLIC_URL="${STRATEGYOS_PUBLIC_URL:-}" \
TARGET_DEPLOY_USER="${HETZNER_USER:-}" \
bash deploy/scripts/validate_deploy_boundary.sh

ssh ${SSH_OPTS} "${TARGET_HOST}" "mkdir -p '${TARGET_DIR}' '${TARGET_DIR}/backups'"

ssh ${SSH_OPTS} "${TARGET_HOST}" "if [ -d '${TARGET_DIR}/app' ]; then cp -a '${TARGET_DIR}/app' '${TARGET_DIR}/backups/app-$(date +%Y%m%d%H%M%S)'; fi"

rsync -az --delete "${RSYNC_SSH_ARGS[@]}" \
  --exclude ".git" \
  --exclude "__pycache__" \
  --exclude ".pytest_cache" \
  --exclude "deploy/.env" \
  --exclude "deploy/.env.secrets" \
  --exclude "deploy/.env.*" \
  ./ "${TARGET_HOST}:${TARGET_DIR}/app/"

rsync -az "${RSYNC_SSH_ARGS[@]}" "${LOCAL_ENV}" "${TARGET_HOST}:${TARGET_DIR}/app/deploy/.env"
rsync -az "${RSYNC_SSH_ARGS[@]}" "${LOCAL_SECRETS_ENV}" "${TARGET_HOST}:${TARGET_DIR}/app/deploy/.env.secrets"

if [ -n "${STRATEGYOS_API_IMAGE:-}" ]; then
  ssh ${SSH_OPTS} "${TARGET_HOST}" "docker pull '${STRATEGYOS_API_IMAGE}'"
  ssh ${SSH_OPTS} "${TARGET_HOST}" "cd '${TARGET_DIR}/app' && docker compose${COMPOSE_FILE_ARGS}${COMPOSE_PROFILE_ARGS}${PROJECT_NAME_ARG} --env-file deploy/.env --env-file deploy/.env.secrets pull --ignore-buildable && docker compose${COMPOSE_FILE_ARGS}${COMPOSE_PROFILE_ARGS}${PROJECT_NAME_ARG} --env-file deploy/.env --env-file deploy/.env.secrets up -d --no-build --wait --wait-timeout '${COMPOSE_WAIT_TIMEOUT_SECONDS}'"
else
  ssh ${SSH_OPTS} "${TARGET_HOST}" "cd '${TARGET_DIR}/app' && docker compose${COMPOSE_FILE_ARGS}${COMPOSE_PROFILE_ARGS}${PROJECT_NAME_ARG} --env-file deploy/.env --env-file deploy/.env.secrets pull --ignore-buildable && docker compose${COMPOSE_FILE_ARGS}${COMPOSE_PROFILE_ARGS}${PROJECT_NAME_ARG} --env-file deploy/.env --env-file deploy/.env.secrets up -d --build --wait --wait-timeout '${COMPOSE_WAIT_TIMEOUT_SECONDS}'"
fi

ssh ${SSH_OPTS} "${TARGET_HOST}" "cd '${TARGET_DIR}/app' && docker compose${COMPOSE_FILE_ARGS}${COMPOSE_PROFILE_ARGS}${PROJECT_NAME_ARG} --env-file deploy/.env --env-file deploy/.env.secrets up -d --no-deps --force-recreate caddy && docker compose${COMPOSE_FILE_ARGS}${COMPOSE_PROFILE_ARGS}${PROJECT_NAME_ARG} --env-file deploy/.env --env-file deploy/.env.secrets exec -T caddy caddy reload --config /etc/caddy/Caddyfile"

echo "Deployment complete. Run: TARGET_HOST=${TARGET_HOST} deploy/scripts/check_health.sh"
