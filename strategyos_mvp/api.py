from __future__ import annotations

import html
import json
import socket
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except Exception as exc:  # pragma: no cover - optional cloud dependency
    raise RuntimeError(
        "FastAPI and pydantic are required to run the StrategyOS API."
    ) from exc

from .auth import (
    authenticate_optional_request,
    require_live_health_access,
    require_role,
)
from .config import CONFIG
from .ingestion import load_dataset
from .neo4j_store import check_neo4j_ready, graph_status_for_run
from .ocr import runtime_dependency_status
from .prepare_inputs import prepare_agent_input
from . import qa as qa_engine
from .skills.finance_controls import run_all_finance_skills
from .reviewer_runtime import resume_reviewed_run
from .run_registry import load_latest_run_summary, update_run_pointers
from .run_poc import run_strategyos_workflow
from .runtime_governance import annotate_governance_state, local_run_id_for_dir
from . import state_store
from .state_store import data_management_status, database_connection
from .storage import ObjectStoreUnavailable, S3CompatibleStore, object_store_status
from .source_pack import (
    confirm_source_pack_mapping,
    resolve_source_pack_for_run,
    stage_source_pack_from_path,
    stage_source_pack_uploads,
    validate_source_pack,
)
from .vector_store import (
    check_qdrant_ready,
    search_run_vectors,
    vector_status_for_run,
)


class RunRequest(BaseModel):
    dataset: str | None = None
    source_pack_id: str | None = None
    run_dir: str | None = None
    skip_prepare: bool = False
    sync_artifacts: bool | None = None
    allow_partial_source_pack: bool = False


class ReviewerDecisionRequest(BaseModel):
    comment: str | None = None
    payload: dict[str, Any] | None = None


class SourcePackPathRequest(BaseModel):
    folder_path: str


class SourcePackValidateRequest(BaseModel):
    source_pack_id: str


class SourcePackMappingConfirmRequest(BaseModel):
    source_pack_id: str
    relative_path: str
    role: str | None = None
    column_mapping: dict[str, str] | None = None


class QaRequest(BaseModel):
    question: str
    run_id: str | None = None


app = FastAPI(title="StrategyOS MVP API", version="0.1.0")
STATIC_DIR = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

ARTIFACT_PREVIEW_LIMIT_BYTES = 24_000
ARTIFACT_JSON_PARSE_LIMIT_BYTES = 200_000
ARTIFACT_ACCESS_AUDIT_LOG = "StrategyOS Artifact Access Audit.jsonl"
KNOWLEDGE_GRAPH_ARTIFACT_KEY = "knowledge_graph"
KNOWLEDGE_GRAPH_DEFAULT_VIEW = "findings"
KNOWLEDGE_GRAPH_FULL_LIMIT = 300
KNOWLEDGE_GRAPH_EXPAND_LIMIT = 25
KNOWLEDGE_GRAPH_BASE_EDGE_LABELS = {
    "SUPPORTED_BY",
    "INVOLVES_VENDOR",
    "HAS_CONTRACT",
    "SAME_BANK_ACCOUNT_AS",
    "SAME_TAX_ID_AS",
}
KNOWLEDGE_GRAPH_EXPAND_EDGE_LABELS = {
    "ISSUED_INVOICE",
    "ISSUED_PO",
}
KNOWLEDGE_GRAPH_VISIBLE_EDGE_LABELS = (
    KNOWLEDGE_GRAPH_BASE_EDGE_LABELS
    | KNOWLEDGE_GRAPH_EXPAND_EDGE_LABELS
    | {"MATCHES_PO"}
)
RESTRICTED_ARTIFACT_KEYS = {
    "case_file",
    "case_file_pdf",
    "citation_audit",
    "data_quality_json",
}
RESTRICTED_ARTIFACT_KEY_MARKERS = ("ocr", "citation", "excerpt")
RESTRICTED_ARTIFACT_PATH_MARKERS = (
    "case file",
    "citation audit",
    "ocr",
    "excerpt",
)
UI_LIFECYCLE_STAGES: list[tuple[str, str]] = [
    ("created", "Created"),
    ("ingest", "Ingest"),
    ("analyst", "Analyst"),
    ("auditor", "Auditor"),
    ("evidence_qa", "Evidence QA"),
    ("knowledge_graph", "Knowledge graph"),
    ("awaiting_review", "Awaiting human review"),
    ("writer", "Writer / completed"),
]
UI_LIFECYCLE_STAGE_ALIASES = {
    "governed_review": "awaiting_review",
    "completed": "writer",
}


