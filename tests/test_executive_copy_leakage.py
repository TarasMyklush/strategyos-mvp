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


API = ROOT / "strategyos_mvp" / "api.py"

# Strings that reach the CEO through the run payload rather than a template.
# KPI driver "detail" lines and plan-health "root_summary" both render in
# executive.js (driver.detail at the summary body and KPI drill; the plan
# health summary under the hero).  The first live probe after the copy pass
# still found "latest governed run" nine times in the served payload, because
# only template strings had been checked -- operator-lane help text may keep
# its own vocabulary, so this is scoped to the executive-facing keys.
PAYLOAD_FACING_PHRASES = (
    "latest governed run",
    "surfaced artifact",
    "bounded executive plan readout",
)

EXECUTIVE_PAYLOAD_KEYS = ("detail", "root_summary", "rationale")


def _executive_payload_strings(path: Path) -> list[str]:
    """String values assigned to executive-facing payload keys.

    Covers both ``{"detail": "..."}`` dict entries and ``root_summary="..."``
    keyword arguments.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value in EXECUTIVE_PAYLOAD_KEYS
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    found.append(value.value)
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if (
                    kw.arg in EXECUTIVE_PAYLOAD_KEYS
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    found.append(kw.value.value)
    return found


def test_executive_payload_strings_have_no_internal_vocabulary() -> None:
    """KPI driver details and plan-health summaries are executive copy too."""
    literals = _executive_payload_strings(API)
    assert literals, "Expected to find executive payload strings to check."

    for phrase in PAYLOAD_FACING_PHRASES:
        offenders = [text for text in literals if phrase in text]
        assert not offenders, (
            f"{phrase!r} reaches the CEO through the run payload. "
            f"Rewrite it in executive language (spec ground rule G3): {offenders[:2]}"
        )


def test_board_surface_does_not_ship_other_personas_assistant_names() -> None:
    """B3: the board sees Minerva only -- in the markup, not just visually.

    Hiding a name with CSS still ships it: a grep of the served HTML finds
    Hermes on a board surface, which is exactly what the spec's acceptance
    test checks.  The threads are withheld from the board markup instead.
    """
    source = _read(EXECUTIVE_JS)
    html = _read(EXECUTIVE_HTML)

    assert 'state.activePersona === "board"\n        ? []' in source, (
        "Assistant-to-assistant threads must be withheld from board markup."
    )
    # The static shell must not hardcode one persona's assistant either; JS
    # fills the real name in after hydration.
    assert "Ask Hermes" not in html, (
        "executive.html ships 'Ask Hermes' before hydration, so a board page "
        "load serves another persona's assistant name."
    )


def test_morning_note_carries_the_days_own_news() -> None:
    """B4: the note must change when the day scrubber advances."""
    source = _read(EXECUTIVE_JS)

    assert "var todaysWins" in source
    assert "enrichment.daily_pulse" in source
    assert "Good news today: " in source


def test_plan_coverage_table_shows_actual_path_and_target_with_evidence() -> None:
    """B1: per-KPI drill is a table with actual vs on-path vs 2028 target."""
    source = _read(EXECUTIVE_JS)

    assert "coverageValue(item.checkpoint, item.unit)" in source
    assert "coverageValue(item.target_2028, item.unit)" in source
    assert "plan-coverage-row--head" in source
    assert "groundingBadgeMarkup(null, {" in source


def test_open_assistant_threads_survive_a_reload() -> None:
    """B5: 'close and reopen -> conversation still there' includes a reload."""
    source = _read(EXECUTIVE_JS)

    assert "function persistA2AOpenThreads()" in source
    assert "function restoreA2AOpenThreads()" in source
    assert "openA2AThreadKeys: restoreA2AOpenThreads()" in source


def test_historic_context_states_the_scope_of_trend_and_drivers() -> None:
    """The multi-year trend and its drivers can be different entities.

    Reporting a division trend and explaining it with group-sized drivers is
    incoherent -- a SAR 2,120M driver cannot account for SAR 43M of growth.
    """
    from pathlib import Path as _Path

    historic = ROOT / "strategyos_mvp" / "source_historic_context.py"
    source = _read(_Path(historic))

    assert "def _scope_of(" in source
    assert '"annual_revenue_scope"' in source
    assert '"revenue_drivers_scope"' in source
    assert '"scope_warning"' in source

    qa = _read(ROOT / "strategyos_mvp" / "llm_qa.py")
    assert "annual_revenue_scope" in qa
    assert "scope_warning" in qa
    assert "cannot account for a trend" in qa, (
        "The prompt must forbid explaining a movement with a different entity's driver."
    )


def test_group_ebitda_uses_the_stated_amount_not_a_rounded_margin() -> None:
    """Reconstructing EBITDA from a 1-dp margin moved the group figure ~SAR 1M."""
    source = _read(ROOT / "strategyos_mvp" / "source_finance_kpis.py")

    assert '"ebitdah1budgetsarm"' in source
    assert '"ebitdah1actualsarm"' in source
    assert 'group_total.get("actual_ebitda") is not None' in source
    assert 'group_total.get("plan_ebitda") is not None' in source


def test_morning_note_never_renders_a_null_pulse_value_to_the_ceo() -> None:
    """Most daily-pulse rows carry Notes: null.

    ``firstDefined`` treats null as present, so a naive String() would put the
    literal text "null" in front of the CEO.  When there is no note the day's
    own measures are used instead, read by column meaning rather than a fixed
    header so a renamed dataset still works.
    """
    source = _read(EXECUTIVE_JS)

    assert 'pulseNote === "null"' in source, (
        "A null pulse note must not reach the CEO as the string 'null'."
    )
    assert "Today's pulse: " in source
    assert "/sales/i.test(key)" in source
    assert "/collection/i.test(key)" in source
    # Reuse the existing money formatter rather than adding a second one.
    assert "formatSarBrief" not in source
    assert "formatSarCompact(sales)" in source


def test_developments_card_keeps_a_positive_item_when_concerns_fill_it() -> None:
    """The card sorts critical -> watch -> positive, then truncates.

    With six drifting items -- the normal case -- every achievement sorted to
    the back and was cut, so the CEO saw a wall of red and no recognition.
    The truncation now reserves the last slot for a positive item.
    """
    source = _read(EXECUTIVE_JS)

    assert "function keepPositive(" in source
    assert "function withPositiveItem(" in source
    assert "withPositiveItem(developmentsAndConcerns, 6)" in source
    assert "}).slice(0, 6);" not in source, (
        "A bare slice() after the tone sort drops every positive item."
    )


def test_decision_title_column_cannot_collapse() -> None:
    """Three auto columns starved the 1fr title down to ~15px.

    The decision headline wrapped one word per line and overlapped the status
    chip.  The title now has a real minimum and the metadata ellipsises.
    """
    css = _read(ROOT / "strategyos_mvp" / "static" / "executive.css")

    assert "grid-template-columns: 8px minmax(190px, 1.6fr) auto minmax(0, auto) minmax(0, auto) 16px;" in css
    assert "grid-template-columns: 8px minmax(0, 1fr) auto auto auto 16px;" not in css
    assert "text-overflow: ellipsis;" in css
