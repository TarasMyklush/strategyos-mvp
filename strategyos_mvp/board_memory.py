"""Append-only board packets. Frozen content, current source permissions."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Mapping

from . import state_store

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategyos_board_snapshots (
    tenant_key text NOT NULL,
    meeting_id text NOT NULL,
    run_id text NOT NULL,
    closed_by text NOT NULL,
    closed_at timestamptz NOT NULL DEFAULT now(),
    digest text NOT NULL,
    packet_json jsonb NOT NULL,
    PRIMARY KEY (tenant_key, meeting_id)
);
CREATE OR REPLACE FUNCTION strategyos_reject_board_change() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
    RAISE EXCEPTION 'Closed board packets are immutable; create a separate correction record';
END $$;
DROP TRIGGER IF EXISTS strategyos_board_immutable ON strategyos_board_snapshots;
CREATE TRIGGER strategyos_board_immutable BEFORE UPDATE OR DELETE ON strategyos_board_snapshots
FOR EACH ROW EXECUTE FUNCTION strategyos_reject_board_change();
"""


def canonical(packet: Mapping[str, Any]) -> str:
    return json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str)


def packet_digest(packet: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical(packet).encode()).hexdigest()


def initialize(conn: Any) -> None:
    if str(getattr(state_store.CONFIG, 'database_schema_mode', 'auto')).lower() == 'verify':
        state_store.ensure_data_schema(conn)
        return
    with conn.cursor() as cur:
        # A transaction lock prevents concurrent first-use schema changes.
        cur.execute("SELECT pg_advisory_xact_lock(71380912)")
        cur.execute(SCHEMA)


def close_meeting(tenant: str, meeting_id: str, *, run_id: str, actor: str,
                  approved_context: Mapping[str, Any], files: Mapping[str, bytes],
                  authority: Mapping[str, Any]) -> dict[str, Any]:
    if not tenant or not meeting_id or not run_id or not actor:
        raise ValueError("A tenant, meeting, approved run and closing identity are required.")
    if len(meeting_id) > 160 or not files:
        raise ValueError("A bounded meeting ID and at least one approved document are required.")
    if sum(len(content) for content in files.values()) > 20_000_000:
        raise ValueError("Board packet exceeds the 20 MB snapshot limit.")
    packet = {"version": 1, "tenant_id": tenant, "meeting_id": meeting_id, "run_id": run_id,
              "context": dict(approved_context), "authority": dict(authority),
              "files": {name: {"sha256": hashlib.sha256(content).hexdigest(),
                               "base64": base64.b64encode(content).decode()}
                        for name, content in files.items()}}
    digest = packet_digest(packet)
    handle, failure = state_store.database_connection()
    if failure or handle is None:
        raise RuntimeError("Board memory requires the durable database.")
    with handle as conn:
        initialize(conn)
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO strategyos_board_snapshots
                (tenant_key, meeting_id, run_id, closed_by, digest, packet_json)
                VALUES (%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING""",
                (tenant, meeting_id, run_id, actor, digest, canonical(packet)))
            cur.execute("SELECT digest FROM strategyos_board_snapshots WHERE tenant_key=%s AND meeting_id=%s", (tenant, meeting_id))
            existing = cur.fetchone()[0]
            if existing != digest:
                raise ValueError("This meeting is already closed with different content; issue a separate correction.")
        conn.commit()
    return {"meeting_id": meeting_id, "run_id": run_id, "digest": digest, "status": "closed"}


def authorize_run(tenant: str, run_id: str, *, principal: Mapping[str, Any] | None = None,
                  purpose: str = 'executive_briefing') -> None:
    from .access_scope import principal_scope
    from .claim_store import ClaimRepository
    from .source_claims import PolicyContext
    actor = principal if principal is not None else principal_scope.get()
    if actor is None:
        return  # Internal storage/recovery calls; HTTP callers supply identity.
    if str(actor.get('tenant_id') or '') != tenant or not run_id:
        raise PermissionError('Board material is unavailable under current source permissions.')
    try:
        decision = ClaimRepository().run_source_access(run_id, context=PolicyContext(
            tenant_id=tenant, principal_id=str(actor.get('subject') or 'unknown'),
            roles=frozenset({str(actor.get('role') or '')}),
            business_units=frozenset(actor.get('business_units') or ()), purpose=purpose))
    except (RuntimeError, ValueError, KeyError):
        raise PermissionError('Board material is unavailable under current source permissions.') from None
    # Historical content stays frozen when newer inputs arrive. This exception
    # never overrides withdrawal, role, purpose, storage or export restrictions.
    if not decision.get('allowed') and set(decision.get('reasons') or ()) != {'bulk_revised_inputs_require_recompute'}:
        raise PermissionError('Board material is unavailable under current source permissions.')


def read_meeting(tenant: str, meeting_id: str, *, principal: Mapping[str, Any] | None = None,
                 purpose: str = 'executive_briefing') -> dict[str, Any] | None:
    handle, failure = state_store.database_connection()
    if failure or handle is None:
        raise RuntimeError("Board memory requires the durable database.")
    with handle as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('strategyos_board_snapshots')")
            if cur.fetchone()[0] is None:
                return None
            cur.execute('SELECT run_id FROM strategyos_board_snapshots WHERE tenant_key=%s AND meeting_id=%s', (tenant, meeting_id))
            reference = cur.fetchone()
            if reference is None:
                return None
            authorize_run(tenant, str(reference[0]), principal=principal, purpose=purpose)
            cur.execute("""SELECT packet_json, digest, closed_at, closed_by FROM strategyos_board_snapshots
                WHERE tenant_key=%s AND meeting_id=%s""", (tenant, meeting_id))
            row = state_store.fetchone_dict(cur)
    if row is None:
        return None
    if packet_digest(row["packet_json"]) != row["digest"]:
        raise RuntimeError("Board snapshot integrity verification failed.")
    return {"packet": row["packet_json"], "digest": row["digest"],
            "closed_at": str(row["closed_at"]), "closed_by": row["closed_by"], "status": "closed"}


def answer_from_snapshot(snapshot: Mapping[str, Any], question: str) -> dict[str, Any]:
    """Resolve approved answer keys only; never fall back to a live run or model."""
    packet = snapshot["packet"]
    answers = packet["context"].get("approved_answers") or {}
    key = " ".join(question.casefold().split()).rstrip("?.")
    match = next((value for prompt, value in answers.items()
                  if " ".join(prompt.casefold().split()).rstrip("?.") == key), None)
    return {"status": "ok", "matched": match is not None,
            "answer": str(match) if match is not None else "That answer is not in this closed meeting’s approved snapshot. Request a supplementary answer as a separate record.",
            "response_mode": "frozen_board_snapshot", "snapshot_digest": snapshot["digest"],
            "citations": [{"source_path": f"board-snapshot://{packet['meeting_id']}", "locator": snapshot["digest"]}] if match is not None else []}
