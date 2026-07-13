from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .config import (
    CONFIG,
    EXTERNAL_MODE_BATCH_APIS,
    EXTERNAL_MODE_HOSTED_OCR_VISION,
    EXTERNAL_MODE_MODEL_PROVIDER,
    EXTERNAL_MODE_OBJECT_STORAGE_SYNC,
)
from .ingestion import RUN_CONTEXT_FILENAME
from .models import AuditEvent
from .neo4j_store import sync_knowledge_graph
from .paths import AGENT_INPUT_DIR, DEFAULT_RUN_DIR
from .platform_foundation import build_run_report_contracts, build_tenant_context
from .plugins import load_configured_plugins, plugin_status
from .prepare_inputs import prepare_agent_input
from .run_registry import allocate_run_dir, update_run_pointers
from .runtime_artifacts import AUDIT_LOG_FILENAME, remove_legacy_artifacts
from .state_store import persist_run_summary
from .storage import sync_artifacts as sync_artifact_files
from .storage import sync_source_files
from .runtime_governance import RuntimeGovernance, build_run_summary, checkpoint_state
from .source_finance_kpis import derive_source_finance_kpis
from .source_calendar import derive_calendar_agenda
from .source_pack import resolve_source_pack_for_run
from .vector_store import sync_findings_vector_store
from .workflow import build_workflow


HOSTED_OCR_ENGINES = {
    "google_vision",
    "textract",
    "hosted_ocr",
    "hosted_vision",
}


def _persist_run_summary_best_effort(
    summary: dict[str, Any],
    *,
    run_id: str | None,
    bundle: Any,
    findings: list[Any],
    artifacts: dict[str, Path],
    audit_events: list[AuditEvent],
) -> dict[str, Any]:
    try:
        return persist_run_summary(
            summary,
            run_id=run_id,
            bundle=bundle,
            findings=findings,
            artifacts=artifacts,
            audit_events=audit_events,
        )
    except Exception as exc:
        return {
            "status": "failed",
            "run_id": run_id,
            "reason": str(exc),
            "error_type": type(exc).__name__,
        }


