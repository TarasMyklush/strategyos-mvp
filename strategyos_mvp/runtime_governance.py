from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .agents.pipeline import is_review_gate_stage, is_terminal_stage
from .state_store import create_run, persist_checkpoint

RUNNING_STATUS = "running"
AWAITING_REVIEW_STATUS = "awaiting_review"
COMPLETED_STATUS = "completed"

AWAITING_REVIEW_STAGE = "awaiting_review"


class RuntimeGovernance:
    def __init__(
        self,
        *,
        dataset_root: Path,
        source_pack_id: str | None = None,
        run_dir: Path,
        requires_human_review: bool = True,
        stop_before_writer: bool = True,
    ) -> None:
        self.dataset_root = dataset_root
        self.source_pack_id = source_pack_id
        self.run_dir = run_dir
        self.requires_human_review = requires_human_review
        self.stop_before_writer = stop_before_writer

    def initial_state(self) -> dict[str, Any]:
        state = {
            "dataset_root": self.dataset_root,
            "source_pack_id": self.source_pack_id,
            "run_dir": self.run_dir,
            "run_id": None,
            "workflow_status": RUNNING_STATUS,
            "current_stage": "created",
            "requires_human_review": self.requires_human_review,
            "approval_status": "pending"
            if self.requires_human_review
            else "not_required",
            "checkpoints": [],
            "runtime_record": None,
        }
        record = create_run(
            {
                "dataset": str(self.dataset_root),
                "source_pack_id": self.source_pack_id,
                "run_dir": str(self.run_dir),
                "status": RUNNING_STATUS,
                "current_stage": "created",
            },
            requires_human_review=self.requires_human_review,
        )
        state["runtime_record"] = record
        run_id = record.get("run_id")
        if isinstance(run_id, str):
            state["run_id"] = run_id
        return state

    def checkpoint(self, stage: str, state: dict[str, Any]) -> dict[str, Any]:
        workflow_status = self._workflow_status_for_stage(stage, state)
        approval_status = self._approval_status_for_stage(stage, state)
        updated = {
            **state,
            "workflow_status": workflow_status,
            "current_stage": stage,
            "approval_status": approval_status,
        }
        checkpoint_summary = build_run_summary(updated)
        checkpoint_record = {"status": "skipped", "reason": "run_id is unavailable."}
        run_id = updated.get("run_id")
        if isinstance(run_id, str):
            checkpoint_record = persist_checkpoint(
                run_id,
                stage,
                workflow_status,
                checkpoint_state(updated),
                checkpoint_summary,
            )
        checkpoints = list(updated.get("checkpoints", []))
        checkpoints.append(
            {
                "stage": stage,
                "status": workflow_status,
                "approval_status": approval_status,
                "checkpoint_id": checkpoint_record.get("checkpoint_id"),
                "persistence": checkpoint_record.get("status", "persisted"),
            }
        )
        return {
            **updated,
            "checkpoints": checkpoints,
            "last_checkpoint": checkpoint_record,
        }

    def _workflow_status_for_stage(self, stage: str, state: dict[str, Any]) -> str:
        if is_review_gate_stage(stage):
            return AWAITING_REVIEW_STATUS
        if is_terminal_stage(stage):
            return COMPLETED_STATUS
        return str(state.get("workflow_status") or RUNNING_STATUS)

    def _approval_status_for_stage(self, stage: str, state: dict[str, Any]) -> str:
        if is_review_gate_stage(stage) and self.requires_human_review:
            return "pending"
        return str(state.get("approval_status") or "not_required")


def checkpoint_state(state: dict[str, Any]) -> dict[str, Any]:
    findings = state.get("findings", []) or []
    audit_events = state.get("audit_events", []) or []
    artifacts = state.get("artifacts", {}) or {}
    evidence_qa = state.get("evidence_qa", {}) or {}
    knowledge_graph = state.get("knowledge_graph")
    payload = {
        "run_id": state.get("run_id"),
        "dataset_root": _normalize_value(state.get("dataset_root")),
        "source_pack_id": _normalize_value(state.get("source_pack_id")),
        "run_dir": _normalize_value(state.get("run_dir")),
        "workflow_status": state.get("workflow_status"),
        "current_stage": state.get("current_stage"),
        "requires_human_review": state.get("requires_human_review"),
        "approval_status": state.get("approval_status"),
        "findings": [_normalize_value(finding) for finding in findings],
        "findings_count": len(findings),
        "locked_findings": sum(
            getattr(finding, "status", None) == "locked" for finding in findings
        ),
        "audit_events": [_normalize_value(event) for event in audit_events],
        "audit_event_count": len(audit_events),
        "audit_verification": _normalize_value(state.get("audit_verification") or {}),
        "artifact_keys": sorted(str(key) for key in artifacts.keys()),
        "artifact_paths": {
            str(key): _normalize_value(value) for key, value in artifacts.items()
        },
        "evidence_qa": {
            str(key): _normalize_value(value) for key, value in evidence_qa.items()
        },
        "knowledge_graph": _normalize_value(knowledge_graph),
    }
    return annotate_governance_state(payload)


