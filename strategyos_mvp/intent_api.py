"""Read-only Intent Vault over the selected governed source pack."""
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .auth import require_role
from .strategy_compiler import compile_strategy, evaluate_strategy

router = APIRouter()


def _current(principal):
    from . import api
    summary = api._qa_summary_for_run(None)
    if (summary.get("tenant_context") or {}).get("tenant_id") != api._principal_tenant_id(principal):
        raise HTTPException(404, "No governed plan is selected for this tenant.")
    root = Path(str(summary.get("dataset") or summary.get("dataset_root") or "")).resolve()
    path = root / "20_Board_KPIs" / "Intent_Plan.json"
    if not path.is_file():
        raise HTTPException(404, "No Intent plan has been supplied in the selected source pack.")
    plan = json.loads(path.read_text())
    definitions_path = path.with_name("Metric_Definitions.json")
    definitions = json.loads(definitions_path.read_text()) if definitions_path.exists() else {}
    bindings = {f"{key}.actual" for key in definitions.get("metrics", {})}
    compiled = compile_strategy(plan, available_bindings=bindings)
    return root, summary, compiled


@router.get("/api/intent")
def read(principal: dict[str, Any] = require_role("executive")):
    root, summary, compiled = _current(principal)
    for commitment in compiled["commitments"]:
        source = commitment["source"]
        path = (root / source["path"]).resolve()
        source["resolved"] = path.is_relative_to(root) and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]
        source["route"] = f"/api/intent/commitments/{commitment['id']}/source"
    health = (summary.get("strategy_enrichment") or {}).get("plan_health") or {}
    measurements = {str(item.get("kpi_id")) + ".actual": item.get("actual") for item in health.get("commitments", [])}
    return {**compiled, "evaluation": evaluate_strategy(compiled, measurements), "run_id": summary.get("run_id"),
            "amendment_status": "supplied" if compiled["amendments"] else "No amendment register supplied. No changes have been inferred."}


@router.get("/api/intent/commitments/{commitment_id}/source")
def source(commitment_id: str, principal: dict[str, Any] = require_role("executive")):
    root, _, compiled = _current(principal)
    item = next((item for item in compiled["commitments"] if item["id"] == commitment_id), None)
    if item is None:
        raise HTTPException(404, "Commitment not found.")
    path = (root / item["source"]["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["source"]["sha256"]:
        raise HTTPException(409, "The source is missing or changed; recompile and review the plan mapping.")
    return FileResponse(path, filename=path.name, headers={"Cache-Control": "private, no-store"})