def _normalize_lifecycle_stage(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "created"
    return UI_LIFECYCLE_STAGE_ALIASES.get(normalized, normalized)


def _run_lifecycle_timeline(record: dict[str, Any]) -> list[dict[str, Any]]:
    latest_checkpoint = record.get("latest_checkpoint") or {}
    approval = record.get("approval") or {}
    approval_status = str(
        approval.get("approval_status")
        or record.get("approval_status")
        or latest_checkpoint.get("state_json", {}).get("approval_status")
        or "pending"
    ).lower()
    status = str(record.get("status") or latest_checkpoint.get("status") or "").lower()
    current_stage = _normalize_lifecycle_stage(
        record.get("current_stage")
        or latest_checkpoint.get("stage")
        or latest_checkpoint.get("state_json", {}).get("current_stage")
    )
    if status == "completed":
        current_stage = "writer"

    stage_order = [stage for stage, _label in UI_LIFECYCLE_STAGES]
    try:
        current_index = stage_order.index(current_stage)
    except ValueError:
        current_index = 0
        current_stage = "created"

    timeline: list[dict[str, Any]] = []
    for index, (stage, label) in enumerate(UI_LIFECYCLE_STAGES):
        state = "pending"
        detail = "Not reached yet."
        if index < current_index:
            state = "completed"
            detail = "Completed before the current workflow position."
        elif index == current_index:
            state = "current"
            detail = "Current workflow position."

        if stage == "created":
            detail = (
                f"Run created at {record.get('created_at')}."
                if record.get("created_at")
                else "Run record created."
            )
        elif stage == "awaiting_review":
            if approval_status == "approved":
                state = "completed" if current_stage == "writer" else "current"
                detail = "Reviewer approved the governed pause; operator resume is allowed."
            elif approval_status == "rejected":
                state = "rejected"
                detail = "Reviewer rejected the run; workflow must not resume as completed."
            elif current_stage == "awaiting_review" or status == "awaiting_review":
                state = "blocked"
                detail = "Paused for mandatory reviewer decision."
        elif stage == "writer":
            if current_stage == "writer" or status == "completed":
                state = "completed"
                detail = "Workflow resumed through writer and completed."
            elif approval_status == "approved":
                detail = "Ready for operator resume into writer/completed."
            elif approval_status == "rejected":
                detail = "Blocked until a new approved governed review path exists."

        timeline.append(
            {
                "stage": stage,
                "label": label,
                "state": state,
                "detail": detail,
                "is_current": stage == current_stage,
            }
        )
    return timeline


def _latest_summary() -> dict[str, Any] | None:
    summary = load_latest_run_summary()
    if summary is None:
        return None
    return _with_local_run_identity(summary)


def _with_local_run_identity(summary: dict[str, Any]) -> dict[str, Any]:
    if summary.get("run_id") or not summary.get("run_dir"):
        return summary
    enriched = dict(summary)
    enriched["run_id"] = local_run_id_for_dir(Path(str(summary["run_dir"])))
    checkpoint = enriched.get("local_review_checkpoint")
    if isinstance(checkpoint, dict):
        checkpoint = dict(checkpoint)
        checkpoint["run_id"] = enriched["run_id"]
        enriched["local_review_checkpoint"] = checkpoint
    return enriched


def _latest_summary_path(summary: dict[str, Any]) -> Path | None:
    pointer = summary.get("latest_pointer")
    if isinstance(pointer, dict) and pointer.get("summary_path"):
        return Path(str(pointer["summary_path"])).expanduser().resolve()
    if summary.get("run_dir"):
        return Path(str(summary["run_dir"])).expanduser().resolve() / "run_summary.json"
    return None


def _local_review_checkpoint_for_run(run_id: str) -> dict[str, Any] | None:
    summary = _latest_summary()
    if not summary or str(summary.get("run_id") or "") != str(run_id):
        return None
    checkpoint = summary.get("local_review_checkpoint")
    if not isinstance(checkpoint, dict):
        if not summary.get("requires_human_review"):
            return None
        if str(summary.get("current_stage") or "").lower() != "awaiting_review":
            return None
        checkpoint = {
            "checkpoint_id": f"local-checkpoint:{run_id}:awaiting_review",
            "run_id": run_id,
            "stage": "awaiting_review",
            "status": "awaiting_review",
            "state_json": {
                "run_id": run_id,
                "dataset_root": summary.get("dataset") or summary.get("dataset_root"),
                "source_pack_id": summary.get("source_pack_id"),
                "run_dir": summary.get("run_dir"),
                "workflow_status": summary.get("status"),
                "current_stage": summary.get("current_stage"),
                "requires_human_review": summary.get("requires_human_review"),
                "approval_status": summary.get("approval_status") or "pending",
                "findings": [],
                "audit_events": [],
                "artifact_paths": summary.get("artifacts") or {},
            },
            "summary_json": summary,
            "persistence": "local_synthesized",
        }
    normalized = dict(checkpoint)
    normalized["run_id"] = run_id
    normalized.setdefault("checkpoint_id", f"local-checkpoint:{run_id}:awaiting_review")
    normalized.setdefault("stage", summary.get("current_stage") or "awaiting_review")
    normalized.setdefault("status", summary.get("status") or "awaiting_review")
    normalized.setdefault("state_json", {})
    normalized.setdefault("summary_json", summary)
    normalized["persistence"] = "local"
    return normalized


def _local_approval_status_for_run(run_id: str) -> dict[str, Any] | None:
    summary = _latest_summary()
    if not summary or str(summary.get("run_id") or "") != str(run_id):
        return None
    decision = summary.get("review_decision")
    return {
        "run_id": run_id,
        "run_status": summary.get("status"),
        "current_stage": summary.get("current_stage"),
        "requires_human_review": bool(summary.get("requires_human_review")),
        "approved_at": summary.get("approved_at"),
        "approved_by": summary.get("approved_by"),
        "approval_status": str(summary.get("approval_status") or "pending"),
        "latest_approval": decision if isinstance(decision, dict) else None,
    }


def _local_pending_review_items() -> list[dict[str, Any]]:
    summary = _latest_summary()
    if not summary:
        return []
    if not summary.get("requires_human_review"):
        return []
    if str(summary.get("status") or "").lower() != "awaiting_review":
        return []
    if str(summary.get("approval_status") or "pending").lower() in {"approved", "rejected"}:
        return []
    run_id = summary.get("run_id")
    if not run_id:
        return []
    checkpoint = _local_review_checkpoint_for_run(str(run_id))
    return [
        {
            "run_id": str(run_id),
            "run_dir": summary.get("run_dir"),
            "dataset_root": summary.get("dataset") or summary.get("dataset_root"),
            "status": summary.get("status"),
            "current_stage": summary.get("current_stage"),
            "requires_human_review": True,
            "checkpoint_id": checkpoint.get("checkpoint_id") if checkpoint else None,
            "checkpoint_stage": "awaiting_review",
            "review_assignment": {"claimed": False, "claimed_by": None, "claimed_at": None},
            "approval_status": str(summary.get("approval_status") or "pending"),
            "source": "local_summary",
        }
    ]


def _write_local_review_summary(
    summary: dict[str, Any],
    summary_path: Path,
) -> dict[str, Any]:
    summary = annotate_governance_state(summary)
    summary["pointer_metadata"] = update_run_pointers(summary, summary_path)
    summary["latest_pointer"] = summary["pointer_metadata"]["latest"]
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _record_local_reviewer_decision(
    *,
    run_id: str,
    decision: str,
    request: ReviewerDecisionRequest,
    principal: dict[str, Any],
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    summary = _latest_summary()
    if not summary or str(summary.get("run_id") or "") != str(run_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' was not found.",
        )
    if str(summary.get("status") or "").lower() != "awaiting_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run '{run_id}' is not awaiting review.",
        )
    approval_status = str(summary.get("approval_status") or "pending").lower()
    if approval_status in {"approved", "rejected"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run '{run_id}' already has reviewer decision '{approval_status}'.",
        )
    summary_path = _latest_summary_path(summary)
    if summary_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' summary file was not found.",
        )
    reviewer_subject = str(principal.get("subject") or "unknown")
    reviewer_role = str(principal.get("role") or "reviewer")
    created_at = datetime.now(UTC).isoformat()
    payload = {
        "decision": decision,
        "comment": request.comment,
        "checkpoint": {
            "checkpoint_id": checkpoint.get("checkpoint_id"),
            "stage": checkpoint.get("stage"),
            "status": checkpoint.get("status"),
        },
        **(request.payload or {}),
    }
    result = {
        "approval_id": f"local-approval:{run_id}:{decision}",
        "run_id": run_id,
        "checkpoint_id": checkpoint.get("checkpoint_id"),
        "reviewer": reviewer_subject,
        "reviewer_subject": reviewer_subject,
        "reviewer_role": reviewer_role,
        "decision": decision,
        "comment": request.comment,
        "payload": payload,
        "created_at": created_at,
        "run_status": decision,
        "current_stage": summary.get("current_stage"),
        "persistence": "local",
    }
    summary["status"] = "awaiting_review"
    summary["current_stage"] = "awaiting_review"
    summary["approval_status"] = decision
    if decision == "approved":
        summary["approved_by"] = reviewer_subject
        summary["approved_at"] = created_at
    summary["review_decision"] = {
        "decision": decision,
        "comment": request.comment,
        "reviewer": reviewer_subject,
        "reviewer_subject": reviewer_subject,
        "created_at": created_at,
        "checkpoint_id": checkpoint.get("checkpoint_id"),
        "persistence": "local",
    }
    _write_local_review_summary(summary, summary_path)
    return result


def _sync_run_summary_review_state(
    *,
    checkpoint: dict[str, Any],
    decision_result: dict[str, Any],
) -> None:
    state_json = checkpoint.get("state_json") or {}
    run_dir_value = state_json.get("run_dir")
    if not run_dir_value:
        return
    summary_path = Path(str(run_dir_value)).expanduser().resolve() / "run_summary.json"
    if not summary_path.exists():
        return
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["status"] = "awaiting_review"
    summary["current_stage"] = "awaiting_review"
    summary["approval_status"] = str(
        decision_result.get("decision") or summary.get("approval_status") or "pending"
    )
    if summary["approval_status"] == "approved":
        summary["approved_by"] = decision_result.get("reviewer") or summary.get(
            "approved_by"
        )
        summary["approved_at"] = decision_result.get("created_at") or summary.get(
            "approved_at"
        )
    summary["review_decision"] = {
        "decision": decision_result.get("decision"),
        "comment": decision_result.get("comment"),
        "reviewer": decision_result.get("reviewer"),
        "reviewer_subject": decision_result.get("reviewer_subject"),
        "created_at": decision_result.get("created_at"),
        "checkpoint_id": checkpoint.get("checkpoint_id"),
    }
    summary = annotate_governance_state(summary)
    summary["pointer_metadata"] = update_run_pointers(summary, summary_path)
    summary["latest_pointer"] = summary["pointer_metadata"]["latest"]
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def _status_label(value: bool) -> str:
    return "Configured" if value else "Missing"


def _display_role(role: str) -> str:
    labels = {
        "operator": "Operator",
        "reviewer": "Reviewer",
        "anonymous": "Anonymous",
        "public": "Public",
    }
    return labels.get(
        role.strip().lower(), role.replace("_", " ").strip().title() or "Unknown"
    )


def _display_subject(subject: str, role: str) -> str:
    raw = subject.strip()
    if not raw or raw == "anonymous":
        return "Anonymous"
    if raw == "auth-disabled":
        return "Auth disabled"
    if raw.startswith("api-key:"):
        return f"{_display_role(role)} API key"
    if "://" in raw:
        raw = raw.rsplit(":", 1)[-1]
    if raw.endswith(".local"):
        raw = raw[: -len(".local")]
    return raw.replace("_", " ").replace(".", " ").strip().title() or _display_role(
        role
    )


