"""Scheduled and event-driven execution services for digital twins."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any
from uuid import uuid4

from strategyos_mvp.config import StrategyOSConfig, load_config

from . import memory as memory_module
from . import persona as persona_module
from . import resolution as resolution_module
from .orchestration import CycleHistory, CycleScheduler, TriggerEngine
from .runtime import TwinRuntime
from .store import TwinRepositories, build_app_repositories

logger = logging.getLogger(__name__)


def submit_scheduled_cycle(
    cycle_type: str,
    *,
    config: StrategyOSConfig | None = None,
    repositories: TwinRepositories | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    active_config = config or load_config()
    repo_set = repositories or build_app_repositories()
    normalized_cycle = _normalize_cycle_type(cycle_type)
    if not active_config.twins_enabled:
        return _disabled_execution_response(
            execution_type="scheduled_cycle",
            reason="Twin features are disabled.",
            cycle_type=normalized_cycle,
        )
    if not active_config.twins_scheduler_enabled:
        return _disabled_execution_response(
            execution_type="scheduled_cycle",
            reason="Twin scheduler is disabled.",
            cycle_type=normalized_cycle,
        )
    if active_config.run_execution_mode == "hatchet":
        from strategyos_mvp.hatchet_runtime import enqueue_twin_cycle

        execution_id = f"cycle-{uuid4().hex[:12]}"
        repo_set.execution.save({
            "execution_id": execution_id,
            "execution_type": "scheduled_cycle",
            "cycle_type": normalized_cycle,
            "idempotency_key": idempotency_key,
            "status": "queued",
            "execution_mode": active_config.run_execution_mode,
            "started_at": datetime.now(UTC).isoformat(),
            "trigger": "scheduler",
        })
        queue_ref = enqueue_twin_cycle({"cycle_type": normalized_cycle})
        repo_set.execution.update(execution_id, {"result": queue_ref})
        return {
            "status": "queued",
            "execution_mode": "hatchet",
            "cycle_type": normalized_cycle,
            "execution_id": execution_id,
            **queue_ref,
        }
    return execute_scheduled_cycle_job(
        cycle_type=normalized_cycle,
        repositories=repo_set,
        config=active_config,
        idempotency_key=idempotency_key,
    )


def submit_event_execution(
    *,
    max_stale_hours: int = 24,
    config: StrategyOSConfig | None = None,
    repositories: TwinRepositories | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    active_config = config or load_config()
    repo_set = repositories or build_app_repositories()
    if not active_config.twins_enabled:
        return _disabled_execution_response(
            execution_type="event_execution",
            reason="Twin features are disabled.",
        )
    if not active_config.twins_scheduler_enabled:
        return _disabled_execution_response(
            execution_type="event_execution",
            reason="Twin scheduler is disabled.",
        )
    if active_config.run_execution_mode == "hatchet":
        from strategyos_mvp.hatchet_runtime import enqueue_twin_events

        execution_id = f"event-{uuid4().hex[:12]}"
        repo_set.execution.save({
            "execution_id": execution_id,
            "execution_type": "event_execution",
            "idempotency_key": idempotency_key,
            "status": "queued",
            "execution_mode": active_config.run_execution_mode,
            "started_at": datetime.now(UTC).isoformat(),
            "trigger": "live_events",
            "max_stale_hours": max_stale_hours,
        })
        queue_ref = enqueue_twin_events({"max_stale_hours": max_stale_hours})
        repo_set.execution.update(execution_id, {"result": queue_ref})
        return {
            "status": "queued",
            "execution_mode": "hatchet",
            "execution_id": execution_id,
            **queue_ref,
        }
    return execute_event_execution_job(
        max_stale_hours=max_stale_hours,
        repositories=repo_set,
        config=active_config,
        idempotency_key=idempotency_key,
    )


def execute_scheduled_cycle_job(
    *,
    cycle_type: str,
    repositories: TwinRepositories | None = None,
    config: StrategyOSConfig | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    active_config = config or load_config()
    repo_set = repositories or build_app_repositories()
    if idempotency_key:
        existing = repo_set.execution.find_by_idempotency_key("scheduled_cycle", idempotency_key)
        if existing is not None:
            return _execution_response(existing, idempotent_replay=True)
    execution_id = f"cycle-{uuid4().hex[:12]}"
    logger.info("Twin scheduled cycle start cycle_type=%s execution_id=%s", cycle_type, execution_id)
    repo_set.execution.save({
        "execution_id": execution_id,
        "execution_type": "scheduled_cycle",
        "cycle_type": _normalize_cycle_type(cycle_type),
        "idempotency_key": idempotency_key,
        "status": "running",
        "execution_mode": active_config.run_execution_mode,
        "started_at": datetime.now(UTC).isoformat(),
        "trigger": "scheduler",
    })
    try:
        scheduler = CycleScheduler(
            _build_runtime_registry(repo_set),
            history=CycleHistory(repo_set.cycle_history),
        )
        runner = {
            "daily_standup": scheduler.run_daily_standup,
            "weekly_review": scheduler.run_weekly_review,
            "monthly_board": scheduler.run_monthly_board,
        }[_normalize_cycle_type(cycle_type)]
        result = runner()
        repo_set.execution.update(execution_id, {
            "status": "completed",
            "completed_at": datetime.now(UTC).isoformat(),
            "result": result,
        })
        logger.info("Twin scheduled cycle complete cycle_type=%s execution_id=%s", cycle_type, execution_id)
        return _execution_response(repo_set.execution.load(execution_id) or {}, idempotent_replay=False)
    except Exception as exc:
        logger.exception("Twin scheduled cycle failed execution_id=%s", execution_id)
        repo_set.execution.update(execution_id, {
            "status": "failed",
            "completed_at": datetime.now(UTC).isoformat(),
            "error": str(exc),
        })
        raise


def execute_event_execution_job(
    *,
    max_stale_hours: int = 24,
    repositories: TwinRepositories | None = None,
    config: StrategyOSConfig | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    active_config = config or load_config()
    repo_set = repositories or build_app_repositories()
    if idempotency_key:
        existing = repo_set.execution.find_by_idempotency_key("event_execution", idempotency_key)
        if existing is not None:
            return _execution_response(existing, idempotent_replay=True)
    execution_id = f"event-{uuid4().hex[:12]}"
    logger.info("Twin event execution start execution_id=%s", execution_id)
    repo_set.execution.save({
        "execution_id": execution_id,
        "execution_type": "event_execution",
        "idempotency_key": idempotency_key,
        "status": "running",
        "execution_mode": active_config.run_execution_mode,
        "started_at": datetime.now(UTC).isoformat(),
        "trigger": "live_events",
        "max_stale_hours": max_stale_hours,
    })
    try:
        runtimes = _build_runtime_registry(repo_set)
        kpi_tree = repo_set.kpis.load() or resolution_module.KPI_TREE
        trigger_engine = TriggerEngine(kpi_tree, runtimes)
        threshold_events = [
            {**item, "event_type": "kpi_breach", "trigger_reason": f"KPI breach for {item['node_id']}"}
            for item in trigger_engine.check_thresholds()
        ]
        stale_events = [
            {**item, "event_type": "stale_evidence", "trigger_reason": f"Stale KPI evidence for {item['node_id']}"}
            for item in trigger_engine.check_staleness(max_age_hours=max_stale_hours)
        ]
        approval_deadlines = _collect_approval_deadline_events(repo_set)

        handled: list[dict[str, Any]] = []
        for event in threshold_events + stale_events:
            owner_role = str(event.get("owner") or "")
            if owner_role not in runtimes:
                continue
            investigation_id = trigger_engine.trigger_investigation(
                str(event["node_id"]),
                str(event["trigger_reason"]),
            )
            investigation_record = runtimes[owner_role].state.active_investigations.get(investigation_id)
            if investigation_record is not None:
                repo_set.investigations.save(owner_role, investigation_record)
            summary = runtimes[owner_role].run_once()
            handled.append({
                **event,
                "role": owner_role,
                "investigation_id": investigation_id,
                "cycle_id": summary.get("cycle_id"),
            })

        for event in approval_deadlines:
            repo_set.reasoning.update(event["trace_id"], {
                "approval_disposition": "deadline_escalated",
                "review_state": "pending_human_review",
            })
            repo_set.governance.save_routing_event({
                "event_id": f"route-{uuid4().hex[:12]}",
                "event_type": "escalation",
                "source_role": event["role"],
                "target_role": "human",
                "item_id": event["trace_id"],
                "title": "Reasoning approval deadline exceeded",
                "reason": event["trigger_reason"],
                "actor_role": "system",
                "actor_subject": "twin-runtime:event-engine",
                "timestamp": datetime.now(UTC).isoformat(),
            })
            if event["role"] in runtimes:
                summary = runtimes[event["role"]].run_once()
                handled.append({
                    **event,
                    "cycle_id": summary.get("cycle_id"),
                })

        repo_set.execution.update(execution_id, {
            "status": "completed",
            "completed_at": datetime.now(UTC).isoformat(),
            "result": {
                "events": handled,
                "threshold_count": len(threshold_events),
                "stale_count": len(stale_events),
                "approval_deadline_count": len(approval_deadlines),
            },
        })
        logger.info("Twin event execution complete execution_id=%s events=%s", execution_id, len(handled))
        return _execution_response(repo_set.execution.load(execution_id) or {}, idempotent_replay=False)
    except Exception as exc:
        logger.exception("Twin event execution failed execution_id=%s", execution_id)
        repo_set.execution.update(execution_id, {
            "status": "failed",
            "completed_at": datetime.now(UTC).isoformat(),
            "error": str(exc),
        })
        raise


def _build_runtime_registry(repositories: TwinRepositories) -> dict[str, TwinRuntime]:
    repositories.kpis.ensure_seeded(resolution_module.KPI_TREE)
    runtimes: dict[str, TwinRuntime] = {}
    for twin_persona in persona_module.TWIN_CATALOG.values():
        payload = repositories.states.load(twin_persona.role)
        state = (
            memory_module.TwinState(
                twin_id=str(payload.get("twin_id", "")),
                role=str(payload.get("role", twin_persona.role)),
                active_investigations=dict(payload.get("active_investigations", {})),
                pending_requests=dict(payload.get("pending_requests", {})),
                conversation_history=list(payload.get("conversation_history", [])),
                working_memory=dict(payload.get("working_memory", {})),
                last_wake_at=payload.get("last_wake_at"),
                cycle_count=int(payload.get("cycle_count", 0)),
            )
            if payload is not None
            else memory_module.create_twin_state(twin_persona.role)
        )
        runtimes[twin_persona.role] = TwinRuntime(
            persona=twin_persona,
            state=state,
            repositories=repositories,
        )
    return runtimes


def _collect_approval_deadline_events(repositories: TwinRepositories) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    events: list[dict[str, Any]] = []
    for trace in repositories.reasoning.list(limit=200):
        if str(trace.get("approval_disposition") or "") not in {"pending", ""}:
            continue
        deadline_raw = trace.get("approval_deadline_at")
        if not deadline_raw:
            continue
        try:
            deadline = datetime.fromisoformat(str(deadline_raw))
        except ValueError:
            continue
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        if deadline > now:
            continue
        events.append({
            "event_type": "approval_deadline",
            "trace_id": trace.get("trace_id"),
            "role": trace.get("role"),
            "trigger_reason": f"Approval deadline expired for reasoning trace {trace.get('trace_id')}",
        })
    return events


def _normalize_cycle_type(value: str) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "daily": "daily_standup",
        "daily_standup": "daily_standup",
        "weekly": "weekly_review",
        "weekly_review": "weekly_review",
        "monthly": "monthly_board",
        "monthly_board": "monthly_board",
    }
    resolved = aliases.get(normalized)
    if resolved is None:
        raise ValueError(f"Unsupported twin cycle type: {value}")
    return resolved


def _disabled_execution_response(
    *,
    execution_type: str,
    reason: str,
    cycle_type: str | None = None,
) -> dict[str, Any]:
    payload = {
        "status": "disabled",
        "execution_type": execution_type,
        "reason": reason,
    }
    if cycle_type is not None:
        payload["cycle_type"] = cycle_type
    return payload


def _execution_response(record: dict[str, Any], *, idempotent_replay: bool) -> dict[str, Any]:
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    payload = {
        "status": str(record.get("status") or "unknown"),
        "execution_mode": record.get("execution_mode"),
        "execution_id": record.get("execution_id"),
        "execution_type": record.get("execution_type"),
        "idempotent_replay": idempotent_replay,
    }
    if record.get("cycle_type"):
        payload["cycle_type"] = record.get("cycle_type")
    if record.get("execution_type") == "scheduled_cycle":
        payload["result"] = result
    else:
        payload.update({
            "events": list(result.get("events") or []),
            "threshold_count": int(result.get("threshold_count") or 0),
            "stale_count": int(result.get("stale_count") or 0),
            "approval_deadline_count": int(result.get("approval_deadline_count") or 0),
        })
    return payload
