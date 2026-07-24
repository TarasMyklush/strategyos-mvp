from __future__ import annotations

from typing import Any, Mapping

from .executive_read_model import provenance_summary


def _claim_value(claim: Mapping[str, Any] | None, fallback: Any = None) -> Any:
    if not isinstance(claim, Mapping):
        return fallback
    return claim.get("value", fallback)


def _provenance(claim: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(claim, Mapping):
        return None
    provenance = claim.get("provenance")
    return dict(provenance) if isinstance(provenance, Mapping) else None


def _format_sar(value: Any) -> str:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return "--"
    absolute = abs(number)
    if absolute >= 1_000_000:
        return f"SAR {number / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"SAR {round(number / 1_000):,.0f}K"
    return f"SAR {round(number):,}"


def _as_money(value: Any) -> float | None:
    """A money figure the run actually carries, or nothing."""
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _headline_with_value(
    recoverable_total: float | None,
    finding_count: int,
    *,
    fallback: str,
) -> str:
    """Lead the hero with what was found, not with where it sits in our workflow.

    "Reviewer decision is still open" describes the state of this product. An
    executive opening the page wants the state of their business: money
    identified, and how many issues carry it. The sign-off is the qualifier and
    belongs in the sentence below, not in the headline.

    When the run proves no recoverable value, there is no business fact to lead
    with and the workflow sentence is the honest headline -- so the caller's
    fallback stands rather than a manufactured number.
    """
    if not recoverable_total or finding_count <= 0:
        return fallback
    issue_word = "issue" if finding_count == 1 else "issues"
    return f"{_format_sar(recoverable_total)} identified across {finding_count} {issue_word}"


def _ratio_display(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "--"
    total = int(value.get("total") or 0)
    if total <= 0 or value.get("resolved") is None:
        return "--"
    resolved = int(value.get("resolved") or 0)
    if resolved < 0 or resolved > total:
        return "--"
    return f"{resolved} / {total}"


def _humanize(value: Any, fallback: str = "Unavailable") -> str:
    text = str(value or "").replace("_", " ").replace("-", " ").strip()
    return text.title() if text else fallback


def _metric_card(
    key: str,
    label: str,
    claim: Mapping[str, Any],
    *,
    formatter: str = "plain",
    detail: str,
    sub: str,
) -> dict[str, Any]:
    raw_value = _claim_value(claim)
    if formatter == "sar":
        metric = _format_sar(raw_value)
    elif formatter == "ratio":
        metric = _ratio_display(raw_value)
    else:
        metric = str(raw_value if raw_value is not None else "--")
    return {
        "driver_key": key,
        "key": key,
        "label": label,
        "metric": metric,
        "value": metric,
        "status": sub,
        "detail": detail,
        "pct": None,
        "sub": sub,
        "chips": [],
        "movers": {"lifting": [], "dragging": []},
        "trend": {"actual": [], "plan": []},
        "provenance": _provenance(claim),
    }


_CEO_KPI_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "revenue",
        "label": "Revenue",
        "actual": "revenue_actual",
        "comparator": "revenue_plan",
        "formula": "Revenue = sum of scoped revenue-account balances for the selected period.",
        "inputs": ("Scoped revenue facts", "Approved revenue plan"),
        "unit": "SAR",
    },
    {
        "key": "ebitda_margin",
        "label": "EBITDA margin",
        "actual": "ebitda_actual",
        "denominator": "revenue_actual",
        "plan_numerator": "ebitda_plan",
        "plan_denominator": "revenue_plan",
        "formula": "EBITDA margin = EBITDA ÷ Revenue; variance to plan is shown in basis points.",
        "inputs": ("Scoped EBITDA facts", "Scoped revenue facts", "Approved EBITDA plan", "Approved revenue plan"),
        "unit": "percent",
    },
    {
        "key": "operating_cost",
        "label": "Operating cost",
        "actual": "operating_cost_actual",
        "comparator": "operating_cost_plan",
        "formula": "Operating cost = sum of scoped operating-expense balances for the selected period.",
        "inputs": ("Scoped operating-cost facts", "Approved operating-cost plan"),
        "unit": "SAR",
        "inverse": True,
    },
    {
        "key": "cash_vs_floor",
        "label": "Cash vs floor",
        "actual": "cash_balance",
        "comparator": "board_floor",
        "formula": "Cash vs floor = latest scoped cash and cash-equivalent balance ÷ approved board cash floor.",
        "inputs": ("Latest scoped cash balance", "Approved board cash floor"),
        "unit": "SAR",
    },
)


def _number_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _percent_display(value: float | None) -> str:
    return "--" if value is None else f"{value:.1f}%"


def _basis_points_display(value: float | None) -> str:
    if value is None:
        return "Plan comparison unavailable"
    rounded = round(value)
    return f"{rounded:+d} bps vs plan"


def _source_title(path: Any) -> str:
    """Return a CEO-readable source label without losing the raw trail."""
    value = str(path or "")
    lowered = value.lower()
    if "gl_extract" in lowered:
        return "General ledger extract"
    if "chart_of_accounts" in lowered:
        return "Chart of accounts"
    if "cash_forecast" in lowered or "cash_position" in lowered:
        return "Treasury cash position"
    return "Finance source"


