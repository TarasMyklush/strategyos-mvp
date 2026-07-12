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


def _oracle_kpi_payload(read_model: Mapping[str, Any]) -> dict[str, Any]:
    payload = read_model.get("oracle_kpi")
    if not isinstance(payload, Mapping):
        return {}
    # The CEO page accepts figures only from the deterministic engine.  A
    # similarly shaped, hand-authored summary is not sufficient evidence.
    if payload.get("derived_from") != "deterministic_oracle_kpi_engine":
        return {}
    if payload.get("authoritative") is not True:
        return {}
    return dict(payload)


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
        "sub": "Cannot be calculated from the current processed dataset",
        "detail": reason,
        "story": reason,
        "formula": spec["formula"],
        "inputs": list(spec["inputs"]),
        "missing_inputs": missing,
        "availability": "unavailable",
        "comparison": "No comparison is shown because the required governed inputs are missing.",
        "chips": [],
        "movers": {"lifting": [], "dragging": []},
        "trend": {"actual": [], "plan": []},
        "trend_status": "Historical governed periods are not available.",
        "provenance": {
            "source": "current processed dataset",
            "complete": False,
            "reason": reason,
        },
    }


def _ceo_kpi_cards(read_model: Mapping[str, Any]) -> list[dict[str, Any]]:
    oracle_payload = _oracle_kpi_payload(read_model)
    components = oracle_payload.get("components") if isinstance(oracle_payload.get("components"), Mapping) else {}
    period = str(oracle_payload.get("reporting_period_key") or "the selected period")
    provenance = {
        "source": "deterministic Oracle finance snapshot",
        "complete": bool(oracle_payload),
        "reporting_period_key": oracle_payload.get("reporting_period_key"),
        "computation_boundary": oracle_payload.get("computation_boundary"),
    }
    cards: list[dict[str, Any]] = []

    for spec in _CEO_KPI_SPECS:
        if not oracle_payload:
            cards.append(
                _unavailable_ceo_kpi(
                    spec,
                    reason=(
                        "This run contains governed findings and evidence, but no reconciled "
                        "Oracle finance snapshot for this KPI. StrategyOS will not estimate it."
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
                        + " in the reconciled finance snapshot."
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
            missing_inputs = [] if plan_margin is not None else ["Approved EBITDA plan", "Approved revenue plan"]
        else:
            pct = (actual / comparator) * 100 if comparator not in {None, 0} else None
            metric = _format_sar(actual)
            if comparator is None:
                comparison = "Plan or floor comparison unavailable"
                missing_inputs = ["Approved plan" if spec["key"] != "cash_vs_floor" else "Approved board cash floor"]
            else:
                delta = actual - comparator
                if spec["key"] == "cash_vs_floor":
                    comparison = f"{_format_sar(delta)} {'above' if delta >= 0 else 'below'} floor"
                else:
                    comparison = f"{pct:.1f}% of plan"
                missing_inputs = []

        availability = "verified" if not missing_inputs else "partial"
        status = "Verified" if availability == "verified" else "Partial — comparator unavailable"
        sub = comparison
        detail = (
            f"Calculated for {period} from the deterministic finance snapshot. {comparison}."
            if availability == "verified"
            else f"Calculated for {period}; {comparison.lower()}. No comparator has been inferred."
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
                "trend": _safe_trend(oracle_payload, str(spec["key"])),
                "trend_status": "Historical governed periods are not available.",
                "provenance": dict(provenance),
            }
        )
    return cards


def _hero(read_model: Mapping[str, Any]) -> dict[str, Any]:
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
    if read_model.get("data_status") != "ready":
        label = "Board readiness is unavailable"
        body = read_model.get("status_reason") or "No current governed database run is available."
        status = "missing"
    elif challenged:
        label = "Board pack is not yet clean for release"
        body = f"{challenged} item(s) still need evidence closure before executive release."
        status = "needs_reviewer_closure"
    elif approval_status == "approved" and reports:
        label = "Board pack is approved for release"
        body = f"Approval is recorded and {reports} report surface(s) are available from the governed run."
        status = "release_ready"
    elif approval_status in {"pending", "awaiting_review", ""}:
        label = "Reviewer decision is still open"
        body = "The packet has governed finance evidence, but release still depends on human review."
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
        "secondary_fact": f"As of {read_model.get('as_of')}" if read_model.get("as_of") else "Current governed data",
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
    hero = _hero(read_model)
    drivers = _ceo_kpi_cards(read_model)
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
