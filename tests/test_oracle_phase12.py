from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from strategyos_mvp.oracle_finance import (
    _resolve_period_bounds,
    BUFlexfieldMappingConfig,
    build_oracle_kpi_narration_payload,
    compute_oracle_pilot_kpis,
    ingest_oracle_pilot_extracts,
    load_pilot_extract_batch,
)


def _mapping() -> BUFlexfieldMappingConfig:
    return BUFlexfieldMappingConfig(
        segment_name="segment2",
        segment_index=1,
        value_to_bu={"BU01": "Consumer", "BU02": "Healthcare"},
        default_bu="Corporate",
    )


def test_phase12_core_profit_liquidity_working_capital_and_leverage_formulas_are_deterministic():
    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(
            {
                "GL": [
                    {
                        "natural_key": "gl-revenue-1",
                        "fact_type": "revenue",
                        "amount": "1000",
                        "currency": "SAR",
                        "period_name": "2026-06",
                        "period_start": "2026-06-01",
                        "period_end": "2026-06-30",
                        "flexfield_segments": ["COMP", "BU01", "CC100"],
                    },
                    {
                        "natural_key": "gl-ebitda-1",
                        "fact_type": "ebitda",
                        "amount": "250",
                        "currency": "SAR",
                        "period_name": "2026-06",
                        "period_start": "2026-06-01",
                        "period_end": "2026-06-30",
                        "flexfield_segments": ["COMP", "BU01", "CC100"],
                    },
                    {
                        "natural_key": "gl-opex-1",
                        "fact_type": "operating_cost",
                        "amount": "600",
                        "currency": "SAR",
                        "period_name": "2026-06",
                        "period_start": "2026-06-01",
                        "period_end": "2026-06-30",
                        "flexfield_segments": ["COMP", "BU01", "CC100"],
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
                        "natural_key": "ap-balance-1",
                        "fact_type": "accounts_payable_balance",
                        "amount": "90",
                        "currency": "SAR",
                        "event_date": "2026-06-30",
                        "flexfield_segments": ["COMP", "BU02", "CC220"],
                    },
                    {
                        "natural_key": "ap-debt-1",
                        "fact_type": "debt_balance",
                        "amount": "500",
                        "currency": "SAR",
                        "event_date": "2026-06-30",
                        "flexfield_segments": ["COMP", "BU02", "CC220"],
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
                "INV": [
                    {
                        "natural_key": "inv-balance-1",
                        "fact_type": "inventory_balance",
                        "amount": "75",
                        "currency": "SAR",
                        "event_date": "2026-06-27",
                        "cadence": "weekly",
                        "flexfield_segments": ["COMP", "BU02", "CC220"],
                    }
                ],
            }
        ),
        bu_mapping=_mapping(),
        manual_inputs=[
            {
                "input_key": "budget-june",
                "input_type": "budget_plan",
                "input_name": "June budget",
                "storage_kind": "file",
                "period_key": "2026-06",
                "metrics": {
                    "revenue": "800",
                    "ebitda": "200",
                    "operating_cost": "500",
                },
            },
            {
                "input_key": "board-floor-june",
                "input_type": "board_floor",
                "input_name": "June floor",
                "storage_kind": "manual",
                "period_key": "2026-06-30",
                "board_floor": "100",
            },
            {
                "input_key": "covenant-pack-q2",
                "input_type": "covenant_terms",
                "input_name": "Q2 covenant pack",
                "storage_kind": "file",
                "period_key": "2026-Q2",
                "terms": {"max_net_debt_to_ebitda": "3.0"},
            },
            {
                "input_key": "commentary-june",
                "input_type": "commentary",
                "input_name": "June commentary",
                "storage_kind": "manual",
                "period_key": "2026-06",
                "note": "Narration belongs downstream.",
            },
        ],
    )

    computation = compute_oracle_pilot_kpis(snapshot, reporting_period_key="2026-06")

    assert computation.authoritative is True
    assert computation.reporting_cadence == "monthly"
    assert computation.period_days == 30
    assert computation.manual_input_keys == (
        "budget-june",
        "board-floor-june",
        "covenant-pack-q2",
    )
    assert computation.metrics["revenue_attainment_pct"] == Decimal("125")
    assert computation.metrics["ebitda_margin_pct"] == Decimal("25.00")
    assert computation.metrics["ebitda_attainment_pct"] == Decimal("125")
    assert computation.metrics["operating_cost_pct_of_plan"] == Decimal("120")
    assert computation.metrics["cash_vs_board_floor_pct"] == Decimal("120")
    assert computation.metrics["cash_floor_headroom"] == Decimal("20")
    assert computation.metrics["dso_days"] == Decimal("4.50")
    assert computation.metrics["dpo_days"] == Decimal("4.50")
    assert computation.metrics["dio_days"] == Decimal("3.75")
    assert computation.metrics["ccc_days"] == Decimal("3.75")
    assert computation.components["net_debt"] == Decimal("380")
    assert computation.metrics["net_debt_to_ebitda"] == Decimal("1.52")
    assert computation.metrics["covenant_headroom"] == Decimal("1.48")


def test_phase12_working_capital_respects_weekly_cadence_and_period_days():
    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(
            {
                "GL": [
                    {
                        "natural_key": "gl-revenue-week",
                        "fact_type": "revenue",
                        "amount": "700",
                        "currency": "SAR",
                        "period_key": "2026-W26",
                        "cadence": "weekly",
                        "period_start": "2026-06-22",
                        "period_end": "2026-06-28",
                    },
                    {
                        "natural_key": "gl-opex-week",
                        "fact_type": "operating_cost",
                        "amount": "350",
                        "currency": "SAR",
                        "period_key": "2026-W26",
                        "cadence": "weekly",
                        "period_start": "2026-06-22",
                        "period_end": "2026-06-28",
                    },
                ],
                "AR": [
                    {
                        "natural_key": "ar-balance-week",
                        "fact_type": "accounts_receivable_balance",
                        "amount": "210",
                        "currency": "SAR",
                        "event_date": "2026-06-28",
                    }
                ],
                "AP": [
                    {
                        "natural_key": "ap-balance-week",
                        "fact_type": "accounts_payable_balance",
                        "amount": "140",
                        "currency": "SAR",
                        "event_date": "2026-06-28",
                    }
                ],
                "INV": [
                    {
                        "natural_key": "inv-balance-week",
                        "fact_type": "inventory_balance",
                        "amount": "70",
                        "currency": "SAR",
                        "event_date": "2026-06-28",
                    }
                ],
            }
        ),
        bu_mapping=_mapping(),
    )

    computation = compute_oracle_pilot_kpis(
        snapshot,
        reporting_period_key="2026-W26",
        reporting_cadence="weekly",
    )

    assert computation.period_days == 7
    assert computation.metrics["dso_days"] == Decimal("2.1")
    assert computation.metrics["dpo_days"] == Decimal("2.8")
    assert computation.metrics["dio_days"] == Decimal("1.4")
    assert computation.metrics["ccc_days"] == Decimal("0.7")


