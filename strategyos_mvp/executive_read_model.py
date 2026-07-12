from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


ALLOWED_LIVE_CLAIM_CLASSES = {"db_fact", "db_aggregate", "db_derived", "ui_copy"}
PUBLIC_RUN_ALIAS = "latest-public"


def _real_run_id(summary: Mapping[str, Any] | None) -> str | None:
    if not isinstance(summary, Mapping):
        return None
    candidate = summary.get("_backing_run_id") or summary.get("run_id")
    if not candidate or str(candidate) == PUBLIC_RUN_ALIAS:
        return None
    return str(candidate)


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_label(value: Any, fallback: str) -> str:
    text = str(value or "").replace("_", " ").replace("-", " ").strip()
    return text.title() if text else fallback


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _provenance(
    claim_class: str,
    *,
    run_id: str | None,
    as_of: str | None,
    source: str,
    record_count: int = 1,
    derivation: str = "direct",
    complete: bool = True,
    freshness: str = "current",
) -> dict[str, Any]:
    if claim_class not in ALLOWED_LIVE_CLAIM_CLASSES:
        raise ValueError(f"disallowed live claim class: {claim_class}")
    return {
        "class": claim_class,
        "run_id": run_id,
        "as_of": as_of,
        "source": source,
        "record_count": record_count,
        "derivation": derivation,
        "freshness": freshness,
        "complete": bool(complete),
    }


def claim(
    value: Any,
    *,
    display: str | None = None,
    claim_class: str,
    run_id: str | None,
    as_of: str | None,
    source: str,
    record_count: int = 1,
    derivation: str = "direct",
    complete: bool = True,
) -> dict[str, Any]:
    return {
        "value": value,
        "display": str(display if display is not None else value),
        "provenance": _provenance(
            claim_class,
            run_id=run_id,
            as_of=as_of,
            source=source,
            record_count=record_count,
            derivation=derivation,
            complete=complete,
        ),
    }


