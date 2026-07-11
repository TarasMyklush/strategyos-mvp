from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from . import state_store
from .config import CONFIG, StrategyOSConfig
from .run_poc import run_strategyos_workflow


RUN_TASK_NAME = "strategyos.run.execute"
TWIN_CYCLE_TASK_NAME = "strategyos.twins.cycle.execute"
TWIN_EVENTS_TASK_NAME = "strategyos.twins.events.execute"
HATCHET_EXECUTION_TIMEOUT = timedelta(minutes=30)
HATCHET_SCHEDULE_TIMEOUT = timedelta(minutes=15)
HATCHET_RETRIES = 0
_HATCHET_IMPORT_ERROR: Exception | None = None
hatchet: Any | None = None

try:  # pragma: no cover - exercised only when Hatchet SDK is installed.
    from hatchet_sdk import Context, Hatchet
    hatchet = Hatchet()
except Exception as exc:  # pragma: no cover - optional production dependency.
    Context = Any  # type: ignore[assignment]
    Hatchet = None  # type: ignore[assignment]
    _HATCHET_IMPORT_ERROR = exc


class StrategyOSRunInput(BaseModel):
    job_id: str
    dataset: str | None = None
    source_pack_id: str | None = None
    run_dir: str
    skip_prepare: bool = False
    sync_artifacts: bool | None = None
    allow_partial_source_pack: bool = False


class StrategyOSRunOutput(BaseModel):
    job_id: str
    status: str
    strategyos_run_id: str | None = None
    run_dir: str | None = None


class TwinCycleInput(BaseModel):
    cycle_type: str


class TwinCycleOutput(BaseModel):
    status: str
    execution_id: str | None = None
    cycle_type: str


class TwinEventsInput(BaseModel):
    max_stale_hours: int = 24


class TwinEventsOutput(BaseModel):
    status: str
    execution_id: str | None = None
    event_count: int = 0


def hatchet_dependency_status(
    config: StrategyOSConfig | None = None,
    *,
    verify_connection: bool = False,
) -> dict[str, Any]:
    active_config = config or CONFIG
    if active_config.run_execution_mode != "hatchet":
        return {
            "status": "skipped",
            "execution_mode": active_config.run_execution_mode,
            "reason": "Hatchet execution mode is disabled.",
        }
    if _HATCHET_IMPORT_ERROR is not None:
        return {
            "status": "failed",
            "execution_mode": active_config.run_execution_mode,
            "reason": f"hatchet-sdk is not installed or could not be imported: {_HATCHET_IMPORT_ERROR}",
        }
    if not active_config.hatchet_client_token:
        return {
            "status": "failed",
            "execution_mode": active_config.run_execution_mode,
            "reason": "HATCHET_CLIENT_TOKEN or STRATEGYOS_HATCHET_CLIENT_TOKEN is required.",
        }
    payload = {
        "status": "ok",
        "execution_mode": active_config.run_execution_mode,
        "worker_name": active_config.hatchet_worker_name,
        "worker_slots": active_config.hatchet_worker_slots,
        "tls_strategy": active_config.hatchet_client_tls_strategy,
        "dashboard_url": active_config.hatchet_dashboard_url,
    }
    if not verify_connection:
        return payload
    if hatchet is None:
        return {
            **payload,
            "status": "failed",
            "reason": "Hatchet client was not initialized.",
        }
    try:
        worker_list = hatchet.workers.list()
    except Exception as exc:
        return {
            **payload,
            "status": "failed",
            "reason": f"Hatchet engine probe failed: {type(exc).__name__}: {exc}",
        }
    workers = list(getattr(worker_list, "rows", None) or [])
    matching_workers = [
        worker
        for worker in workers
        if (
            str(getattr(worker, "name", "")) == active_config.hatchet_worker_name
            or str(getattr(worker, "name", "")).endswith(
                f"{active_config.hatchet_worker_name}"
            )
        )
        and str(
            getattr(getattr(worker, "status", None), "value", None)
            or getattr(worker, "status", "")
        ).upper()
        == "ACTIVE"
    ]
    if not matching_workers:
        return {
            **payload,
            "status": "failed",
            "reason": (
                "Hatchet engine is reachable, but the configured StrategyOS worker "
                "is not registered."
            ),
            "registered_worker_count": len(workers),
        }
    return {
        **payload,
        "connection_verified": True,
        "registered_worker_count": len(matching_workers),
    }


