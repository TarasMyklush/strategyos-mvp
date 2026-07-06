from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE_ROOT = PACKAGE_ROOT.parent


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in {None, ""} else default


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_csv(name: str) -> tuple[str, ...]:
    value = env(name)
    if value is None:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def env_key_value_map(name: str, default: dict[str, str] | None = None) -> dict[str, str]:
    value = env(name)
    if value is None:
        return dict(default or {})
    pairs: dict[str, str] = {}
    for item in value.split(","):
        chunk = item.strip()
        if not chunk:
            continue
        if "=" in chunk:
            key, secret = chunk.split("=", 1)
        elif ":" in chunk:
            key, secret = chunk.split(":", 1)
        else:
            continue
        key = key.strip()
        secret = secret.strip()
        if key and secret:
            pairs[key] = secret
    return pairs or dict(default or {})


def env_path(name: str, default: Path) -> Path:
    return Path(env(name, str(default))).expanduser().resolve()


def _source_pack_raw_candidates(workspace_root: Path) -> list[Path]:
    source_pack_root = (workspace_root / "outputs" / "source_packs").expanduser().resolve()
    if not source_pack_root.exists():
        return []
    candidates = [path for path in source_pack_root.glob("*/raw") if path.is_dir()]
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)


def _resolved_repo_fixture_dataset_root(dataset_root: Path) -> Path:
    if not dataset_root.exists() or not dataset_root.is_dir():
        return dataset_root

    symlinked_dirs = [
        child for child in dataset_root.iterdir() if child.is_dir() and child.is_symlink()
    ]
    if not symlinked_dirs:
        return dataset_root

    resolved_roots = {child.resolve().parent for child in symlinked_dirs}
    if len(resolved_roots) != 1:
        return dataset_root

    resolved_root = next(iter(resolved_roots))
    return resolved_root if resolved_root.is_dir() else dataset_root


def default_source_dataset_path(
    workspace_root: Path,
    poc_root: Path,
    *,
    package_root: Path = PACKAGE_ROOT,
) -> Path:
    configured_default = (poc_root / "01_Synthetic_Dataset").expanduser().resolve()
    if configured_default.exists():
        return configured_default

    repo_fixture = (package_root / ".fixtures" / "01_Synthetic_Dataset").expanduser().resolve()
    if repo_fixture.exists():
        return _resolved_repo_fixture_dataset_root(repo_fixture)

    for candidate in _source_pack_raw_candidates(workspace_root):
        if (candidate / "02_ERP_Extracts" / "AP_Invoices_H1_2026.xlsx").exists() and (
            candidate / "04_Contracts"
        ).exists():
            return candidate

    return configured_default


@dataclass(frozen=True)
class ObjectStoreConfig:
    bucket: str | None
    endpoint_url: str | None
    region: str
    access_key_id: str | None
    secret_access_key: str | None
    prefix: str
    force_path_style: bool

    @property
    def enabled(self) -> bool:
        return bool(self.bucket and self.endpoint_url)


EXTERNAL_MODE_OBJECT_STORAGE_SYNC = "object_storage_sync"
EXTERNAL_MODE_MODEL_PROVIDER = "model_provider_use"
EXTERNAL_MODE_BATCH_APIS = "batch_apis"
EXTERNAL_MODE_HOSTED_OCR_VISION = "hosted_ocr_vision"
EXTERNAL_MODE_NAMES = (
    EXTERNAL_MODE_OBJECT_STORAGE_SYNC,
    EXTERNAL_MODE_MODEL_PROVIDER,
    EXTERNAL_MODE_BATCH_APIS,
    EXTERNAL_MODE_HOSTED_OCR_VISION,
)


@dataclass(frozen=True)
class RunPolicyConfig:
    mode: str
    approved_external_modes: tuple[str, ...]

    def allows(self, external_mode: str) -> bool:
        return self.mode == "external-approved" and external_mode in self.approved_external_modes


