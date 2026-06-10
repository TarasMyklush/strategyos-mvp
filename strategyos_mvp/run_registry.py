from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import CONFIG

LATEST_RUN_POINTER = "latest_run_pointer.json"
CURRENT_RUN_POINTER = "current_run_pointer.json"
TIMESTAMP_PATTERN = re.compile(r".+-\d{8}T\d{6}Z(?:-\d+)?$")


def allocate_run_dir(requested_run_dir: Path | None = None) -> Path:
    base_dir = (requested_run_dir or CONFIG.default_run_dir).expanduser().resolve()
    if _looks_timestamped(base_dir.name) and not base_dir.exists():
        return base_dir

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    candidate = base_dir.parent / f"{base_dir.name}-{timestamp}"
    suffix = 1
    while candidate.exists():
        candidate = base_dir.parent / f"{base_dir.name}-{timestamp}-{suffix:02d}"
        suffix += 1
    return candidate


def latest_run_pointer_path() -> Path:
    return CONFIG.output_root / LATEST_RUN_POINTER


def current_run_pointer_path() -> Path:
    return CONFIG.output_root / CURRENT_RUN_POINTER


def update_latest_run_pointer(summary: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    return _write_run_pointer(summary, summary_path, latest_run_pointer_path(), "latest")


def update_current_run_pointer(summary: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    return _write_run_pointer(summary, summary_path, current_run_pointer_path(), "current")


def update_run_pointers(summary: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    return {
        "latest": update_latest_run_pointer(summary, summary_path),
        "current": update_current_run_pointer(summary, summary_path),
    }


def _write_run_pointer(
    summary: dict[str, Any],
    summary_path: Path,
    pointer_path: Path,
    pointer_type: str,
) -> dict[str, Any]:
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "pointer_type": pointer_type,
        "pointer_path": str(pointer_path),
        "updated_at": datetime.now(UTC).isoformat(),
        "run_id": summary.get("run_id"),
        "run_dir": summary.get("run_dir"),
        "status": summary.get("status"),
        "current_stage": summary.get("current_stage"),
        "approval_status": summary.get("approval_status"),
        "review_state": summary.get("review_state"),
        "resume_state": summary.get("resume_state"),
        "resume_ready": summary.get("resume_ready"),
        "run_outcome": summary.get("run_outcome"),
        "deliverables_status": summary.get("deliverables_status"),
        "summary_path": str(summary_path),
    }
    pointer_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_latest_run_summary() -> dict[str, Any] | None:
    pointer_path = latest_run_pointer_path()
    if not pointer_path.exists():
        return None

    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    summary_path = Path(str(pointer.get("summary_path") or "")).expanduser().resolve()
    if not summary_path.exists():
        return {
            "status": "missing",
            "reason": "Latest run pointer exists but summary file is unavailable.",
            "latest_pointer": pointer,
        }

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["latest_pointer"] = pointer
    return summary


def _looks_timestamped(name: str) -> bool:
    return bool(TIMESTAMP_PATTERN.fullmatch(name))
