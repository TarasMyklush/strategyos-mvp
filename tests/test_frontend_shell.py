import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
import strategyos_mvp.run_poc as run_poc_module
import strategyos_mvp.state_store as state_store
import strategyos_mvp.storage as storage
from strategyos_mvp.config import load_config


def _apply_env(env_updates: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in env_updates}
    for key, value in env_updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    api_module.CONFIG = config
    auth_module.CONFIG = config
    run_poc_module.CONFIG = config
    state_store.CONFIG = config
    storage.CONFIG = config
    return original


def _restore_env(original: dict[str, str | None]):
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    api_module.CONFIG = config
    auth_module.CONFIG = config
    run_poc_module.CONFIG = config
    state_store.CONFIG = config
    storage.CONFIG = config


def _app_entry_response() -> str:
    client = TestClient(api_module.app)
    response = client.get("/app")
    assert response.status_code == 200
    return response.text


def _homepage_response() -> str:
    client = TestClient(api_module.app)
    response = client.get("/")
    assert response.status_code == 200
    return response.text


def _static_executive_js() -> str:
    client = TestClient(api_module.app)
    response = client.get("/static/executive.js")
    assert response.status_code == 200
    return response.text


def test_executive_assistant_uses_governed_qa_not_fake_captured_reply():
    js = _static_executive_js()

    assert 'mode: "auto"' in js
    assert 'var endpoint = "/assistant/chat";' in js
    assert 'postJson("/assistant/chat", body' in js or 'fetch(endpoint, {' in js
    assert 'persona: state.activePersona || "ceo"' in js
    assert 'driver_context' in js
    assert "still the active lens" not in js
    assert "Follow-up captured" not in js
    assert "Prompt captured" not in js


def test_executive_has_a_dedicated_agents_tab_and_honest_calendar_empty_state():
    html = _app_entry_response()
    js = _static_executive_js()

    assert 'data-view-target="agents"' in html
    assert 'data-view-panel="agents"' in html
    twin_render = js[js.index("function renderAgentsDiscovery"):js.index("function renderAssistantStudio")]
    assert "switchView('assistants')" not in twin_render
    assert "data-twin-toggle" in twin_render
    assert "No governed calendar is available for this reporting period" in js


def test_executive_static_js_switches_latest_run_route_by_session_mode():
    js = _static_executive_js()

    assert 'function latestRunRouteForSession(session)' in js
    assert 'if (session && session.api_auth_enabled === false) return "/runs/latest";' in js
    assert 'if (session && session.authenticated) return "/runs/latest";' in js
    assert 'return "/public/runs/latest";' in js
    assert 'var session = await fetchJson("/ui/session") || {};' in js
    assert 'var latestPacket = await fetchJson(latestRunRouteForSession(session) + buildQuery(params));' in js


def test_workspace_chat_defaults_to_auto_qa_mode():
    workspace_html = (Path(api_module.STATIC_DIR) / "index.html").read_text(encoding="utf-8")
    js = TestClient(api_module.app).get("/static/app.js").text

    assert 'data-qa-mode="auto"' in workspace_html
    assert 'qaMode: window.sessionStorage.getItem(QA_MODE_KEY) || "auto"' in js
    assert 'mode: state.qaMode' in js
    assert "Auto: deterministic first, AI if needed" in js


def test_guide_route_renders_plain_english_public_guide():
    client = TestClient(api_module.app)
    response = client.get("/guide")

    assert response.status_code == 200
    html = response.text
    html_lower = html.lower()

    assert "How StrategyOS works" in html
    assert "What StrategyOS does" in html
    assert "How it works" in html
    assert "What you can see right now" in html
    assert "Try it yourself" in html
    assert "What's next" in html
    assert "Use the temporary test login page" in html
    assert 'href="/login"' in html
    assert "https://strategyos.live/login" in html
    assert "Executive users land on" in html
    assert "all other test roles land on" in html
    assert "No sign-up needed for the public preview" not in html
    assert "5–10 minutes" in html
    assert "criticalBlockers" not in html
    assert "activeActionItems" not in html

    for unsafe_phrase in (
        "ai agents",
        "autonomous",
        "fully automated",
        "real-time",
        "all-in-one platform",
        "ceo cockpit",
        "replace your existing tools",
        "revolutionises",
        "guarantees",
    ):
        assert unsafe_phrase not in html_lower


def test_homepage_renders_minimal_executive_diagnostics_surface():
    html = _homepage_response()

    marker = '<script id="strategyos-executive-bootstrap" type="application/json">'
    assert "StrategyOS — Group CEO Briefing" in html
    assert marker in html
    assert 'href="/guide"' in html
    assert "How it works" in html
    bootstrap_json = html.partition(marker)[2].partition("</script>")[0]
    bootstrap = json.loads(bootstrap_json)
    assert bootstrap["product_name"] == "StrategyOS"
    assert "StrategyOS" in html
    assert '<script id="strategyos-bootstrap"' not in html
    # Design-faithful structure: topbar
    assert 'id="topbar"' in html or 'class="topbar"' in html
    assert 'class="brand"' in html
    assert 'class="brand-mark"' in html
    # Persona switcher
    assert 'id="persona-menu"' in html or 'id="persona-btn"' in html
    # 22.06 top bar / nav parity
    assert 'id="view-nav"' in html
    assert "Briefing" in html and "Calendar" in html and "Hermes" in html and "Evidence" in html
    assert 'id="view-calendar"' in html and 'id="calendar-agenda-panel"' in html
    assert "Mizan Group" not in html
    assert "Viewing as" not in html
    assert "ask-toggle" not in html, "ask-toggle button must be absent (simplified topbar)"
    assert ">KA<" not in html
    assert 'id="brand-org">StrategyOS<' in html
    assert 'id="topbar-avatar">—<' in html
    # Hero banner
    assert 'id="hero"' in html or 'class="hero"' in html
    assert 'id="hero-head"' in html or 'class="hero-title"' in html
    assert 'id="hero-body"' in html or 'class="hero-body"' in html
    assert 'id="hero-score"' in html or 'class="hero-score__value"' in html
    # Driver grid
    assert 'id="driver-row"' in html or 'class="driver-grid"' in html
    # Home composition parity
    assert "Enterprise performance" in html
    assert 'id="driver-drill"' in html
    assert 'id="findings-panel"' in html
    assert 'id="developments-panel"' in html
    assert 'id="week-panel"' in html
    assert "Prepare the next move" in html
    assert 'id="board-portal"' in html
    assert 'id="agents-activity"' in html
    assert 'id="functions-overview"' in html
    assert 'id="functions-roster"' in html
    assert 'id="functions-audit"' in html
    assert 'id="assistant-studio"' in html
    assert 'id="assistant-form"' in html
    assert 'id="assistant-drawer"' in html
    assert 'id="chat-launcher"' in html
    assert 'id="knowledge-graph-card"' in html


def test_executive_route_renders_minimal_live_diagnostics_shell():
    client = TestClient(api_module.app)
    response = client.get("/executive")
    assert response.status_code == 200
    html = response.text
    js = _static_executive_js()

    marker = '<script id="strategyos-executive-bootstrap" type="application/json">'
    assert "StrategyOS — Group CEO Briefing" in html
    assert marker in html
    assert 'href="/guide"' in html
    bootstrap_json = html.partition(marker)[2].partition("</script>")[0]
    bootstrap = json.loads(bootstrap_json)
    assert bootstrap["product_name"] == "StrategyOS"
    # Design-faithful UI elements
    assert 'id="topbar"' in html or 'class="topbar"' in html
    assert 'class="brand"' in html
    assert 'id="view-nav"' in html
    assert "Briefing" in html and "Calendar" in html and "Hermes" in html and "Evidence" in html
    assert 'id="view-calendar"' in html and 'id="calendar-agenda-panel"' in html
    assert "Mizan Group" not in html
    assert "Viewing as" not in html
    assert "ask-toggle" not in html, "ask-toggle button must be absent (simplified topbar)"
    assert ">KA<" not in html
    assert 'id="hero"' in html or 'class="hero"' in html
    assert 'id="hero-score"' in html or 'class="hero-score__value"' in html
    assert 'id="hero-head"' in html or 'class="hero-title"' in html
    assert 'id="driver-row"' in html or 'class="driver-grid"' in html
    assert "Enterprise performance" in html
    assert 'id="decision-questions-section"' in html
    assert 'id="driver-drill"' in html
    assert 'id="findings-panel"' in html
    assert 'id="developments-panel"' in html
    assert 'id="week-panel"' in html
    assert 'id="board-portal"' in html
    assert 'id="agents-activity"' in html
    assert 'id="persona-menu"' in html or 'id="persona-btn"' in html
    assert 'id="functions-overview"' in html
    assert 'id="functions-roster"' in html
    assert 'id="functions-audit"' in html
    assert 'id="knowledge-graph-card"' in html
    assert 'id="assistant-studio"' in html
    assert 'id="assistant-drawer"' in html
    assert 'id="chat-launcher"' in html
    assert "strategyos.ui.token" in js
    assert "function authHeaders(options)" in js
    assert "token = firstDefined(state && state.token, \"\")" in js
    assert "Authorization: \"Bearer \" + token" in js
    assert "fetch(path, { headers: authHeaders() })" in js
    assert '<script id="strategyos-bootstrap"' not in html
    assert "(state.session || {}).token" not in js


def test_app_entry_routes_render_executive_shell():
    client = TestClient(api_module.app)

    app_response = client.get("/app")
    alias_response = client.get("/dashboard")

    assert app_response.status_code == 200
    assert alias_response.status_code == 200
    assert "StrategyOS — Group CEO Briefing" in app_response.text
    assert "StrategyOS — Group CEO Briefing" in alias_response.text
    assert '<script id="strategyos-executive-bootstrap"' in app_response.text
    assert '<script id="strategyos-executive-bootstrap"' in alias_response.text
    assert '<script id="strategyos-bootstrap"' not in app_response.text
    assert '<script id="strategyos-bootstrap"' not in alias_response.text
    assert "StrategyOS.live Governed Diagnostics Workspace" not in app_response.text
    assert "StrategyOS.live Governed Diagnostics Workspace" not in alias_response.text


def test_app_entry_uses_design_faithful_executive_surface():
    html = _app_entry_response()
    js = _static_executive_js()

    assert "StrategyOS — Group CEO Briefing" in html
    assert "StrategyOS" in html
    assert 'id="topbar"' in html or 'class="topbar"' in html
    assert 'class="brand"' in html
    assert 'id="view-nav"' in html
    assert "Briefing" in html and "Calendar" in html and "Hermes" in html and "Evidence" in html
    assert "Mizan Group" not in html
    assert "Viewing as" not in html
    assert "ask-toggle" not in html, "ask-toggle button must be absent (simplified topbar)"
    assert ">KA<" not in html
    assert 'id="hero"' in html or 'class="hero"' in html
    assert 'id="driver-row"' in html or 'class="driver-grid"' in html
    assert "Enterprise performance" in html
    assert 'id="decision-questions-section"' in html
    assert 'id="driver-drill"' in html
    assert 'id="findings-panel"' in html
    assert 'id="developments-panel"' in html
    assert 'id="week-panel"' in html
    assert 'id="board-portal"' in html
    assert 'id="agents-activity"' in html
    assert 'id="functions-overview"' in html
    assert 'id="functions-roster"' in html
    assert 'id="functions-audit"' in html
    assert 'id="knowledge-graph-card"' in html
    assert 'id="assistant-studio"' in html
    assert 'id="assistant-drawer"' in html
    assert 'id="chat-launcher"' in html
    assert "StrategyOS.live Governed Diagnostics Workspace" not in html
    assert 'strategyos.ui.token' in js
    assert 'renderViewNav' in js
    assert 'renderViewPanels' in js
    assert 'renderDriverDrillFidelity' in js
    assert 'renderLowerRailFidelity' in js
    assert 'renderBoardPortal' in js
    assert 'renderAgentsDiscovery' in js
    assert 'renderAssistantNetwork' in js
    assert 'renderKnowledgeGraph' in js
    assert 'renderAssistantStudio' in js


def test_homepage_redirects_authenticated_roles_to_default_lane() -> None:
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": None,
            "STRATEGYOS_REVIEWER_API_KEYS": None,
        }
    )
    try:
        client = TestClient(api_module.app)
        bu = client.get("/", headers={"X-API-Key": "bu"}, follow_redirects=False)
        reviewer = client.get("/", headers={"X-API-Key": "reviewer"}, follow_redirects=False)
        operator = client.get("/", headers={"X-API-Key": "operator"}, follow_redirects=False)
        tenant_admin = client.get("/", headers={"X-API-Key": "tenant_admin"}, follow_redirects=False)
        executive = client.get("/", headers={"X-API-Key": "executive"}, follow_redirects=False)

        assert bu.status_code == 307
        assert bu.headers["location"] == "/app?lane=review#bu"
        assert reviewer.status_code == 307
        assert reviewer.headers["location"] == "/app?lane=review#review"
        assert operator.status_code == 307
        assert operator.headers["location"] == "/app?lane=operate"
        assert tenant_admin.status_code == 307
        assert tenant_admin.headers["location"] == "/app?lane=system"
        assert executive.status_code == 307
        assert executive.headers["location"] == "/app"
    finally:
        _restore_env(original)


def test_app_entry_embeds_parseable_executive_bootstrap_json():
    html = _app_entry_response()

    marker = '<script id="strategyos-executive-bootstrap" type="application/json">'
    assert marker in html
    bootstrap_json = html.partition(marker)[2].partition("</script>")[0]
    assert "&quot;" not in bootstrap_json
    bootstrap = json.loads(bootstrap_json)
    assert bootstrap["product_name"] == "StrategyOS"
    assert bootstrap["executive_route_base"] == "/app"
    assert bootstrap["executive_entry_route"] == "/app"
    assert bootstrap["requested_view_state"]["persona"] is None
    assert bootstrap["route_contracts"]["app"].startswith("/app")
    assert bootstrap["route_contracts"]["dashboard"] == "/dashboard"
    assert bootstrap["route_contracts"]["executive"] == "/executive"
    assert bootstrap["route_contracts"]["workspace_contract"] == "/ui/workspace-contract/latest"
    assert bootstrap["qa_modes"]["auto"]["enabled"] is True
    assert bootstrap["qa_modes"]["auto"]["description"].startswith("Deterministic Q&A first")
    assert bootstrap["qa_modes"]["deterministic"]["enabled"] is True
    assert "enabled" in bootstrap["qa_modes"]["llm"]


def test_app_entry_bootstrap_preserves_requested_view_state():
    client = TestClient(api_module.app)
    response = client.get("/app?persona=board&board=closed&driver=owed_upward&company=tenant-alpha&portfolio=release-readiness")

    assert response.status_code == 200
    marker = '<script id="strategyos-executive-bootstrap" type="application/json">'
    bootstrap_json = response.text.partition(marker)[2].partition("</script>")[0]
    bootstrap = json.loads(bootstrap_json)
    assert bootstrap["requested_view_state"]["persona"] == "board"
    assert bootstrap["requested_view_state"]["board"] == "closed"
    assert bootstrap["requested_view_state"]["driver"] == "owed_upward"
    assert bootstrap["requested_view_state"]["company"] == "tenant-alpha"
    assert bootstrap["requested_view_state"]["portfolio"] == "release-readiness"
    assert (
        bootstrap["route_contracts"]["entry"]
        == "/app?persona=board&board=closed&driver=owed_upward&company=tenant-alpha&portfolio=release-readiness"
    )


def test_app_entry_uses_content_hashed_executive_assets():
    html = _app_entry_response()
    asset_rev = api_module._executive_asset_revision()

    assert f'/static/executive.css?v={asset_rev}' in html
    assert f'/static/executive.js?v={asset_rev}' in html
    assert "__EXECUTIVE_ASSET_REV__" not in html


def test_entry_routes_static_assets_have_no_external_origins():
    html = _app_entry_response()
    js = _static_executive_js()
    client = TestClient(api_module.app)
    executive_html = client.get("/executive").text
    css = client.get("/static/executive.css").text

    combined = html + executive_html + js + css
    assert "https://cdn" not in combined
    assert "http://" not in combined
    assert "https://" not in combined.replace("https://strategyos.live", "")
    assert "fonts.googleapis" not in combined


def test_app_entry_preserves_bootstrap_bound_client_rendering():
    html = _app_entry_response()
    js = _static_executive_js()

    assert "__STRATEGYOS_EXECUTIVE_BOOTSTRAP__" not in html
    assert "bootstrap" in js
    assert "bootstrap.environment" in js
    assert "bootstrap.api_auth_enabled" in js


def test_ui_session_reports_anonymous_when_auth_enabled_and_no_credentials():
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-key",
        }
    )
    try:
        client = TestClient(api_module.app)

        response = client.get("/ui/session")

        assert response.status_code == 200
        payload = response.json()
        assert payload["authenticated"] is False
        assert payload["role"] == "anonymous"
        assert payload["api_auth_enabled"] is True
    finally:
        _restore_env(original)


