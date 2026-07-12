"""Specialist agent handlers (design doc section 2 catalogue).

A handler receives a task's input + a ToolExecutionContext and returns a
dict matching the AgentResult envelope (models.py). PR 2 ships the two
read-only handlers named in the design doc's migration sequence: Cash
Recovery and Evidence Closure. Board Pack and Runtime Guardrail handlers
land in PR 4 alongside real handoff wiring.

Handlers must not call repository.py or events.py directly -- workflows.py
owns the task-attempt lifecycle around a handler call (create attempt,
invoke handler, record result, transition task). A handler is a pure
function of (context, input) -> result; it does not know it is running
inside Hatchet.
"""

from __future__ import annotations

from typing import Any

from .registry import AGENT_DEFINITIONS_BY_KEY
from .tools import ToolExecutionContext, invoke_tool


class HandlerInputInvalid(Exception):
    pass


def _citation_coverage(findings: list[dict[str, Any]], citations: list[dict[str, Any]]) -> dict[str, Any]:
    citation_counts: dict[str, int] = {}
    for citation in citations:
        finding_id = citation.get("finding_id")
        if finding_id:
            citation_counts[finding_id] = citation_counts.get(finding_id, 0) + 1

    weak_findings = [
        finding["finding_id"]
        for finding in findings
        if citation_counts.get(finding["finding_id"], 0) == 0
    ]
    return {"citation_counts": citation_counts, "weak_findings": weak_findings}


