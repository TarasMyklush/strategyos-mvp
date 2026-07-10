from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_HTML = ROOT / "strategyos_mvp" / "static" / "plan.html"
PLAN_DATA = ROOT / "strategyos_mvp" / "static" / "plan_data.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_plan_static_fixture_module_is_not_a_truth_source() -> None:
    data = _read(PLAN_DATA)

    assert "window.STRATEGYOS_PLAN" not in data
    assert "window payload as execution truth" in data


def test_plan_page_fetches_governed_api_payload_instead_of_static_truth() -> None:
    html = _read(PLAN_HTML)

    assert '<h1>Execution tracker</h1>' in html
    assert 'href="/guide"' in html
    assert '>Guide</a>' in html
    assert "Loading governed execution tracker truth" in html
    assert "fetch('/api/plan/latest')" in html
    assert "/static/plan_data.js" not in html
    assert "window.STRATEGYOS_PLAN" not in html
    assert 'font-size: clamp(30px, 4vw, 40px);' in html
    assert 'padding: 44px 0 26px;' in html
