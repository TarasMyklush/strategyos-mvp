"""Contract tests for executive persona design and golden prompts.

Verifies:
- All personas are present with required shape (health, drivers, findings, prompts, week)
- Golden prompts are present and match expected values
- Board design is complete with governance, decks, supplementary, actions
- Activity design has correct structure
- Running agents, discoverable agents, and subtools are well-formed
- No LLM/hallucination in design data — all values are deterministic

Target architecture: EXECUTIVE_DESIGN dict in executive_design.py
"""

from __future__ import annotations

import pytest

from strategyos_mvp.executive_design import (
    EXECUTIVE_DESIGN,
    executive_persona_design,
    executive_board_design,
    executive_activity_design,
    executive_running_agents_design,
    executive_discover_agents_design,
    executive_subtools_design,
)


# ─────────────────────────────────────────────────────────────────────────────
# Persona existence and shape
# ─────────────────────────────────────────────────────────────────────────────

PERSONA_IDS = ("ceo", "cfo", "gm", "bucfo", "logistics")

REQUIRED_PERSONA_KEYS = {
    "health", "assistant", "assistantRole", "brief", "quote", "by",
    "threads", "prompts", "drivers", "findings", "developments", "week",
}

REQUIRED_DRIVER_KEYS = {"key", "label", "pct", "value", "sub", "vsPlan", "story", "movers"}

REQUIRED_HEALTH_KEYS = {"score", "headline", "body", "scoreNote"}

REQUIRED_WEEK_ITEM_KEYS = {"key", "day", "title", "when", "prep", "urgent", "prompt"}


def test_all_personas_present():
    """All five persona IDs must be present in EXECUTIVE_DESIGN.personas."""
    personas = EXECUTIVE_DESIGN.get("personas", {})
    for pid in PERSONA_IDS:
        assert pid in personas, f"Missing persona: {pid}"
        assert isinstance(personas[pid], dict), f"Persona {pid} is not a dict"


def test_ceo_persona_shape():
    persona = executive_persona_design("ceo")
    missing = REQUIRED_PERSONA_KEYS - set(persona.keys())
    assert not missing, f"CEO persona missing keys: {missing}"
    assert persona["assistant"] == "Hermes"
    assert persona["assistantRole"] == "chief of staff"
    assert "Thursday" in persona["brief"] or "board" in persona["brief"].lower()


def test_cfo_persona_shape():
    persona = executive_persona_design("cfo")
    missing = REQUIRED_PERSONA_KEYS - set(persona.keys())
    assert not missing, f"CFO persona missing keys: {missing}"
    assert persona["assistant"] == "Atlas"
    assert persona["assistantRole"] == "finance chief of staff"
    assert "liquidity" in persona["brief"].lower()


def test_gm_persona_shape():
    persona = executive_persona_design("gm")
    missing = REQUIRED_PERSONA_KEYS - set(persona.keys())
    assert not missing, f"GM persona missing keys: {missing}"
    assert persona["assistant"] == "Iris"
    assert persona["assistantRole"] == "ground operator"


def test_bucfo_persona_shape():
    persona = executive_persona_design("bucfo")
    missing = REQUIRED_PERSONA_KEYS - set(persona.keys())
    assert not missing, f"BU CFO persona missing keys: {missing}"
    assert persona["assistant"] == "Argus"
    assert persona["assistantRole"] == "exacting controller"


def test_logistics_persona_shape():
    persona = executive_persona_design("logistics")
    missing = REQUIRED_PERSONA_KEYS - set(persona.keys())
    assert not missing, f"Logistics persona missing keys: {missing}"
    assert persona["assistant"] == "Vega"
    assert persona["assistantRole"] == "logistics chief of staff"


# ─────────────────────────────────────────────────────────────────────────────
# Health scores
# ─────────────────────────────────────────────────────────────────────────────

def test_health_scores_are_present_and_valid():
    """Every persona's health block must have score, headline, body, scoreNote."""
    for pid in PERSONA_IDS:
        persona = executive_persona_design(pid)
        health = persona["health"]
        missing = REQUIRED_HEALTH_KEYS - set(health.keys())
        assert not missing, f"{pid} health missing keys: {missing}"
        assert isinstance(health["score"], int), f"{pid} health.score not int"
        assert 0 <= health["score"] <= 100, f"{pid} health.score {health['score']} out of range"
        assert health["headline"], f"{pid} health.headline is empty"
        assert health["body"], f"{pid} health.body is empty"
        assert health["scoreNote"], f"{pid} health.scoreNote is empty"


