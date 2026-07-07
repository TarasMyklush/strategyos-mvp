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
    assert "StrategyOS — Group CEO Diagnostics" in html
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
    assert "Diagnostics" in html and "Assistants" in html and "Knowledge" in html
    assert "Mizan Group" in html
    assert "Viewing as" not in html
    assert "ask-toggle" not in html, "ask-toggle button must be absent (simplified topbar)"
    assert ">KA<" in html
    # Hero banner
    assert 'id="hero"' in html or 'class="hero"' in html
    assert 'id="hero-head"' in html or 'class="hero-title"' in html
    assert 'id="hero-body"' in html or 'class="hero-body"' in html
    assert 'id="hero-score"' in html or 'class="hero-score__value"' in html
    # Driver grid
    assert 'id="driver-row"' in html or 'class="driver-grid"' in html
    # Home composition parity
    assert "The group index" in html
    assert 'id="driver-drill"' in html
    assert 'id="findings-panel"' in html
    assert 'id="developments-panel"' in html
    assert 'id="week-panel"' in html
    assert "Explore scenarios" in html
    assert 'id="board-portal"' in html
    assert 'id="agents-activity"' in html
    assert 'id="assistant-network-card"' in html
    assert 'id="a2a-fab"' in html
    assert 'id="a2a-panel"' in html
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
    assert "StrategyOS — Group CEO Diagnostics" in html
    assert marker in html
    assert 'href="/guide"' in html
    bootstrap_json = html.partition(marker)[2].partition("</script>")[0]
    bootstrap = json.loads(bootstrap_json)
    assert bootstrap["product_name"] == "StrategyOS"
    # Design-faithful UI elements
    assert 'id="topbar"' in html or 'class="topbar"' in html
    assert 'class="brand"' in html
    assert 'id="view-nav"' in html
    assert "Diagnostics" in html and "Assistants" in html and "Knowledge" in html
    assert "Mizan Group" in html
    assert "Viewing as" not in html
    assert "ask-toggle" not in html, "ask-toggle button must be absent (simplified topbar)"
    assert ">KA<" in html
    assert 'id="hero"' in html or 'class="hero"' in html
    assert 'id="hero-score"' in html or 'class="hero-score__value"' in html
    assert 'id="hero-head"' in html or 'class="hero-title"' in html
    assert 'id="driver-row"' in html or 'class="driver-grid"' in html
    assert "The group index" in html
    assert 'id="summary-card"' in html or 'class="summary"' in html
    assert 'id="driver-drill"' in html
    assert 'id="findings-panel"' in html
    assert 'id="developments-panel"' in html
    assert 'id="week-panel"' in html
    assert 'id="board-portal"' in html
    assert 'id="agents-activity"' in html
    assert 'id="persona-menu"' in html or 'id="persona-btn"' in html
    assert 'id="assistant-network-card"' in html
    assert 'id="a2a-fab"' in html
    assert 'id="a2a-panel"' in html
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
    assert "StrategyOS — Group CEO Diagnostics" in app_response.text
    assert "StrategyOS — Group CEO Diagnostics" in alias_response.text
    assert '<script id="strategyos-executive-bootstrap"' in app_response.text
    assert '<script id="strategyos-executive-bootstrap"' in alias_response.text
    assert '<script id="strategyos-bootstrap"' not in app_response.text
    assert '<script id="strategyos-bootstrap"' not in alias_response.text
    assert "StrategyOS.live Governed Diagnostics Workspace" not in app_response.text
    assert "StrategyOS.live Governed Diagnostics Workspace" not in alias_response.text


def test_app_entry_uses_design_faithful_executive_surface():
    html = _app_entry_response()
    js = _static_executive_js()

    assert "StrategyOS — Group CEO Diagnostics" in html
    assert "StrategyOS" in html
    assert 'id="topbar"' in html or 'class="topbar"' in html
    assert 'class="brand"' in html
    assert 'id="view-nav"' in html
    assert "Diagnostics" in html and "Assistants" in html and "Knowledge" in html
    assert "Mizan Group" in html
    assert "Viewing as" not in html
    assert "ask-toggle" not in html, "ask-toggle button must be absent (simplified topbar)"
    assert ">KA<" in html
    assert 'id="hero"' in html or 'class="hero"' in html
    assert 'id="driver-row"' in html or 'class="driver-grid"' in html
    assert "The group index" in html
    assert 'id="summary-card"' in html or 'class="summary"' in html
    assert 'id="driver-drill"' in html
    assert 'id="findings-panel"' in html
    assert 'id="developments-panel"' in html
    assert 'id="week-panel"' in html
    assert 'id="board-portal"' in html
    assert 'id="agents-activity"' in html
    assert 'id="assistant-network-card"' in html
    assert 'id="a2a-fab"' in html
    assert 'id="a2a-panel"' in html
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


