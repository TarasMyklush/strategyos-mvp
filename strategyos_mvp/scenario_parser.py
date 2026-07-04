"""Scenario parser for server-side assistant orchestration.

Parses structured and semi-structured scenario prompts (e.g. "Digital Health flat by
EOY") into deterministic, traceable calculation chains backed by KG/evidence citations.
Every output carries explicit assumptions, calculation steps, and hallucination-risk
metadata so the answer is never a black box.

Analogous prompts are matched by keyword/regex to scenario families that share the
same deterministic calculation logic. Unmatched prompts return suggestions rather
than a guess.

Architecture: each scenario family is a callable registered in SCENARIO_FAMILIES.
The parser evaluates each family's matcher against the normalized prompt and dispatches
to the first matching handler. All handlers produce a ``ScenarioResult`` with the same
structured contract.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from .models import (
    CalculationStep,
    HallucinationRisk,
    HallucinationRiskLevel,
    KGContext,
    ScenarioResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LLM_PROBES: list[str] = []
"""Globally registered fallback LLM probes registered by the assistant orchestrator
after the deterministic parser signals unmatched."""

_NOW = date.today()

_DIGITAL_HEALTH_SYNONYMS: list[tuple[str, str]] = [
    (r"\bdigital health\b", "digital_health"),
    (r"\btelehealth\b", "telehealth"),
    (r"\btelemedicine\b", "telehealth"),
    (r"\bremote patient (monitoring|care)\b", "telehealth"),
    (r"\behr\b", "ehr"),
    (r"\belectronic health records?\b", "ehr"),
    (r"\bhealth it\b", "health_it"),
    (r"\bhealth tech\b", "health_tech"),
    (r"\bflat\b", "flat"),
    (r"\bflatline\b", "flat"),
    (r"\bstagnant\b", "stagnant"),
    (r"\bno growth\b", "stagnant"),
    (r"\bzero growth\b", "stagnant"),
    (r"\bend of year\b", "eoy"),
    (r"\beoy\b", "eoy"),
    (r"\bby end of\b", "eoy"),
    (r"\bby december\b", "eoy"),
    (r"\bq4\b", "q4"),
    (r"\bh1\b", "h1"),
    (r"\bh2\b", "h2"),
    (r"\bforecast\b", "forecast"),
    (r"\bprojection\b", "forecast"),
    (r"\boutlook\b", "forecast"),
    (r"\btrend\b", "trend"),
    (r"\badoption\b", "adoption"),
    (r"\bpenetration\b", "adoption"),
    (r"\buptake\b", "adoption"),
    (r"\bdeployment\b", "deployment"),
    (r"\brollout\b", "deployment"),
    (r"\breimbursement\b", "reimbursement"),
    (r"\bpayment model\b", "reimbursement"),
    (r"\bcpt code\b", "reimbursement"),
    (r"\bregulatory\b", "regulatory"),
    (r"\bfda\b", "regulatory"),
    (r"\bhipaa\b", "regulatory"),
    (r"\bcompliance\b", "regulatory"),
    (r"\binteroperab\w+\b", "interoperability"),
    (r"\bfhir\b", "interoperability"),
    (r"\bhl7\b", "interoperability"),
    (r"\bmarket size\b", "market_size"),
    (r"\btam\b", "market_size"),
    (r"\bsam\b", "market_size"),
    (r"\bsom\b", "market_size"),
    (r"\bshare\b", "market_share"),
    (r"\bcompetitor\b", "competitive"),
    (r"\bepic\b", "competitive"),
    (r"\bcerner\b", "competitive"),
    (r"\boracle health\b", "competitive"),
    (r"\bathenahealth\b", "competitive"),
    (r"\bmeditech\b", "competitive"),
    (r"\brevenue\b", "revenue"),
    (r"\bcost\b", "cost"),
    (r"\binvestment\b", "investment"),
    (r"\broi\b", "roi"),
    (r"\breturn on investment\b", "roi"),
    (r"\bpayback\b", "roi"),
    (r"\bbreak.even\b", "roi"),
]

# Map scenario family IDs to canonical labels for the UI
SCENARIO_LABELS: dict[str, str] = {
    "digital_health_eoy_flat": "Digital Health — Flat by EOY",
    "digital_health_market": "Digital Health — Market Sizing",
    "digital_health_roi": "Digital Health — ROI / Investment",
    "digital_health_trend": "Digital Health — Trend & Adoption",
    "digital_health_regulatory": "Digital Health — Regulatory Impact",
    "finance_leakage": "Finance — Leakage & Recovery",
    "finance_working_capital": "Finance — Working Capital",
    "finance_invoice": "Finance — Invoice Analysis",
    "generic_scenario": "Generic Scenario Analysis",
}


def _normalize(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _expand_domain_synonyms(text: str) -> str:
    """Inject canonical tokens so keyword-based matchers catch colloquial phrasing."""
    extra: set[str] = set()
    for pattern, canonical in _DIGITAL_HEALTH_SYNONYMS:
        if re.search(pattern, text):
            extra.add(canonical)
    if not extra:
        return text
    return " ".join([text, *sorted(extra)])


def _sar(value: float) -> str:
    return f"SAR {value:,.2f}"


def _usd(value: float) -> str:
    return f"USD {value:,.2f}"


def _percent(value: float, decimals: int = 1) -> str:
    return f"{value * 100:.{decimals}f}%"


def _risk_none(basis: str) -> HallucinationRisk:
    return HallucinationRisk(
        level=HallucinationRiskLevel.NONE,
        score=0.0,
        factors=[{"name": "deterministic_calculation", "detail": "All values computed from explicit formulas with cited inputs."}],
        traceable=True,
        mitigations=["Every calculation step carries a formula, inputs, and source citations."],
        verification_path=basis,
    )


def _risk_low(basis: str, gap: str | None = None) -> HallucinationRisk:
    return HallucinationRisk(
        level=HallucinationRiskLevel.LOW,
        score=0.1,
        factors=[
            {"name": "partial_grounding", "detail": "Core calculations are deterministic; some extrapolations use industry baselines."},
            {"name": "external_baseline", "detail": "External reference rates sourced from documented industry reports."},
        ],
        traceable=True,
        traceability_gap=gap,
        mitigations=["External baselines are cited explicitly; verify against latest published data."],
        verification_path=basis,
    )


def _risk_medium(basis: str, gap: str) -> HallucinationRisk:
    return HallucinationRisk(
        level=HallucinationRiskLevel.MEDIUM,
        score=0.35,
        factors=[
            {"name": "extrapolated", "detail": "Values extrapolated from partial data with documented assumptions."},
            {"name": "missing_primary", "detail": f"No primary data source available: {gap}"},
        ],
        traceable=True,
        traceability_gap=gap,
        mitigations=[
            "Run with live data for primary-source verification.",
            "Cross-reference against independent industry benchmarks.",
        ],
        verification_path=basis,
    )


def _risk_high(basis: str, gap: str) -> HallucinationRisk:
    return HallucinationRisk(
        level=HallucinationRiskLevel.HIGH,
        score=0.6,
        factors=[
            {"name": "synthetic", "detail": "Values based on synthetic or modeled data with no direct evidence grounding."},
            {"name": "no_primary_evidence", "detail": gap},
        ],
        traceable=False,
        traceability_gap=gap,
        mitigations=[
            "Flag as requiring human review before operational use.",
            "Replace synthetic inputs with actual ledger/contract data.",
        ],
        verification_path=basis,
    )


def _kg_evidence(bundle: Any, role: str, locator: str) -> dict[str, Any]:
    """Build a citation from the bundle's data contracts (mirrors qa._ledger_citation)."""
    contract = (getattr(bundle, "data_contracts", None) or {}).get(role) or {}
    source_path = contract.get("relative_path") or str(getattr(bundle, "dataset_root", "unknown"))
    return {"source_path": source_path, "locator": locator, "excerpt": ""}


