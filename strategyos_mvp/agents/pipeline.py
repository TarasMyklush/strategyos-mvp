from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class AgentStage:
    name: str
    label: str
    is_review_gate: bool = False
    is_terminal: bool = False


_STAGE_REGISTRY: dict[str, AgentStage] = {}


def register_stage(stage: AgentStage) -> AgentStage:
    existing = _STAGE_REGISTRY.get(stage.name)
    if existing is not None and existing != stage:
        raise ValueError(f"Agent stage '{stage.name}' is already registered.")
    _STAGE_REGISTRY[stage.name] = stage
    return stage


def stage_registry() -> tuple[AgentStage, ...]:
    return tuple(_STAGE_REGISTRY.values())


def stage_by_name(name: str) -> AgentStage:
    return _STAGE_REGISTRY[str(name)]


def pipeline_from_names(names: Iterable[str]) -> tuple[AgentStage, ...]:
    return tuple(stage_by_name(name) for name in names)


def is_review_gate_stage(name: str) -> bool:
    stage = _STAGE_REGISTRY.get(str(name).lower())
    return bool(stage and stage.is_review_gate)


def is_terminal_stage(name: str) -> bool:
    stage = _STAGE_REGISTRY.get(str(name).lower())
    return bool(stage and stage.is_terminal)


INGEST_STAGE = register_stage(AgentStage("ingest", "Ingest"))
ANALYST_STAGE = register_stage(AgentStage("analyst", "Analyst"))
AUDITOR_STAGE = register_stage(AgentStage("auditor", "Auditor"))
EVIDENCE_QA_STAGE = register_stage(AgentStage("evidence_qa", "Evidence QA"))
KNOWLEDGE_GRAPH_STAGE = register_stage(
    AgentStage("knowledge_graph", "Knowledge Graph")
)
AWAITING_REVIEW_STAGE = register_stage(
    AgentStage("awaiting_review", "Awaiting Human Review", is_review_gate=True)
)
WRITER_STAGE = register_stage(AgentStage("writer", "Writer", is_terminal=True))

DEFAULT_PIPELINE_STAGE_NAMES: tuple[str, ...] = (
    INGEST_STAGE.name,
    ANALYST_STAGE.name,
    AUDITOR_STAGE.name,
    EVIDENCE_QA_STAGE.name,
    KNOWLEDGE_GRAPH_STAGE.name,
    AWAITING_REVIEW_STAGE.name,
    WRITER_STAGE.name,
)

DEFAULT_PIPELINE: tuple[AgentStage, ...] = pipeline_from_names(
    DEFAULT_PIPELINE_STAGE_NAMES
)