def _governed_strategic_reference(payload: Mapping[str, Any], key: str) -> dict[str, str] | None:
    """Return an optional strategic reference only when its source is supplied.

    A strategic target can provide useful context, but it must never be a
    presentation constant.  The standard source-pack path currently does not
    supply one, so this function intentionally returns ``None`` for the H1
    dataset.  A future governed input must name its source explicitly.
    """
    references = payload.get("strategic_references")
    item = references.get(key) if isinstance(references, Mapping) else None
    if not isinstance(item, Mapping):
        return None
    label = str(item.get("label") or "").strip()
    value = str(item.get("value") or "").strip()
    source = str(item.get("source") or "").strip()
    if not label or not value or not source:
        return None
    note = str(item.get("note") or "Reference only; not used as a period comparison.").strip()
    return {"label": label, "value": value, "note": note, "source": source}


def _executive_kpi_signal(
    spec: Mapping[str, Any],
    *,
    actual: float,
    components: Mapping[str, Any],
    missing_inputs: list[str],
    actual_complete: bool,
) -> dict[str, Any]:
    """Translate a finance calculation into a CEO posture and next move.

    The calculation remains available in the audit trail.  This contract is
    intentionally about intervention: whether the position is material, what
    direction it is moving in, and whether the CEO needs to act.
    """
    key = str(spec["key"])
    if missing_inputs or not actual_complete:
        return {
            "posture": "Comparison pending",
            "variance_label": "No like-for-like comparator",
            "tone": "neutral",
            "action_required": False,
            "readout": "The current actual is available, but a CEO performance conclusion is not yet safe.",
            "decision": "Keep this with the Group CFO until the period, scope and comparator are aligned.",
        }

    if key == "ebitda_margin":
        revenue = _number_or_none(components.get("revenue_actual"))
        plan_ebitda = _number_or_none(components.get("ebitda_plan"))
        plan_revenue = _number_or_none(components.get("revenue_plan"))
        actual_margin = (actual / revenue) * 100 if revenue else None
        plan_margin = (plan_ebitda / plan_revenue) * 100 if plan_ebitda is not None and plan_revenue else None
        gap_bps = (actual_margin - plan_margin) * 100 if actual_margin is not None and plan_margin is not None else 0.0
        within_tolerance = abs(gap_bps) <= 25
        favourable = gap_bps >= 0
        posture = "Broadly on plan" if within_tolerance else "Ahead of plan" if favourable else "Below plan"
        tone = "neutral" if within_tolerance else "positive" if favourable else "critical" if gap_bps <= -150 else "watch"
        variance_label = f"{abs(round(gap_bps))} bps {'above' if favourable else 'below'} plan"
        readout = (
            f"EBITDA margin is broadly on plan, within {abs(round(gap_bps))} basis points of the approved level."
            if within_tolerance
            else f"EBITDA margin is {abs(round(gap_bps))} basis points {'above' if favourable else 'below'} plan."
        )
        decision = (
            "No immediate CEO intervention; ask the CFO to keep the margin bridge under watch."
            if within_tolerance
            else "Validate whether the upside is repeatable before changing guidance."
            if favourable
            else "Confirm the margin recovery owner, the two largest levers and the date the gap will close."
        )
        return {
            "posture": posture,
            "variance_label": variance_label,
            "tone": tone,
            "action_required": not within_tolerance and not favourable,
            "readout": readout,
            "decision": decision,
        }

    comparator = _number_or_none(components.get(spec.get("comparator")))
    ratio = (actual / comparator) if comparator not in {None, 0} else 1.0
    gap_pct = (ratio - 1) * 100
    inverse = bool(spec.get("inverse"))
    favourable = gap_pct <= 0 if inverse else gap_pct >= 0
    within_tolerance = abs(gap_pct) <= 1

    if key == "cash_vs_floor":
        gap_amount = actual - float(comparator or 0)
        favourable = gap_amount >= 0
        posture = "Above floor" if favourable else "Below floor"
        tone = "positive" if favourable else "critical"
        variance_label = f"{_format_sar(abs(gap_amount))} {'above' if favourable else 'below'} floor"
        return {
            "posture": posture,
            "variance_label": variance_label,
            "tone": tone,
            "action_required": not favourable,
            "readout": f"Liquidity is {variance_label.lower()} for the current reporting scope.",
            "decision": (
                "No liquidity intervention is required; keep the headroom protected against committed uses."
                if favourable
                else "Confirm the liquidity action, accountable owner and deadline before the next commitment is made."
            ),
        }

    posture = "Broadly on plan" if within_tolerance else "Ahead of plan" if favourable else "Off plan"
    tone = "neutral" if within_tolerance else "positive" if favourable else "critical" if abs(gap_pct) >= 5 else "watch"
    variance_label = f"{abs(gap_pct):.1f}% {'below' if gap_pct < 0 else 'above'} plan"
    subject = "Operating cost" if key == "operating_cost" else "Revenue"
    readout = (
        f"{subject} is broadly on plan for the current period ({variance_label})."
        if within_tolerance
        else f"{subject} is {variance_label} for the current period."
    )
    decision = (
        "No immediate CEO intervention. Keep the run-rate under watch and escalate only if the gap widens next period."
        if within_tolerance
        else "Validate whether the favourable variance is repeatable before changing guidance."
        if favourable
        else "Confirm the recovery owner, the largest contributing business line and the date the gap will close."
    )
    return {
        "posture": posture,
        "variance_label": variance_label,
        "tone": tone,
        "action_required": not within_tolerance and not favourable,
        "readout": readout,
        "decision": decision,
    }


