from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI
    from pydantic import BaseModel
except Exception as exc:  # pragma: no cover - optional cloud dependency
    raise RuntimeError("FastAPI and pydantic are required to run the StrategyOS API.") from exc

from .config import CONFIG
from .prepare_inputs import prepare_agent_input
from .run_poc import run_strategyos_workflow
from .storage import object_store_status


class RunRequest(BaseModel):
    dataset: str | None = None
    run_dir: str | None = None
    skip_prepare: bool = False
    sync_artifacts: bool | None = None


app = FastAPI(title="StrategyOS MVP API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "workspace_root": str(CONFIG.workspace_root),
        "output_root": str(CONFIG.output_root),
        "object_store": object_store_status(),
        "database_configured": bool(CONFIG.database_url),
        "redis_configured": bool(CONFIG.redis_url),
        "neo4j_configured": bool(CONFIG.neo4j_uri),
    }


@app.post("/runs")
def create_run(request: RunRequest) -> dict[str, Any]:
    dataset = Path(request.dataset).expanduser().resolve() if request.dataset else None
    run_dir = Path(request.run_dir).expanduser().resolve() if request.run_dir else CONFIG.default_run_dir
    summary = run_strategyos_workflow(
        dataset=dataset,
        run_dir=run_dir,
        skip_prepare=request.skip_prepare,
        sync_artifacts=request.sync_artifacts,
    )
    return summary


@app.get("/runs/latest")
def latest_run() -> dict[str, Any]:
    summary_path = CONFIG.default_run_dir / "run_summary.json"
    if not summary_path.exists():
        return {"status": "missing", "run_dir": str(CONFIG.default_run_dir)}
    return json.loads(summary_path.read_text(encoding="utf-8"))


@app.post("/inputs/prepare")
def prepare_inputs() -> dict[str, str]:
    agent_input, evaluation = prepare_agent_input()
    return {"agent_input": str(agent_input), "evaluation": str(evaluation)}
