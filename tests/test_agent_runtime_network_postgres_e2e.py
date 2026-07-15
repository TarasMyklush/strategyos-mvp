"""Integration tests for PR5's /api/v1/agents, /api/v1/agent-network,
/api/v1/agent-approvals, and /api/v1/agent-events/stream against real
Postgres, exercised through FastAPI's TestClient.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import strategyos_mvp.agent_runtime.api as agent_api_module
import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
import strategyos_mvp.state_store as state_store
from strategyos_mvp.agent_runtime import repository as repo
from strategyos_mvp.agent_runtime.models import ApprovalStatus, TaskStatus
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
    agent_api_module.CONFIG = config
    state_store.CONFIG = config
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
    agent_api_module.CONFIG = config
    state_store.CONFIG = config


def _truncate_strategyos_tables(database_url: str) -> None:
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(database_url, autocommit=True) as conn:
        state_store.ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select tablename from pg_tables
                where schemaname = 'public' and tablename like 'strategyos_%'
                order by tablename
                """
            )
            tables = [row[0] for row in cur.fetchall()]
            if tables:
                cur.execute(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")


def _auth_header(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


@pytest.fixture
def api_env(tmp_path: Path):
    database_url = os.environ.get("STRATEGYOS_POSTGRES_E2E_DATABASE_URL")
    if not database_url:
        pytest.skip("Set STRATEGYOS_POSTGRES_E2E_DATABASE_URL to run the agent-runtime network e2e proof.")
    _truncate_strategyos_tables(database_url)
    original = _apply_env(
        {
            "DATABASE_URL": database_url,
            "STRATEGYOS_DATABASE_URL": database_url,
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_AGENT_LIVE_UI_ENABLED": "true",
        }
    )
    try:
        yield database_url
    finally:
        _restore_env(original)


@pytest.mark.integration
def test_live_ui_feature_flag_disabled_returns_404(tmp_path: Path):
    database_url = os.environ.get("STRATEGYOS_POSTGRES_E2E_DATABASE_URL")
    if not database_url:
        pytest.skip("Set STRATEGYOS_POSTGRES_E2E_DATABASE_URL to run the agent-runtime network e2e proof.")
    _truncate_strategyos_tables(database_url)
    original = _apply_env(
        {
            "DATABASE_URL": database_url,
            "STRATEGYOS_DATABASE_URL": database_url,
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_AGENT_LIVE_UI_ENABLED": "false",
        }
    )
    try:
        client = TestClient(api_module.app)
        response = client.get("/api/v1/agent-network", headers=_auth_header("operator-secret"))
        assert response.status_code == 404
    finally:
        _restore_env(original)


@pytest.mark.integration
def test_list_agents_reflects_role_permissions(api_env):
    client = TestClient(api_module.app)
    response = client.get("/api/v1/agents", headers=_auth_header("operator-secret"))
    assert response.status_code == 200
    agents = response.json()["agents"]
    assert len(agents) == 4
    assert {a["agent_key"] for a in agents} == {"cash-recovery", "evidence-closure", "board-pack", "runtime-guardrail"}


@pytest.mark.integration
def test_agent_network_reflects_real_task_state(api_env):
    client = TestClient(api_module.app)
    headers = _auth_header("operator-secret")

    empty = client.get("/api/v1/agent-network", headers=headers)
    assert empty.status_code == 200
    assert all(m["status"] == "idle" for m in empty.json()["modules"])

    tenant_id = repo.resolve_tenant_id(load_config().tenant_slug)
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    task = repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=1,
        task_type="quantify_recoverable_value", objective="Reconcile", risk_class="read_only",
        requested_by_type="user", requested_by_id="ceo-1", idempotency_key="net:1", input={},
    )
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"})

    with_task = client.get("/api/v1/agent-network", headers=headers)
    assert with_task.status_code == 200
    body = with_task.json()
    cash_module = next(m for m in body["modules"] if m["agent_key"] == "cash-recovery")
    assert cash_module["status"] == "queued"
    assert cash_module["status_label"] == "Queued"
    assert body["summary"]["active_count"] == 1


@pytest.mark.integration
def test_agent_approvals_list_and_decide(api_env):
    client = TestClient(api_module.app)
    operator_headers = _auth_header("operator-secret")
    reviewer_headers = _auth_header("reviewer-secret")

    tenant_id = repo.resolve_tenant_id(load_config().tenant_slug)
    installation = repo.ensure_agent_installation(tenant_id, "board-pack")
    task = repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=1,
        task_type="prepare_board_pack", objective="Publish board pack", risk_class="write",
        requested_by_type="agent", requested_by_id=installation["installation_id"],
        idempotency_key="approval:1", input={},
    )
    approval = repo.create_approval_request(
        tenant_id, task_id=task["task_id"], effect_hash="deadbeef", risk_class="write",
        public_explanation="Publish board pack for Q3",
    )

    pending = client.get("/api/v1/agent-approvals?status_filter=pending", headers=reviewer_headers)
    assert pending.status_code == 200
    assert any(a["approval_id"] == approval["approval_id"] for a in pending.json()["approvals"])

    decided = client.post(
        f"/api/v1/agent-approvals/{approval['approval_id']}/decision",
        headers=reviewer_headers,
        json={"decision": "approved", "comment": "Looks good"},
    )
    assert decided.status_code == 200
    decided_body = decided.json()
    assert decided_body["status"] == "approved"
    assert decided_body["decided_by_role"] == "reviewer"

    # decision on an already-decided approval must 409
    redecide = client.post(
        f"/api/v1/agent-approvals/{approval['approval_id']}/decision",
        headers=reviewer_headers,
        json={"decision": "rejected"},
    )
    assert redecide.status_code == 409


