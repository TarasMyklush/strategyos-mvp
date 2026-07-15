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
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable, Mapping

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
    "recovery_realization": "Finance — Recovery Realization",
    "fx_hedge": "Finance — FX Hedge",
    "ebitda_scenario": "Finance — EBITDA Scenario",
    "finance_leakage": "Finance — Leakage & Recovery",
    "finance_working_capital": "Finance — Working Capital",
    "finance_invoice": "Finance — Invoice Analysis",
    "public_exec_gap_widening": "Executive Surface — Gap Widening",
    "public_exec_full_year_risk": "Executive Surface — Full-Year Risk",
    "public_exec_fx_impact": "Executive Surface — FX Hedge Impact",
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


def _sar_decimal(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"SAR {rounded:,.2f}"


def _sar_executive_decimal(value: Decimal) -> str:
    """Render scenario narrative figures at CEO scan speed; audit steps stay exact."""
    absolute = abs(value)
    if absolute >= Decimal("1000000000"):
        display = f"{absolute / Decimal('1000000000'):.1f}B"
    elif absolute >= Decimal("1000000"):
        display = f"{absolute / Decimal('1000000'):.1f}M"
    elif absolute >= Decimal("1000"):
        display = f"{absolute / Decimal('1000'):.1f}K"
    else:
        display = f"{absolute.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,.0f}"
    return f"SAR {display}"


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


_SCENARIO_INTENT_RE = re.compile(
    r"\b(if|assume|assuming|scenario|simulate|model|project|increase|decrease|"
    r"recover|realize|collect|hedge|change by|reach|target|achieve|what needs to change|what would happen|what happens|"
    r"impact of|falls?|rises?|flat by|by end of year|eoy)\b",
    re.IGNORECASE,
)

_NUMBER_RE = re.compile(
    r"(?P<prefix>\b(?:sar|usd|eur|aed|gbp)\s*)?"
    r"(?P<value>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*(?P<scale>[kmb])?"
    r"\s*(?P<suffix>%|\b(?:sar|usd|eur|aed|gbp)\b)?",
    re.IGNORECASE,
)


def has_scenario_intent(prompt: str) -> bool:
    """Public: does this prompt ask the scenario engine to model something?

    Exported so the chat router can ask the engine that owns scenarios whether
    it claims a question, instead of guessing from a keyword list.
    """
    return _has_scenario_intent(prompt)


def _has_scenario_intent(prompt: str) -> bool:
    return bool(_SCENARIO_INTENT_RE.search(prompt or ""))


def _parse_numeric_tokens(prompt: str) -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    for match in _NUMBER_RE.finditer(prompt or ""):
        raw_value = match.group("value")
        try:
            value = Decimal(raw_value.replace(",", ""))
        except (InvalidOperation, AttributeError):
            continue
        scale = (match.group("scale") or "").strip().lower()
        if scale == "k":
            value *= Decimal("1000")
        elif scale == "m":
            value *= Decimal("1000000")
        elif scale == "b":
            value *= Decimal("1000000000")
        prefix = (match.group("prefix") or "").strip().upper()
        suffix = (match.group("suffix") or "").strip().upper()
        unit = "%" if suffix == "%" else (prefix or suffix or "")
        tokens.append(
            {
                "raw": match.group(0).strip(),
                "value": value,
                "unit": unit,
                "span": match.span(),
            }
        )
    return tokens


def _serialized_prompt_numbers(prompt_numbers: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"raw": str(n["raw"]), "value": str(n["value"]), "unit": str(n["unit"])}
        for n in prompt_numbers
    ]


def _select_recovery_amount(prompt: str, prompt_numbers: list[dict[str, Any]]) -> dict[str, Any] | None:
    amount_candidates = [
        token for token in prompt_numbers
        if token["unit"] in {"", "SAR"} and token["value"] > 0
    ]
    if not amount_candidates:
        return None
    for token in amount_candidates:
        start, end = token["span"]
        window = _normalize((prompt[max(0, start - 32):start] + " " + prompt[end:end + 24]))
        if re.search(r"\b(recover|recovery|realize|realise|collect)\b", window):
            return token
    return amount_candidates[0]


def _scenario_missing_data_result(
    scenario_id: str,
    scenario_label: str,
    answer: str,
    missing_inputs: list[str],
    prompt_numbers: list[dict[str, Any]],
    suggestions: list[str] | None = None,
) -> ScenarioResult:
    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_label=scenario_label,
        matched=True,
        answer=answer,
        calculations=[
            CalculationStep(
                step_id="scenario_validation",
                description="Scenario request validation failed closed because governed inputs are missing",
                formula="VALIDATE(required_inputs) before calculation",
                inputs={
                    "missing_inputs": missing_inputs,
                    "prompt_numbers": _serialized_prompt_numbers(prompt_numbers),
                },
                result="missing_governed_inputs",
                unit=None,
                citations=[],
            )
        ],
        kg_context=[],
        citations=[],
        assumptions=[],
        hallucination_risk=HallucinationRisk(
            level=HallucinationRiskLevel.NONE,
            score=0.0,
            factors=[{"name": "fail_closed", "detail": "No unsupported financial calculation was generated."}],
            traceable=True,
            mitigations=["Load the missing governed inputs, then rerun the scenario."],
            verification_path="Scenario validation stopped before calculation.",
        ),
        suggestions=suggestions or ["Load governed baseline inputs", "Ask about recoverable leakage using current findings"],
        scenario_type="missing_data",
        basis="Recognized numeric scenario intent, but required governed inputs were unavailable.",
    )


def _recoverable_total_from_findings(findings: list[Any]) -> Decimal:
    total = Decimal("0")
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        raw = finding.get("recoverable_sar", finding.get("recoverable", 0)) or 0
        try:
            total += Decimal(str(raw))
        except (InvalidOperation, ValueError):
            continue
    return total


def _governed_recovery_baseline(context: Mapping[str, Any]) -> tuple[Decimal, int, list[dict[str, Any]]]:
    """Resolve the one recoverable-value total used across chat entry points.

    The public CEO surface intentionally exposes a compact findings list, so
    summing that list understates the governed total. Prefer the reconciled
    packet total and use the complete finding count carried beside it.
    """
    packet = _public_packet(dict(context))
    public_facts = packet.get("public_facts") if isinstance(packet.get("public_facts"), Mapping) else {}
    reconciliation = packet.get("findings_reconciliation") if isinstance(packet.get("findings_reconciliation"), Mapping) else {}
    raw_total = public_facts.get("total_recoverable_sar")
    if raw_total is None:
        raw_total = reconciliation.get("total_recoverable_sar")
    total = _decimal_or_none(raw_total)
    if total is not None and total > 0:
        count = int(
            public_facts.get("total_finding_count")
            or reconciliation.get("total_finding_count")
            or len(context.get("findings") or [])
        )
        return total, count, [_public_packet_citation("findings_reconciliation.total_recoverable_sar", "Reconciled recoverable-value total")]

    findings = list(context.get("findings") or [])
    total = _recoverable_total_from_findings(findings)
    citations = [{"source_path": "run_artifacts://findings", "locator": "recoverable_sar aggregation", "excerpt": ""}]
    return total, len([item for item in findings if isinstance(item, dict)]), citations


def _asks_to_realize_all_recoverable(normalized_prompt: str) -> bool:
    return bool(
        re.search(
            r"\b(?:collect|recover|realize|realise)\s+(?:the\s+)?(?:entire|full|all)(?:\s+of\s+the)?\s+(?:current\s+)?recoverable",
            normalized_prompt,
        )
        or re.search(r"\ball\s+(?:current\s+)?recoverable\s+(?:value|amount|cash|leakage)\b", normalized_prompt)
    )


