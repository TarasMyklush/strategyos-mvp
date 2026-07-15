from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


ALLOWED_LIVE_CLAIM_CLASSES = {
    "db_fact",
    "db_aggregate",
    "db_derived",
    # A lever is arithmetic on governed data offered as something to act on --
    # "Salaries are 26.3% of opex; 5% is SAR 1.2M". The number is as real as any
    # db_derived value, but the framing invites a decision, and no budget or
    # benchmark in the run says the line is wrong. It therefore cannot wear the
    # same badge as "Revenue is SAR 385.1M": a fact and a judgement must be
    # distinguishable on the surface, or the badge stops meaning anything.
    "db_derived_lever",
    "artifact_fact",
    "artifact_aggregate",
    "artifact_derived",
    "ui_copy",
}

# What a claim class is allowed to say about itself on the executive surface.
CLAIM_CLASS_DISPLAY = {
    "db_derived_lever": "Suggested · from your GL, not yet reviewed",
}
PUBLIC_RUN_ALIAS = "latest-public"
TRUTH_SOURCES = {"database", "governed_artifacts"}


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


def _as_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _truth_contract(truth_source: str) -> tuple[str, str]:
    if truth_source not in TRUTH_SOURCES:
        raise ValueError(f"unsupported executive truth source: {truth_source}")
    if truth_source == "database":
        return "db", "strategyos"
    return "artifact", "governed_artifact"


def _claim_class(truth_source: str, kind: str) -> str:
    prefix, _ = _truth_contract(truth_source)
    return f"{prefix}_{kind}"