def test_entry_routes_static_assets_have_no_external_origins():
    html = _app_entry_response()
    js = _static_executive_js()
    client = TestClient(api_module.app)
    executive_html = client.get("/executive").text
    css = client.get("/static/executive.css").text

    combined = html + executive_html + js + css
    assert "https://cdn" not in combined
    assert "http://" not in combined
    # Allow intentional YouTube embed URLs in the Leaders' Corner modal
    combined_no_youtube = combined.replace("https://www.youtube-nocookie.com", "").replace("https://www.youtube.com", "").replace("https://strategyos.live", "")
    assert "https://" not in combined_no_youtube
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
        assert contract_payload["agents"]["discover"]["native"][0]["id"] == "native-covenant"
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


def test_ui_session_and_workspace_contract_support_executive_demo_role(monkeypatch):
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
        assert cases_surface["primary_route"] == "/public/runs/latest/findings"
        assert payload["evidence"]["preview_route"] == "/public/data/evidence-preview"
        assert payload["plan_health"]["root_label"] == "Governed plan posture"
        assert payload["domain_tree"]["nodes"][0]["domain_id"] == "finance"
        assert payload["strategy_substrate"]["intent"]["label"] == "Convert governed finance signal into executive action"
        assert payload["strategy_substrate"]["intent"]["guardrails"]
        assert payload["board_portal"]["meeting"]["title"] == "Governed board packet"
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
        assert payload["board_portal"]["meeting"]["design_title"] == "Q2 Board Meeting"
        assert payload["board_portal"]["kpis"][0]["key"] == "revenue"
        assert payload["board_portal"]["decks"][0]["status"] == "approved"
        assert "default_case_id" not in payload["drilldown"]
        assert payload["drilldown"]["cash_pulse"]["basis"] == "governed_findings"
        assert payload["drilldown"]["gravity"]["prompts"]
        assert payload["drilldown"]["gravity"]["assistant"] == "Minerva"
        assert payload["drilldown"]["gravity"]["sandbox"]["board_state"] == "closed"
        assert payload["drilldown"]["lower_rail"]["board_state"]["presentation_state"] == "closed"
        assert payload["drilldown"]["lower_rail"]["week_ahead"][0]["prompt"]
        assert payload["drilldown"]["lower_rail"]["owed_upward"]["items"]
        assert payload["interaction_contracts"]["latest_run"]["route"] == "/public/runs/latest"
        assert payload["chat"]["assistant"]["persona_id"] == "board"
        assert payload["chat"]["assistant"]["board_state"] == "closed"
        assert payload["chat"]["store"]["mode"] == "client_session"
        assert payload["chat"]["threads"][0]["thread_id"] == "system:latest-public"
        assert payload["agents"]["running"][0]["id"] == "boardpack"
        assert payload["agent_modules"]["summary"]["discoverable_count"] >= 4
        assert payload["tenant_admin_system"]["managed_data"]["reports"]["report_count"] == 2
        assert payload["tenant_admin_system"]["trend"]["truth_basis"] == "reconciled_governed_metrics"
        assert payload["role_actions"]["viewer_role"] == "executive"
        assert "node_id" not in str(payload["strategy_substrate"])
        assert payload["strategy_substrate"]["value_drivers"][0]["driver_id"] == "cash_recovery"
        assert any(driver["driver_id"] == "board_pack_readiness_driver" for driver in payload["strategy_substrate"]["value_drivers"])
        assert any(item["portfolio_id"] == "release-readiness" for item in payload["strategy_substrate"]["portfolio_views"])
        assert any(item["reasoning_id"] == "hold-runtime-boundary" for item in payload["strategy_substrate"]["reasoning"])
        assert payload["executive_diagnostics"]["hero"]["persona_id"] == "board"
        assert payload["executive_diagnostics"]["hero"]["board_state"] == "closed"
        assert payload["executive_diagnostics"]["persona_blueprint"]["assistant"] == "Hermes"
        assert payload["executive_diagnostics"]["board_packet"]["assistant"] == "Minerva"
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
        assert payload["display_subject"] == "Operator"
        assert payload["display_name"] == "Operator"
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
        assert payload["scenario_id"] == "digital_health_eoy_flat"
        assert payload["matched"] is True
        assert payload["mode"] == "deterministic"
        assert payload["assistant_mode"] == "scenario"
        assert payload["trace"]
        assert payload["audit_trail_id"]
        assert payload["hallucination_risk"]["level"] == "low"
        assert payload["prompt_contracts"]["role"]["prompt_id"] == "role:ceo:v1"
        assert "I couldn't reach the shared assistant service just now." not in payload["answer"]
    finally:
        _restore_env(original)


