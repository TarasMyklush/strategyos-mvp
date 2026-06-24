"""KPI resolution engine — tree traversal, gap detection, and ownership routing.

Connects twin personas to the KPI tree for Phase 1 by operating on a
hardcoded KPI_TREE. In later phases this will be replaced by live
Neo4j queries against the StrategyOS KPI substrate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from strategyos_mvp.twins.protocol import InterTwinMessage

# ---------------------------------------------------------------------------
# Hardcoded KPI tree (Phase 1 — no live Neo4j yet)
# ---------------------------------------------------------------------------

KPI_TREE: dict[str, dict[str, Any]] = {
    "margin_q2": {
        "owner": "cfo",
        "value": None,
        "status": "stale",
        "last_updated": "2026-05-15",
        "components": ["revenue_q2", "cogs_q2"],
    },
    "revenue_q2": {
        "owner": "group_manager",
        "value": 2_100_000_000,
        "status": "current",
    },
    "cogs_q2": {
        "owner": "cfo",
        "value": None,
        "status": "missing",
        "components": ["raw_materials_q2"],
    },
    "raw_materials_q2": {
        "owner": "group_manager",
        "value": None,
        "status": "missing",
    },
}

# ---------------------------------------------------------------------------
# Resolution engine
# ---------------------------------------------------------------------------


class KPIResolutionEngine:
    """Traces KPI nodes, detects gaps, and routes data requests to owners.

    Operates on the hardcoded KPI_TREE for Phase 1. Each method is
    a pure function over the tree — the engine carries no instance
    state so it is safe to share across twin cycles.
    """

    # ------------------------------------------------------------------
    # Tree traversal
    # ------------------------------------------------------------------

    def trace_tree(self, kpi_node_id: str) -> dict[str, Any]:
        """Trace a KPI node upward (objectives that reference it) and
        downward (component KPIs it decomposes into).

        Args:
            kpi_node_id: The root KPI node to trace from.

        Returns:
            A dict with keys:
            - ``node``: the node's own data (or *None* if unknown)
            - ``upstream``: list of node IDs that reference this node
              as a component
            - ``downstream``: recursively resolved component tree
        """
        node = KPI_TREE.get(kpi_node_id)

        # Upstream: which nodes list this one as a component
        upstream: list[str] = []
        for nid, ndata in KPI_TREE.items():
            components = ndata.get("components", [])
            if kpi_node_id in components:
                upstream.append(nid)

        # Downstream: recursively resolve components
        downstream: list[dict[str, Any]] = []
        if node and "components" in node:
            for comp_id in node["components"]:
                child = KPI_TREE.get(comp_id)
                if child:
                    downstream.append({
                        "node_id": comp_id,
                        "data": dict(child),
                        "children": self._resolve_components(comp_id),
                    })

        return {
            "node": dict(node) if node else None,
            "upstream": upstream,
            "downstream": downstream,
        }

    def _resolve_components(
        self, node_id: str, visited: set[str] | None = None
    ) -> list[dict[str, Any]]:
        """Recursively resolve the component tree under *node_id*.

        Args:
            node_id: The node whose children to resolve.
            visited: Set of already-visited nodes to prevent cycles.

        Returns:
            A list of child node dicts, each with ``node_id``, ``data``,
            and ``children``.
        """
        if visited is None:
            visited = set()
        if node_id in visited:
            return []
        visited.add(node_id)

        node = KPI_TREE.get(node_id)
        if not node or "components" not in node:
            return []

        children: list[dict[str, Any]] = []
        for comp_id in node["components"]:
            child = KPI_TREE.get(comp_id)
            if child:
                children.append({
                    "node_id": comp_id,
                    "data": dict(child),
                    "children": self._resolve_components(comp_id, visited),
                })
        return children

    # ------------------------------------------------------------------
    # Ownership
    # ------------------------------------------------------------------

    def find_owner(self, kpi_node_id: str) -> str | None:
        """Return the role that owns the given KPI node.

        Args:
            kpi_node_id: The KPI node identifier.

        Returns:
            The owning role string (e.g. ``"cfo"``) or *None* if the
            node is unknown.
        """
        node = KPI_TREE.get(kpi_node_id)
        if node is None:
            return None
        return node.get("owner")

    # ------------------------------------------------------------------
    # Gap detection
    # ------------------------------------------------------------------

    def detect_gaps(self, kpi_node_id: str) -> list[dict[str, Any]]:
        """Detect gaps for a KPI node.

        A gap is any condition where the KPI data is not fully current
        and reliable:
        - ``status == "missing"`` — no data available at all
        - ``value is None`` — data hasn't been populated
        - ``status == "stale"`` — data exists but hasn't been refreshed
          recently (configurable threshold)

        Args:
            kpi_node_id: The KPI node to check.

        Returns:
            A list of gap dicts, each with ``kpi_node_id``, ``type``,
            ``detail``, and ``owner`` keys. Empty list if no gaps found.
        """
        node = KPI_TREE.get(kpi_node_id)
        if node is None:
            return [{
                "kpi_node_id": kpi_node_id,
                "type": "unknown_node",
                "detail": f"KPI node {kpi_node_id!r} is not defined in the tree.",
                "owner": None,
            }]

        gaps: list[dict[str, Any]] = []
        owner = node.get("owner", "unknown")
        status = node.get("status", "unknown")
        value = node.get("value")

        if status == "missing":
            gaps.append({
                "kpi_node_id": kpi_node_id,
                "type": "missing_data",
                "detail": f"No data available for {kpi_node_id}.",
                "owner": owner,
            })
        elif status == "stale":
            last_updated = node.get("last_updated", "unknown")
            gaps.append({
                "kpi_node_id": kpi_node_id,
                "type": "stale_data",
                "detail": (
                    f"Data for {kpi_node_id} is stale "
                    f"(last updated: {last_updated})."
                ),
                "owner": owner,
            })
        if value is None and status not in ("missing", "stale", "current"):
            gaps.append({
                "kpi_node_id": kpi_node_id,
                "type": "missing_value",
                "detail": f"Value for {kpi_node_id} is not populated.",
                "owner": owner,
            })

        # Recurse into components
        if "components" in node:
            for comp_id in node["components"]:
                gaps.extend(self.detect_gaps(comp_id))

        return gaps

    # ------------------------------------------------------------------
    # Request routing
    # ------------------------------------------------------------------

    _message_counter: int = 0

    def route_request(
        self,
        kpi_node_id: str,
        gap: dict[str, Any],
        requestor_role: str,
    ) -> InterTwinMessage:
        """Create a structured data_request message to the KPI owner.

        Args:
            kpi_node_id: The KPI node with a detected gap.
            gap: The gap dict returned by :meth:`detect_gaps`.
            requestor_role: Role of the twin requesting the data.

        Returns:
            An :class:`InterTwinMessage` ready to be sent to the KPI
            owner via :func:`tools.send_message`.
        """
        owner = self.find_owner(kpi_node_id) or "unknown"
        self.__class__._message_counter += 1
        msg_id = f"req-{kpi_node_id}-{self.__class__._message_counter:04d}"

        return InterTwinMessage(
            message_id=msg_id,
            sender_role=requestor_role,
            recipient_role=owner,
            message_type="data_request",
            priority="high" if gap.get("type") == "missing_data" else "normal",
            subject=f"Data request: {kpi_node_id} — {gap.get('type', 'gap')}",
            body=(
                f"Requesting updated data for KPI {kpi_node_id}.\n"
                f"Gap: {gap.get('detail', 'Unknown gap')}\n"
                f"Requested by {requestor_role} twin."
            ),
            evidence_citations=(),
            deadline_seconds=3600,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="pending",
        )