def test_phase12_oracle_month_names_resolve_full_month_and_match_iso_reporting_period():
    assert _resolve_period_bounds("JUN-26", "monthly") == (date(2026, 6, 1), date(2026, 6, 30))
    assert _resolve_period_bounds("June-26", "monthly") == (date(2026, 6, 1), date(2026, 6, 30))
    assert _resolve_period_bounds("Jun-26 Adj", "monthly") == (date(2026, 6, 1), date(2026, 6, 30))

    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(
            {
                "GL": [
                    {"natural_key": "gl-revenue-june-26", "fact_type": "revenue", "amount": "3000", "period_name": "June-26"},
                    {"natural_key": "gl-ebitda-jun-adj", "fact_type": "ebitda", "amount": "600", "period_name": "Jun-26 Adj"},
                    {"natural_key": "gl-opex-jun-26", "fact_type": "operating_cost", "amount": "1500", "period_name": "JUN-26"},
                ],
                "AR": [{"natural_key": "ar-jun-26", "fact_type": "accounts_receivable_balance", "amount": "300", "event_date": "2026-06-30"}],
                "AP": [
                    {"natural_key": "ap-balance-jun-26", "fact_type": "accounts_payable_balance", "amount": "450", "event_date": "2026-06-30"},
                    {"natural_key": "ap-debt-jun-26", "fact_type": "debt_balance", "amount": "400", "event_date": "2026-06-30"},
                ],
                "INV": [{"natural_key": "inv-jun-26", "fact_type": "inventory_balance", "amount": "150", "event_date": "2026-06-30", "cadence": "daily"}],
                "CE": [{"natural_key": "ce-jun-26", "fact_type": "cash_balance", "amount": "100", "as_of_date": "2026-06-30"}],
            }
        ),
        bu_mapping=_mapping(),
        reporting_currency="SAR",
    )

    computation = compute_oracle_pilot_kpis(snapshot, reporting_period_key="2026-06")

    assert computation.period_days == 30
    assert computation.components["revenue_actual"] == Decimal("3000")
    assert computation.components["ebitda_actual"] == Decimal("600")
    assert computation.metrics["dso_days"] == Decimal("3.0")
    assert computation.metrics["dpo_days"] == Decimal("9.0")
    assert computation.metrics["dio_days"] == Decimal("3.0")
    assert computation.metrics["ccc_days"] == Decimal("-3.0")