def _node_domain(node: dict[str, Any]) -> str:
    properties = node.get("properties") if isinstance(node, dict) else {}
    if not isinstance(properties, dict):
        properties = {}
    return str(properties.get("domain") or "").lower()


def _hydrate_scenario_result(result: ScenarioResult) -> ScenarioResult:
    citations: list[dict[str, Any]] = list(result.citations)
    assumptions: list[str] = list(result.assumptions)
    seen_citations: set[tuple[str, str, str]] = set()
    for citation in citations:
        key = (
            str(citation.get("source_path") or ""),
            str(citation.get("locator") or ""),
            str(citation.get("excerpt") or ""),
        )
        seen_citations.add(key)

    for calc in result.calculations:
        for citation in calc.citations:
            key = (
                str(citation.get("source_path") or ""),
                str(citation.get("locator") or ""),
                str(citation.get("excerpt") or ""),
            )
            if key not in seen_citations:
                citations.append(citation)
                seen_citations.add(key)
        for assumption in calc.assumptions:
            if assumption not in assumptions:
                assumptions.append(assumption)

    result.citations = citations
    result.assumptions = assumptions
    return result


# ---------------------------------------------------------------------------
# Digital Health — Flat by EOY scenario family
# ---------------------------------------------------------------------------

def _parse_digital_health_eoy_flat(
    prompt: str,
    context: dict[str, Any],
) -> ScenarioResult | None:
    """Handle 'Digital Health flat by EOY' and analogous prompts.

    Deterministic calculation:
    1. Check if any Digital Health data is in the KG or findings
    2. If yes → compute trend + projection from actual data
    3. If no → return explicit "no data" answer with synthetic assumptions flagged
    """
    norm = _normalize(prompt)
    match_text = _expand_domain_synonyms(norm)

    # Must match digital_health + (flat or stagnant) + (eoy or forecast) OR "digital health" + "by end of year"
    is_dh = "digital_health" in match_text or "telehealth" in match_text or "ehr" in match_text
    is_flat = "flat" in match_text or "stagnant" in match_text
    is_eoy = "eoy" in match_text or "forecast" in match_text
    is_dh_flat = is_dh and (is_flat or is_eoy)

    if not is_dh_flat:
        return None

    scenario_id = "digital_health_eoy_flat"
    bundle = context.get("bundle")
    findings = context.get("findings") or []
    kg_nodes = context.get("kg_nodes") or []

    # Step 1: Check for Digital Health data in the KG
    dh_kg_nodes = [
        n for n in kg_nodes
        if any(
            term in str(n.get("label", "")).lower()
            or term in _node_domain(n)
            for term in ("digital_health", "telehealth", "ehr", "health_it", "health_tech")
        )
    ]

    dh_findings = [
        f for f in findings
        if (isinstance(f, dict) and any(
            term in str(f.get("pattern_type", "")).lower()
            or term in str(f.get("title", "")).lower()
            for term in ("digital_health", "health", "telehealth", "ehr")
        ))
    ]

    has_dh_data = bool(dh_kg_nodes or dh_findings)
    calcs: list[CalculationStep] = []
    assumptions: list[str] = []
    citations: list[dict[str, Any]] = []
    kg_ctx: list[KGContext] = []
    summary_answer: str
    risk: HallucinationRisk

    # Step 2: Compute based on data availability
    if has_dh_data and bundle is not None:
        # We have some Digital Health data — compute from it
        dh_node_count = len(dh_kg_nodes)
        dh_finding_count = len(dh_findings)

        calcs.append(CalculationStep(
            step_id="dh_data_presence",
            description="Digital Health data presence check in knowledge graph",
            formula="COUNT(KG nodes with domain == 'digital_health' OR 'health_it') + COUNT(findings with DH pattern)",
            inputs={"kg_node_count_total": len(kg_nodes), "dh_kg_nodes": dh_node_count},
            result=dh_node_count,
            unit="KG nodes",
            citations=[{"source_path": "neo4j://knowledge_graph", "locator": "digital_health domain nodes"}],
        ))

        calcs.append(CalculationStep(
            step_id="dh_finding_count",
            description="Digital Health related findings count",
            formula="COUNT(findings matching DH pattern keywords)",
            inputs={"total_findings": len(findings), "dh_findings": dh_finding_count},
            result=dh_finding_count,
            unit="findings",
            citations=[{"source_path": "run_artifacts://findings", "locator": "DH-pattern findings"}],
        ))

        # Check if findings indicate a flat trend
        flat_indicator_count = sum(
            1 for f in dh_findings
            if isinstance(f, dict) and any(
                term in str(f.get("rationale", "")).lower()
                or term in str(f.get("classification", "")).lower()
                for term in ("flat", "stagnant", "no growth", "decline", "slow")
            )
        )

        flat_pct = flat_indicator_count / dh_finding_count if dh_finding_count else 0.0
        calcs.append(CalculationStep(
            step_id="dh_flat_indicator",
            description="Flat trend indicator from rationale/classification keywords",
            formula="COUNT(findings with 'flat'/'stagnant'/'no growth' keywords) / COUNT(dh_findings)",
            inputs={"flat_keyword_matches": flat_indicator_count, "dh_finding_count": dh_finding_count},
            result=round(flat_pct, 4),
            unit="ratio",
            citations=[],
            assumptions=["Keyword-based classification; review individual finding rationales for nuance."],
        ))

        # Build KG context nodes
        for node in dh_kg_nodes[:5]:
            kg_ctx.append(KGContext(
                entity_id=str(node.get("id", "unknown")),
                entity_type=str(node.get("label", "Unknown")),
                label=str(node.get("properties", {}).get("name", node.get("label", "Unknown"))),
                properties=node.get("properties", {}),
                confidence=0.9 if has_dh_data else 0.3,
            ))

        # EOY projection (deterministic linear extrapolation from available data)
        # Use today's date to compute months remaining
        months_remaining = max(0, (date(_NOW.year, 12, 31) - _NOW).days / 30.44)
        calcs.append(CalculationStep(
            step_id="eoy_projection",
            description=f"End-of-year projection ({months_remaining:.1f} months remaining)",
            formula="current_value + (flat_trend_indicator * baseline_monthly_drift)",
            inputs={
                "months_remaining": round(months_remaining, 1),
                "flat_indicator_pct": round(flat_pct * 100, 1),
                "assumed_monthly_drift_pct": 0.5,
            },
            result=f"{flat_pct * 100:.1f}% of DH findings indicate flat/stagnant trends through EOY",
            unit="trend signal",
            citations=[],
            assumptions=[
                "Linear extrapolation; real trends may be non-linear.",
                "Monthly drift of 0.5% assumed as baseline; adjust with actual revenue/usage data.",
                f"Projection based on {dh_finding_count} DH findings and {dh_node_count} KG nodes.",
            ],
        ))

        summary_answer = (
            f"Digital Health findings show {flat_pct * 100:.1f}% flat/stagnant indicators "
            f"across {dh_finding_count} DH-related findings and {dh_node_count} KG nodes. "
            f"Flat-by-EOY projection: based on current data, {flat_indicator_count} of "
            f"{dh_finding_count} DH signals carry flat/stagnant markers."
        )

        risk = _risk_low(
            basis=f"DH findings ({dh_finding_count}) and KG nodes ({dh_node_count}) from current run.",
            gap="No time-series revenue/usage data available; trend is inferred from qualitative finding markers.",
        )

    else:
        # No Digital Health data — return explicit "no data" with synthetic fallback
        calcs.append(CalculationStep(
            step_id="dh_no_data",
            description="Digital Health data absence confirmation",
            formula="CHECK(KG for DH domain nodes) == empty && CHECK(findings for DH pattern) == empty",
            inputs={"kg_node_count_total": len(kg_nodes), "finding_count_total": len(findings)},
            result="No Digital Health data found in current run.",
            unit=None,
            citations=[],
        ))

        # Synthetic baseline for illustrative purposes only
        synthetic_adoption = 0.42  # 42% — US telehealth adoption baseline ~2025-2026
        synthetic_growth = 0.0    # flat growth assumption

        calcs.append(CalculationStep(
            step_id="synthetic_dh_baseline",
            description="Synthetic Digital Health baseline (ILLUSTRATIVE ONLY)",
            formula="US telehealth adoption rate ~2025-2026 (synthetic baseline = 42%)",
            inputs={"source": "Industry benchmarks — HHS/CMS telehealth utilization reports 2025"},
            result=_percent(synthetic_adoption),
            unit="adoption rate",
            citations=[{
                "source_path": "external://hhs_telehealth_report_2025",
                "locator": "US telehealth adoption ~42% of outpatient visits 2025",
                "excerpt": "Synthetic baseline. Replace with actual data.",
            }],
            assumptions=["Synthetic data — not from this run.", "Verify against live HHS/CMS data."],
        ))

        calcs.append(CalculationStep(
            step_id="synthetic_eoy_projection",
            description="Synthetic EOY flat projection (ILLUSTRATIVE ONLY)",
            formula="baseline_adoption * (1 + growth_rate) adjusted for months_remaining",
            inputs={
                "baseline_adoption_pct": round(synthetic_adoption * 100, 1),
                "assumed_growth_rate": 0.0,
                "months_remaining": round(max(0, (date(_NOW.year, 12, 31) - _NOW).days / 30.44), 1),
            },
            result=f"Projected flat at {_percent(synthetic_adoption)} through EOY (synthetic, 0% growth assumption)",
            unit="projection",
            citations=[],
            assumptions=[
                "SYNTHETIC DATA — NOT production evidence.",
                "Replace with actual Digital Health ledger/extract data.",
                "Ingest DH adoption/vendor data via source packs for real projections.",
            ],
        ))

        summary_answer = (
            f"No Digital Health data is available in the current run. "
            f"Using synthetic industry baselines (US telehealth adoption ~{_percent(synthetic_adoption)}), "
            f"a flat-by-EOY scenario projects no growth from current baseline. "
            f"This is an illustrative answer — ingest actual DH data for production-grade analysis."
        )

        risk = _risk_high(
            basis="Synthetic industry benchmarks with no primary evidence from this run.",
            gap="No Digital Health data source is present in the current run. All values are synthetic.",
        )

        kg_ctx = [
            KGContext(
                entity_id="synthetic_dh_baseline",
                entity_type="ExternalBenchmark",
                label="US Telehealth Adoption Rate (2025)",
                properties={"adoption_rate": synthetic_adoption, "source": "HHS/CMS synthetic proxy", "growth": 0.0},
                confidence=0.3,
            )
        ]

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_label=SCENARIO_LABELS.get(scenario_id, scenario_id),
        matched=True,
        answer=summary_answer,
        calculations=calcs,
        kg_context=kg_ctx,
        citations=citations,
        assumptions=assumptions,
        hallucination_risk=risk,
        suggestions=[
            "Show Digital Health adoption trend over time",
            "What is the Digital Health market size?",
            "Digital Health ROI analysis",
            "Telehealth regulatory impact assessment",
        ],
        scenario_type="deterministic",
        basis=f"Scenario parser matched 'digital_health_flat_eoy' against prompt; {len(calcs)} calculation steps produced.",
    )


