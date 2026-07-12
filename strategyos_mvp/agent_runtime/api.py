"""FastAPI router for the agents layer (design doc section 11).

Mounted at /api/v1 in strategyos_mvp/api.py following the twins_router
precedent (strategyos_mvp/twins/api.py: APIRouter(prefix=...), included via
app.include_router()).

Conversation routes (PR3) are gated behind CONFIG.agent_conversations_enabled
(STRATEGYOS_AGENT_CONVERSATIONS_ENABLED, default off). Network/catalogue/
approval/event-stream routes (PR5) are gated behind
CONFIG.agent_live_ui_enabled (STRATEGYOS_AGENT_LIVE_UI_ENABLED, default
off) -- matching the design doc's per-PR feature flags so each vertical
slice can be turned on independently.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..auth import require_role
from ..config import CONFIG
from ..platform_foundation import principal_has_any_role
from . import projections, repository, streaming
from .coordinator import process_conversation_message
from .errors import AgentDomainError
from .models import ApprovalStatus
from .registry import AGENT_DEFINITIONS

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


def _require_live_ui_enabled() -> None:
    if not CONFIG.agent_live_ui_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The agent network API is not enabled for this deployment.",
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
    inspectable from PR3 onward; cancel/input routes remain out of scope
    until a real cancellation/input-resumption workflow exists."""
    _require_feature_enabled()
    tenant_id = _resolve_tenant_id(principal)
    task = repository.get_task(tenant_id, task_id)
    return _require_record(task, missing_detail="Task not found.")


# ---------------------------------------------------------------------------
# PR5: catalogue, live network, approvals, event stream
# ---------------------------------------------------------------------------


@router.get("/agents")
def list_agents(
    principal: dict[str, Any] = require_role(*CONVERSATION_ROLES),
) -> dict[str, Any]:
    """Permitted installed agents and capabilities (design doc section 11).
    Filters the shipped catalogue down to what this principal's role may
    use, per each AgentDefinition's allowed_roles."""
    _require_live_ui_enabled()
    role = str(principal.get("role") or "anonymous")
    agents = [
        {
            "agent_key": d.agent_key,
            "display_name": d.display_name,
            "purpose": d.purpose,
            "version": d.version,
            "permitted": role in d.allowed_roles or role in {"system", "tenant_admin"},
        }
        for d in AGENT_DEFINITIONS
    ]
    return {"agents": agents}


@router.get("/agent-network")
def agent_network(
    principal: dict[str, Any] = require_role(*CONVERSATION_ROLES),
) -> dict[str, Any]:
    """Real task/handoff/approval-backed module network (design doc
    section 12: "Replace agent_modules.running as the runtime authority
    with GET /api/v1/agent-network"). Also the polling fallback for
    clients that can't hold an SSE connection."""
    _require_live_ui_enabled()
    tenant_id = _resolve_tenant_id(principal)
    payload = projections.agent_network_payload(tenant_id)
    if payload.get("status") == "skipped":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=payload.get("reason") or "unavailable")
    return payload


APPROVAL_DECISION_ROLES = ("reviewer", "operator")


class ApprovalDecisionRequest(BaseModel):
    decision: str  # "approved" | "rejected"
    comment: str | None = None


@router.get("/agent-approvals")
def list_agent_approvals(
    status_filter: str = "pending",
    principal: dict[str, Any] = require_role(*APPROVAL_DECISION_ROLES),
) -> dict[str, Any]:
    _require_live_ui_enabled()
    tenant_id = _resolve_tenant_id(principal)
    approvals = repository.list_approval_requests(tenant_id, status=status_filter)
    return {"approvals": approvals}


@router.post("/agent-approvals/{approval_id}/decision")
def decide_agent_approval(
    approval_id: str,
    body: ApprovalDecisionRequest,
    principal: dict[str, Any] = require_role(*APPROVAL_DECISION_ROLES),
) -> dict[str, Any]:
    """No model response can directly mark an approval as granted (design
    doc section 8.4) -- decided_by_subject/role are resolved from the
    authenticated principal here, never from the request body."""
    _require_live_ui_enabled()
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="decision must be 'approved' or 'rejected'.")
    tenant_id = _resolve_tenant_id(principal)
    target_status = ApprovalStatus.APPROVED if body.decision == "approved" else ApprovalStatus.REJECTED
    try:
        decided = repository.decide_approval(
            tenant_id, approval_id, target_status=target_status,
            decided_by_subject=str(principal.get("subject") or "unknown"),
            decided_by_role=str(principal.get("role") or "unknown"),
            decision_comment=body.comment,
        )
    except repository.TenantMismatch as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.") from exc
    except repository.InvalidStatusTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _require_record(decided, missing_detail="Approval not found.")


@router.get("/agent-events/stream")
def agent_events_stream(
    principal: dict[str, Any] = require_role(*CONVERSATION_ROLES),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """SSE stream of public-safe event projections (design doc section 11).
    Supports Last-Event-ID for reconnect replay. Falls back is
    GET /api/v1/agent-network for clients that cannot hold a streaming
    connection (e.g. behind a buffering proxy)."""
    _require_live_ui_enabled()
    tenant_id = _resolve_tenant_id(principal)
    return StreamingResponse(
        streaming.sse_event_stream(tenant_id, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