def _display_name_for_principal(role: str, subject: str) -> str:
    normalized_role = role.strip().lower()
    if normalized_role in {"operator", "reviewer"}:
        return _display_role(normalized_role)
    return _display_subject(subject, normalized_role)


def _health_check(status: str, **details: Any) -> dict[str, Any]:
    payload = {"status": status}
    payload.update(details)
    return payload


def _artifact_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix == ".md":
        return "text/markdown"
    if suffix in {".txt", ".log", ".csv"}:
        return "text/plain"
    return "application/octet-stream"


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _run_artifact_map(record: dict[str, Any]) -> dict[str, str]:
    summary = record.get("summary_json") or {}
    artifacts = summary.get("artifacts") or {}
    return {str(key): str(value) for key, value in artifacts.items()}


def _checkpoint_artifact_map(record: dict[str, Any]) -> dict[str, str]:
    state_json = record.get("state_json") or {}
    artifacts = state_json.get("artifact_paths") or {}
    return {str(key): str(value) for key, value in artifacts.items()}


def _artifact_restriction_reasons(artifact_key: str, artifact_path: Path) -> list[str]:
    key = artifact_key.strip().lower()
    path_text = str(artifact_path).strip().lower()
    name = artifact_path.name.strip().lower()
    reasons: list[str] = []
    if key in RESTRICTED_ARTIFACT_KEYS:
        reasons.append(f"artifact_key:{key}")
    for marker in RESTRICTED_ARTIFACT_KEY_MARKERS:
        if marker in key:
            reasons.append(f"artifact_key_marker:{marker}")
    for marker in RESTRICTED_ARTIFACT_PATH_MARKERS:
        if marker in path_text or marker in name:
            reasons.append(f"artifact_path_marker:{marker}")
    return sorted(set(reasons))


def _artifact_access_audit_log_path() -> Path:
    return CONFIG.output_root / ARTIFACT_ACCESS_AUDIT_LOG


def _audit_artifact_access(
    *,
    principal: dict[str, Any],
    artifact_key: str,
    artifact_path: Path,
    scope: str,
    run_id: str,
    checkpoint_id: str | None,
    allowed: bool,
    restriction_reasons: list[str],
    detail: str,
) -> None:
    audit_record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "artifact_key": artifact_key,
        "artifact_path": str(artifact_path),
        "scope": scope,
        "run_id": run_id,
        "checkpoint_id": checkpoint_id,
        "principal_role": str(principal.get("role") or "unknown"),
        "principal_subject": str(principal.get("subject") or "unknown"),
        "allowed": allowed,
        "restricted": bool(restriction_reasons),
        "restriction_reasons": restriction_reasons,
        "detail": detail,
    }
    log_path = _artifact_access_audit_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(audit_record, sort_keys=True) + "\n")


def _enforce_artifact_access(
    *,
    principal: dict[str, Any],
    artifact_key: str,
    artifact_path: Path,
    scope: str,
    run_id: str,
    checkpoint_id: str | None = None,
    review_assignment: dict[str, Any] | None = None,
) -> None:
    resolved = artifact_path.expanduser().resolve()
    if not _path_is_within(resolved, CONFIG.output_root):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact path falls outside the configured output boundary.",
        )
    if not resolved.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact '{artifact_key}' does not exist on disk.",
        )

    restriction_reasons = _artifact_restriction_reasons(artifact_key, artifact_path)
    if not restriction_reasons:
        _audit_artifact_access(
            principal=principal,
            artifact_key=artifact_key,
            artifact_path=resolved,
            scope=scope,
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            allowed=True,
            restriction_reasons=[],
            detail="Non-restricted artifact preview allowed.",
        )
        return

    role = str(principal.get("role") or "")
    subject = str(principal.get("subject") or "")
    claimed_by = str((review_assignment or {}).get("claimed_by") or "")
    allowed = role == "operator" or (role == "reviewer" and subject and subject == claimed_by)
    detail = (
        "Restricted artifact preview allowed."
        if allowed
        else "Restricted artifact preview denied: operator or claimed reviewer required."
    )
    _audit_artifact_access(
        principal=principal,
        artifact_key=artifact_key,
        artifact_path=resolved,
        scope=scope,
        run_id=run_id,
        checkpoint_id=checkpoint_id,
        allowed=allowed,
        restriction_reasons=restriction_reasons,
        detail=detail,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Restricted artifacts require operator access or the currently claimed reviewer.",
        )


def _read_artifact_payload(
    *,
    artifact_key: str,
    artifact_path: Path,
    scope: str,
    run_id: str,
    checkpoint_id: str | None = None,
) -> dict[str, Any]:
    resolved = artifact_path.expanduser().resolve()
    if not _path_is_within(resolved, CONFIG.output_root):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact path falls outside the configured output boundary.",
        )
    if not resolved.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact '{artifact_key}' does not exist on disk.",
        )

    payload = {
        "status": "ok",
        "artifact_key": artifact_key,
        "scope": scope,
        "run_id": run_id,
        "checkpoint_id": checkpoint_id,
        "path": str(resolved),
        "name": resolved.name,
        "media_type": _artifact_media_type(resolved),
        "size_bytes": resolved.stat().st_size if resolved.is_file() else 0,
        "preview_kind": "unavailable",
        "preview_text": "",
        "preview_json": None,
        "truncated": False,
    }
    if resolved.is_dir():
        payload.update(
            {
                "preview_kind": "directory",
                "preview_text": "Directory artifacts are not previewed in this thin slice.",
            }
        )
        return payload

    size_bytes = int(payload["size_bytes"])
    with resolved.open("rb") as handle:
        raw = handle.read(ARTIFACT_PREVIEW_LIMIT_BYTES + 1)
    truncated = size_bytes > ARTIFACT_PREVIEW_LIMIT_BYTES
    preview_bytes = raw[:ARTIFACT_PREVIEW_LIMIT_BYTES]

    if b"\x00" in preview_bytes:
        payload.update(
            {
                "preview_kind": "binary",
                "preview_text": "Binary artifact preview is unavailable in this thin slice.",
                "truncated": truncated,
            }
        )
        return payload

    preview_text = preview_bytes.decode("utf-8", errors="ignore")
    if truncated:
        preview_text = f"{preview_text}\n\n… preview truncated …"

    suffix = resolved.suffix.lower()
    preview_kind = "text"
    preview_json = None
    if suffix == ".json":
        preview_kind = "json"
        if size_bytes <= ARTIFACT_JSON_PARSE_LIMIT_BYTES:
            try:
                preview_json = json.loads(resolved.read_text(encoding="utf-8"))
            except Exception:
                preview_json = None

    payload.update(
        {
            "preview_kind": preview_kind,
            "preview_text": preview_text,
            "preview_json": preview_json,
            "truncated": truncated,
        }
    )
    return payload


def _run_artifact_payload(
    run_id: str,
    artifact_key: str,
    principal: dict[str, Any],
) -> dict[str, Any]:
    record = _require_store_record(
        state_store.get_run_detail(run_id),
        missing_detail=f"Run '{run_id}' was not found.",
    )
    assert isinstance(record, dict)
    artifacts = _run_artifact_map(record)
    artifact_path = artifacts.get(artifact_key)
    if artifact_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact '{artifact_key}' was not found for run '{run_id}'.",
        )
    _enforce_artifact_access(
        principal=principal,
        artifact_key=artifact_key,
        artifact_path=Path(artifact_path),
        scope="run",
        run_id=run_id,
        review_assignment=record.get("review_assignment"),
    )
    return _read_artifact_payload(
        artifact_key=artifact_key,
        artifact_path=Path(artifact_path),
        scope="run",
        run_id=run_id,
    )


