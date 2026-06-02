from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import CONFIG


def persist_run_summary(summary: dict[str, Any]) -> dict[str, Any]:
    if not CONFIG.database_url:
        return {"status": "skipped", "reason": "DATABASE_URL is not configured."}
    try:
        import psycopg
    except Exception as exc:  # pragma: no cover - optional cloud dependency
        return {"status": "skipped", "reason": f"psycopg is not installed: {exc}"}

    with psycopg.connect(CONFIG.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into strategyos_runs
                    (run_dir, dataset_root, finding_count, locked_finding_count, total_recoverable_sar, summary_json)
                values (%s, %s, %s, %s, %s, %s::jsonb)
                returning id
                """,
                (
                    summary["run_dir"],
                    summary["dataset"],
                    summary["findings"],
                    summary["locked_findings"],
                    summary["total_recoverable_sar"],
                    json.dumps(summary),
                ),
            )
            run_id = cur.fetchone()[0]
        conn.commit()
    return {"status": "persisted", "run_id": str(run_id)}


def schema_path() -> Path:
    return Path(__file__).resolve().parents[1] / "deploy" / "postgres" / "schema.sql"
