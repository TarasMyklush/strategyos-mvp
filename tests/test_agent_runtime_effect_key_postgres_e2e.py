"""Integration tests for effect-key reservation and task-attempt tracking
against real Postgres. Covers design principle 11: "At-least-once
execution, effectively-once effects. Workers may retry; idempotency keys
and unique effect records prevent duplicate side effects."
"""

from __future__ import annotations

import os

import pytest

import strategyos_mvp.state_store as state_store
from strategyos_mvp.agent_runtime import capability_tokens as capability_tokens_module
from strategyos_mvp.agent_runtime import repository as repo
from strategyos_mvp.agent_runtime import workflows
from strategyos_mvp.agent_runtime.models import TaskStatus
from strategyos_mvp.agent_runtime.tools import ToolExecutionContext, ToolInputInvalid, invoke_tool
from strategyos_mvp.config import load_config


def _apply_env(env_updates: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in env_updates}
    for key, value in env_updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    state_store.CONFIG = config
    workflows.CONFIG = config
    capability_tokens_module.CONFIG = config
    return original


def _restore_env(original: dict[str, str | None]):
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    state_store.CONFIG = config
    workflows.CONFIG = config
    capability_tokens_module.CONFIG = config


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


@pytest.fixture
def database_url():
    url = os.environ.get("STRATEGYOS_POSTGRES_E2E_DATABASE_URL")
    if not url:
        pytest.skip("Set STRATEGYOS_POSTGRES_E2E_DATABASE_URL to run the agent-runtime effect-key e2e proof.")
    _truncate_strategyos_tables(url)
    original = _apply_env(
        {"DATABASE_URL": url, "STRATEGYOS_DATABASE_URL": url, "STRATEGYOS_AGENT_CAPABILITY_TOKEN_SECRET": "effect-key-e2e-secret"}
    )
    try:
        yield url
    finally:
        _restore_env(original)


def _tenant(slug: str) -> str:
    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_tenants (slug, display_name) values (%s, %s) returning id", (slug, slug)
            )
            tenant_id = str(cur.fetchone()[0])
        conn.commit()
    return tenant_id


def _cash_recovery_task(tenant_id: str, finding_id: str, idempotency_key: str) -> dict:
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    return repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=2,
        task_type="create_remediation_proposal", objective=f"Propose remediation for {finding_id}",
        risk_class="write", requested_by_type="user", requested_by_id="reviewer-1",
        idempotency_key=idempotency_key, input={"finding_id": finding_id},
    )


def _write_token_ctx(tenant_id: str, task_id: str, installation_id: str) -> ToolExecutionContext:
    token = capability_tokens_module.issue_capability_token(
        tenant_id=tenant_id, task_id=task_id, attempt_no=1, agent_installation_id=installation_id,
        allowed_tool_keys=("remediation.propose",), max_risk_class="write",
    )
    claims = capability_tokens_module.verify_capability_token(token)
    return ToolExecutionContext(tenant_id=tenant_id, task_id=task_id, run_id=None, capability_claims=claims)


@pytest.mark.integration
def test_create_task_attempt_assigns_monotonic_attempt_numbers(database_url):
    tenant_id = _tenant("attempt-monotonic")
    task = _cash_recovery_task(tenant_id, "FIN-001", "attempt:monotonic:1")

    attempt1 = repo.create_task_attempt(tenant_id, task["task_id"], worker_id="w1")
    attempt2 = repo.create_task_attempt(tenant_id, task["task_id"], worker_id="w2")
    attempt3 = repo.create_task_attempt(tenant_id, task["task_id"], worker_id="w3")

    assert [attempt1["attempt_no"], attempt2["attempt_no"], attempt3["attempt_no"]] == [1, 2, 3]


@pytest.mark.integration
def test_finish_task_attempt_records_terminal_status_and_timestamp(database_url):
    tenant_id = _tenant("attempt-finish")
    task = _cash_recovery_task(tenant_id, "FIN-001", "attempt:finish:1")
    attempt = repo.create_task_attempt(tenant_id, task["task_id"], worker_id="w1")

    finished = repo.finish_task_attempt(
        tenant_id, attempt["task_attempt_id"], status="failed",
        error_code="AGENT_TIMEOUT", error_detail_restricted="internal detail never surfaced publicly",
    )
    assert finished["status"] == "failed"
    assert finished["error_code"] == "AGENT_TIMEOUT"
    assert finished["finished_at"] is not None


@pytest.mark.integration
def test_reserve_tool_effect_is_idempotent_across_repeated_calls(database_url):
    tenant_id = _tenant("effect-idempotent")
    task = _cash_recovery_task(tenant_id, "FIN-001", "effect:idempotent:1")

    first = repo.reserve_tool_effect(
        tenant_id, task["task_id"], task_attempt_id=None, tool_key="remediation.propose",
        tool_version="v1", input_hash="hash1", effect_key="effect-key-1",
    )
    assert first["status"] == "pending"

    with pytest.raises(repo.EffectAlreadyReserved) as excinfo:
        repo.reserve_tool_effect(
            tenant_id, task["task_id"], task_attempt_id=None, tool_key="remediation.propose",
            tool_version="v1", input_hash="hash1", effect_key="effect-key-1",
        )
    assert excinfo.value.existing_invocation["tool_invocation_id"] == first["tool_invocation_id"]


