from types import SimpleNamespace

from strategyos_mvp.assistants.graph_retrieval import route_graph_question
from strategyos_mvp import graph_queries


def test_graph_router_skips_when_graph_not_synced(monkeypatch):
    monkeypatch.setattr(
        graph_queries,
        "graph_capability_status",
        lambda run_id: {"status": "skipped", "run_id": run_id, "reason": "NEO4J_URI missing"},
    )

    result = route_graph_question("run-1", "show evidence for F-004")

    assert result["matched"] is False
    assert result["answered_by"] == ""


def test_graph_router_routes_each_supported_intent(monkeypatch):
    monkeypatch.setattr(graph_queries, "graph_capability_status", lambda run_id: {"status": "synced", "run_id": run_id})
    monkeypatch.setattr(graph_queries, "finding_evidence_chain", lambda run_id, finding_id, limit=10: {"matched": True, "available": True, "intent": "finding_evidence_chain", "answer": finding_id, "basis": "graph", "citations": [{"source_path": "08_Invoices/invoice.pdf", "locator": finding_id}]})
    monkeypatch.setattr(graph_queries, "vendor_finding_exposure", lambda run_id, vendor_id, limit=10: {"matched": True, "available": True, "intent": "vendor_finding_exposure", "answer": vendor_id, "basis": "graph", "citations": [{"source_path": "08_Invoices/invoice.pdf", "locator": vendor_id}]})
    monkeypatch.setattr(graph_queries, "shared_evidence_findings", lambda run_id, limit=10: {"matched": True, "available": True, "intent": "shared_evidence_findings", "answer": "shared", "basis": "graph", "citations": [{"source_path": "08_Invoices/invoice.pdf", "locator": "shared"}]})
    monkeypatch.setattr(graph_queries, "vendor_contract_gaps", lambda run_id, limit=10: {"matched": True, "available": True, "intent": "vendor_contract_gap", "answer": "gaps", "basis": "graph", "citations": []})
    monkeypatch.setattr(graph_queries, "vendor_collusion_clusters", lambda run_id, limit=10: {"matched": True, "available": True, "intent": "vendor_collusion_cluster", "answer": "clusters", "basis": "graph", "citations": [{"source_path": "03_Master_Data/Vendor_Master.xlsx", "locator": "Vendor:V-1142"}]})

    assert route_graph_question("run-1", "show evidence for F-004")["answer"] == "F-004"
    assert route_graph_question("run-1", "show exposure to vendor V-1142")["answer"] == "V-1142"
    assert route_graph_question("run-1", "show shared evidence findings")["answer"] == "shared"
    assert route_graph_question("run-1", "show vendor contract gaps")["answer"] == "gaps"
    collusion = route_graph_question("run-1", "show vendor collusion via shared bank account")
    assert collusion["answer"] == "clusters"
    assert collusion["answered_by"] == "graph"


def test_graph_router_normalizes_fnd_ids_and_vendor_names(monkeypatch):
    monkeypatch.setattr(graph_queries, "graph_capability_status", lambda run_id: {"status": "synced", "run_id": run_id})
    monkeypatch.setattr(graph_queries, "finding_evidence_chain", lambda run_id, finding_id, limit=10: {"matched": True, "available": True, "intent": "finding_evidence_chain", "answer": finding_id, "basis": "graph", "citations": []})
    monkeypatch.setattr(graph_queries, "vendor_finding_exposure", lambda run_id, vendor_id, limit=10: {"matched": True, "available": True, "intent": "vendor_finding_exposure", "answer": vendor_id, "basis": "graph", "citations": []})

    assert route_graph_question("run-1", "show the evidence chain for FND-001")["answer"] == "F-001"
    assert route_graph_question("run-1", "What is the exposure to Tamween Distribution for the CEO?")["answer"] == "Tamween Distribution"


def test_graph_router_normalizes_finding_ids_and_vendor_names(monkeypatch):
    monkeypatch.setattr(graph_queries, "graph_capability_status", lambda run_id: {"status": "synced", "run_id": run_id})

    captured = {"finding_id": None, "vendor_ref": None}

    def fake_finding(run_id, finding_id, limit=10):
        captured["finding_id"] = finding_id
        return {"matched": True, "available": True, "intent": "finding_evidence_chain", "answer": finding_id, "basis": "graph", "citations": []}

    def fake_vendor(run_id, vendor_id, limit=10):
        captured["vendor_ref"] = vendor_id
        return {"matched": True, "available": True, "intent": "vendor_finding_exposure", "answer": vendor_id, "basis": "graph", "citations": []}

    monkeypatch.setattr(graph_queries, "finding_evidence_chain", fake_finding)
    monkeypatch.setattr(graph_queries, "vendor_finding_exposure", fake_vendor)
    monkeypatch.setattr(graph_queries, "shared_evidence_findings", lambda run_id, limit=10: {"matched": False, "available": True, "intent": "shared_evidence_findings"})
    monkeypatch.setattr(graph_queries, "vendor_contract_gaps", lambda run_id, limit=10: {"matched": False, "available": True, "intent": "vendor_contract_gap"})
    monkeypatch.setattr(graph_queries, "vendor_collusion_clusters", lambda run_id, limit=10: {"matched": False, "available": True, "intent": "vendor_collusion_cluster"})

    finding_result = route_graph_question("run-1", "Show the evidence chain for FND-001")
    vendor_result = route_graph_question("run-1", "What is the exposure to Tamween Distribution?")

    assert finding_result["answer"] == "F-001"
    assert captured["finding_id"] == "F-001"
    assert vendor_result["answer"] == "Tamween Distribution"
    assert captured["vendor_ref"] == "Tamween Distribution"
