from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from .agents import CaseFileWriter, FinanceAnalystAgent, FinanceAuditorAgent, KnowledgeGraphAgent
from .ingestion import DataBundle, load_dataset
from .models import AuditEvent, Finding


class StrategyOSState(TypedDict, total=False):
    dataset_root: Path
    run_dir: Path
    bundle: DataBundle
    findings: list[Finding]
    audit_events: list[AuditEvent]
    knowledge_graph: Path
    artifacts: dict[str, Path]


class LocalStrategyOSWorkflow:
    """Deterministic fallback that mirrors the LangGraph node sequence."""

    def __init__(self) -> None:
        self.analyst = FinanceAnalystAgent()
        self.auditor = FinanceAuditorAgent()
        self.kg = KnowledgeGraphAgent()
        self.writer = CaseFileWriter()

    def invoke(self, state: StrategyOSState) -> StrategyOSState:
        bundle = load_dataset(state["dataset_root"])
        manifest_path = state["run_dir"] / "source_hash_manifest.json"
        bundle.evidence.save_manifest(manifest_path)
        findings = self.analyst.draft_findings(bundle)
        audit_events = self.auditor.challenge_findings(findings)
        knowledge_graph = self.kg.build(bundle, findings, state["run_dir"])
        artifacts = self.writer.write_all(bundle, findings, audit_events, state["run_dir"])
        artifacts["manifest"] = manifest_path
        artifacts["knowledge_graph"] = knowledge_graph
        return {
            **state,
            "bundle": bundle,
            "findings": findings,
            "audit_events": audit_events,
            "knowledge_graph": knowledge_graph,
            "artifacts": artifacts,
        }


def build_workflow():
    """Return a real LangGraph workflow when installed; otherwise return local fallback.

    The node order is: ingest -> analyst -> auditor -> writer. Production should attach
    a durable checkpointer and human approval interrupt before writer.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception:
        return LocalStrategyOSWorkflow()

    analyst = FinanceAnalystAgent()
    auditor = FinanceAuditorAgent()
    kg = KnowledgeGraphAgent()
    writer = CaseFileWriter()

    def ingest_node(state: StrategyOSState) -> StrategyOSState:
        bundle = load_dataset(state["dataset_root"])
        manifest_path = state["run_dir"] / "source_hash_manifest.json"
        bundle.evidence.save_manifest(manifest_path)
        return {**state, "bundle": bundle, "artifacts": {"manifest": manifest_path}}

    def analyst_node(state: StrategyOSState) -> StrategyOSState:
        return {**state, "findings": analyst.draft_findings(state["bundle"])}

    def auditor_node(state: StrategyOSState) -> StrategyOSState:
        findings = state["findings"]
        return {**state, "findings": findings, "audit_events": auditor.challenge_findings(findings)}

    def writer_node(state: StrategyOSState) -> StrategyOSState:
        artifacts = dict(state.get("artifacts", {}))
        artifacts.update(writer.write_all(state["bundle"], state["findings"], state["audit_events"], state["run_dir"]))
        return {**state, "artifacts": artifacts}

    def knowledge_graph_node(state: StrategyOSState) -> StrategyOSState:
        artifacts = dict(state.get("artifacts", {}))
        knowledge_graph = kg.build(state["bundle"], state["findings"], state["run_dir"])
        artifacts["knowledge_graph"] = knowledge_graph
        return {**state, "knowledge_graph": knowledge_graph, "artifacts": artifacts}

    graph = StateGraph(StrategyOSState)
    graph.add_node("ingest", ingest_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("auditor", auditor_node)
    graph.add_node("knowledge_graph", knowledge_graph_node)
    graph.add_node("writer", writer_node)
    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "analyst")
    graph.add_edge("analyst", "auditor")
    graph.add_edge("auditor", "knowledge_graph")
    graph.add_edge("knowledge_graph", "writer")
    graph.add_edge("writer", END)
    return graph.compile()
