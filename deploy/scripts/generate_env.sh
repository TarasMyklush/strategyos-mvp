#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-deploy/.env}"
EXAMPLE_FILE="${EXAMPLE_FILE:-deploy/.env.example}"

if [ -f "${ENV_FILE}" ]; then
  echo "${ENV_FILE} already exists; refusing to overwrite."
  exit 1
fi

cp "${EXAMPLE_FILE}" "${ENV_FILE}"

replace_secret() {
  local key="$1"
  local value
  value="$(openssl rand -hex 24)"
  sed -i.bak "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
}

replace_secret "NEO4J_PASSWORD"
replace_secret "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY"
replace_secret "MINIO_ROOT_PASSWORD"

rm -f "${ENV_FILE}.bak"
echo "Created ${ENV_FILE}. Review domains, object-store settings, and passwords before deployment."
