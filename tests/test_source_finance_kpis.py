from __future__ import annotations

from pathlib import Path

from strategyos_mvp.executive_presentation import build_executive_presentation
from strategyos_mvp.executive_read_model import build_executive_read_model
from strategyos_mvp.source_finance_kpis import derive_source_finance_kpis


DATASET = Path(__file__).parent / "fixtures" / "01_Synthetic_Dataset"


def test_source_pack_calculates_four_ceo_actuals_with_lineage():
    payload = derive_source_finance_kpis(DATASET)

    assert payload["authoritative"] is True
    assert payload["derived_from"] == "deterministic_source_finance_kpi_engine"
    assert payload["reporting_period_key"] == "H1 2026"
    assert payload["components"] == {
        "revenue_actual": "385079908.90",
        "revenue_plan": None,
        "cogs_actual": "75503688.29",
        "ebitda_actual": "215741310.56",
        "ebitda_plan": None,
        "operating_cost_actual": "93834910.05",
        "operating_cost_plan": None,
        "cash_balance": "42341408.58",
        "board_floor": None,
    }
    assert payload["evidence"]["revenue"]["details"]["account_scopes"]["revenue"]["accounts"] == [
        "4000", "4010", "4020", "4030"
    ]
    revenue_drivers = payload["evidence"]["revenue"]["details"]["contributors"]["revenue"]
    assert [(item["label"], item["value_sar"], item["share_pct"]) for item in revenue_drivers] == [
        ("Revenue – Catering", "123016434.85", 31.9),
        ("Revenue – Government", "109896978.70", 28.5),
        ("Revenue – Modern Trade", "103168943.62", 26.8),
        ("Revenue – Hospitality", "48997551.73", 12.7),
    ]
    assert payload["evidence"]["cash_vs_floor"]["actual_complete"] is False
    assert payload["evidence"]["cash_vs_floor"]["details"]["missing_accounts"] == ["Emirates NBD EUR"]


def test_source_pack_actuals_render_without_inventing_missing_comparators():
    read_model = build_executive_read_model(
        {"run_id": "source-pack-run", "finance_kpi": derive_source_finance_kpis(DATASET)},
        [], {}, {"report_count": 0}, {},
    )
    cards = build_executive_presentation(read_model)["driver_grid"]

    assert [(card["label"], card["metric"]) for card in cards] == [
        ("Revenue", "SAR 385.1M"),
        ("EBITDA margin", "56.0%"),
        ("Operating cost", "SAR 93.8M"),
        ("Cash vs floor", "SAR 42.3M"),
    ]
    assert cards[0]["availability"] == "partial"
    assert cards[0]["missing_inputs"] == ["H1 budget aligned to this reporting scope"]
    assert cards[1]["missing_inputs"] == [
        "H1 EBITDA budget aligned to this scope",
        "H1 revenue budget aligned to this scope",
    ]
    assert cards[3]["missing_inputs"] == [
        "Complete Group cash position aligned to the approved floor",
        "Complete latest cash-position balances",
    ]
    assert cards[0]["executive_brief"]["strategic_reference"]["value"] == "SAR 8.35B"
    assert cards[1]["executive_brief"]["strategic_reference"]["value"] == "23.0%"
    assert cards[3]["executive_brief"]["strategic_reference"]["value"] == "SAR 1.20B"
    assert [(card["ring_pct"], card["ring_label"]) for card in cards] == [
        (4.6, "of FY2026 Group plan"),
        (56.0, "current margin"),
        (24.4, "of revenue"),
        (3.5, "of Group floor · partial scope"),
    ]
    assert cards[0]["source_files"] == [
        "02_ERP_Extracts/GL_Extract_H1_2026.csv",
        "03_Master_Data/Chart_of_Accounts.xlsx",
    ]
    assert "8,479 GL rows" in cards[0]["evidence_summary"]
    assert "missing Emirates NBD EUR" in cards[3]["detail"]
    assert cards[1]["executive_brief"]["calculation"]["steps"] == [
        {"label": "Revenue", "value": "SAR 385.1M"},
        {"label": "Less cost of goods sold", "value": "SAR 75.5M"},
        {"label": "Less operating cost", "value": "SAR 93.8M"},
        {"label": "EBITDA", "value": "SAR 215.7M"},
    ]
    assert cards[2]["executive_brief"]["readout"].startswith("Operating expenditure across 126")
    assert cards[2]["executive_brief"]["drivers"][0]["label"] == "Salaries & Wages"
    assert cards[2]["executive_brief"]["decision_context"].startswith("Current operating cost is available")