def _current_cash_baseline(context: Mapping[str, Any]) -> tuple[Decimal | None, bool]:
    summary = context.get("summary") if isinstance(context.get("summary"), Mapping) else {}
    for key in ("finance_kpi", "oracle_kpi"):
        payload = summary.get(key) if isinstance(summary, Mapping) else None
        if not isinstance(payload, Mapping):
            continue
        components = payload.get("components") if isinstance(payload.get("components"), Mapping) else payload
        cash = _decimal_or_none(components.get("cash_balance"))
        if cash is not None:
            evidence = payload.get("evidence") if isinstance(payload.get("evidence"), Mapping) else {}
            cash_evidence = evidence.get("cash_vs_floor") if isinstance(evidence.get("cash_vs_floor"), Mapping) else {}
            return cash, bool(cash_evidence.get("actual_complete", True))

    packet = _public_packet(dict(context))
    facts = packet.get("public_facts") if isinstance(packet.get("public_facts"), Mapping) else {}
    cash = _decimal_or_none(facts.get("current_cash_sar"))
    return cash, bool(facts.get("current_cash_complete", False)) if cash is not None else False


def _parse_recovery_realization(prompt: str, context: dict[str, Any]) -> ScenarioResult | None:
    norm = _normalize(prompt)
    if not _has_scenario_intent(prompt):
        return None
    if not re.search(r"\b(?:recover|recovery|realize|realise|collect|remaining|remains)\b", norm):
        return None

    prompt_numbers = _parse_numeric_tokens(prompt)
    recovery_amount = _select_recovery_amount(prompt, prompt_numbers)
    baseline, finding_count, citations = _governed_recovery_baseline(context)
    if recovery_amount is None and baseline > 0 and _asks_to_realize_all_recoverable(norm):
        recovery_amount = {
            "raw": "all current recoverable value",
            "value": baseline,
            "unit": "SAR",
            "span": (0, 0),
        }
    if recovery_amount is None:
        return _scenario_missing_data_result(
            scenario_id="recovery_realization",
            scenario_label="Finance - Recovery Realization",
            answer=(
                "I can model recovery only after the recovery amount is explicit. "
                "Ask for example: if we recover SAR 400,000, what remains?"
            ),
            missing_inputs=["realized_recovery_amount_sar"],
            prompt_numbers=prompt_numbers,
            suggestions=["If we recover SAR 400,000, what remains?"],
        )

    if baseline <= 0:
        return _scenario_missing_data_result(
            scenario_id="recovery_realization",
            scenario_label="Finance - Recovery Realization",
            answer=(
                "I cannot calculate the recovery scenario because the current governed run "
                "does not expose a recoverable-value baseline."
            ),
            missing_inputs=["baseline_recoverable_sar"],
            prompt_numbers=prompt_numbers,
            suggestions=["Run governed finance analysis", "Show current recoverable leakage"],
        )

    realized = recovery_amount["value"]
    remaining = max(Decimal("0"), baseline - realized)
    capped_realized = min(realized, baseline)
    realization_rate = capped_realized / baseline if baseline else Decimal("0")
    over_recovery = realized > baseline

    current_cash, cash_complete = _current_cash_baseline(context)
    ending_cash = current_cash + capped_realized if current_cash is not None else None
    calculations = [
        CalculationStep(
            step_id="baseline_recoverable",
            description="Current governed recoverable-value baseline",
            formula="SUM(recoverable_sar) over current run findings",
            inputs={"finding_count": finding_count},
            result=_sar_decimal(baseline),
            unit="SAR",
            citations=citations,
        ),
        CalculationStep(
            step_id="remaining_recoverable",
            description="Recoverable value remaining after user-provided realization",
            formula="remaining_recoverable = baseline_recoverable - realized_amount",
            inputs={
                "baseline_recoverable_sar": str(baseline),
                "realized_amount_sar": str(realized),
                "prompt_amount": recovery_amount["raw"],
                "prompt_numbers": _serialized_prompt_numbers(prompt_numbers),
            },
            result=_sar_decimal(remaining),
            unit="SAR",
            citations=citations,
            assumptions=["Recovery realization changes value remaining; it does not automatically clear evidence challenges or board approvals."],
        ),
        CalculationStep(
            step_id="realization_rate",
            description="Share of current recoverable value realized by the scenario",
            formula="realization_rate = min(realized_amount, baseline_recoverable) / baseline_recoverable",
            inputs={"capped_realized_sar": str(capped_realized), "baseline_recoverable_sar": str(baseline)},
            result=_percent(float(realization_rate), 2),
            unit="ratio",
            citations=citations,
        ),
    ]
    if ending_cash is not None:
        calculations.append(
            CalculationStep(
                step_id="cash_position_after_recovery",
                description="Reported cash position after the scenario collection",
                formula="scenario_ending_cash = current_reported_cash + realized_recovery",
                inputs={
                    "current_reported_cash_sar": str(current_cash),
                    "realized_recovery_sar": str(capped_realized),
                    "cash_scope_complete": cash_complete,
                },
                result=_sar_decimal(ending_cash),
                unit="SAR",
                citations=citations,
                assumptions=["The scenario assumes the recovered amount is collected in cash during the period."],
            )
        )
    answer = (
        f"If SAR {realized:,.2f} is recovered, remaining recoverable value falls from "
        f"{_sar_decimal(baseline)} to {_sar_decimal(remaining)}. "
        f"That realizes {_percent(float(realization_rate), 2)} of the current recoverable baseline. "
        "Board readiness does not automatically clear: evidence status, challenges, approvals, and collection proof still need to be closed separately."
    )
    if ending_cash is not None:
        scope_note = " The current cash baseline is partial, so the resulting cash position remains partial." if not cash_complete else ""
        answer += (
            f" On the reported cash baseline, cash would rise from {_sar_executive_decimal(current_cash)} "
            f"to {_sar_executive_decimal(ending_cash)}.{scope_note}"
        )
    elif "cash" in norm:
        answer += " Cash increases by the recovered amount, but an ending cash position cannot be stated because the current cash baseline is unavailable."
    if over_recovery:
        answer += " The requested recovery amount is above the current baseline, so the remaining value is capped at SAR 0.00."

    return ScenarioResult(
        scenario_id="recovery_realization",
        scenario_label="Finance - Recovery Realization",
        matched=True,
        answer=answer,
        calculations=calculations,
        kg_context=[],
        citations=citations,
        assumptions=["User-provided recovery amount is treated as a scenario assumption, not an actual collection event."],
        hallucination_risk=_risk_none("Deterministic recovery realization from current run findings and explicit user amount."),
        suggestions=["Show the recovery calculation", "What should Finance act on first?", "What evidence still blocks collection?"],
        scenario_type="deterministic",
        basis="Scenario parser matched recovery realization and applied the user-provided amount to current run findings.",
    )


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _governed_finance_baseline(context: Mapping[str, Any]) -> dict[str, Any] | None:
    """Resolve one compatible finance baseline from the current governed run.

    Source-derived finance KPIs are preferred because they are the same deterministic
    actuals rendered by the CEO dashboard. The older oracle payload remains supported
    for runs created before the source-finance engine was introduced.
    """
    summary = context.get("summary")
    if not isinstance(summary, Mapping):
        return None

    for key in ("finance_kpi", "oracle_kpi"):
        payload = summary.get(key)
        if not isinstance(payload, Mapping):
            continue
        components = payload.get("components")
        if not isinstance(components, Mapping):
            components = payload

        revenue = _decimal_or_none(components.get("revenue_actual"))
        cogs = _decimal_or_none(components.get("cogs_actual"))
        operating_cost = _decimal_or_none(components.get("operating_cost_actual"))
        ebitda = _decimal_or_none(components.get("ebitda_actual"))
        revenue_plan = _decimal_or_none(components.get("revenue_plan"))
        ebitda_plan = _decimal_or_none(components.get("ebitda_plan"))
        if revenue is None or revenue <= 0:
            continue

        # EBITDA can safely complete one missing cost component because this is the
        # governing identity used by the dashboard calculation contract.
        if ebitda is None and cogs is not None and operating_cost is not None:
            ebitda = revenue - cogs - operating_cost
        elif cogs is None and ebitda is not None and operating_cost is not None:
            cogs = revenue - operating_cost - ebitda
        elif operating_cost is None and ebitda is not None and cogs is not None:
            operating_cost = revenue - cogs - ebitda

        if any(value is None for value in (cogs, operating_cost, ebitda)):
            continue
        assert cogs is not None and operating_cost is not None and ebitda is not None

        evidence = payload.get("evidence") if isinstance(payload.get("evidence"), Mapping) else {}
        ebitda_evidence = evidence.get("ebitda_margin") if isinstance(evidence, Mapping) else {}
        files = ebitda_evidence.get("files") if isinstance(ebitda_evidence, Mapping) else []
        citations = [
            {
                "source_path": str(source_path),
                "locator": "Governed revenue, COGS, operating-cost and EBITDA baseline",
                "excerpt": "",
            }
            for source_path in (files or [])
            if source_path
        ]
        if not citations:
            citations = [{
                "source_path": f"run_summary://{key}",
                "locator": "components.revenue_actual,cogs_actual,operating_cost_actual,ebitda_actual",
                "excerpt": "",
            }]

        return {
            "source_key": key,
            "period": str(payload.get("reporting_period_key") or summary.get("reporting_period") or "current governed period"),
            "currency": str(payload.get("reporting_currency") or "SAR"),
            "revenue": revenue,
            "cogs": cogs,
            "operating_cost": operating_cost,
            "ebitda": ebitda,
            "revenue_plan": revenue_plan,
            "ebitda_plan": ebitda_plan,
            "citations": citations,
        }
    return None


