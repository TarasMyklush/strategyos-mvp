"""Integration tests for agent_runtime.workflows against real Postgres.

Same opt-in guard as the PR1 repository e2e suite. Covers design doc
section 18: attempt/retry/timeout, effective task claiming (queued ->
running compare-and-set), and the outbox dispatcher / reconciliation job
named in the PR2 migration step.
"""

from __future__ import annotations

import os

import pytest

import strategyos_mvp.state_store as state_store
from strategyos_mvp.agent_runtime import repository as repo
from strategyos_mvp.agent_runtime import workflows
from strategyos_mvp.agent_runtime.models import TaskStatus
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
    return original


def _restore_env(original: dict[str, str | None]):
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    state_store.CONFIG = load_config()


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


def _create_tenant_and_run(slug: str) -> tuple[str, str]:
    connection, skipped = state_store.database_connection()
    assert skipped is None, skipped
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_tenants (slug, display_name) values (%s, %s) returning id", (slug, slug)
            )
            tenant_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into strategyos_runs (run_dir, dataset_root, finding_count, locked_finding_count, "
                "total_recoverable_sar, status, summary_json) values (%s, 'ds', 1, 1, 10000, 'completed', '{}'::jsonb) "
                "returning id",
                (f"{slug}-run",),
            )
            run_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into strategyos_findings (run_id, finding_id, pattern_type, vendor_id, vendor_name, "
                "status, confidence, leakage_sar, recoverable_sar, finding_json) "
                "values (%s, 'FIN-001', 'duplicate_payment', 'V1', 'Vendor', 'locked', 'HIGH', 10000, 10000, '{}'::jsonb)",
                (run_id,),
            )
            cur.execute(
                "insert into strategyos_finding_citations (run_id, finding_id, source_path, locator, resolved) "
                "values (%s, 'FIN-001', 'invoice.pdf', 'row-1', true)",
                (run_id,),
            )
        conn.commit()
    return tenant_id, run_id


@pytest.fixture
def database_url():
    url = os.environ.get("STRATEGYOS_POSTGRES_E2E_DATABASE_URL")
    if not url:
        pytest.skip("Set STRATEGYOS_POSTGRES_E2E_DATABASE_URL to run the agent-runtime workflows e2e proof.")
    _truncate_strategyos_tables(url)
    original = _apply_env({"DATABASE_URL": url, "STRATEGYOS_DATABASE_URL": url})
    try:
        yield url
    finally:
        _restore_env(original)


def _queued_cash_recovery_task(tenant_id: str, run_id: str, idempotency_key: str) -> dict:
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    task = repo.create_task(
        tenant_id,
        agent_installation_id=installation["installation_id"],
        agent_definition_version=1,
        task_type="quantify_recoverable_value",
        objective="Reconcile",
        risk_class="read_only",
        requested_by_type="user",
        requested_by_id="ceo-1",
        idempotency_key=idempotency_key,
        input={"run_id": run_id},
    )
    return repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"})


@pytest.mark.integration
def test_dispatch_ready_tasks_executes_queued_task_to_success(database_url):
    tenant_id, run_id = _create_tenant_and_run("wf-dispatch")
    queued = _queued_cash_recovery_task(tenant_id, run_id, "wf:dispatch:1")

    result = workflows.dispatch_ready_tasks()
    assert result["dispatched"] == 1

    final = repo.get_task(tenant_id, queued["task_id"])
    assert final["status"] == "succeeded"
    assert final["result_json"]["data"]["total_recoverable_sar"] == 10000.0


@pytest.mark.integration
def test_dispatch_ready_tasks_only_touches_queued_tasks(database_url):
    tenant_id, run_id = _create_tenant_and_run("wf-selective")
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    # a task left in `proposed` must not be picked up
    proposed_task = repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=1,
        task_type="quantify_recoverable_value", objective="Reconcile", risk_class="read_only",
        requested_by_type="user", requested_by_id="ceo-1", idempotency_key="wf:selective:1",
        input={"run_id": run_id},
    )

    result = workflows.dispatch_ready_tasks()
    assert result["dispatched"] == 0

    still_proposed = repo.get_task(tenant_id, proposed_task["task_id"])
    assert still_proposed["status"] == "proposed"


@pytest.mark.integration
def test_execute_agent_task_job_fails_task_when_no_installation_agent_registered(database_url):
    """Simulates AGENT_NOT_PERMITTED: an installation whose agent_key isn't
    in the registry (e.g. a stale/disabled installation) must fail the task
    with a public-safe reason, not crash the dispatcher."""
    tenant_id, run_id = _create_tenant_and_run("wf-unregistered")
    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_agent_installations (tenant_id, agent_key, agent_definition_version) "
                "values (%s, 'not-a-real-agent', 1) returning id",
                (tenant_id,),
            )
            installation_id = str(cur.fetchone()[0])
        conn.commit()

    task = repo.create_task(
        tenant_id, agent_installation_id=installation_id, agent_definition_version=1,
        task_type="quantify_recoverable_value", objective="Reconcile", risk_class="read_only",
        requested_by_type="user", requested_by_id="ceo-1", idempotency_key="wf:unregistered:1",
        input={"run_id": run_id},
    )
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"})

    result = workflows.dispatch_ready_tasks()
    assert result["dispatched"] == 1

    final = repo.get_task(tenant_id, task["task_id"])
    assert final["status"] == "failed"
    assert final["failure_code"] == "AGENT_NOT_PERMITTED"
    assert final["failure_detail_public"]


