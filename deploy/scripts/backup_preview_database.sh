#!/usr/bin/env bash
# Preview-only backup. Never reads credentials into the runner or touches prod.
set -euo pipefail
TARGET_HOST="${TARGET_HOST:?Set the preview SSH host}"
TARGET_DIR="${TARGET_DIR:?Set the preview deployment directory}"
SSH_OPTS="${SSH_OPTS:-}"
if [[ "${TARGET_DIR}" != "/opt/strategyos-branch" ]]; then
  echo "Refusing database backup outside the preview deployment." >&2
  exit 1
fi
ssh ${SSH_OPTS} "${TARGET_HOST}" bash -s <<'REMOTE'
set -euo pipefail
umask 077
container=strategyos-branch-postgres-1
if ! docker inspect "$container" >/dev/null 2>&1; then
  echo "Initial preview installation: no existing database to back up."
  exit 0
fi
test "$(docker inspect --format '{{.State.Running}}' "$container")" = true
mkdir -p /opt/strategyos-branch/backups
backup_dir=$(mktemp -d /opt/strategyos-branch/backups/claims-db-XXXXXXXX)
docker exec "$container" sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$backup_dir/database.dump"
test -s "$backup_dir/database.dump"
docker exec -i "$container" pg_restore --list < "$backup_dir/database.dump" >/dev/null
sha256sum "$backup_dir/database.dump" > "$backup_dir/database.dump.sha256"
echo "Preview database archive validated: $backup_dir"
REMOTE
