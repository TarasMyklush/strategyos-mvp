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

    gaps = []
    if unresolved:
        gaps.append(f"{len(unresolved)} citation(s) failed hash/content resolution")
    if unsupported_findings:
        gaps.append(f"{len(unsupported_findings)} requested finding(s) have no citation on record: " + ", ".join(unsupported_findings))

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
        },
        "citations": result_citations,
        "confidence": confidence,
        "gaps": gaps,
        "proposed_actions": [],
        "artifacts": [],
        "metrics": {},
    }


HANDLER_KEY_TO_FUNCTION = {
    "cash_recovery.v1": cash_recovery_handler,
    "evidence_closure.v1": evidence_closure_handler,
}


def validate_worker_registry() -> None:
    """Every implemented handler must correspond to a real registered agent
    definition's handler_key. The inverse (every definition has a handler)
    is NOT required here -- board_pack.v1/runtime_guardrail.v1 are
    intentionally unimplemented until PR 4."""
    known_handler_keys = {d.handler_key for d in AGENT_DEFINITIONS_BY_KEY.values()}
    unknown = set(HANDLER_KEY_TO_FUNCTION.keys()) - known_handler_keys
    if unknown:
        raise ValueError(f"worker handlers registered for unknown handler_keys: {sorted(unknown)}")


def run_handler(handler_key: str, ctx: ToolExecutionContext, input: dict[str, Any]) -> dict[str, Any]:
    handler = HANDLER_KEY_TO_FUNCTION.get(handler_key)
    if handler is None:
        raise HandlerInputInvalid(f"no handler implemented for handler_key {handler_key!r}")
    return handler(ctx, input)