def _normalize_json(value):
    if is_dataclass(value):
        return {key: _normalize_json(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _normalize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_json(item) for item in value]
    return value


def _materialize_ping_pong_audit_log(
    run_dir: Path,
    audit_events: list,
    artifacts: dict[str, Path],
) -> dict[str, Path]:
    if not audit_events:
        return artifacts
    audit_log_path = Path(artifacts.get("audit_log") or run_dir / AUDIT_LOG_FILENAME)
    audit_log_path.write_text(
        json.dumps(_normalize_json(audit_events), indent=2),
        encoding="utf-8",
    )
    return {**artifacts, "audit_log": audit_log_path}


def _external_mode_status(
    *,
    mode_name: str,
    requested: bool,
    reason: str,
    enabled: bool = False,
) -> dict[str, object]:
    return {
        "requested": requested,
        "approved": CONFIG.run_policy.allows(mode_name),
        "enabled": enabled,
        "policy_mode": CONFIG.run_policy.mode,
        "reason": reason,
    }


def _build_external_mode_statuses(sync_artifacts_requested: bool) -> dict[str, dict[str, object]]:
    hosted_ocr_requested = bool(
        CONFIG.hosted_ocr_vision_enabled or CONFIG.ocr_engine in HOSTED_OCR_ENGINES
    )
    return {
        EXTERNAL_MODE_OBJECT_STORAGE_SYNC: _external_mode_status(
            mode_name=EXTERNAL_MODE_OBJECT_STORAGE_SYNC,
            requested=sync_artifacts_requested,
            reason="Artifact sync was not requested."
            if not sync_artifacts_requested
            else "Awaiting run-policy gate review.",
        ),
        EXTERNAL_MODE_MODEL_PROVIDER: _external_mode_status(
            mode_name=EXTERNAL_MODE_MODEL_PROVIDER,
            requested=bool(CONFIG.model_provider_enabled),
            reason="Hosted model-provider path is not requested."
            if not CONFIG.model_provider_enabled
            else "Hosted model-provider request is blocked pending explicit run-policy approval.",
        ),
        EXTERNAL_MODE_BATCH_APIS: _external_mode_status(
            mode_name=EXTERNAL_MODE_BATCH_APIS,
            requested=bool(CONFIG.batch_apis_enabled),
            reason="Hosted batch API path is not requested."
            if not CONFIG.batch_apis_enabled
            else "Hosted batch API request is blocked pending explicit run-policy approval.",
        ),
        EXTERNAL_MODE_HOSTED_OCR_VISION: _external_mode_status(
            mode_name=EXTERNAL_MODE_HOSTED_OCR_VISION,
            requested=hosted_ocr_requested,
            reason="Hosted OCR/vision path is not requested; local OCR remains authoritative."
            if not hosted_ocr_requested
            else "Hosted OCR/vision request is blocked pending explicit run-policy approval.",
        ),
    }


def _finalize_external_mode_statuses(
    statuses: dict[str, dict[str, object]],
    *,
    object_store_configured: bool,
    object_storage_sync_executed: bool,
) -> dict[str, dict[str, object]]:
    finalized = {key: dict(value) for key, value in statuses.items()}
    object_sync = finalized[EXTERNAL_MODE_OBJECT_STORAGE_SYNC]
    if bool(object_sync["requested"]):
        if not bool(object_sync["approved"]):
            object_sync["reason"] = (
                f"Run policy '{CONFIG.run_policy.mode}' blocks external mode '{EXTERNAL_MODE_OBJECT_STORAGE_SYNC}'."
            )
        elif not object_store_configured:
            object_sync["reason"] = "Object storage sync is approved but the object store is not configured."
        elif object_storage_sync_executed:
            object_sync["enabled"] = True
            object_sync["reason"] = "Object storage sync executed against the configured object store."
        else:
            object_sync["reason"] = "Object storage sync was approved but did not execute."

    for mode_name, reason in (
        (
            EXTERNAL_MODE_MODEL_PROVIDER,
            "No hosted model-provider integration is wired in this build; local execution remains in force.",
        ),
        (
            EXTERNAL_MODE_BATCH_APIS,
            "No hosted batch API integration is wired in this build; local execution remains in force.",
        ),
        (
            EXTERNAL_MODE_HOSTED_OCR_VISION,
            "No hosted OCR/vision integration is wired in this build; local OCR remains authoritative.",
        ),
    ):
        status = finalized[mode_name]
        if bool(status["requested"]) and bool(status["approved"]):
            status["reason"] = reason
    return finalized


def _build_run_policy_audit_events(
    statuses: dict[str, dict[str, object]],
) -> list[AuditEvent]:
    events: list[AuditEvent] = []
    for mode_name, status in statuses.items():
        events.append(
            AuditEvent(
                round_no=0,
                actor="Runtime Governance",
                finding_id=mode_name,
                action="run_policy_gate",
                detail=(
                    f"External mode {mode_name}: requested={status['requested']}; approved={status['approved']}; "
                    f"enabled={status['enabled']}; policy_mode={status['policy_mode']}. {status['reason']}"
                ),
                status="enabled"
                if bool(status["enabled"])
                else "blocked"
                if bool(status["requested"]) and not bool(status["approved"])
                else "logged",
            )
        )
    return events


def _write_source_pack_run_context(dataset_root: Path, source_pack_payload: dict | None) -> None:
    if source_pack_payload is None:
        return
    readiness = source_pack_payload.get("task_readiness") or {}
    resolution = source_pack_payload.get("run_resolution") or {}
    duplicate_roles = [str(role) for role in readiness.get("duplicate_run_model_roles", [])]
    # Single source of truth: the run resolution computed available/missing
    # roles from the real readiness inventory using canonical role names.
    available_roles = sorted(str(role) for role in resolution.get("available_roles", []))
    missing_roles = sorted(str(role) for role in resolution.get("missing_roles", []))
    context_path = dataset_root / RUN_CONTEXT_FILENAME
    context_path.write_text(
        json.dumps(
            {
                "source_pack_id": source_pack_payload.get("source_pack_id"),
                "run_mode": resolution.get("run_mode", "full"),
                "available_roles": available_roles,
                "missing_roles": missing_roles,
                "duplicate_roles": duplicate_roles,
                "tenant_context": source_pack_payload.get("tenant_context") or {},
                "ingestion_job": source_pack_payload.get("ingestion_job") or {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _execute_strategyos_workflow(
    dataset: Path | None = None,
    source_pack_id: str | None = None,
    run_dir: Path = DEFAULT_RUN_DIR,
    skip_prepare: bool = False,
    sync_artifacts: bool | None = None,
    local_only_fallback: bool = False,
    require_human_review: bool | None = None,
    allow_partial_source_pack: bool = False,
) -> tuple[dict, dict]:
    load_configured_plugins()
    source_pack_payload: dict | None = None
    if source_pack_id:
        source_pack_payload = resolve_source_pack_for_run(
            source_pack_id, allow_partial=allow_partial_source_pack
        )
        dataset_root = Path(
            str((source_pack_payload.get("run_resolution") or {}).get("dataset_root") or source_pack_payload["normalized_dataset_root"])
        ).resolve()
        skip_prepare = True
    elif skip_prepare:
        dataset_root = dataset or AGENT_INPUT_DIR
    else:
        agent_input, evaluation = prepare_agent_input()
        dataset_root = dataset or agent_input
    _write_source_pack_run_context(dataset_root, source_pack_payload)

    actual_run_dir = allocate_run_dir(run_dir)
    actual_run_dir.mkdir(parents=True, exist_ok=False)
    remove_legacy_artifacts(actual_run_dir)
    requires_human_review = (
        CONFIG.require_human_review
        if require_human_review is None
        else bool(require_human_review)
    )
    governance = RuntimeGovernance(
        dataset_root=dataset_root,
        source_pack_id=source_pack_id,
        run_dir=actual_run_dir,
        requires_human_review=requires_human_review,
    )
    requested_backend = (
        "local" if local_only_fallback else getattr(CONFIG, "runtime_backend", "local")
    )
    workflow = build_workflow(
        checkpoint_handler=governance.checkpoint,
        stop_before_writer=governance.stop_before_writer,
        runtime_backend=requested_backend,
        postgres_url=CONFIG.database_url,
        allow_local_fallback=False,
    )
    result = workflow.invoke(governance.initial_state())
    requested_object_storage_sync = (
        bool(CONFIG.sync_artifacts) if sync_artifacts is None else bool(sync_artifacts)
    )
    external_mode_statuses = _build_external_mode_statuses(requested_object_storage_sync)
    artifacts = _materialize_ping_pong_audit_log(
        actual_run_dir,
        list(result.get("audit_events", []))
        + _build_run_policy_audit_events(
            _finalize_external_mode_statuses(
                external_mode_statuses,
                object_store_configured=bool(CONFIG.object_store.enabled),
                object_storage_sync_executed=False,
            )
        ),
        dict(result.get("artifacts", {})),
    )
    result["artifacts"] = artifacts
    result["audit_events"] = list(result.get("audit_events", [])) + _build_run_policy_audit_events(
        _finalize_external_mode_statuses(
            external_mode_statuses,
            object_store_configured=bool(CONFIG.object_store.enabled),
            object_storage_sync_executed=False,
        )
    )

    summary = build_run_summary(result)
    # Standard runs receive source extracts directly. Derive the CEO actuals
    # from those files instead of requiring a separate Oracle API request.
    summary["finance_kpi"] = derive_source_finance_kpis(dataset_root)
    summary["calendar_agenda"] = derive_calendar_agenda(dataset_root)
    attach_local_review_checkpoint(summary, result)
    if source_pack_payload is not None:
        summary["source_pack"] = {
            "source_pack_id": source_pack_payload.get("source_pack_id"),
            "source_kind": source_pack_payload.get("source_kind"),
            "normalized_dataset_root": source_pack_payload.get("normalized_dataset_root"),
            "task_readiness": source_pack_payload.get("task_readiness"),
            "run_resolution": source_pack_payload.get("run_resolution"),
        }
    # Surface detector coverage (which detectors ran vs were skipped for missing
    # roles) and the run mode in machine-readable output, not only the prose
    # deliverables. Pulled from the loaded bundle.
    bundle = result.get("bundle")
    detector_report = _normalize_json(getattr(bundle, "detector_report", {}) or {})
    run_meta = _normalize_json(getattr(bundle, "run_metadata", {}) or {})
    summary["detector_report"] = detector_report
    summary["run_mode"] = run_meta.get("run_mode", "full")
    summary["available_roles"] = run_meta.get("available_roles", [])
    summary["missing_roles"] = run_meta.get("missing_roles", [])
    tenant_payload = run_meta.get("tenant_context") or source_pack_payload.get("tenant_context") if source_pack_payload else None
    tenant_context = build_tenant_context(
        tenant_id=(tenant_payload or {}).get("tenant_id") if isinstance(tenant_payload, dict) else None,
        tenant_name=(tenant_payload or {}).get("tenant_name") if isinstance(tenant_payload, dict) else None,
        workspace_id=(tenant_payload or {}).get("workspace_id") if isinstance(tenant_payload, dict) else None,
    )
    summary["tenant_context"] = asdict(tenant_context)
    if source_pack_payload is not None and source_pack_payload.get("ingestion_job"):
        summary["ingestion_job"] = source_pack_payload.get("ingestion_job")
    summary["artifacts"] = {key: str(path) for key, path in artifacts.items()}
    summary["report_contracts"] = asdict(
        build_run_report_contracts(
            summary["artifacts"],
            tenant_id=tenant_context.tenant_id,
            run_id=str(summary.get("run_id") or "") or None,
        )
    )
    summary["audit_event_count"] = len(result.get("audit_events", []))
    summary["audit_verification"] = _normalize_json(
        result.get("audit_verification", {})
    )
    summary["runtime"] = dict(getattr(workflow, "runtime_metadata", {}))
    summary["plugins"] = plugin_status()
    summary["run_policy"] = {
        "mode": CONFIG.run_policy.mode,
        "approved_external_modes": list(CONFIG.run_policy.approved_external_modes),
    }
    summary["external_modes"] = {
        "runtime_backend": requested_backend,
        **_finalize_external_mode_statuses(
            external_mode_statuses,
            object_store_configured=bool(CONFIG.object_store.enabled),
            object_storage_sync_executed=False,
        ),
    }
    summary_path = actual_run_dir / "run_summary.json"
    attach_local_review_checkpoint(summary, result)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    do_sync = (
        requested_object_storage_sync
        and bool(CONFIG.run_policy.allows(EXTERNAL_MODE_OBJECT_STORAGE_SYNC))
        and bool(CONFIG.object_store.enabled)
    )
    if do_sync:
        uploaded = sync_artifact_files(
            actual_run_dir,
            [Path(p) for p in summary["artifacts"].values()] + [summary_path],
        )
        source_uploads = sync_source_files(dataset_root)
        summary["object_store_uploads"] = uploaded
        summary["source_uploads"] = source_uploads
    summary["external_modes"] = {
        "runtime_backend": requested_backend,
        **_finalize_external_mode_statuses(
            external_mode_statuses,
            object_store_configured=bool(CONFIG.object_store.enabled),
            object_storage_sync_executed=do_sync,
        ),
    }
    result["audit_events"] = list(result.get("audit_events", []))
    result["audit_events"][-4:] = _build_run_policy_audit_events(
        _finalize_external_mode_statuses(
            external_mode_statuses,
            object_store_configured=bool(CONFIG.object_store.enabled),
            object_storage_sync_executed=do_sync,
        )
    )
    result["artifacts"] = _materialize_ping_pong_audit_log(
        actual_run_dir,
        result.get("audit_events", []),
        {key: Path(path) for key, path in summary["artifacts"].items()},
    )
    summary["artifacts"] = {key: str(path) for key, path in result["artifacts"].items()}
    summary["report_contracts"] = asdict(
        build_run_report_contracts(
            summary["artifacts"],
            tenant_id=tenant_context.tenant_id,
            run_id=str(summary.get("run_id") or "") or None,
        )
    )
    summary["audit_event_count"] = len(result.get("audit_events", []))
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["state_store"] = _persist_run_summary_best_effort(
        summary,
        run_id=result.get("run_id"),
        bundle=result.get("bundle"),
        findings=result.get("findings", []),
        artifacts=result["artifacts"],
        audit_events=result.get("audit_events", []),
    )
    summary["pointer_metadata"] = update_run_pointers(summary, summary_path)
    summary["latest_pointer"] = summary["pointer_metadata"]["latest"]
    persisted_run_id = summary["state_store"].get("run_id") or result.get("run_id")
    summary["neo4j"] = sync_knowledge_graph(
        run_id=str(persisted_run_id) if persisted_run_id else None,
        tenant_slug=CONFIG.tenant_slug,
        knowledge_graph_path=result.get("artifacts", {}).get("knowledge_graph"),
        authoritative_status=summary.get("state_store"),
    )
    summary["qdrant"] = sync_findings_vector_store(
        run_id=str(persisted_run_id) if persisted_run_id else None,
        tenant_slug=CONFIG.tenant_slug,
        findings=result.get("findings", []),
        knowledge_graph_path=result.get("artifacts", {}).get("knowledge_graph"),
    )
    attach_local_review_checkpoint(summary, result)
    summary["pointer_metadata"] = update_run_pointers(summary, summary_path)
    summary["latest_pointer"] = summary["pointer_metadata"]["latest"]
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["twin_kpi_refresh"] = _refresh_twin_kpis_best_effort(summary)
    return summary, result


def _refresh_twin_kpis_best_effort(summary: dict[str, Any]) -> dict[str, Any]:
    """Best-effort twin KPI refresh from this run's summary.

    Mirrors the Neo4j/Qdrant sync pattern above: a failure here must never
    fail the run itself, since it is a downstream twin-dashboard concern,
    not part of the governed finance deliverable. Every access -- including
    reading the feature flag -- stays inside the guard for that reason.
    """
    try:
        if not getattr(CONFIG, "twins_enabled", False):
            return {"status": "skipped", "reason": "twins_enabled is False."}

        from .twins.kpi_ingest import refresh_kpis_from_run
        from .twins.store import build_app_repositories

        repositories = build_app_repositories()
        updated = refresh_kpis_from_run(repository=repositories.kpis, summary=summary)
        return {"status": "ok", "updated_node_ids": sorted(updated.keys())}
    except Exception as exc:  # pragma: no cover - defensive guard, mirrors neo4j/qdrant sync
        return {"status": "failed", "reason": str(exc)}


def attach_local_review_checkpoint(
    summary: dict[str, Any], result: dict[str, Any]
) -> None:
    """Keep no-database governed runs reviewable through the API."""
    if not summary.get("run_id"):
        return
    if not summary.get("requires_human_review"):
        return
    if str(summary.get("current_stage") or "").lower() != "awaiting_review":
        summary.pop("local_review_checkpoint", None)
        return
    checkpoint_record = result.get("last_checkpoint")
    if isinstance(checkpoint_record, dict) and checkpoint_record.get("checkpoint_id"):
        summary.pop("local_review_checkpoint", None)
        return
    checkpoint_id = f"local-checkpoint:{summary['run_id']}:awaiting_review"
    summary["local_review_checkpoint"] = {
        "checkpoint_id": checkpoint_id,
        "run_id": summary["run_id"],
        "stage": "awaiting_review",
        "status": "awaiting_review",
        "state_json": checkpoint_state(result),
        "summary_json": {
            key: value
            for key, value in summary.items()
            if key not in {"local_review_checkpoint", "pointer_metadata", "latest_pointer"}
        },
        "persistence": "local",
    }


def run_strategyos_workflow(
    dataset: Path | None = None,
    source_pack_id: str | None = None,
    run_dir: Path = DEFAULT_RUN_DIR,
    skip_prepare: bool = False,
    sync_artifacts: bool | None = None,
    local_only_fallback: bool = False,
    require_human_review: bool | None = None,
    allow_partial_source_pack: bool = False,
) -> dict:
    summary, _ = _execute_strategyos_workflow(
        dataset=dataset,
        source_pack_id=source_pack_id,
        run_dir=run_dir,
        skip_prepare=skip_prepare,
        sync_artifacts=sync_artifacts,
        local_only_fallback=local_only_fallback,
        require_human_review=require_human_review,
        allow_partial_source_pack=allow_partial_source_pack,
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run StrategyOS MVP POC workflow.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Dataset root. Defaults to sanitized analysis input pack.",
    )
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument(
        "--skip-prepare",
        action="store_true",
        help="Use existing dataset path without preparing input/evaluation folders.",
    )
    parser.add_argument(
        "--sync-artifacts",
        action="store_true",
        help="Upload run artifacts to the configured S3-compatible object store.",
    )
    parser.add_argument(
        "--local-only-fallback",
        action="store_true",
        help="Use the deterministic local workflow instead of the LangGraph Postgres runtime.",
    )
    args = parser.parse_args()

    summary = run_strategyos_workflow(
        dataset=args.dataset,
        run_dir=args.run_dir,
        skip_prepare=args.skip_prepare,
        sync_artifacts=args.sync_artifacts or None,
        local_only_fallback=args.local_only_fallback,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
