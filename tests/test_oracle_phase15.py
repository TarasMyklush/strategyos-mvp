from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
from strategyos_mvp.config import load_config
from strategyos_mvp.oracle_finance import (
    BUFlexfieldMappingConfig,
    build_oracle_pilot_lineage_payload,
    build_oracle_pilot_readiness_report,
    build_oracle_pilot_reconciliation_report,
    build_oracle_pilot_rollout_report,
    compute_oracle_pilot_kpis,
    compute_oracle_pilot_leakage,
    ingest_oracle_pilot_extracts,
    load_pilot_extract_batch,
)


ROOT = Path(__file__).resolve().parents[1]
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


def _phase15_env(tmp_path: Path, *, rollout_ready: bool) -> dict[str, str]:
    return {
        "STRATEGYOS_API_AUTH_ENABLED": "true",
        "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
        "STRATEGYOS_TWINS_ENABLED": "true",
        "STRATEGYOS_TWINS_MUTATIONS_ENABLED": "true",
        "STRATEGYOS_TWINS_SCHEDULER_ENABLED": "true",
        "STRATEGYOS_ORACLE_PILOT_ENABLED": "true" if rollout_ready else "false",
        "STRATEGYOS_ORACLE_PILOT_CEO_SURFACE_ENABLED": "true" if rollout_ready else "false",
        "STRATEGYOS_ORACLE_PILOT_CFO_SURFACE_ENABLED": "true" if rollout_ready else "false",
        "STRATEGYOS_ORACLE_PILOT_ROLLBACK_READY": "true" if rollout_ready else "false",
        "STRATEGYOS_OUTPUT_ROOT": str(tmp_path / "outputs"),
    }