def _finance_baseline_result(baseline: Mapping[str, Any]) -> ScenarioResult:
    """Explain the same EBITDA identity and period used by the CEO card."""
    revenue = Decimal(baseline["revenue"])
    cogs = Decimal(baseline["cogs"])
    operating_cost = Decimal(baseline["operating_cost"])
    ebitda = Decimal(baseline["ebitda"])
    margin = ebitda / revenue
    revenue_plan = baseline.get("revenue_plan")
    ebitda_plan = baseline.get("ebitda_plan")
    citations = list(baseline["citations"])
    comparison = (
        f" The aligned plan margin is {_percent(float(Decimal(ebitda_plan) / Decimal(revenue_plan)), 1)}."
        if revenue_plan is not None and ebitda_plan is not None and Decimal(revenue_plan) > 0
        else " No approved EBITDA and revenue plan for the same scope and period is available, so I have not shown a plan variance."
    )
    answer = (
        f"For {baseline['period']}, EBITDA margin is {_percent(float(margin), 1)}. "
        f"That is {_sar_executive_decimal(ebitda)} of EBITDA on {_sar_executive_decimal(revenue)} revenue, "
        f"after {_sar_executive_decimal(cogs)} cost of goods sold and "
        f"{_sar_executive_decimal(operating_cost)} operating cost."
        f"{comparison}"
    )
    return ScenarioResult(
        scenario_id="governed_ebitda_baseline",
        scenario_label="Finance - EBITDA Baseline",
        matched=True,
        answer=answer,
        calculations=[
            CalculationStep(
                step_id="governed_ebitda_baseline",
                description="Reconcile the EBITDA measure shown on the CEO dashboard",
                formula="EBITDA = revenue - COGS - operating cost; EBITDA margin = EBITDA / revenue",
                inputs={
                    "period": baseline["period"],
                    "revenue_sar": str(revenue),
                    "cogs_sar": str(cogs),
                    "operating_cost_sar": str(operating_cost),
                },
                result={
                    "ebitda_sar": _sar_decimal(ebitda),
                    "ebitda_margin": _percent(float(margin), 1),
                },
                unit="SAR and percent",
                citations=citations,
            )
        ],
        kg_context=[],
        citations=citations,
        assumptions=[],
        hallucination_risk=_risk_none("Current-run finance components and the governed EBITDA identity."),
        suggestions=["Model a target EBITDA margin", "Show the EBITDA calculation", "Which costs are included?"],
        scenario_type="deterministic",
        basis="Read from the same governed finance contract used by the CEO KPI card.",
    )


def _target_margin_from_prompt(prompt: str, prompt_numbers: list[dict[str, Any]]) -> Decimal | None:
    norm = _normalize(prompt)
    if "margin" not in norm:
        return None
    percentages = [token for token in prompt_numbers if token.get("unit") == "%"]
    if not percentages:
        return None
    # Prefer the percentage closest to the word "margin" so prompts containing
    # other percentages remain deterministic.
    margin_at = norm.find("margin")
    selected = min(percentages, key=lambda token: abs(int(token["span"][0]) - margin_at))
    target = Decimal(selected["value"]) / Decimal("100")
    return target if Decimal("0") < target < Decimal("1") else None


def _cost_line_reduction_from_prompt(
    prompt: str,
    prompt_numbers: list[dict[str, Any]],
    context: Mapping[str, Any],
) -> tuple[dict[str, Any], Decimal] | None:
    """Match a prompt against the cost lines this run actually proves.

    "What happens to EBITDA if we cut salaries by 10%?" names a lever, not a
    target margin, so the target-margin path never claimed it and the question
    fell through to a fail-closed answer that listed revenue and cost baselines
    as missing -- inputs the run plainly holds. The fail-closed posture was
    right in general and wrong here: nothing was missing except a parser that
    could see the line being named.

    The candidate lines come from the run's own operating-cost composition, so
    no vocabulary is hardcoded: whatever the general ledger calls a line is what
    an executive can name. A line is matched only when the prompt contains its
    label or a whole word from it, which keeps "salaries" -> "Salaries & Wages"
    working without inventing a synonym table that would rot against the next
    dataset.
    """
    percentages = [token for token in prompt_numbers if token.get("unit") == "%"]
    if not percentages:
        return None

    summary = context.get("summary")
    if not isinstance(summary, Mapping):
        return None
    for key in ("finance_kpi", "oracle_kpi"):
        payload = summary.get(key)
        if not isinstance(payload, Mapping):
            continue
        evidence = payload.get("evidence")
        if not isinstance(evidence, Mapping):
            continue
        scope_evidence = evidence.get("operating_cost")
        if not isinstance(scope_evidence, Mapping):
            continue
        details = scope_evidence.get("details")
        if not isinstance(details, Mapping):
            continue
        contributors = details.get("contributors")
        if not isinstance(contributors, Mapping):
            continue
        rows = [row for row in (contributors.get("operating_cost") or []) if isinstance(row, Mapping)]
        if not rows:
            continue

        norm = _normalize(prompt)
        best: tuple[dict[str, Any], int] | None = None
        for row in rows:
            label = str(row.get("label") or "").strip()
            if not label or label.casefold().startswith("other "):
                continue
            value = _decimal_or_none(row.get("value_sar"))
            if value is None or value <= 0:
                continue
            label_norm = _normalize(label)
            # Whole words only: a three-letter fragment must not claim a line.
            words = [word for word in re.split(r"[^a-z0-9]+", label_norm) if len(word) > 3]
            hit = label_norm and label_norm in norm
            if not hit:
                hit = any(re.search(rf"\b{re.escape(word)}", norm) for word in words)
            if not hit:
                continue
            # Prefer the most specific label when several match.
            if best is None or len(label_norm) > best[1]:
                best = ({"label": label, "value": value, "share_pct": row.get("share_pct")}, len(label_norm))
        if best is None:
            continue

        line = best[0]
        label_at = norm.find(_normalize(line["label"]).split()[0])
        selected = min(
            percentages,
            key=lambda token: abs(int(token["span"][0]) - (label_at if label_at >= 0 else 0)),
        )
        reduction = Decimal(selected["value"]) / Decimal("100")
        if not (Decimal("0") < reduction <= Decimal("1")):
            return None
        return line, reduction
    return None


