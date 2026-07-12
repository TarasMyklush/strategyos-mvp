"""Hatchet durable task execution (design doc section 8.2, 14).

Registers strategyos.agent.task.execute beside the existing run/twin
workflows in hatchet_runtime.py's pattern: a module-level `hatchet` client
that is None when the SDK/config is unavailable, with tasks registered only
when it is present, and a synchronous execute_agent_task_job(...) function
that is directly callable from tests/the outbox dispatcher regardless of
whether Hatchet is running.

Delivery semantics (design doc section 14):
1. repository.transition_task() writes task + event + outbox atomically
   (done in PR 1/repository.py).
2. dispatch_ready_tasks() (the outbox dispatcher) publishes queued tasks'
   IDs to Hatchet.
3. A worker claims a task via transition_task(queued -> running), which is
   an atomic compare-and-set through repository.py's `for update` lock.
4. A retry creates a new attempt row, not a duplicate task.
5. Effect-idempotency (tool_invocations.effect_key) is PR 6 territory --
   PR 2's handlers are read-only and have no side effects to key.
6. Completion commits result + event atomically (repository.transition_task
   already does this).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pydantic import BaseModel

from ..config import CONFIG
from ..state_store import database_connection, fetchall_dicts
from . import repository
from .models import TaskStatus
from .registry import AGENT_DEFINITIONS_BY_KEY
from .tools import ToolExecutionContext
from .workers import HandlerInputInvalid, run_handler

AGENT_TASK_EXECUTE_TASK_NAME = "strategyos.agent.task.execute"
HATCHET_EXECUTION_TIMEOUT = timedelta(minutes=10)
HATCHET_SCHEDULE_TIMEOUT = timedelta(minutes=5)
HATCHET_RETRIES = 2

_HATCHET_IMPORT_ERROR: Exception | None = None
hatchet: Any | None = None

try:  # pragma: no cover - exercised only when Hatchet SDK is installed.
    from hatchet_sdk import Context, Hatchet

    hatchet = Hatchet()
except Exception as exc:  # pragma: no cover - optional production dependency.
    Context = Any  # type: ignore[assignment]
    Hatchet = None  # type: ignore[assignment]
    _HATCHET_IMPORT_ERROR = exc


class AgentTaskExecuteInput(BaseModel):
    tenant_id: str
    task_id: str


class AgentTaskExecuteOutput(BaseModel):
    task_id: str
    status: str
    failure_code: str | None = None


class TaskExecutionFailed(Exception):
    def __init__(self, failure_code: str, detail_public: str):
        super().__init__(detail_public)
        self.failure_code = failure_code
        self.detail_public = detail_public


def execute_agent_task_job(
    task_input: AgentTaskExecuteInput, ctx: Any | None = None
) -> AgentTaskExecuteOutput:
    """The actual task-execution logic, callable directly in tests without a
    live Hatchet engine. Claims the task (queued -> running), resolves its
    agent definition's handler, executes it, and transitions to a terminal
    status with the result recorded -- all through repository.transition_task
    so every step writes its event atomically."""
    tenant_id = task_input.tenant_id
    task_id = task_input.task_id

    task = repository.get_task(tenant_id, task_id)
    if task is None:
        raise TaskExecutionFailed("AGENT_INVALID_INPUT", "Task not found.")
    if isinstance(task, dict) and task.get("status") in ("missing", "skipped"):
        raise TaskExecutionFailed("AGENT_TOOL_UNAVAILABLE", "State store is unavailable.")

    if task["status"] != TaskStatus.QUEUED.value:
        # Not our job to claim -- another worker likely already has it, or
        # it was cancelled/timed out between dispatch and claim.
        return AgentTaskExecuteOutput(task_id=task_id, status=task["status"])

    worker_actor = {"type": "system", "id": "agent-worker"}
    try:
        running_task = repository.transition_task(
            tenant_id, task_id, target_status=TaskStatus.RUNNING, actor=worker_actor
        )
    except repository.InvalidStatusTransition:
        # Lost the race to claim this task to another worker; not a failure.
        current = repository.get_task(tenant_id, task_id)
        return AgentTaskExecuteOutput(task_id=task_id, status=(current or {}).get("status", "unknown"))

    installation = _get_installation(tenant_id, running_task["agent_installation_id"])
    agent_definition = AGENT_DEFINITIONS_BY_KEY.get(installation["agent_key"]) if installation else None

    if agent_definition is None:
        return _fail_task(
            tenant_id, task_id, worker_actor,
            failure_code="AGENT_NOT_PERMITTED",
            detail_public="No registered agent is installed for this task.",
        )

    tool_ctx = ToolExecutionContext(
        tenant_id=tenant_id,
        task_id=task_id,
        run_id=(running_task.get("input_json") or {}).get("run_id")
        or (running_task.get("context_manifest_json") or {}).get("run_id"),
    )

    try:
        result = run_handler(agent_definition.handler_key, tool_ctx, running_task.get("input_json") or {})
    except HandlerInputInvalid as exc:
        return _fail_task(
            tenant_id, task_id, worker_actor,
            failure_code="AGENT_INVALID_INPUT",
            detail_public=str(exc),
        )
    except Exception as exc:  # pragma: no cover - defensive: unexpected handler crash
        return _fail_task(
            tenant_id, task_id, worker_actor,
            failure_code="AGENT_INTERNAL_FAILURE",
            detail_public=f"The specialist agent could not complete this task: {type(exc).__name__}.",
        )

    final = repository.transition_task(
        tenant_id, task_id, target_status=TaskStatus.SUCCEEDED, actor=worker_actor, result=result
    )
    return AgentTaskExecuteOutput(task_id=task_id, status=final["status"])


def _fail_task(
    tenant_id: str, task_id: str, actor: dict[str, str], *, failure_code: str, detail_public: str
) -> AgentTaskExecuteOutput:
    final = repository.transition_task(
        tenant_id, task_id, target_status=TaskStatus.FAILED, actor=actor,
        failure_code=failure_code, failure_detail_public=detail_public,
    )
    return AgentTaskExecuteOutput(task_id=task_id, status=final["status"], failure_code=failure_code)


def _get_installation(tenant_id: str, installation_id: str) -> dict[str, Any] | None:
    connection, skipped = database_connection()
    if skipped is not None:
        return None
    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select agent_key from strategyos_agent_installations where id = %s and tenant_id = %s",
                (installation_id, tenant_id),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        return None
    return {"agent_key": row[0]}


def enqueue_agent_task(tenant_id: str, task_id: str) -> dict[str, Any]:
    if hatchet is None or _HATCHET_IMPORT_ERROR is not None:
        raise RuntimeError(
            f"hatchet-sdk is required for Hatchet execution mode: {_HATCHET_IMPORT_ERROR}"
        )
    task_input = AgentTaskExecuteInput(tenant_id=tenant_id, task_id=task_id)
    ref = execute_agent_task.run(input=task_input, wait_for_result=False)  # type: ignore[attr-defined]
    hatchet_run_id = (
        getattr(ref, "run_id", None)
        or getattr(ref, "RunId", None)
        or getattr(ref, "workflow_run_id", None)
        or getattr(ref, "id", None)
    )
    return {"hatchet_run_id": str(hatchet_run_id) if hatchet_run_id is not None else None}


if hatchet is not None:  # pragma: no cover - requires external Hatchet SDK/server.

    @hatchet.task(
        name=AGENT_TASK_EXECUTE_TASK_NAME,
        input_validator=AgentTaskExecuteInput,
        execution_timeout=HATCHET_EXECUTION_TIMEOUT,
        schedule_timeout=HATCHET_SCHEDULE_TIMEOUT,
        retries=HATCHET_RETRIES,
    )
    def execute_agent_task(input: AgentTaskExecuteInput, ctx: Context) -> AgentTaskExecuteOutput:
        return execute_agent_task_job(input, ctx)

else:

    def execute_agent_task(
        input: AgentTaskExecuteInput, ctx: Any | None = None
    ) -> AgentTaskExecuteOutput:
        raise RuntimeError(
            f"hatchet-sdk is required for Hatchet execution mode: {_HATCHET_IMPORT_ERROR}"
        )


# ---------------------------------------------------------------------------
# Outbox dispatcher and reconciliation (design doc section 14 "Stuck work")
# ---------------------------------------------------------------------------


def dispatch_ready_tasks(*, limit: int = 50) -> dict[str, Any]:
    """Publish every `queued` task that has no Hatchet run yet. Called by a
    scheduled reconciler in production; directly callable in tests/dev to
    drive execution without a live Hatchet engine (falls back to running the
    handler inline when Hatchet is unavailable, mirroring how PR 1's tests
    exercised repository.py without a running worker)."""
    connection, skipped = database_connection()
    if skipped is not None:
        return {"dispatched": 0, "reason": skipped.get("reason")}

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id::text as id, tenant_id::text as tenant_id
                from strategyos_agent_tasks
                where status = 'queued'
                order by created_at asc
                limit %s
                """,
                (limit,),
            )
            rows = fetchall_dicts(cur)
        conn.commit()

    dispatched = 0
    results = []
    for row in rows:
        if hatchet is not None and _HATCHET_IMPORT_ERROR is None and CONFIG.run_execution_mode == "hatchet":
            outcome = enqueue_agent_task(row["tenant_id"], row["id"])
        else:
            outcome = execute_agent_task_job(
                AgentTaskExecuteInput(tenant_id=row["tenant_id"], task_id=row["id"])
            ).model_dump()
        results.append({"task_id": row["id"], **outcome})
        dispatched += 1
    return {"dispatched": dispatched, "results": results}