def _checkpoint_artifact_payload(
    checkpoint_id: str,
    artifact_key: str,
    principal: dict[str, Any],
) -> dict[str, Any]:
    record = _require_store_record(
        state_store.get_checkpoint_detail(checkpoint_id),
        missing_detail=f"Checkpoint '{checkpoint_id}' was not found.",
    )
    assert isinstance(record, dict)
    artifacts = _checkpoint_artifact_map(record)
    artifact_path = artifacts.get(artifact_key)
    if artifact_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Artifact '{artifact_key}' was not found for checkpoint '{checkpoint_id}'."
            ),
        )
    run_id = str(record.get("run_id") or "")
    run_record = _require_store_record(
        state_store.get_run_detail(run_id),
        missing_detail=f"Run '{run_id}' was not found.",
    )
    assert isinstance(run_record, dict)
    _enforce_artifact_access(
        principal=principal,
        artifact_key=artifact_key,
        artifact_path=Path(artifact_path),
        scope="checkpoint",
        run_id=run_id,
        checkpoint_id=checkpoint_id,
        review_assignment=run_record.get("review_assignment"),
    )
    return _read_artifact_payload(
        artifact_key=artifact_key,
        artifact_path=Path(artifact_path),
        scope="checkpoint",
        run_id=run_id,
        checkpoint_id=checkpoint_id,
    )


def _resolve_dataset_path(dataset: str | None, *, skip_prepare: bool) -> Path | None:
    if dataset is None:
        return None
    resolved = Path(dataset).expanduser().resolve()
    allowed_roots = [CONFIG.workspace_root]
    if skip_prepare:
        allowed_roots.append(CONFIG.agent_input_dir)
    if not any(_path_is_within(resolved, root) for root in allowed_roots):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Dataset path must stay within the configured workspace boundary"
                " for local MVP execution."
            ),
        )
    return resolved


def _resolve_run_dir_path(run_dir: str | None) -> Path:
    resolved = (
        Path(run_dir).expanduser().resolve() if run_dir else CONFIG.default_run_dir
    )
    if not _path_is_within(resolved, CONFIG.output_root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Run directory must stay within the configured output boundary"
                " for local MVP execution."
            ),
        )
    return resolved


def _parse_network_target(value: str) -> tuple[str, int]:
    parsed = urlparse(value)
    host = parsed.hostname
    port = parsed.port
    if host is None:
        raise ValueError(f"Unable to parse host from '{value}'.")
    if port is None:
        port = 7687 if parsed.scheme.startswith("bolt") else 6379
    return host, port


def _check_postgres() -> dict[str, Any]:
    connection, skipped = database_connection()
    if skipped is not None:
        return _health_check("skipped", reason=skipped.get("reason"))
    assert connection is not None
    try:
        with connection as conn:
            with conn.cursor() as cur:
                cur.execute("select 1")
                cur.fetchone()
        return _health_check("ok")
    except Exception as exc:
        return _health_check("failed", reason=str(exc))


def _check_redis() -> dict[str, Any]:
    if not CONFIG.redis_url:
        return _health_check("skipped", reason="REDIS_URL is not configured.")
    try:
        host, port = _parse_network_target(CONFIG.redis_url)
        with closing(socket.create_connection((host, port), timeout=3)) as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = sock.recv(16)
        if response.startswith(b"+PONG"):
            return _health_check("ok", host=host, port=port)
        return _health_check(
            "failed",
            host=host,
            port=port,
            reason=f"Unexpected Redis response: {response!r}",
        )
    except Exception as exc:
        return _health_check("failed", reason=str(exc))


def _check_neo4j() -> dict[str, Any]:
    return check_neo4j_ready()


def _check_qdrant() -> dict[str, Any]:
    return check_qdrant_ready()


def _check_object_store() -> dict[str, Any]:
    if not CONFIG.object_store.enabled:
        return _health_check("skipped", reason="Object store is not configured.")
    try:
        store = S3CompatibleStore()
        store.client.head_bucket(Bucket=store.config.bucket)
        return _health_check("ok", bucket=store.config.bucket)
    except ObjectStoreUnavailable as exc:
        return _health_check("failed", reason=str(exc))
    except Exception as exc:
        return _health_check("failed", reason=str(exc))


def _check_workspace() -> dict[str, Any]:
    try:
        CONFIG.output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=CONFIG.output_root, prefix="healthcheck-", delete=True
        ):
            pass
        return _health_check("ok", output_root=str(CONFIG.output_root))
    except Exception as exc:
        return _health_check(
            "failed", output_root=str(CONFIG.output_root), reason=str(exc)
        )


def _check_runtime_dependencies() -> dict[str, Any]:
    return runtime_dependency_status()


def _check_auth_boundary() -> dict[str, Any]:
    if not CONFIG.api_auth_enabled:
        return _health_check("skipped", reason="API auth is disabled.")
    if CONFIG.idp_enabled:
        missing = []
        if not CONFIG.idp_issuer:
            missing.append("STRATEGYOS_IDP_ISSUER")
        if not CONFIG.idp_token_url:
            missing.append("STRATEGYOS_IDP_TOKEN_URL")
        if not CONFIG.idp_introspection_url:
            missing.append("STRATEGYOS_IDP_INTROSPECTION_URL")
        if not CONFIG.idp_client_id:
            missing.append("STRATEGYOS_IDP_CLIENT_ID")
        if not CONFIG.idp_client_secret:
            missing.append("STRATEGYOS_IDP_CLIENT_SECRET")
        if not CONFIG.idp_operator_username or not CONFIG.idp_reviewer_username:
            missing.append("STRATEGYOS_IDP_OPERATOR_USERNAME/STRATEGYOS_IDP_REVIEWER_USERNAME")
        if missing:
            return _health_check(
                "failed",
                reason=f"Local identity provider config is incomplete: {', '.join(missing)}.",
            )
        return _health_check(
            "ok",
            mode="identity-provider",
            issuer=CONFIG.idp_issuer,
            operator_username=CONFIG.idp_operator_username,
            reviewer_username=CONFIG.idp_reviewer_username,
            public_live_health=CONFIG.public_health_enabled,
        )
    if not CONFIG.operator_api_keys:
        return _health_check("failed", reason="STRATEGYOS_OPERATOR_API_KEYS is empty.")
    if not CONFIG.reviewer_api_keys:
        return _health_check("failed", reason="STRATEGYOS_REVIEWER_API_KEYS is empty.")
    return _health_check(
        "ok",
        operator_keys=len(CONFIG.operator_api_keys),
        reviewer_keys=len(CONFIG.reviewer_api_keys),
        public_live_health=CONFIG.public_health_enabled,
    )


def _check_governance_boundary() -> dict[str, Any]:
    if not CONFIG.require_human_review:
        return _health_check("skipped", reason="Human review gate is disabled.")
    if not CONFIG.api_auth_enabled:
        return _health_check(
            "failed", reason="Human review is enabled but API auth is disabled."
        )
    if CONFIG.idp_enabled:
        auth_boundary = _check_auth_boundary()
        if auth_boundary.get("status") != "ok":
            return _health_check(
                "failed",
                reason=str(auth_boundary.get("reason") or "Identity provider is not configured."),
            )
        return _health_check(
            "ok",
            require_human_review=True,
            auth_mode="identity-provider",
        )
    if not CONFIG.operator_api_keys or not CONFIG.reviewer_api_keys:
        return _health_check(
            "failed",
            reason="Human review requires both operator and reviewer API keys.",
        )
    return _health_check("ok", require_human_review=True)


def _ui_environment_label() -> str:
    return "Local broader-testing"


