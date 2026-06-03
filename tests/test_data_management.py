import os

from strategyos_mvp.config import load_config
from strategyos_mvp.state_store import data_management_status, schema_path


def test_schema_defines_managed_data_layers():
    schema = schema_path().read_text(encoding="utf-8")
    required_tables = [
        "strategyos_tenants",
        "strategyos_source_systems",
        "strategyos_ingestion_batches",
        "strategyos_evidence_documents",
        "strategyos_finance_entities",
        "strategyos_finance_transactions",
        "strategyos_finance_balances",
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
    original_env = {key: os.environ.get(key) for key in ["DATABASE_URL", "STRATEGYOS_DATABASE_URL"]}
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
