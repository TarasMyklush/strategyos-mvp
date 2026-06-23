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
    response = client.get("/app")
    assert response.status_code == 200
    return response.text


def _homepage_response() -> str:
    client = TestClient(api_module.app)
    response = client.get("/")
    assert response.status_code == 200
    return response.text


def _static_app_js() -> str:
    client = TestClient(api_module.app)
    response = client.get("/static/app.js")
    assert response.status_code == 200
    return response.text


def _static_executive_js() -> str:
    client = TestClient(api_module.app)
    response = client.get("/static/executive.js")
    assert response.status_code == 200
    return response.text


def test_homepage_renders_executive_recovery_control_room():
    html = _homepage_response()

    marker = '<script id="strategyos-executive-bootstrap" type="application/json">'
    assert "StrategyOS.live Executive Cockpit" in html
    assert "RECOVERY INTELLIGENCE ONLINE" in html
    assert "Open review app" in html
    assert "Cash recovery radar" in html
    assert "STRATEGYOS COPILOT" in html
    assert "Case matrix" in html
    assert "Reports" in html
    assert 'id="exec-persona-tabs"' in html
    assert 'id="exec-lifecycle-tabs"' in html
    assert 'id="exec-driver-stack"' in html
    assert 'id="exec-theme-tabs"' in html
    assert 'id="exec-density-tabs"' in html
    assert 'id="exec-movers-tabs"' in html
    assert 'id="exec-thread-list"' in html
    assert 'id="exec-assistant-network"' in html
    assert 'id="exec-week-rail"' in html
    assert "Board-safe narrative surface" in html
    assert "Governed review lane" in html
    assert "Run-control lane" in html
    assert "Tenant admin / system altitude" in html
    assert "Good morning, Khalid" in html
    assert "Hermes · Executive brief from live run data." in html
    assert "Truth today: there is no standalone executive auth role; the BU backend role is now bounded and read-only." in html
    assert marker in html
    bootstrap_json = html.partition(marker)[2].partition("</script>")[0]
    bootstrap = json.loads(bootstrap_json)
    assert bootstrap["product_name"] == "StrategyOS"
    assert 'href="#overview"' in html
    assert 'href="#cases"' in html
    assert 'href="#evidence"' in html
    assert 'href="#reports"' in html
    assert '<script id="strategyos-bootstrap"' not in html


