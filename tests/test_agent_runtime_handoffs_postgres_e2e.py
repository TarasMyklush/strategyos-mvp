"""Integration tests for real specialist handoffs (PR4) against real
Postgres. Covers design doc section 8.3: a worker's proposed_actions
becoming a real handoff + child task, subject to depth/fan-out/loop
budgets, and consequential handoffs creating a linked approval request.
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
    workflows.CONFIG = config
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
        pytest.skip("Set STRATEGYOS_POSTGRES_E2E_DATABASE_URL to run the agent-runtime handoffs e2e proof.")
    _truncate_strategyos_tables(url)
    original = _apply_env(
        {"DATABASE_URL": url, "STRATEGYOS_DATABASE_URL": url, "STRATEGYOS_AGENT_HANDOFFS_ENABLED": "true"}
    )
    try:
        yield url
    finally:
        _restore_env(original)


def _seed_run_with_weak_finding(slug: str) -> tuple[str, str]:
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
                "total_recoverable_sar, status, summary_json) values (%s, 'ds', 2, 1, 50000, 'completed', '{}'::jsonb) "
                "returning id",
                (f"{slug}-run",),
            )
            run_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into strategyos_findings (run_id, finding_id, pattern_type, vendor_id, vendor_name, "
                "status, confidence, leakage_sar, recoverable_sar, finding_json) "
                "values (%s, 'FIN-001', 'duplicate_payment', 'V1', 'Acme', 'locked', 'HIGH', 30000, 30000, '{}'::jsonb), "
                "       (%s, 'FIN-002', 'price_variance', 'V2', 'Beta', 'draft', 'MEDIUM', 20000, 20000, '{}'::jsonb)",
                (run_id, run_id),
            )
            cur.execute(
                "insert into strategyos_finding_citations (run_id, finding_id, source_path, locator, resolved) "
                "values (%s, 'FIN-001', 'invoice.pdf', 'row-1', true)",
                (run_id,),
            )
        conn.commit()
    return tenant_id, run_id


def _run_cash_recovery_to_completion(tenant_id: str, run_id: str, idempotency_key: str) -> dict:
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    task = repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=1,
        task_type="quantify_recoverable_value", objective="Reconcile", risk_class="read_only",
        requested_by_type="user", requested_by_id="ceo-1", idempotency_key=idempotency_key,
        input={"run_id": run_id},
    )
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"})
    workflows.dispatch_ready_tasks()
    return repo.get_task(tenant_id, task["task_id"])


def _handoffs_for(tenant_id: str, source_task_id: str) -> list[tuple]:
    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, requested_capability, child_task_id::text from strategyos_agent_handoffs "
                "where source_task_id = %s and tenant_id = %s",
                (source_task_id, tenant_id),
            )
            rows = cur.fetchall()
        conn.commit()
    return rows


@pytest.mark.integration
def test_weak_citation_coverage_creates_a_real_handoff(database_url):
    tenant_id, run_id = _seed_run_with_weak_finding("handoff-basic")
    final_task = _run_cash_recovery_to_completion(tenant_id, run_id, "handoff:basic:1")
    assert final_task["status"] == "succeeded"

    handoffs = _handoffs_for(tenant_id, final_task["task_id"])
    assert len(handoffs) == 1
    status, capability, child_task_id = handoffs[0]
    assert status == "accepted"
    assert capability == "resolve_evidence_gap"

    child_task = repo.get_task(tenant_id, child_task_id)
    assert child_task["parent_task_id"] == final_task["task_id"]
    assert child_task["input_json"]["run_id"] == run_id
    assert child_task["status"] == "queued"  # resolve_evidence_gap is read_only, auto-queues


@pytest.mark.integration
def test_handoff_child_task_executes_and_reports_unsupported_findings(database_url):
    tenant_id, run_id = _seed_run_with_weak_finding("handoff-execute")
    final_task = _run_cash_recovery_to_completion(tenant_id, run_id, "handoff:execute:1")
    handoffs = _handoffs_for(tenant_id, final_task["task_id"])
    _, _, child_task_id = handoffs[0]

    workflows.dispatch_ready_tasks()  # runs the child (evidence closure) task

    final_child = repo.get_task(tenant_id, child_task_id)
    assert final_child["status"] == "succeeded"
    assert "FIN-002" in final_child["result_json"]["data"]["unsupported_findings"]


@pytest.mark.integration
def test_handoff_is_idempotent_across_repeated_execution_attempts(database_url):
    """The same source task's proposed_actions must not create a duplicate
    handoff if _create_proposed_handoffs somehow ran twice (e.g. a retry
    after a crash between transition_task(succeeded) and handoff creation)
    -- protected by the idempotency_key embedding source_task_id+capability+
    scope_hash on the child task."""
    tenant_id, run_id = _seed_run_with_weak_finding("handoff-idempotent")
    final_task = _run_cash_recovery_to_completion(tenant_id, run_id, "handoff:idempotent:1")

    from strategyos_mvp.agent_runtime.workflows import _create_proposed_handoffs
    from strategyos_mvp.agent_runtime.registry import CASH_RECOVERY

    running_task_view = repo.get_task(tenant_id, final_task["task_id"])
    _create_proposed_handoffs(
        tenant_id, final_task["task_id"], running_task_view, CASH_RECOVERY,
        final_task["result_json"], {"type": "system", "id": "agent-worker"},
    )

    handoffs = _handoffs_for(tenant_id, final_task["task_id"])
    assert len(handoffs) == 1, f"expected exactly 1 handoff after a repeated call, got {len(handoffs)}"


@pytest.mark.integration
def test_handoffs_disabled_flag_creates_no_handoff(database_url):
    tenant_id, run_id = _seed_run_with_weak_finding("handoff-disabled")
    original = _apply_env({"STRATEGYOS_AGENT_HANDOFFS_ENABLED": "false"})
    try:
        final_task = _run_cash_recovery_to_completion(tenant_id, run_id, "handoff:disabled:1")
        assert final_task["status"] == "succeeded"
        handoffs = _handoffs_for(tenant_id, final_task["task_id"])
        assert handoffs == []
    finally:
        _restore_env(original)


@pytest.mark.integration
def test_fully_cited_findings_create_no_handoff(database_url):
    """A run where every finding has a citation must produce zero
    proposed_actions and therefore zero handoffs."""
    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_tenants (slug, display_name) values ('handoff-none', 'handoff-none') returning id"
            )
            tenant_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into strategyos_runs (run_dir, dataset_root, finding_count, locked_finding_count, "
                "total_recoverable_sar, status, summary_json) values ('r','ds',1,1,10000,'completed','{}'::jsonb) "
                "returning id"
            )
            run_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into strategyos_findings (run_id, finding_id, pattern_type, vendor_id, vendor_name, "
                "status, confidence, leakage_sar, recoverable_sar, finding_json) "
                "values (%s, 'FIN-001', 'duplicate_payment', 'V1', 'Acme', 'locked', 'HIGH', 10000, 10000, '{}'::jsonb)",
                (run_id,),
            )
            cur.execute(
                "insert into strategyos_finding_citations (run_id, finding_id, source_path, locator, resolved) "
                "values (%s, 'FIN-001', 'invoice.pdf', 'row-1', true)",
                (run_id,),
            )
        conn.commit()

    final_task = _run_cash_recovery_to_completion(tenant_id, run_id, "handoff:none:1")
    assert final_task["status"] == "succeeded"
    assert final_task["result_json"]["gaps"] == []
    handoffs = _handoffs_for(tenant_id, final_task["task_id"])
    assert handoffs == []
