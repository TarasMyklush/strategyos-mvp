"""Historic context must read the dataset's multi-year trend, never invent one."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from strategyos_mvp.source_historic_context import derive_historic_context


def _write_revenue_analytics(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Annual_Summary"
    ws.append(["Year", "Net Revenue (SAR M)", "YoY %", "Commentary"])
    ws.append([2023, 590.0, "—", "Pre-acquisition."])
    ws.append([2024, 633.1, "7.3%", "Acquisition year."])
    ws.append([2025, 697.0, "10.1%", "NUPCO full-year effect."])
    wb.save(path)


def test_reads_the_multi_year_revenue_trend_from_the_dataset(tmp_path):
    _write_revenue_analytics(tmp_path / "Revenue_Analytics_2023-2026.xlsx")
    ctx = derive_historic_context(tmp_path)
    assert ctx["available"] is True
    years = [row["year"] for row in ctx["annual_revenue"]]
    assert years == ["2023", "2024", "2025"]
    assert ctx["annual_revenue"][1]["net_revenue_sar_m"] == 633.1
    assert "Acquisition year" in ctx["annual_revenue"][1]["commentary"]
    assert "Revenue_Analytics_2023-2026.xlsx" in ctx["source_files"]


def test_is_absent_when_the_dataset_carries_no_history(tmp_path):
    ctx = derive_historic_context(tmp_path)
    assert ctx["available"] is False
    assert "no multi-year" in ctx["reason"]


def test_a_single_year_is_not_a_trend(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Annual_Summary"
    ws.append(["Year", "Net Revenue (SAR M)"])
    ws.append([2026, 385.0])
    wb.save(tmp_path / "Revenue_Analytics_2026.xlsx")
    # one year is not a multi-year series
    assert derive_historic_context(tmp_path)["available"] is False


def test_evidence_payload_exposes_history_to_the_model():
    from strategyos_mvp.llm_qa import _historic_context_evidence

    summary = {
        "historic_context": {
            "available": True,
            "basis": "read from strategic files",
            "source_files": ["Revenue_Analytics.xlsx"],
            "annual_revenue": [{"year": "2023", "net_revenue_sar_m": 590.0}],
            "revenue_drivers": [{"driver": "NUPCO award", "impact_sar_m": 52.0}],
        }
    }
    ev = _historic_context_evidence(summary)
    assert ev["available"] is True
    assert ev["annual_revenue"][0]["year"] == "2023"
    # absent history stays absent
    assert _historic_context_evidence({})["available"] is False


def test_prompt_tells_the_model_to_use_history_when_present():
    import strategyos_mvp.llm_qa as m

    prompt = " ".join(m.SYSTEM_PROMPT.split())
    assert "historic_context.available" in prompt
    assert "never say historic data is unavailable while that block is present" in prompt
