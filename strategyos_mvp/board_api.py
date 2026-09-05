"""Governed board closure and immutable read endpoints."""
from pathlib import Path
import base64
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .auth import require_role
from . import board_memory

router = APIRouter()


class CloseRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=160)


def _read(tenant: str, meeting: str):
    try:
        snapshot = board_memory.read_meeting(tenant, meeting)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    if snapshot is None:
        raise HTTPException(404, "Meeting not found.")
    return snapshot


@router.post("/api/board/meetings/{meeting_id}/close")
def close(meeting_id: str, request: CloseRequest, principal: dict[str, Any] = require_role("executive")):
    from . import api
    tenant = api._principal_tenant_id(principal)
    summary = api._qa_summary_for_run(request.run_id)
    owner = (summary.get("tenant_context") or {}).get("tenant_id")
    if owner != tenant:
        raise HTTPException(404, "Approved run not found in this tenant.")
    if summary.get("approval_status") != "approved":
        raise HTTPException(409, "The run must be approved before a board meeting can close.")
    publication = api._summary_publication_payload(summary, principal_role="executive")
    if publication.get("status") not in {"published", "approved_for_release"}:
        raise HTTPException(409, "The board publication reconciliation gate has not passed.")
    portal = api._board_portal_payload(summary, principal_role="executive")
    # Capture the board-safe rendered context and bytes now. No future path is
    # dereferenced by a closed view, answer or download.
    context = {"board_portal": portal, "publication": publication,
               "approved_answers": {"What is the board summary?": str(portal.get("board_summary") or "No approved summary available.")}}
    finance = summary.get("finance_kpi") or {}
    context["finance_kpi"] = finance
    context["plan_health"] = (summary.get("strategy_enrichment") or {}).get("plan_health") or {}
    period = str(finance.get("reporting_period_key") or "the approved period")
    for key, label in (("revenue_actual", "revenue"), ("ebitda_actual", "EBITDA"), ("cash_balance", "cash balance")):
        value = (finance.get("components") or {}).get(key)
        if value is not None:
            answer = f"For {period}, the approved snapshot records {label} of SAR {value}."
            for prompt in (f"What is {label}?", f"What was {label}?", f"What was group {label}?"):
                context["approved_answers"][prompt] = answer
    for commitment in context["plan_health"].get("commitments", []):
        if commitment.get("actual") is not None:
            context["approved_answers"][f"What was {commitment['name']}?"] = f"The approved snapshot records {commitment['name']} at {commitment['actual']} {commitment['unit']}, against checkpoint {commitment['checkpoint']} {commitment['unit']}. Measurement status: {commitment['measurement_status']}."
    files = {"approved-board-context.json": board_memory.canonical(context).encode()}
    root = Path(str(summary.get("run_dir") or "")).resolve()
    if not root.is_relative_to(api.CONFIG.output_root.resolve()):
        raise HTTPException(409, "The approved run is outside the governed output directory.")
    for report in api._summary_report_contracts(summary).get("reports", []):
        if report.get("restricted") or not report.get("path"):
            continue
        path = Path(report["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(409, "An approved document is unavailable; closure was not saved.")
        files[str(report["artifact_key"]) + path.suffix] = path.read_bytes()
    try:
        return board_memory.close_meeting(tenant, meeting_id, run_id=request.run_id,
            actor=str(principal.get("subject")), approved_context=context, files=files,
            authority=api.get_authority_matrix(tenant))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/api/board/meetings/{meeting_id}")
def read(meeting_id: str, principal: dict[str, Any] = require_role("executive")):
    from .api import _principal_tenant_id
    snapshot = _read(_principal_tenant_id(principal), meeting_id)
    packet = snapshot["packet"]
    return {**snapshot, "packet": {**packet, "files": {name: {"sha256": info["sha256"]}
            for name, info in packet["files"].items()}}}


@router.get("/api/board/meetings/{meeting_id}/files/{name}")
def download(meeting_id: str, name: str, principal: dict[str, Any] = require_role("executive")):
    from .api import _principal_tenant_id
    snapshot = _read(_principal_tenant_id(principal), meeting_id)
    item = snapshot["packet"]["files"].get(name)
    if item is None:
        raise HTTPException(404, "Document not found in this snapshot.")
    return Response(base64.b64decode(item["base64"]), media_type="application/octet-stream",
                    headers={"ETag": item["sha256"], "Cache-Control": "private, no-store"})



@router.get("/api/board/meetings")
def meetings(principal: dict[str, Any] = require_role("executive")):
    from . import state_store
    handle, failure = state_store.database_connection()
    if failure or handle is None:
        raise HTTPException(503, "Board memory requires the durable database.")
    with handle as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('strategyos_board_snapshots')")
            if cur.fetchone()[0] is None:
                return {"meetings": []}
            cur.execute("SELECT meeting_id,closed_at,digest FROM strategyos_board_snapshots WHERE tenant_key=%s ORDER BY closed_at DESC LIMIT 100", (principal["tenant_id"],))
            rows = state_store.fetchall_dicts(cur)
    return {"meetings": rows}


class BoardQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@router.post("/api/board/meetings/{meeting_id}/questions")
def question(meeting_id: str, request: BoardQuestion, principal: dict[str, Any] = require_role("executive")):
    return board_memory.answer_from_snapshot(_read(principal["tenant_id"], meeting_id), request.question)
