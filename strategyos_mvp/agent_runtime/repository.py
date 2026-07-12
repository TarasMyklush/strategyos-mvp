"""Postgres persistence for the agents layer (design doc sections 5-7).

Follows the pooled-connection pattern in state_store.database_connection():
callers get a (connection, skipped) tuple back and use `with connection as
conn:` themselves, so this module can be exercised with the same
integration-test skip semantics as the rest of the app when DATABASE_URL is
not configured.

Only the transition_* methods here may change task/handoff/approval status
(design doc: "Only the service/repository transition method may change a
status. Direct status updates from API handlers or workers are
prohibited."). Every transition writes its event in the same transaction as
the business-record update via events.append_event().
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any
from uuid import UUID

from ..state_store import database_connection, fetchall_dicts, fetchone_dict, json_blob, normalize_record
from . import events as events_module
from .models import (
    ApprovalStatus,
    HandoffStatus,
    TaskStatus,
    is_approval_transition_allowed,
    is_handoff_transition_allowed,
    is_task_transition_allowed,
)
from .registry import AGENT_DEFINITIONS


class InvalidStatusTransition(Exception):
    def __init__(self, aggregate: str, current: str, target: str):
        super().__init__(f"{aggregate} cannot transition from {current!r} to {target!r}")
        self.aggregate = aggregate
        self.current = current
        self.target = target


class TenantMismatch(Exception):
    """Raised when a lookup by id resolves a row belonging to a different
    tenant than the caller's principal -- prevents cross-tenant reads by
    UUID guessing even though ids are not sequential."""


def _new_correlation_id() -> str:
    return str(uuid.uuid4())


def _stringify_uuids(record: dict[str, Any]) -> dict[str, Any]:
    """See events._stringify_uuids: normalize_record()'s string-coercion
    allowlist is narrow (id/run_id/checkpoint_id/approval_id), so every
    other uuid-typed column must be stringified here for JSON-safety."""
    return {
        key: (str(value) if isinstance(value, UUID) else value)
        for key, value in record.items()
    }


# ---------------------------------------------------------------------------
# Tenant resolution
# ---------------------------------------------------------------------------


def resolve_tenant_id(tenant_slug: str, *, display_name: str | None = None) -> str:
    """Every agent_runtime table's tenant_id column is a UUID FK to
    strategyos_tenants(id), but the authenticated principal only carries a
    slug (state_store.upsert_tenant() hardcodes CONFIG.tenant_slug, which
    assumes a single tenant per deployment -- this resolver is generic over
    any slug so the API layer can convert whatever slug the principal
    carries). Upserts on conflict so repeated calls for the same slug are
    idempotent and never create duplicate tenant rows."""
    connection, skipped = database_connection()
    if skipped is not None:
        raise RuntimeError(skipped.get("reason", "database unavailable"))

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into strategyos_tenants (slug, display_name)
                values (%s, %s)
                on conflict (slug) do update set display_name = coalesce(excluded.display_name, strategyos_tenants.display_name)
                returning id
                """,
                (tenant_slug, display_name or tenant_slug),
            )
            tenant_id = cur.fetchone()[0]
        conn.commit()
    return str(tenant_id)


# ---------------------------------------------------------------------------
# Agent definitions and installations
# ---------------------------------------------------------------------------


def sync_agent_definitions() -> dict[str, Any]:
    """Upsert the code-defined catalogue (registry.AGENT_DEFINITIONS) into
    strategyos_agent_definitions. Idempotent: re-running with unchanged
    definitions is a no-op; changing a definition's fields for an existing
    (agent_key, version) updates that row rather than creating a duplicate,
    since a real "new version" should bump `version` in registry.py."""
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            for definition in AGENT_DEFINITIONS:
                cur.execute(
                    """
                    insert into strategyos_agent_definitions
                        (agent_key, version, display_name, purpose, handler_key, input_schema,
                         output_schema, tool_keys, allowed_roles, max_handoff_depth,
                         default_timeout_seconds, enabled)
                    values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                    on conflict (agent_key, version) do update set
                        display_name = excluded.display_name,
                        purpose = excluded.purpose,
                        handler_key = excluded.handler_key,
                        input_schema = excluded.input_schema,
                        output_schema = excluded.output_schema,
                        tool_keys = excluded.tool_keys,
                        allowed_roles = excluded.allowed_roles,
                        max_handoff_depth = excluded.max_handoff_depth,
                        default_timeout_seconds = excluded.default_timeout_seconds,
                        enabled = excluded.enabled
                    """,
                    (
                        definition.agent_key,
                        definition.version,
                        definition.display_name,
                        definition.purpose,
                        definition.handler_key,
                        definition.input_schema,
                        definition.output_schema,
                        json_blob(list(definition.tool_keys)),
                        json_blob(list(definition.allowed_roles)),
                        definition.max_handoff_depth,
                        definition.default_timeout_seconds,
                        definition.enabled,
                    ),
                )
        conn.commit()
    return {"status": "synced", "count": len(AGENT_DEFINITIONS)}


