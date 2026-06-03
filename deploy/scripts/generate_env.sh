#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-deploy/.env}"
EXAMPLE_FILE="${EXAMPLE_FILE:-deploy/.env.example}"

if [ -f "${ENV_FILE}" ]; then
  echo "${ENV_FILE} already exists; refusing to overwrite."
  exit 1
fi

cp "${EXAMPLE_FILE}" "${ENV_FILE}"

replace_value() {
  local key="$1"
  local value="$2"
  sed -i.bak "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
}

neo4j_password="$(openssl rand -hex 24)"
object_password="$(openssl rand -hex 24)"
replace_value "NEO4J_PASSWORD" "${neo4j_password}"
replace_value "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY" "${object_password}"
replace_value "MINIO_ROOT_PASSWORD" "${object_password}"

rm -f "${ENV_FILE}.bak"
echo "Created ${ENV_FILE}. Review domains, object-store settings, and passwords before deployment."
