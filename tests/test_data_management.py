import os
from datetime import datetime
from decimal import Decimal

from strategyos_mvp.models import (
    CutoverMetric,
    CutoverMetricThreshold,
    FXNormalization,
    TenantProfileVersion,
)
from strategyos_mvp.config import load_config
from strategyos_mvp.state_store import (
    approval_status_for_run,
    create_run,
    data_management_status,
    schema_path,
)


def test_schema_defines_managed_data_layers():
    schema = schema_path().read_text(encoding="utf-8")
    required_tables = [
        "strategyos_runs",
        "strategyos_run_jobs",
        "strategyos_run_checkpoints",
        "strategyos_approvals",
        "strategyos_tenants",
        "strategyos_source_systems",
        "strategyos_ingestion_batches",
        "strategyos_evidence_documents",
        "strategyos_finance_entities",
        "strategyos_finance_transactions",
        "strategyos_finance_balances",
        "strategyos_tenant_profiles",
        "strategyos_tenant_profile_versions",
        "strategyos_canonical_finance_entities",
        "strategyos_canonical_finance_entity_links",
        "strategyos_fx_rates",
        "strategyos_backfill_runs",
        "strategyos_cutover_metrics",
        "strategyos_finding_citations",
        "strategyos_agent_events",
        "strategyos_kg_nodes",
        "strategyos_kg_edges",
    ]
    for table in required_tables:
        assert f"create table if not exists {table}" in schema


def test_data_management_status_noops_without_database():
    import strategyos_mvp.state_store as state_store

    original_config = state_store.CONFIG
    original_env = {
        key: os.environ.get(key) for key in ["DATABASE_URL", "STRATEGYOS_DATABASE_URL"]
    }
    try:
        for key in original_env:
            os.environ.pop(key, None)
        state_store.CONFIG = load_config()
        status = data_management_status()
        assert status["status"] == "skipped"
    finally:
        for key, value in original_env.items():
            if value is not None:
                os.environ[key] = value
        state_store.CONFIG = original_config


def test_runtime_persistence_primitives_noop_without_database():
    import strategyos_mvp.state_store as state_store

    original_config = state_store.CONFIG
    original_env = {
        key: os.environ.get(key) for key in ["DATABASE_URL", "STRATEGYOS_DATABASE_URL"]
    }
    try:
        for key in original_env:
            os.environ.pop(key, None)
        state_store.CONFIG = load_config()
        created = create_run(
            {"dataset": "dataset", "run_dir": "run-dir"}, requires_human_review=True
        )
        approval = approval_status_for_run("missing-run")
        assert created["status"] == "skipped"
        assert approval["status"] == "skipped"
    finally:
        for key, value in original_env.items():
            if value is not None:
                os.environ[key] = value
        state_store.CONFIG = original_config


def test_invoice_substrate_contract_primitives_capture_fx_profile_and_cutover_rules():
    profile = TenantProfileVersion(
        tenant_id="tenant-1",
        profile_id="gulf-retail-ap-v1",
        version=3,
        document_type="invoice",
        lifecycle_status="active",
        field_aliases={"invoice_number": ["Invoice No", "INV #"]},
        required_fields=["invoice_number", "invoice_date", "total_amount"],
        parser_preference_order=["pdf_invoice", "spreadsheet_invoice"],
        validation_rules={"min_confidence": 0.86},
        approver="ap-manager",
        activated_at=datetime(2026, 6, 6, 0, 0, 0),
    )
    fx = FXNormalization(
        reporting_currency="SAR",
        fx_rate_source="ecb",
        fx_rate_value=Decimal("4.12500000"),
        normalized_total_amount=Decimal("4125.00"),
        fx_status="normalized",
    )
    metric = CutoverMetric(
        tenant_id="tenant-1",
        metric_key="invoice_sum",
        sample_window_label="2026-H1",
        legacy_value=Decimal("100.00"),
        canonical_value=Decimal("100.25"),
        threshold=CutoverMetricThreshold(max_delta_value=Decimal("1.00")),
        exclusion_breakdown={"missing_fx": 1},
    )

    assert profile.supports_new_jobs() is True
    assert profile.supports_shadow_runs() is True
    assert fx.supports_reporting_total() is True
    assert metric.delta_value() == Decimal("0.25")
    assert metric.within_threshold() is True