def ensure_agent_installation(tenant_id: str, agent_key: str, *, version: int | None = None) -> dict[str, Any]:
    """Activate `agent_key` for `tenant_id`, or return the existing active
    installation. Enforces the unique-active-per-(tenant,agent_key) index by
    checking first rather than relying on a races-prone upsert, since the
    partial unique index has no natural ON CONFLICT target.

    `version` defaults to the registry's current version for this agent_key
    (not a hardcoded 1) -- BOARD_PACK moved to v2 in PR 6, and a caller that
    didn't pass a version would otherwise silently install every new
    installation pinned to v1 forever, permanently missing v2's
    publication.release tool."""
    if version is None:
        from .registry import AGENT_DEFINITIONS_BY_KEY

        definition = AGENT_DEFINITIONS_BY_KEY.get(agent_key)
        version = definition.version if definition is not None else 1

    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, tenant_id, agent_key, agent_definition_version, active, config_json, created_at, updated_at
                from strategyos_agent_installations
                where tenant_id = %s and agent_key = %s and active
                """,
                (tenant_id, agent_key),
            )
            existing = fetchone_dict(cur)
            if existing is not None:
                conn.commit()
                return _normalize_installation(existing)

            cur.execute(
                """
                insert into strategyos_agent_installations (tenant_id, agent_key, agent_definition_version)
                values (%s, %s, %s)
                returning id, tenant_id, agent_key, agent_definition_version, active, config_json, created_at, updated_at
                """,
                (tenant_id, agent_key, version),
            )
            record = fetchone_dict(cur)
        conn.commit()
    assert record is not None
    return _normalize_installation(record)


def _normalize_installation(record: dict[str, Any]) -> dict[str, Any]:
    normalized = _stringify_uuids(normalize_record(record))
    normalized["installation_id"] = normalized.pop("id")
    return normalized


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


def create_conversation(
    tenant_id: str,
    *,
    created_by_subject: str,
    persona: str | None = None,
    run_id: str | None = None,
    finding_id: str | None = None,
    classification: str = "restricted",
) -> dict[str, Any]:
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into strategyos_agent_conversations
                    (tenant_id, created_by_subject, persona, run_id, finding_id, classification)
                values (%s, %s, %s, %s, %s, %s)
                returning id, tenant_id, created_by_subject, persona, run_id, finding_id,
                          board_state, classification, archived_at, created_at, updated_at
                """,
                (tenant_id, created_by_subject, persona, run_id, finding_id, classification),
            )
            record = fetchone_dict(cur)
            conversation_id = record["id"]
            cur.execute(
                """
                insert into strategyos_agent_participants (conversation_id, participant_type, participant_id)
                values (%s, 'user', %s)
                on conflict do nothing
                """,
                (conversation_id, created_by_subject),
            )
        conn.commit()
    assert record is not None
    normalized = _stringify_uuids(normalize_record(record))
    normalized["conversation_id"] = normalized.pop("id")
    return normalized


def get_conversation(tenant_id: str, conversation_id: str) -> dict[str, Any] | None:
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, tenant_id, created_by_subject, persona, run_id, finding_id,
                       board_state, classification, archived_at, created_at, updated_at
                from strategyos_agent_conversations
                where id = %s and tenant_id = %s
                """,
                (conversation_id, tenant_id),
            )
            record = fetchone_dict(cur)
        conn.commit()
    if record is None:
        return None
    normalized = _stringify_uuids(normalize_record(record))
    normalized["conversation_id"] = normalized.pop("id")
    return normalized


def archive_conversation(tenant_id: str, conversation_id: str) -> dict[str, Any] | None:
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update strategyos_agent_conversations
                set archived_at = coalesce(archived_at, now()), updated_at = now()
                where id = %s and tenant_id = %s
                returning id, tenant_id, created_by_subject, persona, run_id, finding_id,
                          board_state, classification, archived_at, created_at, updated_at
                """,
                (conversation_id, tenant_id),
            )
            record = fetchone_dict(cur)
        conn.commit()
    if record is None:
        return None
    normalized = _stringify_uuids(normalize_record(record))
    normalized["conversation_id"] = normalized.pop("id")
    return normalized


