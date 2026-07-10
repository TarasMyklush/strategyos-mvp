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