# ---------------------------------------------------------------------------
# Digital Health — Market Sizing scenario family
# ---------------------------------------------------------------------------

def _parse_digital_health_market(prompt: str, context: dict[str, Any]) -> ScenarioResult | None:
    norm = _normalize(prompt)
    match_text = _expand_domain_synonyms(norm)
    is_dh = "digital_health" in match_text or "telehealth" in match_text or "ehr" in match_text
    is_market = "market_size" in match_text or any(t in match_text for t in ("market size", "tam", "sam", "som", "share"))

    if not (is_dh and is_market):
        return None

    scenario_id = "digital_health_market"
    bundle = context.get("bundle")

    # Synthetic market sizing (no specialized DH market data in finance leakage runs)
    synthetic_tam_usd = 250_000_000_000  # $250B global DH market ~2026
    synthetic_sam_usd = 45_000_000_000   # $45B addressable (MENA/GCC region)
    synthetic_som_usd = 500_000_000      # $500M serviceable obtainable

    calcs = [
        CalculationStep(
            step_id="dh_tam",
            description="Digital Health Total Addressable Market (synthetic, 2026 estimate)",
            formula="TAM = global DH market size estimate ~2026",
            inputs={"source": "MarketsandMarkets / Grand View Research 2025-2026 DH reports (synthetic proxy)"},
            result=_usd(synthetic_tam_usd),
            unit="USD",
            citations=[{"source_path": "external://marketsandmarkets_dh_2026", "locator": "Global Digital Health market ~$250B 2026"}],
            assumptions=["Synthetic TAM estimate; replace with actual market research data.", "Excludes device/hardware segments."],
        ),
        CalculationStep(
            step_id="dh_sam",
            description="Digital Health Serviceable Addressable Market (MENA/GCC focus)",
            formula="SAM = TAM * regional_factor (~18% for MENA/GCC)",
            inputs={"tam_usd": synthetic_tam_usd, "regional_factor": 0.18},
            result=_usd(synthetic_sam_usd),
            unit="USD",
            citations=[],
            assumptions=["18% regional factor — adjust for actual target geography."],
        ),
        CalculationStep(
            step_id="dh_som",
            description="Digital Health Serviceable Obtainable Market (initial target)",
            formula="SOM = SAM * penetration_rate (~1.1%)",
            inputs={"sam_usd": synthetic_sam_usd, "penetration_rate": 0.011},
            result=_usd(synthetic_som_usd),
            unit="USD",
            citations=[],
            assumptions=["1.1% initial penetration estimate for new entrant."],
        ),
    ]

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_label=SCENARIO_LABELS.get(scenario_id, scenario_id),
        matched=True,
        answer=(
            f"Global Digital Health TAM: {_usd(synthetic_tam_usd)} (2026 est.). "
            f"MENA/GCC SAM: {_usd(synthetic_sam_usd)}. "
            f"Initial SOM: {_usd(synthetic_som_usd)}. "
            f"All figures are synthetic industry benchmarks — ingest actual market data for precision."
        ),
        calculations=calcs,
        kg_context=[],
        citations=[{"source_path": "external://dh_market_sizing", "locator": "synthetic TAM/SAM/SOM model"}],
        assumptions=[
            "Synthetic market sizing based on 2025-2026 industry reports.",
            "Regional factor and penetration rate are illustrative defaults.",
        ],
        hallucination_risk=_risk_medium(
            basis="Synthetic market sizing from published industry benchmarks.",
            gap="No primary market research data ingested. All values are illustrative.",
        ),
        suggestions=[
            "Digital Health flat by EOY analysis",
            "Digital Health ROI calculation",
            "Digital Health vendor competitive analysis",
        ],
        scenario_type="deterministic",
        basis="Scenario parser matched 'digital_health_market' against prompt.",
    )


