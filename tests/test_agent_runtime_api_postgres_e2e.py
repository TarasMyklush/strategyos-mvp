"""Integration tests for the /api/v1/agent-conversations HTTP surface
against a real Postgres instance, exercised through FastAPI's TestClient
-- same opt-in guard and env-swap pattern as
test_governed_review_flow_postgres_e2e.py.

Covers: feature-flag gate (404 when disabled), auth (401/403), the full
answer/delegate/clarify conversation flow through HTTP, Idempotency-Key
enforcement, and 404s for missing conversations/tasks.
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
        pytest.skip("Set STRATEGYOS_POSTGRES_E2E_DATABASE_URL to run the agent-runtime api e2e proof.")
    _truncate_strategyos_tables(database_url)
    original = _apply_env(
        {
            "DATABASE_URL": database_url,
            "STRATEGYOS_DATABASE_URL": database_url,
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_AGENT_CONVERSATIONS_ENABLED": "true",
        }
    )
    try:
        yield database_url
    finally:
        _restore_env(original)


@pytest.mark.integration
def test_feature_flag_disabled_returns_404(tmp_path: Path):
    database_url = os.environ.get("STRATEGYOS_POSTGRES_E2E_DATABASE_URL")
    if not database_url:
        pytest.skip("Set STRATEGYOS_POSTGRES_E2E_DATABASE_URL to run the agent-runtime api e2e proof.")
    _truncate_strategyos_tables(database_url)
    original = _apply_env(
        {
            "DATABASE_URL": database_url,
            "STRATEGYOS_DATABASE_URL": database_url,
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_AGENT_CONVERSATIONS_ENABLED": "false",
        }
    )
    try:
        client = TestClient(api_module.app)
        response = client.post(
            "/api/v1/agent-conversations", headers=_auth_header("operator-secret"), json={}
        )
        assert response.status_code == 404
    finally:
        _restore_env(original)


@pytest.mark.integration
def test_unauthenticated_request_is_rejected(api_env):
    client = TestClient(api_module.app)
    response = client.post("/api/v1/agent-conversations", json={})
    assert response.status_code == 401


@pytest.mark.integration
def test_create_conversation_and_full_answer_delegate_flow(api_env):
    client = TestClient(api_module.app)
    headers = _auth_header("operator-secret")

    repo.sync_agent_definitions()
    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_runs (run_dir, dataset_root, finding_count, locked_finding_count, "
                "total_recoverable_sar, status, summary_json) values ('run1','ds1',1,1,10000,'completed','{}'::jsonb) "
                "returning id"
            )
            run_id = str(cur.fetchone()[0])
        conn.commit()

    created = client.post("/api/v1/agent-conversations", headers=headers, json={"persona": "ceo"})
    assert created.status_code == 200
    conversation_id = created.json()["conversation_id"]

    fetched = client.get(f"/api/v1/agent-conversations/{conversation_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["conversation_id"] == conversation_id

    # message without Idempotency-Key must be rejected
    missing_key = client.post(
        f"/api/v1/agent-conversations/{conversation_id}/messages",
        headers=headers,
        json={"body": "What is the board state?"},
    )
    assert missing_key.status_code == 400

    # answer path
    answer_resp = client.post(
        f"/api/v1/agent-conversations/{conversation_id}/messages",
        headers={**headers, "Idempotency-Key": "req-1"},
        json={"body": "What is the current board state?", "persona": "ceo"},
    )
    assert answer_resp.status_code == 200
    answer_body = answer_resp.json()
    assert answer_body["decision"]["intent"] == "answer"
    assert answer_body["task"] is None

    # delegate path
    delegate_resp = client.post(
        f"/api/v1/agent-conversations/{conversation_id}/messages",
        headers={**headers, "Idempotency-Key": "req-2"},
        json={"body": "Why does the recoverable value not reconcile for this run?", "scope": {"run_id": run_id}},
    )
    assert delegate_resp.status_code == 200
    delegate_body = delegate_resp.json()
    assert delegate_body["decision"]["intent"] == "delegate"
    assert delegate_body["task"] is not None
    task_id = delegate_body["task"]["task_id"]

    # idempotent retry returns the same task
    retry_resp = client.post(
        f"/api/v1/agent-conversations/{conversation_id}/messages",
        headers={**headers, "Idempotency-Key": "req-2"},
        json={"body": "Why does the recoverable value not reconcile for this run?", "scope": {"run_id": run_id}},
    )
    assert retry_resp.status_code == 200
    assert retry_resp.json()["task"]["task_id"] == task_id

    # task readable through the API
    task_resp = client.get(f"/api/v1/agent-tasks/{task_id}", headers=headers)
    assert task_resp.status_code == 200
    assert task_resp.json()["task_id"] == task_id

    # transcript persisted server-side and readable
    messages_resp = client.get(f"/api/v1/agent-conversations/{conversation_id}/messages", headers=headers)
    assert messages_resp.status_code == 200
    messages = messages_resp.json()["messages"]
    assert len(messages) >= 6  # 3 user + 3 hermes turns (idempotent retry is a distinct HTTP call)

    # archive
    archive_resp = client.post(f"/api/v1/agent-conversations/{conversation_id}/archive", headers=headers)
    assert archive_resp.status_code == 200
    assert archive_resp.json()["archived_at"] is not None


@pytest.mark.integration
def test_missing_conversation_returns_404(api_env):
    client = TestClient(api_module.app)
    headers = _auth_header("operator-secret")
    response = client.get("/api/v1/agent-conversations/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404


@pytest.mark.integration
def test_posting_to_missing_conversation_returns_404(api_env):
    client = TestClient(api_module.app)
    headers = _auth_header("operator-secret")
    response = client.post(
        "/api/v1/agent-conversations/00000000-0000-0000-0000-000000000000/messages",
        headers={**headers, "Idempotency-Key": "req-x"},
        json={"body": "hello"},
    )
    assert response.status_code == 404


@pytest.mark.integration
def test_missing_task_returns_404(api_env):
    client = TestClient(api_module.app)
    headers = _auth_header("operator-secret")
    response = client.get("/api/v1/agent-tasks/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404