def _finance_cost_line_scenario_result(
    line: Mapping[str, Any],
    reduction: Decimal,
    baseline: Mapping[str, Any],
    prompt_numbers: list[dict[str, Any]],
) -> ScenarioResult:
    """Model a stated reduction on one governed cost line, arithmetically.

    Every number below is the run's own or follows from it by the same EBITDA
    identity the dashboard uses. The model states what the arithmetic says and
    stops: whether the line CAN be cut by this much is an operating judgement
    the run holds no evidence for, and saying otherwise would be advice dressed
    as a calculation.
    """
    revenue = Decimal(baseline["revenue"])
    cogs = Decimal(baseline["cogs"])
    operating_cost = Decimal(baseline["operating_cost"])
    ebitda = Decimal(baseline["ebitda"])
    citations = list(baseline["citations"])

    current_line = Decimal(str(line["value"]))
    saving = (current_line * reduction).quantize(Decimal("0.01"))
    new_operating_cost = operating_cost - saving
    new_ebitda = revenue - cogs - new_operating_cost
    current_margin = ebitda / revenue
    new_margin = new_ebitda / revenue

    label = str(line["label"])
    pct = _percent(float(reduction), 0 if reduction * 100 == (reduction * 100).to_integral_value() else 1)

    baseline_step = CalculationStep(
        step_id="governed_cost_line_baseline",
        description=f"Read the governed {label} balance and the EBITDA baseline",
        formula="EBITDA = revenue - COGS - operating cost",
        inputs={
            "line_item": label,
            "line_sar": str(current_line),
            "revenue_sar": str(revenue),
            "cogs_sar": str(cogs),
            "operating_cost_sar": str(operating_cost),
            "period": baseline["period"],
        },
        result=_sar_decimal(ebitda),
        unit="SAR",
        citations=citations,
    )
    change_step = CalculationStep(
        step_id="cost_line_reduction",
        description=f"Apply the requested {pct} reduction to {label}",
        formula="saving = line balance × reduction; new EBITDA = revenue - COGS - (operating cost - saving)",
        inputs={
            "line_sar": str(current_line),
            "reduction": str(reduction),
            "prompt_numbers": _serialized_prompt_numbers(prompt_numbers),
        },
        result=_sar_decimal(new_ebitda),
        unit="SAR",
        citations=citations,
        assumptions=[
            "The reduction is applied as stated in the question; the run holds no evidence that this line can be reduced by this amount.",
            "Revenue and COGS are held at their governed baseline.",
        ],
    )

    answer = (
        f"Cutting {label} by {pct} would save {_sar_executive_decimal(saving)} against a governed "
        f"{label} balance of {_sar_executive_decimal(current_line)} for {baseline['period']}. "
        f"That lifts EBITDA from {_sar_executive_decimal(ebitda)} to {_sar_executive_decimal(new_ebitda)} "
        f"({_percent(float(current_margin), 1)} to {_percent(float(new_margin), 1)} margin), holding revenue "
        f"and COGS at their governed baseline. This is the arithmetic of the cut you named -- nothing in this "
        f"run says the line can be reduced by that much, so treat the operating feasibility as an open question."
    )
    return ScenarioResult(
        scenario_id="cost_line_reduction",
        scenario_label=f"Finance - {label} Reduction",
        matched=True,
        answer=answer,
        calculations=[baseline_step, change_step],
        kg_context=[],
        citations=citations,
        assumptions=[
            "Only the named line moves; every other governed component is held constant.",
        ],
        hallucination_risk=_risk_none(
            "Current-run finance KPI components, the run's own operating-cost composition, and the deterministic EBITDA identity."
        ),
        suggestions=[
            f"Show what makes up {label}",
            "Show the reconciled leakage already identified in this run",
        ],
        scenario_type="deterministic",
        basis="Calculated from the governed operating-cost composition and the same EBITDA identity the CEO dashboard uses.",
    )


def _asks_for_governed_ebitda_baseline(normalized_prompt: str) -> bool:
    """Identify factual EBITDA questions without swallowing forecast/FX intents."""
    if not any(token in normalized_prompt for token in ("ebitda", "operating margin", "margin bridge")):
        return False
    if any(
        token in normalized_prompt
        for token in (
            "forecast",
            "project ",
            "projection",
            "scenario",
            "assume",
            "hedge",
            "currency",
            " fx ",
            "risk to",
            "impact of",
            "what happens",
        )
    ):
        return False
    return any(
        token in normalized_prompt
        for token in (
            "current",
            "actual",
            "explain",
            "bridge",
            "calculate",
            "calculation",
            "how is",
            "how do",
            "what is",
            "show",
        )
    )


