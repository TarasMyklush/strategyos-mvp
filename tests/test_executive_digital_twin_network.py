from pathlib import Path

from strategyos_mvp import api as api_module
from strategyos_mvp.scenario_parser import parse_scenario
from strategyos_mvp.twins.store import build_repositories


def test_agents_surface_reads_persistent_digital_twin_runtime(tmp_path, monkeypatch):
    repositories = build_repositories(tmp_path / "twins")
    repositories.states.save(
        "ceo",
        {
            "twin_id": "ceo-1",
            "role": "ceo",
            "last_wake_at": "2026-07-14T08:00:00+00:00",
            "cycle_count": 3,
            "active_investigations": {},
            "pending_requests": {},
        },
    )
    repositories.investigations.save(
        "cfo",
        {
            "id": "inv-1",
            "title": "Reconcile H1 EBITDA bridge",
            "status": "open",
        },
    )
    repositories.requests.save(
        "cfo",
        {
            "request_message_id": "req-1",
            "responder_role": "ceo",
            "subject": "Confirm aligned H1 budget",
            "status": "pending",
            "updated_at": "2026-07-14T08:05:00+00:00",
        },
    )
    repositories.requests.save(
        "ceo",
        {
            "request_message_id": "req-resolved",
            "responder_role": "cfo",
            "subject": "Resolved board narrative request",
            "status": "fulfilled",
            "updated_at": "2026-07-14T08:06:00+00:00",
        },
    )
    repositories.requests.save(
        "group_manager",
        {
            "request_message_id": "req-expired",
            "responder_role": "analyst",
            "subject": "Expired operating metric request",
            "status": "expired",
            "updated_at": "2026-07-14T08:07:00+00:00",
        },
    )
    repositories.governance.save_routing_event(
        {
            "event_id": "route-1",
            "event_type": "handoff",
            "source_role": "cfo",
            "target_role": "ceo",
            "title": "EBITDA evidence ready",
            "timestamp": "2026-07-14T08:10:00+00:00",
        }
    )
    monkeypatch.setattr(api_module, "build_app_repositories", lambda: repositories)

    payload = api_module._agents_surface_payload(
        {"run_id": "run-1"},
        {"role": "executive", "authenticated": True},
    )

    assert payload["contract_version"] == "digital_twin_network.v1"
    assert [item["role"] for item in payload["digital_twins"]] == [
        "ceo",
        "cfo",
        "group_manager",
        "strategy",
        "analyst",
        "reviewer",
    ]
    cfo = next(item for item in payload["digital_twins"] if item["role"] == "cfo")
    assert cfo["assistant_name"] == "Atlas"
    assert cfo["status"] == "active"
    assert cfo["active_investigation_count"] == 1
    assert cfo["pending_request_count"] == 1
    assert cfo["current_activity"] == "Reconcile H1 EBITDA bridge"
    assert cfo["route"] is None  # CEO may inspect the network, not enter CFO-only controls.
    assert payload["collaboration"]["open_handoff_count"] == 1
    assert payload["collaboration"]["resolved_handoff_count"] == 1
    assert payload["collaboration"]["exception_handoff_count"] == 1
    assert payload["collaboration"]["executive_attention_count"] == 0
    assert payload["collaboration"]["routing_gap_count"] == 0
    assert "None is flagged for executive attention" in payload["collaboration"]["summary"]
    assert payload["collaboration"]["recent_events"][0]["subject"] == "EBITDA evidence ready"
    assert payload["running"] == []  # Workflow modules are never relabelled as twins.