def _validation_payload() -> dict[str, object]:
    return {
        "reporting_currency": "SAR",
        "reporting_period_key": "2026-06",
        "approval_status": "approved",
        "reviewer_actions": [
            {
                "action": "phase15_signoff",
                "reviewer": "cfo.oracle",
                "comment": "Pilot numbers reconciled and rollout gate accepted.",
            }
        ],
        "bu_mapping": {
            "segment_name": "segment2",
            "segment_index": 1,
            "value_to_bu": {"BU01": "Consumer", "BU02": "Healthcare"},
            "default_bu": "Corporate",
        },
        "extracts": {
            "GL": [
                {
                    "natural_key": "gl-revenue-june",
                    "fact_type": "revenue",
                    "amount": "10000",
                    "currency": "SAR",
                    "period_name": "2026-06",
                    "period_start": "2026-06-01",
                    "period_end": "2026-06-30",
                    "flexfield_segments": ["COMP", "BU01", "CC100"],
                    "source_reference": "GL_BALANCES:1",
                },
                {
                    "natural_key": "gl-ebitda-june",
                    "fact_type": "ebitda",
                    "amount": "3000",
                    "currency": "SAR",
                    "period_name": "2026-06",
                    "period_start": "2026-06-01",
                    "period_end": "2026-06-30",
                    "flexfield_segments": ["COMP", "BU01", "CC100"],
                    "source_reference": "GL_BALANCES:2",
                },
                {
                    "natural_key": "gl-opex-june",
                    "fact_type": "operating_cost",
                    "amount": "5000",
                    "currency": "SAR",
                    "period_name": "2026-06",
                    "period_start": "2026-06-01",
                    "period_end": "2026-06-30",
                    "flexfield_segments": ["COMP", "BU01", "CC100"],
                    "source_reference": "GL_BALANCES:3",
                },
            ],
            "AR": [
                {
                    "natural_key": "ar-balance-1",
                    "fact_type": "accounts_receivable_balance",
                    "amount": "150",
                    "currency": "SAR",
                    "event_date": "2026-06-30",
                    "flexfield_segments": ["COMP", "BU01", "CC100"],
                }
            ],
            "AP": [
                {
                    "natural_key": "ap-dup-1",
                    "fact_type": "payment",
                    "amount": "1200",
                    "payment_amount": "1200",
                    "currency": "SAR",
                    "invoice_num": "DUP-001",
                    "invoice_date": "2026-06-05",
                    "payment_date": "2026-06-10",
                    "payment_reference": "PAY-001",
                    "vendor_id": "V100",
                    "vendor_name": "Alpha Supplies",
                },
                {
                    "natural_key": "ap-dup-2",
                    "fact_type": "payment",
                    "amount": "1200",
                    "payment_amount": "1200",
                    "currency": "SAR",
                    "invoice_num": "DUP-001",
                    "invoice_date": "2026-06-05",
                    "payment_date": "2026-06-12",
                    "payment_reference": "PAY-002",
                    "vendor_id": "V100",
                    "vendor_name": "Alpha Supplies",
                },
                {
                    "natural_key": "ap-ent-1",
                    "fact_type": "payment",
                    "amount": "800",
                    "payment_amount": "800",
                    "currency": "SAR",
                    "invoice_num": "ENT-001",
                    "invoice_date": "2026-06-07",
                    "payment_date": "2026-06-14",
                    "payment_reference": "PAY-ENT-1",
                    "vendor_id": "V201",
                    "vendor_name": "Beta Industrial",
                    "vendor_tax_id": "TAX-8899",
                },
                {
                    "natural_key": "ap-ent-2",
                    "fact_type": "payment",
                    "amount": "800",
                    "payment_amount": "800",
                    "currency": "SAR",
                    "invoice_num": "ENT-001",
                    "invoice_date": "2026-06-07",
                    "payment_date": "2026-06-15",
                    "payment_reference": "PAY-ENT-2",
                    "vendor_id": "V202",
                    "vendor_name": "Beta Industrial LLC",
                    "vendor_tax_id": "TAX-8899",
                },
                {
                    "natural_key": "ap-off-1",
                    "fact_type": "invoice",
                    "amount": "1500",
                    "invoice_amount": "1500",
                    "currency": "SAR",
                    "invoice_num": "OFF-001",
                    "invoice_date": "2026-06-09",
                    "vendor_id": "V300",
                    "vendor_name": "Gamma Tech",
                    "category": "IT",
                    "quantity": "10",
                },
                {
                    "natural_key": "ap-pv-1",
                    "fact_type": "invoice",
                    "amount": "1200",
                    "invoice_amount": "1200",
                    "currency": "SAR",
                    "invoice_num": "PV-001",
                    "invoice_date": "2026-06-11",
                    "vendor_id": "V400",
                    "vendor_name": "Delta Parts",
                    "category": "MRO",
                    "quantity": "10",
                    "invoice_unit_price": "120",
                    "po_reference": "PO-400",
                },
                {
                    "natural_key": "ap-disc-1",
                    "fact_type": "invoice",
                    "amount": "1000",
                    "invoice_amount": "1000",
                    "currency": "SAR",
                    "invoice_num": "DISC-001",
                    "invoice_date": "2026-06-01",
                    "payment_date": "2026-06-20",
                    "vendor_id": "V500",
                    "vendor_name": "Epsilon Services",
                    "discount_pct": "2",
                    "discount_due_date": "2026-06-05",
                },
                {
                    "natural_key": "ap-balance-1",
                    "fact_type": "accounts_payable_balance",
                    "amount": "6200",
                    "currency": "SAR",
                    "event_date": "2026-06-30",
                },
                {
                    "natural_key": "ap-fx-1",
                    "fact_type": "invoice",
                    "amount": "3900",
                    "invoice_amount": "3900",
                    "currency": "USD",
                    "invoice_num": "FX-001",
                    "invoice_date": "2026-06-16",
                    "vendor_id": "V700",
                    "vendor_name": "Zeta Global",
                    "foreign_amount": "1000",
                    "applied_fx_rate": "3.90",
                },
                {
                    "natural_key": "ap-credit-1",
                    "fact_type": "credit_balance",
                    "amount": "-250",
                    "currency": "SAR",
                    "vendor_id": "V800",
                    "vendor_name": "Eta Logistics",
                    "credit_reference": "CR-001",
                    "credit_balance_amount": "250",
                    "last_activity_date": "2026-02-01",
                    "credit_status": "open",
                },
                {
                    "natural_key": "ap-debt-1",
                    "fact_type": "debt_balance",
                    "amount": "500",
                    "currency": "SAR",
                    "event_date": "2026-06-30",
                },
            ],
            "CE": [
                {
                    "natural_key": "ce-cash-1",
                    "fact_type": "cash_balance",
                    "amount": "120",
                    "currency": "SAR",
                    "as_of_date": "2026-06-30",
                }
            ],
            "PO": [
                {
                    "natural_key": "po-400",
                    "fact_type": "purchase_order_line",
                    "amount": "850",
                    "currency": "SAR",
                    "event_date": "2026-06-02",
                    "po_reference": "PO-400",
                    "po_unit_price": "85",
                    "quantity": "10",
                    "vendor_id": "V400",
                    "vendor_name": "Delta Parts",
                    "category": "MRO",
                }
            ],
            "INV": [
                {
                    "natural_key": "inv-balance-1",
                    "fact_type": "inventory_balance",
                    "amount": "75",
                    "currency": "SAR",
                    "event_date": "2026-06-27",
                }
            ],
        },
        "manual_inputs": [
            {
                "input_key": "budget-june",
                "input_type": "budget_plan",
                "input_name": "June budget",
                "storage_kind": "file",
                "period_key": "2026-06",
                "owner_role": "finance_controller",
                "source_uri": "s3://oracle-pilot/budget-june.xlsx",
                "metrics": {
                    "revenue": "8000",
                    "ebitda": "2000",
                    "operating_cost": "5000",
                },
            },
            {
                "input_key": "board-floor-june",
                "input_type": "board_floor",
                "input_name": "June board floor",
                "storage_kind": "manual",
                "period_key": "2026-06-30",
                "owner_role": "treasury_director",
                "source_uri": "manual://board-floor/june-2026",
                "board_floor": "100",
            },
            {
                "input_key": "covenant-pack-q2",
                "input_type": "covenant_terms",
                "input_name": "Q2 covenant pack",
                "storage_kind": "file",
                "period_key": "2026-Q2",
                "owner_role": "group_treasury",
                "source_uri": "s3://oracle-pilot/covenants-q2.pdf",
                "terms": {"max_net_debt_to_ebitda": "3.0"},
            },
            {
                "input_key": "contracts-june",
                "input_type": "contract_registry",
                "input_name": "June contract registry",
                "storage_kind": "file",
                "period_key": "2026-06",
                "owner_role": "procurement_ops",
                "source_uri": "s3://oracle-pilot/contracts-june.xlsx",
                "contracts": [
                    {
                        "contract_id": "C-300",
                        "vendor_id": "V300",
                        "vendor_name": "Gamma Tech",
                        "category": "IT",
                        "start_date": "2026-01-01",
                        "end_date": "2026-12-31",
                        "unit_price": "100",
                    },
                    {
                        "contract_id": "C-600",
                        "vendor_id": "V600",
                        "vendor_name": "Theta Software",
                        "auto_renewal": True,
                        "renewal_date": "2026-06-18",
                        "previous_annual_value": "1000",
                        "renewed_annual_value": "1300",
                    },
                ],
                "line_items": [
                    {
                        "contract_id": "C-300-BENCH",
                        "vendor_id": "V300",
                        "vendor_name": "Gamma Tech",
                        "category": "IT",
                        "off_contract_savings_pct": "10",
                    }
                ],
            },
            {
                "input_key": "hedges-june",
                "input_type": "hedge_register",
                "input_name": "June hedge register",
                "storage_kind": "file",
                "period_key": "2026-06",
                "owner_role": "treasury_manager",
                "source_uri": "s3://oracle-pilot/hedges-june.xlsx",
                "hedges": [
                    {
                        "hedge_id": "H-700",
                        "invoice_num": "FX-001",
                        "vendor_id": "V700",
                        "currency": "USD",
                        "hedged_rate": "3.75",
                    }
                ],
            },
        ],
    }