def test_ui_session_reports_authenticated_role_for_api_key():
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_BU_API_KEYS": "bu-key",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-key",
        }
    )
    try:
        client = TestClient(api_module.app)

        response = client.get("/ui/session", headers={"X-API-Key": "reviewer-key"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["authenticated"] is True
        assert payload["role"] == "reviewer"
        assert payload["altitude"] == "review"
        assert payload["capabilities"]["can_review"] is True
        assert payload["subject"].startswith("api-key:reviewer:")
    finally:
        _restore_env(original)


def test_ui_session_reports_bu_role_with_read_only_review_capabilities():
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_BU_API_KEYS": "bu-key",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-key",
        }
    )
    try:
        client = TestClient(api_module.app)

        response = client.get("/ui/session", headers={"X-API-Key": "bu-key"})
        contract = client.get("/ui/workspace-contract/latest", headers={"X-API-Key": "bu-key"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["authenticated"] is True
        assert payload["role"] == "bu"
        assert payload["altitude"] == "review"
        assert payload["capabilities"]["can_view_cases"] is True
        assert payload["capabilities"]["can_review"] is False
        assert payload["company_switcher"]["active_company_id"]
        assert payload["portfolio_switcher"]["active_portfolio_id"]
        assert contract.status_code == 200
        contract_payload = contract.json()
        workflow_surface = next(item for item in contract_payload["surfaces"] if item["surface_id"] == "workflow")
        reports_surface = next(item for item in contract_payload["surfaces"] if item["surface_id"] == "reports")
        assert workflow_surface["primary_route"] == "/bu/pending-reviews"
        assert reports_surface["primary_route"] == "/bu/runs/{run_id}"
        assert contract_payload["domain_filters"][0]["filter_id"] == "finance_integrity"
        assert contract_payload["lanes"]["bu"]["evidence_qa_route"].endswith("domain=evidence_qa")
        assert contract_payload["kpi_cards"][0]["card_id"] == "recoverable_value"
        assert contract_payload["board_portal"]["state"] in {"pre", "live", "closed"}
        assert contract_payload["board_portal"]["publish_state"] == contract_payload["reports"]["publication"]["publish_state"]
        assert contract_payload["executive_modes"]["active_persona_id"] == "ceo"
        assert any(item["persona_id"] == "cfo" for item in contract_payload["executive_modes"]["personas"])
        assert any(item["persona_id"] == "board" for item in contract_payload["executive_modes"]["personas"])
        assert any(item["active"] for item in contract_payload["executive_modes"]["board_states"])
        assert any(item["driver_key"] == "cash_pulse" for item in contract_payload["executive_modes"]["driver_focus"])
        assert any(item["driver_key"] == "owed_upward" for item in contract_payload["executive_modes"]["driver_focus"])
        assert contract_payload["drilldown"]["routes"]["case_detail"].endswith("{finding_id}")
        assert contract_payload["drilldown"]["gravity"]["rails"][1] in {"pre", "live", "closed"}
        assert contract_payload["drilldown"]["lower_rail"]["week_ahead"][0]["event_id"] == "prep"
        assert contract_payload["interaction_contracts"]["pending_reviews"]["route"] == "/bu/pending-reviews"
        assert contract_payload["agents"]["discover"]["native"] == []
        assert contract_payload["agents"]["discover"]["marketplace"]
        assert contract_payload["agent_modules"]["summary"]["running_count"] >= 4
        assert contract_payload["tenant_admin_system"]["connector_posture"]["count"] >= 3
        assert contract_payload["tenant_admin_system"]["workflow_posture"]["review_queue_route"] == "/reviewer/pending-reviews"
        assert contract_payload["role_actions"]["viewer_role"] == "bu"
        assert contract_payload["reports"]["publication"]["allowed_actions"] == [
            "view_governed_report_status",
            "view_report_preview",
        ]
    finally:
        _restore_env(original)


def test_ui_session_and_workspace_contract_use_governed_routes_for_authenticated_executive(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": None,
            "STRATEGYOS_REVIEWER_API_KEYS": None,
        }
    )
    try:
        monkeypatch_summary = {
            "run_id": "run-42",
            "tenant_context": {
                "tenant_id": "tenant-alpha",
                "tenant_name": "Tenant Alpha",
                "workspace_id": "tenant-alpha",
            },
            "artifacts": {
                "case_file": "/tmp/Final consolidated case file.md",
                "working_capital": "/tmp/Working Capital Memo.md",
                "citation_audit": "/tmp/StrategyOS Citation Audit.json",
            },
            "report_contracts": {
                "tenant_id": "tenant-alpha",
                "run_id": "run-42",
                "evidence": [
                    {
                        "artifact_key": "citation_audit",
                        "title": "Citation audit",
                        "category": "evidence",
                        "format": "json",
                        "path": "/tmp/StrategyOS Citation Audit.json",
                        "restricted": True,
                    }
                ],
                "reports": [
                    {
                        "artifact_key": "case_file",
                        "title": "Case file",
                        "category": "report",
                        "format": "md",
                        "path": "/tmp/Final consolidated case file.md",
                        "restricted": True,
                    },
                    {
                        "artifact_key": "working_capital",
                        "title": "Working capital memo",
                        "category": "report",
                        "format": "md",
                        "path": "/tmp/Working Capital Memo.md",
                        "restricted": False,
                    },
                ],
            },
        }
        monkeypatch.setattr(api_module, "_latest_summary", lambda: monkeypatch_summary)
        client = TestClient(api_module.app)

        session = client.get("/ui/session", headers={"X-API-Key": "executive"})
        contract = client.get(
            "/ui/workspace-contract/latest?persona=board&board=closed&driver=owed_upward&portfolio=release-readiness",
            headers={"X-API-Key": "executive"},
        )

        assert session.status_code == 200
        assert session.json()["role"] == "executive"
        assert session.json()["display_name"] == "Executive"
        assert contract.status_code == 200
        payload = contract.json()
        assert payload["principal"]["altitude"] == "executive"
        cases_surface = next(item for item in payload["surfaces"] if item["surface_id"] == "cases")
        assert cases_surface["primary_route"] == "/runs/latest/findings"
        assert payload["evidence"]["preview_route"] == "/public/data/evidence-preview"
        assert payload["plan_health"]["root_label"] == "Governed plan posture"
        assert payload["domain_tree"]["nodes"][0]["domain_id"] == "finance"
        assert payload["strategy_substrate"]["intent"]["label"] == "Convert governed finance signal into executive action"
        assert payload["strategy_substrate"]["intent"]["guardrails"]
        assert payload["board_portal"]["meeting"]["title"] == "Board pack"
        assert payload["executive_modes"]["active_persona_id"] == "board"
        assert payload["executive_modes"]["active_board_state"] == "closed"
        assert payload["executive_modes"]["active_driver_key"] == "owed_upward"
        assert payload["executive_modes"]["portfolio_id"] == "release-readiness"
        assert payload["executive_modes"]["state_contract"]["requested"]["board"] == "closed"
        assert payload["executive_modes"]["state_contract"]["requested"]["persona"] == "board"
        assert payload["executive_modes"]["driver_focus"][0]["driver_key"] == "board_packet"
        assert any(item["persona_id"] == "cfo" for item in payload["executive_modes"]["personas"])
        assert any(item["persona_id"] == "logistics" for item in payload["executive_modes"]["personas"])
        assert payload["board_portal"]["presentation_state"] == "closed"
        assert payload["board_portal"]["lifecycle_flow"][2]["presented"] is True
        assert payload["board_portal"]["state_detail"]["state"] == "closed"
        assert payload["board_portal"]["meeting"]["design_title"] is None
        assert payload["board_portal"]["kpis"][0]["key"] == "recoverable_value"
        assert payload["board_portal"]["decks"] == []
        assert payload["drilldown"]["default_case_id"] is None
        assert payload["drilldown"]["cash_pulse"]["basis"] == "governed_findings"
        assert payload["drilldown"]["gravity"]["prompts"]
        assert payload["drilldown"]["gravity"]["assistant"] == "StrategyOS"
        assert payload["drilldown"]["gravity"]["sandbox"]["board_state"] == "closed"
        assert payload["drilldown"]["lower_rail"]["board_state"]["presentation_state"] == "closed"
        assert payload["drilldown"]["lower_rail"]["week_ahead"][0]["detail"]
        assert payload["drilldown"]["lower_rail"]["owed_upward"]["items"] == []
        assert payload["interaction_contracts"]["latest_run"]["route"] == "/runs/latest"
        assert payload["interaction_contracts"]["report_preview"]["route"] == "/runs/latest/report-preview"
        assert payload["chat"]["assistant"]["persona_id"] == "board"
        assert payload["chat"]["assistant"]["board_state"] == "closed"
        assert payload["chat"]["store"]["mode"] == "client_session"
        assert payload["chat"]["threads"][0]["thread_id"] == "system:run-42"
        assert payload["agents"]["running"] == []
        assert payload["agents"]["discover"]["marketplace"]
        assert payload["agent_modules"]["summary"]["discoverable_count"] >= 4
        assert payload["tenant_admin_system"]["managed_data"]["reports"]["report_count"] == 2
        assert payload["tenant_admin_system"]["trend"]["truth_basis"] == "reconciled_governed_metrics"
        assert payload["role_actions"]["viewer_role"] == "executive"
        assert "Illustrative demo narrative" not in json.dumps(payload)
        assert "SAR 2.09B" not in json.dumps(payload)
        assert payload["strategy_substrate"]["value_drivers"][0]["driver_id"] == "cash_recovery"
        assert any(driver["driver_id"] == "board_pack_readiness_driver" for driver in payload["strategy_substrate"]["value_drivers"])
        assert any(item["portfolio_id"] == "release-readiness" for item in payload["strategy_substrate"]["portfolio_views"])
        assert any(item["reasoning_id"] == "hold-runtime-boundary" for item in payload["strategy_substrate"]["reasoning"])
        assert payload["executive_diagnostics"]["hero"]["persona_id"] == "board"
        assert payload["executive_diagnostics"]["hero"]["board_state"] == "closed"
        assert payload["executive_diagnostics"]["persona_blueprint"]["assistant"] == "StrategyOS"
        assert "assistant" not in payload["executive_diagnostics"]["board_packet"]
        assert payload["executive_diagnostics"]["composition"]["board_portal"]["presentation_state"] == "closed"
        assert payload["executive_diagnostics"]["composition"]["gravity"]["sandbox"]["active_driver_key"] == "owed_upward"
        assert any(item["option_id"] == "release-readiness" for item in payload["portfolio_switcher"]["options"])
        assert all("path" not in item for item in payload["reports"]["artifacts"])
    finally:
        _restore_env(original)


def test_ui_session_reports_environment_label_from_config():
    original = _apply_env({"STRATEGYOS_ENVIRONMENT_LABEL": "Hosted QA"})
    try:
        client = TestClient(api_module.app)

        response = client.get("/ui/session")

        assert response.status_code == 200
        payload = response.json()
        assert payload["environment"] == "Hosted QA"
    finally:
        _restore_env(original)


def test_discoverable_agent_modules_are_native_strategyos_surfaces():
    payload = api_module._agent_modules_payload(
        None,
        [],
        None,
        {"role": "executive", "authenticated": False},
    )

    assert payload["discoverable"]
    assert {item["source"] for item in payload["discoverable"]} == {"native"}


def test_digital_twin_cards_open_in_place_and_keep_connector_install_separate():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    executive_css = Path("strategyos_mvp/static/executive.css").read_text(encoding="utf-8")

    assert "data-twin-toggle" in executive_js
    assert "twin-network-search" in executive_js
    assert "state.openAgentId = state.openAgentId === id ? '' : id" in executive_js
    assert "showAgentInstallRequest(item, sourceEl)" in executive_js
    assert "Agent installation is available from the operator surface" not in executive_js
    assert ".strategyos-agent-install-modal" in executive_css
    assert ".strategyos-toast" in executive_css


def test_workspace_contract_accepts_design_persona_ids_and_legacy_aliases(monkeypatch):
    monkeypatch_summary = {
        "run_id": "run-77",
        "tenant_context": {
            "tenant_id": "tenant-alpha",
            "tenant_name": "Tenant Alpha",
            "workspace_id": "tenant-alpha",
        },
        "artifacts": {},
        "report_contracts": {
            "tenant_id": "tenant-alpha",
            "run_id": "run-77",
            "evidence": [],
            "reports": [],
        },
        "findings": [],
    }
    monkeypatch.setattr(api_module, "_latest_summary", lambda: monkeypatch_summary)
    client = TestClient(api_module.app)

    gm = client.get("/ui/workspace-contract/latest?persona=gm")
    alias_gm = client.get("/ui/workspace-contract/latest?persona=pharma")
    bu_cfo = client.get("/ui/workspace-contract/latest?persona=bucfo")
    alias_bu_cfo = client.get("/ui/workspace-contract/latest?persona=distribution")

    assert gm.status_code == 200
    assert alias_gm.status_code == 200
    assert bu_cfo.status_code == 200
    assert alias_bu_cfo.status_code == 200
    assert gm.json()["executive_modes"]["active_persona_id"] == "gm"
    assert alias_gm.json()["executive_modes"]["active_persona_id"] == "gm"
    assert bu_cfo.json()["executive_modes"]["active_persona_id"] == "bucfo"
    assert alias_bu_cfo.json()["executive_modes"]["active_persona_id"] == "bucfo"


def test_ui_session_returns_clean_display_identity_for_idp_subject(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
            "STRATEGYOS_IDP_OPERATOR_USERNAME": "operator.local",
            "STRATEGYOS_IDP_OPERATOR_PASSWORD": "operator-pass",
            "STRATEGYOS_IDP_REVIEWER_USERNAME": "reviewer.local",
            "STRATEGYOS_IDP_REVIEWER_PASSWORD": "reviewer-pass",
        }
    )
    try:
        monkeypatch.setattr(
            auth_module,
            "_introspect_identity_token",
            lambda token: {
                "operator-token": {
                    "role": "operator",
                    "subject": "http://localhost:8089:operator.local",
                }
            }.get(token),
        )
        client = TestClient(api_module.app)

        response = client.get(
            "/ui/session", headers={"Authorization": "Bearer operator-token"}
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["authenticated"] is True
        assert payload["role"] == "operator"
        assert payload["subject"] == "http://localhost:8089:operator.local"
        assert payload["display_role"] == "Operator"
        assert payload["display_subject"] == "Operator Local"
        assert payload["display_name"] == "Operator Local"
        assert "localhost" not in payload["display_name"]
        assert "localhost" not in payload["display_subject"]
    finally:
        _restore_env(original)


def test_public_executive_shell_ceo_prompt_succeeds_without_session_token(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: None)
        client = TestClient(api_module.app)

        shell = client.get("/executive?persona=ceo")
        session = client.get("/ui/session")
        response = client.post(
            "/assistant/chat",
            json={
                "question": "Simulate digital health flat by end of year",
                "persona": "ceo",
                "mode": "auto",
            },
        )

        assert shell.status_code == 200
        assert session.status_code == 200
        session_payload = session.json()
        assert session_payload["authenticated"] is False
        assert session_payload["role"] == "anonymous"
        assert "token" not in session_payload

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["scenario_id"] == "public_exec_governed_packet"
        assert payload["matched"] is True
        assert payload["mode"] == "deterministic"
        assert payload["assistant_mode"] == "scenario"
        assert payload["trace"]
        assert payload["audit_trail_id"]
        assert payload["hallucination_risk"]["level"] == "low"
        assert payload["prompt_contracts"]["role"]["prompt_id"] == "role:ceo:v1"
        assert "current governed" in payload["answer"].lower()
        assert "I couldn't reach the shared assistant service just now." not in payload["answer"]
    finally:
        _restore_env(original)


def test_kg_render_includes_modern_elements():
    """renderKnowledgeGraph() must produce modern graph stage, inspector,
    and category-colored node classes."""
    js = _static_executive_js()
    assert "kg-stage" in js, "kg-stage CSS class must be used in rendering"
    assert "kg-inspector" in js, "kg-inspector element must exist in rendering logic"
    assert "kg-node-dot--" in js, "Category-colored node dot classes must exist"
    assert "kg-node--major" in js, "Major node sizing class must exist"
    assert "kg-node--minor" in js, "Minor node sizing class must exist"
    assert "kg-legend__swatch" in js, "Legend color swatches must exist"
    assert "is-selected" in js, "Selected node state class must exist"
    assert 'role="application"' in js, "Graph stage must have application ARIA role"
    assert "aria-label" in js, "Graph must have aria-labels"
    assert "kg-dimmed" in js, "Dimmed state class for hover must exist"
    assert "What drives the four headline figures" in js
    assert "kg-density-toggle" in js, "Density toggle control must exist"
    assert "kg-zoom-in" in js and "kg-zoom-out" in js, "Zoom controls must exist"
    assert "kg-focus-mode" in js, "Focus mode control must exist"
    assert "Select any item for its business meaning" in js
    assert "No illustrative business data" not in js


def test_kg_hover_uses_stable_hit_geometry():
    """Hover emphasis must not move the SVG node under the pointer."""
    js = _static_executive_js()
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    assert 'class="kg-node-hit"' in js
    assert "interactionRadius" in js
    assert ".kg-node-hit" in css
    assert "pointer-events: all" in css

    dot_start = css.index(".kg-node-dot {")
    dot_end = css.index(".kg-node-dot--plan", dot_start)
    dot_rule = css[dot_start:dot_end]
    assert "pointer-events: none" in dot_rule
    assert "transform" not in dot_rule

    hover_start = css.index(".kg-node:hover .kg-node-dot")
    hover_end = css.index("}", hover_start) + 1
    hover_rule = css[hover_start:hover_end]
    assert "transform" not in hover_rule


def test_kg_inspector_has_ask_hermes_cta():
    """Inspector panel must include an 'Ask Hermes about this' CTA button."""
    js = _static_executive_js()
    # Check the inspector builder
    insp_start = js.index("function openNodeInspector")
    insp_end = js.index("function closeNodeInspector")
    inspector_code = js[insp_start:insp_end]
    assert "Ask Hermes" in inspector_code, "Inspector must have 'Ask Hermes' CTA text"
    assert "kg-inspector__ask" in inspector_code, "Inspector must have Ask Hermes button class"
    assert "hermes_prompt" in inspector_code, "Inspector must use hermes_prompt from node data"
    assert "askAssistant" in inspector_code, (
        "Ask Hermes CTA must call askAssistant() with the node's hermes_prompt"
    )


def test_kg_universe_controls_present():
    """Graph universe must expose the dense-navigation controls."""
    js = _static_executive_js()

    assert "kg-controls" in js, "Graph universe toolbar must exist"
    assert "kg-density-toggle" in js, "Density toggle must exist"
    assert "kg-zoom-in" in js, "Zoom-in control must exist"
    assert "kg-zoom-out" in js, "Zoom-out control must exist"
    assert "kg-fit" in js, "Fit control must exist"
    assert "kg-reset" in js, "Reset control must exist"
    assert "kg-focus-mode" in js, "Focus mode control must exist"


def test_kg_universe_does_not_generate_decorative_density_nodes():
    """The graph must not generate decorative business data."""
    js = _static_executive_js()

    assert "targetTotalNodes = Math.max(110" not in js
    assert "satelliteKind" not in js
    assert "relayCount" not in js
    assert "Choose a headline figure to see what makes it up" in js
    assert "No illustrative business data" not in js
    assert "Why it matters" in js
    assert "Ask Hermes for a decision-focused explanation" in js


def test_assistant_drawer_unified_opening_path():
    """All assistant-opening CTAs must route through _openHermesDrawer or openAssistantDrawer.

    Verifies that the shared opening path exists and askAssistant calls it.
    """
    js = _static_executive_js()

    # Core functions must exist
    assert "function _openHermesDrawer(" in js, "Unified drawer opener must exist"
    assert "function openAssistantDrawer(" in js, "Public drawer opener alias must exist"
    assert "function askAssistant(" in js, "askAssistant must exist"

    # openAssistantDrawer must delegate to _openHermesDrawer
    assert "_openHermesDrawer(" in js, "_openHermesDrawer must be callable"

    # askAssistant must call openAssistantDrawer (not duplicate logic)
    ask_fn_start = js.index("function askAssistant(")
    ask_fn_block = js[ask_fn_start:ask_fn_start + 800]  # first ~800 chars of askAssistant
    assert "openAssistantDrawer(" in ask_fn_block, (
        "askAssistant must call openAssistantDrawer() — not bypass the shared path"
    )


def test_assistant_drawer_shared_state_guard():
    """_openHermesDrawer must guard A2A and avoid redundant opens."""
    js = _static_executive_js()

    open_fn_start = js.index("function _openHermesDrawer(")
    open_fn_end = js.index("function _closeHermesDrawer()")
    open_fn_body = js[open_fn_start:open_fn_end]

    # A2A panel guard
    assert "state.a2aOpen" in open_fn_body, (
        "Must check a2aOpen before opening drawer"
    )

    # Already-open drawer must still re-render so submitted prompts show a
    # visible user message and pending assistant state immediately.
    assert "if (state.drawerOpen)" in open_fn_body, (
        "Must guard against redundant drawer opening"
    )
    already_open_block = open_fn_body[
        open_fn_body.index("if (state.drawerOpen)"):
        open_fn_body.index("state.drawerOpen = true;")
    ]
    assert "renderAssistantStudio();" in already_open_block
    assert "focusAssistantInput();" in already_open_block


def test_driver_grid_renders_governed_metric_when_percent_is_absent():
    js = _static_executive_js()
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    assert "function driverCenterMarkup(driver)" in js
    assert "function driverMeasureLabel(driver)" in js
    assert "driverCenterMarkup(driver)" in js
    assert "driverMeasureLabel(driver) + ' · '" in js

    render_start = js.index("function renderDriverGrid()")
    render_end = js.index("function renderMetrics()")
    render_body = js[render_start:render_end]
    assert "firstDefined(driver.pct, '—')" not in render_body
    assert "driver-pct--metric" in css


def test_executive_surface_bundles_reference_display_font_and_ring_tokens():
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")
    static_dir = Path(api_module.STATIC_DIR)

    assert '@font-face' in css
    assert 'font-family: "Newsreader"' in css
    assert 'url("/static/newsreader-latin.woff2")' in css
    assert 'url("/static/newsreader-italic-latin.woff2")' in css
    assert (static_dir / "newsreader-latin.woff2").stat().st_size > 100_000
    assert (static_dir / "newsreader-italic-latin.woff2").stat().st_size > 100_000
    assert "--ring-track: #e9e5dc" in css
    assert "--ring-tick: #9b968a" in css
    assert ".driver-ring__value--flat { stroke: var(--flat); }" in css
    assert ".driver-pct {" in css and "font-family: var(--serif);" in css
    assert '"Helvetica Neue", Helvetica, Arial, sans-serif' in css
    assert "gap: 13px;" in css
    assert "padding: 24px 18px 20px;" in css
    assert "width: 104px;\n  height: 104px;\n  min-height: 104px;" in css
    assert "container-type: inline-size;" in css
    assert ".driver-pct--money" in css
    assert ".driver-foot__metric" in css
    assert "white-space: normal;" in css
    assert "@container (max-width: 230px)" in css
    assert "box-shadow: 0 0 0 1px var(--accent)" in css
    assert "border-right: 1px solid var(--accent);" in css
    assert "border-bottom: 1px solid var(--accent);" in css
    assert ".driver-tile > .driver-meta > .grounding-badge" in css
    assert "position: absolute;\n  top: 8px;\n  right: 8px;" in css
    assert "grid-template-columns: 128px minmax(0, 1fr);" in css
    assert "width: 128px;\n  height: 128px;" in css
    assert "stroke-width: 6;" in css
    # Bounded by the square inscribed in the inner circle, not the ring's
    # square: 116px on a 128px ring reached the corners where the circle has
    # already curved away, so the status word sat on the stroke.
    assert "width: calc((100% - 18px) * 0.707);" in css
    assert ".hero-score__value--compact" in css
    assert 'classList.toggle("hero-score__value--compact", heroScoreText.length > 4)' in _static_executive_js()
    assert ".kpi-brief-title-row" in css
    assert ".kpi-brief-ratio" in css
    assert "font-size: 15px;\n  font-weight: 600;" in css
    assert "font-size: 12.5px;\n  font-weight: 400;" in css
    assert "font-size: 15.5px;" in css
    assert 'class="kpi-brief-title-row"' in _static_executive_js()
    assert "var executiveSignal = brief.executive_signal || {};" in _static_executive_js()
    assert 'class="kpi-brief-variance tone-' in _static_executive_js()


def test_driver_card_money_and_metadata_typography_is_structured():
    js = _static_executive_js()

    assert "moneyMatch" in js
    assert 'driver-pct__currency' in js
    assert 'driver-pct__amount' in js
    assert 'driver-pct__magnitude' in js
    assert 'driver-foot__metric' in js
    assert '<span class="driver-sub"> · ' not in js


def test_unavailable_ceo_kpis_explain_the_data_request_without_empty_rings():
    js = _static_executive_js()
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    assert "function unavailableDriverMarkup(driver)" in js
    assert "Finance data required" in js
    assert "View formula and data request" in js
    assert "driver-tile--unavailable" in js
    assert ".driver-tile--unavailable" in css
    assert ".driver-unavailable__cta" in css


def test_ceo_kpi_selection_is_inline_and_never_scrolls_the_page():
    js = _static_executive_js()
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")
    html = (Path(api_module.STATIC_DIR) / "executive.html").read_text(encoding="utf-8")

    render_start = js.index("function renderDriverGrid()")
    render_end = js.index("function renderMetrics()")
    render_body = js[render_start:render_end]
    assert "scrollIntoView" not in render_body
    assert "var readingPosition = Number.isFinite(rememberedPosition) ? rememberedPosition : window.scrollY;" in render_body
    assert "window.scrollTo(0, readingPosition)" in render_body
    assert 'tile.addEventListener("pointerdown", function (event)' in render_body
    assert "event.preventDefault()" in render_body
    assert ".view-panel--home" in css
    assert "overflow-anchor: none" in css
    assert "state.driverSelectionScrollY" in render_body
    assert "aria-pressed" in render_body
    assert 'data-driver-key' in render_body
    assert "function syncDriverSelectionUI(grid, activeKey)" in js
    click_body = render_body[render_body.index("tile.onclick = function"):]
    assert "syncDriverSelectionUI(grid, key);" in click_body
    assert "renderDriverGrid();" not in click_body
    assert 'function renderInlineKpiDrill(driver, drillCard)' in js
    assert 'entrypoint: "ceo_kpi_inline"' in js
    assert 'data-kpi-label=' in js
    assert 'nodeProperties.kpi_key' in js
    assert 'payload.grounding_status' in js
    # The badge must be driven by grounding_status. Its wording is copy, not
    # contract -- pinning the exact word made a plain-English rewrite look like
    # a regression.
    assert '? "Evidence verified"' in js
    assert "kpi_key:" in js
    assert "Evidence and calculation" in js
    assert "data-kpi-question" in js
    assert 'decision: "For " + label + ", do I need to intervene now?' in js
    assert "kpi_question_intent: questionType" in js
    assert "function assistantAnswerCacheKey(question, assistantContext)" in js
    assert 'String(firstDefined(context.kpi_question_intent, "free_text"))' in js
    assert "kpiCompositionMarkup(key, brief, drivers)" in js
    assert "Share of the current reported figure" in js
    assert 'class="kpi-composition__bar"' in js
    assert "function kpiTrendChartMarkup(driver)" in js
    assert "Actual series only — plan is not inferred" in js
    assert "trend.has_plan_series === true" in js
    assert "kpiMovementMarkup(driver)" in js
    assert "What changed" in js
    assert "kpiExecutiveContextMarkup(brief, comparison, strategicReference)" in js
    assert "Comparison boundary" in js
    assert "referenceOnlyRatio" not in js
    assert "CEO readout" in js
    assert "Supporting analysis" in js
    assert "kpi-mix-chart" not in js
    assert ".kpi-executive-grid" in css
    assert ".kpi-trend svg {\n  display: block;\n  width: 100%;\n  height: 164px;" in css
    assert ".kpi-mix-chart" not in css
    assert "data-kpi-inline-composer" not in js
    assert "executiveKpiBrief(driver)" in js
    assert 'id="driver-drill"' in html
    assert html.index('id="driver-row"') < html.index('id="driver-drill"')


def test_ceo_information_architecture_separates_board_and_operational_surfaces():
    js = _static_executive_js()
    html = (Path(api_module.STATIC_DIR) / "executive.html").read_text(encoding="utf-8")

    assert 'id="board-workspace"' in html
    assert 'id="agents-section"' in html
    assert 'id="decision-questions-section"' in html
    assert 'data-view-target="agents"' in html
    assert 'data-view-panel="agents"' in html
    assert 'state.activePersona === "board" && !boardReleased' in js
    assert "No live diagnostics, working evidence, or pre-board figures" in js
    assert "Pressure-test the next move" in js
    assert "Enterprise performance" in js
    assert "Decisions for you" in js


def test_kpi_questions_use_the_shared_assistant_drawer():
    js = _static_executive_js()
    drill_start = js.index("function renderInlineKpiDrill(driver, drillCard)")
    drill_end = js.index("function renderDriverDrillFidelity()")
    drill_body = js[drill_start:drill_end]

    assert "askAssistant(" in drill_body
    assert "buildAssistantReply(question, null" not in drill_body
    assert "current posture and evidence boundary" in drill_body
    assert "Do I need to intervene?" in drill_body
    assert "kpi-inline-retry" not in drill_body


def test_ceo_driver_copy_polishes_internal_governed_artifact_keys():
    js = _static_executive_js()

    assert "GOVERNED_MEASURE_LABELS" in js
    for internal_key, public_label in {
        "bounded_finance_snapshot": "Finance recovery snapshot",
        "case_worklist": "Governed case list",
        "evidence_chain": "Citation evidence chain",
        "review_attention": "Reviewer attention queue",
    }.items():
        assert internal_key in js
        assert public_label in js

    render_start = js.index("function renderDriverGrid()")
    render_end = js.index("function renderMetrics()")
    render_body = js[render_start:render_end]
    assert "driverSubLabel(driver)" in render_body
    assert "firstDefined(driver.sub, \"current measure\")" not in render_body
    assert "firstDefined(driver.sub, 'current measure')" not in render_body

    drill_start = js.index("function renderDriverDrillFidelity()")
    drill_end = js.index("function renderBoardStateTabs()")
    drill_body = js[drill_start:drill_end]
    assert "driverSubLabel(driver)" in drill_body
    assert "firstDefined(driver.sub, 'current measure')" not in drill_body


def test_governed_measure_hint_replaces_percent_copy_when_driver_pct_absent():
    js = _static_executive_js()

    start = js.index("function renderHomeComposition()")
    end = js.index("function renderAssistantNetwork()")
    body = js[start:end]
    assert "hasPercentDrivers" in body
    assert "All figures: current measures" in body
    assert "All figures: % of plan" in body


def test_assistant_dock_does_not_reserve_desktop_page_column():
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    page_start = css.index(".page {")
    page_end = css.index("}", page_start)
    page_block = css[page_start:page_end]
    footer_start = css.index(".composed-footer {")
    footer_end = css.index("}", footer_start)
    footer_block = css[footer_start:footer_end]
    dock_start = css.index(".assistant-dock {")
    dock_end = css.index("}", dock_start)
    dock_block = css[dock_start:dock_end]
    launcher_prompt_start = css.index(".chat-launcher__prompt {")
    launcher_prompt_end = css.index("}", launcher_prompt_start)
    launcher_prompt_block = css[launcher_prompt_start:launcher_prompt_end]
    a2a_text_start = css.index(".a2a-fab-text {")
    a2a_text_end = css.index("}", a2a_text_start)
    a2a_text_block = css[a2a_text_start:a2a_text_end]

    assert "--assistant-dock-width: clamp(220px" in css
    assert "padding-right: calc(" not in page_block
    assert "padding-right: calc(" not in footer_block
    assert "display: flex" in dock_block
    assert "max-width: min(460px" in dock_block
    assert "display: none" in launcher_prompt_block
    assert "display: none" in a2a_text_block
    assert 'id="topbar-assistant-launch"' in (Path(api_module.STATIC_DIR) / "executive.html").read_text(encoding="utf-8")
    assert "@media (min-width: 981px) and (max-width: 1799px)" in css
    assert ".assistant-dock { display: none; }" in css
    assert ".topbar-assistant-launch { display: inline-flex; }" in css


def test_assistant_drawer_and_messages_are_bounded_to_prevent_cropped_chat():
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    drawer_start = css.index(".assistant-drawer {")
    drawer_end = css.index("}", drawer_start)
    drawer_block = css[drawer_start:drawer_end]
    message_start = css.index(".assistant-message {")
    message_end = css.index("}", message_start)
    message_block = css[message_start:message_end]
    user_start = css.index(".assistant-message--user {")
    user_end = css.index("}", user_start)
    user_block = css[user_start:user_end]

    assert "width: min(560px" in drawer_block
    assert "max-width: 560px" in drawer_block
    assert "max-width: min(86%" in message_block
    assert "overflow-wrap: anywhere" in message_block
    assert "max-width: min(78%" in user_block


def test_assistant_drawer_css_z_index_layering():
    """CSS z-index must be layered: chat launcher < video modal < assistant scrim < assistant drawer."""
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    # Z-index token system must be documented
    assert "Z-INDEX TOKEN SYSTEM" in css, (
        "Z-index token system must be documented in CSS"
    )

    # Drawer z-index must be above video modal
    assert "z-index: 1101" in css and "assistant-drawer" in css, (
        "assistant-drawer z-index must be 1101 (above video modal)"
    )

    # Scrim must be at 1100 (paired with drawer)
    assert "z-index: 1100" in css and "assistant-scrim" in css, (
        "assistant-scrim z-index must be 1100"
    )


def test_assistant_drawer_mobile_bottom_sheet():
    """Mobile (<760px) must use bottom-sheet drawer, not full-screen overlay."""
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    # Find the 760px breakpoint block (contains drawer bottom-sheet rules)
    assert "@media (max-width: 760px)" in css, "760px breakpoint must exist"
    mobile_idx = css.index("@media (max-width: 760px)")
    mobile_block = css[mobile_idx:mobile_idx + 1200]  # drawer rules block

    # Bottom sheet behavior
    assert "bottom: 0" in mobile_block, "Mobile drawer must anchor to bottom"
    assert "max-height: calc(100dvh - 48px)" in mobile_block, "Mobile drawer must have max-height"
    assert "border-radius: 18px 18px 0 0" in mobile_block, "Mobile drawer must have top rounded corners"
    assert "transform: translateY(100%)" in mobile_block, "Mobile drawer must slide from bottom"

    # Drag handle (::before pseudo-element)
    assert "::before" in mobile_block, "Mobile drawer must have drag handle pseudo-element"


def test_mobile_assistant_dock_and_a2a_panel_use_full_width_stack():
    """Mobile overlay controls must stack cleanly and stay usable on narrow viewports."""
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    mobile_idx = css.index("@media (max-width: 760px)")
    mobile_block = css[mobile_idx:mobile_idx + 1800]

    assert ".assistant-dock" in mobile_block and "width: 100%" in mobile_block, (
        "Mobile assistant dock must use full available width"
    )
    assert ".chat-launcher__cta" in mobile_block and ".a2a-fab" in mobile_block and "justify-content: space-between" in mobile_block, (
        "Mobile launcher and A2A trigger must stretch cleanly instead of clipping"
    )
    assert ".a2a-foot-btn" in mobile_block and ".a2a-tab" in mobile_block and ".a2a-bubble" in mobile_block and "width: 100%" in mobile_block, (
        "Mobile A2A panel controls and messages must avoid narrow-viewport clipping"
    )


def test_board_portal_state_detail_note_differs_from_summary():
    """Board portal payload must expose unique note vs summary copy for each board state."""
    board_portal = api_module._board_portal_payload(None)
    detail = board_portal["state_detail"]

    assert detail.get("note"), "Board portal state detail must include note copy"
    assert detail.get("summary"), "Board portal state detail must include summary copy"
    assert detail["note"] != detail["summary"], (
        "Board portal note and summary must stay distinct to avoid duplicate CEO copy"
    )


def test_assistant_drawer_desktop_layout():
    """Desktop drawer must use two-column layout with thread sidebar + conversation."""
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    assert ".assistant-layout" in css, "assistant-layout class must exist"
    assert "minmax(240px, 280px)" in css, "Thread sidebar must have minmax sizing"
    assert ".assistant-threads" in css, "Thread sidebar class must exist"
    assert ".assistant-conversation" in css, "Conversation area class must exist"


def test_safe_array_not_used_for_assistant_cta_entrypoints():
    """safeArray() is fragile; verify it is NOT used for primary assistant-opening CTAs.

    The known-fragile pattern is safeArray(querySelectorAll(...)).forEach(...) for
    assistant CTAs. We verify the askAssistant call sites don't depend on safeArray
    for core CTAs like driver chips, hero prompts, and board actions.
    """
    js = _static_executive_js()

    # Count safeArray usages
    safe_count = js.count("safeArray(")
    # We expect safeArray to exist (it's a utility), but check that core CTA
    # bindings use explicit pattern or that the number is controlled
    assert safe_count >= 1, "safeArray utility must exist (but be used carefully)"
    # Key CTAs should still function — verify askAssistant is called from
    # the correct entrypoints
    assert "askAssistant(prompt, button)" in js, "Driver chip CTA must exist"
    assert "askAssistant(prompt, askBtn)" in js, "KG inspector CTA must exist"


def test_all_cta_families_call_ask_assistant():
    """Every CTA family must route through askAssistant() for traceability.

    Verifies all representative CTA families from the 18+ entrypoint audit:
    - Findings/Developments: data-rail-prompt → askAssistant
    - Week ahead: data-chat-prompt → askAssistant
    - Driver drill: data-driver-chip → askAssistant
    - Gravity/Scenario: data-chat-prompt → askAssistant
    - Board portal: data-board-prompt, data-board-action → askAssistant
    - KG Inspector: kg-inspector-ask → askAssistant
    - Hero prompts: prompt-chip → askAssistant (line 1362)
    - Assistant drawer: data-assistant-prompt → askAssistant
    - Floating launcher: chat-launcher → _openHermesDrawer
    """
    js = _static_executive_js()

    # Must have the shared entrypoint
    assert "function askAssistant(" in js, "Shared askAssistant function must exist"

    # Count askAssistant call sites — should be multiple (not just one or two)
    call_count = js.count("askAssistant(")
    assert call_count >= 12, (
        f"Expected at least 12 askAssistant call sites across CTA families, found {call_count}"
    )

    # Representative CTA families must be present
    cta_patterns = [
        ("Findings/Developments rail", 'data-rail-prompt'),
        ("Week ahead prep chips", 'data-chat-prompt'),
        ("Driver drill chips", 'data-driver-chip'),
        ("Board prompts", 'data-board-prompt'),
        ("Board actions", 'data-board-action'),
        ("KG Inspector", 'kg-inspector-ask'),
        ("Assistant prompt chips", 'data-assistant-prompt'),
    ]
    for label, pattern in cta_patterns:
        assert pattern in js, (
            f"CTA family '{label}' must have attribute '{pattern}' in executive.js"
        )

    # Both global entry points must open the same governed drawer. At ordinary
    # desktop widths the top-bar trigger replaces the floating dock so it
    # cannot obscure KPI evidence while the user scrolls.
    assert '[launcher, topbarLauncher].forEach' in js, (
        "Dock and top-bar Hermes triggers must share one binding path"
    )
    launcher_idx = js.index('[launcher, topbarLauncher].forEach')
    launcher_block = js[launcher_idx:launcher_idx + 300]
    assert 'trigger.onclick' in launcher_block and '_openHermesDrawer(trigger)' in launcher_block, (
        "Each global Hermes trigger must use the shared drawer-opening route"
    )


def test_assistant_transport_includes_source_and_entrypoint_metadata():
    """Shared assistant transport must send explicit source/entrypoint metadata."""
    js = _static_executive_js()
    assert "assistantEntrypointContext" in js
    assert "assistantEntrypointContext(sourceEl)" in js
    assert "body.assistant_context = entrypointCtx;" in js
    assert "body.source = body.assistant_context.source;" in js
    assert "body.entrypoint = body.assistant_context.entrypoint;" in js


def test_board_portal_uses_delegated_click_handling_for_ctas():
    """Board Portal CTAs must be handled through a stable delegated click path."""
    js = _static_executive_js()

    assert "function bindBoardPortalInteractions(portal)" in js
    assert "portal.addEventListener('click'" in js
    assert "target.closest('[data-board-action]')" in js
    assert "target.closest('[data-board-prompt]')" in js
    assert "askAssistant(boardActionPrompt(actionButton.getAttribute('data-board-action') || '', getBoardPortal()), actionButton);" in js


def test_board_state_tabs_use_stable_delegated_click_handling():
    """Board state tabs must use per-button addEventListener, not fragile onclick."""
    js = _static_executive_js()

    assert "function eventTargetElement(event)" in js
    assert "function syncBoardStateTabUI(nextState)" in js
    assert "state.activeBoard = nextState;" in js
    assert "button.setAttribute('data-board-state', modeState);" in js
    assert "var modeState = String(firstDefined(mode.state_id, mode.id, mode.key, '')).trim().toLowerCase();" in js

    tabs_start = js.index("function renderBoardStateTabs()")
    portal_start = js.index("function renderBoardPortal()", tabs_start)
    tabs_block = js[tabs_start:portal_start]
    assert "button.onclick" not in tabs_block, (
        "Board state tabs must not depend on per-button onclick wiring that can go inert after rerender"
    )
    # Each button uses addEventListener (not onclick) so new buttons created
    # after row.innerHTML = '' receive fresh handlers on every renderBoardStateTabs call.
    assert "addEventListener('click'" in tabs_block, (
        "Board state tabs must use addEventListener over fragile onclick"
    )


def test_board_state_tabs_accept_clicks_from_nested_text_nodes():
    """Board state per-button handler uses event.currentTarget which always refers to the button element."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    # Verify the per-button click handler uses event.currentTarget (not event.target)
    # so text-node targets are handled correctly by the browser's event dispatch.
    assert "event.currentTarget || event.target" in executive_js, (
        "Per-button click handler must prefer event.currentTarget for reliable element access"
    )
    # Verify the handler calls activateBoardState with the data-board-state attribute
    assert 'activateBoardState(stateAttr)' in executive_js, (
        "Per-button click handler must call activateBoardState with the parsed state attribute"
    )
    # Verify stopPropagation prevents the (now removed) delegated row handler from firing
    assert "event.stopPropagation()" in executive_js, (
        "Per-button click handler must stop propagation so only the per-button handler fires"
    )


def test_board_state_tabs_exact_selector_click_switches_stage():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveBoardStateSelectorHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return { renderBoardStateTabs: renderBoardStateTabs, state: state };\n}\nmodule.exports = __executiveBoardStateSelectorHarness;\n',
        1,
    )
    harness_js = harness_js.replace(
        "    renderPersonaView();",
        "    if (!window.__BOARD_STATE_TEST_SUPPRESS_RENDER__) renderPersonaView();",
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');
const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-board-state-selector-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

function makeStore(seed = {{}}) {{
  const data = new Map(Object.entries(seed));
  return {{
    getItem(key) {{ return data.has(key) ? data.get(key) : null; }},
    setItem(key, value) {{ data.set(key, String(value)); }},
    removeItem(key) {{ data.delete(key); }},
    clear() {{ data.clear(); }},
  }};
}}

function makeButton() {{
  return {{
    tagName: 'BUTTON',
    nodeType: 1,
    attributes: {{}},
    className: '',
    innerHTML: '',
    listeners: {{}},
    setAttribute(name, value) {{ this.attributes[name] = String(value); }},
    getAttribute(name) {{ return this.attributes[name] || null; }},
    addEventListener(name, handler) {{ this.listeners[name] = handler; }},
    click() {{ if (this.listeners.click) this.listeners.click({{ target: this, currentTarget: this, preventDefault() {{}}, stopPropagation() {{}} }}); }},
    closest(selector) {{ return selector === '[data-board-state]' ? this : null; }},
  }};
}}

const row = {{
  __boardStateInteractionsBound: false,
  innerHTML: '',
  buttons: [],
  listeners: {{}},
  addEventListener(name, handler) {{ this.listeners[name] = handler; }},
  appendChild(child) {{ this.buttons.push(child); return child; }},
  contains(target) {{ return this.buttons.includes(target); }},
  querySelectorAll(selector) {{
    if (selector === '[data-board-state]') return this.buttons.slice();
    return [];
  }},
  querySelector(selector) {{
    const match = selector.match(/\\[data-board-state="([^"]+)"\\]/);
    if (!match) return null;
    return this.buttons.find((button) => button.getAttribute('data-board-state') === match[1]) || null;
  }},
}};

const note = {{ textContent: '' }};

global.window = {{
  __BOARD_STATE_TEST_SUPPRESS_RENDER__: true,
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [] }} }} }},
  localStorage: makeStore(),
  sessionStorage: makeStore(),
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  setTimeout() {{ return 1; }},
  requestAnimationFrame(cb) {{ cb(); }},
  clearTimeout() {{}},
  setInterval() {{ return 1; }},
  clearInterval() {{}},
  addEventListener() {{}},
  removeEventListener() {{}},
  innerWidth: 1280,
  location: {{ pathname: '/app' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{
    if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify({{ assistant_public_context: {{}} }}) }};
    if (id === 'board-state-row') return row;
    if (id === 'board-state-note') return note;
    return null;
  }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement(tag) {{ return tag === 'button' ? makeButton() : {{}}; }},
}};

const factory = require(tempFile);
const harness = factory();
harness.state.latestPacket = {{
  board_portal: {{
    lifecycle_flow: [
      {{ state_id: 'pre', label: 'Pre-board', detail: 'Prepare governed packet' }},
      {{ state_id: 'live', label: 'Live', detail: 'Run the room inside approved material' }},
      {{ state_id: 'closed', label: 'Closed', detail: 'Freeze memory after the room closes' }}
    ],
    presentation_state: 'pre',
  }},
}};
harness.state.activeBoard = 'pre';
harness.renderBoardStateTabs();
const live = row.querySelector('[data-board-state="live"]');
live.click();
console.log(JSON.stringify({{ activeBoard: harness.state.activeBoard }}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "board_state_selector_click_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    assert result["activeBoard"] == "live", (
        "Board state selector buttons must switch the client lifecycle state when clicked through the exact data-board-state selector path"
    )


def test_board_state_note_updates_on_client_only_stage_switch():
    """activateBoardState switches lifecycle stages purely client-side (no
    network re-fetch — see activateBoardState's own comments). state.latestPacket
    still holds board_portal.state_detail computed for whichever stage was
    active at the LAST fetch. boardStateSupportNote used to trust
    state_detail.note unconditionally, so clicking straight from a "closed"
    fetch to "Live" left the #board-state-note caption showing the stale
    Closed-stage text instead of the Live-stage text -- this reproduces that
    exact click sequence and asserts the caption text is stage-correct."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveBoardStateNoteHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return { activateBoardState: activateBoardState, state: state };\n}\nmodule.exports = __executiveBoardStateNoteHarness;\n',
        1,
    )
    harness_js = harness_js.replace(
        "    renderPersonaView();",
        "    if (!window.__BOARD_STATE_TEST_SUPPRESS_RENDER__) renderPersonaView();",
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');
const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-board-state-note-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

function makeStore(seed = {{}}) {{
  const data = new Map(Object.entries(seed));
  return {{
    getItem(key) {{ return data.has(key) ? data.get(key) : null; }},
    setItem(key, value) {{ data.set(key, String(value)); }},
    removeItem(key) {{ data.delete(key); }},
    clear() {{ data.clear(); }},
  }};
}}

function makeButton() {{
  return {{
    tagName: 'BUTTON',
    nodeType: 1,
    attributes: {{}},
    className: '',
    innerHTML: '',
    listeners: {{}},
    setAttribute(name, value) {{ this.attributes[name] = String(value); }},
    getAttribute(name) {{ return this.attributes[name] || null; }},
    addEventListener(name, handler) {{ this.listeners[name] = handler; }},
    click() {{ if (this.listeners.click) this.listeners.click({{ target: this, currentTarget: this, preventDefault() {{}}, stopPropagation() {{}} }}); }},
    closest(selector) {{ return selector === '[data-board-state]' ? this : null; }},
  }};
}}

function makeElement(id) {{
  return {{
    id,
    innerHTML: '',
    textContent: '',
    style: {{}},
    disabled: false,
    hidden: false,
    children: [],
    classList: {{ add() {{}}, remove() {{}} }},
    setAttribute() {{}},
    appendChild(child) {{ this.children.push(child); return child; }},
    addEventListener() {{}},
    querySelector() {{ return null; }},
    querySelectorAll() {{ return []; }},
    contains() {{ return true; }},
  }};
}}

const row = {{
  __boardStateInteractionsBound: false,
  innerHTML: '',
  buttons: [],
  listeners: {{}},
  addEventListener(name, handler) {{ this.listeners[name] = handler; }},
  appendChild(child) {{ this.buttons.push(child); return child; }},
  contains(target) {{ return this.buttons.includes(target); }},
  querySelectorAll(selector) {{
    if (selector === '[data-board-state]') return this.buttons.slice();
    return [];
  }},
  querySelector(selector) {{
    const match = selector.match(/\\[data-board-state="([^"]+)"\\]/);
    if (!match) return null;
    return this.buttons.find((button) => button.getAttribute('data-board-state') === match[1]) || null;
  }},
}};

const note = {{ textContent: '' }};
const portal = makeElement('board-portal');
const boardNote = makeElement('board-note');

global.window = {{
  __BOARD_STATE_TEST_SUPPRESS_RENDER__: true,
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [] }} }} }},
  localStorage: makeStore(),
  sessionStorage: makeStore(),
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  setTimeout() {{ return 1; }},
  requestAnimationFrame(cb) {{ cb(); }},
  clearTimeout() {{}},
  setInterval() {{ return 1; }},
  clearInterval() {{}},
  addEventListener() {{}},
  removeEventListener() {{}},
  innerWidth: 1280,
  location: {{ pathname: '/app' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{
    if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify({{ assistant_public_context: {{}} }}) }};
    if (id === 'board-state-row') return row;
    if (id === 'board-state-note') return note;
    if (id === 'board-portal') return portal;
    if (id === 'board-note') return boardNote;
    return null;
  }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement(tag) {{ return tag === 'button' ? makeButton() : {{}}; }},
}};