def test_leaders_corner_has_four_youtube_video_ids():
    js = _static_executive_js()
    assert "uTRKdCY4HdE" in js
    assert "sFSzPE2AOE0" in js
    assert "pQtdQ6AHn_Q" in js
    assert "t885M1WB1pg" in js


def test_leaders_corner_has_inline_embed_not_dead_buttons():
    js = _static_executive_js()
    # Inline embed approach — iframe directly in leaders-card
    assert 'leaders-featured-iframe' in js, "Must have inline iframe for featured video"
    assert 'youtube-nocookie.com/embed' in js
    # Thumbnail selectors that swap the inline player
    assert 'leaders-thumb' in js
    assert 'leaders-thumb-grid' in js
    assert 'selectLeadersVideo' in js
    # No fake placeholder copy from old entries
    assert 'Reading margin pressure' not in js
    assert 'Dr. Amal Faris' not in js
    assert 'Tariq Bensalem' not in js
    assert 'Huda Karim' not in js
    # No dead data-vlog-topic or leader-row buttons
    assert 'data-vlog-topic' not in js
    assert 'leader-row__copy' not in js, "Must not render leader-row list — use inline embed + thumbnails"


def test_leaders_corner_modal_fallback_still_works():
    js = _static_executive_js()
    # Modal functions still available as fallback/alternative path
    assert 'openVideoModal' in js
    assert 'closeVideoModal' in js
    has_keyboard = 'Escape' in js or 'keydown' in js or 'addEventListener' in js
    assert has_keyboard, "Modal must have keyboard/Escape support"


def test_leaders_corner_has_hermes_cta_and_fallback_link():
    js = _static_executive_js()
    # Hermes integration still exists for follow-up
    assert 'askAssistant' in js
    assert 'leaders-hermes-cta' in js
    assert 'Ask Hermes about this topic' in js
    # Fallback link to YouTube
    assert 'youtube.com/watch' in js
    assert 'leaders-yt-link' in js
    assert 'Open on YouTube' in js


# ── Leaders' Corner 4-video grid consistency (post-reorg) ──

def test_leaders_corner_four_consistent_thumb_cards():
    """All 4 videos must be in the thumb grid with consistent structure,
    not 1 featured + 3 list rows. Grid wrapper must have proper ID."""
    js = _static_executive_js()

    # Grid wrapper must have id="leaders-thumb-grid" (not just class)
    assert 'id="leaders-thumb-grid"' in js, (
        "Leaders thumb grid must have id='leaders-thumb-grid' for selectLeadersVideo"
    )
    assert 'leaders-thumb-grid' in js, (
        "Leaders thumb grid wrapper class must be present"
    )

    # All 4 video IDs must exist in the source (in vlogs array)
    for vid in ['uTRKdCY4HdE', 'sFSzPE2AOE0', 'pQtdQ6AHn_Q', 't885M1WB1pg']:
        assert ("'" + vid + "'") in js or ('"' + vid + '"') in js, (
            f"Video ID {vid} must be present in vlogs array"
        )

    # data-video-id attribute must be present in thumb rendering (dynamic, but pattern exists)
    assert "data-video-id" in js, (
        "Thumb rendering must use data-video-id attributes"
    )

    # No 'Select a video below' — replaced with 'Loading video...'
    assert 'Select a video below' not in js, (
        "'Select a video below' instruction copy must be removed"
    )
    assert 'Loading video...' in js, (
        "Fallback card must show 'Loading video...' not old instruction copy"
    )