def append_message(
    tenant_id: str,
    conversation_id: str,
    *,
    author_type: str,
    author_id: str,
    body: str,
    metadata: dict[str, Any] | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Insert the next message in monotonic sequence order for the
    conversation. Uses a row lock on the conversation to serialize
    sequence-number assignment under concurrent writers."""
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id from strategyos_agent_conversations where id = %s and tenant_id = %s for update",
                (conversation_id, tenant_id),
            )
            if cur.fetchone() is None:
                conn.rollback()
                raise TenantMismatch(f"conversation {conversation_id} not found for tenant {tenant_id}")

            cur.execute(
                "select coalesce(max(sequence_no), 0) + 1 from strategyos_agent_messages where conversation_id = %s",
                (conversation_id,),
            )
            next_sequence = cur.fetchone()[0]

            cur.execute(
                """
                insert into strategyos_agent_messages
                    (tenant_id, conversation_id, sequence_no, author_type, author_id, body, metadata_json, task_id)
                values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                returning id, tenant_id, conversation_id, sequence_no, author_type, author_id, body,
                          metadata_json, task_id, created_at
                """,
                (
                    tenant_id,
                    conversation_id,
                    next_sequence,
                    author_type,
                    author_id,
                    body,
                    json_blob(metadata or {}),
                    task_id,
                ),
            )
            record = fetchone_dict(cur)
            cur.execute(
                """
                update strategyos_agent_conversations set updated_at = now() where id = %s
                """,
                (conversation_id,),
            )
        conn.commit()
    assert record is not None
    normalized = _stringify_uuids(normalize_record(record))
    normalized["message_id"] = normalized.pop("id")
    return normalized


def list_messages(
    tenant_id: str, conversation_id: str, *, after_sequence: int = 0
) -> list[dict[str, Any]]:
    connection, skipped = database_connection()
    if skipped is not None:
        return []

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, tenant_id, conversation_id, sequence_no, author_type, author_id, body,
                       metadata_json, task_id, created_at
                from strategyos_agent_messages
                where conversation_id = %s and tenant_id = %s and sequence_no > %s
                order by sequence_no asc
                """,
                (conversation_id, tenant_id, after_sequence),
            )
            rows = cur.fetchall()
            columns = [getattr(d, "name", d[0]) for d in (cur.description or [])]
        conn.commit()
    messages = []
    for row in rows:
        record = {column: value for column, value in zip(columns, row, strict=False)}
        normalized = _stringify_uuids(normalize_record(record))
        normalized["message_id"] = normalized.pop("id")
        messages.append(normalized)
    return messages


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def create_task(
    tenant_id: str,
    *,
    agent_installation_id: str,
    agent_definition_version: int,
    task_type: str,
    objective: str,
    risk_class: str,
    requested_by_type: str,
    requested_by_id: str,
    idempotency_key: str,
    conversation_id: str | None = None,
    parent_task_id: str | None = None,
    input: dict[str, Any] | None = None,
    context_manifest: dict[str, Any] | None = None,
    deadline_at: str | None = None,
    initial_status: TaskStatus = TaskStatus.PROPOSED,
) -> dict[str, Any]:
    """Create a task at `initial_status` (default `proposed`) and its
    creation event, atomically. Re-submitting the same
    (tenant_id, idempotency_key) returns the existing task unchanged instead
    of raising, so callers can retry a command safely."""
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id from strategyos_agent_tasks where tenant_id = %s and idempotency_key = %s
                """,
                (tenant_id, idempotency_key),
            )
            existing = cur.fetchone()
            if existing is not None:
                conn.commit()
                return get_task(tenant_id, str(existing[0]))

            cur.execute(
                """
                insert into strategyos_agent_tasks
                    (tenant_id, conversation_id, parent_task_id, agent_installation_id,
                     agent_definition_version, task_type, objective, input_json, context_manifest_json,
                     risk_class, status, requested_by_type, requested_by_id, idempotency_key, deadline_at,
                     aggregate_version)
                values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, 1)
                returning id, tenant_id, conversation_id, parent_task_id, agent_installation_id,
                          agent_definition_version, task_type, objective, input_json, context_manifest_json,
                          risk_class, status, requested_by_type, requested_by_id, idempotency_key,
                          deadline_at, result_json, failure_code, failure_detail_public, aggregate_version,
                          created_at, updated_at, started_at, finished_at
                """,
                (
                    tenant_id,
                    conversation_id,
                    parent_task_id,
                    agent_installation_id,
                    agent_definition_version,
                    task_type,
                    objective,
                    json_blob(input or {}),
                    json_blob(context_manifest or {}),
                    risk_class,
                    initial_status.value,
                    requested_by_type,
                    requested_by_id,
                    idempotency_key,
                    deadline_at,
                ),
            )
            record = fetchone_dict(cur)
            assert record is not None
            task_id = str(record["id"])

            events_module.append_event(
                cur,
                tenant_id=tenant_id,
                aggregate_type="agent_task",
                aggregate_id=task_id,
                expected_version=1,
                event_type=f"agent.task.{initial_status.value}.v1",
                actor={"type": requested_by_type, "id": requested_by_id},
                correlation_id=_new_correlation_id(),
                causation_id=None,
                trace_id=None,
                payload={"task_type": task_type, "risk_class": risk_class},
                public_projection={"status": initial_status.value, "objective": objective},
            )
        conn.commit()
    return _normalize_task(record)


def get_task(tenant_id: str, task_id: str) -> dict[str, Any] | None:
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, tenant_id, conversation_id, parent_task_id, agent_installation_id,
                       agent_definition_version, task_type, objective, input_json, context_manifest_json,
                       risk_class, status, requested_by_type, requested_by_id, idempotency_key,
                       deadline_at, result_json, failure_code, failure_detail_public, aggregate_version,
                       created_at, updated_at, started_at, finished_at
                from strategyos_agent_tasks
                where id = %s and tenant_id = %s
                """,
                (task_id, tenant_id),
            )
            record = fetchone_dict(cur)
        conn.commit()
    if record is None:
        return None
    return _normalize_task(record)


