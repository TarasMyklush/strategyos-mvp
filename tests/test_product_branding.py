"""Public-brand contract for the Kyvern product surface.

The implementation deliberately retains ``strategyos`` technical identifiers for
backward-compatible routes, storage keys, database objects and deployment
configuration.  This contract is limited to copy a person can see or hear.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from strategyos_mvp import api as api_module
from strategyos_mvp import idp as idp_module
from strategyos_mvp.executive_design import EXECUTIVE_DESIGN


STATIC_DIR = Path(api_module.STATIC_DIR)
PUBLIC_HTML = (
    "architecture.html",
    "architecture-business.html",
    "architecture-technical.html",
    "claim-intake.html",
    "claim-recalculation.html",
    "claims.html",
    "executive.html",
    "guide.html",
    "home.html",
    "index.html",
    "plan.html",
    "source-intake.html",
)


def test_static_html_uses_kyvern_brand_without_legacy_visible_name() -> None:
    for filename in PUBLIC_HTML:
        text = (STATIC_DIR / filename).read_text(encoding="utf-8")
        assert "StrategyOS" not in text, filename

    executive = (STATIC_DIR / "executive.html").read_text(encoding="utf-8")
    assert "Kyvern — Group CEO Briefing" in executive
    assert 'aria-label="Kyvern home"' in executive
    assert '<span class="brand-name">Kyvern</span>' in executive


def test_public_routes_and_identity_page_render_kyvern() -> None:
    client = TestClient(api_module.app)
    bootstrap_marker = '<script id="strategyos-executive-bootstrap" type="application/json">'
    for route in (
        "/",
        "/app",
        "/dashboard",
        "/executive",
        "/guide",
        "/architecture",
        "/architecture/business",
        "/architecture/technical",
    ):
        response = client.get(route)
        assert response.status_code == 200, route
        assert "Kyvern" in response.text, route
        visible_markup = response.text
        if bootstrap_marker in response.text:
            before, _, remainder = response.text.partition(bootstrap_marker)
            bootstrap_json, closing, after = remainder.partition("</script>")
            assert closing, route
            assert json.loads(bootstrap_json)["product_name"] == "Kyvern", route
            # Runtime paths and compatibility identifiers inside bootstrap remain
            # unchanged; only the rendered product name is part of this contract.
            visible_markup = before + after
        assert "StrategyOS" not in visible_markup, route


def test_persona_document_titles_are_kyvern_branded() -> None:
    personas = EXECUTIVE_DESIGN["personas"]
    assert personas
    for persona_id, persona in personas.items():
        title = persona["documentTitle"]
        assert title.startswith("Kyvern — "), persona_id
        assert "StrategyOS" not in title, persona_id


def test_identity_provider_uses_kyvern_brand() -> None:
    response = TestClient(idp_module.app).get("/login")
    assert response.status_code == 200
    assert "Sign in to Kyvern" in response.text
    assert "authorized Kyvern account" in response.text
    assert "StrategyOS" not in response.text


def test_favicon_accessibility_name_and_glyph_are_kyvern_specific() -> None:
    favicon = (STATIC_DIR / "favicon.svg").read_text(encoding="utf-8")
    assert 'aria-label="Kyvern"' in favicon
    assert "M18 13h9v15" in favicon
    assert "M18 22c0-5" not in favicon


def test_runtime_copy_uses_kyvern_while_technical_identifiers_stay_stable() -> None:
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    executive_js = (STATIC_DIR / "executive.js").read_text(encoding="utf-8")
    twin_js = (STATIC_DIR / "twin_live.js").read_text(encoding="utf-8")

    assert "Kyvern copilot" in app_js
    assert "waiting for Kyvern worker" in app_js
    assert "Ask Kyvern to prepare something" in executive_js
    assert "checking live Kyvern data" in twin_js

    # Existing browser sessions and integrations must survive a display-name change.
    assert '"strategyos.ui.token"' in app_js
    assert '"strategyos.ui.token"' in executive_js
    assert "window.STRATEGYOS_X" in executive_js
