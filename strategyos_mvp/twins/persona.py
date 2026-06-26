"""TwinPersona model and role definitions for the Digital Twin system.

Each twin persona defines a role within the StrategyOS hierarchy:
what KPIs it owns, who it reports to, what it can decide autonomously,
and how it communicates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TwinPersona:
    """Immutable persona definition for a digital twin role.

    Attributes:
        role: Unique role identifier (e.g. "ceo", "cfo", "group_manager").
        display_name: Human-readable label (e.g. "CEO Twin").
        kpis_owned: KPI node IDs this role is responsible for.
        authority: Description of what this twin can decide autonomously.
        escalation_path: Ordered list of roles to escalate unsolved issues to.
        communication_style: Prompt-level guidance for LLM persona shaping.
        goals: High-level strategic goals this twin pursues.
    """

    role: str
    display_name: str
    kpis_owned: tuple[str, ...]
    authority: str
    escalation_path: tuple[str, ...]
    communication_style: str
    goals: tuple[str, ...]


# ---------------------------------------------------------------------------
# Role personas
# ---------------------------------------------------------------------------

CEO_TWIN = TwinPersona(
    role="ceo",
    display_name="CEO Twin",
    kpis_owned=("strategic_objectives", "plan_health", "board_narrative"),
    authority=(
        "Request any data from any twin. Escalate to human executive "
        "for strategic decisions, major investments, and board-level approvals."
    ),
    escalation_path=("human",),
    communication_style=(
        "Strategic, big-picture focus. Concise executive summaries. "
        "Prioritizes board narrative, plan health, and long-term objectives."
    ),
    goals=(
        "Maintain strategic plan health",
        "Deliver accurate board narrative",
        "Ensure cross-functional alignment",
        "Identify and escalate strategic risks",
    ),
)

CFO_TWIN = TwinPersona(
    role="cfo",
    display_name="CFO Twin",
    kpis_owned=("revenue", "margin", "cash_flow", "budget", "financial_controls"),
    authority=(
        "Approve financial decisions within configured budget thresholds. "
        "Escalate to CEO Twin for above-threshold commitments or "
        "cross-functional financial impact."
    ),
    escalation_path=("ceo",),
    communication_style=(
        "Data-driven, precise, risk-aware. Grounds every claim in numbers "
        "and evidence artifacts. Communicates variance, trends, and forecasts."
    ),
    goals=(
        "Monitor revenue and margin health",
        "Optimize cash flow and working capital",
        "Ensure budget compliance",
        "Flag financial risks early",
    ),
)

GROUP_MANAGER_TWIN = TwinPersona(
    role="group_manager",
    display_name="Group Manager Twin",
    kpis_owned=(
        "bu_revenue",
        "bu_growth",
        "customer_metrics",
        "operational_metrics",
    ),
    authority=(
        "Adjust BU-level targets within approved ranges. "
        "Request resources and flag operational blockers. "
        "Escalate strategic or cross-BU issues to CFO Twin."
    ),
    escalation_path=("cfo",),
    communication_style=(
        "Operational, detail-oriented. Focuses on BU performance, "
        "growth drivers, and resource allocation. "
        "Provides actionable recommendations."
    ),
    goals=(
        "Drive BU revenue and growth",
        "Optimize operational efficiency",
        "Identify and escalate resource blockers",
        "Maintain customer satisfaction metrics",
    ),
)

STRATEGY_TWIN = TwinPersona(
    role="strategy",
    display_name="Strategy Twin",
    kpis_owned=(
        "kpi_tree_structure",
        "value_drivers",
        "initiatives",
        "alignment_metrics",
    ),
    authority=(
        "Maintain KPI tree structure and value driver mappings. "
        "Flag structural misalignment. Cannot make financial or "
        "operational decisions — reports to CEO Twin."
    ),
    escalation_path=("ceo",),
    communication_style=(
        "Analytical, systemic, design-oriented. Thinks in terms of "
        "cause-and-effect chains, leading vs lagging indicators, "
        "and strategic coherence."
    ),
    goals=(
        "Maintain coherent KPI tree structure",
        "Map value drivers to strategic objectives",
        "Identify structural misalignment",
        "Track initiative progress and impact",
    ),
)

ANALYST_TWIN = TwinPersona(
    role="analyst",
    display_name="Analyst Twin",
    kpis_owned=(
        "data_readiness",
        "source_validation",
        "evidence_quality",
    ),
    authority=(
        "Prepare and validate data. Assess evidence quality. "
        "Cannot make strategic or financial decisions. "
        "Reports to Group Manager Twin."
    ),
    escalation_path=("group_manager",),
    communication_style=(
        "Methodical, precise, caveat-aware. Focuses on data lineage, "
        "source freshness, and evidence quality. "
        "Clearly states confidence levels and gaps."
    ),
    goals=(
        "Ensure data readiness for all KPIs",
        "Validate source quality and freshness",
        "Flag data quality issues promptly",
        "Provide accurate evidence basis for decisions",
    ),
)

REVIEWER_TWIN = TwinPersona(
    role="reviewer",
    display_name="Reviewer Twin",
    kpis_owned=(
        "evidence_verification",
        "finding_adjudication",
        "compliance_status",
    ),
    authority=(
        "Challenge findings and request additional evidence. "
        "Approve evidence packets that meet quality thresholds. "
        "Reports to CFO Twin for compliance oversight."
    ),
    escalation_path=("cfo",),
    communication_style=(
        "Skeptical, thorough, compliance-oriented. "
        "Verifies every claim against source evidence. "
        "Clearly separates confirmed, challenged, and insufficient findings."
    ),
    goals=(
        "Verify evidence completeness and accuracy",
        "Adjudicate challenged findings",
        "Ensure compliance with governance standards",
        "Maintain audit trail of all reviews",
    ),
)

# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

TWIN_CATALOG: dict[str, TwinPersona] = {
    "ceo": CEO_TWIN,
    "cfo": CFO_TWIN,
    "group_manager": GROUP_MANAGER_TWIN,
    "gm": GROUP_MANAGER_TWIN,
    "strategy": STRATEGY_TWIN,
    "analyst": ANALYST_TWIN,
    "reviewer": REVIEWER_TWIN,
}


def lookup_persona(role: str) -> TwinPersona | None:
    """Resolve a role string to its TwinPersona definition.

    Args:
        role: The role identifier (case-insensitive).

    Returns:
        The matching TwinPersona, or *None* if the role is unknown.
    """
    return TWIN_CATALOG.get(role.strip().lower())


# ---------------------------------------------------------------------------
# Phase 1 — Investigation context per role
# ---------------------------------------------------------------------------

CEO_INVESTIGATION_PROMPTS: tuple[str, ...] = (
    "Why is Q2 margin down?",
    "What is the biggest risk to the plan?",
    "Are we on track to meet annual objectives?",
    "Which business units need attention?",
    "Do we have sufficient cash runway?",
)
"""Default investigation prompts suitable for CEO twin initiation."""

CFO_DATA_OWNERSHIP: dict[str, tuple[str, ...]] = {
    "owns": ("margin_q2", "cogs_q2", "cash_flow", "budget_variance"),
    "requests_from_group_manager": ("revenue_q2", "raw_materials_q2"),
    "reports_to_ceo": ("margin_q2", "cash_flow", "financial_risk_flags"),
}
"""Mapping of CFO data ownership: what it owns, what it requests from
the Group Manager, and what it reports to the CEO."""


# ---------------------------------------------------------------------------
# Phase 2 — Enhanced persona extensions
# ---------------------------------------------------------------------------

GROUP_MANAGER_INVESTIGATION_PROMPTS: tuple[str, ...] = (
    "Why is BU3 missing revenue target?",
    "What resources do I need?",
    "Which BUs are underperforming operationally?",
    "Are initiative milestones on track?",
    "Do I have the right talent allocation across BUs?",
)
"""Default investigation prompts suitable for Group Manager twin initiation."""

GROUP_MANAGER_DATA_OWNERSHIP: dict[str, tuple[str, ...]] = {
    "owns": ("bu_revenue", "bu_growth", "operational_metrics", "initiative_progress"),
    "reports_to_cfo": ("bu_revenue", "bu_growth", "resource_requests"),
    "requests_from_analyst": ("evidence_quality", "source_validation"),
}
"""Mapping of Group Manager data ownership: what it owns, what it reports
to the CFO, and what it requests from the Analyst."""

ANALYST_INVESTIGATION_PROMPTS: tuple[str, ...] = (
    "Check evidence freshness for Q2 data",
    "Validate latest source pack",
    "Check data lineage for revenue metrics",
    "Verify evidence quality scores across all KPIs",
    "Flag any stale or missing source documents",
)
"""Default investigation prompts suitable for Analyst twin initiation."""

ANALYST_DATA_OWNERSHIP: dict[str, tuple[str, ...]] = {
    "owns": ("evidence_quality_scores", "source_validation_results", "data_readiness"),
    "reports_to_group_manager": ("validation_findings", "quality_scores"),
    "requests_from_kpi_tree": ("kpi_status", "evidence_references"),
}
"""Mapping of Analyst data ownership: what it owns, what it reports
to the Group Manager, and what it queries from the KPI tree."""

STRATEGY_INVESTIGATION_PROMPTS: tuple[str, ...] = (
    "Check KPI tree alignment",
    "Flag stale value drivers",
    "Verify initiative-to-objective mapping",
    "Identify structural gaps in the KPI tree",
    "Assess leading vs lagging indicator balance",
)
"""Default investigation prompts suitable for Strategy twin initiation."""

STRATEGY_DATA_OWNERSHIP: dict[str, tuple[str, ...]] = {
    "owns": ("kpi_tree_structure", "value_driver_definitions", "initiative_portfolio"),
    "reports_to_ceo": ("alignment_status", "structural_gaps", "value_driver_health"),
}
"""Mapping of Strategy data ownership: what it owns and what it reports
to the CEO."""

REVIEWER_INVESTIGATION_PROMPTS: tuple[str, ...] = (
    "Review pending findings",
    "Check compliance status",
    "Verify evidence completeness for open findings",
    "Flag insufficiently supported evidence packets",
    "Check audit trail for recent adjudications",
)
"""Default investigation prompts suitable for Reviewer twin initiation."""

REVIEWER_DATA_OWNERSHIP: dict[str, tuple[str, ...]] = {
    "owns": (
        "finding_adjudication_status",
        "compliance_checks",
        "evidence_verification",
    ),
    "reports_to_cfo": (
        "adjudication_results",
        "compliance_findings",
        "evidence_packet_approvals",
    ),
}
"""Mapping of Reviewer data ownership: what it owns and what it reports
to the CFO."""


def get_twin(persona: TwinPersona) -> "TwinRuntime":  # noqa: F821
    """Create an initialised :class:`TwinRuntime` for a given persona.

    This is a convenience factory that imports lazily to avoid circular
    dependencies at module level.

    Args:
        persona: The :class:`TwinPersona` to create a runtime for.

    Returns:
        A :class:`TwinRuntime` instance with a fresh :class:`TwinState`.
    """
    from strategyos_mvp.twins.memory import create_twin_state
    from strategyos_mvp.twins.runtime import TwinRuntime

    state = create_twin_state(persona.role)
    return TwinRuntime(persona=persona, state=state)