def test_executive_cockpit_renders_live_command_shell():
    client = TestClient(api_module.app)
    response = client.get("/executive")
    assert response.status_code == 200
    html = response.text
    js = _static_executive_js()

    marker = '<script id="strategyos-executive-bootstrap" type="application/json">'
    assert "StrategyOS.live Executive Cockpit" in html
    assert 'href="/static/executive.css?v=ux-20260623c"' in html
    assert 'src="/static/executive.js?v=ux-20260623c"' in html
    assert marker in html
    bootstrap_json = html.partition(marker)[2].partition("</script>")[0]
    bootstrap = json.loads(bootstrap_json)
    assert bootstrap["product_name"] == "StrategyOS"
    assert 'id="exec-command-form"' in html
    assert 'id="exec-session-panel"' in html
    assert 'id="exec-decision-list"' in html
    assert 'id="exec-case-body"' in html
    assert "Overview" in html
    assert "Cases" in html
    assert "Evidence" in html
    assert "Reports" in html
    assert 'id="exec-overview-status"' in html
    assert 'id="exec-plan-health-status"' in html
    assert 'id="exec-plan-kpi-value"' in html
    assert 'id="exec-plan-kpi-cases"' in html
    assert 'id="exec-plan-kpi-evidence"' in html
    assert 'id="exec-plan-health-source-note"' in html
    assert 'id="exec-company-switcher"' in html
    assert 'id="exec-portfolio-switcher"' in html
    assert 'id="exec-scope-summary"' in html
    assert 'id="exec-evidence-preview"' in html
    assert 'id="exec-report-list"' in html
    assert 'id="exec-report-preview"' in html
    assert 'id="exec-domain-tree"' in html
    assert 'id="exec-publication-list"' in html
    assert 'id="exec-kpi-tree-status"' in html
    assert 'id="exec-value-driver-list"' in html
    assert 'id="exec-strategy-intent-summary"' in html
    assert 'id="exec-intent-reasoning-list"' in html
    assert 'id="exec-persona-tabs"' in html
    assert 'id="exec-persona-button"' in html
    assert 'id="exec-persona-menu"' in html
    assert 'id="exec-lifecycle-tabs"' in html
    assert 'id="exec-driver-stack"' in html
    assert 'id="exec-theme-tabs"' in html
    assert 'id="exec-density-tabs"' in html
    assert 'id="exec-movers-tabs"' in html
    assert 'id="exec-hero-score"' in html
    assert 'id="exec-driver-tiles"' in html
    assert 'id="exec-drill-trend"' in html
    assert 'id="exec-drill-movers"' in html
    assert 'id="exec-drill-prompts"' in html
    assert 'id="exec-gravity-prompt-list"' in html
    assert 'id="exec-gravity-quote"' in html
    assert 'id="exec-board-lifecycle"' in html
    assert 'id="exec-board-primary-list"' in html
    assert 'id="exec-agents-running-list"' in html
    assert 'id="exec-agents-native-list"' in html
    assert 'id="exec-developments-list"' in html
    assert 'id="exec-week-rail"' in html
    assert 'id="exec-pulse-grid"' in html
    assert 'id="exec-owed-list"' in html
    assert 'id="exec-board-state-detail"' in html
    assert 'id="exec-thread-list"' in html
    assert 'id="exec-assistant-network"' in html
    assert "Executive altitude" in html
    assert "BU / reviewer altitude" in html
    assert "Operator altitude" in html
    assert "Tenant admin / system altitude" in html
    assert "Board portal lifecycle" in html
    assert "Running now and discover more" in html
    assert "Developments, prep, and weekly rhythm" in html
    assert "Good morning, Khalid" in html
    assert "Hermes · Executive brief from live run data." in html
    assert "Executive remains read-only." in html
    assert "strategyos.ui.token" in js
    assert "headers.Authorization" in js
    assert "`Bearer ${state.token}`" in js
    assert '"X-API-Key"' in js
    assert 'requestJson("/runs/latest")' in js
    assert 'requestJson("/runs/latest/audit-summary")' in js
    assert 'requestJson("/runs/latest/knowledge-graph")' in js
    assert 'requestJson("/runs/latest/findings")' in js
    assert 'requestJson("/public/runs/latest")' in js
    assert 'requestJson("/public/runs/latest/findings")' in js
    assert 'requestJson("/public/runs/latest/report-preview")' in js
    assert 'requestJson("/ui/workspace-contract/latest")' in js
    assert 'requestJson("/reviewer/pending-reviews")' in js
    assert 'requestJson(`/reviewer/runs/${encodeURIComponent(latestRun.run_id)}`)' in js
    assert 'function renderPlanHealth(config)' in js
    assert 'function renderExecutiveModes()' in js
    assert 'function renderExecutiveHero(run, citations, challenged)' in js
    assert 'function renderDriverDrillFidelity(selected, run, citations, challenged)' in js
    assert 'function renderLowerRailFidelity(run, citations, challenged)' in js
    assert 'function renderCashPulseAndOwed(run, citations, challenged)' in js
    assert 'function renderAssistantNarrative(run, citations, challenged)' in js
    assert 'function renderBoardPortal(run, citations, challenged)' in js
    assert 'function renderAgentsDiscovery(run, citations, challenged)' in js
    assert 'const DISPLAY_THEMES = [' in js
    assert 'const DISPLAY_DENSITIES = [' in js
    assert 'const MOVERS_VIEWS = [' in js
    assert 'data-exec-persona' in js
    assert 'data-persona-menu-item' in js
    assert 'data-board-state' in js
    assert 'data-driver-key' in js
    assert 'data-theme-mode' in js
    assert 'data-density-mode' in js
    assert 'data-movers-mode' in js
    assert 'Good morning, Khalid' in js
    assert 'assistantRole: "chief of staff"' in js
    assert 'function normalizedCitationSummary(run, rows)' in js
    assert 'function renderExecutiveSignalFoundation()' in js
    assert 'function executivePlanHealthConfig(fallback)' in js
    assert 'function publicationActionLabels(publication)' in js
    assert 'function strategySubstrate()' in js
    assert 'function renderScopeRibbon()' in js
    assert 'function rerenderExecutiveNarrative()' in js
    assert 'function humanizeNextAction(value)' in js
    assert 'Finance-derived signal only' in js
    assert 'Value-driver mapping will appear once a governed packet exists.' in js
    assert 'not a full enterprise strategy compiler' in js
    assert 'board pack ${humanizeToken(boardPack.status || "pending")}' in js
    assert 'Next valid action: ${humanizeNextAction(nextAction)}.' in js
    assert '"/data/evidence-preview" : "/public/data/evidence-preview"' in js
    assert 'requestJson(`/public/data/evidence-preview?run_id=${encodeURIComponent(publicRun?.run_id || "")}&finding_id=${encodeURIComponent(preferredFinding)}`)' in js
    assert 'requestJson("/qa"' in js
    assert "function selectFinding" in js
    assert "function loadReportPreview" in js
    assert "mode: \"deterministic\"" in js
    assert '<script id="strategyos-bootstrap"' not in html


