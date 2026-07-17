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
    revenue_trend = payload["trend"]["revenue"]
    assert revenue_trend["labels"] == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    assert revenue_trend["actual"] == [
        "72561833.68",
        "56571935.86",
        "67615475.08",
        "68261922.69",
        "56702067.56",
        "63366674.03",
    ]
    assert revenue_trend["plan"] == []
    assert revenue_trend["has_plan_series"] is False
    assert revenue_trend["unit"] == "sar"
    ebitda_margin_trend = payload["trend"]["ebitda_margin"]
    assert ebitda_margin_trend["labels"] == revenue_trend["labels"]
    assert ebitda_margin_trend["actual"] == ["44.06", "38.77", "55.40", "64.10", "60.95", "72.69"]
    assert ebitda_margin_trend["plan"] == []
    assert ebitda_margin_trend["has_plan_series"] is False
    assert ebitda_margin_trend["unit"] == "percent"
    assert payload["dynamics"]["revenue"]["lifting"][0]["delta"].startswith("+SAR ")
    assert "5615726.86" not in payload["dynamics"]["revenue"]["lifting"][0]["delta"]


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
    assert cards[0]["trend"]["actual"]
    assert cards[0]["trend"]["plan"] == []
    assert cards[0]["trend"]["has_plan_series"] is False
    assert cards[0]["missing_inputs"] == ["H1 budget aligned to this reporting scope"]
    assert cards[1]["missing_inputs"] == [
        "H1 EBITDA budget aligned to this scope",
        "H1 revenue budget aligned to this scope",
    ]
    assert cards[3]["missing_inputs"] == [
        "Approved cash floor aligned to this reporting scope",
        "Complete latest cash-position balances",
    ]
    assert [card["executive_brief"]["strategic_reference"] for card in cards] == [None, None, None, None]
    assert [(card["ring_pct"], card["ring_label"]) for card in cards] == [
        (None, ""),
        (56.0, "current margin"),
        (24.4, "of revenue"),
        (None, ""),
    ]
    assert cards[1]["trend"]["unit"] == "percent"
    assert cards[1]["trend"]["actual"] == [44.06, 38.77, 55.4, 64.1, 60.95, 72.69]
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
    assert cards[2]["executive_brief"]["readout"] == (
        "The current actual is available, but a CEO performance conclusion is not yet safe."
    )
    assert cards[2]["executive_brief"]["executive_signal"]["posture"] == "Comparison pending"
    assert "Group CFO" in cards[2]["executive_brief"]["decision_context"]
    assert cards[2]["executive_brief"]["drivers"][0]["label"] == "Salaries & Wages"
    assert cards[2]["executive_brief"]["decision_context"].startswith("Keep this with the Group CFO")


def _write_reconciliation(path: Path, *, division_2026f: str = "775") -> None:
    """A minimal division-to-group reconciliation, matching the real file's shape."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Division_to_Group"
    ws.append(["SAR M", "2023A", "2024A", "2025A", "2026F"])
    ws.append(["Central Region division net revenue (this ERP dataset)", 590, 633, 697, division_2026f])
    ws.append(["Tamween Pharma Distribution BU total", 1940, 2120, 2340, 2540])
    wb.save(path)


def test_reconciliation_plan_derives_the_aligned_h1_budget(tmp_path):
    """The dataset carries a division 2026F forecast; the H1 plan is half of it.

    This is the fix for the live "plan comparison unavailable" -- the budget was
    there all along in the reconciliation file, just never read.
    """
    from strategyos_mvp.source_finance_kpis import _reconciliation_plan

    _write_reconciliation(tmp_path / "Division_to_Group_Reconciliation.xlsx")
    plan = _reconciliation_plan(tmp_path, "H1 2026")
    assert plan is not None
    # 775M annual x 0.5 for H1
    assert plan["revenue_plan"] == "387500000.00"
    assert plan["basis"]["forecast_column"] == "2026F"
    assert plan["basis"]["annual_plan_sar"] == "775000000.00"
    assert plan["basis"]["period_fraction"] == "0.5"


def test_plan_is_absent_when_the_dataset_carries_no_reconciliation(tmp_path):
    """No file -> fail closed, exactly as the old dataset does."""
    from strategyos_mvp.source_finance_kpis import _reconciliation_plan

    assert _reconciliation_plan(tmp_path, "H1 2026") is None


def test_plan_is_absent_for_a_period_it_cannot_align(tmp_path):
    """An unknown period shape must not silently borrow the H1 halving."""
    from strategyos_mvp.source_finance_kpis import _reconciliation_plan

    _write_reconciliation(tmp_path / "Division_to_Group_Reconciliation.xlsx")
    assert _reconciliation_plan(tmp_path, "mystery period") is None
    # A different year has no matching forecast column.
    assert _reconciliation_plan(tmp_path, "H1 2029") is None


def test_a_full_year_period_takes_the_whole_plan_not_half(tmp_path):
    from strategyos_mvp.source_finance_kpis import _reconciliation_plan

    _write_reconciliation(tmp_path / "Division_to_Group_Reconciliation.xlsx")
    plan = _reconciliation_plan(tmp_path, "FY 2026")
    assert plan["revenue_plan"] == "775000000.00"
    assert plan["basis"]["period_fraction"] == "1"


def test_existing_dataset_without_a_plan_still_reports_none():
    """The shared fixture has no reconciliation file: plan must stay None."""
    payload = derive_source_finance_kpis(DATASET)
    assert payload["components"]["revenue_plan"] is None
    assert payload["trend"]["revenue"]["has_plan_series"] is False
