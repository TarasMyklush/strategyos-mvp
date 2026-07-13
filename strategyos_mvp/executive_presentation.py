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


# Board-approved strategic references are deliberately kept separate from the
# period-aligned finance comparators above.  The current finance extract is H1
# and scoped; comparing it directly with an annual Group target would create a
# misleading percentage.  These references tell the CEO what has been approved
# while making the remaining alignment requirement explicit.
_BOARD_STRATEGIC_REFERENCES: dict[str, dict[str, Any]] = {
    "revenue": {
        "label": "Approved FY2026 Group revenue plan",
        "value": "SAR 8.35B",
        "note": "Board approved on 12 January 2026. A phased H1 budget for the same entities is still required for a valid performance comparison.",
    },
    "ebitda_margin": {
        "label": "Approved FY2028 Group EBITDA margin target",
        "value": "23.0%",
        "note": "This is the approved long-term target, not an H1 2026 budget comparator.",
    },
    "cash_vs_floor": {
        "label": "Approved Group cash floor",
        "value": "SAR 1.20B",
        "note": "The current cash extract is partial and is not yet aligned to the full Group scope required for a valid floor assessment.",
    },
}

_STRATEGY_SOURCE_TITLE = "Mizan Group Strategy 2026–2028 · Board approved 12 January 2026"


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
    strategic_reference = _BOARD_STRATEGIC_REFERENCES.get(key)
    comparison_name = "Current-period comparison"
    comparison_value = comparison if not missing_inputs else "Not yet aligned"
    comparison_note = (
        "An approved strategic reference exists, but the current actual and comparator are not yet aligned to the same period and scope."
        if missing_inputs and strategic_reference
        else "A current-period budget for the same scope has not yet been connected."
        if missing_inputs
        else "Compared with the approved comparator supplied for this period."
    )
    scoped_accounts = {}
    if isinstance(evidence_details.get("account_scopes"), Mapping):
        scoped_accounts = evidence_details["account_scopes"]
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
    narrative = ""
    implication = ""
    decision_question = ""
    if key == "revenue":
        account_count = len((scoped_accounts.get("revenue") or {}).get("accounts") or [])
        narrative = "Revenue recognised in the H1 general ledger."
        calculation_steps = [{"label": "Recognised revenue", "value": metric}]
        if account_count:
            narrative = f"Revenue recognised across {account_count} revenue account groups in the H1 general ledger."
        driver_rows = contributor_rows("revenue")
        implication = "The FY2026 Group revenue plan is approved. Performance against it will be shown once the phased H1 budget is aligned to this reporting scope." if missing_inputs else comparison
        decision_question = "Which revenue streams account for the current result, and where is concentration risk highest?"
    elif key == "ebitda_margin":
        revenue = _number_or_none(components.get("revenue_actual"))
        cogs = _number_or_none(components.get("cogs_actual"))
        operating_cost = _number_or_none(components.get("operating_cost_actual"))
        ebitda = _number_or_none(components.get("ebitda_actual"))
        display_component = lambda value: _format_sar(value) if value is not None else "Not supplied"
        narrative = "Margin before depreciation, amortisation, interest and tax."
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
        implication = "The FY2028 margin target is approved. An H1 2026 EBITDA budget for the same scope is still needed for a current performance comparison." if missing_inputs else comparison
        decision_question = "What is the EBITDA bridge from revenue through direct and operating costs?"
    elif key == "operating_cost":
        account_count = len((scoped_accounts.get("operating_cost") or {}).get("accounts") or [])
        narrative = "Operating expenditure before depreciation, amortisation and interest."
        calculation_steps = [{"label": "Operating cost", "value": metric}]
        if account_count:
            narrative = f"Operating expenditure across {account_count} expense accounts; depreciation, amortisation and interest excluded."
        driver_rows = contributor_rows("operating_cost")
        implication = "Current operating cost is available. The matching H1 operating-cost budget has not yet been connected." if missing_inputs else comparison
        decision_question = "Which operating-cost accounts create the largest spend concentration and merit review?"
    elif key == "cash_vs_floor":
        as_of = str(evidence_details.get("as_of") or "the latest reported date")
        missing_accounts = list(evidence_details.get("missing_accounts") or [])
        narrative = f"Latest reported treasury cash position as at {as_of}."
        if missing_accounts:
            narrative += " One balance remains outstanding and has not been estimated."
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
        implication = "The Group cash floor is SAR 1.20B. The current cash position is partial and not yet aligned to full Group scope, so a floor comparison is withheld." if missing_inputs else comparison
        decision_question = "What cash is reported, what remains missing, and what floor is required for a board-safe comparison?"

    return {
        "period_label": f"{period} actual",
        "metric": metric,
        "readout": narrative,
        "drivers": driver_rows,
        "driver_title": "What makes up this figure" if key != "ebitda_margin" else "EBITDA bridge",
        "decision_context": implication,
        "decision_question": decision_question,
        "comparison": {
            "label": comparison_name,
            "value": comparison_value,
            "note": comparison_note,
            "available": not bool(missing_inputs),
        },
        "strategic_reference": {
            **strategic_reference,
            "source": _STRATEGY_SOURCE_TITLE,
        } if strategic_reference else None,
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


def _safe_trend(payload: Mapping[str, Any], key: str) -> dict[str, list[float]]:
    trend = payload.get("trend")
    item = trend.get(key) if isinstance(trend, Mapping) else None
    if not isinstance(item, Mapping):
        return {"actual": [], "plan": []}

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
    return {"actual": actual, "plan": plan} if actual and plan and len(actual) == len(plan) else {"actual": [], "plan": []}


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
        "trend": {"actual": [], "plan": []},
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
        if denominator_key:
            plan_numerator = _number_or_none(components.get(spec["plan_numerator"]))
            plan_denominator = _number_or_none(components.get(spec["plan_denominator"]))
            actual_margin = (actual / denominator) * 100
            plan_margin = (plan_numerator / plan_denominator) * 100 if plan_numerator is not None and plan_denominator not in {None, 0} else None
            pct = (actual_margin / plan_margin) * 100 if plan_margin not in {None, 0} else None
            variance_bps = (actual_margin - plan_margin) * 100 if plan_margin is not None else None
            metric = _percent_display(actual_margin)
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
                    else "Complete Group cash position aligned to the approved floor"
                ]
            else:
                delta = actual - comparator
                if spec["key"] == "cash_vs_floor":
                    comparison = f"{_format_sar(delta)} {'above' if delta >= 0 else 'below'} floor"
                else:
                    comparison = f"{pct:.1f}% of plan"
                missing_inputs = []

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
        cards.append(
            {
                "kpi_contract": True,
                "driver_key": spec["key"],
                "key": spec["key"],
                "label": spec["label"],
                "metric": metric,
                "value": metric,
                "pct": round(pct, 1) if pct is not None else None,
                "status": status,
                "sub": sub,
                "detail": detail,
                "story": detail,
                "formula": spec["formula"],
                "inputs": list(spec["inputs"]),
                "missing_inputs": missing_inputs,
                "availability": availability,
                "comparison": comparison,
                "chips": [],
                "movers": {"lifting": [], "dragging": []},
                "trend": _safe_trend(finance_payload, str(spec["key"])),
                "trend_status": "Comparable historical periods are not available.",
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
    elif challenged:
        label = "Board pack is not yet clean for release"
        body = f"{challenged} item(s) still need evidence closure before executive release."
        status = "needs_reviewer_closure"
    elif approval_status == "approved" and reports:
        label = "Board pack is approved for release"
        body = f"Approval is recorded and {reports} report surface(s) are ready."
        status = "release_ready"
    elif approval_status in {"pending", "awaiting_review", ""}:
        label = "Reviewer decision is still open"
        body = "The finance evidence is ready, but release still depends on human review."
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
        "score_note": (
            "Database-backed board readiness"
            if read_model.get("source") == "database"
            else "Governed artifact board readiness"
        ),
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
        rows.append(
            {
                "finding_id": _claim_value(item.get("finding_id"), ""),
                "title": _claim_value(item.get("title"), "Governed finance finding"),
                "tag": _claim_value(item.get("pattern_label"), "Governed Finance Finding"),
                "detail": (
                    f"{_format_sar(recoverable)} recoverable"
                    + f" · {citations} citation(s)"
                    + (" · needs closure" if challenged else "")
                ),
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
        rows.append(
            {
                "finding_id": _claim_value(item.get("finding_id"), ""),
                "title": _claim_value(item.get("title"), "Governed finance finding"),
                "tag": _claim_value(item.get("pattern_label"), "Governed Finance Finding"),
                "detail": (
                    f"{_format_sar(recoverable)} recoverable"
                    + f" · {citations} citation(s)"
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


def build_executive_presentation(read_model: dict[str, Any]) -> dict[str, Any]:
    drivers = _ceo_kpi_cards(read_model)
    hero = _hero(read_model, drivers=drivers)
    findings, reconciliation = _findings(read_model)
    developments = list((read_model.get("developments") or {}).get("items") or [])
    week = list((read_model.get("week_ahead") or {}).get("items") or [])
    sections = {
        "drivers": drivers,
        "findings": {
            "items": findings,
            "case_index": _case_index(read_model),
            "reconciliation": reconciliation,
        },
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