def _normalize_task(record: dict[str, Any]) -> dict[str, Any]:
    normalized = _stringify_uuids(normalize_record(record))
    normalized["task_id"] = normalized.pop("id")
    return normalized


def transition_task(
    tenant_id: str,
    task_id: str,
    *,
    target_status: TaskStatus,
    actor: dict[str, str],
    result: dict[str, Any] | None = None,
    failure_code: str | None = None,
    failure_detail_public: str | None = None,
    causation_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """The only sanctioned way to change a task's status. Validates the
    transition against models.TASK_STATUS_TRANSITIONS, bumps
    aggregate_version, and writes the event in the same transaction."""
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select status, aggregate_version from strategyos_agent_tasks
                where id = %s and tenant_id = %s
                for update
                """,
                (task_id, tenant_id),
            )
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                raise TenantMismatch(f"task {task_id} not found for tenant {tenant_id}")
            current_status = TaskStatus(row[0])
            current_version = row[1]

            if not is_task_transition_allowed(current_status, target_status):
                conn.rollback()
                raise InvalidStatusTransition("agent_task", current_status.value, target_status.value)

            next_version = current_version + 1
            set_started = target_status == TaskStatus.RUNNING and current_status != TaskStatus.RUNNING
            set_finished = target_status in {
                TaskStatus.SUCCEEDED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
                TaskStatus.TIMED_OUT,
            }

            cur.execute(
                f"""
                update strategyos_agent_tasks
                set status = %s,
                    aggregate_version = %s,
                    result_json = coalesce(%s::jsonb, result_json),
                    failure_code = coalesce(%s, failure_code),
                    failure_detail_public = coalesce(%s, failure_detail_public),
                    updated_at = now()
                    {", started_at = now()" if set_started else ""}
                    {", finished_at = now()" if set_finished else ""}
                where id = %s and tenant_id = %s
                returning id, tenant_id, conversation_id, parent_task_id, agent_installation_id,
                          agent_definition_version, task_type, objective, input_json, context_manifest_json,
                          risk_class, status, requested_by_type, requested_by_id, idempotency_key,
                          deadline_at, result_json, failure_code, failure_detail_public, aggregate_version,
                          created_at, updated_at, started_at, finished_at
                """,
                (
                    target_status.value,
                    next_version,
                    json_blob(result) if result is not None else None,
                    failure_code,
                    failure_detail_public,
                    task_id,
                    tenant_id,
                ),
            )
            record = fetchone_dict(cur)
            assert record is not None

            events_module.append_event(
                cur,
                tenant_id=tenant_id,
                aggregate_type="agent_task",
                aggregate_id=task_id,
                expected_version=next_version,
                event_type=f"agent.task.{target_status.value}.v1",
                actor=actor,
                correlation_id=_new_correlation_id(),
                causation_id=causation_id,
                trace_id=trace_id,
                payload={"from_status": current_status.value, "to_status": target_status.value},
                public_projection={"status": target_status.value},
            )
        conn.commit()
    return _normalize_task(record)


# ---------------------------------------------------------------------------
# Handoffs
# ---------------------------------------------------------------------------


def create_handoff(
    tenant_id: str,
    *,
    source_task_id: str,
    child_task_id: str,
    from_agent_installation_id: str,
    to_agent_installation_id: str,
    reason: str,
    requested_capability: str,
    expected_output_schema: str,
    input: dict[str, Any] | None = None,
    deadline_at: str | None = None,
    actor: dict[str, str] | None = None,
) -> dict[str, Any]:
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into strategyos_agent_handoffs
                    (tenant_id, source_task_id, child_task_id, from_agent_installation_id,
                     to_agent_installation_id, reason, requested_capability, input_json,
                     expected_output_schema, status, deadline_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                returning id, tenant_id, source_task_id, child_task_id, from_agent_installation_id,
                          to_agent_installation_id, reason, requested_capability, input_json,
                          expected_output_schema, status, deadline_at, created_at, updated_at
                """,
                (
                    tenant_id,
                    source_task_id,
                    child_task_id,
                    from_agent_installation_id,
                    to_agent_installation_id,
                    reason,
                    requested_capability,
                    json_blob(input or {}),
                    expected_output_schema,
                    HandoffStatus.PROPOSED.value,
                    deadline_at,
                ),
            )
            record = fetchone_dict(cur)
            assert record is not None
            handoff_id = str(record["id"])

            events_module.append_event(
                cur,
                tenant_id=tenant_id,
                aggregate_type="agent_handoff",
                aggregate_id=handoff_id,
                expected_version=1,
                event_type="agent.handoff.proposed.v1",
                actor=actor or {"type": "agent", "id": from_agent_installation_id},
                correlation_id=_new_correlation_id(),
                causation_id=source_task_id,
                trace_id=None,
                payload={"requested_capability": requested_capability, "child_task_id": child_task_id},
                public_projection={"status": HandoffStatus.PROPOSED.value},
            )
        conn.commit()
    return _normalize_handoff(record)


