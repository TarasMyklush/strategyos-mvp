"""Authorization and approval decisions (design doc sections 3.8-3.9, 13).

The policy engine, not Hermes, decides the final risk class and whether
approval is required (design doc section 9). This module is intentionally
small in PR 3: it resolves an agent definition's declared risk posture for a
task_type into a concrete risk_class, and decides queued-vs-approval routing
for the design doc's two paths (8.2 step 4: "Read-only work automatically
transitions to queued; higher-risk work creates an approval request").

Full capability-token/effect-hash binding is PR 6 territory.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import RiskClass
from .registry import AgentDefinition

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
