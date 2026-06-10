from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agents import CaseFileWriter
from .ingestion import load_dataset
from .models import AuditEvent, Citation, Finding
from .run_registry import update_run_pointers
from .runtime_artifacts import remove_legacy_artifacts
from .runtime_governance import (
    AWAITING_REVIEW_STAGE,
    COMPLETED_STATUS,
    annotate_governance_state,
    build_run_summary,
    checkpoint_state,
)
from .state_store import approval_status_for_run, persist_checkpoint, update_run_summary


def resume_reviewed_run(run_id: str, checkpoint: dict[str, Any]) -> dict[str, Any]:
    state = checkpoint.get("state_json") or {}
    checkpoint_stage = str(
        checkpoint.get("stage") or state.get("current_stage") or ""
    ).lower()
    if checkpoint_stage != AWAITING_REVIEW_STAGE:
        raise ValueError(
            f"Run '{run_id}' cannot resume from checkpoint stage '{checkpoint_stage or 'unknown'}'."
        )
    dataset_root = Path(str(state["dataset_root"])).expanduser().resolve()
    run_dir = Path(str(state["run_dir"])).expanduser().resolve()
    findings = [finding_from_payload(item) for item in state.get("findings", [])]
    audit_events = [
        audit_event_from_payload(item) for item in state.get("audit_events", [])
    ]
    bundle = load_dataset(dataset_root)
    artifacts = {
        str(key): Path(str(value))
        for key, value in (state.get("artifact_paths") or {}).items()
    }
    remove_legacy_artifacts(run_dir)
    artifacts.update(
        CaseFileWriter().write_all(bundle, findings, audit_events, run_dir)
    )
    resumed_state = {
        "run_id": run_id,
        "dataset_root": dataset_root,
        "source_pack_id": state.get("source_pack_id"),
        "run_dir": run_dir,
        "findings": findings,
        "audit_events": audit_events,
        "artifacts": artifacts,
        "workflow_status": COMPLETED_STATUS,
        "current_stage": "writer",
        "requires_human_review": bool(state.get("requires_human_review", True)),
        "approval_status": "approved",
        "checkpoints": [],
    }
    summary = build_run_summary(resumed_state)
    if resumed_state.get("source_pack_id"):
        summary["source_pack"] = {
            "source_pack_id": resumed_state.get("source_pack_id"),
            "normalized_dataset_root": str(dataset_root),
        }
    checkpoint_record = persist_checkpoint(
        run_id,
        "writer",
        COMPLETED_STATUS,
        checkpoint_state(resumed_state),
        summary,
    )
    approval = approval_status_for_run(run_id)
    if isinstance(approval, dict):
        summary["approved_by"] = approval.get("approved_by")
        summary["approved_at"] = approval.get("approved_at")
    summary_path = run_dir / "run_summary.json"
    summary["state_store"] = update_run_summary(run_id, summary)
    summary["resume"] = {"checkpoint": checkpoint_record}
    summary = annotate_governance_state(summary)
    summary["pointer_metadata"] = update_run_pointers(summary, summary_path)
    summary["latest_pointer"] = summary["pointer_metadata"]["latest"]
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def finding_from_payload(payload: dict[str, Any]) -> Finding:
    return Finding(
        finding_id=str(payload["finding_id"]),
        title=str(payload["title"]),
        pattern_type=payload["pattern_type"],
        vendor_id=str(payload["vendor_id"]),
        vendor_name=str(payload["vendor_name"]),
        leakage_sar=float(payload["leakage_sar"]),
        recoverable_sar=float(payload["recoverable_sar"]),
        recoverable_usd=float(payload["recoverable_usd"]),
        confidence=payload["confidence"],
        classification=str(payload["classification"]),
        rationale=str(payload["rationale"]),
        remediation=str(payload["remediation"]),
        citations=[
            citation_from_payload(item) for item in payload.get("citations", [])
        ],
        calculation=dict(payload.get("calculation", {})),
        status=payload.get("status", "draft"),
        challenges=[str(item) for item in payload.get("challenges", [])],
    )


def citation_from_payload(payload: dict[str, Any]) -> Citation:
    return Citation(
        source_path=str(payload["source_path"]),
        locator=str(payload["locator"]),
        excerpt=str(payload.get("excerpt", "")),
        source_hash=payload.get("source_hash"),
    )


def audit_event_from_payload(payload: dict[str, Any]) -> AuditEvent:
    return AuditEvent(
        round_no=int(payload["round_no"]),
        actor=str(payload["actor"]),
        finding_id=str(payload["finding_id"]),
        action=str(payload["action"]),
        detail=str(payload["detail"]),
        challenge=payload.get("challenge"),
        response=payload.get("response"),
        status=str(payload.get("status", "logged")),
        confidence_before=payload.get("confidence_before"),
        confidence_after=payload.get("confidence_after"),
        confidence_change=str(payload.get("confidence_change", "UNCHANGED")),
        started_at=payload.get("started_at"),
        completed_at=payload.get("completed_at"),
        prompt_tokens=payload.get("prompt_tokens"),
        completion_tokens=payload.get("completion_tokens"),
        total_tokens=payload.get("total_tokens"),
        estimated_cost_usd=payload.get("estimated_cost_usd"),
    )
