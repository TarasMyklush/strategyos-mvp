"""Versioned agent and tool definitions (design doc sections 2, 5.1, 10).

This module is the single source of truth for which agents and tools exist.
Definitions are code-defined here and synchronized into
strategyos_agent_definitions by repository.sync_agent_definitions(); the
database never invents a definition on its own.

Capability routing (section 9) is deterministic for the first release: each
capability maps to exactly one agent_key. An unknown capability must resolve
to `clarify`/`refuse` upstream, never to an invented agent.
"""

from __future__ import annotations

from .models import AgentDefinition

CASH_RECOVERY = AgentDefinition(
    agent_key="cash-recovery",
    version=1,
    display_name="Cash Recovery Agent",
    purpose="Find, quantify, and monitor recoverable leakage",
    handler_key="cash_recovery.v1",
    input_schema="cash_recovery_task.v1",
    output_schema="agent_result.v1",
    tool_keys=("findings.read", "finance_facts.read", "citations.search"),
    allowed_roles=("executive", "finance", "reviewer", "operator"),
)

EVIDENCE_CLOSURE = AgentDefinition(
    agent_key="evidence-closure",
    version=1,
    display_name="Evidence Closure Agent",
    purpose="Resolve citation gaps, validate provenance, and challenge weak findings",
    handler_key="evidence_closure.v1",
    input_schema="evidence_closure_task.v1",
    output_schema="agent_result.v1",
    tool_keys=("citations.search", "findings.read", "graph.query"),
    allowed_roles=("executive", "finance", "reviewer", "operator"),
)

BOARD_PACK = AgentDefinition(
    agent_key="board-pack",
    # v2 (PR 6): added publication.release so board_pack_handler can report
    # release eligibility through the restricted-tool capability-token path
    # rather than reading approval_status_for_run directly. Per design doc
    # section 5.1, this is a new version, not an in-place edit -- any task
    # still recorded against agent_definition_version=1 keeps its original
    # contract.
    version=2,
    display_name="Board Pack Agent",
    purpose="Produce board-safe summaries and publication candidates",
    handler_key="board_pack.v1",
    input_schema="board_pack_task.v1",
    output_schema="agent_result.v1",
    tool_keys=("board_pack.prepare", "findings.read", "review.request", "publication.release"),
    allowed_roles=("executive", "reviewer", "operator"),
)

RUNTIME_GUARDRAIL = AgentDefinition(
    agent_key="runtime-guardrail",
    version=1,
    display_name="Runtime Guardrail Agent",
    purpose="Inspect runtime, connector, queue, and policy health",
    handler_key="runtime_guardrail.v1",
    input_schema="runtime_guardrail_task.v1",
    output_schema="agent_result.v1",
    tool_keys=("runtime.health.read",),
    allowed_roles=("executive", "operator"),
)

AGENT_DEFINITIONS: tuple[AgentDefinition, ...] = (
    CASH_RECOVERY,
    EVIDENCE_CLOSURE,
    BOARD_PACK,
    RUNTIME_GUARDRAIL,
)

AGENT_DEFINITIONS_BY_KEY: dict[str, AgentDefinition] = {
    definition.agent_key: definition for definition in AGENT_DEFINITIONS
}

# Capability -> agent_key routing table (design doc section 9). An LLM may
# classify free-text intent into this allowlist; it may not invent entries.
CAPABILITY_ROUTES: dict[str, str] = {
    "quantify_recoverable_value": "cash-recovery",
    "monitor_recovery_case": "cash-recovery",
    "resolve_evidence_gap": "evidence-closure",
    "challenge_finding": "evidence-closure",
    "prepare_board_pack": "board-pack",
    "explain_publication_posture": "board-pack",
    "inspect_runtime_health": "runtime-guardrail",
    "diagnose_connector_or_queue": "runtime-guardrail",
}

# Tool key -> risk class (design doc section 10). Tool handlers/schemas land
# in tools.py in a later PR; this catalogue exists now so registry sync and
# policy checks have a stable vocabulary to validate agent tool_keys against.
TOOL_RISK_CLASSES: dict[str, str] = {
    "findings.read": "read_only",
    "citations.search": "read_only",
    "graph.query": "read_only",
    "finance_facts.read": "read_only",
    "runtime.health.read": "read_only",
    "finance_controls.run": "prepare",
    # board_pack.prepare and review.request are catalogued read_only, not
    # "prepare": both tools.py implementations (_board_pack_prepare,
    # _review_request) only wrap existing read functions
    # (_summary_publication_payload/_summary_report_contracts,
    # approval_status_for_run) -- neither mutates anything. Classifying
    # them as "prepare" would (correctly, as of PR 6's capability-token
    # gate) require every existing board-pack task to carry a token for a
    # call that has no side effect to protect against. Only
    # publication.release and a hypothetical future finance_controls.run
    # wiring are genuinely consequential in this catalogue.
    "board_pack.prepare": "read_only",
    "review.request": "read_only",
    "publication.release": "restricted",
}


def resolve_agent_for_capability(capability: str) -> AgentDefinition | None:
    agent_key = CAPABILITY_ROUTES.get(capability)
    if agent_key is None:
        return None
    return AGENT_DEFINITIONS_BY_KEY.get(agent_key)


def known_capabilities() -> frozenset[str]:
    return frozenset(CAPABILITY_ROUTES.keys())


def validate_definitions() -> None:
    """Fail fast if a shipped definition references an unknown tool key.

    Called from tests and from sync_agent_definitions() so a typo in
    tool_keys is caught at registry load time, not at task-execution time.
    """
    for definition in AGENT_DEFINITIONS:
        unknown = set(definition.tool_keys) - set(TOOL_RISK_CLASSES.keys())
        if unknown:
            raise ValueError(
                f"agent {definition.agent_key!r} references unknown tool keys: {sorted(unknown)}"
            )
