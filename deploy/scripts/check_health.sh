#!/usr/bin/env bash
set -euo pipefail

TARGET_URL="${TARGET_URL:-}"
TARGET_HOST="${TARGET_HOST:-}"
SSH_OPTS="${SSH_OPTS:-}"
READINESS_API_KEY="${READINESS_API_KEY:-}"
READINESS_AUTH_HEADER="${READINESS_AUTH_HEADER:-}"

if [ -z "${READINESS_AUTH_HEADER}" ] && [ -n "${READINESS_API_KEY}" ]; then
  READINESS_AUTH_HEADER="X-API-Key: ${READINESS_API_KEY}"
fi

curl_ready() {
  local base_url="${1%/}"
  if [ -n "${READINESS_AUTH_HEADER}" ]; then
    curl -fsS -H "${READINESS_AUTH_HEADER}" "${base_url}/health/ready"
  else
    curl -fsS "${base_url}/health/ready"
  fi
}

if [ -n "${TARGET_URL}" ]; then
  curl_ready "${TARGET_URL}"
  echo
  exit 0
fi

if [ -z "${TARGET_HOST}" ]; then
  echo "Set TARGET_URL=https://domain or TARGET_HOST=root@server. Provide READINESS_API_KEY or READINESS_AUTH_HEADER when readiness is protected."
  exit 1
fi

REMOTE_HEADER="${READINESS_AUTH_HEADER//\"/\\\"}"
ssh ${SSH_OPTS} "${TARGET_HOST}" "if [ -n \"${REMOTE_HEADER}\" ]; then curl -fsS -H \"${REMOTE_HEADER}\" http://localhost/health/ready; else curl -fsS http://localhost/health/ready; fi && echo"
