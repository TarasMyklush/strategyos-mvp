"""Pure-unit tests for agent_runtime.policy.resolve_effective_authority --
no Postgres required. Covers design principle 8: "Authority never
increases through delegation. Effective permission is the intersection of
the user, agent, tenant, tool, and task policy."
"""

from __future__ import annotations

from strategyos_mvp.agent_runtime.policy import resolve_effective_authority
from strategyos_mvp.agent_runtime.registry import BOARD_PACK, CASH_RECOVERY, RUNTIME_GUARDRAIL


def test_inactive_installation_grants_no_tools_regardless_of_role_or_agent():
    auth = resolve_effective_authority(
        agent_definition=BOARD_PACK, requesting_role="operator",
        installation_active=False, task_risk_class="restricted",
    )
    assert auth.allowed_tool_keys == ()


def test_a_read_only_capped_role_never_gets_a_restricted_tool():
    for role in ("bu", "finance", "executive"):
        auth = resolve_effective_authority(
            agent_definition=BOARD_PACK, requesting_role=role,
            installation_active=True, task_risk_class="restricted",
        )
        assert "publication.release" not in auth.allowed_tool_keys, role


def test_a_write_capped_role_never_gets_a_restricted_tool():
    for role in ("reviewer", "operator"):
        auth = resolve_effective_authority(
            agent_definition=BOARD_PACK, requesting_role=role,
            installation_active=True, task_risk_class="restricted",
        )
        assert "publication.release" not in auth.allowed_tool_keys, role
        assert auth.max_risk_class == "write"


def test_system_and_tenant_admin_bypass_the_role_cap():
    for role in ("system", "tenant_admin"):
        auth = resolve_effective_authority(
            agent_definition=BOARD_PACK, requesting_role=role,
            installation_active=True, task_risk_class="restricted",
        )
        assert "publication.release" in auth.allowed_tool_keys, role
        assert auth.max_risk_class == "restricted"


def test_task_risk_class_narrows_the_ceiling_even_for_a_privileged_role():
    """An operator delegating a purely read_only task must not receive a
    write-scoped token just because operator's own ceiling is write --
    the task leg of the intersection still applies."""
    auth = resolve_effective_authority(
        agent_definition=BOARD_PACK, requesting_role="operator",
        installation_active=True, task_risk_class="read_only",
    )
    assert auth.max_risk_class == "read_only"


def test_allowed_tool_keys_is_always_a_subset_of_the_agent_definitions_tool_keys():
    for agent_definition in (CASH_RECOVERY, BOARD_PACK, RUNTIME_GUARDRAIL):
        for role in ("bu", "finance", "executive", "reviewer", "operator", "system", "tenant_admin"):
            for risk_class in ("read_only", "prepare", "write", "restricted"):
                auth = resolve_effective_authority(
                    agent_definition=agent_definition, requesting_role=role,
                    installation_active=True, task_risk_class=risk_class,
                )
                assert set(auth.allowed_tool_keys) <= set(agent_definition.tool_keys), (
                    agent_definition.agent_key, role, risk_class
                )


def test_max_risk_class_never_exceeds_the_role_cap():
    """Regardless of task_risk_class, a bu/finance/executive-initiated
    task's resolved max_risk_class must never rank above read_only."""
    for role in ("bu", "finance", "executive"):
        for task_risk_class in ("read_only", "prepare", "write", "restricted"):
            auth = resolve_effective_authority(
                agent_definition=BOARD_PACK, requesting_role=role,
                installation_active=True, task_risk_class=task_risk_class,
            )
            assert auth.max_risk_class == "read_only", (role, task_risk_class)


def test_an_unknown_role_defaults_to_read_only_not_unbounded():
    """A role string that isn't in _ROLE_MAX_TOOL_RISK (e.g. a typo, or a
    role added to auth.py but not yet to policy.py) must fail closed to
    read_only, never fail open to unrestricted access."""
    auth = resolve_effective_authority(
        agent_definition=BOARD_PACK, requesting_role="some_future_role_not_yet_mapped",
        installation_active=True, task_risk_class="restricted",
    )
    assert auth.max_risk_class == "read_only"
    assert "publication.release" not in auth.allowed_tool_keys


def test_read_only_tools_remain_available_at_every_privilege_level():
    """The intersection narrows which prepare/write/restricted tools are
    reachable, but must never strip a read_only tool that the agent
    actually has -- read_only is always <= any role's ceiling. Uses
    RUNTIME_GUARDRAIL because its single tool (runtime.health.read) is
    unconditionally read_only; CASH_RECOVERY (v2) legitimately mixes
    read_only findings/citations tools with the write-classed
    remediation.propose, so its full tool_keys set is NOT expected to
    survive every role/risk_class combination -- that's covered instead by
    test_max_risk_class_never_exceeds_the_role_cap and
    test_allowed_tool_keys_is_always_a_subset_of_the_agent_definitions_tool_keys."""
    for role in ("bu", "finance", "executive", "reviewer", "operator"):
        auth = resolve_effective_authority(
            agent_definition=RUNTIME_GUARDRAIL, requesting_role=role,
            installation_active=True, task_risk_class="read_only",
        )
        assert set(auth.allowed_tool_keys) == set(RUNTIME_GUARDRAIL.tool_keys), role