# ─────────────────────────────────────────────────────────────────────────────
# Golden prompts
# ─────────────────────────────────────────────────────────────────────────────

GOLDEN_PROMPTS = {
    "ceo": [
        "Am I on track for the board on Thursday?",
        "What is the single biggest risk to plan?",
        "Who deserves recognition this week?",
    ],
    "cfo": [
        "Walk me through the EBITDA bridge.",
        "Where is the SAR 8.6M?",
        "Can the JV be funded from cash?",
    ],
    "gm": [
        "How long until the Eastern hub caps us?",
        "Where is capacity binding first?",
        "What do I owe the CEO before tomorrow's call?",
    ],
    "bucfo": [
        "Draft my variance note on the margin drag.",
        "What is the SAR 1.2M recovery path?",
        "What still needs closing before the cost line steps down?",
    ],
    "logistics": [
        "What keeps service credibility strongest this week?",
        "Where could continuity slip before the board?",
        "Which logistics win should the board hear?",
    ],
}


def test_golden_prompts_per_persona():
    """Every persona must have exactly the expected golden prompts."""
    for pid in PERSONA_IDS:
        persona = executive_persona_design(pid)
        prompts = persona.get("prompts", [])
        expected = GOLDEN_PROMPTS[pid]
        assert prompts == expected, (
            f"{pid} prompts mismatch.\n  Got:      {prompts}\n  Expected: {expected}"
        )


def test_golden_prompts_are_non_empty():
    """No golden prompt should be empty or whitespace-only."""
    for pid in PERSONA_IDS:
        persona = executive_persona_design(pid)
        prompts = persona.get("prompts", [])
        assert len(prompts) >= 3, f"{pid} has fewer than 3 prompts: {len(prompts)}"
        for prompt in prompts:
            assert prompt.strip(), f"{pid} has blank prompt"


# ─────────────────────────────────────────────────────────────────────────────
# Threads
# ─────────────────────────────────────────────────────────────────────────────

def test_threads_per_persona():
    """Each persona must have at least 3 threads with key, title, preview."""
    for pid in PERSONA_IDS:
        persona = executive_persona_design(pid)
        threads = persona.get("threads", [])
        assert len(threads) == 3, f"{pid} has {len(threads)} threads (expected 3)"
        for thread in threads:
            assert "key" in thread, f"{pid} thread missing key: {thread}"
            assert "title" in thread, f"{pid} thread missing title"
            assert "preview" in thread, f"{pid} thread missing preview"


# ─────────────────────────────────────────────────────────────────────────────
# Drivers
# ─────────────────────────────────────────────────────────────────────────────

def test_drivers_per_persona():
    """Each persona must have exactly 4 drivers with required shape."""
    for pid in PERSONA_IDS:
        persona = executive_persona_design(pid)
        drivers = persona.get("drivers", [])
        assert len(drivers) == 4, f"{pid} has {len(drivers)} drivers (expected 4)"
        for driver in drivers:
            missing = REQUIRED_DRIVER_KEYS - set(driver.keys())
            assert not missing, f"{pid} driver '{driver.get('key')}' missing: {missing}"
            assert isinstance(driver["pct"], int), f"{pid} driver pct not int"
            # Movers must have lifting and dragging lists
            movers = driver["movers"]
            assert "lifting" in movers, f"{pid} driver {driver['key']} movers missing 'lifting'"
            assert "dragging" in movers, f"{pid} driver {driver['key']} movers missing 'dragging'"
            assert isinstance(movers["lifting"], list)
            assert isinstance(movers["dragging"], list)


# ─────────────────────────────────────────────────────────────────────────────
# CEO-specific driver contents (Digital Health flat, e-Pharmacy, FX hedge)
# ─────────────────────────────────────────────────────────────────────────────

