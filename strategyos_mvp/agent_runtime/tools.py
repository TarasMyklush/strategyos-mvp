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
    resolved scope, plus (as of PR 6) the verified capability_claims a
    handler must pass through to invoke_tool() for any non-read_only tool
    call. Constructed by workflows.py from the task's issued capability
    token; a handler never mints or re-verifies a token itself."""

    tenant_id: str
    task_id: str
    run_id: str | None
    allowed_evidence_ids: tuple[str, ...] = ()
    capability_claims: Any | None = None


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


def _publication_release(ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    """Deliberately read-only, despite being catalogued as a "restricted"
    tool. The existing publication mutation (_record_reviewer_decision /
    POST /reviewer/runs/{run_id}/approve) already requires an authenticated
    human reviewer identity, a claimed checkpoint, and a fingerprint match
    -- design doc section 20 explicitly excludes agents from performing
    consequential mutations directly in this release ("agents transferring
    funds, editing ERP records, or emailing third parties" is the named
    non-goal category; publication release is the same class of action).
    An agent task can only report whether a run is eligible for release
    and what would still block it; the actual state change stays exclusively
    on the existing human-reviewer HTTP path. This satisfies "restricted"
    classification (it still requires a valid capability token to invoke)
    without giving a worker the power to publish anything itself."""
    run_id = input.get("run_id") or ctx.run_id
    if not run_id:
        raise ToolInputInvalid("publication.release requires a run_id")
    approval_status = state_store.approval_status_for_run(run_id)
    if isinstance(approval_status, dict) and approval_status.get("status") == "missing":
        return {"available": False, "run_id": run_id, "reason": "run not found"}
    eligible = (
        isinstance(approval_status, dict)
        and approval_status.get("approval_status") == "approved"
    )
    return {
        "available": True,
        "run_id": run_id,
        "release_eligible": eligible,
        "approval_status": approval_status,
        "blocking_reason": None if eligible else "run has not been approved by a human reviewer",
    }


def _remediation_propose(ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    """Cash Recovery's one named consequential capability (design doc
    section 2: "create remediation proposal; never move money"). This tool
    performs a REAL, durable, agent_runtime-owned side effect -- unlike
    publication.release/board_pack.prepare, which are deliberately
    read-only reports over an existing human-only mutation path. It never
    touches strategyos_findings or any other pipeline-owned table (that
    would be the kind of consequential pipeline mutation section 20
    excludes from this release); it only records, within agent_runtime's
    own schema, that a remediation proposal was raised for a
    (task, finding) pair -- exactly the kind of durable "prepare a change
    without applying it" record design principle 9 describes.

    Effect-key reservation (design doc section 14 step 5: "External-effect
    tools reserve a unique effect key before execution") is what actually
    guarantees at-least-once task execution produces effectively-once
    effects here: a retried task with the same task_id+finding_id reserves
    the same effect_key and gets EffectAlreadyReserved back instead of
    inserting a second artifact_links row."""
    from . import repository

    finding_id = input.get("finding_id")
    if not finding_id:
        raise ToolInputInvalid("remediation.propose requires a finding_id")
    reason = input.get("reason") or "Cash Recovery Agent proposed remediation"

    effect_key = f"remediation-proposal:{ctx.task_id}:{finding_id}"
    input_hash = repository.hash_scope({"finding_id": finding_id, "reason": reason})

    try:
        invocation = repository.reserve_tool_effect(
            ctx.tenant_id, ctx.task_id,
            task_attempt_id=None,
            tool_key="remediation.propose", tool_version="v1",
            input_hash=input_hash, effect_key=effect_key,
        )
    except repository.EffectAlreadyReserved as exc:
        # Already reserved by a prior attempt -- report the existing
        # invocation's outcome rather than raising or silently re-applying.
        return {
            "available": True,
            "finding_id": finding_id,
            "already_proposed": True,
            "status": exc.existing_invocation.get("status"),
        }

    try:
        artifact_link = repository.create_artifact_link(
            ctx.tenant_id, task_id=ctx.task_id,
            reference_type="remediation_proposal", reference_id=finding_id,
        )
        repository.record_tool_invocation_result(
            ctx.tenant_id, invocation["tool_invocation_id"], status="succeeded",
            output_hash=repository.hash_scope({"artifact_link_id": artifact_link["artifact_link_id"]}),
        )
    except Exception as exc:
        repository.record_tool_invocation_result(
            ctx.tenant_id, invocation["tool_invocation_id"], status="failed", error_code=type(exc).__name__,
        )
        raise
    return {
        "available": True,
        "finding_id": finding_id,
        "already_proposed": False,
        "status": "succeeded",
        "artifact_link_id": artifact_link["artifact_link_id"],
    }


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
    "publication.release": _publication_release,
    "remediation.propose": _remediation_propose,
    "runtime.health.read": _runtime_health_read,
}


def validate_tool_registry() -> None:
    """Every handler must be a catalogued, risk-classed tool key, and every
    tool key actually referenced by a shipped agent definition must have an
    implemented handler. TOOL_RISK_CLASSES may still list a tool
    (finance_controls.run) that no current agent uses and that has no
    Postgres-backed seam to wrap -- skills/finance_controls.py operates on
    an in-memory DataBundle from the live finance-run pipeline, not
    historical Postgres state, so it cannot be called from an after-the-
    fact agent task without re-running the whole pipeline. It stays
    catalogued (a future agent might reference it) but unimplemented is
    not an error until something actually depends on it."""
    from .registry import AGENT_DEFINITIONS

    unknown = set(TOOL_HANDLERS.keys()) - set(TOOL_RISK_CLASSES.keys())
    if unknown:
        raise ValueError(f"tool handlers registered for uncatalogued tool keys: {sorted(unknown)}")
    referenced_tool_keys = {key for definition in AGENT_DEFINITIONS for key in definition.tool_keys}
    missing = referenced_tool_keys - set(TOOL_HANDLERS.keys())
    if missing:
        raise ValueError(f"agent-referenced tool keys have no implemented handler: {sorted(missing)}")


def invoke_tool(
    tool_key: str,
    ctx: ToolExecutionContext,
    input: dict[str, Any],
    *,
    capability_claims: Any | None = None,
) -> dict[str, Any]:
    """A verified capability token (capability_tokens.CapabilityClaims) is
    required for prepare/write/restricted tools -- design doc section 13:
    "Tool dispatch verifies it." Defaults to ctx.capability_claims so a
    handler calling invoke_tool(key, ctx, input) doesn't need to
    separately thread the token through every call site; pass
    capability_claims explicitly only to override that default. Read-only
    tools remain callable without a token."""
    if capability_claims is None:
        capability_claims = ctx.capability_claims
    handler = TOOL_HANDLERS.get(tool_key)
    if handler is None:
        raise ToolNotFound(f"no handler registered for tool key {tool_key!r}")

    tool_risk_class = TOOL_RISK_CLASSES.get(tool_key, "restricted")
    if tool_risk_class != "read_only":
        if capability_claims is None:
            raise ToolInputInvalid(
                f"tool {tool_key!r} (risk class {tool_risk_class!r}) requires a verified capability token"
            )
        from .capability_tokens import authorize_tool_call

        authorize_tool_call(capability_claims, tool_key=tool_key, tool_risk_class=tool_risk_class)
    return handler(ctx, input)
