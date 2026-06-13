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


def _dashboard_response() -> str:
    client = TestClient(api_module.app)
    response = client.get("/")
    assert response.status_code == 200
    return response.text


def _static_app_js() -> str:
    client = TestClient(api_module.app)
    response = client.get("/static/app.js")
    assert response.status_code == 200
    return response.text


def test_dashboard_renders_chat_dashboard_shell():
    html = _dashboard_response()

    assert "StrategyOS Chat Dashboard" in html
    assert 'id="app-name"' in html
    assert 'id="run-pill"' in html
    assert 'id="ui-identity"' in html
    assert 'id="new-run-button"' in html
    assert 'id="system-drawer-button"' in html
    assert 'src="/static/app.js"' in html
    assert 'href="/static/styles.css"' in html


def test_dashboard_embeds_parseable_bootstrap_json():
    html = _dashboard_response()

    marker = '<script id="strategyos-bootstrap" type="application/json">'
    assert marker in html
    bootstrap_json = html.partition(marker)[2].partition("</script>")[0]
    assert "&quot;" not in bootstrap_json
    bootstrap = json.loads(bootstrap_json)
    assert bootstrap["product_name"] == "StrategyOS"
    assert bootstrap["qa_modes"]["deterministic"]["enabled"] is True
    assert "enabled" in bootstrap["qa_modes"]["llm"]


def test_dashboard_renders_kpi_stage_and_store_hooks():
    html = _dashboard_response()
    js = _static_app_js()

    assert 'id="kpi-cards"' in html
    assert 'id="kpi-recoverable"' in html
    assert 'id="kpi-findings"' in html
    assert 'id="kpi-citations"' in html
    assert 'id="kpi-challenged"' in html
    assert 'id="stage-stepper"' in html
    assert 'id="store-badges"' in html
    assert 'id="partial-run-chips"' in html
    assert 'requestJson("/runs/latest/audit-summary")' in js
    assert "total_recoverable_sar" in js
    assert "runtime?.pipeline" in js
    assert "state_store" in js
    assert "No analyses yet - choose Start analysis." in js
    assert "No vector data yet" in js
    assert "Graph empty" in js


def test_dashboard_renders_deterministic_chat_hooks_and_qa_fetch():
    html = _dashboard_response()
    js = _static_app_js()

    assert "Ask questions about the latest analysis." in html
    assert "uploaded files" in html
    assert 'id="chat-thread"' in html
    assert 'id="chat-messages"' in html
    assert 'id="chat-suggestions"' in html
    assert 'id="chat-form"' in html
    assert 'id="chat-input"' in html
    assert 'id="chat-send"' in html
    assert 'id="qa-mode-switch"' in html
    assert 'data-qa-mode="deterministic"' in html
    assert 'data-qa-mode="llm"' in html
    assert 'requestJson("/qa"' in js
    assert "mode: state.qaMode" in js
    assert "strategyos.ui.qaMode" in js
    assert "activeQaRunId: activeRunId" in js
    assert "What is the total recoverable?" in js


def test_dashboard_renders_unmatched_chat_suggestions_path():
    js = _static_app_js()

    assert "payload.matched === false" in js
    assert "payload.suggestions" in js
    assert "I don't have" not in js  # copy belongs to the deterministic backend, not UI fakery
    assert "data-suggestion" in js


def test_dashboard_renders_review_action_message_hooks():
    html = _dashboard_response()
    js = _static_app_js()

    assert 'id="review-message"' in html
    assert 'id="review-comment"' in html
    assert 'id="review-approve"' in html
    assert 'id="review-reject"' in html
    assert 'id="review-resume"' in html
    assert 'id="review-new-run"' in html
    assert "Waiting for reviewer approval." in js
    assert "Upload readable finance files before review." in js
    assert "/claim" in js
    assert "/reviewer/runs/" in js
    assert "/operator/runs/" in js
    assert "requires_human_review" in js


def test_dashboard_renders_sign_in_and_local_storage_token_flow():
    html = _dashboard_response()
    js = _static_app_js()

    assert 'id="sign-in-panel"' in html
    assert 'id="session-token"' in html
    assert 'id="connect-button"' in html
    assert 'id="clear-button"' in html
    assert "strategyos.ui.token" in js
    assert "window.localStorage.setItem" in js
    assert "Authorization: `Bearer" in js
    assert '"X-API-Key"' in js
    assert 'requestJson("/ui/session")' in js
    assert "formatSessionIdentity" in js
    assert "`${role}: ${subject}`" not in js