def test_dashboard_shell_is_served_from_app_route_and_alias():
    client = TestClient(api_module.app)

    app_response = client.get("/app")
    alias_response = client.get("/dashboard")

    assert app_response.status_code == 200
    assert alias_response.status_code == 200
    assert "StrategyOS.live Governed Diagnostics Workspace" in app_response.text
    assert "StrategyOS.live Governed Diagnostics Workspace" in alias_response.text
    assert '<script id="strategyos-bootstrap"' in app_response.text
    assert '<script id="strategyos-bootstrap"' in alias_response.text


def test_dashboard_renders_chat_dashboard_shell():
    html = _dashboard_response()
    js = _static_app_js()

    assert "StrategyOS.live Governed Diagnostics Workspace" in html
    assert "Governed workbench" in html
    assert "Latest governed finance case" in html
    assert "Role-aware governed diagnostics workspace" in html
    assert "Role entry points" in html
    assert "Tenant admin / system lane" in html
    assert "BU / reviewer decision lane" in html
    assert "Run-control lane" in html
    assert "Tenant admin / system" in html
    assert "Company and portfolio switching" in html
    assert "Case → finding → evidence → report drill-down" in html
    assert 'id="company-switcher"' in html
    assert 'id="portfolio-switcher"' in html
    assert 'id="bu-domain-filters"' in html
    assert 'id="bu-surface-kpi-grid"' in html
    assert 'id="bu-workflow-list"' in html
    assert 'id="reviewer-queue-list"' in html
    assert 'id="operator-workflow-list"' in html
    assert 'id="system-workflow-compact"' in html
    assert 'id="system-publication-list"' in html
    assert 'id="system-surface-list"' in html
    assert 'id="drilldown-report-list"' in html
    assert 'id="parity-status-pill"' in html
    assert 'id="parity-executive-list"' in html
    assert 'id="parity-review-list"' in html
    assert 'id="parity-system-list"' in html
    assert 'id="publication-summary"' in html
    assert 'id="publication-payload-preview"' in html
    assert "Truth today: StrategyOS now exposes a bounded BU backend role for read-only governed review access." in html
    assert "Choose the truthful StrategyOS lane" in html
    assert "BU leaders now have a bounded backend role for governed queue and report read paths, while reviewer sign-off remains the approval gate." in html
    assert 'id="app-name"' in html
    assert 'id="workspace-subtitle"' in html
    assert 'id="workspace-headline"' in html
    assert 'id="workspace-note"' in html
    assert 'id="role-lane-pill"' in html
    assert 'id="run-pill"' in html
    assert 'id="ui-identity"' in html
    assert 'id="new-run-button"' in html
    assert 'id="system-drawer-button"' in html
    assert 'id="graph-drawer-button"' in html
    assert "Current role priorities" in html
    assert 'id="role-task-title"' in html
    assert 'id="role-task-note"' in html
    assert 'id="role-task-list"' in html
    assert "Evidence map" in html
    assert "Evidence map and sources" in html
    assert 'class="rail-nav"' not in html
    assert 'data-scroll-target="' not in html
    assert 'data-open-drawer="new-run"' in html
    assert 'data-open-drawer="system"' in html
    assert 'data-drawer-target="source-pack-section"' in html
    assert 'data-drawer-target="kg-panel"' in html
    assert 'querySelectorAll("[data-scroll-target]")' not in js
    assert 'querySelectorAll("[data-open-drawer]")' in js
    assert 'workspaceSubtitle: byId("workspace-subtitle")' in js
    assert 'function renderRoleFrame()' in js
    assert 'function renderRoleTasks()' in js
    assert 'function renderRoleSurfaces()' in js
    assert 'function renderSharedScope()' in js
    assert 'function syncSharedDrilldown(findingId)' in js
    assert 'function applyLaneHint()' in js
    assert 'tenant_admin' in js
    assert 'els.workspaceSubtitle.textContent = "BU / reviewer decision lane"' in js
    assert 'els.workspaceSubtitle.textContent = "Operator control plane"' in js
    assert 'els.workspaceSubtitle.textContent = "Tenant admin / system lane"' in js
    assert 'els.workspaceSubtitle.textContent = "Role-aware governed diagnostics workspace"' in js
    assert 'id="plan-health-status"' in html
    assert 'id="plan-health-tree"' in html
    assert 'id="publication-surface-list"' in html
    assert 'id="strategy-intent-pill"' in html
    assert 'id="strategy-intent-summary"' in html
    assert 'id="strategy-intent-next"' in html
    assert 'id="strategy-kpi-list"' in html
    assert 'id="value-driver-list"' in html
    assert 'id="strategy-reasoning-list"' in html
    assert 'id="publication-panel"' in html
    assert 'function renderPlanSignalPanel()' in js
    assert 'function renderStrategyPanel()' in js
    assert 'function renderParityPanel()' in js
    assert 'function renderPublicationGovernance()' in js
    assert 'function publicationActionLabels(publication)' in js
    assert 'publicationSummary: byId("publication-summary")' in js
    assert 'publicationPayloadPreview: byId("publication-payload-preview")' in js
    assert 'function reviewQueueRoute()' in js
    assert 'guarded("Pending reviews", requestJson(reviewQueueRoute()), { status: "empty", items: [] })' in js
    assert 'const meaningfulRows = rows.filter((row) => {' in js
    assert 'across ${formatCount(meaningfulRows.length)} trustworthy reviews' in js
    assert 'src="/static/app.js?v=ux-20260623a"' in html
    assert 'href="/static/styles.css?v=ux-20260623a"' in html
    assert 'function selectedStrategyView()' in js
    assert 'function currentTrendPayload()' in js
    assert 'function humanizeNextAction(value)' in js
    assert 'board pack ${humanizeToken(publication.board_pack?.status || "pending")}' in js


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
        assert executive.status_code == 200
        assert "StrategyOS.live Executive Cockpit" in executive.text
    finally:
        _restore_env(original)


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