def test_executive_ui_distinguishes_assistants_from_functions_and_status_panel():
    root = Path(api_module.STATIC_DIR)
    js = (root / "executive.js").read_text(encoding="utf-8")
    css = (root / "executive.css").read_text(encoding="utf-8")
    html = (root / "executive.html").read_text(encoding="utf-8")

    assert '<h2 class="section-title" id="agents-heading">AI assistants</h2>' in html
    assert "AI assistants by executive role" in js
    assert "Specialist work such as analysis or audit is tracked separately under Functions." in js
    assert 'data-view-target="functions"' in html
    assert 'id="subtools-panel" hidden' in html
    assert "automationCard.hidden = true" in js
    assert "System workflows — not digital twins" not in js
    assert ".agents-col-head > div" in css
    assert ".agents-col-head .ach-title" in css
    assert ".agents-col-head .ach-hint" in css
    assert "text-align: left" in css
    assert "This view shows coordination between AI assistants" in js
    assert "Assistant collaboration" in js
    assert "Who each assistant represents" in js
    assert "executive twins" not in js.lower()
    assert 'String(getLeadershipTeam().length) + " assistants"' in js
    assert "scrubExecutiveTechnicalLanguage(firstDefined(item.authority" in js
    assert "in progress" in js
    assert "need your attention" in js
    assert "legacy request" not in js
    assert "quarantined" not in js
    assert "system-owner remediation" not in js
    assert "Governed runtime active" not in js
    assert "queued messages" not in js
    assert "No inter-twin handoff has been recorded yet" not in js
    assert "agents.digital_twins" in js
    assert 'reviewGate\n      ? "Review required"' in js
    assert 'var statusSignal = reviewGate' in js
    assert '"Business view ready"' in js
    assert ".hero-status__signal.is-attention" in css
    assert ".score-ring" not in css
    assert "--display: var(--serif)" in css


def test_governed_ebitda_answer_uses_same_finance_components_as_ceo_card():
    context = {
        "summary": {
            "reporting_period": "H1 2026",
            "finance_kpi": {
                "reporting_period_key": "H1 2026",
                "reporting_currency": "SAR",
                "components": {
                    "revenue_actual": 1000,
                    "cogs_actual": 300,
                    "operating_cost_actual": 140,
                    "ebitda_actual": 560,
                    "revenue_plan": None,
                    "ebitda_plan": None,
                },
            },
        },
    }

    result = parse_scenario("Explain the current EBITDA margin and bridge", context)

    assert result.scenario_id == "governed_ebitda_baseline"
    assert "56.0%" in result.answer
    assert "SAR 560" in result.answer
    assert "have not shown a plan variance" in result.answer
    assert result.basis == "Read from the same governed finance contract used by the CEO KPI card."


def test_hermes_ai_team_answer_uses_same_persistent_runtime(tmp_path, monkeypatch):
    repositories = build_repositories(tmp_path / "twins")
    repositories.states.save(
        "ceo",
        {
            "twin_id": "ceo-1",
            "role": "ceo",
            "last_wake_at": "2026-07-14T08:00:00+00:00",
            "cycle_count": 2,
        },
    )
    repositories.requests.save(
        "ceo",
        {
            "request_message_id": "req-1",
            "subject": "Data request: board_narrative — unknown_node",
            "status": "pending",
        },
    )
    monkeypatch.setattr(api_module, "build_app_repositories", lambda: repositories)

    result = api_module._resolve_digital_twin_status(
        "What is my AI team doing now, and which Digital Twin needs executive attention?",
        summary={"run_id": "run-1"},
        role="executive",
        public_safe=False,
    )

    assert result is not None
    assert result["matched"] is True
    assert result["answered_by"] == "digital_twin_runtime"
    assert "4 configured AI assistants" in result["answer"]
    assert [item["role"] for item in result["digital_twin_network"]["digital_twins"]] == [
        "ceo",
        "cfo",
        "group_manager",
        "strategy",
    ]
    assert "No AI assistant is currently flagged for executive attention" in result["answer"]
    assert "unknown_node" not in result["answer"]
    assert result["digital_twin_network"]["contract_version"] == "digital_twin_network.v1"


def test_hermes_specific_twin_answer_is_role_specific(tmp_path, monkeypatch):
    repositories = build_repositories(tmp_path / "twins")
    repositories.investigations.save(
        "cfo",
        {
            "id": "inv-1",
            "title": "Reconcile H1 EBITDA bridge",
            "status": "open",
        },
    )
    monkeypatch.setattr(api_module, "build_app_repositories", lambda: repositories)

    result = api_module._resolve_digital_twin_status(
        "What is Atlas doing now?",
        summary={"run_id": "run-1"},
        role="executive",
        public_safe=False,
    )

    assert result is not None
    assert "Atlas (CFO Assistant)" in result["answer"]
    assert "Reconcile H1 EBITDA bridge" in result["answer"]
    assert "not currently flagged for executive intervention" in result["answer"]
