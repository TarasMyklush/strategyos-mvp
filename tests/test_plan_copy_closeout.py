from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_HTML = ROOT / "strategyos_mvp" / "static" / "plan.html"
PLAN_DATA = ROOT / "strategyos_mvp" / "static" / "plan_data.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_plan_copy_closeout_has_no_active_plan_scope_rows() -> None:
    data = _read(PLAN_DATA)

    assert 'updated: "2026-07-05"' in data
    assert 'criticalBlockers: []' in data
    assert 'activeActionItems: []' in data
    assert 'Ask Hermes assistant hardening is shipped and live-verified' in data
    assert '1ddd7e1' in data
    assert 'DONE-010' in data
    assert 'Ask Hermes assistant hardening shipped and verified' in data
    assert 'CI succeeded for release 1ddd7e1.' in data
    assert 'Deploy succeeded for release 1ddd7e1.' in data
    assert 'Working tree is clean at release verification time.' in data
    assert 'Live direct /assistant/chat checks passed for margin variance in mode=auto and mode=llm.' in data
    assert "Live browser drawer check passed for 'What’s driving the margin variance?'." in data
    assert 'deterministic finance/scenario routing first and governed LLM fallback' in data
    assert 'provider failures now retain trace metadata instead of silently collapsing into canned copy' in data
    assert 'What’s driving the margin variance?' in data
    assert 'DONE-009' in data
    assert 'Final copy-polish row closed' in data

    action_section = data.split('activeActionItems:', 1)[1].split('hostedVerificationState:', 1)[0]
    blocker_section = data.split('criticalBlockers:', 1)[1].split('activeActionItems:', 1)[0]
    assert 'COPY-001' not in action_section
    assert 'BUG-005' not in action_section
    assert 'UX-001' not in action_section
    assert 'ORACLE-VERIFY' not in action_section
    assert 'SEC-001' not in action_section
    assert 'BLK-001' not in blocker_section
    assert 'BLK-002' not in blocker_section


def test_plan_hero_copy_is_tightened_and_empty_states_are_explicit() -> None:
    html = _read(PLAN_HTML)

    assert '<h1>Execution tracker</h1>' in html
    assert 'href="/guide"' in html
    assert '>Guide</a>' in html
    assert (
        'No active scope remains. The final copy pass is closed, and verified behavior work stays in shipped history.'
        in html
    )
    assert 'font-size: clamp(30px, 4vw, 40px);' in html
    assert 'padding: 44px 0 26px;' in html
    assert 'No critical blockers remain' in html
    assert 'No active action items remain.' in html

    assert 'The page shows only real remaining work and concise shipped history' not in html
    assert 'font-size: clamp(32px, 5vw, 48px);' not in html
