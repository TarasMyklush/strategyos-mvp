from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
import strategyos_mvp.state_store as state_store_module
from strategyos_mvp.config import load_config
from strategyos_mvp.oracle_finance import (
    BUFlexfieldMappingConfig,
    ingest_oracle_pilot_extracts,
    load_pilot_extract_batch,
    snapshot_summary,
    snapshot_payload,
)


client = TestClient(api_module.app)


def _apply_env(env_updates: dict[str, str | None]):
    import os

    original = {key: os.environ.get(key) for key in env_updates}
    for key, value in env_updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    api_module.CONFIG = config
    auth_module.CONFIG = config
    return original


def _restore_env(original: dict[str, str | None]):
    import os

    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    api_module.CONFIG = config
    auth_module.CONFIG = config


def _auth(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _phase10_env(tmp_path) -> dict[str, str]:
    return {
        "STRATEGYOS_API_AUTH_ENABLED": "true",
        "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": "true",
        "STRATEGYOS_TWINS_DATA_DIR": str(tmp_path / "app-data"),
        "STRATEGYOS_TWINS_ENABLED": "true",
        "STRATEGYOS_TWINS_MUTATIONS_ENABLED": "true",
        "STRATEGYOS_TWINS_SCHEDULER_ENABLED": "true",
        "STRATEGYOS_TWINS_EXPOSE_REASONING_DIAGNOSTICS": "false",
    }


def _oracle_ingestion_env(tmp_path) -> dict[str, str]:
    return {
        **_phase10_env(tmp_path),
        "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
    }


def test_extract_fixture_ingestion_builds_canonical_finance_snapshot():
    fixtures = {
        "GL": [
            {
                "natural_key": "gl-revenue-1",
                "fact_type": "revenue",
                "amount": "125000.50",
                "currency": "SAR",
                "account_code": "4000",
                "period_name": "2026-06",
                "period_start": "2026-06-01",
                "flexfield_segments": ["COMP", "BU01", "CC100"],
                "source_reference": "GL_BALANCES:1",
            },
            {
                "record_type": "fx_rate",
                "rate_key": "usd-sar-2026-06-30",
                "source_currency": "USD",
                "reporting_currency": "SAR",
                "rate_source": "GL_DAILY_RATES",
                "rate_date": "2026-06-30",
                "rate_value": "3.7500",
            },
        ],
        "AR": [
            {
                "natural_key": "ar-1",
                "fact_type": "cash_in",
                "amount": "22000",
                "currency": "SAR",
                "event_date": "2026-06-29",
                "flexfield_segments": ["COMP", "BU01", "CC100"],
            }
        ],
        "AP": [
            {
                "natural_key": "ap-1",
                "fact_type": "cash_out",
                "amount": "14000",
                "currency": "SAR",
                "event_date": "2026-06-29",
                "flexfield_segments": ["COMP", "BU02", "CC220"],
            },
            {
                "natural_key": "ap-debt-1",
                "fact_type": "debt_balance",
                "amount": "80000",
                "currency": "SAR",
                "event_date": "2026-06-30",
                "flexfield_segments": ["COMP", "BU02", "CC220"],
            },
        ],
        "CE": [
            {
                "natural_key": "ce-1",
                "amount": "95000",
                "currency": "SAR",
                "as_of_date": "2026-06-30",
                "fact_type": "cash_balance",
            }
        ],
        "FA": [
            {
                "natural_key": "fa-1",
                "amount": "450000",
                "currency": "SAR",
                "event_date": "2026-04-01",
            }
        ],
        "PO": [
            {
                "natural_key": "po-1",
                "amount": "30000",
                "currency": "SAR",
                "event_date": "2026-06-24",
                "flexfield_segments": ["COMP", "BU01", "CC100"],
            }
        ],
        "INV": [
            {
                "natural_key": "inv-1",
                "fact_type": "working_capital_inventory",
                "amount": "41000",
                "currency": "SAR",
                "event_date": "2026-06-24",
                "flexfield_segments": ["COMP", "BU02", "CC220"],
            }
        ],
    }
    manual_inputs = [
        {
            "input_type": "budget_plan",
            "input_name": "FY26 Board Budget",
            "storage_kind": "file",
            "period_key": "2026-06",
            "source_uri": "s3://pilot/budget.xlsx",
        },
        {
            "input_type": "hedge_register",
            "input_name": "Treasury Hedge Register",
            "storage_kind": "file",
            "period_key": "2026-W26",
            "source_uri": "s3://pilot/hedges.xlsx",
        },
        {
            "input_type": "contract_registry",
            "input_name": "Supplier Contracts",
            "storage_kind": "file",
            "source_uri": "sharepoint://contracts",
        },
        {
            "input_type": "covenant_terms",
            "input_name": "Loan Covenant Pack",
            "storage_kind": "file",
            "source_uri": "sharepoint://covenants",
        },
        {
            "input_type": "board_floor",
            "input_name": "Board Cash Floor",
            "storage_kind": "manual",
            "period_key": "2026-06-30",
            "source_uri": "manual://board-floor",
        },
        {
            "input_type": "commentary",
            "input_name": "BU CFO June Commentary",
            "storage_kind": "manual",
            "period_key": "2026-06",
            "owner_role": "bu_cfo",
            "source_uri": "manual://commentary/june",
        },
    ]
    mapping = BUFlexfieldMappingConfig(
        segment_name="segment2",
        segment_index=1,
        value_to_bu={"BU01": "Consumer", "BU02": "Healthcare"},
        default_bu="Corporate",
    )

    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(fixtures),
        bu_mapping=mapping,
        manual_inputs=manual_inputs,
    )

    assert {connector.module for connector in snapshot.connectors} == {
        "GL",
        "AR",
        "AP",
        "CE",
        "FA",
        "PO",
        "INV",
    }
    assert len(snapshot.facts) == 8
    assert len(snapshot.fx_rates) == 1
    assert len(snapshot.manual_inputs) == 6
    assert {fact.fact_type for fact in snapshot.facts} >= {
        "revenue",
        "cash_in",
        "cash_out",
        "cash_balance",
        "debt_balance",
        "working_capital_inventory",
    }
    assert snapshot.fx_rates[0].rate_value == Decimal("3.7500")

    payload = snapshot_payload(snapshot)
    assert payload["metadata"]["modules_loaded"]["GL"] == 2
    assert any(item["target_field"] == "business_unit" for item in payload["connector_mappings"])