def cash_recovery_handler(ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    """Handler for handler_key cash_recovery.v1 (quantify_recoverable_value,
    monitor_recovery_case). Reads governed findings for the task's run,
    quantifies recoverable value, and reports a citation-coverage gap that
    a caller (workflows.py) can use to decide whether a resolve_evidence_gap
    handoff is warranted -- this handler does not create the handoff itself,
    per design doc section 8.3 step 1 (the worker "emits a typed handoff
    proposal", which is workflows.py's job, not the handler's)."""
    run_id = input.get("run_id") or ctx.run_id
    if not run_id:
        raise HandlerInputInvalid("cash_recovery_handler requires a run_id")

    findings_result = invoke_tool("findings.read", ctx, {"run_id": run_id})
    if not findings_result.get("available"):
        return {
            "summary": "Findings are not available for this run.",
            "status": "insufficient_evidence",
            "data": {},
            "citations": [],
            "confidence": "low",
            "gaps": [findings_result.get("reason") or "findings unavailable"],
            "proposed_actions": [],
            "artifacts": [],
            "metrics": {},
        }

    findings = findings_result.get("findings", [])
    citations_result = invoke_tool("citations.search", ctx, {"run_id": run_id})
    citations = citations_result.get("citations", [])
    coverage = _citation_coverage(findings, citations)

    total_recoverable = sum(float(f.get("recoverable_sar") or 0.0) for f in findings)
    locked_recoverable = sum(
        float(f.get("recoverable_sar") or 0.0) for f in findings if f.get("status") == "locked"
    )

    result_citations = [
        {"kind": "finding", "id": f["finding_id"], "locator": "recoverable_sar"}
        for f in findings[:20]
    ]

    if not findings:
        return {
            "summary": f"No findings are recorded for run {run_id}.",
            "status": "insufficient_evidence",
            "data": {"run_id": run_id, "finding_count": 0},
            "citations": [],
            "confidence": "low",
            "gaps": ["no findings recorded for this run"],
            "proposed_actions": [],
            "artifacts": [],
            "metrics": {},
        }

    gaps = []
    if coverage["weak_findings"]:
        gaps.append(
            f"{len(coverage['weak_findings'])} finding(s) have no resolvable citation: "
            f"{', '.join(coverage['weak_findings'][:10])}"
        )

    confidence = "high" if not gaps else ("medium" if len(coverage["weak_findings"]) < len(findings) else "low")

    return {
        "summary": (
            f"{len(findings)} finding(s) explain SAR {total_recoverable:,.0f} recoverable "
            f"(SAR {locked_recoverable:,.0f} locked)."
        ),
        "status": "complete" if not gaps else "complete",
        "data": {
            "run_id": run_id,
            "finding_count": len(findings),
            "total_recoverable_sar": total_recoverable,
            "locked_recoverable_sar": locked_recoverable,
            "weak_findings": coverage["weak_findings"],
        },
        "citations": result_citations,
        "confidence": confidence,
        "gaps": gaps,
        "proposed_actions": (
            [
                {
                    "action": "resolve_evidence_gap",
                    "reason": "Citation coverage is below policy",
                    "run_id": run_id,
                    "finding_ids": coverage["weak_findings"],
                }
            ]
            if coverage["weak_findings"]
            else []
        ),
        "artifacts": [],
        "metrics": {},
    }


def evidence_closure_handler(ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    """Handler for handler_key evidence_closure.v1 (resolve_evidence_gap,
    challenge_finding). Resolves citation status for the requested finding
    IDs (or every finding on the run if none given) and reports which
    findings remain unsupported."""
    run_id = input.get("run_id") or ctx.run_id
    if not run_id:
        raise HandlerInputInvalid("evidence_closure_handler requires a run_id")

    requested_finding_ids = set(input.get("finding_ids") or [])
    citations_result = invoke_tool("citations.search", ctx, {"run_id": run_id})
    citations = citations_result.get("citations", [])

    if requested_finding_ids:
        citations = [c for c in citations if c.get("finding_id") in requested_finding_ids]

    resolved = [c for c in citations if c.get("resolved")]
    unresolved = [c for c in citations if not c.get("resolved")]

    findings_with_citations = {c.get("finding_id") for c in citations}
    unsupported_findings = sorted(requested_finding_ids - findings_with_citations) if requested_finding_ids else []

    result_citations = [
        {"kind": "citation", "id": c["citation_id"], "locator": c.get("locator", "")}
        for c in resolved[:20]
    ]

    # Read the underlying evidence excerpt for a bounded sample of resolved
    # citations (design doc section 13: cap retrieved documents), always
    # through evidence.read -- which always routes text through the
    # prompt-injection guard, never returning raw excerpt text. A citation
    # whose evidence trips the scanner is surfaced as a gap, not silently
    # incorporated, since injected instruction text inside client-supplied
    # evidence must never be treated as trustworthy content to act on.
    flagged_citation_ids: list[str] = []
    for citation in resolved[:5]:
        evidence_result = invoke_tool(
            "evidence.read", ctx, {"run_id": run_id, "citation_id": citation.get("citation_id")}
        )
        if evidence_result.get("available") and evidence_result.get("contains_prompt_injection_signals"):
            flagged_citation_ids.append(citation.get("citation_id"))

    gaps = []
    if unresolved:
        gaps.append(f"{len(unresolved)} citation(s) failed hash/content resolution")
    if unsupported_findings:
        gaps.append(f"{len(unsupported_findings)} requested finding(s) have no citation on record: " + ", ".join(unsupported_findings))
    if flagged_citation_ids:
        gaps.append(
            f"{len(flagged_citation_ids)} citation(s) contain prompt-injection signals in their evidence text "
            f"and were not treated as trustworthy content: {', '.join(flagged_citation_ids)}"
        )

    if not citations and not unsupported_findings:
        return {
            "summary": f"No citations found for run {run_id}.",
            "status": "insufficient_evidence",
            "data": {"run_id": run_id},
            "citations": [],
            "confidence": "low",
            "gaps": ["no citations recorded for this run"],
            "proposed_actions": [],
            "artifacts": [],
            "metrics": {},
        }

    confidence = "high" if not gaps else ("medium" if resolved else "low")
    status = "complete" if (resolved or not requested_finding_ids) else "insufficient_evidence"

    return {
        "summary": (
            f"{len(resolved)} of {len(citations)} citation(s) resolved"
            + (f"; {len(unsupported_findings)} finding(s) unsupported" if unsupported_findings else "")
            + "."
        ),
        "status": status,
        "data": {
            "run_id": run_id,
            "resolved_count": len(resolved),
            "unresolved_count": len(unresolved),
            "unsupported_findings": unsupported_findings,
            "flagged_citation_ids": flagged_citation_ids,
        },
        "citations": result_citations,
        "confidence": confidence,
        "gaps": gaps,
        "proposed_actions": [],
        "artifacts": [],
        "metrics": {},
    }


def board_pack_handler(ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    """Handler for handler_key board_pack.v1 (prepare_board_pack,
    explain_publication_posture). Wraps the board_pack.prepare tool, which
    itself wraps api.py's real publication-payload builders -- this handler
    never invents a "published" status; it reports whatever the existing
    reviewer/publication gate currently says."""
    run_id = input.get("run_id") or ctx.run_id
    if not run_id:
        raise HandlerInputInvalid("board_pack_handler requires a run_id")

    board_pack_result = invoke_tool(
        "board_pack.prepare", ctx,
        {"run_id": run_id, "principal_role": input.get("principal_role"), "public_safe": input.get("public_safe", False)},
    )
    if not board_pack_result.get("available"):
        return {
            "summary": "The board pack could not be prepared for this run.",
            "status": "insufficient_evidence",
            "data": {"run_id": run_id},
            "citations": [],
            "confidence": "low",
            "gaps": [board_pack_result.get("reason") or "run not found"],
            "proposed_actions": [],
            "artifacts": [],
            "metrics": {},
        }

    publication = board_pack_result.get("publication", {})
    reports = board_pack_result.get("reports", {})
    release_status = (publication.get("board_pack") or {}).get("status") or publication.get("publish_state")
    report_count = (publication.get("board_pack") or {}).get("report_count", 0)
    evidence_count = (publication.get("board_pack") or {}).get("evidence_count", 0)

    gaps = []
    proposed_actions = []
    if release_status not in ("published", "approved_for_release"):
        gaps.append(f"Board pack release status is {release_status!r}; not yet approved or published.")
        proposed_actions.append({"action": "review.request", "reason": "Board pack awaiting reviewer decision", "run_id": run_id})

    return {
        "summary": f"Board pack for run {run_id} is {release_status} with {report_count} report(s), {evidence_count} evidence item(s).",
        "status": "complete",
        "data": {
            "run_id": run_id,
            "release_status": release_status,
            "report_count": report_count,
            "evidence_count": evidence_count,
        },
        "citations": [],
        "confidence": "high" if not gaps else "medium",
        "gaps": gaps,
        "proposed_actions": proposed_actions,
        "artifacts": [],
        "metrics": {},
    }


def runtime_guardrail_handler(ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    """Handler for handler_key runtime_guardrail.v1 (inspect_runtime_health,
    diagnose_connector_or_queue). Wraps runtime.health.read, which itself
    wraps the existing readiness_payload()/hatchet_dependency_status()
    functions -- no synthetic health data."""
    health = invoke_tool("runtime.health.read", ctx, {})
    overall_status = health.get("status", "unknown")
    checks = health.get("checks", {})

    failing = [name for name, result in checks.items() if isinstance(result, dict) and result.get("status") == "failed"]
    degraded = [name for name, result in checks.items() if isinstance(result, dict) and result.get("status") == "skipped"]

    gaps = []
    if failing:
        gaps.append(f"{len(failing)} subsystem(s) failing: {', '.join(failing)}")
    if degraded:
        gaps.append(f"{len(degraded)} subsystem(s) degraded/skipped: {', '.join(degraded)}")

    hatchet_status = health.get("hatchet", {}).get("status", "unknown")
    if hatchet_status == "failed":
        gaps.append(f"Hatchet task queue is unhealthy: {health.get('hatchet', {}).get('reason', 'unknown reason')}")

    confidence = "high" if overall_status == "ok" else ("medium" if overall_status == "degraded" else "low")

    return {
        "summary": f"Runtime status is {overall_status}" + (f"; {len(failing)} subsystem(s) failing" if failing else "."),
        "status": "complete",
        "data": {
            "overall_status": overall_status,
            "failing_subsystems": failing,
            "degraded_subsystems": degraded,
            "hatchet_status": hatchet_status,
        },
        "citations": [],
        "confidence": confidence,
        "gaps": gaps,
        "proposed_actions": [],
        "artifacts": [],
        "metrics": {},
    }


HANDLER_KEY_TO_FUNCTION = {
    "cash_recovery.v1": cash_recovery_handler,
    "evidence_closure.v1": evidence_closure_handler,
    "board_pack.v1": board_pack_handler,
    "runtime_guardrail.v1": runtime_guardrail_handler,
}


def validate_worker_registry() -> None:
    """Every implemented handler must correspond to a real registered agent
    definition's handler_key, and as of PR 4 every catalogued agent
    definition must have an implemented handler."""
    known_handler_keys = {d.handler_key for d in AGENT_DEFINITIONS_BY_KEY.values()}
    unknown = set(HANDLER_KEY_TO_FUNCTION.keys()) - known_handler_keys
    if unknown:
        raise ValueError(f"worker handlers registered for unknown handler_keys: {sorted(unknown)}")
    missing = known_handler_keys - set(HANDLER_KEY_TO_FUNCTION.keys())
    if missing:
        raise ValueError(f"agent definitions have no implemented handler: {sorted(missing)}")


def run_handler(handler_key: str, ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    handler = HANDLER_KEY_TO_FUNCTION.get(handler_key)
    if handler is None:
        raise HandlerInputInvalid(f"no handler implemented for handler_key {handler_key!r}")
    return handler(ctx, input)
