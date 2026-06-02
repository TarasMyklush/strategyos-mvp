#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="${TARGET_HOST:?Set TARGET_HOST, for example root@1.2.3.4}"
TARGET_DIR="${TARGET_DIR:-/opt/strategyos}"
SSH_OPTS="${SSH_OPTS:-}"
LOCAL_ENV="${LOCAL_ENV:-deploy/.env}"

if [ ! -f "${LOCAL_ENV}" ]; then
  echo "Missing ${LOCAL_ENV}. Run deploy/scripts/generate_env.sh first or create it from deploy/.env.example."
  exit 1
fi

ssh ${SSH_OPTS} "${TARGET_HOST}" "mkdir -p '${TARGET_DIR}' '${TARGET_DIR}/backups'"

ssh ${SSH_OPTS} "${TARGET_HOST}" "if [ -d '${TARGET_DIR}/app' ]; then cp -a '${TARGET_DIR}/app' '${TARGET_DIR}/backups/app-$(date +%Y%m%d%H%M%S)'; fi"

rsync -az --delete \
  --exclude ".git" \
  --exclude "__pycache__" \
  --exclude ".pytest_cache" \
  --exclude "deploy/.env" \
  ./ "${TARGET_HOST}:${TARGET_DIR}/app/"

rsync -az "${LOCAL_ENV}" "${TARGET_HOST}:${TARGET_DIR}/app/deploy/.env"

ssh ${SSH_OPTS} "${TARGET_HOST}" "cd '${TARGET_DIR}/app' && docker compose -f deploy/docker-compose.yml --env-file deploy/.env pull postgres redis neo4j minio minio-create-bucket caddy && docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build"

echo "Deployment complete. Run: TARGET_HOST=${TARGET_HOST} deploy/scripts/check_health.sh"
