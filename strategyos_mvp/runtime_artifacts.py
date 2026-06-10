from __future__ import annotations

from pathlib import Path

AUDIT_LOG_FILENAME = "StrategyOS Ping Pong Audit Log.json"
LEGACY_AUDIT_LOG_FILENAMES = ("Ping-pong audit log.json",)


def remove_legacy_artifacts(run_dir: Path) -> None:
    for name in LEGACY_AUDIT_LOG_FILENAMES:
        legacy_path = run_dir / name
        if legacy_path.exists() and legacy_path.is_file():
            legacy_path.unlink()
