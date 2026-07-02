import json
import os

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
    assert "No sign-up needed for the public preview" in html
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
    assert 'id="ask-toggle"' in html
    assert "Mizan Group" in html
    assert "Viewing as" not in html
    assert "◆ Hermes" in html
    assert ">KA<" in html
    assert 'id="theme-toggle"' in html
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
    assert "Think and model on your data" in html
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
    assert 'id="ask-toggle"' in html
    assert "Mizan Group" in html
    assert "Viewing as" not in html
    assert "◆ Hermes" in html
    assert ">KA<" in html
    assert 'id="theme-toggle"' in html
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
    assert '<script id="strategyos-bootstrap"' not in html


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
    assert "◆ Hermes" in html
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
    assert "https://" not in combined
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