def get_handoff(tenant_id: str, handoff_id: str) -> dict[str, Any] | None:
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, tenant_id, source_task_id, child_task_id, from_agent_installation_id,
                       to_agent_installation_id, reason, requested_capability, input_json,
                       expected_output_schema, status, deadline_at, created_at, updated_at
                from strategyos_agent_handoffs
                where id = %s and tenant_id = %s
                """,
                (handoff_id, tenant_id),
            )
            record = fetchone_dict(cur)
        conn.commit()
    if record is None:
        return None
    return _normalize_handoff(record)


def _normalize_handoff(record: dict[str, Any]) -> dict[str, Any]:
    normalized = _stringify_uuids(normalize_record(record))
    normalized["handoff_id"] = normalized.pop("id")
    return normalized


def find_root_task_id(tenant_id: str, task_id: str) -> str:
    """Walks parent_task_id up to the root. Used by handoff budget checks
    (design doc section 15: budgets are enforced "per root task")."""
    connection, skipped = database_connection()
    if skipped is not None:
        return task_id

    assert connection is not None
    current_id = task_id
    with connection as conn:
        with conn.cursor() as cur:
            for _ in range(50):  # hard bound: never loop forever on bad data
                cur.execute(
                    "select parent_task_id::text from strategyos_agent_tasks where id = %s and tenant_id = %s",
                    (current_id, tenant_id),
                )
                row = cur.fetchone()
                if row is None or row[0] is None:
                    break
                current_id = row[0]
        conn.commit()
    return current_id


def handoff_depth_for_task(tenant_id: str, task_id: str) -> int:
    """Counts ancestor hops from `task_id` back to its root via
    parent_task_id -- the depth a new handoff FROM this task would be
    created at."""
    connection, skipped = database_connection()
    if skipped is not None:
        return 0

    assert connection is not None
    depth = 0
    current_id = task_id
    with connection as conn:
        with conn.cursor() as cur:
            for _ in range(50):
                cur.execute(
                    "select parent_task_id::text from strategyos_agent_tasks where id = %s and tenant_id = %s",
                    (current_id, tenant_id),
                )
                row = cur.fetchone()
                if row is None or row[0] is None:
                    break
                depth += 1
                current_id = row[0]
        conn.commit()
    return depth


def count_tasks_under_root(tenant_id: str, root_task_id: str) -> int:
    """Counts every task descended from (or equal to) root_task_id, using a
    recursive CTE over parent_task_id -- the child-task-count budget check."""
    connection, skipped = database_connection()
    if skipped is not None:
        return 0

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                with recursive descendants as (
                    select id from strategyos_agent_tasks where id = %s and tenant_id = %s
                    union all
                    select t.id from strategyos_agent_tasks t
                    join descendants d on t.parent_task_id = d.id
                    where t.tenant_id = %s
                )
                select count(*) from descendants
                """,
                (root_task_id, tenant_id, tenant_id),
            )
            count = cur.fetchone()[0]
        conn.commit()
    return int(count)