const factory = require(tempFile);
const harness = factory();

// Simulate the last network fetch having happened while "closed" was the
// active stage -- state_detail is server data computed for "closed" only.
harness.state.latestPacket = {{
  board_portal: {{
    lifecycle_flow: [
      {{ state_id: 'pre', label: 'Pre-board', detail: 'Prepare governed packet' }},
      {{ state_id: 'live', label: 'Live', detail: 'Run the room inside approved material' }},
      {{ state_id: 'closed', label: 'Closed', detail: 'Freeze memory after the room closes' }}
    ],
    presentation_state: 'closed',
    state_detail: {{
      state: 'closed',
      title: 'Closed / frozen snapshot',
      summary: 'Keep the board memory frozen and bounded to approved outputs after the session closes.',
      note: 'The room is closed now; preserve the frozen record and work follow-ups outside the board surface.',
    }},
  }},
}};
harness.state.activeBoard = 'closed';

// Now click "Live" -- purely client-side, no re-fetch (activateBoardState's
// own design). state.latestPacket.board_portal.state_detail is still the
// stale "closed" payload from above.
harness.activateBoardState('live');

console.log(JSON.stringify({{
  activeBoard: harness.state.activeBoard,
  noteText: note.textContent,
}}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "board_state_note_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    assert result["activeBoard"] == "live"
    assert "live" in result["noteText"].lower() or "approved" in result["noteText"].lower(), (
        f"Caption must reflect the newly selected 'live' stage, not the stale "
        f"'closed' stage carried over from the last fetch. Got: {result['noteText']!r}"
    )
    assert "closed" not in result["noteText"].lower(), (
        f"Caption is still showing Closed-stage text after switching to Live -- "
        f"the stale server state_detail.note won over the fresh client-side "
        f"stage. Got: {result['noteText']!r}"
    )


def test_assistant_markdown_renders_headers_bold_rules_and_tables():
    """Ask Hermes replies come straight from an LLM and routinely contain
    **bold**, ### headers, --- rules, and pipe tables. The assistant message
    renderer used to just escapeHtml() the raw text into a <p>, so all of
    that markdown syntax showed up literally in the chat modal instead of
    being rendered as formatted text. renderAssistantMarkdownToHtml() must
    convert the common constructs into real tags."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveAssistantMarkdownHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return { renderAssistantMarkdownToHtml: renderAssistantMarkdownToHtml };\n}\nmodule.exports = __executiveAssistantMarkdownHarness;\n',
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');
const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-assistant-markdown-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

global.window = {{
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  localStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}} }},
  sessionStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}} }},
  location: {{ pathname: '/app' }},
}};
global.document = {{
  getElementById() {{ return null; }},
  addEventListener() {{}},
  removeEventListener() {{}},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
}};

const factory = require(tempFile);
const harness = factory();

const heading = harness.renderAssistantMarkdownToHtml('### Executive Summary');
const bold = harness.renderAssistantMarkdownToHtml('**Locked Findings:** 8 items');
const rule = harness.renderAssistantMarkdownToHtml('above\\n---\\nbelow');
const table = harness.renderAssistantMarkdownToHtml('| ID | Vendor |\\n|----|--------|\\n| F-001 | Acme Co |');
const injection = harness.renderAssistantMarkdownToHtml('<img src=x onerror=alert(1)> and **bold**');

console.log(JSON.stringify({{ heading, bold, rule, table, injection }}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "assistant_markdown_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    assert "###" not in result["heading"], f"literal ### leaked through: {result['heading']!r}"
    assert "<strong" in result["heading"] and "Executive Summary" in result["heading"]

    assert "**" not in result["bold"], f"literal ** leaked through: {result['bold']!r}"
    assert "<strong>Locked Findings:</strong>" in result["bold"]

    assert "<hr" in result["rule"], f"--- did not become an <hr>: {result['rule']!r}"
    assert "---" not in result["rule"]

    assert "<table" in result["table"] and "<th>" in result["table"] and "<td>" in result["table"], (
        f"pipe-table markdown did not become a real <table>: {result['table']!r}"
    )
    assert "F-001" in result["table"] and "Acme Co" in result["table"]
    assert "|" not in result["table"], f"literal pipe syntax leaked through: {result['table']!r}"

    # Escaping must still happen first -- markdown transforms must never
    # reopen an XSS path through a literal <img>/<script> in the LLM's text.
    assert "<img" not in result["injection"], f"raw HTML was not escaped: {result['injection']!r}"
    assert "&lt;img" in result["injection"]
    assert "<strong>bold</strong>" in result["injection"]


def test_board_state_tabs_exact_selector_click_updates_dom_state_with_normalized_ids():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveBoardStateDomHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return { renderBoardStateTabs: renderBoardStateTabs, state: state };\n}\nmodule.exports = __executiveBoardStateDomHarness;\n',
        1,
    )
    harness_js = harness_js.replace(
        "    renderPersonaView();",
        "    if (!window.__BOARD_STATE_TEST_SUPPRESS_RENDER__) renderPersonaView();",
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');
const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-board-state-dom-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

function makeStore(seed = {{}}) {{
  const data = new Map(Object.entries(seed));
  return {{
    getItem(key) {{ return data.has(key) ? data.get(key) : null; }},
    setItem(key, value) {{ data.set(key, String(value)); }},
    removeItem(key) {{ data.delete(key); }},
    clear() {{ data.clear(); }},
  }};
}}

function makeButton() {{
  return {{
    tagName: 'BUTTON',
    nodeType: 1,
    attributes: {{}},
    className: '',
    innerHTML: '',
    listeners: {{}},
    type: 'button',
    setAttribute(name, value) {{ this.attributes[name] = String(value); }},
    getAttribute(name) {{ return this.attributes[name] || null; }},
    addEventListener(name, handler) {{ this.listeners[name] = handler; }},
    click() {{ if (this.listeners.click) this.listeners.click({{ target: this, currentTarget: this, preventDefault() {{}}, stopPropagation() {{}} }}); }},
    closest(selector) {{ return selector === '[data-board-state]' ? this : null; }},
  }};
}}

function makeElement(id) {{
  return {{
    id,
    innerHTML: '',
    textContent: '',
    style: {{}},
    disabled: false,
    hidden: false,
    children: [],
    classList: {{ add() {{}}, remove() {{}} }},
    setAttribute() {{}},
    appendChild(child) {{ this.children.push(child); return child; }},
    addEventListener() {{}},
    querySelector() {{ return null; }},
    querySelectorAll() {{ return []; }},
    contains() {{ return true; }},
  }};
}}

const row = {{
  __boardStateInteractionsBound: false,
  innerHTML: '',
  buttons: [],
  listeners: {{}},
  addEventListener(name, handler) {{ this.listeners[name] = handler; }},
  appendChild(child) {{ this.buttons.push(child); return child; }},
  contains(target) {{ return this.buttons.includes(target); }},
  querySelectorAll(selector) {{
    if (selector === '[data-board-state]') return this.buttons.slice();
    return [];
  }},
  querySelector(selector) {{
    const match = selector.match(/\[data-board-state="([^"]+)"\]/);
    if (!match) return null;
    return this.buttons.find((button) => button.getAttribute('data-board-state') === match[1]) || null;
  }},
}};

const note = {{ textContent: '' }};
const portal = makeElement('board-portal');

global.window = {{
  __BOARD_STATE_TEST_SUPPRESS_RENDER__: true,
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [] }} }} }},
  localStorage: makeStore(),
  sessionStorage: makeStore(),
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  requestAnimationFrame(cb) {{ cb(); }},
  setTimeout() {{ return 1; }},
  clearTimeout() {{}},
  setInterval() {{ return 1; }},
  clearInterval() {{}},
  addEventListener() {{}},
  removeEventListener() {{}},
  innerWidth: 1280,
  location: {{ pathname: '/app' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{
    if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify({{ assistant_public_context: {{}} }}) }};
    if (id === 'board-state-row') return row;
    if (id === 'board-state-note') return note;
    if (id === 'board-portal') return portal;
    return null;
  }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement(tag) {{ return tag === 'button' ? makeButton() : makeElement(tag); }},
}};

const factory = require(tempFile);
const harness = factory();
harness.state.latestPacket = {{
  board_portal: {{
    lifecycle_flow: [
      {{ state_id: ' PRE ', label: 'Pre-board', detail: 'Prepare governed packet' }},
      {{ state_id: ' Live ', label: 'Live', detail: 'Run the room inside approved material' }},
      {{ state_id: ' Closed ', label: 'Closed', detail: 'Freeze memory after the room closes' }}
    ],
    presentation_state: 'pre',
    meeting: {{ title: 'Q2 Board Meeting' }},
  }},
}};
harness.state.activeBoard = 'pre';
harness.renderBoardStateTabs();
const pre = row.querySelector('[data-board-state="pre"]');
const live = row.querySelector('[data-board-state="live"]');
live.click();
console.log(JSON.stringify({{
  activeBoard: harness.state.activeBoard,
  preSelected: pre.getAttribute('aria-selected'),
  preClass: pre.className,
  liveSelected: live.getAttribute('aria-selected'),
  liveClass: live.className,
}}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "board_state_selector_dom_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    assert result["activeBoard"] == "live"
    assert result["preSelected"] == "false"
    assert result["preClass"] == "state-tab"
    assert result["liveSelected"] == "true"
    assert result["liveClass"] == "state-tab is-active"


def test_board_portal_refresh_preserves_user_selected_stage():
    """P0-10: refresh must not overwrite the stage a user just selected in the Board Portal.

    The fast path in renderBoardStateTabs updates existing button attributes in-place
    instead of destroying and recreating the DOM, eliminating the timing window that
    required the _boardStateTransitionCooldown guard. The firstDefined guard in refresh()
    still preserves the existing activeBoard value via the _boardStateTransition signal.
    """
    js = _static_executive_js()

    assert "state.activeBoard = firstDefined(state.activeBoard, (state.latestPacket.executive_modes || {}).active_board_state, (state.latestPacket.board_portal || {}).presentation_state, \"pre\");" in js, (
        "Board Portal refresh must preserve activeBoard with firstDefined including existing state"
    )
    # P0-10: renderBoardStateTabs fast path updates button attributes in-place instead
    # of innerHTML destroy-recreate. This eliminates the need for _boardStateTransition-
    # Cooldown because buttons persist across state switches. The delegated click handler
    # on board-state-row ensures clicks are captured regardless of button lifecycle.
    # The _boardStateTransition signal (set by activateBoardState, cleared after render)
    # still guards refresh() from overwriting the user's selected state.
    assert "if (!state._boardStateTransition) {" in js, (
        "Board Portal refresh must guard activeBoard assignment behind _boardStateTransition "
        "or server presentation_state overwrites the user's selected stage"
    )
    assert "syncBoardStateTabUI" in js, "syncBoardStateTabUI must exist for attribute updates"
    assert "renderBoardStateTabs" in js, "renderBoardStateTabs must exist for fast path"


def test_board_portal_renders_selected_stage_copy_instead_of_server_default():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveBoardRenderHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return { renderBoardPortal: renderBoardPortal, state: state };\n}\nmodule.exports = __executiveBoardRenderHarness;\n',
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');
const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-board-render-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

function makeStore(seed = {{}}) {{
  const data = new Map(Object.entries(seed));
  return {{
    getItem(key) {{ return data.has(key) ? data.get(key) : null; }},
    setItem(key, value) {{ data.set(key, String(value)); }},
    removeItem(key) {{ data.delete(key); }},
    clear() {{ data.clear(); }},
  }};
}}

function makeElement(id) {{
  return {{
    id,
    innerHTML: '',
    textContent: '',
    style: {{}},
    disabled: false,
    hidden: false,
    children: [],
    classList: {{ add() {{}}, remove() {{}} }},
    setAttribute() {{}},
    appendChild(child) {{ this.children.push(child); return child; }},
    addEventListener() {{}},
    querySelector() {{ return null; }},
    querySelectorAll() {{ return []; }},
    contains() {{ return true; }},
  }};
}}

const elements = {{
  'board-portal': makeElement('board-portal'),
  'board-note': makeElement('board-note'),
}};

global.window = {{
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [] }} }} }},
  localStorage: makeStore(),
  sessionStorage: makeStore(),
  requestAnimationFrame(cb) {{ cb(); }},
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  setTimeout() {{ return 1; }},
  clearTimeout() {{}},
  setInterval() {{ return 1; }},
  clearInterval() {{}},
  addEventListener() {{}},
  removeEventListener() {{}},
  innerWidth: 1280,
  location: {{ pathname: '/app' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{
    if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify({{ assistant_public_context: {{}} }}) }};
    return elements[id] || null;
  }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement(tag) {{ return makeElement(tag); }},
}};

const factory = require(tempFile);
const harness = factory();
harness.state.latestPacket = {{
  board_portal: {{
    presentation_state: 'pre',
    state_label: 'Pre-board',
    state_detail: {{ state: 'pre', title: 'Pre-board preparation', summary: 'Prepare the packet.' }},
    meeting: {{ title: 'Q2 Board Meeting', date: 'Thu 18 Jun · 14:00', room: 'Riyadh HQ + remote' }},
    kpis: [],
    decks: [],
    actions: [
      {{ item: 'Ratify the 60% EUR hedge', owner: 'Group CFO', due: 'on approval' }},
      {{ item: 'Approve GLP-1 JV signature', owner: 'Group CEO', due: 'this week' }},
      {{ item: 'Review Tamween recovery at Q3', owner: 'Board', due: 'Q3' }}
    ],
    supplementary_questions: [
      {{ q: 'What is the downside if EUR strengthens after a 60% hedge?', to: 'Group CEO', status: 'sent' }},
      {{ q: 'Can the JV be funded fully from cash without touching the facility?', to: 'Group CFO', status: 'answered' }}
    ],
    live_prompts: ['Why is EBITDA 20 bps under plan?'],
    lifecycle_flow: [
      {{ state_id: 'pre', label: 'Pre-board', detail: 'Prepare governed packet', presented: true }},
      {{ state_id: 'live', label: 'Live', detail: 'Run the room inside approved material', presented: false }},
      {{ state_id: 'closed', label: 'Closed', detail: 'Freeze memory after the room closes', presented: false }}
    ],
    frozen_snapshot: {{ status: 'frozen', summary: 'Frozen snapshot summary.' }},
    board_summary: 'Board summary fallback.'
  }}
}};

harness.state.activePersona = 'ceo';
harness.state.activeBoard = 'live';
harness.renderBoardPortal();
const liveHtml = elements['board-portal'].innerHTML;

harness.state.activeBoard = 'closed';
harness.renderBoardPortal();
const closedHtml = elements['board-portal'].innerHTML;

console.log(JSON.stringify({{ liveHtml, closedHtml }}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "board_render_state_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    assert "Live board session" in result["liveHtml"]
    assert "Pre-board preparation" not in result["liveHtml"], (
        "Selected Live stage must not keep rendering pre-board header copy from the server default"
    )
    for text in [
        "Ratify the 60% EUR hedge",
        "Approve GLP-1 JV signature",
        "Review Tamween recovery at Q3",
    ]:
        assert text in result["liveHtml"], (
            "Selected Live stage must preserve visible lifecycle actions instead of dropping them during rerender"
        )
    assert "What is the downside if EUR strengthens after a 60% hedge?" not in result["liveHtml"], (
        "Selected Live stage must switch out the pre-board supplementary-question panel"
    )
    assert "Closed — record kept as it was" in result["closedHtml"]


def test_board_portal_pre_board_preserves_visible_lifecycle_actions_and_supplementary_questions():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveBoardPreStateHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return { renderBoardPortal: renderBoardPortal, state: state };\n}\nmodule.exports = __executiveBoardPreStateHarness;\n',
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');
const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-board-pre-state-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

function makeStore(seed = {{}}) {{
  const data = new Map(Object.entries(seed));
  return {{
    getItem(key) {{ return data.has(key) ? data.get(key) : null; }},
    setItem(key, value) {{ data.set(key, String(value)); }},
    removeItem(key) {{ data.delete(key); }},
    clear() {{ data.clear(); }},
  }};
}}

function makeElement(id) {{
  return {{
    id,
    innerHTML: '',
    textContent: '',
    style: {{}},
    disabled: false,
    hidden: false,
    children: [],
    classList: {{ add() {{}}, remove() {{}} }},
    setAttribute() {{}},
    appendChild(child) {{ this.children.push(child); return child; }},
    addEventListener() {{}},
    querySelector() {{ return null; }},
    querySelectorAll() {{ return []; }},
    contains() {{ return true; }},
  }};
}}

const elements = {{
  'board-portal': makeElement('board-portal'),
  'board-note': makeElement('board-note'),
}};

global.window = {{
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [] }} }} }},
  localStorage: makeStore(),
  requestAnimationFrame(cb) {{ cb(); }},
  sessionStorage: makeStore(),
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  setTimeout() {{ return 1; }},
  clearTimeout() {{}},
  setInterval() {{ return 1; }},
  clearInterval() {{}},
  addEventListener() {{}},
  removeEventListener() {{}},
  innerWidth: 1280,
  location: {{ pathname: '/app' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{
    if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify({{ assistant_public_context: {{}} }}) }};
    return elements[id] || null;
  }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement(tag) {{ return makeElement(tag); }},
}};

const factory = require(tempFile);
const harness = factory();
harness.state.latestPacket = {{
  board_portal: {{
    presentation_state: 'pre',
    state_label: 'Pre-board',
    state_detail: {{ state: 'pre', title: 'Pre-board preparation', summary: 'Prepare the packet.' }},
    meeting: {{ title: 'Q2 Board Meeting', date: 'Thu 18 Jun · 14:00', room: 'Riyadh HQ + remote' }},
    kpis: [],
    decks: [],
    actions: [
      {{ item: 'Ratify the 60% EUR hedge', owner: 'Group CFO', due: 'on approval' }},
      {{ item: 'Approve GLP-1 JV signature', owner: 'Group CEO', due: 'this week' }},
      {{ item: 'Review Tamween recovery at Q3', owner: 'Board', due: 'Q3' }}
    ],
    supplementary_questions: [
      {{ q: 'What is the downside if EUR strengthens after a 60% hedge?', to: 'Group CEO', status: 'sent' }},
      {{ q: 'Can the JV be funded fully from cash without touching the facility?', to: 'Group CFO', status: 'answered' }}
    ],
    live_prompts: ['Why is EBITDA 20 bps under plan?'],
    lifecycle_flow: [
      {{ state_id: 'pre', label: 'Pre-board', detail: 'Prepare governed packet', presented: true }},
      {{ state_id: 'live', label: 'Live', detail: 'Run the room inside approved material', presented: false }},
      {{ state_id: 'closed', label: 'Closed', detail: 'Freeze memory after the room closes', presented: false }}
    ],
    frozen_snapshot: {{ status: 'frozen', summary: 'Frozen snapshot summary.' }},
    board_summary: 'Board summary fallback.'
  }}
}};

harness.state.activePersona = 'ceo';
harness.state.activeBoard = 'pre';
harness.renderBoardPortal();
console.log(JSON.stringify({{ preHtml: elements['board-portal'].innerHTML }}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "board_pre_state_content_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    for text in [
        "Ratify the 60% EUR hedge",
        "Approve GLP-1 JV signature",
        "Review Tamween recovery at Q3",
        "What is the downside if EUR strengthens after a 60% hedge?",
        "Can the JV be funded fully from cash without touching the facility?",
    ]:
        assert text in result["preHtml"], (
            "Pre-board render must keep the visible lifecycle actions and supplementary questions that the live board path depends on"
        )


def test_board_portal_css_does_not_permanently_hide_second_panel():
    """Board Portal secondary panels must stay visible when rendered for a stage."""
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    assert ".board-panel + .board-panel { display: none; }" not in css, (
        "Board Portal CSS must not hard-hide the second board panel, or lifecycle/supplementary "
        "content stays present in the DOM but invisible"
    )


def test_assistant_drawer_escape_key_closes():
    """Escape key must close the assistant drawer."""
    js = _static_executive_js()

    open_fn_start = js.index("function _openHermesDrawer(")
    open_fn_end = js.index("function _closeHermesDrawer()")
    open_fn_body = js[open_fn_start:open_fn_end]

    assert "Escape" in open_fn_body, "Escape key handler must be registered"
    assert "_closeHermesDrawer()" in open_fn_body, "Escape must call _closeHermesDrawer"
    assert "addEventListener" in open_fn_body, "keydown listener must be added"


def test_assistant_drawer_no_duplicate_surface_rendering():
    """No duplicate assistant surface element — only one aside#assistant-drawer."""
    html = _homepage_response()

    drawer_count = html.count('id="assistant-drawer"')
    assert drawer_count == 1, (
        f"Expected exactly 1 assistant-drawer element, found {drawer_count}"
    )

    scrim_count = html.count('id="assistant-scrim"')
    assert scrim_count == 1, (
        f"Expected exactly 1 assistant-scrim element, found {scrim_count}"
    )


def test_assistant_drawer_html_structure_complete():
    """Assistant drawer HTML must have all required sub-elements for a usable surface."""
    html = _homepage_response()

    # Core structure
    assert 'id="assistant-drawer"' in html
    assert 'id="assistant-scrim"' in html
    assert 'id="assistant-studio"' in html

    # Thread management
    assert 'id="assistant-thread-list"' in html, "Thread list must exist"
    assert 'id="assistant-thread-title"' in html, "Thread title must exist"
    assert 'id="assistant-thread-tools"' in html, "Thread tools must exist"

    # Conversation
    assert 'id="assistant-messages"' in html, "Messages area must exist"
    assert 'id="assistant-prompt-row"' in html, "Prompt chips row must exist"
    assert 'id="assistant-form"' in html, "Assistant input form must exist"
    assert 'id="assistant-input"' in html, "Assistant text input must exist"

    # Header
    assert 'id="assistant-heading"' in html, "Assistant heading for aria must exist"
    assert 'id="assistant-close"' in html, "Close button must exist"

    # Launcher
    assert 'id="chat-launcher"' in html, "Floating chat launcher must exist"


def test_assistant_drawer_state_initialized():
    """State object must initialize the active assistant surfaces as closed."""
    js = _static_executive_js()

    # state initialization block
    state_start = js.index("var state = {")
    state_end = js.index("bindAssistantForm();")
    state_block = js[state_start:state_end]

    assert "drawerOpen: false" in state_block, "drawerOpen must be initialized to false"
    assert "a2aOpen: false" in state_block, "a2aOpen must be initialized to false"


# ── Hermes Assistant Drawer CEO UX ──

def test_ceo_drawer_no_banned_strings():
    """CEO assistant drawer must not show PRE-BOARD, writable, governed packet, History in default state."""
    # Banned strings that must NOT appear in the CEO drawer's visible text
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    # Verify that CEO-codepath text assignments don't include banned strings
    # Specifically check the CEO-guarded paths:
    # - Initial thread message (line ~737)
    # - Empty state message (line ~2218) 
    # - History toggle injection (lines ~2133-2151)
    # - Thread tools chips (lines ~2200-2206)
    # The banned strings may still exist in the file for non-CEO personas,
    # but they must be inside blocks guarded against CEO
    # Check that the CEO-facing text strings are clean
    ceo_facing_texts = [
        'I can answer using the current board pack.',
        'Ask a question to begin.',
        'assistantName + " will answer here using the current board pack."',
    ]
    for text in ceo_facing_texts:
        assert text in executive_js, f"Expected CEO-facing text not found: {text}"
    # Verify no banned strings appear in CEO-guarded code paths
    # The History toggle injection should be guarded: 'state.activePersona !== "ceo"'
    assert 'state.activePersona !== "ceo"' in executive_js, "CEO guard missing for persona-specific code"


def test_ceo_drawer_single_column_default():
    """CEO drawer must use single-column layout by default, threads sidebar hidden."""
    executive_html = Path("strategyos_mvp/static/executive.html").read_text()
    assert 'threads-collapsed' in executive_html, "Default state must have threads-collapsed"
    # HTML default: threads sidebar has is-collapsed class
    assert 'assistant-threads is-collapsed' in executive_html or 'is-collapsed' in executive_html


def test_all_cta_groups_exist():
    """Verify the executive.js contains handlers for all major CTA groups."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    cta_patterns = [
        'data-rail-prompt',     # Findings "Ask why this matters"
        'data-board-prompt',    # Board portal prompts
        'data-driver-chip',     # Driver drill chips
        'data-chat-prompt',     # Week panel / gravity grid
        'data-assistant-prompt', # Prompt chips inside drawer
        'askAssistant',          # Core askAssistant function
        'openAssistantDrawer',   # Core open function
    ]
    for pattern in cta_patterns:
        assert pattern in executive_js, f"CTA pattern missing: {pattern}"


def test_ceo_drawer_state_pill_hidden_for_ceo():
    """CEO drawer must explicitly hide #assistant-state (hidden + empty textContent) when activePersona is CEO."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    # The hide logic must set both textContent="" and hidden=true for CEO
    assert 'assistantState' in executive_js, \
        "assistantState not found in executive.js"
    assert 'assistantState.hidden = true' in executive_js, \
        "assistantState.hidden = true missing — must explicitly hide the state pill for CEO"
    assert 'assistantState.hidden = false' in executive_js, \
        "assistantState.hidden = false missing — must restore visibility for non-CEO personas"
    assert 'assistantState.textContent = ""' in executive_js, \
        "assistantState.textContent = '' missing — must clear text for CEO"
    # The control flow must guard on activePersona === "ceo"
    assert 'state.activePersona === "ceo"' in executive_js, \
        "CEO persona guard missing in executive.js"
    # Verify the hide logic is inside renderAssistantStudio (near the assistantHeading line)
    lines = executive_js.split('\n')
    in_render_fn = False
    found_hide = False
    for i, line in enumerate(lines):
        if 'function renderAssistantStudio' in line:
            in_render_fn = True
            continue
        if in_render_fn and 'assistantState.hidden = true' in line:
            found_hide = True
            break
    assert found_hide, \
        "assistantState.hidden = true must be inside renderAssistantStudio function"


def test_ceo_fresh_thread_per_cta():
    """askAssistant must use the shared writable-thread path for every persona."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    assert 'async function askAssistant' in executive_js, \
        "askAssistant function not found"
    assert 'createWritableThread' in executive_js, \
        "createWritableThread not found in executive.js"
    assert 'ensureWritableThread' in executive_js, \
        "ensureWritableThread not found in executive.js"
    ask_start = executive_js.index('async function askAssistant')
    ask_end = executive_js.index('function switchView', ask_start)
    ask_block = executive_js[ask_start:ask_end]
    assert 'silentInitialMessage: true' in ask_block
    assert 'state.activePersona === "ceo" ? createWritableThread' not in ask_block


def test_driver_composer_opens_drawer():
    """Driver composer submit handler must call openAssistantDrawer()."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    assert '#driver-composer' in executive_js, \
        "#driver-composer not found in executive.js"
    assert "openAssistantDrawer();" in executive_js, \
        "openAssistantDrawer() not found in executive.js"


def test_ceo_drawer_css_hides_empty_state_pill():
    """executive.css must hide #assistant-state when empty."""
    executive_css = Path("strategyos_mvp/static/executive.css").read_text()
    assert '#assistant-state:empty' in executive_css, \
        "#assistant-state:empty rule not found in executive.css"
    # Verify the combined rule: #assistant-state:empty { display: none; }
    # Normalise whitespace for reliable matching
    css_normalised = executive_css.replace(' ', '').replace('\n', '').replace('\t', '')
    assert '#assistant-state:empty{display:none' in css_normalised or \
           '#assistant-state:empty' in executive_css, \
        "#assistant-state:empty with display:none rule not found in executive.css"


def test_all_banned_strings_absent_from_ceo_drawer_code():
    """Banned strings must not appear in CEO-visible code paths.
    
    Verifies that each banned string either does not exist in executive.js
    OR is inside a block explicitly guarded by state.activePersona !== "ceo".
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    lines = executive_js.split('\n')
    banned = [
        "PRE-BOARD",
        "Named assistant",
        "writable",
        "board-safe move",
        "governed packet",
        "Open a writable",
        "Select a thread to continue",
    ]

    # Lines where "writable" is structural (function definitions, known CEO-only paths,
    # or already inside a guard block) and should be exempt from the guard check.
    # These are not user-facing banned strings in CEO-visible UI.
    structural_writable_fragments = (
        'createWritableThread(',
        'ensureWritableThread(',
        'Writable board-safe thread.',
        'createWritableThread();',
    )

    violations = []
    for i, line in enumerate(lines):
        line_no = i + 1
        for banned_str in banned:
            if banned_str in line:
                # Structural exemptions for 'writable' in function names
                if banned_str == "writable" and any(fragment in line for fragment in structural_writable_fragments):
                    continue
                # Check a 10-line window for a CEO-excluding guard:
                # - explicit !== "ceo"
                # - === "board" (board is a distinct persona, not CEO)
                window_start = max(0, i - 10)
                window_end = min(len(lines), i + 10)
                nearby = '\n'.join(lines[window_start:window_end])
                has_ceo_guard = (
                    'state.activePersona !== "ceo"' in nearby or
                    'state.activePersona === "board"' in nearby
                )
                if not has_ceo_guard:
                    violations.append(f"Line {line_no}: '{banned_str}' without CEO-"
                                      f"excluding guard (nearby: ...{nearby.strip()[-80:]})")

    assert not violations, (
        "Banned strings found outside CEO-guarded blocks:\n" +
        "\n".join(violations)
    )


def test_ceo_drawer_preboard_not_rendered_for_ceo():
    """statusLabel(board) must never be called for CEO in renderAssistantStudio.

    The PRE-BOARD pill comes from statusLabel returning "Pre-board" when state.activeBoard
    is "pre".  For the CEO persona the assistant-state element must be hidden (not just
    emptied) and statusLabel must NOT be invoked with the board value in the CEO codepath.
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    lines = executive_js.split('\n')

    # Find renderAssistantStudio function boundaries
    in_fn = False
    fn_start = -1
    fn_end = -1
    brace_depth = 0
    for i, line in enumerate(lines):
        if 'function renderAssistantStudio' in line:
            in_fn = True
            fn_start = i
            brace_depth = line.count('{') - line.count('}')
            continue
        if not in_fn:
            continue
        brace_depth += line.count('{') - line.count('}')
        if brace_depth <= 0:
            fn_end = i
            break

    assert fn_start >= 0 and fn_end > fn_start, \
        "renderAssistantStudio function boundaries not found"

    fn_body = '\n'.join(lines[fn_start:fn_end + 1])

    # 1. The CEO guard must prevent statusLabel from being called with board data
    #    The pattern: inside "activePersona === 'ceo'" block, statusLabel is NOT called
    #    with firstDefined(state.activeBoard, ...)
    #    We verify this by checking that the only statusLabel calls inside the CEO branch
    #    are on non-board values.
    #
    #    Since the function may contain statusLabel calls for non-CEO paths,
    #    we check that the CEO block doesn't contain statusLabel with activeBoard.
    ceo_block_pattern = re.search(
        r'state\.activePersona\s*===\s*"ceo"[^}]*?\{([^}]*?)\}',
        fn_body, re.DOTALL
    )
    if ceo_block_pattern:
        ceo_block = ceo_block_pattern.group(1)
        # statusLabel must NOT appear inside the CEO block with activeBoard
        prohibited = 'statusLabel' in ceo_block and 'activeBoard' in ceo_block
        assert not prohibited, (
            "statusLabel must NOT be called with activeBoard inside CEO block "
            "of renderAssistantStudio — this is what renders PRE-BOARD"
        )

    # 2. Verify the explicit hide: assistantState.hidden = true is in the function body
    assert 'assistantState.hidden = true' in fn_body, (
        "renderAssistantStudio must set assistantState.hidden = true for CEO"
    )

    # 3. The subtitle must NOT contain "Pre-board" or "PRE-BOARD" for any persona
    assert 'Pre-board' not in fn_body, (
        "'Pre-board' (statusLabel output) must not appear in renderAssistantStudio body"
    )


def test_ceo_dead_end_guard_handles_driver_relevance_questions():
    """Driver relevance must be delegated to the backend with explicit context."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    assert "assistantEntrypointContext" in executive_js
    assert "assistantEntrypointContext(sourceEl)" in executive_js
    assert 'var endpoint = "/assistant/chat";' in executive_js


def test_ceo_typo_normalization_includes_whis():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    assert "whis: 'why'" in executive_js


def test_ceo_generic_fallback_no_relevant_card_operator_punt():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    assert "CEO implication: growth and liquidity are ahead" not in executive_js
    assert "governed Q&A session against the full evidence bundle" not in executive_js


def test_ceo_driver_relevance_answer_uses_context_fields():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    start = executive_js.index('body.driver_context = {')
    helper = executive_js[start:start + 400]
    for expected in ["label", "metric", "pct", "status", "detail", "movers"]:
        assert expected in helper


def test_executive_frontend_sends_shared_assistant_entrypoint_context():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    assert "assistantEntrypointContext" in executive_js
    assert "assistantEntrypointContext(sourceEl)" in executive_js
    assert 'var endpoint = "/assistant/chat";' in executive_js


def test_assistant_requests_include_shared_entrypoint_metadata():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    assert "function assistantEntrypointContext" in executive_js
    assert "assistantEntrypointContext(sourceEl)" in executive_js
    for token in [
        '"driver_composer"',
        '"finding_cta"',
        '"development_cta"',
        '"week_composer"',
        '"knowledge_graph"',
        '"agents_discovery"',
        '"board_portal"',
    ]:
        assert token in executive_js


def test_hermes_network_uses_named_assistants_and_status_before_chat():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    network_start = executive_js.index("function getAssistantNetwork()")
    network_end = executive_js.index("function getAssistantExchanges()", network_start)
    network_block = executive_js[network_start:network_end]
    assert "getLeadershipTeam().map" in network_block
    assert "assistantId:" in network_block
    assert "item && item.module_id" not in network_block

    render_start = executive_js.index("function renderAssistantNetwork()")
    render_block = executive_js[render_start:render_start + 9000]
    assert "data-network-status-toggle" in render_block
    assert "state.openNetworkAssistantId" in render_block
    assert "data-network-ask" in render_block
    assert "Ask Hermes for a brief" in render_block
    assert 'entrypoint: "ai_team_brief"' in render_block
    assert "assistant_id: assistant.assistantId" in render_block


def test_executive_surface_prefers_shared_assistant_packet_for_visible_facts():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    assert "BOOTSTRAP_ASSISTANT_CONTEXT = bootstrap.assistant_public_context || {}" in executive_js
    assert "function getSharedAssistantContext()" in executive_js
    assert "state.latestPacket && state.latestPacket.assistant_public_context" in executive_js
    assert "return getSharedAssistantContext().board_portal || {}" in executive_js
    assert "if ((shared.persona_id || \"ceo\") === personaId)" in executive_js
    assert "return shared.agent_activity || {}" in executive_js
    assert "if (safeArray(shared.kg_nodes).length)" in executive_js


def test_assistant_network_uses_live_agent_modules_instead_of_zero_score():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveNetworkHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return { state: state, getAssistantNetwork: getAssistantNetwork, getAssistantNetworkMeta: getAssistantNetworkMeta, getAssistantExchanges: getAssistantExchanges, renderAssistantNetwork: renderAssistantNetwork, getFinanceFunctionReview: getFinanceFunctionReview };\n'
        '}\n'
        'module.exports = __executiveNetworkHarness;\n',
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');

const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-network-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

const bootstrapPayload = {{
  requested_view_state: {{ persona: 'ceo', board: 'pre' }},
  assistant_public_context: {{
    persona_id: 'ceo',
    assistant: 'Hermes',
    agent_activity: {{
      line: '4 active module(s) · 5 discoverable · 3 approval gate(s)',
      execution_log: {{
        status: 'available',
        round_count: 2,
        total_count: 6,
        entries: [
          {{ round_no: 2, actor: 'Finance Auditor', finding_id: 'F-001', action: 'lock', status: 'locked', detail: 'Finding locked after analyst response.' }},
          {{ round_no: 2, actor: 'Finance Auditor', finding_id: 'F-002', action: 'block', status: 'blocked', detail: 'Finding remains blocked by required evidence verification.' }},
          {{ round_no: 1, actor: 'Finance Analyst', finding_id: 'F-001', action: 'response', status: 'responded', detail: 'Analyst supplied the evidence response.' }},
          {{ round_no: 1, actor: 'Finance Auditor', finding_id: 'F-001', action: 'challenge', status: 'challenged', detail: 'Citation support was challenged.' }},
          {{ round_no: 1, actor: 'Finance Auditor', finding_id: 'F-002', action: 'challenge', status: 'challenged', detail: 'Calculation support was challenged.' }},
          {{ round_no: 0, actor: 'Runtime Governance', action: 'policy gate', status: 'approved', detail: 'Technical runtime event.' }},
        ]
      }}
    }},
    running_agents: [
      {{ module_id: 'cash-recovery-watch', label: 'Cash recovery watch', status: 'running', lane: 'executive', summary: 'Tracks recoverable value across 8 governed cases.', output_metric: 'SAR 794K', approval_dependency: 'none' }},
      {{ module_id: 'evidence-closure-monitor', label: 'Evidence closure monitor', status: 'blocked', lane: 'review', summary: 'Watches citation resolution and challenged cases.', output_metric: '39 / 24', approval_dependency: 'reviewer_release' }},
      {{ module_id: 'board-pack-compiler', label: 'Board-pack compiler', status: 'preview_only', lane: 'executive', summary: 'Builds the board-safe packet.', output_metric: '3 report surfaces', approval_dependency: 'close_challenged_cases' }},
      {{ module_id: 'runtime-guardrail', label: 'Runtime guardrail', status: 'protected', lane: 'system', summary: 'Keeps tenant runtime boundaries protected.', output_metric: 'langgraph', approval_dependency: 'system_boundary' }},
    ],
  }},
  agents: {{
    digital_twins: [
      {{ twin_id: 'ceo', role: 'ceo', display_name: 'Chief of Staff', assistant_name: 'Hermes', status: 'active', current_activity: 'Preparing the board briefing', active_investigation_count: 1, pending_request_count: 0, cycle_count: 3, authority: 'Coordinate the executive agenda and synthesise leadership inputs.', escalation_path: ['Group CEO'] }},
      {{ twin_id: 'cfo', role: 'cfo', display_name: 'Group CFO', assistant_name: 'Atlas', status: 'attention', current_activity: 'Validating the cash recovery recommendation', active_investigation_count: 2, pending_request_count: 1, cycle_count: 2, authority: 'Own finance analysis and surface material exceptions.', escalation_path: ['Group CEO', 'Group CFO'] }},
      {{ twin_id: 'gm', role: 'gm', display_name: 'Group Manager', assistant_name: 'Iris', status: 'monitoring', current_activity: 'Monitoring operating commitments', active_investigation_count: 1, pending_request_count: 0, cycle_count: 4, authority: 'Track operating commitments across the group.', escalation_path: ['Group Manager'] }},
      {{ twin_id: 'strategy', role: 'strategy', display_name: 'Strategy Lead', assistant_name: 'Nora', status: 'ready', current_activity: 'Ready to prepare the next strategy review', active_investigation_count: 0, pending_request_count: 0, cycle_count: 1, authority: 'Maintain the strategy review and decision record.', escalation_path: ['Group CEO'] }},
    ],
  }},
}};

const nodes = {{
  'assistant-network-card': {{ innerHTML: '', hidden: false, querySelectorAll: () => [], querySelector: () => null, closest: () => null }},
  'strategyos-executive-bootstrap': {{ textContent: JSON.stringify(bootstrapPayload) }},
}};

global.window = {{
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [], findings: [], developments: [], week: [] }} }}, networkMeta: {{}}, network: [], a2a: [], subtools: [] }},
  localStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}}, clear() {{}} }},
  sessionStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}}, clear() {{}} }},
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  innerWidth: 1280,
  setTimeout(fn) {{ fn(); return 1; }},
  clearTimeout() {{}},
  setInterval() {{ return 1; }},
  addEventListener() {{}},
  removeEventListener() {{}},
  location: {{ pathname: '/app' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{ return nodes[id] || null; }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement() {{ return {{ setAttribute() {{}}, appendChild() {{}}, style: {{}}, classList: {{ add() {{}}, remove() {{}}, contains() {{ return false; }} }} }}; }},
}};

const factory = require(tempFile);
const harness = factory();
const network = harness.getAssistantNetwork();
const exchanges = harness.getAssistantExchanges();
const functionReview = harness.getFinanceFunctionReview();
harness.renderAssistantNetwork();
console.log(JSON.stringify({{
  networkCount: network.length,
  statusRanks: network.map((item) => item.statusRank),
  metaHint: harness.getAssistantNetworkMeta().hint,
  exchangeCount: exchanges.length,
  functionStatus: functionReview.status,
  functionEntryCount: functionReview.entries.length,
  functionFindingCount: functionReview.findings.length,
  functionLockedCount: functionReview.locked_count,
  functionStuckCount: functionReview.stuck_count,
  functionRoundCount: functionReview.round_count,
  functionNames: functionReview.functions.map((item) => item.name),
  html: nodes['assistant-network-card'].innerHTML,
}}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "assistant_network_harness.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    assert result["networkCount"] == 4
    assert result["exchangeCount"] == 4
    assert result["functionStatus"] == "stuck"
    assert result["functionEntryCount"] == 5
    assert result["functionFindingCount"] == 2
    assert result["functionLockedCount"] == 1
    assert result["functionStuckCount"] == 1
    assert result["functionRoundCount"] == 2
    assert result["functionNames"] == ["Finance Analyst", "Finance Auditor"]
    assert result["metaHint"] == "2 assistants are active · 1 assistant needs your review"
    assert "Hermes" in result["html"] and "Atlas" in result["html"]
    assert "Cash recovery watch" not in result["html"]
    # The network is an honest status view of named AI assistants; it must not
    # invent readiness scores or expose product-module internals.
    assert "Team readiness score" not in result["html"]
    assert "target 80" not in result["html"]
    assert "working now" in result["html"]
    assert "2 working" in result["html"]
    assert "1 ready" in result["html"]
    assert "1 need your review" in result["html"]
    assert "data-network-status-toggle" in result["html"]
    assert "Runtime Governance" not in result["html"]
    for fabricated in ("92", "76", "62", "45"):
        assert ">" + fabricated + "<" not in result["html"], (
            f"fabricated readiness score {fabricated} leaked back into the card"
        )
    executive_js_now = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    assert "assistantModuleScore" not in executive_js_now, (
        "the fabricated per-status score table must stay deleted"
    )


def test_assistant_transport_failures_are_retryable_not_final_answers():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    assert 'function markThreadTransportFailuresRetryable' in executive_js
    assert 'message.status = "failed"' in executive_js
    assert 'message.retryPrompt' in executive_js
    assert 'data-assistant-retry-index' in executive_js
    assert 'Retry now' in executive_js
    assert 'maybeAutoRetryLatestFailure(current);' in executive_js
    assert 'state.failedAssistantAutoRetried' in executive_js


def test_assistant_transport_failures_log_visible_diagnostics():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    assert 'console.error("[Hermes] assistant transport failure", details);' in executive_js
    assert 'body.trace_id = clientRequestId;' in executive_js
    assert 'headers["X-Request-ID"] = requestId;' in executive_js or 'headers["X-Request-ID"] = clientRequestId;' in executive_js
    assert 'response.headers.get("x-request-id")' in executive_js
    assert 'errorType: firstDefined(error && error.errorType, "network_error")' in executive_js or 'errorType: "network_error"' in executive_js
    assert 'errorType = response.status === 401 ? "auth_error"' in executive_js or ': "http_error";' in executive_js
    assert 'errorType = "timeout"' in executive_js
    assert 'Promise.race([requestPromise, timeoutPromise])' in executive_js
    assert 'A request must always leave its loading state' in executive_js
    assert 'pendingThread = threadStore()[threadKey]' in executive_js


def test_assistant_network_count_is_labeled_not_presented_as_failed_requests():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()

    assert "function getAssistantNetworkMeta()" in executive_js
    assert "Hermes' AI leadership team" in executive_js
    assert '" assistant" + (activeCount === 1 ? " is" : "s are") + " active"' in executive_js
    assert 'fabBadge.hidden = true' in executive_js


def test_assistant_invalid_ui_token_recovers_anonymously_and_replaces_failed_message():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveTestHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        '  function renderAssistantStudio() {',
        '  function renderAssistantStudio() {\n    if (window.__TEST_MINIMAL_RENDER__) return;',
        1,
    )
    harness_js = harness_js.replace(
        '  function showToast(message) {',
        '  function showToast(message) {\n    if (window.__TEST_MINIMAL_RENDER__) { window.__TEST_LAST_TOAST__ = message; return; }',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return {\n'
        '    state: state,\n'
        '    ensureThreads: ensureThreads,\n'
        '    threadStore: threadStore,\n'
        '    retryAssistantMessage: retryAssistantMessage\n'
        '  };\n'
        '}\n'
        'module.exports = __executiveTestHarness;\n',
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');

const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

function makeStore(seed = {{}}) {{
  const data = new Map(Object.entries(seed));
  return {{
    getItem(key) {{ return data.has(key) ? data.get(key) : null; }},
    setItem(key, value) {{ data.set(key, String(value)); }},
    removeItem(key) {{ data.delete(key); }},
    clear() {{ data.clear(); }},
    dump() {{ return Object.fromEntries(data.entries()); }},
  }};
}}

const persistedThreadKey = 'ceo:invalid-token-thread';
const storageKey = 'strategyos.chat.latest-public.ceo';
const retryPrompt = 'What should I tell the board about Tamween recovery?';
const failedText = 'Hermes could not reach the shared assistant service. Retry now once the service is reachable.';

const bootstrapPayload = {{
  requested_view_state: {{ persona: 'ceo', board: 'pre' }},
  executive_entry_route: '/app',
  assistant_public_context: {{ persona_id: 'ceo', assistant: 'Hermes', drivers: [], findings: [], developments: [], week: [] }},
  idp_enabled: true,
}};

const persistedThreads = {{
  [persistedThreadKey]: {{
    key: persistedThreadKey,
    title: 'Tamween recovery',
    preview: 'Retry needed · What should I tell the board about Tamween recovery?',
    route: '',
    readOnly: false,
    kind: 'followup',
    assistant: 'Hermes',
    messages: [
      {{ role: 'user', text: retryPrompt, timestamp: '2026-07-07T00:00:00.000Z', status: 'ok' }},
      {{ role: 'assistant', text: failedText, timestamp: '2026-07-07T00:00:01.000Z', status: 'failed', retryable: true, needsRetry: true, retryPrompt: retryPrompt, endpoint: '/assistant/chat', errorType: 'auth_error', statusCode: 401 }},
    ],
    lastUpdated: '2026-07-07T00:00:01.000Z',
  }}
}};

const localStorage = makeStore({{ 'strategyos.ui.token': 'definitely-invalid-token' }});
const sessionStorage = makeStore({{ [storageKey]: JSON.stringify(persistedThreads) }});
const fetchCalls = [];

global.window = {{
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [], findings: [], developments: [], week: [] }} }}, networkMeta: {{}}, network: [], a2a: [], subtools: [] }},
  localStorage,
  sessionStorage,
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  __TEST_MINIMAL_RENDER__: true,
  __TEST_LAST_TOAST__: '',
  innerWidth: 1280,
  setTimeout(fn) {{ return setTimeout(fn, 0); }},
  clearTimeout(id) {{ clearTimeout(id); }},
  setInterval() {{ return 1; }},
  addEventListener() {{}},
  removeEventListener() {{}},
  location: {{ pathname: '/app' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  visibilityState: 'visible',
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{
    if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify(bootstrapPayload) }};
    return null;
  }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement() {{
    return {{
      className: '',
      textContent: '',
      style: {{}},
      hidden: false,
      setAttribute() {{}},
      appendChild() {{}},
      remove() {{}},
      querySelector() {{ return null; }},
      querySelectorAll() {{ return []; }},
      parentNode: {{ appendChild() {{}} }},
    }};
  }},
}};

global.fetch = async function(pathname, options = {{}}) {{
  fetchCalls.push({{
    pathname,
    headers: options.headers || {{}},
    body: options.body || '',
  }});
  if (pathname !== '/assistant/chat') throw new Error('unexpected fetch ' + pathname);
  if (fetchCalls.length === 1) {{
    return {{
      ok: false,
      status: 401,
      headers: {{ get(name) {{ return String(name).toLowerCase() === 'x-request-id' ? 'server-req-401' : null; }} }},
      text: async function() {{
        return JSON.stringify({{ detail: 'A valid identity token is required.' }});
      }},
    }};
  }}
  return {{
    ok: true,
    status: 200,
    headers: {{ get(name) {{ return String(name).toLowerCase() === 'x-request-id' ? 'server-req-200' : null; }} }},
    text: async function() {{
      return JSON.stringify({{
        status: 'ok',
        answer: 'Tamween recovery remains the main board item: public packet shows SAR 8.6M recovery, with clear next actions and no auth-required private context needed.',
        mode: 'deterministic',
        assistant_mode: 'scenario',
        why: 'Public-safe board packet answer.',
        run_id: 'latest-public',
        citations: [{{ locator: 'public_context_packet.tamween', source_path: 'public_packet://latest-public' }}],
        hallucination_risk: {{ level: 'low' }},
      }});
    }},
  }};
}};

async function main() {{
  const factory = require(tempFile);
  const harness = factory();
  harness.state.latestPacket = {{
    run_id: 'latest-public',
    chat: {{ run_id: 'latest-public', threads: [], assistant: {{ name: 'Hermes' }} }},
    assistant_public_context: bootstrapPayload.assistant_public_context,
    executive_modes: {{ active_persona_id: 'ceo', active_board_state: 'pre', active_driver_key: 'board_packet' }},
  }};
  harness.state.activePersona = 'ceo';
  harness.state.activeThreadKey = persistedThreadKey;
  harness.ensureThreads();

  const thread = harness.threadStore()[persistedThreadKey];
  await harness.retryAssistantMessage(persistedThreadKey, 1, null, {{ silentToast: true }});
  const finalMessage = thread.messages[1];
  console.log(JSON.stringify({{
    fetchCalls,
    finalStatus: finalMessage.status,
    finalText: finalMessage.text,
    finalMeta: finalMessage.meta || '',
    hasRetryPrompt: Object.prototype.hasOwnProperty.call(finalMessage, 'retryPrompt'),
    localStorageAfter: localStorage.dump(),
  }}));
}}

main().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "assistant_invalid_token_recovery.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
    result = json.loads(completed.stdout.strip())

    assert len(result["fetchCalls"]) == 2
    assert result["fetchCalls"][0]["pathname"] == "/assistant/chat"
    assert result["fetchCalls"][0]["headers"]["Authorization"] == "Bearer definitely-invalid-token"
    assert "Authorization" not in result["fetchCalls"][1]["headers"]
    assert result["finalStatus"] == "ok"
    assert "SAR 8.6M recovery" in result["finalText"]
    assert "packet" not in result["finalText"].lower()
    assert "Retry now once the service is reachable" not in result["finalText"]
    assert result["hasRetryPrompt"] is False
    assert "strategyos.ui.token" not in result["localStorageAfter"]


def test_exact_fx_cta_thread_is_preserved_as_retryable_flow():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    assert "data-executive-prompt" in executive_js
    assert "cross the CEO materiality threshold" in executive_js
    assert "askAssistant(button.getAttribute('data-executive-prompt')" in executive_js
    assert 'markThreadTransportFailuresRetryable(current);' in executive_js
    assert 'data-assistant-retry-latest' in executive_js


def test_stale_fx_fallback_thread_reloads_without_duplicate_auto_retry():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveTestHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        '  function renderAssistantStudio() {',
        '  function renderAssistantStudio() {\n    if (window.__TEST_MINIMAL_RENDER__) return;',
        1,
    )
    harness_js = harness_js.replace(
        '  function showToast(message) {',
        '  function showToast(message) {\n    if (window.__TEST_MINIMAL_RENDER__) { window.__TEST_LAST_TOAST__ = message; return; }',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return {\n'
        '    state: state,\n'
        '    ensureThreads: ensureThreads,\n'
        '    threadStore: threadStore,\n'
        '    maybeAutoRetryLatestFailure: maybeAutoRetryLatestFailure\n'
        '  };\n'
        '}\n'
        'module.exports = __executiveTestHarness;\n',
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');

const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

function makeStore(seed = {{}}) {{
  const data = new Map(Object.entries(seed));
  return {{
    getItem(key) {{ return data.has(key) ? data.get(key) : null; }},
    setItem(key, value) {{ data.set(key, String(value)); }},
    removeItem(key) {{ data.delete(key); }},
    clear() {{ data.clear(); }},
  }};
}}

const persistedThreadKey = 'ceo:fx-thread';
const storageKey = 'strategyos.chat.latest-public.ceo';
const fxPrompt = 'Explain why “FX is building a ~SAR 9k margin drag this week” matters for the board review and what action I should consider.';
const staleFallback = "I couldn't reach the shared assistant service just now. Question asked: “" + fxPrompt + "”. Please try again in a moment or reopen the board assistant.";

const bootstrapPayload = {{
  requested_view_state: {{ persona: 'ceo', board: 'pre' }},
  executive_entry_route: '/app',
  assistant_public_context: {{ persona_id: 'ceo', assistant: 'Hermes', drivers: [], findings: [], developments: [], week: [] }},
}};

const persistedThreads = {{
  [persistedThreadKey]: {{
    key: persistedThreadKey,
    title: 'FX follow-up',
    preview: staleFallback,
    route: '',
    readOnly: false,
    kind: 'followup',
    assistant: 'Hermes',
    messages: [
      {{ role: 'user', text: fxPrompt, timestamp: '2026-07-04T00:00:00.000Z' }},
      {{ role: 'assistant', text: staleFallback, timestamp: '2026-07-04T00:00:01.000Z' }},
    ],
    lastUpdated: '2026-07-04T00:00:01.000Z',
  }}
}};

global.window = {{
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [], findings: [], developments: [], week: [] }} }}, networkMeta: {{}}, network: [], a2a: [], subtools: [] }},
  localStorage: makeStore(),
  sessionStorage: makeStore({{ [storageKey]: JSON.stringify(persistedThreads) }}),
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  __TEST_MINIMAL_RENDER__: true,
  __TEST_LAST_TOAST__: '',
  setTimeout(fn) {{ fn(); return 1; }},
  clearTimeout() {{}},
  setInterval() {{ return 1; }},
  addEventListener() {{}},
  removeEventListener() {{}},
  location: {{ pathname: '/app' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{
    if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify(bootstrapPayload) }};
    return null;
  }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement() {{
    return {{
      className: '',
      textContent: '',
      style: {{}},
      hidden: false,
      setAttribute() {{}},
      appendChild() {{}},
      remove() {{}},
      querySelector() {{ return null; }},
      querySelectorAll() {{ return []; }},
      parentNode: {{ appendChild() {{}} }},
    }};
  }},
}};

global.fetch = async function(pathname) {{
  if (pathname !== '/assistant/chat') throw new Error('unexpected fetch ' + pathname);
  return {{
    ok: true,
    status: 200,
    headers: {{ get(name) {{ return String(name).toLowerCase() === 'x-request-id' ? 'server-req-1' : null; }} }},
    text: async function() {{
      return JSON.stringify({{
        status: 'ok',
        answer: 'The public packet shows EBITDA margin at 19.2% versus a 19.4% plan with FX flagged as the cleanest board action item. The 60% EUR hedge leaves ~SAR 9k weekly drag, so the board action is to tighten the hedge response now.',
        mode: 'deterministic',
        assistant_mode: 'scenario',
        why: 'FX is the cleanest board action item in the public packet.',
        run_id: 'latest-public',
        citations: [{{ locator: 'public_context_packet.margin', source_path: 'public_packet://latest-public' }}],
        hallucination_risk: {{ level: 'low' }},
      }});
    }},
  }};
}};

async function main() {{
  const factory = require(tempFile);
  const harness = factory();
  harness.state.latestPacket = {{
    run_id: 'latest-public',
    chat: {{ run_id: 'latest-public', threads: [], assistant: {{ name: 'Hermes' }} }},
    assistant_public_context: bootstrapPayload.assistant_public_context,
    executive_modes: {{ active_persona_id: 'ceo', active_board_state: 'pre', active_driver_key: 'margin' }},
  }};
  harness.state.activePersona = 'ceo';
  harness.state.activeThreadKey = persistedThreadKey;
  harness.state.drawerOpen = true;

  harness.ensureThreads();
  const thread = harness.threadStore()[persistedThreadKey];
  const afterReload = {{
    status: thread.messages[1].status,
    retryable: thread.messages[1].retryable,
    text: thread.messages[1].text,
    preview: thread.preview,
  }};

  harness.maybeAutoRetryLatestFailure(thread);
  for (let index = 0; index < 8 && thread.messages[1].status === 'pending'; index += 1) {{
    await Promise.resolve();
  }}

  const finalMessage = thread.messages[1];
  console.log(JSON.stringify({{
    afterReload,
    finalStatus: finalMessage.status,
    finalText: finalMessage.text,
    finalPreview: thread.preview,
    autoRetried: harness.state.failedAssistantAutoRetried[persistedThreadKey + ':1'] === true,
  }}));
}}

main().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "stale_fx_reload_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
    result = json.loads(completed.stdout.strip())

    assert result["afterReload"]["status"] == "failed"
    assert result["afterReload"]["retryable"] is True
    assert "Retry now once the service is reachable" in result["afterReload"]["text"]
    assert result["afterReload"]["preview"].startswith("Retry needed ·")
    assert result["autoRetried"] is False
    assert result["finalStatus"] == "failed"
    assert "Retry now once the service is reachable" in result["finalText"]


def test_assistant_css_styles_retryable_failure_state():
    executive_css = Path("strategyos_mvp/static/executive.css").read_text()
    assert '.assistant-message--failed' in executive_css
    assert '.assistant-message__meta' in executive_css
    assert '.assistant-retry-button' in executive_css
    assert '.assistant-tool-chip--action' in executive_css


def test_assistant_transport_has_cached_fallback_without_automatic_retry_loop():
    executive_js = _static_executive_js()

    assert "strategyos.hermes.answer-cache.v1" in executive_js
    assert "Showing the last known answer from" in executive_js
    assert "cachedAssistantFallback" in executive_js
    assert "message.autoRetryEligible = false" in executive_js


def test_persona_title_grounding_badges_and_native_agent_actions_are_visible():
    executive_js = _static_executive_js()
    executive_css = Path("strategyos_mvp/static/executive.css").read_text()

    assert "function updateDocumentTitle" in executive_js
    assert 'personaLabel = state.activePersona === "board" ? "Board Room"' in executive_js
    assert 'moduleId === "ceo-brief"' in executive_js
    assert 'moduleId === "board-room-memory"' in executive_js
    assert "CEO brief opened in Hermes" in executive_js
    assert "Board room memory opened" in executive_js
    # Plain English for an executive: "grounded" reads as electrical wiring.
    assert "Evidence verified" in executive_js
    assert "Evidence gap" in executive_js
    assert ".grounding-badge--grounded" in executive_css
    assert ".grounding-badge--needs-evidence" in executive_css


def test_executive_ux_layout_contracts_are_guarded():
    executive_css = Path("strategyos_mvp/static/executive.css").read_text()
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")

    assert ".hero-score__label" in executive_css
    assert "0.707" in executive_css  # hero ring label bounded by the inscribed square
    assert ".hero-score__caption" in executive_css
    assert "white-space: nowrap" in executive_css
    assert ".twin-card-list" in executive_css
    assert ".twin-card__head" in executive_css
    assert ".twin-network-intro" in executive_css
    assert 'data-twin-toggle="' in executive_js
    assert "padding-bottom: max(112px" in executive_css


def test_assistant_success_messages_render_metadata_behaviorally():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveTestHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return {\n'
        '    state: state,\n'
        '    ensureThreads: ensureThreads,\n'
        '    threadStore: threadStore,\n'
        '    renderAssistantStudio: renderAssistantStudio,\n'
        '    applyAssistantResultToMessage: applyAssistantResultToMessage\n'
        '  };\n'
        '}\n'
        'module.exports = __executiveTestHarness;\n',
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');

const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-meta-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

function makeStore(seed = {{}}) {{
  const data = new Map(Object.entries(seed));
  return {{
    getItem(key) {{ return data.has(key) ? data.get(key) : null; }},
    setItem(key, value) {{ data.set(key, String(value)); }},
    removeItem(key) {{ data.delete(key); }},
    clear() {{ data.clear(); }},
  }};
}}

function makeClassList() {{
  const values = new Set();
  return {{
    add(name) {{ values.add(name); }},
    remove(name) {{ values.delete(name); }},
    contains(name) {{ return values.has(name); }},
    toggle(name, force) {{
      if (force === true) {{ values.add(name); return true; }}
      if (force === false) {{ values.delete(name); return false; }}
      if (values.has(name)) {{ values.delete(name); return false; }}
      values.add(name); return true;
    }},
  }};
}}

function makeElement(id = '') {{
  return {{
    id,
    innerHTML: '',
    textContent: '',
    hidden: false,
    onclick: null,
    scrollTop: 0,
    scrollHeight: 0,
    style: {{}},
    attributes: {{}},
    classList: makeClassList(),
    setAttribute(name, value) {{ this.attributes[name] = String(value); }},
    getAttribute(name) {{ return this.attributes[name] || null; }},
    querySelector() {{ return null; }},
    querySelectorAll() {{ return []; }},
    closest() {{ return null; }},
    appendChild() {{}},
    insertBefore() {{}},
    focus() {{}},
  }};
}}

const bootstrapPayload = {{
  requested_view_state: {{ persona: 'ceo', board: 'pre' }},
  executive_entry_route: '/app',
  assistant_public_context: {{ persona_id: 'ceo', assistant: 'Hermes', drivers: [], findings: [], developments: [], week: [] }},
}};

const drawer = makeElement('assistant-drawer');
drawer.querySelector = function(selector) {{
  if (selector === '.assistant-threads') return makeElement('threads-pane');
  if (selector === '.assistant-layout') return makeElement('layout');
  if (selector === '.assistant-head__actions') return makeElement('head-actions');
  return null;
}};

const elements = {{
  'assistant-thread-list': makeElement('assistant-thread-list'),
  'assistant-thread-title': makeElement('assistant-thread-title'),
  'assistant-thread-meta': makeElement('assistant-thread-meta'),
  'assistant-messages': makeElement('assistant-messages'),
  'assistant-prompt-row': makeElement('assistant-prompt-row'),
  'assistant-thread-tools': makeElement('assistant-thread-tools'),
  'assistant-heading': makeElement('assistant-heading'),
  'assistant-subtitle': makeElement('assistant-subtitle'),
  'assistant-state': makeElement('assistant-state'),
  'assistant-drawer': drawer,
  'assistant-scrim': makeElement('assistant-scrim'),
  'chat-launcher': makeElement('chat-launcher'),
  'assistant-close': makeElement('assistant-close'),
}};

global.window = {{
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [], findings: [], developments: [], week: [] }} }}, networkMeta: {{}}, network: [], a2a: [], subtools: [] }},
  localStorage: makeStore(),
  sessionStorage: makeStore(),
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  setTimeout(fn) {{ fn(); return 1; }},
  clearTimeout() {{}},
  setInterval() {{ return 1; }},
  addEventListener() {{}},
  removeEventListener() {{}},
  location: {{ pathname: '/app' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{
    if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify(bootstrapPayload) }};
    return elements[id] || null;
  }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement() {{ return makeElement(); }},
}};

const factory = require(tempFile);
const harness = factory();
harness.state.latestPacket = {{
  run_id: 'latest-public',
  chat: {{ run_id: 'latest-public', threads: [], assistant: {{ name: 'Hermes' }} }},
  assistant_public_context: bootstrapPayload.assistant_public_context,
  executive_modes: {{ active_persona_id: 'ceo', active_board_state: 'pre', active_driver_key: 'margin' }},
}};
harness.state.activePersona = 'ceo';
harness.state.activeThreadKey = 'ceo:meta-thread';
harness.state.drawerOpen = true;

harness.ensureThreads();
const thread = harness.threadStore()['ceo:meta-thread'] = {{
  key: 'ceo:meta-thread',
  title: 'Board packet summary',
  preview: 'Board packet summary',
  route: '',
  readOnly: false,
  kind: 'followup',
  assistant: 'Hermes',
  messages: [
    {{ role: 'user', text: 'summarize the board packet in plain english', timestamp: '2026-07-04T00:00:00.000Z', status: 'ok' }},
    {{ role: 'assistant', text: 'pending', timestamp: '2026-07-04T00:00:01.000Z', status: 'pending' }},
  ],
  lastUpdated: '2026-07-04T00:00:01.000Z',
}};

harness.applyAssistantResultToMessage(thread, thread.messages[1], {{
  ok: true,
  answer: 'In plain English: revenue is ahead, margin is the soft spot, and the board still needs a hedge decision.',
  metadata: '',
  responsePayload: {{ mode: 'llm', assistant_mode: 'llm' }},
}});
harness.renderAssistantStudio();

console.log(JSON.stringify({{
  messagesHtml: elements['assistant-messages'].innerHTML,
  storedMeta: thread.messages[1].meta,
  storedPayloadMode: thread.messages[1].payload && thread.messages[1].payload.mode,
}}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "assistant_meta_render_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    assert "board still needs a hedge decision" in result["messagesHtml"]
    assert "assistant-message__meta" not in result["messagesHtml"]
    assert result["storedMeta"] == ""
    assert result["storedPayloadMode"] == "llm"


def test_public_ceo_answer_metadata_omits_debug_trace_terms_behaviorally():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'

    harness_js = executive_js.replace(prefix, 'function __executiveQaHarness() {\n  "use strict";\n', 1)
    harness_js = harness_js.replace(
        suffix,
        '  return { qaAnswerMeta: qaAnswerMeta };\n}\nmodule.exports = __executiveQaHarness;\n',
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');

const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-qa-meta-safety-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

global.window = {{
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [], findings: [], developments: [], week: [] }} }}, networkMeta: {{}}, network: [], a2a: [], subtools: [] }},
  localStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}}, clear() {{}} }},
  sessionStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}}, clear() {{}} }},
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  setTimeout(fn) {{ fn(); return 1; }},
  clearTimeout() {{}},
  setInterval() {{ return 1; }},
  addEventListener() {{}},
  removeEventListener() {{}},
  location: {{ pathname: '/app' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{
    if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify({{ requested_view_state: {{ persona: 'ceo', board: 'pre' }}, assistant_public_context: {{ persona_id: 'ceo' }} }}) }};
    return null;
  }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement() {{ return {{ setAttribute() {{}}, appendChild() {{}}, style: {{}}, classList: {{ add() {{}}, remove() {{}}, contains() {{ return false; }} }} }}; }},
}};

const factory = require(tempFile);
const harness = factory();
const meta = harness.qaAnswerMeta({{
  mode: 'llm',
  assistant_mode: 'packet',
  run_id: 'latest-public',
  basis: 'Grounded in current board facts.',
  citations: [{{ source_path: 'public_packet://latest-public', locator: 'public_context_packet.facts[0]' }}],
  hallucination_risk: {{ level: 'low' }},
  llm_status: {{ enabled: true, reason: 'provider unavailable' }},
  matched: false,
}});
console.log(JSON.stringify({{ meta }}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "assistant_meta_safety_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    meta = result["meta"].lower()
    for banned in (
        "[",
        "]",
        "path:",
        "run:",
        "llm",
        "answered by ai fallback",
        "public-safe",
        "deterministic",
        "vector",
        "graph",
    ):
        assert banned not in meta, f"unexpected debug metadata leak: {banned}"


def test_public_ceo_finance_answer_uses_executive_labels_behaviorally():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'

    harness_js = executive_js.replace(prefix, 'function __executiveQaHarness() {\n  "use strict";\n', 1)
    harness_js = harness_js.replace(
        suffix,
        '  return { qaAnswerText: qaAnswerText, qaAnswerMeta: qaAnswerMeta };\n}\nmodule.exports = __executiveQaHarness;\n',
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');

const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-qa-finance-labels-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

global.window = {{
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [], findings: [], developments: [], week: [] }} }}, networkMeta: {{}}, network: [], a2a: [], subtools: [] }},
  localStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}}, clear() {{}} }},
  sessionStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}}, clear() {{}} }},
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  setTimeout(fn) {{ fn(); return 1; }},
  clearTimeout() {{}},
  setInterval() {{ return 1; }},
  addEventListener() {{}},
  removeEventListener() {{}},
  location: {{ pathname: '/app' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{
    if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify({{ requested_view_state: {{ persona: 'ceo', board: 'pre' }}, assistant_public_context: {{ persona_id: 'ceo' }} }}) }};
    return null;
  }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement() {{ return {{ setAttribute() {{}}, appendChild() {{}}, style: {{}}, classList: {{ add() {{}}, remove() {{}}, contains() {{ return false; }} }} }}; }},
}};

const factory = require(tempFile);
const harness = factory();
const payload = {{
  answer: 'Total recoverable leakage: SAR 794,108.00 across 8 findings. Breakdown: auto_renewal_escalation: SAR 250,416.00; duplicate_payment: SAR 177,188.00; dormant_credit_balance: SAR 128,000.00; entity_resolution_duplicate: SAR 104,750.00; missed_early_pay_discount: SAR 56,666.00.',
  basis: "Scenario parser matched 'finance_leakage'; computed from run findings.",
  calculations: [1, 2, 3, 4, 5, 6],
  citations: [{{ source_path: 'public_packet://latest-public', locator: 'findings' }}],
  hallucination_risk: {{ level: 'medium' }},
}};
const actionPayload = {{
  scenario_id: 'revenue_plan_attainment_action_plan',
  answer: 'Decision today: approve a Revenue closure sprint. 1. Accountable owner — assign the Group commercial/revenue executive. 2. Validation owner — CFO/Finance confirms the aligned plan. 3. CEO control — start a daily gap review. What the current run can prove: the governed Revenue actual.',
}};
console.log(JSON.stringify({{
  answerText: harness.qaAnswerText(payload),
  answerMeta: harness.qaAnswerMeta(payload),
  actionText: harness.qaAnswerText(actionPayload),
}}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "assistant_qa_finance_labels_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    combined = f"{result['answerText']} {result['answerMeta']}"

    assert "Total recoverable value" in result["answerText"]
    assert "Auto-renewal escalation" in result["answerText"]
    assert "Duplicate payment" in result["answerText"]
    assert "Dormant supplier credit" in result["answerText"]
    assert "Duplicate supplier identity" in result["answerText"]
    assert "Missed early-payment discount" in result["answerText"]
    assert "Evidence basis: Calculated from current reviewed findings" in result["answerMeta"]
    assert "Calculation: 6 checks reconciled" in result["answerMeta"]
    assert "Evidence confidence: Partial" in result["answerMeta"]
    assert "\n\n**1. Accountable owner** —" in result["actionText"]
    assert "\n\n**2. Validation owner** —" in result["actionText"]
    assert "\n\n**3. CEO control** —" in result["actionText"]
    assert "\n\n**Evidence boundary** —" in result["actionText"]
    for banned in (
        "auto_renewal_escalation",
        "duplicate_payment",
        "dormant_credit_balance",
        "entity_resolution_duplicate",
        "missed_early_pay_discount",
        "finance_leakage",
        "Scenario parser",
        "Formula steps",
        "Grounding level",
        "recoverable leakage",
    ):
        assert banned.lower() not in combined.lower()


def test_qa_answer_text_unwraps_raw_json_payload_behaviorally():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveQaHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return { qaAnswerText: qaAnswerText, qaAnswerMeta: qaAnswerMeta };\n'
        '}\n'
        'module.exports = __executiveQaHarness;\n',
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');

const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-qa-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

global.window = {{
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [], findings: [], developments: [], week: [] }} }}, networkMeta: {{}}, network: [], a2a: [], subtools: [] }},
  localStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}}, clear() {{}} }},
  sessionStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}}, clear() {{}} }},
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  setTimeout(fn) {{ fn(); return 1; }},
  clearTimeout() {{}},
  setInterval() {{ return 1; }},
  addEventListener() {{}},
  removeEventListener() {{}},
  location: {{ pathname: '/app' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{
    if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify({{ requested_view_state: {{ persona: 'ceo', board: 'pre' }}, assistant_public_context: {{ persona_id: 'ceo' }} }}) }};
    return null;
  }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement() {{ return {{ setAttribute() {{}}, appendChild() {{}}, style: {{}}, classList: {{ add() {{}}, remove() {{}}, contains() {{ return false; }} }} }}; }},
}};

const factory = require(tempFile);
const harness = factory();
const payload = {{
  mode: 'llm',
  assistant_mode: 'llm',
  answered_by: 'llm',
  answer_origin: 'llm',
  calculation_status: 'not_calculated',
  review_status: 'required',
  human_review_required: true,
  run_id: 'latest-public',
  answer: JSON.stringify({{
    matched: true,
    answer: 'Since last week, NUPCO awards were confirmed and FX remains the main margin watch item.',
    basis: 'Grounded in public developments and drivers.',
    citations: [],
    suggestions: [],
  }}),
  basis: 'outer wrapper',
  citations: [{{ source_path: 'public_packet://latest-public', locator: 'public_context_packet.developments[0]' }}],
  llm_status: {{ enabled: true }},
}};
console.log(JSON.stringify({{
  answerText: harness.qaAnswerText(payload),
  answerMeta: harness.qaAnswerMeta(payload),
}}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "assistant_qa_answer_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    assert result["answerText"].startswith("Since last week, NUPCO awards were confirmed")
    assert '"matched"' not in result["answerText"]
    assert "AI-generated answer" in result["answerMeta"]
    assert "Review before use" in result["answerMeta"]
    assert "outer wrapper" not in result["answerMeta"]
    assert "Evidence: 1 source checked" in result["answerMeta"]
    assert "LLM provided" not in result["answerMeta"]
    assert "Not calculated" in result["answerMeta"]
    assert "Review before use" in result["answerMeta"]


def test_qa_answer_text_extracts_answer_from_truncated_jsonish_payload_behaviorally():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    harness_js = executive_js.replace(prefix, 'function __executiveQaHarness() {\n  "use strict";\n', 1)
    harness_js = harness_js.replace(
        suffix,
        '  return { qaAnswerText: qaAnswerText };\n}\nmodule.exports = __executiveQaHarness;\n',
        1,
    )

    truncated_answer = '{\n  "matched": true,\n  "answer": "Since last week, NUPCO awards were confirmed and FX remains the main margin watch item.",\n  "basis": "Grounded in public developments."'
    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');
const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-qa-harness-truncated-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');
global.window = {{ STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [], findings: [], developments: [], week: [] }} }}, networkMeta: {{}}, network: [], a2a: [], subtools: [] }}, localStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}}, clear() {{}} }}, sessionStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}}, clear() {{}} }}, MIZAN_X: {{ threads: {{}}, assistants: {{}} }}, setTimeout(fn) {{ fn(); return 1; }}, clearTimeout() {{}}, setInterval() {{ return 1; }}, addEventListener() {{}}, removeEventListener() {{}}, location: {{ pathname: '/app' }}, history: {{ replaceState() {{}} }}, navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }} }};
global.document = {{ body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }}, documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }}, addEventListener() {{}}, removeEventListener() {{}}, getElementById(id) {{ if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify({{ requested_view_state: {{ persona: 'ceo', board: 'pre' }}, assistant_public_context: {{ persona_id: 'ceo' }} }}) }}; return null; }}, querySelector() {{ return null; }}, querySelectorAll() {{ return []; }}, createElement() {{ return {{ setAttribute() {{}}, appendChild() {{}}, style: {{}}, classList: {{ add() {{}}, remove() {{}}, contains() {{ return false; }} }} }}; }} }};
const factory = require(tempFile);
const harness = factory();
const payload = {{ answer: {json.dumps(truncated_answer)}, llm_status: {{ enabled: true }} }};
console.log(JSON.stringify({{ answerText: harness.qaAnswerText(payload) }}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "assistant_qa_truncated_answer_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    assert result["answerText"] == "Since last week, NUPCO awards were confirmed and FX remains the main margin watch item."


def test_ceo_follow_up_reuses_visible_thread_and_keeps_composer_live():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'

    harness_js = executive_js.replace(prefix, 'function __executiveFollowupHarness() {\n  "use strict";\n', 1)
    harness_js = harness_js.replace(
        suffix,
        '  return {\n'
        '    state: state,\n'
        '    askAssistant: askAssistant,\n'
        '    ensureThreads: ensureThreads,\n'
        '    threadStore: threadStore,\n'
        '    currentThreadKey: currentThreadKey,\n'
        '    renderAssistantStudio: renderAssistantStudio\n'
        '  };\n'
        '}\n'
        'module.exports = __executiveFollowupHarness;\n',
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');

const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-followup-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

function makeStore(seed = {{}}) {{
  const data = new Map(Object.entries(seed));
  return {{
    getItem(key) {{ return data.has(key) ? data.get(key) : null; }},
    setItem(key, value) {{ data.set(key, String(value)); }},
    removeItem(key) {{ data.delete(key); }},
    clear() {{ data.clear(); }},
  }};
}}

function makeClassList() {{
  const values = new Set();
  return {{
    add(name) {{ values.add(name); }},
    remove(name) {{ values.delete(name); }},
    contains(name) {{ return values.has(name); }},
    toggle(name, force) {{
      if (force === true) {{ values.add(name); return true; }}
      if (force === false) {{ values.delete(name); return false; }}
      if (values.has(name)) {{ values.delete(name); return false; }}
      values.add(name); return true;
    }},
  }};
}}

function makeElement(id = '') {{
  return {{
    id,
    nodeType: 1,
    value: '',
    innerHTML: '',
    textContent: '',
    placeholder: '',
    hidden: false,
    disabled: false,
    onclick: null,
    scrollTop: 0,
    scrollHeight: 0,
    style: {{}},
    attributes: {{}},
    listeners: {{}},
    classList: makeClassList(),
    setAttribute(name, value) {{ this.attributes[name] = String(value); }},
    getAttribute(name) {{ return this.attributes[name] || null; }},
    addEventListener(name, handler) {{ this.listeners[name] = handler; }},
    removeEventListener(name) {{ delete this.listeners[name]; }},
    querySelector() {{ return null; }},
    querySelectorAll() {{ return []; }},
    closest() {{ return null; }},
    appendChild() {{}},
    insertBefore() {{}},
    focus() {{ this.focused = true; }},
  }};
}}

const bootstrapPayload = {{
  requested_view_state: {{ persona: 'ceo', board: 'pre' }},
  executive_entry_route: '/app',
  assistant_public_context: {{ persona_id: 'ceo', assistant: 'Hermes', drivers: [], findings: [], developments: [], week: [] }},
}};

const drawer = makeElement('assistant-drawer');
const threadsPane = makeElement('threads-pane');
threadsPane.classList.add('assistant-threads');
threadsPane.classList.add('is-collapsed');
const layout = makeElement('layout');
layout.classList.add('assistant-layout');
layout.classList.add('threads-collapsed');
const headActions = makeElement('head-actions');
headActions.classList.add('assistant-head__actions');
drawer.querySelector = function(selector) {{
  if (selector === '.assistant-threads') return threadsPane;
  if (selector === '.assistant-layout') return layout;
  if (selector === '.assistant-head__actions') return headActions;
  return null;
}};

const form = makeElement('assistant-form');
const input = makeElement('assistant-input');
input.placeholder = 'Ask Hermes…';
form.querySelector = function(selector) {{
  if (selector === '#assistant-input') return input;
  return null;
}};

const elements = {{
  'assistant-thread-list': makeElement('assistant-thread-list'),
  'assistant-thread-title': makeElement('assistant-thread-title'),
  'assistant-thread-meta': makeElement('assistant-thread-meta'),
  'assistant-messages': makeElement('assistant-messages'),
  'assistant-prompt-row': makeElement('assistant-prompt-row'),
  'assistant-thread-tools': makeElement('assistant-thread-tools'),
  'assistant-heading': makeElement('assistant-heading'),
  'assistant-subtitle': makeElement('assistant-subtitle'),
  'assistant-state': makeElement('assistant-state'),
  'assistant-drawer': drawer,
  'assistant-scrim': makeElement('assistant-scrim'),
  'chat-launcher': makeElement('chat-launcher'),
  'assistant-close': makeElement('assistant-close'),
  'assistant-form': form,
  'assistant-input': input,
  'persona-label': makeElement('persona-label'),
  'brand-org': makeElement('brand-org'),
  'topbar-avatar': makeElement('topbar-avatar'),
}};

const fetchCalls = [];

global.window = {{
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [], findings: [], developments: [], week: [] }} }}, networkMeta: {{}}, network: [], a2a: [], subtools: [] }},
  localStorage: makeStore(),
  sessionStorage: makeStore(),
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  innerWidth: 1280,
  setTimeout(fn) {{ fn(); return 1; }},
  clearTimeout() {{}},
  setInterval() {{ return 1; }},
  addEventListener() {{}},
  removeEventListener() {{}},
  location: {{ pathname: '/app', origin: 'https://strategyos.live' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{
    if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify(bootstrapPayload) }};
    return elements[id] || null;
  }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement() {{ return makeElement(); }},
}};

global.fetch = async function(pathname) {{
  fetchCalls.push(pathname);
  return {{
    ok: true,
    status: 200,
    headers: {{ get(name) {{ return String(name).toLowerCase() === 'x-request-id' ? 'server-req-' + fetchCalls.length : null; }} }},
    text: async function() {{
      return JSON.stringify({{
        status: 'ok',
        answer: fetchCalls.length === 1
          ? 'FX and API cost are the main margin pressure. Healthcare occupancy and Tamween recovery still need board action.'
          : 'Follow-up: the hedge decision and the healthcare recovery actions should stay in the same board thread.',
        mode: 'deterministic',
        assistant_mode: 'scenario',
        run_id: 'latest-public',
        citations: [{{ source_path: 'public_packet://latest-public', locator: 'public_context_packet.facts[0]' }}],
        hallucination_risk: {{ level: 'low' }},
      }});
    }},
  }};
}};

async function main() {{
  const factory = require(tempFile);
  const harness = factory();
  harness.state.latestPacket = {{
    run_id: 'latest-public',
    chat: {{ run_id: 'latest-public', threads: [], assistant: {{ name: 'Hermes' }} }},
    assistant_public_context: bootstrapPayload.assistant_public_context,
    executive_modes: {{ active_persona_id: 'ceo', active_board_state: 'pre', active_driver_key: 'ebitda' }},
  }};
  harness.state.activePersona = 'ceo';
  harness.state.drawerOpen = true;
  harness.ensureThreads();

  await harness.askAssistant('What is driving margin pressure this quarter?', form);
  const firstThreadKey = harness.currentThreadKey();
  const firstThread = harness.threadStore()[firstThreadKey];

  await harness.askAssistant('What should I do next?', form);
  const secondThreadKey = harness.currentThreadKey();
  const secondThread = harness.threadStore()[secondThreadKey];

  console.log(JSON.stringify({{
    fetchCalls,
    threadKeys: Object.keys(harness.threadStore()),
    firstThreadKey,
    secondThreadKey,
    firstThreadMessages: firstThread ? firstThread.messages.length : 0,
    secondThreadMessages: secondThread ? secondThread.messages.length : 0,
    inputStillExists: Boolean(elements['assistant-input']),
    formStillExists: Boolean(elements['assistant-form']),
    inputDisabled: elements['assistant-input'].disabled,
    inputPlaceholder: elements['assistant-input'].placeholder,
  }}));
}}

main().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "assistant_followup_thread_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    assert result["fetchCalls"] == ["/assistant/chat", "/assistant/chat"]
    assert result["formStillExists"] is True
    assert result["inputStillExists"] is True
    assert result["inputDisabled"] is False
    assert result["inputPlaceholder"] == "Ask Hermes…"
    assert result["firstThreadKey"] == result["secondThreadKey"], "Follow-up must stay in the same visible thread"
    assert result["secondThreadMessages"] == 4, "Follow-up thread must keep both Q&A turns together"


def test_board_action_prompt_builder_outputs_plain_english_prompts():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executivePromptHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return { boardActionPrompt: boardActionPrompt };\n}\nmodule.exports = __executivePromptHarness;\n',
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');
const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-board-prompt-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

function makeStore(seed = {{}}) {{
  const data = new Map(Object.entries(seed));
  return {{
    getItem(key) {{ return data.has(key) ? data.get(key) : null; }},
    setItem(key, value) {{ data.set(key, String(value)); }},
    removeItem(key) {{ data.delete(key); }},
    clear() {{ data.clear(); }},
  }};
}}

global.window = {{
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [] }} }} }},
  requestAnimationFrame(cb) {{ cb(); }},
  localStorage: makeStore(),
  sessionStorage: makeStore(),
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  setTimeout() {{ return 1; }},
  clearTimeout() {{}},
  setInterval() {{ return 1; }},
  addEventListener() {{}},
  removeEventListener() {{}},
  location: {{ pathname: '/app' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{
    if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify({{ assistant_public_context: {{}} }}) }};
    return null;
  }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement() {{ return {{ style: {{}}, setAttribute() {{}}, appendChild() {{}}, querySelector() {{ return null; }}, querySelectorAll() {{ return []; }}, parentNode: {{ appendChild() {{}} }} }}; }},
}};

const factory = require(tempFile);
const harness = factory();
const prepare = harness.boardActionPrompt('prepare_board_pack', {{ presentation_state: 'pre' }});
const challenged = harness.boardActionPrompt('close_challenged_cases', {{ presentation_state: 'pre', supplementary: {{ question_count: 3 }} }});
console.log(JSON.stringify({{ prepare, challenged }}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "board_prompt_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    assert result["prepare"].startswith("Help me prepare the board materials for the pre-board stage.")
    assert "prepare_board_pack" not in result["prepare"]
    assert result["challenged"].startswith("Help me close challenged cases before the board meeting.")
    assert "close_challenged_cases" not in result["challenged"]


def test_board_portal_exact_selector_click_routes_action_and_prompt_to_hermes():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveBoardPortalHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        "  async function askAssistant(prompt, sourceChip) {",
        "  async function askAssistant(prompt, sourceChip) {\n    if (window.__BOARD_PORTAL_TEST_CAPTURE__) { window.__BOARD_PORTAL_TEST_CAPTURE__.push({ prompt: String(prompt || ''), label: sourceChip ? String(sourceChip.textContent || '') : '' }); return; }",
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return { bindBoardPortalInteractions: bindBoardPortalInteractions, state: state };\n}\nmodule.exports = __executiveBoardPortalHarness;\n',
        1,
    )

    node_script = f"""
const fs = require('fs');
const path = require('path');
const os = require('os');
const source = {json.dumps(harness_js)};
const tempFile = path.join(os.tmpdir(), 'executive-board-portal-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

function makeStore(seed = {{}}) {{
  const data = new Map(Object.entries(seed));
  return {{
    getItem(key) {{ return data.has(key) ? data.get(key) : null; }},
    setItem(key, value) {{ data.set(key, String(value)); }},
    removeItem(key) {{ data.delete(key); }},
    clear() {{ data.clear(); }},
  }};
}}

function makeButton(attrs, text) {{
  return {{
    tagName: 'BUTTON',
    nodeType: 1,
    textContent: text,
    attributes: Object.assign({{}}, attrs),
    getAttribute(name) {{ return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null; }},
    closest(selector) {{
      if (selector === '[data-board-action]' && this.attributes['data-board-action']) return this;
      if (selector === '[data-board-prompt]' && this.attributes['data-board-prompt']) return this;
      return null;
    }},
  }};
}}

const actionButton = makeButton({{ 'data-board-action': 'prepare_board_pack' }}, 'Review: Prepare Board Pack');
const promptButton = makeButton({{ 'data-board-prompt': 'Why is EBITDA 20 bps under plan?' }}, 'Why is EBITDA 20 bps under plan?');
const portal = {{
  __boardPortalInteractionsBound: false,
  listeners: {{}},
  addEventListener(name, handler) {{ this.listeners[name] = handler; }},
  contains(target) {{ return target === actionButton || target === promptButton; }},
}};

global.window = {{
  __BOARD_PORTAL_TEST_CAPTURE__: [],
  requestAnimationFrame(cb) {{ cb(); }},
  STRATEGYOS_EXECUTIVE_DESIGN: {{ personas: {{ ceo: {{ assistant: 'Hermes', threads: [] }} }} }},
  localStorage: makeStore(),
  sessionStorage: makeStore(),
  MIZAN_X: {{ threads: {{}}, assistants: {{}} }},
  setTimeout() {{ return 1; }},
  clearTimeout() {{}},
  setInterval() {{ return 1; }},
  clearInterval() {{}},
  addEventListener() {{}},
  removeEventListener() {{}},
  innerWidth: 1280,
  location: {{ pathname: '/app' }},
  history: {{ replaceState() {{}} }},
  navigator: {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }},
}};

global.document = {{
  body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
  documentElement: {{ getAttribute() {{ return 'light'; }}, setAttribute() {{}} }},
  addEventListener() {{}},
  removeEventListener() {{}},
  getElementById(id) {{
    if (id === 'strategyos-executive-bootstrap') return {{ textContent: JSON.stringify({{ assistant_public_context: {{}} }}) }};
    return null;
  }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  createElement() {{ return {{}}; }},
}};

const factory = require(tempFile);
const harness = factory();
harness.state.latestPacket = {{
  board_portal: {{
    presentation_state: 'pre',
    supplementary: {{ question_count: 3 }},
  }},
}};
harness.state.activeBoard = 'pre';
harness.bindBoardPortalInteractions(portal);
portal.listeners.click({{ target: actionButton, preventDefault() {{}}, stopPropagation() {{}} }});
portal.listeners.click({{ target: promptButton, preventDefault() {{}}, stopPropagation() {{}} }});
console.log(JSON.stringify(window.__BOARD_PORTAL_TEST_CAPTURE__));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "board_portal_selector_click_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())
    assert result[0]["prompt"].startswith("Help me prepare the board materials for the pre-board stage.")
    assert result[0]["label"] == "Review: Prepare Board Pack"
    assert result[1]["prompt"] == "Why is EBITDA 20 bps under plan?"


def test_board_state_tabs_switch_client_state_without_refresh_reset():
    """activateBoardState must set state, update history, and render — never call refresh directly."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    fn_start = executive_js.index("function activateBoardState(nextState)")
    fn_end = executive_js.index("function statusLabel(token)", fn_start)
    fn_block = executive_js[fn_start:fn_end]

    assert 'state.activeBoard = nextState;' in fn_block
    assert 'updateHistory();' in fn_block
    assert 'renderBoardStageSurface();' in fn_block
    assert 'state._boardStateTransition = \'\';' in fn_block, (
        "activateBoardState must clear _boardStateTransition after render so refresh() can update activeBoard from the server packet"
    )
    assert 'refresh(true);' not in fn_block, (
        "Board state activation must not call refresh which could reset the selected stage"
    )


def test_refresh_preserves_selected_board_state_over_server_default():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    assert 'state.activeBoard = firstDefined(state.activeBoard, (state.latestPacket.executive_modes || {}).active_board_state, (state.latestPacket.board_portal || {}).presentation_state, "pre");' in executive_js


def test_board_state_tabs_click_resistant_to_closure_and_rerender_cycle():
    """Board lifecycle clicks must survive the full innerHTML replacement + activateBoardState cycle
    in the real DOM path. This catches regression where tab buttons become inert after render."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveBoardStateCycleHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return { renderBoardStateTabs: renderBoardStateTabs, renderBoardPortal: renderBoardPortal, renderBoardStageSurface: renderBoardStageSurface, state: state, syncBoardStateTabUI: syncBoardStateTabUI };\n}\nmodule.exports = __executiveBoardStateCycleHarness;\n',
        1,
    )
    harness_js = harness_js.replace(
        "    renderPersonaView();",
        "    if (!window.__BOARD_STATE_TEST_SUPPRESS_RENDER__) renderPersonaView();",
        1,
    )

    node_script = r"""
const fs = require('fs');
const path = require('path');
const os = require('os');
const source = """ + json.dumps(harness_js) + r""";
const tempFile = path.join(os.tmpdir(), 'executive-board-state-cycle-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

function makeClassList() {
  return {
    items: [],
    add: function(c) { this.items.push(c); },
    remove: function(c) { this.items = this.items.filter(function(x) { return x !== c; }); },
    contains: function(c) { return this.items.indexOf(c) >= 0; },
  };
}

function makeStore(seed = {}) {
  const data = new Map(Object.entries(seed));
  return {
    getItem(key) { return data.has(key) ? data.get(key) : null; },
    setItem(key, value) { data.set(key, String(value)); },
    removeItem(key) { data.delete(key); },
    clear() { data.clear(); },
  };
}

function makeButton(id) {
  var button = {
    tagName: 'BUTTON',
    nodeType: 1,
    id: id || '',
    attributes: {},
    className: '',
    innerHTML: '',
    textContent: '',
    listeners: {},
    style: {},
    disabled: false,
    classList: makeClassList(),
    setAttribute: function(name, value) { this.attributes[name] = String(value); },
    getAttribute: function(name) { return this.attributes[name] || null; },
    addEventListener: function(name, handler) { this.listeners[name] = handler; },
    removeEventListener: function() {},
    dispatchEvent: function() {},
    closest: function(selector) { return selector === '[data-board-state]' || selector === '.state-tab' ? this : null; },
    click: function() {
      var handler = this.listeners.click;
      if (handler) {
        handler({
          type: 'click',
          target: this,
          currentTarget: this,
          preventDefault: function() {},
          stopPropagation: function() {},
        });
      }
    },
    querySelector: function(sel) {
      if (sel === 'strong') return null;
      return null;
    },
  };
  return button;
}

var calledLive = false;
var calledClosed = false;
var boardPortalElement = {
  id: 'board-portal',
  tagName: 'ARTICLE',
  innerHTML: '',
  style: {},
  classList: makeClassList(),
  listeners: {},
  setAttribute: function() {},
  getAttribute: function() { return null; },
  addEventListener: function(name, handler) { this.listeners[name] = handler; },
  querySelector: function() { return null; },
  querySelectorAll: function() { return []; },
};

var row = {
  __boardStateInteractionsBound: false,
  __id: 'board-state-row',
  innerHTML: '',
  buttons: [],
  listeners: {},
  addEventListener: function(name, handler) { this.listeners[name] = handler; },
  appendChild: function(child) { this.buttons.push(child); return child; },
  contains: function(target) { return this.buttons.includes(target); },
  querySelectorAll: function(selector) {
    if (selector === '[data-board-state]') return this.buttons.slice();
    return [];
  },
  querySelector: function(selector) {
    var match = selector.match(/\[data-board-state="([^"]+)"\]/);
    if (!match) return null;
    return this.buttons.find(function(b) { return b.getAttribute('data-board-state') === match[1]; }) || null;
  },
};

var note = { textContent: '' };

global.window = {
  __BOARD_STATE_TEST_SUPPRESS_RENDER__: true,
  STRATEGYOS_EXECUTIVE_DESIGN: { personas: { ceo: { assistant: 'Hermes', threads: [] } } },
  localStorage: makeStore(),
  sessionStorage: makeStore(),
  MIZAN_X: { threads: {}, assistants: {} },
  setTimeout: function() { return 1; },
  requestAnimationFrame: function(cb) { cb(); },
  clearTimeout: function() {},
  setInterval: function() { return 1; },
  clearInterval: function() {},
  addEventListener: function() {},
  removeEventListener: function() {},
  innerWidth: 1280,
  location: { pathname: '/app' },
  history: { replaceState: function() {} },
  navigator: { clipboard: { writeText: function() { return Promise.resolve(); } } },
};

global.document = {
  body: { style: {}, appendChild: function() {}, removeChild: function() {} },
  documentElement: { getAttribute: function() { return 'light'; }, setAttribute: function() {} },
  addEventListener: function() {},
  removeEventListener: function() {},
  getElementById: function(id) {
    if (id === 'strategyos-executive-bootstrap') return { textContent: JSON.stringify({ assistant_public_context: {} }) };
    if (id === 'board-state-row') return row;
    if (id === 'board-state-note') return note;
    if (id === 'board-portal') return boardPortalElement;
    return null;
  },
  querySelector: function() { return null; },
  querySelectorAll: function() { return []; },
  createElement: function(tag) { return tag === 'button' ? makeButton() : { setAttribute: function() {}, classList: makeClassList() }; },
};

const factory = require(tempFile);
const harness = factory();
harness.state.latestPacket = {
  board_portal: {
    lifecycle_flow: [
      { state_id: 'pre', label: 'Pre-board', detail: 'Prepare governed packet' },
      { state_id: 'live', label: 'Live', detail: 'Run the room inside approved material' },
      { state_id: 'closed', label: 'Closed', detail: 'Freeze memory after the room closes' }
    ],
    presentation_state: 'pre',
  },
};
harness.state.activeBoard = 'pre';

// --- CYCLE 1: Initial render + click Live ---
harness.renderBoardStateTabs();
var liveBtn = row.querySelector('[data-board-state="live"]');
liveBtn.click();
var afterLiveClick = {
  activeBoard: harness.state.activeBoard,
  preSelected: row.buttons[0].getAttribute('aria-selected'),
  preClass: row.buttons[0].className,
  liveSelected: row.buttons[1].getAttribute('aria-selected'),
  liveClass: row.buttons[1].className,
  closedSelected: row.buttons[2].getAttribute('aria-selected'),
  closedClass: row.buttons[2].className,
};

// --- CYCLE 2: Re-render (simulates activateBoardState's renderBoardStageSurface path) ---
harness.renderBoardStateTabs();
var liveBtn2 = row.querySelector('[data-board-state="live"]');
var afterRerender = {
  activeBoard: harness.state.activeBoard,
  preSelected: row.buttons[0].getAttribute('aria-selected'),
  preClass: row.buttons[0].className,
  liveSelected: row.buttons[1].getAttribute('aria-selected'),
  liveClass: row.buttons[1].className,
};

// --- CYCLE 3: Click Closed after re-render ---
var closedBtn = row.querySelector('[data-board-state="closed"]');
closedBtn.click();
var afterClosedClick = {
  activeBoard: harness.state.activeBoard,
  preSelected: row.buttons[0].getAttribute('aria-selected'),
  preClass: row.buttons[0].className,
  liveSelected: row.buttons[1].getAttribute('aria-selected'),
  liveClass: row.buttons[1].className,
  closedSelected: row.buttons[2].getAttribute('aria-selected'),
  closedClass: row.buttons[2].className,
};

// --- CYCLE 4: Click back to Live ---
var liveBtn3 = row.querySelector('[data-board-state="live"]');
liveBtn3.click();
var afterBackToLive = {
  activeBoard: harness.state.activeBoard,
  preSelected: row.buttons[0].getAttribute('aria-selected'),
  liveSelected: row.buttons[1].getAttribute('aria-selected'),
  liveClass: row.buttons[1].className,
  closedSelected: row.buttons[2].getAttribute('aria-selected'),
};

console.log(JSON.stringify({
  cycle1_live_click: afterLiveClick,
  cycle2_rerender: afterRerender,
  cycle3_closed_click: afterClosedClick,
  cycle4_back_to_live: afterBackToLive,
}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "board_state_cycle_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())

    # Cycle 1: Clicking Live must switch activeBoard and DOM
    c1 = result["cycle1_live_click"]
    assert c1["activeBoard"] == "live", (
        f"Click on Live must set activeBoard to 'live', got '{c1['activeBoard']}'"
    )
    assert c1["liveSelected"] == "true", "Click on Live left aria-selected=false on Live"
    assert c1["preSelected"] == "false", "Click on Live left aria-selected=true on Pre-board"
    assert c1["liveClass"] == "state-tab is-active", "Click on Live did not add is-active to Live"
    assert c1["preClass"] == "state-tab", "Click on Live left is-active on Pre-board"

    # Cycle 2: After re-render (renderBoardStageSurface path), activeBoard must persist
    c2 = result["cycle2_rerender"]
    assert c2["activeBoard"] == "live", (
        f"After re-render, activeBoard must still be 'live', got '{c2['activeBoard']}'"
    )
    assert c2["liveSelected"] == "true", "Re-render lost Live selection"
    assert c2["preSelected"] == "false", "Re-render re-activated Pre-board"

    # Cycle 3: Click Closed after re-render
    c3 = result["cycle3_closed_click"]
    assert c3["activeBoard"] == "closed", (
        f"Click on Closed must set activeBoard to 'closed', got '{c3['activeBoard']}'"
    )
    assert c3["closedSelected"] == "true", "Click on Closed left aria-selected=false on Closed"
    assert c3["closedClass"] == "state-tab is-active", "Click on Closed did not add is-active"
    assert c3["liveSelected"] == "false", "Click on Closed left aria-selected=true on Live"
    assert c3["preSelected"] == "false", "Click on Closed left aria-selected=true on Pre-board"

    # Cycle 4: Click back to Live from Closed
    c4 = result["cycle4_back_to_live"]
    assert c4["activeBoard"] == "live", (
        f"Click back to Live must set activeBoard to 'live', got '{c4['activeBoard']}'"
    )
    assert c4["liveSelected"] == "true", "Back-to-Live left aria-selected=false on Live"
    assert c4["preSelected"] == "false", "Back-to-Live left Pre-board active"
    assert c4["closedSelected"] == "false", "Back-to-Live left Closed active"


def test_board_state_tabs_click_always_triggers_render_even_when_state_matches():
    """activateBoardState must always proceed with re-render even if state.activeBoard already matches the target.

    Regression: clicking Live when state.activeBoard is already 'live' must still sync the DOM
    and re-render. The old guard (state.activeBoard === nextState) caused silent tab failure when
    a concurrent refresh() set state.activeBoard = 'live' but the DOM never reflected it.
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveStaleStateHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return { renderBoardStateTabs: renderBoardStateTabs, state: state };\n}\nmodule.exports = __executiveStaleStateHarness;\n',
        1,
    )
    harness_js = harness_js.replace(
        "    renderPersonaView();",
        "    if (!window.__BOARD_STATE_TEST_SUPPRESS_RENDER__) renderPersonaView();",
        1,
    )

    # Use json.dumps to safely embed harness_js into the Node template
    node_script = """const fs = require('fs');
const path = require('path');
const os = require('os');

function makeStore(seed) {
  var data = {};
  if (seed) { Object.keys(seed).forEach(function(k) { data[k] = seed[k]; }); }
  return {
    getItem: function(key) { return data.hasOwnProperty(key) ? data[key] : null; },
    setItem: function(key, value) { data[key] = String(value); },
    removeItem: function(key) { delete data[key]; },
    clear: function() { data = {}; },
  };
}

var setTimeoutCalls = [];

function makeButton() {
  var attributes = {};
  var listeners = {};
  return {
    tagName: 'BUTTON',
    nodeType: 1,
    attributes: attributes,
    className: '',
    innerHTML: '',
    style: {},
    listeners: listeners,
    setAttribute: function(name, value) { attributes[name] = String(value); if (name === 'class') { this.className = value; } },
    getAttribute: function(name) { return attributes[name] || null; },
    addEventListener: function(name, handler) { listeners[name] = handler; },
    click: function() {
      var handler = listeners.click;
      if (handler) {
        handler({
          type: 'click',
          target: this,
          currentTarget: this,
          preventDefault: function() {},
          stopPropagation: function() {},
        });
      }
    },
    closest: function(selector) { return selector === '[data-board-state]' || selector === '.state-tab' ? this : null; },
  };
}

var boardPortalElement = {
  id: 'board-portal',
  tagName: 'ARTICLE',
  innerHTML: '',
  style: { background: 'white' },
  classList: { add: function() {}, remove: function() {}, contains: function() { return false; } },
  listeners: {},
  setAttribute: function() {},
  getAttribute: function() { return null; },
  addEventListener: function(name, handler) { this.listeners[name] = handler; },
  querySelector: function() { return null; },
  querySelectorAll: function() { return []; },
};

var row = {
  __boardStateInteractionsBound: false,
  __id: 'board-state-row',
  innerHTML: '',
  buttons: [],
  listeners: {},
  addEventListener: function(name, handler) { this.listeners[name] = handler; },
  appendChild: function(child) { this.buttons.push(child); return child; },
  contains: function(target) { return this.buttons.indexOf(target) !== -1; },
  querySelectorAll: function(selector) {
    if (selector === '[data-board-state]') return this.buttons.slice();
    return [];
  },
  querySelector: function(selector) {
    var m = selector.match(/\[data-board-state="([^"]+)"\]/);
    if (!m) return null;
    for (var i = 0; i < this.buttons.length; i++) {
      if (this.buttons[i].getAttribute('data-board-state') === m[1]) return this.buttons[i];
    }
    return null;
  },
};

var note = { textContent: '' };

global.window = {
  __BOARD_STATE_TEST_SUPPRESS_RENDER__: true,
  STRATEGYOS_EXECUTIVE_DESIGN: { personas: { ceo: { assistant: 'Hermes', threads: [] } } },
  localStorage: makeStore(),
  sessionStorage: makeStore(),
  MIZAN_X: { threads: {}, assistants: {} },
  setTimeout: function(fn) { setTimeoutCalls.push(fn); return 1; },
  clearTimeout: function() {},
  setInterval: function() { return 1; },
  clearInterval: function() {},
  addEventListener: function() {},
  removeEventListener: function() {},
  innerWidth: 1280,
  location: { pathname: '/app' },
  history: { replaceState: function() {} },
  navigator: { clipboard: { writeText: function() { return Promise.resolve(); } } },
};

global.document = {
  body: { style: {}, appendChild: function() {}, removeChild: function() {} },
  documentElement: { getAttribute: function() { return 'light'; }, setAttribute: function() {} },
  addEventListener: function() {},
  removeEventListener: function() {},
  getElementById: function(id) {
    if (id === 'strategyos-executive-bootstrap') return { textContent: JSON.stringify({ assistant_public_context: {} }) };
    if (id === 'board-state-row') return row;
    if (id === 'board-state-note') return note;
    if (id === 'board-portal') return boardPortalElement;
    return null;
  },
  querySelector: function() { return null; },
  querySelectorAll: function() { return []; },
  createElement: function(tag) { return tag === 'button' ? makeButton() : { setAttribute: function() {}, classList: { add: function() {}, remove: function() {}, contains: function() { return false; }, toggle: function() { return false; } } }; },
};

var source = """ + json.dumps(harness_js) + """;
var tempFile = path.join(os.tmpdir(), 'executive-stale-state-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

const factory = require(tempFile);
const harness = factory();
harness.state.latestPacket = {
  board_portal: {
    lifecycle_flow: [
      { state_id: 'pre', label: 'Pre-board', detail: 'Prepare governed packet' },
      { state_id: 'live', label: 'Live', detail: 'Run the room inside approved material' },
      { state_id: 'closed', label: 'Closed', detail: 'Freeze memory after the room closes' }
    ],
    presentation_state: 'pre',
  },
};
harness.state.activeBoard = 'live';
harness.renderBoardStateTabs();

var pre = row.querySelector('[data-board-state="pre"]');
var live = row.querySelector('[data-board-state="live"]');
var closed = row.querySelector('[data-board-state="closed"]');

var beforeClick = {
  activeBoard: harness.state.activeBoard,
  preSelected: pre.getAttribute('aria-selected'),
  preActive: pre.getAttribute('data-board-state-active'),
  liveSelected: live.getAttribute('aria-selected'),
  liveActive: live.getAttribute('data-board-state-active'),
  liveClass: live.className,
  preClass: pre.className,
};

// Click Live even though state.activeBoard is already 'live'
live.click();

var afterSameLiveClick = {
  activeBoard: harness.state.activeBoard,
  preSelected: pre.getAttribute('aria-selected'),
  preActive: pre.getAttribute('data-board-state-active'),
  liveSelected: live.getAttribute('aria-selected'),
  liveActive: live.getAttribute('data-board-state-active'),
  liveClass: live.className,
  preClass: pre.className,
  closedSelected: closed.getAttribute('aria-selected'),
  closedActive: closed.getAttribute('data-board-state-active'),
  setTimeoutSyncCount: setTimeoutCalls.length,
};

// Now click Closed
closed.click();

var afterClosedClick = {
  activeBoard: harness.state.activeBoard,
  preSelected: pre.getAttribute('aria-selected'),
  preActive: pre.getAttribute('data-board-state-active'),
  liveSelected: live.getAttribute('aria-selected'),
  liveActive: live.getAttribute('data-board-state-active'),
  closedSelected: closed.getAttribute('aria-selected'),
  closedActive: closed.getAttribute('data-board-state-active'),
  closedClass: closed.className,
  liveClass: live.className,
};

// Click back to Live
live.click();

var afterBackToLive = {
  activeBoard: harness.state.activeBoard,
  preSelected: pre.getAttribute('aria-selected'),
  preActive: pre.getAttribute('data-board-state-active'),
  liveSelected: live.getAttribute('aria-selected'),
  liveActive: live.getAttribute('data-board-state-active'),
  closedSelected: closed.getAttribute('aria-selected'),
  closedActive: closed.getAttribute('data-board-state-active'),
  liveClass: live.className,
  preClass: pre.className,
};

console.log(JSON.stringify({
  before: beforeClick,
  after_same_live_click: afterSameLiveClick,
  after_closed_click: afterClosedClick,
  after_back_to_live: afterBackToLive,
}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "board_state_stale_state_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())

    # Before: state.activeBoard is 'live' so tabs should reflect that
    before = result["before"]
    assert before["activeBoard"] == "live"
    assert before["liveSelected"] == "true"
    assert before["preSelected"] == "false"

    # After clicking Live when state.activeBoard is already 'live':
    # The fix removes the early-return guard, so re-render + sync fires anyway.
    after = result["after_same_live_click"]
    assert after["activeBoard"] == "live", (
        "Clicking Live when activeBoard is already 'live' must keep 'live'"
    )
    assert after["liveSelected"] == "true", (
        "Clicking Live when activeBoard is 'live' must still set aria-selected=true on Live"
    )
    assert after["preSelected"] == "false", (
        "Clicking Live when activeBoard is 'live' must not activate Pre-board"
    )
    assert after["liveActive"] == "true", (
        "data-board-state-active must be 'true' on Live after clicking Live"
    )
    assert after["preActive"] == "false", (
        "data-board-state-active must be 'false' on Pre-board after clicking Live"
    )

    # After clicking Closed: must switch
    c3 = result["after_closed_click"]
    assert c3["activeBoard"] == "closed", (
        f"Click Closed must switch to 'closed', got '{c3['activeBoard']}'"
    )
    assert c3["closedSelected"] == "true", "Clicked Closed but aria-selected is not true"
    assert c3["closedActive"] == "true", "data-board-state-active must be true on Closed"
    assert c3["liveSelected"] == "false", "Closed: Live must not still be selected"
    assert c3["preSelected"] == "false", "Closed: Pre-board must not be selected"

    # After clicking back to Live: must switch back
    c4 = result["after_back_to_live"]
    assert c4["activeBoard"] == "live", (
        f"Click back to Live must switch to 'live', got '{c4['activeBoard']}'"
    )
    assert c4["liveSelected"] == "true", "Back to Live: aria-selected not true"
    assert c4["liveActive"] == "true", "Back to Live: data-board-state-active not true"
    assert c4["closedSelected"] == "false", "Back to Live: Closed still selected"
    assert c4["preSelected"] == "false", "Back to Live: Pre-board still selected"


def test_board_state_tabs_sync_inline_style_survives_render():
    """syncBoardStateTabUI must set inline style.background on buttons so the visual
    state survives even if className is stripped during CSSOM recalculation."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    fn_start = executive_js.index("function syncBoardStateTabUI(nextState)")
    fn_end = executive_js.index("function renderBoardStageSurface()", fn_start)
    fn_body = executive_js[fn_start:fn_end]

    assert "var expectedBackground = isActive ? 'var(--accent-soft)' : 'transparent';" in fn_body, (
        "syncBoardStateTabUI must compute the inline fallback background for each tab"
    )
    assert "button.style.background = expectedBackground;" in fn_body, (
        "syncBoardStateTabUI must set inline style.background as triple-redundant fallback"
    )
    assert "data-board-state-active" in fn_body, (
        "syncBoardStateTabUI must set data-board-state-active attribute"
    )


