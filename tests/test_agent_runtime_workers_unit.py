"""Pure-unit tests for agent_runtime.workers -- no Postgres required.

Handlers are pure functions of (ToolExecutionContext, input) that call
tools.invoke_tool internally; we monkeypatch tools.TOOL_HANDLERS to isolate
handler logic (citation-coverage math, gap reporting, status/confidence
selection) from the Postgres-backed tool implementations, which are covered
separately in the integration suite.
"""

from __future__ import annotations

import pytest

from strategyos_mvp.agent_runtime import tools as tools_module
from strategyos_mvp.agent_runtime import workers
from strategyos_mvp.agent_runtime.tools import ToolExecutionContext


@pytest.fixture
def ctx():
    return ToolExecutionContext(tenant_id="t1", task_id="task1", run_id="run1")


def _patch_tools(monkeypatch, findings=None, citations=None):
    def fake_findings_read(ctx, input):
        if findings is None:
            return {"available": False, "reason": "unavailable", "findings": []}
        return {"available": True, "run_id": input.get("run_id"), "findings": findings, "count": len(findings)}

    def fake_citations_search(ctx, input):
        run_citations = citations or []
        finding_id = input.get("finding_id")
        if finding_id:
            run_citations = [c for c in run_citations if c.get("finding_id") == finding_id]
        return {"run_id": input.get("run_id"), "citations": run_citations, "count": len(run_citations)}

    monkeypatch.setitem(tools_module.TOOL_HANDLERS, "findings.read", fake_findings_read)
    monkeypatch.setitem(tools_module.TOOL_HANDLERS, "citations.search", fake_citations_search)


def test_validate_worker_registry_passes_for_shipped_handlers():
    workers.validate_worker_registry()  # must not raise


def test_run_handler_dispatches_by_handler_key(monkeypatch, ctx):
    _patch_tools(monkeypatch, findings=[], citations=[])
    result = workers.run_handler("cash_recovery.v1", ctx, {"run_id": "run1"})
    assert result["status"] == "insufficient_evidence"


def test_run_handler_rejects_unknown_handler_key(ctx):
    with pytest.raises(workers.HandlerInputInvalid):
        workers.run_handler("no_such_handler.v1", ctx, {})


def test_cash_recovery_handler_requires_run_id(ctx):
    ctx_no_run = ToolExecutionContext(tenant_id="t1", task_id="task1", run_id=None)
    with pytest.raises(workers.HandlerInputInvalid):
        workers.cash_recovery_handler(ctx_no_run, {})


def test_cash_recovery_handler_reports_insufficient_evidence_when_findings_unavailable(monkeypatch, ctx):
    _patch_tools(monkeypatch, findings=None)
    result = workers.cash_recovery_handler(ctx, {"run_id": "run1"})
    assert result["status"] == "insufficient_evidence"
    assert result["confidence"] == "low"


def test_cash_recovery_handler_reports_insufficient_evidence_when_no_findings(monkeypatch, ctx):
    _patch_tools(monkeypatch, findings=[], citations=[])
    result = workers.cash_recovery_handler(ctx, {"run_id": "run1"})
    assert result["status"] == "insufficient_evidence"
    assert "no findings recorded" in result["gaps"][0]


def test_cash_recovery_handler_sums_recoverable_value_and_flags_weak_findings(monkeypatch, ctx):
    findings = [
        {"finding_id": "FIN-001", "recoverable_sar": 30000, "status": "locked"},
        {"finding_id": "FIN-002", "recoverable_sar": 20000, "status": "draft"},
    ]
    citations = [{"finding_id": "FIN-001", "citation_id": "c1", "locator": "row-1", "resolved": True}]
    _patch_tools(monkeypatch, findings=findings, citations=citations)

    result = workers.cash_recovery_handler(ctx, {"run_id": "run1"})

    assert result["data"]["total_recoverable_sar"] == 50000.0
    assert result["data"]["locked_recoverable_sar"] == 30000.0
    assert result["data"]["weak_findings"] == ["FIN-002"]
    assert result["confidence"] == "medium"
    assert result["proposed_actions"][0]["action"] == "resolve_evidence_gap"
    assert result["proposed_actions"][0]["finding_ids"] == ["FIN-002"]


def test_cash_recovery_handler_reports_high_confidence_when_fully_cited(monkeypatch, ctx):
    findings = [{"finding_id": "FIN-001", "recoverable_sar": 30000, "status": "locked"}]
    citations = [{"finding_id": "FIN-001", "citation_id": "c1", "locator": "row-1", "resolved": True}]
    _patch_tools(monkeypatch, findings=findings, citations=citations)

    result = workers.cash_recovery_handler(ctx, {"run_id": "run1"})

    assert result["confidence"] == "high"
    assert result["gaps"] == []
    assert result["proposed_actions"] == []


def test_evidence_closure_handler_requires_run_id(ctx):
    ctx_no_run = ToolExecutionContext(tenant_id="t1", task_id="task1", run_id=None)
    with pytest.raises(workers.HandlerInputInvalid):
        workers.evidence_closure_handler(ctx_no_run, {})


def test_evidence_closure_handler_reports_insufficient_evidence_with_no_citations(monkeypatch, ctx):
    _patch_tools(monkeypatch, citations=[])
    result = workers.evidence_closure_handler(ctx, {"run_id": "run1"})
    assert result["status"] == "insufficient_evidence"


def test_evidence_closure_handler_flags_unsupported_requested_findings(monkeypatch, ctx):
    _patch_tools(monkeypatch, citations=[])
    result = workers.evidence_closure_handler(ctx, {"run_id": "run1", "finding_ids": ["FIN-002"]})
    assert result["status"] == "insufficient_evidence"
    assert result["data"]["unsupported_findings"] == ["FIN-002"]


def test_evidence_closure_handler_reports_resolved_and_unresolved_split(monkeypatch, ctx):
    citations = [
        {"finding_id": "FIN-001", "citation_id": "c1", "locator": "row-1", "resolved": True},
        {"finding_id": "FIN-001", "citation_id": "c2", "locator": "row-2", "resolved": False},
    ]
    _patch_tools(monkeypatch, citations=citations)

    result = workers.evidence_closure_handler(ctx, {"run_id": "run1", "finding_ids": ["FIN-001"]})

    assert result["data"]["resolved_count"] == 1
    assert result["data"]["unresolved_count"] == 1
    assert result["status"] == "complete"
    assert result["confidence"] == "medium"
    assert len(result["citations"]) == 1


def test_evidence_closure_handler_high_confidence_when_all_resolved(monkeypatch, ctx):
    citations = [{"finding_id": "FIN-001", "citation_id": "c1", "locator": "row-1", "resolved": True}]
    _patch_tools(monkeypatch, citations=citations)

    result = workers.evidence_closure_handler(ctx, {"run_id": "run1", "finding_ids": ["FIN-001"]})

    assert result["confidence"] == "high"
    assert result["gaps"] == []
