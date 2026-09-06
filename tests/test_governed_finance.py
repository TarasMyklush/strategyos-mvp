from __future__ import annotations

from strategyos_mvp.executive_presentation import build_executive_presentation
from strategyos_mvp.executive_read_model import build_executive_read_model
from strategyos_mvp.governed_finance import finance_payload_from_claim_snapshot


def _claim(component_key: str, value: str, *, kind: str = "actual") -> dict:
    return {
        "claim_revision_id": f"revision-{component_key}",
        "family_key": f"family-{component_key}",
        "label": f"{component_key} {kind}",
        "claim_kind": kind,
        "metric_key": f"ceo.{component_key}",
        "value": value,
        "scale": "1",
        "unit": "SAR",
        "currency": "SAR",
        "period_start": "2026-01-01",
        "period_end": "2026-06-30",
        "traceability": "present",
        "dimensions": {"component_key": component_key},
        "sources": [
            {
                "source_key": "erp-finance",
                "origin_category": "internal_system",
                "locator": f"finance.csv:{component_key}",
            }
        ],
    }


def test_snapshot_overlay_removes_unauthorized_legacy_headline_values():
    legacy = {
        "authoritative": True,
        "derived_from": "deterministic_source_finance_kpi_engine",
        "components": {
            "revenue_actual": "999999999",
            "revenue_plan": "888888888",
            "operating_cost_actual": "777777777",
        },
        "trend": {"revenue": {"actual": [1, 2], "plan": [1, 2]}},
    }
    result = finance_payload_from_claim_snapshot(
        legacy,
        {
            "snapshot_id": "snapshot-1",
            "snapshot_key": "run:run-1",
            "analysis_as_of": "2026-07-01T00:00:00+00:00",
            "policy_version": "source-claim-v1",
            "denied_count": 2,
            "records": [_claim("revenue_actual", "100")],
        },
    )

    assert result["components"] == {"revenue_actual": "100"}
    assert result["components"].get("revenue_plan") is None
    assert result["components"].get("operating_cost_actual") is None
    assert result["trend"] == legacy["trend"]
    assert result["claim_snapshot"]["denied_count"] == 2
    assert result["component_claims"]["revenue_actual"]["claim_revision_id"] == "revision-revenue_actual"


def test_governed_snapshot_drives_cards_and_discloses_claim_lineage():
    legacy = {
        "authoritative": True,
        "derived_from": "deterministic_source_finance_kpi_engine",
        "reporting_period_key": "H1 2026",
        "components": {},
        "evidence": {"revenue": {"files": ["finance.csv"]}},
    }
    finance = finance_payload_from_claim_snapshot(
        legacy,
        {
            "snapshot_id": "snapshot-1",
            "snapshot_key": "run:run-1",
            "analysis_as_of": "2026-07-01T00:00:00+00:00",
            "policy_version": "source-claim-v1",
            "records": [
                _claim("revenue_actual", "100"),
                _claim("revenue_plan", "95", kind="plan"),
            ],
        },
        reconciliation={"status": "passed", "difference_sar": "0"},
    )
    read_model = build_executive_read_model(
        {
            "run_id": "run-1",
            "finance_kpi": finance,
            "claim_snapshot": finance["claim_snapshot"],
            "claim_reconciliation": finance["claim_reconciliation"],
            "canonical_claim_status": "ready",
        },
        [],
        {},
        {"report_count": 0},
        {},
    )
    cards = build_executive_presentation(read_model)["driver_grid"]
    revenue = cards[0]

    assert revenue["metric"] == "SAR 100"
    assert revenue["pct"] == 105.3
    assert revenue["provenance"]["source"] == "governed claim ledger"
    assert revenue["provenance"]["snapshot_id"] == "snapshot-1"
    assert revenue["provenance"]["reconciliation_status"] == "passed"
    assert revenue["provenance"]["actual_claim"]["claim_revision_id"] == "revision-revenue_actual"
    assert revenue["provenance"]["comparison_claim"]["claim_revision_id"] == "revision-revenue_plan"
    assert read_model["canonical_claim_status"] == "ready"


def test_partial_reconciliation_never_renders_as_evidence_verified():
    finance = finance_payload_from_claim_snapshot(
        {
            "authoritative": True,
            "derived_from": "deterministic_source_finance_kpi_engine",
            "reporting_period_key": "H1 2026",
            "components": {},
        },
        {
            "snapshot_id": "snapshot-partial",
            "snapshot_key": "run:run-partial",
            "analysis_as_of": "2026-07-01T00:00:00+00:00",
            "policy_version": "source-claim-v1",
            "records": [
                _claim("revenue_actual", "100"),
                _claim("revenue_plan", "95", kind="plan"),
            ],
        },
        reconciliation={"status": "partial", "difference_sar": "10"},
    )
    card = build_executive_presentation(
        build_executive_read_model(
            {"run_id": "run-partial", "finance_kpi": finance},
            [],
            {},
            {"report_count": 0},
            {},
        )
    )["driver_grid"][0]

    assert card["grounding"]["status"] == "needs_evidence"
    assert "Passed canonical claim reconciliation" in card["missing_inputs"]
    assert "not passed reconciliation" in card["detail"]