def _executive_kpi_brief(
    spec: Mapping[str, Any],
    *,
    period: str,
    actual: float,
    metric: str,
    components: Mapping[str, Any],
    evidence: Mapping[str, Any],
    missing_inputs: list[str],
    actual_complete: bool,
    comparison: str,
    strategic_reference: Mapping[str, Any] | None,
    executive_signal: Mapping[str, Any],
) -> dict[str, Any]:
    """Separate the CEO decision brief from the expandable calculation trail.

    The CEO surface receives a compact, plain-language explanation.  The
    reproducible inputs remain present under ``audit`` so no lineage is hidden
    or rephrased as a business claim.
    """
    key = str(spec["key"])
    evidence_details = evidence.get("details") if isinstance(evidence.get("details"), Mapping) else {}
    source_files = list(evidence.get("files") or [])
    source_titles = list(dict.fromkeys(_source_title(item) for item in source_files))
    comparison_name = "Current-period comparison"
    comparison_value = comparison if not missing_inputs else "Not yet aligned"
    comparison_note = (
        "A governed strategic reference is available, but it is not aligned to the current period and scope."
        if missing_inputs and strategic_reference
        else "A like-for-like approved comparator for the current period and scope has not been supplied."
        if missing_inputs
        else "Compared with the approved comparator supplied for this period."
    )
    contributors = evidence_details.get("contributors") if isinstance(evidence_details.get("contributors"), Mapping) else {}

    def contributor_rows(scope: str, limit: int = 5) -> list[dict[str, Any]]:
        rows = list(contributors.get(scope) or []) if isinstance(contributors, Mapping) else []
        result: list[dict[str, Any]] = []
        for row in rows[:limit]:
            if not isinstance(row, Mapping):
                continue
            result.append(
                {
                    "label": str(row.get("label") or row.get("account") or "Account"),
                    "value": _format_sar(row.get("value_sar")),
                    "share_pct": _number_or_none(row.get("share_pct")),
                }
            )
        if len(rows) > limit:
            shown = sum((_number_or_none(row.get("value_sar")) or 0) for row in rows[:limit] if isinstance(row, Mapping))
            total = sum((_number_or_none(row.get("value_sar")) or 0) for row in rows if isinstance(row, Mapping))
            remainder = total - shown
            result.append({"label": f"Other {len(rows) - limit} accounts", "value": _format_sar(remainder), "share_pct": (remainder / total * 100) if total else None})
        return result

    calculation_steps: list[dict[str, str]] = []
    driver_rows: list[dict[str, Any]] = []
    narrative = str(executive_signal.get("readout") or "Current performance is available for review.")
    implication = str(executive_signal.get("decision") or "No CEO action is currently identified.")
    decision_question = ""
    if key == "revenue":
        calculation_steps = [{"label": "Recognised revenue", "value": metric}]
        driver_rows = contributor_rows("revenue")
        decision_question = "Does the current revenue position require intervention, and which business line should own it?"
    elif key == "ebitda_margin":
        revenue = _number_or_none(components.get("revenue_actual"))
        cogs = _number_or_none(components.get("cogs_actual"))
        operating_cost = _number_or_none(components.get("operating_cost_actual"))
        ebitda = _number_or_none(components.get("ebitda_actual"))
        display_component = lambda value: _format_sar(value) if value is not None else "Not supplied"
        calculation_steps = [
            {"label": "Revenue", "value": display_component(revenue)},
            {"label": "Less cost of goods sold", "value": display_component(cogs)},
            {"label": "Less operating cost", "value": display_component(operating_cost)},
            {"label": "EBITDA", "value": display_component(ebitda)},
        ]
        driver_rows = [
            {"label": "Revenue", "value": display_component(revenue), "share_pct": None},
            {"label": "Cost of goods sold", "value": display_component(cogs), "share_pct": (cogs / revenue * 100) if revenue and cogs is not None else None},
            {"label": "Operating cost", "value": display_component(operating_cost), "share_pct": (operating_cost / revenue * 100) if revenue and operating_cost is not None else None},
            {"label": "EBITDA", "value": display_component(ebitda), "share_pct": (ebitda / revenue * 100) if revenue and ebitda is not None else None},
        ]
        decision_question = "Does the margin gap require intervention, and which two levers will close it?"
    elif key == "operating_cost":
        calculation_steps = [{"label": "Operating cost", "value": metric}]
        driver_rows = contributor_rows("operating_cost")
        decision_question = "Does the cost position require intervention, and which owner has the largest controllable gap?"
    elif key == "cash_vs_floor":
        calculation_steps = [{"label": "Reported cash position", "value": metric}]
        reported_accounts = list(evidence_details.get("reported_accounts") or [])
        cash_total = sum((_number_or_none(row.get("balance_sar")) or 0) for row in reported_accounts if isinstance(row, Mapping))
        driver_rows = [
            {
                "label": str(row.get("account") or "Treasury account"),
                "value": _format_sar(row.get("balance_sar")),
                "share_pct": ((_number_or_none(row.get("balance_sar")) or 0) / cash_total * 100) if cash_total else None,
            }
            for row in reported_accounts if isinstance(row, Mapping)
        ]
        decision_question = "Is liquidity headroom sufficient for the next commitments, and what needs protecting?"

    return {
        "period_label": f"{period} actual",
        "metric": metric,
        "readout": narrative,
        "drivers": driver_rows,
        "driver_title": "What makes up this figure" if key != "ebitda_margin" else "EBITDA bridge",
        "decision_context": implication,
        "decision_question": decision_question,
        "executive_signal": dict(executive_signal),
        "comparison": {
            "label": comparison_name,
            "value": comparison_value,
            "note": comparison_note,
            "available": not bool(missing_inputs),
        },
        "strategic_reference": dict(strategic_reference) if strategic_reference else None,
        "calculation": {
            "label": "How this figure is built",
            "formula": str(spec["formula"]),
            "steps": calculation_steps,
        },
        "coverage": {
            "label": "Data coverage",
            "value": "Complete" if actual_complete else "Partial",
            "note": "All source values used in this figure are present."
            if actual_complete
            else "The reported figure excludes missing source values; none have been estimated.",
        },
        "audit": {
            "source_titles": source_titles,
            "source_files": source_files,
            "required_inputs": list(spec["inputs"]),
            "missing_inputs": list(missing_inputs),
            "evidence_summary": str(evidence.get("summary") or ""),
            "computation_boundary": "No missing value has been estimated.",
        },
    }


