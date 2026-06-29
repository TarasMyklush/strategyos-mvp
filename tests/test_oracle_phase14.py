from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


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

    assert "active product narrative is now Oracle pilot conformance" in plan_html
    assert "Phases 0–13 complete locally · Phase 14 active focus" in plan_html
    assert "Group CEO Oracle pilot" in executive_html
    assert "twin-platform build remains visible as delivery history" in plan_html
    assert "Twin-platform history remains visible" in executive_data


def test_phase14_plan_data_marks_phase14_complete_without_starting_phase15() -> None:
    text = _read("strategyos_mvp", "static", "plan_data.js")

    phase14_block = text.split('id: "phase-14"', 1)[1].split('id: "phase-15"', 1)[0]
    phase15_block = text.split('id: "phase-15"', 1)[1]

    assert 'updated: "2026-06-29"' in text
    assert 'overallStatus: "in_progress"' in text
    assert 'status: "completed"' in phase14_block
    for story_id in ["14.1", "14.2", "14.3", "14.4", "14.5"]:
        assert f'id: "{story_id}"' in phase14_block
    assert phase14_block.count('status: "completed"') >= 6
    assert 'status: "not_started"' in phase15_block


def test_phase14_no_regressions_on_prior_oracle_phases() -> None:
    text = _read("strategyos_mvp", "static", "plan_data.js")
    phase11_block = text.split('id: "phase-11"', 1)[1].split('id: "phase-12"', 1)[0]
    phase12_block = text.split('id: "phase-12"', 1)[1].split('id: "phase-13"', 1)[0]
    phase13_block = text.split('id: "phase-13"', 1)[1].split('id: "phase-14"', 1)[0]

    assert 'status: "completed"' in phase11_block
    assert 'status: "completed"' in phase12_block
    assert 'status: "completed"' in phase13_block
    assert 'title: "Cash leakage engine"' in phase13_block
