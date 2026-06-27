"""Phase 7 tests for twin identity and governance integration."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
from strategyos_mvp.config import load_config
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


def _phase7_env(tmp_path) -> dict[str, str]:
    return {
        "STRATEGYOS_API_AUTH_ENABLED": "true",
        "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": "true",
        "STRATEGYOS_TWINS_DATA_DIR": str(tmp_path / "app-data"),
    }


def test_unauthenticated_requests_are_blocked(tmp_path):
    original = _apply_env(_phase7_env(tmp_path))
    try:
        assert client.get("/twin/ceo").status_code == 401
        assert client.get("/twin/api/status/ceo").status_code == 401
    finally:
        _restore_env(original)


def test_authorized_role_access_is_allowed(tmp_path):
    original = _apply_env(_phase7_env(tmp_path))
    try:
        assert client.get("/twin/ceo", headers=_auth("executive")).status_code == 200
        assert client.get("/twin/cfo", headers=_auth("operator")).status_code == 200
        assert client.get("/twin/gm", headers=_auth("bu")).status_code == 200
        assert client.get("/twin/api/status/cfo", headers=_auth("reviewer")).status_code == 200
    finally:
        _restore_env(original)


def test_wrong_role_access_is_denied(tmp_path):
    original = _apply_env(_phase7_env(tmp_path))
    try:
        assert client.get("/twin/ceo", headers=_auth("bu")).status_code == 403
        assert client.get("/twin/api/status/cfo", headers=_auth("executive")).status_code == 403
        assert client.post(
            "/twin/api/approve/cfo",
            headers=_auth("bu"),
            json={"item_id": "bud-001", "title": "Budget 1"},
        ).status_code == 403
    finally:
        _restore_env(original)


def test_approval_persistence(tmp_path):
    original = _apply_env(_phase7_env(tmp_path))
    try:
        response = client.post(
            "/twin/api/approve/cfo",
            headers=_auth("operator"),
            json={
                "item_id": "bud-900",
                "title": "Q4 capex release",
                "rationale": "Within approved finance envelope.",
            },
        )
        assert response.status_code == 200
        repositories = build_repositories(tmp_path / "app-data")
        decisions = repositories.governance.list_decisions("cfo")
        saved = next(item for item in decisions if item["item_id"] == "bud-900")
        assert saved["status"] == "approved"
        assert saved["rationale"] == "Within approved finance envelope."
        assert saved["actor_role"] == "operator"
        assert response.json()["governance"]["approval_trail"][0]["item_id"] == "bud-900"
    finally:
        _restore_env(original)


def test_reject_persistence_with_rationale(tmp_path):
    original = _apply_env(_phase7_env(tmp_path))
    try:
        response = client.post(
            "/twin/api/reject/ceo",
            headers=_auth("executive"),
            json={
                "item_id": "dec-404",
                "title": "Acquisition approval",
                "rationale": "Insufficient downside scenario evidence.",
            },
        )
        assert response.status_code == 200
        repositories = build_repositories(tmp_path / "app-data")
        decisions = repositories.governance.list_decisions("ceo")
        saved = next(item for item in decisions if item["item_id"] == "dec-404")
        assert saved["status"] == "rejected"
        assert saved["reviewer_notes"] == "Insufficient downside scenario evidence."
        assert response.json()["record"]["actor_subject"] == "demo-role:executive"
    finally:
        _restore_env(original)


def test_redirect_and_escalation_audit_persistence(tmp_path):
    original = _apply_env(_phase7_env(tmp_path))
    try:
        redirect_response = client.post(
            "/twin/api/redirect/gm",
            headers=_auth("bu"),
            json={
                "item_id": "inv-77",
                "title": "Demand variance review",
                "target_role": "analyst",
                "reason": "Need evidence refresh before sign-off.",
            },
        )
        escalate_response = client.post(
            "/twin/api/escalate/gm",
            headers=_auth("bu"),
            json={
                "item_id": "inv-77",
                "title": "Demand variance review",
                "reason": "Blocked on finance decision.",
            },
        )
        assert redirect_response.status_code == 200
        assert escalate_response.status_code == 200

        repositories = build_repositories(tmp_path / "app-data")
        routing = repositories.governance.list_routing_events("group_manager")
        assert len([item for item in routing if item["item_id"] == "inv-77"]) == 2
        redirect_saved = next(item for item in routing if item["event_type"] == "redirect" and item["item_id"] == "inv-77")
        escalate_saved = next(item for item in routing if item["event_type"] == "escalation" and item["item_id"] == "inv-77")
        assert redirect_saved["target_role"] == "analyst"
        assert escalate_saved["target_role"] == "cfo"
        assert redirect_saved["actor_role"] == "bu"

        history_response = client.get("/twin/api/history/gm", headers=_auth("bu"))
        history = history_response.json()["governance"]["history"]
        assert any(item["result"] == "REDIRECTED" for item in history)
        assert any(item["result"] == "ESCALATED" for item in history)
    finally:
        _restore_env(original)


def test_phase0_to_phase6_contracts_still_work_with_auth(tmp_path):
    original = _apply_env(_phase7_env(tmp_path))
    try:
        investigate = client.post(
            "/twin/api/investigate/ceo?query=Why+is+margin+down%3F",
            headers=_auth("executive"),
        )
        status = client.get("/twin/api/status/ceo", headers=_auth("executive"))
        inbox = client.get("/twin/api/inbox/ceo", headers=_auth("executive"))
        dashboard = client.get("/twin/ceo", headers=_auth("executive"))

        assert investigate.status_code == 200
        assert status.status_code == 200
        assert inbox.status_code == 200
        assert dashboard.status_code == 200
        assert set(["role", "display_name", "status", "cycle_count", "active_investigations", "pending_requests"]).issubset(status.json())
        assert "messages" in inbox.json()
        assert "governance" in status.json()
    finally:
        _restore_env(original)
