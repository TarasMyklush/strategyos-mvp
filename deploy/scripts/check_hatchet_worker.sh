#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILES="${COMPOSE_FILES:-deploy/docker-compose.yml}"
COMPOSE_PROFILES="${COMPOSE_PROFILES:-hatchet}"
ENV_FILE="${ENV_FILE:-deploy/.env}"
SECRETS_FILE="${SECRETS_FILE:-deploy/.env.secrets}"
SERVICE="${HATCHET_WORKER_SERVICE:-strategyos-worker}"
ATTEMPTS="${HATCHET_WORKER_CHECK_ATTEMPTS:-12}"
SLEEP_SECONDS="${HATCHET_WORKER_CHECK_SLEEP_SECONDS:-5}"
LOG_TAIL="${HATCHET_WORKER_CHECK_LOG_TAIL:-160}"

compose_args=()
for compose_file in ${COMPOSE_FILES}; do
  compose_args+=(-f "${compose_file}")
done

for compose_profile in ${COMPOSE_PROFILES}; do
  compose_args+=(--profile "${compose_profile}")
done

compose_args+=(--env-file "${ENV_FILE}" --env-file "${SECRETS_FILE}")

check_logs_for_auth_error() {
  docker compose "${compose_args[@]}" logs --tail="${LOG_TAIL}" "${SERVICE}" 2>&1 \
    | grep -E "invalid auth token|UNAUTHENTICATED|failed to register workflow" >/dev/null
}

last_state=""
for ((attempt = 1; attempt <= ATTEMPTS; attempt += 1)); do
  container_id="$(docker compose "${compose_args[@]}" ps -q "${SERVICE}" 2>/dev/null || true)"
  if [ -z "${container_id}" ]; then
    last_state="missing-container"
  else
    status="$(docker inspect "${container_id}" --format '{{.State.Status}}' 2>/dev/null || true)"
    restart_count="$(docker inspect "${container_id}" --format '{{.RestartCount}}' 2>/dev/null || true)"
    last_state="status=${status:-unknown} restart_count=${restart_count:-unknown}"

    if check_logs_for_auth_error; then
      echo "Hatchet worker authentication/registration failure detected in recent logs." >&2
      docker compose "${compose_args[@]}" logs --tail="${LOG_TAIL}" "${SERVICE}" >&2
      exit 1
    fi

    if [ "${status}" = "running" ] && [ "${restart_count}" = "0" ]; then
      echo "Hatchet worker is running; restart_count=0; no auth-registration errors in recent logs."
      exit 0
    fi
  fi

  if [ "${attempt}" -lt "${ATTEMPTS}" ]; then
    sleep "${SLEEP_SECONDS}"
  fi
done

echo "Hatchet worker did not become healthy: ${last_state}" >&2
docker compose "${compose_args[@]}" ps "${SERVICE}" >&2 || true
docker compose "${compose_args[@]}" logs --tail="${LOG_TAIL}" "${SERVICE}" >&2 || true
exit 1