def enqueue_strategyos_run(payload: dict[str, Any]) -> dict[str, Any]:
    if hatchet is None or _HATCHET_IMPORT_ERROR is not None:
        raise RuntimeError(
            f"hatchet-sdk is required for Hatchet execution mode: {_HATCHET_IMPORT_ERROR}"
        )
    task_input = StrategyOSRunInput(**payload)
    ref = execute_strategyos_run.run(input=task_input, wait_for_result=False)  # type: ignore[attr-defined]
    hatchet_run_id = (
        getattr(ref, "run_id", None)
        or getattr(ref, "RunId", None)
        or getattr(ref, "workflow_run_id", None)
        or getattr(ref, "id", None)
    )
    return {
        "hatchet_run_id": str(hatchet_run_id) if hatchet_run_id is not None else None,
        "ref_type": type(ref).__name__,
    }


def enqueue_twin_cycle(payload: dict[str, Any]) -> dict[str, Any]:
    if hatchet is None or _HATCHET_IMPORT_ERROR is not None:
        raise RuntimeError(
            f"hatchet-sdk is required for Hatchet execution mode: {_HATCHET_IMPORT_ERROR}"
        )
    task_input = TwinCycleInput(**payload)
    ref = execute_twin_cycle.run(input=task_input, wait_for_result=False)  # type: ignore[attr-defined]
    hatchet_run_id = (
        getattr(ref, "run_id", None)
        or getattr(ref, "RunId", None)
        or getattr(ref, "workflow_run_id", None)
        or getattr(ref, "id", None)
    )
    return {
        "hatchet_run_id": str(hatchet_run_id) if hatchet_run_id is not None else None,
        "ref_type": type(ref).__name__,
    }


def enqueue_twin_events(payload: dict[str, Any]) -> dict[str, Any]:
    if hatchet is None or _HATCHET_IMPORT_ERROR is not None:
        raise RuntimeError(
            f"hatchet-sdk is required for Hatchet execution mode: {_HATCHET_IMPORT_ERROR}"
        )
    task_input = TwinEventsInput(**payload)
    ref = execute_twin_events.run(input=task_input, wait_for_result=False)  # type: ignore[attr-defined]
    hatchet_run_id = (
        getattr(ref, "run_id", None)
        or getattr(ref, "RunId", None)
        or getattr(ref, "workflow_run_id", None)
        or getattr(ref, "id", None)
    )
    return {
        "hatchet_run_id": str(hatchet_run_id) if hatchet_run_id is not None else None,
        "ref_type": type(ref).__name__,
    }


def execute_strategyos_run_job(
    task_input: StrategyOSRunInput,
    ctx: Any | None = None,
) -> StrategyOSRunOutput:
    job_id = task_input.job_id
    retry_count = getattr(ctx, "retry_count", None)
    state_store.update_run_job(
        job_id,
        status="running",
        metadata={
            "component": "strategyos-worker",
            "hatchet_task": RUN_TASK_NAME,
            **({"hatchet_retry_count": retry_count} if retry_count is not None else {}),
        },
    )
    try:
        summary = run_strategyos_workflow(
            dataset=Path(task_input.dataset) if task_input.dataset else None,
            source_pack_id=task_input.source_pack_id,
            run_dir=Path(task_input.run_dir),
            skip_prepare=task_input.skip_prepare,
            sync_artifacts=task_input.sync_artifacts,
            allow_partial_source_pack=task_input.allow_partial_source_pack,
        )
        strategyos_run_id = (
            summary.get("run_id")
            or (summary.get("state_store") or {}).get("run_id")
        )
        updated = state_store.update_run_job(
            job_id,
            status="succeeded",
            strategyos_run_id=str(strategyos_run_id) if strategyos_run_id else None,
            metadata={"summary": summary},
        )
        return StrategyOSRunOutput(
            job_id=str(updated.get("job_id") or job_id),
            status="succeeded",
            strategyos_run_id=str(strategyos_run_id) if strategyos_run_id else None,
            run_dir=str(summary.get("run_dir") or task_input.run_dir),
        )
    except Exception as exc:
        state_store.update_run_job(
            job_id,
            status="failed",
            failure_reason=str(exc),
            metadata={"error_type": type(exc).__name__},
        )
        raise


