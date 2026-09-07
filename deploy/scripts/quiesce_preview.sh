#!/usr/bin/env bash
# Fail closed after an attempted preview rollout. Keep all evidence/history and
# infrastructure; never automatically restore a potentially weaker application.
set -euo pipefail
TARGET_HOST="${TARGET_HOST:?Set the preview SSH host}"
TARGET_DIR="${TARGET_DIR:?Set the preview deployment directory}"
SSH_OPTS="${SSH_OPTS:-}"
if [[ "${TARGET_DIR}" != "/opt/strategyos-branch" ]]; then
  echo "Refusing recovery outside the preview deployment." >&2
  exit 1
fi
ssh ${SSH_OPTS} "${TARGET_HOST}" bash -s <<'REMOTE'
set -euo pipefail
for service in strategyos-api strategyos-worker strategyos-claim-projector; do
  ids=$(docker ps -q \
    --filter label=com.docker.compose.project=strategyos-branch \
    --filter "label=com.docker.compose.service=$service")
  for container_id in $ids; do
    [[ "$container_id" =~ ^[a-f0-9]{12,64}$ ]] || { echo "Invalid container identity; refusing recovery." >&2; exit 1; }
    project=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$container_id")
    actual_service=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$container_id")
    [[ "$project" == strategyos-branch && "$actual_service" == "$service" ]] || { echo "Preview ownership mismatch; refusing stop." >&2; exit 1; }
    docker stop --time 30 "$container_id"
  done
done
mapfile -t postgres_ids < <(docker ps -q \
  --filter label=com.docker.compose.project=strategyos-branch \
  --filter label=com.docker.compose.service=postgres)
if (( ${#postgres_ids[@]} > 1 )); then
  echo "Ambiguous preview PostgreSQL ownership; refusing recovery." >&2
  exit 1
fi
if (( ${#postgres_ids[@]} == 1 )); then
  postgres_id="${postgres_ids[0]}"
  [[ "$postgres_id" =~ ^[a-f0-9]{12,64}$ ]] || { echo "Invalid PostgreSQL container identity; refusing recovery." >&2; exit 1; }
  project=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$postgres_id")
  actual_service=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$postgres_id")
  [[ "$project" == strategyos-branch && "$actual_service" == postgres ]] || { echo "Preview PostgreSQL ownership mismatch; refusing recovery." >&2; exit 1; }
  docker exec "$postgres_id" sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'"'"'SQL'"'"'
update strategyos_run_jobs
set status = 'cancelled',
    failure_reason = 'Guarded preview shutdown interrupted this queued or running job.',
    metadata_json = coalesce(metadata_json, '{}'::jsonb) || '{"shutdown_reason":"failed_preview_rollout"}'::jsonb,
    finished_at = coalesce(finished_at, now()),
    updated_at = now()
where status in ('queued', 'running');
SQL'
fi
echo "Preview application quiesced. Database, evidence, audit history, indexes and backups retained."
echo "Recovery requires a verified roll-forward release; no older read path was automatically enabled."
REMOTE