@dataclass(frozen=True)
class StrategyOSConfig:
    tenant_slug: str
    tenant_name: str
    company_slug: str
    company_name: str
    portfolio_slug: str
    portfolio_name: str
    company_options: dict[str, str]
    portfolio_options: dict[str, str]
    environment_label: str
    source_system_name: str
    workspace_root: Path
    poc_root: Path
    source_dataset: Path
    output_root: Path
    default_run_dir: Path
    agent_input_dir: Path
    evaluation_dir: Path
    object_store: ObjectStoreConfig
    database_url: str | None
    redis_url: str | None
    neo4j_uri: str | None
    neo4j_user: str | None
    neo4j_password: str | None
    qdrant_url: str | None
    auth_mode: str
    api_auth_enabled: bool
    demo_role_login_enabled: bool
    idp_enabled: bool
    idp_issuer: str | None
    idp_token_url: str | None
    idp_introspection_url: str | None
    idp_client_id: str | None
    idp_client_secret: str | None
    idp_operator_username: str | None
    idp_operator_password: str | None
    idp_reviewer_username: str | None
    idp_reviewer_password: str | None
    idp_test_users: dict[str, str]
    idp_token_ttl_seconds: int
    bu_api_keys: tuple[str, ...]
    tenant_operator_api_keys: tuple[str, ...]
    tenant_admin_api_keys: tuple[str, ...]
    system_api_keys: tuple[str, ...]
    reviewer_api_keys: tuple[str, ...]
    operator_api_keys: tuple[str, ...]
    trust_proxy_auth: bool
    trusted_proxy_auth_secret: str | None
    bu_emails: tuple[str, ...]
    tenant_operator_emails: tuple[str, ...]
    tenant_admin_emails: tuple[str, ...]
    system_emails: tuple[str, ...]
    reviewer_emails: tuple[str, ...]
    operator_emails: tuple[str, ...]
    oidc_issuer_url: str | None
    oidc_client_id: str | None
    oidc_redirect_url: str | None
    sensitive_identifier_active_key_id: str
    sensitive_identifier_hmac_keys: dict[str, str]
    public_health_enabled: bool
    require_human_review: bool
    oracle_pilot_enabled: bool
    oracle_pilot_ceo_surface_enabled: bool
    oracle_pilot_cfo_surface_enabled: bool
    oracle_pilot_rollback_ready: bool
    twins_enabled: bool
    twins_mutations_enabled: bool
    twins_scheduler_enabled: bool
    twins_expose_reasoning_diagnostics: bool
    ocr_engine: str
    runtime_dep_ca_certificates_version: str
    runtime_dep_curl_version: str
    runtime_dep_poppler_utils_version: str
    runtime_dep_tesseract_version: str
    runtime_dep_tesseract_eng_version: str
    runtime_backend: str
    run_execution_mode: str
    hatchet_client_token: str | None
    hatchet_client_tls_strategy: str | None
    hatchet_worker_name: str
    hatchet_worker_slots: int
    hatchet_dashboard_url: str | None
    plugin_modules: tuple[str, ...]
    plugin_failure_mode: str
    run_policy: RunPolicyConfig
    sync_artifacts: bool
    sync_source_files: bool
    model_provider_enabled: bool
    llm_chat_enabled: bool
    llm_provider: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str | None
    llm_timeout_seconds: int
    llm_retry_attempts: int
    llm_retry_backoff_ms: int
    vector_routing_enabled: bool
    batch_apis_enabled: bool
    hosted_ocr_vision_enabled: bool
    source_pack_structured_candidate_threshold: float
    source_pack_document_indicator_threshold: int
    acceptance_generic_citation_resolution_min_rate: float
    finance_usd_rate: float
    finance_fx_hedge_default_rate: float
    finance_off_contract_min_invoices: int
    finance_off_contract_single_approver_ratio: float
    finance_price_variance_min_excess_sar: float
    finance_early_pay_discount_window_days: int
    finance_early_pay_discount_rate: float
    finance_working_capital_min_weekly_invoice_count: int
    finance_working_capital_min_weekly_amount_sar: float
    finance_working_capital_max_driver_concentration: float
    finance_working_capital_min_consecutive_drift_weeks: int
    finance_working_capital_min_drift_days: float


