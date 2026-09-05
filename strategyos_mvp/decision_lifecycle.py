"""Durable, scoped decision events; recording never implies external delivery."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from . import access_scope, state_store
from .decision_velocity import summarize

SCHEMA = """CREATE TABLE IF NOT EXISTS strategyos_decision_events (
 id bigserial PRIMARY KEY, tenant_key text NOT NULL, run_id uuid NOT NULL REFERENCES strategyos_runs(id),
 decision_key text NOT NULL, kind text NOT NULL CHECK (kind IN ('surfaced','decided','action_verified')),
 actor text NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now(), payload jsonb NOT NULL,
 effect_key text NOT NULL, UNIQUE(tenant_key, run_id, decision_key, effect_key),
 UNIQUE(tenant_key, run_id, decision_key, kind)
)"""


def _connect(run_id):
    access_scope.guard_run(run_id, require_store=True)
    handle, failure = state_store.database_connection()
    if failure or handle is None:
        raise RuntimeError("Decisions require the durable database. Nothing has been recorded.")
    return handle


def _tenant():
    principal = access_scope.principal_scope.get()
    return str((principal or {}).get("tenant_id") or state_store.CONFIG.tenant_slug)


def append(run_id: str, decision_key: str, kind: str, *, actor: str, payload: dict, effect_key: str) -> dict:
    if kind not in {"surfaced", "decided", "action_verified"} or not decision_key or not actor or not effect_key:
        raise ValueError("A valid event, decision, actor and retry key are required.")
    encoded = json.dumps(payload, sort_keys=True, allow_nan=False)
    tenant = _tenant()
    with _connect(run_id) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (tenant + run_id + decision_key,))
            cur.execute("SELECT kind, payload FROM strategyos_decision_events WHERE tenant_key=%s AND run_id=%s AND decision_key=%s", (tenant, run_id, decision_key))
            existing = dict(cur.fetchall())
            if kind in existing:
                if existing[kind] != payload:
                    raise ValueError("A different event is already recorded. A reviewed amendment is required.")
                return {"status": "recorded", "idempotent_replay": True}
            if kind == "decided" and "surfaced" not in existing:
                raise ValueError("Refresh the decision before recording it.")
            if kind == "action_verified":
                if "decided" not in existing or existing["decided"].get("choice") != "Approve":
                    raise ValueError("An approved decision is required before an action can be verified.")
                if not payload.get("evidence_sha256") or not payload.get("evidence_path"):
                    raise ValueError("Verified first action requires resolving evidence.")
            cur.execute("""INSERT INTO strategyos_decision_events
                (tenant_key,run_id,decision_key,kind,actor,payload,effect_key) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)
                RETURNING id, occurred_at""", (tenant, run_id, decision_key, kind, actor, encoded, hashlib.sha256(effect_key.encode()).hexdigest()))
            row = cur.fetchone()
        conn.commit()
    return {"status": "recorded", "event_id": row[0], "occurred_at": row[1].isoformat(), "idempotent_replay": False}


def read(run_id: str) -> dict[str, Any]:
    with _connect(run_id) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
            cur.execute("""SELECT id, decision_key, kind, actor, occurred_at, payload FROM strategyos_decision_events
                WHERE tenant_key=%s AND run_id=%s ORDER BY occurred_at, id""", (_tenant(), run_id))
            events = state_store.fetchall_dicts(cur)
        conn.commit()
    records = {}
    for event in events:
        key, kind = event["decision_key"], event["kind"]
        record = records.setdefault(key, {"decision_key": key, "event_ids": [], "events": [], "delivery_status": "not_connected", "issue_status": "open"})
        record["event_ids"].append(event["id"])
        record["events"].append({**event, "occurred_at": event["occurred_at"].isoformat()})
        timestamp = event["occurred_at"].isoformat()
        if kind == "surfaced":
            record.update(surfaced_at=timestamp, title=event["payload"].get("title"))
        elif kind == "decided":
            record.update(decided_at=timestamp, choice=event["payload"].get("choice"), owner=event["payload"].get("owner"))
        else:
            record.update(first_action_at=timestamp, action_evidence_verified=True)
    result = list(records.values())
    return {"status": "ok", "run_id": run_id, "records": result, "velocity": summarize(result)}