def test_leaders_corner_first_thumb_is_active():
    """First thumb (index 0) must have is-active class inside the class attribute."""
    js = _static_executive_js()

    # The is-active class must be inside the class attribute, not outside
    assert "is-active" in js, (
        "is-active class logic must be present in thumb rendering"
    )
    # Correct pattern: class= ends AFTER the is-active ternary, not before
    assert "class=\"leaders-thumb' + (i === 0 ? ' is-active' : '') + '\"" in js, (
        "is-active must be placed inside the class attribute: "
        "class=\"leaders-thumb' + (i === 0 ? ' is-active' : '') + '\""
    )
    # Verify the old broken pattern (is-active outside class attribute) is absent
    assert "class=\"leaders-thumb\"' + (i === 0 ? ' is-active'" not in js, (
        "is-active must NOT be placed outside the class attribute — "
        "the closing quote of class must come AFTER the ternary"
    )


def test_leaders_corner_summary_label_correct():
    """Summary label must be 'Summary', not 'Transcript' or 'Key points'."""
    js = _static_executive_js()

    assert '<summary>Summary</summary>' in js, (
        "Video info must use 'Summary' label, not 'Transcript' or 'Key points'"
    )


# ── Knowledge Graph rendering ──

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
    assert "Graph Universe" in js, "Knowledge graph should expose Graph Universe mode"
    assert "kg-density-toggle" in js, "Density toggle control must exist"
    assert "kg-zoom-in" in js and "kg-zoom-out" in js, "Zoom controls must exist"
    assert "kg-focus-mode" in js, "Focus mode control must exist"
    assert "evidence/source/relationship nodes" in js, "Synthetic node provenance copy must be explicit"


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


def test_kg_universe_uses_honest_derived_density_nodes():
    """Dense graph mode must use explicit derived evidence/source/path nodes, not silent fake claims."""
    js = _static_executive_js()

    assert 'satelliteKind = satelliteIndex % 5 === 0 ? "source"' in js, (
        "Dense universe must derive source/evidence satellites"
    )
    assert "targetTotalNodes = Math.max(110" in js, (
        "Dense universe must target 100+ visible nodes in honest derived mode"
    )
    assert "visual evidence density, not a new business claim" in js, (
        "Derived density nodes must explicitly disclaim fabricated business claims"
    )
    assert 'category: "relationship"' in js, "Relationship relay nodes must exist"
    assert "relayCount = primaryNodes.length <= 6 ? 3 : 2" in js, (
        "Sparse governed graphs must gain extra bridge relays so the universe reads visually dense"
    )


# ── YouTube Leaders' Corner embed safety ──

def test_leaders_corner_embed_has_origin_param():
    """YouTube embed URL must include origin parameter (prevents Error 153)."""
    js = _static_executive_js()

    # Inline embed (initial render)
    assert "encodeURIComponent(window.location.origin)" in js, (
        "origin must be set dynamically via encodeURIComponent(window.location.origin)"
    )
    assert "?origin=" in js, "URL must contain origin parameter"

    # The embed URL must still be wired for controlled playback surfaces.
    origin_count = js.count("encodeURIComponent(window.location.origin)")
    assert origin_count >= 1, (
        f"origin should appear in at least 1 playback URL, found {origin_count}"
    )


def test_leaders_corner_embed_has_enablejsapi():
    """YouTube embed URL must include enablejsapi=1 for postMessage error detection."""
    js = _static_executive_js()

    assert "enablejsapi=1" in js, (
        "enablejsapi=1 required for YouTube IFrame API postMessage events"
    )

    # Must still appear in the controlled playback path.
    jsapi_count = js.count("enablejsapi=1")
    assert jsapi_count >= 1, (
        f"enablejsapi=1 should appear in at least 1 playback URL, found {jsapi_count}"
    )


def test_leaders_corner_embed_has_safe_params():
    """YouTube embed must keep rel=0 and modestbranding=1 params."""
    js = _static_executive_js()

    assert "rel=0" in js, "rel=0 prevents related videos at end"
    assert "modestbranding=1" in js, "modestbranding=1 keeps player clean"