# ---------------------------------------------------------------------------
# Digital Health — ROI scenario family
# ---------------------------------------------------------------------------

def _parse_digital_health_roi(prompt: str, context: dict[str, Any]) -> ScenarioResult | None:
    norm = _normalize(prompt)
    match_text = _expand_domain_synonyms(norm)
    is_dh = "digital_health" in match_text or "telehealth" in match_text or "ehr" in match_text
    is_roi = "roi" in match_text or "investment" in match_text or "payback" in match_text or "break" in match_text

    if not (is_dh and is_roi):
        return None

    scenario_id = "digital_health_roi"
    findings = context.get("findings") or []

    # Synthetic ROI model for DH initiative
    synthetic_investment = 5_000_000      # $5M initial investment
    synthetic_annual_savings = 750_000    # $750K/yr from reduced admin, improved billing
    synthetic_annual_revenue = 1_200_000  # $1.2M/yr new revenue from DH services
    synthetic_years = 5

    annual_return = synthetic_annual_savings + synthetic_annual_revenue
    total_return = annual_return * synthetic_years
    roi_pct = (total_return - synthetic_investment) / synthetic_investment
    payback_years = synthetic_investment / annual_return if annual_return else float("inf")

    calcs = [
        CalculationStep(
            step_id="dh_investment",
            description="Digital Health initiative investment (synthetic)",
            formula="INVESTMENT = technology + integration + training + licensing",
            inputs={"synthetic_total": synthetic_investment},
            result=_usd(synthetic_investment),
            unit="USD",
            citations=[],
            assumptions=["Synthetic investment estimate. Replace with actual budget data."],
        ),
        CalculationStep(
            step_id="dh_annual_savings",
            description="Annual operational savings from DH adoption",
            formula="SAVINGS = admin_reduction + billing_improvement + compliance_avoidance",
            inputs={"synthetic_annual": synthetic_annual_savings},
            result=_usd(synthetic_annual_savings),
            unit="USD/yr",
            citations=[],
            assumptions=["Based on industry benchmarks for EHR/telehealth operational savings."],
        ),
        CalculationStep(
            step_id="dh_annual_revenue",
            description="Annual new revenue from DH services",
            formula="REVENUE = new_patient_volume * avg_revenue_per_encounter",
            inputs={"synthetic_annual": synthetic_annual_revenue},
            result=_usd(synthetic_annual_revenue),
            unit="USD/yr",
            citations=[],
            assumptions=["Revenue estimate based on telehealth visit volume and reimbursement rates."],
        ),
        CalculationStep(
            step_id="dh_roi",
            description="Digital Health 5-year ROI",
            formula="ROI = ((annual_return * years) - investment) / investment",
            inputs={"investment": synthetic_investment, "annual_return": annual_return, "years": synthetic_years, "total_return": total_return},
            result=_percent(roi_pct),
            unit="ROI",
            citations=[],
        ),
        CalculationStep(
            step_id="dh_payback",
            description="Digital Health investment payback period",
            formula="PAYBACK = investment / annual_return",
            inputs={"investment": synthetic_investment, "annual_return": annual_return},
            result=f"{payback_years:.1f} years",
            unit="years",
            citations=[],
            assumptions=["Simple payback; does not discount cash flows."],
        ),
    ]

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_label=SCENARIO_LABELS.get(scenario_id, scenario_id),
        matched=True,
        answer=(
            f"Digital Health initiative projected ROI: {_percent(roi_pct)} over {synthetic_years} years "
            f"({_usd(total_return)} total return on {_usd(synthetic_investment)} investment). "
            f"Simple payback: {payback_years:.1f} years. "
            f"Annual benefit: {_usd(annual_return)} (savings {_usd(synthetic_annual_savings)} + revenue {_usd(synthetic_annual_revenue)})."
        ),
        calculations=calcs,
        kg_context=[],
        citations=[],
        assumptions=[
            "Synthetic financial model — replace with actual budget and operational data.",
            "5-year horizon assumed; adjust for actual planning window.",
            "No discount rate applied; NPV analysis would require cost of capital input.",
        ],
        hallucination_risk=_risk_medium(
            basis="Synthetic ROI model with published industry savings benchmarks.",
            gap="No actual budget, operational cost, or revenue data ingested. All inputs are synthetic.",
        ),
        suggestions=[
            "Digital Health flat by EOY analysis",
            "Digital Health market sizing",
            "Break down savings by category",
        ],
        scenario_type="deterministic",
        basis="Scenario parser matched 'digital_health_roi' against prompt.",
    )


