"""Illustrative executive packet used only by scenario and model unit tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_PACKET: dict[str, Any] = {
    "packet_id": "test-fixture:executive-demo",
    "persona_id": "ceo",
    "is_illustrative": True,
    "public_safe": True,
    "source_label": "Illustrative unit-test fixture; not derived from a governed run.",
    "assistant": "Hermes",
    "health": {
        "score": 78,
        "headline": "Illustrative margin signal",
        "body": "Test-only board narrative.",
        "scoreNote": "test fixture",
    },
    "kpis": [
        {"key": "revenue", "label": "Revenue", "value": "SAR 2.09B"},
        {"key": "ebitda", "label": "EBITDA margin", "value": "19.2%"},
        {"key": "cash", "label": "Cash vs floor", "value": "SAR 1.48B"},
    ],
    "drivers": [
        {
            "key": "revenue",
            "label": "Revenue",
            "value": "SAR 2.09B",
            "story": "Illustrative e-Pharmacy and Digital Health growth signal.",
        },
        {
            "key": "ebitda",
            "label": "EBITDA margin",
            "value": "19.2%",
            "story": "Illustrative FX and input-cost pressure.",
        },
    ],
    "findings": [
        {
            "title": "SAR 8.6M is recoverable across the group",
            "tag": "Test finding",
            "detail": "Tamween audit contributes SAR 1.2M to the test recovery pool.",
        }
    ],
    "developments": [
        {
            "title": "Tamween audit: SAR 1.2M recoverable",
            "meta": "Test fixture",
            "impact": "Part of the SAR 8.6M test recovery pool.",
        },
        {
            "title": "e-Pharmacy orders increased",
            "meta": "Test fixture",
            "impact": "Orders are up 12% week on week in this fixture.",
        },
    ],
    "week": [
        {
            "key": "board",
            "title": "Illustrative board meeting",
            "prep": "Test the margin narrative and GLP-1 JV question.",
            "prompt": "What should I prepare for the board?",
        }
    ],
    "board_portal": {
        "state": "pre",
        "presentation_state": "pre",
        "summary": "Illustrative board fixture",
        "decks": [],
        "supplementary": [],
    },
    "agent_activity": {"line": "Illustrative test activity", "metrics": [], "log": []},
    "activity": {"line": "Illustrative test activity", "metrics": [], "log": []},
    "running_agents": [],
    "public_facts": {
        "group_recoverable_sar": 8_600_000.0,
        "tamween_recoverable_sar": 1_200_000.0,
        "fx_drag_weekly_sar": 9_000.0,
        "fx_hedge_recovery_bps": 15.0,
        "ebitda_margin_pct": 19.2,
        "ebitda_plan_pct": 19.4,
        "epharmacy_orders_wow_pct": 12.0,
        "healthcare_occupancy_delta_pct": -3.8,
        "board_pack_completion_pct": 80.0,
        "cold_chain_integrity_pct": 99.4,
        "source_boundary": "Illustrative unit-test fixture only.",
    },
    "facts": [
        "Tamween audit: SAR 1.2M recoverable.",
        "SAR 8.6M is recoverable across the group.",
        "e-Pharmacy orders are up 12% week on week.",
        "FX creates a SAR 9k weekly test drag and a 60% hedge is under review.",
        "The illustrative board pack is 80% composed.",
    ],
    "kg_nodes": [
        {"id": "kpi:revenue", "label": "Revenue", "properties": {"value": "SAR 2.09B"}},
        {"id": "kpi:ebitda", "label": "EBITDA margin", "properties": {"value": "19.2%"}},
        {"id": "initiative:epharmacy", "label": "e-Pharmacy", "properties": {"orders_wow_pct": 12}},
        {"id": "finding:tamween", "label": "Tamween audit", "properties": {"recoverable_sar": 1_200_000}},
        {"id": "finding:group", "label": "Group recovery", "properties": {"recoverable_sar": 8_600_000}},
        {"id": "risk:fx", "label": "FX exposure", "properties": {"weekly_drag_sar": 9_000}},
    ],
    "kg_edges": [
        {"source": "initiative:epharmacy", "target": "kpi:revenue", "label": "LIFTS"},
        {"source": "risk:fx", "target": "kpi:ebitda", "label": "DRAGS"},
        {"source": "finding:tamween", "target": "finding:group", "label": "PART_OF"},
    ],
    "trace_summary": {"activity_line": "Illustrative test activity"},
}


def executive_demo_packet(persona_id: str = "ceo") -> dict[str, Any]:
    packet = deepcopy(_PACKET)
    packet["persona_id"] = persona_id
    return packet
