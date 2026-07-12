from __future__ import annotations

from pathlib import Path
import re

import strategyos_mvp.api as api_module


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
    # executive_design_data.js was deleted (UI DB-purity): the executive
    # surface no longer ships a client-side fixture, so only the twins CEO
    # page assertions remain meaningful here.
    ceo_text = _read("strategyos_mvp", "twins", "static", "ceo.html")

    assert "Oracle-backed financial rings" in ceo_text
    assert "deterministic Oracle pilot outputs" in ceo_text
    assert "Revenue attainment ring" in ceo_text
    assert "EBITDA margin ring" in ceo_text


def test_phase14_operational_items_are_marked_manual_or_deferred() -> None:
    ceo_text = _read("strategyos_mvp", "twins", "static", "ceo.html")
    cfo_text = _read("strategyos_mvp", "twins", "static", "cfo.html")

    for expected in ["Cold-chain", "e-Rx", "LfL", "occupancy"]:
        assert expected in ceo_text or expected in cfo_text
    assert "manual / deferred" in ceo_text
    assert "manual / deferred" in cfo_text


def test_phase14_public_copy_stays_consistent_with_oracle_pilot_state() -> None:
    plan_html = _read("strategyos_mvp", "static", "plan.html")
    executive_html = _read("strategyos_mvp", "static", "executive.html")

    assert "Live tracker" in plan_html
    assert "Loading governed execution tracker truth" in plan_html
    assert "fetch('/api/plan/latest')" in plan_html
    assert "/static/plan_data.js" not in plan_html
    assert "Group CEO Diagnostics" in executive_html
    assert "window payload as execution truth" in _plan_data()
    assert "Diagnostics" in executive_html
    assert "Assistants" in executive_html
    assert "Knowledge" in executive_html
    assert "The group index" in executive_html
    assert "Decision questions" in executive_html


def test_phase14_plan_data_marks_phase14_complete_after_phase15_closes() -> None:
    text = _plan_data()
    payload = api_module._plan_tracker_payload()

    assert "window.STRATEGYOS_PLAN" not in text
    assert "window payload as execution truth" in text
    assert payload["backlog"]["summary"] == "Only real remaining work belongs here; static narrative is not used as tracker truth."
    assert payload["completedHistory"] == []


def test_phase14_no_regressions_on_prior_oracle_phases() -> None:
    text = _plan_data()
    payload = api_module._plan_tracker_payload()

    assert "window payload as execution truth" in text
    assert payload["hostedVerificationState"]["checks"][0]["label"] == "Database-backed run store availability"
    assert payload["hostedVerificationState"]["checks"][1]["label"] == "Latest governed run visibility"