def test_dashboard_renders_findings_worklist_hooks():
    html = _dashboard_response()
    js = _static_app_js()

    # Findings decision worklist panel + drill-down drawer (fix-list item 3).
    assert 'id="findings-panel"' in html
    assert "Findings worklist" in html
    assert 'id="findings-list"' in html
    assert 'id="findings-summary"' in html
    assert 'id="finding-drawer"' in html
    assert 'id="finding-detail-citations"' in html
    assert "Show in evidence map" in html
    assert 'requestJson("/runs/latest/findings")' in js
    assert "function renderFindings" in js
    assert "function openFindingDetail" in js
    # Plain-language labels, not raw pattern_type (fix-list item 7).
    assert "PATTERN_LABELS" in js
    assert "humanizePattern" in js


def test_dashboard_renders_trend_strip_hooks():
    html = _dashboard_response()
    js = _static_app_js()

    # CEO direction-of-travel trend strip (fix-list item 8).
    assert 'id="trend-strip"' in html
    assert "Direction of travel" in html
    assert 'id="trend-bars"' in html
    assert 'requestJson("/runs/history")' in js
    assert "function renderTrend" in js


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

    assert "Upload .zip" in html
    assert "Choose folder" in html
    assert "Pick a .zip or a folder above, then start analysis." in html
    assert "Check selected files" not in html
    assert "Advanced: use a server folder" not in html
    assert "POST /source-packs" not in html
    assert 'id="source-pack-upload-form"' in html
    assert 'id="source-pack-files"' in html
    assert 'id="source-pack-folder-files"' in html
    assert 'accept=".zip,application/zip,application/x-zip-compressed"' in html
    assert "webkitdirectory" in html
    assert 'id="source-pack-path-form"' in html
    assert 'id="source-pack-path"' in html
    assert 'id="source-pack-mappings"' in html
    assert 'id="source-pack-manifest-body"' in html
    assert 'id="source-pack-readiness"' in html
    assert 'requestMultipart("/source-packs"' in js
    assert "sourcePackFolderFiles" in js
    assert 'requestJson("/source-packs/from-path"' in js
    assert 'requestJson("/source-packs/validate"' in js
    assert 'requestJson("/source-packs/confirm-mapping"' in js


