#!/usr/bin/env bash
set -euo pipefail

TARGET_URL="${TARGET_URL:-}"
TARGET_HOST="${TARGET_HOST:-}"
SSH_OPTS="${SSH_OPTS:-}"
RUN_AUTH_HEADER="${RUN_AUTH_HEADER:-}"
RUN_POLL_JOB="${RUN_POLL_JOB:-true}"
RUN_POLL_TIMEOUT_SECONDS="${RUN_POLL_TIMEOUT_SECONDS:-900}"
RUN_POLL_INTERVAL_SECONDS="${RUN_POLL_INTERVAL_SECONDS:-5}"
RUN_PAYLOAD="${RUN_PAYLOAD:-}"
if [ -n "${RUN_PAYLOAD}" ]; then
  PAYLOAD="${RUN_PAYLOAD}"
else
  PAYLOAD='{"skip_prepare": true, "sync_artifacts": true}'
fi

curl_run() {
  local base_url="${1%/}"
  if [ -n "${RUN_AUTH_HEADER}" ]; then
    curl -fsS -X POST "${base_url}/runs" -H "${RUN_AUTH_HEADER}" -H "Content-Type: application/json" -d "${PAYLOAD}"
  else
    curl -fsS -X POST "${base_url}/runs" -H "Content-Type: application/json" -d "${PAYLOAD}"
  fi
}

REMOTE_HEADER="${RUN_AUTH_HEADER//\"/\\\"}"

curl_job() {
  local base_url="${1%/}"
  local job_id="${2}"
  if [ -n "${RUN_AUTH_HEADER}" ]; then
    curl -fsS "${base_url}/runs/jobs/${job_id}" -H "${RUN_AUTH_HEADER}"
  else
    curl -fsS "${base_url}/runs/jobs/${job_id}"
  fi
}

remote_run() {
  ssh ${SSH_OPTS} "${TARGET_HOST}" "if [ -n \"${REMOTE_HEADER}\" ]; then curl -fsS -X POST http://localhost/runs -H \"${REMOTE_HEADER}\" -H 'Content-Type: application/json' -d '${PAYLOAD}'; else curl -fsS -X POST http://localhost/runs -H 'Content-Type: application/json' -d '${PAYLOAD}'; fi"
}

remote_job() {
  local job_id="${1}"
  ssh ${SSH_OPTS} "${TARGET_HOST}" "if [ -n \"${REMOTE_HEADER}\" ]; then curl -fsS http://localhost/runs/jobs/${job_id} -H \"${REMOTE_HEADER}\"; else curl -fsS http://localhost/runs/jobs/${job_id}; fi"
}

json_field() {
  local field="${1}"
  python3 -c '
import json
import sys

data = json.load(sys.stdin)
value = data
for part in sys.argv[1].split("."):
    value = value.get(part, "") if isinstance(value, dict) else ""
if value is None:
    value = ""
print(json.dumps(value) if isinstance(value, (dict, list)) else value)
' "${field}"
}

if [ -n "${TARGET_URL}" ]; then
  response="$(curl_run "${TARGET_URL}")"
elif [ -n "${TARGET_HOST}" ]; then
  response="$(remote_run)"
else
  echo "Set TARGET_URL=https://domain or TARGET_HOST=root@server."
  exit 1
fi

printf '%s\n' "${response}"
job_id="$(printf '%s' "${response}" | json_field job_id || true)"
if [ "${RUN_POLL_JOB}" != "true" ] || [ -z "${job_id}" ]; then
  exit 0
fi

deadline=$((SECONDS + RUN_POLL_TIMEOUT_SECONDS))
while [ "${SECONDS}" -lt "${deadline}" ]; do
  if [ -n "${TARGET_URL}" ]; then
    status_response="$(curl_job "${TARGET_URL}" "${job_id}")"
  else
    status_response="$(remote_job "${job_id}")"
  fi
  status="$(printf '%s' "${status_response}" | json_field status || true)"
  printf '%s\n' "${status_response}"
  case "${status}" in
    succeeded|completed)
      exit 0
      ;;
    failed|cancelled|canceled)
      exit 1
      ;;
  esac
  sleep "${RUN_POLL_INTERVAL_SECONDS}"
done

echo "Timed out waiting for run job ${job_id}." >&2
exit 1