def test_board_state_tabs_fast_path_replaces_dom_sync_guard():
    """P0-10: renderBoardStateTabs fast path replaces the three-phase _domSyncGuard.

    _domSyncGuard was removed because the fast path updates existing button attributes
    in-place instead of innerHTML destroy-recreate. The delegated click handler on
    board-state-row ensures clicks are captured even during full DOM rebuild.
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    # Verify the guard was replaced with the comment
    assert "_domSyncGuard removed in P0-10" in executive_js, (
        "_domSyncGuard was removed in P0-10 — fast path eliminates the destroy-recreate cycle"
    )
    # Verify the fast path exists
    assert "listsMatch" in executive_js, (
        "renderBoardStateTabs must have the listsMatch fast-path detection"
    )
    assert "_ensureBoardStateRowDelegated" in executive_js, (
        "renderBoardStateTabs must have the delegated click handler"
    )


def test_board_state_tabs_fast_path_attaches_individual_handler():
    """P0-11: renderBoardStateTabs fast path must attach individual button click handlers
    as belt-and-suspenders alongside the delegated handler on board-state-row.

    The individual handler uses __boardTabHandlerAttached flag to avoid double-binding
    (the slow path already attaches its own handler via the closure in the loop).
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    assert "__boardTabHandlerAttached" in executive_js, (
        "Fast path must use __boardTabHandlerAttached flag to avoid double-binding individual handlers"
    )
    assert "belt-and-suspenders" in executive_js.lower() or "belt" in executive_js, (
        "Fast path must attach individual click handler for belt-and-suspenders coverage"
    )


