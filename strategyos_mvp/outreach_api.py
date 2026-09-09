"""Authenticated API for the connector-free outreach demonstration."""
from typing import Any

from fastapi import APIRouter, HTTPException

from .auth import require_role
from . import outreach

router = APIRouter(prefix="/api/outreach", tags=["Outreach"])
READ_ROLES = ("operator", "reviewer", "executive", "tenant_admin", "system")


@router.get("/synthetic")
def synthetic_catalog(principal: dict[str, Any] = require_role(*READ_ROLES)):
    try:
        return outreach.build_catalog(requests=outreach.list_data_requests(principal))
    except outreach.OutreachUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/requests", status_code=201)
def create_data_request(
    request: outreach.DataRequestCreate,
    principal: dict[str, Any] = require_role(*READ_ROLES),
):
    try:
        return outreach.create_data_request(principal, request)
    except outreach.OutreachUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/synthetic/threads/{thread_id}")
def synthetic_thread(thread_id: str, _: dict[str, Any] = require_role(*READ_ROLES)):
    try:
        return outreach.thread_detail(thread_id)
    except KeyError as exc:
        raise HTTPException(404, "Synthetic outreach thread was not found.") from exc


@router.get("/synthetic/knowledge/{entry_id}")
def synthetic_knowledge(entry_id: str, _: dict[str, Any] = require_role(*READ_ROLES)):
    try:
        return outreach.knowledge_detail(entry_id)
    except KeyError as exc:
        raise HTTPException(404, "Synthetic knowledge projection was not found.") from exc