def _ui_bootstrap() -> dict[str, Any]:
    return {
        "product_name": "StrategyOS",
        "shell_title": "StrategyOS Governed Operations",
        "environment": _ui_environment_label(),
        "workspace_root": str(CONFIG.workspace_root),
        "default_run_dir": str(CONFIG.default_run_dir),
        "output_root": str(CONFIG.output_root),
        "api_auth_enabled": CONFIG.api_auth_enabled,
        "idp_enabled": CONFIG.idp_enabled,
        "require_human_review": CONFIG.require_human_review,
        "public_health_enabled": CONFIG.public_health_enabled,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _dashboard_html() -> str:
    bootstrap_json = (
        json.dumps(_ui_bootstrap())
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    template_path = STATIC_DIR / "index.html"
    html_text = template_path.read_text(encoding="utf-8")
    return html_text.replace("__STRATEGYOS_BOOTSTRAP__", bootstrap_json)


def _load_summary_artifact_json(
    summary: dict[str, Any],
    artifact_key: str,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    artifacts = summary.get("artifacts") if isinstance(summary, dict) else None
    if not isinstance(artifacts, dict):
        return None
    artifact_path = artifacts.get(artifact_key)
    if not artifact_path:
        return None
    path = Path(str(artifact_path))
    if not path.exists() or not path.is_file():
        return None
    if path.stat().st_size > ARTIFACT_JSON_PARSE_LIMIT_BYTES:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict) or (
        isinstance(payload, list) and all(isinstance(item, dict) for item in payload)
    ):
        return payload
    return None


def _knowledge_graph_path_from_summary(summary: dict[str, Any]) -> Path | None:
    artifacts = summary.get("artifacts") if isinstance(summary, dict) else None
    if not isinstance(artifacts, dict):
        return None
    artifact_path = artifacts.get(KNOWLEDGE_GRAPH_ARTIFACT_KEY)
    if not artifact_path:
        return None
    path = Path(str(artifact_path)).expanduser().resolve()
    allowed_roots = [CONFIG.output_root]
    run_dir = summary.get("run_dir")
    if run_dir:
        allowed_roots.append(Path(str(run_dir)).expanduser().resolve())
    if not any(_path_is_within(path, root) for root in allowed_roots):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge graph artifact path falls outside the configured output or run boundary.",
        )
    if not path.exists() or not path.is_file():
        return None
    return path


def _load_knowledge_graph_artifact(summary: dict[str, Any]) -> tuple[Path | None, dict[str, Any] | None]:
    path = _knowledge_graph_path_from_summary(summary)
    if path is None:
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Knowledge graph artifact could not be read: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Knowledge graph artifact is not a JSON object.",
        )
    return path, payload


def _kg_node_id(node: dict[str, Any]) -> str:
    return str(node.get("id") or "")


def _kg_node_label(node: dict[str, Any]) -> str:
    return str(node.get("label") or "")


def _kg_node_properties(node: dict[str, Any]) -> dict[str, Any]:
    properties = node.get("properties")
    return properties if isinstance(properties, dict) else {}


def _kg_edge_source(edge: dict[str, Any]) -> str:
    return str(edge.get("source") or "")


def _kg_edge_target(edge: dict[str, Any]) -> str:
    return str(edge.get("target") or "")


def _kg_edge_label(edge: dict[str, Any]) -> str:
    return str(edge.get("label") or "")


def _kg_amount(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _kg_display_for_node(
    node: dict[str, Any],
    *,
    invoice_counts: dict[str, int],
) -> dict[str, Any]:
    node_id = _kg_node_id(node)
    label = _kg_node_label(node)
    properties = _kg_node_properties(node)
    display = node_id
    sublabel = label
    if label == "Finding":
        display = str(properties.get("finding_id") or node_id.removeprefix("Finding:"))
        sublabel = str(properties.get("title") or properties.get("pattern_type") or "Finding")
    elif label == "Vendor":
        display = str(properties.get("vendor_name") or properties.get("vendor_id") or node_id.removeprefix("Vendor:"))
        invoice_count = invoice_counts.get(node_id, 0)
        vendor_id = properties.get("vendor_id") or node_id.removeprefix("Vendor:")
        sublabel = f"{vendor_id} - {invoice_count:,} invoices" if invoice_count else str(vendor_id)
    elif label == "Evidence":
        source_path = str(properties.get("source_path") or node_id.removeprefix("Evidence:"))
        display = Path(source_path).name or source_path
        sublabel = source_path
    elif label == "Contract":
        source_path = str(properties.get("source_path") or node_id.removeprefix("Contract:"))
        display = str(properties.get("contract_reference") or Path(source_path).name or "Contract")
        sublabel = str(properties.get("vendor_id") or source_path)
    elif label == "Invoice":
        display = str(properties.get("invoice_id") or node_id.removeprefix("Invoice:"))
        amount = _kg_amount(properties.get("amount_sar"))
        sublabel = f"SAR {amount:,.0f}" if amount else str(properties.get("status") or "Invoice")
    elif label == "PurchaseOrder":
        display = str(properties.get("po_id") or node_id.removeprefix("PurchaseOrder:"))
        amount = _kg_amount(properties.get("total"))
        sublabel = f"SAR {amount:,.0f}" if amount else str(properties.get("status") or "Purchase order")
    return {
        "id": node_id,
        "label": label,
        "display": display,
        "sublabel": sublabel,
        "properties": properties,
        "recoverable_sar": _kg_amount(properties.get("recoverable_sar")),
        "invoice_count": invoice_counts.get(node_id, 0),
    }


def _kg_edge_view(edge: dict[str, Any]) -> dict[str, Any]:
    source = _kg_edge_source(edge)
    target = _kg_edge_target(edge)
    label = _kg_edge_label(edge)
    properties = edge.get("properties")
    return {
        "id": f"{source}|{label}|{target}",
        "source": source,
        "target": target,
        "label": label,
        "properties": properties if isinstance(properties, dict) else {},
    }


def _kg_invoice_counts(edges: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in edges:
        if _kg_edge_label(edge) != "ISSUED_INVOICE":
            continue
        source = _kg_edge_source(edge)
        counts[source] = counts.get(source, 0) + 1
    return counts


def _knowledge_graph_base_node_ids(
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> set[str]:
    selected: set[str] = {
        node_id
        for node_id, node in nodes_by_id.items()
        if _kg_node_label(node) == "Finding"
    }
    first_hop = True
    while first_hop:
        first_hop = False
        for edge in edges:
            label = _kg_edge_label(edge)
            source = _kg_edge_source(edge)
            target = _kg_edge_target(edge)
            if label in {"SUPPORTED_BY", "INVOLVES_VENDOR"} and source in selected:
                for node_id in (source, target):
                    if node_id not in selected:
                        selected.add(node_id)
                        first_hop = True

    vendor_ids = {
        node_id
        for node_id in selected
        if _kg_node_label(nodes_by_id.get(node_id, {})) == "Vendor"
    }
    for edge in edges:
        label = _kg_edge_label(edge)
        source = _kg_edge_source(edge)
        target = _kg_edge_target(edge)
        if label in {"HAS_CONTRACT", "SAME_BANK_ACCOUNT_AS", "SAME_TAX_ID_AS"} and (
            source in vendor_ids or target in vendor_ids
        ):
            selected.add(source)
            selected.add(target)

    contract_ids = {
        node_id
        for node_id in selected
        if _kg_node_label(nodes_by_id.get(node_id, {})) == "Contract"
    }
    for edge in edges:
        if _kg_edge_label(edge) == "SUPPORTED_BY" and _kg_edge_source(edge) in contract_ids:
            selected.add(_kg_edge_target(edge))
    return selected


def _knowledge_graph_expand_node_ids(
    *,
    expand: str | None,
    limit: int,
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    selected: set[str],
) -> dict[str, Any]:
    if not expand:
        return {"node_id": None, "added": 0, "truncated": 0, "limit": limit}
    if expand not in nodes_by_id:
        return {"node_id": expand, "added": 0, "truncated": 0, "limit": limit, "status": "missing"}

    candidates: list[tuple[float, str, str]] = []
    for edge in edges:
        label = _kg_edge_label(edge)
        source = _kg_edge_source(edge)
        target = _kg_edge_target(edge)
        if label not in KNOWLEDGE_GRAPH_EXPAND_EDGE_LABELS:
            continue
        if source != expand and target != expand:
            continue
        other = target if source == expand else source
        other_props = _kg_node_properties(nodes_by_id.get(other, {}))
        amount = _kg_amount(other_props.get("amount_sar") or other_props.get("total"))
        candidates.append((amount, other, label))

    capped = sorted(candidates, key=lambda item: (-item[0], item[1]))[:limit]
    before = len(selected)
    selected.add(expand)
    for _, node_id, _ in capped:
        selected.add(node_id)

    truncated = max(0, len(candidates) - len(capped))
    return {
        "node_id": expand,
        "added": max(0, len(selected) - before),
        "truncated": truncated,
        "limit": limit,
        "status": "expanded",
    }


def _knowledge_graph_payload(
    *,
    summary: dict[str, Any],
    view: str,
    expand: str | None,
    limit: int,
) -> dict[str, Any]:
    graph_path, graph = _load_knowledge_graph_artifact(summary)
    if graph is None:
        return {
            "status": "missing",
            "run_id": summary.get("run_id"),
            "view": view,
            "reason": "Latest run has no knowledge graph artifact.",
            "nodes": [],
            "edges": [],
            "meta": {},
        }

    raw_nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    raw_edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
    nodes_by_id = {_kg_node_id(node): node for node in raw_nodes if _kg_node_id(node)}
    invoice_counts = _kg_invoice_counts(raw_edges)
    normalized_view = (view or KNOWLEDGE_GRAPH_DEFAULT_VIEW).strip().lower()
    bounded_limit = max(1, min(int(limit or KNOWLEDGE_GRAPH_EXPAND_LIMIT), 100))
    if normalized_view not in {"findings", "full"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Knowledge graph view must be 'findings' or 'full'.",
        )

    if normalized_view == "full":
        selected = set(sorted(nodes_by_id)[:KNOWLEDGE_GRAPH_FULL_LIMIT])
        expansion = {"node_id": None, "added": 0, "truncated": 0, "limit": bounded_limit}
        view_truncated = max(0, len(nodes_by_id) - len(selected))
    else:
        selected = _knowledge_graph_base_node_ids(nodes_by_id, raw_edges)
        expansion = _knowledge_graph_expand_node_ids(
            expand=expand,
            limit=bounded_limit,
            nodes_by_id=nodes_by_id,
            edges=raw_edges,
            selected=selected,
        )
        view_truncated = 0

    selected_edges = [
        edge
        for edge in raw_edges
        if _kg_edge_source(edge) in selected
        and _kg_edge_target(edge) in selected
        and _kg_edge_label(edge) in KNOWLEDGE_GRAPH_VISIBLE_EDGE_LABELS
    ]
    selected_nodes = [
        nodes_by_id[node_id]
        for node_id in sorted(selected)
        if node_id in nodes_by_id
    ]
    graph_meta = graph.get("meta") if isinstance(graph.get("meta"), dict) else {}
    return {
        "status": "ok",
        "run_id": summary.get("run_id"),
        "view": normalized_view,
        "graph_path": str(graph_path) if graph_path else None,
        "nodes": [
            _kg_display_for_node(node, invoice_counts=invoice_counts)
            for node in selected_nodes
        ],
        "edges": [_kg_edge_view(edge) for edge in selected_edges],
        "meta": {
            **graph_meta,
            "source_node_count": len(raw_nodes),
            "source_edge_count": len(raw_edges),
            "view_node_count": len(selected_nodes),
            "view_edge_count": len(selected_edges),
            "view_truncated": view_truncated,
        },
        "expansion": expansion,
    }


def _challenged_finding_ids_from_audit_log(
    payload: dict[str, Any] | list[dict[str, Any]] | None,
) -> list[str]:
    if isinstance(payload, dict):
        events = payload.get("events") or payload.get("records") or payload.get("items") or []
    else:
        events = payload or []
    challenged: set[str] = set()
    for item in events:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").lower()
        status_value = str(item.get("status") or "").lower()
        if action != "challenge" and status_value != "challenged":
            continue
        finding_id = item.get("finding_id")
        if finding_id:
            challenged.add(str(finding_id))
    return sorted(challenged)


def readiness_payload() -> dict[str, Any]:
    checks = {
        "postgres": _check_postgres(),
        "redis": _check_redis(),
        "neo4j": _check_neo4j(),
        "qdrant": _check_qdrant(),
        "object_store": _check_object_store(),
        "workspace": _check_workspace(),
        "ocr_runtime": _check_runtime_dependencies(),
        "auth": _check_auth_boundary(),
        "governance": _check_governance_boundary(),
    }
    statuses = [result.get("status") for result in checks.values()]
    if any(status == "failed" for status in statuses):
        overall = "failed"
    elif any(status == "skipped" for status in statuses):
        overall = "degraded"
    else:
        overall = "ok"
    return {
        "status": overall,
        "workspace_root": str(CONFIG.workspace_root),
        "output_root": str(CONFIG.output_root),
        "checks": checks,
    }


def _require_store_record(
    record: dict[str, Any] | list[dict[str, Any]] | None,
    *,
    missing_detail: str,
) -> dict[str, Any] | list[dict[str, Any]]:
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=missing_detail,
        )
    if isinstance(record, dict):
        record_status = record.get("status")
        if record_status == "missing":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=missing_detail,
            )
        if record_status == "skipped":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(record.get("reason") or "State store is unavailable."),
            )
    return record


