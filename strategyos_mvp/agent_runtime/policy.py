"""Authorization and approval decisions (design doc sections 3.8-3.9, 13).

The policy engine, not Hermes, decides the final risk class and whether
approval is required (design doc section 9). This module resolves an agent
definition's declared risk posture for a task_type into a concrete
risk_class, decides queued-vs-approval routing for the design doc's two
paths (8.2 step 4: "Read-only work automatically transitions to queued;
higher-risk work creates an approval request"), and (PR 7) computes the
effective-authority intersection required by design principle 8: "Authority
never increases through delegation. Effective permission is the
intersection of the user, agent, tenant, tool, and task policy."
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import RiskClass
from .registry import TOOL_RISK_CLASSES, AgentDefinition

# Every role that may appear on an authenticated principal, ordered from
# least to most privileged for role-scoped tool restriction below. "system"/
# "tenant_admin" are excluded here -- they bypass the per-role tool
# restriction entirely (see resolve_effective_authority), matching
# is_role_permitted's existing system/tenant_admin bypass.
_ROLE_MAX_TOOL_RISK: dict[str, str] = {
    # A role that can only read board-safe/public material should never be
    # able to mint a token authorizing a "prepare"/"write"/"restricted"
    # tool, even if the agent it's delegating to is itself allowed to call
    # one -- this is the "user" leg of the intersection.
    "bu": "read_only",
    "finance": "read_only",
    "executive": "read_only",
    "reviewer": "write",
    "operator": "write",
}
_RISK_CLASS_RANK: dict[str, int] = {"read_only": 0, "prepare": 1, "write": 2, "restricted": 3}

# Per design doc section 2's specialist table: only Cash Recovery's
# "create remediation proposal" and Board Pack's publication step are
# consequential; everything else in the initial catalogue is read-only.
CONSEQUENTIAL_TASK_TYPES: frozenset[str] = frozenset(
    {
        "create_remediation_proposal",
        "prepare_board_pack",
        "explain_publication_posture",
    }
)


@dataclass(frozen=True)
class PolicyDecision:
    risk_class: RiskClass
    requires_approval: bool
    reason: str


def resolve_risk_class(agent_definition: AgentDefinition, task_type: str, risk_class_hint: str | None) -> PolicyDecision:
    """Resolve a task's actual risk class. A hint from Hermes/the caller is
    advisory only -- the policy engine has final say, per design doc section
    9: "The policy engine, not Hermes, decides the final risk class."""
    if task_type in CONSEQUENTIAL_TASK_TYPES:
        return PolicyDecision(
            risk_class=RiskClass.WRITE,
            requires_approval=True,
            reason=f"task_type {task_type!r} is consequential and requires reviewer/operator approval",
        )

    # Default: everything else in the initial catalogue is read-only.
    hinted = risk_class_hint if risk_class_hint in {rc.value for rc in RiskClass} else None
    if hinted == RiskClass.RESTRICTED.value:
        return PolicyDecision(
            risk_class=RiskClass.RESTRICTED,
            requires_approval=True,
            reason="restricted risk class always requires approval",
        )
    return PolicyDecision(
        risk_class=RiskClass.READ_ONLY,
        requires_approval=False,
        reason="read-only investigation task",
    )


def is_role_permitted(agent_definition: AgentDefinition, role: str) -> bool:
    return role in agent_definition.allowed_roles or role in {"system", "tenant_admin"}


# Design doc section 15 "Budgets and loop prevention" -- per root task:
MAX_HANDOFF_DEPTH = 3
MAX_CHILD_TASKS_PER_ROOT = 8


@dataclass(frozen=True)
class HandoffPolicyDecision:
    allowed: bool
    reason: str


