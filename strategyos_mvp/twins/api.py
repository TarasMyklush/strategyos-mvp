"""FastAPI router for twin dashboard data endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from strategyos_mvp.auth import authenticate_request
from strategyos_mvp.platform_foundation import principal_has_any_role
from strategyos_mvp.twins import memory, persona, resolution, runtime as twin_runtime
from strategyos_mvp.twins.store import TwinRepositories, build_app_repositories
from strategyos_mvp.twins.strategyos_data import (
    build_surface_payload,
    compose_investigation_payload,
)

router = APIRouter(prefix="/twin/api", tags=["twins"])

EXECUTIVE_TWIN_ROLES = ("executive", "tenant_admin", "system")
FINANCE_TWIN_ROLES = ("operator", "reviewer", "tenant_admin", "system")
GM_TWIN_ROLES = ("bu", "operator", "tenant_operator", "tenant_admin", "system")
TWIN_SURFACE_ROLES: dict[str, tuple[str, ...]] = {
    "ceo": EXECUTIVE_TWIN_ROLES,
    "cfo": FINANCE_TWIN_ROLES,
    "group_manager": GM_TWIN_ROLES,
}


class TwinDecisionRequest(BaseModel):
    item_id: str
    title: str | None = None
    rationale: str | None = None


class TwinRoutingRequest(BaseModel):
    item_id: str
    title: str | None = None
    target_role: str | None = None
    reason: str | None = None


def _canonical_role(role: str) -> str:
    twin_persona = persona.lookup_persona(role)
    if twin_persona is None:
        raise HTTPException(status_code=404, detail=f"Unknown twin role: {role}")
    return twin_persona.role


def _allowed_roles_for_twin(role: str) -> tuple[str, ...]:
    return TWIN_SURFACE_ROLES.get(_canonical_role(role), ())


def _authorize_twin_access(
    role: str,
    principal: dict[str, Any],
    *,
    action: str,
) -> dict[str, Any]:
    allowed_roles = _allowed_roles_for_twin(role)
    if principal.get("auth_disabled"):
        fallback_role = allowed_roles[0] if allowed_roles else "anonymous"
        return {**principal, "role": fallback_role}
    principal_role = str(principal.get("role") or "")
    if not principal_has_any_role(principal_role, *allowed_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This identity is not permitted to {action} for the {role} twin.",
        )
    return principal


def require_twin_dashboard_access(role: str):
    def dependency(
        principal: dict[str, Any] = Depends(authenticate_request),
    ) -> dict[str, Any]:
        return _authorize_twin_access(role, principal, action="access this dashboard")

    return Depends(dependency)


def _get_repositories() -> TwinRepositories:
    repositories = build_app_repositories()
    repositories.kpis.ensure_seeded(resolution.KPI_TREE)
    for seed_role in ("ceo", "cfo", "group_manager"):
        repositories.governance.seed_demo_history(seed_role)
    return repositories


def _load_or_create_state(role: str, repositories: TwinRepositories) -> memory.TwinState:
    canonical_role = _canonical_role(role)
    payload = repositories.states.load(canonical_role)
    if payload is None:
        state = memory.create_twin_state(canonical_role)
        repositories.states.save(canonical_role, state)
        return state

    return memory.TwinState(
        twin_id=str(payload.get("twin_id", "")),
        role=str(payload.get("role", canonical_role)),
        active_investigations=dict(payload.get("active_investigations", {})),
        pending_requests=dict(payload.get("pending_requests", {})),
        conversation_history=list(payload.get("conversation_history", [])),
        working_memory=dict(payload.get("working_memory", {})),
        last_wake_at=payload.get("last_wake_at"),
        cycle_count=int(payload.get("cycle_count", 0)),
    )


def _governance_payload(role: str, repositories: TwinRepositories) -> dict[str, Any]:
    canonical_role = _canonical_role(role)
    approvals = repositories.governance.list_decisions(canonical_role, limit=20)
    routing = repositories.governance.list_routing_events(canonical_role, limit=20)
    history = repositories.governance.history(canonical_role, limit=20)
    return {
        "approval_count": len(approvals),
        "routing_event_count": len(routing),
        "approval_trail": approvals,
        "routing_history": routing,
        "history": history,
    }


def _fallback_kpis(role: str, twin_persona: persona.TwinPersona, repositories: TwinRepositories) -> dict[str, Any]:
    eng = resolution.KPIResolutionEngine(repository=repositories.kpis)
    results: dict[str, Any] = {}
    for kpi_id in twin_persona.kpis_owned:
        gaps = eng.detect_gaps(kpi_id)
        node = eng.get_node(kpi_id) or {}
        results[kpi_id] = {
            "label": node.get("label", kpi_id),
            "value": node.get("value"),
            "status": node.get("status", "unknown"),
            "gaps": gaps,
            "health": "healthy" if not gaps else ("warning" if len(gaps) == 1 else "critical"),
            "source": "twin_repository",
        }
    return results


def _actor_identity(principal: dict[str, Any]) -> tuple[str, str]:
    return (
        str(principal.get("role") or "anonymous"),
        str(principal.get("subject") or "anonymous"),
    )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _default_escalation_target(role: str) -> str:
    twin_persona = persona.lookup_persona(role)
    if twin_persona is None:
        raise HTTPException(status_code=404, detail=f"Unknown twin role: {role}")
    return twin_persona.escalation_path[0] if twin_persona.escalation_path else "human"


@router.get("/status/{role}")
def twin_status(
    role: str,
    principal: dict[str, Any] = Depends(authenticate_request),
) -> dict[str, Any]:
    """Get twin status: active/sleeping, cycle count, last wake, investigations."""
    principal = _authorize_twin_access(role, principal, action="view status")
    canonical_role = _canonical_role(role)
    twin_persona = persona.lookup_persona(role)
    assert twin_persona is not None

    repositories = _get_repositories()
    state = _load_or_create_state(canonical_role, repositories)
    investigations = repositories.investigations.list(canonical_role)
    strategyos_surface = build_surface_payload(canonical_role)
    return {
        "role": role,
        "canonical_role": canonical_role,
        "display_name": twin_persona.display_name,
        "status": "active",
        "cycle_count": state.cycle_count,
        "last_wake": state.last_wake_at,
        "active_investigations": [item.get("id") for item in investigations],
        "active_investigation_details": investigations[-20:],
        "pending_requests": len(state.pending_requests),
        "governance": _governance_payload(canonical_role, repositories),
        "strategyos": strategyos_surface,
        "viewer": {
            "role": str(principal.get("role") or "anonymous"),
            "subject": str(principal.get("subject") or "anonymous"),
        },
    }


@router.get("/kpis/{role}")
def twin_kpis(
    role: str,
    principal: dict[str, Any] = Depends(authenticate_request),
) -> dict[str, Any]:
    """Get KPI health for a role — returns owned KPIs with values, gaps, status."""
    _authorize_twin_access(role, principal, action="view KPIs")
    canonical_role = _canonical_role(role)
    twin_persona = persona.lookup_persona(role)
    assert twin_persona is not None

    repositories = _get_repositories()
    surface = build_surface_payload(canonical_role, _fallback_kpis(canonical_role, twin_persona, repositories))

    return {
        "role": role,
        "canonical_role": canonical_role,
        "display_name": twin_persona.display_name,
        "data_source": surface["data_source"],
        "bounded_fallback": surface["bounded_fallback"],
        "kpis": surface["kpis"],
        "run_context": surface["run_context"],
        "board": surface["board"],
        "evidence": surface["evidence"],
        "consistency": surface["consistency"],
        "metrics": surface["metrics"],
        "publication": surface["publication"],
        "plan_health": surface["plan_health"],
    }


@router.get("/inbox/{role}")
def twin_inbox(
    role: str,
    principal: dict[str, Any] = Depends(authenticate_request),
) -> dict[str, Any]:
    """Get inbox messages for a role twin."""
    _authorize_twin_access(role, principal, action="view inbox")
    canonical_role = _canonical_role(role)
    twin_persona = persona.lookup_persona(role)
    assert twin_persona is not None

    repositories = _get_repositories()
    messages = repositories.inboxes.load(canonical_role)[:20]

    return {
        "role": role,
        "canonical_role": canonical_role,
        "display_name": twin_persona.display_name,
        "message_count": len(messages),
        "messages": [
            {
                "type": m.get("type", "unknown"),
                "subject": m.get("subject", ""),
                "from": m.get("from") or m.get("sender_role", "system"),
                "timestamp": m.get("timestamp") or m.get("created_at", ""),
                "status": m.get("status", "pending"),
                "priority": m.get("priority", "normal"),
            }
            for m in messages
        ],
    }


@router.post("/investigate/{role}")
def twin_investigate(
    role: str,
    query: str = "",
    principal: dict[str, Any] = Depends(authenticate_request),
) -> dict[str, Any]:
    """Ask a twin a question. Runs a full OODA cycle and returns findings."""
    _authorize_twin_access(role, principal, action="investigate")
    canonical_role = _canonical_role(role)
    twin_persona = persona.lookup_persona(role)
    assert twin_persona is not None

    repositories = _get_repositories()
    state = _load_or_create_state(canonical_role, repositories)
    tw = twin_runtime.TwinRuntime(twin_persona, state, repositories=repositories)

    if query:
        tw.state.working_memory["last_query"] = query
        query_id = f"query-{tw.state.cycle_count + 1}"
        memory.add_investigation(tw.state, query_id, {"query": query})
        repositories.investigations.save(canonical_role, tw.state.active_investigations[query_id])
        repositories.states.save(canonical_role, tw.state)

    summary = tw.run_once()
    strategyos_payload = compose_investigation_payload(canonical_role, query)

    if query:
        persisted = repositories.investigations.load(canonical_role, query_id) or {"id": query_id, "query": query}
        persisted.update({
            "id": query_id,
            "query": query,
            "response": strategyos_payload["response"],
            "evidence": strategyos_payload["evidence"],
            "board": strategyos_payload["board"],
            "run_context": strategyos_payload["run_context"],
            "consistency": strategyos_payload["consistency"],
            "linked_finding_ids": strategyos_payload["linked_finding_ids"],
            "linked_run_id": strategyos_payload["run_context"].get("run_id"),
            "data_source": strategyos_payload["data_source"],
        })
        repositories.investigations.save(canonical_role, persisted)

    return {
        "role": role,
        "canonical_role": canonical_role,
        "display_name": twin_persona.display_name,
        "query": query,
        "cycle_count": summary.get("cycle", 0),
        "investigations": list(tw.state.active_investigations.keys()),
        "observations": summary.get("observations", {}),
        "issues_found": len(summary.get("issues", [])),
        "actions_taken": len(summary.get("decisions", [])),
        "summary": summary,
        "response": strategyos_payload["response"],
        "evidence": strategyos_payload["evidence"],
        "board": strategyos_payload["board"],
        "run_context": strategyos_payload["run_context"],
        "consistency": strategyos_payload["consistency"],
        "data_source": strategyos_payload["data_source"],
        "bounded_fallback": strategyos_payload["bounded_fallback"],
        "governance": _governance_payload(canonical_role, repositories),
    }


@router.get("/history/{role}")
def twin_governance_history(
    role: str,
    principal: dict[str, Any] = Depends(authenticate_request),
) -> dict[str, Any]:
    _authorize_twin_access(role, principal, action="view governance history")
    canonical_role = _canonical_role(role)
    repositories = _get_repositories()
    return {
        "role": role,
        "canonical_role": canonical_role,
        "governance": _governance_payload(canonical_role, repositories),
    }


@router.post("/approve/{role}")
def approve_twin_item(
    role: str,
    request: TwinDecisionRequest,
    principal: dict[str, Any] = Depends(authenticate_request),
) -> dict[str, Any]:
    _authorize_twin_access(role, principal, action="approve this item")
    canonical_role = _canonical_role(role)
    actor_role, actor_subject = _actor_identity(principal)
    repositories = _get_repositories()
    record = repositories.governance.save_decision({
        "event_id": f"gov-{uuid4().hex[:12]}",
        "event_type": "approval",
        "role": canonical_role,
        "item_id": request.item_id,
        "title": request.title or request.item_id,
        "status": "approved",
        "rationale": (request.rationale or "").strip(),
        "reviewer_notes": (request.rationale or "").strip(),
        "actor_role": actor_role,
        "actor_subject": actor_subject,
        "timestamp": _timestamp(),
    })
    return {
        "status": "ok",
        "record": record,
        "governance": _governance_payload(canonical_role, repositories),
    }


@router.post("/reject/{role}")
def reject_twin_item(
    role: str,
    request: TwinDecisionRequest,
    principal: dict[str, Any] = Depends(authenticate_request),
) -> dict[str, Any]:
    _authorize_twin_access(role, principal, action="reject this item")
    canonical_role = _canonical_role(role)
    actor_role, actor_subject = _actor_identity(principal)
    repositories = _get_repositories()
    record = repositories.governance.save_decision({
        "event_id": f"gov-{uuid4().hex[:12]}",
        "event_type": "rejection",
        "role": canonical_role,
        "item_id": request.item_id,
        "title": request.title or request.item_id,
        "status": "rejected",
        "rationale": (request.rationale or "").strip(),
        "reviewer_notes": (request.rationale or "").strip(),
        "actor_role": actor_role,
        "actor_subject": actor_subject,
        "timestamp": _timestamp(),
    })
    return {
        "status": "ok",
        "record": record,
        "governance": _governance_payload(canonical_role, repositories),
    }


@router.post("/redirect/{role}")
def redirect_twin_item(
    role: str,
    request: TwinRoutingRequest,
    principal: dict[str, Any] = Depends(authenticate_request),
) -> dict[str, Any]:
    _authorize_twin_access(role, principal, action="redirect this item")
    canonical_role = _canonical_role(role)
    target_role = _canonical_role(request.target_role or "")
    actor_role, actor_subject = _actor_identity(principal)
    repositories = _get_repositories()
    record = repositories.governance.save_routing_event({
        "event_id": f"route-{uuid4().hex[:12]}",
        "event_type": "redirect",
        "source_role": canonical_role,
        "target_role": target_role,
        "item_id": request.item_id,
        "title": request.title or request.item_id,
        "reason": (request.reason or "").strip(),
        "actor_role": actor_role,
        "actor_subject": actor_subject,
        "timestamp": _timestamp(),
    })
    return {
        "status": "ok",
        "record": record,
        "governance": _governance_payload(canonical_role, repositories),
    }


@router.post("/escalate/{role}")
def escalate_twin_item(
    role: str,
    request: TwinRoutingRequest,
    principal: dict[str, Any] = Depends(authenticate_request),
) -> dict[str, Any]:
    _authorize_twin_access(role, principal, action="escalate this item")
    canonical_role = _canonical_role(role)
    target_role = _canonical_role(request.target_role or _default_escalation_target(canonical_role))
    actor_role, actor_subject = _actor_identity(principal)
    repositories = _get_repositories()
    record = repositories.governance.save_routing_event({
        "event_id": f"route-{uuid4().hex[:12]}",
        "event_type": "escalation",
        "source_role": canonical_role,
        "target_role": target_role,
        "item_id": request.item_id,
        "title": request.title or request.item_id,
        "reason": (request.reason or "").strip(),
        "actor_role": actor_role,
        "actor_subject": actor_subject,
        "timestamp": _timestamp(),
    })
    return {
        "status": "ok",
        "record": record,
        "governance": _governance_payload(canonical_role, repositories),
    }