def reconcile_stuck_tasks(*, running_lease_minutes: int = 15) -> dict[str, Any]:
    """Marks tasks stuck in `running` past a lease window as timed_out. A
    full heartbeat/lease mechanism is PR 6 territory (capability tokens
    carry expiry); PR 2 ships the coarse time-based version so the
    reconciliation job named in the design doc's migration sequence exists
    and is testable end to end."""
    connection, skipped = database_connection()
    if skipped is not None:
        return {"timed_out": 0, "reason": skipped.get("reason")}

    assert connection is not None
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id::text as id, tenant_id::text as tenant_id
                from strategyos_agent_tasks
                where status = 'running'
                  and started_at is not null
                  and started_at < now() - (%s || ' minutes')::interval
                """,
                (running_lease_minutes,),
            )
            rows = fetchall_dicts(cur)
        conn.commit()

    timed_out = 0
    for row in rows:
        try:
            repository.transition_task(
                row["tenant_id"], row["id"], target_status=TaskStatus.TIMED_OUT,
                actor={"type": "system", "id": "reconciler"},
                failure_code="AGENT_TIMEOUT",
                failure_detail_public="This task exceeded its execution lease and was stopped.",
            )
            timed_out += 1
        except repository.InvalidStatusTransition:
            continue  # already transitioned by the time we got here
    return {"timed_out": timed_out}