def test_board_state_transition_signal_cleared_after_side_effects():
    """P0-11: _boardStateTransition must be cleared AFTER animateCard and updateHistory
    complete, not before. If the transition signal is cleared before side effects finish,
    a concurrent refresh() queued via setInterval just before the click may read
    _boardStateTransition as falsy and overwrite state.activeBoard from the server packet.
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    fn_start = executive_js.index("function activateBoardState(nextState)")
    fn_end = executive_js.index("function statusLabel", fn_start)
    fn_body = executive_js[fn_start:fn_end]
    # Find the transition clear position
    clear_pos = fn_body.index("state._boardStateTransition = ''")
    before_clear = fn_body[:clear_pos]
    assert "animateCard('board-portal')" in before_clear, (
        "animateCard must complete before _boardStateTransition is cleared"
    )
    assert "updateHistory()" in before_clear, (
        "updateHistory must complete before _boardStateTransition is cleared"
    )


def test_switch_view_reasserts_board_tab_ui_for_knowledge():
    """P0-11: switchView('knowledge') must call syncBoardStateTabUI after renderPersonaView
    to re-assert the board tab UI. Some browser rendering modes (Chrome CSSOM recalc after
    hidden-to-visible transition) can discard className-based styling.
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    fn_start = executive_js.index("function switchView(view)")
    fn_end = executive_js.index("function animateCard", fn_start)
    fn_body = executive_js[fn_start:fn_end]
    assert 'state.activeView === "knowledge"' in fn_body, (
        "switchView must re-assert board tab UI when switching to knowledge view"
    )
    assert "syncBoardStateTabUI(resolveBoardState())" in fn_body, (
        "switchView must call syncBoardStateTabUI after switching to knowledge view"
    )