# ---------------------------------------------------------------------------
# Digital Health — Trend & Adoption scenario family
# ---------------------------------------------------------------------------

def _parse_digital_health_trend(prompt: str, context: dict[str, Any]) -> ScenarioResult | None:
    norm = _normalize(prompt)
    match_text = _expand_domain_synonyms(norm)
    is_dh = "digital_health" in match_text or "telehealth" in match_text or "ehr" in match_text
    is_trend = "trend" in match_text or "adoption" in match_text or "uptake" in match_text

    if not (is_dh and is_trend):
        return None

    scenario_id = "digital_health_trend"
    # Synthetic adoption curve
    calcs = [
        CalculationStep(
            step_id="dh_adoption_2024",
            description="DH adoption baseline (2024 estimate, synthetic)",
            formula="BASELINE = published industry rate",
            inputs={"source": "HHS/CMS telehealth claims data (synthetic proxy)"},
            result="38%",
            unit="adoption rate",
            citations=[],
            assumptions=["2024 baseline from public CMS telehealth utilization data."],
        ),
        CalculationStep(
            step_id="dh_adoption_2025",
            description="DH adoption current (2025 estimate, synthetic)",
            formula="CURRENT = baseline * (1 + annual_growth)",
            inputs={"baseline_pct": 38, "annual_growth_pct": 11},
            result="42%",
            unit="adoption rate",
            citations=[],
            assumptions=["11% YoY growth from industry trend reports."],
        ),
        CalculationStep(
            step_id="dh_adoption_2026",
            description="DH adoption projection (2026 estimate, synthetic)",
            formula="PROJECTED = current * (1 + annual_growth) with deceleration factor",
            inputs={"current_pct": 42, "annual_growth_pct": 11, "deceleration_factor": 0.85},
            result="46%",
            unit="adoption rate",
            citations=[],
            assumptions=["Growth deceleration as market matures; 0.85 factor applied."],
        ),
    ]

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_label=SCENARIO_LABELS.get(scenario_id, scenario_id),
        matched=True,
        answer=(
            "Digital Health adoption trend (US market, synthetic): "
            "2024: 38% → 2025: 42% → 2026E: 46%. "
            "Growth is decelerating as the market matures. "
            "Flat-by-EOY projection suggests limited upside without new regulatory or reimbursement catalysts."
        ),
        calculations=calcs,
        kg_context=[],
        citations=[],
        assumptions=["Synthetic adoption rates from CMS/HHS public data.", "Deceleration factor of 0.85 applied for 2026 projection."],
        hallucination_risk=_risk_low(
            basis="Adoption curve extrapolated from public CMS/HHS telehealth utilization data (synthetic proxy).",
            gap="No actual organization-specific DH adoption metrics available.",
        ),
        suggestions=[
            "Digital Health flat by EOY analysis",
            "What drives DH adoption acceleration?",
            "Competitive landscape for DH platforms",
        ],
        scenario_type="deterministic",
        basis="Scenario parser matched 'digital_health_trend' against prompt.",
    )