def _finance_kpi_payload(read_model: Mapping[str, Any]) -> dict[str, Any]:
    """Accept only a named deterministic calculation, never a prose value."""
    for field, engine in (
        ("finance_kpi", "deterministic_source_finance_kpi_engine"),
        ("oracle_kpi", "deterministic_oracle_kpi_engine"),
    ):
        payload = read_model.get(field)
        if isinstance(payload, Mapping) and payload.get("derived_from") == engine and payload.get("authoritative") is True:
            return dict(payload)
    return {}


def _safe_trend(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    trend = payload.get("trend")
    item = trend.get(key) if isinstance(trend, Mapping) else None
    if not isinstance(item, Mapping):
        return {"actual": [], "plan": [], "labels": [], "has_plan_series": False, "unit": ""}

    def values(name: str) -> list[float]:
        result: list[float] = []
        for value in list(item.get(name) or []):
            number = _number_or_none(value)
            if number is None:
                return []
            result.append(number)
        return result

    actual = values("actual")
    plan = values("plan")
    labels = [str(value) for value in list(item.get("labels") or [])]
    has_plan = bool(item.get("has_plan_series")) and bool(plan) and len(actual) == len(plan)
    result = {
        "actual": actual,
        "plan": plan if has_plan else [],
        "labels": labels if len(labels) == len(actual) else [],
        "has_plan_series": has_plan,
        "unit": str(item.get("unit") or ""),
    }
    if item.get("scope_note"):
        result["scope_note"] = str(item["scope_note"])
    if item.get("plan_note"):
        result["plan_note"] = str(item["plan_note"])
    return result


def _unavailable_ceo_kpi(spec: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    missing = list(spec["inputs"])
    return {
        "kpi_contract": True,
        "driver_key": spec["key"],
        "key": spec["key"],
        "label": spec["label"],
        "metric": "Not available",
        "value": "Not available",
        "pct": None,
        "status": "Not available",
        "sub": "Required finance information is not available for this reporting period",
        "detail": reason,
        "story": reason,
        "formula": spec["formula"],
        "inputs": list(spec["inputs"]),
        "missing_inputs": missing,
        "availability": "unavailable",
        "comparison": "No comparison is shown until the required finance information is available.",
        "chips": [],
        "movers": {"lifting": [], "dragging": []},
        "trend": {"actual": [], "plan": [], "labels": [], "has_plan_series": False, "unit": ""},
        "trend_status": "Comparable historical periods are not available.",
        "provenance": {
            "source": "current reporting information",
            "complete": False,
            "reason": reason,
        },
    }


def _ceo_kpi_cards(read_model: Mapping[str, Any]) -> list[dict[str, Any]]:
    finance_payload = _finance_kpi_payload(read_model)
    components = finance_payload.get("components") if isinstance(finance_payload.get("components"), Mapping) else {}
    evidence = finance_payload.get("evidence") if isinstance(finance_payload.get("evidence"), Mapping) else {}
    dynamics = finance_payload.get("dynamics") if isinstance(finance_payload.get("dynamics"), Mapping) else {}
    actual_complete = finance_payload.get("actual_complete") if isinstance(finance_payload.get("actual_complete"), Mapping) else {}
    period = str(finance_payload.get("reporting_period_key") or "the selected period")
    provenance = {
        "source": "current finance records",
        "complete": bool(finance_payload),
        "reporting_period_key": finance_payload.get("reporting_period_key"),
        "computation_boundary": finance_payload.get("computation_boundary"),
    }
    cards: list[dict[str, Any]] = []

    for spec in _CEO_KPI_SPECS:
        if not finance_payload:
            cards.append(
                _unavailable_ceo_kpi(
                    spec,
                    reason=(
                        "The finance information required for this figure is not available for the current reporting period. "
                        "No value has been estimated."
                    ),
                )
            )
            continue

        actual = _number_or_none(components.get(spec["actual"]))
        denominator_key = spec.get("denominator")
        denominator = _number_or_none(components.get(denominator_key)) if denominator_key else None
        if actual is None or (denominator_key and (denominator is None or denominator == 0)):
            missing_keys = [spec["actual"]]
            if denominator_key:
                missing_keys.append(denominator_key)
            cards.append(
                _unavailable_ceo_kpi(
                    spec,
                    reason=(
                        f"Cannot calculate {spec['label']} for {period}: missing "
                        + ", ".join(missing_keys)
                        + " in the current finance records."
                    ),
                )
            )
            continue

        comparator_key = spec.get("comparator")
        comparator = _number_or_none(components.get(comparator_key)) if comparator_key else None
        ring_pct: float | None = None
        ring_label = ""
        if denominator_key:
            plan_numerator = _number_or_none(components.get(spec["plan_numerator"]))
            plan_denominator = _number_or_none(components.get(spec["plan_denominator"]))
            actual_margin = (actual / denominator) * 100
            plan_margin = (plan_numerator / plan_denominator) * 100 if plan_numerator is not None and plan_denominator not in {None, 0} else None
            pct = (actual_margin / plan_margin) * 100 if plan_margin not in {None, 0} else None
            variance_bps = (actual_margin - plan_margin) * 100 if plan_margin is not None else None
            metric = _percent_display(actual_margin)
            ring_pct = actual_margin
            ring_label = "current margin"
            comparison = _basis_points_display(variance_bps)
            missing_inputs = [] if plan_margin is not None else ["H1 EBITDA budget aligned to this scope", "H1 revenue budget aligned to this scope"]
        else:
            pct = (actual / comparator) * 100 if comparator not in {None, 0} else None
            metric = _format_sar(actual)
            if comparator is None:
                comparison = "Board floor comparison unavailable" if spec["key"] == "cash_vs_floor" else "Plan comparison unavailable"
                missing_inputs = [
                    "H1 budget aligned to this reporting scope"
                    if spec["key"] != "cash_vs_floor"
                    else "Approved cash floor aligned to this reporting scope"
                ]
            else:
                delta = actual - comparator
                if spec["key"] == "cash_vs_floor":
                    comparison = f"{_format_sar(delta)} {'above' if delta >= 0 else 'below'} floor"
                else:
                    comparison = f"{pct:.1f}% of plan"
                missing_inputs = []

            if spec["key"] == "operating_cost":
                revenue_actual = _number_or_none(components.get("revenue_actual"))
                if revenue_actual:
                    ring_pct = actual / revenue_actual * 100
                    ring_label = "of revenue"

        kpi_evidence = evidence.get(spec["key"]) if isinstance(evidence.get(spec["key"]), Mapping) else {}
        actual_is_complete = bool(actual_complete.get(spec["key"], True))
        actual_missing = [] if actual_is_complete else ["Complete latest cash-position balances"]
        missing_inputs = list(dict.fromkeys([*missing_inputs, *actual_missing]))
        availability = "verified" if not missing_inputs else "partial"
        status = "Verified" if availability == "verified" else "Current actual available · comparison pending"
        sub = comparison
        detail = (
            f"Calculated for {period}. {comparison}."
            if availability == "verified"
            else f"Calculated for {period}. A comparison is withheld until period and scope are aligned."
        )
        evidence_summary = str(kpi_evidence.get("summary") or "")
        if evidence_summary:
            detail += " " + evidence_summary
        if not actual_is_complete:
            detail += " The current cash figure is partial; no missing balance has been estimated."
        card_provenance = {
            **provenance,
            "complete": actual_is_complete,
            "source_files": list(kpi_evidence.get("files") or []),
        }
        strategic_reference = _governed_strategic_reference(finance_payload, str(spec["key"]))
        executive_signal = _executive_kpi_signal(
            spec,
            actual=actual,
            components=components,
            missing_inputs=missing_inputs,
            actual_complete=actual_is_complete,
        )
        cards.append(
            {
                "kpi_contract": True,
                "driver_key": spec["key"],
                "key": spec["key"],
                "label": spec["label"],
                "metric": metric,
                "value": metric,
                "pct": round(pct, 1) if pct is not None else None,
                "ring_pct": round(ring_pct, 1) if ring_pct is not None else None,
                "ring_label": ring_label,
                "status": status,
                "tone": executive_signal["tone"],
                "sub": sub,
                "detail": detail,
                "story": detail,
                "formula": spec["formula"],
                "inputs": list(spec["inputs"]),
                "missing_inputs": missing_inputs,
                "availability": availability,
                "comparison": comparison,
                "chips": [],
                "movers": dict(dynamics.get(spec["key"]) or {"lifting": [], "dragging": []}),
                "trend": _safe_trend(finance_payload, str(spec["key"])),
                "trend_status": (
                    "Plan comparison is available from the aligned budget series."
                    if _safe_trend(finance_payload, str(spec["key"])).get("has_plan_series")
                    else "Actual trend is shown when multiple governed periods are available; no plan series has been supplied."
                ),
                "provenance": card_provenance,
                "grounding": {
                    "status": "grounded" if actual_is_complete else "needs_evidence",
                    "source": card_provenance["source"],
                },
                "evidence_summary": evidence_summary,
                "source_files": list(kpi_evidence.get("files") or []),
                "executive_brief": _executive_kpi_brief(
                    spec,
                    period=period,
                    actual=actual,
                    metric=metric,
                    components=components,
                    evidence=kpi_evidence,
                    missing_inputs=missing_inputs,
                    actual_complete=actual_is_complete,
                    comparison=comparison,
                    strategic_reference=strategic_reference,
                    executive_signal=executive_signal,
                ),
            }
        )
    return cards


def _hero(
    read_model: Mapping[str, Any],
    *,
    drivers: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    metrics = read_model.get("metrics") or {}
    lifecycle = read_model.get("lifecycle") or {}
    challenged = int(_claim_value(metrics.get("challenged_count"), 0) or 0)
    reports = int(_claim_value(metrics.get("report_count"), 0) or 0)
    approval_status = str(_claim_value(lifecycle.get("approval_status"), "pending") or "pending").lower()
    citation_value = _claim_value(metrics.get("citation_resolution"), {}) or {}
    citation_total = int(citation_value.get("total") or 0) if isinstance(citation_value, Mapping) else 0
    citation_resolved = citation_value.get("resolved") if isinstance(citation_value, Mapping) else None
    if citation_resolved is not None:
        citation_resolved = int(citation_resolved)
    finance_kpis_unavailable = bool(drivers) and all(
        str(driver.get("availability") or "") == "unavailable"
        for driver in drivers or []
    )
    driver_signals: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for driver in drivers or []:
        brief = driver.get("executive_brief") if isinstance(driver.get("executive_brief"), Mapping) else {}
        signal = brief.get("executive_signal") if isinstance(brief.get("executive_signal"), Mapping) else {}
        if signal:
            driver_signals.append((driver, signal))
    intervention = next((item for item in driver_signals if item[1].get("action_required") is True), None)
    comparable_signals = [item for item in driver_signals if item[1].get("posture") != "Comparison pending"]
    if read_model.get("data_status") != "ready":
        label = "Board readiness is unavailable"
        body = read_model.get("status_reason") or "Current reporting information is not available."
        status = "missing"
    elif finance_kpis_unavailable:
        label = "CEO finance baseline is not yet connected"
        body = (
            "The board packet is available, but Revenue, EBITDA margin, Operating cost and Cash vs floor "
            "are withheld because the required finance information is not available for this reporting period."
        )
        status = "finance_data_required"
    elif intervention:
        driver, signal = intervention
        label = f"{driver.get('label') or 'Performance'} needs executive intervention"
        body = f"{signal.get('readout')} {signal.get('decision')}"
        if challenged:
            body += f" Board release is also blocked by {challenged} evidence {'issue' if challenged == 1 else 'issues'}."
        status = "intervention_required"
    elif comparable_signals:
        label = "Enterprise performance is broadly on plan"
        body = "No headline measure currently crosses the CEO intervention threshold."
        if challenged:
            body += f" Board release remains blocked by {challenged} evidence {'issue' if challenged == 1 else 'issues'}."
        elif approval_status in {"pending", "awaiting_review", "in_review", ""}:
            body += " The board pack remains with the reviewer for final sign-off."
        elif approval_status == "approved" and reports:
            body += f" The board pack is approved and {reports} {'report is' if reports == 1 else 'reports are'} ready."
        status = "on_plan"
    elif challenged:
        label = "Board release needs executive attention"
        body = f"{challenged} evidence {'issue is' if challenged == 1 else 'issues are'} still blocking a clean release."
        status = "needs_reviewer_closure"
    elif approval_status == "approved" and reports:
        label = "Board pack is approved for release"
        body = f"Approval is recorded and {reports} {'report' if reports == 1 else 'reports'} are ready."
        status = "release_ready"
    elif approval_status in {"pending", "awaiting_review", ""}:
        label = "Board pack is waiting for final sign-off"
        body = "The reviewer decision is still open; distribution remains blocked until it is recorded."
        status = "review_gate"
    else:
        label = "Board pack needs follow-up"
        body = f"Current approval posture is {_humanize(approval_status).lower()}."
        status = "attention"
    readiness_operands = {
        "approval_status": approval_status,
        "challenged_count": challenged,
        "citation_resolved": citation_resolved,
        "citation_total": citation_total,
        "report_count": reports,
    }
    return {
        "status": status,
        "label": label,
        "headline": label,
        "summary": label,
        "body": body,
        "score": None,
        "executive_posture": (
            "Action"
            if status in {"intervention_required", "needs_reviewer_closure"}
            else "On plan"
            if status == "on_plan"
            else "Ready"
            if status == "release_ready"
            else "Review"
        ),
        "score_note": "current posture",
        "secondary_fact": f"As of {read_model.get('as_of')}" if read_model.get("as_of") else "Current reporting period",
        "readiness_operands": readiness_operands,
    }


def _findings(read_model: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_findings = list(read_model.get("findings") or [])
    displayed = all_findings[:3]
    rows: list[dict[str, Any]] = []
    displayed_total = 0.0
    total = 0.0
    for item in all_findings:
        total += float(_claim_value(item.get("recoverable_sar"), 0.0) or 0.0)
    for item in displayed:
        recoverable = float(_claim_value(item.get("recoverable_sar"), 0.0) or 0.0)
        displayed_total += recoverable
        citations = int(_claim_value(item.get("citation_count"), 0) or 0)
        challenged = bool(_claim_value(item.get("challenged"), False))
        # The counterparty is the part an executive recognises. "INV-2026-0341"
        # means nothing to them; "Premier Packaging LLC" tells them who to call.
        # Stated only when the run carries it -- never inferred.
        counterparty = str(_claim_value(item.get("counterparty"), "") or "").strip()
        # What to do about it, and where it sits. Both are governed facts read
        # from the finding, so a card is no longer a dead end: it names the
        # recommended action and its state, and the recovery it is worth.
        action = str(_claim_value(item.get("recommended_action"), "") or "").strip()
        state = str(_claim_value(item.get("state"), "") or "").strip()
        rows.append(
            {
                "finding_id": _claim_value(item.get("finding_id"), ""),
                "title": _claim_value(item.get("title"), "Governed finance finding"),
                "tag": _claim_value(item.get("pattern_label"), "Governed Finance Finding"),
                "counterparty": counterparty or None,
                "detail": (
                    (f"{counterparty} · " if counterparty else "")
                    + f"{_format_sar(recoverable)} recoverable"
                    + f" · {citations} supporting {'document' if citations == 1 else 'documents'}"
                    + (" · needs closure" if challenged else "")
                ),
                "recommended_action": action or None,
                "state": state or None,
                "tone": "flat" if challenged else "up",
                "recoverable_sar": recoverable,
                "citation_count": citations,
                "challenged": challenged,
                "provenance": _provenance(item.get("recoverable_sar")),
            }
        )
    return rows, {
        "total_recoverable_sar": round(total, 2),
        "displayed_recoverable_sar": round(displayed_total, 2),
        "remaining_recoverable_sar": round(max(0.0, total - displayed_total), 2),
        "total_finding_count": len(all_findings),
        "displayed_finding_count": len(displayed),
    }


def _case_index(read_model: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Compact navigation records for every governed finding in the run."""
    rows: list[dict[str, Any]] = []
    for item in list(read_model.get("findings") or []):
        recoverable = float(_claim_value(item.get("recoverable_sar"), 0.0) or 0.0)
        citations = int(_claim_value(item.get("citation_count"), 0) or 0)
        challenged = bool(_claim_value(item.get("challenged"), False))
        # The counterparty is the part an executive recognises. "INV-2026-0341"
        # means nothing to them; "Premier Packaging LLC" tells them who to call.
        # Stated only when the run carries it -- never inferred.
        counterparty = str(_claim_value(item.get("counterparty"), "") or "").strip()
        rows.append(
            {
                "finding_id": _claim_value(item.get("finding_id"), ""),
                "title": _claim_value(item.get("title"), "Governed finance finding"),
                "tag": _claim_value(item.get("pattern_label"), "Governed Finance Finding"),
                "counterparty": counterparty or None,
                "detail": (
                    (f"{counterparty} · " if counterparty else "")
                    + f"{_format_sar(recoverable)} recoverable"
                    + f" · {citations} supporting {'document' if citations == 1 else 'documents'}"
                    + (" · needs closure" if challenged else "")
                ),
                "tone": "flat" if challenged else "up",
                "recoverable_sar": recoverable,
                "citation_count": citations,
                "challenged": challenged,
                "provenance": _provenance(item.get("recoverable_sar")),
            }
        )
    return rows


def _executive_priorities(
    read_model: Mapping[str, Any],
    *,
    drivers: list[Mapping[str, Any]],
    reconciliation: Mapping[str, Any],
) -> dict[str, Any]:
    """Aggregate operational findings into CEO decisions and business signals.

    Individual invoices, citations and recovery cases remain available to the
    finance/review lanes and Hermes.  The CEO home receives only material
    enterprise implications, explicit ownership and the required decision.
    """
    metrics = read_model.get("metrics") if isinstance(read_model.get("metrics"), Mapping) else {}
    lifecycle = read_model.get("lifecycle") if isinstance(read_model.get("lifecycle"), Mapping) else {}
    approval_status = str(_claim_value(lifecycle.get("approval_status"), "pending") or "pending").lower()
    challenged_count = int(_claim_value(metrics.get("challenged_count"), 0) or 0)
    report_count = int(_claim_value(metrics.get("report_count"), 0) or 0)
    total_recoverable = float(reconciliation.get("total_recoverable_sar") or 0.0)
    total_finding_count = int(reconciliation.get("total_finding_count") or 0)
    finance_payload = _finance_kpi_payload(read_model)
    components = finance_payload.get("components") if isinstance(finance_payload.get("components"), Mapping) else {}
    revenue_actual = _number_or_none(components.get("revenue_actual"))
    materiality_threshold = max(1_000_000.0, (revenue_actual or 0.0) * 0.005)
    material_recovery = total_recoverable >= materiality_threshold

    calendar = read_model.get("week_ahead") if isinstance(read_model.get("week_ahead"), Mapping) else {}
    calendar_items = list(calendar.get("items") or [])
    board_event = next(
        (item for item in calendar_items if "board" in str((item or {}).get("title") or "").lower()),
        None,
    )
    board_timing = (
        f"Before {str(board_event.get('title') or 'the board meeting').lower()}"
        if isinstance(board_event, Mapping)
        else "Before board release"
    )

    decisions: list[dict[str, Any]] = []
    if challenged_count:
        decisions.append(
            {
                "key": "evidence_gate",
                "title": "Clear the board evidence gate",
                "summary": (
                    f"{challenged_count} {'issue is' if challenged_count == 1 else 'issues are'} blocking a clean release. "
                    "The CEO decision is the escalation mandate, not the case-by-case review."
                ),
                "decision": "Confirm the accountable executive and the deadline for closure.",
                "owner": "Group CFO and Reviewer",
                "timing": board_timing,
                "priority": "critical",
                "action_required": True,
                "prompt": "Give me the shortest evidence-closure plan for the board pack: accountable owner, deadline, and only the items that require CEO escalation.",
            }
        )
    elif approval_status in {"pending", "awaiting_review", "in_review", ""}:
        decisions.append(
            {
                "key": "board_signoff",
                "title": "Hold the board pack for final sign-off",
                "summary": (
                    f"The evidence review is open and {report_count} {'report is' if report_count == 1 else 'reports are'} prepared. "
                    "Distribution should remain blocked until the reviewer decision is recorded."
                ),
                "decision": "Confirm who will sign off and when the pack can be released.",
                "owner": "Reviewer",
                "timing": board_timing,
                "priority": "watch",
                "action_required": True,
                "prompt": "What remains before final board-pack sign-off, who owns it, and when can the pack be released?",
            }
        )

    if material_recovery:
        materiality_pct = (total_recoverable / revenue_actual * 100) if revenue_actual else None
        scale_note = f" ({materiality_pct:.1f}% of current revenue)" if materiality_pct is not None else ""
        decisions.append(
            {
                "key": "recovery_mandate",
                "title": f"Set the mandate for {_format_sar(total_recoverable)} of recovery",
                "summary": (
                    f"The opportunity is aggregated across {total_finding_count} finance-control cases{scale_note}. "
                    "Keep invoice-level execution with Finance; set the target and escalation threshold here."
                ),
                "decision": "Confirm the recovery target, executive owner and exceptions that return to you.",
                "owner": "Group CFO",
                "timing": "Next executive review",
                "priority": "watch",
                "action_required": True,
                "prompt": "Frame the finance recovery programme for a CEO decision: target, owner, deadline, and escalation threshold. Do not list individual invoices unless material.",
            }
        )

    performance_signals: list[dict[str, Any]] = []
    for driver in drivers:
        brief = driver.get("executive_brief") if isinstance(driver.get("executive_brief"), Mapping) else {}
        signal = brief.get("executive_signal") if isinstance(brief.get("executive_signal"), Mapping) else {}
        if not signal or signal.get("tone") not in {"critical", "watch", "positive"}:
            continue
        performance_signals.append(
            {
                "key": str(driver.get("driver_key") or driver.get("key") or "performance"),
                "title": f"{driver.get('label')}: {signal.get('posture')}",
                "summary": str(signal.get("readout") or ""),
                "implication": str(signal.get("decision") or ""),
                "tone": str(signal.get("tone") or "neutral"),
                "action_required": bool(signal.get("action_required")),
                "prompt": str(brief.get("decision_question") or "Explain the executive implication and required owner."),
            }
        )
    performance_signals.sort(
        key=lambda item: ({"critical": 0, "watch": 1, "positive": 2}.get(str(item.get("tone")), 3), str(item.get("title")))
    )
    if not performance_signals:
        performance_signals.append(
            {
                "key": "performance_within_tolerance",
                "title": "No material headline variance requires CEO intervention",
                "summary": "The current four enterprise measures do not show an exception above the executive threshold.",
                "implication": "Keep the operating review delegated and watch for a change in direction next period.",
                "tone": "neutral",
                "action_required": False,
                "prompt": "Confirm whether any headline performance measure requires CEO intervention now, and explain why.",
            }
        )

    delegated_summary = None
    if total_finding_count and not material_recovery:
        delegated_summary = {
            "title": "Operational controls remain delegated",
            "summary": (
                f"{total_finding_count} finance-control {'case is' if total_finding_count == 1 else 'cases are'} below the CEO materiality threshold "
                f"of {_format_sar(materiality_threshold)} and remain with the Group CFO."
            ),
            "owner": "Group CFO",
        }

    return {
        "decisions": decisions[:3],
        "signals": performance_signals[:3],
        "delegated_summary": delegated_summary,
        "materiality_threshold_sar": round(materiality_threshold, 2),
    }


def build_executive_presentation(read_model: dict[str, Any]) -> dict[str, Any]:
    drivers = _ceo_kpi_cards(read_model)
    hero = _hero(read_model, drivers=drivers)
    findings, reconciliation = _findings(read_model)
    executive_priorities = _executive_priorities(read_model, drivers=drivers, reconciliation=reconciliation)
    developments = list((read_model.get("developments") or {}).get("items") or [])
    week = list((read_model.get("week_ahead") or {}).get("items") or [])
    sections = {
        "drivers": drivers,
        "findings": {
            "items": findings,
            "case_index": _case_index(read_model),
            "reconciliation": reconciliation,
        },
        "executive_priorities": executive_priorities,
        "developments": {
            "items": developments,
            "status": (read_model.get("developments") or {}).get("status"),
            "reason": (read_model.get("developments") or {}).get("reason"),
        },
        "week_ahead": {
            "items": week,
            "status": (read_model.get("week_ahead") or {}).get("status"),
            "reason": (read_model.get("week_ahead") or {}).get("reason"),
        },
    }
    payload = {
        "mode": "live",
        "source": read_model.get("source"),
        "run_id": read_model.get("run_id"),
        "as_of": read_model.get("as_of"),
        "data_status": read_model.get("data_status"),
        "status_reason": read_model.get("status_reason"),
        "hero": hero,
        "driver_grid": drivers,
        "persona_blueprint": {
            "health": {
                "headline": hero.get("headline"),
                "body": hero.get("body"),
                "scoreNote": hero.get("score_note"),
            },
            "assistant": "Hermes",
            "drivers": drivers,
            "findings": findings,
            "developments": developments,
            "week": week,
        },
        "sections": sections,
        "findings_reconciliation": reconciliation,
    }
    payload["provenance_summary"] = provenance_summary(read_model)
    return payload
