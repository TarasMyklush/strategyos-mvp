"""Integration hooks — tools that digital twins use to interact with StrategyOS.

These are the twin-facing API surface that bridges autonomous twin logic
with the existing StrategyOS platform (KPI nodes, evidence spine, knowledge
graph, health endpoints).
"""

from __future__ import annotations

import logging
from typing import Any

from strategyos_mvp.twins.protocol import InterTwinMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# KPI query
# ---------------------------------------------------------------------------


def query_kpi(kpi_node_id: str) -> dict[str, Any]:
    """Fetch a KPI node from the StrategyOS KPI substrate.

    Args:
        kpi_node_id: The node identifier for the KPI to query.

    Returns:
        A dict with at least ``node_id``, ``status``, ``value_display``,
        and ``detail`` keys. Returns an error-shaped dict when the KPI
        cannot be resolved.
    """
    try:
        from strategyos_mvp.platform_foundation import StrategyKpiNodeContract

        # In a real implementation this would resolve from the KPI tree
        # via graph_queries or a KPI service. Here we return a stub
        # that can be replaced when the resolution engine is wired up.
        return {
            "node_id": kpi_node_id,
            "status": "unresolved",
            "value_display": "—",
            "detail": "KPI query stub — resolution engine not yet connected.",
        }
    except ImportError:
        logger.warning("query_kpi: platform_foundation not available")
        return {"node_id": kpi_node_id, "status": "error", "detail": "Platform layer unavailable"}


# ---------------------------------------------------------------------------
# Evidence search
# ---------------------------------------------------------------------------


def query_evidence(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Semantic search across the StrategyOS evidence spine.

    Args:
        query: Natural-language search string.
        limit: Maximum number of results to return.

    Returns:
        A list of evidence snippet dicts, each with at least ``id``,
        ``content``, ``source``, and ``score`` keys.
    """
    try:
        from strategyos_mvp.vector_store import search

        results = search(query=query, limit=limit)
        return [
            {
                "id": str(r.get("id", "")),
                "content": str(r.get("content", "")),
                "source": str(r.get("source", "unknown")),
                "score": float(r.get("score", 0.0)),
            }
            for r in results
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


def send_message(msg: InterTwinMessage) -> None:
    """Enqueue an InterTwinMessage for delivery.

    Currently a stub that logs the message to the console. In Phase 1+
    this will write to a message queue / database for async delivery.

    Args:
        msg: The fully-constructed and validated message to send.
    """
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


# ---------------------------------------------------------------------------
# Human escalation
# ---------------------------------------------------------------------------


def escalate_to_human(reason: str, context: dict[str, Any]) -> None:
    """Escalate an issue to a human operator.

    Stub implementation that logs the escalation. In later phases this
    will notify via the UI, email, or Slack integration.

    Args:
        reason: Human-readable explanation of why escalation is needed.
        context: Supporting data (KPI node, message chain, etc.).
    """
    logger.warning(
        "HUMAN ESCALATION: %s | context=%s",
        reason,
        {k: str(v)[:200] for k, v in context.items()},
    )
    print(f"\n*** HUMAN ESCALATION ***\n{reason}\nContext keys: {list(context.keys())}\n")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def check_health() -> dict[str, Any]:
    """Check system readiness for twin operations.

    Returns a dict with health status for key subsystems.

    Returns:
        A dict with ``status`` (``"healthy"`` or ``"degraded"``) and
        per-subsystem status entries.
    """
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

    return health