@pytest.mark.integration
def test_agent_approvals_decision_requires_reviewer_or_operator_role(api_env):
    client = TestClient(api_module.app)
    # no auth at all
    response = client.get("/api/v1/agent-approvals")
    assert response.status_code == 401


@pytest.mark.integration
def test_invalid_decision_value_returns_400(api_env):
    client = TestClient(api_module.app)
    headers = _auth_header("reviewer-secret")
    tenant_id = repo.resolve_tenant_id(load_config().tenant_slug)
    installation = repo.ensure_agent_installation(tenant_id, "board-pack")
    task = repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=1,
        task_type="prepare_board_pack", objective="Publish", risk_class="write",
        requested_by_type="agent", requested_by_id=installation["installation_id"],
        idempotency_key="approval:invalid:1", input={},
    )
    approval = repo.create_approval_request(
        tenant_id, task_id=task["task_id"], effect_hash="cafebabe", risk_class="write", public_explanation="x",
    )
    response = client.post(
        f"/api/v1/agent-approvals/{approval['approval_id']}/decision",
        headers=headers,
        json={"decision": "maybe"},
    )
    assert response.status_code == 400


@pytest.mark.integration
def test_agent_events_stream_route_requires_auth_and_feature_flag(api_env):
    """The route wiring itself (auth dependency, feature-flag gate, and
    that it returns a StreamingResponse rather than raising) is exercised
    here without actually draining the stream: TestClient's synchronous
    httpx transport runs a StreamingResponse's generator in-process, and
    streaming.sse_event_stream()'s default poll-forever behavior (real
    time.sleep between polls, no natural end) would hang a client.stream()
    call that tries to fully consume it. The streaming logic itself
    (replay-from-cursor, no-history-on-fresh-connect, heartbeat cadence)
    is covered directly against streaming.sse_event_stream() with a bounded
    max_iterations in test_agent_runtime_streaming_unit.py, not through
    the HTTP layer."""
    client = TestClient(api_module.app)
    unauthenticated = client.get("/api/v1/agent-events/stream")
    assert unauthenticated.status_code == 401


@pytest.mark.integration
def test_agent_events_stream_disabled_flag_returns_404(tmp_path: Path):
    database_url = os.environ.get("STRATEGYOS_POSTGRES_E2E_DATABASE_URL")
    if not database_url:
        pytest.skip("Set STRATEGYOS_POSTGRES_E2E_DATABASE_URL to run the agent-runtime network e2e proof.")
    _truncate_strategyos_tables(database_url)
    original = _apply_env(
        {
            "DATABASE_URL": database_url,
            "STRATEGYOS_DATABASE_URL": database_url,
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_AGENT_LIVE_UI_ENABLED": "false",
        }
    )
    try:
        client = TestClient(api_module.app)
        response = client.get("/api/v1/agent-events/stream", headers=_auth_header("operator-secret"))
        assert response.status_code == 404
    finally:
        _restore_env(original)
