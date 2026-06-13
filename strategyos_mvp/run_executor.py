from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import StrategyOSConfig
from . import state_store


class RunExecutionUnavailable(RuntimeError):
    """Raised when the configured run execution mode cannot accept work."""


SyncRunner = Callable[..., dict[str, Any]]


def build_run_request_payload(
    *,
    dataset: Path | None,
    source_pack_id: str | None,
    run_dir: Path,
    skip_prepare: bool,
    sync_artifacts: bool | None,
    allow_partial_source_pack: bool,
) -> dict[str, Any]:
    return {
        "dataset": str(dataset) if dataset is not None else None,
        "source_pack_id": source_pack_id,
        "run_dir": str(run_dir),
        "skip_prepare": bool(skip_prepare),
        "sync_artifacts": sync_artifacts,
        "allow_partial_source_pack": bool(allow_partial_source_pack),
    }


def submit_run(
    *,
    dataset: Path | None,
    source_pack_id: str | None,
    run_dir: Path,
    skip_prepare: bool,
    sync_artifacts: bool | None,
    allow_partial_source_pack: bool,
    submitted_by: str | None,
    config: StrategyOSConfig,
    sync_runner: SyncRunner,
) -> dict[str, Any]:
    if config.run_execution_mode == "sync":
        return sync_runner(
            dataset=dataset,
            source_pack_id=source_pack_id,
            run_dir=run_dir,
            skip_prepare=skip_prepare,
            sync_artifacts=sync_artifacts,
            allow_partial_source_pack=allow_partial_source_pack,
        )
    if config.run_execution_mode == "hatchet":
        return submit_hatchet_run(
            dataset=dataset,
            source_pack_id=source_pack_id,
            run_dir=run_dir,
            skip_prepare=skip_prepare,
            sync_artifacts=sync_artifacts,
            allow_partial_source_pack=allow_partial_source_pack,
            submitted_by=submitted_by,
        )
    raise RunExecutionUnavailable(
        f"Unsupported run execution mode '{config.run_execution_mode}'."
    )


def submit_hatchet_run(
    *,
    dataset: Path | None,
    source_pack_id: str | None,
    run_dir: Path,
    skip_prepare: bool,
    sync_artifacts: bool | None,
    allow_partial_source_pack: bool,
    submitted_by: str | None,
) -> dict[str, Any]:
    request_payload = build_run_request_payload(
        dataset=dataset,
        source_pack_id=source_pack_id,
        run_dir=run_dir,
        skip_prepare=skip_prepare,
        sync_artifacts=sync_artifacts,
        allow_partial_source_pack=allow_partial_source_pack,
    )
    job = state_store.create_run_job(
        request_payload,
        submitted_by=submitted_by,
        execution_mode="hatchet",
        metadata={"component": "strategyos-api"},
    )
    if job.get("status") in {"skipped", "failed"} and not job.get("job_id"):
        raise RunExecutionUnavailable(
            "Hatchet mode requires a configured Postgres job store: "
            f"{job.get('reason') or job.get('status')}"
        )

    try:
        from .hatchet_runtime import enqueue_strategyos_run

        hatchet_ref = enqueue_strategyos_run({"job_id": job["job_id"], **request_payload})
    except Exception as exc:
        state_store.update_run_job(
            str(job["job_id"]),
            status="failed",
            failure_reason=str(exc),
            metadata={"enqueue_error": str(exc)},
        )
        raise RunExecutionUnavailable(f"Unable to enqueue StrategyOS Hatchet run: {exc}") from exc

    hatchet_run_id = str(hatchet_ref.get("hatchet_run_id") or "")
    updated = state_store.update_run_job(
        str(job["job_id"]),
        status="queued",
        hatchet_run_id=hatchet_run_id or None,
        metadata={"hatchet_ref": hatchet_ref},
    )
    return {
        "status": "queued",
        "execution_mode": "hatchet",
        "job_id": updated.get("job_id") or job.get("job_id"),
        "hatchet_run_id": updated.get("hatchet_run_id") or hatchet_run_id or None,
        "strategyos_run_id": updated.get("strategyos_run_id"),
        "request_hash": updated.get("request_hash") or job.get("request_hash"),
        "detail": "StrategyOS run queued for Hatchet worker execution.",
    }