def _require_store_mutation_result(
    record: dict[str, Any] | None,
    *,
    missing_detail: str,
    conflict_detail: str,
) -> dict[str, Any]:
    result = _require_store_record(record, missing_detail=missing_detail)
    assert isinstance(result, dict)
    if result.get("status") == "conflict":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(result.get("reason") or conflict_detail),
        )
    return result


def _record_reviewer_decision(
    *,
    run_id: str,
    decision: str,
    request: ReviewerDecisionRequest,
    principal: dict[str, Any],
) -> dict[str, Any]:
    checkpoint_record = state_store.latest_checkpoint(run_id)
    local_checkpoint = None
    if isinstance(checkpoint_record, dict) and checkpoint_record.get("status") == "skipped":
        local_checkpoint = _local_review_checkpoint_for_run(run_id)
        checkpoint_record = local_checkpoint
    checkpoint = _require_store_record(
        checkpoint_record,
        missing_detail=f"No checkpoint found for run '{run_id}'.",
    )
    assert isinstance(checkpoint, dict)
    reviewer_subject = str(principal.get("subject") or "unknown")
    reviewer_role = str(principal.get("role") or "reviewer")
    payload = {
        "decision": decision,
        "comment": request.comment,
        "checkpoint": {
            "checkpoint_id": checkpoint.get("checkpoint_id"),
            "stage": checkpoint.get("stage"),
            "status": checkpoint.get("status"),
        },
        **(request.payload or {}),
    }
    if local_checkpoint is not None:
        return _record_local_reviewer_decision(
            run_id=run_id,
            decision=decision,
            request=request,
            principal=principal,
            checkpoint=checkpoint,
        )
    result = _require_store_mutation_result(
        state_store.record_approval(
            run_id,
            str(checkpoint["checkpoint_id"]),
            reviewer_subject,
            reviewer_subject,
            reviewer_role,
            decision,
            request.comment,
            payload,
        ),
        missing_detail=f"Unable to record review decision for run '{run_id}'.",
        conflict_detail=f"Unable to record review decision for run '{run_id}'.",
    )
    _sync_run_summary_review_state(checkpoint=checkpoint, decision_result=result)
    return result


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return _dashboard_html()


