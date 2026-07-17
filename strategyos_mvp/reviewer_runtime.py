from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
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
    GOVERNED_RELEASE_RECEIPT_FILENAME,
    _quantification_summary,
    annotate_governance_state,
    build_run_summary,
    checkpoint_state,
    governance_fingerprint_for_checkpoint_state,
)
from .state_store import approval_status_for_run, persist_checkpoint, update_run_summary


_APPROVED_CONTEXT_KEYS = (
    "finance_kpi",
    "oracle_kpi",
    "calendar_agenda",
    "historic_context",
    "source_pack",
    "detector_report",
    "run_mode",
    "available_roles",
    "missing_roles",
    "tenant_context",
    "ingestion_job",
    "runtime",
    "plugins",
    "run_policy",
    "external_modes",
)


def _preserve_approved_context(
    summary: dict[str, Any],
    prior_summary: dict[str, Any],
) -> None:
    """Carry approved source-derived context across the writer resume boundary.

    The writer rebuilds the lifecycle summary from checkpoint state, which does
    not contain the enriched finance, calendar, history, or source-governance
    payloads attached after the initial workflow invocation.  Those values are
    part of the exact summary the reviewer approved, so resume must retain them
    without re-reading or re-interpreting the source pack.
    """
    for key in _APPROVED_CONTEXT_KEYS:
        if key in prior_summary:
            summary[key] = deepcopy(prior_summary[key])


def resume_reviewed_run(run_id: str, checkpoint: dict[str, Any]) -> dict[str, Any]:
    state = checkpoint.get("state_json") or {}
    checkpoint_stage = str(
        checkpoint.get("stage") or state.get("current_stage") or ""
    ).lower()
    if checkpoint_stage != AWAITING_REVIEW_STAGE:
        raise ValueError(
            f"Run '{run_id}' cannot resume from checkpoint stage '{checkpoint_stage or 'unknown'}'."
        )
    _validate_checkpoint_for_resume(run_id, checkpoint, state)
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
    release_receipt_path = run_dir / GOVERNED_RELEASE_RECEIPT_FILENAME
    artifacts["governed_release_receipt"] = _write_governed_release_receipt(
        release_receipt_path,
        run_id=run_id,
        checkpoint=checkpoint,
        state=state,
        artifacts=artifacts,
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
    prior_summary = checkpoint.get("summary_json") or {}
    if not isinstance(prior_summary, dict):
        prior_summary = {}
    summary = build_run_summary(resumed_state)
    _preserve_approved_context(summary, prior_summary)
    summary["checkpoint_count"] = int(prior_summary.get("checkpoint_count") or 0) + 1
    if resumed_state.get("source_pack_id"):
        source_pack = dict(summary.get("source_pack") or {})
        source_pack.setdefault("source_pack_id", resumed_state.get("source_pack_id"))
        source_pack.setdefault("normalized_dataset_root", str(dataset_root))
        summary["source_pack"] = source_pack
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
    summary["resume"] = {"checkpoint": _checkpoint_reference(checkpoint_record)}
    summary = annotate_governance_state(summary)
    summary["pointer_metadata"] = update_run_pointers(summary, summary_path)
    summary["latest_pointer"] = summary["pointer_metadata"]["latest"]
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _checkpoint_reference(checkpoint_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "checkpoint_id": checkpoint_record.get("checkpoint_id"),
        "run_id": checkpoint_record.get("run_id"),
        "stage": checkpoint_record.get("stage"),
        "status": checkpoint_record.get("status"),
        "created_at": checkpoint_record.get("created_at"),
        "persistence": checkpoint_record.get("persistence"),
    }


def _validate_checkpoint_for_resume(
    run_id: str,
    checkpoint: dict[str, Any],
    state: dict[str, Any],
) -> None:
    expected_fingerprint = str(
        state.get("checkpoint_fingerprint")
        or (checkpoint.get("summary_json") or {}).get("checkpoint_fingerprint")
        or ""
    )
    actual_fingerprint = governance_fingerprint_for_checkpoint_state(state)
    if expected_fingerprint and expected_fingerprint != actual_fingerprint:
        raise ValueError(
            f"Run '{run_id}' checkpoint fingerprint mismatch; governed resume is blocked."
        )
    expected_quantification = state.get("quantification") or {}
    actual_quantification = _quantification_summary(state)
    if expected_quantification and expected_quantification != actual_quantification:
        raise ValueError(
            f"Run '{run_id}' checkpoint quantification mismatch; governed resume is blocked."
        )
    artifact_integrity = state.get("artifact_integrity") or {}
    if isinstance(artifact_integrity, dict):
        invalid: list[str] = []
        for key, payload in artifact_integrity.items():
            if not isinstance(payload, dict):
                continue
            path_value = payload.get("path")
            if not path_value:
                continue
            path = Path(str(path_value)).expanduser().resolve()
            if not path.exists() or not path.is_file():
                invalid.append(str(key))
                continue
            expected_hash = payload.get("sha256")
            if expected_hash and expected_hash != _sha256_for_path(path):
                invalid.append(str(key))
        if invalid:
            raise ValueError(
                f"Run '{run_id}' has changed or missing governed evidence artifacts: {', '.join(sorted(invalid))}."
            )


def _write_governed_release_receipt(
    path: Path,
    *,
    run_id: str,
    checkpoint: dict[str, Any],
    state: dict[str, Any],
    artifacts: dict[str, Path],
) -> Path:
    payload = {
        "run_id": run_id,
        "released_at": datetime.now(UTC).isoformat(),
        "approved_checkpoint_id": checkpoint.get("checkpoint_id"),
        "approved_checkpoint_fingerprint": state.get("checkpoint_fingerprint"),
        "approved_quantification": state.get("quantification") or {},
        "approval_status": state.get("approval_status"),
        "source_artifacts": state.get("artifact_integrity") or {},
        "final_artifacts": checkpoint_state({"artifacts": artifacts}).get("artifact_integrity")
        or {},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _sha256_for_path(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
