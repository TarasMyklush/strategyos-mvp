"""KPI resolution engine — tree traversal, gap detection, and ownership routing.

Connects twin personas to the KPI tree for Phase 1 by operating on a
hardcoded KPI_TREE. In later phases this will be replaced by live
Neo4j queries against the StrategyOS KPI substrate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from strategyos_mvp.twins.protocol import InterTwinMessage, check_escalation
from strategyos_mvp.twins.store import KpiRepository

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
        "threshold": 18.0,
        "alert_below": 17.0,
    },
    "revenue_q2": {
        "owner": "group_manager",
        "value": 2_100_000_000,
        "status": "current",
        "threshold": 2_000_000_000,
        "alert_below": 1_950_000_000,
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

    def __init__(
        self,
        repository: KpiRepository | None = None,
        fallback_tree: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.repository = repository
        self.fallback_tree = fallback_tree or KPI_TREE
        if self.repository is not None:
            self.repository.ensure_seeded(self.fallback_tree)

    def get_tree(self) -> dict[str, dict[str, Any]]:
        if self.repository is None:
            return KPI_TREE
        tree = self.repository.load()
        return tree or self.fallback_tree

    def get_node(self, kpi_node_id: str) -> dict[str, Any] | None:
        node = self.get_tree().get(kpi_node_id)
        return dict(node) if node else None

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
        tree = self.get_tree()
        node = tree.get(kpi_node_id)

        # Upstream: which nodes list this one as a component
        upstream: list[str] = []
        for nid, ndata in tree.items():
            components = ndata.get("components", [])
            if kpi_node_id in components:
                upstream.append(nid)

        # Downstream: recursively resolve components
        downstream: list[dict[str, Any]] = []
        if node and "components" in node:
            for comp_id in node["components"]:
                child = tree.get(comp_id)
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

        tree = self.get_tree()
        node = tree.get(node_id)
        if not node or "components" not in node:
            return []

        children: list[dict[str, Any]] = []
        for comp_id in node["components"]:
            child = tree.get(comp_id)
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
        node = self.get_tree().get(kpi_node_id)
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
        tree = self.get_tree()
        node = tree.get(kpi_node_id)
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
    # Component chain (Phase 2 — multi-hop)
    # ------------------------------------------------------------------

    def get_component_chain(self, kpi_node_id: str) -> list[str]:
        """Return a flat list of all component KPI node IDs recursively.

        Traverses the component tree under *kpi_node_id* and collects
        every descendant node ID.

        Args:
            kpi_node_id: The root KPI node to traverse from.

        Returns:
            A flat list of descendant node IDs (excluding the root).
        """
        chain: list[str] = []
        tree = self.get_tree()
        node = tree.get(kpi_node_id)
        if not node or "components" not in node:
            return chain

        visited: set[str] = set()
        self._collect_components(kpi_node_id, chain, visited)
        return chain

    def _collect_components(
        self, node_id: str, chain: list[str], visited: set[str]
    ) -> None:
        """Recursively collect component node IDs into *chain*."""
        if node_id in visited:
            return
        visited.add(node_id)

        tree = self.get_tree()
        node = tree.get(node_id)
        if not node or "components" not in node:
            return

        for comp_id in node["components"]:
            if comp_id not in chain:
                chain.append(comp_id)
            self._collect_components(comp_id, chain, visited)

    def find_resolution_path(
        self, kpi_node_id: str, target_data: str
    ) -> list[str]:
        """Find the chain of roles from root owner to target data owner.

        Traces from *kpi_node_id* down the component tree searching for
        a node whose ID contains *target_data* as a substring. Returns
        the ordered list of owning roles from root to leaf.

        Args:
            kpi_node_id: The root KPI node.
            target_data: Substring to match against descendant node IDs.

        Returns:
            A list of role strings (e.g. ``["cfo", "group_manager"]``)
            representing the ownership chain. Returns empty list if the
            target is not found or the root is unknown.
        """
        root_owner = self.find_owner(kpi_node_id)
        if root_owner is None:
            return []

        # Find the target node by traversing components
        result_container: list[str | None] = []
        self._find_target_in_tree(kpi_node_id, target_data, set(), result_container)
        target_node_id = result_container[0] if result_container else None

        # If target not found via tree, search KPI_TREE directly
        if target_node_id is None:
            for nid in self.get_tree():
                if target_data.lower() in nid.lower():
                    target_node_id = nid
                    break

        if target_node_id is None or target_node_id == kpi_node_id:
            return [root_owner]

        # Build the ownership chain from root to target
        chain: list[str] = []
        self._build_owner_chain(kpi_node_id, target_node_id, chain, set())
        # Deduplicate consecutive duplicates (same owner for adjacent nodes)
        deduped: list[str] = []
        for role in chain:
            if not deduped or deduped[-1] != role:
                deduped.append(role)
        return deduped

    def _find_target_in_tree(
        self,
        node_id: str,
        target_data: str,
        visited: set[str],
        result: list[str | None],
    ) -> None:
        """DFS search for a node whose ID contains *target_data*."""
        if node_id in visited:
            return
        visited.add(node_id)

        if target_data.lower() in node_id.lower():
            result.append(node_id)
            return

        tree = self.get_tree()
        node = tree.get(node_id)
        if node and "components" in node:
            for comp_id in node["components"]:
                self._find_target_in_tree(comp_id, target_data, visited, result)
                if result:
                    return

    def _build_owner_chain(
        self,
        from_node: str,
        to_node: str,
        chain: list[str],
        visited: set[str],
    ) -> bool:
        """Build owner chain from *from_node* to *to_node* via DFS.

        Returns *True* if the target was found along this path.
        """
        if from_node in visited:
            return False
        visited.add(from_node)

        owner = self.find_owner(from_node)
        if owner:
            chain.append(owner)

        if from_node == to_node:
            return True

        tree = self.get_tree()
        node = tree.get(from_node)
        if node and "components" in node:
            for comp_id in node["components"]:
                if self._build_owner_chain(comp_id, to_node, chain, visited):
                    return True

        # Backtrack — this path didn't lead to target
        if owner and chain and chain[-1] == owner:
            chain.pop()
        return False

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


# ---------------------------------------------------------------------------
# Multi-hop resolution (Phase 2)
# ---------------------------------------------------------------------------


def resolve_multi_hop(
    engine: KPIResolutionEngine,
    kpi_node_id: str,
    requestor_role: str,
) -> list[InterTwinMessage]:
    """Trace KPI ownership chain and generate all messages needed.

    Starting from *requestor_role*, detects gaps on the KPI node and
    follows the component tree to generate a chain of data request
    messages. Each hop routes to the owner of the next unresolved
    component.

    Example::

        CEO asks about margin → finds COGS component → routes to CFO
        → CFO finds raw_materials → routes to GM

    Args:
        engine: The :class:`KPIResolutionEngine` instance to use.
        kpi_node_id: The root KPI node to resolve.
        requestor_role: The role initiating the resolution.

    Returns:
        An ordered list of :class:`InterTwinMessage` instances
        representing the full resolution chain.
    """
    messages: list[InterTwinMessage] = []

    # Collect the full component chain
    components = engine.get_component_chain(kpi_node_id)
    if not components:
        # Single node with no components — request data for it directly
        gaps = engine.detect_gaps(kpi_node_id)
        if gaps:
            messages.append(
                engine.route_request(kpi_node_id, gaps[0], requestor_role)
            )
        return messages

    # Build the resolution chain: for each level, find gaps and route
    current_role: str = requestor_role

    # Start with the root KPI if it has gaps
    root_gaps = engine.detect_gaps(kpi_node_id)
    if root_gaps:
        root_owner = engine.find_owner(kpi_node_id)
        if root_owner and root_owner != current_role:
            # First hop: requestor → root owner
            msg = engine.route_request(kpi_node_id, root_gaps[0], current_role)
            messages.append(msg)
            current_role = root_owner

    # Then trace through components
    for comp_id in components:
        comp_gaps = engine.detect_gaps(comp_id)
        if comp_gaps:
            comp_owner = engine.find_owner(comp_id)
            if comp_owner and comp_owner != current_role:
                msg = engine.route_request(comp_id, comp_gaps[0], current_role)
                messages.append(msg)
                current_role = comp_owner
            elif comp_owner and comp_owner == current_role:
                # Same owner, create an internal notification
                msg = engine.route_request(comp_id, comp_gaps[0], current_role)
                messages.append(msg)

    return messages
