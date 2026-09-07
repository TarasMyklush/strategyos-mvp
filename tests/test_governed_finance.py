from __future__ import annotations

import pytest
from decimal import Decimal

from strategyos_mvp.executive_presentation import build_executive_presentation
from strategyos_mvp.executive_read_model import build_executive_read_model
from strategyos_mvp.governed_finance import finance_payload_from_claim_snapshot


def _claim(component_key: str, value: str, *, kind: str = "actual") -> dict:
    return {
        "claim_revision_id": f"revision-{component_key}",
        "family_key": f"family-{component_key}",
        "label": f"{component_key} {kind}",
        "claim_kind": kind,
        "metric_key": "ceo." + component_key.removesuffix("_actual").removesuffix("_plan"),
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
    assert result["trend"] == {}
    assert result["claim_snapshot"]["denied_count"] == 2
    assert result["component_claims"]["revenue_actual"]["claim_revision_id"] == "revision-revenue_actual"


def _presentation_claim(
    component: str,
    *,
    driver: str,
    series: str,
    label: str,
    value: str,
    order: int = 0,
    unit: str = "SAR",
    business_unit: str | None = None,
    extra_dimensions: dict | None = None,
) -> dict:
    metric = {
        "trend": "ceo.presentation.trend",
        "contributor": "ceo.presentation.contributor",
        "cost_component": "ceo.presentation.cost_component",
    }[component]
    return {
        "claim_revision_id": f"revision-{component}-{driver}-{series}-{label}",
        "family_key": f"family-{component}-{driver}-{series}-{label}",
        "label": label,
        "claim_kind": "actual" if series == "actual" else "plan",
        "metric_key": metric,
        "value": value,
        "scale": "1",
        "unit": unit,
        "currency": "SAR" if unit == "SAR" else None,
        "business_unit": business_unit,
        "period": {"start": "2026-01-01", "end": "2026-01-31"},
        "traceability": "present",
        "dimensions": {
            "presentation_component": component,
            "driver_key": driver,
            "series": series,
            "label": label,
            "order": order,
            **(extra_dimensions or {}),
        },
        "sources": [{"source_key": "erp-finance", "origin_category": "internal_system"}],
    }


def test_presentation_claims_reconstruct_chart_movers_and_cost_detail():
    records = [
        _claim("operating_cost_actual", "120"),
        _claim("operating_cost_plan", "100", kind="plan"),
        _presentation_claim("trend", driver="operating_cost", series="actual", label="2026-01", value="120"),
        _presentation_claim("trend", driver="operating_cost", series="plan", label="2026-01", value="100"),
        _presentation_claim("contributor", driver="operating_cost", series="actual", label="Tamween", value="70", business_unit="Tamween"),
        _presentation_claim("contributor", driver="operating_cost", series="plan", label="Tamween", value="50", business_unit="Tamween"),
        _presentation_claim(
            "cost_component",
            driver="operating_cost",
            series="actual",
            label="People",
            value="45",
            business_unit="Tamween",
            extra_dimensions={"business_unit": "Tamween", "component": "People"},
        ),
        _presentation_claim(
            "cost_component",
            driver="operating_cost",
            series="plan",
            label="People",
            value="40",
            business_unit="Tamween",
            extra_dimensions={"business_unit": "Tamween", "component": "People"},
        ),
    ]
    result = finance_payload_from_claim_snapshot(
        {"reporting_currency": "SAR", "trend": {"operating_cost": {"actual": [999]}}},
        {"records": records},
    )

    assert result["trend"]["operating_cost"] == {
        "labels": ["2026-01"],
        "actual": ["120"],
        "plan": ["100"],
        "has_plan_series": True,
        "unit": "sar",
    }
    assert result["dynamics"]["operating_cost"]["dragging"] == [
        {"name": "Tamween", "delta": "SAR 20 above plan"}
    ]
    assert result["evidence"]["operating_cost"]["details"]["cost_components"]["rows"][0]["variance_sar"] == "5"


def test_presentation_series_cannot_misrepresent_its_claim_kind():
    record = _presentation_claim(
        "trend",
        driver="revenue",
        series="actual",
        label="2026-01",
        value="120",
    )
    record["claim_kind"] = "plan"

    with pytest.raises(ValueError, match="series does not match"):
        finance_payload_from_claim_snapshot({}, {"records": [record]})


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


@pytest.mark.parametrize("changes", [
    {"claim_kind": "forecast"}, {"claim_kind": "plan"},
    {"metric_key": "ceo.operating_cost"}, {"unit": "percent"},
    {"currency": "USD"}, {"scale": "0"}, {"scale": "-1"},
    {"scale": "NaN"}, {"scale": None}, {"value": "NaN"},
    {"value": "Infinity"}, {"value": "unavailable"},
    {"business_unit": "another-unit"}, {"scenario_key": "optimistic"}, {"scenario": "optimistic"},
])
def test_display_contract_rejects_semantic_substitution(changes):
    record = {**_claim("revenue_actual", "100"), **changes}
    with pytest.raises(ValueError):
        finance_payload_from_claim_snapshot({}, {"records": [record]})


def test_display_contract_rejects_ambiguous_component_instead_of_last_write_wins():
    with pytest.raises(ValueError, match="Multiple claims"):
        finance_payload_from_claim_snapshot({}, {"records": [
            _claim("revenue_actual", "100"), _claim("revenue_actual", "200"),
        ]})


def test_display_contract_normalizes_scale_exactly_once():
    record = {**_claim("revenue_actual", "1.25"), "scale": "1000000"}
    result = finance_payload_from_claim_snapshot({}, {"records": [record]})
    assert Decimal(result["components"]["revenue_actual"]) == Decimal("1250000")
    assert result["component_claims"]["revenue_actual"]["value"] == "1.25"


def test_display_contract_does_not_compare_different_periods():
    actual = _claim("revenue_actual", "100")
    plan = {**_claim("revenue_plan", "95", kind="plan"), "period_end": "2026-12-31"}
    with pytest.raises(ValueError, match="periods"):
        finance_payload_from_claim_snapshot({}, {"records": [actual, plan]})


def test_foreign_currency_cannot_be_relabelled_by_the_sar_finance_presentation():
    record = {**_claim("revenue_actual", "100"), "unit": "USD", "currency": "USD"}
    with pytest.raises(ValueError, match="SAR only"):
        finance_payload_from_claim_snapshot({"reporting_currency": "USD"}, {"records": [record]})


def test_unknown_periods_are_not_assumed_to_be_comparable():
    records = [_claim("revenue_actual", "100"), _claim("revenue_plan", "95", kind="plan")]
    for record in records:
        record.pop("period_start")
        record.pop("period_end")
    with pytest.raises(ValueError, match="periods"):
        finance_payload_from_claim_snapshot({}, {"records": records})
