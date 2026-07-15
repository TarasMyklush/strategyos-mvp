"""CEO module/network read models (design doc section 12).

Replaces api.py's _agent_modules_payload() -- which derives synthetic
module cards from run-summary/publication state -- with projections built
from real task/handoff/approval records. Module IDs
(cash-recovery-watch/evidence-closure-monitor/board-pack-compiler/
runtime-guardrail) are kept identical to the existing payload so the
current UI cards continue to resolve to the same module_id once the CEO UI
switches its data source; only the backing data changes from derived
run-state to durable task/handoff state.

This module is additive: it does not remove or modify
_agent_modules_payload(). Design doc section 12: "Remove copy such as
'following up automatically' unless a follow-up task actually exists" and
section 19's acceptance criteria are enforced by only emitting labels this
module can prove from a real record.
"""

from __future__ import annotations

from typing import Any

from ..state_store import database_connection, fetchall_dicts
from .registry import AGENT_DEFINITIONS

# agent_key -> the module_id the current UI expects, per api.py's
# _agent_modules_payload(). Keeping this mapping explicit (not derived)
# means a registry rename doesn't silently change a UI-facing ID.
AGENT_KEY_TO_MODULE_ID: dict[str, str] = {
    "cash-recovery": "cash-recovery-watch",
    "evidence-closure": "evidence-closure-monitor",
    "board-pack": "board-pack-compiler",
    "runtime-guardrail": "runtime-guardrail",
}

# design doc section 12: precise status labels, each gated on a specific
# underlying record state -- never a generic "active"/"working" default.
_STATUS_LABELS: dict[str, str] = {
    "proposed": "Preparing",
    "waiting_for_approval": "Waiting for reviewer",
    "queued": "Queued",
    "running": "Working",
    "waiting_for_input": "Needs input",
    "succeeded": "Complete",
    "failed": "Could not complete",
    "cancelled": "Cancelled",
    "timed_out": "Timed out",
}


def _task_status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, status)


def agent_network_payload(tenant_id: str) -> dict[str, Any]:
    """Real task/handoff/approval-backed replacement for
    api.py's agent_modules.running (design doc: "Replace
    agent_modules.running as the runtime authority with
    GET /api/v1/agent-network")."""
    connection, skipped = database_connection()
    if skipped is not None:
        return {"status": "skipped", "reason": skipped.get("reason"), "modules": [], "handoffs": [], "summary": {}}

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select ai.agent_key,
                       t.id::text as task_id,
                       t.status,
                       t.objective,
                       t.updated_at,
                       t.risk_class
                from strategyos_agent_tasks t
                join strategyos_agent_installations ai on ai.id = t.agent_installation_id
                where t.tenant_id = %s
                order by t.updated_at desc
                """,
                (tenant_id,),
            )
            task_rows = fetchall_dicts(cur)

            cur.execute(
                """
                select h.id::text as handoff_id,
                       h.status,
                       h.requested_capability,
                       h.reason,
                       h.updated_at,
                       fa.agent_key as from_agent_key,
                       ta.agent_key as to_agent_key,
                       h.source_task_id::text as source_task_id,
                       h.child_task_id::text as child_task_id
                from strategyos_agent_handoffs h
                join strategyos_agent_installations fa on fa.id = h.from_agent_installation_id
                join strategyos_agent_installations ta on ta.id = h.to_agent_installation_id
                where h.tenant_id = %s
                order by h.updated_at desc
                limit 50
                """,
                (tenant_id,),
            )
            handoff_rows = fetchall_dicts(cur)

            cur.execute(
                """
                select count(*) filter (where status not in ('succeeded','failed','cancelled','timed_out')) as active_count,
                       count(*) filter (where status = 'waiting_for_approval') as waiting_for_approval_count,
                       count(*) filter (where status = 'succeeded') as succeeded_count,
                       count(*) filter (where status = 'failed') as failed_count
                from strategyos_agent_tasks
                where tenant_id = %s
                """,
                (tenant_id,),
            )
            summary_row = cur.fetchone()
        conn.commit()

    # Latest task per agent_key -- the module card shows the agent's
    # single most current unit of work, not a full task list.
    latest_by_agent: dict[str, dict[str, Any]] = {}
    for row in task_rows:
        agent_key = row["agent_key"]
        if agent_key not in latest_by_agent:
            latest_by_agent[agent_key] = row

    modules = []
    for definition in AGENT_DEFINITIONS:
        module_id = AGENT_KEY_TO_MODULE_ID.get(definition.agent_key, definition.agent_key)
        latest_task = latest_by_agent.get(definition.agent_key)
        if latest_task is None:
            modules.append(
                {
                    "module_id": module_id,
                    "agent_key": definition.agent_key,
                    "label": definition.display_name,
                    "status": "idle",
                    "status_label": "No active task",
                    "objective": None,
                    "task_id": None,
                    "last_update": None,
                    "approval_dependency": "none",
                    "detail_route": None,
                }
            )
            continue
        status = latest_task["status"]
        modules.append(
            {
                "module_id": module_id,
                "agent_key": definition.agent_key,
                "label": definition.display_name,
                "status": status,
                "status_label": _task_status_label(status),
                "objective": latest_task["objective"],
                "task_id": latest_task["task_id"],
                "last_update": latest_task["updated_at"].isoformat()
                if hasattr(latest_task["updated_at"], "isoformat")
                else latest_task["updated_at"],
                "approval_dependency": "reviewer_approval" if status == "waiting_for_approval" else "none",
                "detail_route": f"/api/v1/agent-tasks/{latest_task['task_id']}",
            }
        )

    handoffs = []
    for row in handoff_rows:
        handoffs.append(
            {
                "handoff_id": row["handoff_id"],
                "status": row["status"],
                "status_label": _handoff_status_label(row["status"]),
                "from_agent_key": row["from_agent_key"],
                "to_agent_key": row["to_agent_key"],
                "requested_capability": row["requested_capability"],
                "reason": row["reason"],
                "source_task_id": row["source_task_id"],
                "child_task_id": row["child_task_id"],
                "last_update": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else row["updated_at"],
            }
        )

    summary = {
        "active_count": int(summary_row[0] or 0),
        "waiting_for_approval_count": int(summary_row[1] or 0),
        "succeeded_count": int(summary_row[2] or 0),
        "failed_count": int(summary_row[3] or 0),
    }

    return {"status": "ok", "modules": modules, "handoffs": handoffs, "summary": summary}


_HANDOFF_STATUS_LABELS: dict[str, str] = {
    "proposed": "Proposed",
    "accepted": "Accepted",
    "in_progress": "Working",
    "completed": "Complete",
    "rejected": "Rejected",
    "escalated": "Escalated",
    "expired": "Expired",
}


def _handoff_status_label(status: str) -> str:
    return _HANDOFF_STATUS_LABELS.get(status, status)
