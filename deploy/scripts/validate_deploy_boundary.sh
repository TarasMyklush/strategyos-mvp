#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-deploy/.env}"
SECRETS_FILE="${SECRETS_FILE:-deploy/.env.secrets}"
TARGET_ENVIRONMENT="${TARGET_ENVIRONMENT:-}"
TARGET_PUBLIC_URL="${TARGET_PUBLIC_URL:-${STRATEGYOS_PUBLIC_URL:-}}"
TARGET_DEPLOY_USER="${TARGET_DEPLOY_USER:-${HETZNER_USER:-}}"
export ENV_FILE
export SECRETS_FILE
export TARGET_ENVIRONMENT
export TARGET_PUBLIC_URL
export TARGET_DEPLOY_USER

python3 - <<'PY'
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse


def load_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SystemExit(f"Missing required env file: {path}")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


env_file = Path(os.environ["ENV_FILE"])
secrets_file = Path(os.environ["SECRETS_FILE"])
target_environment = os.environ.get("TARGET_ENVIRONMENT", "").strip().lower()
target_public_url = os.environ.get("TARGET_PUBLIC_URL", "").strip()
target_deploy_user = os.environ.get("TARGET_DEPLOY_USER", "").strip()

config = load_env(env_file)
secrets = load_env(secrets_file)
merged = {**config, **secrets}

