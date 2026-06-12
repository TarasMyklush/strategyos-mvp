#!/usr/bin/env bash
set -euo pipefail

TARGET_URL="${TARGET_URL:-}"
TARGET_HOST="${TARGET_HOST:-}"
SSH_OPTS="${SSH_OPTS:-}"
RUN_AUTH_HEADER="${RUN_AUTH_HEADER:-}"
PAYLOAD='{"skip_prepare": true, "sync_artifacts": true}'

curl_run() {
  local base_url="${1%/}"
  if [ -n "${RUN_AUTH_HEADER}" ]; then
    curl -fsS -X POST "${base_url}/runs" -H "${RUN_AUTH_HEADER}" -H "Content-Type: application/json" -d "${PAYLOAD}"
  else
    curl -fsS -X POST "${base_url}/runs" -H "Content-Type: application/json" -d "${PAYLOAD}"
  fi
}

if [ -n "${TARGET_URL}" ]; then
  curl_run "${TARGET_URL}"
  echo
  exit 0
fi

if [ -z "${TARGET_HOST}" ]; then
  echo "Set TARGET_URL=https://domain or TARGET_HOST=root@server."
  exit 1
fi

REMOTE_HEADER="${RUN_AUTH_HEADER//\"/\\\"}"
ssh ${SSH_OPTS} "${TARGET_HOST}" "if [ -n \"${REMOTE_HEADER}\" ]; then curl -fsS -X POST http://localhost/runs -H \"${REMOTE_HEADER}\" -H 'Content-Type: application/json' -d '${PAYLOAD}'; else curl -fsS -X POST http://localhost/runs -H 'Content-Type: application/json' -d '${PAYLOAD}'; fi && echo"