def test_bu_mapping_and_cadence_assignment_follow_oracle_doc_defaults():
    mapping = BUFlexfieldMappingConfig(
        segment_name="segment2",
        segment_index=1,
        value_to_bu={"BU01": "Consumer", "BU02": "Healthcare"},
        default_bu="Corporate",
    )
    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(
            {
                "GL": [{"natural_key": "gl-1", "amount": "10", "period_name": "2026-06", "flexfield_segments": ["COMP", "BU01", "CC100"]}],
                "AR": [{"natural_key": "ar-1", "amount": "20", "event_date": "2026-06-28", "flexfield_segments": ["COMP", "BU02", "CC220"]}],
                "AP": [{"natural_key": "ap-1", "amount": "30", "event_date": "2026-06-28", "flexfield_segments": ["COMP", "UNKNOWN", "CC999"]}],
                "CE": [{"natural_key": "ce-1", "amount": "40", "as_of_date": "2026-06-28"}],
                "FA": [{"natural_key": "fa-1", "amount": "50", "event_date": "2026-04-01"}],
                "PO": [{"natural_key": "po-1", "amount": "60", "event_date": "2026-06-23", "flexfield_segments": ["COMP", "BU01", "CC100"]}],
                "INV": [{"natural_key": "inv-1", "amount": "70", "event_date": "2026-06-23", "flexfield_segments": ["COMP", "BU02", "CC220"]}],
            }
        ),
        bu_mapping=mapping,
    )

    facts = {fact.natural_key: fact for fact in snapshot.facts}
    assert facts["gl-1"].bu_code == "Consumer"
    assert facts["ar-1"].bu_code == "Healthcare"
    assert facts["ap-1"].bu_code == "Corporate"
    assert facts["gl-1"].cadence == "monthly"
    assert facts["ar-1"].cadence == "daily"
    assert facts["ce-1"].cadence == "daily"
    assert facts["fa-1"].cadence == "quarterly"
    assert facts["po-1"].cadence == "weekly"
    assert facts["inv-1"].cadence == "weekly"


def test_manual_and_file_inputs_are_registered_as_first_class_inputs():
    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch({}),
        bu_mapping=BUFlexfieldMappingConfig(
            segment_name="segment2",
            segment_index=1,
            value_to_bu={},
            default_bu="Corporate",
        ),
        manual_inputs=[
            {"input_type": "budget_plan", "input_name": "Budget", "storage_kind": "file"},
            {"input_type": "hedge_register", "input_name": "Hedges", "storage_kind": "file"},
            {"input_type": "contract_registry", "input_name": "Contracts", "storage_kind": "file"},
            {"input_type": "covenant_terms", "input_name": "Covenants", "storage_kind": "file"},
            {"input_type": "board_floor", "input_name": "Board Floor", "storage_kind": "manual"},
            {"input_type": "commentary", "input_name": "GM Commentary", "storage_kind": "manual", "owner_role": "gm"},
        ],
    )

    assert {item.input_type for item in snapshot.manual_inputs} == {
        "budget_plan",
        "hedge_register",
        "contract_registry",
        "covenant_terms",
        "board_floor",
        "commentary",
    }
    commentary = next(item for item in snapshot.manual_inputs if item.input_type == "commentary")
    assert commentary.owner_role == "gm"
    assert commentary.storage_kind == "manual"


