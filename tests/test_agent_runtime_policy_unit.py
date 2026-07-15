"""Pure-unit tests for agent_runtime.policy -- no Postgres required.

Covers design doc section 15's budget/loop-prevention rules and section 9's
risk-class resolution.
"""

from __future__ import annotations

from strategyos_mvp.agent_runtime.models import RiskClass
from strategyos_mvp.agent_runtime.policy import (
    MAX_CHILD_TASKS_PER_ROOT,
    MAX_HANDOFF_DEPTH,
    check_handoff_budget,
    is_role_permitted,
    resolve_risk_class,
)
from strategyos_mvp.agent_runtime.registry import CASH_RECOVERY, BOARD_PACK


def test_resolve_risk_class_is_read_only_by_default():
    decision = resolve_risk_class(CASH_RECOVERY, "quantify_recoverable_value", None)
    assert decision.risk_class == RiskClass.READ_ONLY
    assert not decision.requires_approval


def test_resolve_risk_class_forces_write_and_approval_for_consequential_task_types():
    decision = resolve_risk_class(BOARD_PACK, "prepare_board_pack", "read_only")
    assert decision.risk_class == RiskClass.WRITE
    assert decision.requires_approval


def test_resolve_risk_class_honors_restricted_hint():
    decision = resolve_risk_class(CASH_RECOVERY, "quantify_recoverable_value", "restricted")
    assert decision.risk_class == RiskClass.RESTRICTED
    assert decision.requires_approval


def test_resolve_risk_class_ignores_an_unknown_hint_value():
    decision = resolve_risk_class(CASH_RECOVERY, "quantify_recoverable_value", "not-a-real-risk-class")
    assert decision.risk_class == RiskClass.READ_ONLY


def test_is_role_permitted_checks_allowed_roles():
    assert is_role_permitted(CASH_RECOVERY, "finance")
    assert not is_role_permitted(CASH_RECOVERY, "guest")


def test_is_role_permitted_always_allows_system_and_tenant_admin():
    assert is_role_permitted(CASH_RECOVERY, "system")
    assert is_role_permitted(CASH_RECOVERY, "tenant_admin")


def test_check_handoff_budget_rejects_self_handoff():
    decision = check_handoff_budget(
        depth=0, child_task_count=0, from_agent_key="a", to_agent_key="a",
        requested_capability="cap", prior_handoff_signatures=frozenset(), scope_hash="h",
    )
    assert not decision.allowed
    assert "itself" in decision.reason


def test_check_handoff_budget_rejects_at_max_depth():
    decision = check_handoff_budget(
        depth=MAX_HANDOFF_DEPTH, child_task_count=0, from_agent_key="a", to_agent_key="b",
        requested_capability="cap", prior_handoff_signatures=frozenset(), scope_hash="h",
    )
    assert not decision.allowed
    assert "depth" in decision.reason


def test_check_handoff_budget_allows_just_under_max_depth():
    decision = check_handoff_budget(
        depth=MAX_HANDOFF_DEPTH - 1, child_task_count=0, from_agent_key="a", to_agent_key="b",
        requested_capability="cap", prior_handoff_signatures=frozenset(), scope_hash="h",
    )
    assert decision.allowed


def test_check_handoff_budget_rejects_at_max_fan_out():
    decision = check_handoff_budget(
        depth=0, child_task_count=MAX_CHILD_TASKS_PER_ROOT, from_agent_key="a", to_agent_key="b",
        requested_capability="cap", prior_handoff_signatures=frozenset(), scope_hash="h",
    )
    assert not decision.allowed
    assert "child task limit" in decision.reason


def test_check_handoff_budget_rejects_duplicate_signature():
    signatures = frozenset({("b", "cap", "h1")})
    decision = check_handoff_budget(
        depth=0, child_task_count=0, from_agent_key="a", to_agent_key="b",
        requested_capability="cap", prior_handoff_signatures=signatures, scope_hash="h1",
    )
    assert not decision.allowed
    assert "duplicate" in decision.reason


def test_check_handoff_budget_allows_same_agent_different_scope():
    signatures = frozenset({("b", "cap", "h1")})
    decision = check_handoff_budget(
        depth=0, child_task_count=0, from_agent_key="a", to_agent_key="b",
        requested_capability="cap", prior_handoff_signatures=signatures, scope_hash="h2",
    )
    assert decision.allowed


def test_check_handoff_budget_allows_within_all_limits():
    decision = check_handoff_budget(
        depth=1, child_task_count=2, from_agent_key="a", to_agent_key="b",
        requested_capability="cap", prior_handoff_signatures=frozenset(), scope_hash="h",
    )
    assert decision.allowed