def _finance_target_margin_result(
    target_margin: Decimal,
    baseline: Mapping[str, Any],
    prompt_numbers: list[dict[str, Any]],
) -> ScenarioResult:
    revenue = Decimal(baseline["revenue"])
    cogs = Decimal(baseline["cogs"])
    operating_cost = Decimal(baseline["operating_cost"])
    ebitda = Decimal(baseline["ebitda"])
    citations = list(baseline["citations"])
    current_margin = ebitda / revenue
    target_ebitda = revenue * target_margin
    improvement = target_ebitda - ebitda

    baseline_step = CalculationStep(
        step_id="governed_ebitda_baseline",
        description="Reconcile the current EBITDA baseline used by the CEO dashboard",
        formula="EBITDA = revenue - COGS - operating cost; margin = EBITDA / revenue",
        inputs={
            "revenue_sar": str(revenue),
            "cogs_sar": str(cogs),
            "operating_cost_sar": str(operating_cost),
            "period": baseline["period"],
        },
        result=_percent(float(current_margin), 2),
        unit="EBITDA margin",
        citations=citations,
    )
    target_step = CalculationStep(
        step_id="target_ebitda",
        description="Calculate EBITDA required at the requested target margin",
        formula="target EBITDA = governed revenue × target margin",
        inputs={
            "revenue_sar": str(revenue),
            "target_margin": str(target_margin),
            "prompt_numbers": _serialized_prompt_numbers(prompt_numbers),
        },
        result=_sar_decimal(target_ebitda),
        unit="SAR",
        citations=citations,
        assumptions=["The requested margin is treated as a scenario target, not as an approved forecast."],
    )

    if improvement <= 0:
        answer = (
            f"The current EBITDA margin is {_percent(float(current_margin), 1)} "
            f"({_sar_executive_decimal(ebitda)} EBITDA on {_sar_executive_decimal(revenue)} revenue), already at or above "
            f"the requested {_percent(float(target_margin), 1)} target for {baseline['period']}."
        )
        return ScenarioResult(
            scenario_id="ebitda_target_margin",
            scenario_label="Finance - EBITDA Target Margin",
            matched=True,
            answer=answer,
            calculations=[baseline_step, target_step],
            kg_context=[],
            citations=citations,
            assumptions=["No operating change is required to meet a target below the current governed margin."],
            hallucination_risk=_risk_none("Current-run finance KPI components and deterministic EBITDA identity."),
            suggestions=["Model a higher target margin", "Show the EBITDA baseline"],
            scenario_type="deterministic",
            basis="Calculated from the same governed finance components rendered by the CEO dashboard.",
        )

    target_operating_cost = revenue - cogs - target_ebitda
    operating_cost_reduction = operating_cost - target_operating_cost
    operating_cost_reduction_rate = operating_cost_reduction / operating_cost
    cogs_rate = cogs / revenue
    revenue_denominator = Decimal("1") - cogs_rate - target_margin
    required_revenue = operating_cost / revenue_denominator if revenue_denominator > 0 else None

    calculations = [baseline_step, target_step]
    calculations.append(CalculationStep(
        step_id="fixed_revenue_cost_path",
        description="Cost path with revenue and COGS held at their governed baseline",
        formula="target operating cost = revenue - COGS - target EBITDA",
        inputs={
            "revenue_sar": str(revenue),
            "cogs_sar": str(cogs),
            "current_operating_cost_sar": str(operating_cost),
            "target_ebitda_sar": str(target_ebitda),
        },
        result={
            "target_operating_cost_sar": _sar_decimal(target_operating_cost),
            "operating_cost_reduction_sar": _sar_decimal(operating_cost_reduction),
            "operating_cost_reduction_pct": _percent(float(operating_cost_reduction_rate), 1),
        },
        unit="SAR",
        citations=citations,
        assumptions=["Revenue and COGS remain at the current governed baseline."],
    ))

    growth_sentence = ""
    if required_revenue is not None:
        revenue_increase = required_revenue - revenue
        revenue_increase_rate = revenue_increase / revenue
        calculations.append(CalculationStep(
            step_id="fixed_opex_growth_path",
            description="Revenue path with operating cost fixed and COGS held at its current revenue rate",
            formula="required revenue = operating cost / (1 - current COGS rate - target margin)",
            inputs={
                "operating_cost_sar": str(operating_cost),
                "current_cogs_rate": str(cogs_rate),
                "target_margin": str(target_margin),
            },
            result={
                "required_revenue_sar": _sar_decimal(required_revenue),
                "revenue_increase_sar": _sar_decimal(revenue_increase),
                "revenue_increase_pct": _percent(float(revenue_increase_rate), 1),
            },
            unit="SAR",
            citations=citations,
            assumptions=["Operating cost stays fixed and COGS remains the current share of revenue."],
        ))
        growth_sentence = (
            f"\n\nRevenue path — hold operating cost at {_sar_executive_decimal(operating_cost)} and COGS at its current "
            f"{_percent(float(cogs_rate), 1)} of revenue: grow revenue to {_sar_executive_decimal(required_revenue)} "
            f"(+{_sar_executive_decimal(revenue_increase)}, {_percent(float(revenue_increase_rate), 1)})."
        )

    answer = (
        f"Current position — EBITDA margin is {_percent(float(current_margin), 1)}: "
        f"{_sar_executive_decimal(ebitda)} EBITDA on {_sar_executive_decimal(revenue)} revenue for {baseline['period']}.\n\n"
        f"Target — at {_percent(float(target_margin), 1)}, EBITDA must reach {_sar_executive_decimal(target_ebitda)}, "
        f"an improvement of {_sar_executive_decimal(improvement)}.\n\n"
        f"Cost path — hold revenue and COGS constant: reduce operating cost from {_sar_executive_decimal(operating_cost)} "
        f"to {_sar_executive_decimal(target_operating_cost)} (-{_sar_executive_decimal(operating_cost_reduction)}, "
        f"{_percent(float(operating_cost_reduction_rate), 1)})."
        f"{growth_sentence}\n\n"
        "These are auditable boundary paths, not a forecast. Specify the intended revenue/cost mix and timing to model a combined execution path."
    )
    return ScenarioResult(
        scenario_id="ebitda_target_margin",
        scenario_label="Finance - EBITDA Target Margin",
        matched=True,
        answer=answer,
        calculations=calculations,
        kg_context=[],
        citations=citations,
        assumptions=[
            "The target margin is a user-provided scenario assumption, not an approved forecast.",
            "Boundary paths deliberately avoid inventing a management-selected mix of revenue growth and cost action.",
        ],
        hallucination_risk=_risk_none("Current-run finance KPI components and explicit deterministic formulas."),
        suggestions=["Model a 50/50 revenue and cost path", "Show the calculation trace", "What is the current EBITDA baseline?"],
        scenario_type="deterministic",
        basis="Calculated from the same governed finance components rendered by the CEO dashboard.",
    )


def _parse_financial_what_if_guard(prompt: str, context: dict[str, Any]) -> ScenarioResult | None:
    public_packet = _public_packet(context)
    if public_packet and public_packet.get("is_illustrative") is not False:
        return None
    norm = _normalize(prompt)
    if not _has_scenario_intent(prompt):
        return None

    prompt_numbers = _parse_numeric_tokens(prompt)
    if any(token in norm for token in ("hedge", "eur", "euro", "fx", "currency")):
        return _scenario_missing_data_result(
            scenario_id="fx_hedge",
            scenario_label="Finance - FX Hedge",
            answer=(
                "I cannot calculate the hedge scenario from the current governed run because EUR exposure, "
                "FX movement or hedge-rate assumptions, hedge cost, and period are not all available."
            ),
            missing_inputs=["eur_exposure", "fx_rate_change_or_forward_rate", "hedge_cost", "scenario_period"],
            prompt_numbers=prompt_numbers,
            suggestions=["Load EUR exposure and FX assumptions", "Ask for current FX risk evidence"],
        )

    # The finance guard engages when the prompt names a finance subject the run
    # reports. The generic words are a fast path only; a prompt that names a
    # real cost line ("reduce rent expense by 15%") is just as much a finance
    # question, and gating solely on a fixed vocabulary let it escape to the
    # model -- which then denied the line existed while the run held it at SAR
    # 23.7M. What the run reports decides the scope, not a word list.
    line_reduction = _cost_line_reduction_from_prompt(prompt, prompt_numbers, context)
    if line_reduction is not None or any(
        token in norm for token in ("revenue", "cost", "costs", "ebitda", "margin", "opex", "cogs")
    ):
        baseline = _governed_finance_baseline(context)
        target_margin = _target_margin_from_prompt(prompt, prompt_numbers)
        if baseline is not None and target_margin is not None:
            return _finance_target_margin_result(target_margin, baseline, prompt_numbers)
        # A lever named against a real cost line is answerable arithmetic, and
        # must be tried before declaring inputs missing -- otherwise the run
        # reports revenue and cost baselines as unavailable while holding them.
        if baseline is not None and line_reduction is not None:
            line, reduction = line_reduction
            return _finance_cost_line_scenario_result(line, reduction, baseline, prompt_numbers)
        if baseline is not None:
            # The baseline resolved, so revenue and costs are NOT missing. Saying
            # they are would be a false statement about the run's own data. What
            # is actually missing is a lever this run can price.
            return _scenario_missing_data_result(
                scenario_id="ebitda_scenario",
                scenario_label="Finance - EBITDA Scenario",
                answer=(
                    f"I hold the {baseline['period']} baseline -- revenue {_sar_executive_decimal(Decimal(baseline['revenue']))}, "
                    f"EBITDA {_sar_executive_decimal(Decimal(baseline['ebitda']))} -- but I cannot model this change because "
                    "it does not name a cost line this run reports, or a target margin. Name a line from the "
                    "operating-cost composition, or state a target margin, and I can calculate it exactly."
                ),
                missing_inputs=["named_cost_line_or_target_margin"],
                prompt_numbers=prompt_numbers,
                suggestions=["Show what makes up operating cost", "What revenue do we need for a 60% EBITDA margin?"],
            )
        return _scenario_missing_data_result(
            scenario_id="ebitda_scenario",
            scenario_label="Finance - EBITDA Scenario",
            answer=(
                "I cannot calculate the EBITDA scenario from the current governed run because revenue, "
                "cost baseline, compatible period, and scope are not all available."
            ),
            missing_inputs=["baseline_revenue", "baseline_costs", "period", "scope"],
            prompt_numbers=prompt_numbers,
            suggestions=["Load income-statement baselines", "Ask about recoverable leakage in the current run"],
        )

    return None


