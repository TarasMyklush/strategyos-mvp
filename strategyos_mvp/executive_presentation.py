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
    if total <= 0:
        return "--"
    return f"{int(value.get('resolved') or 0)} / {total}"


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


def _hero(read_model: Mapping[str, Any]) -> dict[str, Any]:
    metrics = read_model.get("metrics") or {}
    lifecycle = read_model.get("lifecycle") or {}
    challenged = int(_claim_value(metrics.get("challenged_count"), 0) or 0)
    reports = int(_claim_value(metrics.get("report_count"), 0) or 0)
    approval_status = str(_claim_value(lifecycle.get("approval_status"), "pending") or "pending").lower()
    citation_value = _claim_value(metrics.get("citation_resolution"), {}) or {}
    citation_total = int(citation_value.get("total") or 0) if isinstance(citation_value, Mapping) else 0
    citation_resolved = int(citation_value.get("resolved") or 0) if isinstance(citation_value, Mapping) else 0
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
        "score_note": "Database-backed board readiness",
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


def build_executive_presentation(read_model: dict[str, Any]) -> dict[str, Any]:
    metrics = read_model.get("metrics") or {}
    hero = _hero(read_model)
    drivers = [
        _metric_card(
            "cash_recovery_opportunity",
            "Cash recovery opportunity",
            metrics.get("recoverable_total") or {},
            formatter="sar",
            detail=(
                "Current governed run; latest governed run cash boundary: recoverable "
                "value is summed from persisted governed findings."
            ),
            sub="Current governed value",
        ),
        _metric_card(
            "cases_in_view",
            "Cases in view",
            metrics.get("finding_count") or {},
            detail=(
                "Board review scope from the latest governed run: finding rows persisted "
                "for the selected run."
            ),
            sub="Governed cases",
        ),
        _metric_card(
            "evidence_readiness",
            "Evidence readiness: challenged CEO review and next action",
            metrics.get("citation_resolution") or {},
            formatter="ratio",
            detail=(
                "Board evidence posture from the latest governed run: challenged items, "
                "CEO review, and next action depend on resolved citations over total "
                "persisted citations."
            ),
            sub="Citation chain",
        ),
        _metric_card(
            "items_needing_closure",
            "Items needing closure",
            metrics.get("challenged_count") or {},
            detail=(
                "Challenged board items from the latest governed run: persisted challenged "
                "items still visible in the review posture."
            ),
            sub="Reviewer attention",
        ),
    ]
    findings, reconciliation = _findings(read_model)
    developments = list((read_model.get("developments") or {}).get("items") or [])
    week = list((read_model.get("week_ahead") or {}).get("items") or [])
    sections = {
        "drivers": drivers,
        "findings": {
            "items": findings,
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
        "source": "database",
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