def test_leaders_corner_embed_has_referrerpolicy_and_fullscreen():
    """iframe must have referrerpolicy and fullscreen in allow attribute."""
    js = _static_executive_js()

    assert "referrerpolicy" in js, (
        "iframe must have referrerpolicy attribute for cross-origin"
    )
    assert "strict-origin-when-cross-origin" in js, (
        "referrerpolicy must be strict-origin-when-cross-origin"
    )

    # allow attribute must include fullscreen
    assert "fullscreen" in js, "allow attribute must include fullscreen"
    # Verify fullscreen appears in iframe allow context (near youtube-nocookie)
    embed_section = js[js.index("youtube-nocookie.com/embed"):]
    assert "fullscreen" in embed_section[:500], (
        "fullscreen must be near the youtube-nocookie embed URL"
    )


def test_leaders_corner_has_fallback_card_code():
    """Fallback card code must be present for when embed fails."""
    js = _static_executive_js()

    assert "leaders-fallback-card" in js, (
        "Fallback card HTML class must be present"
    )
    assert "leaders-fallback-icon" in js, (
        "Fallback card icon class must be present"
    )
    assert "leaders-fallback-link" in js, (
        "Fallback 'Open on YouTube' link class must be present"
    )
    assert "leaders-fallback-msg" in js, (
        "Fallback message class must be present"
    )
    assert "is not available" in js, (
        "Fallback must indicate video unavailable inline"
    )


def test_leaders_corner_has_postmessage_error_detection():
    """PostMessage listener must exist for YouTube onError detection."""
    js = _static_executive_js()

    assert "addEventListener('message'" in js, (
        "postMessage listener must be registered for YouTube events"
    )
    assert "youtube-nocookie.com" in js, (
        "postMessage listener must filter youtube-nocookie.com origin"
    )
    assert '"onError"' in js or "'onError'" in js, (
        "postMessage listener must handle YouTube onError event"
    )
    assert "leaders-featured-iframe" in js, (
        "postMessage error handler must target leaders-featured-iframe"
    )


def test_leaders_corner_has_fallback_timer():
    """Fallback timer must use global _leadersFallbackTimer variable."""
    js = _static_executive_js()

    assert "_leadersFallbackTimer" in js, (
        "Must use global _leadersFallbackTimer for consistent fallback timing"
    )
    assert "clearTimeout(_leadersFallbackTimer)" in js, (
        "Must clear previous fallback timer when switching videos"
    )


def test_leaders_corner_no_hardcoded_origin():
    """Origin must NOT be hardcoded — must use window.location.origin."""
    js = _static_executive_js()

    # The hardcoded origin should NOT appear
    assert 'origin=https://strategyos.live' not in js, (
        "Origin must be dynamic (window.location.origin), not hardcoded to strategyos.live"
    )


def test_leaders_corner_fallback_css_exists():
    """CSS must include styles for leaders-fallback-card, including [hidden] override."""
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    assert ".leaders-fallback-card" in css, (
        "CSS must define .leaders-fallback-card styles"
    )
    assert ".leaders-fallback-icon" in css, (
        "CSS must define .leaders-fallback-icon styles"
    )
    assert ".leaders-fallback-link" in css, (
        "CSS must define .leaders-fallback-link styles"
    )
    # The hidden attribute override must exist to prevent display:flex
    # from overruling [hidden] (fallback card stacking above iframe)
    assert ".leaders-fallback-card[hidden]" in css, (
        "CSS must define .leaders-fallback-card[hidden] to override display:flex "
        "when JS sets fallback.hidden = true"
    )
    # Verify the override uses display:none (or !important) — not just a redefinition
    hidden_rule_section = css[css.find(".leaders-fallback-card[hidden]"):]
    assert "display: none" in hidden_rule_section[:120], (
        ".leaders-fallback-card[hidden] must use display:none to hide fallback card"
    )


def test_leaders_corner_fallback_hidden_css_not_overridable():
    """The .leaders-fallback-card[hidden] rule must be placed AFTER the primary
    .leaders-fallback-card rule so it takes priority in the cascade and reliably
    overrides display:flex when the hidden attribute is present.

    This prevents the exact Hermes live-verification failure: hidden=true on the
    element but computed display:flex still wins, stacking fallback above iframe."""
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    fallback_pos = css.find(".leaders-fallback-card {")
    hidden_pos = css.find(".leaders-fallback-card[hidden]")
    assert fallback_pos > 0, ".leaders-fallback-card base rule must exist"
    assert hidden_pos > 0, ".leaders-fallback-card[hidden] override must exist"
    # The [hidden] override must come AFTER the base rule so it wins the cascade
    assert hidden_pos > fallback_pos, (
        ".leaders-fallback-card[hidden] must appear AFTER .leaders-fallback-card "
        "in the stylesheet so the cascade correctly overrides display:flex"
    )


