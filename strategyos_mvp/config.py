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
    api_auth_enabled: bool
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
    idp_token_ttl_seconds: int
    reviewer_api_keys: tuple[str, ...]
    operator_api_keys: tuple[str, ...]
    sensitive_identifier_active_key_id: str
    sensitive_identifier_hmac_keys: dict[str, str]
    public_health_enabled: bool
    require_human_review: bool
    ocr_engine: str
    runtime_dep_ca_certificates_version: str
    runtime_dep_curl_version: str
    runtime_dep_poppler_utils_version: str
    runtime_dep_tesseract_version: str
    runtime_dep_tesseract_eng_version: str
    runtime_backend: str
    plugin_modules: tuple[str, ...]
    plugin_failure_mode: str
    run_policy: RunPolicyConfig
    sync_artifacts: bool
    sync_source_files: bool
    model_provider_enabled: bool
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
    return StrategyOSConfig(
        tenant_slug=env("STRATEGYOS_TENANT_SLUG", "local-poc") or "local-poc",
        tenant_name=env("STRATEGYOS_TENANT_NAME", "StrategyOS Local POC")
        or "StrategyOS Local POC",
        source_system_name=env(
            "STRATEGYOS_SOURCE_SYSTEM_NAME", "Synthetic Finance Dataset"
        )
        or "Synthetic Finance Dataset",
        workspace_root=workspace_root,
        poc_root=poc_root,
        source_dataset=env_path(
            "STRATEGYOS_SOURCE_DATASET", poc_root / "01_Synthetic_Dataset"
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
        api_auth_enabled=env_bool("STRATEGYOS_API_AUTH_ENABLED", False),
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
        idp_token_ttl_seconds=env_int("STRATEGYOS_IDP_TOKEN_TTL_SECONDS", 3600),
        reviewer_api_keys=env_csv("STRATEGYOS_REVIEWER_API_KEYS"),
        operator_api_keys=env_csv("STRATEGYOS_OPERATOR_API_KEYS"),
        sensitive_identifier_active_key_id=sensitive_identifier_active_key_id,
        sensitive_identifier_hmac_keys=sensitive_identifier_hmac_keys,
        public_health_enabled=env_bool("STRATEGYOS_PUBLIC_HEALTH_ENABLED", True),
        require_human_review=env_bool("STRATEGYOS_REQUIRE_HUMAN_REVIEW", True),
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
        plugin_modules=env_csv("STRATEGYOS_PLUGIN_MODULES"),
        plugin_failure_mode=_plugin_failure_mode(),
        run_policy=RunPolicyConfig(
            mode=_run_policy_mode(),
            approved_external_modes=_approved_external_modes(),
        ),
        sync_artifacts=env_bool("STRATEGYOS_SYNC_ARTIFACTS", False),
        sync_source_files=env_bool("STRATEGYOS_SYNC_SOURCE_FILES", False),
        model_provider_enabled=env_bool("STRATEGYOS_MODEL_PROVIDER_ENABLED", False),
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
