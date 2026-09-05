"""Request-bound ownership checks for run-backed storage."""
from contextvars import ContextVar
from typing import Any, Mapping
from uuid import UUID

principal_scope: ContextVar[Mapping[str, Any] | None] = ContextVar("strategyos_principal_scope", default=None)


def run_predicate(alias: str = "r") -> tuple[str, tuple]:
    import json
    if alias not in {"r", "strategyos_runs"}:
        raise ValueError("Unapproved SQL alias.")
    principal = principal_scope.get()
    if principal is None or principal.get("auth_disabled"):
        return "TRUE", ()
    clause = f"{alias}.tenant_key = %s"
    params = (str(principal.get("tenant_id") or ""),)
    if principal.get("role") == "bu":
        clause += f" AND {alias}.business_unit_scope <> '[]'::jsonb AND {alias}.business_unit_scope <@ %s::jsonb"
        params += (json.dumps(principal.get("business_units") or []),)
    return clause, params


def guard_summary(summary: Mapping[str, Any] | None) -> None:
    principal = principal_scope.get()
    if principal is None or principal.get("auth_disabled"):
        return
    if not summary:
        raise PermissionError("Run not found in the authorized scope.")
    owner = (summary.get("tenant_context") or {}).get("tenant_id")
    if not owner or owner != principal.get("tenant_id"):
        raise PermissionError("Run not found in the authorized scope.")
    if principal.get("role") == "bu":
        units = set(summary.get("business_units") or [])
        allowed = set(principal.get("business_units") or [])
        if not units or not allowed or not units.issubset(allowed):
            raise PermissionError("A run scoped to your authorized business unit is required.")


def guard_run(run_id: str | None, *, require_store: bool = False) -> None:
    principal = principal_scope.get()
    if principal is None or principal.get("auth_disabled"):
        return
    if not run_id:
        return  # Store functions return their existing missing-run result.
    from . import state_store
    from .run_registry import load_latest_run_summary
    handle, failure = state_store.database_connection()
    if failure or handle is None:
        if require_store:
            raise PermissionError("Run ownership could not be verified.")
        return  # No database data can be read; file fallback has its own gate.
    try:
        UUID(str(run_id))
    except (ValueError, TypeError):
        with handle:
            pass
        summary = load_latest_run_summary()
        if not summary or str(summary.get("run_id")) != str(run_id):
            raise PermissionError("Run not found in the authorized scope.")
        guard_summary(summary)
        return
    with handle as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT tenant_key, business_unit_scope
                FROM strategyos_runs WHERE id=%s""", (str(run_id),))
            row = cur.fetchone()
    guard_summary({"tenant_context": {"tenant_id": row[0]}, "business_units": row[1]} if row else None)


def guard_reference(kind: str, record_id: str) -> None:
    principal = principal_scope.get()
    if principal is None or principal.get("auth_disabled"):
        return
    from . import state_store
    query = {
        "checkpoint": "SELECT run_id FROM strategyos_run_checkpoints WHERE id=%s",
        "job": "SELECT metadata_json->'tenant_context', metadata_json->'business_units' FROM strategyos_run_jobs WHERE id=%s",
    }[kind]
    handle, failure = state_store.database_connection()
    if failure or handle is None:
        return  # The corresponding store read can only return unavailable.
    with handle as conn:
        with conn.cursor() as cur:
            cur.execute(query, (record_id,))
            row = cur.fetchone()
    if not row:
        raise PermissionError("Record not found in the authorized scope.")
    if kind == "checkpoint":
        guard_run(str(row[0]))
    else:
        guard_summary({"tenant_context": row[0], "business_units": row[1]})