def check_handoff_budget(
    *,
    depth: int,
    child_task_count: int,
    from_agent_key: str,
    to_agent_key: str,
    requested_capability: str,
    prior_handoff_signatures: frozenset[tuple[str, str, str]],
    scope_hash: str,
) -> HandoffPolicyDecision:
    """Enforces depth/fan-out/loop-prevention before a handoff is created.
    `prior_handoff_signatures` is the set of (to_agent_key, capability,
    scope_hash) tuples already used for this root task -- a repeat means the
    same agent is being asked to do the same work on the same scope again,
    which is the design doc's loop-prevention rule ("no handoff to the same
    agent for the same capability and scope hash")."""
    if from_agent_key == to_agent_key:
        return HandoffPolicyDecision(False, "an agent cannot hand off to itself")
    if depth >= MAX_HANDOFF_DEPTH:
        return HandoffPolicyDecision(False, f"handoff depth limit ({MAX_HANDOFF_DEPTH}) reached")
    if child_task_count >= MAX_CHILD_TASKS_PER_ROOT:
        return HandoffPolicyDecision(False, f"child task limit ({MAX_CHILD_TASKS_PER_ROOT}) reached for this root task")
    signature = (to_agent_key, requested_capability, scope_hash)
    if signature in prior_handoff_signatures:
        return HandoffPolicyDecision(False, "duplicate handoff to the same agent for the same capability and scope")
    return HandoffPolicyDecision(True, "within budget")


# ---------------------------------------------------------------------------
# Effective authority (design principle 8, PR 7)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EffectiveAuthority:
    """The bounded set of tool keys and max risk class a task may actually
    exercise -- the intersection of every leg design principle 8 names.
    This, not the raw AgentDefinition.tool_keys, is what a capability token
    must be minted from: a token scoped to the agent's full tool set would
    let a low-privileged user's delegation quietly inherit the agent's
    ceiling instead of the user's."""

    allowed_tool_keys: tuple[str, ...]
    max_risk_class: str
    reason: str


def resolve_effective_authority(
    *,
    agent_definition: AgentDefinition,
    requesting_role: str,
    installation_active: bool,
    task_risk_class: str,
) -> EffectiveAuthority:
    """Intersects four independent constraints, each of which can only
    narrow (never widen) the result:

    1. tenant: an inactive/disabled installation grants nothing at all;
    2. agent: AgentDefinition.tool_keys is the agent's own declared ceiling;
    3. user: requesting_role's _ROLE_MAX_TOOL_RISK caps which risk classes
       that role may ever authorize, regardless of what the agent permits;
    4. task: task_risk_class (already policy-resolved by resolve_risk_class,
       itself derived from task_type, never from a caller-supplied hint)
       further caps the ceiling to what this specific task actually needs.

    "system"/"tenant_admin" bypass the role-risk cap (matching
    is_role_permitted's existing bypass for those two roles), since they are
    not principal roles reachable through the ordinary Hermes delegation
    path -- they represent the platform itself acting, not a user."""
    if not installation_active:
        return EffectiveAuthority(allowed_tool_keys=(), max_risk_class="read_only", reason="agent installation is not active for this tenant")

    if requesting_role in ("system", "tenant_admin"):
        role_ceiling_rank = _RISK_CLASS_RANK.get(task_risk_class, 0)
    else:
        role_max = _ROLE_MAX_TOOL_RISK.get(requesting_role, "read_only")
        role_ceiling_rank = min(_RISK_CLASS_RANK.get(role_max, 0), _RISK_CLASS_RANK.get(task_risk_class, 0))

    allowed_tool_keys = tuple(
        tool_key
        for tool_key in agent_definition.tool_keys
        if _RISK_CLASS_RANK.get(TOOL_RISK_CLASSES.get(tool_key, "restricted"), 3) <= role_ceiling_rank
    )
    max_risk_class = next(
        (rc for rc, rank in sorted(_RISK_CLASS_RANK.items(), key=lambda item: -item[1]) if rank <= role_ceiling_rank),
        "read_only",
    )
    reason = (
        f"intersection of agent tool_keys ({len(agent_definition.tool_keys)}), "
        f"role {requesting_role!r} ceiling ({_ROLE_MAX_TOOL_RISK.get(requesting_role, 'read_only') if requesting_role not in ('system', 'tenant_admin') else 'unbounded'}), "
        f"and task risk_class ({task_risk_class!r})"
    )
    return EffectiveAuthority(allowed_tool_keys=allowed_tool_keys, max_risk_class=max_risk_class, reason=reason)
