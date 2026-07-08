"""Integration hooks — tools that digital twins use to interact with StrategyOS.

These are the twin-facing API surface that bridges autonomous twin logic
with the existing StrategyOS platform (KPI nodes, evidence spine, knowledge
graph, health endpoints).
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from strategyos_mvp.config import load_config
from strategyos_mvp.twins.protocol import validate_message
from strategyos_mvp.twins.store import TwinRepositories, build_app_repositories
from strategyos_mvp.twins.protocol import InterTwinMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# KPI query
# ---------------------------------------------------------------------------


def query_kpi(
    kpi_node_id: str, *, repositories: TwinRepositories | None = None
) -> dict[str, Any]:
    """Fetch a KPI node from the StrategyOS KPI substrate.

    Resolves through :class:`~strategyos_mvp.twins.resolution.KPIResolutionEngine`
    against the shared KPI repository — the same source the twin OODA loop
    and the ``/twin/api/kpis/{role}`` dashboard endpoint use.

    Args:
        kpi_node_id: The node identifier for the KPI to query.
        repositories: Optional repository set to resolve against (mainly
            for tests). Defaults to the shared app repositories.

    Returns:
        A dict with at least ``node_id``, ``status``, ``value_display``,
        and ``detail`` keys. Returns an ``"unresolved"`` shape when the
        node id is unknown to the KPI tree.
    """
    from strategyos_mvp.twins.resolution import KPIResolutionEngine

    repo_set = repositories or build_app_repositories()
    engine = KPIResolutionEngine(repository=repo_set.kpis)
    node = engine.get_node(kpi_node_id)
    if node is None:
        return {
            "node_id": kpi_node_id,
            "status": "unresolved",
            "value_display": "—",
            "detail": f"Unknown KPI node id: {kpi_node_id!r}.",
        }

    value = node.get("value")
    return {
        "node_id": kpi_node_id,
        "status": str(node.get("status") or "unknown"),
        "value_display": "—" if value is None else str(value),
        "value": value,
        "label": node.get("label", kpi_node_id),
        "owner": node.get("owner"),
        "last_updated": node.get("last_updated"),
        "gaps": engine.detect_gaps(kpi_node_id),
        "detail": f"Resolved {kpi_node_id!r} from the KPI repository.",
    }


# ---------------------------------------------------------------------------
# Evidence search
# ---------------------------------------------------------------------------


def query_evidence(run_id: str | None, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Keyword/lexical evidence retrieval over a run's Qdrant-indexed points.

    This is lexical (token-overlap) ranking over hash-based vectors, not
    semantic/embedding search — see ``vector_store.LEXICAL_KEYWORD_MODE``.

    Args:
        run_id: The run to search evidence within. If Qdrant is unconfigured
            or the run has no indexed points, this returns an empty list.
        query: Natural-language search string.
        limit: Maximum number of results to return.

    Returns:
        A list of evidence snippet dicts, each with at least ``id``,
        ``content``, ``source``, and ``score`` keys. Empty when evidence
        retrieval is unavailable (logged, not silent).
    """
    try:
        from strategyos_mvp.vector_store import check_qdrant_ready, search_run_vectors

        readiness = check_qdrant_ready()
        if readiness.get("status") != "ok":
            logger.info(
                "query_evidence: Qdrant not ready (%s) — returning empty",
                readiness.get("reason") or readiness.get("status"),
            )
            return []

        response = search_run_vectors(run_id, query, limit=limit)
        if response.get("status") != "ready":
            logger.info(
                "query_evidence: search unavailable (%s) — returning empty",
                response.get("reason") or response.get("status"),
            )
            return []

        return [
            {
                "id": str(item.get("point_id", "")),
                "content": str(item.get("summary") or item.get("excerpt") or item.get("text") or ""),
                "source": str(item.get("source") or item.get("source_path") or "unknown"),
                "score": float(item.get("score", 0.0)),
            }
            for item in response.get("results", [])
        ]
    except ImportError:
        logger.warning("query_evidence: vector_store not available — returning empty")
        return []
    except Exception:
        logger.exception("query_evidence: search failed")
        return []


# ---------------------------------------------------------------------------
# Message dispatch
# ---------------------------------------------------------------------------