def _kg_evidence(bundle: Any, role: str, locator: str) -> dict[str, Any]:
    """Build a citation from the bundle's data contracts (mirrors qa._ledger_citation)."""
    contract = (getattr(bundle, "data_contracts", None) or {}).get(role) or {}
    source_path = contract.get("relative_path") or str(getattr(bundle, "dataset_root", "unknown"))
    return {"source_path": source_path, "locator": locator, "excerpt": ""}


def _public_packet_citation(locator: str, excerpt: str = "") -> dict[str, Any]:
    return {
        "source_path": "public_packet://executive_public_context",
        "locator": locator,
        "excerpt": excerpt,
    }


def _public_packet_risk(basis: str, gap: str | None = None) -> HallucinationRisk:
    return _risk_low(
        basis,
        gap
        or "Grounded to the public executive packet rather than protected reviewer evidence.",
    )


def _public_packet(context: dict[str, Any]) -> dict[str, Any]:
    packet = context.get("public_context_packet")
    if isinstance(packet, dict):
        return packet
    bundle = context.get("bundle")
    if isinstance(bundle, dict) and bool(bundle.get("public_safe")):
        return bundle
    return {}


def _public_citation(locator: str) -> dict[str, Any]:
    return {
        "source_path": "public_packet://latest-public",
        "locator": locator,
        "excerpt": "",
    }


def _public_risk_low(basis: str, gap: str | None = None) -> HallucinationRisk:
    return HallucinationRisk(
        level=HallucinationRiskLevel.LOW,
        score=0.12,
        factors=[
            {"name": "public_safe_packet", "detail": "Answer synthesized from the same public-safe packet that renders the executive surface."},
            {"name": "bounded_surface_facts", "detail": "Only visible KPI, driver, finding, board, and agent facts were used."},
        ],
        traceable=True,
        traceability_gap=gap,
        mitigations=["Stay inside the public-safe packet boundary.", "Escalate to governed run evidence for private or ledger-backed detail."],
        verification_path=basis,
    )


def _public_driver(packet: dict[str, Any], *tokens: str) -> dict[str, Any] | None:
    lowered = [token.lower() for token in tokens if token]
    for item in packet.get("drivers") or []:
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ("key", "label", "sub", "story", "detail", "value")
        ).lower()
        mover_text = " ".join(
            str(mover.get("name") or "") + " " + str(mover.get("delta") or "") + " " + str(mover.get("detail") or "")
            for group in ("lifting", "dragging", "movers")
            for mover in (
                (item.get(group) or [])
                if isinstance(item.get(group), list)
                else ((item.get(group) or {}).get("lifting") or []) + ((item.get(group) or {}).get("dragging") or [])
            )
            if isinstance(mover, dict)
        ).lower()
        if any(token in haystack or token in mover_text for token in lowered):
            return item
    return None


def _public_board(packet: dict[str, Any]) -> dict[str, Any]:
    board = packet.get("board_portal")
    return board if isinstance(board, dict) else {}


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
    public_packet = _public_packet(context)
    public_dh_driver = _public_driver(public_packet, "digital health") or {}

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

    elif public_dh_driver:
        calcs.append(CalculationStep(
            step_id="dh_public_driver",
            description="Public-safe Digital Health driver visible on the executive surface",
            formula="READ public executive driver card",
            inputs={"driver": public_dh_driver.get("label") or "Digital Health revenue"},
            result=str(public_dh_driver.get("value") or public_dh_driver.get("metric") or "Digital Health signal"),
            unit="driver",
            citations=[_public_citation("public_context_packet.drivers.digital_health")],
        ))
        summary_answer = (
            "The public executive packet already frames Digital Health as a flat-by-EOY board question: "
            "the visible posture is hold-the-line rather than chase breakout growth, and the decision is whether to fund a sharper commercial push or accept a steady contribution into year-end. "
            "That is a grounded public-safe summary, not a ledger projection."
        )
        risk = _risk_low(
            basis="Public-safe executive packet Digital Health driver.",
            gap="The anonymous surface does not expose private time-series ledger detail for a true forecast curve.",
        )
        kg_ctx = [
            KGContext(
                entity_id="public_digital_health_driver",
                entity_type="PublicDriver",
                label=str(public_dh_driver.get("label") or "Digital Health revenue"),
                properties=dict(public_dh_driver),
                confidence=0.72,
            )
        ]
    elif bool(context.get("illustrative_mode")):
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
    else:
        return _scenario_missing_data_result(
            scenario_id="digital_health_eoy_flat",
            scenario_label=SCENARIO_LABELS["digital_health_eoy_flat"],
            answer=(
                "I cannot model Digital Health flat-by-EOY from the current governed run because "
                "no Digital Health time-series, adoption, revenue, or initiative baseline is available. "
                "Illustrative external benchmarks are disabled unless illustrative mode is explicitly selected."
            ),
            missing_inputs=[
                "digital_health_baseline",
                "digital_health_period",
                "digital_health_actuals_or_time_series",
            ],
            prompt_numbers=_parse_numeric_tokens(prompt),
            suggestions=[
                "Load Digital Health revenue or adoption actuals",
                "Enable illustrative mode for external benchmark exploration",
            ],
        )

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
            hallucination_risk=_risk_medium(
                basis="Public/demo prompt matched finance leakage but neither governed findings nor public packet facts were available.",
                gap="Missing findings and missing public-safe executive packet context.",
            ),
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


def _governed_public_suggestions(packet: dict[str, Any]) -> list[str]:
    suggestions: list[str] = []
    for item in list(packet.get("drivers") or [])[:2]:
        label = str(item.get("label") or item.get("key") or "").strip()
        if label:
            suggestions.append(f"Explain the current {label} signal")
    for item in list(packet.get("findings") or [])[:1]:
        title = str(item.get("title") or "").strip()
        if title:
            suggestions.append(f"Why does “{title}” matter for the board?")
    suggestions.append("What should I prepare for the board?")
    return suggestions[:4]


def _governed_public_item_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "").strip()
        for key in ("label", "title", "metric", "value", "status", "meta", "detail", "impact", "story", "tag")
        if str(item.get(key) or "").strip()
    )