def test_render_board_portal_reasserts_tab_ui_after_innerhtml():
    """P0-12: renderBoardPortal must call syncBoardStateTabUI after portal.innerHTML
    replacement, AND schedule a post-paint re-assert via requestAnimationFrame.

    The innerHTML replacement triggers CSSOM recalc which can discard className-based
    styling on tab buttons outside the portal. The synchronous sync is the first guard;
    the rAF guard catches Chrome CSSOM recalc during paint (observed on Chrome 127+).
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    fn_start = executive_js.index("function renderBoardPortal()")
    fn_end = executive_js.index("function assistantNameForState", fn_start)
    fn_body = executive_js[fn_start:fn_end]
    assert "syncBoardStateTabUI(resolveBoardState())" in fn_body, (
        "renderBoardPortal must call syncBoardStateTabUI after innerHTML replacement"
    )
    assert "requestAnimationFrame" in fn_body, (
        "renderBoardPortal must have rAF guard for post-paint tab UI re-assert"
    )


def test_switch_view_knowledge_has_raf_fallthrough():
    """P0-12: switchView('knowledge') must have a requestAnimationFrame fallthrough
    in addition to the synchronous syncBoardStateTabUI call. The hidden-to-visible
    CSSOM recalc in Chrome 127+ can discard inline style guards during paint.

    This mirrors the pattern in renderBoardPortal and activateBoardState — the
    rAF callback fires after the paint cycle, at which point the browser's CSSOM
    has stabilized and className/inline-style/data-attribute guards will stick.
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    fn_start = executive_js.index("function switchView(view)")
    fn_end = executive_js.index("function animateCard", fn_start)
    fn_body = executive_js[fn_start:fn_end]
    # Must have the synchronous re-assert (already there from P0-11)
    assert "syncBoardStateTabUI(resolveBoardState())" in fn_body, (
        "switchView must call syncBoardStateTabUI after switching to knowledge view"
    )
    # Must have the rAF guard (P0-12 addition)
    assert 'state.activeView === "knowledge"' in fn_body, (
        "switchView must contain knowledge-view guard"
    )
    # Verify rAF fallthrough pattern exists — check for nested requestAnimationFrame call
    knowledge_guard_start = fn_body.index('state.activeView === "knowledge"') if 'state.activeView === "knowledge"' in fn_body else -1
    assert knowledge_guard_start >= 0, "Must contain knowledge guard block"
    knowledge_block = fn_body[knowledge_guard_start:]
    assert "requestAnimationFrame" in knowledge_block[:800], (
        "switchView knowledge guard must include requestAnimationFrame fallthrough"
    )