def send_message(
    msg: InterTwinMessage,
    *,
    repositories: TwinRepositories | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist an InterTwinMessage through the configured delivery path."""
    errors = validate_message(msg)
    if errors:
        raise ValueError(f"Invalid inter-twin message: {errors}")

    repo_set = repositories or build_app_repositories()
    envelope = asdict(msg)
    if payload:
        envelope.update(payload)
    envelope.setdefault("message_id", msg.message_id)
    envelope.setdefault("sender_role", msg.sender_role)
    envelope.setdefault("recipient_role", msg.recipient_role)
    envelope.setdefault("message_type", msg.message_type)
    envelope.setdefault("priority", msg.priority)
    envelope.setdefault("subject", msg.subject)
    envelope.setdefault("body", msg.body)
    envelope.setdefault("created_at", msg.created_at)
    envelope["status"] = envelope.get("status") or "delivered"
    repo_set.inboxes.append(msg.recipient_role, envelope)

    logger.info(
        "TWIN MESSAGE [%s] %s → %s | %s | %s",
        msg.priority.upper(),
        msg.sender_role,
        msg.recipient_role,
        msg.message_type,
        msg.subject,
    )
    print(
        f"[TWIN MESSAGE] {msg.priority.upper()}: "
        f"{msg.sender_role} → {msg.recipient_role} "
        f"[{msg.message_type}] {msg.subject}"
    )
    return envelope


# ---------------------------------------------------------------------------
# Human escalation
# ---------------------------------------------------------------------------


def escalate_to_human(
    reason: str,
    context: dict[str, Any],
    *,
    sender_role: str = "system",
    repositories: TwinRepositories | None = None,
) -> dict[str, Any]:
    """Escalate an issue to a human operator.

    Persists the escalation as a real ``InterTwinMessage`` delivered to the
    ``"human"`` inbox (the same recipient concept twin escalation chains
    already terminate at — see ``persona.escalation_path`` and
    ``protocol.escalate_message``), so it is queryable rather than a
    console-only side effect. UI/email/Slack notification remains a
    separate, later integration on top of this inbox record.

    Args:
        reason: Human-readable explanation of why escalation is needed.
        context: Supporting data (KPI node, message chain, etc.).
        sender_role: The twin role raising the escalation.
        repositories: Optional repository set (mainly for tests).

    Returns:
        The persisted message envelope (see :func:`send_message`).
    """
    from datetime import datetime, timezone
    from uuid import uuid4

    message = InterTwinMessage(
        message_id=f"escalation-{uuid4().hex[:12]}",
        sender_role=sender_role,
        recipient_role="human",
        message_type="escalation",
        priority="critical",
        subject=reason[:120],
        body=reason,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    envelope = send_message(
        message,
        repositories=repositories,
        payload={"context": {k: str(v)[:200] for k, v in context.items()}},
    )

    logger.warning(
        "HUMAN ESCALATION: %s | context=%s",
        reason,
        {k: str(v)[:200] for k, v in context.items()},
    )
    print(f"\n*** HUMAN ESCALATION ***\n{reason}\nContext keys: {list(context.keys())}\n")
    return envelope


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def check_health(
    *,
    repositories: TwinRepositories | None = None,
    config: Any | None = None,
) -> dict[str, Any]:
    """Check system readiness for twin operations.

    Returns a dict with health status for key subsystems.

    Returns:
        A dict with ``status`` (``"healthy"`` or ``"degraded"``) and
        per-subsystem status entries.
    """
    active_config = config or load_config()
    health: dict[str, Any] = {
        "status": "healthy",
        "subsystems": {},
    }

    # Check platform_foundation availability
    try:
        from strategyos_mvp.platform_foundation import (
            StrategyKpiNodeContract,
        )

        health["subsystems"]["kpi_substrate"] = "available"
    except ImportError:
        health["subsystems"]["kpi_substrate"] = "unavailable"
        health["status"] = "degraded"

    # Check twin module availability
    try:
        from strategyos_mvp.twins.persona import TWIN_CATALOG

        health["subsystems"]["twin_catalog"] = f"available ({len(TWIN_CATALOG)} roles)"
    except ImportError:
        health["subsystems"]["twin_catalog"] = "unavailable"
        health["status"] = "degraded"

    repo_set = repositories or build_app_repositories()
    try:
        recent_executions = repo_set.execution.list(limit=10)
        recent_reasoning = repo_set.reasoning.list(limit=200)
        recent_decisions = repo_set.governance.list_decisions(limit=50)
        recent_routing = repo_set.governance.list_routing_events(limit=50)
        pending_review_count = sum(
            1
            for trace in recent_reasoning
            if str(trace.get("review_state") or "") == "pending_human_review"
        )
        health["subsystems"]["twin_runtime"] = (
            "enabled" if active_config.twins_enabled else "disabled"
        )
        health["subsystems"]["twin_scheduler"] = (
            "enabled"
            if active_config.twins_enabled and active_config.twins_scheduler_enabled
            else "disabled"
        )
        health["subsystems"]["reasoning"] = (
            "healthy" if active_config.twins_enabled else "disabled"
        )
        health["subsystems"]["governance"] = (
            "healthy" if active_config.twins_enabled else "disabled"
        )
        health["feature_flags"] = {
            "twins_enabled": active_config.twins_enabled,
            "twins_mutations_enabled": active_config.twins_mutations_enabled,
            "twins_scheduler_enabled": active_config.twins_scheduler_enabled,
            "twins_expose_reasoning_diagnostics": active_config.twins_expose_reasoning_diagnostics,
        }
        health["diagnostics"] = {
            "pending_reasoning_reviews": pending_review_count,
            "recent_execution_count": len(recent_executions),
            "recent_governance_decisions": len(recent_decisions),
            "recent_governance_routing_events": len(recent_routing),
            "latest_execution": recent_executions[0] if recent_executions else None,
        }
    except Exception as exc:
        logger.exception("check_health: repository diagnostics failed")
        health["subsystems"]["repository_diagnostics"] = "unavailable"
        health["diagnostics"] = {"error": str(exc)}
        health["status"] = "degraded"

    return health