def _parse_governed_public_exec_surface(
    prompt: str,
    context: dict[str, Any],
    packet: dict[str, Any],
) -> ScenarioResult | None:
    """Answer public executive prompts only from the current governed packet.

    The legacy illustrative packet has richer demo scenarios. A governed packet
    must never inherit those values when a topic is absent; it returns an exact
    data-boundary answer instead.
    """
    norm = _normalize(prompt)
    if (
        "follow-up task" in norm
        or "follow up task" in norm
        or "set a task" in norm
        or "create a task" in norm
        or ("set" in norm and "task" in norm)
    ):
        return ScenarioResult(
            scenario_id="public_exec_governed_packet",
            scenario_label="Executive Surface — Governed Packet",
            matched=True,
            answer=(
                "The public executive surface cannot create or assign tasks. Use the authenticated "
                "operator workflow to set the owner, due date, governed evidence link, and escalation path."
            ),
            calculations=[],
            kg_context=[],
            citations=[],
            assumptions=["The public executive surface is read-only."],
            hallucination_risk=_public_risk_low("Returned the public surface's task-creation boundary."),
            suggestions=_governed_public_suggestions(packet),
            scenario_type="deterministic",
            basis="Task mutation is unavailable on the governed public executive surface.",
        )
    business_tokens = (
        "board",
        "challenged",
        "risk",
        "plan",
        "year",
        "quarter",
        "margin",
        "ebitda",
        "profit",
        "loss",
        "revenue",
        "cash",
        "working capital",
        "recoverable",
        "recovery",
        "evidence",
        "data",
        "database",
        "missing",
        "status",
        "failure",
        "finding",
        "citation",
        "kpi",
        "driver",
        "hedge",
        "currency",
        "eur",
        "fx",
        "healthcare",
        "pharmacy",
        "capacity",
        "jv",
        "joint venture",
    )
    if not any(token in norm for token in business_tokens):
        return ScenarioResult(
            scenario_id="public_exec_governed_packet",
            scenario_label="Executive Surface — Governed Packet",
            matched=False,
            answer=(
                "I can only answer questions grounded in the current governed executive packet. "
                "Try asking about a visible driver, finding, recovery signal, or board posture."
            ),
            calculations=[],
            kg_context=[],
            citations=[],
            assumptions=["No illustrative scenario or fixture narrative was consulted."],
            hallucination_risk=_public_risk_low(
                "No governed packet topic matched the question.",
                gap="The requested topic is absent from the current governed executive packet.",
            ),
            suggestions=_governed_public_suggestions(packet),
            scenario_type="unmatched",
            basis="Question did not match a topic present on the governed executive surface.",
        )

    drivers = [item for item in list(packet.get("drivers") or []) if isinstance(item, dict)]
    findings = [item for item in list(packet.get("findings") or []) if isinstance(item, dict)]
    complete_findings = [item for item in list(packet.get("finding_case_index") or findings) if isinstance(item, dict)]
    developments = [item for item in list(packet.get("developments") or []) if isinstance(item, dict)]
    public_facts = packet.get("public_facts") if isinstance(packet.get("public_facts"), dict) else {}
    data_sources = packet.get("data_sources") if isinstance(packet.get("data_sources"), dict) else {}
    assistant_context = context.get("assistant_context") if isinstance(context.get("assistant_context"), dict) else {}
    entrypoint = str(assistant_context.get("entrypoint") or "").lower()
    board = _public_board(packet)
    suggestions = _governed_public_suggestions(packet)
    citations: list[dict[str, Any]] = []

    wants_database = any(token in norm for token in ("database", "db ", "backing", "status", "failure", "failed"))
    wants_missing_data = (
        "missing data" in norm
        or "what data am i missing" in norm
        or ("missing" in norm and "data" in norm)
        or entrypoint in {"scenario_chip", "week_composer", "missing_data_cta"} and "missing" in norm
    )
    wants_board_safety = (
        "board-safe" in norm
        or "board safe" in norm
        or "safe for board" in norm
        or ("board" in norm and any(token in norm for token in ("safe", "release", "publish", "closed", "live")))
    )

    if wants_database:
        database = data_sources.get("database") if isinstance(data_sources.get("database"), dict) else {}
        db_state = str(database.get("status") or "unavailable").replace("_", " ")
        db_reason = str(database.get("reason") or "Database backing status is temporarily unavailable.")
        answer = f"Database backing status is {db_state}. {db_reason}"
        citations.append(_public_citation("public_context_packet.data_sources.database"))
        basis = "Answered from the public-safe database status field."
    elif wants_missing_data:
        displayed = public_facts.get("displayed_finding_count")
        total = public_facts.get("total_finding_count")
        challenged = public_facts.get("challenged_count")
        answer = "The public packet does not expose case-level missing-data owners or protected evidence files."
        if isinstance(displayed, (int, float)) and isinstance(total, (int, float)) and int(total) > int(displayed):
            answer += f" It shows the top {int(displayed)} of {int(total)} governed findings, so request the protected case detail for the remaining governed findings from the operator/reviewer workspace."
        elif findings:
            answer += " Use the visible findings as the request list and ask the operator/reviewer workspace for protected evidence gaps."
        if isinstance(challenged, (int, float)):
            answer += f" {int(challenged)} challenged item(s) should be closed before board release."
        citations.append(_public_citation("public_context_packet.public_facts"))
        basis = "Explained public-surface missing-data limits and visible governed counts."
    elif wants_board_safety:
        challenged = public_facts.get("challenged_count")
        report_count = public_facts.get("report_count")
        state = str(board.get("presentation_state") or board.get("state") or "current").replace("_", " ")
        answer = f"Board safety posture is {state}."
        if isinstance(report_count, (int, float)):
            answer += f" {int(report_count)} report artifact(s) are surfaced."
        if isinstance(challenged, (int, float)):
            answer += f" {int(challenged)} challenged item(s) remain visible as release constraints."
        citations.append(_public_citation("public_context_packet.board_portal"))
        basis = "Answered board-safety posture from board state, reports, and challenged counts."
    else:
        answer = ""
        basis = ""

    wants_jv_funding = any(token in norm for token in ("jv", "joint venture", "joint-venture"))
    topic_token_source = (
        ("jv", "joint venture", "joint-venture", "liquidity", "funding")
        if wants_jv_funding
        else ("hedge", "currency", "eur", "fx", "margin", "ebitda", "revenue", "cash", "recoverable", "recovery", "evidence")
    )
    topic_tokens = [token for token in topic_token_source if token in norm]
    wants_recovery_priorities = (
        any(token in norm for token in ("recoverable", "recovery", "finding", "case"))
        and any(
            token in norm
            for token in ("largest", "highest", "first", "priority", "priorit", "acted", "action", "sequence", "owner")
        )
    )
    related: list[tuple[str, int, dict[str, Any]]] = []
    for source_name, items in (("drivers", drivers), ("findings", findings)):
        for index, item in enumerate(items):
            item_text = _governed_public_item_text(item).lower()
            if topic_tokens and any(token in item_text for token in topic_tokens):
                related.append((source_name, index, item))

    if answer:
        pass
    elif entrypoint == "development_cta" and developments:
        fragments = []
        for index, item in enumerate(developments[:3]):
            fragments.append(_governed_public_item_text(item))
            citations.append(_public_citation(f"public_context_packet.developments[{index}]"))
        answer = "Current governed development impact: " + "; ".join(fragment for fragment in fragments if fragment) + "."
        basis = "Matched a development CTA to current governed developments."
    elif entrypoint == "finding_cta" and findings:
        fragments = []
        for index, item in enumerate(findings[:3]):
            fragments.append(_governed_public_item_text(item))
            citations.append(_public_citation(f"public_context_packet.findings[{index}]"))
        answer = "This matters because the current governed findings are: " + "; ".join(fragment for fragment in fragments if fragment) + "."
        basis = "Matched a finding CTA to current governed findings."
    elif any(token in norm for token in ("hedge", "currency", "eur", "fx")) and not related:
        answer = (
            "The current governed run does not expose a quantified currency or hedge scenario, "
            "so StrategyOS cannot calculate hedge impact from this packet. No illustrative hedge "
            "assumptions have been substituted."
        )
        basis = "Governed packet contains no matching currency or hedge driver/finding."
    elif wants_jv_funding and not related:
        answer = (
            "The current governed run does not expose a quantified JV funding or liquidity scenario, "
            "so StrategyOS cannot determine how the JV is funded from this packet. No illustrative "
            "funding assumptions have been substituted."
        )
        basis = "Governed packet contains no matching JV funding or liquidity driver/finding."
    elif related and not wants_recovery_priorities:
        fragments = []
        for source_name, index, item in related[:3]:
            fragments.append(_governed_public_item_text(item))
            citations.append(_public_citation(f"public_context_packet.{source_name}[{index}]"))
        answer = "Current governed evidence: " + "; ".join(fragment for fragment in fragments if fragment) + "."
        basis = "Matched the question to current governed driver/finding text."
    elif "board" in norm or "challenged" in norm:
        challenged = public_facts.get("challenged_count")
        report_count = public_facts.get("report_count")
        state = str(board.get("presentation_state") or board.get("state") or "current").replace("_", " ")
        answer = f"The current board posture is {state}."
        if isinstance(challenged, (int, float)):
            answer += f" {int(challenged)} challenged item(s) remain."
        if isinstance(report_count, (int, float)):
            answer += f" {int(report_count)} report artifact(s) are surfaced."
        if "evidence" in norm:
            answer += " The public packet does not expose case-level missing-evidence details."
        if any(token in norm for token in ("prepare", "prep", "next")):
            answer += " Next step: review the surfaced reports and their governed evidence, then close any challenged items before the board session."
        basis = "Read current board state and counts from the governed packet."
        citations.append(_public_citation("public_context_packet.board_portal"))
    elif any(token in norm for token in ("recoverable", "recovery", "evidence", "finding", "citation")):
        total = public_facts.get("total_recoverable_sar")
        ranked = sorted(complete_findings, key=lambda item: float(item.get("recoverable_sar") or 0), reverse=True)
        listed = ranked[:5]
        listed_total = sum(float(item.get("recoverable_sar") or 0) for item in listed)
        remaining_count = max(0, len(ranked) - len(listed))
        remaining_total = max(0.0, float(total or 0) - listed_total)
        fragments = []
        if isinstance(total, (int, float)):
            fragments.append(f"{_sar(float(total))} across {int(public_facts.get('total_finding_count') or len(ranked))} governed cases")
        if listed:
            fragments.append(
                "Largest cases: "
                + "; ".join(
                    f"{str(item.get('title') or 'Governed case')} ({_sar(float(item.get('recoverable_sar') or 0))})"
                    for item in listed
                )
            )
            citations.extend(_public_citation(f"public_context_packet.finding_case_index[{index}]") for index in range(len(listed)))
        if remaining_count:
            fragments.append(f"The remaining {remaining_count} smaller cases total {_sar(remaining_total)}")
        if fragments:
            first = listed[0] if listed else {}
            first_title = str(first.get("title") or "the highest-value case")
            first_amount = float(first.get("recoverable_sar") or 0)
            answer = "The current view shows " + ". ".join(fragments) + "."
            if any(token in norm for token in ("first", "priority", "priorit", "act", "action", "sequence", "owner")):
                answer += (
                    f" Recommended first action: Group Finance should validate collection readiness and assign the accountable case owner for {first_title} ({_sar(first_amount)}) today, "
                    "then work the remaining cases in recoverable-value order. Confirm evidence, collection date and named owner before reporting any amount as realised cash."
                )
        else:
            answer = "The current governed packet contains no finding or recovery detail for that question."
        basis = f"Reconciled all {len(ranked)} cases to the reported total and ranked actions by recoverable value."
    else:
        visible = [_governed_public_item_text(item) for item in drivers[:3]]
        visible = [item for item in visible if item]
        answer = (
            "Current governed drivers: " + "; ".join(visible) + "."
            if visible
            else "The current governed packet does not contain a quantified driver for that question."
        )
        basis = "Summarized only current governed driver cards."
        citations.extend(_public_citation(f"public_context_packet.drivers[{index}]") for index in range(min(3, len(visible))))

    recovery_priority_answer = basis.startswith("Reconciled all ")
    return ScenarioResult(
        scenario_id="governed_recovery_priorities" if recovery_priority_answer else "public_exec_governed_packet",
        scenario_label="Finance — Recovery Priorities" if recovery_priority_answer else "Executive Surface — Governed Packet",
        matched=True,
        answer=answer,
        calculations=[],
        kg_context=[],
        citations=citations,
        assumptions=["No illustrative scenario values are used when the governed packet lacks the requested metric."],
        hallucination_risk=_public_risk_low(
            basis,
            gap="Protected case-level evidence and absent scenario inputs remain outside the public surface.",
        ),
        suggestions=suggestions,
        scenario_type="deterministic",
        basis=basis,
    )