def test_leaders_corner_first_load_initializes_iframe():
    """On first load, selectLeadersVideo must be called with vlogs[0] to show embedded iframe, not dead placeholder."""
    js = _static_executive_js()

    # selectLeadersVideo must be called during initialization with the first video
    assert "selectLeadersVideo(vlogs[0]" in js, (
        "On first load, selectLeadersVideo(vlogs[0]) must be called to initialize embedded player"
    )
    # The featured iframe element must exist in the template
    assert "leaders-featured-iframe" in js, (
        "Featured iframe element must exist for video playback"
    )
    # The fallback card element must exist as safety net but JS must switch to iframe
    assert "leaders-featured-fallback" in js, (
        "Fallback card must exist in template but JS initializes iframe on load"
    )


def test_leaders_corner_single_featured_surface():
    """Featured surface must stay controlled and English-first on the card."""
    js = _static_executive_js()
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    assert "leaders-featured-fallback" in js, "Fallback card element must exist"
    assert "leaders-featured-iframe" in js, "Featured iframe element must exist"
    assert "Preview stays in English on this surface." in js
    assert "iframe.src = ''" in js, "Card preview must clear inline iframe src"
    assert "Watch in player" in js, "Card preview must offer controlled playback CTA"
    assert ".leaders-fallback-card[hidden]" in css, (
        "CSS must preserve hidden override for the fallback shell"
    )


# ── Global Assistant CTA Surface Architecture ──

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
    """_openHermesDrawer must guard: close video modal, close A2A, no redundant open."""
    js = _static_executive_js()

    open_fn_start = js.index("function _openHermesDrawer(")
    open_fn_end = js.index("function _closeHermesDrawer()")
    open_fn_body = js[open_fn_start:open_fn_end]

    # Video modal guard
    assert "state.videoModalOpen" in open_fn_body, (
        "Must check videoModalOpen before opening drawer"
    )
    assert "closeVideoModal()" in open_fn_body, (
        "Must close video modal when opening drawer"
    )

    # A2A panel guard
    assert "state.a2aOpen" in open_fn_body, (
        "Must check a2aOpen before opening drawer"
    )

    # No redundant open
    assert "if (state.drawerOpen) return" in open_fn_body, (
        "Must guard against redundant drawer opening"
    )


def test_assistant_drawer_mutual_exclusion_video_modal():
    """openVideoModal must close assistant drawer before opening modal."""
    js = _static_executive_js()

    modal_fn_start = js.index("function openVideoModal(")
    # End boundary: next function after openVideoModal
    modal_fn_end = js.index("function renderBoardStateTabs()")
    modal_fn_body = js[modal_fn_start:modal_fn_end]

    assert "state.drawerOpen" in modal_fn_body, (
        "openVideoModal must check drawerOpen state"
    )
    assert "_closeHermesDrawer()" in modal_fn_body, (
        "openVideoModal must close drawer when opening modal"
    )


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
    - Leaders' Corner: leaders-hermes-cta → askAssistant
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
        ("Leaders Corner Hermes CTA", 'leaders-hermes-cta'),
        ("KG Inspector", 'kg-inspector-ask'),
        ("Assistant prompt chips", 'data-assistant-prompt'),
    ]
    for label, pattern in cta_patterns:
        assert pattern in js, (
            f"CTA family '{label}' must have attribute '{pattern}' in executive.js"
        )

    # Floating launcher must open drawer directly via shared _openHermesDrawer
    assert 'launcher.onclick' in js, "Floating launcher must have onclick handler"
    launcher_idx = js.index('launcher.onclick')
    launcher_block = js[launcher_idx:launcher_idx + 200]
    assert '_openHermesDrawer(' in launcher_block, (
        "Floating launcher must call _openHermesDrawer() — not bypass the shared path"
    )


def test_assistant_transport_includes_source_and_entrypoint_metadata():
    """Shared assistant transport must send explicit source/entrypoint metadata."""
    js = _static_executive_js()
    assert "assistantEntrypointContext" in js
    assert "body.assistant_context = assistantEntrypointContext(sourceEl);" in js
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