def _snapshot_from_payload():
    payload = _validation_payload()
    return ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(payload["extracts"]),
        bu_mapping=BUFlexfieldMappingConfig(
            segment_name="segment2",
            segment_index=1,
            value_to_bu={"BU01": "Consumer", "BU02": "Healthcare"},
            default_bu="Corporate",
        ),
        manual_inputs=payload["manual_inputs"],
        reporting_currency="SAR",
    )


def test_phase15_reconciliation_auditability_and_readiness_reports_pass_with_signoff():
    snapshot = _snapshot_from_payload()
    computation = compute_oracle_pilot_kpis(snapshot, reporting_period_key="2026-06")
    review = compute_oracle_pilot_leakage(snapshot, reporting_period_key="2026-06")

    reconciliation = build_oracle_pilot_reconciliation_report(snapshot, computation, review)
    lineage = build_oracle_pilot_lineage_payload(
        snapshot,
        computation,
        review,
        reviewer_actions=[
            {"action": "phase15_signoff", "reviewer": "cfo.oracle", "comment": "ready"}
        ],
    )
    rollout = build_oracle_pilot_rollout_report(
        rollout_flags={
            "pilot_enabled": True,
            "ceo_surface_enabled": True,
            "cfo_surface_enabled": True,
            "rollback_ready": True,
        },
        require_human_review=True,
    )
    readiness = build_oracle_pilot_readiness_report(
        reconciliation=reconciliation,
        auditability=lineage["auditability"],
        rollout_controls=rollout,
        review=review,
        reviewer_actions=[{"action": "phase15_signoff", "reviewer": "cfo.oracle"}],
        approval_status="approved",
        require_human_review=True,
    )

    assert reconciliation["passed"] is True
    assert lineage["auditability"]["passed"] is True
    assert rollout["passed"] is True
    assert readiness["passed"] is True
    assert readiness["status"] == "signed_off"
    assert review.total_recoverable_sar is not None
    assert any(item["metric_key"] == "revenue_attainment_pct" for item in lineage["metrics"])


