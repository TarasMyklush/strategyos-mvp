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
from .runtime_governance import annotate_governance_state
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

ARTIFACT_PREVIEW_LIMIT_BYTES = 24_000
ARTIFACT_JSON_PARSE_LIMIT_BYTES = 200_000
ARTIFACT_ACCESS_AUDIT_LOG = "StrategyOS Artifact Access Audit.jsonl"
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
    return load_latest_run_summary()


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
    return f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>StrategyOS Governed Operations</title>
        <style>
          :root {{
            color-scheme: light;
            --bg: #f3f5f8;
            --panel: #ffffff;
            --panel-alt: #f8fafc;
            --ink: #16202a;
            --muted: #5a697a;
            --border: #dbe3ec;
            --accent: #1459b8;
            --accent-soft: #e8f0ff;
            --ok: #176335;
            --ok-soft: #e8f6ed;
            --warn: #9a3412;
            --warn-soft: #fff1e8;
            --danger: #b42318;
            --danger-soft: #fdeceb;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: var(--bg);
            color: var(--ink);
          }}
          * {{ box-sizing: border-box; }}
          body {{ margin: 0; min-height: 100vh; background: var(--bg); color: var(--ink); }}
          a {{ color: var(--accent); text-decoration: none; }}
          a:hover {{ text-decoration: underline; }}
          button, input, textarea {{ font: inherit; }}
          .shell {{ display: grid; grid-template-columns: 260px minmax(0, 1fr); min-height: 100vh; }}
          .sidebar {{ background: #0f1720; color: #eef3f9; padding: 28px 20px; display: grid; align-content: start; gap: 24px; }}
          .brand h1 {{ font-size: 24px; margin: 0 0 8px; }}
          .brand p, .sidebar small {{ color: #a9b9ca; margin: 0; line-height: 1.5; }}
          .nav {{ display: grid; gap: 8px; }}
          .nav button {{ width: 100%; text-align: left; border: 1px solid transparent; background: transparent; color: inherit; padding: 12px 14px; border-radius: 10px; cursor: pointer; }}
          .nav button.active, .nav button:hover {{ background: rgba(255,255,255,0.08); border-color: rgba(255,255,255,0.08); }}
          .nav .meta {{ display: block; font-size: 12px; color: #a9b9ca; margin-top: 4px; }}
          .sidebar-card {{ border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 14px; background: rgba(255,255,255,0.04); display: grid; gap: 10px; }}
          .sidebar-card strong {{ font-size: 13px; letter-spacing: 0.02em; text-transform: uppercase; }}
          .content {{ padding: 28px; display: grid; gap: 18px; }}
          .topbar {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; flex-wrap: wrap; }}
          .topbar h2 {{ margin: 0 0 8px; font-size: 30px; line-height: 1.1; }}
          .topbar p {{ margin: 0; color: var(--muted); max-width: 760px; line-height: 1.6; }}
          .badges {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
          .badge {{ display: inline-flex; align-items: center; gap: 8px; border-radius: 999px; border: 1px solid var(--border); background: var(--panel); padding: 8px 12px; font-size: 13px; font-weight: 700; }}
          .panel {{ background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 20px; box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04); }}
          .panel h3 {{ margin: 0 0 8px; font-size: 18px; }}
          .panel p {{ margin: 0; color: var(--muted); line-height: 1.5; }}
          .auth-panel {{ display: grid; gap: 14px; }}
          .auth-grid {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: end; }}
          label {{ display: grid; gap: 6px; font-size: 13px; font-weight: 700; color: var(--muted); }}
          input, textarea {{ width: 100%; border: 1px solid var(--border); border-radius: 10px; padding: 11px 12px; background: #fff; color: var(--ink); }}
          textarea {{ min-height: 84px; resize: vertical; }}
          .button-row {{ display: flex; gap: 10px; flex-wrap: wrap; }}
          .button, button.button {{ border: 1px solid var(--accent); background: var(--accent); color: #fff; border-radius: 10px; padding: 10px 14px; font-weight: 700; cursor: pointer; }}
          .button.secondary {{ background: #fff; color: var(--accent); border-color: var(--border); }}
          .button.danger {{ background: var(--danger); border-color: var(--danger); }}
          .button[disabled] {{ opacity: 0.5; cursor: not-allowed; }}
          .banner {{ border-radius: 14px; padding: 14px 16px; border: 1px solid var(--border); background: var(--panel-alt); }}
          .banner strong {{ display: block; margin-bottom: 4px; }}
          .banner.ok {{ background: var(--ok-soft); border-color: #c7e6d3; }}
          .banner.warn {{ background: var(--warn-soft); border-color: #f5d2bf; }}
          .banner.danger {{ background: var(--danger-soft); border-color: #f2c3bf; }}
          .kpis {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }}
          .kpi {{ background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 16px; }}
          .kpi span {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.03em; }}
          .kpi strong {{ display: block; font-size: 28px; line-height: 1.1; }}
          .two-col {{ display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.8fr); gap: 16px; align-items: start; }}
          table {{ width: 100%; border-collapse: collapse; }}
          th, td {{ padding: 12px 10px; border-bottom: 1px solid #edf1f5; text-align: left; vertical-align: top; font-size: 14px; }}
          th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.03em; }}
          td code, .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; overflow-wrap: anywhere; }}
          .pill {{ display: inline-flex; align-items: center; border-radius: 999px; padding: 4px 9px; font-size: 12px; font-weight: 700; border: 1px solid var(--border); background: var(--panel-alt); }}
          .pill.ok {{ color: var(--ok); background: var(--ok-soft); border-color: #c7e6d3; }}
          .pill.warn {{ color: var(--warn); background: var(--warn-soft); border-color: #f5d2bf; }}
          .pill.danger {{ color: var(--danger); background: var(--danger-soft); border-color: #f2c3bf; }}
          .card-stack {{ display: grid; gap: 16px; }}
          .kv {{ display: grid; gap: 10px; margin-top: 14px; }}
          .kv div {{ display: flex; justify-content: space-between; gap: 16px; border-bottom: 1px solid #edf1f5; padding-bottom: 10px; }}
          .kv div:last-child {{ border-bottom: 0; padding-bottom: 0; }}
          .kv dt {{ color: var(--muted); }}
          .kv dd {{ margin: 0; font-weight: 700; text-align: right; }}
          .service-list {{ display: grid; gap: 10px; margin-top: 14px; }}
          .service {{ display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #edf1f5; padding-bottom: 10px; }}
          .service:last-child {{ border-bottom: 0; padding-bottom: 0; }}
          .muted {{ color: var(--muted); }}
          .hidden {{ display: none !important; }}
          .placeholder-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
          .placeholder-card {{ background: var(--panel); border: 1px dashed #c6d1dc; border-radius: 16px; padding: 18px; display: grid; gap: 12px; }}
          .detail-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
          .detail-grid.three-up {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
          .detail-card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 18px; display: grid; gap: 12px; }}
          .detail-card h4 {{ margin: 0; font-size: 16px; }}
          .timeline {{ display: grid; gap: 12px; }}
          .timeline-item {{ border-left: 3px solid #d7dee7; padding-left: 12px; display: grid; gap: 4px; }}
          .timeline-item.completed {{ border-left-color: #1f8f5f; }}
          .timeline-item.current {{ border-left-color: #2563eb; background: #f8fbff; }}
          .timeline-item.blocked {{ border-left-color: #c97a1d; background: #fff8f1; }}
          .timeline-item.rejected {{ border-left-color: #c23b32; background: #fff6f5; }}
          .timeline-item strong {{ font-size: 14px; }}
          .artifact-list {{ display: grid; gap: 10px; }}
          .artifact-item {{ border: 1px solid #edf1f5; border-radius: 12px; padding: 12px; background: #fbfcfe; display: grid; gap: 6px; }}
          .artifact-item.selected {{ border-color: #b8c9dd; background: #f4f8fc; }}
          .artifact-item a {{ color: var(--accent); text-decoration: none; }}
          .artifact-item a:hover {{ text-decoration: underline; }}
          .artifact-item .artifact-meta {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
          .artifact-actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
          .tab-row {{ display: flex; gap: 8px; flex-wrap: wrap; }}
          .tab-row button.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
          .artifact-tabs {{ display: flex; gap: 10px; flex-wrap: wrap; }}
          .artifact-tab {{ border: 1px solid var(--border); background: #fff; color: var(--ink); border-radius: 999px; padding: 8px 12px; font-weight: 700; cursor: pointer; }}
          .artifact-tab.active {{ background: var(--accent-soft); color: var(--accent); border-color: #b9cefb; }}
          .inline-form {{ display: grid; gap: 12px; }}
          .inline-form-grid {{ display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(140px, 0.5fr) auto; gap: 12px; align-items: end; }}
          .result-list {{ display: grid; gap: 10px; }}
          .result-item {{ border: 1px solid #edf1f5; border-radius: 12px; padding: 12px; background: #fbfcfe; display: grid; gap: 8px; }}
          .result-item-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }}
          .result-item-head strong {{ font-size: 14px; }}
          .result-meta {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
          .qa-thread {{ max-height: 420px; overflow: auto; padding-right: 4px; }}
          .qa-entry {{ border: 1px solid #edf1f5; border-radius: 12px; padding: 12px; background: #fbfcfe; display: grid; gap: 10px; }}
          .qa-question {{ color: var(--ink); font-weight: 700; }}
          .qa-answer {{ color: var(--ink); line-height: 1.5; }}
          .qa-basis {{ color: var(--muted); font-size: 13px; line-height: 1.4; }}
          .code-block {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; background: #0f172a; color: #e2e8f0; padding: 12px; border-radius: 12px; overflow: auto; }}
          .surface-summary {{ display: grid; gap: 12px; }}
          .surface-summary .summary-line {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; }}
          .surface-summary .summary-line strong {{ font-size: 14px; }}
          .surface-summary .summary-line span {{ color: var(--muted); font-size: 13px; }}
          textarea {{ width: 100%; min-height: 108px; border-radius: 12px; border: 1px solid #c6d1dc; padding: 12px; font: inherit; resize: vertical; }}
          .footer-note {{ color: var(--muted); font-size: 13px; }}
          @media (max-width: 1180px) {{
            .kpis {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
          }}
          @media (max-width: 980px) {{
            .shell {{ grid-template-columns: 1fr; }}
            .sidebar {{ padding-bottom: 0; }}
            .content {{ padding-top: 14px; }}
            .two-col, .placeholder-grid, .detail-grid, .detail-grid.three-up, .inline-form-grid {{ grid-template-columns: 1fr; }}
          }}
          @media (max-width: 720px) {{
            .content {{ padding: 18px; }}
            .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
            .auth-grid {{ grid-template-columns: 1fr; }}
          }}
        </style>
      </head>
      <body>
        <div class="shell">
          <aside class="sidebar">
            <div class="brand">
              <h1>StrategyOS</h1>
              <p>First thin UI slice for the governed review flow. The home surface stays queue-first and binds to the verified MVP endpoints.</p>
            </div>
            <nav class="nav" aria-label="Primary">
              <button class="nav-link active" data-section="home"><strong>Home / Queue</strong><span class="meta">Queue-first reviewer workflow</span></button>
              <button class="nav-link" data-section="runs"><strong>Runs</strong><span class="meta">Lifecycle and latest-run access</span></button>
              <button class="nav-link" data-section="review"><strong>Review Console</strong><span class="meta">Governed decisioning shell</span></button>
              <button class="nav-link" data-section="artifacts"><strong>Artifacts</strong><span class="meta">Thin artifact inspection and deep links</span></button>
              <button class="nav-link" data-section="data"><strong>Data Status</strong><span class="meta">Managed counts, graph, vector</span></button>
              <button class="nav-link" data-section="health"><strong>API / Health</strong><span class="meta">Readiness and integration posture</span></button>
            </nav>
            <div class="sidebar-card">
              <strong>Current role</strong>
              <div id="sidebar-role" class="muted">Unauthenticated</div>
              <small id="sidebar-subject">Provide a bearer token or API key to unlock role-aware actions.</small>
            </div>
            <div class="sidebar-card">
              <strong>MVP grounding</strong>
              <small>Verified local broader-testing state, governed review queue, Neo4j/Qdrant status, and protected runtime endpoints.</small>
            </div>
          </aside>
          <main class="content">
            <section class="topbar">
              <div>
                <h2>Governed Operations Shell</h2>
                <p>Application shell, role-aware navigation, and a queue-first home screen mapped to the present StrategyOS backend surface.</p>
              </div>
              <div class="badges">
                <span class="badge" id="environment-badge">Local broader-testing</span>
                <span class="badge" id="role-badge">Role: unauthenticated</span>
                <span class="badge" id="auth-badge">Auth required</span>
              </div>
            </section>

            <section class="panel auth-panel">
              <div>
                <h3>Session</h3>
                <p>Use the current local identity boundary or API keys. This thin slice does not store credentials server-side; it only forwards the token/key to the existing protected endpoints.</p>
              </div>
              <div class="auth-grid">
                <label>
                  Bearer token or API key
                  <input id="session-token" type="password" placeholder="Paste Bearer token or API key" autocomplete="off" />
                </label>
                <div class="button-row">
                  <button class="button" id="connect-button" type="button">Connect</button>
                  <button class="button secondary" id="clear-button" type="button">Clear</button>
                </div>
              </div>
              <p id="session-help" class="muted">If the local IDP flow is enabled, obtain a bearer token first, then connect the shell.</p>
            </section>

            <section id="status-banner" class="banner warn">
              <strong>Session not connected</strong>
              <span>Home can render the shell publicly, but governed queue, run, data, and health calls require the active identity boundary when auth is enabled.</span>
            </section>

            <section id="home-section" class="section-view">
              <div class="kpis" id="kpi-strip">
                <article class="kpi"><span>Pending reviews</span><strong id="kpi-pending">—</strong></article>
                <article class="kpi"><span>Latest run state</span><strong id="kpi-state">—</strong></article>
                <article class="kpi"><span>Findings</span><strong id="kpi-findings">—</strong></article>
                <article class="kpi"><span>Locked findings</span><strong id="kpi-locked">—</strong></article>
                <article class="kpi"><span>Recoverable SAR</span><strong id="kpi-sar">—</strong></article>
              </div>

              <div class="two-col">
                <section class="panel">
                  <div class="panel-head">
                    <h3>Pending review queue</h3>
                    <p>Queue-first by design: governed work needing attention stays primary, with thin claim/unclaim assignment for reviewer ownership.</p>
                  </div>
                  <div class="button-row" style="margin: 14px 0 10px;">
                    <button class="button secondary" id="refresh-home" type="button">Refresh queue</button>
                    <button class="button hidden" id="start-run" type="button">Start run</button>
                    <button class="button secondary hidden" id="open-latest-run" type="button">Open latest run JSON</button>
                  </div>
                  <div id="start-run-panel" class="placeholder-card hidden">
                    <div class="panel-head">
                      <h4>Start governed run</h4>
                      <p>Operator-only flow over <span class="mono">POST /runs</span> plus source-pack intake for folder selection, upload, validation, normalization, and runnable task-readiness checks.</p>
                    </div>
                    <section class="detail-card" style="margin-bottom:16px;">
                      <div class="panel-head">
                        <h4>Source-pack intake preview</h4>
                        <p>Browser folder upload, optional workspace-bounded folder path staging, content-based classification, normalization into the current run model, and task-readiness display over <span class="mono">POST /source-packs</span>, <span class="mono">POST /source-packs/from-path</span>, and <span class="mono">POST /source-packs/validate</span>. When the current source pack is runnable, <span class="mono">POST /runs</span> can reference its <span class="mono">source_pack_id</span>.</p>
                      </div>
                      <form id="source-pack-upload-form" class="inline-form">
                        <label>
                          Browser folder / files
                          <input id="source-pack-files" type="file" webkitdirectory directory multiple />
                        </label>
                        <div class="button-row">
                          <button class="button secondary" id="source-pack-upload-submit" type="submit">Upload selected folder</button>
                        </div>
                      </form>
                      <form id="source-pack-path-form" class="inline-form" style="margin-top:12px;">
                        <label>
                          Local workspace folder path
                          <input id="source-pack-path" type="text" placeholder="Optional folder path within the workspace boundary" autocomplete="off" />
                        </label>
                        <div class="button-row">
                          <button class="button secondary" id="source-pack-path-submit" type="submit">Stage local folder</button>
                          <button class="button secondary" id="source-pack-validate" type="button">Revalidate current source pack</button>
                        </div>
                      </form>
                      <div class="detail-card" style="margin-top:12px;">
                        <div class="panel-head">
                          <h4>Candidate mappings</h4>
                          <p>Schema-tolerant structured uploads can propose a canonical role and column mapping for operator confirmation before normalization.</p>
                        </div>
                        <div id="source-pack-mappings" class="artifact-list">
                          <div class="artifact-item"><strong>No candidate mappings</strong><span class="muted">Upload or validate a source pack to inspect mapping proposals.</span></div>
                        </div>
                      </div>
                      <div id="source-pack-status" class="surface-summary" style="margin-top:12px;">
                        <div class="summary-line"><strong>Source-pack preview idle</strong><span>Select a browser folder or stage a workspace path to preview the new intake backend.</span></div>
                      </div>
                      <div class="detail-grid" style="margin-top:16px;">
                        <article class="detail-card">
                          <div class="panel-head">
                            <h4>Manifest preview</h4>
                            <p>Stable source ids, relative paths, support visibility, and extraction-state preview.</p>
                          </div>
                          <div id="source-pack-summary" class="surface-summary">
                            <div class="summary-line"><strong>No source pack loaded</strong><span>Manifest counts appear after upload or local staging.</span></div>
                          </div>
                          <div style="overflow:auto; margin-top:12px;">
                            <table>
                              <thead>
                                <tr>
                                  <th>Source ID</th>
                                  <th>Relative path</th>
                                  <th>Hint</th>
                                  <th>Supported</th>
                                  <th>Extraction</th>
                                </tr>
                              </thead>
                              <tbody id="source-pack-manifest-body">
                                <tr><td colspan="5" class="muted">No source-pack manifest yet.</td></tr>
                              </tbody>
                            </table>
                          </div>
                        </article>
                        <article class="detail-card">
                          <div class="panel-head">
                            <h4>Task readiness</h4>
                            <p>Readiness display for the staged source pack, including content-based classification gaps and whether the current run model can execute.</p>
                          </div>
                          <div id="source-pack-readiness" class="artifact-list">
                            <div class="artifact-item"><strong>No readiness payload</strong><span class="muted">Validate a source pack to inspect task-level readiness.</span></div>
                          </div>
                        </article>
                      </div>
                    </section>
                    <form id="start-run-form" class="inline-form">
                      <label>
                        Dataset path
                        <input id="start-run-dataset" type="text" placeholder="Optional dataset path within the workspace boundary" autocomplete="off" />
                      </label>
                      <label>
                        Run directory
                        <input id="start-run-run-dir" type="text" placeholder="Optional run directory within the output boundary" autocomplete="off" />
                      </label>
                      <div class="button-row">
                        <label><input id="start-run-skip-prepare" type="checkbox" /> Skip input preparation</label>
                        <label><input id="start-run-sync-artifacts" type="checkbox" checked /> Sync artifacts when configured</label>
                        <label><input id="start-run-allow-partial-source-pack" type="checkbox" /> Allow partial source-pack run (missing roles skipped, no synthetic fill)</label>
                      </div>
                      <div class="button-row">
                        <button class="button" id="start-run-submit" type="submit">Submit run</button>
                        <button class="button secondary" id="start-run-cancel" type="button">Cancel</button>
                      </div>
                    </form>
                    <div id="start-run-status" class="surface-summary">
                      <div class="summary-line"><strong>Operator-only control</strong><span>Use workspace-bounded dataset and output-bounded run paths. Validation failures stay visible here.</span></div>
                    </div>
                  </div>
                  <div id="queue-empty" class="banner hidden"><strong>No pending governed runs</strong><span>When the queue is empty, operator actions and latest-run context remain available.</span></div>
                  <div style="overflow:auto;">
                    <table>
                      <thead>
                        <tr>
                          <th>Run ID</th>
                          <th>Created</th>
                          <th>Dataset root</th>
                          <th>Checkpoint time</th>
                          <th>Stage</th>
                          <th>Approval</th>
                          <th>Assignment</th>
                          <th>Action</th>
                        </tr>
                      </thead>
                      <tbody id="queue-body">
                        <tr><td colspan="8" class="muted">Connect a session to load governed queue data.</td></tr>
                      </tbody>
                    </table>
                  </div>
                </section>

                <div class="card-stack">
                  <section class="panel">
                    <h3>Latest run snapshot</h3>
                    <p>Secondary context for the freshest governed execution state.</p>
                    <dl class="kv">
                      <div><dt>Run ID</dt><dd id="latest-run-id">—</dd></div>
                      <div><dt>Run directory</dt><dd id="latest-run-dir" class="mono">—</dd></div>
                      <div><dt>Status</dt><dd id="latest-run-status">—</dd></div>
                      <div><dt>Current stage</dt><dd id="latest-run-stage">—</dd></div>
                    </dl>
                  </section>

                  <section class="panel">
                    <h3>Services / health summary</h3>
                    <p>Runtime posture pulled from the current readiness and config surfaces.</p>
                    <div id="services-list" class="service-list">
                      <div class="service"><span>Awaiting health check</span><strong class="muted">—</strong></div>
                    </div>
                  </section>
                </div>
              </div>
            </section>

            <section id="runs-section" class="section-view hidden">
              <section class="panel" style="margin-bottom:16px;">
                <div class="panel-head">
                  <h3>Runs index</h3>
                  <p>Recent governed runs with lifecycle state, review context, and drill-in actions over <span class="mono">GET /reviewer/runs</span>.</p>
                </div>
                <div id="runs-index-empty" class="banner hidden"><strong>No governed runs yet</strong><span>When runs are created, this index becomes the primary drill-in surface for governed history.</span></div>
                <div style="overflow:auto;">
                  <table>
                    <thead>
                      <tr>
                        <th>Run ID</th>
                        <th>Created</th>
                        <th>Status</th>
                        <th>Current stage</th>
                        <th>Review context</th>
                        <th>Evidence</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody id="runs-index-body">
                      <tr><td colspan="7" class="muted">Connect a session to load governed runs.</td></tr>
                    </tbody>
                  </table>
                </div>
              </section>
              <div class="detail-grid">
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Selected run summary</h3>
                    <p>Thin run-detail slice bound to <span class="mono">GET /reviewer/runs/{{run_id}}</span>.</p>
                  </div>
                  <dl class="kv" id="run-detail-kv">
                    <div><dt>Run ID</dt><dd>Choose a governed run.</dd></div>
                  </dl>
                  <div class="button-row">
                    <button class="button secondary" id="select-latest-run" type="button">Select latest run</button>
                    <a class="button secondary" id="selected-run-json" href="/runs/latest" target="_blank" rel="noreferrer">Open run JSON</a>
                  </div>
                </article>
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Lifecycle timeline</h3>
                    <p>Map the governed run through fixed MVP stages so awaiting-review, approval, and completion do not blur together.</p>
                  </div>
                  <div id="run-timeline" class="timeline">
                    <div class="timeline-item"><strong>No run selected</strong><span class="muted">Queue or latest-run selection will hydrate the governed timeline.</span></div>
                  </div>
                </article>
              </div>
              <div class="detail-grid" style="margin-top:16px;">
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Artifact entry points</h3>
                    <p>Expose raw JSON plus discovered artifact paths from run summary and checkpoint state.</p>
                  </div>
                  <div id="run-artifacts" class="artifact-list">
                    <div class="artifact-item"><strong>No artifacts loaded</strong><span class="muted">Select a run to inspect governed outputs.</span></div>
                  </div>
                </article>
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Operational context</h3>
                    <p>Latest managed-data and readiness posture stay visible while reviewing a run.</p>
                  </div>
                  <dl class="kv" id="run-context-kv">
                    <div><dt>Data status</dt><dd>—</dd></div>
                    <div><dt>Health status</dt><dd>—</dd></div>
                    <div><dt>Vector / graph</dt><dd>—</dd></div>
                    <div><dt>Queue depth</dt><dd>—</dd></div>
                  </dl>
                </article>
              </div>
            </section>

            <section id="review-section" class="section-view hidden">
              <div class="detail-grid">
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Review context</h3>
                    <p>First usable review console bound to <span class="mono">GET /reviewer/checkpoints/{{checkpoint_id}}</span>.</p>
                  </div>
                  <dl class="kv" id="review-context-kv">
                    <div><dt>Checkpoint</dt><dd>Choose a queue item or latest run.</dd></div>
                  </dl>
                  <div>
                    <strong>Checkpoint payload snapshot</strong>
                    <pre id="review-state-preview" class="code-block">Awaiting checkpoint context.</pre>
                  </div>
                </article>
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Guarded reviewer/operator actions</h3>
                    <p>Shell actions stay role-aware and still fail closed at the API boundary.</p>
                  </div>
                  <label>
                    Review comment
                    <textarea id="review-comment" placeholder="Optional rationale for approve/reject."></textarea>
                  </label>
                  <div class="button-row">
                    <button class="button secondary hidden" id="claim-run" type="button">Claim review</button>
                    <button class="button secondary hidden" id="unclaim-run" type="button">Unclaim review</button>
                    <button class="button hidden" id="approve-run" type="button">Approve run</button>
                    <button class="button secondary hidden" id="reject-run" type="button">Reject run</button>
                    <button class="button hidden" id="resume-run" type="button">Resume approved run</button>
                  </div>
                  <div id="review-action-hint" class="muted">Reviewer claim/unclaim stays inside the governed queue. Reviewer decisions are available only after the current reviewer claims the run. Operator resume appears only after approval.</div>
                  <div class="button-row">
                    <a class="button secondary" id="selected-checkpoint-json" href="#" target="_blank" rel="noreferrer">Open checkpoint JSON</a>
                    <a class="button secondary" id="selected-review-run-json" href="#" target="_blank" rel="noreferrer">Open run JSON</a>
                  </div>
                </article>
              </div>
              <div class="detail-grid" style="margin-top:16px;">
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Artifact handoff</h3>
                    <p>Use these entry points to inspect generated outputs before or after a reviewer decision.</p>
                  </div>
                  <div id="review-artifacts" class="artifact-list">
                    <div class="artifact-item"><strong>No review artifacts loaded</strong><span class="muted">Run and checkpoint selection will populate output entry points here.</span></div>
                  </div>
                </article>
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Review posture</h3>
                    <p>Keep the active run, approval state, and queue pressure visible during decisioning.</p>
                  </div>
                  <dl class="kv" id="review-posture-kv">
                    <div><dt>Selected run</dt><dd>—</dd></div>
                    <div><dt>Approval state</dt><dd>—</dd></div>
                    <div><dt>Current stage</dt><dd>—</dd></div>
                    <div><dt>Pending reviews</dt><dd>—</dd></div>
                  </dl>
                </article>
              </div>
            </section>

            <section id="artifacts-section" class="section-view hidden">
              <div class="detail-grid">
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Artifact inspector</h3>
                    <p>Usable artifact inspection bound to current run/checkpoint JSON plus existing artifact preview endpoints.</p>
                  </div>
                  <dl class="kv" id="artifact-context-kv">
                    <div><dt>Selected run</dt><dd>Choose a run or review item.</dd></div>
                  </dl>
                </article>
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Artifact metadata</h3>
                    <p>Keep scope, preview type, and truncation state visible while reviewing outputs.</p>
                  </div>
                  <dl class="kv" id="artifact-meta-kv">
                    <div><dt>Artifact</dt><dd>Select a tab below.</dd></div>
                  </dl>
                </article>
              </div>
              <article class="detail-card" style="margin-top:16px;">
                <div class="panel-head">
                  <h3>Artifact tabs</h3>
                  <p>Run detail and review console deep-link here so operators and reviewers inspect the same artifact surfaces.</p>
                </div>
                <div id="artifact-tabs" class="artifact-tabs">
                  <span class="muted">Select a run to load artifact tabs.</span>
                </div>
              </article>
              <article class="detail-card" style="margin-top:16px;">
                <div class="panel-head">
                  <h3>Artifact viewer</h3>
                  <p>Prefer existing backend JSON and artifact outputs; previews stay text-first by design.</p>
                </div>
                <pre id="artifact-viewer" class="code-block">Select an artifact tab or use an Inspect artifact deep link from Runs or Review Console.</pre>
              </article>
            </section>

            <section id="data-section" class="section-view hidden">
              <div class="detail-grid">
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Managed data shell</h3>
                    <p>Counts, persisted batch context, and latest-run linkage stay tied to <span class="mono">GET /data/status</span>.</p>
                  </div>
                  <div id="data-summary" class="surface-summary">
                    <div class="summary-line"><strong>Awaiting data status</strong><span>Connect a session to inspect managed data posture.</span></div>
                  </div>
                  <div class="button-row">
                    <a class="button secondary" href="/data/status" target="_blank" rel="noreferrer">Open data status JSON</a>
                    <a class="button secondary" href="/runs/latest" target="_blank" rel="noreferrer">Open latest run JSON</a>
                  </div>
                </article>
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Data counts</h3>
                    <p>Keep the persisted document, finding, artifact, and knowledge-graph counts visible without leaving the shell.</p>
                  </div>
                  <dl class="kv" id="data-counts-kv">
                    <div><dt>Evidence documents</dt><dd>—</dd></div>
                    <div><dt>Findings</dt><dd>—</dd></div>
                    <div><dt>Artifacts</dt><dd>—</dd></div>
                    <div><dt>KG nodes / edges</dt><dd>—</dd></div>
                  </dl>
                </article>
              </div>
              <div class="detail-grid" style="margin-top:16px;">
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Graph and vector surfaces</h3>
                    <p>Use the current Neo4j and Qdrant status payloads for point-in-time operational verification.</p>
                  </div>
                  <dl class="kv" id="data-systems-kv">
                    <div><dt>Neo4j</dt><dd>—</dd></div>
                    <div><dt>Qdrant</dt><dd>—</dd></div>
                    <div><dt>Graph sample</dt><dd>—</dd></div>
                    <div><dt>Vector sample</dt><dd>—</dd></div>
                  </dl>
                </article>
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Data payload snapshot</h3>
                    <p>Raw JSON stays visible so operators can verify the thin view against the existing backend surface.</p>
                  </div>
                  <div class="button-row">
                    <a class="button secondary" href="/data/vector-search?query=duplicate%20payment%20invoice" target="_blank" rel="noreferrer">Open vector search</a>
                  </div>
                  <pre id="data-payload-preview" class="code-block">Awaiting data status payload.</pre>
                </article>
              </div>
              <div class="detail-grid" style="margin-top:16px;">
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Vector search utility</h3>
                    <p>Thin UI wrapper around <span class="mono">GET /data/vector-search</span> so reviewers and operators can submit a query and inspect ranked hits.</p>
                  </div>
                  <form id="vector-search-form" class="inline-form">
                    <div class="inline-form-grid">
                      <label>
                        Query
                        <input id="vector-search-query" type="text" placeholder="duplicate payment invoice" autocomplete="off" />
                      </label>
                      <label>
                        Limit
                        <input id="vector-search-limit" type="number" min="1" max="10" value="5" />
                      </label>
                      <div class="button-row">
                        <button class="button" id="vector-search-submit" type="submit">Search</button>
                      </div>
                    </div>
                    <div id="vector-search-context" class="muted">Uses the selected run when available, otherwise the latest run surface.</div>
                  </form>
                  <div id="vector-search-summary" class="surface-summary">
                    <div class="summary-line"><strong>Awaiting query</strong><span>Submit a search to inspect ranked vector hits.</span></div>
                  </div>
                </article>
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Ranked hits</h3>
                    <p>Keep the hit list compact, with raw payload JSON beside it for backend traceability.</p>
                  </div>
                  <div id="vector-search-results" class="result-list">
                    <div class="result-item"><strong>No vector search yet</strong><span class="muted">Results will render here after a query runs.</span></div>
                  </div>
                  <pre id="vector-search-payload-preview" class="code-block">Awaiting vector search payload.</pre>
                </article>
              </div>
              <div class="detail-grid" style="margin-top:16px;">
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Data Q&A</h3>
                    <p><span class="mono">POST /qa</span></p>
                  </div>
                  <form id="qa-form" class="inline-form">
                    <label>
                      Question
                      <input id="qa-input" type="text" placeholder="What is the total amount of invoices?" autocomplete="off" />
                    </label>
                    <div class="button-row">
                      <button class="button" id="qa-submit" type="submit">Ask</button>
                    </div>
                    <div id="qa-context" class="muted">Awaiting run context.</div>
                  </form>
                  <div id="qa-summary" class="surface-summary">
                    <div class="summary-line"><strong>Awaiting question</strong><span>Answers will render with basis and sources.</span></div>
                  </div>
                </article>
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Q&A thread</h3>
                    <p>Deterministic answers from the selected run.</p>
                  </div>
                  <div id="qa-thread" class="result-list qa-thread">
                    <div class="result-item"><strong>No questions yet</strong><span class="muted">Ask a finance question to begin.</span></div>
                  </div>
                  <pre id="qa-payload-preview" class="code-block">Awaiting Q&A payload.</pre>
                </article>
              </div>
            </section>

            <section id="health-section" class="section-view hidden">
              <div class="detail-grid">
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>API / health shell</h3>
                    <p>Live, ready, and config surfaces remain separate, but this console keeps their status aligned in one operational view.</p>
                  </div>
                  <div id="health-summary" class="surface-summary">
                    <div class="summary-line"><strong>Awaiting health status</strong><span>Connect a session to inspect API health posture.</span></div>
                  </div>
                  <div class="button-row">
                    <a class="button secondary" href="/health/live" target="_blank" rel="noreferrer">Live</a>
                    <a class="button secondary" href="/health/ready" target="_blank" rel="noreferrer">Ready</a>
                    <a class="button secondary" href="/health/config" target="_blank" rel="noreferrer">Config</a>
                    <a class="button secondary" href="/docs" target="_blank" rel="noreferrer">API docs</a>
                  </div>
                </article>
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Dependency checks</h3>
                    <p>Readiness check results stay compact, but still expose the specific dependency status for operators and reviewers.</p>
                  </div>
                  <dl class="kv" id="health-checks-kv">
                    <div><dt>Postgres</dt><dd>—</dd></div>
                    <div><dt>Redis</dt><dd>—</dd></div>
                    <div><dt>Neo4j / Qdrant</dt><dd>—</dd></div>
                    <div><dt>Workspace / governance</dt><dd>—</dd></div>
                  </dl>
                </article>
              </div>
              <div class="detail-grid" style="margin-top:16px;">
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Config and access posture</h3>
                    <p>Keep auth, review boundary, and backend configuration toggles visible next to readiness.</p>
                  </div>
                  <dl class="kv" id="health-config-kv">
                    <div><dt>API auth</dt><dd>—</dd></div>
                    <div><dt>Human review</dt><dd>—</dd></div>
                    <div><dt>Public live health</dt><dd>—</dd></div>
                    <div><dt>Object store</dt><dd>—</dd></div>
                  </dl>
                </article>
                <article class="detail-card">
                  <div class="panel-head">
                    <h3>Health payload snapshot</h3>
                    <p>Render the current live, ready, and config payloads so the shell stays traceable to backend truth.</p>
                  </div>
                  <pre id="health-payload-preview" class="code-block">Awaiting live, ready, and config payloads.</pre>
                </article>
              </div>
            </section>

            <p class="footer-note">Thin-slice scope: queue-first shell, selected run detail, first usable review console, artifact entry points, and role-aware guarded actions. Deeper artifact viewers and richer data/health consoles remain intentionally lightweight.</p>
          </main>
        </div>

        <script id="strategyos-bootstrap" type="application/json">{bootstrap_json}</script>
        <script>
          const bootstrap = JSON.parse(document.getElementById('strategyos-bootstrap').textContent);
          const state = {{
            token: window.localStorage.getItem('strategyos.ui.token') || '',
            session: null,
            queue: [],
            runs: [],
            latestRun: null,
            selectedRunId: null,
            selectedRun: null,
            selectedCheckpointId: null,
            selectedCheckpoint: null,
            dataStatus: null,
            liveStatus: null,
            readyStatus: null,
            configStatus: null,
            activeSection: 'home',
            selectedArtifact: null,
            artifactPreview: null,
            vectorSearch: {{ status: 'idle', query: '', results: [], payload: null, error: '' }},
            qaThread: [],
            qaStatus: {{ status: 'idle', payload: null, error: '' }},
            startRunPanelOpen: false,
            startRunSubmitting: false,
            sourcePack: null,
            sourcePackSubmitting: false,
          }};

          const els = {{
            environmentBadge: document.getElementById('environment-badge'),
            roleBadge: document.getElementById('role-badge'),
            authBadge: document.getElementById('auth-badge'),
            sidebarRole: document.getElementById('sidebar-role'),
            sidebarSubject: document.getElementById('sidebar-subject'),
            statusBanner: document.getElementById('status-banner'),
            sessionToken: document.getElementById('session-token'),
            sessionHelp: document.getElementById('session-help'),
            queueBody: document.getElementById('queue-body'),
            queueEmpty: document.getElementById('queue-empty'),
            runsIndexBody: document.getElementById('runs-index-body'),
            runsIndexEmpty: document.getElementById('runs-index-empty'),
            latestRunId: document.getElementById('latest-run-id'),
            latestRunDir: document.getElementById('latest-run-dir'),
            latestRunStatus: document.getElementById('latest-run-status'),
            latestRunStage: document.getElementById('latest-run-stage'),
            servicesList: document.getElementById('services-list'),
            kpiPending: document.getElementById('kpi-pending'),
            kpiState: document.getElementById('kpi-state'),
            kpiFindings: document.getElementById('kpi-findings'),
            kpiLocked: document.getElementById('kpi-locked'),
            kpiSar: document.getElementById('kpi-sar'),
            startRun: document.getElementById('start-run'),
            startRunPanel: document.getElementById('start-run-panel'),
            sourcePackUploadForm: document.getElementById('source-pack-upload-form'),
            sourcePackFiles: document.getElementById('source-pack-files'),
            sourcePackUploadSubmit: document.getElementById('source-pack-upload-submit'),
            sourcePackPathForm: document.getElementById('source-pack-path-form'),
            sourcePackPath: document.getElementById('source-pack-path'),
            sourcePackPathSubmit: document.getElementById('source-pack-path-submit'),
            sourcePackValidate: document.getElementById('source-pack-validate'),
            sourcePackMappings: document.getElementById('source-pack-mappings'),
            sourcePackStatus: document.getElementById('source-pack-status'),
            sourcePackSummary: document.getElementById('source-pack-summary'),
            sourcePackManifestBody: document.getElementById('source-pack-manifest-body'),
            sourcePackReadiness: document.getElementById('source-pack-readiness'),
            startRunForm: document.getElementById('start-run-form'),
            startRunDataset: document.getElementById('start-run-dataset'),
            startRunRunDir: document.getElementById('start-run-run-dir'),
            startRunSkipPrepare: document.getElementById('start-run-skip-prepare'),
            startRunSyncArtifacts: document.getElementById('start-run-sync-artifacts'),
            startRunAllowPartialSourcePack: document.getElementById('start-run-allow-partial-source-pack'),
            startRunSubmit: document.getElementById('start-run-submit'),
            startRunCancel: document.getElementById('start-run-cancel'),
            startRunStatus: document.getElementById('start-run-status'),
            openLatestRun: document.getElementById('open-latest-run'),
            runDetailKv: document.getElementById('run-detail-kv'),
            runTimeline: document.getElementById('run-timeline'),
            runArtifacts: document.getElementById('run-artifacts'),
            runContextKv: document.getElementById('run-context-kv'),
            reviewContextKv: document.getElementById('review-context-kv'),
            reviewStatePreview: document.getElementById('review-state-preview'),
            reviewComment: document.getElementById('review-comment'),
            claimRun: document.getElementById('claim-run'),
            unclaimRun: document.getElementById('unclaim-run'),
            approveRun: document.getElementById('approve-run'),
            rejectRun: document.getElementById('reject-run'),
            resumeRun: document.getElementById('resume-run'),
            reviewActionHint: document.getElementById('review-action-hint'),
            selectedRunJson: document.getElementById('selected-run-json'),
            selectedReviewRunJson: document.getElementById('selected-review-run-json'),
            selectedCheckpointJson: document.getElementById('selected-checkpoint-json'),
            reviewArtifacts: document.getElementById('review-artifacts'),
            reviewPostureKv: document.getElementById('review-posture-kv'),
            selectLatestRun: document.getElementById('select-latest-run'),
            artifactContextKv: document.getElementById('artifact-context-kv'),
            artifactMetaKv: document.getElementById('artifact-meta-kv'),
            artifactTabs: document.getElementById('artifact-tabs'),
            artifactViewer: document.getElementById('artifact-viewer'),
            dataSummary: document.getElementById('data-summary'),
            dataCountsKv: document.getElementById('data-counts-kv'),
            dataSystemsKv: document.getElementById('data-systems-kv'),
            dataPayloadPreview: document.getElementById('data-payload-preview'),
            vectorSearchForm: document.getElementById('vector-search-form'),
            vectorSearchQuery: document.getElementById('vector-search-query'),
            vectorSearchLimit: document.getElementById('vector-search-limit'),
            vectorSearchSubmit: document.getElementById('vector-search-submit'),
            vectorSearchContext: document.getElementById('vector-search-context'),
            vectorSearchSummary: document.getElementById('vector-search-summary'),
            vectorSearchResults: document.getElementById('vector-search-results'),
            vectorSearchPayloadPreview: document.getElementById('vector-search-payload-preview'),
            qaForm: document.getElementById('qa-form'),
            qaInput: document.getElementById('qa-input'),
            qaSubmit: document.getElementById('qa-submit'),
            qaContext: document.getElementById('qa-context'),
            qaSummary: document.getElementById('qa-summary'),
            qaThread: document.getElementById('qa-thread'),
            qaPayloadPreview: document.getElementById('qa-payload-preview'),
            healthSummary: document.getElementById('health-summary'),
            healthChecksKv: document.getElementById('health-checks-kv'),
            healthConfigKv: document.getElementById('health-config-kv'),
            healthPayloadPreview: document.getElementById('health-payload-preview'),
          }};

          const navButtons = Array.from(document.querySelectorAll('.nav-link'));
          const sectionViews = Array.from(document.querySelectorAll('.section-view'));

          function authHeaders() {{
            if (!state.token) return {{}};
            return bootstrap.idp_enabled || state.token.startsWith('eyJ') || state.token.includes('.')
              ? {{ Authorization: `Bearer ${{state.token}}` }}
              : {{ 'X-API-Key': state.token }};
          }}

          async function requestJson(url, options = {{}}) {{
            const response = await fetch(url, {{
              ...options,
              headers: {{
                'Content-Type': 'application/json',
                ...authHeaders(),
                ...(options.headers || {{}}),
              }},
            }});
            const text = await response.text();
            const payload = text ? JSON.parse(text) : {{}};
            if (!response.ok) {{
              const error = new Error(payload.detail || payload.reason || `Request failed: ${{response.status}}`);
              error.status = response.status;
              error.payload = payload;
              throw error;
            }}
            return payload;
          }}

          async function requestMultipart(url, formData) {{
            const response = await fetch(url, {{
              method: 'POST',
              headers: authHeaders(),
              body: formData,
            }});
            const text = await response.text();
            const payload = text ? JSON.parse(text) : {{}};
            if (!response.ok) {{
              const error = new Error(payload.detail || payload.reason || `Request failed: ${{response.status}}`);
              error.status = response.status;
              error.payload = payload;
              throw error;
            }}
            return payload;
          }}

          function formatDate(value) {{
            if (!value) return '—';
            const date = new Date(value);
            return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
          }}

          function escapeHtml(value) {{
            return String(value ?? '—')
              .replace(/&/g, '&amp;')
              .replace(/</g, '&lt;')
              .replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;')
              .replace(/'/g, '&#39;');
          }}

          function formatSar(value) {{
            const number = Number(value || 0);
            return Number.isFinite(number) ? number.toLocaleString(undefined, {{ minimumFractionDigits: 0, maximumFractionDigits: 2 }}) : '—';
          }}

          function countLabel(value) {{
            const number = Number(value);
            return Number.isFinite(number) ? number.toLocaleString() : '—';
          }}

          function yesNoPill(value, labels = ['Enabled', 'Disabled']) {{
            return statusPill(value ? labels[0] : labels[1]);
          }}

          function compactJson(value) {{
            return JSON.stringify(value ?? {{}}, null, 2);
          }}

          function statusTone(value) {{
            const normalized = String(value || '').toLowerCase();
            if (['ok', 'ready', 'approved', 'completed', 'synced'].includes(normalized)) return 'ok';
            if (['failed', 'rejected', 'missing'].includes(normalized)) return 'danger';
            return 'warn';
          }}

          function statusPill(value) {{
            const label = value ? String(value) : 'unknown';
            return `<span class="pill ${{statusTone(label)}}">${{label}}</span>`;
          }}

          function setBanner(kind, title, message) {{
            els.statusBanner.className = `banner ${{kind}}`;
            els.statusBanner.innerHTML = `<strong>${{title}}</strong><span>${{message}}</span>`;
          }}

          function renderNavigation() {{
            navButtons.forEach((button) => {{
              button.classList.toggle('active', button.dataset.section === state.activeSection);
            }});
            sectionViews.forEach((section) => {{
              section.classList.toggle('hidden', section.id !== `${{state.activeSection}}-section`);
            }});
          }}

          function artifactDeepLinkHref(item) {{
            const params = new URLSearchParams();
            params.set('section', 'artifacts');
            if (state.selectedRunId) params.set('run', state.selectedRunId);
            if (state.selectedCheckpointId) params.set('checkpoint', state.selectedCheckpointId);
            params.set('artifact', item.key);
            params.set('artifact_scope', item.scope);
            if (item.scopeId) params.set('artifact_scope_id', item.scopeId);
            return `#${{params.toString()}}`;
          }}

          function syncHashRoute() {{
            const params = new URLSearchParams();
            params.set('section', state.activeSection || 'home');
            if (state.selectedRunId) params.set('run', state.selectedRunId);
            if (state.selectedCheckpointId) params.set('checkpoint', state.selectedCheckpointId);
            if (state.activeSection === 'artifacts' && state.selectedArtifact) {{
              params.set('artifact', state.selectedArtifact.key);
              params.set('artifact_scope', state.selectedArtifact.scope);
              if (state.selectedArtifact.scopeId) params.set('artifact_scope_id', state.selectedArtifact.scopeId);
            }}
            window.history.replaceState(null, '', `${{window.location.pathname}}${{window.location.search}}#${{params.toString()}}`);
          }}

          function parseHashRoute() {{
            const raw = window.location.hash.replace(/^#/, '');
            const params = new URLSearchParams(raw);
            return {{
              section: params.get('section') || null,
              runId: params.get('run') || null,
              checkpointId: params.get('checkpoint') || null,
              artifact: params.get('artifact') || null,
              artifactScope: params.get('artifact_scope') || 'run',
              artifactScopeId: params.get('artifact_scope_id') || '',
            }};
          }}

          function renderSession() {{
            const session = state.session || {{ role: 'unauthenticated', subject: 'no active session', authenticated: false, auth_disabled: !bootstrap.api_auth_enabled }};
            const role = session.auth_disabled ? 'auth-disabled' : (session.role || 'unauthenticated');
            els.environmentBadge.textContent = bootstrap.environment;
            els.roleBadge.textContent = `Role: ${{role}}`;
            els.authBadge.textContent = bootstrap.api_auth_enabled ? (session.authenticated ? 'Session connected' : 'Auth required') : 'Auth disabled';
            els.sidebarRole.textContent = session.authenticated ? role : (session.auth_disabled ? 'Auth disabled' : 'Unauthenticated');
            els.sidebarSubject.textContent = session.subject || 'No active subject';
            els.sessionHelp.textContent = bootstrap.api_auth_enabled
              ? 'Reviewer gets queue-first decisioning; operator gets run control and health emphasis.'
              : 'Auth is disabled in this environment, so the shell can call protected surfaces directly.';

            const operator = role === 'operator';
            if (!operator) state.startRunPanelOpen = false;
            els.startRun.classList.toggle('hidden', !operator);
            els.openLatestRun.classList.toggle('hidden', !state.latestRun);
            renderStartRunPanel();
            renderReviewActions();
          }}

          function renderStartRunPanel() {{
            const operator = (state.session?.role || '') === 'operator';
            const visible = operator && state.startRunPanelOpen;
            els.startRunPanel.classList.toggle('hidden', !visible);
            const disabled = state.startRunSubmitting;
            els.startRunDataset.disabled = disabled;
            els.startRunRunDir.disabled = disabled;
            els.startRunSkipPrepare.disabled = disabled;
            els.startRunSyncArtifacts.disabled = disabled;
            els.startRunAllowPartialSourcePack.disabled = disabled;
            // Block submission while any low-confidence role mapping is unconfirmed.
            const unconfirmed = (state.sourcePack?.task_readiness?.unconfirmed_roles) || [];
            const blockedByMapping = state.sourcePack && unconfirmed.length > 0;
            els.startRunSubmit.disabled = disabled || blockedByMapping;
            els.startRunCancel.disabled = disabled;
            renderSourcePackPanel();
            if (state.startRunSubmitting) {{
              setStartRunStatus('warn', 'Submitting run request', 'Posting the selected dataset, run directory, and runtime options to /runs.');
            }} else if (blockedByMapping) {{
              setStartRunStatus('warn', 'Confirm mappings first', `Confirm low-confidence role mappings before running: ${{unconfirmed.join(', ')}}.`);
            }}
          }}

          function setStartRunStatus(kind, title, message) {{
            els.startRunStatus.innerHTML = `<div class="summary-line"><strong>${{escapeHtml(title)}}</strong><span>${{escapeHtml(message)}}</span></div>`;
          }}

          function setSourcePackStatus(kind, title, message) {{
            els.sourcePackStatus.innerHTML = `<div class="summary-line"><strong>${{escapeHtml(title)}}</strong><span>${{escapeHtml(message)}}</span></div>`;
          }}

          function renderSourcePackPanel() {{
            const operator = (state.session?.role || '') === 'operator';
            const disabled = state.sourcePackSubmitting || !operator;
            els.sourcePackFiles.disabled = disabled;
            els.sourcePackUploadSubmit.disabled = disabled;
            els.sourcePackPath.disabled = disabled;
            els.sourcePackPathSubmit.disabled = disabled;
            els.sourcePackValidate.disabled = disabled || !state.sourcePack?.source_pack_id;

            const payload = state.sourcePack;
            if (!payload) {{
              els.sourcePackSummary.innerHTML = '<div class="summary-line"><strong>No source pack loaded</strong><span>Manifest counts appear after upload or local staging.</span></div>';
              els.sourcePackManifestBody.innerHTML = '<tr><td colspan="5" class="muted">No source-pack manifest yet.</td></tr>';
              els.sourcePackMappings.innerHTML = '<div class="artifact-item"><strong>No candidate mappings</strong><span class="muted">Upload or validate a source pack to inspect mapping proposals.</span></div>';
              els.sourcePackReadiness.innerHTML = '<div class="artifact-item"><strong>No readiness payload</strong><span class="muted">Validate a source pack to inspect task-level readiness.</span></div>';
              return;
            }}

            const summary = payload.manifest_summary || {{}};
            els.sourcePackSummary.innerHTML = `
              <div class="summary-line"><strong>Source pack</strong><span>${{escapeHtml(payload.source_pack_id || '—')}} · ${{escapeHtml(payload.source_kind || 'unknown')}}</span></div>
              <div class="summary-line"><strong>Files</strong><span>${{countLabel(summary.file_count)}} total · ${{countLabel(summary.supported_count)}} supported · ${{countLabel(summary.unsupported_count)}} unsupported · ${{countLabel(summary.pending_extraction_count)}} pending extraction</span></div>
              <div class="summary-line"><strong>Validation</strong><span>${{escapeHtml((payload.validation || {{}}).status || 'unknown')}} · ${{escapeHtml(((payload.validation || {{}}).issues || []).join(' | ') || 'No validation issues reported.')}}</span></div>`;

            const manifest = Array.isArray(payload.manifest) ? payload.manifest : [];
            els.sourcePackManifestBody.innerHTML = manifest.length
              ? manifest.slice(0, 12).map((item) => `
                <tr>
                  <td><code>${{escapeHtml(item.source_id || '—')}}</code></td>
                  <td class="mono">${{escapeHtml(item.relative_path || '—')}}</td>
                  <td>${{statusPill(item.file_type_hint || 'unknown')}}</td>
                  <td>${{statusPill(item.supported ? 'supported' : 'unsupported')}}</td>
                  <td>${{statusPill(item.extraction_status || 'unknown')}}</td>
                </tr>`).join('')
              : '<tr><td colspan="5" class="muted">No source-pack manifest yet.</td></tr>';

            const candidates = manifest.filter((item) => (item.classification || {{}}).status === 'candidate');
            els.sourcePackMappings.innerHTML = candidates.length
              ? candidates.map((item) => {{
                  const classification = item.classification || {{}};
                  const proposal = classification.column_mapping_proposal || {{}};
                  const role = classification.role || proposal.role || '';
                  const proposed = proposal.column_mapping || {{}};
                  const sourceColumns = Array.isArray(proposal.source_columns) ? proposal.source_columns : [];
                  const canonicalColumns = Object.keys(proposed).concat(
                    (proposal.missing_required || []).filter((c) => !(c in proposed))
                  );
                  const rel = item.relative_path || '';
                  const rowId = 'map-' + (item.source_id || Math.random().toString(36).slice(2));
                  const rows = canonicalColumns.map((canonical) => {{
                    const chosen = proposed[canonical] || '';
                    const options = ['<option value="">— unmapped —</option>']
                      .concat(sourceColumns.map((src) => `<option value="${{escapeHtml(src)}}" ${{src === chosen ? 'selected' : ''}}>${{escapeHtml(src)}}</option>`))
                      .join('');
                    return `<div class="summary-line"><span class="mono">${{escapeHtml(canonical)}}</span>` +
                      `<select data-canonical="${{escapeHtml(canonical)}}" class="mapping-select">${{options}}</select></div>`;
                  }}).join('');
                  return `
                    <div class="artifact-item" id="${{rowId}}" data-rel="${{escapeHtml(encodeURIComponent(rel))}}" data-role="${{escapeHtml(role)}}">
                      <strong>${{escapeHtml(rel || 'source')}}</strong>
                      <span>${{statusPill(role || 'candidate')}} ${{statusPill('needs confirmation')}}</span>
                      <div class="muted" style="margin-top:8px;font-size:12px;">${{escapeHtml(classification.basis || 'Candidate mapping proposed — review each canonical column.')}}</div>
                      <div style="margin-top:8px;">${{rows || '<span class="muted">No column proposal.</span>'}}</div>
                      <div class="button-row" style="margin-top:8px;">
                        <button class="button secondary" type="button" onclick="confirmSourcePackMapping('${{rowId}}')">Confirm mapping</button>
                      </div>
                    </div>`;
                }}).join('')
              : '<div class="artifact-item"><strong>No candidate mappings</strong><span class="muted">Validated structured mappings appear here when confirmation is required.</span></div>';

            const readiness = payload.task_readiness || {{}};
            const unconfirmed = Array.isArray(readiness.unconfirmed_roles) ? readiness.unconfirmed_roles : [];
            if (unconfirmed.length) {{
              els.sourcePackMappings.innerHTML =
                `<div class="artifact-item"><strong>Confirmation required before run</strong>` +
                `<span class="muted">These roles were auto-mapped with low confidence: ${{escapeHtml(unconfirmed.join(', '))}}. Confirm each mapping below to enable the run.</span></div>` +
                els.sourcePackMappings.innerHTML;
            }}
            const tasks = Array.isArray(readiness.tasks) ? readiness.tasks : [];
            els.sourcePackReadiness.innerHTML = tasks.length
              ? tasks.map((item) => `
                <div class="artifact-item">
                  <strong>${{escapeHtml(item.label || item.task_key || 'Task')}}</strong>
                  <span>${{statusPill(item.status || 'unknown')}}</span>
                  <div class="muted" style="margin-top:8px;font-size:12px;">${{escapeHtml((item.reasons || []).join(' | ') || 'No readiness details.')}}</div>
                  <div class="muted mono" style="margin-top:8px;font-size:12px;">Missing: ${{escapeHtml((item.missing || []).join(', ') || '—')}}</div>
                </div>`).join('')
              : '<div class="artifact-item"><strong>No readiness payload</strong><span class="muted">Validate a source pack to inspect task-level readiness.</span></div>';
          }}

          function toggleStartRunPanel(forceOpen = null) {{
            const operator = (state.session?.role || '') === 'operator';
            if (!operator) return;
            state.startRunPanelOpen = forceOpen === null ? !state.startRunPanelOpen : !!forceOpen;
            if (state.startRunPanelOpen && !state.startRunSubmitting) {{
              setStartRunStatus('ok', 'Operator-only control', 'Use workspace-bounded dataset and output-bounded run paths. Validation failures stay visible here.');
            }}
            renderStartRunPanel();
          }}

          function renderKpis() {{
            const latest = state.latestRun || {{}};
            const dataStatus = state.dataStatus || {{}};
            const counts = dataStatus.counts || {{}};
            els.kpiPending.textContent = String(state.queue.length || 0);
            els.kpiState.textContent = latest.status || latest.lifecycle_status || '—';
            els.kpiFindings.textContent = String(latest.findings ?? counts.findings ?? 0);
            els.kpiLocked.textContent = String(latest.locked_findings ?? 0);
            els.kpiSar.textContent = formatSar(latest.total_recoverable_sar ?? 0);
          }}

          function renderLatestRun() {{
            const latest = state.latestRun || {{}};
            els.latestRunId.textContent = latest.run_id || '—';
            els.latestRunDir.textContent = latest.run_dir || '—';
            els.latestRunStatus.innerHTML = statusPill(latest.status || latest.lifecycle_status || 'missing');
            els.latestRunStage.innerHTML = statusPill(latest.current_stage || 'unknown');
          }}

          function renderQueue() {{
            if (!state.session?.authenticated && bootstrap.api_auth_enabled) {{
              els.queueBody.innerHTML = '<tr><td colspan="8" class="muted">Connect a session to load governed queue data.</td></tr>';
              els.queueEmpty.classList.add('hidden');
              return;
            }}
            if (!state.queue.length) {{
              els.queueBody.innerHTML = '<tr><td colspan="8" class="muted">No pending governed runs.</td></tr>';
              els.queueEmpty.classList.remove('hidden');
              return;
            }}
            els.queueEmpty.classList.add('hidden');
            const role = state.session?.role || 'reviewer';
            els.queueBody.innerHTML = state.queue.map((item) => {{
              const summary = item.checkpoint_summary_json || {{}};
              const assignment = item.review_assignment || {{}};
              const claimedBy = assignment.claimed_by || '';
              const claimedByMe = !!claimedBy && claimedBy === state.session?.subject;
              const assignmentLabel = claimedBy
                ? (claimedByMe ? 'Claimed by you' : `Claimed by ${{claimedBy}}`)
                : 'Unclaimed';
              const actionLabel = role === 'reviewer' ? 'Open review console' : 'Open run detail';
              return `
                <tr>
                  <td><code>${{item.run_id || '—'}}</code></td>
                  <td>${{formatDate(item.created_at)}}</td>
                  <td class="mono">${{item.dataset_root || item.run_dir || '—'}}</td>
                  <td>${{formatDate(item.checkpoint_created_at)}}</td>
                  <td>${{statusPill(item.current_stage || item.checkpoint_stage || item.status || 'unknown')}}</td>
                  <td>${{statusPill(item.decision || 'pending')}}</td>
                  <td>
                    <div>${{statusPill(claimedBy ? (claimedByMe ? 'claimed-by-you' : 'claimed') : 'unclaimed')}}</div>
                    <div class="muted mono" style="margin-top:8px;font-size:12px;">${{escapeHtml(claimedBy || 'Available queue item')}}</div>
                  </td>
                  <td>
                    <div class="button-row">
                      <button class="button secondary" type="button" data-open-run="${{escapeHtml(item.run_id || '')}}" data-open-checkpoint="${{escapeHtml(item.checkpoint_id || '')}}" data-target-section="${{role === 'reviewer' ? 'review' : 'runs'}}">${{actionLabel}}</button>
                      ${{role === 'reviewer' && !claimedBy ? `<button class="button secondary" type="button" data-claim-run="${{escapeHtml(item.run_id || '')}}">Claim</button>` : ''}}
                      ${{role === 'reviewer' && claimedByMe ? `<button class="button secondary" type="button" data-unclaim-run="${{escapeHtml(item.run_id || '')}}">Unclaim</button>` : ''}}
                      <a class="button secondary" href="/reviewer/runs/${{encodeURIComponent(item.run_id)}}" target="_blank" rel="noreferrer">Run JSON</a>
                    </div>
                    <div class="muted" style="margin-top:8px;font-size:12px;">
                      Findings: ${{summary.findings ?? '—'}} · Recoverable SAR: ${{formatSar(summary.total_recoverable_sar)}} · ${{escapeHtml(assignmentLabel)}}
                    </div>
                  </td>
                </tr>`;
            }}).join('');
          }}

          function runReviewContext(item) {{
            const assignment = item.review_assignment || {{}};
            const claimedBy = assignment.claimed_by;
            const approvalStatus = String(item.approval_status || 'pending');
            if (!item.requires_human_review) return 'Review not required';
            if (approvalStatus === 'approved') return `Approved${{item.approval_reviewer ? ` by ${{item.approval_reviewer}}` : ''}}`;
            if (approvalStatus === 'rejected') return `Rejected${{item.approval_reviewer ? ` by ${{item.approval_reviewer}}` : ''}}`;
            if (claimedBy) return `Awaiting review · claimed by ${{claimedBy}}`;
            if (String(item.status || '').toLowerCase() === 'awaiting_review') return 'Awaiting review · unclaimed';
            return 'Review pending';
          }}

          function renderRunsIndex() {{
            if (!state.session?.authenticated && bootstrap.api_auth_enabled) {{
              els.runsIndexBody.innerHTML = '<tr><td colspan="7" class="muted">Connect a session to load governed runs.</td></tr>';
              els.runsIndexEmpty.classList.add('hidden');
              return;
            }}
            if (!state.runs.length) {{
              els.runsIndexBody.innerHTML = '<tr><td colspan="7" class="muted">No governed runs available.</td></tr>';
              els.runsIndexEmpty.classList.remove('hidden');
              return;
            }}
            els.runsIndexEmpty.classList.add('hidden');
            els.runsIndexBody.innerHTML = state.runs.map((item) => {{
              const reviewContext = runReviewContext(item);
              const evidenceSummary = `${{countLabel(item.finding_count)}} findings · ${{countLabel(item.locked_finding_count)}} locked · ${{formatSar(item.total_recoverable_sar)}} SAR`;
              return `
                <tr>
                  <td><code>${{escapeHtml(item.run_id || '—')}}</code></td>
                  <td>${{escapeHtml(formatDate(item.created_at))}}</td>
                  <td>${{statusPill(item.status || 'unknown')}}</td>
                  <td>${{statusPill(item.current_stage || item.checkpoint_stage || 'unknown')}}</td>
                  <td>
                    <div>${{statusPill(item.approval_status || (item.requires_human_review ? 'pending' : 'not_required'))}}</div>
                    <div class="muted" style="margin-top:8px;font-size:12px;">${{escapeHtml(reviewContext)}}</div>
                  </td>
                  <td>
                    <div class="muted">${{escapeHtml(evidenceSummary)}}</div>
                    <div class="muted mono" style="margin-top:8px;font-size:12px;">${{escapeHtml(item.dataset_root || item.run_dir || '—')}}</div>
                  </td>
                  <td>
                    <div class="button-row">
                      <button class="button secondary" type="button" data-open-run="${{escapeHtml(item.run_id || '')}}" data-open-checkpoint="${{escapeHtml(item.checkpoint_id || '')}}" data-target-section="runs">Open run detail</button>
                      <button class="button secondary" type="button" data-open-run="${{escapeHtml(item.run_id || '')}}" data-open-checkpoint="${{escapeHtml(item.checkpoint_id || '')}}" data-target-section="review">Open review context</button>
                      <a class="button secondary" href="/reviewer/runs/${{encodeURIComponent(item.run_id || '')}}" target="_blank" rel="noreferrer">Run JSON</a>
                    </div>
                  </td>
                </tr>`;
            }}).join('');
          }}

          function reviewAssignment() {{
            return state.selectedRun?.review_assignment || {{ claimed: false, claimed_by: null, claimed_at: null }};
          }}

          function claimedByCurrentReviewer() {{
            const claimedBy = reviewAssignment().claimed_by;
            return !!claimedBy && claimedBy === state.session?.subject;
          }}

          function claimedByAnotherReviewer() {{
            const claimedBy = reviewAssignment().claimed_by;
            return !!claimedBy && claimedBy !== state.session?.subject;
          }}

          function renderServices() {{
            const ready = state.readyStatus || {{ checks: {{}} }};
            const dataStatus = state.dataStatus || {{}};
            const services = [
              ['Postgres', ready.checks?.postgres?.status || 'unknown'],
              ['Redis', ready.checks?.redis?.status || 'unknown'],
              ['Neo4j', dataStatus.neo4j?.status || ready.checks?.neo4j?.status || 'unknown'],
              ['Qdrant', dataStatus.qdrant?.status || ready.checks?.qdrant?.status || 'unknown'],
              ['Object store', ready.checks?.object_store?.status || 'unknown'],
            ];
            els.servicesList.innerHTML = services.map(([name, value]) => `
              <div class="service">
                <span>${{name}}</span>
                <strong>${{statusPill(value)}}</strong>
              </div>`).join('');
          }}

          function renderDataStatus() {{
            if (bootstrap.api_auth_enabled && !state.session?.authenticated) {{
              els.dataSummary.innerHTML = '<div class="summary-line"><strong>Session required</strong><span>Connect with reviewer/operator access to load /data/status.</span></div>';
              els.dataCountsKv.innerHTML = '<div><dt>Evidence documents</dt><dd>—</dd></div><div><dt>Findings</dt><dd>—</dd></div><div><dt>Artifacts</dt><dd>—</dd></div><div><dt>KG nodes / edges</dt><dd>—</dd></div>';
              els.dataSystemsKv.innerHTML = '<div><dt>Neo4j</dt><dd>—</dd></div><div><dt>Qdrant</dt><dd>—</dd></div><div><dt>Graph sample</dt><dd>—</dd></div><div><dt>Vector sample</dt><dd>—</dd></div>';
              els.dataPayloadPreview.textContent = 'Connect a session to inspect the managed data payload.';
              return;
            }}
            const payload = state.dataStatus;
            if (!payload) {{
              els.dataSummary.innerHTML = '<div class="summary-line"><strong>Awaiting data status</strong><span>Managed data posture has not been loaded yet.</span></div>';
              els.dataCountsKv.innerHTML = '<div><dt>Evidence documents</dt><dd>—</dd></div><div><dt>Findings</dt><dd>—</dd></div><div><dt>Artifacts</dt><dd>—</dd></div><div><dt>KG nodes / edges</dt><dd>—</dd></div>';
              els.dataSystemsKv.innerHTML = '<div><dt>Neo4j</dt><dd>—</dd></div><div><dt>Qdrant</dt><dd>—</dd></div><div><dt>Graph sample</dt><dd>—</dd></div><div><dt>Vector sample</dt><dd>—</dd></div>';
              els.dataPayloadPreview.textContent = 'Awaiting data status payload.';
              return;
            }}
            const counts = payload.counts || {{}};
            const latest = state.latestRun || {{}};
            const neo4j = payload.neo4j || {{}};
            const qdrant = payload.qdrant || {{}};
            const graphSample = neo4j.sample_relation
              ? `${{neo4j.sample_relation.source_node_key || 'finding'}} → ${{neo4j.sample_relation.target_node_key || 'vendor'}}`
              : (neo4j.reason || 'No sample relation');
            const vectorSample = qdrant.sample_record
              ? `${{qdrant.sample_record.finding_id || 'finding'}} · ${{qdrant.sample_record.vendor_name || qdrant.sample_record.title || 'sample payload'}}`
              : (qdrant.reason || 'No sample vector payload');
            els.dataSummary.innerHTML = `
              <div class="summary-line"><strong>${{statusPill(payload.status || 'unknown')}}</strong><span>Managed data status for run ${{escapeHtml(payload.run_id || latest.run_id || '—')}}</span></div>
              <div class="summary-line"><strong>Batch</strong><span class="mono">${{escapeHtml(payload.batch_id || '—')}}</span></div>
              <div class="summary-line"><strong>Tenant / source</strong><span>${{escapeHtml(`${{payload.tenant || '—'}} / ${{payload.source_system || '—'}}`)}}</span></div>
              <div class="summary-line"><strong>Dataset root</strong><span class="mono">${{escapeHtml(payload.dataset_root || latest.dataset_root || latest.run_dir || '—')}}</span></div>
            `;
            els.dataCountsKv.innerHTML = `
              <div><dt>Evidence documents</dt><dd>${{escapeHtml(countLabel(counts.evidence_documents))}}</dd></div>
              <div><dt>Findings</dt><dd>${{escapeHtml(countLabel(counts.findings))}}</dd></div>
              <div><dt>Artifacts</dt><dd>${{escapeHtml(countLabel(counts.artifacts))}}</dd></div>
              <div><dt>KG nodes / edges</dt><dd>${{escapeHtml(`${{countLabel(counts.kg_nodes)}} / ${{countLabel(counts.kg_edges)}}`)}}</dd></div>`;
            els.dataSystemsKv.innerHTML = `
              <div><dt>Neo4j</dt><dd>${{statusPill(neo4j.status || 'unknown')}}</dd></div>
              <div><dt>Qdrant</dt><dd>${{statusPill(qdrant.status || 'unknown')}}</dd></div>
              <div><dt>Graph sample</dt><dd class="mono">${{escapeHtml(graphSample)}}</dd></div>
              <div><dt>Vector sample</dt><dd class="mono">${{escapeHtml(vectorSample)}}</dd></div>`;
            els.dataPayloadPreview.textContent = compactJson(payload);
          }}

          function activeVectorRunId() {{
            return state.selectedRunId || state.latestRun?.run_id || state.dataStatus?.run_id || null;
          }}

          function renderVectorSearch() {{
            const runId = activeVectorRunId();
            const vectorState = state.vectorSearch || {{ status: 'idle', query: '', results: [], payload: null, error: '' }};
            els.vectorSearchContext.textContent = runId
              ? `Search scope will use run ${{runId}} unless the backend falls back to latest-run context.`
              : 'No run context is loaded yet; the backend will fall back to latest-run context if available.';

            if (bootstrap.api_auth_enabled && !state.session?.authenticated) {{
              els.vectorSearchSummary.innerHTML = '<div class="summary-line"><strong>Session required</strong><span>Connect with reviewer/operator access to call /data/vector-search.</span></div>';
              els.vectorSearchResults.innerHTML = '<div class="result-item"><strong>Session required</strong><span class="muted">Authenticate to submit vector queries.</span></div>';
              els.vectorSearchPayloadPreview.textContent = 'Connect a session to inspect vector search payloads.';
              els.vectorSearchSubmit.disabled = true;
              return;
            }}

            els.vectorSearchSubmit.disabled = vectorState.status === 'loading';
            if (vectorState.status === 'loading') {{
              els.vectorSearchSummary.innerHTML = `<div class="summary-line"><strong>Searching</strong><span>${{escapeHtml(vectorState.query || 'Running vector lookup')}}…</span></div>`;
              els.vectorSearchResults.innerHTML = '<div class="result-item"><strong>Loading ranked hits</strong><span class="muted">Waiting for /data/vector-search to respond.</span></div>';
              els.vectorSearchPayloadPreview.textContent = 'Loading vector search payload…';
              return;
            }}

            if (vectorState.status === 'failed') {{
              els.vectorSearchSummary.innerHTML = `<div class="summary-line"><strong>${{statusPill('failed')}}</strong><span>${{escapeHtml(vectorState.error || 'Vector search failed.')}}</span></div>`;
              els.vectorSearchResults.innerHTML = '<div class="result-item"><strong>Search failed</strong><span class="muted">Inspect the payload pane and retry with a different query or run context.</span></div>';
              els.vectorSearchPayloadPreview.textContent = compactJson(vectorState.payload || {{ status: 'failed', reason: vectorState.error || 'Vector search failed.' }});
              return;
            }}

            if (vectorState.status !== 'ready') {{
              els.vectorSearchSummary.innerHTML = '<div class="summary-line"><strong>Awaiting query</strong><span>Submit a search to inspect ranked vector hits.</span></div>';
              els.vectorSearchResults.innerHTML = '<div class="result-item"><strong>No vector search yet</strong><span class="muted">Results will render here after a query runs.</span></div>';
              els.vectorSearchPayloadPreview.textContent = 'Awaiting vector search payload.';
              return;
            }}

            const results = vectorState.results || [];
            els.vectorSearchSummary.innerHTML = `
              <div class="summary-line"><strong>${{statusPill(vectorState.payload?.status || 'ready')}}</strong><span>${{escapeHtml(vectorState.query || '—')}}</span></div>
              <div class="summary-line"><strong>Run</strong><span class="mono">${{escapeHtml(vectorState.payload?.run_id || runId || '—')}}</span></div>
              <div class="summary-line"><strong>Hits</strong><span>${{escapeHtml(String(results.length))}}</span></div>
            `;
            if (!results.length) {{
              els.vectorSearchResults.innerHTML = '<div class="result-item"><strong>No hits returned</strong><span class="muted">Try a broader query or confirm the current run has indexed findings.</span></div>';
            }} else {{
              els.vectorSearchResults.innerHTML = results.map((item, index) => `
                <div class="result-item">
                  <div class="result-item-head">
                    <strong>${{escapeHtml(item.title || item.finding_id || `Hit ${{index + 1}}`)}}</strong>
                    <span class="pill ok">${{escapeHtml(Number(item.score || 0).toFixed(3))}}</span>
                  </div>
                  <div class="result-meta">
                    <span class="pill">${{escapeHtml(item.finding_id || 'unknown finding')}}</span>
                    <span class="pill">${{escapeHtml(item.pattern_type || 'unknown pattern')}}</span>
                    <span class="pill">${{escapeHtml(item.vendor_name || 'unknown vendor')}}</span>
                  </div>
                  <span class="mono">${{escapeHtml(item.source || 'No source path reported')}}</span>
                </div>
              `).join('');
            }}
            els.vectorSearchPayloadPreview.textContent = compactJson(vectorState.payload);
          }}

          function activeQaRunId() {{
            return state.selectedRunId || state.latestRun?.run_id || state.dataStatus?.run_id || null;
          }}

          function qaRunAvailable() {{
            return Boolean(state.selectedRun || state.latestRun || state.dataStatus?.run_id || state.dataStatus?.dataset_root);
          }}

          function renderQa() {{
            const runId = activeQaRunId();
            const qaStatus = state.qaStatus || {{ status: 'idle', payload: null, error: '' }};
            els.qaContext.textContent = runId
              ? `Answer scope: run ${{runId}}.`
              : (qaRunAvailable() ? 'Answer scope: latest completed run.' : 'No completed run context is loaded yet.');

            if (bootstrap.api_auth_enabled && !state.session?.authenticated) {{
              els.qaSummary.innerHTML = '<div class="summary-line"><strong>Session required</strong><span>Connect with reviewer/operator access to call /qa.</span></div>';
              els.qaThread.innerHTML = '<div class="result-item"><strong>Session required</strong><span class="muted">Authenticate to ask questions.</span></div>';
              els.qaPayloadPreview.textContent = 'Connect a session to inspect Q&A payloads.';
              els.qaSubmit.disabled = true;
              return;
            }}

            const disabled = qaStatus.status === 'loading' || !qaRunAvailable();
            els.qaSubmit.disabled = disabled;

            if (!qaRunAvailable()) {{
              els.qaSummary.innerHTML = '<div class="summary-line"><strong>No run loaded</strong><span>Start or select a completed run before asking.</span></div>';
              els.qaThread.innerHTML = '<div class="result-item"><strong>No run context</strong><span class="muted">Q&A needs a completed run dataset.</span></div>';
              els.qaPayloadPreview.textContent = 'No Q&A payload.';
              return;
            }}

            if (qaStatus.status === 'loading') {{
              els.qaSummary.innerHTML = '<div class="summary-line"><strong>Answering</strong><span>Computing from the run data.</span></div>';
            }} else if (qaStatus.status === 'failed') {{
              els.qaSummary.innerHTML = `<div class="summary-line"><strong>${{statusPill('failed')}}</strong><span>${{escapeHtml(qaStatus.error || 'Q&A failed.')}}</span></div>`;
            }} else if (state.qaThread.length) {{
              const latest = state.qaThread[state.qaThread.length - 1]?.payload || {{}};
              els.qaSummary.innerHTML = `
                <div class="summary-line"><strong>${{statusPill(latest.matched === false ? 'unmatched' : 'answered')}}</strong><span>${{escapeHtml(latest.intent || latest.question || 'latest answer')}}</span></div>
                <div class="summary-line"><strong>Run</strong><span class="mono">${{escapeHtml(latest.run_id || runId || 'latest')}}</span></div>
              `;
            }} else {{
              els.qaSummary.innerHTML = '<div class="summary-line"><strong>Awaiting question</strong><span>Answers will render with basis and sources.</span></div>';
            }}

            const entries = state.qaThread || [];
            if (!entries.length) {{
              els.qaThread.innerHTML = '<div class="result-item"><strong>No questions yet</strong><span class="muted">Ask a finance question to begin.</span></div>';
            }} else {{
              els.qaThread.innerHTML = entries.map((entry) => {{
                const payload = entry.payload || {{}};
                const suggestions = Array.isArray(payload.suggestions) && payload.suggestions.length
                  ? `<div class="result-meta">${{payload.suggestions.map((item) => `<span class="pill">${{escapeHtml(item)}}</span>`).join('')}}</div>`
                  : '';
                const citations = Array.isArray(payload.citations) && payload.citations.length
                  ? `<div class="result-meta">${{payload.citations.map((item) => `<span class="pill">${{escapeHtml(item.source_path || item.source || 'source')}}${{item.locator ? ` · ${{escapeHtml(item.locator)}}` : ''}}</span>`).join('')}}</div>`
                  : '';
                return `
                  <div class="qa-entry">
                    <div class="qa-question">${{escapeHtml(entry.question || payload.question || 'Question')}}</div>
                    <div class="qa-answer">${{escapeHtml(payload.answer || entry.error || 'No answer returned.')}}</div>
                    ${{payload.basis ? `<div class="qa-basis">Basis: ${{escapeHtml(payload.basis)}}</div>` : ''}}
                    ${{suggestions}}
                    ${{citations}}
                  </div>
                `;
              }}).join('');
              els.qaThread.scrollTop = els.qaThread.scrollHeight;
            }}
            els.qaPayloadPreview.textContent = compactJson(qaStatus.payload || entries[entries.length - 1]?.payload || {{ status: qaStatus.status || 'idle' }});
          }}

          function renderHealthConsole() {{
            if (bootstrap.api_auth_enabled && !state.session?.authenticated) {{
              els.healthSummary.innerHTML = '<div class="summary-line"><strong>Session required</strong><span>Connect with reviewer/operator access to load readiness and config surfaces.</span></div>';
              els.healthChecksKv.innerHTML = '<div><dt>Postgres</dt><dd>—</dd></div><div><dt>Redis</dt><dd>—</dd></div><div><dt>Neo4j / Qdrant</dt><dd>—</dd></div><div><dt>Workspace / governance</dt><dd>—</dd></div>';
              els.healthConfigKv.innerHTML = '<div><dt>API auth</dt><dd>—</dd></div><div><dt>Human review</dt><dd>—</dd></div><div><dt>Public live health</dt><dd>—</dd></div><div><dt>Object store</dt><dd>—</dd></div>';
              els.healthPayloadPreview.textContent = 'Connect a session to inspect the live, ready, and config payloads.';
              return;
            }}
            const live = state.liveStatus;
            const ready = state.readyStatus;
            const config = state.configStatus;
            if (!live && !ready && !config) {{
              els.healthSummary.innerHTML = '<div class="summary-line"><strong>Awaiting health status</strong><span>Live, ready, and config payloads have not been loaded yet.</span></div>';
              els.healthChecksKv.innerHTML = '<div><dt>Postgres</dt><dd>—</dd></div><div><dt>Redis</dt><dd>—</dd></div><div><dt>Neo4j / Qdrant</dt><dd>—</dd></div><div><dt>Workspace / governance</dt><dd>—</dd></div>';
              els.healthConfigKv.innerHTML = '<div><dt>API auth</dt><dd>—</dd></div><div><dt>Human review</dt><dd>—</dd></div><div><dt>Public live health</dt><dd>—</dd></div><div><dt>Object store</dt><dd>—</dd></div>';
              els.healthPayloadPreview.textContent = 'Awaiting live, ready, and config payloads.';
              return;
            }}
            const checks = ready?.checks || {{}};
            const configObjectStore = config?.object_store || {{}};
            els.healthSummary.innerHTML = `
              <div class="summary-line"><strong>Live</strong><span>${{statusPill(live?.status || 'unknown')}}</span></div>
              <div class="summary-line"><strong>Ready</strong><span>${{statusPill(ready?.status || 'unknown')}}</span></div>
              <div class="summary-line"><strong>Config</strong><span>${{statusPill(config?.status || 'unknown')}}</span></div>
              <div class="summary-line"><strong>Workspace</strong><span class="mono">${{escapeHtml(live?.workspace_root || ready?.workspace_root || bootstrap.workspace_root)}}</span></div>
            `;
            els.healthChecksKv.innerHTML = `
              <div><dt>Postgres</dt><dd>${{statusPill(checks.postgres?.status || 'unknown')}}</dd></div>
              <div><dt>Redis</dt><dd>${{statusPill(checks.redis?.status || 'unknown')}}</dd></div>
              <div><dt>Neo4j / Qdrant</dt><dd>${{escapeHtml(`${{checks.neo4j?.status || 'unknown'}} / ${{checks.qdrant?.status || 'unknown'}}`)}}</dd></div>
              <div><dt>Workspace / governance</dt><dd>${{escapeHtml(`${{checks.workspace?.status || 'unknown'}} / ${{checks.governance?.status || 'unknown'}}`)}}</dd></div>`;
            els.healthConfigKv.innerHTML = `
              <div><dt>API auth</dt><dd>${{yesNoPill(config?.api_auth_enabled ?? bootstrap.api_auth_enabled)}}</dd></div>
              <div><dt>Human review</dt><dd>${{yesNoPill(config?.require_human_review ?? bootstrap.require_human_review, ['Required', 'Optional'])}}</dd></div>
              <div><dt>Public live health</dt><dd>${{yesNoPill(live?.public_health_enabled ?? bootstrap.public_health_enabled, ['Enabled', 'Protected'])}}</dd></div>
              <div><dt>Object store</dt><dd>${{statusPill(configObjectStore.status || 'unknown')}}</dd></div>`;
            els.healthPayloadPreview.textContent = compactJson({{ live, ready, config }});
          }}

          function reviewableRun() {{
            const run = state.selectedRun || {{}};
            const status = String(run.status || '').toLowerCase();
            const approvalStatus = String(run.approval?.approval_status || '').toLowerCase();
            return status === 'awaiting_review' && !['approved', 'rejected'].includes(approvalStatus);
          }}

          function resumableRun() {{
            const run = state.selectedRun || {{}};
            return String(run.approval?.approval_status || '').toLowerCase() === 'approved';
          }}

          function artifactEntries() {{
            const runArtifacts = state.selectedRun?.summary_json?.artifacts || {{}};
            const checkpointArtifacts = state.selectedCheckpoint?.state_json?.artifact_paths || {{}};
            const merged = new Map();
            Object.entries(runArtifacts).forEach(([key, value]) => merged.set(String(key), {{ value: String(value), scope: 'run' }}));
            Object.entries(checkpointArtifacts).forEach(([key, value]) => merged.set(String(key), {{ value: String(value), scope: 'checkpoint' }}));
            return Array.from(merged.entries()).map(([key, item]) => [key, item]);
          }}

          function artifactItems(options = {{ includeJsonLinks: false }}) {{
            const items = artifactEntries().map(([key, item]) => {{
              const scopeId = item.scope === 'checkpoint' ? state.selectedCheckpointId : state.selectedRunId;
              return {{
                key,
                value: item.value,
                scope: item.scope,
                scopeId,
                previewPath: item.scope === 'checkpoint'
                  ? `/reviewer/checkpoints/${{encodeURIComponent(scopeId || '')}}/artifacts/${{encodeURIComponent(key)}}`
                  : `/reviewer/runs/${{encodeURIComponent(scopeId || '')}}/artifacts/${{encodeURIComponent(key)}}`,
                href: `file://${{encodeURI(item.value)}}`,
                openLabel: 'Open file path',
              }};
            }});
            if (options.includeJsonLinks && state.selectedRunId) {{
              items.push({{
                key: 'run_json',
                value: `/reviewer/runs/${{encodeURIComponent(state.selectedRunId)}}`,
                scope: 'run_json',
                scopeId: state.selectedRunId,
                previewPath: `/reviewer/runs/${{encodeURIComponent(state.selectedRunId)}}`,
                href: `/reviewer/runs/${{encodeURIComponent(state.selectedRunId)}}`,
                openLabel: 'Open endpoint',
              }});
            }}
            if (options.includeJsonLinks && state.selectedCheckpointId) {{
              items.push({{
                key: 'checkpoint_json',
                value: `/reviewer/checkpoints/${{encodeURIComponent(state.selectedCheckpointId)}}`,
                scope: 'checkpoint_json',
                scopeId: state.selectedCheckpointId,
                previewPath: `/reviewer/checkpoints/${{encodeURIComponent(state.selectedCheckpointId)}}`,
                href: `/reviewer/checkpoints/${{encodeURIComponent(state.selectedCheckpointId)}}`,
                openLabel: 'Open endpoint',
              }});
            }}
            return items;
          }}

          function artifactMatches(left, right) {{
            return !!left && !!right
              && left.key === right.key
              && left.scope === right.scope
              && left.scopeId === right.scopeId;
          }}

          function syncArtifactSelection() {{
            const items = artifactItems({{ includeJsonLinks: true }});
            if (!state.selectedArtifact) return;
            const next = items.find((item) => artifactMatches(item, state.selectedArtifact));
            if (next) {{
              state.selectedArtifact = next;
              return;
            }}
            state.selectedArtifact = null;
            state.artifactPreview = null;
          }}

          function renderArtifactList(container, options = {{ showJsonLinks: false }}) {{
            const items = artifactItems({{ includeJsonLinks: options.showJsonLinks }});
            if (!items.length) {{
              container.innerHTML = '<div class="artifact-item"><strong>No artifacts loaded</strong><span class="muted">This thin slice exposes entry points once run/checkpoint context is available.</span></div>';
              return;
            }}
            container.innerHTML = items.map((item) => {{
              const selected = artifactMatches(item, state.selectedArtifact);
              return `
                <div class="artifact-item${{selected ? ' selected' : ''}}">
                  <strong>${{escapeHtml(item.key)}}</strong>
                  <span class="mono">${{escapeHtml(item.value)}}</span>
                  <div class="button-row">
                    <button class="button secondary" type="button" data-open-artifact="${{escapeHtml(item.key)}}" data-artifact-scope="${{escapeHtml(item.scope)}}" data-artifact-scope-id="${{escapeHtml(item.scopeId || '')}}">Inspect artifact</button>
                    <a class="button secondary" href="${{escapeHtml(artifactDeepLinkHref(item))}}">Deep link</a>
                    <a class="button secondary" href="${{escapeHtml(item.previewPath)}}" target="_blank" rel="noreferrer">Artifact JSON</a>
                  </div>
                </div>`;
            }}).join('');
          }}

          function renderArtifactInspector() {{
            const items = artifactItems({{ includeJsonLinks: true }});
            els.artifactContextKv.innerHTML = state.selectedRun
              ? `
                <div><dt>Selected run</dt><dd class="mono">${{escapeHtml(state.selectedRun.run_id || '—')}}</dd></div>
                <div><dt>Checkpoint</dt><dd class="mono">${{escapeHtml(state.selectedCheckpoint?.checkpoint_id || state.selectedRun.latest_checkpoint?.checkpoint_id || '—')}}</dd></div>
                <div><dt>Run status</dt><dd>${{statusPill(state.selectedRun.status || 'unknown')}}</dd></div>
                <div><dt>Artifact count</dt><dd>${{escapeHtml(String(items.length || 0))}}</dd></div>`
              : '<div><dt>Selected run</dt><dd>Choose a run or review item.</dd></div>';
            if (!items.length) {{
              els.artifactTabs.innerHTML = '<span class="muted">Select a run to load artifact tabs.</span>';
              els.artifactMetaKv.innerHTML = '<div><dt>Artifact</dt><dd>Select a tab below.</dd></div>';
              els.artifactViewer.textContent = 'Select an artifact tab or use an Inspect artifact deep link from Runs or Review Console.';
              return;
            }}
            els.artifactTabs.innerHTML = items.map((item) => `
              <button class="artifact-tab ${{artifactMatches(item, state.selectedArtifact) ? 'active' : ''}}" type="button" data-open-artifact="${{escapeHtml(item.key)}}" data-artifact-scope="${{escapeHtml(item.scope)}}" data-artifact-scope-id="${{escapeHtml(item.scopeId || '')}}">${{escapeHtml(item.key)}}</button>
            `).join('');
            if (!state.artifactPreview || !state.selectedArtifact) {{
              els.artifactMetaKv.innerHTML = '<div><dt>Artifact</dt><dd>Select a tab below.</dd></div>';
              els.artifactViewer.textContent = 'Select an artifact tab or use an Inspect artifact deep link from Runs or Review Console.';
              return;
            }}
            const preview = state.artifactPreview;
            els.artifactMetaKv.innerHTML = `
              <div><dt>Artifact</dt><dd>${{escapeHtml(preview.artifact_key || preview.key || '—')}}</dd></div>
              <div><dt>Scope</dt><dd>${{escapeHtml(preview.scope || '—')}}</dd></div>
              <div><dt>Preview kind</dt><dd>${{escapeHtml(preview.preview_kind || 'json')}}</dd></div>
              <div><dt>Source</dt><dd class="mono">${{escapeHtml(preview.path || preview.value || '—')}}</dd></div>
              <div><dt>Truncated</dt><dd>${{escapeHtml(preview.truncated ? 'yes' : 'no')}}</dd></div>`;
            const content = preview.preview_json
              ? JSON.stringify(preview.preview_json, null, 2)
              : (preview.preview_text || 'Artifact content is empty.');
            els.artifactViewer.textContent = content;
          }}

          async function openArtifactInspector(key, scope, scopeId) {{
            const item = artifactItems({{ includeJsonLinks: true }}).find((entry) => entry.key === key && entry.scope === scope && String(entry.scopeId || '') === String(scopeId || ''));
            if (!item) return;
            state.activeSection = 'artifacts';
            state.selectedArtifact = item;
            state.artifactPreview = {{ artifact_key: item.key, scope: item.scope, path: item.value, preview_kind: 'loading', preview_text: 'Loading artifact preview…', truncated: false, preview_json: null }};
            renderNavigation();
            renderArtifactInspector();
            syncHashRoute();
            try {{
              const preview = item.scope === 'run_json' || item.scope === 'checkpoint_json'
                ? await requestJson(item.previewPath).then((payload) => ({{
                    artifact_key: item.key,
                    scope: item.scope,
                    path: item.previewPath,
                    preview_kind: 'json',
                    preview_text: '',
                    preview_json: payload,
                    truncated: false,
                  }}))
                : await requestJson(item.previewPath);
              state.selectedArtifact = item;
              state.artifactPreview = preview;
              renderArtifactInspector();
              syncHashRoute();
            }} catch (error) {{
              state.selectedArtifact = item;
              state.artifactPreview = {{
                artifact_key: item.key,
                scope: item.scope,
                path: item.value,
                preview_kind: 'error',
                preview_text: error?.message || 'Artifact preview could not be loaded.',
                preview_json: null,
                truncated: false,
              }};
              renderArtifactInspector();
              syncHashRoute();
              setBanner('danger', 'Artifact preview failed', error?.message || 'Artifact preview could not be loaded.');
            }}
          }}

          function renderRunDetail() {{
            const run = state.selectedRun;
            const latestApproval = run?.approval?.latest_approval || {{}};
            if (!run) {{
              els.runDetailKv.innerHTML = '<div><dt>Run ID</dt><dd>Choose a governed run.</dd></div>';
              els.runTimeline.innerHTML = '<div class="timeline-item"><strong>No run selected</strong><span class="muted">Queue or latest-run selection will hydrate the governed timeline.</span></div>';
              els.runContextKv.innerHTML = '<div><dt>Data status</dt><dd>—</dd></div><div><dt>Health status</dt><dd>—</dd></div><div><dt>Vector / graph</dt><dd>—</dd></div><div><dt>Queue depth</dt><dd>—</dd></div>';
              els.selectedRunJson.href = '/runs/latest';
              renderArtifactList(els.runArtifacts);
              renderArtifactInspector();
              return;
            }}
            const summary = run.summary_json || {{}};
            els.runDetailKv.innerHTML = `
              <div><dt>Run ID</dt><dd class="mono">${{escapeHtml(run.run_id)}}</dd></div>
              <div><dt>Created</dt><dd>${{escapeHtml(formatDate(run.created_at))}}</dd></div>
              <div><dt>Dataset root</dt><dd class="mono">${{escapeHtml(run.dataset_root || summary.dataset || '—')}}</dd></div>
              <div><dt>Run directory</dt><dd class="mono">${{escapeHtml(run.run_dir || summary.run_dir || '—')}}</dd></div>
              <div><dt>Status</dt><dd>${{statusPill(run.status || 'unknown')}}</dd></div>
              <div><dt>Current stage</dt><dd>${{statusPill(run.current_stage || 'unknown')}}</dd></div>
               <div><dt>Approval</dt><dd>${{statusPill(run.approval?.approval_status || 'pending')}}</dd></div>
               <div><dt>Review owner</dt><dd class="mono">${{escapeHtml(run.review_assignment?.claimed_by || 'Unclaimed')}}</dd></div>
               <div><dt>Findings / locked</dt><dd>${{escapeHtml(`${{summary.findings ?? run.finding_count ?? 0}} / ${{summary.locked_findings ?? run.locked_finding_count ?? 0}}`)}}</dd></div>
               <div><dt>Recoverable SAR</dt><dd>${{escapeHtml(formatSar(summary.total_recoverable_sar ?? run.total_recoverable_sar ?? 0))}}</dd></div>
               <div><dt>Approved by</dt><dd class="mono">${{escapeHtml(run.approved_by || run.approval?.approved_by || latestApproval.reviewer || '—')}}</dd></div>`;
            const timeline = (run.lifecycle_timeline || []).map((item) => `
              <div class="timeline-item ${{escapeHtml(item.state || 'pending')}}">
                <strong>${{escapeHtml(item.label || item.stage || 'Stage')}}</strong>
                <span>${{statusPill(item.state || 'pending')}}</span>
                <span class="muted">${{escapeHtml(item.detail || '—')}}</span>
              </div>`);
            if (run.latest_checkpoint?.checkpoint_id) {{
              timeline.push(`<div class="timeline-item current"><strong>Latest checkpoint</strong><span>${{escapeHtml(formatDate(run.latest_checkpoint.created_at))}}</span><span class="muted">${{escapeHtml(run.latest_checkpoint.stage || 'unknown')}} · ${{escapeHtml(run.latest_checkpoint.status || 'unknown')}} · ${{escapeHtml(run.latest_checkpoint.checkpoint_id)}}</span></div>`);
            }}
            if (latestApproval?.decision) {{
              timeline.push(`<div class="timeline-item ${{escapeHtml(latestApproval.decision === 'rejected' ? 'rejected' : 'completed')}}"><strong>Review decision</strong><span>${{escapeHtml(formatDate(latestApproval.created_at))}}</span><span class="muted">${{escapeHtml(latestApproval.decision || 'pending')}} by ${{escapeHtml(latestApproval.reviewer || latestApproval.reviewer_subject || 'unknown')}}</span></div>`);
            }}
            els.runTimeline.innerHTML = timeline.join('');
            els.runContextKv.innerHTML = `
              <div><dt>Data status</dt><dd>${{statusPill(state.dataStatus?.status || 'unknown')}}</dd></div>
              <div><dt>Health status</dt><dd>${{statusPill(state.readyStatus?.status || 'unknown')}}</dd></div>
              <div><dt>Vector / graph</dt><dd>${{escapeHtml(`${{state.dataStatus?.qdrant?.status || 'unknown'}} / ${{state.dataStatus?.neo4j?.status || 'unknown'}}`)}}</dd></div>
              <div><dt>Queue depth</dt><dd>${{escapeHtml(String(state.queue.length || 0))}}</dd></div>`;
            els.selectedRunJson.href = `/reviewer/runs/${{encodeURIComponent(run.run_id)}}`;
            renderArtifactList(els.runArtifacts, {{ showJsonLinks: true }});
            renderArtifactInspector();
          }}

          function renderReviewActions() {{
            const role = state.session?.role || 'anonymous';
            const canClaim = role === 'reviewer' && reviewableRun() && state.selectedRunId && !reviewAssignment().claimed_by;
            const canUnclaim = role === 'reviewer' && reviewableRun() && state.selectedRunId && claimedByCurrentReviewer();
            const canDecide = role === 'reviewer' && reviewableRun() && state.selectedRunId && claimedByCurrentReviewer();
            els.claimRun.classList.toggle('hidden', !canClaim);
            els.unclaimRun.classList.toggle('hidden', !canUnclaim);
            els.approveRun.classList.toggle('hidden', !canDecide);
            els.rejectRun.classList.toggle('hidden', !canDecide);
            els.resumeRun.classList.toggle('hidden', !(role === 'operator' && resumableRun() && state.selectedRunId));
            if (!state.selectedRunId) {{
              els.reviewActionHint.textContent = 'Select a governed run/checkpoint to unlock role-aware actions.';
              return;
            }}
            if (role === 'reviewer' && reviewableRun() && claimedByAnotherReviewer()) {{
              els.reviewActionHint.textContent = `Run is currently claimed by ${{reviewAssignment().claimed_by}}. Only that reviewer can unclaim or record a decision.`;
              return;
            }}
            if (role === 'reviewer' && reviewableRun() && !reviewAssignment().claimed_by) {{
              els.reviewActionHint.textContent = 'Claim this governed run before approving or rejecting it. Review assignment stays visible in the queue.';
              return;
            }}
            if (role === 'reviewer' && reviewableRun() && claimedByCurrentReviewer()) {{
              els.reviewActionHint.textContent = 'You claimed this run. Reviewer approval or rejection remains enforced by the backend role boundary.';
              return;
            }}
            if (role === 'operator' && resumableRun()) {{
              els.reviewActionHint.textContent = 'Run is approved. Operator can now resume the governed workflow.';
              return;
            }}
            els.reviewActionHint.textContent = 'This role or run state does not expose a next action in the shell. Raw JSON links remain available.';
          }}

          function renderReviewConsole() {{
            const run = state.selectedRun;
            const checkpoint = state.selectedCheckpoint;
            if (!run) {{
              els.reviewContextKv.innerHTML = '<div><dt>Checkpoint</dt><dd>Choose a queue item or latest run.</dd></div>';
              els.reviewStatePreview.textContent = 'Awaiting checkpoint context.';
              els.reviewPostureKv.innerHTML = '<div><dt>Selected run</dt><dd>—</dd></div><div><dt>Approval state</dt><dd>—</dd></div><div><dt>Current stage</dt><dd>—</dd></div><div><dt>Pending reviews</dt><dd>—</dd></div>';
              els.selectedReviewRunJson.href = '#';
              els.selectedCheckpointJson.href = '#';
              renderArtifactList(els.reviewArtifacts);
              renderReviewActions();
              renderArtifactInspector();
              return;
            }}
            const summary = checkpoint?.summary_json || run.latest_checkpoint?.summary_json || {{}};
            const stateJson = checkpoint?.state_json || {{}};
            els.reviewContextKv.innerHTML = `
              <div><dt>Checkpoint</dt><dd class="mono">${{escapeHtml(checkpoint?.checkpoint_id || run.latest_checkpoint?.checkpoint_id || '—')}}</dd></div>
              <div><dt>Checkpoint stage</dt><dd>${{statusPill(checkpoint?.stage || run.latest_checkpoint?.stage || run.current_stage || 'unknown')}}</dd></div>
              <div><dt>Checkpoint status</dt><dd>${{statusPill(checkpoint?.status || run.latest_checkpoint?.status || run.status || 'unknown')}}</dd></div>
              <div><dt>Captured</dt><dd>${{escapeHtml(formatDate(checkpoint?.created_at || run.latest_checkpoint?.created_at))}}</dd></div>
              <div><dt>Findings / locked</dt><dd>${{escapeHtml(`${{summary.findings ?? stateJson.findings_count ?? run.summary_json?.findings ?? 0}} / ${{summary.locked_findings ?? stateJson.locked_findings ?? run.summary_json?.locked_findings ?? 0}}`)}}</dd></div>
              <div><dt>Recoverable SAR</dt><dd>${{escapeHtml(formatSar(summary.total_recoverable_sar ?? run.summary_json?.total_recoverable_sar ?? 0))}}</dd></div>
              <div><dt>Dataset root</dt><dd class="mono">${{escapeHtml(stateJson.dataset_root || run.dataset_root || run.summary_json?.dataset || '—')}}</dd></div>
              <div><dt>Run directory</dt><dd class="mono">${{escapeHtml(stateJson.run_dir || run.run_dir || run.summary_json?.run_dir || '—')}}</dd></div>`;
            els.reviewStatePreview.textContent = JSON.stringify({{
              workflow_status: stateJson.workflow_status || checkpoint?.status || run.status,
              current_stage: stateJson.current_stage || checkpoint?.stage || run.current_stage,
              approval_status: stateJson.approval_status || run.approval?.approval_status,
              artifact_keys: stateJson.artifact_keys || Object.keys(run.summary_json?.artifacts || {{}}),
              audit_event_count: stateJson.audit_event_count,
              findings_count: stateJson.findings_count,
            }}, null, 2);
            els.reviewPostureKv.innerHTML = `
              <div><dt>Selected run</dt><dd class="mono">${{escapeHtml(run.run_id)}}</dd></div>
              <div><dt>Approval state</dt><dd>${{statusPill(run.approval?.approval_status || 'pending')}}</dd></div>
              <div><dt>Claimed by</dt><dd class="mono">${{escapeHtml(run.review_assignment?.claimed_by || 'Unclaimed')}}</dd></div>
              <div><dt>Current stage</dt><dd>${{statusPill(run.current_stage || 'unknown')}}</dd></div>
              <div><dt>Pending reviews</dt><dd>${{escapeHtml(String(state.queue.length || 0))}}</dd></div>`;
            els.selectedReviewRunJson.href = `/reviewer/runs/${{encodeURIComponent(run.run_id)}}`;
            els.selectedCheckpointJson.href = checkpoint?.checkpoint_id
              ? `/reviewer/checkpoints/${{encodeURIComponent(checkpoint.checkpoint_id)}}`
              : '#';
            renderArtifactList(els.reviewArtifacts, {{ showJsonLinks: true }});
            renderReviewActions();
            renderArtifactInspector();
          }}

          async function selectRun(runId, checkpointId = null, targetSection = null) {{
            if (!runId) return;
            if (targetSection) {{
              state.activeSection = targetSection;
              renderNavigation();
            }}
            const run = await requestJson(`/reviewer/runs/${{encodeURIComponent(runId)}}`);
            state.selectedRunId = runId;
            state.selectedRun = run;
            const effectiveCheckpointId = checkpointId || run.latest_checkpoint?.checkpoint_id || null;
            state.selectedCheckpointId = effectiveCheckpointId;
            if (effectiveCheckpointId) {{
              try {{
                state.selectedCheckpoint = await requestJson(`/reviewer/checkpoints/${{encodeURIComponent(effectiveCheckpointId)}}`);
              }} catch (_error) {{
                state.selectedCheckpoint = null;
              }}
            }} else {{
              state.selectedCheckpoint = null;
            }}
            syncArtifactSelection();
            renderRunDetail();
            renderReviewConsole();
            renderVectorSearch();
            renderQa();
            syncHashRoute();
          }}

          async function syncSelectedRun() {{
            if (bootstrap.api_auth_enabled && !state.session?.authenticated) {{
              state.selectedRunId = null;
              state.selectedRun = null;
              state.selectedCheckpointId = null;
              state.selectedCheckpoint = null;
              state.selectedArtifact = null;
              state.artifactPreview = null;
              renderRunDetail();
              renderReviewConsole();
              renderArtifactInspector();
              renderVectorSearch();
              renderQa();
              return;
            }}
            const nextRunId = state.selectedRunId || state.latestRun?.run_id || state.queue[0]?.run_id || null;
            const nextCheckpointId = state.selectedCheckpointId || state.queue.find((item) => item.run_id === nextRunId)?.checkpoint_id || null;
            if (!nextRunId) {{
              renderRunDetail();
              renderReviewConsole();
              renderArtifactInspector();
              renderVectorSearch();
              renderQa();
              return;
            }}
            await selectRun(nextRunId, nextCheckpointId);
          }}

          function renderPosture() {{
            const ready = state.readyStatus;
            if (!ready) {{
              if (bootstrap.api_auth_enabled && !state.session?.authenticated) {{
                setBanner('warn', 'Session not connected', 'Connect with the active reviewer/operator identity to load queue, run, data, and readiness state.');
              }} else {{
                setBanner('warn', 'Awaiting backend data', 'The shell is ready, but runtime posture has not yet been loaded.');
              }}
              return;
            }}
            if (ready.status === 'ok') {{
              setBanner('ok', 'Runtime ready', 'Queue, latest run, data status, and dependency checks loaded successfully.');
              return;
            }}
            if (ready.status === 'degraded') {{
              setBanner('warn', 'Readiness degraded', 'At least one dependency is skipped or degraded. Queue and latest-run review remain visible, but operator/reviewer attention is required.');
              return;
            }}
            setBanner('danger', 'Readiness failed', 'One or more core services failed readiness. The queue remains visible so governed work is not hidden by infrastructure trouble.');
          }}

          async function loadSession() {{
            state.session = await requestJson('/ui/session');
            renderSession();
          }}

          async function loadHomeData() {{
            if (bootstrap.api_auth_enabled && !state.session?.authenticated) {{
              renderQueue();
              renderRunsIndex();
              renderPosture();
              renderKpis();
                renderLatestRun();
                renderServices();
                renderDataStatus();
                renderVectorSearch();
                renderQa();
                renderHealthConsole();
                renderRunDetail();
                renderReviewConsole();
                renderArtifactInspector();
              return;
            }}
            const failures = [];
            async function guarded(label, request, fallback) {{
              try {{
                return await request;
              }} catch (error) {{
                failures.push(`${{label}}: ${{error?.message || 'failed'}}`);
                return fallback;
              }}
            }}
            // /health/ready returns 503 (with a valid body) when posture is
            // "failed" — that is degraded posture, not missing data. Recover the
            // body so it does not trip the "Partial backend data" warning; the
            // dedicated readiness banner reports posture instead.
            async function readinessProbe() {{
              try {{
                return await requestJson('/health/ready');
              }} catch (error) {{
                if (error.status === 503 && error.payload && error.payload.status) {{
                  return error.payload;
                }}
                throw error;
              }}
            }}
            const [queue, runs, latestRun, dataStatus, liveStatus, readyStatus, configStatus] = await Promise.all([
              guarded('Queue', requestJson('/reviewer/pending-reviews').then((payload) => payload.items || []), []),
              guarded('Runs index', requestJson('/reviewer/runs?limit=12').then((payload) => payload.items || []), []),
              guarded('Latest run', requestJson('/runs/latest'), null),
              guarded('Data status', requestJson('/data/status'), null),
              guarded('Live health', requestJson('/health/live'), null),
              guarded('Readiness', readinessProbe(), null),
              guarded('Config', requestJson('/health/config'), null),
            ]);
            state.queue = queue;
            state.runs = runs;
            state.latestRun = latestRun;
            state.dataStatus = dataStatus;
            state.liveStatus = liveStatus;
            state.readyStatus = readyStatus;
            state.configStatus = configStatus;
            renderSession();
            renderQueue();
            renderRunsIndex();
            renderKpis();
            renderLatestRun();
            renderServices();
            renderDataStatus();
            renderVectorSearch();
            renderQa();
            renderHealthConsole();
            renderPosture();
            if (failures.length) {{
              setBanner('warn', 'Partial backend data loaded', failures.join(' · '));
            }}
            await syncSelectedRun();
          }}

          async function refreshAll() {{
            try {{
              await loadSession();
              await loadHomeData();
            }} catch (error) {{
              const message = error?.message || 'Unknown UI loading error';
              state.queue = [];
              state.runs = [];
              state.dataStatus = null;
              state.liveStatus = null;
              state.readyStatus = null;
              state.configStatus = null;
              state.selectedArtifact = null;
              state.artifactPreview = null;
              renderQueue();
              renderRunsIndex();
              renderKpis();
              renderLatestRun();
              renderServices();
              renderDataStatus();
              renderVectorSearch();
              renderQa();
              renderHealthConsole();
              renderArtifactInspector();
              setBanner(error?.status === 401 ? 'warn' : 'danger', error?.status === 401 ? 'Authentication required' : 'Failed to load shell data', message);
            }}
          }}

          async function submitVectorSearch(event) {{
            event?.preventDefault?.();
            const query = els.vectorSearchQuery.value.trim();
            const limit = Math.max(1, Math.min(10, Number(els.vectorSearchLimit.value || 5) || 5));
            state.vectorSearch = {{
              status: 'loading',
              query,
              results: [],
              payload: null,
              error: '',
            }};
            renderVectorSearch();
            try {{
              const params = new URLSearchParams({{ query, limit: String(limit) }});
              const runId = activeVectorRunId();
              if (runId) params.set('run_id', runId);
              const payload = await requestJson(`/data/vector-search?${{params.toString()}}`);
              state.vectorSearch = {{
                status: payload.status === 'ready' ? 'ready' : 'failed',
                query,
                results: payload.results || [],
                payload,
                error: payload.reason || '',
              }};
              renderVectorSearch();
            }} catch (error) {{
              state.vectorSearch = {{
                status: 'failed',
                query,
                results: [],
                payload: error?.payload || {{ status: 'failed', detail: error?.message || 'Vector search failed.' }},
                error: error?.message || 'Vector search failed.',
              }};
              renderVectorSearch();
            }}
          }}

          async function submitQa(event) {{
            event?.preventDefault?.();
            const question = els.qaInput.value.trim();
            if (!question) return;
            const runId = activeQaRunId();
            state.qaStatus = {{ status: 'loading', payload: {{ question }}, error: '' }};
            renderQa();
            try {{
              const body = {{ question }};
              if (runId) body.run_id = runId;
              const payload = await requestJson('/qa', {{
                method: 'POST',
                body: JSON.stringify(body),
              }});
              state.qaThread.push({{ question, payload }});
              state.qaStatus = {{ status: 'ready', payload, error: '' }};
              els.qaInput.value = '';
              renderQa();
            }} catch (error) {{
              const payload = error?.payload || {{ status: 'failed', detail: error?.message || 'Q&A failed.' }};
              state.qaThread.push({{ question, payload, error: error?.message || 'Q&A failed.' }});
              state.qaStatus = {{
                status: 'failed',
                payload,
                error: error?.message || 'Q&A failed.',
              }};
              renderQa();
            }}
          }}

          async function submitStartRun(event) {{
            event?.preventDefault?.();
            if ((state.session?.role || '') !== 'operator') return;
            const payload = {{
              dataset: els.startRunDataset.value.trim() || null,
              source_pack_id: state.sourcePack?.source_pack_id || null,
              run_dir: els.startRunRunDir.value.trim() || null,
              skip_prepare: els.startRunSkipPrepare.checked,
              sync_artifacts: els.startRunSyncArtifacts.checked,
              allow_partial_source_pack: els.startRunAllowPartialSourcePack.checked,
            }};
            if (!payload.dataset) delete payload.dataset;
            if (!payload.source_pack_id) delete payload.source_pack_id;
            if (!payload.run_dir) delete payload.run_dir;
            if (!payload.source_pack_id) delete payload.allow_partial_source_pack;
            state.startRunSubmitting = true;
            setStartRunStatus('warn', 'Submitting run request', payload.source_pack_id
              ? `Posting source pack ${{payload.source_pack_id}} plus runtime options to /runs.`
              : 'Posting the selected dataset, run directory, and runtime options to /runs.');
            renderStartRunPanel();
            try {{
              const result = await requestJson('/runs', {{ method: 'POST', body: JSON.stringify(payload) }});
              state.startRunSubmitting = false;
              state.startRunPanelOpen = false;
              els.startRunDataset.value = '';
              els.startRunRunDir.value = '';
              els.startRunSkipPrepare.checked = false;
              els.startRunSyncArtifacts.checked = true;
              els.startRunAllowPartialSourcePack.checked = false;
              state.latestRun = result;
              setStartRunStatus('ok', 'Run created', `Run ${{result.run_id || 'created'}} routed to governed run detail.`);
              renderStartRunPanel();
              renderLatestRun();
              renderKpis();
              setBanner('ok', 'Run started', `Run ${{result.run_id || 'created'}} is now in state ${{result.status || 'unknown'}}.`);
              await loadHomeData();
              if (result.run_id) await selectRun(result.run_id, null, 'runs');
            }} catch (error) {{
              state.startRunSubmitting = false;
              setStartRunStatus('danger', 'Run start failed', error?.message || 'Unable to start a run.');
              renderStartRunPanel();
              setBanner('danger', 'Run start failed', error?.message || 'Unable to start a run.');
            }}
          }}

          async function submitSourcePackUpload(event) {{
            event?.preventDefault?.();
            if ((state.session?.role || '') !== 'operator') return;
            const files = Array.from(els.sourcePackFiles.files || []);
            if (!files.length) {{
              setSourcePackStatus('warn', 'No files selected', 'Choose a folder or file set before uploading.');
              return;
            }}
            const formData = new FormData();
            files.forEach((file) => {{
              const rel = file.webkitRelativePath || file.name;
              formData.append('files', file, rel);
            }});
            state.sourcePackSubmitting = true;
            setSourcePackStatus('warn', 'Uploading source pack', 'Posting the selected folder payload to /source-packs.');
            renderSourcePackPanel();
            try {{
              const result = await requestMultipart('/source-packs', formData);
              state.sourcePack = result;
              state.sourcePackSubmitting = false;
              setSourcePackStatus('ok', 'Source pack uploaded', `Loaded source pack ${{result.source_pack_id || 'created'}} for manifest preview and readiness display.`);
              renderSourcePackPanel();
            }} catch (error) {{
              state.sourcePackSubmitting = false;
              setSourcePackStatus('danger', 'Upload failed', error?.message || 'Unable to upload the selected source pack.');
              renderSourcePackPanel();
            }}
          }}

          async function submitSourcePackPath(event) {{
            event?.preventDefault?.();
            if ((state.session?.role || '') !== 'operator') return;
            const folderPath = els.sourcePackPath.value.trim();
            if (!folderPath) {{
              setSourcePackStatus('warn', 'No folder path provided', 'Enter a workspace-bounded folder path before staging.');
              return;
            }}
            state.sourcePackSubmitting = true;
            setSourcePackStatus('warn', 'Staging workspace folder', 'Posting the selected workspace path to /source-packs/from-path.');
            renderSourcePackPanel();
            try {{
              const result = await requestJson('/source-packs/from-path', {{
                method: 'POST',
                body: JSON.stringify({{ folder_path: folderPath }}),
              }});
              state.sourcePack = result;
              state.sourcePackSubmitting = false;
              setSourcePackStatus('ok', 'Source pack staged', `Loaded source pack ${{result.source_pack_id || 'created'}} from the workspace boundary.`);
              renderSourcePackPanel();
            }} catch (error) {{
              state.sourcePackSubmitting = false;
              setSourcePackStatus('danger', 'Local staging failed', error?.message || 'Unable to stage the selected workspace folder.');
              renderSourcePackPanel();
            }}
          }}

          async function revalidateSourcePack() {{
            if ((state.session?.role || '') !== 'operator') return;
            const sourcePackId = state.sourcePack?.source_pack_id;
            if (!sourcePackId) {{
              setSourcePackStatus('warn', 'No active source pack', 'Upload or stage a source pack before revalidating.');
              return;
            }}
            state.sourcePackSubmitting = true;
            setSourcePackStatus('warn', 'Revalidating source pack', `Refreshing manifest and readiness payload for ${{sourcePackId}}.`);
            renderSourcePackPanel();
            try {{
              const result = await requestJson('/source-packs/validate', {{
                method: 'POST',
                body: JSON.stringify({{ source_pack_id: sourcePackId }}),
              }});
              state.sourcePack = result;
              state.sourcePackSubmitting = false;
              setSourcePackStatus('ok', 'Source pack validated', `Validation refreshed for source pack ${{result.source_pack_id || sourcePackId}}.`);
              renderSourcePackPanel();
            }} catch (error) {{
              state.sourcePackSubmitting = false;
              setSourcePackStatus('danger', 'Validation failed', error?.message || 'Unable to validate the current source pack.');
              renderSourcePackPanel();
            }}
          }}

          async function confirmSourcePackMapping(rowId) {{
            if ((state.session?.role || '') !== 'operator') return;
            const sourcePackId = state.sourcePack?.source_pack_id;
            const row = document.getElementById(rowId);
            if (!sourcePackId || !row) {{
              setSourcePackStatus('warn', 'No mapping selected', 'Choose a candidate mapping from the validated source pack.');
              return;
            }}
            const decodedPath = decodeURIComponent(row.getAttribute('data-rel') || '');
            const role = row.getAttribute('data-role') || '';
            const columnMapping = {{}};
            row.querySelectorAll('select.mapping-select').forEach((sel) => {{
              const canonical = sel.getAttribute('data-canonical');
              if (canonical && sel.value) columnMapping[canonical] = sel.value;
            }});
            state.sourcePackSubmitting = true;
            setSourcePackStatus('warn', 'Confirming mapping', `Applying the canonical mapping for ${{decodedPath}}.`);
            renderSourcePackPanel();
            try {{
              const body = {{ source_pack_id: sourcePackId, relative_path: decodedPath }};
              if (role) body.role = role;
              if (Object.keys(columnMapping).length) body.column_mapping = columnMapping;
              const result = await requestJson('/source-packs/confirm-mapping', {{
                method: 'POST',
                body: JSON.stringify(body),
              }});
              state.sourcePack = result;
              state.sourcePackSubmitting = false;
              setSourcePackStatus('ok', 'Mapping confirmed', `Canonical mapping confirmed for ${{decodedPath}}.`);
              renderSourcePackPanel();
            }} catch (error) {{
              state.sourcePackSubmitting = false;
              setSourcePackStatus('danger', 'Mapping confirmation failed', error?.message || 'Unable to confirm the source-pack mapping.');
              renderSourcePackPanel();
            }}
          }}

          function openLatestRun() {{
            if (!state.latestRun?.run_id) return;
            selectRun(state.latestRun.run_id, null, 'runs').catch((error) => {{
              setBanner('danger', 'Unable to load latest run', error?.message || 'Latest run detail could not be loaded.');
            }});
          }}

          async function sendReviewDecision(decision) {{
            if (!state.selectedRunId) return;
            const comment = els.reviewComment.value.trim();
            const actionLabel = decision === 'approved' ? 'approve' : 'reject';
            if (!confirm(`Are you sure you want to ${{actionLabel}} run ${{state.selectedRunId}}?`)) return;
            try {{
              await requestJson(`/reviewer/runs/${{encodeURIComponent(state.selectedRunId)}}/${{decision === 'approved' ? 'approve' : 'reject'}}`, {{
                method: 'POST',
                body: JSON.stringify({{ comment }}),
              }});
              setBanner('ok', `Run ${{decision === 'approved' ? 'approved' : 'rejected'}}`, `Reviewer decision recorded for run ${{state.selectedRunId}}.`);
              await loadHomeData();
              await selectRun(state.selectedRunId, state.selectedCheckpointId, 'review');
            }} catch (error) {{
              setBanner('danger', `Run ${{actionLabel}} failed`, error?.message || 'Unable to record reviewer decision.');
            }}
          }}

          async function resumeSelectedRun() {{
            if (!state.selectedRunId) return;
            if (!confirm(`Resume approved run ${{state.selectedRunId}}?`)) return;
            try {{
              await requestJson(`/operator/runs/${{encodeURIComponent(state.selectedRunId)}}/resume`, {{ method: 'POST' }});
              setBanner('ok', 'Run resumed', `Operator resume requested for run ${{state.selectedRunId}}.`);
              await loadHomeData();
              await selectRun(state.selectedRunId, null, 'runs');
            }} catch (error) {{
              setBanner('danger', 'Resume failed', error?.message || 'Unable to resume approved run.');
            }}
          }}

          async function claimSelectedRun() {{
            if (!state.selectedRunId) return;
            try {{
              await requestJson(`/reviewer/runs/${{encodeURIComponent(state.selectedRunId)}}/claim`, {{ method: 'POST' }});
              setBanner('ok', 'Run claimed', `Reviewer claim recorded for run ${{state.selectedRunId}}.`);
              await loadHomeData();
              await selectRun(state.selectedRunId, state.selectedCheckpointId, 'review');
            }} catch (error) {{
              setBanner('danger', 'Claim failed', error?.message || 'Unable to claim this governed run.');
            }}
          }}

          async function unclaimSelectedRun() {{
            if (!state.selectedRunId) return;
            try {{
              await requestJson(`/reviewer/runs/${{encodeURIComponent(state.selectedRunId)}}/unclaim`, {{ method: 'POST' }});
              setBanner('ok', 'Run unclaimed', `Reviewer assignment cleared for run ${{state.selectedRunId}}.`);
              await loadHomeData();
              await selectRun(state.selectedRunId, state.selectedCheckpointId, 'review');
            }} catch (error) {{
              setBanner('danger', 'Unclaim failed', error?.message || 'Unable to clear the reviewer assignment.');
            }}
          }}

          navButtons.forEach((button) => {{
            button.addEventListener('click', () => {{
              state.activeSection = button.dataset.section;
              renderNavigation();
              syncHashRoute();
            }});
          }});
          document.getElementById('connect-button').addEventListener('click', async () => {{
            state.token = els.sessionToken.value.trim();
            if (state.token) window.localStorage.setItem('strategyos.ui.token', state.token);
            else window.localStorage.removeItem('strategyos.ui.token');
            await refreshAll();
          }});
          document.getElementById('clear-button').addEventListener('click', async () => {{
            state.token = '';
            state.session = null;
            state.queue = [];
            state.runs = [];
            state.latestRun = null;
            state.dataStatus = null;
            state.liveStatus = null;
            state.readyStatus = null;
            state.configStatus = null;
            state.selectedArtifact = null;
            state.artifactPreview = null;
            state.vectorSearch = {{ status: 'idle', query: '', results: [], payload: null, error: '' }};
            state.qaThread = [];
            state.qaStatus = {{ status: 'idle', payload: null, error: '' }};
            state.startRunPanelOpen = false;
            state.startRunSubmitting = false;
            state.sourcePack = null;
            state.sourcePackSubmitting = false;
            els.sessionToken.value = '';
            els.sourcePackFiles.value = '';
            els.sourcePackPath.value = '';
            els.startRunDataset.value = '';
            els.startRunRunDir.value = '';
            els.startRunSkipPrepare.checked = false;
            els.startRunSyncArtifacts.checked = true;
            window.localStorage.removeItem('strategyos.ui.token');
            await refreshAll();
          }});
          document.getElementById('refresh-home').addEventListener('click', refreshAll);
          els.vectorSearchForm.addEventListener('submit', submitVectorSearch);
          els.qaForm.addEventListener('submit', submitQa);
          els.startRun.addEventListener('click', () => toggleStartRunPanel());
          els.sourcePackUploadForm.addEventListener('submit', submitSourcePackUpload);
          els.sourcePackPathForm.addEventListener('submit', submitSourcePackPath);
          els.sourcePackValidate.addEventListener('click', revalidateSourcePack);
          els.startRunForm.addEventListener('submit', submitStartRun);
          els.startRunCancel.addEventListener('click', () => toggleStartRunPanel(false));
          els.openLatestRun.addEventListener('click', openLatestRun);
          els.selectLatestRun.addEventListener('click', openLatestRun);
          els.claimRun.addEventListener('click', claimSelectedRun);
          els.unclaimRun.addEventListener('click', unclaimSelectedRun);
          els.approveRun.addEventListener('click', () => sendReviewDecision('approved'));
          els.rejectRun.addEventListener('click', () => sendReviewDecision('rejected'));
          els.resumeRun.addEventListener('click', resumeSelectedRun);
          document.addEventListener('click', (event) => {{
            const trigger = event.target.closest('[data-open-run]');
            if (!trigger) return;
            const runId = trigger.getAttribute('data-open-run') || '';
            const checkpointId = trigger.getAttribute('data-open-checkpoint') || null;
            const targetSection = trigger.getAttribute('data-target-section') || 'runs';
            selectRun(runId, checkpointId || null, targetSection).catch((error) => {{
              setBanner('danger', 'Unable to load governed detail', error?.message || 'Run or checkpoint detail could not be loaded.');
            }});
          }});
          document.addEventListener('click', (event) => {{
            const trigger = event.target.closest('[data-open-artifact]');
            if (!trigger) return;
            const key = trigger.getAttribute('data-open-artifact') || '';
            const scope = trigger.getAttribute('data-artifact-scope') || 'run';
            const scopeId = trigger.getAttribute('data-artifact-scope-id') || '';
            openArtifactInspector(key, scope, scopeId);
          }});
          document.addEventListener('click', (event) => {{
            const claimTrigger = event.target.closest('[data-claim-run]');
            if (claimTrigger) {{
              const runId = claimTrigger.getAttribute('data-claim-run') || '';
              if (!runId) return;
              const checkpointId = state.queue.find((item) => item.run_id === runId)?.checkpoint_id || null;
              selectRun(runId, checkpointId, 'review').then(claimSelectedRun).catch((error) => {{
                setBanner('danger', 'Claim failed', error?.message || 'Unable to load run before claim.');
              }});
              return;
            }}
            const unclaimTrigger = event.target.closest('[data-unclaim-run]');
            if (!unclaimTrigger) return;
            const runId = unclaimTrigger.getAttribute('data-unclaim-run') || '';
            if (!runId) return;
            const checkpointId = state.queue.find((item) => item.run_id === runId)?.checkpoint_id || null;
            selectRun(runId, checkpointId, 'review').then(unclaimSelectedRun).catch((error) => {{
              setBanner('danger', 'Unclaim failed', error?.message || 'Unable to load run before unclaim.');
            }});
          }});
          window.addEventListener('hashchange', () => {{
            const route = parseHashRoute();
            if (!route.runId) return;
            selectRun(route.runId, route.checkpointId || null, route.section || 'runs').then(() => {{
              if (!route.artifact) return;
              return openArtifactInspector(route.artifact, route.artifactScope, route.artifactScopeId || '');
            }}).catch((error) => {{
              setBanner('danger', 'Deep link failed', error?.message || 'Artifact deep link could not be restored.');
            }});
          }});

          els.sessionToken.value = state.token;
          renderNavigation();
          renderSession();
          renderQueue();
          renderRunsIndex();
          renderKpis();
          renderLatestRun();
          renderServices();
          renderDataStatus();
          renderVectorSearch();
          renderQa();
          renderHealthConsole();
          renderStartRunPanel();
          renderSourcePackPanel();
          renderRunDetail();
          renderReviewConsole();
          renderArtifactInspector();
          renderPosture();
          refreshAll().then(() => {{
            const route = parseHashRoute();
            if (route.section) {{
              state.activeSection = route.section;
              renderNavigation();
            }}
            if (!route.runId) return;
            return selectRun(route.runId, route.checkpointId || null, route.section || 'runs').then(() => {{
              if (!route.artifact) return;
              return openArtifactInspector(route.artifact, route.artifactScope, route.artifactScopeId || '');
            }});
          }}).catch((error) => {{
            setBanner('danger', 'Deep link failed', error?.message || 'Artifact deep link could not be restored.');
          }});
        </script>
      </body>
    </html>
    """


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
    checkpoint = _require_store_record(
        state_store.latest_checkpoint(run_id),
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
    return {
        "status": "ok",
        "authenticated": authenticated,
        "role": role,
        "subject": subject,
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
    return {
        "items": items,
        "store_status": store_status,
        "viewer_role": principal.get("role"),
        "viewer_subject": principal.get("subject"),
    }


@app.get("/reviewer/runs")
def reviewer_runs(
    limit: int = 12,
    principal: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    items, store_status = _store_list_or_empty(state_store.list_recent_runs(limit=limit))
    return {
        "items": items,
        "store_status": store_status,
        "viewer_role": principal.get("role"),
        "viewer_subject": principal.get("subject"),
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
    approval = _require_store_record(
        state_store.approval_status_for_run(run_id),
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
    checkpoint = _require_store_record(
        state_store.latest_checkpoint(run_id),
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
