"""Domain contracts for the agents layer.

Immutable dataclasses and enums matching docs/agent-layer/agents-layer-design.md
section 5 (core domain model) and section 6 (event envelope). These types are
the shared vocabulary between registry.py, repository.py, and events.py; they
carry no persistence or execution behavior of their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class RiskClass(str, Enum):
    READ_ONLY = "read_only"
    PREPARE = "prepare"
    WRITE = "write"
    RESTRICTED = "restricted"


class TaskStatus(str, Enum):
    PROPOSED = "proposed"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


# Allowed task-status transitions per the design doc's lifecycle diagram
# (section 7). Enforced by repository.transition_task(); nothing else may
# change task.status.
TASK_STATUS_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PROPOSED: frozenset({TaskStatus.QUEUED, TaskStatus.WAITING_FOR_APPROVAL}),
    TaskStatus.WAITING_FOR_APPROVAL: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED}),
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.TIMED_OUT}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.WAITING_FOR_INPUT,
            TaskStatus.WAITING_FOR_APPROVAL,
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.TIMED_OUT,
        }
    ),
    TaskStatus.WAITING_FOR_INPUT: frozenset({TaskStatus.QUEUED}),
    TaskStatus.FAILED: frozenset({TaskStatus.QUEUED}),
    TaskStatus.SUCCEEDED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.TIMED_OUT: frozenset(),
}

# FAILED is deliberately excluded: the lifecycle diagram (design doc section
# 7) allows failed -> queued under retry policy, so it is not a dead end.
# failure_code/failure_detail_public may still be set on a FAILED task; a
# later retry's transition to QUEUED is expected to clear them via a fresh
# attempt, not by this set's membership.
TASK_TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.SUCCEEDED, TaskStatus.CANCELLED, TaskStatus.TIMED_OUT}
)


class HandoffStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    EXPIRED = "expired"


HANDOFF_STATUS_TRANSITIONS: dict[HandoffStatus, frozenset[HandoffStatus]] = {
    HandoffStatus.PROPOSED: frozenset(
        {HandoffStatus.ACCEPTED, HandoffStatus.REJECTED, HandoffStatus.EXPIRED, HandoffStatus.ESCALATED}
    ),
    HandoffStatus.ACCEPTED: frozenset(
        {HandoffStatus.IN_PROGRESS, HandoffStatus.EXPIRED, HandoffStatus.ESCALATED}
    ),
    HandoffStatus.IN_PROGRESS: frozenset({HandoffStatus.COMPLETED, HandoffStatus.ESCALATED}),
    HandoffStatus.COMPLETED: frozenset(),
    HandoffStatus.REJECTED: frozenset(),
    HandoffStatus.ESCALATED: frozenset(),
    HandoffStatus.EXPIRED: frozenset(),
}

HANDOFF_TERMINAL_STATUSES: frozenset[HandoffStatus] = frozenset(
    {
        HandoffStatus.COMPLETED,
        HandoffStatus.REJECTED,
        HandoffStatus.ESCALATED,
        HandoffStatus.EXPIRED,
    }
)


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


APPROVAL_STATUS_TRANSITIONS: dict[ApprovalStatus, frozenset[ApprovalStatus]] = {
    ApprovalStatus.PENDING: frozenset(
        {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED, ApprovalStatus.CANCELLED}
    ),
    ApprovalStatus.APPROVED: frozenset(),
    ApprovalStatus.REJECTED: frozenset(),
    ApprovalStatus.EXPIRED: frozenset(),
    ApprovalStatus.CANCELLED: frozenset(),
}

RequestedByType = Literal["user", "agent", "system"]
ResultStatus = Literal["complete", "insufficient_evidence", "failed"]
Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class AgentDefinition:
    """A versioned, immutable execution contract (design doc section 5.1).

    Definitions are deployed with code via registry.py and synchronized into
    strategyos_agent_definitions. Editing behavior means adding a new version;
    in-flight tasks retain the version they started with.
    """

    agent_key: str
    version: int
    display_name: str
    purpose: str
    handler_key: str
    input_schema: str
    output_schema: str
    tool_keys: tuple[str, ...]
    allowed_roles: tuple[str, ...]
    max_handoff_depth: int = 3
    default_timeout_seconds: int = 300
    enabled: bool = True


@dataclass(frozen=True)
class ContextSnapshot:
    """Immutable per-task context manifest (design doc section 5.5)."""

    tenant_id: str
    principal_subject: str
    as_of: str
    conversation_id: str | None = None
    run_id: str | None = None
    finding_id: str | None = None
    board_id: str | None = None
    driver_id: str | None = None
    allowed_evidence_ids: tuple[str, ...] = ()
    classification: Literal["public_safe", "restricted"] = "restricted"
    effective_capabilities: tuple[str, ...] = ()
    source_hashes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Citation:
    kind: str
    id: str
    locator: str


@dataclass(frozen=True)
class AgentResult:
    """Shared outer envelope every specialist result must validate against
    (design doc section 5.6)."""

    summary: str
    status: ResultStatus
    data: dict[str, Any] = field(default_factory=dict)
    citations: tuple[Citation, ...] = ()
    confidence: Confidence = "medium"
    gaps: tuple[str, ...] = ()
    proposed_actions: tuple[dict[str, Any], ...] = ()
    artifacts: tuple[dict[str, Any], ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentTask:
    task_id: str
    tenant_id: str
    conversation_id: str | None
    parent_task_id: str | None
    agent_installation_id: str
    agent_definition_version: int
    task_type: str
    objective: str
    input: dict[str, Any]
    context_manifest: dict[str, Any]
    risk_class: RiskClass
    status: TaskStatus
    requested_by_type: RequestedByType
    requested_by_id: str
    idempotency_key: str
    deadline_at: str | None = None
    result: dict[str, Any] | None = None
    failure_code: str | None = None
    failure_detail_public: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass(frozen=True)
class AgentHandoff:
    handoff_id: str
    tenant_id: str
    source_task_id: str
    child_task_id: str
    from_agent_installation_id: str
    to_agent_installation_id: str
    reason: str
    requested_capability: str
    input: dict[str, Any]
    expected_output_schema: str
    status: HandoffStatus
    deadline_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    tenant_id: str
    task_id: str
    effect_hash: str
    risk_class: RiskClass
    public_explanation: str
    status: ApprovalStatus
    linked_approval_id: str | None = None
    decided_by_subject: str | None = None
    decided_by_role: str | None = None
    decision_comment: str | None = None
    created_at: str | None = None
    decided_at: str | None = None
    expires_at: str | None = None


@dataclass(frozen=True)
class DomainEvent:
    """Event envelope (design doc section 6)."""

    event_id: str
    tenant_id: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    event_type: str
    occurred_at: str
    actor: dict[str, str]
    correlation_id: str
    causation_id: str | None
    trace_id: str | None
    payload: dict[str, Any]
    public_projection: dict[str, Any]


FAILURE_CODES = frozenset(
    {
        "AGENT_INVALID_INPUT",
        "AGENT_NOT_PERMITTED",
        "AGENT_APPROVAL_REQUIRED",
        "AGENT_EVIDENCE_INSUFFICIENT",
        "AGENT_TOOL_UNAVAILABLE",
        "AGENT_MODEL_UNAVAILABLE",
        "AGENT_TIMEOUT",
        "AGENT_BUDGET_EXCEEDED",
        "AGENT_CONFLICT",
        "AGENT_INTERNAL_FAILURE",
    }
)


def is_task_transition_allowed(current: TaskStatus, target: TaskStatus) -> bool:
    return target in TASK_STATUS_TRANSITIONS.get(current, frozenset())


def is_handoff_transition_allowed(current: HandoffStatus, target: HandoffStatus) -> bool:
    return target in HANDOFF_STATUS_TRANSITIONS.get(current, frozenset())


def is_approval_transition_allowed(current: ApprovalStatus, target: ApprovalStatus) -> bool:
    return target in APPROVAL_STATUS_TRANSITIONS.get(current, frozenset())
