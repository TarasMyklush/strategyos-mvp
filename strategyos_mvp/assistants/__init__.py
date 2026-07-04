"""StrategyOS Assistant Orchestrator — persona-aware Q&A routing.

The orchestrator replaces the frontend-canned CEO fallback behavior with a
backend KG-grounded deterministic + LLM routed architecture that serves ALL
StrategyOS role scenarios with traceability and auditability.
"""

from .orchestrator import (
    AssistantOrchestrator,
    PersonaAnswer,
    assess_question_for_persona,
    compose_persona_answer,
    get_orchestrator,
    list_supported_personas,
)

__all__ = [
    "AssistantOrchestrator",
    "PersonaAnswer",
    "assess_question_for_persona",
    "compose_persona_answer",
    "get_orchestrator",
    "list_supported_personas",
]