def prior_handoff_signatures_for_root(tenant_id: str, root_task_id: str) -> frozenset[tuple[str, str, str]]:
    """Returns (to_agent installation's agent_key, requested_capability,
    scope_hash) for every handoff already created under this root task's
    tree -- used by policy.check_handoff_budget's loop-prevention check.
    scope_hash is derived by the caller from the handoff's input, not
    stored separately, so this reads input_json and lets the caller hash it
    consistently with how it hashes the new proposed handoff's scope."""
    connection, skipped = database_connection()
    if skipped is not None:
        return frozenset()

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                with recursive descendants as (
                    select id from strategyos_agent_tasks where id = %s and tenant_id = %s
                    union all
                    select t.id from strategyos_agent_tasks t
                    join descendants d on t.parent_task_id = d.id
                    where t.tenant_id = %s
                )
                select ai.agent_key, h.requested_capability, h.input_json
                from strategyos_agent_handoffs h
                join strategyos_agent_installations ai on ai.id = h.to_agent_installation_id
                where h.source_task_id in (select id from descendants) and h.tenant_id = %s
                """,
                (root_task_id, tenant_id, tenant_id, tenant_id),
            )
            rows = cur.fetchall()
        conn.commit()
    signatures = set()
    for agent_key, capability, input_json in rows:
        scope_hash = hash_scope(input_json or {})
        signatures.add((agent_key, capability, scope_hash))
    return frozenset(signatures)


def hash_scope(scope: dict[str, Any]) -> str:
    """Canonical hash for a task/handoff input scope, used both when reading
    prior handoff signatures and when checking a new proposed handoff
    against them -- callers on both sides must use this function so the
    hashes are comparable."""
    canonical = json.dumps(scope, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def transition_handoff(
    tenant_id: str,
    handoff_id: str,
    *,
    target_status: HandoffStatus,
    actor: dict[str, str],
    causation_id: str | None = None,
) -> dict[str, Any]:
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status from strategyos_agent_handoffs where id = %s and tenant_id = %s for update",
                (handoff_id, tenant_id),
            )
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                raise TenantMismatch(f"handoff {handoff_id} not found for tenant {tenant_id}")
            current_status = HandoffStatus(row[0])

            if not is_handoff_transition_allowed(current_status, target_status):
                conn.rollback()
                raise InvalidStatusTransition("agent_handoff", current_status.value, target_status.value)

            cur.execute(
                """
                update strategyos_agent_handoffs
                set status = %s, updated_at = now()
                where id = %s and tenant_id = %s
                returning id, tenant_id, source_task_id, child_task_id, from_agent_installation_id,
                          to_agent_installation_id, reason, requested_capability, input_json,
                          expected_output_schema, status, deadline_at, created_at, updated_at
                """,
                (target_status.value, handoff_id, tenant_id),
            )
            record = fetchone_dict(cur)
            assert record is not None

            cur.execute(
                """
                select count(*) from strategyos_agent_events_v2
                where aggregate_type = 'agent_handoff' and aggregate_id = %s
                """,
                (handoff_id,),
            )
            next_version = cur.fetchone()[0] + 1

            events_module.append_event(
                cur,
                tenant_id=tenant_id,
                aggregate_type="agent_handoff",
                aggregate_id=handoff_id,
                expected_version=next_version,
                event_type=f"agent.handoff.{target_status.value}.v1",
                actor=actor,
                correlation_id=_new_correlation_id(),
                causation_id=causation_id,
                trace_id=None,
                payload={"from_status": current_status.value, "to_status": target_status.value},
                public_projection={"status": target_status.value},
            )
        conn.commit()
    return _normalize_handoff(record)


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


def create_approval_request(
    tenant_id: str,
    *,
    task_id: str,
    effect_hash: str,
    risk_class: str,
    public_explanation: str,
    linked_approval_id: str | None = None,
    expires_at: str | None = None,
    actor: dict[str, str] | None = None,
) -> dict[str, Any]:
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into strategyos_agent_approval_requests
                    (tenant_id, task_id, linked_approval_id, effect_hash, risk_class,
                     public_explanation, status, expires_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                returning id, tenant_id, task_id, linked_approval_id, effect_hash, risk_class,
                          public_explanation, status, decided_by_subject, decided_by_role,
                          decision_comment, created_at, decided_at, expires_at
                """,
                (
                    tenant_id,
                    task_id,
                    linked_approval_id,
                    effect_hash,
                    risk_class,
                    public_explanation,
                    ApprovalStatus.PENDING.value,
                    expires_at,
                ),
            )
            record = fetchone_dict(cur)
            assert record is not None
            approval_id = str(record["id"])

            events_module.append_event(
                cur,
                tenant_id=tenant_id,
                aggregate_type="agent_approval",
                aggregate_id=approval_id,
                expected_version=1,
                event_type="agent.approval.pending.v1",
                actor=actor or {"type": "system", "id": "policy"},
                correlation_id=_new_correlation_id(),
                causation_id=task_id,
                trace_id=None,
                payload={"effect_hash": effect_hash, "risk_class": risk_class},
                public_projection={"status": ApprovalStatus.PENDING.value},
            )
        conn.commit()
    return _normalize_approval(record)


