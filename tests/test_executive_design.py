"""Runtime executive design must remain presentation identity only."""

from __future__ import annotations

from strategyos_mvp.executive_design import (
    EXECUTIVE_DESIGN,
    executive_board_design,
    executive_persona_design,
)


PERSONA_IDS = ("ceo", "cfo", "gm", "bucfo", "logistics", "board")
ALLOWED_PERSONA_KEYS = {"assistant", "assistantRole", "indexLabel"}
FORBIDDEN_RUNTIME_TERMS = (
    "tamween",
    "nupco",
    "glp-1",
    "8.6m",
    "1.2m",
    "runningagents",
    "discoveragents",
    "developments",
    "findings",
    "drivers",
    "cashpulse",
)


def test_all_personas_are_identity_only() -> None:
    personas = EXECUTIVE_DESIGN["personas"]
    assert set(personas) == set(PERSONA_IDS)
    for persona_id in PERSONA_IDS:
        persona = executive_persona_design(persona_id)
        assert set(persona) == ALLOWED_PERSONA_KEYS
        assert all(str(persona[key]).strip() for key in ALLOWED_PERSONA_KEYS)


def test_persona_names_remain_stable() -> None:
    assert executive_persona_design("ceo")["assistant"] == "Hermes"
    assert executive_persona_design("cfo")["assistant"] == "Atlas"
    assert executive_persona_design("gm")["assistant"] == "Iris"
    assert executive_persona_design("bucfo")["assistant"] == "Argus"
    assert executive_persona_design("logistics")["assistant"] == "Vega"
    assert executive_persona_design("board")["assistant"] == "Minerva"
    assert executive_board_design() == {"assistant": "Minerva"}


def test_unknown_persona_falls_back_to_ceo_identity() -> None:
    assert executive_persona_design("unknown") == executive_persona_design("ceo")


def test_identity_results_are_copies() -> None:
    changed = executive_persona_design("ceo")
    changed["assistant"] = "Changed"
    assert executive_persona_design("ceo")["assistant"] == "Hermes"


def test_runtime_design_contains_no_illustrative_business_story() -> None:
    serialized = repr(EXECUTIVE_DESIGN).lower()
    assert all(term not in serialized for term in FORBIDDEN_RUNTIME_TERMS)