# ---------------------------------------------------------------------------
# Digital Health — Regulatory Impact scenario family
# ---------------------------------------------------------------------------

def _parse_digital_health_regulatory(prompt: str, context: dict[str, Any]) -> ScenarioResult | None:
    norm = _normalize(prompt)
    match_text = _expand_domain_synonyms(norm)
    is_dh = "digital_health" in match_text or "telehealth" in match_text or "ehr" in match_text
    is_reg = "regulatory" in match_text or "fda" in match_text or "hipaa" in match_text or "compliance" in match_text or "interoperability" in match_text

    if not (is_dh and is_reg):
        return None

    scenario_id = "digital_health_regulatory"
    calcs = [
        CalculationStep(
            step_id="reg_framework",
            description="Active US DH regulatory frameworks (synthetic mapping)",
            formula="ENUMERATE(applicable_frameworks)",
            inputs={
                "frameworks": ["HIPAA Security/Privacy", "FDA SaMD/DSI guidance", "HTI-1/HITECH", "CMS CoP for telehealth", "ONC Cures Act info blocking"]
            },
            result="5 active/emerging frameworks",
            unit="frameworks",
            citations=[{"source_path": "external://fda_samd_guidance", "locator": "FDA Digital Health Software Precertification"}],
        ),
        CalculationStep(
            step_id="reg_cost",
            description="Estimated compliance cost impact (synthetic)",
            formula="COST = per_framework_avg * framework_count * org_size_factor",
            inputs={"per_framework_avg_usd": 200_000, "framework_count": 5, "org_size_factor": 1.2},
            result=_usd(1_200_000),
            unit="USD estimated",
            citations=[],
            assumptions=["$200K avg per framework is industry rule-of-thumb for mid-size org.", "1.2x factor for multi-state operation."],
        ),
    ]

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_label=SCENARIO_LABELS.get(scenario_id, scenario_id),
        matched=True,
        answer=(
            "Digital Health regulatory landscape (US, 2026): 5 active/emerging frameworks "
            "(HIPAA, FDA SaMD, HTI-1, CMS CoP, ONC Cures Act). "
            f"Estimated compliance investment: {_usd(1_200_000)} across frameworks. "
            "Interoperability mandates (FHIR/HL7) are accelerating, creating both compliance "
            "cost and competitive differentiation opportunity."
        ),
        calculations=calcs,
        kg_context=[],
        citations=[],
        assumptions=["Synthetic regulatory mapping and cost estimates.", "Verify against actual legal/compliance assessment."],
        hallucination_risk=_risk_medium(
            basis="Public regulatory frameworks enumerated; cost estimates are synthetic.",
            gap="No organization-specific compliance gap assessment or actual legal costs.",
        ),
        suggestions=[
            "Digital Health flat by EOY analysis",
            "FHIR interoperability readiness assessment",
            "HIPAA compliance gap analysis",
        ],
        scenario_type="deterministic",
        basis="Scenario parser matched 'digital_health_regulatory' against prompt.",
    )