def get_approval_request(tenant_id: str, approval_id: str) -> dict[str, Any] | None:
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, tenant_id, task_id, linked_approval_id, effect_hash, risk_class,
                       public_explanation, status, decided_by_subject, decided_by_role,
                       decision_comment, created_at, decided_at, expires_at
                from strategyos_agent_approval_requests
                where id = %s and tenant_id = %s
                """,
                (approval_id, tenant_id),
            )
            record = fetchone_dict(cur)
        conn.commit()
    if record is None:
        return None
    return _normalize_approval(record)


def _normalize_approval(record: dict[str, Any]) -> dict[str, Any]:
    normalized = _stringify_uuids(normalize_record(record))
    normalized["approval_id"] = normalized.pop("id")
    return normalized


def list_approval_requests(tenant_id: str, *, status: str | None = "pending", limit: int = 100) -> list[dict[str, Any]]:
    connection, skipped = database_connection()
    if skipped is not None:
        return []

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            if status:
                cur.execute(
                    """
                    select id, tenant_id, task_id, linked_approval_id, effect_hash, risk_class,
                           public_explanation, status, decided_by_subject, decided_by_role,
                           decision_comment, created_at, decided_at, expires_at
                    from strategyos_agent_approval_requests
                    where tenant_id = %s and status = %s
                    order by created_at desc
                    limit %s
                    """,
                    (tenant_id, status, limit),
                )
            else:
                cur.execute(
                    """
                    select id, tenant_id, task_id, linked_approval_id, effect_hash, risk_class,
                           public_explanation, status, decided_by_subject, decided_by_role,
                           decision_comment, created_at, decided_at, expires_at
                    from strategyos_agent_approval_requests
                    where tenant_id = %s
                    order by created_at desc
                    limit %s
                    """,
                    (tenant_id, limit),
                )
            rows = fetchall_dicts(cur)
        conn.commit()
    return [_normalize_approval(row) for row in rows]


def decide_approval(
    tenant_id: str,
    approval_id: str,
    *,
    target_status: ApprovalStatus,
    decided_by_subject: str,
    decided_by_role: str,
    decision_comment: str | None = None,
) -> dict[str, Any]:
    """Record a human approval decision. No model output can reach this
    method directly -- callers in the API layer (a later PR) must resolve
    decided_by_subject/role from the authenticated principal, never from
    request-body-supplied identity."""
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status from strategyos_agent_approval_requests where id = %s and tenant_id = %s for update",
                (approval_id, tenant_id),
            )
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                raise TenantMismatch(f"approval {approval_id} not found for tenant {tenant_id}")
            current_status = ApprovalStatus(row[0])

            if not is_approval_transition_allowed(current_status, target_status):
                conn.rollback()
                raise InvalidStatusTransition("agent_approval", current_status.value, target_status.value)

            cur.execute(
                """
                update strategyos_agent_approval_requests
                set status = %s, decided_by_subject = %s, decided_by_role = %s,
                    decision_comment = %s, decided_at = now()
                where id = %s and tenant_id = %s
                returning id, tenant_id, task_id, linked_approval_id, effect_hash, risk_class,
                          public_explanation, status, decided_by_subject, decided_by_role,
                          decision_comment, created_at, decided_at, expires_at
                """,
                (target_status.value, decided_by_subject, decided_by_role, decision_comment, approval_id, tenant_id),
            )
            record = fetchone_dict(cur)
            assert record is not None

            cur.execute(
                """
                select count(*) from strategyos_agent_events_v2
                where aggregate_type = 'agent_approval' and aggregate_id = %s
                """,
                (approval_id,),
            )
            next_version = cur.fetchone()[0] + 1

            events_module.append_event(
                cur,
                tenant_id=tenant_id,
                aggregate_type="agent_approval",
                aggregate_id=approval_id,
                expected_version=next_version,
                event_type=f"agent.approval.{target_status.value}.v1",
                actor={"type": "user", "id": decided_by_subject},
                correlation_id=_new_correlation_id(),
                causation_id=None,
                trace_id=None,
                payload={"decided_by_role": decided_by_role},
                public_projection={"status": target_status.value},
            )
        conn.commit()
    return _normalize_approval(record)


# ---------------------------------------------------------------------------
# Task attempts (design doc: "task, attempt, and agent IDs" on the
# capability token; strategyos_agent_task_attempts, PR 7)
# ---------------------------------------------------------------------------


def create_task_attempt(
    tenant_id: str,
    task_id: str,
    *,
    worker_id: str,
    context_manifest_hash: str | None = None,
) -> dict[str, Any]:
    """Inserts the next attempt row for a task, with attempt_no computed as
    max(existing attempt_no) + 1 under a row lock scoped to this task_id --
    the row lock (not a client-side read-then-insert) is what keeps this
    correct if two workers ever raced to claim the same task (they can't,
    because transition_task's queued->running compare-and-set already
    prevents that, but attempt_no numbering doesn't rely on that guarantee
    holding forever)."""
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            # Advisory-free row lock via `for update` on the parent task
            # row -- there is no attempts row to lock before the first
            # attempt exists, so lock the task itself to serialize
            # attempt-number assignment.
            cur.execute(
                "select id from strategyos_agent_tasks where id = %s and tenant_id = %s for update",
                (task_id, tenant_id),
            )
            if cur.fetchone() is None:
                conn.rollback()
                raise TenantMismatch(f"task {task_id} not found for tenant {tenant_id}")

            cur.execute(
                "select coalesce(max(attempt_no), 0) + 1 from strategyos_agent_task_attempts where task_id = %s",
                (task_id,),
            )
            next_attempt_no = cur.fetchone()[0]

            cur.execute(
                """
                insert into strategyos_agent_task_attempts (task_id, attempt_no, worker_id, status, context_manifest_hash)
                values (%s, %s, %s, 'running', %s)
                returning id, task_id, attempt_no, worker_id, model_provider, model_name, prompt_version,
                          context_manifest_hash, status, error_code, error_detail_restricted, started_at, finished_at
                """,
                (task_id, next_attempt_no, worker_id, context_manifest_hash),
            )
            record = fetchone_dict(cur)
        conn.commit()
    assert record is not None
    normalized = _stringify_uuids(normalize_record(record))
    normalized["task_attempt_id"] = normalized.pop("id")
    return normalized


def finish_task_attempt(
    tenant_id: str,
    task_attempt_id: str,
    *,
    status: str,
    error_code: str | None = None,
    error_detail_restricted: str | None = None,
) -> dict[str, Any]:
    """error_detail_restricted is exactly that -- restricted. Never surface
    it through a public-safe API response; only failure_detail_public on
    the task itself is safe for that (design doc section 8: "Internal
    exception text belongs in restricted logs/attempt metadata.")."""
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update strategyos_agent_task_attempts
                set status = %s, error_code = %s, error_detail_restricted = %s, finished_at = now()
                where id = %s and task_id in (select id from strategyos_agent_tasks where tenant_id = %s)
                returning id, task_id, attempt_no, worker_id, model_provider, model_name, prompt_version,
                          context_manifest_hash, status, error_code, error_detail_restricted, started_at, finished_at
                """,
                (status, error_code, error_detail_restricted, task_attempt_id, tenant_id),
            )
            record = fetchone_dict(cur)
        conn.commit()
    if record is None:
        raise TenantMismatch(f"task attempt {task_attempt_id} not found for tenant {tenant_id}")
    normalized = _stringify_uuids(normalize_record(record))
    normalized["task_attempt_id"] = normalized.pop("id")
    return normalized


# ---------------------------------------------------------------------------
# Tool invocations and effect-key reservation (design doc section 14 step 5:
# "External-effect tools reserve a unique effect key before execution",
# section 11: "At-least-once execution, effectively-once effects.")
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Artifact links (design doc: "Task/message links to evidence and
# artifacts"). Used by remediation.propose as its actual durable effect --
# an agent_runtime-owned record, never a write into a pipeline-owned table
# like strategyos_findings.
# ---------------------------------------------------------------------------


def create_artifact_link(
    tenant_id: str, *, task_id: str | None = None, message_id: str | None = None,
    reference_type: str, reference_id: str,
) -> dict[str, Any]:
    if task_id is None and message_id is None:
        raise ValueError("create_artifact_link requires task_id or message_id")

    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into strategyos_agent_artifact_links (tenant_id, task_id, message_id, reference_type, reference_id)
                values (%s, %s, %s, %s, %s)
                returning id, tenant_id, task_id, message_id, reference_type, reference_id, created_at
                """,
                (tenant_id, task_id, message_id, reference_type, reference_id),
            )
            record = fetchone_dict(cur)
        conn.commit()
    assert record is not None
    normalized = _stringify_uuids(normalize_record(record))
    normalized["artifact_link_id"] = normalized.pop("id")
    return normalized


