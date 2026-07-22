from pathlib import Path
import os
import tempfile

from strategyos_mvp.config import default_source_dataset_path, load_config
from strategyos_mvp.storage import object_store_status, sync_artifacts


def test_default_config_has_local_paths():
    config = load_config()
    assert config.workspace_root.exists()
    assert config.default_run_dir.name == "StrategyOS MVP Run"
    assert config.runtime_backend == "local"
    assert config.run_policy.mode == "sovereign"
    assert config.run_policy.approved_external_modes == ()


def test_object_store_status_redacts_credentials():
    import strategyos_mvp.storage as storage

    original_config = storage.CONFIG
    original_env = {
        key: os.environ.get(key)
        for key in [
            "STRATEGYOS_OBJECT_BUCKET",
            "STRATEGYOS_OBJECT_ENDPOINT",
            "STRATEGYOS_OBJECT_ACCESS_KEY_ID",
            "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY",
        ]
    }
    try:
        os.environ["STRATEGYOS_OBJECT_BUCKET"] = "bucket"
        os.environ["STRATEGYOS_OBJECT_ENDPOINT"] = "http://object-store"
        os.environ["STRATEGYOS_OBJECT_ACCESS_KEY_ID"] = "access"
        os.environ["STRATEGYOS_OBJECT_SECRET_ACCESS_KEY"] = "secret"
        storage.CONFIG = load_config()
        status = object_store_status()
        assert status["enabled"]
        assert status["access_key_id"] == "***"
        assert status["secret_access_key"] == "***"
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        storage.CONFIG = original_config


def test_sync_artifacts_noops_without_object_store():
    with tempfile.TemporaryDirectory() as tmp:
        artifact = Path(tmp) / "artifact.txt"
        artifact.write_text("ok", encoding="utf-8")
        assert sync_artifacts(Path("run"), [artifact]) == []


