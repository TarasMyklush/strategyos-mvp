"""Hermes planning/delegation logic (design doc section 9).

Produces a validated decision object before answering or delegating.
Capability classification is deterministic for the first release (design
doc: "For the first release, agent selection should be deterministic") --
an LLM MAY be layered on top of `classify_intent` later to handle
free-text phrasing, but it may not invent agents, tools, or capabilities:
any capability it names must still resolve through registry.CAPABILITY_ROUTES
or the classification falls back to `clarify`.

`process_conversation_message` is the single entry point PR 3's API layer
calls: it persists the user message, classifies intent, and either answers
inline (via the existing AssistantOrchestrator) or creates a proposed task
-- never both, and never silently promotes a proposed task to "done".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from ..assistants.orchestrator import get_orchestrator
from . import repository
from .models import TaskStatus
from .policy import resolve_risk_class
from .registry import CAPABILITY_ROUTES, resolve_agent_for_capability

Intent = Literal["answer", "delegate", "clarify", "refuse"]

# Deterministic keyword -> capability routing. Ordered so more specific
# phrasings are checked before generic ones (e.g. "why doesn't ... reconcile"
# must win over a bare "recoverable" match). This is intentionally simple
# regex matching, not an LLM call, per the design doc's "deterministic for
# the first release" instruction.
_CAPABILITY_KEYWORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("resolve_evidence_gap", re.compile(r"\b(citation|evidence|source)s?\b.*\b(gap|missing|unresolved|weak)\b", re.I)),
    ("challenge_finding", re.compile(r"\b(challenge|dispute|question)\b.*\bfinding", re.I)),
    ("quantify_recoverable_value", re.compile(r"\b(reconcile|recoverable|recovery|leakage)\b", re.I)),
    ("monitor_recovery_case", re.compile(r"\bmonitor\b.*\b(recovery|case)\b", re.I)),
    ("prepare_board_pack", re.compile(r"\bboard\s*pack\b|\bprepare.*board\b", re.I)),
    ("explain_publication_posture", re.compile(r"\bpublish|publication\b", re.I)),
    ("inspect_runtime_health", re.compile(r"\b(runtime|system|platform)\b.*\bhealth\b|\bis.*(down|broken|degraded)\b", re.I)),
    ("diagnose_connector_or_queue", re.compile(r"\bconnector\b|\bqueue\b.*\b(stuck|failing|backed up)\b", re.I)),
)

_INVESTIGATION_TRIGGER = re.compile(r"\b(why|investigate|find out|figure out|check|look into)\b", re.I)


@dataclass(frozen=True)
class HermesDecision:
    intent: Intent
    executive_summary: str
    capability: str | None
    task_type: str | None
    objective: str | None
    scope: dict[str, Any]
    risk_class_hint: str | None
    success_criteria: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    user_confirmation_required: bool


def classify_intent(question: str, *, scope: dict[str, Any] | None = None) -> HermesDecision:
    """Pure classification: no side effects, no persistence. Matches a
    question against the capability keyword table; if a capability matches
    AND the question looks like an investigation request (not just a casual
    mention of the word), returns `delegate`. Otherwise `answer`. Never
    returns a capability outside registry.CAPABILITY_ROUTES."""
    scope = scope or {}
    text = question or ""

    matched_capability: str | None = None
    for capability, pattern in _CAPABILITY_KEYWORDS:
        if pattern.search(text):
            matched_capability = capability
            break

    if matched_capability is None:
        return HermesDecision(
            intent="answer",
            executive_summary="Answering directly from governed context.",
            capability=None,
            task_type=None,
            objective=None,
            scope=scope,
            risk_class_hint=None,
            success_criteria=(),
            missing_inputs=(),
            user_confirmation_required=False,
        )

    # Guardrail against invented capabilities: matched_capability must be a
    # real registry entry (it always will be, since the table above is
    # hand-built from CAPABILITY_ROUTES, but this keeps the invariant
    # explicit and machine-checked rather than only "true by construction").
    if matched_capability not in CAPABILITY_ROUTES:
        return HermesDecision(
            intent="clarify",
            executive_summary="I recognized a request but could not map it to a known capability.",
            capability=None,
            task_type=None,
            objective=None,
            scope=scope,
            risk_class_hint=None,
            success_criteria=(),
            missing_inputs=("capability",),
            user_confirmation_required=False,
        )

    is_investigation = bool(_INVESTIGATION_TRIGGER.search(text)) or matched_capability in {
        "prepare_board_pack",
        "inspect_runtime_health",
        "diagnose_connector_or_queue",
    }
    if not is_investigation:
        return HermesDecision(
            intent="answer",
            executive_summary="Answering directly from governed context.",
            capability=None,
            task_type=None,
            objective=None,
            scope=scope,
            risk_class_hint=None,
            success_criteria=(),
            missing_inputs=(),
            user_confirmation_required=False,
        )

    missing_inputs = () if scope.get("run_id") else ("run_id",)
    return HermesDecision(
        intent="delegate" if not missing_inputs else "clarify",
        executive_summary=f"Delegating to resolve: {question.strip()[:200]}",
        capability=matched_capability,
        task_type=matched_capability,
        objective=question.strip()[:500],
        scope=scope,
        risk_class_hint="read_only",
        success_criteria=("All claims have resolvable citations",),
        missing_inputs=missing_inputs,
        user_confirmation_required=False,
    )


def process_conversation_message(
    *,
    tenant_id: str,
    conversation_id: str,
    principal_subject: str,
    principal_role: str,
    question: str,
    scope: dict[str, Any] | None = None,
    idempotency_key: str,
    persona: str | None = None,
) -> dict[str, Any]:
    """The PR 3 entry point: persists the user message, classifies intent,
    and either answers inline or creates a proposed task. Returns
    {user_message, hermes_message, task (optional), decision}."""
    user_message = repository.append_message(
        tenant_id, conversation_id, author_type="user", author_id=principal_subject, body=question
    )

    decision = classify_intent(question, scope=scope)

    if decision.intent == "answer":
        answer = get_orchestrator().process(question=question, persona=persona)
        hermes_message = repository.append_message(
            tenant_id, conversation_id, author_type="agent", author_id="hermes",
            body=answer.answer,
            metadata={"mode": answer.mode, "basis": answer.basis, "citations": answer.citations, "matched": answer.matched},
        )
        return {
            "user_message": user_message,
            "hermes_message": hermes_message,
            "task": None,
            "decision": _decision_dict(decision),
        }

    if decision.intent == "clarify":
        missing = ", ".join(decision.missing_inputs) or "more detail"
        clarification = f"I need {missing} to investigate this. Could you provide it?"
        hermes_message = repository.append_message(
            tenant_id, conversation_id, author_type="agent", author_id="hermes", body=clarification,
            metadata={"intent": "clarify", "missing_inputs": list(decision.missing_inputs)},
        )
        return {
            "user_message": user_message,
            "hermes_message": hermes_message,
            "task": None,
            "decision": _decision_dict(decision),
        }

    if decision.intent == "refuse":
        hermes_message = repository.append_message(
            tenant_id, conversation_id, author_type="agent", author_id="hermes",
            body=decision.executive_summary, metadata={"intent": "refuse"},
        )
        return {
            "user_message": user_message,
            "hermes_message": hermes_message,
            "task": None,
            "decision": _decision_dict(decision),
        }

    # delegate
    assert decision.capability is not None
    agent_definition = resolve_agent_for_capability(decision.capability)
    if agent_definition is None:
        # Invented/unroutable capability slipped through -- fail safe to
        # clarify rather than delegating to nothing.
        hermes_message = repository.append_message(
            tenant_id, conversation_id, author_type="agent", author_id="hermes",
            body="I couldn't find a specialist for that request.", metadata={"intent": "clarify"},
        )
        return {
            "user_message": user_message,
            "hermes_message": hermes_message,
            "task": None,
            "decision": _decision_dict(decision),
        }

    if not _role_permitted(agent_definition, principal_role):
        hermes_message = repository.append_message(
            tenant_id, conversation_id, author_type="agent", author_id="hermes",
            body="Your role does not have access to this specialist.", metadata={"intent": "refuse"},
        )
        return {
            "user_message": user_message,
            "hermes_message": hermes_message,
            "task": None,
            "decision": _decision_dict(decision),
        }

    installation = repository.ensure_agent_installation(tenant_id, agent_definition.agent_key)
    policy_decision = resolve_risk_class(agent_definition, decision.task_type or "", decision.risk_class_hint)

    task_input = dict(decision.scope)

    # create_task() always starts a task at PROPOSED (design doc section 7's
    # lifecycle diagram: [*] --> proposed is the only entry state); the
    # transition to queued/waiting_for_approval below is a separate,
    # policy-driven step, not something create_task() should shortcut.
    task = repository.create_task(
        tenant_id,
        agent_installation_id=installation["installation_id"],
        agent_definition_version=agent_definition.version,
        task_type=decision.task_type,
        objective=decision.objective or question,
        risk_class=policy_decision.risk_class.value,
        requested_by_type="user",
        requested_by_id=principal_subject,
        idempotency_key=idempotency_key,
        conversation_id=conversation_id,
        input=task_input,
        initial_status=TaskStatus.PROPOSED,
    )
    if not policy_decision.requires_approval and task["status"] == TaskStatus.PROPOSED.value:
        task = repository.transition_task(
            tenant_id, task["task_id"], target_status=TaskStatus.QUEUED,
            actor={"type": "system", "id": "policy"},
        )
    elif policy_decision.requires_approval and task["status"] == TaskStatus.PROPOSED.value:
        task = repository.transition_task(
            tenant_id, task["task_id"], target_status=TaskStatus.WAITING_FOR_APPROVAL,
            actor={"type": "system", "id": "policy"},
        )

    hermes_message = repository.append_message(
        tenant_id, conversation_id, author_type="agent", author_id="hermes",
        body=f"{agent_definition.display_name} is now working on: {decision.objective}",
        metadata={"intent": "delegate", "task_id": task["task_id"], "agent_key": agent_definition.agent_key},
        task_id=task["task_id"],
    )
    return {
        "user_message": user_message,
        "hermes_message": hermes_message,
        "task": task,
        "decision": _decision_dict(decision),
    }


def _role_permitted(agent_definition, role: str) -> bool:
    from .policy import is_role_permitted

    return is_role_permitted(agent_definition, role)


def _decision_dict(decision: HermesDecision) -> dict[str, Any]:
    return {
        "intent": decision.intent,
        "executive_summary": decision.executive_summary,
        "capability": decision.capability,
        "task_type": decision.task_type,
        "objective": decision.objective,
        "scope": decision.scope,
        "risk_class_hint": decision.risk_class_hint,
        "success_criteria": list(decision.success_criteria),
        "missing_inputs": list(decision.missing_inputs),
        "user_confirmation_required": decision.user_confirmation_required,
    }