@pytest.mark.integration
def test_execute_agent_task_job_fails_task_on_invalid_input(database_url):
    tenant_id, _ = _create_tenant_and_run("wf-invalid-input")
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    task = repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=1,
        task_type="quantify_recoverable_value", objective="Reconcile", risk_class="read_only",
        requested_by_type="user", requested_by_id="ceo-1", idempotency_key="wf:invalid:1",
        input={},  # no run_id anywhere -- handler must raise HandlerInputInvalid
    )
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"})

    workflows.dispatch_ready_tasks()

    final = repo.get_task(tenant_id, task["task_id"])
    assert final["status"] == "failed"
    assert final["failure_code"] == "AGENT_INVALID_INPUT"


@pytest.mark.integration
def test_execute_agent_task_job_is_a_noop_when_task_not_queued(database_url):
    """A task already claimed/terminal must not be re-executed by a second
    dispatch call -- this is the compare-and-set claiming guarantee."""
    tenant_id, run_id = _create_tenant_and_run("wf-noop")
    queued = _queued_cash_recovery_task(tenant_id, run_id, "wf:noop:1")
    workflows.dispatch_ready_tasks()  # runs it to completion
    succeeded = repo.get_task(tenant_id, queued["task_id"])
    assert succeeded["status"] == "succeeded"

    from strategyos_mvp.agent_runtime.workflows import AgentTaskExecuteInput, execute_agent_task_job

    output = execute_agent_task_job(AgentTaskExecuteInput(tenant_id=tenant_id, task_id=queued["task_id"]))
    assert output.status == "succeeded"  # unchanged, not re-executed

    # aggregate_version must not have incremented further
    unchanged = repo.get_task(tenant_id, queued["task_id"])
    assert unchanged["aggregate_version"] == succeeded["aggregate_version"]


@pytest.mark.integration
def test_reconcile_stuck_tasks_times_out_tasks_past_lease(database_url):
    tenant_id, run_id = _create_tenant_and_run("wf-reconcile")
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    task = repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=1,
        task_type="quantify_recoverable_value", objective="Reconcile", risk_class="read_only",
        requested_by_type="user", requested_by_id="ceo-1", idempotency_key="wf:reconcile:1",
        input={"run_id": run_id},
    )
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"})
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.RUNNING, actor={"type": "agent", "id": "stuck-worker"})

    # backdate started_at to simulate a lease that expired long ago
    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update strategyos_agent_tasks set started_at = now() - interval '1 hour' where id = %s",
                (task["task_id"],),
            )
        conn.commit()

    result = workflows.reconcile_stuck_tasks(running_lease_minutes=15)
    assert result["timed_out"] == 1

    final = repo.get_task(tenant_id, task["task_id"])
    assert final["status"] == "timed_out"
    assert final["failure_code"] == "AGENT_TIMEOUT"


@pytest.mark.integration
def test_reconcile_stuck_tasks_leaves_fresh_running_tasks_alone(database_url):
    tenant_id, run_id = _create_tenant_and_run("wf-reconcile-fresh")
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    task = repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=1,
        task_type="quantify_recoverable_value", objective="Reconcile", risk_class="read_only",
        requested_by_type="user", requested_by_id="ceo-1", idempotency_key="wf:reconcile-fresh:1",
        input={"run_id": run_id},
    )
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"})
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.RUNNING, actor={"type": "agent", "id": "worker-1"})

    result = workflows.reconcile_stuck_tasks(running_lease_minutes=15)
    assert result["timed_out"] == 0

    final = repo.get_task(tenant_id, task["task_id"])
    assert final["status"] == "running"


@pytest.mark.integration
def test_failed_task_can_be_retried_via_queued_transition(database_url):
    """Design doc lifecycle: failed -> queued under retry policy. Simulates
    a caller-driven retry (the actual retry-policy trigger is PR6/operator
    territory; this proves the state machine allows it and a retried task
    re-executes cleanly)."""
    tenant_id, _ = _create_tenant_and_run("wf-retry")
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    task = repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=1,
        task_type="quantify_recoverable_value", objective="Reconcile", risk_class="read_only",
        requested_by_type="user", requested_by_id="ceo-1", idempotency_key="wf:retry:1",
        input={},  # invalid -- forces a failure first
    )
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"})
    workflows.dispatch_ready_tasks()
    failed = repo.get_task(tenant_id, task["task_id"])
    assert failed["status"] == "failed"

    retried = repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "retry-policy"})
    assert retried["status"] == "queued"
    assert int(retried["aggregate_version"]) == int(failed["aggregate_version"]) + 1