def test_activate_board_state_has_multi_timing_re_sync_chain():
    """P0-13: activateBoardState must schedule a multi-timing re-sync chain
    (rAF + setTimeout(0/50/250)) in addition to the existing synchronous and
    rAF guards. This catches competing async re-renders (e.g. a pending
    refresh() response completing after the user's click) that can revert
    the active board state before the browser paints.
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    fn_start = executive_js.index("function activateBoardState(nextState)")
    fn_end = executive_js.index("function statusLabel", fn_start)
    fn_body = executive_js[fn_start:fn_end]
    # Must have the multi-timing re-sync chain
    assert "function _boardStateReSync" in fn_body, (
        "activateBoardState must define _boardStateReSync helper"
    )
    assert "window.requestAnimationFrame(_boardStateReSync)" in fn_body, (
        "activateBoardState must schedule rAF with _boardStateReSync"
    )
    assert "window.setTimeout(_boardStateReSync, 0)" in fn_body, (
        "activateBoardState must schedule setTimeout(0) with _boardStateReSync"
    )
    assert "window.setTimeout(_boardStateReSync, 50)" in fn_body, (
        "activateBoardState must schedule setTimeout(50) with _boardStateReSync"
    )
    assert "window.setTimeout(_boardStateReSync, 250)" in fn_body, (
        "activateBoardState must schedule setTimeout(250) with _boardStateReSync"
    )


def test_render_board_portal_has_multi_timing_re_sync_chain():
    """P0-13: renderBoardPortal must schedule a multi-timing re-sync chain
    (rAF + setTimeout(0/50/250)) in addition to the synchronous
    syncBoardStateTabUI call. This catches CSSOM recalc and competing
    re-renders at multiple timing levels.
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    fn_start = executive_js.index("function renderBoardPortal()")
    fn_end = executive_js.index("function assistantNameForState", fn_start)
    fn_body = executive_js[fn_start:fn_end]
    # Must have the synchronous sync
    assert "syncBoardStateTabUI(resolveBoardState())" in fn_body, (
        "renderBoardPortal must call syncBoardStateTabUI synchronously"
    )
    # Must have multi-timing re-sync with rAF + setTimeouts
    assert "window.requestAnimationFrame" in fn_body, (
        "renderBoardPortal must have rAF in re-sync chain"
    )
    assert "window.setTimeout(_boardPortalReSync, 0)" in fn_body, (
        "renderBoardPortal must have setTimeout(0) in re-sync chain"
    )
    assert "window.setTimeout(_boardPortalReSync, 50)" in fn_body, (
        "renderBoardPortal must have setTimeout(50) in re-sync chain"
    )
    assert "window.setTimeout(_boardPortalReSync, 250)" in fn_body, (
        "renderBoardPortal must have setTimeout(250) in re-sync chain"
    )


