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


def test_dashboard_renders_queue_first_shell():
    client = TestClient(api_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Governed Operations Shell" in response.text
    assert "Home / Queue" in response.text
    assert "Pending review queue" in response.text
    assert "StrategyOS Governed Operations" in response.text
    assert "Partial backend data loaded" in response.text
    assert "guarded('Latest run', requestJson('/runs/latest'), null)" in response.text


def test_dashboard_embeds_parseable_bootstrap_json():
    client = TestClient(api_module.app)

    response = client.get("/")

    assert response.status_code == 200
    marker = '<script id="strategyos-bootstrap" type="application/json">'
    assert marker in response.text
    bootstrap_json = response.text.partition(marker)[2].partition("</script>")[0]
    assert "&quot;" not in bootstrap_json
    assert json.loads(bootstrap_json)["product_name"] == "StrategyOS"


def test_dashboard_renders_run_detail_and_review_console_slice():
    client = TestClient(api_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Selected run summary" in response.text
    assert "Lifecycle timeline" in response.text
    assert "fixed MVP stages" in response.text
    assert "awaiting-review, approval, and completion" in response.text
    assert "Review context" in response.text
    assert "Guarded reviewer/operator actions" in response.text
    assert 'id="claim-run"' in response.text
    assert 'id="unclaim-run"' in response.text
    assert 'id="approve-run"' in response.text
    assert 'id="resume-run"' in response.text
    assert "Artifact entry points" in response.text


def test_dashboard_renders_runs_index_slice_and_fetch_hook():
    client = TestClient(api_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Runs index" in response.text
    assert "Recent governed runs with lifecycle state, review context, and drill-in actions" in response.text
    assert 'id="runs-index-body"' in response.text
    assert 'id="runs-index-empty"' in response.text
    assert "Open run detail" in response.text
    assert "Open review context" in response.text
    assert "requestJson('/reviewer/runs?limit=12')" in response.text
    assert "runReviewContext(item)" in response.text


def test_dashboard_renders_queue_assignment_hooks_for_claim_unclaim_slice():
    client = TestClient(api_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "thin claim/unclaim assignment" in response.text
    assert "Claim this governed run before approving or rejecting it" in response.text
    assert "data-claim-run" in response.text
    assert "data-unclaim-run" in response.text
    assert "claimSelectedRun" in response.text
    assert "unclaimSelectedRun" in response.text


def test_dashboard_renders_artifact_inspection_slice_and_deep_linking_hooks():
    client = TestClient(api_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Artifact inspector" in response.text
    assert "Artifact tabs" in response.text
    assert "Artifact viewer" in response.text
    assert "Deep link" in response.text
    assert "parseHashRoute" in response.text


def test_dashboard_renders_artifact_inspector_slice():
    client = TestClient(api_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert ">Artifacts<" in response.text
    assert "Artifact inspector" in response.text
    assert 'id="artifact-tabs"' in response.text
    assert 'id="artifact-viewer"' in response.text
    assert "Inspect artifact" in response.text


def test_dashboard_renders_richer_data_status_console_slice():
    client = TestClient(api_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Managed data shell" in response.text
    assert "Data counts" in response.text
    assert "Graph and vector surfaces" in response.text
    assert 'id="data-summary"' in response.text
    assert 'id="data-counts-kv"' in response.text
    assert 'id="data-systems-kv"' in response.text
    assert 'id="data-payload-preview"' in response.text


def test_dashboard_renders_vector_search_utility_panel_and_fetch_hook():
    client = TestClient(api_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Vector search utility" in response.text
    assert "GET /data/vector-search" in response.text
    assert 'id="vector-search-form"' in response.text
    assert 'id="vector-search-query"' in response.text
    assert 'id="vector-search-results"' in response.text
    assert 'id="vector-search-payload-preview"' in response.text
    assert "activeVectorRunId()" in response.text
    assert "requestJson(`/data/vector-search?${params.toString()}`)" in response.text


def test_dashboard_renders_qa_panel_and_fetch_hook():
    client = TestClient(api_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Data Q&A" in response.text
    assert "POST /qa" in response.text
    assert 'id="qa-form"' in response.text
    assert 'id="qa-input"' in response.text
    assert 'id="qa-thread"' in response.text
    assert 'id="qa-payload-preview"' in response.text
    assert "activeQaRunId()" in response.text
    assert "requestJson('/qa'" in response.text


def test_dashboard_renders_operator_start_run_form_slice_and_submit_hook():
    client = TestClient(api_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Start governed run" in response.text
    assert "POST /runs" in response.text
    assert 'id="start-run-form"' in response.text
    assert 'id="start-run-dataset"' in response.text
    assert 'id="start-run-run-dir"' in response.text
    assert 'id="start-run-skip-prepare"' in response.text
    assert 'id="start-run-sync-artifacts"' in response.text
    assert "toggleStartRunPanel" in response.text
    assert "submitStartRun" in response.text
    assert "requestJson('/runs', { method: 'POST', body: JSON.stringify(payload) })" in response.text


def test_dashboard_renders_source_pack_intake_slice_and_hooks():
    client = TestClient(api_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Source-pack intake preview" in response.text
    assert "POST /source-packs" in response.text
    assert "POST /source-packs/from-path" in response.text
    assert "POST /source-packs/validate" in response.text
    assert 'id="source-pack-upload-form"' in response.text
    assert 'id="source-pack-files"' in response.text
    assert "webkitdirectory" in response.text
    assert 'id="source-pack-path-form"' in response.text
    assert 'id="source-pack-path"' in response.text
    assert 'id="source-pack-mappings"' in response.text
    assert 'id="source-pack-manifest-body"' in response.text
    assert 'id="source-pack-readiness"' in response.text
    assert "requestMultipart('/source-packs', formData)" in response.text
    assert "submitSourcePackUpload" in response.text
    assert "submitSourcePackPath" in response.text
    assert "revalidateSourcePack" in response.text
    assert "confirmSourcePackMapping" in response.text
    assert 'id="start-run-allow-partial-source-pack"' in response.text


def test_dashboard_renders_richer_health_console_slice_and_live_fetch_hook():
    client = TestClient(api_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "API / health shell" in response.text
    assert "Dependency checks" in response.text
    assert "Config and access posture" in response.text
    assert 'id="health-summary"' in response.text
    assert 'id="health-checks-kv"' in response.text
    assert 'id="health-config-kv"' in response.text
    assert 'id="health-payload-preview"' in response.text
    assert "requestJson('/health/live')" in response.text


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