@pytest.mark.integration
def test_remediation_propose_produces_exactly_one_effect_across_two_invocations(database_url):
    """The full property this gap closes: at-least-once task execution
    (simulated here as two direct invoke_tool calls, as if a retried task
    ran the same tool call twice) must never produce two durable effects."""
    tenant_id = _tenant("remediation-exactly-once")
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    task = _cash_recovery_task(tenant_id, "FIN-001", "remediation:exactly-once:1")
    ctx = _write_token_ctx(tenant_id, task["task_id"], installation["installation_id"])

    result1 = invoke_tool("remediation.propose", ctx, {"finding_id": "FIN-001", "reason": "first"})
    result2 = invoke_tool("remediation.propose", ctx, {"finding_id": "FIN-001", "reason": "retry"})

    assert result1["already_proposed"] is False
    assert result2["already_proposed"] is True

    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from strategyos_agent_artifact_links where task_id = %s and reference_id = 'FIN-001'",
                (task["task_id"],),
            )
            link_count = cur.fetchone()[0]
        conn.commit()
    assert link_count == 1


@pytest.mark.integration
def test_remediation_propose_for_different_findings_creates_independent_effects(database_url):
    tenant_id = _tenant("remediation-independent")
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    task = _cash_recovery_task(tenant_id, "FIN-001", "remediation:independent:1")
    ctx = _write_token_ctx(tenant_id, task["task_id"], installation["installation_id"])

    result_a = invoke_tool("remediation.propose", ctx, {"finding_id": "FIN-001", "reason": "a"})
    result_b = invoke_tool("remediation.propose", ctx, {"finding_id": "FIN-002", "reason": "b"})

    assert result_a["already_proposed"] is False
    assert result_b["already_proposed"] is False
    assert result_a["artifact_link_id"] != result_b["artifact_link_id"]


@pytest.mark.integration
def test_remediation_propose_requires_a_write_scoped_capability_token(database_url):
    tenant_id = _tenant("remediation-no-token")
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    task = _cash_recovery_task(tenant_id, "FIN-001", "remediation:no-token:1")

    ctx_no_token = ToolExecutionContext(tenant_id=tenant_id, task_id=task["task_id"], run_id=None)
    with pytest.raises(ToolInputInvalid):
        invoke_tool("remediation.propose", ctx_no_token, {"finding_id": "FIN-001"})


@pytest.mark.integration
def test_remediation_propose_rejects_a_read_only_scoped_token(database_url):
    tenant_id = _tenant("remediation-readonly-token")
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    task = _cash_recovery_task(tenant_id, "FIN-001", "remediation:readonly-token:1")

    token = capability_tokens_module.issue_capability_token(
        tenant_id=tenant_id, task_id=task["task_id"], attempt_no=1,
        agent_installation_id=installation["installation_id"],
        allowed_tool_keys=("findings.read",), max_risk_class="read_only",
    )
    claims = capability_tokens_module.verify_capability_token(token)
    ctx = ToolExecutionContext(tenant_id=tenant_id, task_id=task["task_id"], run_id=None, capability_claims=claims)

    with pytest.raises(Exception):
        invoke_tool("remediation.propose", ctx, {"finding_id": "FIN-001"})


@pytest.mark.integration
def test_execute_agent_task_job_creates_and_finishes_a_real_attempt_row(database_url):
    tenant_id = _tenant("attempt-full-path")
    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_runs (run_dir, dataset_root, finding_count, locked_finding_count, "
                "total_recoverable_sar, status, summary_json) values ('r','ds',1,1,10000,'completed','{}'::jsonb) "
                "returning id"
            )
            run_id = str(cur.fetchone()[0])
        conn.commit()

    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    task = repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=2,
        task_type="quantify_recoverable_value", objective="Reconcile", risk_class="read_only",
        requested_by_type="user", requested_by_id="ceo-1", idempotency_key="attempt:full-path:1",
        input={"run_id": run_id},
    )
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"})

    result = workflows.execute_agent_task_job(workflows.AgentTaskExecuteInput(tenant_id=tenant_id, task_id=task["task_id"]))
    assert result.status == "succeeded"

    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select attempt_no, status, finished_at from strategyos_agent_task_attempts where task_id = %s",
                (task["task_id"],),
            )
            rows = cur.fetchall()
        conn.commit()
    assert len(rows) == 1
    attempt_no, status, finished_at = rows[0]
    assert attempt_no == 1
    assert status == "succeeded"
    assert finished_at is not None


@pytest.mark.integration
def test_a_failed_handler_finishes_its_attempt_as_failed_not_left_running(database_url):
    tenant_id = _tenant("attempt-failed-path")
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    task = repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=2,
        task_type="quantify_recoverable_value", objective="Reconcile", risk_class="read_only",
        requested_by_type="user", requested_by_id="ceo-1", idempotency_key="attempt:failed:1",
        input={},  # no run_id -- handler raises HandlerInputInvalid
    )
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"})

    result = workflows.execute_agent_task_job(workflows.AgentTaskExecuteInput(tenant_id=tenant_id, task_id=task["task_id"]))
    assert result.status == "failed"

    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, error_code from strategyos_agent_task_attempts where task_id = %s",
                (task["task_id"],),
            )
            rows = cur.fetchall()
        conn.commit()
    assert len(rows) == 1
    status, error_code = rows[0]
    assert status == "failed"
    assert error_code == "AGENT_INVALID_INPUT"
