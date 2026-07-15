"""Append-only domain events and transactional outbox (design doc section 6).

Every state transition in repository.py writes an event row and an outbox
row in the same transaction as the business-record update, using an
optimistic aggregate_version to reject conflicting concurrent transitions.
This module owns only the event/outbox writes and reads; it does not decide
*when* to emit an event -- that decision lives in repository.py's transition
methods so business-record and event writes can never be split across
transactions.

Publishing outbox rows to Hatchet/SSE fan-out (the dispatcher) lands in a
later PR (workflows.py); PR 1 only guarantees events are durably recorded.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ..state_store import fetchone_dict, json_blob, normalize_record


class ConcurrentAggregateModification(Exception):
    """Raised when an event write's expected aggregate_version does not
    match the current version already recorded for that aggregate -- i.e.
    another transaction modified it first."""

    def __init__(self, aggregate_type: str, aggregate_id: str, expected_version: int):
        super().__init__(
            f"aggregate {aggregate_type}:{aggregate_id} is not at expected "
            f"version {expected_version}; concurrent modification"
        )
        self.aggregate_type = aggregate_type
        self.aggregate_id = aggregate_id
        self.expected_version = expected_version


def _stringify_uuids(record: dict[str, Any]) -> dict[str, Any]:
    """normalize_record() only stringifies a small allowlist of key names
    (id/run_id/checkpoint_id/approval_id); every other uuid-typed column
    comes back as a raw psycopg UUID object, which is not JSON-serializable.
    Agent-layer records are returned across a future HTTP API boundary, so
    every UUID must be a plain string regardless of column name."""
    return {
        key: (str(value) if isinstance(value, UUID) else value)
        for key, value in record.items()
    }


def append_event(
    cur: Any,
    *,
    tenant_id: str,
    aggregate_type: str,
    aggregate_id: str,
    expected_version: int,
    event_type: str,
    actor: dict[str, str],
    correlation_id: str,
    causation_id: str | None,
    trace_id: str | None,
    payload: dict[str, Any],
    public_projection: dict[str, Any],
) -> dict[str, Any]:
    """Insert one event at `expected_version` and its outbox row.

    Must be called with `cur` inside the same transaction as the business
    record's own version bump so the two writes commit or roll back
    together. Raises ConcurrentAggregateModification if `expected_version`
    has already been used for this aggregate (unique constraint on
    (aggregate_type, aggregate_id, aggregate_version)).
    """
    try:
        cur.execute(
            """
            insert into strategyos_agent_events_v2
                (tenant_id, aggregate_type, aggregate_id, aggregate_version, event_type,
                 actor_json, correlation_id, causation_id, trace_id, payload_json, public_projection_json)
            values (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, %s::jsonb)
            returning id, tenant_id, aggregate_type, aggregate_id, aggregate_version, event_type,
                      occurred_at, actor_json, correlation_id, causation_id, trace_id,
                      payload_json, public_projection_json
            """,
            (
                tenant_id,
                aggregate_type,
                aggregate_id,
                expected_version,
                event_type,
                json_blob(actor),
                correlation_id,
                causation_id,
                trace_id,
                json_blob(payload),
                json_blob(public_projection),
            ),
        )
    except Exception as exc:
        if _is_unique_violation(exc):
            raise ConcurrentAggregateModification(
                aggregate_type, aggregate_id, expected_version
            ) from exc
        raise
    record = fetchone_dict(cur)
    assert record is not None
    event = _stringify_uuids(normalize_record(record))
    event["event_id"] = event.pop("id")

    cur.execute(
        """
        insert into strategyos_agent_outbox (event_id, destination)
        values (%s, 'hatchet')
        returning id, event_id, destination, publish_attempts, published_at, last_error, created_at
        """,
        (event["event_id"],),
    )
    outbox_record = fetchone_dict(cur)
    assert outbox_record is not None
    event["outbox"] = _stringify_uuids(normalize_record(outbox_record))
    return event


def _is_unique_violation(exc: Exception) -> bool:
    sqlstate = getattr(exc, "sqlstate", None) or getattr(
        getattr(exc, "diag", None), "sqlstate", None
    )
    if sqlstate is not None:
        return sqlstate == "23505"
    return "unique constraint" in str(exc).lower()


def list_events_for_aggregate(
    cur: Any, *, tenant_id: str, aggregate_type: str, aggregate_id: str
) -> list[dict[str, Any]]:
    cur.execute(
        """
        select id, tenant_id, aggregate_type, aggregate_id, aggregate_version, event_type,
               occurred_at, actor_json, correlation_id, causation_id, trace_id,
               payload_json, public_projection_json
        from strategyos_agent_events_v2
        where tenant_id = %s and aggregate_type = %s and aggregate_id = %s
        order by aggregate_version asc
        """,
        (tenant_id, aggregate_type, aggregate_id),
    )
    rows = cur.fetchall()
    columns = [getattr(d, "name", d[0]) for d in (cur.description or [])]
    events = []
    for row in rows:
        record = {column: value for column, value in zip(columns, row, strict=False)}
        normalized = _stringify_uuids(normalize_record(record))
        normalized["event_id"] = normalized.pop("id")
        events.append(normalized)
    return events


def unpublished_outbox_rows(cur: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    """Rows a reconciler/dispatcher (later PR) would re-publish. Exposed here
    so repository/integration tests can assert the outbox row exists without
    reaching into workflows.py, which does not exist yet."""
    cur.execute(
        """
        select o.id, o.event_id, o.destination, o.publish_attempts, o.published_at, o.last_error, o.created_at
        from strategyos_agent_outbox o
        where o.published_at is null
        order by o.created_at asc
        limit %s
        """,
        (limit,),
    )
    rows = cur.fetchall()
    columns = [getattr(d, "name", d[0]) for d in (cur.description or [])]
    return [
        _stringify_uuids(normalize_record({column: value for column, value in zip(columns, row, strict=False)}))
        for row in rows
    ]
