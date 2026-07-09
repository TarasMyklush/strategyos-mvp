"""Phase 10 tests for production hardening, rollout controls, and regression coverage."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
from strategyos_mvp.config import load_config
from strategyos_mvp.twins.execution import submit_event_execution, submit_scheduled_cycle
from strategyos_mvp.twins.store import build_repositories


client = TestClient(api_module.app)


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


def _auth(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _phase10_env(tmp_path) -> dict[str, str]:
    return {
        "STRATEGYOS_API_AUTH_ENABLED": "true",
        "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": "true",
        "STRATEGYOS_TWINS_DATA_DIR": str(tmp_path / "app-data"),
        "STRATEGYOS_TWINS_ENABLED": "true",
        "STRATEGYOS_TWINS_MUTATIONS_ENABLED": "true",
        "STRATEGYOS_TWINS_SCHEDULER_ENABLED": "true",
        "STRATEGYOS_TWINS_EXPOSE_REASONING_DIAGNOSTICS": "false",
    }


def test_authenticated_dashboard_and_investigate_flow_is_stable_and_idempotent(tmp_path):
    original = _apply_env(_phase10_env(tmp_path))
    try:
        dashboard = client.get("/twin/ceo", headers=_auth("executive"))
        first = client.post(
            "/twin/api/investigate/ceo?query=Why+is+margin+down%3F",
            headers={**_auth("executive"), "Idempotency-Key": "investigate-1"},
        )
        second = client.post(
            "/twin/api/investigate/ceo?query=Why+is+margin+down%3F",
            headers={**_auth("executive"), "Idempotency-Key": "investigate-1"},
        )

        assert dashboard.status_code == 200
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["idempotent_replay"] is True
        assert second.json()["summary"]["cycle_id"] == first.json()["summary"]["cycle_id"]
    finally:
        _restore_env(original)


def test_governance_path_is_idempotent_and_redacts_sensitive_subjects_for_non_admin(tmp_path):
    original = _apply_env(_phase10_env(tmp_path))
    try:
        first = client.post(
            "/twin/api/approve/ceo",
            headers={**_auth("executive"), "Idempotency-Key": "approve-1"},
            json={"item_id": "dec-1000", "title": "Board packet", "rationale": "Ship it."},
        )
        second = client.post(
            "/twin/api/approve/ceo",
            headers={**_auth("executive"), "Idempotency-Key": "approve-1"},
            json={"item_id": "dec-1000", "title": "Board packet", "rationale": "Ship it."},
        )
        history_exec = client.get("/twin/api/history/ceo", headers=_auth("executive"))
        history_admin = client.get("/twin/api/history/ceo", headers=_auth("tenant_admin"))

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["idempotent_replay"] is True
        assert second.json()["record"]["actor_subject"] == "demo-role:executive"
        exec_item = history_exec.json()["governance"]["approval_trail"][0]
        admin_item = history_admin.json()["governance"]["approval_trail"][0]
        assert "actor_subject" not in exec_item
        assert admin_item["actor_subject"] == "demo-role:executive"
    finally:
        _restore_env(original)


def test_scheduler_and_event_execution_are_retry_safe(tmp_path):
    original = _apply_env(_phase10_env(tmp_path))
    try:
        repositories = build_repositories(tmp_path / "app-data")
        scheduled_first = submit_scheduled_cycle(
            "daily",
            repositories=repositories,
            config=load_config(),
            idempotency_key="sched-1",
        )
        scheduled_second = submit_scheduled_cycle(
            "daily",
            repositories=repositories,
            config=load_config(),
            idempotency_key="sched-1",
        )
        event_first = submit_event_execution(
            repositories=repositories,
            config=load_config(),
            idempotency_key="event-1",
        )
        event_second = submit_event_execution(
            repositories=repositories,
            config=load_config(),
            idempotency_key="event-1",
        )

        assert scheduled_first["status"] == "completed"
        assert scheduled_second["idempotent_replay"] is True
        assert scheduled_first["execution_id"] == scheduled_second["execution_id"]
        assert event_first["status"] == "completed"
        assert event_second["idempotent_replay"] is True
        assert event_first["execution_id"] == event_second["execution_id"]
    finally:
        _restore_env(original)


def test_cycle_endpoint_requires_diagnostic_role(tmp_path):
    original = _apply_env(_phase10_env(tmp_path))
    try:
        forbidden = client.post(
            "/twin/api/cycles/daily_standup",
            headers=_auth("executive"),
        )
        assert forbidden.status_code == 403
    finally:
        _restore_env(original)


def test_cycle_endpoint_runs_a_real_cycle_synchronously_and_is_idempotent(tmp_path):
    original = _apply_env(_phase10_env(tmp_path))
    try:
        first = client.post(
            "/twin/api/cycles/daily_standup",
            headers={**_auth("tenant_admin"), "Idempotency-Key": "cycle-http-1"},
        )
        second = client.post(
            "/twin/api/cycles/daily_standup",
            headers={**_auth("tenant_admin"), "Idempotency-Key": "cycle-http-1"},
        )

        assert first.status_code == 200
        assert first.json()["status"] == "completed"
        assert second.json()["idempotent_replay"] is True
        assert first.json()["execution_id"] == second.json()["execution_id"]
    finally:
        _restore_env(original)


def test_cycle_endpoint_accepts_short_aliases_and_rejects_unknown_types(tmp_path):
    original = _apply_env(_phase10_env(tmp_path))
    try:
        weekly = client.post(
            "/twin/api/cycles/weekly",
            headers={**_auth("tenant_admin"), "Idempotency-Key": "cycle-http-weekly"},
        )
        bad = client.post(
            "/twin/api/cycles/not_a_real_cycle",
            headers=_auth("tenant_admin"),
        )

        assert weekly.status_code == 200
        assert weekly.json()["status"] == "completed"
        assert bad.status_code == 400
    finally:
        _restore_env(original)


def test_cycle_endpoint_returns_503_when_twins_disabled(tmp_path):
    env = _phase10_env(tmp_path)
    env["STRATEGYOS_TWINS_ENABLED"] = "false"
    original = _apply_env(env)
    try:
        response = client.post(
            "/twin/api/cycles/daily_standup",
            headers=_auth("tenant_admin"),
        )
        assert response.status_code == 503
    finally:
        _restore_env(original)


def test_observability_surfaces_twin_runtime_health(tmp_path):
    original = _apply_env(_phase10_env(tmp_path))
    try:
        health = client.get("/twin/api/health", headers=_auth("tenant_admin"))
        config = client.get("/health/config", headers=_auth("tenant_admin"))

        assert health.status_code == 200
        assert health.json()["feature_flags"]["twins_enabled"] is True
        assert "diagnostics" in health.json()
        assert config.status_code == 200
        assert config.json()["twins"]["feature_flags"]["twins_scheduler_enabled"] is True
    finally:
        _restore_env(original)


def test_rollout_controls_can_disable_twins_mutations_and_scheduler(tmp_path):
    env = _phase10_env(tmp_path)
    env.update(
        {
            "STRATEGYOS_TWINS_MUTATIONS_ENABLED": "false",
            "STRATEGYOS_TWINS_SCHEDULER_ENABLED": "false",
        }
    )
    original = _apply_env(env)
    try:
        investigate = client.post(
            "/twin/api/investigate/ceo?query=blocked",
            headers=_auth("executive"),
        )
        approve = client.post(
            "/twin/api/approve/ceo",
            headers=_auth("executive"),
            json={"item_id": "dec-2000", "title": "Blocked"},
        )
        scheduled = submit_scheduled_cycle(
            "daily",
            repositories=build_repositories(tmp_path / "app-data"),
            config=load_config(),
        )

        assert investigate.status_code == 503
        assert approve.status_code == 503
        assert scheduled["status"] == "disabled"
    finally:
        _restore_env(original)


def test_phase0_to_phase9_regression_paths_still_hold(tmp_path):
    original = _apply_env(_phase10_env(tmp_path))
    try:
        status = client.get("/twin/api/status/ceo", headers=_auth("executive"))
        inbox = client.get("/twin/api/inbox/ceo", headers=_auth("executive"))
        investigate = client.post(
            "/twin/api/investigate/ceo?query=Why+is+margin+down%3F",
            headers=_auth("executive"),
        )
        dashboard = client.get("/twin/ceo", headers=_auth("executive"))

        assert status.status_code == 200
        assert inbox.status_code == 200
        assert investigate.status_code == 200
        assert dashboard.status_code == 200
        assert "governance" in status.json()
        assert "reasoning_trace_ids" in investigate.json()["summary"]
    finally:
        _restore_env(original)