@app.get("/ui/session")
def ui_session(
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> dict[str, Any]:
    authenticated = bool(principal.get("authenticated"))
    role = str(principal.get("role") or "anonymous")
    subject = str(principal.get("subject") or "anonymous")
    display_role = _display_role(role)
    display_subject = _display_subject(subject, role)
    display_name = _display_name_for_principal(role, subject)
    return {
        "status": "ok",
        "authenticated": authenticated,
        "role": role,
        "subject": subject,
        "display_role": display_role,
        "display_subject": display_subject,
        "display_name": display_name,
        "auth_disabled": bool(principal.get("auth_disabled", False)),
        "api_auth_enabled": CONFIG.api_auth_enabled,
        "idp_enabled": CONFIG.idp_enabled,
        "public_health_enabled": CONFIG.public_health_enabled,
        "require_human_review": CONFIG.require_human_review,
        "environment": _ui_environment_label(),
        "default_run_dir": str(CONFIG.default_run_dir),
        "output_root": str(CONFIG.output_root),
    }


@app.get("/health")
def health(
    _: dict[str, Any] = Depends(require_live_health_access),
) -> dict[str, Any]:
    return {
        "status": "ok",
        "workspace_root": str(CONFIG.workspace_root),
        "output_root": str(CONFIG.output_root),
        "public_health_enabled": CONFIG.public_health_enabled,
    }


@app.get("/health/live")
def health_live(
    _: dict[str, Any] = Depends(require_live_health_access),
) -> dict[str, Any]:
    return {
        "status": "ok",
        "workspace_root": str(CONFIG.workspace_root),
        "output_root": str(CONFIG.output_root),
        "public_health_enabled": CONFIG.public_health_enabled,
    }


@app.get("/health/ready")
def health_ready(
    _: dict[str, Any] = require_role("operator", "reviewer"),
) -> JSONResponse:
    payload = readiness_payload()
    status_code = 200 if payload["status"] in {"ok", "degraded"} else 503
    return JSONResponse(content=payload, status_code=status_code)


@app.get("/health/config")
def health_config(
    _: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    return {
        "status": "ok",
        "object_store": object_store_status(),
        "ocr_runtime_dependencies": runtime_dependency_status(),
        "database_configured": bool(CONFIG.database_url),
        "redis_configured": bool(CONFIG.redis_url),
        "neo4j_configured": bool(CONFIG.neo4j_uri),
        "api_auth_enabled": CONFIG.api_auth_enabled,
        "require_human_review": CONFIG.require_human_review,
    }


@app.get("/health/dependencies")
def health_dependencies(
    _: dict[str, Any] = require_role("operator", "reviewer"),
) -> JSONResponse:
    payload = runtime_dependency_status()
    status_code = 200 if payload["status"] == "ok" else 503
    return JSONResponse(content=payload, status_code=status_code)


def _store_list_or_empty(
    record: dict[str, Any] | list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], str]:
    """List endpoints tolerate an unconfigured local store.

    When the state store is simply not configured (local-only mode, no
    DATABASE_URL), there is genuinely nothing persisted to list, so we return an
    empty list with a ``store_status`` of ``skipped`` rather than a 503. A real
    store error still surfaces as 503 via _require_store_record.
    """
    if isinstance(record, dict) and record.get("status") in {"skipped", "missing"}:
        return [], str(record.get("status"))
    items = _require_store_record(record, missing_detail="Records are unavailable.")
    assert isinstance(items, list)
    return items, "ok"


@app.get("/reviewer/pending-reviews")
def pending_reviews(
    principal: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    items, store_status = _store_list_or_empty(state_store.list_pending_reviews())
    if store_status == "skipped":
        items = _local_pending_review_items()
    role = str(principal.get("role") or "unknown")
    subject = str(principal.get("subject") or "unknown")
    return {
        "items": items,
        "store_status": store_status,
        "viewer_role": role,
        "viewer_subject": subject,
        "viewer_display_name": _display_name_for_principal(role, subject),
    }


@app.get("/reviewer/runs")
def reviewer_runs(
    limit: int = 12,
    principal: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    items, store_status = _store_list_or_empty(state_store.list_recent_runs(limit=limit))
    if store_status == "skipped":
        items = _local_pending_review_items()
    role = str(principal.get("role") or "unknown")
    subject = str(principal.get("subject") or "unknown")
    return {
        "items": items,
        "store_status": store_status,
        "viewer_role": role,
        "viewer_subject": subject,
        "viewer_display_name": _display_name_for_principal(role, subject),
    }


@app.get("/reviewer/runs/{run_id}")
def reviewer_run_detail(
    run_id: str,
    _: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    record = _require_store_record(
        state_store.get_run_detail(run_id),
        missing_detail=f"Run '{run_id}' was not found.",
    )
    assert isinstance(record, dict)
    record["lifecycle_timeline"] = _run_lifecycle_timeline(record)
    return record


@app.get("/reviewer/checkpoints/{checkpoint_id}")
def reviewer_checkpoint_detail(
    checkpoint_id: str,
    _: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    record = _require_store_record(
        state_store.get_checkpoint_detail(checkpoint_id),
        missing_detail=f"Checkpoint '{checkpoint_id}' was not found.",
    )
    assert isinstance(record, dict)
    return record


@app.get("/reviewer/runs/{run_id}/artifacts/{artifact_key}")
def reviewer_run_artifact_preview(
    run_id: str,
    artifact_key: str,
    principal: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    return _run_artifact_payload(run_id, artifact_key, principal)


@app.get("/reviewer/checkpoints/{checkpoint_id}/artifacts/{artifact_key}")
def reviewer_checkpoint_artifact_preview(
    checkpoint_id: str,
    artifact_key: str,
    principal: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    return _checkpoint_artifact_payload(checkpoint_id, artifact_key, principal)


@app.post("/reviewer/runs/{run_id}/claim")
def claim_run(
    run_id: str,
    principal: dict[str, Any] = require_role("reviewer"),
) -> dict[str, Any]:
    reviewer_subject = str(principal.get("subject") or "unknown")
    return _require_store_mutation_result(
        state_store.claim_pending_review(run_id, reviewer_subject),
        missing_detail=f"Run '{run_id}' was not found.",
        conflict_detail=f"Run '{run_id}' is not available for claim.",
    )


@app.post("/reviewer/runs/{run_id}/unclaim")
def unclaim_run(
    run_id: str,
    principal: dict[str, Any] = require_role("reviewer"),
) -> dict[str, Any]:
    reviewer_subject = str(principal.get("subject") or "unknown")
    return _require_store_mutation_result(
        state_store.unclaim_pending_review(run_id, reviewer_subject),
        missing_detail=f"Run '{run_id}' was not found.",
        conflict_detail=f"Run '{run_id}' is not currently claimed.",
    )


@app.post("/reviewer/runs/{run_id}/approve")
def approve_run(
    run_id: str,
    request: ReviewerDecisionRequest,
    principal: dict[str, Any] = require_role("reviewer"),
) -> dict[str, Any]:
    return _record_reviewer_decision(
        run_id=run_id,
        decision="approved",
        request=request,
        principal=principal,
    )


@app.post("/reviewer/runs/{run_id}/reject")
def reject_run(
    run_id: str,
    request: ReviewerDecisionRequest,
    principal: dict[str, Any] = require_role("reviewer"),
) -> dict[str, Any]:
    return _record_reviewer_decision(
        run_id=run_id,
        decision="rejected",
        request=request,
        principal=principal,
    )


@app.post("/operator/runs/{run_id}/resume")
def resume_run(
    run_id: str,
    _: dict[str, Any] = require_role("operator"),
) -> dict[str, Any]:
    approval_record = state_store.approval_status_for_run(run_id)
    if isinstance(approval_record, dict) and approval_record.get("status") == "skipped":
        approval_record = _local_approval_status_for_run(run_id)
    approval = _require_store_record(
        approval_record,
        missing_detail=f"Run '{run_id}' was not found.",
    )
    assert isinstance(approval, dict)
    if approval.get("approval_status") != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run '{run_id}' is not approved for resume.",
        )
    current_stage = _normalize_lifecycle_stage(approval.get("current_stage"))
    run_status = str(approval.get("run_status") or "").lower()
    if run_status == "completed" or current_stage == "writer":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run '{run_id}' already completed its writer deliverables.",
        )
    if current_stage != "awaiting_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Run '{run_id}' is at stage '{current_stage or 'unknown'}', not awaiting review."
            ),
        )
    checkpoint_record = state_store.latest_checkpoint(run_id)
    if isinstance(checkpoint_record, dict) and checkpoint_record.get("status") == "skipped":
        checkpoint_record = _local_review_checkpoint_for_run(run_id)
    checkpoint = _require_store_record(
        checkpoint_record,
        missing_detail=f"No checkpoint found for run '{run_id}'.",
    )
    assert isinstance(checkpoint, dict)
    checkpoint_stage = _normalize_lifecycle_stage(checkpoint.get("stage"))
    if checkpoint_stage != "awaiting_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Run '{run_id}' latest checkpoint is '{checkpoint_stage or 'unknown'}', not awaiting review."
            ),
    )
    return resume_reviewed_run(run_id, checkpoint)


@app.post("/source-packs")
def create_source_pack(
    files: list[UploadFile] = File(...),
    _: dict[str, Any] = require_role("operator"),
) -> dict[str, Any]:
    return stage_source_pack_uploads(files)


@app.post("/source-packs/from-path")
def create_source_pack_from_path(
    request: SourcePackPathRequest,
    _: dict[str, Any] = require_role("operator"),
) -> dict[str, Any]:
    return stage_source_pack_from_path(request.folder_path)


@app.post("/source-packs/validate")
def validate_source_pack_endpoint(
    request: SourcePackValidateRequest,
    _: dict[str, Any] = require_role("operator"),
) -> dict[str, Any]:
    return validate_source_pack(request.source_pack_id)


@app.post("/source-packs/confirm-mapping")
def confirm_source_pack_mapping_endpoint(
    request: SourcePackMappingConfirmRequest,
    _: dict[str, Any] = require_role("operator"),
) -> dict[str, Any]:
    return confirm_source_pack_mapping(
        request.source_pack_id,
        request.relative_path,
        role=request.role,
        column_mapping=request.column_mapping,
    )


@app.post("/runs")
def create_run(
    request: RunRequest,
    _: dict[str, Any] = require_role("operator"),
) -> dict[str, Any]:
    source_pack_id = (request.source_pack_id or "").strip() or None
    if source_pack_id and request.dataset:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run creation accepts either dataset or source_pack_id, not both.",
        )

    dataset = _resolve_dataset_path(request.dataset, skip_prepare=request.skip_prepare)
    run_dir = _resolve_run_dir_path(request.run_dir)
    if source_pack_id:
        resolve_source_pack_for_run(
            source_pack_id, allow_partial=bool(request.allow_partial_source_pack)
        )
    summary = run_strategyos_workflow(
        dataset=dataset,
        source_pack_id=source_pack_id,
        run_dir=run_dir,
        skip_prepare=request.skip_prepare if source_pack_id is None else True,
        sync_artifacts=request.sync_artifacts,
        allow_partial_source_pack=bool(request.allow_partial_source_pack),
    )
    return summary