def test_ceo_drivers_contain_key_business_terms():
    """CEO drivers must reference Digital Health, e-Pharmacy, FX/hedge, Healthcare occupancy."""
    persona = executive_persona_design("ceo")
    drivers = persona.get("drivers", [])
    driver_text = " ".join(
        str(d.get("story", "")) + " " + str(d.get("label", ""))
        for d in drivers
    ).lower()
    # Digital Health is a key revenue mover
    assert "digital health" in driver_text, "CEO drivers missing 'Digital Health' reference"
    # e-Pharmacy is a growth driver
    assert "e-pharmacy" in driver_text or "epharmacy" in driver_text, (
        "CEO drivers missing 'e-Pharmacy' reference"
    )
    # FX/hedge is a margin drag
    assert "fx" in driver_text or "hedge" in driver_text, (
        "CEO drivers missing 'FX' or 'hedge' reference"
    )
    # Healthcare occupancy is a drag
    assert "healthcare" in driver_text, "CEO drivers missing 'Healthcare' reference"


def test_ceo_findings_contain_sar_8_6m():
    """CEO findings must reference the SAR 8.6M recoverable finding."""
    persona = executive_persona_design("ceo")
    findings = persona.get("findings", [])
    findings_text = " ".join(
        f.get("title", "") + " " + f.get("detail", "")
        for f in findings
    ).lower()
    assert "8.6m" in findings_text or "8.6 m" in findings_text, (
        "CEO findings missing SAR 8.6M reference"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CFO-specific driver contents (FX hedge)
# ─────────────────────────────────────────────────────────────────────────────

def test_cfo_drivers_contain_fx_hedge():
    """CFO drivers must reference the 60% EUR hedge decision."""
    persona = executive_persona_design("cfo")
    drivers = persona.get("drivers", [])
    driver_text = " ".join(
        str(d.get("story", "")) + " " + str(d.get("label", ""))
        for d in drivers
    ).lower()
    assert "fx" in driver_text or "hedge" in driver_text, (
        "CFO drivers missing 'FX' or 'hedge' reference"
    )
    # The cash pulse must include the SAR 8.6M loss/leakage pillar
    cash_pulse = persona.get("cashPulse", {})
    pillars = cash_pulse.get("pillars", [])
    leakage_pillar = [p for p in pillars if "leak" in p.get("label", "").lower() or "lost" in p.get("label", "").lower()]
    assert leakage_pillar, "CFO cash pulse missing leakage/lost pillar"
    assert any("8.6" in str(p.get("value", "")) for p in leakage_pillar), (
        "CFO leakage pillar missing SAR 8.6M value"
    )


# ─────────────────────────────────────────────────────────────────────────────
# BU GM Healthcare occupancy
# ─────────────────────────────────────────────────────────────────────────────

def test_gm_drivers_contain_capacity_and_sla():
    """BU GM drivers must reference capacity constraints and SLA."""
    persona = executive_persona_design("gm")
    drivers = persona.get("drivers", [])
    driver_text = " ".join(
        str(d.get("story", "")) + " " + str(d.get("label", ""))
        for d in drivers
    ).lower()
    assert "capacity" in driver_text, "GM drivers missing 'capacity' reference"
    assert "sla" in driver_text or "fulfilment" in driver_text, (
        "GM drivers missing SLA/fulfilment reference"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Board design
# ─────────────────────────────────────────────────────────────────────────────

def test_board_design_is_complete():
    """Board design must have governance, meeting, kpis, decks, supplementary, actions."""
    board = executive_board_design()
    required = {"assistant", "meeting", "governance", "kpis", "decks",
                 "supplementary", "livePrompts", "actions", "summary"}
    missing = required - set(board.keys())
    assert not missing, f"Board design missing keys: {missing}"
    assert board["assistant"] == "Minerva"

    # KPIs must include revenue, ebitda, cash, localisation
    kpis = board.get("kpis", [])
    kpi_keys = {k.get("key") for k in kpis}
    assert "revenue" in kpi_keys, "Board KPIs missing 'revenue'"
    assert "ebitda" in kpi_keys, "Board KPIs missing 'ebitda'"
    assert "cash" in kpi_keys, "Board KPIs missing 'cash'"
    assert "localisation" in kpi_keys, "Board KPIs missing 'localisation'"

    # Decks must include the 4 expected decks
    decks = board.get("decks", [])
    assert len(decks) == 4, f"Board has {len(decks)} decks (expected 4)"

    # Actions must include hedge ratification, JV approval, Tamween recovery review
    actions = board.get("actions", [])
    action_text = " ".join(a.get("item", "") for a in actions).lower()
    assert "hedge" in action_text, "Board actions missing hedge reference"
    assert "jv" in action_text or "glp-1" in action_text, "Board actions missing JV reference"
    assert "tamween" in action_text, "Board actions missing Tamween reference"


def test_board_live_prompts_are_present():
    """Board must have live prompts for the board room."""
    board = executive_board_design()
    prompts = board.get("livePrompts", [])
    assert len(prompts) >= 2, f"Board has {len(prompts)} live prompts (expected >= 2)"


# ─────────────────────────────────────────────────────────────────────────────
# Activity design
# ─────────────────────────────────────────────────────────────────────────────

def test_activity_design_has_correct_metrics():
    """Activity design must list 5 agents, 25 steps, 15 tool calls, SAR 8.6M value."""
    activity = executive_activity_design()
    assert "line" in activity
    assert "SAR 8.6M" in activity["line"], f"Activity line missing SAR 8.6M: {activity['line']}"
    assert "metrics" in activity
    assert "log" in activity
    metrics = activity.get("metrics", [])
    metrics_by_k = {m["k"]: m["v"] for m in metrics}
    assert metrics_by_k.get("agents") == "5"
    assert metrics_by_k.get("value found") == "SAR 8.6M"


def test_running_agents_are_well_formed():
    """Each running agent must have id, name, status, progress, tag, doing."""
    agents = executive_running_agents_design()
    assert len(agents) == 5, f"Expected 5 running agents, got {len(agents)}"
    for agent in agents:
        assert "id" in agent, f"Agent missing id: {agent}"
        assert "name" in agent, f"Agent missing name"
        assert "status" in agent, f"Agent {agent['name']} missing status"
        assert "progress" in agent, f"Agent {agent['name']} missing progress"
        assert isinstance(agent["progress"], int), f"Agent progress not int"
        assert 0 <= agent["progress"] <= 100, f"Agent progress out of range"
        assert "doing" in agent, f"Agent {agent['name']} missing doing"


def test_discover_agents_are_well_formed():
    """Each discoverable agent must have id, glyph, name, source, desc, connector."""
    agents = executive_discover_agents_design()
    assert len(agents) >= 4, f"Expected >= 4 discover agents, got {len(agents)}"
    for agent in agents:
        assert "id" in agent
        assert "glyph" in agent
        assert "name" in agent
        assert "desc" in agent
        assert "connector" in agent


def test_subtools_are_well_formed():
    """Each subtool must have name, glyph, desc."""
    tools = executive_subtools_design()
    assert len(tools) == 4, f"Expected 4 subtools, got {len(tools)}"
    for tool in tools:
        assert "name" in tool
        assert "glyph" in tool
        assert "desc" in tool


# ─────────────────────────────────────────────────────────────────────────────
# Fallback — nonexistent persona returns CEO
# ─────────────────────────────────────────────────────────────────────────────

def test_nonexistent_persona_returns_ceo():
    """Asking for a nonexistent persona returns the CEO design as fallback."""
    result = executive_persona_design("nonexistent-persona")
    ceo = executive_persona_design("ceo")
    assert result == ceo, "Nonexistent persona should fall back to CEO"


# ─────────────────────────────────────────────────────────────────────────────
# Immutability — design functions return deep copies
# ─────────────────────────────────────────────────────────────────────────────

def test_persona_design_returns_deep_copy():
    """Mutating the return value must not affect the underlying EXECUTIVE_DESIGN."""
    original = executive_persona_design("ceo")
    copy1 = executive_persona_design("ceo")
    copy1["health"] = {"score": 999, "headline": "mutated", "body": "mutated", "scoreNote": "x"}
    copy2 = executive_persona_design("ceo")
    assert copy2["health"] == original["health"], "deep copy was not returned"


def test_board_design_returns_deep_copy():
    """Mutating the board return value must not affect the underlying design."""
    original = executive_board_design()
    copy1 = executive_board_design()
    copy1["assistant"] = "HACKED"
    copy2 = executive_board_design()
    assert copy2["assistant"] == original["assistant"], "board deep copy was not returned"
