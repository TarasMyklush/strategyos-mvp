"""Presentation identity for executive personas.

This runtime module intentionally contains no KPI values, findings, board
events, agent activity, prompts, or illustrative business narrative. Executive
business content must be built from the current governed read model.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


EXECUTIVE_DESIGN: dict[str, Any] = {
    "personas": {
        "ceo": {
            "assistant": "Hermes",
            "assistantRole": "chief of staff",
            "indexLabel": "The group index",
        },
        "cfo": {
            "assistant": "Atlas",
            "assistantRole": "finance chief of staff",
            "indexLabel": "The financial index",
        },
        "gm": {
            "assistant": "Iris",
            "assistantRole": "ground operator",
            "indexLabel": "The business-unit index",
        },
        "bucfo": {
            "assistant": "Argus",
            "assistantRole": "controller",
            "indexLabel": "The business-unit financial index",
        },
        "logistics": {
            "assistant": "Vega",
            "assistantRole": "logistics chief of staff",
            "indexLabel": "The logistics index",
        },
        "board": {
            "assistant": "Minerva",
            "assistantRole": "board chief of staff",
            "indexLabel": "The board index",
        },
    },
    "board": {"assistant": "Minerva"},
}


def executive_persona_design(persona_id: str) -> dict[str, Any]:
    """Return immutable presentation identity for a supported persona."""

    personas = EXECUTIVE_DESIGN["personas"]
    return deepcopy(personas.get(persona_id) or personas["ceo"])


def executive_board_design() -> dict[str, Any]:
    """Return board-room presentation identity only."""

    return deepcopy(EXECUTIVE_DESIGN["board"])
