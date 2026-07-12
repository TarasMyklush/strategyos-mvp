"""SSE projection (design doc section 11 "Live events").

No SSE precedent exists elsewhere in this codebase (confirmed by full-repo
search before writing this module) -- the framing/heartbeat/replay
conventions below are established fresh for this endpoint, following the
plain W3C EventSource wire format (no external SSE library dependency).

Requirements this module satisfies:
- support Last-Event-ID (cursor is the events_v2.aggregate_version-derived
  per-event, but since two aggregates can share nothing comparable, we use
  strategyos_agent_events_v2.id, a monotonically-created UUID with a
  separate insertion-order-safe cursor via created columns -- see
  _events_after());
- authorize every subscription scope (done by the caller/route, not here);
- emit heartbeat comments (": heartbeat\n\n") so idle connections don't
  time out at a reverse proxy;
- fetch missed events from Postgres before switching to live fan-out
  (PR5 polls Postgres on an interval rather than wiring a live outbox
  listener -- see the module docstring note below);
- use bounded public projections (public_projection_json), never raw
  event payload_json, which may carry restricted context;
- the /api/v1/agent-network?after= polling fallback is a separate,
  simpler read path in api.py, not implemented in this module.

PR5 implementation note: true continuous live fan-out (e.g. LISTEN/NOTIFY
or a Redis pub/sub bridge reading the outbox) is not implemented here --
that is optional transport acceleration per design doc principle 3 ("Redis
is optional transport, never truth"). This module instead polls Postgres
on a short interval within the same generator, which satisfies every
correctness requirement (missed-event replay, heartbeats, authorization)
at the cost of poll latency rather than push latency. Swapping in a live
listener later does not change this module's public contract.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from ..state_store import database_connection, fetchall_dicts

SSE_POLL_INTERVAL_SECONDS = 2.0
SSE_HEARTBEAT_EVERY_N_POLLS = 5


def _events_after(
    tenant_id: str, *, after_event_id: str | None, since_connect: Any, limit: int = 200
) -> list[dict[str, Any]]:
    """`after_event_id` set (a reconnect with Last-Event-ID) replays every
    event since that cursor -- the "fetch missed events from Postgres
    before switching to live fan-out" requirement. A fresh connect with no
    cursor does NOT replay full history; `since_connect` marks the
    connect-time boundary so the stream only yields events from here
    forward, matching normal EventSource semantics (a fresh subscription
    sees new activity, not a history dump)."""
    connection, skipped = database_connection()
    if skipped is not None:
        return []

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            if after_event_id:
                cur.execute(
                    """
                    select id::text as id, aggregate_type, aggregate_id::text as aggregate_id,
                           aggregate_version, event_type, occurred_at, public_projection_json
                    from strategyos_agent_events_v2
                    where tenant_id = %s and occurred_at > (
                        select occurred_at from strategyos_agent_events_v2 where id = %s and tenant_id = %s
                    )
                    order by occurred_at asc, id asc
                    limit %s
                    """,
                    (tenant_id, after_event_id, tenant_id, limit),
                )
            else:
                cur.execute(
                    """
                    select id::text as id, aggregate_type, aggregate_id::text as aggregate_id,
                           aggregate_version, event_type, occurred_at, public_projection_json
                    from strategyos_agent_events_v2
                    where tenant_id = %s and occurred_at > %s
                    order by occurred_at asc, id asc
                    limit %s
                    """,
                    (tenant_id, since_connect, limit),
                )
            rows = fetchall_dicts(cur)
        conn.commit()
    return rows


def _format_sse_event(row: dict[str, Any]) -> str:
    """One SSE frame: id/event/data lines per the EventSource wire format.
    `data` carries only public_projection_json -- never payload_json, which
    may contain restricted context per design doc section 13."""
    event_id = row["id"]
    event_type = row["event_type"]
    occurred_at = row["occurred_at"]
    data = {
        "aggregate_type": row["aggregate_type"],
        "aggregate_id": row["aggregate_id"],
        "aggregate_version": row["aggregate_version"],
        "occurred_at": occurred_at.isoformat() if hasattr(occurred_at, "isoformat") else occurred_at,
        **(row.get("public_projection_json") or {}),
    }
    lines = [f"id: {event_id}", f"event: {event_type}", f"data: {json.dumps(data)}"]
    return "\n".join(lines) + "\n\n"


def _db_now():
    connection, skipped = database_connection()
    if skipped is not None:
        return None
    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute("select now()")
            value = cur.fetchone()[0]
        conn.commit()
    return value


def sse_event_stream(
    tenant_id: str,
    *,
    last_event_id: str | None,
    max_iterations: int | None = None,
) -> Iterator[str]:
    """Generator yielding SSE-framed text chunks. `max_iterations` exists
    only for tests (an infinite generator can't be asserted against
    directly); production callers leave it None and rely on client
    disconnect to stop iteration, which is FastAPI's StreamingResponse
    contract."""
    cursor = last_event_id
    # Fresh connects (no Last-Event-ID) anchor to the database's own clock
    # at connect time, not Python's, so this boundary is directly
    # comparable to occurred_at (a db-generated timestamptz) with no
    # cross-process clock skew.
    connect_boundary = None if cursor else _db_now()
    iterations = 0
    poll_count = 0

    while max_iterations is None or iterations < max_iterations:
        events = _events_after(tenant_id, after_event_id=cursor, since_connect=connect_boundary)
        if events:
            for row in events:
                yield _format_sse_event(row)
                cursor = row["id"]
            poll_count = 0
        else:
            poll_count += 1
            if poll_count >= SSE_HEARTBEAT_EVERY_N_POLLS:
                yield ": heartbeat\n\n"
                poll_count = 0
        iterations += 1
        if max_iterations is None:
            import time

            time.sleep(SSE_POLL_INTERVAL_SECONDS)