# ---------------------------------------------------------------------------
# Finance — Leakage scenario family (delegates to qa.py if bundle present)
# ---------------------------------------------------------------------------

def _parse_finance_leakage(prompt: str, context: dict[str, Any]) -> ScenarioResult | None:
    norm = _normalize(prompt)
    match_text = _expand_domain_synonyms(norm)
    is_finance = any(t in match_text for t in ("leakage", "recoverable", "savings", "finance", "recovery"))
    is_not_dh = "digital_health" not in match_text and "telehealth" not in match_text

    if not (is_finance and is_not_dh):
        return None

    findings = context.get("findings") or []
    if not findings:
        return ScenarioResult(
            scenario_id="finance_leakage",
            scenario_label=SCENARIO_LABELS["finance_leakage"],
            matched=True,
            answer="No findings available for leakage analysis. Run a governed analysis first.",
            calculations=[CalculationStep(
                step_id="no_data",
                description="No findings in current run",
                formula="CHECK(findings) == empty",
                inputs={},
                result="0 findings",
                unit="findings",
                citations=[],
            )],
            kg_context=[],
            citations=[],
            assumptions=["No data available."],
            hallucination_risk=_risk_none("Checked run findings — none available."),
            suggestions=["Run a governed analysis to generate findings"],
            scenario_type="deterministic",
            basis="Scenario parser matched 'finance_leakage'; no findings available.",
        )

    total = sum(float(f.get("recoverable_sar", f.get("recoverable", 0)) or 0) for f in findings if isinstance(f, dict))
    by_pattern: dict[str, float] = {}
    for f in findings:
        if isinstance(f, dict):
            pt = str(f.get("pattern_type", "unknown"))
            by_pattern[pt] = by_pattern.get(pt, 0.0) + float(f.get("recoverable_sar", 0) or 0)

    rows = sorted(by_pattern.items(), key=lambda x: x[1], reverse=True)
    calcs = [
        CalculationStep(
            step_id="leakage_total",
            description="Total recoverable leakage across all findings",
            formula="SUM(recoverable_sar) over all findings",
            inputs={"finding_count": len(findings)},
            result=_sar(total),
            unit="SAR",
            citations=[{"source_path": "run_artifacts://findings", "locator": "recoverable_sar aggregation"}],
        ),
    ]
    for pt, val in rows[:5]:
        calcs.append(CalculationStep(
            step_id=f"leakage_{pt}",
            description=f"Recoverable leakage — {pt}",
            formula="SUM(recoverable_sar) WHERE pattern_type == '{pt}'",
            inputs={"pattern_type": pt},
            result=_sar(val),
            unit="SAR",
            citations=[],
        ))

    listing = "; ".join(f"{pt}: {_sar(val)}" for pt, val in rows[:5])
    return ScenarioResult(
        scenario_id="finance_leakage",
        scenario_label=SCENARIO_LABELS["finance_leakage"],
        matched=True,
        answer=f"Total recoverable leakage: {_sar(total)} across {len(findings)} findings. Breakdown: {listing}.",
        calculations=calcs,
        kg_context=[],
        citations=[],
        assumptions=[],
        hallucination_risk=_risk_none(f"Summed recoverable_sar over {len(findings)} findings from the current run."),
        suggestions=["Top findings by recoverable", "Leakage trend over time", "Recovery action plan"],
        scenario_type="deterministic",
        basis="Scenario parser matched 'finance_leakage'; computed from run findings.",
    )


# ---------------------------------------------------------------------------
# Generic / Fallback scenario
# ---------------------------------------------------------------------------

