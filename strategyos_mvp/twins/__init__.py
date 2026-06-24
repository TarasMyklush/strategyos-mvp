"""Digital Twin system — autonomous agent layer for StrategyOS."""

from strategyos_mvp.twins.persona import (
    ANALYST_TWIN,
    CEO_TWIN,
    CFO_TWIN,
    GROUP_MANAGER_TWIN,
    REVIEWER_TWIN,
    STRATEGY_TWIN,
    TWIN_CATALOG,
    TwinPersona,
)
from strategyos_mvp.twins.protocol import (
    InterTwinMessage,
    TwinResponse,
    validate_message,
    should_escalate,
)
from strategyos_mvp.twins.memory import (
    TwinState,
    create_twin_state,
    save_state,
    load_state,
    add_to_history,
    add_investigation,
    resolve_investigation,
)
from strategyos_mvp.twins.tools import (
    query_kpi,
    query_evidence,
    send_message,
    escalate_to_human,
    check_health,
)

__all__ = [
    # Persona
    "TwinPersona",
    "CEO_TWIN",
    "CFO_TWIN",
    "GROUP_MANAGER_TWIN",
    "STRATEGY_TWIN",
    "ANALYST_TWIN",
    "REVIEWER_TWIN",
    "TWIN_CATALOG",
    # Protocol
    "InterTwinMessage",
    "TwinResponse",
    "validate_message",
    "should_escalate",
    # Memory
    "TwinState",
    "create_twin_state",
    "save_state",
    "load_state",
    "add_to_history",
    "add_investigation",
    "resolve_investigation",
    # Tools
    "query_kpi",
    "query_evidence",
    "send_message",
    "escalate_to_human",
    "check_health",
]