def test_load_config_parses_runtime_auth_and_governance_flags(monkeypatch):
    monkeypatch.setenv("STRATEGYOS_ENVIRONMENT_LABEL", "Hosted QA")
    monkeypatch.setenv("STRATEGYOS_API_AUTH_ENABLED", "true")
    monkeypatch.setenv("STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED", "true")
    monkeypatch.setenv("STRATEGYOS_REVIEWER_API_KEYS", "reviewer-a, reviewer-b")
    monkeypatch.setenv("STRATEGYOS_OPERATOR_API_KEYS", "operator-a")
    monkeypatch.setenv("STRATEGYOS_PUBLIC_HEALTH_ENABLED", "false")
    monkeypatch.setenv("STRATEGYOS_REQUIRE_HUMAN_REVIEW", "true")
    monkeypatch.setenv("STRATEGYOS_RUN_POLICY", "external-approved")
    monkeypatch.setenv(
        "STRATEGYOS_APPROVED_EXTERNAL_MODES",
        "object_storage_sync, model_provider_use, batch_apis, hosted_ocr_vision",
    )
    monkeypatch.setenv("STRATEGYOS_MODEL_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("STRATEGYOS_LLM_CHAT_ENABLED", "true")
    monkeypatch.setenv("STRATEGYOS_LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("STRATEGYOS_LLM_BASE_URL", "https://api.openai.test/v1")
    monkeypatch.setenv("STRATEGYOS_LLM_MODEL", "gpt-test")
    monkeypatch.setenv("STRATEGYOS_LLM_API_KEY", "test-key")
    monkeypatch.setenv("STRATEGYOS_LLM_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("STRATEGYOS_BATCH_APIS_ENABLED", "true")
    monkeypatch.setenv("STRATEGYOS_HOSTED_OCR_VISION_ENABLED", "true")
    monkeypatch.setenv("STRATEGYOS_TWINS_ENABLED", "true")
    monkeypatch.setenv("STRATEGYOS_TWINS_MUTATIONS_ENABLED", "false")
    monkeypatch.setenv("STRATEGYOS_TWINS_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("STRATEGYOS_TWINS_EXPOSE_REASONING_DIAGNOSTICS", "false")

    config = load_config()

    assert config.environment_label == "Hosted QA"
    assert config.api_auth_enabled is True
    assert config.demo_role_login_enabled is True
    assert config.reviewer_api_keys == ("reviewer-a", "reviewer-b")
    assert config.operator_api_keys == ("operator-a",)
    assert config.public_health_enabled is False
    assert config.require_human_review is True
    assert config.run_policy.mode == "external-approved"
    assert config.run_policy.approved_external_modes == (
        "object_storage_sync",
        "model_provider_use",
        "batch_apis",
        "hosted_ocr_vision",
    )
    assert config.model_provider_enabled is True
    assert config.llm_chat_enabled is True
    assert config.llm_provider == "openai-compatible"
    assert config.llm_base_url == "https://api.openai.test/v1"
    assert config.llm_model == "gpt-test"
    assert config.llm_api_key == "test-key"
    assert config.llm_timeout_seconds == 7
    assert config.batch_apis_enabled is True
    assert config.hosted_ocr_vision_enabled is True
    assert config.twins_enabled is True
    assert config.twins_mutations_enabled is False
    assert config.twins_scheduler_enabled is True
    assert config.twins_expose_reasoning_diagnostics is False


def test_load_config_parses_proxy_oidc_boundary(monkeypatch):
    monkeypatch.setenv("STRATEGYOS_AUTH_MODE", "proxy_oidc")
    monkeypatch.setenv("STRATEGYOS_TRUST_PROXY_AUTH", "true")
    monkeypatch.setenv("STRATEGYOS_OPERATOR_EMAILS", "operator@example.com")
    monkeypatch.setenv("STRATEGYOS_REVIEWER_EMAILS", "reviewer@example.com")
    monkeypatch.setenv("STRATEGYOS_TRUSTED_PROXY_AUTH_SECRET", "shared-secret")
    monkeypatch.setenv("OAUTH2_PROXY_OIDC_ISSUER_URL", "https://accounts.google.com")
    monkeypatch.setenv("OAUTH2_PROXY_CLIENT_ID", "client-id")
    monkeypatch.setenv(
        "OAUTH2_PROXY_REDIRECT_URL",
        "https://strategyos.example.com/oauth2/callback",
    )

    config = load_config()

    assert config.auth_mode == "proxy_oidc"
    assert config.trust_proxy_auth is True
    assert config.operator_emails == ("operator@example.com",)
    assert config.reviewer_emails == ("reviewer@example.com",)
    assert config.trusted_proxy_auth_secret == "shared-secret"
    assert config.oidc_issuer_url == "https://accounts.google.com"
    assert config.oidc_client_id == "client-id"
    assert config.oidc_redirect_url == "https://strategyos.example.com/oauth2/callback"


def test_load_config_uses_deepseek_defaults_and_key_fallback(monkeypatch):
    for key in [
        "STRATEGYOS_LLM_PROVIDER",
        "STRATEGYOS_LLM_BASE_URL",
        "STRATEGYOS_LLM_MODEL",
        "STRATEGYOS_LLM_API_KEY",
        "OPENAI_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")

    config = load_config()

    assert config.llm_provider == "deepseek"
    assert config.llm_base_url == "https://api.deepseek.com"
    assert config.llm_model == "deepseek-v4-pro"
    assert config.llm_api_key == "deepseek-key"


def test_load_config_parses_schema_tolerant_thresholds_and_fx_defaults(monkeypatch):
    monkeypatch.setenv("STRATEGYOS_SOURCE_PACK_STRUCTURED_CANDIDATE_THRESHOLD", "0.72")
    monkeypatch.setenv("STRATEGYOS_SOURCE_PACK_DOCUMENT_INDICATOR_THRESHOLD", "3")
    monkeypatch.setenv("STRATEGYOS_FINANCE_USD_RATE", "3.81")
    monkeypatch.setenv("STRATEGYOS_FINANCE_FX_HEDGE_DEFAULT_RATE", "3.7")
    monkeypatch.setenv("STRATEGYOS_FINANCE_OFF_CONTRACT_MIN_INVOICES", "6")
    monkeypatch.setenv("STRATEGYOS_FINANCE_OFF_CONTRACT_SINGLE_APPROVER_RATIO", "0.85")
    monkeypatch.setenv("STRATEGYOS_FINANCE_PRICE_VARIANCE_MIN_EXCESS_SAR", "12000")
    monkeypatch.setenv("STRATEGYOS_FINANCE_EARLY_PAY_DISCOUNT_WINDOW_DAYS", "15")
    monkeypatch.setenv("STRATEGYOS_FINANCE_EARLY_PAY_DISCOUNT_RATE", "0.03")
    monkeypatch.setenv("STRATEGYOS_FINANCE_WORKING_CAPITAL_MIN_WEEKLY_INVOICE_COUNT", "7")
    monkeypatch.setenv("STRATEGYOS_FINANCE_WORKING_CAPITAL_MIN_WEEKLY_AMOUNT_SAR", "150000")
    monkeypatch.setenv("STRATEGYOS_FINANCE_WORKING_CAPITAL_MAX_DRIVER_CONCENTRATION", "0.55")
    monkeypatch.setenv("STRATEGYOS_FINANCE_WORKING_CAPITAL_MIN_CONSECUTIVE_DRIFT_WEEKS", "3")
    monkeypatch.setenv("STRATEGYOS_FINANCE_WORKING_CAPITAL_MIN_DRIFT_DAYS", "4.5")

    config = load_config()

    assert config.source_pack_structured_candidate_threshold == 0.72
    assert config.source_pack_document_indicator_threshold == 3
    assert config.finance_usd_rate == 3.81
    assert config.finance_fx_hedge_default_rate == 3.7
    assert config.finance_off_contract_min_invoices == 6
    assert config.finance_off_contract_single_approver_ratio == 0.85
    assert config.finance_price_variance_min_excess_sar == 12000.0
    assert config.finance_early_pay_discount_window_days == 15
    assert config.finance_early_pay_discount_rate == 0.03
    assert config.finance_working_capital_min_weekly_invoice_count == 7
    assert config.finance_working_capital_min_weekly_amount_sar == 150000.0
    assert config.finance_working_capital_max_driver_concentration == 0.55
    assert config.finance_working_capital_min_consecutive_drift_weeks == 3
    assert config.finance_working_capital_min_drift_days == 4.5


def test_default_source_dataset_path_falls_back_to_repo_fixture(tmp_path):
    workspace_root = tmp_path / "workspace"
    poc_root = tmp_path / "missing-poc"
    package_root = tmp_path / "repo"
    fixture_dataset = package_root / ".fixtures" / "01_Synthetic_Dataset"
    fixture_dataset.mkdir(parents=True)

    resolved = default_source_dataset_path(
        workspace_root,
        poc_root,
        package_root=package_root,
    )

    assert resolved == fixture_dataset.resolve()


def test_default_source_dataset_path_dereferences_symlinked_repo_fixture_dirs(tmp_path):
    workspace_root = tmp_path / "workspace"
    poc_root = tmp_path / "missing-poc"
    package_root = tmp_path / "repo"
    raw_root = workspace_root / "outputs" / "source_packs" / "pack-b" / "raw"
    (raw_root / "02_ERP_Extracts").mkdir(parents=True, exist_ok=True)
    (raw_root / "04_Contracts").mkdir(parents=True, exist_ok=True)
    (raw_root / "02_ERP_Extracts" / "AP_Invoices_H1_2026.xlsx").write_text("ok", encoding="utf-8")

    fixture_dataset = package_root / ".fixtures" / "01_Synthetic_Dataset"
    fixture_dataset.mkdir(parents=True)
    (fixture_dataset / "02_ERP_Extracts").symlink_to(
        raw_root / "02_ERP_Extracts",
        target_is_directory=True,
    )
    (fixture_dataset / "04_Contracts").symlink_to(
        raw_root / "04_Contracts",
        target_is_directory=True,
    )

    resolved = default_source_dataset_path(
        workspace_root,
        poc_root,
        package_root=package_root,
    )

    assert resolved == raw_root.resolve()


def test_default_source_dataset_path_falls_back_to_latest_source_pack_raw(tmp_path):
    workspace_root = tmp_path / "workspace"
    poc_root = tmp_path / "missing-poc"
    package_root = tmp_path / "repo"
    latest_raw = workspace_root / "outputs" / "source_packs" / "pack-b" / "raw"
    older_raw = workspace_root / "outputs" / "source_packs" / "pack-a" / "raw"
    for raw_root in (older_raw, latest_raw):
        (raw_root / "02_ERP_Extracts").mkdir(parents=True, exist_ok=True)
        (raw_root / "04_Contracts").mkdir(parents=True, exist_ok=True)
        (raw_root / "02_ERP_Extracts" / "AP_Invoices_H1_2026.xlsx").write_text("ok", encoding="utf-8")
    os.utime(older_raw, (1, 1))
    os.utime(latest_raw, (2, 2))

    resolved = default_source_dataset_path(
        workspace_root,
        poc_root,
        package_root=package_root,
    )

    assert resolved == latest_raw.resolve()