@app.get("/runs/latest")
def latest_run(
    _: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    summary = _latest_summary()
    if summary is None:
        return {"status": "missing", "run_dir": str(CONFIG.default_run_dir)}
    return summary


@app.get("/runs/latest/audit-summary")
def latest_run_audit_summary(
    _: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    summary = _latest_summary()
    if summary is None:
        return {
            "status": "missing",
            "challenged_finding_ids": [],
            "citation_count": None,
            "resolved_count": None,
        }

    citation_payload = _load_summary_artifact_json(summary, "citation_audit")
    citation_summary = (
        citation_payload.get("summary")
        if isinstance(citation_payload, dict)
        and isinstance(citation_payload.get("summary"), dict)
        else {}
    )
    acceptance = summary.get("acceptance") if isinstance(summary.get("acceptance"), dict) else {}
    audit_payload = _load_summary_artifact_json(summary, "audit_log")
    challenged_ids = _challenged_finding_ids_from_audit_log(audit_payload)
    verification = summary.get("audit_verification")
    if not challenged_ids and isinstance(verification, dict):
        raw_ids = verification.get("challenged_finding_ids") or []
        if isinstance(raw_ids, list):
            challenged_ids = sorted(str(item) for item in raw_ids if item)

    return {
        "status": "ok",
        "run_id": summary.get("run_id"),
        "run_dir": summary.get("run_dir"),
        "challenged_finding_ids": challenged_ids,
        "citation_count": citation_summary.get(
            "citation_count", acceptance.get("citation_count")
        ),
        "resolved_count": citation_summary.get(
            "resolved_count", acceptance.get("resolved_citation_count")
        ),
    }


@app.get("/runs/latest/knowledge-graph")
def latest_run_knowledge_graph(
    view: str = KNOWLEDGE_GRAPH_DEFAULT_VIEW,
    expand: str | None = None,
    limit: int = KNOWLEDGE_GRAPH_EXPAND_LIMIT,
    _: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    summary = _latest_summary()
    if summary is None:
        return {
            "status": "missing",
            "view": view,
            "reason": "No latest run is available.",
            "nodes": [],
            "edges": [],
            "meta": {},
        }
    return _knowledge_graph_payload(
        summary=summary,
        view=view,
        expand=expand,
        limit=limit,
    )


@app.get("/data/status")
def data_status(
    _: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    status_payload = data_management_status()
    run_id = status_payload.get("run_id")
    if run_id is None:
        latest_summary = _latest_summary() or {}
        run_id = latest_summary.get("run_id")
    status_payload["neo4j"] = graph_status_for_run(str(run_id) if run_id else None)
    status_payload["qdrant"] = vector_status_for_run(str(run_id) if run_id else None)
    return status_payload


@app.get("/data/vector-search")
def vector_search(
    query: str,
    run_id: str | None = None,
    limit: int = 5,
    _: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    if run_id is None:
        latest_summary = _latest_summary() or {}
        run_id = latest_summary.get("run_id")
    return search_run_vectors(str(run_id) if run_id else None, query, limit=limit)


# Cache reloaded Q&A contexts by a stable run key so repeated chat questions do
# not reload the dataset each time. Keyed by (dataset_root, run_mode).
_QA_CONTEXT_CACHE: dict[tuple[str, str, str], dict[str, Any]] = {}


def _qa_summary_for_run(run_id: str | None) -> dict[str, Any]:
    if run_id:
        record = state_store.get_run_detail(run_id)
        if isinstance(record, dict) and record.get("status") == "missing":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run '{run_id}' was not found.",
            )
        if isinstance(record, dict) and record.get("status") == "skipped":
            latest = _latest_summary() or {}
            if str(latest.get("run_id") or "") == str(run_id):
                return latest
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Run lookup is unavailable because the state store is not configured. "
                    "Omit run_id to use the latest local run."
                ),
            )
        if not isinstance(record, dict):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run '{run_id}' was not found.",
            )
        summary = dict(record.get("summary_json") or {})
        if record.get("dataset_root") and not summary.get("dataset"):
            summary["dataset"] = record["dataset_root"]
        if record.get("run_dir") and not summary.get("run_dir"):
            summary["run_dir"] = record["run_dir"]
        summary["run_id"] = run_id
        return summary
    return _latest_summary() or {}


def _resolve_qa_context(run_id: str | None) -> dict[str, Any]:
    """Reload the bundle + findings for a run so Q&A can compute fresh answers.

    Uses the latest run when run_id is omitted. Returns a context dict with the
    bundle, findings, and the resolved run identifiers, or raises HTTPException
    with actionable guidance when no answerable run exists.
    """
    summary = _qa_summary_for_run(run_id)
    resolved_run_id = summary.get("run_id") or run_id
    dataset_root = summary.get("dataset") or summary.get("dataset_root")
    run_mode = str(summary.get("run_mode") or "full")
    if not dataset_root:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed run is available to answer questions yet. Start a run first.",
        )
    cache_run_key = str(resolved_run_id or dataset_root)
    cache_key = (cache_run_key, str(dataset_root), run_mode)
    cached = _QA_CONTEXT_CACHE.get(cache_key)
    if cached is None:
        dataset_path = Path(str(dataset_root))
        if not dataset_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"The run's source data is no longer available at {dataset_root}.",
            )
        try:
            bundle = load_dataset(dataset_path, strict=(run_mode != "partial"))
            findings = run_all_finance_skills(bundle)
        except Exception as exc:  # pragma: no cover - defensive reload guard
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not reload the run's data for Q&A: {exc}",
            ) from exc
        cached = {"bundle": bundle, "findings": findings}
        _QA_CONTEXT_CACHE[cache_key] = cached
    return {
        "bundle": cached["bundle"],
        "findings": cached["findings"],
        "run_id": resolved_run_id,
        "run_mode": run_mode,
    }


@app.post("/qa")
def data_qa(
    request: QaRequest,
    _: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    question = (request.question or "").strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ask a question, e.g. 'What is the total amount of invoices?'.",
        )
    context = _resolve_qa_context(request.run_id)
    result = qa_engine.answer_question(
        question, bundle=context["bundle"], findings=context["findings"]
    )
    return {
        "status": "ok",
        "run_id": context["run_id"],
        "run_mode": context["run_mode"],
        "question": question,
        **result,
    }


@app.post("/inputs/prepare")
def prepare_inputs(
    _: dict[str, Any] = require_role("operator"),
) -> dict[str, str]:
    agent_input, evaluation = prepare_agent_input()
    return {"agent_input": str(agent_input), "evaluation": str(evaluation)}
