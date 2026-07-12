"""Tool registry and validated invocation (design doc section 10).

Tools wrap existing StrategyOS read seams rather than duplicating logic:
findings/citations come from Postgres (state_store.py), graph queries wrap
graph_queries.py's module functions, board-pack/publication wraps api.py's
publication payload builders, and runtime health wraps api.py's
readiness_payload(). Handlers receive a ToolExecutionContext built by the
server (workers.py) -- never a raw bearer token, database URL, or
unrestricted repository, per design doc section 10/13.

Only registry.TOOL_RISK_CLASSES-listed keys may be registered here;
tools.validate_tool_registry() cross-checks the two catalogues agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .. import state_store
from ..config import CONFIG
from .registry import TOOL_RISK_CLASSES


@dataclass(frozen=True)
class ToolExecutionContext:
    """What a tool handler is allowed to see. No bearer tokens, no raw
    database connections, no unrestricted repository objects -- only
    resolved scope. Constructed by workers.py from the task's capability
    token (PR 6) or, in PR 2, directly from the task's context_manifest."""

    tenant_id: str
    task_id: str
    run_id: str | None
    allowed_evidence_ids: tuple[str, ...] = ()


class ToolNotFound(Exception):
    pass


class ToolInputInvalid(Exception):
    pass


# ---------------------------------------------------------------------------
# findings.read
# ---------------------------------------------------------------------------


