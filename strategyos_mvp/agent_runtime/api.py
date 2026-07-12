"""FastAPI router for the agents layer (design doc section 11).

Mounted at /api/v1 in strategyos_mvp/api.py following the twins_router
precedent (strategyos_mvp/twins/api.py: APIRouter(prefix=...), included via
app.include_router()). PR 3 ships conversations only; tasks/handoffs/
approvals read routes are additive in PR 4-5.

The whole router is gated behind CONFIG.agent_conversations_enabled
(feature flag STRATEGYOS_AGENT_CONVERSATIONS_ENABLED, default off) so it
can be mounted with zero behavior change until explicitly turned on --
matches the design doc's PR3 instruction: "Feature flag:
STRATEGYOS_AGENT_CONVERSATIONS_ENABLED."
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from ..auth import require_role
from ..config import CONFIG
from ..platform_foundation import principal_has_any_role
from . import repository
from .coordinator import process_conversation_message
from .errors import AgentDomainError

router = APIRouter(prefix="/api/v1", tags=["agent-runtime"])
logger = logging.getLogger(__name__)

# Every authenticated role may hold a Hermes conversation; investigation
# delegation is further gated per-agent by registry AgentDefinition.allowed_roles
# (design doc section 5.1) inside coordinator.py, not here.
CONVERSATION_ROLES = ("executive", "finance", "reviewer", "operator", "bu", "tenant_admin", "system")


class CreateConversationRequest(BaseModel):
    persona: str | None = None
    run_id: str | None = None
    finding_id: str | None = None
    classification: str = "restricted"


class PostMessageRequest(BaseModel):
    body: str
    scope: dict[str, Any] | None = None
    persona: str | None = None


def _require_feature_enabled() -> None:
    if not CONFIG.agent_conversations_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The agent conversations API is not enabled for this deployment.",
        )


def _resolve_tenant_id(principal: dict[str, Any]) -> str:
    tenant_slug = str(principal.get("tenant_id") or CONFIG.tenant_slug)
    try:
        return repository.resolve_tenant_id(tenant_slug)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def _require_record(record: dict[str, Any] | None, *, missing_detail: str) -> dict[str, Any]:
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=missing_detail)
    if isinstance(record, dict) and record.get("status") == "skipped":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(record.get("reason") or "State store is unavailable."),
        )
    return record


@router.post("/agent-conversations")
def create_conversation(
    body: CreateConversationRequest,
    principal: dict[str, Any] = require_role(*CONVERSATION_ROLES),
) -> dict[str, Any]:
    _require_feature_enabled()
    tenant_id = _resolve_tenant_id(principal)
    conversation = repository.create_conversation(
        tenant_id,
        created_by_subject=str(principal.get("subject") or "unknown"),
        persona=body.persona,
        run_id=body.run_id,
        finding_id=body.finding_id,
        classification=body.classification,
    )
    return _require_record(conversation, missing_detail="Could not create conversation.")


@router.get("/agent-conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    principal: dict[str, Any] = require_role(*CONVERSATION_ROLES),
) -> dict[str, Any]:
    _require_feature_enabled()
    tenant_id = _resolve_tenant_id(principal)
    conversation = repository.get_conversation(tenant_id, conversation_id)
    return _require_record(conversation, missing_detail="Conversation not found.")


@router.get("/agent-conversations/{conversation_id}/messages")
def list_conversation_messages(
    conversation_id: str,
    after_sequence: int = 0,
    principal: dict[str, Any] = require_role(*CONVERSATION_ROLES),
) -> dict[str, Any]:
    _require_feature_enabled()
    tenant_id = _resolve_tenant_id(principal)
    # 404 on a missing conversation rather than silently returning [] --
    # list_messages() returns [] both when the conversation doesn't exist
    # and when it's merely empty, so check existence explicitly first.
    conversation = repository.get_conversation(tenant_id, conversation_id)
    _require_record(conversation, missing_detail="Conversation not found.")
    messages = repository.list_messages(tenant_id, conversation_id, after_sequence=after_sequence)
    return {"conversation_id": conversation_id, "messages": messages}


@router.post("/agent-conversations/{conversation_id}/messages")
def post_conversation_message(
    conversation_id: str,
    body: PostMessageRequest,
    principal: dict[str, Any] = require_role(*CONVERSATION_ROLES),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """Persists the user message, routes through Hermes's answer/delegate/
    clarify/refuse classification, and returns both the user and Hermes
    messages plus any created task. Requires Idempotency-Key so a retried
    request does not create a duplicate delegated task (design doc section
    11: "Message creation requires Idempotency-Key.")."""
    _require_feature_enabled()
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required.",
        )
    tenant_id = _resolve_tenant_id(principal)
    conversation = repository.get_conversation(tenant_id, conversation_id)
    _require_record(conversation, missing_detail="Conversation not found.")

    try:
        result = process_conversation_message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            principal_subject=str(principal.get("subject") or "unknown"),
            principal_role=str(principal.get("role") or "anonymous"),
            question=body.body,
            scope=body.scope,
            idempotency_key=f"{tenant_id}:{conversation_id}:{idempotency_key}",
            persona=body.persona,
        )
    except AgentDomainError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail_public) from exc
    return result


@router.post("/agent-conversations/{conversation_id}/archive")
def archive_conversation(
    conversation_id: str,
    principal: dict[str, Any] = require_role(*CONVERSATION_ROLES),
) -> dict[str, Any]:
    _require_feature_enabled()
    tenant_id = _resolve_tenant_id(principal)
    conversation = repository.get_conversation(tenant_id, conversation_id)
    _require_record(conversation, missing_detail="Conversation not found.")
    updated = repository.archive_conversation(tenant_id, conversation_id)
    return _require_record(updated, missing_detail="Conversation not found.")


@router.get("/agent-tasks/{task_id}")
def get_task(
    task_id: str,
    principal: dict[str, Any] = require_role(*CONVERSATION_ROLES),
) -> dict[str, Any]:
    """Minimal read route so a conversation's referenced task_id is
    inspectable from PR3 onward; cancel/input/handoff routes are PR4-5
    territory once real handoff execution exists."""
    _require_feature_enabled()
    tenant_id = _resolve_tenant_id(principal)
    task = repository.get_task(tenant_id, task_id)
    return _require_record(task, missing_detail="Task not found.")
