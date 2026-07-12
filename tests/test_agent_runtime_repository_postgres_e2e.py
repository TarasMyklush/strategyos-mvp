"""Integration tests for agent_runtime.repository against a real Postgres
instance. Same opt-in guard as test_governed_review_flow_postgres_e2e.py and
test_state_store_pool.py: skips unless STRATEGYOS_POSTGRES_E2E_DATABASE_URL
is set.

Covers design doc section 18 "Repository/integration" list: tenant
isolation, optimistic concurrency / duplicate command handling, transactional
event/outbox writes, and idempotent retries.
"""

from __future__ import annotations

import json
import os

import pytest

import strategyos_mvp.state_store as state_store
from strategyos_mvp.agent_runtime import events as events_module
from strategyos_mvp.agent_runtime import repository as repo
from strategyos_mvp.agent_runtime.models import ApprovalStatus, HandoffStatus, TaskStatus
from strategyos_mvp.agent_runtime.repository import InvalidStatusTransition, TenantMismatch
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
                select tablename
                from pg_tables
                where schemaname = 'public'
                  and tablename like 'strategyos_%'
                order by tablename
                """
            )
            tables = [row[0] for row in cur.fetchall()]
            if tables:
                joined = ", ".join(tables)
                cur.execute(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE")


def _create_tenant(slug: str) -> str:
    connection, skipped = state_store.database_connection()
    assert skipped is None, skipped
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_tenants (slug, display_name) values (%s, %s) returning id",
                (slug, slug),
            )
            tenant_id = str(cur.fetchone()[0])
        conn.commit()
    return tenant_id


@pytest.fixture
def database_url():
    url = os.environ.get("STRATEGYOS_POSTGRES_E2E_DATABASE_URL")
    if not url:
        pytest.skip("Set STRATEGYOS_POSTGRES_E2E_DATABASE_URL to run the agent-runtime repository e2e proof.")
    _truncate_strategyos_tables(url)
    original = _apply_env({"DATABASE_URL": url, "STRATEGYOS_DATABASE_URL": url})
    try:
        yield url
    finally:
        _restore_env(original)


@pytest.mark.integration
def test_sync_agent_definitions_is_idempotent(database_url):
    first = repo.sync_agent_definitions()
    second = repo.sync_agent_definitions()
    assert first == {"status": "synced", "count": 4}
    assert second == {"status": "synced", "count": 4}


@pytest.mark.integration
def test_ensure_agent_installation_is_idempotent_per_tenant(database_url):
    tenant_id = _create_tenant("tenant-installation")
    first = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    second = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    assert first["installation_id"] == second["installation_id"]


@pytest.mark.integration
def test_agent_records_are_json_serializable(database_url):
    """Guards against uuid.UUID leaking into API-facing records: every field
    normalize_record() doesn't stringify by name must be explicitly coerced
    by repository._stringify_uuids, or this raises TypeError."""
    tenant_id = _create_tenant("tenant-json-safety")
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    conversation = repo.create_conversation(tenant_id, created_by_subject="ceo-1")
    task = repo.create_task(
        tenant_id,
        agent_installation_id=installation["installation_id"],
        agent_definition_version=1,
        task_type="quantify_recoverable_value",
        objective="test",
        risk_class="read_only",
        requested_by_type="user",
        requested_by_id="ceo-1",
        idempotency_key="tenant:json-safety:1",
        conversation_id=conversation["conversation_id"],
    )
    json.dumps(installation)
    json.dumps(conversation)
    json.dumps(task)
    assert isinstance(installation["tenant_id"], str)
    assert isinstance(task["agent_installation_id"], str)


@pytest.mark.integration
def test_create_task_with_same_idempotency_key_returns_the_same_task(database_url):
    tenant_id = _create_tenant("tenant-idempotency")
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    kwargs = dict(
        agent_installation_id=installation["installation_id"],
        agent_definition_version=1,
        task_type="quantify_recoverable_value",
        objective="Reconcile",
        risk_class="read_only",
        requested_by_type="user",
        requested_by_id="ceo-1",
        idempotency_key="tenant:conv:duplicate-request",
    )
    first = repo.create_task(tenant_id, **kwargs)
    second = repo.create_task(tenant_id, **kwargs)
    assert first["task_id"] == second["task_id"]

    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from strategyos_agent_tasks where tenant_id = %s and idempotency_key = %s",
                (tenant_id, "tenant:conv:duplicate-request"),
            )
            count = cur.fetchone()[0]
        conn.commit()
    assert count == 1, "idempotent create_task must not insert a second row"


@pytest.mark.integration
def test_task_lifecycle_transitions_and_rejects_invalid_jump(database_url):
    tenant_id = _create_tenant("tenant-task-lifecycle")
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
        idempotency_key="tenant:conv:lifecycle",
    )
    assert task["status"] == "proposed"

    queued = repo.transition_task(
        tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"}
    )
    assert queued["status"] == "queued"
    assert int(queued["aggregate_version"]) == 2

    with pytest.raises(InvalidStatusTransition):
        repo.transition_task(
            tenant_id, task["task_id"], target_status=TaskStatus.SUCCEEDED, actor={"type": "system", "id": "policy"}
        )

    repo.transition_task(
        tenant_id, task["task_id"], target_status=TaskStatus.RUNNING, actor={"type": "agent", "id": "worker-1"}
    )
    final = repo.transition_task(
        tenant_id,
        task["task_id"],
        target_status=TaskStatus.SUCCEEDED,
        actor={"type": "agent", "id": "worker-1"},
        result={"summary": "done", "status": "complete"},
    )
    assert final["status"] == "succeeded"
    assert final["started_at"] is not None
    assert final["finished_at"] is not None
    assert final["result_json"]["summary"] == "done"


@pytest.mark.integration
def test_every_task_transition_writes_an_event_in_the_same_transaction(database_url):
    tenant_id = _create_tenant("tenant-events")
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
        idempotency_key="tenant:conv:events",
    )
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"})
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.RUNNING, actor={"type": "agent", "id": "worker-1"})
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.SUCCEEDED, actor={"type": "agent", "id": "worker-1"})

    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            found_events = events_module.list_events_for_aggregate(
                cur, tenant_id=tenant_id, aggregate_type="agent_task", aggregate_id=task["task_id"]
            )
            outbox = events_module.unpublished_outbox_rows(cur)
        conn.commit()

    assert [e["event_type"] for e in found_events] == [
        "agent.task.proposed.v1",
        "agent.task.queued.v1",
        "agent.task.running.v1",
        "agent.task.succeeded.v1",
    ]
    outbox_event_ids = {row["event_id"] for row in outbox}
    assert {e["event_id"] for e in found_events} <= outbox_event_ids, (
        "every event must have a corresponding unpublished outbox row"
    )


@pytest.mark.integration
def test_tenant_isolation_on_task_read_and_transition(database_url):
    tenant_a = _create_tenant("tenant-a")
    tenant_b = _create_tenant("tenant-b")
    installation = repo.ensure_agent_installation(tenant_a, "cash-recovery")
    task = repo.create_task(
        tenant_a,
        agent_installation_id=installation["installation_id"],
        agent_definition_version=1,
        task_type="quantify_recoverable_value",
        objective="Reconcile",
        risk_class="read_only",
        requested_by_type="user",
        requested_by_id="ceo-1",
        idempotency_key="tenant:conv:isolation",
    )

    assert repo.get_task(tenant_b, task["task_id"]) is None

    with pytest.raises(TenantMismatch):
        repo.transition_task(
            tenant_b, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "user", "id": "intruder"}
        )

    # task must remain untouched under its real tenant
    unchanged = repo.get_task(tenant_a, task["task_id"])
    assert unchanged["status"] == "proposed"


@pytest.mark.integration
def test_conversation_messages_are_strictly_sequential(database_url):
    tenant_id = _create_tenant("tenant-messages")
    conversation = repo.create_conversation(tenant_id, created_by_subject="ceo-1")
    for i in range(5):
        message = repo.append_message(
            tenant_id,
            conversation["conversation_id"],
            author_type="user",
            author_id="ceo-1",
            body=f"message {i}",
        )
        assert message["sequence_no"] == i + 1

    all_messages = repo.list_messages(tenant_id, conversation["conversation_id"])
    assert [m["sequence_no"] for m in all_messages] == [1, 2, 3, 4, 5]

    later = repo.list_messages(tenant_id, conversation["conversation_id"], after_sequence=3)
    assert [m["sequence_no"] for m in later] == [4, 5]


@pytest.mark.integration
def test_handoff_lifecycle_requires_in_progress_before_completed(database_url):
    tenant_id = _create_tenant("tenant-handoff")
    cash_recovery = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    evidence_closure = repo.ensure_agent_installation(tenant_id, "evidence-closure")

    parent_task = repo.create_task(
        tenant_id,
        agent_installation_id=cash_recovery["installation_id"],
        agent_definition_version=1,
        task_type="quantify_recoverable_value",
        objective="Reconcile",
        risk_class="read_only",
        requested_by_type="user",
        requested_by_id="ceo-1",
        idempotency_key="tenant:conv:parent",
    )
    child_task = repo.create_task(
        tenant_id,
        agent_installation_id=evidence_closure["installation_id"],
        agent_definition_version=1,
        task_type="resolve_evidence_gap",
        objective="Resolve citations",
        risk_class="read_only",
        requested_by_type="agent",
        requested_by_id=cash_recovery["installation_id"],
        idempotency_key="tenant:conv:child",
        parent_task_id=parent_task["task_id"],
    )
    handoff = repo.create_handoff(
        tenant_id,
        source_task_id=parent_task["task_id"],
        child_task_id=child_task["task_id"],
        from_agent_installation_id=cash_recovery["installation_id"],
        to_agent_installation_id=evidence_closure["installation_id"],
        reason="Citation coverage is below policy",
        requested_capability="resolve_evidence_gap",
        expected_output_schema="evidence_closure_result.v1",
    )
    assert handoff["status"] == "proposed"

    repo.transition_handoff(
        tenant_id, handoff["handoff_id"], target_status=HandoffStatus.ACCEPTED,
        actor={"type": "agent", "id": evidence_closure["installation_id"]},
    )
    with pytest.raises(InvalidStatusTransition):
        repo.transition_handoff(
            tenant_id, handoff["handoff_id"], target_status=HandoffStatus.COMPLETED,
            actor={"type": "agent", "id": evidence_closure["installation_id"]},
        )
    repo.transition_handoff(
        tenant_id, handoff["handoff_id"], target_status=HandoffStatus.IN_PROGRESS,
        actor={"type": "agent", "id": evidence_closure["installation_id"]},
    )
    completed = repo.transition_handoff(
        tenant_id, handoff["handoff_id"], target_status=HandoffStatus.COMPLETED,
        actor={"type": "agent", "id": evidence_closure["installation_id"]},
    )
    assert completed["status"] == "completed"


@pytest.mark.integration
def test_handoff_rejects_self_reference_at_the_database_level(database_url):
    tenant_id = _create_tenant("tenant-self-handoff")
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
        idempotency_key="tenant:conv:self-handoff",
    )
    psycopg = pytest.importorskip("psycopg")
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.create_handoff(
            tenant_id,
            source_task_id=task["task_id"],
            child_task_id=task["task_id"],
            from_agent_installation_id=installation["installation_id"],
            to_agent_installation_id=installation["installation_id"],
            reason="loop",
            requested_capability="quantify_recoverable_value",
            expected_output_schema="agent_result.v1",
        )


@pytest.mark.integration
def test_approval_decision_requires_pending_status(database_url):
    tenant_id = _create_tenant("tenant-approval")
    installation = repo.ensure_agent_installation(tenant_id, "cash-recovery")
    task = repo.create_task(
        tenant_id,
        agent_installation_id=installation["installation_id"],
        agent_definition_version=1,
        task_type="prepare_board_pack",
        objective="Publish board pack",
        risk_class="write",
        requested_by_type="agent",
        requested_by_id=installation["installation_id"],
        idempotency_key="tenant:conv:approval",
    )
    approval = repo.create_approval_request(
        tenant_id,
        task_id=task["task_id"],
        effect_hash="deadbeef",
        risk_class="write",
        public_explanation="Publish board pack for Q3",
    )
    assert approval["status"] == "pending"

    decided = repo.decide_approval(
        tenant_id, approval["approval_id"], target_status=ApprovalStatus.APPROVED,
        decided_by_subject="reviewer-1", decided_by_role="reviewer",
    )
    assert decided["status"] == "approved"
    assert decided["decided_by_subject"] == "reviewer-1"

    with pytest.raises(InvalidStatusTransition):
        repo.decide_approval(
            tenant_id, approval["approval_id"], target_status=ApprovalStatus.REJECTED,
            decided_by_subject="reviewer-1", decided_by_role="reviewer",
        )


@pytest.mark.integration
def test_unique_active_installation_per_tenant_and_agent_key(database_url):
    tenant_id = _create_tenant("tenant-unique-installation")
    repo.ensure_agent_installation(tenant_id, "cash-recovery")

    psycopg = pytest.importorskip("psycopg")
    connection, skipped = state_store.database_connection()
    with pytest.raises(psycopg.errors.UniqueViolation):
        with connection as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "insert into strategyos_agent_installations (tenant_id, agent_key, agent_definition_version) "
                    "values (%s, %s, %s)",
                    (tenant_id, "cash-recovery", 1),
                )
            conn.commit()