class EffectAlreadyReserved(Exception):
    """Raised by reserve_tool_effect when (tenant_id, effect_key) already
    has a row -- the caller must treat this as "already handled", not as an
    error to retry past. This is the mechanism that turns at-least-once
    task execution into effectively-once side effects."""

    def __init__(self, existing_invocation: dict[str, Any]):
        super().__init__(
            f"effect_key already reserved by tool_invocation {existing_invocation.get('tool_invocation_id')} "
            f"(status={existing_invocation.get('status')})"
        )
        self.existing_invocation = existing_invocation


def reserve_tool_effect(
    tenant_id: str,
    task_id: str,
    *,
    task_attempt_id: str | None,
    tool_key: str,
    tool_version: str,
    input_hash: str,
    effect_key: str,
) -> dict[str, Any]:
    """Inserts a `pending` tool_invocations row keyed on
    (tenant_id, effect_key) BEFORE the tool's actual side effect executes.
    If a row with this effect_key already exists (a retry of a task whose
    prior attempt reserved the effect but crashed before or after applying
    it), raises EffectAlreadyReserved with the existing row instead of
    inserting a duplicate -- the caller must not re-apply the effect, only
    decide whether to wait/re-check/report based on the existing row's
    status. record_tool_invocation_result() completes the row once the
    actual call (success or failure) is known."""
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, tenant_id, task_id, task_attempt_id, tool_key, tool_version, input_hash,
                       output_hash, effect_key, status, error_code, created_at, completed_at
                from strategyos_agent_tool_invocations
                where tenant_id = %s and effect_key = %s
                """,
                (tenant_id, effect_key),
            )
            existing = fetchone_dict(cur)
            if existing is not None:
                conn.commit()
                normalized_existing = _stringify_uuids(normalize_record(existing))
                normalized_existing["tool_invocation_id"] = normalized_existing.pop("id")
                raise EffectAlreadyReserved(normalized_existing)

            cur.execute(
                """
                insert into strategyos_agent_tool_invocations
                    (tenant_id, task_id, task_attempt_id, tool_key, tool_version, input_hash, effect_key, status)
                values (%s, %s, %s, %s, %s, %s, %s, 'pending')
                returning id, tenant_id, task_id, task_attempt_id, tool_key, tool_version, input_hash,
                          output_hash, effect_key, status, error_code, created_at, completed_at
                """,
                (tenant_id, task_id, task_attempt_id, tool_key, tool_version, input_hash, effect_key),
            )
            record = fetchone_dict(cur)
        conn.commit()
    assert record is not None
    normalized = _stringify_uuids(normalize_record(record))
    normalized["tool_invocation_id"] = normalized.pop("id")
    return normalized


def record_tool_invocation_result(
    tenant_id: str,
    tool_invocation_id: str,
    *,
    status: str,
    output_hash: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update strategyos_agent_tool_invocations
                set status = %s, output_hash = %s, error_code = %s, completed_at = now()
                where id = %s and tenant_id = %s
                returning id, tenant_id, task_id, task_attempt_id, tool_key, tool_version, input_hash,
                          output_hash, effect_key, status, error_code, created_at, completed_at
                """,
                (status, output_hash, error_code, tool_invocation_id, tenant_id),
            )
            record = fetchone_dict(cur)
        conn.commit()
    if record is None:
        raise TenantMismatch(f"tool invocation {tool_invocation_id} not found for tenant {tenant_id}")
    normalized = _stringify_uuids(normalize_record(record))
    normalized["tool_invocation_id"] = normalized.pop("id")
    return normalized
