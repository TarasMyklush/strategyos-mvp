"""FastAPI router for twin dashboard data endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from strategyos_mvp.twins import memory, persona, resolution, runtime as twin_runtime
from strategyos_mvp.twins.store import TwinRepositories, build_app_repositories

router = APIRouter(prefix="/twin/api", tags=["twins"])


def _get_repositories() -> TwinRepositories:
    repositories = build_app_repositories()
    repositories.kpis.ensure_seeded(resolution.KPI_TREE)
    return repositories


def _load_or_create_state(role: str, repositories: TwinRepositories) -> memory.TwinState:
    payload = repositories.states.load(role)
    if payload is None:
        state = memory.create_twin_state(role)
        repositories.states.save(role, state)
        return state

    return memory.TwinState(
        twin_id=str(payload.get("twin_id", "")),
        role=str(payload.get("role", role)),
        active_investigations=dict(payload.get("active_investigations", {})),
        pending_requests=dict(payload.get("pending_requests", {})),
        conversation_history=list(payload.get("conversation_history", [])),
        working_memory=dict(payload.get("working_memory", {})),
        last_wake_at=payload.get("last_wake_at"),
        cycle_count=int(payload.get("cycle_count", 0)),
    )


@router.get("/status/{role}")
def twin_status(role: str) -> dict[str, Any]:
    """Get twin status: active/sleeping, cycle count, last wake, investigations."""
    p = persona.TWIN_CATALOG.get(role)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Unknown twin role: {role}")

    repositories = _get_repositories()
    state = _load_or_create_state(role, repositories)
    investigations = repositories.investigations.list(role)
    return {
        "role": role,
        "display_name": p.display_name,
        "status": "active",
        "cycle_count": state.cycle_count,
        "last_wake": state.last_wake_at,
        "active_investigations": [item.get("id") for item in investigations],
        "pending_requests": len(state.pending_requests),
    }


@router.get("/kpis/{role}")
def twin_kpis(role: str) -> dict[str, Any]:
    """Get KPI health for a role — returns owned KPIs with values, gaps, status."""
    p = persona.TWIN_CATALOG.get(role)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Unknown twin role: {role}")

    repositories = _get_repositories()
    eng = resolution.KPIResolutionEngine(repository=repositories.kpis)
    results: dict[str, Any] = {}

    for kpi_id in p.kpis_owned:
        gaps = eng.detect_gaps(kpi_id)
        node = eng.get_node(kpi_id) or {}
        results[kpi_id] = {
            "label": node.get("label", kpi_id),
            "value": node.get("value"),
            "status": node.get("status", "unknown"),
            "gaps": gaps,
            "health": "healthy" if not gaps else ("warning" if len(gaps) == 1 else "critical"),
        }

    return {"role": role, "display_name": p.display_name, "kpis": results}


@router.get("/inbox/{role}")
def twin_inbox(role: str) -> dict[str, Any]:
    """Get inbox messages for a role twin."""
    p = persona.TWIN_CATALOG.get(role)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Unknown twin role: {role}")

    repositories = _get_repositories()
    messages = repositories.inboxes.load(role)[:20]

    return {
        "role": role,
        "display_name": p.display_name,
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
def twin_investigate(role: str, query: str = "") -> dict[str, Any]:
    """Ask a twin a question. Runs a full OODA cycle and returns findings."""
    p = persona.TWIN_CATALOG.get(role)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Unknown twin role: {role}")

    repositories = _get_repositories()
    state = _load_or_create_state(role, repositories)
    tw = twin_runtime.TwinRuntime(p, state, repositories=repositories)

    # If query provided, add to working memory
    if query:
        tw.state.working_memory["last_query"] = query
        query_id = f"query-{tw.state.cycle_count + 1}"
        memory.add_investigation(tw.state, query_id, {"query": query})
        repositories.investigations.save(role, tw.state.active_investigations[query_id])
        repositories.states.save(role, tw.state)

    summary = tw.run_once()

    return {
        "role": role,
        "display_name": p.display_name,
        "query": query,
        "cycle_count": summary.get("cycle", 0),
        "investigations": list(tw.state.active_investigations.keys()),
        "observations": summary.get("observations", {}),
        "issues_found": len(summary.get("issues", [])),
        "actions_taken": len(summary.get("decisions", [])),
        "summary": summary,
    }
