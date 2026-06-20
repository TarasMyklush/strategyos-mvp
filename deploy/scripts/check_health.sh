#!/usr/bin/env bash
set -euo pipefail

TARGET_URL="${TARGET_URL:-}"
TARGET_HOST="${TARGET_HOST:-}"
SSH_OPTS="${SSH_OPTS:-}"
READINESS_API_KEY="${READINESS_API_KEY:-}"
READINESS_AUTH_HEADER="${READINESS_AUTH_HEADER:-}"
READINESS_MAX_ATTEMPTS="${READINESS_MAX_ATTEMPTS:-30}"
READINESS_WAIT_SECONDS="${READINESS_WAIT_SECONDS:-2}"
CURL_MAX_TIME_SECONDS="${CURL_MAX_TIME_SECONDS:-10}"

if [ -z "${READINESS_AUTH_HEADER}" ] && [ -n "${READINESS_API_KEY}" ]; then
  READINESS_AUTH_HEADER="X-API-Key: ${READINESS_API_KEY}"
fi

curl_ready_target() {
  local target_url="${1}"
  local tmp_file
  tmp_file="$(mktemp)"
  local http_status
  local curl_status
  if [ -n "${READINESS_AUTH_HEADER}" ]; then
    if http_status="$(curl -sS -o "${tmp_file}" -w "%{http_code}" --max-time "${CURL_MAX_TIME_SECONDS}" -H "${READINESS_AUTH_HEADER}" "${target_url}")"; then
      curl_status=0
    else
      curl_status=$?
    fi
  else
    if http_status="$(curl -sS -o "${tmp_file}" -w "%{http_code}" --max-time "${CURL_MAX_TIME_SECONDS}" "${target_url}")"; then
      curl_status=0
    else
      curl_status=$?
    fi
  fi
  READINESS_LAST_BODY="$(cat "${tmp_file}" 2>/dev/null || true)"
  rm -f "${tmp_file}"
  printf '%s' "${http_status:-000}"
  return ${curl_status}
}

curl_ready_remote() {
  local target_url="${1}"
  local remote_header="${READINESS_AUTH_HEADER//\"/\\\"}"
  local remote_url="${target_url//\"/\\\"}"
  local remote_output
  remote_output="$(ssh ${SSH_OPTS} "${TARGET_HOST}" "READINESS_AUTH_HEADER=\"${remote_header}\" TARGET_URL=\"${remote_url}\" CURL_MAX_TIME_SECONDS=\"${CURL_MAX_TIME_SECONDS}\" bash -s" <<'REMOTE'
set -euo pipefail
tmp_file="$(mktemp)"
if [ -n "${READINESS_AUTH_HEADER}" ]; then
  if http_status="$(curl -sS -o "${tmp_file}" -w "%{http_code}" --max-time "${CURL_MAX_TIME_SECONDS}" -H "${READINESS_AUTH_HEADER}" "${TARGET_URL}")"; then
    curl_status=0
  else
    curl_status=$?
  fi
else
  if http_status="$(curl -sS -o "${tmp_file}" -w "%{http_code}" --max-time "${CURL_MAX_TIME_SECONDS}" "${TARGET_URL}")"; then
    curl_status=0
  else
    curl_status=$?
  fi
fi
printf '__HTTP_STATUS__%s\n' "${http_status:-000}"
cat "${tmp_file}" || true
rm -f "${tmp_file}"
exit ${curl_status}
REMOTE
)"
  local ssh_status=$?
  READINESS_LAST_BODY="$(printf '%s\n' "${remote_output}" | sed '1{/^__HTTP_STATUS__/d;}')"
  printf '%s' "$(printf '%s\n' "${remote_output}" | sed -n '1s/^__HTTP_STATUS__//p')"
  return ${ssh_status}
}

wait_for_ready() {
  local target_url="${1}"
  local runner="${2:-local}"
  local attempt=1
  while [ "${attempt}" -le "${READINESS_MAX_ATTEMPTS}" ]; do
    if [ "${runner}" = "remote" ]; then
      if http_status="$(curl_ready_remote "${target_url}")"; then
        curl_status=0
      else
        curl_status=$?
      fi
    else
      if http_status="$(curl_ready_target "${target_url}")"; then
        curl_status=0
      else
        curl_status=$?
      fi
    fi
    if [ ${curl_status} -eq 0 ]; then
      if [ "${http_status}" = "200" ]; then
        if [ -n "${READINESS_LAST_BODY:-}" ]; then
          printf '%s\n' "${READINESS_LAST_BODY}"
        fi
        return 0
      fi
      echo "Readiness attempt ${attempt}/${READINESS_MAX_ATTEMPTS} returned HTTP ${http_status}." >&2
      if [ -n "${READINESS_LAST_BODY:-}" ]; then
        printf '%s\n' "${READINESS_LAST_BODY}" >&2
      fi
    else
      echo "Readiness attempt ${attempt}/${READINESS_MAX_ATTEMPTS} failed to connect or execute." >&2
      if [ -n "${READINESS_LAST_BODY:-}" ]; then
        printf '%s\n' "${READINESS_LAST_BODY}" >&2
      fi
    fi

    if [ "${attempt}" -lt "${READINESS_MAX_ATTEMPTS}" ]; then
      sleep "${READINESS_WAIT_SECONDS}"
    fi
    attempt=$((attempt + 1))
  done

  echo "Protected readiness did not return HTTP 200 after ${READINESS_MAX_ATTEMPTS} attempts." >&2
  return 1
}

if [ -n "${TARGET_URL}" ]; then
  wait_for_ready "${TARGET_URL%/}/health/ready"
  echo
  exit 0
fi

if [ -z "${TARGET_HOST}" ]; then
  echo "Set TARGET_URL=https://domain or TARGET_HOST=root@server. Provide READINESS_API_KEY or READINESS_AUTH_HEADER when readiness is protected."
  exit 1
fi

wait_for_ready "http://localhost/health/ready" remote
