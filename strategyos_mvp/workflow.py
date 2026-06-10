from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Literal, TypedDict

from .agents import (
    DEFAULT_PIPELINE,
    AgentStage,
    CaseFileWriter,
    EvidenceQAAgent,
    FinanceAnalystAgent,
    FinanceAuditorAgent,
    KnowledgeGraphAgent,
    register_stage,
)
from .ingestion import DataBundle, load_dataset
from .models import AuditEvent, Finding
from .runtime_governance import AWAITING_REVIEW_STAGE, COMPLETED_STATUS


class StrategyOSState(TypedDict, total=False):
    dataset_root: Path
    source_pack_id: str | None
    run_dir: Path
    run_id: str | None
    runtime_record: dict[str, Any] | None
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
    last_checkpoint: dict[str, Any]


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
        pipeline: Sequence[AgentStage] | None = None,
        stage_handlers: Mapping[
            str, Callable[[StrategyOSState], StrategyOSState]
        ]
        | None = None,
    ) -> None:
        self.analyst = FinanceAnalystAgent()
        self.auditor = FinanceAuditorAgent()
        self.evidence_qa = EvidenceQAAgent()
        self.kg = KnowledgeGraphAgent()
        self.writer = CaseFileWriter()
        self.pipeline = tuple(pipeline or DEFAULT_PIPELINE)
        for stage in self.pipeline:
            register_stage(stage)
        self.stage_handlers: dict[
            str, Callable[[StrategyOSState], StrategyOSState]
        ] = self._default_stage_handlers()
        if stage_handlers:
            self.stage_handlers.update(stage_handlers)
        self._validate_pipeline()
        self.checkpoint_handler = checkpoint_handler
        self.stop_before_writer = stop_before_writer
        self.runtime_metadata = {
            "requested_backend": requested_backend,
            "actual_backend": "local",
            "checkpointing": "governance_handler",
            "fallback_used": requested_backend != "local",
            "pipeline": [stage.name for stage in self.pipeline],
        }

    def _checkpoint(self, stage: str, state: StrategyOSState) -> StrategyOSState:
        if self.checkpoint_handler is None:
            return {**state, "current_stage": stage}
        return self.checkpoint_handler(stage, state)

    def _default_stage_handlers(
        self,
    ) -> dict[str, Callable[[StrategyOSState], StrategyOSState]]:
        return {
            "ingest": self._ingest_node,
            "analyst": self._analyst_node,
            "auditor": self._auditor_node,
            "evidence_qa": self._evidence_qa_node,
            "knowledge_graph": self._knowledge_graph_node,
            "awaiting_review": self._awaiting_review_node,
            "writer": self._writer_node,
        }

    def _validate_pipeline(self) -> None:
        missing = [
            stage.name for stage in self.pipeline if stage.name not in self.stage_handlers
        ]
        if missing:
            raise ValueError(
                "Pipeline stages are missing workflow handlers: "
                + ", ".join(sorted(missing))
            )
        if not any(stage.is_terminal for stage in self.pipeline):
            raise ValueError("Pipeline must include one terminal stage.")

    def _should_enter_review_gate(self, state: StrategyOSState) -> bool:
        return bool(self.stop_before_writer and state.get("requires_human_review"))

    def _run_stage(
        self, stage: AgentStage, state: StrategyOSState
    ) -> StrategyOSState:
        return self.stage_handlers[stage.name](state)

    def invoke(self, state: StrategyOSState) -> StrategyOSState:
        for stage in self.pipeline:
            if stage.is_review_gate and not self._should_enter_review_gate(state):
                continue
            state = self._run_stage(stage, state)
            if stage.is_review_gate:
                return state
        return state

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
        pipeline: Sequence[AgentStage] | None = None,
        stage_handlers: Mapping[
            str, Callable[[StrategyOSState], StrategyOSState]
        ]
        | None = None,
    ) -> None:
        super().__init__(
            checkpoint_handler=checkpoint_handler,
            stop_before_writer=stop_before_writer,
            requested_backend=requested_backend,
            pipeline=pipeline,
            stage_handlers=stage_handlers,
        )
        self.postgres_url = postgres_url
        self.allow_local_fallback = allow_local_fallback
        self.runtime_metadata = {
            "requested_backend": requested_backend,
            "actual_backend": "langgraph",
            "checkpointing": "postgres",
            "fallback_used": False,
            "pipeline": [stage.name for stage in self.pipeline],
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
                "pipeline": [stage.name for stage in self.pipeline],
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
            "pipeline": [stage.name for stage in self.pipeline],
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
            from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
            from langgraph.graph import END, START, StateGraph
            from psycopg import Connection
            from psycopg.rows import dict_row
        except Exception as exc:  # pragma: no cover - depends on optional runtime deps
            raise RuntimeError(
                "LangGraph Postgres runtime dependencies are unavailable."
            ) from exc

        builder = StateGraph(StrategyOSState)
        for stage in self.pipeline:
            builder.add_node(stage.name, self._node_for_stage(stage.name))
        self._wire_langgraph_pipeline(builder, START, END)

        @contextmanager
        def checkpointer_cm():
            with Connection.connect(
                self.postgres_url,
                autocommit=True,
                prepare_threshold=0,
                row_factory=dict_row,
            ) as conn:
                # StrategyOS graph state still carries rich in-process objects
                # such as DataBundle/Finding. Keep this limited to trusted
                # Postgres runtimes until the graph state is reduced to durable
                # handles plus serializable payloads.
                yield PostgresSaver(
                    conn,
                    serde=JsonPlusSerializer(pickle_fallback=True),
                )

        return builder, checkpointer_cm()

    def _node_for_stage(
        self, stage_name: str
    ) -> Callable[[StrategyOSState], StrategyOSState]:
        def node(state: StrategyOSState) -> StrategyOSState:
            return self.stage_handlers[stage_name](state)

        return node

    def _wire_langgraph_pipeline(self, builder: Any, start: Any, end: Any) -> None:
        if not self.pipeline:
            raise ValueError("Pipeline must include at least one stage.")
        builder.add_edge(start, self.pipeline[0].name)
        for index, stage in enumerate(self.pipeline):
            if stage.is_terminal or index == len(self.pipeline) - 1:
                builder.add_edge(stage.name, end)
                continue
            next_stage = self.pipeline[index + 1]
            if next_stage.is_review_gate:
                stage_after_gate = self._stage_after(index + 1)
                if stage_after_gate is None:
                    raise ValueError(
                        f"Review gate '{next_stage.name}' must be followed by a stage."
                    )
                builder.add_conditional_edges(
                    stage.name,
                    self._route_to_review_gate_or_next(
                        next_stage.name, stage_after_gate.name
                    ),
                    {
                        next_stage.name: next_stage.name,
                        stage_after_gate.name: stage_after_gate.name,
                    },
                )
                continue
            if stage.is_review_gate:
                builder.add_edge(stage.name, end)
                continue
            builder.add_edge(stage.name, next_stage.name)

    def _stage_after(self, index: int) -> AgentStage | None:
        if index + 1 >= len(self.pipeline):
            return None
        return self.pipeline[index + 1]

    def _route_to_review_gate_or_next(
        self, review_gate_name: str, next_stage_name: str
    ) -> Callable[[StrategyOSState], str]:
        def route(state: StrategyOSState) -> str:
            if self._should_enter_review_gate(state):
                return review_gate_name
            return next_stage_name

        return route

    def _route_after_knowledge_graph(self, state: StrategyOSState) -> str:
        if self._should_enter_review_gate(state):
            return "awaiting_review"
        return "writer"

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
    pipeline: Sequence[AgentStage] | None = None,
    stage_handlers: Mapping[str, Callable[[StrategyOSState], StrategyOSState]]
    | None = None,
):
    """Build the StrategyOS workflow runtime with optional LangGraph execution."""
    if runtime_backend == "local":
        return LocalStrategyOSWorkflow(
            checkpoint_handler=checkpoint_handler,
            stop_before_writer=stop_before_writer,
            requested_backend="local",
            pipeline=pipeline,
            stage_handlers=stage_handlers,
        )
    return LangGraphStrategyOSWorkflow(
        checkpoint_handler=checkpoint_handler,
        stop_before_writer=stop_before_writer,
        postgres_url=postgres_url,
        allow_local_fallback=allow_local_fallback or runtime_backend == "auto",
        requested_backend=runtime_backend,
        pipeline=pipeline,
        stage_handlers=stage_handlers,
    )