def test_phase15_validation_endpoint_covers_ingestion_to_pilot_surfaces(tmp_path: Path):
    original = _apply_env(_phase15_env(tmp_path, rollout_ready=True))
    try:
        response = client.post(
            "/finance/oracle/validate",
            headers=_auth("operator-secret"),
            json=_validation_payload(),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["snapshot"]["facts_by_module"]["GL"] == 3
        assert body["kpi"]["authoritative"] is True
        assert body["reconciliation"]["passed"] is True
        assert body["lineage"]["auditability"]["passed"] is True
        assert body["rollout_controls"]["passed"] is True
        assert body["readiness"]["status"] == "signed_off"

        ceo_text = (ROOT / "strategyos_mvp" / "twins" / "static" / "ceo.html").read_text(encoding="utf-8")
        cfo_text = (ROOT / "strategyos_mvp" / "twins" / "static" / "cfo.html").read_text(encoding="utf-8")
        assert "Oracle-backed financial rings" in ceo_text
        assert "Oracle-first finance cockpit" in cfo_text
    finally:
        _restore_env(original)


def test_phase15_validation_endpoint_blocks_when_rollout_gates_are_not_ready(tmp_path: Path):
    original = _apply_env(_phase15_env(tmp_path, rollout_ready=False))
    try:
        response = client.post(
            "/finance/oracle/validate",
            headers=_auth("reviewer-secret"),
            json={**_validation_payload(), "approval_status": "pending"},
        )

        assert response.status_code == 409
        body = response.json()
        assert body["status"] == "blocked"
        assert body["rollout_controls"]["passed"] is False
        assert "rollout_controls" in body["readiness"]["failed_checks"]
        assert "reviewer_approval" in body["readiness"]["failed_checks"]
    finally:
        _restore_env(original)


def test_phase15_plan_and_public_copy_mark_final_oracle_completion() -> None:
    plan_data = (ROOT / "strategyos_mvp" / "static" / "plan_data.js").read_text(encoding="utf-8")
    plan_html = (ROOT / "strategyos_mvp" / "static" / "plan.html").read_text(encoding="utf-8")

    assert 'updated: "2026-07-01"' in plan_data
    assert "criticalBlockers: []" in plan_data
    assert "activeActionItems: []" in plan_data
    assert "Foundation through Oracle pilot delivery shipped" in plan_data
    assert "CEO/CFO pilot alignment, production validation, and pilot readiness work" in plan_data
    assert "No active scope remains" in plan_html
    assert "Hosted tracker reflects the active tranche and direct verification" in plan_html