def _source(truth_source: str, database_path: str, artifact_path: str) -> str:
    return database_path if truth_source == "database" else artifact_path


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
    truth_source: str,
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
                    claim_class=_claim_class(truth_source, "fact"),
                    run_id=run_id,
                    as_of=as_of,
                    source=_source(truth_source, "strategyos_findings.finding_id", "governed_artifact.findings.finding_id"),
                ),
                "title": claim(
                    str(title),
                    claim_class=_claim_class(truth_source, "fact"),
                    run_id=run_id,
                    as_of=as_of,
                    source=_source(truth_source, "strategyos_findings.finding_json.title", "governed_artifact.findings.title"),
                ),
                "pattern_label": claim(
                    _safe_label(pattern, "Governed Finance Finding"),
                    claim_class=_claim_class(truth_source, "derived"),
                    run_id=run_id,
                    as_of=as_of,
                    source=_source(truth_source, "strategyos_findings.pattern_type", "governed_artifact.findings.pattern_type"),
                    derivation="controlled_pattern_label",
                ),
                "recoverable_sar": claim(
                    recoverable,
                    claim_class=_claim_class(truth_source, "fact"),
                    run_id=run_id,
                    as_of=as_of,
                    source=_source(truth_source, "strategyos_findings.recoverable_sar", "governed_artifact.findings.recoverable_sar"),
                ),
                "citation_count": claim(
                    citation_count,
                    claim_class=_claim_class(truth_source, "aggregate"),
                    run_id=run_id,
                    as_of=as_of,
                    source=_source(truth_source, "strategyos_finding_citations", "governed_artifact.knowledge_graph.supported_by"),
                    record_count=citation_count,
                    derivation="count(citations by finding)",
                ),
                "challenged": claim(
                    bool(row.get("challenged")),
                    claim_class=_claim_class(truth_source, "fact"),
                    run_id=run_id,
                    as_of=as_of,
                    source=_source(truth_source, "strategyos_findings.status", "governed_artifact.audit_log.current_state"),
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
    *,
    truth_source: str = "governed_artifacts",
    source_status_reason: str | None = None,
) -> dict[str, Any]:
    _truth_contract(truth_source)
    rows = list(finding_rows or [])
    run_id = _real_run_id(summary)
    as_of = _iso_or_none((summary or {}).get("created_at") or (summary or {}).get("updated_at"))
    data_status = "ready" if summary and run_id else "missing"
    status_reason = source_status_reason or (
        "Current governed database run is available."
        if data_status == "ready" and truth_source == "database"
        else "Current governed artifact run is available; database truth is unavailable."
        if data_status == "ready"
        else "No current governed run is available."
    )
    total_recoverable = round(sum(_as_float(row.get("recoverable_sar")) for row in rows), 2)
    finding_citation_count = sum(_as_int(row.get("citation_count")) for row in rows)
    audited_citation_count = _as_optional_int((audit_summary or {}).get("citation_count"))
    citation_count = (
        audited_citation_count
        if audited_citation_count is not None
        else finding_citation_count
    )
    resolved_count = _as_optional_int((audit_summary or {}).get("resolved_count"))
    challenged_count = sum(1 for row in rows if row.get("challenged"))
    report_count = _as_optional_int((publication or {}).get("report_count"))
    approval_status = str((summary or {}).get("approval_status") or "pending").lower()
    current_stage = str((summary or {}).get("current_stage") or "unknown").lower()
    metrics = {
        "recoverable_total": claim(
            total_recoverable,
            claim_class=_claim_class(truth_source, "aggregate"),
            run_id=run_id,
            as_of=as_of,
            source=_source(truth_source, "strategyos_findings.recoverable_sar", "governed_artifact.findings.recoverable_sar"),
            record_count=len(rows),
            derivation="sum(recoverable_sar)",
            complete=bool(summary),
        ),
        "finding_count": claim(
            len(rows),
            claim_class=_claim_class(truth_source, "aggregate"),
            run_id=run_id,
            as_of=as_of,
            source=_source(truth_source, "strategyos_findings", "governed_artifact.findings"),
            record_count=len(rows),
            derivation="count(findings)",
            complete=bool(summary),
        ),
        "citation_resolution": claim(
            {"resolved": resolved_count, "total": citation_count},
            claim_class=_claim_class(truth_source, "aggregate"),
            run_id=run_id,
            as_of=as_of,
            source=_source(truth_source, "strategyos_finding_citations.resolved", "governed_artifact.citation_audit.resolved"),
            record_count=citation_count,
            derivation="count(resolved citations) / count(citations)",
            complete=(
                bool(summary)
                and resolved_count is not None
                and 0 <= resolved_count <= citation_count
            ),
        ),
        "challenged_count": claim(
            challenged_count,
            claim_class=_claim_class(truth_source, "aggregate"),
            run_id=run_id,
            as_of=as_of,
            source=_source(truth_source, "strategyos_findings.status", "governed_artifact.audit_log.current_state"),
            record_count=len(rows),
            derivation="count(challenged findings)",
            complete=bool(summary),
        ),
        "report_count": claim(
            report_count,
            claim_class=_claim_class(truth_source, "aggregate"),
            run_id=run_id,
            as_of=as_of,
            source=_source(truth_source, "strategyos_artifacts", "governed_artifact.report_contracts"),
            record_count=report_count or 0,
            derivation="count(report artifacts)",
            complete=bool(summary) and report_count is not None,
        ),
    }
    return {
        "mode": "live",
        "source": truth_source,
        "run_id": run_id,
        "as_of": as_of,
        "data_status": data_status,
        "status_reason": status_reason,
        "lifecycle": {
            "approval_status": claim(
                approval_status,
                claim_class=_claim_class(truth_source, "fact"),
                run_id=run_id,
                as_of=as_of,
                source=_source(truth_source, "strategyos_runs.approval_status", "governed_artifact.run_summary.approval_status"),
                complete=bool(summary),
            ),
            "current_stage": claim(
                current_stage,
                claim_class=_claim_class(truth_source, "fact"),
                run_id=run_id,
                as_of=as_of,
                source=_source(truth_source, "strategyos_runs.current_stage", "governed_artifact.run_summary.current_stage"),
                complete=bool(summary),
            ),
        },
        "metrics": metrics,
        # This payload is optional because the governed findings run and the
        # Oracle finance snapshot can arrive independently.  The presentation
        # layer accepts it only when it identifies the deterministic Oracle
        # engine; otherwise the CEO KPI cards deliberately render unavailable
        # states rather than borrowing values from a different dataset.
        "oracle_kpi": (
            dict((summary or {}).get("oracle_kpi") or {})
            if isinstance((summary or {}).get("oracle_kpi"), Mapping)
            else {}
        ),
        "finance_kpi": (
            dict((summary or {}).get("finance_kpi") or {})
            if isinstance((summary or {}).get("finance_kpi"), Mapping)
            else {}
        ),
        "findings": _finding_claims(
            rows,
            run_id=run_id,
            as_of=as_of,
            truth_source=truth_source,
        ),
        "developments": {
            "items": [],
            "status": "unavailable",
            "reason": "No persisted prior-snapshot comparison is available for this run.",
        },
        "week_ahead": (
            dict((summary or {}).get("calendar_agenda") or {})
            if isinstance((summary or {}).get("calendar_agenda"), Mapping)
            else {
                "items": [],
                "status": "unavailable",
                "reason": "No governed calendar workbook was supplied for this run.",
            }
        ),
        "agent_activity": {
            "items": list((agent_modules or {}).get("audit_log") or []),
            "status": (
                "db_backed"
                if truth_source == "database" and (agent_modules or {}).get("audit_log")
                else "artifact_backed"
                if (agent_modules or {}).get("audit_log")
                else "capability_only"
            ),
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
