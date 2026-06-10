#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-deploy/.env}"
SECRETS_FILE="${SECRETS_FILE:-deploy/.env.secrets}"
CONFIG_TEMPLATE="${CONFIG_TEMPLATE:-deploy/.env.example}"
SECRETS_TEMPLATE="${SECRETS_TEMPLATE:-deploy/.env.secrets.example}"

if [ -f "${ENV_FILE}" ]; then
  echo "${ENV_FILE} already exists; refusing to overwrite."
  exit 1
fi

if [ -f "${SECRETS_FILE}" ]; then
  echo "${SECRETS_FILE} already exists; refusing to overwrite."
  exit 1
fi

cp "${CONFIG_TEMPLATE}" "${ENV_FILE}"
cp "${SECRETS_TEMPLATE}" "${SECRETS_FILE}"

replace_value() {
  local target_file="$1"
  local key="$2"
  local value="$3"
  sed -i.bak "s|^${key}=.*|${key}=${value}|" "${target_file}"
}

generate_secret() {
  openssl rand -hex 24
}

postgres_password="$(generate_secret)"
neo4j_password="$(generate_secret)"
object_password="$(generate_secret)"
idp_client_secret="$(generate_secret)"
operator_password="$(generate_secret)"
reviewer_password="$(generate_secret)"
sensitive_identifier_hmac_key="$(generate_secret)"

replace_value "${SECRETS_FILE}" "POSTGRES_PASSWORD" "${postgres_password}"
replace_value "${SECRETS_FILE}" "NEO4J_PASSWORD" "${neo4j_password}"
replace_value "${SECRETS_FILE}" "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY" "${object_password}"
replace_value "${SECRETS_FILE}" "MINIO_ROOT_PASSWORD" "${object_password}"
replace_value "${SECRETS_FILE}" "STRATEGYOS_IDP_CLIENT_SECRET" "${idp_client_secret}"
replace_value "${SECRETS_FILE}" "STRATEGYOS_IDP_OPERATOR_PASSWORD" "${operator_password}"
replace_value "${SECRETS_FILE}" "STRATEGYOS_IDP_REVIEWER_PASSWORD" "${reviewer_password}"
replace_value "${SECRETS_FILE}" "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEY" "${sensitive_identifier_hmac_key}"

rm -f "${ENV_FILE}.bak" "${SECRETS_FILE}.bak"
echo "Created ${ENV_FILE} and ${SECRETS_FILE}. Review non-secret config separately from injected secrets before deployment."