def execute_twin_cycle_job(task_input: TwinCycleInput, ctx: Any | None = None) -> TwinCycleOutput:
    from .twins.execution import execute_scheduled_cycle_job

    summary = execute_scheduled_cycle_job(cycle_type=task_input.cycle_type, config=CONFIG)
    return TwinCycleOutput(
        status=str(summary.get("status") or "completed"),
        execution_id=str(summary.get("execution_id") or "") or None,
        cycle_type=str(summary.get("cycle_type") or task_input.cycle_type),
    )


def execute_twin_events_job(task_input: TwinEventsInput, ctx: Any | None = None) -> TwinEventsOutput:
    from .twins.execution import execute_event_execution_job

    summary = execute_event_execution_job(
        max_stale_hours=int(task_input.max_stale_hours),
        config=CONFIG,
    )
    return TwinEventsOutput(
        status=str(summary.get("status") or "completed"),
        execution_id=str(summary.get("execution_id") or "") or None,
        event_count=len(list(summary.get("events") or [])),
    )


if hatchet is not None:  # pragma: no cover - requires external Hatchet SDK/server.

    @hatchet.task(
        name=RUN_TASK_NAME,
        input_validator=StrategyOSRunInput,
        execution_timeout=HATCHET_EXECUTION_TIMEOUT,
        schedule_timeout=HATCHET_SCHEDULE_TIMEOUT,
        retries=HATCHET_RETRIES,
    )
    def execute_strategyos_run(
        input: StrategyOSRunInput, ctx: Context
    ) -> StrategyOSRunOutput:
        return execute_strategyos_run_job(input, ctx)

    @hatchet.task(
        name=TWIN_CYCLE_TASK_NAME,
        input_validator=TwinCycleInput,
        execution_timeout=HATCHET_EXECUTION_TIMEOUT,
        schedule_timeout=HATCHET_SCHEDULE_TIMEOUT,
        retries=HATCHET_RETRIES,
    )
    def execute_twin_cycle(input: TwinCycleInput, ctx: Context) -> TwinCycleOutput:
        return execute_twin_cycle_job(input, ctx)

    @hatchet.task(
        name=TWIN_EVENTS_TASK_NAME,
        input_validator=TwinEventsInput,
        execution_timeout=HATCHET_EXECUTION_TIMEOUT,
        schedule_timeout=HATCHET_SCHEDULE_TIMEOUT,
        retries=HATCHET_RETRIES,
    )
    def execute_twin_events(input: TwinEventsInput, ctx: Context) -> TwinEventsOutput:
        return execute_twin_events_job(input, ctx)

else:

    def execute_strategyos_run(
        input: StrategyOSRunInput, ctx: Any | None = None
    ) -> StrategyOSRunOutput:
        raise RuntimeError(
            f"hatchet-sdk is required for Hatchet execution mode: {_HATCHET_IMPORT_ERROR}"
        )

    def execute_twin_cycle(
        input: TwinCycleInput, ctx: Any | None = None
    ) -> TwinCycleOutput:
        raise RuntimeError(
            f"hatchet-sdk is required for Hatchet execution mode: {_HATCHET_IMPORT_ERROR}"
        )

    def execute_twin_events(
        input: TwinEventsInput, ctx: Any | None = None
    ) -> TwinEventsOutput:
        raise RuntimeError(
            f"hatchet-sdk is required for Hatchet execution mode: {_HATCHET_IMPORT_ERROR}"
        )


def run_worker() -> None:
    if hatchet is None or _HATCHET_IMPORT_ERROR is not None:
        raise RuntimeError(
            f"hatchet-sdk is required to start StrategyOS worker: {_HATCHET_IMPORT_ERROR}"
        )
    worker = hatchet.worker(
        CONFIG.hatchet_worker_name,
        slots=max(1, int(CONFIG.hatchet_worker_slots)),
        workflows=[execute_strategyos_run, execute_twin_cycle, execute_twin_events],
    )
    worker.start()