def test_dashboard_renders_system_drawer_data_health_and_artifact_hooks():
    html = _dashboard_response()
    js = _static_app_js()

    assert 'id="system-drawer"' in html
    assert "System lane" in html
    assert "Safe admin context" in html
    assert "Hosted workflow" in html
    assert "Connector catalog" in html
    assert "Shared diagnostics" in html
    assert "Managed data" in html
    assert "Relationship map" in html
    assert "Runtime health" in html
    assert "Artifact inspector" in html
    assert 'id="admin-context-panel"' in html
    assert 'id="admin-context-summary"' in html
    assert 'id="admin-context-kv"' in html
    assert 'id="admin-capabilities-kv"' in html
    assert 'id="admin-context-payload-preview"' in html
    assert 'id="system-workflow-panel"' in html
    assert 'id="system-workflow-summary"' in html
    assert 'id="system-workflow-list"' in html
    assert 'id="system-workflow-payload-preview"' in html
    assert 'id="connectors-panel"' in html
    assert 'id="connectors-summary"' in html
    assert 'id="connectors-list"' in html
    assert 'id="connectors-payload-preview"' in html
    assert 'id="data-summary"' in html
    assert 'id="data-counts-kv"' in html
    assert 'id="data-systems-kv"' in html
    assert 'id="data-payload-preview"' in html
    assert 'id="kg-panel"' in html
    assert 'id="data-panel"' in html
    assert 'id="vector-search-panel"' in html
    assert 'id="health-panel"' in html
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
    assert 'requestJson("/ingestion/connectors")' in js
    assert 'requestJson("/ui/workspace-contract/latest")' in js
    assert "sanitizeUiPayload({ live, ready, config, dependencies })" in js
    assert "internal identity boundary" in js
    assert "function renderAdminContext()" in js
    assert "function renderSystemWorkflow()" in js
    assert "function renderConnectors()" in js


def test_dashboard_renders_vector_search_utility_hooks():
    html = _dashboard_response()
    js = _static_app_js()

    assert "Search index utility" in html
    assert "GET /data/vector-search" not in html
    assert 'id="vector-search-form"' in html
    assert 'id="vector-search-query"' in html
    assert 'id="vector-search-type"' in html
    assert 'id="vector-search-pattern"' in html
    assert 'id="vector-search-vendor"' in html
    assert 'id="vector-search-confidence"' in html
    assert 'id="vector-search-source"' in html
    assert 'id="vector-search-finding"' in html
    assert 'id="vector-search-limit"' in html
    assert 'id="vector-search-results"' in html
    assert 'id="vector-search-evidence-preview"' in html
    assert 'id="vector-search-payload-preview"' in html
    assert "requestJson(`/data/vector-search?${params.toString()}`)" in js
    assert "data-open-evidence" in js
    assert "requestJson(href)" in js


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
        assert contract_payload["agents"]["discover"]["native"][0]["id"] == "native-evidence-qa"
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
            "/ui/workspace-contract/latest", headers={"X-API-Key": "executive"}
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
        assert payload["executive_modes"]["active_board_state"] == payload["board_portal"]["state"]
        assert payload["executive_modes"]["driver_focus"][0]["driver_key"] == "board_packet"
        assert any(item["persona_id"] == "cfo" for item in payload["executive_modes"]["personas"])
        assert any(item["persona_id"] == "logistics" for item in payload["executive_modes"]["personas"])
        assert payload["drilldown"]["default_case_id"] is None
        assert payload["drilldown"]["cash_pulse"]["basis"] == "governed_findings"
        assert payload["drilldown"]["gravity"]["prompts"]
        assert payload["interaction_contracts"]["latest_run"]["route"] == "/public/runs/latest"
        assert payload["agents"]["running"][0]["id"] == "evidence-qa"
        assert payload["agent_modules"]["summary"]["discoverable_count"] >= 4
        assert payload["tenant_admin_system"]["managed_data"]["reports"]["report_count"] == 2
        assert payload["tenant_admin_system"]["trend"]["truth_basis"] == "reconciled_governed_metrics"
        assert payload["role_actions"]["viewer_role"] == "executive"
        assert payload["strategy_substrate"]["kpi_tree"]["nodes"][0]["node_id"] == "value_capture"
        assert any(node["node_id"] == "publication_boundary" for node in payload["strategy_substrate"]["kpi_tree"]["nodes"])
        assert payload["strategy_substrate"]["value_drivers"][0]["driver_id"] == "cash_recovery"
        assert any(driver["driver_id"] == "board_pack_readiness_driver" for driver in payload["strategy_substrate"]["value_drivers"])
        assert any(item["portfolio_id"] == "release-readiness" for item in payload["strategy_substrate"]["portfolio_views"])
        assert any(item["reasoning_id"] == "hold-runtime-boundary" for item in payload["strategy_substrate"]["reasoning"])
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
