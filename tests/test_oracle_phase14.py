from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def _plan_data() -> str:
    return _read("strategyos_mvp", "static", "plan_data.js")


def _completed_history_block(text: str, done_id: str) -> str:
    pattern = rf'id: "{re.escape(done_id)}"[\s\S]*?(?=\n\s*{{\n\s*id: "DONE-|\n\s*]\n\s*}};|$)'
    match = re.search(pattern, text)
    assert match is not None, f"Missing completed history block {done_id}"
    return match.group(0)


def test_phase14_cfo_surface_is_oracle_first() -> None:
    text = _read("strategyos_mvp", "twins", "static", "cfo.html")

    assert "Oracle-first finance cockpit" in text
    assert "Oracle ingestion &amp; reconciliation context" in text
    assert "Deterministic Oracle-backed pilot KPIs" in text
    assert "Revenue attainment" in text
    assert "EBITDA margin" in text
    assert "Cash vs board floor" in text


def test_phase14_ceo_surface_reflects_oracle_backed_finance_rings() -> None:
    ceo_text = _read("strategyos_mvp", "twins", "static", "ceo.html")
    executive_data = _read("strategyos_mvp", "static", "executive_design_data.js")

    assert "Oracle-backed financial rings" in ceo_text
    assert "deterministic Oracle pilot outputs" in ceo_text
    assert "Revenue attainment ring" in ceo_text
    assert "EBITDA margin ring" in ceo_text
    assert "Oracle-backed finance rings now drive the CEO surface" in executive_data
    assert "Oracle-backed · deterministic" in executive_data


def test_phase14_operational_items_are_marked_manual_or_deferred() -> None:
    ceo_text = _read("strategyos_mvp", "twins", "static", "ceo.html")
    cfo_text = _read("strategyos_mvp", "twins", "static", "cfo.html")
    executive_data = _read("strategyos_mvp", "static", "executive_design_data.js")

    for expected in ["Cold-chain", "e-Rx", "LfL", "occupancy"]:
        assert expected in ceo_text or expected in cfo_text or expected in executive_data
    assert "manual / deferred" in ceo_text
    assert "manual / deferred" in cfo_text
    assert "manual / deferred" in executive_data


def test_phase14_public_copy_stays_consistent_with_oracle_pilot_state() -> None:
    plan_html = _read("strategyos_mvp", "static", "plan.html")
    executive_html = _read("strategyos_mvp", "static", "executive.html")
    executive_data = _read("strategyos_mvp", "static", "executive_design_data.js")

    assert "Live tracker" in plan_html
    assert "No active scope remains" in plan_html
    assert "Group CEO Diagnostics" in executive_html
    assert "Foundation through Oracle pilot delivery shipped" in _plan_data()
    assert "Twin-platform history remains visible" in executive_data
    assert "Diagnostics" in executive_html
    assert "Assistants" in executive_html
    assert "Knowledge" in executive_html
    assert "The group index" in executive_html
    assert "Explore scenarios" in executive_html


def test_phase14_plan_data_marks_phase14_complete_after_phase15_closes() -> None:
    text = _plan_data()
    foundation_block = _completed_history_block(text, "DONE-005")

    assert 'updated: "2026-07-05"' in text
    assert "criticalBlockers: []" in text
    assert "activeActionItems: []" in text
    assert 'id: "DONE-010"' in text
    assert "Oracle EBS ingestion, deterministic KPI calculation, and cash-leakage detection" in foundation_block
    assert "CEO/CFO pilot alignment, production validation, and pilot readiness work" in foundation_block


def test_phase14_no_regressions_on_prior_oracle_phases() -> None:
    text = _plan_data()
    reviewed_backend_block = _completed_history_block(text, "DONE-001")
    tracker_truth_block = _completed_history_block(text, "DONE-004")

    assert "Oracle month-name period resolution fixed for real monthly Oracle labels" in reviewed_backend_block
    assert "Oracle pilot flag enforced before write acceptance" in reviewed_backend_block
    assert "Oracle roadmap closure retained in delivery history" in tracker_truth_block