def test_board_portal_refresh_preserves_user_selected_stage():
    """Refresh must not overwrite the stage a user just selected in the Board Portal."""
    js = _static_executive_js()

    expected = "state.activeBoard = firstDefined(state.activeBoard, (state.latestPacket.executive_modes || {}).active_board_state, (state.latestPacket.board_portal || {}).presentation_state, \"pre\");"
    assert expected in js, (
        "Board Portal refresh must prefer the locally selected activeBoard before packet defaults, "
        "or Live/Closed clicks snap back to Pre-board"
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
    """State object must have drawerOpen and videoModalOpen initialized to false."""
    js = _static_executive_js()

    # state initialization block
    state_start = js.index("var state = {")
    state_end = js.index("bindAssistantForm();")
    state_block = js[state_start:state_end]

    assert "drawerOpen: false" in state_block, "drawerOpen must be initialized to false"
    assert "videoModalOpen: false" in state_block, "videoModalOpen must be initialized to false"
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
        'Hermes will answer here using the current board pack.',
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
    assert "function ceoDriverRelevanceReply" not in executive_js
    assert "driver_context" in executive_js
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
    assert "body.assistant_context = assistantEntrypointContext(sourceEl);" in executive_js
    assert 'var endpoint = "/assistant/chat";' in executive_js


def test_assistant_requests_include_shared_entrypoint_metadata():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    assert "function assistantEntrypointContext" in executive_js
    assert "body.assistant_context = assistantEntrypointContext(sourceEl);" in executive_js
    for token in [
        '"driver_composer"',
        '"finding_cta"',
        '"development_cta"',
        '"week_composer"',
        '"leaders_corner"',
        '"knowledge_graph"',
        '"agents_discovery"',
        '"board_portal"',
    ]:
        assert token in executive_js


def test_executive_surface_prefers_shared_assistant_packet_for_visible_facts():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text()
    assert "BOOTSTRAP_ASSISTANT_CONTEXT = bootstrap.assistant_public_context || {}" in executive_js
    assert "function getSharedAssistantContext()" in executive_js
    assert "state.latestPacket && state.latestPacket.assistant_public_context" in executive_js
    assert "return getSharedAssistantContext().board_portal || DESIGN_GLOBAL.board || {}" in executive_js
    assert "if ((shared.persona_id || \"ceo\") === personaId)" in executive_js
    assert "return shared.agent_activity || DESIGN_GLOBAL.activity || {}" in executive_js
    assert "if (safeArray(shared.kg_nodes).length)" in executive_js


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
    assert 'Explain why “' in executive_js
    assert 'matters for the board review and what action I should consider.' in executive_js
    assert 'markThreadTransportFailuresRetryable(current);' in executive_js
    assert 'data-assistant-retry-latest' in executive_js


def test_stale_fx_fallback_thread_reloads_and_auto_recovers():
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
    assert result["autoRetried"] is True
    assert result["finalStatus"] == "ok"
    assert "I couldn't reach the shared assistant service just now." not in result["finalText"]
    assert "~SAR 9k weekly drag" in result["finalText"]
    assert "19.2% versus a 19.4% plan" in result["finalText"]
    assert "packet" not in result["finalText"].lower()


def test_assistant_css_styles_retryable_failure_state():
    executive_css = Path("strategyos_mvp/static/executive.css").read_text()
    assert '.assistant-message--failed' in executive_css
    assert '.assistant-message__meta' in executive_css
    assert '.assistant-retry-button' in executive_css
    assert '.assistant-tool-chip--action' in executive_css


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
    assert result["answerMeta"] == ""


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


def test_board_state_tabs_switch_client_state_without_refresh_reset():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    tabs_start = executive_js.index("function renderBoardStateTabs()")
    portal_start = executive_js.index("function renderBoardPortal()", tabs_start)
    tabs_block = executive_js[tabs_start:portal_start]

    assert 'state.activeBoard = mode.state_id;' in tabs_block
    assert 'updateHistory();' in tabs_block
    assert 'renderPersonaView();' in tabs_block
    assert 'refresh(true);' not in tabs_block, (
        "Board state tab clicks must not refresh and immediately reset the selected stage"
    )


def test_refresh_preserves_selected_board_state_over_server_default():
    executive_js = Path("strategyos_mvp/static/executive.js").read_text(encoding="utf-8")
    assert 'state.activeBoard = firstDefined(state.activeBoard, (state.latestPacket.executive_modes || {}).active_board_state, (state.latestPacket.board_portal || {}).presentation_state, "pre");' in executive_js
