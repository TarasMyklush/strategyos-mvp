from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Literal, TypedDict

from .agents import (
    CaseFileWriter,
    EvidenceQAAgent,
    FinanceAnalystAgent,
    FinanceAuditorAgent,
    KnowledgeGraphAgent,
)
from .ingestion import DataBundle, load_dataset
from .models import AuditEvent, Finding
from .runtime_governance import AWAITING_REVIEW_STAGE, COMPLETED_STATUS


class StrategyOSState(TypedDict, total=False):
    dataset_root: Path
    run_dir: Path
    run_id: str | None
    workflow_status: str
    current_stage: str
    requires_human_review: bool
    approval_status: str
    checkpoints: list[dict[str, Any]]
    bundle: DataBundle
    findings: list[Finding]
    audit_events: list[AuditEvent]
    audit_verification: dict[str, Any]
    evidence_qa: dict[str, Path]
    knowledge_graph: Path
    artifacts: dict[str, Path]


RuntimeBackend = Literal["auto", "langgraph", "local"]


class LocalStrategyOSWorkflow:
    """Deterministic fallback that mirrors the LangGraph node sequence."""

    def __init__(
        self,
        *,
        checkpoint_handler: Callable[[str, StrategyOSState], StrategyOSState]
        | None = None,
        stop_before_writer: bool = False,
        requested_backend: RuntimeBackend = "local",
    ) -> None:
        self.analyst = FinanceAnalystAgent()
        self.auditor = FinanceAuditorAgent()
        self.evidence_qa = EvidenceQAAgent()
        self.kg = KnowledgeGraphAgent()
        self.writer = CaseFileWriter()
        self.checkpoint_handler = checkpoint_handler
        self.stop_before_writer = stop_before_writer
        self.runtime_metadata = {
            "requested_backend": requested_backend,
            "actual_backend": "local",
            "checkpointing": "governance_handler",
            "fallback_used": requested_backend != "local",
        }

    def _checkpoint(self, stage: str, state: StrategyOSState) -> StrategyOSState:
        if self.checkpoint_handler is None:
            return {**state, "current_stage": stage}
        return self.checkpoint_handler(stage, state)

    def invoke(self, state: StrategyOSState) -> StrategyOSState:
        bundle = load_dataset(state["dataset_root"])
        manifest_path = state["run_dir"] / "source_hash_manifest.json"
        bundle.evidence.save_manifest(manifest_path)
        state = self._checkpoint(
            "ingest",
            {
                **state,
                "bundle": bundle,
                "artifacts": {"manifest": manifest_path},
            },
        )
        findings = self.analyst.draft_findings(bundle)
        state = self._checkpoint(
            "analyst",
            {
                **state,
                "findings": findings,
            },
        )
        review_rounds = getattr(self.auditor, "run_review_rounds", None)
        if callable(review_rounds):
            audit_events = review_rounds(findings, analyst=self.analyst)
        else:
            audit_events = self.auditor.challenge_findings(findings)
        state = self._checkpoint(
            "auditor",
            {
                **state,
                "audit_events": audit_events,
                "audit_verification": getattr(self.auditor, "last_verification", {}),
            },
        )
        evidence_qa = self.evidence_qa.write_reports(bundle, findings, state["run_dir"])
        artifacts = dict(state.get("artifacts", {}))
        artifacts.update(evidence_qa)
        state = self._checkpoint(
            "evidence_qa",
            {
                **state,
                "evidence_qa": evidence_qa,
                "artifacts": artifacts,
            },
        )
        knowledge_graph = self.kg.build(bundle, findings, state["run_dir"])
        artifacts = dict(state.get("artifacts", {}))
        artifacts["knowledge_graph"] = knowledge_graph
        state = self._checkpoint(
            "knowledge_graph",
            {
                **state,
                "knowledge_graph": knowledge_graph,
                "artifacts": artifacts,
            },
        )
        if self.stop_before_writer and state.get("requires_human_review"):
            return self._checkpoint(
                AWAITING_REVIEW_STAGE,
                {
                    **state,
                    "workflow_status": AWAITING_REVIEW_STAGE,
                    "approval_status": "pending",
                },
            )
        artifacts = dict(state.get("artifacts", {}))
        artifacts.update(
            self.writer.write_all(bundle, findings, audit_events, state["run_dir"])
        )
        return self._checkpoint(
            "writer",
            {
                **state,
                "artifacts": artifacts,
                "workflow_status": COMPLETED_STATUS,
            },
        )


