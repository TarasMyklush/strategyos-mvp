#!/usr/bin/env bash
set -euo pipefail

TARGET_URL="${TARGET_URL:-}"
TARGET_HOST="${TARGET_HOST:-}"
SSH_OPTS="${SSH_OPTS:-}"
PAYLOAD='{"skip_prepare": true, "sync_artifacts": true}'

if [ -n "${TARGET_URL}" ]; then
  curl -fsS -X POST "${TARGET_URL%/}/runs" -H "Content-Type: application/json" -d "${PAYLOAD}"
  echo
  exit 0
fi

if [ -z "${TARGET_HOST}" ]; then
  echo "Set TARGET_URL=https://domain or TARGET_HOST=root@server."
  exit 1
fi

ssh ${SSH_OPTS} "${TARGET_HOST}" "curl -fsS -X POST http://localhost/runs -H 'Content-Type: application/json' -d '${PAYLOAD}' && echo"
