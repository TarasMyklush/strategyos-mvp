"""Refresh KPI_TREE node values from a real governed run.

``resolution.KPI_TREE`` is a hardcoded structural fallback (node ids,
owners, thresholds) seeded once into ``KpiRepository`` when it is empty.
Historically the *values* on those nodes never moved past their seeded
placeholders, so the twin dashboards (``/twin/api/kpis/{role}``) always
showed the same fixed numbers regardless of what a real run produced.

This module updates node *values* in the repository from the latest
governed run summary, using :meth:`KpiRepository.update`. It does not
invent mappings: a node is only updated when a real, computed value for
it exists in the run summary. Nodes with no honest source in the current
run are marked ``status="unavailable"`` with an explicit reason rather
than left silently fabricated or silently untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from strategyos_mvp.run_registry import load_latest_run_summary
from strategyos_mvp.twins.store import KpiRepository

# Nodes in resolution.KPI_TREE that have NO honest source in the default
# (non-Oracle-pilot) finance run today. They are Oracle/P&L concepts
# (revenue, margin, COGS) that this codebase only computes when a tenant
# has explicitly ingested Oracle EBS extracts via POST /finance/oracle/ingest
# -- and there is currently no read-back path from that persisted snapshot,
# so refreshing these from "the latest run" would require fabricating a
# mapping that does not exist. Mark them unavailable rather than fake it.
UNMAPPED_ORACLE_SHAPED_NODES: tuple[str, ...] = (
    "margin_q2",
    "revenue_q2",
    "cogs_q2",
    "raw_materials_q2",
)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def refresh_kpis_from_run(
    *, repository: KpiRepository, summary: dict[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    """Refresh KPI node values in *repository* from a governed run.

    Args:
        repository: The KPI repository to update in place.
        summary: A run summary dict (as written to ``run_summary.json``).
            Defaults to the latest governed run on disk.

    Returns:
        A dict of ``{node_id: updated_node}`` for every node this call
        touched (including nodes marked unavailable).
    """
    if summary is None:
        summary = load_latest_run_summary()

    updated: dict[str, dict[str, Any]] = {}

    if summary is None or summary.get("status") == "missing":
        # No governed run on disk yet -- leave existing values untouched
        # rather than overwrite them with an "unavailable" verdict that
        # would just be replacing one kind of stale data with another.
        return updated

    run_id = str(summary.get("run_id") or "") or None
    audit_verification = summary.get("audit_verification")
    if isinstance(audit_verification, dict) and audit_verification:
        updated["finding_adjudication"] = repository.update(
            "finding_adjudication",
            {
                "owner": "reviewer",
                "status": "current" if audit_verification.get("passed") else "attention_needed",
                "value": audit_verification.get("actual_challenged_findings"),
                "value_label": (
                    f"{audit_verification.get('actual_challenged_findings')}/"
                    f"{audit_verification.get('required_challenged_findings')} "
                    "findings challenged"
                ),
                "detail": audit_verification.get("detail"),
                "challenged_finding_ids": audit_verification.get("challenged_finding_ids") or [],
                "rounds_completed": audit_verification.get("rounds_completed"),
                "run_id": run_id,
                "last_updated": _timestamp(),
                "source": "run_summary.audit_verification",
            },
        )
        updated["compliance_status"] = repository.update(
            "compliance_status",
            {
                "owner": "reviewer",
                "status": "current" if audit_verification.get("passed") else "attention_needed",
                "value": bool(audit_verification.get("passed")),
                "value_label": "pass" if audit_verification.get("passed") else "fail",
                "detail": audit_verification.get("detail"),
                "run_id": run_id,
                "last_updated": _timestamp(),
                "source": "run_summary.audit_verification",
            },
        )

    total_recoverable = summary.get("total_recoverable_sar")
    if total_recoverable is not None:
        updated["recoverable_leakage_q2"] = repository.update(
            "recoverable_leakage_q2",
            {
                "owner": "cfo",
                "status": "current",
                "value": total_recoverable,
                "value_label": f"SAR {float(total_recoverable):,.2f} recoverable",
                "locked_findings": summary.get("locked_findings"),
                "run_id": run_id,
                "last_updated": _timestamp(),
                "source": "run_summary.total_recoverable_sar",
            },
        )

    for node_id in UNMAPPED_ORACLE_SHAPED_NODES:
        existing = repository.load(node_id) or {}
        if existing.get("status") == "unavailable":
            continue
        updated[node_id] = repository.update(
            node_id,
            {
                "status": "unavailable",
                "value": None,
                "detail": (
                    "No governed-run source for this KPI today. Revenue/margin/COGS "
                    "are Oracle EBS concepts computed only via POST /finance/oracle/ingest "
                    "+ /finance/oracle/validate, and there is no persisted-snapshot "
                    "read-back path yet -- see the Oracle KPI engine in oracle_finance.py."
                ),
                "last_updated": _timestamp(),
                "source": "kpi_ingest.unmapped",
            },
        )

    return updated