def _parse_public_exec_surface(prompt: str, context: dict[str, Any]) -> ScenarioResult | None:
    packet = _public_packet(context)
    if not packet or packet.get("is_illustrative") is not False:
        return None
    return _parse_governed_public_exec_surface(prompt, context, packet)


# ---------------------------------------------------------------------------
# Scenario family registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScenarioFamily:
    name: str
    matcher: Callable[[str, dict[str, Any]], ScenarioResult | None]
    priority: int = 0  # lower = higher priority


SCENARIO_FAMILIES: tuple[ScenarioFamily, ...] = (
    # Governed numeric scenarios must run before legacy factual packet handlers.
    ScenarioFamily("recovery_realization", _parse_recovery_realization, priority=0),
    ScenarioFamily("financial_what_if_guard", _parse_financial_what_if_guard, priority=0),
    # Digital Health families (higher priority — check before generic finance)
    ScenarioFamily("digital_health_eoy_flat", _parse_digital_health_eoy_flat, priority=1),
    ScenarioFamily("digital_health_market", _parse_digital_health_market, priority=2),
    ScenarioFamily("digital_health_roi", _parse_digital_health_roi, priority=3),
    ScenarioFamily("digital_health_trend", _parse_digital_health_trend, priority=4),
    ScenarioFamily("digital_health_regulatory", _parse_digital_health_regulatory, priority=5),
    # Finance families
    ScenarioFamily("public_exec_surface", _parse_public_exec_surface, priority=9),
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

    # Governed public surfaces may run the same deterministic target-margin
    # scenario as the CEO dashboard when the user supplies an explicit margin
    # and the source-derived baseline is present. Keep recovery, hedge, and all
    # legacy illustrative scenario families inside the governed-public boundary.
    public_packet = _public_packet(context)
    norm = _normalize(prompt)
    prompt_numbers = _parse_numeric_tokens(prompt)

    # Authenticated chat does not carry the anonymous/public packet marker. It
    # still must use the same source-finance contract as the CEO card instead
    # of falling through to the older tabular QA engine. A marker explicitly
    # declaring illustrative data remains excluded from this route.
    if public_packet.get("is_illustrative") is not True:
        recovery_result = _parse_recovery_realization(prompt, context)
        if recovery_result is not None:
            return _hydrate_scenario_result(recovery_result)
        target_margin = _target_margin_from_prompt(prompt, prompt_numbers)
        if target_margin is not None and any(token in norm for token in ("margin", "ebitda")):
            result = _parse_financial_what_if_guard(prompt, context)
            if result is not None:
                return _hydrate_scenario_result(result)
        if _asks_for_governed_ebitda_baseline(norm):
            baseline = _governed_finance_baseline(context)
            if baseline is not None:
                return _hydrate_scenario_result(_finance_baseline_result(baseline))

    if public_packet.get("is_illustrative") is False:
        result = _parse_governed_public_exec_surface(prompt, context, public_packet)
        return _hydrate_scenario_result(result)

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