def _findings_read(ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    """Direct Postgres read over strategyos_findings, scoped to the task's
    run_id. This is deliberately a new reader rather than a reuse of
    api.py's _finding_rows_from_summary (which reads a filesystem knowledge-
    graph artifact) -- Postgres is the durable source of truth an agent task
    should cite against, and the artifact path is UI-presentation-specific."""
    run_id = input.get("run_id") or ctx.run_id
    if not run_id:
        raise ToolInputInvalid("findings.read requires a run_id")

    connection, skipped = state_store.database_connection()
    if skipped is not None:
        return {"available": False, "reason": skipped.get("reason", "database unavailable"), "findings": []}

    assert connection is not None
    with connection as conn:
        state_store.ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    id::text as id,
                    run_id::text as run_id,
                    finding_id,
                    pattern_type,
                    vendor_id,
                    vendor_name,
                    status,
                    confidence,
                    leakage_sar,
                    recoverable_sar,
                    finding_json
                from strategyos_findings
                where run_id = %s
                order by recoverable_sar desc, finding_id
                """,
                (run_id,),
            )
            rows = state_store.fetchall_dicts(cur)
        conn.commit()
    findings = [state_store.normalize_record(row) for row in rows]
    return {"available": True, "run_id": run_id, "findings": findings, "count": len(findings)}


def _citations_search(ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    run_id = input.get("run_id") or ctx.run_id
    if not run_id:
        raise ToolInputInvalid("citations.search requires a run_id")
    citations = state_store.search_citations_for_run(run_id)
    finding_id = input.get("finding_id")
    if finding_id:
        citations = [c for c in citations if c.get("finding_id") == finding_id]
    return {"run_id": run_id, "citations": citations, "count": len(citations)}


def _finance_facts_read(ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    """Reads strategyos_finance_facts, tenant-scoped. Optional module/
    fact_type/period_key filters narrow the result for a specific KPI
    investigation without exposing the whole tenant's fact table."""
    connection, skipped = state_store.database_connection()
    if skipped is not None:
        return {"available": False, "reason": skipped.get("reason", "database unavailable"), "facts": []}

    filters = ["tenant_id = %s"]
    params: list[Any] = [ctx.tenant_id]
    for column, key in (("module", "module"), ("fact_type", "fact_type"), ("period_key", "period_key")):
        value = input.get(key)
        if value:
            filters.append(f"{column} = %s")
            params.append(value)
    where_clause = " and ".join(filters)
    limit = min(int(input.get("limit", 200) or 200), 1000)

    assert connection is not None
    with connection as conn:
        state_store.ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select id::text as id, tenant_id::text as tenant_id, module, fact_type, natural_key,
                       period_key, cadence, bu_code, cost_centre, account_code, amount_value,
                       currency, reporting_currency, source_locator, created_at
                from strategyos_finance_facts
                where {where_clause}
                order by period_key desc, module, fact_type
                limit %s
                """,
                (*params, limit),
            )
            rows = state_store.fetchall_dicts(cur)
        conn.commit()
    facts = [state_store.normalize_record(row) for row in rows]
    return {"available": True, "facts": facts, "count": len(facts)}


def _graph_query(ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    """Dispatches to graph_queries.py's module-level functions, which never
    raise and already return a uniform {available, matched, ...} envelope --
    no exception handling needed here."""
    from .. import graph_queries

    run_id = input.get("run_id") or ctx.run_id
    query_type = input.get("query_type")
    limit = int(input.get("limit", 25) or 25)

    if query_type == "vendor_collusion_clusters":
        return graph_queries.vendor_collusion_clusters(run_id, limit=limit)
    if query_type == "finding_evidence_chain":
        finding_id = input.get("finding_id")
        if not finding_id:
            raise ToolInputInvalid("graph.query finding_evidence_chain requires finding_id")
        return graph_queries.finding_evidence_chain(run_id, finding_id, limit=limit)
    if query_type == "vendor_finding_exposure":
        vendor_id = input.get("vendor_id")
        if not vendor_id:
            raise ToolInputInvalid("graph.query vendor_finding_exposure requires vendor_id")
        return graph_queries.vendor_finding_exposure(run_id, vendor_id, limit=limit)
    if query_type == "shared_evidence_findings":
        return graph_queries.shared_evidence_findings(run_id, limit=limit)
    if query_type == "vendor_contract_gaps":
        return graph_queries.vendor_contract_gaps(run_id, limit=limit)
    raise ToolInputInvalid(f"graph.query: unknown query_type {query_type!r}")


def _board_pack_prepare(ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    """Wraps api.py's existing publication-payload builders instead of the
    fixture-backed twins/orchestration.py:generate_board_packet, which
    operates over the mocked KPI_TREE, not real finance findings.

    _summary_publication_payload/_summary_report_contracts read top-level
    keys (status, approval_status, current_stage, artifacts) off `summary`,
    which is exactly the flattened shape state_store.get_run_detail()
    returns -- not the nested summary_json blob."""
    from .. import api as api_module

    run_id = input.get("run_id") or ctx.run_id
    if not run_id:
        raise ToolInputInvalid("board_pack.prepare requires a run_id")
    summary = state_store.get_run_detail(run_id)
    # get_run_detail()/database_connection() share the "missing"/"skipped"
    # sentinel convention used throughout state_store.py and api.py's
    # _require_store_record(); a real run's own `status` (running/
    # completed/...) never collides with these two sentinel values.
    if summary.get("status") in ("missing", "skipped"):
        return {"available": False, "run_id": run_id, "reason": summary.get("reason") or summary.get("status")}
    publication = api_module._summary_publication_payload(
        summary, principal_role=input.get("principal_role"), public_safe=bool(input.get("public_safe", False))
    )
    reports = api_module._summary_report_contracts(summary)
    return {"available": True, "run_id": run_id, "publication": publication, "reports": reports}


def _review_request(ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    """Reads the existing reviewer-queue status for a run rather than
    creating a second approval mechanism (design doc section 11: link to
    strategyos_approvals, don't duplicate it)."""
    run_id = input.get("run_id") or ctx.run_id
    if not run_id:
        raise ToolInputInvalid("review.request requires a run_id")
    status = state_store.approval_status_for_run(run_id)
    return {"run_id": run_id, "approval_status": status}


def _runtime_health_read(ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    from .. import api as api_module
    from .. import hatchet_runtime

    payload = api_module.readiness_payload()
    payload["hatchet"] = hatchet_runtime.hatchet_dependency_status(CONFIG, verify_connection=False)
    return payload


ToolHandler = Callable[[ToolExecutionContext, dict[str, Any]], dict[str, Any]]

TOOL_HANDLERS: dict[str, ToolHandler] = {
    "findings.read": _findings_read,
    "citations.search": _citations_search,
    "finance_facts.read": _finance_facts_read,
    "graph.query": _graph_query,
    "board_pack.prepare": _board_pack_prepare,
    "review.request": _review_request,
    "runtime.health.read": _runtime_health_read,
}


def validate_tool_registry() -> None:
    """Every handler must be a catalogued, risk-classed tool key, and every
    read_only/prepare tool referenced by an agent definition should have a
    handler here by PR 2 (restricted tools like publication.release are
    intentionally still unimplemented -- PR 6 territory)."""
    unknown = set(TOOL_HANDLERS.keys()) - set(TOOL_RISK_CLASSES.keys())
    if unknown:
        raise ValueError(f"tool handlers registered for uncatalogued tool keys: {sorted(unknown)}")


def invoke_tool(tool_key: str, ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    handler = TOOL_HANDLERS.get(tool_key)
    if handler is None:
        raise ToolNotFound(f"no handler registered for tool key {tool_key!r}")
    return handler(ctx, input)