def test_phase12_negative_or_near_zero_ebitda_does_not_emit_leverage_or_covenant_headroom():
    covenant_input = {
        "input_key": "covenant-q2",
        "input_type": "covenant_terms",
        "input_name": "Q2 covenant",
        "storage_kind": "file",
        "period_key": "2026-Q2",
        "terms": {"max_net_debt_to_ebitda": "3.0"},
    }
    negative_snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(
            {
                "GL": [{"natural_key": "gl-ebitda-negative", "fact_type": "ebitda", "amount": "-10", "period_name": "2026-06"}],
                "AP": [{"natural_key": "ap-debt-negative", "fact_type": "debt_balance", "amount": "500", "event_date": "2026-06-30"}],
                "CE": [{"natural_key": "ce-cash-negative", "fact_type": "cash_balance", "amount": "100", "as_of_date": "2026-06-30"}],
            }
        ),
        bu_mapping=_mapping(),
        manual_inputs=[covenant_input],
    )
    near_zero_snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(
            {
                "GL": [{"natural_key": "gl-ebitda-near-zero", "fact_type": "ebitda", "amount": "0.001", "period_name": "2026-06"}],
                "AP": [{"natural_key": "ap-debt-near-zero", "fact_type": "debt_balance", "amount": "500", "event_date": "2026-06-30"}],
                "CE": [{"natural_key": "ce-cash-near-zero", "fact_type": "cash_balance", "amount": "100", "as_of_date": "2026-06-30"}],
            }
        ),
        bu_mapping=_mapping(),
        manual_inputs=[covenant_input],
    )

    negative = compute_oracle_pilot_kpis(negative_snapshot, reporting_period_key="2026-06")
    near_zero = compute_oracle_pilot_kpis(near_zero_snapshot, reporting_period_key="2026-06")

    assert negative.metrics["net_debt_to_ebitda"] is None
    assert negative.metrics["covenant_headroom"] is None
    assert near_zero.metrics["net_debt_to_ebitda"] is None
    assert near_zero.metrics["covenant_headroom"] is None


def test_phase12_manual_month_inputs_with_oracle_period_names_match_iso_reporting_period():
    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(
            {
                "GL": [
                    {"natural_key": "gl-revenue-jun-26", "fact_type": "revenue", "amount": "300", "period_name": "JUN-26"},
                    {"natural_key": "gl-ebitda-jun-26", "fact_type": "ebitda", "amount": "60", "period_name": "JUN-26"},
                ]
            }
        ),
        bu_mapping=_mapping(),
        manual_inputs=[
            {
                "input_key": "budget-june",
                "input_type": "budget_plan",
                "input_name": "June budget",
                "storage_kind": "file",
                "period_key": "June-26",
                "revenue": "250",
                "ebitda": "50",
            }
        ],
    )

    computation = compute_oracle_pilot_kpis(snapshot, reporting_period_key="2026-06")

    assert computation.components["revenue_plan"] == Decimal("250")
    assert computation.components["ebitda_plan"] == Decimal("50")
    assert computation.metrics["revenue_attainment_pct"] == Decimal("120")
    assert computation.metrics["ebitda_attainment_pct"] == Decimal("120")


def test_phase12_narration_payload_is_explicitly_downstream_and_non_authoritative():
    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(
            {
                "GL": [
                    {
                        "natural_key": "gl-revenue-1",
                        "fact_type": "revenue",
                        "amount": "100",
                        "currency": "SAR",
                        "period_name": "2026-06",
                        "period_start": "2026-06-01",
                        "period_end": "2026-06-30",
                    },
                    {
                        "natural_key": "gl-ebitda-1",
                        "fact_type": "ebitda",
                        "amount": "20",
                        "currency": "SAR",
                        "period_name": "2026-06",
                        "period_start": "2026-06-01",
                        "period_end": "2026-06-30",
                    },
                ]
            }
        ),
        bu_mapping=_mapping(),
        manual_inputs=[
            {
                "input_key": "budget-june",
                "input_type": "budget_plan",
                "input_name": "June budget",
                "storage_kind": "file",
                "period_key": "2026-06",
                "revenue": "80",
                "ebitda": "16",
            },
            {
                "input_key": "commentary-june",
                "input_type": "commentary",
                "input_name": "June commentary",
                "storage_kind": "manual",
                "period_key": "2026-06",
                "headline": "Narrative should never change the formula output.",
            },
        ],
    )

    computation = compute_oracle_pilot_kpis(snapshot, reporting_period_key="2026-06")
    commentary_inputs = [record for record in snapshot.manual_inputs if record.input_type == "commentary"]
    narration = build_oracle_kpi_narration_payload(computation, commentary_inputs=commentary_inputs)

    assert computation.metrics["revenue_attainment_pct"] == Decimal("125")
    assert narration["authoritative"] is False
    assert narration["derived_from"] == "deterministic_oracle_kpi_engine"
    assert narration["metric_values"]["revenue_attainment_pct"] == "125"
    assert narration["commentary_inputs"][0]["input_key"] == "commentary-june"
    assert "fixed computed numbers" in narration["instructions"]


def test_phase12_plan_data_keeps_completed_oracle_phases_truthful_during_hosted_follow_through():
    plan_file = (
        Path(__file__).resolve().parents[1]
        / "strategyos_mvp"
        / "static"
        / "plan_data.js"
    )
    text = plan_file.read_text(encoding="utf-8")
    assert 'updated: "2026-06-30"' in text
    assert 'Foundation through Oracle pilot delivery shipped' in text
    assert 'Oracle EBS ingestion, deterministic KPI calculation, and cash-leakage detection.' in text
    assert 'id: "DONE-007"' in text
    assert 'Earlier live deploy tranche landed and was re-verified' in text
    assert 'Hosted /public/runs/latest/audit-summary now returns the sanitized public-safe payload' in text