errors: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def bool_is_true(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def looks_local(url: str | None) -> bool:
    value = str(url or "").strip().lower()
    return any(host in value for host in ("localhost", "127.0.0.1", "0.0.0.0", "strategyos-idp:9000"))


def looks_local_label(value: str | None) -> bool:
    normalized = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    if not normalized:
        return True
    return any(marker in normalized for marker in ("local", "broader testing", "broader-testing"))


def looks_local_identity(value: str | None) -> bool:
    normalized = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    if not normalized:
        return True
    return any(marker in normalized for marker in ("local", "localhost", ".local", "local poc"))


def normalized_csv(value: str | None) -> set[str]:
    normalized: set[str] = set()
    for item in str(value or "").split(","):
        candidate = item.strip().lower().replace("-", "_").replace(" ", "_")
        if candidate:
            normalized.add(candidate)
    return normalized


required_secret_keys = [
    "POSTGRES_PASSWORD",
    "NEO4J_PASSWORD",
    "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY",
    "MINIO_ROOT_PASSWORD",
    "STRATEGYOS_IDP_CLIENT_SECRET",
    "STRATEGYOS_IDP_OPERATOR_PASSWORD",
    "STRATEGYOS_IDP_REVIEWER_PASSWORD",
    "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEY",
]

for key in required_secret_keys:
    value = secrets.get(key, "")
    require(bool(value), f"{key} must be populated in {secrets_file}.")
    require("__CHANGE_ME_" not in value, f"{key} still contains a placeholder value.")

secret_only_keys = set(
    required_secret_keys
    + [
        "STRATEGYOS_LLM_API_KEY",
        "HATCHET_CLIENT_TOKEN",
        "HATCHET_POSTGRES_PASSWORD",
        "STRATEGYOS_TRUSTED_PROXY_AUTH_SECRET",
        "OAUTH2_PROXY_CLIENT_SECRET",
        "OAUTH2_PROXY_COOKIE_SECRET",
    ]
)
for key in secret_only_keys:
    require(key not in config, f"{key} must not be committed or rendered into {env_file}; keep it in {secrets_file}.")


auth_mode = str(merged.get("STRATEGYOS_AUTH_MODE", "") or "").strip().lower()
if auth_mode not in {"", "api_key", "identity_provider", "proxy_oidc", "disabled"}:
    require(False, "STRATEGYOS_AUTH_MODE must be one of api_key, identity_provider, proxy_oidc, or disabled.")
resolved_auth_mode = auth_mode or (
    "identity_provider"
    if bool_is_true(merged.get("STRATEGYOS_IDP_ENABLED"))
    else "api_key"
)

require(bool_is_true(merged.get("STRATEGYOS_API_AUTH_ENABLED")), "STRATEGYOS_API_AUTH_ENABLED must remain true for deployable environments.")
require(bool_is_true(merged.get("STRATEGYOS_REQUIRE_HUMAN_REVIEW")), "STRATEGYOS_REQUIRE_HUMAN_REVIEW must remain true for deployable environments.")
require(not bool_is_true(merged.get("STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED")), "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED=true is local-only and must not be deployed externally.")
if target_environment == "hetzner-branch":
    require(bool_is_true(merged.get("STRATEGYOS_LOGIN_REQUIRED")), "Branch preview must require login before serving application surfaces.")

run_execution_mode = str(merged.get("STRATEGYOS_RUN_EXECUTION_MODE", "sync") or "sync").strip().lower()
if run_execution_mode == "hatchet":
    hatchet_password = secrets.get("HATCHET_POSTGRES_PASSWORD", "")
    require(bool(hatchet_password), "HATCHET_POSTGRES_PASSWORD must be populated in hatchet execution mode.")
    require("__CHANGE_ME_" not in hatchet_password, "HATCHET_POSTGRES_PASSWORD still contains a placeholder value.")
    hatchet_token = secrets.get("HATCHET_CLIENT_TOKEN", "")
    require(bool(str(hatchet_token).strip()), "HATCHET_CLIENT_TOKEN must be populated in deploy secrets when STRATEGYOS_RUN_EXECUTION_MODE=hatchet.")
    require("__CHANGE_ME_" not in hatchet_token, "HATCHET_CLIENT_TOKEN still contains a placeholder value.")
    for key in (
        "HATCHET_SERVER_AUTH_COOKIE_SECRETS",
        "HATCHET_SERVER_ENCRYPTION_MASTER_KEYSET",
        "HATCHET_SERVER_ENCRYPTION_JWT_PRIVATE_KEYSET",
        "HATCHET_SERVER_ENCRYPTION_JWT_PUBLIC_KEYSET",
    ):
        value = str(secrets.get(key, "") or "").strip()
        require(bool(value), f"{key} must be populated in deploy secrets when STRATEGYOS_RUN_EXECUTION_MODE=hatchet.")
        require("__CHANGE_ME_" not in value, f"{key} still contains a placeholder value.")

model_provider_enabled = bool_is_true(merged.get("STRATEGYOS_MODEL_PROVIDER_ENABLED"))
llm_chat_enabled = bool_is_true(merged.get("STRATEGYOS_LLM_CHAT_ENABLED"))
approved_external_modes = normalized_csv(merged.get("STRATEGYOS_APPROVED_EXTERNAL_MODES"))
run_policy = str(merged.get("STRATEGYOS_RUN_POLICY", "sovereign") or "sovereign").strip().lower()
if model_provider_enabled or llm_chat_enabled:
    require(run_policy == "external-approved", "Model-provider features require STRATEGYOS_RUN_POLICY=external-approved.")
    require("model_provider_use" in approved_external_modes, "Model-provider features require STRATEGYOS_APPROVED_EXTERNAL_MODES to include model_provider_use.")
    llm_api_key = secrets.get("STRATEGYOS_LLM_API_KEY", "")
    require(bool(llm_api_key), "STRATEGYOS_LLM_API_KEY must be populated in deploy secrets when LLM chat/provider access is enabled.")

if resolved_auth_mode == "proxy_oidc":
    require(bool_is_true(merged.get("STRATEGYOS_TRUST_PROXY_AUTH")), "proxy_oidc requires STRATEGYOS_TRUST_PROXY_AUTH=true.")
    require(bool(str(merged.get("STRATEGYOS_OPERATOR_EMAILS", "")).strip()), "proxy_oidc requires STRATEGYOS_OPERATOR_EMAILS.")
    require(bool(str(merged.get("STRATEGYOS_REVIEWER_EMAILS", "")).strip()), "proxy_oidc requires STRATEGYOS_REVIEWER_EMAILS.")
    require(bool(str(merged.get("OAUTH2_PROXY_OIDC_ISSUER_URL", "")).strip()), "proxy_oidc requires OAUTH2_PROXY_OIDC_ISSUER_URL.")
    require(bool(str(merged.get("OAUTH2_PROXY_CLIENT_ID", "")).strip()), "proxy_oidc requires OAUTH2_PROXY_CLIENT_ID.")
    require(bool(str(merged.get("OAUTH2_PROXY_REDIRECT_URL", "")).strip()), "proxy_oidc requires OAUTH2_PROXY_REDIRECT_URL.")
    proxy_auth_secret = secrets.get("STRATEGYOS_TRUSTED_PROXY_AUTH_SECRET", "")
    proxy_client_secret = secrets.get("OAUTH2_PROXY_CLIENT_SECRET", "")
    proxy_cookie_secret = secrets.get("OAUTH2_PROXY_COOKIE_SECRET", "")
    require(bool(proxy_auth_secret), "proxy_oidc requires STRATEGYOS_TRUSTED_PROXY_AUTH_SECRET in deploy secrets.")
    require(bool(proxy_client_secret), "proxy_oidc requires OAUTH2_PROXY_CLIENT_SECRET in deploy secrets.")
    require(bool(proxy_cookie_secret), "proxy_oidc requires OAUTH2_PROXY_COOKIE_SECRET in deploy secrets.")
    require("__CHANGE_ME_" not in proxy_auth_secret, "STRATEGYOS_TRUSTED_PROXY_AUTH_SECRET still contains a placeholder value.")
    require("__CHANGE_ME_" not in proxy_client_secret, "OAUTH2_PROXY_CLIENT_SECRET still contains a placeholder value.")
    require("__CHANGE_ME_" not in proxy_cookie_secret, "OAUTH2_PROXY_COOKIE_SECRET still contains a placeholder value.")

if target_public_url and not looks_local(target_public_url):
    require(
        not looks_local_label(merged.get("STRATEGYOS_ENVIRONMENT_LABEL")),
        "Hosted deploys must not use a local-looking STRATEGYOS_ENVIRONMENT_LABEL.",
    )
    require(
        not looks_local(merged.get("STRATEGYOS_IDP_ISSUER")),
        "Hosted deploys must not use a localhost/local-container identity issuer.",
    )
    require(
        not looks_local_identity(merged.get("STRATEGYOS_TENANT_SLUG")),
        "Hosted deploys must not use a local-looking STRATEGYOS_TENANT_SLUG.",
    )
    require(
        not looks_local_identity(merged.get("STRATEGYOS_TENANT_NAME")),
        "Hosted deploys must not use a local-looking STRATEGYOS_TENANT_NAME.",
    )
    if resolved_auth_mode == "identity_provider":
        require(
            not looks_local_identity(merged.get("STRATEGYOS_IDP_OPERATOR_USERNAME")),
            "Hosted identity-provider deploys must not use a local-looking STRATEGYOS_IDP_OPERATOR_USERNAME.",
        )
        require(
            not looks_local_identity(merged.get("STRATEGYOS_IDP_REVIEWER_USERNAME")),
            "Hosted identity-provider deploys must not use a local-looking STRATEGYOS_IDP_REVIEWER_USERNAME.",
        )

if target_environment == "production":
    require(target_public_url.startswith("https://"), "Production deploys require STRATEGYOS_PUBLIC_URL to use https://.")
    require((merged.get("STRATEGYOS_SITE_ADDRESS") or "").strip() not in {"", ":80"}, "Production deploys require a real STRATEGYOS_SITE_ADDRESS domain/TLS address, not :80.")
    require(not bool_is_true(merged.get("STRATEGYOS_PUBLIC_HEALTH_ENABLED")), "Production deploys must keep STRATEGYOS_PUBLIC_HEALTH_ENABLED=false.")
    require(resolved_auth_mode != "api_key", "Production deploys must not use api_key auth mode for human access.")
    if resolved_auth_mode == "identity_provider":
        require(bool_is_true(merged.get("STRATEGYOS_IDP_ENABLED")), "Production identity_provider auth requires STRATEGYOS_IDP_ENABLED=true.")
        require(str(merged.get("STRATEGYOS_IDP_ISSUER", "")).strip().startswith("https://"), "Production deploys require the identity issuer to use https://.")
    if resolved_auth_mode == "proxy_oidc":
        require(not looks_local(merged.get("OAUTH2_PROXY_OIDC_ISSUER_URL")), "Production proxy_oidc deploys must not use a localhost/local-container OIDC issuer.")
        require(str(merged.get("OAUTH2_PROXY_OIDC_ISSUER_URL", "")).strip().startswith("https://"), "Production proxy_oidc deploys require the OIDC issuer to use https://.")
        require(str(merged.get("OAUTH2_PROXY_REDIRECT_URL", "")).strip().startswith("https://"), "Production proxy_oidc deploys require the redirect URL to use https://.")
    require(target_deploy_user not in {"", "root"}, "Production deploys must use a dedicated non-root deploy user.")
    target_host = urlparse(target_public_url).hostname or ""
    site_address = str(merged.get("STRATEGYOS_SITE_ADDRESS") or "").strip()
    if target_host and site_address and "://" not in site_address and not site_address.startswith(":"):
        site_hosts = {part.strip().split(":", 1)[0].lower() for part in site_address.split(",") if part.strip()}
        require(target_host.lower() in site_hosts, "Production deploys require STRATEGYOS_SITE_ADDRESS to cover the STRATEGYOS_PUBLIC_URL host.")
    redirect_host = urlparse(str(merged.get("OAUTH2_PROXY_REDIRECT_URL", ""))).hostname or ""
    if resolved_auth_mode == "proxy_oidc" and target_host and redirect_host:
        require(redirect_host.lower() == target_host.lower(), "Production proxy_oidc deploys require OAUTH2_PROXY_REDIRECT_URL to use the STRATEGYOS_PUBLIC_URL host.")

if errors:
    for message in errors:
        print(f"BOUNDARY VALIDATION FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)

print("Deploy boundary validation passed.")
PY