def _finding_claims(
    rows: list[dict[str, Any]],
    *,
    run_id: str | None,
    as_of: str | None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        citation_count = _as_int(row.get("citation_count"))
        recoverable = round(_as_float(row.get("recoverable_sar")), 2)
        pattern = row.get("pattern_label") or row.get("pattern_type") or row.get("classification")
        title = row.get("title") or _safe_label(pattern, f"Governed finance finding {index}")
        findings.append(
            {
                "finding_id": claim(
                    row.get("finding_id") or f"finding-{index}",
                    claim_class="db_fact",
                    run_id=run_id,
                    as_of=as_of,
                    source="strategyos_findings.finding_id",
                ),
                "title": claim(
                    str(title),
                    claim_class="db_fact",
                    run_id=run_id,
                    as_of=as_of,
                    source="strategyos_findings.finding_json.title",
                ),
                "pattern_label": claim(
                    _safe_label(pattern, "Governed Finance Finding"),
                    claim_class="db_derived",
                    run_id=run_id,
                    as_of=as_of,
                    source="strategyos_findings.pattern_type",
                    derivation="controlled_pattern_label",
                ),
                "recoverable_sar": claim(
                    recoverable,
                    claim_class="db_fact",
                    run_id=run_id,
                    as_of=as_of,
                    source="strategyos_findings.recoverable_sar",
                ),
                "citation_count": claim(
                    citation_count,
                    claim_class="db_aggregate",
                    run_id=run_id,
                    as_of=as_of,
                    source="strategyos_finding_citations",
                    record_count=citation_count,
                    derivation="count(citations by finding)",
                ),
                "challenged": claim(
                    bool(row.get("challenged")),
                    claim_class="db_fact",
                    run_id=run_id,
                    as_of=as_of,
                    source="strategyos_findings.challenge_state",
                    complete=True,
                ),
            }
        )
    return findings


def build_executive_read_model(
    summary: dict[str, Any] | None,
    finding_rows: list[dict[str, Any]],
    audit_summary: dict[str, Any] | None,
    publication: dict[str, Any] | None,
    agent_modules: dict[str, Any] | None,
) -> dict[str, Any]:
    rows = list(finding_rows or [])
    run_id = _real_run_id(summary)
    as_of = _iso_or_none((summary or {}).get("created_at") or (summary or {}).get("updated_at"))
    data_status = "ready" if summary and run_id else "missing"
    status_reason = (
        "Current governed database run is available."
        if data_status == "ready"
        else "No current governed database run is available."
    )
    total_recoverable = round(sum(_as_float(row.get("recoverable_sar")) for row in rows), 2)
    citation_count = sum(_as_int(row.get("citation_count")) for row in rows)
    resolved_count = _as_int((audit_summary or {}).get("resolved_count"))
    challenged_count = sum(1 for row in rows if row.get("challenged"))
    report_count = _as_int((publication or {}).get("report_count"))
    approval_status = str((summary or {}).get("approval_status") or "pending").lower()
    current_stage = str((summary or {}).get("current_stage") or "unknown").lower()
    metrics = {
        "recoverable_total": claim(
            total_recoverable,
            claim_class="db_aggregate",
            run_id=run_id,
            as_of=as_of,
            source="strategyos_findings.recoverable_sar",
            record_count=len(rows),
            derivation="sum(recoverable_sar)",
            complete=bool(summary),
        ),
        "finding_count": claim(
            len(rows),
            claim_class="db_aggregate",
            run_id=run_id,
            as_of=as_of,
            source="strategyos_findings",
            record_count=len(rows),
            derivation="count(findings)",
            complete=bool(summary),
        ),
        "citation_resolution": claim(
            {"resolved": resolved_count, "total": citation_count},
            claim_class="db_aggregate",
            run_id=run_id,
            as_of=as_of,
            source="strategyos_finding_citations.resolved",
            record_count=citation_count,
            derivation="count(resolved citations) / count(citations)",
            complete=bool(summary),
        ),
        "challenged_count": claim(
            challenged_count,
            claim_class="db_aggregate",
            run_id=run_id,
            as_of=as_of,
            source="strategyos_findings.challenge_state",
            record_count=len(rows),
            derivation="count(challenged findings)",
            complete=bool(summary),
        ),
        "report_count": claim(
            report_count,
            claim_class="db_aggregate",
            run_id=run_id,
            as_of=as_of,
            source="strategyos_artifacts",
            record_count=report_count,
            derivation="count(report artifacts)",
            complete=bool(summary),
        ),
    }
    return {
        "mode": "live",
        "source": "database",
        "run_id": run_id,
        "as_of": as_of,
        "data_status": data_status,
        "status_reason": status_reason,
        "lifecycle": {
            "approval_status": claim(
                approval_status,
                claim_class="db_fact",
                run_id=run_id,
                as_of=as_of,
                source="strategyos_runs.approval_status",
                complete=bool(summary),
            ),
            "current_stage": claim(
                current_stage,
                claim_class="db_fact",
                run_id=run_id,
                as_of=as_of,
                source="strategyos_runs.current_stage",
                complete=bool(summary),
            ),
        },
        "metrics": metrics,
        "findings": _finding_claims(rows, run_id=run_id, as_of=as_of),
        "developments": {
            "items": [],
            "status": "unavailable",
            "reason": "No persisted prior-snapshot comparison is available for this run.",
        },
        "week_ahead": {
            "items": [],
            "status": "unavailable",
            "reason": "No persisted schedule or decision records are available for this run.",
        },
        "agent_activity": {
            "items": list((agent_modules or {}).get("audit_log") or []),
            "status": "db_backed" if (agent_modules or {}).get("audit_log") else "capability_only",
            "reason": "Running-agent claims require persisted task or event records.",
        },
    }


def provenance_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    claim_count = 0
    rejected_count = 0

    def walk(value: Any) -> None:
        nonlocal claim_count, rejected_count
        if isinstance(value, Mapping):
            provenance = value.get("provenance")
            if isinstance(provenance, Mapping):
                claim_count += 1
                if provenance.get("class") not in ALLOWED_LIVE_CLAIM_CLASSES:
                    rejected_count += 1
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return {
        "all_claims_validated": rejected_count == 0,
        "claim_count": claim_count,
        "rejected_claim_count": rejected_count,
    }