def build_run_summary(state: dict[str, Any]) -> dict[str, Any]:
    findings = state.get("findings", []) or []
    artifacts = state.get("artifacts", {}) or {}
    workflow_status = state.get("workflow_status", RUNNING_STATUS)
    current_stage = state.get("current_stage")
    approval_status = state.get("approval_status", "not_required")
    payload = {
        "run_id": state.get("run_id"),
        "dataset": _normalize_value(state.get("dataset_root")),
        "source_pack_id": _normalize_value(state.get("source_pack_id")),
        "run_dir": _normalize_value(state.get("run_dir")),
        "findings": len(findings),
        "locked_findings": sum(
            getattr(finding, "status", None) == "locked" for finding in findings
        ),
        "total_recoverable_sar": round(
            sum(
                float(getattr(finding, "recoverable_sar", 0.0)) for finding in findings
            ),
            2,
        ),
        "artifacts": {
            str(key): _normalize_value(value) for key, value in artifacts.items()
        },
        "status": workflow_status,
        "current_stage": current_stage,
        "requires_human_review": bool(state.get("requires_human_review", False)),
        "approval_status": approval_status,
        "checkpoint_count": len(state.get("checkpoints", []) or []),
        "run_outcome": _run_outcome(workflow_status, current_stage),
        "deliverables_status": _deliverables_status(workflow_status, current_stage),
    }
    return annotate_governance_state(payload)


def annotate_governance_state(payload: dict[str, Any]) -> dict[str, Any]:
    workflow_status = payload.get("status") or payload.get("workflow_status")
    current_stage = payload.get("current_stage")
    requires_human_review = bool(payload.get("requires_human_review", False))
    approval_status = str(payload.get("approval_status") or "not_required")
    resume_state = _resume_state(
        workflow_status,
        current_stage,
        requires_human_review,
        approval_status,
    )
    return {
        **payload,
        "review_state": _review_state(
            workflow_status,
            current_stage,
            requires_human_review,
            approval_status,
        ),
        "resume_state": resume_state,
        "resume_ready": resume_state == "ready",
    }


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {key: _normalize_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


def _run_outcome(workflow_status: Any, current_stage: Any) -> str:
    normalized_status = str(workflow_status or "").lower()
    normalized_stage = str(current_stage or "").lower()
    if normalized_status == COMPLETED_STATUS or is_terminal_stage(normalized_stage):
        return "completed"
    if (
        normalized_status == AWAITING_REVIEW_STATUS
        or is_review_gate_stage(normalized_stage)
    ):
        return "awaiting_review"
    return "in_progress"


def _deliverables_status(workflow_status: Any, current_stage: Any) -> str:
    outcome = _run_outcome(workflow_status, current_stage)
    if outcome == "completed":
        return "complete"
    if outcome == "awaiting_review":
        return "paused_before_writer"
    return "in_progress"


def _review_state(
    workflow_status: Any,
    current_stage: Any,
    requires_human_review: bool,
    approval_status: str,
) -> str:
    if not requires_human_review:
        return "not_required"
    normalized_approval = approval_status.lower()
    normalized_status = str(workflow_status or "").lower()
    normalized_stage = str(current_stage or "").lower()
    if normalized_approval == "approved":
        return "approved"
    if normalized_approval == "rejected":
        return "rejected"
    if (
        is_review_gate_stage(normalized_stage)
        or normalized_status == AWAITING_REVIEW_STATUS
    ):
        return "awaiting_decision"
    return "not_reached"


def _resume_state(
    workflow_status: Any,
    current_stage: Any,
    requires_human_review: bool,
    approval_status: str,
) -> str:
    if not requires_human_review:
        return "not_required"
    normalized_approval = approval_status.lower()
    normalized_status = str(workflow_status or "").lower()
    normalized_stage = str(current_stage or "").lower()
    if is_terminal_stage(normalized_stage) or normalized_status == COMPLETED_STATUS:
        return "completed"
    if normalized_approval == "approved" and is_review_gate_stage(normalized_stage):
        return "ready"
    if normalized_approval == "rejected":
        return "blocked_rejected"
    if is_review_gate_stage(normalized_stage):
        return "blocked_pending_review"
    return "not_available"
