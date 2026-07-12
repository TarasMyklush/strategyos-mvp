"""Pure-unit tests for agent_runtime.models and registry -- no Postgres
required, run on every CI invocation.

Covers every allowed and forbidden task/handoff/approval transition (design
doc section 18 "Unit" test list) plus registry loop/self-reference and
capability-routing invariants.
"""

from __future__ import annotations

import itertools

from strategyos_mvp.agent_runtime import registry
from strategyos_mvp.agent_runtime.models import (
    APPROVAL_STATUS_TRANSITIONS,
    HANDOFF_STATUS_TRANSITIONS,
    HANDOFF_TERMINAL_STATUSES,
    TASK_STATUS_TRANSITIONS,
    TASK_TERMINAL_STATUSES,
    ApprovalStatus,
    HandoffStatus,
    TaskStatus,
    is_approval_transition_allowed,
    is_handoff_transition_allowed,
    is_task_transition_allowed,
)


def test_task_terminal_statuses_have_no_outgoing_transitions():
    for status in TASK_TERMINAL_STATUSES:
        assert TASK_STATUS_TRANSITIONS[status] == frozenset()


def test_task_every_non_terminal_status_can_reach_a_terminal_status():
    for status in TaskStatus:
        if status in TASK_TERMINAL_STATUSES:
            continue
        assert TASK_STATUS_TRANSITIONS[status], f"{status} is a dead end"


def test_task_proposed_can_only_go_to_queued_or_waiting_for_approval():
    assert TASK_STATUS_TRANSITIONS[TaskStatus.PROPOSED] == frozenset(
        {TaskStatus.QUEUED, TaskStatus.WAITING_FOR_APPROVAL}
    )


def test_task_queued_cannot_jump_straight_to_a_terminal_status_except_cancel_or_timeout():
    # queued -> succeeded/failed must go through running first
    assert TaskStatus.SUCCEEDED not in TASK_STATUS_TRANSITIONS[TaskStatus.QUEUED]
    assert TaskStatus.FAILED not in TASK_STATUS_TRANSITIONS[TaskStatus.QUEUED]
    assert TaskStatus.CANCELLED in TASK_STATUS_TRANSITIONS[TaskStatus.QUEUED]
    assert TaskStatus.TIMED_OUT in TASK_STATUS_TRANSITIONS[TaskStatus.QUEUED]


def test_task_failed_can_retry_to_queued():
    assert TaskStatus.QUEUED in TASK_STATUS_TRANSITIONS[TaskStatus.FAILED]


def test_task_all_other_transitions_are_forbidden():
    allowed_pairs = {
        (current, target)
        for current, targets in TASK_STATUS_TRANSITIONS.items()
        for target in targets
    }
    for current, target in itertools.product(TaskStatus, TaskStatus):
        expected = (current, target) in allowed_pairs
        assert is_task_transition_allowed(current, target) == expected, (current, target)


def test_handoff_terminal_statuses_have_no_outgoing_transitions():
    for status in HANDOFF_TERMINAL_STATUSES:
        assert HANDOFF_STATUS_TRANSITIONS[status] == frozenset()


def test_handoff_accepted_cannot_skip_in_progress_to_reach_completed():
    assert HandoffStatus.COMPLETED not in HANDOFF_STATUS_TRANSITIONS[HandoffStatus.ACCEPTED]
    assert HandoffStatus.IN_PROGRESS in HANDOFF_STATUS_TRANSITIONS[HandoffStatus.ACCEPTED]


def test_handoff_proposed_can_be_rejected_or_expired_without_acceptance():
    proposed_targets = HANDOFF_STATUS_TRANSITIONS[HandoffStatus.PROPOSED]
    assert HandoffStatus.REJECTED in proposed_targets
    assert HandoffStatus.EXPIRED in proposed_targets


def test_handoff_all_other_transitions_are_forbidden():
    allowed_pairs = {
        (current, target)
        for current, targets in HANDOFF_STATUS_TRANSITIONS.items()
        for target in targets
    }
    for current, target in itertools.product(HandoffStatus, HandoffStatus):
        expected = (current, target) in allowed_pairs
        assert is_handoff_transition_allowed(current, target) == expected, (current, target)


def test_approval_pending_can_reach_every_terminal_outcome():
    pending_targets = APPROVAL_STATUS_TRANSITIONS[ApprovalStatus.PENDING]
    assert pending_targets == frozenset(
        {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED, ApprovalStatus.CANCELLED}
    )


def test_approval_terminal_statuses_are_immutable():
    for status in ApprovalStatus:
        if status is ApprovalStatus.PENDING:
            continue
        assert APPROVAL_STATUS_TRANSITIONS[status] == frozenset()


def test_approval_all_other_transitions_are_forbidden():
    allowed_pairs = {
        (current, target)
        for current, targets in APPROVAL_STATUS_TRANSITIONS.items()
        for target in targets
    }
    for current, target in itertools.product(ApprovalStatus, ApprovalStatus):
        expected = (current, target) in allowed_pairs
        assert is_approval_transition_allowed(current, target) == expected, (current, target)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_validate_definitions_passes_for_shipped_catalogue():
    registry.validate_definitions()  # must not raise


def test_registry_has_exactly_the_four_specification_agents():
    assert {d.agent_key for d in registry.AGENT_DEFINITIONS} == {
        "cash-recovery",
        "evidence-closure",
        "board-pack",
        "runtime-guardrail",
    }


def test_registry_every_capability_routes_to_a_known_agent():
    for capability, agent_key in registry.CAPABILITY_ROUTES.items():
        assert agent_key in registry.AGENT_DEFINITIONS_BY_KEY, capability


def test_registry_resolve_agent_for_capability_matches_the_design_doc_table():
    expected = {
        "quantify_recoverable_value": "cash-recovery",
        "monitor_recovery_case": "cash-recovery",
        "resolve_evidence_gap": "evidence-closure",
        "challenge_finding": "evidence-closure",
        "prepare_board_pack": "board-pack",
        "explain_publication_posture": "board-pack",
        "inspect_runtime_health": "runtime-guardrail",
        "diagnose_connector_or_queue": "runtime-guardrail",
    }
    for capability, agent_key in expected.items():
        resolved = registry.resolve_agent_for_capability(capability)
        assert resolved is not None
        assert resolved.agent_key == agent_key


def test_registry_resolve_agent_for_capability_rejects_unknown_capability():
    assert registry.resolve_agent_for_capability("delete_all_the_things") is None


def test_registry_known_capabilities_matches_capability_routes_keys():
    assert registry.known_capabilities() == frozenset(registry.CAPABILITY_ROUTES.keys())


def test_registry_definitions_only_reference_catalogued_tool_keys():
    for definition in registry.AGENT_DEFINITIONS:
        for tool_key in definition.tool_keys:
            assert tool_key in registry.TOOL_RISK_CLASSES, (definition.agent_key, tool_key)
