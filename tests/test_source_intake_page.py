from pathlib import Path

import pytest
from fastapi import HTTPException
from strategyos_mvp import api


def test_operator_lane_resolves_to_source_intake(monkeypatch):
    monkeypatch.setattr(api, "_login_or_authorized_html", lambda principal: None)
    response = api.dashboard(lane="operate", principal={"role":"operator"})
    assert response.status_code == 303
    assert response.headers["location"] == "/sources/intake"
    with pytest.raises(HTTPException) as denied:
        api.dashboard(lane="operate", principal={"role":"executive"})
    assert denied.value.status_code == 403


def test_source_intake_is_operator_only_and_noncacheable():
    route = next(r for r in api.app.routes if getattr(r, "path", None) == "/sources/intake")
    dependency = route.dependant.dependencies[0].call
    with pytest.raises(HTTPException) as denied:
        dependency(principal={"role":"executive"})
    assert denied.value.status_code == 403
    assert dependency(principal={"role":"operator"})["role"] == "operator"
    response = api.governed_source_intake_page(principal={"role":"operator"})
    assert response.headers["cache-control"] == "no-store"


def test_intake_uses_safe_rendering_explicit_consent_and_manual_launch():
    static = Path(__file__).resolve().parents[1] / "strategyos_mvp/static"
    script = (static / "source-intake.js").read_text()
    html = (static / "source-intake.html").read_text()
    assert "innerHTML" not in script
    assert "ticket !== generation" in script
    assert "external_model_allowed:false" in script
    assert "quote_allowed:false" in script
    assert "start.addEventListener('click'" in script
    assert 'name="storage_allowed" required' in html
    assert 'id="source-start" type="button" disabled' in html
    assert '/static/claims.css' in html
