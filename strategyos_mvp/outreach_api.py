"""Authenticated API for the connector-free outreach demonstration."""
from typing import Any

from fastapi import APIRouter, HTTPException

from .auth import require_role
from . import outreach

router = APIRouter(prefix="/api/outreach", tags=["Outreach"])
READ_ROLES = ("operator", "reviewer", "executive", "tenant_admin", "system")


@router.get("/synthetic")
def synthetic_catalog(_: dict[str, Any] = require_role(*READ_ROLES)):
    return outreach.build_catalog()


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