def test_dashboard_renders_new_run_slide_over_and_start_run_hooks():
    html = _dashboard_response()
    js = _static_app_js()

    assert 'id="new-run-drawer"' in html
    assert "Start analysis" in html
    assert "Start with current settings" in html
    assert "POST /runs" not in html
    assert 'id="start-run-form"' in html
    assert 'id="start-run-dataset"' in html
    assert 'id="start-run-run-dir"' in html
    assert 'id="start-run-skip-prepare"' in html
    assert 'id="start-run-sync-artifacts"' in html
    assert 'id="start-run-allow-partial-source-pack"' in html
    assert 'requestJson("/runs"' in js
    assert "submitStartRun" in js


def test_dashboard_renders_source_pack_intake_hooks():
    html = _dashboard_response()
    js = _static_app_js()

    assert "Select a folder or zip" in html
    assert "Choose the sample dataset zip or a folder of finance files." in html
    assert "Check selected files" not in html
    assert "Advanced: use a server folder" not in html
    assert "POST /source-packs" not in html
    assert 'id="source-pack-upload-form"' in html
    assert 'id="source-pack-files"' in html
    assert "webkitdirectory" in html
    assert 'id="source-pack-path-form"' in html
    assert 'id="source-pack-path"' in html
    assert 'id="source-pack-mappings"' in html
    assert 'id="source-pack-manifest-body"' in html
    assert 'id="source-pack-readiness"' in html
    assert 'requestMultipart("/source-packs"' in js
    assert 'requestJson("/source-packs/from-path"' in js
    assert 'requestJson("/source-packs/validate"' in js
    assert 'requestJson("/source-packs/confirm-mapping"' in js


def test_dashboard_renders_system_drawer_data_health_and_artifact_hooks():
    html = _dashboard_response()
    js = _static_app_js()

    assert 'id="system-drawer"' in html
    assert "Managed data" in html
    assert "Knowledge graph" in html
    assert "Runtime health" in html
    assert "Artifact inspector" in html
    assert 'id="data-summary"' in html
    assert 'id="data-counts-kv"' in html
    assert 'id="data-systems-kv"' in html
    assert 'id="data-payload-preview"' in html
    assert 'id="kg-panel"' in html
    assert 'id="kg-summary"' in html
    assert 'id="kg-graph"' in html
    assert 'id="kg-detail"' in html
    assert 'id="kg-refresh"' in html
    assert 'src="/static/vendor/cytoscape.min.js"' in html
    assert 'id="artifact-tabs"' in html
    assert 'id="artifact-viewer"' in html
    assert 'id="health-summary"' in html
    assert 'id="health-checks-kv"' in html
    assert 'id="health-config-kv"' in html
    assert 'id="health-payload-preview"' in html
    assert 'requestJson("/data/status")' in js
    assert 'requestJson("/runs/latest/knowledge-graph")' in js
    assert "focusKnowledgeGraphNode" in js
    assert "data-kg-node" in js
    assert 'requestJson("/health/live")' in js
    assert 'requestJson("/health/ready")' in js
    assert 'requestJson("/health/dependencies")' in js
    assert "sanitizeUiPayload({ live, ready, config, dependencies })" in js
    assert "internal identity boundary" in js


def test_dashboard_renders_vector_search_utility_hooks():
    html = _dashboard_response()
    js = _static_app_js()

    assert "Search index utility" in html
    assert "GET /data/vector-search" not in html
    assert 'id="vector-search-form"' in html
    assert 'id="vector-search-query"' in html
    assert 'id="vector-search-limit"' in html
    assert 'id="vector-search-results"' in html
    assert 'id="vector-search-payload-preview"' in html
    assert "requestJson(`/data/vector-search?${params.toString()}`)" in js


def test_dashboard_static_assets_have_no_external_origins():
    html = _dashboard_response()
    js = _static_app_js()
    client = TestClient(api_module.app)
    css = client.get("/static/styles.css").text

    combined = html + js + css
    assert "https://cdn" not in combined
    assert "http://" not in combined
    assert "https://" not in combined
    assert "fonts.googleapis" not in combined


def test_dashboard_preserves_bootstrap_bound_client_rendering():
    html = _dashboard_response()
    js = _static_app_js()

    assert "__STRATEGYOS_BOOTSTRAP__" not in html
    assert "bootstrap.product_name" in js
    assert "bootstrap.environment" in js
    assert "bootstrap.api_auth_enabled" in js
    assert "bootstrap.require_human_review" in js


def test_dashboard_polling_uses_latest_run_status_and_visibility():
    js = _static_app_js()

    assert 'requestJson("/runs/latest")' in js
    assert "document.visibilityState" in js
    assert "5000" in js
    assert "30000" in js


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
        assert payload["subject"].startswith("api-key:reviewer:")
    finally:
        _restore_env(original)


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
