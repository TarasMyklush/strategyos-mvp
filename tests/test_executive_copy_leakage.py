"""Ground rule G3 as an enforced contract.

The Legion build spec states the copy rule for every executive-facing string:

    "would a chief of staff say this aloud to the CEO?"

Concretely: no "governed milestone", "reconciled evidence and approval lane",
"lifecycle actions attached to this state", "completed at writer", "surfaced
artifacts".  Never render internal paths (/runs/latest/report-preview), run IDs,
or writer/stage names on an executive or board surface.

These tests pin the vocabulary at the point it is authored, so a future edit
cannot quietly reintroduce internal language into the CEO or board surface.
The banned terms below are the spec's own list; ``executive.js`` and the
executive presentation contract are the two places CEO-facing copy is written.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXECUTIVE_JS = ROOT / "strategyos_mvp" / "static" / "executive.js"
EXECUTIVE_HTML = ROOT / "strategyos_mvp" / "static" / "executive.html"
PRESENTATION = ROOT / "strategyos_mvp" / "executive_presentation.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# Phrases the spec names explicitly.  Each one reads as internal machinery
# rather than something a chief of staff would say out loud.
BANNED_EXECUTIVE_PHRASES = (
    "governed milestone",
    "reconciled evidence and approval lane",
    "lifecycle actions are attached",
    "Lifecycle actions",
    "completed at writer",
    "surfaced artifacts",
    "latest governed run",
    "governed commentary",
    "ranked governed components",
    "Monitoring its governed KPIs",
)

# Internal pipeline stage names must never appear in a rendered sentence.
BANNED_STAGE_WORDS = ("writer", "reviewer stage", "analyst stage")


def _rendered_string_literals(path: Path) -> list[str]:
    """Every string literal in a Python module, excluding docstrings.

    Docstrings and comments describe our own machinery to engineers and may say
    "governed milestone" freely.  Only text that can reach a CEO's screen is
    held to the copy rule.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_executive_presentation_copy_has_no_internal_vocabulary() -> None:
    """The CEO hero/KPI contract is authored here; keep it in plain language."""
    literals = _rendered_string_literals(PRESENTATION)

    for phrase in BANNED_EXECUTIVE_PHRASES:
        offenders = [text for text in literals if phrase in text]
        assert not offenders, (
            f"{phrase!r} reads as internal machinery, not chief-of-staff language. "
            f"Rewrite the executive-facing string (spec ground rule G3): {offenders[:2]}"
        )


def test_executive_presentation_asks_for_a_due_date_in_plain_language() -> None:
    """The spec gives this exact replacement wording; pin it."""
    source = _read(PRESENTATION)

    assert "No due date is set yet — when do you want it?" in source


def test_executive_surface_renders_no_internal_paths_or_run_ids() -> None:
    """No /runs/... route, run id, or stage name on an executive surface."""
    for path in (EXECUTIVE_JS, EXECUTIVE_HTML):
        source = _read(path)
        assert "/runs/latest/report-preview" not in source, (
            f"{path.name} renders an internal report-preview path to the executive."
        )


def test_executive_js_has_no_lifecycle_or_writer_vocabulary() -> None:
    source = _read(EXECUTIVE_JS)

    assert "Lifecycle actions" not in source
    assert "No lifecycle actions are attached to this state." not in source
    assert "Nothing needs your action at this stage." in source
    assert "What needs your action" in source
    # "Previewable report routes" describes our URL surface, not the board's pack.
    assert "Previewable report routes" not in source
    assert "Reports in the board pack" in source


def test_executive_greeting_addresses_the_modelled_executive_not_the_login() -> None:
    """B3: the greeting is the persona's owner, never the sign-in account.

    ``executive.tester`` must not produce "Good morning, Executive" while the
    dataset names the CEO.  The hero eyebrow and the morning note must resolve
    the greeted person through the same helper so they cannot disagree.
    """
    source = _read(EXECUTIVE_JS)

    assert "function greetedOwnerName()" in source, (
        "Greeting resolution must live in one helper so hero and morning note agree."
    )
    # The hero eyebrow must not read the session name directly any more.
    hero_assignment = re.search(
        r"var fullName = ([A-Za-z_$][\w$]*)\(\);\s*\n\s*var firstName", source
    )
    assert hero_assignment is not None, "Could not locate the hero greeting assignment."
    assert hero_assignment.group(1) == "greetedOwnerName", (
        "The hero greeting must resolve through greetedOwnerName(), not "
        f"{hero_assignment.group(1)}() — otherwise a test login is greeted by name."
    )


def test_achievements_window_is_derived_not_a_hardcoded_date() -> None:
    """B2: good news must survive, and the window must come from the run.

    The achievements filter used a literal "2026-05-28" floor, which silently
    stops working the moment the dataset anchor moves.  The window is now
    derived from the run's own demo_window.
    """
    source = _read(EXECUTIVE_JS)

    assert '"2026-05-28"' not in source, (
        "Achievement recency was pinned to a hardcoded date; derive it from demo_window."
    )
    assert "function lastVisitDate()" in source
    assert "function isSinceLastVisit(" in source
    assert "isSinceLastVisit(item.date)" in source


def test_developments_card_reserves_a_slot_for_an_achievement() -> None:
    """Concerns are concatenated first, so a plain slice() drops all good news."""
    source = _read(EXECUTIVE_JS)

    assert "function withAchievement(" in source
    assert "withAchievement(developmentsSection.items, 3)" in source
    assert "safeArray(developmentsSection.items).slice(0, 3)" not in source


def test_since_you_were_here_count_line_is_rendered() -> None:
    """B2 header count line, counted from the same records the card lists."""
    source = _read(EXECUTIVE_JS)
    html = _read(EXECUTIVE_HTML)

    assert 'id="lower-rail-note"' in html, "The count line needs a render target."
    assert "function renderSinceYouWereHereNote()" in source
    assert '"Since " + label + ": " + parts.join(" · ")' in source


def test_plan_health_ring_shows_a_score_above_plan_instead_of_flattening_it() -> None:
    """Running ahead of plan is a real result; 101.2 must not render as 100.

    The ring arc still clamps to 0-100 because that is geometry, but the number
    the CEO reads is the true score.
    """
    source = _read(EXECUTIVE_JS)

    assert "var displayScore" in source
    assert 'String(displayScore || 0) + "% of plan"' in source
    assert "escapeHtml(String(displayScore || 0)) + '</span><small>plan health</small>'" in source
    assert "escapeHtml(String(clampedScore || 0)) + '</span><small>plan health</small>'" not in source