def env_float(name: str, default: float) -> float:
    value = env(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _runtime_backend() -> str:
    backend = (env("STRATEGYOS_RUNTIME_BACKEND", "local") or "local").strip().lower()
    if backend in {"local", "langgraph", "auto"}:
        return backend
    return "local"


def _run_execution_mode() -> str:
    mode = (
        env("STRATEGYOS_RUN_EXECUTION_MODE", "sync") or "sync"
    ).strip().lower()
    if mode in {"sync", "hatchet"}:
        return mode
    return "sync"


def _plugin_failure_mode() -> str:
    mode = (
        env("STRATEGYOS_PLUGIN_FAILURE_MODE", "strict") or "strict"
    ).strip().lower()
    if mode in {"strict", "permissive"}:
        return mode
    return "strict"


def _run_policy_mode() -> str:
    mode = (env("STRATEGYOS_RUN_POLICY", "sovereign") or "sovereign").strip().lower()
    if mode in {"sovereign", "external-approved"}:
        return mode
    return "sovereign"


def _auth_mode() -> str:
    explicit = (env("STRATEGYOS_AUTH_MODE") or "").strip().lower()
    if explicit in {"api_key", "identity_provider", "proxy_oidc", "disabled"}:
        return explicit
    if env_bool("STRATEGYOS_IDP_ENABLED", False):
        return "identity_provider"
    if env_bool("STRATEGYOS_API_AUTH_ENABLED", False):
        return "api_key"
    return "disabled"


def _approved_external_modes() -> tuple[str, ...]:
    normalized: list[str] = []
    for item in env_csv("STRATEGYOS_APPROVED_EXTERNAL_MODES"):
        candidate = item.strip().lower().replace("-", "_").replace(" ", "_")
        if candidate in EXTERNAL_MODE_NAMES and candidate not in normalized:
            normalized.append(candidate)
    return tuple(normalized)


def load_config() -> StrategyOSConfig:
    workspace_root = env_path("STRATEGYOS_WORKSPACE_ROOT", DEFAULT_WORKSPACE_ROOT)
    poc_root = env_path(
        "STRATEGYOS_POC_ROOT", workspace_root / "strategy os" / "StrategyOS POC"
    )
    output_root = env_path("STRATEGYOS_OUTPUT_ROOT", workspace_root / "outputs")
    default_sensitive_key_id = "local-v1"
    default_sensitive_keys = {
        default_sensitive_key_id: env(
            "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEY",
            "strategyos-local-dev-sensitive-id-key",
        )
        or "strategyos-local-dev-sensitive-id-key"
    }
    sensitive_identifier_hmac_keys = env_key_value_map(
        "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEYS",
        default_sensitive_keys,
    )
    sensitive_identifier_active_key_id = (
        env("STRATEGYOS_SENSITIVE_IDENTIFIER_ACTIVE_KEY_ID")
        or next(iter(sensitive_identifier_hmac_keys.keys()), default_sensitive_key_id)
    )
    if sensitive_identifier_active_key_id not in sensitive_identifier_hmac_keys:
        sensitive_identifier_active_key_id = next(
            iter(sensitive_identifier_hmac_keys.keys()),
            default_sensitive_key_id,
        )
    llm_provider = (env("STRATEGYOS_LLM_PROVIDER", "deepseek") or "deepseek").strip()
    llm_base_url = (
        env("STRATEGYOS_LLM_BASE_URL", "https://api.deepseek.com")
        or "https://api.deepseek.com"
    ).strip()
    llm_model = (
        env("STRATEGYOS_LLM_MODEL", "deepseek-v4-pro") or "deepseek-v4-pro"
    ).strip()
    llm_api_key = env("STRATEGYOS_LLM_API_KEY")
    normalized_provider = llm_provider.lower()
    normalized_base_url = llm_base_url.lower()
    if not llm_api_key and (
        normalized_provider == "deepseek" or "api.deepseek.com" in normalized_base_url
    ):
        llm_api_key = env("DEEPSEEK_API_KEY")
    if not llm_api_key and (
        normalized_provider == "openai" or "api.openai.com" in normalized_base_url
    ):
        llm_api_key = env("OPENAI_API_KEY")
    return StrategyOSConfig(
        tenant_slug=env("STRATEGYOS_TENANT_SLUG", "local-poc") or "local-poc",
        tenant_name=env("STRATEGYOS_TENANT_NAME", "StrategyOS Local POC")
        or "StrategyOS Local POC",
        company_slug=env("STRATEGYOS_COMPANY_SLUG", env("STRATEGYOS_TENANT_SLUG", "local-poc"))
        or "local-poc",
        company_name=env("STRATEGYOS_COMPANY_NAME", env("STRATEGYOS_TENANT_NAME", "StrategyOS Local POC"))
        or "StrategyOS Local POC",
        portfolio_slug=env("STRATEGYOS_PORTFOLIO_SLUG", "finance-diagnostics")
        or "finance-diagnostics",
        portfolio_name=env("STRATEGYOS_PORTFOLIO_NAME", "Finance diagnostics")
        or "Finance diagnostics",
        company_options=env_key_value_map(
            "STRATEGYOS_COMPANY_OPTIONS",
            {
                env("STRATEGYOS_COMPANY_SLUG", env("STRATEGYOS_TENANT_SLUG", "local-poc"))
                or "local-poc": env(
                    "STRATEGYOS_COMPANY_NAME",
                    env("STRATEGYOS_TENANT_NAME", "StrategyOS Local POC"),
                )
                or "StrategyOS Local POC",
            },
        ),
        portfolio_options=env_key_value_map(
            "STRATEGYOS_PORTFOLIO_OPTIONS",
            {
                env("STRATEGYOS_PORTFOLIO_SLUG", "finance-diagnostics")
                or "finance-diagnostics": env(
                    "STRATEGYOS_PORTFOLIO_NAME", "Finance diagnostics"
                )
                or "Finance diagnostics",
                "evidence-governance": "Evidence governance",
                "release-readiness": "Release readiness",
                "runtime-governance": "Runtime governance",
            },
        ),
        environment_label=env("STRATEGYOS_ENVIRONMENT_LABEL", "Local development")
        or "Local development",
        source_system_name=env(
            "STRATEGYOS_SOURCE_SYSTEM_NAME", "Synthetic Finance Dataset"
        )
        or "Synthetic Finance Dataset",
        workspace_root=workspace_root,
        poc_root=poc_root,
        source_dataset=env_path(
            "STRATEGYOS_SOURCE_DATASET",
            default_source_dataset_path(workspace_root, poc_root),
        ),
        output_root=output_root,
        default_run_dir=env_path(
            "STRATEGYOS_RUN_DIR", output_root / "StrategyOS MVP Run"
        ),
        agent_input_dir=env_path(
            "STRATEGYOS_AGENT_INPUT_DIR", output_root / "StrategyOS Agent Input"
        ),
        evaluation_dir=env_path(
            "STRATEGYOS_EVALUATION_DIR", output_root / "StrategyOS Evaluation"
        ),
        object_store=ObjectStoreConfig(
            bucket=env("STRATEGYOS_OBJECT_BUCKET"),
            endpoint_url=env("STRATEGYOS_OBJECT_ENDPOINT"),
            region=env("STRATEGYOS_OBJECT_REGION", "us-east-1") or "us-east-1",
            access_key_id=env("STRATEGYOS_OBJECT_ACCESS_KEY_ID"),
            secret_access_key=env("STRATEGYOS_OBJECT_SECRET_ACCESS_KEY"),
            prefix=(
                env("STRATEGYOS_OBJECT_PREFIX", "strategyos") or "strategyos"
            ).strip("/"),
            force_path_style=env_bool("STRATEGYOS_OBJECT_FORCE_PATH_STYLE", True),
        ),
        database_url=env("DATABASE_URL") or env("STRATEGYOS_DATABASE_URL"),
        redis_url=env("REDIS_URL") or env("STRATEGYOS_REDIS_URL"),
        neo4j_uri=env("NEO4J_URI") or env("STRATEGYOS_NEO4J_URI"),
        neo4j_user=env("NEO4J_USER") or env("STRATEGYOS_NEO4J_USER"),
        neo4j_password=env("NEO4J_PASSWORD") or env("STRATEGYOS_NEO4J_PASSWORD"),
        qdrant_url=env("QDRANT_URL") or env("STRATEGYOS_QDRANT_URL"),
        auth_mode=_auth_mode(),
        api_auth_enabled=env_bool("STRATEGYOS_API_AUTH_ENABLED", False),
        demo_role_login_enabled=env_bool("STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED", False),
        idp_enabled=env_bool("STRATEGYOS_IDP_ENABLED", False),
        idp_issuer=env("STRATEGYOS_IDP_ISSUER"),
        idp_token_url=env("STRATEGYOS_IDP_TOKEN_URL"),
        idp_introspection_url=env("STRATEGYOS_IDP_INTROSPECTION_URL"),
        idp_client_id=env("STRATEGYOS_IDP_CLIENT_ID"),
        idp_client_secret=env("STRATEGYOS_IDP_CLIENT_SECRET"),
        idp_operator_username=env("STRATEGYOS_IDP_OPERATOR_USERNAME"),
        idp_operator_password=env("STRATEGYOS_IDP_OPERATOR_PASSWORD"),
        idp_reviewer_username=env("STRATEGYOS_IDP_REVIEWER_USERNAME"),
        idp_reviewer_password=env("STRATEGYOS_IDP_REVIEWER_PASSWORD"),
        idp_test_users=env_key_value_map("STRATEGYOS_IDP_TEST_USERS"),
        idp_token_ttl_seconds=env_int("STRATEGYOS_IDP_TOKEN_TTL_SECONDS", 3600),
        bu_api_keys=env_csv("STRATEGYOS_BU_API_KEYS"),
        tenant_operator_api_keys=env_csv("STRATEGYOS_TENANT_OPERATOR_API_KEYS"),
        tenant_admin_api_keys=env_csv("STRATEGYOS_TENANT_ADMIN_API_KEYS"),
        system_api_keys=env_csv("STRATEGYOS_SYSTEM_API_KEYS"),
        reviewer_api_keys=env_csv("STRATEGYOS_REVIEWER_API_KEYS"),
        operator_api_keys=env_csv("STRATEGYOS_OPERATOR_API_KEYS"),
        trust_proxy_auth=env_bool("STRATEGYOS_TRUST_PROXY_AUTH", False),
        trusted_proxy_auth_secret=env("STRATEGYOS_TRUSTED_PROXY_AUTH_SECRET"),
        bu_emails=env_csv("STRATEGYOS_BU_EMAILS"),
        tenant_operator_emails=env_csv("STRATEGYOS_TENANT_OPERATOR_EMAILS"),
        tenant_admin_emails=env_csv("STRATEGYOS_TENANT_ADMIN_EMAILS"),
        system_emails=env_csv("STRATEGYOS_SYSTEM_EMAILS"),
        reviewer_emails=env_csv("STRATEGYOS_REVIEWER_EMAILS"),
        operator_emails=env_csv("STRATEGYOS_OPERATOR_EMAILS"),
        oidc_issuer_url=env("OAUTH2_PROXY_OIDC_ISSUER_URL"),
        oidc_client_id=env("OAUTH2_PROXY_CLIENT_ID"),
        oidc_redirect_url=env("OAUTH2_PROXY_REDIRECT_URL"),
        sensitive_identifier_active_key_id=sensitive_identifier_active_key_id,
        sensitive_identifier_hmac_keys=sensitive_identifier_hmac_keys,
        public_health_enabled=env_bool("STRATEGYOS_PUBLIC_HEALTH_ENABLED", False),
        require_human_review=env_bool("STRATEGYOS_REQUIRE_HUMAN_REVIEW", True),
        oracle_pilot_enabled=env_bool("STRATEGYOS_ORACLE_PILOT_ENABLED", False),
        oracle_pilot_ceo_surface_enabled=env_bool(
            "STRATEGYOS_ORACLE_PILOT_CEO_SURFACE_ENABLED", False
        ),
        oracle_pilot_cfo_surface_enabled=env_bool(
            "STRATEGYOS_ORACLE_PILOT_CFO_SURFACE_ENABLED", False
        ),
        oracle_pilot_rollback_ready=env_bool(
            "STRATEGYOS_ORACLE_PILOT_ROLLBACK_READY", False
        ),
        twins_enabled=env_bool("STRATEGYOS_TWINS_ENABLED", True),
        twins_mutations_enabled=env_bool("STRATEGYOS_TWINS_MUTATIONS_ENABLED", True),
        twins_scheduler_enabled=env_bool("STRATEGYOS_TWINS_SCHEDULER_ENABLED", True),
        twins_expose_reasoning_diagnostics=env_bool(
            "STRATEGYOS_TWINS_EXPOSE_REASONING_DIAGNOSTICS", False
        ),
        ocr_engine=(env("STRATEGYOS_OCR_ENGINE", "tesseract") or "tesseract").lower(),
        runtime_dep_ca_certificates_version=(
            env("STRATEGYOS_RUNTIME_DEP_CA_CERTIFICATES_VERSION", "20250419")
            or "20250419"
        ),
        runtime_dep_curl_version=(
            env("STRATEGYOS_RUNTIME_DEP_CURL_VERSION", "8.14.1-2+deb13u3")
            or "8.14.1-2+deb13u3"
        ),
        runtime_dep_poppler_utils_version=(
            env(
                "STRATEGYOS_RUNTIME_DEP_POPPLER_UTILS_VERSION",
                "25.03.0-5+deb13u3",
            )
            or "25.03.0-5+deb13u3"
        ),
        runtime_dep_tesseract_version=(
            env("STRATEGYOS_RUNTIME_DEP_TESSERACT_VERSION", "5.5.0-1+b1")
            or "5.5.0-1+b1"
        ),
        runtime_dep_tesseract_eng_version=(
            env("STRATEGYOS_RUNTIME_DEP_TESSERACT_ENG_VERSION", "1:4.1.0-2")
            or "1:4.1.0-2"
        ),
        runtime_backend=_runtime_backend(),
        run_execution_mode=_run_execution_mode(),
        hatchet_client_token=env("HATCHET_CLIENT_TOKEN")
        or env("STRATEGYOS_HATCHET_CLIENT_TOKEN"),
        hatchet_client_tls_strategy=env("HATCHET_CLIENT_TLS_STRATEGY")
        or env("STRATEGYOS_HATCHET_CLIENT_TLS_STRATEGY"),
        hatchet_worker_name=env(
            "STRATEGYOS_HATCHET_WORKER_NAME", "strategyos-worker"
        )
        or "strategyos-worker",
        hatchet_worker_slots=env_int("STRATEGYOS_HATCHET_WORKER_SLOTS", 1),
        hatchet_dashboard_url=env("STRATEGYOS_HATCHET_DASHBOARD_URL"),
        plugin_modules=env_csv("STRATEGYOS_PLUGIN_MODULES"),
        plugin_failure_mode=_plugin_failure_mode(),
        run_policy=RunPolicyConfig(
            mode=_run_policy_mode(),
            approved_external_modes=_approved_external_modes(),
        ),
        sync_artifacts=env_bool("STRATEGYOS_SYNC_ARTIFACTS", False),
        sync_source_files=env_bool("STRATEGYOS_SYNC_SOURCE_FILES", False),
        model_provider_enabled=env_bool("STRATEGYOS_MODEL_PROVIDER_ENABLED", False),
        llm_chat_enabled=env_bool("STRATEGYOS_LLM_CHAT_ENABLED", False),
        llm_provider=llm_provider,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        llm_timeout_seconds=env_int("STRATEGYOS_LLM_TIMEOUT_SECONDS", 30),
        llm_retry_attempts=env_int("STRATEGYOS_LLM_RETRY_ATTEMPTS", 3),
        llm_retry_backoff_ms=env_int("STRATEGYOS_LLM_RETRY_BACKOFF_MS", 250),
        vector_routing_enabled=env_bool("STRATEGYOS_VECTOR_ROUTING_ENABLED", False),
        batch_apis_enabled=env_bool("STRATEGYOS_BATCH_APIS_ENABLED", False),
        hosted_ocr_vision_enabled=env_bool("STRATEGYOS_HOSTED_OCR_VISION_ENABLED", False),
        source_pack_structured_candidate_threshold=env_float(
            "STRATEGYOS_SOURCE_PACK_STRUCTURED_CANDIDATE_THRESHOLD", 0.6
        ),
        source_pack_document_indicator_threshold=env_int(
            "STRATEGYOS_SOURCE_PACK_DOCUMENT_INDICATOR_THRESHOLD", 2
        ),
        acceptance_generic_citation_resolution_min_rate=env_float(
            "STRATEGYOS_ACCEPTANCE_GENERIC_CITATION_RESOLUTION_MIN_RATE", 0.9
        ),
        finance_usd_rate=env_float("STRATEGYOS_FINANCE_USD_RATE", 3.75),
        finance_fx_hedge_default_rate=env_float(
            "STRATEGYOS_FINANCE_FX_HEDGE_DEFAULT_RATE", 3.73
        ),
        finance_off_contract_min_invoices=env_int(
            "STRATEGYOS_FINANCE_OFF_CONTRACT_MIN_INVOICES", 5
        ),
        finance_off_contract_single_approver_ratio=env_float(
            "STRATEGYOS_FINANCE_OFF_CONTRACT_SINGLE_APPROVER_RATIO", 0.8
        ),
        finance_price_variance_min_excess_sar=env_float(
            "STRATEGYOS_FINANCE_PRICE_VARIANCE_MIN_EXCESS_SAR", 10_000.0
        ),
        finance_early_pay_discount_window_days=env_int(
            "STRATEGYOS_FINANCE_EARLY_PAY_DISCOUNT_WINDOW_DAYS", 10
        ),
        finance_early_pay_discount_rate=env_float(
            "STRATEGYOS_FINANCE_EARLY_PAY_DISCOUNT_RATE", 0.02
        ),
        finance_working_capital_min_weekly_invoice_count=env_int(
            "STRATEGYOS_FINANCE_WORKING_CAPITAL_MIN_WEEKLY_INVOICE_COUNT", 5
        ),
        finance_working_capital_min_weekly_amount_sar=env_float(
            "STRATEGYOS_FINANCE_WORKING_CAPITAL_MIN_WEEKLY_AMOUNT_SAR", 100_000.0
        ),
        finance_working_capital_max_driver_concentration=env_float(
            "STRATEGYOS_FINANCE_WORKING_CAPITAL_MAX_DRIVER_CONCENTRATION", 0.65
        ),
        finance_working_capital_min_consecutive_drift_weeks=env_int(
            "STRATEGYOS_FINANCE_WORKING_CAPITAL_MIN_CONSECUTIVE_DRIFT_WEEKS", 2
        ),
        finance_working_capital_min_drift_days=env_float(
            "STRATEGYOS_FINANCE_WORKING_CAPITAL_MIN_DRIFT_DAYS", 3.0
        ),
    )


CONFIG = load_config()
