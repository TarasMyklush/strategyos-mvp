from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
import strategyos_mvp.twins.api as twins_api
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


def _collect_strings(payload):
    if isinstance(payload, dict):
        values = []
        for item in payload.values():
            values.extend(_collect_strings(item))
        return values
    if isinstance(payload, list):
        values = []
        for item in payload:
            values.extend(_collect_strings(item))
        return values
    if isinstance(payload, str):
        return [payload]
    return []


_FIXTURE_MARKERS = (
    "Illustrative demo narrative",
    "SAR 2.09B",
    "SAR 8.6M",
    "Mizan Group",
    "Khalid",
)


def test_public_latest_run_current_payload_has_no_illustrative_fixture_markers(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(
            api_module,
            "_latest_summary",
            lambda: {
                "run_id": "run-governed",
                "run_dir": "/tmp/run-governed",
                "approval_status": "approved",
                "current_stage": "awaiting_review",
                "requires_human_review": False,
            },
        )
        monkeypatch.setattr(
            api_module,
            "_load_knowledge_graph_artifact",
            lambda summary: (None, {"nodes": [], "edges": []}),
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        payload = TestClient(api_module.app).get("/public/runs/latest").json()
        all_strings = "\n".join(_collect_strings(payload))

        assert payload["status"] == "ok"
        assert payload.get("assistant_public_context", {}).get("is_illustrative") is not True
        assert all(marker not in all_strings for marker in _FIXTURE_MARKERS)
    finally:
        _restore_env(original)


def test_public_latest_run_missing_summary_reports_missing_without_demo_payload(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: None)

        payload = TestClient(api_module.app).get("/public/runs/latest").json()
        all_strings = "\n".join(_collect_strings(payload))

        assert payload == {"status": "missing", "public_safe": True, "run_id": api_module.ANONYMOUS_PUBLIC_RUN_ID}
        assert all(marker not in all_strings for marker in _FIXTURE_MARKERS)
    finally:
        _restore_env(original)


def test_executive_static_js_does_not_reference_design_fixture_or_prefer_design_drivers():
    js = TestClient(api_module.app).get("/static/executive.js").text

    assert "window.STRATEGYOS_EXECUTIVE_DESIGN" not in js
    assert "designDrivers.length ? designDrivers : packetDrivers" not in js


def test_executive_js_has_no_hardcoded_identity_fixtures():
    """The greeting and avatar initials must come from the authenticated
    session (/ui/session display_name), never from the fixture person that
    only exists in the demo storyline."""
    js = TestClient(api_module.app).get("/static/executive.js").text

    assert "Khalid" not in js
    assert '"KA"' not in js
    assert "sessionDisplayName" in js


def test_executive_shell_has_no_hardcoded_org_identity_or_legacy_namespace():
    client = TestClient(api_module.app)
    html = client.get("/app").text
    js = client.get("/static/executive.js").text

    for marker in ("Mizan", "Khalid", ">KA<", "window.MIZAN", "MIZAN_X"):
        assert marker not in html
        assert marker not in js
    assert "tenantDisplayName" in js
    assert "window.STRATEGYOS_X" in js


def test_executive_design_data_fixture_file_is_deleted():
    fixture_path = Path(api_module.__file__).parent / "static" / "executive_design_data.js"
    assert not fixture_path.exists(), (
        "executive_design_data.js must stay deleted -- the executive surface "
        "must not ship a client-side design fixture"
    )


_FIXTURE_THREAD_MARKERS = (
    "EUR hedge",
    "Thursday board readiness",
    "e-Pharmacy",
    "Am I on track for the board",
)


def test_chat_starter_threads_derive_from_governed_findings_not_fixture_narrative(monkeypatch):
    """Chat starter threads used to be seeded from the design fixture's
    narrative prompts ('Model a 60% EUR hedge...'). They must derive from the
    latest governed run's actual findings, and disappear when there are none."""
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(
            api_module,
            "_latest_summary",
            lambda: {
                "run_id": "run-governed",
                "run_dir": "/tmp/run-governed",
                "approval_status": "approved",
                "current_stage": "awaiting_review",
                "requires_human_review": False,
            },
        )
        monkeypatch.setattr(
            api_module,
            "_load_knowledge_graph_artifact",
            lambda summary: (
                None,
                {
                    "nodes": [
                        {
                            "id": "Finding:F-001",
                            "label": "Finding",
                            "properties": {
                                "finding_id": "F-001",
                                "title": "Duplicate payment for INV-9001",
                                "pattern_type": "duplicate_payment",
                                "recoverable_sar": 1000.0,
                            },
                        }
                    ],
                    "edges": [],
                },
            ),
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        payload = TestClient(api_module.app).get("/public/runs/latest").json()
        threads = (payload.get("chat") or {}).get("threads") or []
        starter_threads = [t for t in threads if t.get("kind") == "starter_prompt"]
        thread_text = "\n".join(_collect_strings(payload.get("chat") or {}))

        assert all(marker not in thread_text for marker in _FIXTURE_THREAD_MARKERS), (
            f"chat threads still carry fixture narrative: {thread_text!r}"
        )
        assert starter_threads, "expected starter threads derived from the run's findings"
        # One thread per finding, keyed finding-N. On the public-safe surface
        # the scrubber replaces raw titles with board-safe labels -- that is
        # governed data (derived + scrubbed), not fixture narrative.
        assert len(starter_threads) == 1
        assert starter_threads[0].get("thread_id", "").endswith("finding-1"), (
            f"starter threads must derive from the governed findings, got: {starter_threads!r}"
        )
        assert (payload.get("chat") or {}).get("starter_prompts") == [
            starter_threads[0]["starter_prompt"]
        ]
    finally:
        _restore_env(original)


def test_chat_starter_threads_absent_when_run_has_no_findings(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(
            api_module,
            "_latest_summary",
            lambda: {
                "run_id": "run-governed",
                "run_dir": "/tmp/run-governed",
                "approval_status": "approved",
                "current_stage": "awaiting_review",
                "requires_human_review": False,
            },
        )
        monkeypatch.setattr(
            api_module,
            "_load_knowledge_graph_artifact",
            lambda summary: (None, {"nodes": [], "edges": []}),
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        payload = TestClient(api_module.app).get("/public/runs/latest").json()
        threads = (payload.get("chat") or {}).get("threads") or []
        starter_threads = [t for t in threads if t.get("kind") == "starter_prompt"]

        assert starter_threads == [], (
            "with no findings in the governed run there is nothing to suggest -- "
            f"fixture-narrative starter threads must not reappear, got: {starter_threads!r}"
        )
        assert (payload.get("chat") or {}).get("starter_prompts") == []
    finally:
        _restore_env(original)


def test_executive_modes_personas_carry_no_fixture_narrative_quotes(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(
            api_module,
            "_latest_summary",
            lambda: {
                "run_id": "run-governed",
                "run_dir": "/tmp/run-governed",
                "approval_status": "approved",
                "current_stage": "awaiting_review",
                "requires_human_review": False,
            },
        )
        monkeypatch.setattr(
            api_module,
            "_load_knowledge_graph_artifact",
            lambda summary: (None, {"nodes": [], "edges": []}),
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        payload = TestClient(api_module.app).get("/public/runs/latest").json()
        personas = (payload.get("executive_modes") or {}).get("personas") or []

        assert personas, "expected persona metadata in executive_modes"
        for item in personas:
            assert not item.get("quote"), (
                f"persona {item.get('persona_id')!r} still carries a fixture narrative quote: {item.get('quote')!r}"
            )
            assert not item.get("quoted_by")
            assert all(
                person not in str(item.get("detail") or "")
                for person in ("Khalid", "Sara", "Lina", "Yusuf")
            )
    finally:
        _restore_env(original)


def test_governed_public_assistant_refuses_missing_fixture_scenario_values(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(
            api_module,
            "_latest_summary",
            lambda: {
                "run_id": "run-governed",
                "run_dir": "/tmp/run-governed",
                "approval_status": "approved",
                "current_stage": "awaiting_review",
                "requires_human_review": False,
            },
        )
        monkeypatch.setattr(
            api_module,
            "_load_knowledge_graph_artifact",
            lambda summary: (None, {"nodes": [], "edges": []}),
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        response = TestClient(api_module.app).post(
            "/assistant/chat",
            json={
                "question": "Tell me the downside of the EUR hedge",
                "persona": "ceo",
                "mode": "deterministic",
            },
        )
        payload = response.json()
        answer_text = "\n".join(
            _collect_strings(
                {
                    "answer": payload.get("answer"),
                    "basis": payload.get("basis"),
                    "suggestions": payload.get("suggestions"),
                }
            )
        )

        assert response.status_code == 200
        assert "does not expose a quantified currency or hedge scenario" in payload["answer"]
        assert all(marker not in answer_text for marker in _FIXTURE_THREAD_MARKERS)
        assert "19.2%" not in answer_text
        assert "SAR 9k" not in answer_text
    finally:
        _restore_env(original)


def test_client_migrates_retired_fixture_threads_and_never_falls_back_to_design_threads():
    js = TestClient(api_module.app).get("/static/executive.js").text

    assert "function isRetiredFixtureThread" in js
    assert "if (isRetiredFixtureThread(key, persisted[key])) return;" in js
    assert "var seededThreads = safeArray(chat.threads);" in js
    assert "safeArray(blueprint.threads).map" not in js


def test_executive_static_js_uses_authenticated_governed_route_not_public_demo_route():
    js = TestClient(api_module.app).get("/static/executive.js").text

    assert 'function latestRunRouteForSession(session)' in js
    assert 'if (session && session.authenticated) return "/runs/latest";' in js
    assert 'fetchJson("/public/runs/latest" + buildQuery(params))' not in js


def test_plan_page_is_not_bootstrapped_from_static_plan_fixture():
    html = TestClient(api_module.app).get("/plan").text

    assert "/static/plan_data.js" not in html
    assert "window.STRATEGYOS_PLAN" not in html
    assert "/api/plan/latest" in html


def test_plan_api_reports_unavailable_when_database_is_not_configured(monkeypatch):
    monkeypatch.setattr(api_module, "_latest_summary", lambda: None)
    monkeypatch.setattr(
        api_module,
        "data_management_status",
        lambda run_id=None: {"status": "skipped", "reason": "DATABASE_URL is not configured."},
    )

    payload = TestClient(api_module.app).get("/api/plan/latest").json()

    assert payload["criticalBlockers"][0]["id"] == "DB-UNAVAILABLE"
    assert "DATABASE_URL is not configured" in payload["criticalBlockers"][0]["detail"]
    assert payload["hostedVerificationState"]["checks"][0]["result"] == "fail"


def test_authenticated_latest_run_uses_actual_current_run_payload_without_demo_markers(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "true", "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": "true"})
    try:
        monkeypatch.setattr(
            api_module,
            "_latest_summary",
            lambda: {
                "run_id": "run-auth-001",
                "run_dir": "/tmp/run-auth-001",
                "approval_status": "approved",
                "current_stage": "writer",
                "requires_human_review": False,
                "tenant_context": {"tenant_id": "tenant-live", "tenant_name": "Tenant Live", "workspace_id": "tenant-live"},
            },
        )
        monkeypatch.setattr(
            api_module,
            "_load_knowledge_graph_artifact",
            lambda summary: (None, {"nodes": [], "edges": []}),
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        payload = TestClient(api_module.app).get("/runs/latest", headers={"X-API-Key": "executive"}).json()
        all_strings = "\n".join(_collect_strings(payload))

        assert payload["status"] == "ok"
        assert payload["run_id"] == "run-auth-001"
        assert payload["data_source"] == "actual"
        assert payload["data_source_status"] == "current_run"
        assert payload["run_source"] == "current_run"
        assert payload.get("public_safe") is not True
        assert payload.get("assistant_public_context", {}).get("is_illustrative") is not True
        assert all(marker not in all_strings for marker in _FIXTURE_MARKERS)
    finally:
        _restore_env(original)


def test_authenticated_latest_run_missing_summary_reports_missing_without_public_demo_flag(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "true", "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": "true"})
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: None)

        payload = TestClient(api_module.app).get("/runs/latest", headers={"X-API-Key": "executive"}).json()

        assert payload == {
            "status": "missing",
            "data_source": "unavailable",
            "data_source_status": "missing",
            "run_source": "current_run",
        }
    finally:
        _restore_env(original)


def test_authenticated_twin_kpis_report_missing_source_status_without_demo_markers(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "true", "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": "true"})
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: None)

        payload = TestClient(api_module.app).get("/twin/api/kpis/ceo", headers={"X-API-Key": "executive"}).json()
        all_strings = "\n".join(_collect_strings(payload))

        assert payload["data_source"] == "twin_repository_fallback"
        assert payload["source_status"] == "missing"
        assert payload["bounded_fallback"] is True
        assert payload["run_context"]["available"] is False
        assert all(marker not in all_strings for marker in _FIXTURE_MARKERS)
    finally:
        _restore_env(original)


def test_twin_repository_bootstrap_does_not_seed_demo_truth(monkeypatch, tmp_path):
    class _FailingKpis:
        def ensure_seeded(self, seed_data):
            pytest.fail("Twin repository bootstrap must not seed KPI_TREE values as production truth.")

    class _FailingGovernance:
        def seed_demo_history(self, role):
            pytest.fail("Twin repository bootstrap must not seed demo governance history.")

    repositories = SimpleNamespace(
        kpis=_FailingKpis(),
        governance=_FailingGovernance(),
    )
    monkeypatch.setattr(twins_api, "build_app_repositories", lambda: repositories)

    result = twins_api._get_repositories()

    assert result is repositories


def test_plan_static_fixture_module_is_not_present_as_truth_source():
    plan_data_path = Path(api_module.STATIC_DIR) / "plan_data.js"
    text = plan_data_path.read_text(encoding="utf-8")

    assert "window.STRATEGYOS_PLAN" not in text