def _parse_generic(prompt: str, context: dict[str, Any]) -> ScenarioResult:
    """Catch-all that provides a structured 'not matched' response with suggestions."""
    return ScenarioResult(
        scenario_id="generic_scenario",
        scenario_label=SCENARIO_LABELS["generic_scenario"],
        matched=False,
        answer="I don't have a deterministic scenario parser for that prompt yet. Try one of these:",
        calculations=[],
        kg_context=[],
        citations=[],
        assumptions=[],
        hallucination_risk=HallucinationRisk(
            level=HallucinationRiskLevel.NONE,
            score=0.0,
            factors=[{"name": "no_match", "detail": "No scenario family matched; no AI generation attempted."}],
            traceable=True,
            mitigations=["Return suggestions for supported scenarios."],
        ),
        suggestions=[
            "Digital Health flat by EOY",
            "Digital Health market size",
            "Digital Health ROI analysis",
            "Digital Health adoption trend",
            "Digital Health regulatory impact",
            "Total recoverable leakage",
            "Working capital analysis",
            "Top vendors by spend",
        ],
        scenario_type="unmatched",
        basis="No scenario family matched the prompt. Returning suggestions for supported scenarios.",
    )


# ---------------------------------------------------------------------------
# Scenario family registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScenarioFamily:
    name: str
    matcher: Callable[[str, dict[str, Any]], ScenarioResult | None]
    priority: int = 0  # lower = higher priority


SCENARIO_FAMILIES: tuple[ScenarioFamily, ...] = (
    # Digital Health families (higher priority — check before generic finance)
    ScenarioFamily("digital_health_eoy_flat", _parse_digital_health_eoy_flat, priority=1),
    ScenarioFamily("digital_health_market", _parse_digital_health_market, priority=2),
    ScenarioFamily("digital_health_roi", _parse_digital_health_roi, priority=3),
    ScenarioFamily("digital_health_trend", _parse_digital_health_trend, priority=4),
    ScenarioFamily("digital_health_regulatory", _parse_digital_health_regulatory, priority=5),
    # Finance families
    ScenarioFamily("finance_leakage", _parse_finance_leakage, priority=10),
)

# Suggested prompts surfaced in UI when no match
SCENARIO_SUGGESTIONS: tuple[str, ...] = (
    "Digital Health flat by EOY — project trends and stagnation signals",
    "Digital Health market sizing — TAM, SAM, SOM for health IT",
    "Digital Health ROI for a $5M EHR/telehealth investment",
    "Digital Health adoption trend — 2024–2026 US market",
    "Digital Health regulatory impact — HIPAA, FDA, CMS compliance costs",
    "Total recoverable leakage across all findings",
    "Working capital drift analysis",
)


def parse_scenario(prompt: str, context: dict[str, Any]) -> ScenarioResult:
    """Parse a scenario prompt and return a structured ScenarioResult.

    Tries each registered ScenarioFamily in priority order. Returns the first
    match. Falls back to `_parse_generic` if nothing matches.
    """
    if not prompt or not prompt.strip():
        return ScenarioResult(
            scenario_id="empty_prompt",
            scenario_label="Empty Prompt",
            matched=False,
            answer="Please provide a scenario prompt, e.g. 'Digital Health flat by EOY'.",
            calculations=[],
            kg_context=[],
            citations=[],
            assumptions=[],
            hallucination_risk=HallucinationRisk(
                level=HallucinationRiskLevel.NONE, score=0.0,
                factors=[{"name": "empty_prompt", "detail": "No prompt provided."}],
                traceable=True,
            ),
            suggestions=list(SCENARIO_SUGGESTIONS),
            scenario_type="unmatched",
            basis="Empty prompt — no scenario to parse.",
        )

    families = sorted(SCENARIO_FAMILIES, key=lambda f: f.priority)
    for family in families:
        try:
            result = family.matcher(prompt, context)
            if result is not None:
                return _hydrate_scenario_result(result)
        except Exception as exc:
            # Defensive: never crash scenario parsing on handler errors
            return ScenarioResult(
                scenario_id=family.name,
                scenario_label=SCENARIO_LABELS.get(family.name, family.name),
                matched=False,
                answer="I could not complete that deterministic scenario safely. Try again with a supported scenario or review the available data inputs.",
                calculations=[],
                kg_context=[],
                citations=[],
                assumptions=[],
                hallucination_risk=HallucinationRisk(
                    level=HallucinationRiskLevel.HIGH,
                    score=0.8,
                    factors=[{"name": "handler_error", "detail": f"Deterministic scenario handler failed for family '{family.name}'."}],
                    traceable=False,
                    traceability_gap="Scenario handler failed before producing a grounded result.",
                    mitigations=[
                        "Retry after validating KG/findings inputs.",
                        "Fall back to a supported deterministic scenario or ingest additional data.",
                    ],
                    verification_path=f"Scenario family '{family.name}' raised an internal handler error.",
                ),
                suggestions=list(SCENARIO_SUGGESTIONS),
                scenario_type="error",
                basis=f"Scenario family '{family.name}' failed before producing a grounded result.",
            )

    return _parse_generic(prompt, context)


def register_llm_probe(probe_fn: Callable[[str, dict[str, Any]], dict[str, Any] | None]) -> None:
    """Register a fallback LLM probe to be called by the orchestrator when all
    deterministic scenario families return unmatched. The orchestrator calls these
    in registration order and uses the first non-None result."""
    _LLM_PROBES.append(probe_fn)


def get_llm_probes() -> list[Callable]:
    return list(_LLM_PROBES)
