#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="${TARGET_HOST:?Set TARGET_HOST, for example root@1.2.3.4}"
TARGET_DIR="${TARGET_DIR:-/opt/strategyos}"
SOURCE_DATASET="${SOURCE_DATASET:?Set SOURCE_DATASET to the local 01_Synthetic_Dataset folder}"
SSH_OPTS="${SSH_OPTS:-}"

if [ ! -d "${SOURCE_DATASET}" ]; then
  echo "SOURCE_DATASET does not exist: ${SOURCE_DATASET}"
  exit 1
fi

tar -C "${SOURCE_DATASET}" -czf - . | ssh ${SSH_OPTS} "${TARGET_HOST}" "cd '${TARGET_DIR}/app' && docker compose -f deploy/docker-compose.yml --env-file deploy/.env --env-file deploy/.env.secrets run --rm -T --volume strategyos_strategyos-workspace:/workspace alpine sh -c 'mkdir -p /workspace/source_dataset && rm -rf /workspace/source_dataset/* && tar -xzf - -C /workspace/source_dataset'"

echo "Source dataset synced into strategyos_strategyos-workspace:/source_dataset on ${TARGET_HOST}."
