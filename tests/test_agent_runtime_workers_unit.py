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


def _patch_board_pack_tool(monkeypatch, board_pack_result):
    def fake_board_pack_prepare(ctx, input):
        return board_pack_result

    monkeypatch.setitem(tools_module.TOOL_HANDLERS, "board_pack.prepare", fake_board_pack_prepare)


def _patch_runtime_health_tool(monkeypatch, health_result):
    def fake_runtime_health_read(ctx, input):
        return health_result

    monkeypatch.setitem(tools_module.TOOL_HANDLERS, "runtime.health.read", fake_runtime_health_read)


def test_board_pack_handler_requires_run_id(ctx):
    ctx_no_run = ToolExecutionContext(tenant_id="t1", task_id="task1", run_id=None)
    with pytest.raises(workers.HandlerInputInvalid):
        workers.board_pack_handler(ctx_no_run, {})


def test_board_pack_handler_reports_insufficient_evidence_when_run_missing(monkeypatch, ctx):
    _patch_board_pack_tool(monkeypatch, {"available": False, "run_id": "run1", "reason": "run not found"})
    result = workers.board_pack_handler(ctx, {"run_id": "run1"})
    assert result["status"] == "insufficient_evidence"


def test_board_pack_handler_reports_awaiting_review_gap(monkeypatch, ctx):
    _patch_board_pack_tool(
        monkeypatch,
        {
            "available": True,
            "run_id": "run1",
            "publication": {
                "board_pack": {"status": "ready", "report_count": 3, "evidence_count": 5},
                "publish_state": "awaiting_review",
            },
            "reports": {},
        },
    )
    result = workers.board_pack_handler(ctx, {"run_id": "run1"})
    assert result["status"] == "complete"
    assert result["gaps"], "expected a gap for an unpublished/unapproved board pack"
    assert result["proposed_actions"][0]["action"] == "review.request"


def test_board_pack_handler_no_gap_when_approved_for_release(monkeypatch, ctx):
    _patch_board_pack_tool(
        monkeypatch,
        {
            "available": True,
            "run_id": "run1",
            "publication": {
                "board_pack": {"status": "approved_for_release", "report_count": 3, "evidence_count": 5},
                "publish_state": "approved_for_release",
            },
            "reports": {},
        },
    )
    result = workers.board_pack_handler(ctx, {"run_id": "run1"})
    assert result["gaps"] == []
    assert result["confidence"] == "high"


def test_runtime_guardrail_handler_reports_ok_status(monkeypatch, ctx):
    _patch_runtime_health_tool(
        monkeypatch,
        {
            "status": "ok",
            "checks": {"postgres": {"status": "ok"}, "neo4j": {"status": "ok"}},
            "hatchet": {"status": "ok"},
        },
    )
    result = workers.runtime_guardrail_handler(ctx, {})
    assert result["data"]["overall_status"] == "ok"
    assert result["confidence"] == "high"
    assert result["gaps"] == []


def test_runtime_guardrail_handler_flags_failing_subsystems(monkeypatch, ctx):
    _patch_runtime_health_tool(
        monkeypatch,
        {
            "status": "failed",
            "checks": {"postgres": {"status": "failed"}, "neo4j": {"status": "ok"}},
            "hatchet": {"status": "ok"},
        },
    )
    result = workers.runtime_guardrail_handler(ctx, {})
    assert result["data"]["overall_status"] == "failed"
    assert "postgres" in result["data"]["failing_subsystems"]
    assert result["confidence"] == "low"
    assert result["gaps"]


def test_runtime_guardrail_handler_flags_hatchet_unhealthy(monkeypatch, ctx):
    _patch_runtime_health_tool(
        monkeypatch,
        {
            "status": "degraded",
            "checks": {"postgres": {"status": "ok"}},
            "hatchet": {"status": "failed", "reason": "worker not registered"},
        },
    )
    result = workers.runtime_guardrail_handler(ctx, {})
    assert any("Hatchet" in gap for gap in result["gaps"])