class LangGraphStrategyOSWorkflow(LocalStrategyOSWorkflow):
    """Primary LangGraph runtime path with Postgres-backed checkpointing."""

    def __init__(
        self,
        *,
        checkpoint_handler: Callable[[str, StrategyOSState], StrategyOSState]
        | None = None,
        stop_before_writer: bool = False,
        postgres_url: str | None = None,
        allow_local_fallback: bool = False,
        requested_backend: RuntimeBackend = "langgraph",
    ) -> None:
        super().__init__(
            checkpoint_handler=checkpoint_handler,
            stop_before_writer=stop_before_writer,
            requested_backend=requested_backend,
        )
        self.postgres_url = postgres_url
        self.allow_local_fallback = allow_local_fallback
        self.runtime_metadata = {
            "requested_backend": requested_backend,
            "actual_backend": "langgraph",
            "checkpointing": "postgres",
            "fallback_used": False,
        }

    def invoke(self, state: StrategyOSState) -> StrategyOSState:
        try:
            graph_builder, checkpointer_cm = self._prepare_langgraph_runtime()
        except Exception as exc:
            if not self.allow_local_fallback:
                raise RuntimeError(self._runtime_error_message(exc)) from exc
            self.runtime_metadata = {
                "requested_backend": self.runtime_metadata.get(
                    "requested_backend", "auto"
                ),
                "actual_backend": "local",
                "checkpointing": "governance_handler",
                "fallback_used": True,
                "fallback_reason": str(exc),
            }
            return super().invoke(state)

        thread_id = self._thread_id(state)
        self.runtime_metadata = {
            "requested_backend": self.runtime_metadata.get(
                "requested_backend", "langgraph"
            ),
            "actual_backend": "langgraph",
            "checkpointing": "postgres",
            "fallback_used": False,
            "thread_id": thread_id,
        }
        with checkpointer_cm as checkpointer:
            setup = getattr(checkpointer, "setup", None)
            if callable(setup):
                setup()
            compiled = graph_builder.compile(checkpointer=checkpointer)
            return compiled.invoke(
                state,
                config={"configurable": {"thread_id": thread_id}},
            )

    def _prepare_langgraph_runtime(self):
        if not self.postgres_url:
            raise RuntimeError(
                "DATABASE_URL/STRATEGYOS_DATABASE_URL is required for the LangGraph runtime path."
            )

        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from langgraph.graph import END, START, StateGraph
        except Exception as exc:  # pragma: no cover - depends on optional runtime deps
            raise RuntimeError(
                "LangGraph Postgres runtime dependencies are unavailable."
            ) from exc

        builder = StateGraph(StrategyOSState)
        builder.add_node("ingest", self._ingest_node)
        builder.add_node("analyst", self._analyst_node)
        builder.add_node("auditor", self._auditor_node)
        builder.add_node("evidence_qa", self._evidence_qa_node)
        builder.add_node("knowledge_graph", self._knowledge_graph_node)
        builder.add_node("awaiting_review", self._awaiting_review_node)
        builder.add_node("writer", self._writer_node)
        builder.add_edge(START, "ingest")
        builder.add_edge("ingest", "analyst")
        builder.add_edge("analyst", "auditor")
        builder.add_edge("auditor", "evidence_qa")
        builder.add_edge("evidence_qa", "knowledge_graph")
        builder.add_conditional_edges(
            "knowledge_graph",
            self._route_after_knowledge_graph,
            {"awaiting_review": "awaiting_review", "writer": "writer"},
        )
        builder.add_edge("awaiting_review", END)
        builder.add_edge("writer", END)

        checkpointer_cm = getattr(PostgresSaver, "from_conn_string", None)
        if checkpointer_cm is None:
            raise RuntimeError("PostgresSaver.from_conn_string is unavailable.")

        return builder, checkpointer_cm(self.postgres_url)

    def _route_after_knowledge_graph(self, state: StrategyOSState) -> str:
        if self.stop_before_writer and state.get("requires_human_review"):
            return "awaiting_review"
        return "writer"

    def _ingest_node(self, state: StrategyOSState) -> StrategyOSState:
        bundle = load_dataset(state["dataset_root"])
        manifest_path = state["run_dir"] / "source_hash_manifest.json"
        bundle.evidence.save_manifest(manifest_path)
        return self._checkpoint(
            "ingest",
            {
                **state,
                "bundle": bundle,
                "artifacts": {"manifest": manifest_path},
            },
        )

    def _analyst_node(self, state: StrategyOSState) -> StrategyOSState:
        findings = self.analyst.draft_findings(state["bundle"])
        return self._checkpoint(
            "analyst",
            {
                **state,
                "findings": findings,
            },
        )

    def _auditor_node(self, state: StrategyOSState) -> StrategyOSState:
        review_rounds = getattr(self.auditor, "run_review_rounds", None)
        if callable(review_rounds):
            audit_events = review_rounds(state["findings"], analyst=self.analyst)
        else:
            audit_events = self.auditor.challenge_findings(state["findings"])
        return self._checkpoint(
            "auditor",
            {
                **state,
                "audit_events": audit_events,
                "audit_verification": getattr(self.auditor, "last_verification", {}),
            },
        )

    def _evidence_qa_node(self, state: StrategyOSState) -> StrategyOSState:
        evidence_qa = self.evidence_qa.write_reports(
            state["bundle"], state["findings"], state["run_dir"]
        )
        artifacts = dict(state.get("artifacts", {}))
        artifacts.update(evidence_qa)
        return self._checkpoint(
            "evidence_qa",
            {
                **state,
                "evidence_qa": evidence_qa,
                "artifacts": artifacts,
            },
        )

    def _knowledge_graph_node(self, state: StrategyOSState) -> StrategyOSState:
        knowledge_graph = self.kg.build(
            state["bundle"], state["findings"], state["run_dir"]
        )
        artifacts = dict(state.get("artifacts", {}))
        artifacts["knowledge_graph"] = knowledge_graph
        return self._checkpoint(
            "knowledge_graph",
            {
                **state,
                "knowledge_graph": knowledge_graph,
                "artifacts": artifacts,
            },
        )

    def _awaiting_review_node(self, state: StrategyOSState) -> StrategyOSState:
        return self._checkpoint(
            AWAITING_REVIEW_STAGE,
            {
                **state,
                "workflow_status": AWAITING_REVIEW_STAGE,
                "approval_status": "pending",
            },
        )

    def _writer_node(self, state: StrategyOSState) -> StrategyOSState:
        artifacts = dict(state.get("artifacts", {}))
        artifacts.update(
            self.writer.write_all(
                state["bundle"],
                state["findings"],
                state.get("audit_events", []),
                state["run_dir"],
            )
        )
        return self._checkpoint(
            "writer",
            {
                **state,
                "artifacts": artifacts,
                "workflow_status": COMPLETED_STATUS,
            },
        )

    def _thread_id(self, state: StrategyOSState) -> str:
        run_id = state.get("run_id")
        if isinstance(run_id, str) and run_id.strip():
            return run_id
        run_dir = state.get("run_dir")
        if isinstance(run_dir, Path):
            return run_dir.name
        return "strategyos-local-thread"

    def _runtime_error_message(self, exc: Exception) -> str:
        return (
            "LangGraph runtime path could not start with Postgres checkpointing. "
            f"{exc} Use the explicit local-only fallback if you need deterministic local execution."
        )


def build_workflow(
    *,
    checkpoint_handler: Callable[[str, StrategyOSState], StrategyOSState] | None = None,
    stop_before_writer: bool = False,
    runtime_backend: RuntimeBackend = "auto",
    postgres_url: str | None = None,
    allow_local_fallback: bool = False,
):
    """Build the StrategyOS workflow runtime with optional LangGraph execution."""
    if runtime_backend == "local":
        return LocalStrategyOSWorkflow(
            checkpoint_handler=checkpoint_handler,
            stop_before_writer=stop_before_writer,
            requested_backend="local",
        )
    return LangGraphStrategyOSWorkflow(
        checkpoint_handler=checkpoint_handler,
        stop_before_writer=stop_before_writer,
        postgres_url=postgres_url,
        allow_local_fallback=allow_local_fallback or runtime_backend == "auto",
        requested_backend=runtime_backend,
    )