def test_snapshot_summary_reports_module_and_manual_input_coverage():
    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(
            {
                "GL": [{"natural_key": "gl-1", "amount": "10", "period_name": "2026-06"}],
                "AP": [{"natural_key": "ap-1", "amount": "20", "event_date": "2026-06-30"}],
            }
        ),
        bu_mapping=BUFlexfieldMappingConfig(
            segment_name="segment2",
            segment_index=1,
            value_to_bu={},
            default_bu="Corporate",
        ),
        manual_inputs=[
            {"input_type": "budget_plan", "input_name": "Budget", "storage_kind": "file"},
            {"input_type": "commentary", "input_name": "Narrative", "storage_kind": "manual"},
        ],
    )

    summary = snapshot_summary(snapshot)

    assert summary["facts"] == 2
    assert summary["facts_by_module"]["GL"] == 1
    assert summary["facts_by_module"]["AP"] == 1
    assert summary["manual_inputs"] == 2
    assert summary["manual_inputs_by_type"]["budget_plan"] == 1
    assert summary["manual_inputs_by_type"]["commentary"] == 1


def test_persist_oracle_snapshot_returns_auditable_metadata_and_upsert_counts(monkeypatch):
    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(
            {
                "GL": [{"natural_key": "gl-1", "amount": "10", "period_name": "2026-06"}],
                "CE": [
                    {
                        "natural_key": "ce-1",
                        "amount": "15",
                        "as_of_date": "2026-06-30",
                        "fact_type": "cash_balance",
                    }
                ],
            }
        ),
        bu_mapping=BUFlexfieldMappingConfig(
            segment_name="segment2",
            segment_index=1,
            value_to_bu={},
            default_bu="Corporate",
        ),
        manual_inputs=[
            {"input_type": "board_floor", "input_name": "Board floor", "storage_kind": "manual"}
        ],
    )

    statements: list[tuple[str, tuple[object, ...]]] = []

    class FakeCursor:
        def execute(self, sql, params):
            statements.append((str(sql), tuple(params)))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(state_store_module, "database_connection", lambda: (FakeConnection(), None))
    monkeypatch.setattr(state_store_module, "ensure_data_schema", lambda conn: None)

    persisted = state_store_module.persist_oracle_canonical_snapshot(
        snapshot,
        tenant_id="11111111-1111-1111-1111-111111111111",
        batch_id="22222222-2222-2222-2222-222222222222",
        source_system_id="33333333-3333-3333-3333-333333333333",
    )

    assert persisted["status"] == "ok"
    assert persisted["tenant_id"] == "11111111-1111-1111-1111-111111111111"
    assert persisted["batch_id"] == "22222222-2222-2222-2222-222222222222"
    assert persisted["source_system_id"] == "33333333-3333-3333-3333-333333333333"
    assert persisted["facts"] == len(snapshot.facts)
    assert persisted["manual_inputs"] == len(snapshot.manual_inputs)

    fact_sql = next(sql for sql, _ in statements if "insert into strategyos_finance_facts" in sql)
    manual_sql = next(sql for sql, _ in statements if "insert into strategyos_finance_manual_inputs" in sql)
    mapping_sql = next(sql for sql, _ in statements if "insert into strategyos_oracle_connector_mappings" in sql)
    assert "on conflict" in fact_sql.lower()
    assert "on conflict" in manual_sql.lower()
    assert "on conflict" in mapping_sql.lower()

    fact_params = next(params for sql, params in statements if "insert into strategyos_finance_facts" in sql)
    manual_params = next(
        params for sql, params in statements if "insert into strategyos_finance_manual_inputs" in sql
    )
    mapping_params = next(
        params for sql, params in statements if "insert into strategyos_oracle_connector_mappings" in sql
    )
    assert fact_params[0:3] == (
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
    )
    assert manual_params[0:2] == (
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    )
    assert mapping_params[0:2] == (
        "11111111-1111-1111-1111-111111111111",
        "33333333-3333-3333-3333-333333333333",
    )


