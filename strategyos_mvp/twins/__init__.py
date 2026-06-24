"""Digital Twin system — autonomous agent layer for StrategyOS."""

from strategyos_mvp.twins.persona import (
    ANALYST_TWIN,
    CEO_TWIN,
    CFO_TWIN,
    CEO_INVESTIGATION_PROMPTS,
    CFO_DATA_OWNERSHIP,
    GROUP_MANAGER_TWIN,
    GROUP_MANAGER_INVESTIGATION_PROMPTS,
    GROUP_MANAGER_DATA_OWNERSHIP,
    ANALYST_INVESTIGATION_PROMPTS,
    ANALYST_DATA_OWNERSHIP,
    STRATEGY_TWIN,
    STRATEGY_INVESTIGATION_PROMPTS,
    STRATEGY_DATA_OWNERSHIP,
    REVIEWER_TWIN,
    REVIEWER_INVESTIGATION_PROMPTS,
    REVIEWER_DATA_OWNERSHIP,
    TWIN_CATALOG,
    TwinPersona,
    get_twin,
    lookup_persona,
)
from strategyos_mvp.twins.protocol import (
    InterTwinMessage,
    TwinResponse,
    validate_message,
    validate_response,
    should_escalate,
    check_escalation,
    escalate_message,
    get_escalation_timeout,
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
from strategyos_mvp.twins.resolution import (
    KPI_TREE,
    KPIResolutionEngine,
    resolve_multi_hop,
)
from strategyos_mvp.twins.runtime import (
    TwinRuntime,
)
from strategyos_mvp.twins.orchestration import (
    CycleScheduler,
    TriggerEngine,
    GovernanceGate,
    GovernanceEngine,
    CycleRecord,
    CycleHistory,
    generate_board_packet,
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
    "lookup_persona",
    "get_twin",
    "CEO_INVESTIGATION_PROMPTS",
    "CFO_DATA_OWNERSHIP",
    "GROUP_MANAGER_INVESTIGATION_PROMPTS",
    "GROUP_MANAGER_DATA_OWNERSHIP",
    "ANALYST_INVESTIGATION_PROMPTS",
    "ANALYST_DATA_OWNERSHIP",
    "STRATEGY_INVESTIGATION_PROMPTS",
    "STRATEGY_DATA_OWNERSHIP",
    "REVIEWER_INVESTIGATION_PROMPTS",
    "REVIEWER_DATA_OWNERSHIP",
    # Protocol
    "InterTwinMessage",
    "TwinResponse",
    "validate_message",
    "validate_response",
    "should_escalate",
    "check_escalation",
    "escalate_message",
    "get_escalation_timeout",
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
    # Resolution
    "KPI_TREE",
    "KPIResolutionEngine",
    "resolve_multi_hop",
    # Runtime
    "TwinRuntime",
    # Orchestration
    "CycleScheduler",
    "TriggerEngine",
    "GovernanceGate",
    "GovernanceEngine",
    "CycleRecord",
    "CycleHistory",
    "generate_board_packet",
]
