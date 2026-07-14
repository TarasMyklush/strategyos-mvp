"""Phase 11 tests for twin collaboration lifecycle, durability, and scheduler seams."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from strategyos_mvp.config import load_config
from strategyos_mvp.twins.execution import execute_scheduled_cycle_job, submit_scheduled_cycle
from strategyos_mvp.twins.memory import TwinState, create_twin_state
from strategyos_mvp.twins.orchestration import CycleHistory, CycleRecord, GovernanceEngine
from strategyos_mvp.twins.persona import CEO_TWIN, CFO_TWIN
from strategyos_mvp.twins.protocol import InterTwinMessage
from strategyos_mvp.twins.resolution import KPI_TREE, KPIResolutionEngine
from strategyos_mvp.twins.runtime import TwinRuntime
from strategyos_mvp.twins.store import build_repositories
from strategyos_mvp.twins.tools import reconcile_message_routing_audit, send_message


def _apply_env(env_updates: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in env_updates}
    for key, value in env_updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    return original


def _restore_env(original: dict[str, str | None]):
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _load_state(role: str, repositories) -> TwinState:
    payload = repositories.states.load(role)
    assert payload is not None
    return TwinState(
        twin_id=str(payload.get("twin_id") or ""),
        role=str(payload.get("role") or role),
        active_investigations=dict(payload.get("active_investigations") or {}),
        pending_requests=dict(payload.get("pending_requests") or {}),
        conversation_history=list(payload.get("conversation_history") or []),
        working_memory=dict(payload.get("working_memory") or {}),
        last_wake_at=payload.get("last_wake_at"),
        cycle_count=int(payload.get("cycle_count") or 0),
    )


def test_send_message_persists_via_repository(tmp_path):
    repositories = build_repositories(tmp_path / "twins")

    msg = InterTwinMessage(
        message_id="msg-persist-1",
        sender_role="ceo",
        recipient_role="cfo",
        message_type="notification",
        priority="normal",
        subject="Persist this message",
        body="Delivery should hit the inbox repository.",
        created_at="2026-07-07T00:00:00+00:00",
    )

    envelope = send_message(msg, repositories=repositories)

    inbox = repositories.inboxes.load("cfo")
    assert envelope["message_id"] == "msg-persist-1"
    assert inbox[0]["message_id"] == "msg-persist-1"
    assert inbox[0]["subject"] == "Persist this message"
    routing = repositories.governance.list_routing_events()
    assert len(routing) == 1
    assert routing[0]["event_type"] == "message_dispatched"
    assert routing[0]["item_id"] == "msg-persist-1"
    assert routing[0]["audit_source"] == "message_dispatch"

    # Worker retries must not duplicate either the inbox envelope or audit event.
    send_message(msg, repositories=repositories)
    assert len(repositories.inboxes.load("cfo")) == 1
    assert len(repositories.governance.list_routing_events()) == 1


def test_reconcile_message_routing_audit_backfills_legacy_inbox_once(tmp_path):
    repositories = build_repositories(tmp_path / "twins")
    repositories.inboxes.append(
        "cfo",
        {
            "message_id": "legacy-1",
            "sender_role": "ceo",
            "recipient_role": "cfo",
            "message_type": "data_request",
            "priority": "normal",
            "subject": "Legacy governed request",
            "created_at": "2026-07-01T09:00:00+00:00",
            "status": "pending",
        },
    )

    first = reconcile_message_routing_audit(repositories=repositories)
    second = reconcile_message_routing_audit(repositories=repositories)

    assert first == {"scanned": 1, "created": 1, "quarantined": 0}
    assert second == {"scanned": 1, "created": 0, "quarantined": 0}
    routing = repositories.governance.list_routing_events()
    assert len(routing) == 1
    assert routing[0]["item_id"] == "legacy-1"
    assert routing[0]["audit_source"] == "inbox_reconciliation"


def test_reconcile_quarantines_unknown_recipient_and_closes_request(tmp_path):
    repositories = build_repositories(tmp_path / "twins")
    repositories.requests.save(
        "ceo",
        {
            "request_message_id": "legacy-unknown-1",
            "requester_role": "ceo",
            "responder_role": "unknown",
            "status": "pending",
            "created_at": "2026-07-01T09:00:00+00:00",
        },
    )
    repositories.inboxes.append(
        "unknown",
        {
            "message_id": "legacy-unknown-1",
            "sender_role": "ceo",
            "recipient_role": "unknown",
            "message_type": "data_request",
            "subject": "Unowned KPI request",
            "created_at": "2026-07-01T09:00:00+00:00",
            "status": "pending",
        },
    )

    result = reconcile_message_routing_audit(repositories=repositories)

    assert result == {"scanned": 1, "created": 0, "quarantined": 1}
    request = repositories.requests.load("ceo", "legacy-unknown-1")
    assert request is not None
    assert request["status"] == "failed"
    assert request["routing_status"] == "unroutable"
    message = repositories.inboxes.load("unknown")[0]
    assert message["status"] == "expired"
    assert message["routing_status"] == "unroutable"
    rejected = repositories.governance.list_routing_events()
    assert rejected[0]["event_type"] == "message_routing_rejected"


def test_request_response_flow_reconciles_pending_and_persists(tmp_path):
    repositories = build_repositories(tmp_path / "twins")
    repositories.kpis.save(KPI_TREE)
    repositories.kpis.update("cogs_q2", {
        "owner": "cfo",
        "status": "current",
        "value": 11.2,
        "threshold": 12.0,
        "last_updated": "2026-07-07T00:00:00+00:00",
    })

    ceo = TwinRuntime(CEO_TWIN, create_twin_state("ceo"), repositories=repositories)
    gap = KPIResolutionEngine(repository=repositories.kpis).detect_gaps("cogs_q2")[0]
    request = KPIResolutionEngine(repository=repositories.kpis).route_request("cogs_q2", gap, "ceo")

    ceo.act([{"action": "send_data_request", "message": request, "investigation_id": "inv-request-1"}])
    repositories.states.save("ceo", ceo.state)

    cfo = TwinRuntime(CFO_TWIN, create_twin_state("cfo"), repositories=repositories)
    cfo.run_once()

    ceo_reloaded = TwinRuntime(CEO_TWIN, _load_state("ceo", repositories), repositories=repositories)
    ceo_reloaded.run_once()

    assert request.message_id not in ceo_reloaded.state.pending_requests
    request_record = repositories.requests.load("ceo", request.message_id)
    assert request_record is not None
    assert request_record["status"] == "fulfilled"
    assert request_record["response_message_id"] == f"resp-{request.message_id}"
    assert request_record["data_payload"]["kpi_node_id"] == "cogs_q2"
    remembered = ceo_reloaded.state.working_memory[f"request:{request.message_id}"]
    assert remembered["status"] == "fulfilled"
    assert remembered["data"]["kpi_node_id"] == "cogs_q2"


def test_gap_response_marks_request_failed_and_persists(tmp_path):
    repositories = build_repositories(tmp_path / "twins")
    repositories.kpis.save(KPI_TREE)

    ceo = TwinRuntime(CEO_TWIN, create_twin_state("ceo"), repositories=repositories)
    request = InterTwinMessage(
        message_id="req-missing-001",
        sender_role="ceo",
        recipient_role="cfo",
        message_type="data_request",
        priority="high",
        subject="Data request: unknown_margin_driver — missing_data",
        body="Need missing KPI details.",
        metadata={"kpi_node_id": "unknown_margin_driver"},
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    ceo.act([{"action": "send_data_request", "message": request, "investigation_id": "inv-request-2"}])
    repositories.states.save("ceo", ceo.state)

    cfo = TwinRuntime(CFO_TWIN, create_twin_state("cfo"), repositories=repositories)
    cfo.run_once()

    ceo_reloaded = TwinRuntime(CEO_TWIN, _load_state("ceo", repositories), repositories=repositories)
    ceo_reloaded.run_once()

    request_record = repositories.requests.load("ceo", request.message_id)
    assert request_record is not None
    assert request_record["status"] == "failed"
    assert request.message_id not in ceo_reloaded.state.pending_requests
    assert request_record["gaps_remaining"]


def test_governance_audit_and_cycle_history_persist_across_instances(tmp_path):
    repositories = build_repositories(tmp_path / "twins")

    governance = GovernanceEngine(repository=repositories.governance)
    governance.log_decision("cfo", "approve_budget", 125_000.0, True, "human")

    history = CycleHistory(repositories.cycle_history)
    history.record_cycle(
        CycleRecord(
            cycle_id="cycle-persist-1",
            cycle_type="daily_standup",
            started_at="2026-07-07T00:00:00+00:00",
            completed_at="2026-07-07T00:05:00+00:00",
            participants=["ceo", "cfo"],
            findings=[{"role": "ceo"}],
            decisions=[{"action": "send_data_request"}],
            status="completed",
        )
    )

    reloaded = build_repositories(tmp_path / "twins")
    audit = GovernanceEngine(repository=reloaded.governance).get_audit_log()
    cycle = CycleHistory(reloaded.cycle_history).get_cycle("cycle-persist-1")

    assert audit[-1]["role"] == "cfo"
    assert cycle is not None
    assert cycle.cycle_id == "cycle-persist-1"
    assert cycle.participants == ["ceo", "cfo"]


def test_scheduled_cycle_records_history_and_hatchet_queue_status(tmp_path, monkeypatch):
    env = _apply_env({
        "STRATEGYOS_TWINS_ENABLED": "true",
        "STRATEGYOS_TWINS_SCHEDULER_ENABLED": "true",
        "STRATEGYOS_RUN_EXECUTION_MODE": "hatchet",
    })
    try:
        repositories = build_repositories(tmp_path / "twins")
        monkeypatch.setattr(
            "strategyos_mvp.hatchet_runtime.enqueue_twin_cycle",
            lambda payload: {"hatchet_run_id": "hatchet-123", "ref_type": "FakeRef"},
        )

        queued = submit_scheduled_cycle(
            "daily",
            repositories=repositories,
            config=load_config(),
        )
        completed = execute_scheduled_cycle_job(
            cycle_type="daily_standup",
            repositories=repositories,
            config=load_config(),
        )

        queued_record = repositories.execution.load(queued["execution_id"])
        reloaded = build_repositories(tmp_path / "twins")
        recorded_cycles = reloaded.cycle_history.list(limit=5)

        assert queued["status"] == "queued"
        assert queued_record is not None
        assert queued_record["status"] == "queued"
        assert queued_record["result"]["hatchet_run_id"] == "hatchet-123"
        assert completed["status"] == "completed"
        assert recorded_cycles
        assert recorded_cycles[0]["cycle_type"] == "daily_standup"
    finally:
        _restore_env(env)
