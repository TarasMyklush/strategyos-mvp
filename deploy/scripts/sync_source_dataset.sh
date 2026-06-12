#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="${TARGET_HOST:?Set TARGET_HOST, for example root@1.2.3.4}"
TARGET_DIR="${TARGET_DIR:-/opt/strategyos}"
SOURCE_DATASET="${SOURCE_DATASET:?Set SOURCE_DATASET to the local 01_Synthetic_Dataset folder}"
SSH_OPTS="${SSH_OPTS:-}"
COMPOSE_FILES="${COMPOSE_FILES:-deploy/docker-compose.yml}"
WORKSPACE_VOLUME="${WORKSPACE_VOLUME:-strategyos_strategyos-workspace}"
ALPINE_IMAGE="${ALPINE_IMAGE:-alpine:3.20}"

COMPOSE_FILE_ARGS=""
for compose_file in ${COMPOSE_FILES}; do
  COMPOSE_FILE_ARGS="${COMPOSE_FILE_ARGS} -f ${compose_file}"
done

if [ ! -d "${SOURCE_DATASET}" ]; then
  echo "SOURCE_DATASET does not exist: ${SOURCE_DATASET}"
  exit 1
fi

tar -C "${SOURCE_DATASET}" -czf - . | ssh ${SSH_OPTS} "${TARGET_HOST}" "cd '${TARGET_DIR}/app' && docker run --rm -i --volume '${WORKSPACE_VOLUME}:/workspace' '${ALPINE_IMAGE}' sh -c 'mkdir -p /workspace/source_dataset && rm -rf /workspace/source_dataset/* && tar -xzf - -C /workspace/source_dataset'"

echo "Source dataset synced into ${WORKSPACE_VOLUME}:/source_dataset on ${TARGET_HOST}."
