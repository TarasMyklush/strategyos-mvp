"""StrategyOS Assistant Orchestrator — persona-aware Q&A routing engine.

Replaces the frontend-canned CEO fallback behavior (executive.js lines 285-317)
with a backend KG-grounded deterministic + LLM routed architecture.

Each persona has:
- A set of known-safe deterministic answer patterns (no LLM needed)
- Role-specific context enrichment from the knowledge graph
- Persona-appropriate answer formatting (CEO: concise, CFO: data-rich, etc.)

Architecture:
    Question → classify persona + intent → assemble KG context →
    try deterministic persona patterns → try generic QA engine →
    (if still unmatched and LLM enabled) LLM with persona system prompt →
    format answer per persona communication style
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable
from uuid import uuid4

from ..models import HallucinationRisk, HallucinationRiskLevel
from ..twins.persona import (
    CEO_TWIN,
    CFO_TWIN,
    GROUP_MANAGER_TWIN,
    STRATEGY_TWIN,
    ANALYST_TWIN,
    REVIEWER_TWIN,
    TWIN_CATALOG,
    TwinPersona,
)


# ---------------------------------------------------------------------------
# Answer data type
# ---------------------------------------------------------------------------


@dataclass
class PersonaAnswer:
    """A persona-aware answer produced by the orchestrator.

    Attributes:
        answer: The natural-language answer text.
        matched: Whether the orchestrator matched a deterministic pattern.
        persona: The persona this answer was composed for.
        mode: How the answer was produced — "persona_deterministic",
              "scenario", "qa_engine", or "llm".
        basis: Human-readable description of how the answer was derived.
        citations: Evidence citations (from QA engine or LLM path).
        suggestions: Follow-up question suggestions.
        trace: Audit metadata for live verification.
    """

    answer: str
    matched: bool
    persona: str
    mode: str  # "persona_deterministic" | "scenario" | "qa_engine" | "llm"
    basis: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


def role_prompt_contract(persona: str | None) -> dict[str, Any]:
    persona_key = _resolve_persona(persona)
    twin = TWIN_CATALOG.get(persona_key) or TWIN_CATALOG.get("ceo")
    return {
        "prompt_id": f"role:{persona_key}:v1",
        "persona": persona_key,
        "display_name": twin.display_name,
        "communication_style": twin.communication_style,
        "authority": twin.authority,
        "goals": list(twin.goals),
        "kpis_owned": list(twin.kpis_owned),
    }


def scenario_prompt_contract(question: str, scenario_result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not scenario_result:
        return None
    return {
        "prompt_id": f"scenario:{scenario_result.get('scenario_id') or 'unknown'}:v1",
        "question": question,
        "scenario_id": scenario_result.get("scenario_id"),
        "scenario_label": scenario_result.get("scenario_label"),
        "scenario_type": scenario_result.get("scenario_type"),
        "matched": bool(scenario_result.get("matched")),
    }


def hallucination_risk_metadata(
    *,
    mode: str,
    basis: str,
    citations: list[dict[str, Any]] | None = None,
    scenario_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if scenario_result and scenario_result.get("hallucination_risk"):
        return dict(scenario_result["hallucination_risk"])
    citations = citations or []
    if mode == "llm":
        return HallucinationRisk(
            level=HallucinationRiskLevel.LOW if citations else HallucinationRiskLevel.MEDIUM,
            score=0.18 if citations else 0.35,
            factors=[
                {
                    "name": "llm_generation",
                    "detail": "Answer was generated through the gated model-provider path.",
                },
                {
                    "name": "evidence_citations",
                    "detail": f"Returned with {len(citations)} citation(s).",
                },
            ],
            traceable=bool(citations),
            traceability_gap=None if citations else "LLM answer returned without explicit citations.",
            mitigations=[
                "Verify against cited evidence before operational use.",
                "Prefer deterministic routes when they cover the question.",
            ],
            verification_path=basis,
        ).as_dict()
    return HallucinationRisk(
        level=HallucinationRiskLevel.NONE,
        score=0.0,
        factors=[
            {
                "name": "deterministic_path",
                "detail": "Answer came from persona rules, deterministic QA, or explicit scenario calculations.",
            }
        ],
        traceable=True,
        mitigations=["Replay the cited basis and calculations to verify the answer."],
        verification_path=basis,
    ).as_dict()


# ---------------------------------------------------------------------------
# Persona-specific deterministic answer patterns
# ---------------------------------------------------------------------------

# Each pattern is a (regex, answer_builder_or_string) pair.
# The regex is tested against the lowercased question.
# If matched, the answer is used directly (string) or via builder callable.

_CEO_PATTERNS: list[tuple[str, str | Callable[[], str]]] = [
    # Greetings
    (
        r"^(hi|hey|hello|good\s+(morning|afternoon|evening)|how\s+are\s+you|what'?s\s+up|sup|yo|hola|bonjour|namaste)([!.\s]*)$",
        lambda: (
            "Hello — I can help with board readiness, margin risk, cash position, "
            "or the knowledge map. What would you like to review?"
        ),
    ),
    # Board status / readiness
    (
        r"\b(board|thursday|readiness|on\s+track)\b",
        "The board pack is under review. Here's what I can cover now: "
        "revenue position, margin health, cash headroom, cost variance, "
        "driver-level performance, and open board decisions. "
        "What specific area would you like to check?",
    ),
    # Driver relevance (context-aware — will be enriched by caller)
    (
        r"\b(relevan|matter|driver\s+card|this\s+(card|driver)|why\s+(is|this|does)|what\s+does\s+this\s+mean)\b",
        "__DRIVER_RELEVANCE__",  # Placeholder — enriched by caller with driver context
    ),
    # Revenue overview
    (
        r"\b(revenue|top.?line)\b",
        "Group Revenue is available from the governed run ledger. "
        "The board pack shows current performance as a % of plan with "
        "driver-level breakdowns. Would you like the group-level figure, "
        "a specific business unit, or the driver that's moving it most?",
    ),
    # Margin / profitability
    (
        r"\b(margin|profit|ebitda)\b",
        "EBITDA margin is tracked against plan in the current board pack. "
        "The margin bridge shows variance by driver — including FX exposure, "
        "cost pressure, and revenue mix. Which aspect would you like to examine?",
    ),
    # Cash / liquidity
    (
        r"\b(cash|liquidity|floor|covenant)\b",
        "Cash position and liquidity are monitored against the board floor. "
        "The treasury ledger tracks cash headroom, weekly liquidity changes, "
        "and covenant compliance. Would you like the current snapshot or "
        "the forward projection?",
    ),
    # Cost
    (
        r"\b(cost|spend|expense|overhead)\b",
        "Operating costs are tracked against plan with driver-level variance. "
        "Key cost pressures are highlighted in the board pack — including "
        "input costs, logistics, and fixed overhead. Which cost line do "
        "you want to see?",
    ),
    # Risk
    (
        r"\b(risk|threat|exposure|hedge|forex|fx|currency)\b",
        "Strategic risks are flagged in the board pack with severity and "
        "mitigation status. Current flagged items include FX exposure "
        "and supply-chain dependencies. Would you like the risk register "
        "or a specific item?",
    ),
    # Growth / expansion
    (
        r"\b(growth|expand|scaling|new\s+(market|segment))\b",
        "Growth drivers are mapped in the KPI tree with leading and "
        "lagging indicators. Revenue growth is broken down by business "
        "unit and initiative. Which growth lever would you like to "
        "examine — organic, new markets, or digital?",
    ),
    # KPI tree / knowledge graph
    (
        r"\b(kpi|metric|measure|indicator|knowledge\s+(graph|map)|cause.?and.?effect)\b",
        "The KPI tree maps cause-and-effect chains from value drivers "
        "to strategic objectives. Leading indicators are tracked weekly; "
        "lagging indicators are updated each board cycle. Which part "
        "of the map do you want to explore?",
    ),
]

_CFO_PATTERNS: list[tuple[str, str | Callable[[], str]]] = [
    # Greetings
    (
        r"^(hi|hey|hello|good\s+(morning|afternoon|evening)|how\s+are\s+you|what'?s\s+up)([!.\s]*)$",
        "Hello — I can help with revenue, margin, cash flow, budget "
        "variance, and financial controls. What would you like to analyse?",
    ),
    # Financial data request
    (
        r"\b(margin|revenue|cash\s+flow|budget|forecast|variance)\b",
        "__CFO_FINANCIAL__",  # Placeholder — enriched with actual bundle data
    ),
    # Controls / compliance
    (
        r"\b(control|compliance|audit|sox|internal\s+control)\b",
        "Financial controls status is available from the reviewer dashboard. "
        "Evidence packets are adjudicated and the audit trail is maintained. "
        "Would you like the control health summary or a specific control area?",
    ),
    # Working capital
    (
        r"\b(working\s+capital|dso|dpo|inventory|receivables?|payables?)\b",
        "Working capital metrics are tracked in the financial ledger — "
        "DSO, DPO, inventory turns, and cash conversion cycle. "
        "Which metric would you like to see?",
    ),
]

_GM_PATTERNS: list[tuple[str, str | Callable[[], str]]] = [
    # Greetings
    (
        r"^(hi|hey|hello|good\s+(morning|afternoon|evening)|how\s+are\s+you|what'?s\s+up)([!.\s]*)$",
        "Hello — I can help with BU performance, growth drivers, "
        "resource allocation, and operational metrics. What would you "
        "like to review?",
    ),
    # BU performance
    (
        r"\b(bu|business\s+unit|division|branch|unit\s+performance)\b",
        "BU performance is tracked against plan with revenue, growth, "
        "and operational metrics. Which business unit would you like "
        "to drill into?",
    ),
    # Resources / talent
    (
        r"\b(resource|talent|staff|headcount|allocation)\b",
        "Resource allocation is mapped against BU plans and initiative "
        "milestones. Would you like the allocation summary or "
        "a specific BU's resource profile?",
    ),
    # Operational metrics
    (
        r"\b(operational|efficiency|throughput|sla|fulfilment)\b",
        "Operational metrics are available by business unit — including "
        "throughput, SLA compliance, and efficiency ratios. Which "
        "metric are you interested in?",
    ),
]

_STRATEGY_PATTERNS: list[tuple[str, str | Callable[[], str]]] = [
    (
        r"^(hi|hey|hello|good\s+(morning|afternoon|evening))([!.\s]*)$",
        "Hello — I can help with KPI tree structure, value driver "
        "mappings, initiative alignment, and strategic coherence. "
        "What would you like to assess?",
    ),
    (
        r"\b(alignment|coherence|gap|misalignment|structural)\b",
        "KPI tree alignment is assessed against strategic objectives. "
        "Structural gaps and misaligned drivers are flagged. Would you "
        "like the alignment report or a specific area?",
    ),
    (
        r"\b(value\s+driver|initiative|leading|lagging|indicator)\b",
        "Value drivers and initiatives are mapped in the KPI tree with "
        "leading/lagging indicators. Which driver or initiative would "
        "you like to examine?",
    ),
]

_ANALYST_PATTERNS: list[tuple[str, str | Callable[[], str]]] = [
    (
        r"^(hi|hey|hello|good\s+(morning|afternoon|evening))([!.\s]*)$",
        "Hello — I can help with data readiness, source validation, "
        "and evidence quality. What would you like to check?",
    ),
    (
        r"\b(data|source|freshness|lineage|quality|validation)\b",
        "Data readiness and source validation results are available. "
        "Evidence quality scores are tracked across all KPIs. Which "
        "data domain would you like to validate?",
    ),
]

_REVIEWER_PATTERNS: list[tuple[str, str | Callable[[], str]]] = [
    (
        r"^(hi|hey|hello|good\s+(morning|afternoon|evening))([!.\s]*)$",
        "Hello — I can help with pending findings, evidence verification, "
        "and compliance status. What would you like to review?",
    ),
    (
        r"\b(finding|review|adjudicat|compliance|evidence|audit)\b",
        "Pending findings and adjudication status are available from the "
        "reviewer dashboard. Would you like the pending queue or "
        "a specific finding?",
    ),
]

# Default catch-all response per persona when nothing matches
_PERSONA_DEFAULTS: dict[str, str] = {
    "ceo": (
        "The current board pack shows governed data across revenue, margin, "
        "cash, cost, and strategic drivers. CEO implication: the latest "
        "governed run is available — which board decision would you like "
        "to pressure-test? I can help with the margin bridge, cash headroom, "
        "cost variance, revenue quality, or driver-level detail."
    ),
    "cfo": (
        "Financial data from the latest governed run is available. I can "
        "help with revenue, margin, cash flow, budget variance, and "
        "financial controls. Which area would you like to analyse?"
    ),
    "gm": (
        "BU performance data from the latest governed run is available. "
        "I can help with BU revenue, growth drivers, resource allocation, "
        "and operational metrics. Which BU or metric would you like to see?"
    ),
    "strategy": (
        "The KPI tree and strategic alignment data are available. I can help "
        "with structural coherence, value driver mapping, and initiative "
        "tracking. Which area would you like to assess?"
    ),
    "analyst": (
        "Data readiness and evidence quality information is available. I can "
        "help with source validation, data freshness, and quality scores. "
        "What would you like to check?"
    ),
    "reviewer": (
        "Review and compliance information is available. I can help with "
        "pending findings, evidence verification, and adjudication. "
        "What would you like to review?"
    ),
}


# ---------------------------------------------------------------------------
# Persona pattern registry
# ---------------------------------------------------------------------------

_PERSONA_PATTERN_REGISTRY: dict[str, list[tuple[str, str | Callable[[], str]]]] = {
    "ceo": _CEO_PATTERNS,
    "cfo": _CFO_PATTERNS,
    "gm": _GM_PATTERNS,
    "bucfo": _CFO_PATTERNS,  # BUCFO uses CFO patterns
    "logistics": _GM_PATTERNS,  # Logistics uses GM operational patterns
    "board": _CEO_PATTERNS,  # Board uses CEO-level patterns
    "strategy": _STRATEGY_PATTERNS,
    "analyst": _ANALYST_PATTERNS,
    "reviewer": _REVIEWER_PATTERNS,
    "group_manager": _GM_PATTERNS,
}


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def list_supported_personas() -> tuple[str, ...]:
    """Return all persona IDs the orchestrator can handle."""
    return tuple(sorted(set(
        list(TWIN_CATALOG.keys()) + list(_PERSONA_PATTERN_REGISTRY.keys())
    )))


def _resolve_persona(persona: str | None) -> str:
    """Normalize a persona identifier to a canonical key."""
    if not persona:
        return "ceo"  # Default for executive surface
    key = persona.strip().lower()
    # Standardize aliases
    aliases = {
        "group_manager": "gm",
        "bucfo": "bucfo",
        "logistics": "logistics",
        "board": "board",
    }
    return aliases.get(key, key)


def _match_persona_pattern(
    question: str,
    persona_key: str,
) -> tuple[str, str] | None:
    """Try to match a question against the persona's deterministic patterns.

    Returns (answer, basis) if matched, None otherwise.
    """
    patterns = _PERSONA_PATTERN_REGISTRY.get(persona_key, [])
    lower_q = question.lower().strip()

    for pattern, answer_or_builder in patterns:
        if re.search(pattern, lower_q):
            if callable(answer_or_builder):
                answer = answer_or_builder()
            else:
                answer = answer_or_builder
            return (answer, f"Persona-deterministic pattern match for {persona_key}")
    return None


def assess_question_for_persona(
    question: str,
    persona: str | None = None,
    driver_context: dict[str, Any] | None = None,
) -> PersonaAnswer:
    """Assess a question through the lens of a StrategyOS persona.

    This is the **primary entry point** for the assistant orchestrator.
    It replaces the frontend dead-end guard with backend persona-aware routing.

    Args:
        question: The natural-language question from the user.
        persona: The StrategyOS persona (ceo, cfo, gm, analyst, reviewer, etc.).
            Defaults to "ceo" for the executive surface.
        driver_context: Optional driver card context for enriching relevance replies.

    Returns:
        PersonaAnswer with the persona-aware response.
    """
    persona_key = _resolve_persona(persona)
    clean_question = question.strip()
    trace = {
        "persona": persona_key,
        "question": clean_question,
        "mode": "persona_deterministic",
    }

    if not clean_question:
        fallback = _PERSONA_DEFAULTS.get(persona_key, _PERSONA_DEFAULTS["ceo"])
        return PersonaAnswer(
            answer=fallback,
            matched=False,
            persona=persona_key,
            mode="persona_deterministic",
            basis=f"No question provided — returned {persona_key} default greeting.",
            trace=trace,
        )

    # Try persona-specific deterministic patterns
    match = _match_persona_pattern(clean_question, persona_key)
    if match:
        answer, basis = match
        trace["mode"] = "persona_deterministic"
        trace["matched"] = True

        # Enrich driver relevance placeholder with actual context
        if answer == "__DRIVER_RELEVANCE__" and driver_context:
            answer = _build_driver_relevance_reply(driver_context)
            trace["enriched_with"] = "driver_context"
        elif answer == "__CFO_FINANCIAL__":
            answer = _build_cfo_financial_reply(clean_question)
            trace["enriched_with"] = "cfo_financial_template"

        return PersonaAnswer(
            answer=answer,
            matched=True,
            persona=persona_key,
            mode="persona_deterministic",
            basis=basis,
            suggestions=_suggested_followups(persona_key),
            trace=trace,
        )

    # No persona pattern matched — signal caller to fall through to QA engine
    return PersonaAnswer(
        answer="__FALLTHROUGH__",
        matched=False,
        persona=persona_key,
        mode="persona_deterministic",
        basis=f"No persona pattern matched — fall through to QA engine.",
        trace=trace,
    )


def compose_persona_answer(
    qa_result: dict[str, Any] | None,
    persona: str | None = None,
    question: str = "",
    llm_result: dict[str, Any] | None = None,
    scenario_result: dict[str, Any] | None = None,
    driver_context: dict[str, Any] | None = None,
) -> PersonaAnswer:
    """Compose a persona-aware answer from QA engine and/or LLM results.

    This is called after the main Q&A pipeline runs. It wraps the raw
    results with persona-appropriate formatting.

    Args:
        qa_result: Result from the deterministic QA engine (or None).
        persona: The persona to compose for.
        question: The original question (for trace context).
        llm_result: Result from LLM fallback (or None).
        scenario_result: Result from deterministic scenario parsing (or None).
        driver_context: Optional driver card context.

    Returns:
        PersonaAnswer with persona-appropriate formatting.
    """
    persona_key = _resolve_persona(persona)
    trace = {"persona": persona_key, "question": question}

    # 1. Deterministic scenario orchestration takes precedence for scenario prompts.
    if scenario_result and scenario_result.get("matched"):
        answer = scenario_result.get("answer", "")
        trace.update(
            {
                "mode": "scenario",
                "matched": True,
                "scenario_id": scenario_result.get("scenario_id"),
                "scenario_type": scenario_result.get("scenario_type"),
                "hallucination_risk": scenario_result.get("hallucination_risk"),
            }
        )
        return PersonaAnswer(
            answer=_format_for_persona(answer, persona_key),
            matched=True,
            persona=persona_key,
            mode="scenario",
            basis=scenario_result.get("basis", "Deterministic scenario parser"),
            citations=scenario_result.get("citations", []),
            suggestions=scenario_result.get("suggestions", []) or _suggested_followups(persona_key),
            trace=trace,
        )

    # 2. If an LLM answer already exists, prefer it over generic persona
    # patterns. Persona canned responses are guardrails for deterministic
    # fallthrough, not something that should overwrite a grounded answer.
    if llm_result and llm_result.get("matched") is not False:
        answer = llm_result.get("answer", "")
        assistant_mode = str(llm_result.get("assistant_mode") or "llm")
        return PersonaAnswer(
            answer=_format_for_persona(answer, persona_key),
            matched=True,
            persona=persona_key,
            mode=assistant_mode,
            basis=llm_result.get("basis", "LLM evidence-grounded Q&A"),
            citations=llm_result.get("citations", []),
            suggestions=llm_result.get("suggestions") or _suggested_followups(persona_key),
            trace={**trace, "mode": assistant_mode, "matched": True},
        )

    # 3. Try persona-specific deterministic patterns first
    persona_match = assess_question_for_persona(
        question, persona_key, driver_context
    )
    if persona_match.matched and persona_match.answer != "__FALLTHROUGH__":
        return persona_match

    # 4. QA engine result
    if qa_result and qa_result.get("matched") is not False:
        answer = qa_result.get("answer", "")
        assistant_mode = str(qa_result.get("assistant_mode") or "qa_engine")
        return PersonaAnswer(
            answer=_format_for_persona(answer, persona_key),
            matched=True,
            persona=persona_key,
            mode=assistant_mode,
            basis=qa_result.get("basis", ""),
            citations=qa_result.get("citations", []),
            suggestions=qa_result.get("suggestions") or _suggested_followups(persona_key),
            trace={**trace, "mode": assistant_mode, "matched": True},
        )

    # 5. Complete fallback — nothing matched
    fallback = _PERSONA_DEFAULTS.get(persona_key, _PERSONA_DEFAULTS["ceo"])
    return PersonaAnswer(
        answer=fallback,
        matched=False,
        persona=persona_key,
        mode="persona_deterministic",
        basis=f"All paths exhausted for {persona_key} — returned fallback guidance.",
        suggestions=_suggested_followups(persona_key),
        trace={**trace, "mode": "fallback", "matched": False},
    )


# ---------------------------------------------------------------------------
# Answer enrichment helpers
# ---------------------------------------------------------------------------


def _build_driver_relevance_reply(driver_context: dict[str, Any]) -> str:
    """Build a context-aware driver relevance reply."""
    label = driver_context.get("label", "this driver")
    metric = driver_context.get("metric", "the current metric")
    pct = driver_context.get("pct", "—")
    status = driver_context.get("status", driver_context.get("sub", "current board context"))
    detail = driver_context.get("detail", "")
    movers = driver_context.get("movers", {})
    lifting = movers.get("lifting", [])
    dragging = movers.get("dragging", [])
    all_movers = lifting + dragging
    mover_text = " ; ".join(
        f"{m.get('name', 'a mover')} ({m.get('delta', 'movement')})"
        for m in all_movers[:2]
    )

    parts = [
        f"This {label} card is the active board driver at {metric} "
        f"({pct}% of plan; {status})."
    ]
    if detail:
        parts.append(detail)
    if mover_text:
        parts.append(f"The movement is explained by {mover_text}.")
    parts.append(
        "CEO implication: this is the decision signal to either "
        "protect the upside or intervene before the variance becomes "
        "structural."
    )
    parts.append(
        "Recommended next step: inspect the largest mover behind "
        f"{label} and decide whether it needs a board action, owner "
        "follow-up, or no action."
    )
    return " ".join(parts)


def _build_cfo_financial_reply(question: str) -> str:
    """Build a CFO-appropriate financial reply template."""
    lower_q = question.lower()
    if "margin" in lower_q:
        return (
            "Margin data is available from the latest governed run. "
            "EBITDA margin is tracked against plan with variance analysis "
            "by driver. The margin bridge shows FX exposure, cost pressure, "
            "and revenue mix effects. Would you like the full bridge or "
            "a specific driver?"
        )
    if "revenue" in lower_q:
        return (
            "Revenue data is available from the latest governed run — "
            "broken down by business unit, channel, and product line. "
            "The revenue ledger shows plan vs actual with driver-level "
            "attribution. Which segment would you like to analyse?"
        )
    if "cash" in lower_q or "flow" in lower_q:
        return (
            "Cash flow data is available from the treasury ledger — "
            "operating, investing, and financing cash flows with "
            "working capital detail. Would you like the summary or "
            "the full cash waterfall?"
        )
    if "budget" in lower_q or "variance" in lower_q:
        return (
            "Budget variance is tracked against plan for all cost centres "
            "and business units. The variance report shows absolute and "
            "percentage deviations with driver attribution. Which cost "
            "centre or BU would you like to examine?"
        )
    return (
        "Financial data from the latest governed run is available. "
        "I can help with revenue, margin, cash flow, budget variance, "
        "and financial controls. Which area would you like to analyse?"
    )


def _format_for_persona(answer: str, persona_key: str) -> str:
    """Apply persona-appropriate formatting to a raw QA answer.

    CEO: Strip metadata, keep concise.
    CFO: Keep data-rich with basis.
    GM: Operational framing.
    Others: Pass through with light enrichment.
    """
    if persona_key == "ceo":
        # CEO: strip mode/status annotations, keep answer only
        # Remove phrases like "Answered by AI fallback..."
        cleaned = re.sub(
            r"\bAnswered by AI fallback because[^.]+\.", "", answer
        )
        cleaned = re.sub(r"\bBasis:[^.]+\.", "", cleaned)
        cleaned = re.sub(r"\bRun:[^.]+\.", "", cleaned)
        cleaned = re.sub(r"\bAI fallback is not available:[^.]+\.", "", cleaned)
        cleaned = " ".join(cleaned.split())
        return cleaned.strip() or answer.strip()

    # Non-CEO personas get the full answer
    return answer.strip()


def _suggested_followups(persona_key: str) -> list[str]:
    """Return persona-appropriate follow-up question suggestions."""
    suggestions_by_persona: dict[str, list[str]] = {
        "ceo": [
            "What's driving the margin variance?",
            "Show me cash headroom vs the board floor",
            "Which business unit needs attention?",
            "What are the open board decisions?",
            "Show the risk register",
        ],
        "cfo": [
            "Show the margin bridge by driver",
            "What's the budget variance by cost centre?",
            "Show working capital metrics",
            "What's the cash flow forecast?",
            "Which controls have open findings?",
        ],
        "gm": [
            "Show BU revenue vs plan",
            "Which BU is underperforming?",
            "Show resource allocation by unit",
            "What are the operational bottlenecks?",
            "Show initiative milestone status",
        ],
        "strategy": [
            "Show KPI tree alignment gaps",
            "Which value drivers are stale?",
            "Show leading vs lagging indicator balance",
            "Which initiatives are off-track?",
            "Flag structural misalignment",
        ],
        "analyst": [
            "Check data freshness for Q2",
            "Validate latest source pack",
            "Show evidence quality scores",
            "Flag stale source documents",
            "Check data lineage for revenue",
        ],
        "reviewer": [
            "Show pending findings",
            "Check compliance status",
            "Verify evidence for open findings",
            "Show audit trail for recent adjudications",
            "Flag insufficiently supported evidence",
        ],
    }
    return suggestions_by_persona.get(persona_key, suggestions_by_persona["ceo"])[:3]


# ---------------------------------------------------------------------------
# Singleton for API integration
# ---------------------------------------------------------------------------

_ORCHESTRATOR_INSTANCE: AssistantOrchestrator | None = None


class AssistantOrchestrator:
    """Singleton orchestrator for the StrategyOS assistant system.

    Integrates persona-aware routing with the existing QA engine and
    LLM fallback pipeline.
    """

    def __init__(self) -> None:
        self._audit_log: list[dict[str, Any]] = []

    def process(
        self,
        question: str,
        persona: str | None = None,
        qa_result: dict[str, Any] | None = None,
        llm_result: dict[str, Any] | None = None,
        scenario_result: dict[str, Any] | None = None,
        driver_context: dict[str, Any] | None = None,
    ) -> PersonaAnswer:
        """Process a question through the orchestrator.

        This is the main integration point for the API layer.

        Args:
            question: The user's question.
            persona: The StrategyOS persona.
            qa_result: Optional result from the deterministic QA engine.
            llm_result: Optional result from the LLM fallback.
            scenario_result: Optional result from deterministic scenario parsing.
            driver_context: Optional driver card context.

        Returns:
            A persona-aware answer.
        """
        result = compose_persona_answer(
            qa_result=qa_result,
            persona=persona,
            question=question,
            llm_result=llm_result,
            scenario_result=scenario_result,
            driver_context=driver_context,
        )

        persona_key = _resolve_persona(persona)
        result.trace.setdefault("persona", persona_key)
        result.trace.setdefault("prompts", {})
        result.trace["prompts"]["role"] = role_prompt_contract(persona_key)
        result.trace["prompts"]["scenario"] = scenario_prompt_contract(question, scenario_result)
        result.trace["deterministic_boundary"] = {
            "deterministic_routes": ["persona_deterministic", "scenario", "qa_engine"],
            "llm_route": "llm",
            "selected_mode": result.mode,
        }
        result.trace["hallucination_risk"] = hallucination_risk_metadata(
            mode=result.mode,
            basis=result.basis,
            citations=result.citations,
            scenario_result=scenario_result,
        )

        # Audit logging (for Hermes live verification)
        audit_trail_id = str(uuid4())
        result.trace.setdefault("audit_trail_id", audit_trail_id)
        audit_entry = {
            "audit_trail_id": audit_trail_id,
            "question": question,
            "persona": _resolve_persona(persona),
            "mode": result.mode,
            "matched": result.matched,
            "basis": result.basis,
            "answer_preview": result.answer[:100] if result.answer else "",
            "trace": result.trace,
        }
        self._audit_log.append(audit_entry)

        return result

    def get_audit_trail(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent audit entries for traceability."""
        return list(self._audit_log[-limit:])


def get_orchestrator() -> AssistantOrchestrator:
    """Get or create the singleton orchestrator."""
    global _ORCHESTRATOR_INSTANCE
    if _ORCHESTRATOR_INSTANCE is None:
        _ORCHESTRATOR_INSTANCE = AssistantOrchestrator()
    return _ORCHESTRATOR_INSTANCE