def test_oracle_ingestion_endpoint_requires_operator_and_returns_auditable_counts(tmp_path, monkeypatch):
    original = _apply_env(_oracle_ingestion_env(tmp_path))
    captured: dict[str, object] = {}
    payload = {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "batch_id": "22222222-2222-2222-2222-222222222222",
        "source_system_id": "33333333-3333-3333-3333-333333333333",
        "reporting_currency": "SAR",
        "bu_mapping": {
            "segment_name": "segment2",
            "segment_index": 1,
            "value_to_bu": {"BU01": "Consumer"},
            "default_bu": "Corporate",
        },
        "extracts": {
            "GL": [
                {
                    "natural_key": "gl-1",
                    "amount": "10",
                    "period_name": "2026-06",
                    "flexfield_segments": ["COMP", "BU01", "CC100"],
                }
            ],
            "AR": [
                {
                    "natural_key": "ar-1",
                    "amount": "20",
                    "event_date": "2026-06-30",
                    "flexfield_segments": ["COMP", "BU01", "CC100"],
                }
            ],
        },
        "manual_inputs": [
            {
                "input_type": "budget_plan",
                "input_name": "Budget",
                "storage_kind": "file",
                "source_uri": "s3://pilot/budget.xlsx",
            }
        ],
    }

    def _fake_persist(snapshot, *, tenant_id, batch_id=None, source_system_id=None):
        captured["tenant_id"] = tenant_id
        captured["batch_id"] = batch_id
        captured["source_system_id"] = source_system_id
        captured["snapshot"] = snapshot
        return {
            "status": "ok",
            "tenant_id": tenant_id,
            "batch_id": batch_id,
            "source_system_id": source_system_id,
            "connector_mappings": len(snapshot.connector_mappings),
            "periods": len(snapshot.periods),
            "facts": len(snapshot.facts),
            "fx_rates": len(snapshot.fx_rates),
            "manual_inputs": len(snapshot.manual_inputs),
        }

    monkeypatch.setattr(api_module.state_store, "persist_oracle_canonical_snapshot", _fake_persist)
    try:
        unauthorized = client.post("/finance/oracle/ingest", json=payload)
        assert unauthorized.status_code == 401

        forbidden = client.post(
            "/finance/oracle/ingest",
            headers=_auth("reviewer-secret"),
            json=payload,
        )
        assert forbidden.status_code == 403

        response = client.post(
            "/finance/oracle/ingest",
            headers=_auth("operator-secret"),
            json=payload,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["tenant_id"] == "11111111-1111-1111-1111-111111111111"
        assert body["batch_id"] == "22222222-2222-2222-2222-222222222222"
        assert body["source_system_id"] == "33333333-3333-3333-3333-333333333333"
        assert body["snapshot"]["facts"] == 2
        assert body["snapshot"]["manual_inputs"] == 1
        assert body["snapshot"]["facts_by_module"]["GL"] == 1
        assert body["snapshot"]["facts_by_module"]["AR"] == 1
        assert body["persistence"]["facts"] == 2
        assert captured["tenant_id"] == "11111111-1111-1111-1111-111111111111"
    finally:
        _restore_env(original)


def test_plan_data_marks_phase11_complete_without_starting_phase13():
    plan_file = (
        Path(__file__).resolve().parents[1]
        / "strategyos_mvp"
        / "static"
        / "plan_data.js"
    )
    text = plan_file.read_text(encoding="utf-8")
    phase1_block = text.split('id: "phase-1"', 1)[1].split('id: "phase-2"', 1)[0]
    assert 'status: "completed"' in phase1_block
    phase11_block = text.split('id: "phase-11"', 1)[1].split('id: "phase-12"', 1)[0]
    assert 'id: "phase-11"' in text
    assert 'status: "completed"' in phase11_block
    assert 'id: "12.1"' in text
    assert 'title: "Deterministic KPI calculation engine"' in text
    phase12_block = text.split('id: "phase-12"', 1)[1].split('id: "phase-13"', 1)[0]
    assert 'status: "completed"' in phase12_block
    phase13_block = text.split('id: "phase-13"', 1)[1].split('id: "phase-14"', 1)[0]
    assert 'status: "not_started"' in phase13_block
    assert 'overallStatus: "in_progress"' in text


def test_phase0_to_phase10_regression_paths_still_hold(tmp_path):
    original = _apply_env(_phase10_env(tmp_path))
    try:
        status = client.get("/twin/api/status/ceo", headers=_auth("executive"))
        inbox = client.get("/twin/api/inbox/ceo", headers=_auth("executive"))
        investigate = client.post(
            "/twin/api/investigate/ceo?query=Why+is+margin+down%3F",
            headers=_auth("executive"),
        )
        dashboard = client.get("/twin/ceo", headers=_auth("executive"))

        assert status.status_code == 200
        assert inbox.status_code == 200
        assert investigate.status_code == 200
        assert dashboard.status_code == 200
        assert "governance" in status.json()
        assert "reasoning_trace_ids" in investigate.json()["summary"]
    finally:
        _restore_env(original)