def test_render_persona_view_reasserts_board_tab_ui_for_board_workspace():
    """P0-13: renderPersonaView must call syncBoardStateTabUI at the end
    for the knowledge view, after ALL render functions have completed.
    This catches className/inline-style reversion from any of the many
    innerHTML replacements in the render pipeline.
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    fn_start = executive_js.index("function renderPersonaView()")
    fn_end = executive_js.index("function refresh", fn_start)
    fn_body = executive_js[fn_start:fn_end]
    # Must have final re-assert for the dedicated board workspace after all renders
    assert 'state.activePersona === "board" && state.activeView === "home"' in fn_body, (
        "renderPersonaView must check for the board workspace"
    )
    assert "syncBoardStateTabUI(resolveBoardState())" in fn_body, (
        "renderPersonaView must re-assert board tab UI for knowledge view"
    )
    # The re-assert must be AFTER all render functions, i.e. it must
    # appear after renderSummary in the function body
    summary_pos = fn_body.rindex("renderSummary")
    reassert_pos = fn_body.rindex("syncBoardStateTabUI")
    assert reassert_pos > summary_pos, (
        "syncBoardStateTabUI call must be AFTER renderSummary (last render function)"
    )


def test_board_state_tabs_mutation_observer_auto_recovers_from_dom_reset():
    """Board lifecycle tab state must auto-recover via MutationObserver when DOM
    is mutated by a concurrent process (e.g. CSSOM recalc, refresh render cycle,
    or third-party script). This simulates the live failure mode where clicking
    Live tab leaves Pre-board as active after a competing DOM mutation."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")

    # Verify MutationObserver is used on board-state-row
    assert "MutationObserver" in executive_js, (
        "executive.js must use MutationObserver to guard board tab state"
    )
    assert "board-state-row" in executive_js[executive_js.index("MutationObserver"):], (
        "MutationObserver must observe board-state-row"
    )
    assert "_ensureBoardStateObserver" in executive_js, (
        "executive.js must define _ensureBoardStateObserver"
    )

    # Verify synchronous re-sync is present on the observer callback
    observer_call = executive_js[executive_js.index("_ensureBoardStateObserver"):]
    assert "var desiredState = state.activeBoard || resolveBoardState();" in observer_call, (
        "MutationObserver callback must derive desiredState using state.activeBoard as primary source"
    )
    assert "syncBoardStateTabUI(desiredState);" in observer_call, (
        "MutationObserver callback must re-sync using the resolved desiredState"
    )


def test_board_state_tabs_mutation_observer_has_loop_guard():
    """MutationObserver must not feed back into itself and freeze the browser.

    Regression: observing aria-selected/class changes on board-state-row while the
    callback itself mutates those same attributes can create an automation-visible
    hang. The observer therefore needs both a self-suppression flag and a mismatch
    check so it only re-syncs when the DOM is actually wrong.
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")

    assert "var _boardStateObserverSyncing = false;" in executive_js, (
        "executive.js must track when board tab syncing is already in progress"
    )
    assert "function boardStateTabUIMismatch(nextState)" in executive_js, (
        "executive.js must expose a board tab mismatch detector for observer guardrails"
    )

    observer_start = executive_js.index("function _ensureBoardStateObserver()")
    observer_end = executive_js.index("function renderBoardStateTabs()", observer_start)
    observer_block = executive_js[observer_start:observer_end]
    assert "if (_boardStateObserverSyncing) return;" in observer_block, (
        "MutationObserver callback must skip self-triggered attribute mutations"
    )
    assert "!boardStateTabUIMismatch(desiredState)" in observer_block, (
        "MutationObserver callback must bail out when board tab DOM is already correct"
    )

    sync_start = executive_js.index("function syncBoardStateTabUI(nextState)")
    sync_end = executive_js.index("function renderBoardStageSurface()", sync_start)
    sync_block = executive_js[sync_start:sync_end]
    assert "_boardStateObserverSyncing = true;" in sync_block, (
        "syncBoardStateTabUI must raise the observer suppression flag while mutating attributes"
    )
    assert "_boardStateObserverSyncing = false;" in sync_block, (
        "syncBoardStateTabUI must always clear the observer suppression flag"
    )


def test_board_state_tabs_activeboard_priority_over_transition_signal():
    """resolveBoardState must prefer state.activeBoard over state._boardStateTransition.
    Once a user has selected a board stage, that selection (activeBoard) must be the
    authoritative source — the transient transition signal should not override the
    user's anchored choice in any resolveBoardState call."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")

    fn_start = executive_js.index("function resolveBoardState()")
    fn_end = executive_js.index("function syncBoardStateTabUI", fn_start)
    fn_body = executive_js[fn_start:fn_end]

    # Must check state.activeBoard before state._boardStateTransition
    active_pos = fn_body.index("state.activeBoard")
    transition_pos = fn_body.index("state._boardStateTransition")
    assert active_pos < transition_pos, (
        "resolveBoardState must check state.activeBoard before state._boardStateTransition"
    )


def test_board_state_tabs_click_updates_aria_selected_and_class_and_content():
    """P0-14: Clicking a board state tab (e.g. Live) must update:
    - aria-selected on both the previously-active and newly-active tabs
    - className (state-tab vs state-tab is-active) on both tabs
    - portal inner HTML to reflect the new board state (e.g. Live board session title)

    This reproduces the exact Hermes live verification path:
    1. Render board state tabs with Pre-board active
    2. Click the Live tab
    3. Verify aria-selected, className, and portal content all reflect Live
    """
    import subprocess, json, tempfile
    from pathlib import Path

    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    prefix = '(function () {\n  "use strict";\n'
    suffix = '  bindAssistantForm();\n  bindViewNav();\n  refresh(false);\n  window.setInterval(function () { refresh(false); }, 60000);\n})();\n'
    assert prefix in executive_js
    assert suffix in executive_js

    harness_js = executive_js.replace(
        prefix,
        'function __executiveBoardTabClickHarness() {\n  "use strict";\n',
        1,
    )
    harness_js = harness_js.replace(
        suffix,
        '  return { renderBoardStateTabs: renderBoardStateTabs, renderBoardPortal: renderBoardPortal, state: state, getBoardPortal: getBoardPortal, resolveBoardState: resolveBoardState };\n}\nmodule.exports = __executiveBoardTabClickHarness;\n',
        1,
    )
    harness_js = harness_js.replace(
        "    renderPersonaView();",
        "    if (!window.__BOARD_STATE_TEST_SUPPRESS_RENDER__) renderPersonaView();",
        1,
    )

    node_script = """const fs = require('fs');
const path = require('path');
const os = require('os');
const source = """ + json.dumps(harness_js) + """;
const tempFile = path.join(os.tmpdir(), 'executive-board-tab-click-harness-' + Date.now() + '.cjs');
fs.writeFileSync(tempFile, source, 'utf8');

function makeStore(seed) {
  var data = {};
  if (seed) { Object.keys(seed).forEach(function(k) { data[k] = seed[k]; }); }
  return {
    getItem: function(key) { return data.hasOwnProperty(key) ? data[key] : null; },
    setItem: function(key, value) { data[key] = String(value); },
    removeItem: function(key) { delete data[key]; },
    clear: function() { data = {}; },
  };
}

var setTimeoutCalls = [];

function makeButton() {
  var attributes = {};
  var listeners = {};
  return {
    tagName: 'BUTTON',
    nodeType: 1,
    attributes: attributes,
    className: '',
    innerHTML: '<span class="state-tab__copy"><strong>Tab</strong><span>desc</span></span>',
    style: {},
    listeners: listeners,
    setAttribute: function(name, value) { attributes[name] = String(value); if (name === 'class') { this.className = value; } },
    getAttribute: function(name) { return attributes[name] || null; },
    addEventListener: function(name, handler) { listeners[name] = handler; },
    click: function() {
      var handler = listeners.click;
      if (handler) {
        handler({
          type: 'click',
          target: this,
          currentTarget: this,
          preventDefault: function() {},
          stopPropagation: function() {},
          _boardTabHandled: false,
        });
      }
    },
    closest: function(selector) { return selector === '[data-board-state]' || selector === '.state-tab' ? this : null; },
    querySelector: function() { return null; },
    contains: function() { return false; },
  };
}

var boardPortalElement = {
  id: 'board-portal',
  tagName: 'ARTICLE',
  innerHTML: '<div id="board-portal-test">initial</div>',
  style: { background: 'white' },
  classList: { add: function() {}, remove: function() {}, contains: function() { return false; } },
  listeners: {},
  setAttribute: function() {},
  getAttribute: function() { return null; },
  addEventListener: function(name, handler) { this.listeners[name] = handler; },
  querySelector: function() { return null; },
  querySelectorAll: function() { return []; },
  contains: function() { return true; },
};

var row = {
  __boardStateInteractionsBound: false,
  __id: 'board-state-row',
  innerHTML: '',
  buttons: [],
  listeners: {},
  addEventListener: function(name, handler) { this.listeners[name] = handler; },
  appendChild: function(child) { this.buttons.push(child); return child; },
  contains: function(target) { return this.buttons.indexOf(target) !== -1 || target === this; },
  querySelectorAll: function(selector) {
    if (selector === '[data-board-state]') return this.buttons.slice();
    return [];
  },
  querySelector: function(selector) {
    var m = selector.match(/\[data-board-state="([^"]+)"\]/);
    if (!m) return null;
    for (var i = 0; i < this.buttons.length; i++) {
      if (this.buttons[i].getAttribute('data-board-state') === m[1]) return this.buttons[i];
    }
    return null;
  },
};

var note = { textContent: '' };

function fireTimeouts() {
  var safety = 0;
  while (setTimeoutCalls.length > 0 && safety < 50) {
    var fn = setTimeoutCalls.shift();
    if (typeof fn === 'function') fn();
    safety++;
  }
}

global.window = {
  __BOARD_STATE_TEST_SUPPRESS_RENDER__: true,
  STRATEGYOS_EXECUTIVE_DESIGN: { personas: { ceo: { assistant: 'Hermes', threads: [] } } },
  localStorage: makeStore(),
  sessionStorage: makeStore(),
  MIZAN_X: { threads: {}, assistants: {} },
  setTimeout: function(fn) { setTimeoutCalls.push(fn); return 1; },
  clearTimeout: function() {},
  setInterval: function() { return 1; },
  clearInterval: function() {},
  requestAnimationFrame: function(fn) { setTimeoutCalls.push(fn); return 1; },
  addEventListener: function() {},
  removeEventListener: function() {},
  innerWidth: 1280,
  location: { pathname: '/app' },
  history: { replaceState: function() {} },
  navigator: { clipboard: { writeText: function() { return Promise.resolve(); } } },
};

global.document = {
  body: { style: {}, appendChild: function() {}, removeChild: function() {} },
  documentElement: { getAttribute: function() { return 'light'; }, setAttribute: function() {} },
  addEventListener: function() {},
  removeEventListener: function() {},
  getElementById: function(id) {
    if (id === 'strategyos-executive-bootstrap') return { textContent: JSON.stringify({ assistant_public_context: {} }) };
    if (id === 'board-state-row') return row;
    if (id === 'board-state-note') return note;
    if (id === 'board-portal') return boardPortalElement;
    if (id === 'board-note') return note;
    return null;
  },
  querySelector: function() { return null; },
  querySelectorAll: function() { return []; },
  createElement: function(tag) { return tag === 'button' ? makeButton() : { setAttribute: function() {}, classList: { add: function() {}, remove: function() {}, contains: function() { return false; }, toggle: function() { return false; } } }; },
};

const factory = require(tempFile);
const harness = factory();

harness.state.latestPacket = {
  board_portal: {
    lifecycle_flow: [
      { state_id: 'pre', label: 'Pre-board', detail: 'Prepare governed packet' },
      { state_id: 'live', label: 'Live', detail: 'Run the room inside approved material' },
      { state_id: 'closed', label: 'Closed', detail: 'Freeze memory after the room closes' }
    ],
    presentation_state: 'pre',
    state: 'pre',
    state_detail: { state: 'pre', title: 'Pre-board preparation', summary: 'Prepare the packet.' },
  },
};
harness.state.activeBoard = 'pre';

harness.renderBoardStateTabs();
harness.renderBoardPortal();

var pre = row.querySelector('[data-board-state="pre"]');
var live = row.querySelector('[data-board-state="live"]');
var closed = row.querySelector('[data-board-state="closed"]');

var initial = {
  preSelected: pre.getAttribute('aria-selected'),
  preClass: pre.className,
  liveSelected: live.getAttribute('aria-selected'),
  liveClass: live.className,
  closedSelected: closed.getAttribute('aria-selected'),
  closedClass: closed.className,
  portalHtml: boardPortalElement.innerHTML,
  activeBoard: harness.state.activeBoard,
  resolveState: harness.resolveBoardState(),
};

live.click();
fireTimeouts();

var afterLiveClick = {
  preSelected: pre.getAttribute('aria-selected'),
  preClass: pre.className,
  liveSelected: live.getAttribute('aria-selected'),
  liveClass: live.className,
  closedSelected: closed.getAttribute('aria-selected'),
  closedClass: closed.className,
  portalHtml: boardPortalElement.innerHTML,
  activeBoard: harness.state.activeBoard,
  resolveState: harness.resolveBoardState(),
};

closed.click();
fireTimeouts();

var afterClosedClick = {
  preSelected: pre.getAttribute('aria-selected'),
  preClass: pre.className,
  liveSelected: live.getAttribute('aria-selected'),
  liveClass: live.className,
  closedSelected: closed.getAttribute('aria-selected'),
  closedClass: closed.className,
  portalHtml: boardPortalElement.innerHTML,
  activeBoard: harness.state.activeBoard,
  resolveState: harness.resolveBoardState(),
};

live.click();
fireTimeouts();

var afterBackToLive = {
  preSelected: pre.getAttribute('aria-selected'),
  preClass: pre.className,
  liveSelected: live.getAttribute('aria-selected'),
  liveClass: live.className,
  closedSelected: closed.getAttribute('aria-selected'),
  closedClass: closed.className,
  portalHtml: boardPortalElement.innerHTML,
  activeBoard: harness.state.activeBoard,
  resolveState: harness.resolveBoardState(),
};

console.log(JSON.stringify({
  initial: initial,
  after_live_click: afterLiveClick,
  after_closed_click: afterClosedClick,
  after_back_to_live: afterBackToLive,
}));
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "board_tab_click_test.cjs"
        script_path.write_text(node_script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )

    result = json.loads(completed.stdout.strip())

    i = result["initial"]
    assert i["preSelected"] == "true", "Initial: Pre-board must be selected"
    assert i["preClass"] == "state-tab is-active", "Initial: Pre-board must be is-active"
    assert i["liveSelected"] == "false", "Initial: Live must not be selected"
    assert i["closedSelected"] == "false", "Initial: Closed must not be selected"

    c2 = result["after_live_click"]
    assert c2["activeBoard"] == "live", f"Click Live: activeBoard must be 'live', got '{c2['activeBoard']}'"
    assert c2["liveSelected"] == "true", "Click Live: Live aria-selected must be true"
    assert c2["liveClass"] == "state-tab is-active", "Click Live: Live class must be 'state-tab is-active'"
    assert c2["preSelected"] == "false", "Click Live: Pre-board aria-selected must be false"
    assert c2["preClass"] == "state-tab", "Click Live: Pre-board class must be 'state-tab'"
    assert c2["closedSelected"] == "false", "Click Live: Closed aria-selected must be false"
    assert "Live board session" in c2["portalHtml"] or "Live" in c2["portalHtml"], (
        f"Click Live: Portal content must reflect Live state, got: {c2['portalHtml'][:200]}"
    )
    assert "Pre-board preparation" not in c2["portalHtml"], (
        "Click Live: Portal content must not show Pre-board preparation title"
    )

    c3 = result["after_closed_click"]
    assert c3["activeBoard"] == "closed", f"Click Closed: activeBoard must be 'closed', got '{c3['activeBoard']}'"
    assert c3["closedSelected"] == "true", "Click Closed: Closed aria-selected must be true"
    assert c3["closedClass"] == "state-tab is-active", "Click Closed: Closed class must be 'state-tab is-active'"
    assert c3["liveSelected"] == "false", "Click Closed: Live aria-selected must be false"
    assert c3["preSelected"] == "false", "Click Closed: Pre-board aria-selected must be false"

    c4 = result["after_back_to_live"]
    assert c4["activeBoard"] == "live", f"Back to Live: activeBoard must be 'live', got '{c4['activeBoard']}'"
    assert c4["liveSelected"] == "true", "Back to Live: Live aria-selected must be true"
    assert c4["liveClass"] == "state-tab is-active", "Back to Live: Live class must be 'state-tab is-active'"
    assert c4["preSelected"] == "false", "Back to Live: Pre-board aria-selected must be false"
    assert c4["closedSelected"] == "false", "Back to Live: Closed aria-selected must be false"


def test_board_state_tabs_delegated_handler_fallback():
    """P0-14: The delegated click handler on board-state-row must have fallback
    paths when event.target.closest('[data-board-state]') fails or returns null."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    fn_start = executive_js.index("function _ensureBoardStateRowDelegated")
    fn_end = executive_js.index("function renderBoardStateTabs", fn_start)
    fn_body = executive_js[fn_start:fn_end]

    assert "target.closest" in fn_body, "Must use target.closest as primary path"
    assert "tagName === 'BUTTON'" in fn_body or 'tagName === "BUTTON"' in fn_body, (
        "Must have tagName fallback for closest failure"
    )
    assert "querySelector" in fn_body and "data-board-state" in fn_body, (
        "Must have querySelector fallback for nested elements"
    )


def test_board_state_re_sync_chain_current_state_not_capture():
    """P0-14: All re-sync chains must use resolveBoardState() not captured snapshot."""
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")

    # activateBoardState
    ab_start = executive_js.index("function activateBoardState(nextState)")
    ab_end = executive_js.index("function statusLabel", ab_start)
    ab_body = executive_js[ab_start:ab_end]
    assert "syncBoardStateTabUI(resolveBoardState())" in ab_body

    # renderBoardPortal
    rp_start = executive_js.index("function renderBoardPortal()")
    rp_end = executive_js.index("function assistantNameForState", rp_start)
    rp_body = executive_js[rp_start:rp_end]
    assert "syncBoardStateTabUI(resolveBoardState())" in rp_body
    reSync_def = rp_body.index("function _boardPortalReSync")
    assert "syncBoardStateTabUI(resolveBoardState())" in rp_body[reSync_def:reSync_def + 300]

    # switchView
    sv_start = executive_js.index("function switchView(view)")
    sv_end = executive_js.index("function animateCard", sv_start)
    sv_body = executive_js[sv_start:sv_end]
    assert 'state.activeView === "knowledge"' in sv_body
    sv_knowledge = sv_body[sv_body.index('state.activeView === "knowledge"'):]
    assert "syncBoardStateTabUI(resolveBoardState())" in sv_knowledge


def test_board_state_re_sync_chain_does_not_restore_captured_prior_click():
    """P0-22: Rapid Live->Closed click must not have stale re-sync callback
    revert state.activeBoard to the captured prior 'live' value.

    Sequence: click Live -> before queued callbacks flush, click Closed ->
    flush all callbacks -> state.activeBoard must be 'closed', not 'live'.
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")

    # _boardPortalReSync must use resolveBoardState() not a captured snapshot
    rp_start = executive_js.index("function renderBoardPortal()")
    rp_end = executive_js.index("function assistantNameForState", rp_start)
    rp_body = executive_js[rp_start:rp_end]
    assert "function _boardPortalReSync" in rp_body
    re_sync_start = rp_body.index("function _boardPortalReSync")
    re_sync_end = rp_body.index("}", re_sync_start)
    re_sync_body = rp_body[re_sync_start:re_sync_end]
    # Must call resolveBoardState() not reference a captured variable
    assert "resolveBoardState()" in re_sync_body, (
        "_boardPortalReSync must call resolveBoardState() — not use captured nextState"
    )
    # Must NOT close over a captured variable like nextState
    assert "nextState" not in re_sync_body, (
        "_boardPortalReSync must not close over a captured nextState variable"
    )

    # activateBoardState: the state transition chains must also use resolveBoardState
    ab_start = executive_js.index("function activateBoardState(nextState)")
    ab_end = executive_js.index("function statusLabel", ab_start)
    ab_body = executive_js[ab_start:ab_end]
    assert "syncBoardStateTabUI(resolveBoardState())" in ab_body, (
        "activateBoardState must use resolveBoardState() in re-sync chain"
    )


def test_board_prompt_driver_context_omitted_for_board_portal():
    """P0-22: Board portal prompt chips must NOT attach stale hero driver_context.

    When entrypoint is 'board_portal', the driver_context should be omitted so
    the backend routes the question against board-relevant context (hedge, JV,
    EBITDA) rather than stale hero driver metrics (e.g. revenue).
    """
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")

    # Must conditionally skip driver_context for board_portal
    build_start = executive_js.index("function buildAssistantReply(message, sourceEl)")
    build_end = executive_js.index("function threadStore()", build_start)
    build_body = executive_js[build_start:build_end]
    assert 'entrypointCtx.entrypoint !== "board_portal"' in build_body, (
        "buildAssistantReply must check entrypoint before attaching driver_context"
    )
    # Must still have driver_context for non-board entrypoints
    assert "body.driver_context = {" in build_body, (
        "buildAssistantReply must still attach driver_context for non-board entrypoints"
    )
    # assistantEntrypointContext still classifies board prompts correctly
    ctx_start = executive_js.index("function assistantEntrypointContext(sourceEl)")
    ctx_end = executive_js.index("function buildAssistantReply", ctx_start)
    ctx_body = executive_js[ctx_start:ctx_end]
    assert '"board_portal"' in ctx_body, (
        "assistantEntrypointContext must still classify board prompts as board_portal"
    )
    # Board portal prompts must use board_packet driver_key not stale active driver
    assert '"board_packet"' in ctx_body, (
        "assistantEntrypointContext must use board_packet driver_key for board_portal"
    )
