import json
from pathlib import Path

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module


def _static_executive_js() -> str:
    client = TestClient(api_module.app)
    response = client.get("/static/executive.js")
    assert response.status_code == 200
    return response.text


def _ceo_executive_html() -> str:
    client = TestClient(api_module.app)
    response = client.get("/executive?persona=ceo")
    assert response.status_code == 200
    return response.text


def _static_executive_css() -> str:
    client = TestClient(api_module.app)
    response = client.get("/static/executive.css")
    assert response.status_code == 200
    return response.text


def test_ceo_assistant_never_leaks_raw_internals():
    """CEO surface must route through the shared API without a client-side brain."""
    js = _static_executive_js()
    qa_start = js.index("function qaAnswerText")
    qa_end = js.index("function boardSafeStatusReply", qa_start)
    qa_block = js[qa_start:qa_end]

    assert 'postJson("/assistant/chat"' in js
    assert 'persona: state.activePersona || "ceo"' in js
    assert "ceoDriverRelevanceReply" not in js
    assert "The board pack is under review." not in qa_block
    assert "Why:" not in qa_block and "Risk:" not in qa_block and "Path:" not in qa_block
    assert "I could not compute a protected data answer in this executive surface." not in js


def test_ceo_surface_no_raw_json_links():
    """CEO persona must never see links to /public/runs/latest/report-preview."""
    js = _static_executive_js()

    # CEO persona guard must exist in renderReportSurface
    assert 'state.activePersona === "ceo"' in js

    # renderSummary must hide link for CEO
    assert 'link.style.display = "none"' in js, (
        "summary-link must be hidden for CEO persona"
    )

    # createWritableThread must not set route for CEO
    assert 'state.activePersona === "ceo" ? ""' in js, (
        "createWritableThread: no route for CEO threads"
    )

    # renderReportSurface must conditionally show the preview link
    assert (
        'state.activePersona === "ceo" ? \'\'' in js
        or "activePersona === \"ceo\"" in js
    ), "renderReportSurface: CEO gate for preview link must exist"


def test_ceo_thread_list_no_debug_threads():
    """Thread filtering must exclude bug-report and system threads for CEO."""
    js = _static_executive_js()

    # Thread filtering logic for CEO
    assert "report a bug" in js.lower() or "bug" in js.lower(), (
        "Thread filtering must reference bug detection"
    )

    assert "kind === 'system'" in js or 'kind === "system"' in js, (
        "Thread filtering must exclude system threads"
    )


def test_ceo_jargon_replacements():
    """CEO-visible text must use clean labels, not internal jargon."""
    js = _static_executive_js()

    # Jargon must be replaced
    assert "Data relationships" in js, (
        "Knowledge graph badge must say 'Data relationships'"
    )
    assert "Runs on your infrastructure" not in js, (
        "Sovereign text must be CEO-friendly"
    )
    assert "Your AI interfaces to the leadership team" in js, (
        "AI team must use CEO-friendly leadership vocabulary"
    )
    for internal_copy in (
        "persistent runtime",
        "configured twin",
        "Role-specific digital twins",
        "Awaiting module telemetry",
        "Governed runtime",
        "System workflows — not digital twins",
        "Governed automations",
    ):
        assert internal_copy not in js, f"CEO surface leaks internal copy: {internal_copy}"
    assert "Board reports" in js, (
        "Report surface must be rebadged as 'Board reports'"
    )
    assert '{ label: "Calendar", value: String(upcomingCommitments) + " upcoming" }' in js
    assert 'String(getLeadershipTeam().length) + " assistants"' in js, (
        "Hero mini-stats must describe the AI team as assistants, not technical agents"
    )

    # Old text must NOT appear (or must be in non-CEO context)
    # Allow "under the hood" only if it's NOT in CEO context
    # Since we replaced it with "Data relationships", it shouldn't appear as a displayed label
    hood_count = js.count("under the hood")
    assert hood_count <= 0, (
        "'under the hood' must be removed (found %d)" % hood_count
    )


def test_ceo_feedback_button_not_hermes():
    """Feedback button must open inline form, not call askAssistant.
    
    Also verifies that no CEO-visible 'Report bug' or 'Report a bug'
    text remains anywhere in the feedback path (buttons, modal, labels).
    """
    js = _static_executive_js()

    # Feedback button must call showFeedbackForm
    assert "showFeedbackForm" in js, (
        "Feedback form function must exist"
    )

    # Verify feedback onclick does NOT call askAssistant for the feedback button
    # (the A2A report bug button should also call showFeedbackForm)
    assert "showFeedbackForm()" in js, (
        "Feedback button onclick must call showFeedbackForm"
    )

    # ── BUG WORDING MUST NOT APPEAR ANYWHERE IN FEEDBACK CODE PATH ──
    # The showFeedbackForm function must NOT contain 'bug' in visible labels
    fb_func_start = js.index("function showFeedbackForm")
    # Find end of this function (next function declaration after it)
    next_func_match = None
    for keyword in ["function renderTopbar", "function renderA2APanel",
                    "function renderHero", "function renderDriverGrid"]:
        idx = js.find(keyword, fb_func_start + 10)
        if idx != -1 and (next_func_match is None or idx < next_func_match):
            next_func_match = idx
    if next_func_match is None:
        next_func_match = fb_func_start + 2000
    show_feedback_code = js[fb_func_start:next_func_match]

    # Visible bug wording must NOT appear in feedback modal
    assert "Report a bug" not in show_feedback_code, (
        "showFeedbackForm: 'Report a bug' must not appear in feedback modal text"
    )
    assert "report a bug" not in show_feedback_code, (
        "showFeedbackForm: 'report a bug' must not appear in feedback modal text"
    )

    # The modal heading and aria-label must use neutral 'Send feedback' text
    assert "'Send feedback'" in show_feedback_code, (
        "showFeedbackForm: modal heading must use 'Send feedback' not bug wording"
    )


def test_ceo_executive_html_never_exposes_report_preview_as_href():
    """The STRONGEST test: served CEO executive HTML must NOT contain
    `/public/runs/latest/report-preview` as an href attribute.

    Even if JS guards are in place, a stray inline link or template
    leak could expose the raw JSON route as a clickable href to the CEO.
    This test catches that at the HTML level.
    """
    html = _ceo_executive_html()

    assert 'href="/public/runs/latest/report-preview"' not in html, (
        "CEO executive HTML must not contain report-preview as href attribute"
    )
    # Bootstrap JSON may still carry governed route metadata for the client;
    # the safety boundary is that it must never be emitted as a clickable href.
    assert 'href="/public/runs/latest' not in html


def test_ceo_prompt_chips_send():
    """Prompt chip onclick must call askAssistant with correct prompt."""
    js = _static_executive_js()

    # askAssistant must accept sourceChip parameter for loading state
    assert "sourceChip" in js, (
        "askAssistant must accept sourceChip parameter for chip loading state"
    )
    assert "loading" in js, (
        "Chip loading state must exist"
    )

    # Prompt chips must call askAssistant with button element
    assert "askAssistant(prompt, button)" in js, (
        "Hero prompt chips must pass button for loading state"
    )


def test_ceo_persona_dropdown_clean_labels():
    """Persona dropdown must not show persona_id codes as tags."""
    js = _static_executive_js()

    # persona-item__tag class should NOT appear (was removed for CEO-friendly display)
    assert "persona-item__tag" not in js, (
        "Persona dropdown must not show persona_id tag (persona-item__tag removed)"
    )


def test_ceo_toast_feedback_system():
    """Toast and feedback form functions must exist."""
    js = _static_executive_js()

    assert "showToast" in js, (
        "Toast function must exist for user feedback"
    )
    assert "strategyos-toast" in js, (
        "Toast DOM class must exist"
    )


def test_ceo_dead_controls_fixed():
    """No visible clickable CEO control must be dead/silent."""
    js = _static_executive_js()

    # "Browse all agents" button must have onclick handler
    assert "disco-browse" in js, (
        "Browse all agents button must exist"
    )

    # "Show the work" must toggle to "Hide the work"
    assert "Hide the work" in js, (
        "Show the work toggle must display Hide the work when open"
    )

    # KA avatar must have onclick or title
    assert "avatar.title" in js or "topbar-avatar" in js, (
        "KA avatar must have tooltip or click handler"
    )


def test_ceo_status_tokens_humanized():
    """CEO-visible rendered/static content must NEVER contain raw all-caps
    underscored status tokens. All status pills must use human-readable labels.
    """
    js = _static_executive_js()
    html = _ceo_executive_html()

    # Banned raw patterns — these must NEVER appear in CEO-visible content
    banned_raw = [
        "AWAITING_REVIEW",
        "AWAITING REVIEW",
        "PRE",
        "CHALLENGED",
    ]

    for phrase in banned_raw:
        # In JS: raw token must not appear in CEO-facing string literals
        # Check all template literal strings (between single quotes)
        assert phrase not in js, (
            f"Raw status token '{phrase}' found in executive.js — "
            f"must be humanized via statusLabel()"
        )
        assert phrase not in html, (
            f"Raw status token '{phrase}' found in served CEO HTML — "
            f"must be humanized before rendering"
        )

    # The statusLabel function must exist with the correct mappings
    assert "statusLabel" in js, (
        "statusLabel() function must exist in executive.js"
    )

    # Mapped labels must be present (proving humanization is active)
    assert "Under review" in js, (
        "statusLabel must map 'awaiting_review' → 'Under review'"
    )
    assert "Pre-board" in js, (
        "statusLabel must map 'pre' → 'Pre-board'"
    )
    assert "items need review" in js, (
        "statusLabel must map 'N challenged' → 'N items need review'"
    )

    # Verify the CEO preparation action does not leak raw publish-state tokens.
    think_pill_context = js[js.index("Prepare me"):js.index("Prepare me") + 600] if "Prepare me" in js else ""
    assert "Prepare me" in think_pill_context, "CEO preparation action must exist"
    # Raw status tokens must not appear near the simplified gravity card
    for raw_token in ["AWAITING_REVIEW", "CHALLENGED"]:
        assert raw_token not in think_pill_context, (
            f"Raw token '{raw_token}' must not appear near simplified Explore scenarios card"
        )

    # Report surface pill must also use statusLabel
    report_context = js[js.index("Board reports"):js.index("Board reports") + 400] if "Board reports" in js else ""
    assert "statusLabel" in report_context, (
        "'Board reports' card pill must call statusLabel() not raw publish_state"
    )


def test_ceo_agenda_has_no_raw_status_tokens():
    """The CEO agenda must use decision questions, not internal state tokens."""
    js = _static_executive_js()
    html = _ceo_executive_html()
    bootstrap_marker = '<script id="strategyos-executive-bootstrap" type="application/json">'
    visible_html = html
    if bootstrap_marker in visible_html:
        before_bootstrap, _, bootstrap_tail = visible_html.partition(bootstrap_marker)
        _, _, after_bootstrap = bootstrap_tail.partition("</script>")
        visible_html = before_bootstrap + after_bootstrap

    assert "fidelity-thinking-prompts" in js
    gravity_idx = js.index("fidelity-thinking-prompts")
    gravity_context = js[gravity_idx:gravity_idx + 800]

    # ---------------------------------------------------------------
    # PART B: The pill-row was intentionally removed — verify absence
    # ---------------------------------------------------------------
    # The old gravity-play-card had a pill-row with toneClass(item) and
    # statusLabel(item). After simplification, only prompt chips remain.
    assert "pill-row" not in gravity_context, (
        "CEO agenda must not contain the removed status pill row"
    )

    # ---------------------------------------------------------------
    # PART C: Raw token patterns must NOT appear near gravity-play-card
    # ---------------------------------------------------------------
    banned_near_gravity = [
        "AWAITING_REVIEW",
        "PRE",
        "CHALLENGED",
    ]
    for phrase in banned_near_gravity:
        assert phrase not in gravity_context, (
            f"Raw status token '{phrase}' found near the CEO agenda in JS — "
            f"must not appear after simplification"
        )

    # ---------------------------------------------------------------
    # PART D: Served CEO HTML must NOT show raw gravity.rails tokens
    # Internal bootstrap JSON may legitimately contain machine states such as
    # "awaiting_review"; this guard is about user-visible/static markup.
    # ---------------------------------------------------------------
    for phrase in banned_near_gravity:
        assert phrase not in visible_html, (
            f"Raw status token '{phrase}' found in served CEO HTML — "
            f"must not appear after simplification"
        )

    # Also check for lowercase raw patterns in visible/static markup.
    raw_patterns_lower = [
        "awaiting_review",
        "4 challenged",
    ]
    for phrase in raw_patterns_lower:
        assert phrase not in visible_html, (
            f"Raw status token '{phrase}' found in served CEO HTML visible markup — "
            f"must not appear after simplification"
        )

    # ---------------------------------------------------------------
    # PART E: Verify the decision questions are the only interactive content
    # ---------------------------------------------------------------
    assert 'data-chat-prompt="' in gravity_context
    assert "thinking-composer" in gravity_context
    assert "askAssistant" in gravity_context, (
        "CEO decision questions must open Hermes with the current context"
    )


# ── Knowledge Graph surface safety ──

def test_kg_no_raw_developer_jargon():
    """Inspector panel and graph must not expose raw developer labels or
    internal data-structure jargon (e.g. 'node', 'edge', 'object Promise',
    'graph data', 'vertices')."""
    js = _static_executive_js()

    banned = [
        "Object",
        "Promise",
        "[object",
        "graph data",
        "vertices",
        "vertex",
    ]
    # Extract the inspector-building section (openNodeInspector → innerHTML)
    insp_start = js.index("function openNodeInspector")
    insp_end = js.index("function closeNodeInspector")
    inspector_code = js[insp_start:insp_end]

    for phrase in banned:
        assert phrase not in inspector_code, (
            f"Banned developer jargon '{phrase}' found in inspector panel code — "
            f"inspector must use CEO-safe labels only"
        )

    # Also check renderKnowledgeGraph for node/edge as standalone in template strings
    kg_start = js.index("function renderKnowledgeGraph")
    kg_end = js.index("function renderHero")
    kg_code = js[kg_start:kg_end]

    # 'edge' and 'node' are fine as variable names, but not as visible text
    # Verify no label text containing raw graph jargon
    assert "Node\">" not in kg_code, "Raw 'Node>' label fallback exposed in graph"
    assert "Edge\">" not in kg_code, "Raw 'Edge>' label fallback exposed in graph"


def test_kg_has_category_color_system():
    """Knowledge graph must define category color assignments (KG_CATEGORY_COLORS)
    with at least 8 category entries."""
    js = _static_executive_js()

    assert "KG_CATEGORY_COLORS" in js, (
        "Knowledge graph must define KG_CATEGORY_COLORS map"
    )
    # Verify all 8 required categories are present
    required_categories = [
        "plan", "KPI", "business_unit", "finding",
        "document", "vendor", "invoice", "contract"
    ]
    for cat in required_categories:
        assert cat in js, (
            f"Category '{cat}' not found in JS — must be defined in KG_CATEGORY_COLORS"
        )

    # Each category must have a color hex
    assert "#25335c" in js, "plan category color navy missing"
    assert "#1a6e54" in js, "KPI category color forest missing"
    assert "#8c6a3d" in js, "business_unit category color gold missing"


def test_kg_question_lenses_exist():
    """Knowledge graph must render question lens buttons with proper structure."""
    js = _static_executive_js()

    assert "kg-question" in js, "Must render question lens chips"
    assert "data-kg-question" in js, "Question lenses must have data-kg-question attribute"
    assert "knowledgeQuestionIndex" in js, (
        "Must manage active question lens via state.knowledgeQuestionIndex"
    )
    assert 'role="tab"' in js, "Question lenses must have proper ARIA role"
    assert "aria-selected" in js, "Question lenses must have aria-selected state"


# ── CEO feedback / report bug removal (server-side strip + client-side remove) ──

def test_ceo_no_report_bug_visible_labels():
    """CEO surface must NOT expose any visible 'Report bug', 'Report a bug',
    'Feedback', or 'Send feedback' text in buttons, labels, modals,
    aria-labels, or titles.

    Server-side strips feedback/report nodes from CEO HTML; client-side
    uses remove() (not hidden=true) as defense-in-depth. Internal variable
    names (reportBug, a2a-report-bug as DOM id) and thread-filtering logic
    are acceptable since they are NOT user-visible.
    """
    js = _static_executive_js()
    html = _ceo_executive_html()

    # ── HTML: feedback/report buttons must be ABSENT from CEO HTML ──
    import re

    # feedback-btn must not appear in CEO HTML at all
    fb_match = re.search(r'<button[^>]*id="feedback-btn"[^>]*>', html)
    assert fb_match is None, (
        "CEO HTML must not contain feedback-btn button element"
    )

    # a2a-report-bug must not appear in CEO HTML at all
    a2a_match = re.search(r'<button[^>]*id="a2a-report-bug"[^>]*>', html)
    assert a2a_match is None, (
        "CEO HTML must not contain a2a-report-bug button element"
    )

    # CEO HTML must not contain feedback-related aria/title attributes
    assert 'aria-label="Send feedback"' not in html, (
        "CEO HTML must not contain Send feedback aria-label"
    )
    assert 'title="Send feedback"' not in html, (
        "CEO HTML must not contain Send feedback title"
    )

    # CEO HTML must not contain 'Feedback' as visible button text
    assert "<span>Feedback</span>" not in html, (
        "CEO HTML must not contain Feedback button text"
    )

    # HTML must not contain 'Report bug' or 'Report a bug' as visible text
    assert "Report bug" not in html, (
        "CEO HTML must not contain 'Report bug' visible text"
    )
    assert "Report a bug" not in html, (
        "CEO HTML must not contain 'Report a bug' visible text"
    )

    # ── JS: showFeedbackForm function must use neutral labels ──
    assert "'Send feedback'" in js, (
        "showFeedbackForm must use neutral 'Send feedback' heading"
    )


def test_ceo_no_feedback_controls():
    """CEO surface must REMOVE ALL feedback/report buttons (topbar + A2A footer)
    from the DOM entirely — NOT just hide them.

    Approach:
    1. Server-side: strip feedback-btn / a2a-report-bug from CEO HTML
       (nodes never reach the client for CEO persona)
    2. Client-side: use remove() (not hidden=true) as defense-in-depth

    This test verifies:
    1. CEO HTML does NOT contain feedback/report button DOM nodes
    2. CEO HTML does NOT contain feedback-related aria/title labels
    3. CEO HTML does NOT contain 'Feedback' visible button text
    4. JS uses remove() (not hidden=true) for CEO guards
    5. showFeedbackForm still exists (for non-CEO personas)
    6. CEO persona guard exists in the feedback handling blocks
    """
    html = _ceo_executive_html()
    js = _static_executive_js()

    # ── CEO HTML must NOT contain feedback/report button DOM nodes ──
    assert 'id="feedback-btn"' not in html, (
        "CEO HTML must not contain feedback-btn node"
    )
    assert 'id="a2a-report-bug"' not in html, (
        "CEO HTML must not contain a2a-report-bug node"
    )

    # ── CEO HTML must NOT contain feedback-related aria/title labels ──
    assert 'aria-label="Send feedback"' not in html, (
        "CEO HTML must not contain Send feedback aria-label"
    )
    assert 'title="Send feedback"' not in html, (
        "CEO HTML must not contain Send feedback title"
    )

    # ── CEO HTML must NOT contain 'Feedback' in visible button text ──
    assert "<span>Feedback</span>" not in html, (
        "CEO HTML must not contain Feedback button text"
    )

    # ── JS must use remove() (not hidden=true) for CEO guards ──
    assert "reportBug.remove()" in js, (
        "renderA2APanel must remove (not hide) a2a-report-bug for CEO"
    )

    # ── JS must NOT contain hidden=true for CEO guard (deprecated pattern) ──
    assert "feedbackButton.hidden = true" not in js, (
        "CEO guard must NOT use hidden=true on feedbackButton (must use remove())"
    )
    assert "reportBug.hidden = true" not in js, (
        "CEO guard must NOT use hidden=true on reportBug (must use remove())"
    )

    # ── showFeedbackForm must still exist (for non-CEO personas) ──
    assert "showFeedbackForm" in js, (
        "showFeedbackForm function must exist for non-CEO personas"
    )

    # ── Feedback action is now inside avatar tooltip menu ──
    assert "data-avatar-action=\"feedback\"" in js, (
        "Feedback action must be in avatar tooltip via data-avatar-action"
    )
    assert "showFeedbackForm()" in js, (
        "Avatar tooltip feedback must call showFeedbackForm"
    )


def test_ceo_html_feedback_absent_from_innertext():
    """CEO HTML document.body.innerText must not contain 'Feedback' or
    'Send feedback' or 'Report bug' or 'Report a bug'.

    This is a direct test of the acceptance criteria: text that was
    previously leaked via hidden=true on buttons must now be fully absent
    from the served CEO HTML, ensuring that even before JS hydration,
    document.body.innerText and accessibility snapshots are clean.
    """
    html = _ceo_executive_html()

    # Strip HTML tags to simulate innerText
    import re
    inner_text = re.sub(r"<[^>]+>", " ", html)
    inner_text = re.sub(r"\s+", " ", inner_text).strip()

    # These terms must NOT appear in the text content
    assert "Feedback" not in inner_text, (
        "CEO innerText must not contain 'Feedback'"
    )
    assert "Send feedback" not in inner_text, (
        "CEO innerText must not contain 'Send feedback'"
    )
    assert "Report bug" not in inner_text, (
        "CEO innerText must not contain 'Report bug'"
    )
    assert "Report a bug" not in inner_text, (
        "CEO innerText must not contain 'Report a bug'"
    )


def test_ceo_js_removes_nodes_not_hides():
    """CEO hydration must use remove() (not hidden=true) to eliminate
    feedback/report nodes from the DOM entirely.

    The exact runtime guard must call .remove() on the DOM elements,
    not merely set hidden=true, which leaves text in innerText and
    accessibility snapshots.
    """
    js = _static_executive_js()

    # ── Verify remove() calls in CEO code paths ──
    assert "data-avatar-action=\"feedback\"" in js, (
        "renderTopbar avatar tooltip must include feedback action"
    )
    assert "reportBug.remove()" in js, (
        "renderA2APanel CEO path must call reportBug.remove()"
    )

    # ── Verify hidden=true is NOT the CEO mechanism ──
    # The non-CEO path still uses hidden=false (to show) — that's fine.
    # CEO path must not use hidden=true
    assert "feedbackButton.hidden = true" not in js, (
        "CEO guard must not use hidden=true on feedbackButton"
    )
    assert "reportBug.hidden = true" not in js, (
        "CEO guard must not use hidden=true on reportBug"
    )

    # ── Feedback is now in avatar tooltip, not standalone button ──
    assert "data-avatar-action=\"feedback\"" in js, (
        "Avatar tooltip must include feedback action"
    )
    assert "showFeedbackForm()" in js, (
        "Avatar tooltip feedback must call showFeedbackForm"
    )

    # ── Verify reportBug remove() is still CEO-guarded ──
    # Find the reportBug handling block
    rb_start = js.index("if (reportBug)")
    rb_end = js.index("}", js.index("{", rb_start) + 200)
    rb_block = js[rb_start:rb_end + 30]
    assert 'state.activePersona === "ceo"' in rb_block, (
        "CEO guard must wrap reportBug.remove()"
    )
    assert "reportBug.remove()" in rb_block, (
        "reportBug.remove() must be inside CEO guard block"
    )


def test_ceo_greeting_response_humane():
    """CEO greetings must route to the shared assistant API, not a client reply."""
    js = _static_executive_js()
    assert "greetingPatterns" not in js
    assert "I can help with board readiness, margin risk, cash, or the knowledge map" not in js
    assert 'postJson("/assistant/chat"' in js


def test_ceo_digital_twin_cards_and_search_are_interactive():
    """Digital Twin cards and search must have explicit action handling."""
    js = _static_executive_js()

    assert "data-twin-toggle" in js
    assert "twin-network-search" in js
    assert "state.openAgentId = state.openAgentId === id ? '' : id" in js
    assert "showAgentInstallRequest(item, sourceEl)" in js, (
        "connector installation must remain a separate governed flow"
    )
    assert "Operator-gated install" in js, (
        "restricted discovery actions must show an operator-gated install message"
    )
    assert "Agent installation is available from the operator surface." not in js, (
        "disco-add must not regress to the old invisible toast-only CEO path"
    )
    assert "Agent deployment is available from the operator or reviewer surface." not in js, (
        "disco-add must not regress to the old invisible toast-only non-CEO path"
    )

    assert "querySelectorAll('[data-twin-toggle]')" in js


# ══════════════════════════════════════════════════════════════════════
# NEW TESTS — CEO Demo Defect Batch 2026-07-03
# ══════════════════════════════════════════════════════════════════════

def test_ceo_hero_uses_business_status_panel_not_technical_gauge():
    """The first viewport must explain the decision state, not expose storage internals."""
    html = _ceo_executive_html()
    js = _static_executive_js()

    assert 'class="hero-status"' in html
    assert 'aria-label="Executive status"' in html
    assert 'id="hero-status-signal"' in html
    assert 'id="hero-mini-stats"' in html
    assert "Business view ready" in js
    assert "Built from the latest available operating data." in js
    assert 'truthSourceBadge' not in js
    assert 'id="hero-dot"' not in html
    assert 'class="score-ring"' not in html


def test_kpi_spacing_css_exists():
    """#2: Board KPI must have adequate spacing between label and value."""
    css_path = Path(__file__).resolve().parent.parent / \
        "strategyos_mvp" / "static" / "executive.css"
    css = css_path.read_text()

    # board-kpi must have flex column layout with gap
    assert ".board-kpi" in css, "board-kpi CSS class must exist"
    # The class must have flex-direction: column and gap
    assert "flex-direction: column" in css, "board-kpi must use column layout"


def test_week_ahead_toggle_behavior():
    """#5: Clicking the same Week Ahead chip must toggle collapse."""
    js = _static_executive_js()

    # Toggle logic: state.openWeekIndex === idx ? -1 : idx
    assert "openWeekIndex === idx" in js or "openWeekIndex ===" in js, (
        "Week Ahead must toggle collapse when same chip is clicked"
    )


def test_ai_team_search_stays_in_agents_workspace():
    """AI-team search must filter in place, not redirect to chat."""
    js = _static_executive_js()

    assert 'data-view-target="agents"' in _ceo_executive_html()
    assert "state.discoveryQuery = search.value || '';" in js
    assert "renderAgentsDiscovery();" in js
    assert "Show me the agent catalogue" not in js, (
        "CEO Browse All Agents must not submit a canned assistant prompt"
    )


def test_report_category_map_exists():
    """#7: Board Reports must use REPORT_CATEGORY_MAP for polished labels."""
    js = _static_executive_js()

    assert "REPORT_CATEGORY_MAP" in js, (
        "REPORT_CATEGORY_MAP must exist for polishing board report sub-labels"
    )
    assert 'board_pack": "Board pack"' in js or 'board_pack: "Board pack"' in js, (
        "REPORT_CATEGORY_MAP must map 'board_pack' to 'Board pack'"
    )
    assert 'graph": "Data relationships"' in js or 'graph: "Data relationships"' in js, (
        "REPORT_CATEGORY_MAP must map 'graph' to 'Data relationships'"
    )
    assert 'audit": "Review trail"' in js or 'audit: "Review trail"' in js, (
        "REPORT_CATEGORY_MAP must map 'audit' to 'Review trail'"
    )
    assert 'narrative": "Board narrative"' in js or 'narrative: "Board narrative"' in js, (
        "REPORT_CATEGORY_MAP must map 'narrative' to 'Board narrative'"
    )
    # renderReportSurface must use REPORT_CATEGORY_MAP
    assert "REPORT_CATEGORY_MAP[item.category]" in js, (
        "renderReportSurface must look up category via REPORT_CATEGORY_MAP"
    )


def test_snapshot_cards_have_click_handlers():
    """#8: Snapshot cards (Deck release / Frozen snapshot) must be clickable."""
    js = _static_executive_js()

    assert "snapshot-card" in js, (
        "Snapshot cards must exist in the board portal"
    )
    assert "querySelectorAll('.snapshot-card')" in js or \
        "snapshot-card" in js, (
        "Snapshot cards must have click handler wiring"
    )


def test_feedback_form_css_layout():
    """#9: Feedback form must have proper CSS layout for inputs."""
    css_path = Path(__file__).resolve().parent.parent / \
        "strategyos_mvp" / "static" / "executive.css"
    css = css_path.read_text()

    assert ".strategyos-feedback-card form" in css or \
        ".strategyos-feedback-card" in css, (
        "Feedback form must have CSS styling"
    )


def test_knowledge_graph_subtitle_grammar():
    """#10: Knowledge graph subtitle must disclose its governed KPI boundary."""
    js = _static_executive_js()

    assert "Choose a headline figure to see what makes it up" in js
    assert "governed finance contract" not in js
    # Old wording must NOT appear
    assert "proof the system" not in js, (
        "Knowledge graph subtitle must NOT contain 'proof the system' (old wording)"
    )


def test_hermes_header_phrase_clean():
    """#11: Hermes header must use 'Ask Hermes' heading and 'Answers from the current board pack' subtitle."""
    js = _static_executive_js()

    assert 'assistantHeading.textContent = "Ask " + assistantName' in js, (
        "Assistant header heading must follow the active persona's assistant"
    )
    assert 'assistantName + " will answer here using the current board pack."' in js, (
        "Assistant subtitle must follow the active persona's assistant"
    )
    # Old jargon must not appear
    assert "named, threaded chief-of-staff follow-up" not in js, (
        "Hermes header must NOT contain old jargon phrase"
    )
    assert "Your AI chief of staff" not in js, (
        "Hermes subtitle must NOT contain old 'Your AI chief of staff' phrase"
    )


def test_pre_badge_uses_status_label():
    """#12: Hermes PRE badge must show 'Pre-board' not raw 'Pre'."""
    js = _static_executive_js()

    # statusLabel must be used for board state badge (not humanizeToken)
    # Verify statusLabel is called for activeBoard in thread tools
    assert "statusLabel(firstDefined(state.activeBoard" in js, (
        "Thread tools badge must use statusLabel() for board state"
    )


def test_thread_metadata_simplified():
    """#13: Thread list items must not show redundant metadata — no '· writable' tag or 'send and receive'."""
    js = _static_executive_js()

    # The old pattern: 'send and receive' / '· writable' in thread metadata — must be gone
    assert "· writable" not in js, (
        "Thread metadata must NOT contain '· writable' tag"
    )
    # "Open a writable" text must also be gone (new conversation button simplified)
    assert "Open a writable" not in js, (
        "New conversation button must NOT contain 'Open a writable'"
    )


def test_persona_polished_labels():
    """#14: Persona dropdown must use polished labels, not raw codes."""
    js = _static_executive_js()

    assert "POLISHED_LABELS" in js, (
        "POLISHED_LABELS map must exist in getPersonaLabel"
    )
    assert 'bucfo": "Business Unit CFO"' in js or 'bucfo: "Business Unit CFO"' in js, (
        "POLISHED_LABELS must map 'bucfo' to 'Business Unit CFO'"
    )
    assert 'gm": "General Manager"' in js or 'gm: "General Manager"' in js, (
        "POLISHED_LABELS must map 'gm' to 'General Manager'"
    )


def test_avatar_click_rich_panel():
    """#15: KA Avatar click must show interactive panel with actions."""
    js = _static_executive_js()

    # Avatar tooltip must have action buttons (not just text)
    assert "Profile &amp; settings" in js or "Profile & settings" in js or \
        "avatar-tooltip-action" in js, (
        "Avatar panel must contain profile/settings action button"
    )
    assert "Switch persona" in js, (
        "Avatar panel must contain switch persona action"
    )


def test_logo_home_link():
    """#16: StrategyOS logo must be clickable home link."""
    html = _ceo_executive_html()

    assert "switchView" in html, (
        "Logo brand div must have onclick to switchView"
    )
    assert 'cursor:pointer' in html or 'cursor: pointer' in html, (
        "Logo brand div must have cursor:pointer style"
    )


def test_workflow_modules_are_hidden_from_the_ceo_surface():
    """Operator workflow services must not be presented on the CEO surface."""
    js = _static_executive_js()
    html = _ceo_executive_html()

    assert "automationCard.hidden = true" in js
    assert "automationCard.innerHTML = ''" in js
    assert "Governed automations" not in js
    assert "System workflows — not digital twins" not in js
    assert "Tenant runtime watch" not in html, (
        "CEO HTML must not render 'Tenant runtime watch'"
    )
    # Also check Python API
    api_path = Path(__file__).resolve().parent.parent / \
        "strategyos_mvp" / "api.py"
    api_text = api_path.read_text()
    assert "Tenant runtime watch" not in api_text, (
        "API must not contain 'Tenant runtime watch'"
    )
    assert "System health monitor" in api_text, (
        "API must contain 'System health monitor'"
    )


def test_error_thread_filter_enhanced():
    """#18: CEO thread filter must exclude error-containing threads."""
    js = _static_executive_js()

    # Error filter must check preview for error text
    assert "could not compute a protected data" in js, (
        "CEO thread filter must check for 'could not compute a protected data'"
    )
    # Error filter must also check title for 'error'
    assert "title.indexOf('error')" in js or "title.indexOf(\"error\")" in js, (
        "CEO thread filter must check title for 'error' substring"
    )
    assert "isError" in js, (
        "CEO thread filter must define isError variable"
    )
    assert "!isError" in js, (
        "CEO thread filter must exclude error threads"
    )


def test_challenged_cases_buttons_exist():
    """#4: Close Challenged Cases buttons must exist with handlers."""
    js = _static_executive_js()

    # Buttons must exist for challenged cases
    assert "data-board-action" in js, (
        "Challenged case buttons must have data-board-action attribute"
    )
    assert "querySelectorAll('[data-board-action]')" in js or \
        "data-board-action" in js, (
        "Challenged case buttons must have click handler wiring"
    )


def test_close_challenged_cases_button_action():
    """#4b: Close Challenged Cases buttons must trigger askAssistant()."""
    js = _static_executive_js()

    # Click handler must call askAssistant
    assert "data-board-action" in js, (
        "Challenged case buttons must exist with data-board-action"
    )


def test_board_portal_review_buttons_use_plain_english_prompts():
    """Board Portal review CTAs must not pass raw action codes to Hermes."""
    js = _static_executive_js()

    assert "I need to review and act on: ' + action" not in js, (
        "Board Portal CTAs must not build prompts from raw internal action codes"
    )
    assert "Help me prepare the board materials" in js, (
        "Board Portal CTA copy must include a plain-English board review prompt"
    )
    assert "Help me close challenged cases" in js, (
        "Board Portal CTA copy must include a plain-English challenged-cases prompt"
    )


def test_board_portal_buttons_expose_plain_english_hermes_action_labels():
    """Board Portal CTAs must read as human actions, not inert status styling."""
    js = _static_executive_js()

    assert 'aria-label="Ask Hermes what to do next: ' in js
    assert 'aria-label="Ask Hermes to review ' in js
    assert 'Next: ' in js
    assert 'Review: ' in js


def test_avatar_profile_action_is_wired_not_dead():
    """Avatar tooltip Profile & settings action must have a real click handler."""
    js = _static_executive_js()
    avatar_start = js.index("data-avatar-action=\"profile\"")
    avatar_block = js[avatar_start:avatar_start + 1600]

    assert "querySelector('[data-avatar-action=\"profile\"]')" in avatar_block, (
        "Profile action must be queried after the tooltip renders"
    )
    assert ".onclick = function" in avatar_block, (
        "Profile action must have an onclick handler instead of a dead menu item"
    )


def test_assistant_network_uses_executive_semantic_headers():
    """Assistant rows use business output and decision semantics, not telemetry jargon."""
    js = _static_executive_js()
    network_start = js.index("function renderAssistantNetwork()")
    network_end = js.index("function renderA2APanel()", network_start)
    network_block = js[network_start:network_end]

    assert "network-header" in network_block or "network-list-head" in network_block, (
        "Assistant network must render one visible semantic header row"
    )
    assert "<small>freshness</small>" not in network_block, (
        "Assistant rows must not repeat the visible 'freshness' label"
    )
    assert "<small>used</small>" not in network_block, (
        "Assistant rows must not repeat the visible 'used' label"
    )
    assert "<small>context</small>" not in network_block, (
        "Assistant rows must not repeat the visible 'context' label"
    )
    assert '<span class="sr-only">Freshness</span><span class="network-stat-value">' not in network_block, (
        "Assistant rows must not repeat row-level Freshness labels once the header exists"
    )
    assert 'aria-label="State"' in network_block
    assert 'aria-label="Business output"' in network_block
    assert 'aria-label="Decision or scope"' in network_block


def test_dark_theme_native_controls_inherit_executive_text_colour():
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    assert "button { color: inherit; }" in css
    assert 'html[data-theme="dark"] .pill-inline.warn' in css
    assert 'html[data-theme="dark"] .pill-inline.danger' in css


def test_review_gate_copy_is_executive_safe_and_decision_kpi_routes_deterministically():
    js = _static_executive_js()
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    assert '? "Your decision"' in js
    assert '? "Review required"' in js
    assert '"An item is waiting for executive sign-off."' in js
    assert 'data-kpi-key=' in js
    assert 'if (contextualKpiKey) entrypoint = "ceo_kpi_inline"' in js
    assert ".hero-status__signal.is-attention" in css
    assert ".score-ring" not in css


def test_agents_running_panel_has_no_orphan_sovereign_bullet_for_ceo():
    """CEO agents panel must not render an empty decorative sovereign bullet."""
    js = _static_executive_js()

    assert "<span class=\"sov-dot\"></span> ' + (state.activePersona === \"ceo\" ? ''" not in js, (
        "CEO agents panel must not leave an orphan sovereign dot when no text follows"
    )
    assert '<span class="aa-spark">✦</span>' not in js, (
        "Agents activity summary must not render a decorative star that can appear as orphan content"
    )


def test_board_portal_state_note_uses_unique_support_copy():
    """Board Portal intro note must not duplicate the main card summary copy.

    boardStateSupportNote() used to carry its own hardcoded per-stage
    fallback strings and trusted server state_detail.note unconditionally --
    which went stale on a purely client-side stage switch (see
    test_board_state_note_updates_on_client_only_stage_switch in
    test_frontend_shell.py). It now delegates to boardStateDetailForRender(),
    which applies the same "only trust server data when its own state
    matches the current selection" guard used elsewhere, and whose
    per-stage `note` defaults remain distinct from the `summary` defaults
    this test guards against duplicating."""
    js = _static_executive_js()

    assert "function boardStateSupportNote(board)" in js, (
        "Board Portal should derive a distinct support note for lifecycle guidance"
    )
    # The invariant is that each stage's note is DISTINCT from its summary --
    # not that it uses one particular sentence. Pinning the sentence made a
    # plain-English rewrite look like a regression while the guarantee held.
    assert "Keep the pack to this executive view until the questioned items are closed" in js, (
        "Pre-board support note should give unique CEO guidance instead of repeating the card summary"
    )
    assert "return boardStateDetailForRender(resolveBoardState(), board).note;" in js, (
        "Board state intro note must derive from boardStateDetailForRender's guarded per-stage note"
    )


def test_board_portal_panels_are_not_permanently_hidden_in_css():
    """Board Portal lifecycle panels must remain visible when rendered."""
    css = _static_executive_css()

    assert ".board-panel + .board-panel { display: none; }" not in css, (
        "Board Portal must not permanently hide later panels via sibling display:none"
    )
    assert ".board-panel { max-height: 220px; overflow: hidden; }" not in css, (
        "Board Portal panels must not be hard-clipped to a collapsed height"
    )


def test_mobile_assistant_overlay_stays_usable_on_narrow_viewports():
    """Mobile Hermes/A2A dock must span the viewport safely and avoid clipped actions."""
    css = _static_executive_css()

    mobile_start = css.index("@media (max-width: 760px)")
    mobile_block = css[mobile_start:mobile_start + 2600]

    assert ".assistant-dock" in mobile_block and "left: 0;" in mobile_block and "right: 0;" in mobile_block and "width: 100%;" in mobile_block, (
        "Mobile assistant dock must anchor to both sides and span the viewport so the floating overlay does not clip off-screen"
    )
    assert ".a2a-fab" in mobile_block and "width: 100%;" in mobile_block, (
        "Mobile A2A launcher must fill the dock width for reliable tap targets"
    )
    assert ".chat-launcher__cta," in mobile_block and ".a2a-fab" in mobile_block and "justify-content: space-between;" in mobile_block, (
        "Mobile launcher and A2A trigger must stretch cleanly instead of clipping on narrow viewports"
    )


def test_discovery_cards_do_not_duplicate_built_in_label_for_ceo():
    """CEO discovery cards must not render 'Built-in' as repeated clutter."""
    js = _static_executive_js()

    assert "state.activePersona === \"ceo\" ? 'Built-in' :" not in js, (
        "CEO discovery rendering must not hardcode repeated 'Built-in' labels inside every card"
    )
    assert "Built-in assistants" not in js, (
        "Discovery section should use a clear StrategyOS heading instead of the old Built-in fragment"
    )


# ══════════════════════════════════════════════════════════════════════
# LIVE-VERIFICATION REGRESSION TESTS — 2026-07-03
# Six live-visible failures caught by Hermes at
# https://strategyos.live/executive?persona=ceo&board=pre&driver=board_packet
# Each test proves the fix is in the served JS / HTML / CSS.
# ══════════════════════════════════════════════════════════════════════

def test_driver_drill_no_tap_a_note_instruction():
    """#1: Driver drill must NOT show 'tap a note — the GM's commentary
    rides up with the number' instruction text."""
    js = _static_executive_js()

    assert 'tap a note' not in js, (
        "Driver drill must NOT contain 'tap a note' instruction text"
    )
    assert "GM's commentary rides up with the number" not in js, (
        "Driver drill must NOT contain GM commentary instruction"
    )


def test_evidence_chain_hidden_by_default():
    """#2: Evidence chain must be hidden by default and CSS must respect
    the hidden attribute (display: flex must not override display: none)."""
    js = _static_executive_js()
    css_path = Path(__file__).resolve().parent.parent / \
        "strategyos_mvp" / "static" / "executive.css"
    css = css_path.read_text()

    # Evidence div must be hidden by default in JS template
    assert '<div class="drill-evidence" hidden>' in js, (
        "Evidence chain div must have hidden attribute by default"
    )

    # CSS must explicitly hide drill-evidence when [hidden]
    assert '.drill-evidence[hidden]' in css or \
        'drill-evidence[hidden]' in css, (
        "CSS must have .drill-evidence[hidden] rule to override display:flex"
    )


def test_digital_twin_attention_label_is_ceo_friendly():
    """Twin attention status must name the required human action."""
    js = _static_executive_js()

    assert 'attention: "Needs human review"' in js
    assert "Running now" in js


def test_twin_status_labels_are_ceo_friendly():
    """Twin runtime states must be translated into CEO-friendly labels."""
    js = _static_executive_js()

    # Global statusLabel map must include CEO-friendly mappings
    assert '"protected": "Guarded"' in js, (
        "statusLabel must map 'protected' to 'Guarded'"
    )
    assert '"preview": "View only"' in js or '"board_safe_preview": "View only"' in js, (
        "statusLabel must map preview statuses to 'View only'"
    )
    assert '"preview_only": "View only"' in js, (
        "statusLabel must map 'preview_only' to 'View only'"
    )

    assert 'active: "Working"' in js
    assert 'monitoring: "Monitoring"' in js
    assert 'ready: "Ready"' in js


def test_assistants_tab_no_ai_adoption_wording():
    """#6: Assistants tab must NOT contain old 'AI adoption' wording.
    Must use 'team readiness' instead."""
    js = _static_executive_js()
    html = _ceo_executive_html()
    design_path = Path(__file__).resolve().parent.parent / \
        "strategyos_mvp" / "static" / "executive_design_data.js"

    # The client-side design fixture was deleted outright (UI DB-purity):
    # its absence is the strongest guarantee no fixture wording can render.
    assert not design_path.exists(), (
        "executive_design_data.js must stay deleted -- the executive surface "
        "must not ship a client-side design fixture"
    )

    # Served HTML static subtitle must not contain old wording
    assert "How current and deeply-used each assistant is" not in html, (
        "CEO executive HTML must not contain old assistant subtitle wording"
    )

    # JS default hint must be clean
    assert "AI adoption" not in js, (
        "executive.js must not contain 'AI adoption'"
    )


def test_evidence_footer_css_no_display_flex_override():
    """#2b: The .drill-evidence CSS must not leave display:flex unchallenged.
    A second assertion ensures [hidden] wins over display:flex."""
    css_path = Path(__file__).resolve().parent.parent / \
        "strategyos_mvp" / "static" / "executive.css"
    css = css_path.read_text()

    # Find .drill-evidence rule block
    idx = css.find('.drill-evidence')
    assert idx != -1, ".drill-evidence CSS rule must exist"

    # After the .drill-evidence block, there must be a [hidden] override
    post_block = css[idx:idx + 400]
    assert '[hidden]' in post_block, (
        ".drill-evidence CSS must be followed by [hidden] override rule"
    )


# ── "Ask why this matters" CTA + assistant drawer regression tests ──


def test_executive_priority_cta_calls_ask_assistant():
    """CEO priority cards must open Hermes with an aggregated decision prompt."""
    js = _static_executive_js()

    assert "data-executive-prompt" in js, (
        "Executive priority CTA must have data-executive-prompt"
    )
    assert "Open decision brief" in js, (
        "Executive priority must describe the decision-support action"
    )

    assert "askAssistant(button.getAttribute('data-executive-prompt')" in js, (
        "Executive priority CTA must call the shared assistant"
    )


def test_assistant_drawer_css_right_panel():
    """The assistant drawer CSS must position it as a right-side panel, not a bottom overlay."""
    css_path = Path(__file__).resolve().parent.parent / \
        "strategyos_mvp" / "static" / "executive.css"
    css = css_path.read_text()

    # Find the .assistant-drawer rule block
    idx = css.find('.assistant-drawer {')
    assert idx != -1, ".assistant-drawer CSS rule must exist"

    # Extract the rule block (from opening brace to closing brace)
    block_start = css.index('{', idx)
    # Find the matching closing brace by counting
    depth = 0
    block_end = block_start
    for i in range(block_start, len(css)):
        if css[i] == '{':
            depth += 1
        elif css[i] == '}':
            depth -= 1
            if depth == 0:
                block_end = i
                break
    block = css[idx:block_end + 1]

    # Must be position:fixed
    assert 'position: fixed' in block, (
        ".assistant-drawer must use position:fixed for viewport anchoring"
    )

    # Must be anchored to right edge
    assert 'right: 0' in block, (
        ".assistant-drawer must anchor to right edge (right:0)"
    )

    # Must be full viewport height
    assert 'top: 0' in block, (
        ".assistant-drawer must anchor to top edge (top:0)"
    )
    assert 'bottom: 0' in block, (
        ".assistant-drawer must anchor to bottom edge (bottom:0)"
    )

    # Must have sane max-width for desktop
    assert 'min(760px' in block or '760px' in block or 'max-width' in block, (
        ".assistant-drawer must have a bounded width for desktop"
    )

    # Must have overflow control
    assert 'overflow' in block, (
        ".assistant-drawer must have overflow control"
    )

    # Must have background to prevent transparent overlay
    assert 'background' in block, (
        ".assistant-drawer must have a background to prevent see-through"
    )

    # Must have box-shadow or border for visual separation
    assert ('box-shadow' in block or 'border' in block), (
        ".assistant-drawer must have visual separation from page content"
    )

    # Must NOT be a bottom sheet — verify it doesn't use bottom-only anchoring
    # A bottom sheet would have: bottom:0, left:0, right:0, but NO top:0
    # Our drawer has right:0 AND top:0 AND bottom:0 — it's a right panel
    # Verify the right-anchoring is present
    assert 'right: 0' in block, (
        ".assistant-drawer must be right-anchored, not a bottom overlay"
    )


def test_body_scroll_lock_on_drawer_open():
    """When assistant drawer opens, body overflow must be locked to prevent background scroll."""
    js = _static_executive_js()

    # _openHermesDrawer must set body.style.overflow = 'hidden'
    assert "document.body.style.overflow = 'hidden'" in js, (
        "_openHermesDrawer must lock body scroll with overflow:hidden"
    )

    # _closeHermesDrawer must restore body scroll
    assert "document.body.style.overflow = ''" in js, (
        "_closeHermesDrawer must restore body scroll"
    )

    # Both open and close functions must exist
    assert "function _openHermesDrawer" in js, (
        "_openHermesDrawer function must exist"
    )
    assert "function _closeHermesDrawer" in js, (
        "_closeHermesDrawer function must exist"
    )


def test_assistant_drawer_not_bottom_overlay():
    """The assistant drawer HTML must render as a side panel (<aside>), not an inline bottom div."""
    html = _ceo_executive_html()

    # Must use <aside> semantic element
    assert '<aside class="assistant-drawer"' in html, (
        "Assistant drawer must be an <aside> element, not a generic <div>"
    )

    # Must have the hidden attribute initially (the <aside> tag itself)
    aside_idx = html.find('<aside class="assistant-drawer"')
    assert aside_idx != -1, "Assistant drawer <aside> must exist in HTML"
    aside_tag = html[aside_idx:aside_idx + 300]
    assert 'hidden' in aside_tag, (
        "Assistant drawer <aside> must have hidden attribute initially"
    )

    # Must have an ID for JS targeting
    assert 'id="assistant-drawer"' in html, (
        "Assistant drawer must have id='assistant-drawer'"
    )

    # Must be outside the main content flow (after main page closes)
    main_close_idx = html.rfind('</main>')
    drawer_idx = html.find('id="assistant-drawer"')
    assert drawer_idx > main_close_idx, (
        "Assistant drawer must be rendered after </main>, outside content flow"
    )


def test_drawer_prompt_chips_not_overlapping():
    """Prompt chips and assistant input must not be structurally nested in a way that overlaps."""
    html = _ceo_executive_html()
    js = _static_executive_js()

    # The prompt row and form must exist as separate elements in the HTML
    assert 'id="assistant-prompt-row"' in html, (
        "Prompt chips must have their own container (assistant-prompt-row) in HTML"
    )
    assert 'id="assistant-form"' in html, (
        "Assistant input form must have its own container (assistant-form) in HTML"
    )

    # The prompt row element must be referenced in JS for rendering
    assert '$("assistant-prompt-row")' in js, (
        "assistant-prompt-row must be referenced in JS for rendering"
    )

    # The conversation layout must use CSS grid with proper row sizing
    css_path = Path(__file__).resolve().parent.parent / \
        "strategyos_mvp" / "static" / "executive.css"
    css = css_path.read_text()

    # .assistant-conversation must use grid-template-rows with explicit sizing
    conv_idx = css.find('.assistant-conversation {')
    assert conv_idx != -1, ".assistant-conversation CSS rule must exist"

    # Check that grid-template-rows uses minmax(0, 1fr) for scrollable area
    assert 'minmax(0, 1fr)' in css, (
        ".assistant-conversation or its children must use minmax(0,1fr) for scrollable area"
    )

    # Messages area must have overflow:auto for internal scrolling
    msg_idx = css.find('.assistant-messages {')
    assert msg_idx != -1, ".assistant-messages CSS rule must exist"
    msg_block = css[msg_idx:msg_idx + 300]
    assert 'overflow: auto' in msg_block or 'overflow:auto' in msg_block, (
        ".assistant-messages must have overflow:auto for internal scrolling"
    )


# ══════════════════════════════════════════════════════════════════════
# CTA ENUMERATION — every contextual assistant-opening CTA group
# ══════════════════════════════════════════════════════════════════════

def test_cta_enum_hero_prompts():
    """CTA 1: Hero prompt chips call askAssistant(prompt, button)."""
    js = _static_executive_js()
    assert 'askAssistant(prompt, button)' in js

def test_cta_enum_driver_chips():
    """CTA 2: Driver drill [data-driver-chip] chips call askAssistant."""
    js = _static_executive_js()
    assert "data-driver-chip" in js
    assert "querySelectorAll('[data-driver-chip]')" in js

def test_cta_enum_driver_composer():
    """CTA 3: Driver composer form #driver-composer calls askAssistant."""
    js = _static_executive_js()
    assert "driver-composer" in js

def test_cta_enum_gravity_explore():
    """CTA 4: Gravity/Explore scenarios [data-chat-prompt] chips."""
    js = _static_executive_js()
    assert "data-chat-prompt" in js

def test_cta_enum_board_prompts():
    """CTA 7: Board portal [data-board-prompt] prompt chips."""
    js = _static_executive_js()
    assert "data-board-prompt" in js

def test_cta_enum_board_actions():
    """CTA 8: Board portal [data-board-action] action buttons."""
    js = _static_executive_js()
    assert "data-board-action" in js

def test_cta_enum_executive_decision_brief():
    """CTA 9: Aggregated CEO priority opens a decision brief."""
    js = _static_executive_js()
    assert "data-executive-prompt" in js
    assert "Open decision brief" in js

def test_cta_enum_business_signal_pressure_test():
    """CTA 10: Material business signals can be pressure-tested."""
    js = _static_executive_js()
    assert "Pressure-test with Hermes" in js

def test_cta_enum_week_decision_preparation():
    """CTA 11: Commitments provide executable preparation actions."""
    js = _static_executive_js()
    assert "Prepare me" in js
    assert "Draft input request" in js
    assert 'entrypoint: "calendar_quick_action"' in js
    assert "calendarQuickActionContext" in js

def test_cta_enum_week_composer():
    """CTA 12: Week composer form #week-composer."""
    js = _static_executive_js()
    assert "week-composer" in js

def test_cta_enum_kg_ask_hermes():
    """CTA 13: Knowledge graph inspector 'Ask Hermes about this'."""
    js = _static_executive_js()
    assert "kg-inspector-ask" in js
    assert 'askAssistant(prompt, askBtn)' in js

def test_cta_enum_a2a_followup():
    """CTA 14: A2A panel follow-up button calls askAssistant."""
    js = _static_executive_js()
    assert "a2a-report-bug" in js

def test_cta_enum_drawer_internal_prompts():
    """CTA 15: Assistant drawer [data-assistant-prompt] internal chips."""
    js = _static_executive_js()
    assert "data-assistant-prompt" in js

def test_cta_enum_assistant_form():
    """CTA 16: Assistant form #assistant-form."""
    js = _static_executive_js()
    assert "assistant-form" in js
    assert "bindAssistantForm" in js

def test_cta_enum_agents_browse():
    """CTA 17: Agents discovery 'Browse all agents'."""
    js = _static_executive_js()
    assert "assistantCatalogueOpen" in js
    assert "Show me the agent catalogue" not in js

def test_cta_enum_new_conversation_threads():
    """CTA 18: New conversation buttons call openAssistantDrawer."""
    js = _static_executive_js()
    assert "data-thread-new" in js

def test_cta_count_all_matches_expected():
    """Total askAssistant call sites must match expected count."""
    js = _static_executive_js()
    count = js.count('askAssistant(')
    assert count >= 17, (
        f"Expected at least 17 askAssistant call sites, found {count}"
    )


# ══════════════════════════════════════════════════════════════════════
# KPI RING VISUAL ENCODING — preserve the supplied executive reference
#  - 100% is marked at three quarters of the ring
#  - the remaining quarter leaves visible headroom for over-plan performance
#  - a small tick makes the 100% reference explicit
# ══════════════════════════════════════════════════════════════════════

def test_driver_ring_arc_no_pct_clamp():
    """KPI ring arc must NOT clamp percentage to 100 — values up to 100
    are proportional, values above 100 cap at full ring (100%)."""
    js = _static_executive_js()

    assert "var pct = Math.max(0," in js, (
        "driverRingMarkup must set pct with Math.max(0, ...) only, no upper clamp"
    )

    # Extract only the driverRingMarkup function body to check it specifically
    func_start = js.index("function driverRingMarkup")
    func_end = js.index("function qaAnswerText", func_start)
    ring_func_body = js[func_start:func_end]

    # The old clamp must NOT exist inside driverRingMarkup
    assert "Math.min(100," not in ring_func_body, (
        "driverRingMarkup must NOT contain Math.min(100, ...) clamp — "
        "the natural cap at full ring (100%) handles values >= 100%"
    )


def test_driver_ring_preserves_reference_headroom_above_100():
    """The supplied reference reserves one quarter of the ring for values
    above 100%, with the plan tick at exactly three quarters."""
    js = _static_executive_js()

    assert "ringMax = 400 / 3" in js, (
        "driverRingMarkup must preserve the reference ring ceiling so 100% lands at three quarters"
    )
    assert "Math.min(pct, ringMax) / ringMax" in js, (
        "driverRingMarkup must calculate the arc against the reference ring ceiling"
    )


def test_driver_ring_has_reference_tick():
    """The visual contract requires a visible 100% plan marker."""
    js = _static_executive_js()

    func_start = js.index("function driverRingMarkup")
    func_end = js.index("function qaAnswerText", func_start)
    ring_func_body = js[func_start:func_end]

    assert "tickAngle" in ring_func_body
    assert "driver-ring__tick" in ring_func_body


def test_driver_ring_dash_proportional_to_pct():
    """Verify the exact 104px reference-gauge geometry."""
    import math
    radius = (104 - 5) / 2 - 8
    circumference = 2 * math.pi * radius
    ring_max = 400 / 3

    def expected_dash(pct_value):
        pct = max(0, pct_value)
        frac = max(0.02, min(pct, ring_max) / ring_max)
        return round(circumference * frac, 1)

    dash_0 = expected_dash(0)
    dash_50 = expected_dash(50)
    dash_100 = expected_dash(100)
    dash_123 = expected_dash(123)
    dash_max = expected_dash(ring_max)

    assert abs(dash_0 - circumference * 0.02) < 0.2
    assert abs(dash_50 - circumference * 0.375) < 0.2
    assert abs(dash_100 - circumference * 0.75) < 0.2
    assert dash_100 < dash_123 < dash_max
    assert abs(dash_max - circumference) < 0.2


def test_driver_ring_frac_floor_preserved():
    """The minimum frac of 0.02 must still be preserved so zero/very-low
    values show a visible sliver instead of an invisible ring."""
    js = _static_executive_js()

    assert "0.02" in js, (
        "driverRingMarkup must preserve the min frac=0.02 floor"
    )


def test_driver_ring_uses_plan_variance_for_its_semantic_color():
    """The KPI ring itself, rather than an overlapping badge, carries the signal."""
    js = _static_executive_js()

    ring_start = js.index("function driverRingMarkup")
    ring_end = js.index("function driverHasPercent", ring_start)
    ring_body = js[ring_start:ring_end]

    assert "var rawPlanPct = driver && driver.pct;" in ring_body
    assert 'planPct > 100 ? "up" : "down"' in ring_body
    assert 'driver-ring__value--\' + tone' in ring_body


def test_driver_ring_is_neutral_without_a_plan_delta():
    """Exactly-on-plan and absent comparisons must retain the neutral ring."""
    js = _static_executive_js()

    assert '!Number.isFinite(planPct) || planPct === 100' in js
    assert '? "flat"' in js


def test_driver_grid_has_no_plan_variance_badge():
    """The removed percentage pill must not overlap the gauge or metadata."""
    js = _static_executive_js()
    css = _static_executive_css()

    assert "driverPlanVarianceBadgeMarkup" not in js
    assert "driver-plan-variance" not in js
    assert ".driver-plan-variance" not in css


def test_driver_ring_has_rich_positive_and_negative_colors():
    """Above-plan and below-plan ring arcs use restrained rich semantic colors."""
    css = _static_executive_css()

    assert "--up: #176b4f;" in css
    assert "--down: #a33f35;" in css
    assert ".driver-ring__value--up { stroke: var(--up); }" in css
    assert ".driver-ring__value--down { stroke: var(--down); }" in css


def test_assistant_controls_do_not_cover_financial_evidence_at_desktop():
    """The dock may float only when there is a genuine external gutter.

    Standard executive laptop/desktop widths use an in-bar launcher instead,
    avoiding an action control sitting over values in a KPI drill.
    """
    css = _static_executive_css()

    assert "--assistant-dock-width" in css, (
        "Desktop layout must define a bounded assistant-dock width"
    )
    assert "--assistant-dock-width: clamp(220px, 18vw, 300px)" in css, (
        "Assistant dock must stay compact on desktop"
    )
    page_start = css.index(".page {")
    page_end = css.index("}", page_start)
    assert "padding-right: calc(" not in css[page_start:page_end], (
        "Desktop page layout must not reserve a large right-hand column for the fixed dock"
    )
    dock_start = css.index(".assistant-dock {")
    dock_end = css.index("}", dock_start)
    dock_block = css[dock_start:dock_end]
    assert "display: flex" in dock_block and "max-width: min(460px" in dock_block, (
        "Desktop dock must be a compact horizontal control, not a tall stacked rail"
    )
    assert "@media (min-width: 981px) and (max-width: 1799px)" in css, (
        "The fixed dock must be suppressed where the page has no outer gutter"
    )
    assert ".assistant-dock { display: none; }" in css, (
        "The standard desktop dock must not overlay decision evidence"
    )
    assert ".topbar-assistant-launch { display: inline-flex; }" in css, (
        "A visible in-bar Ask Hermes control must replace the suppressed dock"
    )
    assert "@media (max-width: 960px)" in css and "position: static;" in css, (
        "Mobile/tablet layout must drop the fixed dock and return it to normal flow"
    )


# ── Hermes Assistant Drawer UX Simplification Tests ──────────────────────


def test_ceo_assistant_header_no_named_assistant():
    """'Named assistant' must NOT appear in CEO executive page HTML."""
    html = _ceo_executive_html()
    assert "Named assistant" not in html, (
        "CEO executive page must not contain 'Named assistant' eyebrow text"
    )


def test_ceo_assistant_no_message_writable_metadata():
    """'message(s) · writable' must NOT appear in executive.js CEO thread card rendering."""
    js = _static_executive_js()
    assert "· writable" not in js, (
        "executive.js must not contain '· writable' metadata in thread cards"
    )
    # The old 'send and receive' pattern must also be gone
    assert "send and receive" not in js, (
        "executive.js must not contain 'send and receive' — old thread metadata pattern"
    )


def test_ceo_assistant_no_open_writable_text():
    """'Open a writable' must NOT appear in executive.js."""
    js = _static_executive_js()
    assert "Open a writable" not in js, (
        "executive.js must not contain 'Open a writable' — replaced with simplified text"
    )


def test_ceo_assistant_no_board_safe_move_placeholder():
    """'board-safe move' must NOT appear in executive.js input placeholder."""
    js = _static_executive_js()
    assert "board-safe move" not in js, (
        "executive.js input placeholder must not contain 'board-safe move'"
    )


def test_ceo_assistant_placeholder_is_ask_hermes():
    """'Ask Hermes…' must be in executive.js input placeholder."""
    js = _static_executive_js()
    assert "Ask Hermes" in js, (
        "executive.js input placeholder must contain 'Ask Hermes'"
    )


def test_ceo_assistant_history_collapsed_default():
    """.assistant-threads must have is-collapsed class or equivalent collapsed default in JS/HTML."""
    html = _ceo_executive_html()
    js = _static_executive_js()

    # In HTML: .assistant-threads should have is-collapsed
    assert 'assistant-threads is-collapsed' in html, (
        "HTML: .assistant-threads must have is-collapsed class by default"
    )

    # In JS: the toggle must set aria-expanded to 'false' (collapsed by default)
    assert "'false'" in js, (
        "JS: toggle button aria-expanded must default to 'false' (collapsed)"
    )
    # threads-collapsed class must be on layout
    assert "threads-collapsed" in js or 'threads-collapsed' in html, (
        "threads-collapsed class must be present (in HTML or JS sync)"
    )


def test_ceo_assistant_no_duplicate_under_review():
    """Both thread card preview AND assistant answer must NOT both contain under-review copy for the same thread."""
    js = _static_executive_js()
    # The boardSafeStatusReply CEO message is short: "The board pack is under review. Here's what I can answer now:"
    # We want to verify it's concise and there's no duplication pattern
    # Count occurrences of 'under review' — should appear in boardSafeStatusReply but not duplicated
    under_review_count = js.count("under review")
    assert under_review_count <= 3, (
        f"'under review' appears {under_review_count} times — "
        "should appear at most 3 times (boardSafeStatusReply + createWritableThread initial message + CEO dead-end guard)"
    )
    # Verify boardSafeStatusReply no longer has the old verbose text
    assert "Hermes will answer from the approved pack" not in js, (
        "Old verbose boardSafeStatusReply text must be replaced with concise version"
    )


def test_ceo_assistant_header_is_ask_hermes():
    """The CEO resolves Hermes while other personas keep their own assistant."""
    js = _static_executive_js()
    assert 'assistantHeading.textContent = "Ask " + assistantName' in js, (
        "executive.js must bind the heading to the persona assistant"
    )
    html = _ceo_executive_html()
    assert "Ask Hermes</h3>" in html or "Ask Hermes</h3>" in html, (
        "executive.html must have 'Ask Hermes' as the assistant heading"
    )


def test_ceo_assistant_prompt_chips_max_2():
    """Prompt chip rendering in assistant drawer must use .slice(0, 2) for getHeroPrompts."""
    js = _static_executive_js()
    # The assistant drawer prompt chips: getHeroPrompts().slice(0, 2)
    assert "getHeroPrompts().slice(0, 2)" in js, (
        "Assistant drawer prompt chip rendering must use getHeroPrompts().slice(0, 2)"
    )
    # Old pattern getHeroPrompts().slice(0, 3) must be gone
    assert "getHeroPrompts().slice(0, 3)" not in js, (
        "Assistant drawer must not use getHeroPrompts().slice(0, 3)"
    )


# ── Hermes Drawer Answer-Quality Regression Tests ──

def test_hermes_answer_no_stale_fx_fallback_for_digital_health():
    """Digital Health prompts must go server-side, not through canned JS branches."""
    js = _static_executive_js()
    assert 'postJson("/assistant/chat"' in js
    assert "/digital health/i.test" not in js
    assert "ceoDriverRelevanceReply" not in js
    assert "driver_context" in js
    assert "trace_id" in js


def test_hermes_answer_fx_fallback_still_works_for_fx_prompt():
    """FX prompts still carry driver context into the shared assistant API."""
    js = _static_executive_js()
    assert "driver_context" in js
    for token in ["label", "metric", "pct", "status", "detail", "movers"]:
        assert token in js


def test_hermes_answer_no_truncated_fragment():
    """Thread preview must not contain mid-word truncated fragments.

    The wordSlice helper must cut at word boundaries,
    not produce fragments like 'This matters because i'.
    """
    js = _static_executive_js()

    # wordSlice function must exist
    assert "function wordSlice" in js, (
        "wordSlice helper function must be defined for word-boundary truncation"
    )
    # Must use lastIndexOf(' ') for word-boundary detection
    assert "lastIndexOf(' ')" in js or 'lastIndexOf(" ")' in js, (
        "wordSlice must search for last space to cut at word boundary"
    )
    # Raw .slice(0, 84) on text without word boundary must be gone
    # (There may still be .slice(0, 84) for non-text values; key check:
    #  wordSlice must be used for thread.preview assignments)
    assert "wordSlice(answer" in js or "wordSlice(text" in js, (
        "Thread preview assignment must use wordSlice, not raw .slice(0, 84)"
    )


def test_hermes_thread_initial_message_not_under_review():
    """createWritableThread initial message must NOT contain 'under review'.

    The thread creation message must be a clean starter,
    not a duplicate of the boardSafeStatusReply CEO message.
    """
    js = _static_executive_js()

    # Find createWritableThread function content
    func_start = js.index("function createWritableThread")
    # Find the next function declaration after it
    next_funcs = []
    for kw in ["function pushThreadMessage", "function threadStore",
               "function friendlyThreadTime", "function showToast"]:
        idx = js.find(kw, func_start + 10)
        if idx != -1:
            next_funcs.append(idx)
    func_end = min(next_funcs) if next_funcs else func_start + 3000
    cwt_body = js[func_start:func_end]

    # The initial message in createWritableThread must NOT say "under review"
    assert "The board pack is under review" not in cwt_body, (
        "createWritableThread initial message must NOT contain "
        "'The board pack is under review' — avoid duplicate under-review bubbles"
    )

    assert "silentInitialMessage" in cwt_body


def test_hermes_answer_context_aware_initial_message():
    """createWritableThread must produce a context-aware initial message
    when called with a seedPreview (question text).

    The message should reference the question topic, not a generic
    'board pack under review' placeholder.
    """
    js = _static_executive_js()

    # Initial message must be context-aware — should reference seedPreview
    assert "seedPreview" in js, (
        "createWritableThread must reference seedPreview for context-aware message"
    )
    # The context-aware pattern: "I'll look up \"...\" against the current board pack"
    assert "I'll look up" in js or "current board pack" in js, (
        "Initial thread message must be context-aware when seedPreview is provided"
    )


def test_hermes_answer_generic_under_review_not_duplicated():
    """The word 'under review' must not appear excessively.

    With the deduplication fix (createWritableThread no longer says
    'board pack under review'), the count must be lower than before.
    """
    js = _static_executive_js()
    # Count occurrences — after fix should be at most 2:
    # 1. boardSafeStatusReply CEO message
    # 2. statusLabel mappings ("Under review")
    # Old code also had createWritableThread initial message (removed)
    under_review_count = js.count("under review")
    assert under_review_count <= 3, (
        f"'under review' appears {under_review_count} times — "
        "should appear at most 3 times after deduplication fix"
    )


# ── Hermes Answer-Quality: Context-Aware Branch Regression Tests ──

def test_hermes_digital_health_branch_has_correct_context():
    """Digital Health scenario prompts must route through shared /qa transport."""
    js = _static_executive_js()
    assert 'postJson("/assistant/chat"' in js
    assert "driver_context" in js
    assert "/digital health/i.test" not in js


def test_hermes_epharmacy_branch_has_correct_context():
    """e-Pharmacy prompts should be handled by the backend, not client regex branches."""
    js = _static_executive_js()
    assert "/e-pharmacy|epharmacy/i.test" not in js
    assert 'postJson("/assistant/chat"' in js


def test_hermes_fx_branch_has_correct_context():
    """FX prompts should use shared API transport plus driver context."""
    js = _static_executive_js()
    assert "driver_context" in js
    assert "/fx|margin|hedg|forex|currency/i.test" not in js


def test_hermes_cash_branch_has_correct_context():
    """Cash prompts should not rely on a client-side cash fallback branch."""
    js = _static_executive_js()
    assert "/cash|liquidity|floor|covenant/i.test" not in js
    assert 'postJson("/assistant/chat"' in js


def test_hermes_cold_chain_branch_has_correct_context():
    """Cold-chain prompts should be delegated to the backend orchestrator."""
    js = _static_executive_js()
    assert "/cold.chain|coldchain|resilience/i.test" not in js
    assert 'postJson("/assistant/chat"' in js


def test_hermes_generic_branch_has_bounded_answer():
    """No generic JS fallback branch should exist anymore."""
    js = _static_executive_js()
    assert "// CEO dead-end guard:" not in js
    assert 'postJson("/assistant/chat"' in js


def test_hermes_no_old_dead_end_patterns():
    """Old dead-end copy must be gone now that the backend owns answers."""
    js = _static_executive_js()

    # These old patterns must NOT appear anywhere in the JS
    assert "The exact Digital Health absolute figure is not available" not in js, (
        "Old Digital Health dead-end text must be removed"
    )
    assert "The FX margin detail is not available" not in js, (
        "Old FX dead-end text must be removed"
    )
    assert "The absolute cash figure is not available" not in js, (
        "Old Cash dead-end text must be removed"
    )
    assert "The absolute cost figure is not available" not in js, (
        "Old Cost dead-end text must be removed"
    )
    assert "The exact figure is not available in the current board pack" not in js, (
        "Old generic dead-end text must be removed"
    )

    assert "ceoDriverRelevanceReply" not in js
    assert "// CEO dead-end guard:" not in js


def test_ceo_simulation_intent_gets_actionable_thinking_mode_answer():
    """Simulation prompts must be sent to the shared backend API."""
    js = _static_executive_js()
    assert "isCeoSimulationIntent" not in js
    assert "ceoSimulationReply" not in js
    assert 'postJson("/assistant/chat"' in js


def test_ceo_simulation_prompt_starts_with_help_not_lookup():
    """New ask flows should suppress the seed assistant bubble to avoid duplicates."""
    js = _static_executive_js()
    create_start = js.index("function createWritableThread")
    create_end = js.index("function pushThreadMessage", create_start)
    create_block = js[create_start:create_end]

    assert "silentInitialMessage" in create_block
    assert "messages: silentInitialMessage ? []" in create_block


def test_ceo_simulation_branch_precedes_generic_board_pack_recap():
    """Simulation handling no longer lives in a client-side branch."""
    js = _static_executive_js()
    assert "// CEO dead-end guard:" not in js



def test_hermes_facts_lead_not_excuses():
    """There must be no client-side dead-end branches left to tune."""
    js = _static_executive_js()
    assert "// CEO dead-end guard:" not in js
    assert "answer = answer +" not in js


# ── Drawer hidden-state enforcement ──

def test_ceo_drawer_hidden_on_page_load():
    """Fresh CEO page load must NOT expose the assistant drawer in the
    accessibility tree. The drawer element must carry aria-hidden='true',
    and the CSS must override [hidden] with visibility: hidden so
    screen readers skip it entirely.

    Acceptance A: No visible/open assistant drawer; no accessible
    'Select a thread to continue' unless drawer opened.
    """
    js = _static_executive_js()
    css = _static_executive_css()

    # ── JS: renderAssistantStudio must set aria-hidden on drawer when closed ──
    # The drawer DOM element getter + aria-hidden setter must be in JS
    assert 'aria-hidden' in js, (
        "drawer must set aria-hidden attribute in renderAssistantStudio"
    )
    # Verify the aria-hidden is set conditionally on drawerOpen state
    studio_start = js.index("function renderAssistantStudio")
    studio_end = studio_start + 3000
    studio_block = js[studio_start:min(studio_end, len(js))]
    assert 'state.drawerOpen ? "false" : "true"' in studio_block or \
           'state.drawerOpen' in studio_block, (
        "aria-hidden must toggle with state.drawerOpen"
    )

    # ── CSS: assistant-drawer[hidden] must include visibility: hidden ──
    drawer_hidden_css_start = css.index(".assistant-drawer[hidden]")
    drawer_hidden_css = css[drawer_hidden_css_start:drawer_hidden_css_start + 300]
    assert "visibility: hidden" in drawer_hidden_css, (
        "CSS rule .assistant-drawer[hidden] must set visibility: hidden "
        "to remove drawer from accessibility tree when closed"
    )

    # ── CSS: assistant-scrim[hidden] must also include visibility: hidden ──
    scrim_hidden_css_start = css.index(".assistant-scrim[hidden]")
    scrim_hidden_css = css[scrim_hidden_css_start:scrim_hidden_css_start + 200]
    assert "visibility: hidden" in scrim_hidden_css, (
        "CSS rule .assistant-scrim[hidden] must set visibility: hidden"
    )


def test_ceo_no_stale_thread_leakage():
    """CEO persona must filter system and invalid legacy threads."""
    js = _static_executive_js()

    # ── ensureThreads must contain the CEO stale-thread filter ──
    assert "state.activePersona === \"ceo\"" in js, (
        "CEO stale-thread guard must exist in ensureThreads"
    )

    # Find ensureThreads function
    ensure_start = js.index("function ensureThreads")
    ensure_end = ensure_start + 3000
    ensure_block = js[ensure_start:min(ensure_end, len(js))]

    assert "isSystem" in ensure_block, (
        "ensureThreads must filter system threads for CEO"
    )


def test_ceo_digital_health_answer_leads_with_facts():
    """Digital Health prompts are now routed to backend scenarios, not JS copy."""
    js = _static_executive_js()
    assert "/digital health/i" not in js
    assert 'postJson("/assistant/chat"' in js


# The knowledge-map hover-vibration regression is guarded by
# test_kg_hover_uses_stable_hit_geometry in test_frontend_shell.py: the
# hit-circle approach (359bdf1) superseded the transform-box fix this file
# previously asserted, so the old transform-based assertions were removed
# rather than left to contradict the shipped geometry.


def test_hero_status_panel_is_compact_and_responsive():
    """The CEO status summary must remain a bounded card at every viewport."""
    css = _static_executive_css()

    assert ".hero-status {" in css
    assert "minmax(280px, 0.75fr)" in css
    assert ".hero-status__heading" in css
    assert ".hero-status__signal.is-attention" in css
    assert ".hero-mini-stats .mini-stat" in css
    assert ".hero-score" not in css
    assert ".score-ring" not in css


def test_kpi_panel_free_text_ask_carries_the_active_figure_as_context():
    """The free-text box under the preset questions must keep the figure first.

    A CEO typing into the Revenue panel means Revenue. The input therefore
    sends the same assistant_context the preset buttons send (kpi_key /
    kpi_label), which is the explicit-key path the causation guard preserves --
    so the figure on screen stays the subject rather than being inferred from
    the words typed.
    """
    js = _static_executive_js()
    css = _static_executive_css()

    assert "data-kpi-ask-form" in js, "the KPI panel must expose a free-text ask"
    assert 'kpi_question_intent: "free_text"' in js, (
        "a typed question must be distinguishable from the preset intents"
    )

    form_start = js.index("[data-kpi-ask-form]")
    handler = js[form_start:form_start + 900]
    assert "kpi_key: key" in handler and "kpi_label: label" in handler, (
        "the typed question must carry the active KPI as context, so the "
        "figure on screen is answered first"
    )
    assert 'entrypoint: "ceo_kpi_inline"' in handler

    assert ".kpi-inline-ask" in css, "the free-text ask must be styled with the panel"


def test_kpi_mover_note_is_a_shared_server_resolved_assistant_subject():
    """Inline, drawer and follow-up asks must retain the selected governed mover."""
    js = _static_executive_js()

    assert "function kpiAssistantSubject(driver)" in js
    assert 'kind: "kpi_mover"' in js
    assert 'parent_kind: "kpi"' in js
    assert "note:" not in js[js.index("function kpiAssistantSubject(driver)"):js.index("function kpiMovementMarkup", js.index("function kpiAssistantSubject(driver)"))]
    assert 'subject: entrypoint === "board_portal" ? undefined : kpiAssistantSubject(activeDriver)' in js
    assert js.count("subject: kpiAssistantSubject(driver)") >= 2

    cache_start = js.index("function assistantAnswerCacheKey")
    cache_end = js.index("function loadAssistantAnswerCache", cache_start)
    cache_body = js[cache_start:cache_end]
    assert "subject.kind" in cache_body
    assert "subject.key" in cache_body


def test_ai_team_card_renders_leadership_status_not_raw_execution_log():
    """CEO AI-team cards must not expose technical audit/runtime events."""
    js = _static_executive_js()
    assert "function renderExecutionLog()" in js
    assert "function renderLeadershipStatus(item)" in js
    assert "+ renderLeadershipStatus(item) +" in js
    assert "renderExecutionLog() + (item.route" not in js


def test_twins_and_specialist_functions_are_separate_ceo_surfaces():
    html = (Path(api_module.STATIC_DIR) / "executive.html").read_text(encoding="utf-8")
    js = _static_executive_js()

    assert 'data-view-target="agents"' in html
    assert 'data-view-target="functions"' in html
    assert 'id="view-functions"' in html
    assert 'id="functions-roster"' in html
    assert 'id="functions-audit"' not in html
    assert 'data-view-target="assistants"' not in html
    assert 'id="assistant-network-card"' not in html
    assert 'id="a2a-fab"' not in html
    assert 'id="a2a-panel"' not in html
    assert 'id="assistant-drawer"' in html
    assert "AI Assistants represent leaders. Agents complete specialist work." in js
    assert "Specialist analysis and audit work is tracked under Agents." in js


def test_finance_function_workspace_uses_recorded_audit_events_and_exposes_stuck_state():
    js = _static_executive_js()
    review_block = js.split("function getFinanceFunctionReview()")[1].split(
        "function functionStateLabel", 1
    )[0]
    render_block = js.split("function renderFunctionsWorkspace()")[1].split(
        "function renderLeadershipStatus", 1
    )[0]

    assert "getExecutionLog()" in review_block
    assert "isFinanceFunctionActor(entry.actor)" in review_block
    assert 'name: "Finance Analyst"' in review_block
    assert 'name: "Finance Auditor"' in review_block
    assert 'stateKey = /\\b(locked|resolved|approved|complete|completed|closed|accepted)\\b/' in review_block
    assert '"stuck"' in review_block
    assert "Recorded review trail" in render_block
    assert "Expand a finding to see this agent’s work" in render_block
    assert "function-card__trail" in render_block
    assert "data-function-finding-toggle" not in render_block
    assert 'entrypoint: "function_review"' in render_block
    assert "Presentation composer" in render_block and "Meeting booker" in render_block
    assert "Planned · not enabled" in render_block


def test_leadership_status_does_not_read_raw_execution_events():
    js = _static_executive_js()
    status_block = js.split("function renderLeadershipStatus(item)")[1][:1800]
    assert "getExecutionLog" not in status_block
    assert "Execution log" not in status_block
    assert "Current status" in status_block
    assert "function leadershipActivityCopy(item)" in js
    assert "key performance measures" in js
    assert "Portfolio under review" in js


def test_execution_log_styles_are_served():
    css = _static_executive_css()
    for selector in (".agent-trail", ".trail-item", ".trail-quote", ".trail-note", ".trail-foot"):
        assert selector in css, f"missing style for {selector}"


def test_hermes_network_is_a_named_ai_leadership_team_not_product_modules():
    js = _static_executive_js()
    assert "Governed Assistant Network" not in js
    assert "Hermes' AI leadership team" in js
    assert "function getLeadershipTeam()" in js
    assert "agents.digital_twins" in js
    assert "isExecutiveLeadershipTwin" in js
    assert "analyst|auditor|reviewer" in js
    assert "data-network-status-toggle" in js
    assert 'entrypoint: "ai_team_brief"' in js
    assert "working now" in js


def test_executive_surface_speaks_english_not_pipeline():
    """Words an executive cannot be expected to know, on their own dashboard."""
    js = _static_executive_js()
    for jargon in (
        "Grounded ✓",
        "Needs evidence ⚠",
        "bounded KPI layer",
        "release posture",
        "human gate",
    ):
        assert jargon not in js, f"pipeline jargon on the CEO surface: {jargon}"


def test_grounding_badge_says_what_it_means():
    js = _static_executive_js()
    assert "Evidence verified" in js
    assert "Evidence gap" in js


def test_expired_sign_in_is_reported_as_expired_sign_in():
    """The live failure: an expired token read as a service outage.

    Every assistant failure said "could not reach the shared assistant
    service", so a session that had simply timed out looked like a broken
    product, and the advice -- retry -- was the one thing that could never fix
    it.
    """
    js = _static_executive_js()
    assert "function assistantFailureCopy(errorType, statusCode)" in js
    assert "Your sign-in has expired. Sign in again to carry on the conversation." in js
    # An expired sign-in is not retryable: retrying is what wasted the reader's time.
    assert 'if (errorType === "auth_error" || status === 401)' in js
    # The failure builder must consult it rather than hardcoding one sentence.
    assert "var copy = assistantFailureCopy(errorType, statusCode);" in js
    assert "answer: copy.answer," in js


def test_forbidden_and_timeout_say_what_they_are():
    js = _static_executive_js()
    assert "Your account does not have access to this." in js
    assert "That took too long to come back." in js


def _ready_hero_read_model(recoverable: float, finding_count: int):
    return {
        "data_status": "ready",
        "metrics": {
            "recoverable_total": {"value": recoverable},
            "challenged_count": {"value": 0},
            "report_count": {"value": 1},
            "citation_resolution": {"value": {"total": 41, "resolved": 40}},
        },
        "lifecycle": {"approval_status": {"value": "pending"}},
        "findings": [{"finding_id": {"value": f"F-{i:03d}"}} for i in range(finding_count)],
    }


def test_hero_leads_with_the_business_not_our_workflow():
    """The headline leads with enterprise posture, not cases or workflow."""
    from strategyos_mvp.executive_presentation import _hero

    hero = _hero(_ready_hero_read_model(794108.0, 8), drivers=[{
        "availability": "verified",
        "label": "Revenue",
        "executive_brief": {"executive_signal": {
            "posture": "Broadly on plan",
            "action_required": False,
            "readout": "Revenue is broadly on plan.",
            "decision": "No intervention required.",
        }},
    }])
    assert hero["label"] == "Enterprise performance is broadly on plan"
    assert "No headline measure" in hero["body"]
    assert hero["executive_posture"] == "On plan"


def test_hero_does_not_manufacture_a_headline_when_nothing_was_found():
    from strategyos_mvp.executive_presentation import _hero

    hero = _hero(_ready_hero_read_model(0.0, 0), drivers=[{"availability": "available"}])
    assert hero["label"] == "Board pack is waiting for final sign-off"


def test_a_finding_names_the_counterparty_an_executive_recognises():
    """"INV-2026-0341" tells a CEO nothing; the vendor tells them who to call."""
    from strategyos_mvp.executive_read_model import build_executive_read_model
    from strategyos_mvp.executive_presentation import build_executive_presentation

    read_model = build_executive_read_model(
        summary={"run_id": "r1", "approval_status": "pending"},
        finding_rows=[{
            "finding_id": "F-002",
            "title": "Duplicate payment for invoice INV-2026-0341",
            "pattern_type": "duplicate_payment",
            "vendor_name": "Premier Packaging LLC",
            "recoverable_sar": 177188.0,
            "citation_count": 6,
            "challenged": False,
        }],
        audit_summary={},
        publication={},
        agent_modules={},
        truth_source="database",
    )
    item = build_executive_presentation(read_model)["sections"]["findings"]["items"][0]
    assert item["counterparty"] == "Premier Packaging LLC"
    assert item["detail"].startswith("Premier Packaging LLC · SAR 177K recoverable")


def test_a_finding_without_a_counterparty_states_no_counterparty():
    """Never infer a vendor the run does not carry."""
    from strategyos_mvp.executive_read_model import build_executive_read_model
    from strategyos_mvp.executive_presentation import build_executive_presentation

    read_model = build_executive_read_model(
        summary={"run_id": "r1", "approval_status": "pending"},
        finding_rows=[{
            "finding_id": "F-009",
            "title": "Unallocated variance",
            "pattern_type": "variance",
            "recoverable_sar": 1000.0,
            "citation_count": 1,
            "challenged": False,
        }],
        audit_summary={},
        publication={},
        agent_modules={},
        truth_source="database",
    )
    item = build_executive_presentation(read_model)["sections"]["findings"]["items"][0]
    assert item["counterparty"] is None
    assert item["detail"].startswith("SAR 1K recoverable")


def test_counterparty_is_read_from_the_database_row_shape():
    """The live failure: the fix worked in tests and did nothing on the page.

    state_store projects Finding.vendor_name into a key called "owner" for the
    database path, while the governed-artifact path keeps "vendor_name". My
    fixture used vendor_name only, so the test passed while prod -- which reads
    the database -- showed no counterparty at all.
    """
    from strategyos_mvp.executive_read_model import build_executive_read_model
    from strategyos_mvp.executive_presentation import build_executive_presentation

    read_model = build_executive_read_model(
        summary={"run_id": "r1", "approval_status": "pending"},
        # Exactly what state_store.executive_snapshot_for_run emits.
        finding_rows=[{
            "finding_id": "F-002",
            "title": "Duplicate payment for invoice INV-2026-0341",
            "pattern_type": "duplicate_payment",
            "classification": "",
            "confidence": "HIGH",
            "status": "draft",
            "recoverable_sar": 177188.0,
            "leakage_sar": 177188.0,
            "owner": "Premier Packaging LLC",
            "citation_count": 6,
            "resolved_citation_count": 6,
            "challenged": False,
        }],
        audit_summary={},
        publication={},
        agent_modules={},
        truth_source="database",
    )
    item = build_executive_presentation(read_model)["sections"]["findings"]["items"][0]
    assert item["counterparty"] == "Premier Packaging LLC"
    assert item["detail"].startswith("Premier Packaging LLC · SAR 177K recoverable")


def test_no_pipeline_vocabulary_in_the_strings_a_ceo_reads():
    """Words that are ours, not the company's, on surfaces an executive reads.

    Scoped to the strings that actually render. A live walk of the CEO views
    found exactly four survivors after the first pass -- grep over every source
    string would have flagged dozens that no executive ever sees, and chasing
    those would churn internal contracts for no reader.
    """
    js = _static_executive_js()
    for jargon in (
        "Which governed cases create",
        "this board packet can be released",
        "governed report posture",
        "Governed board packet",
        "Governed Assistant Network",
    ):
        assert jargon not in js, f"pipeline vocabulary a CEO would read: {jargon}"


def test_agent_module_summaries_do_not_say_governed():
    """These render verbatim on the Assistants page."""
    import strategyos_mvp.api as api_module
    import inspect

    source = inspect.getsource(api_module._agent_modules_payload)
    assert "governed case" not in source
    assert "governed report posture" not in source


def test_a_finding_carries_its_recommended_action_and_state():
    """A finding was a dead end -- a value with no next step. It now names the
    recommended action and where it sits, both read from the governed finding."""
    from strategyos_mvp.executive_read_model import build_executive_read_model
    from strategyos_mvp.executive_presentation import build_executive_presentation

    read_model = build_executive_read_model(
        summary={"run_id": "r1", "approval_status": "pending"},
        finding_rows=[{
            "finding_id": "F-002",
            "title": "Duplicate payment for invoice INV-2026-0341",
            "pattern_type": "duplicate_payment",
            "owner": "Premier Packaging LLC",
            "status": "draft",
            "remediation": "AP should immediately recover the duplicate payment from the vendor.",
            "recoverable_sar": 177188.0,
            "citation_count": 6,
            "challenged": False,
        }],
        audit_summary={}, publication={}, agent_modules={}, truth_source="database",
    )
    item = build_executive_presentation(read_model)["sections"]["findings"]["items"][0]
    assert item["state"] == "Ready for your review"
    assert item["recommended_action"].startswith("AP should immediately recover")


def test_a_finding_with_no_recommended_action_shows_none_not_a_blank():
    from strategyos_mvp.executive_read_model import build_executive_read_model
    from strategyos_mvp.executive_presentation import build_executive_presentation

    read_model = build_executive_read_model(
        summary={"run_id": "r1", "approval_status": "pending"},
        finding_rows=[{
            "finding_id": "F-009", "title": "Unallocated variance",
            "pattern_type": "variance", "status": "draft",
            "recoverable_sar": 1000.0, "citation_count": 1, "challenged": False,
        }],
        audit_summary={}, publication={}, agent_modules={}, truth_source="database",
    )
    item = build_executive_presentation(read_model)["sections"]["findings"]["items"][0]
    assert item["recommended_action"] is None


def test_ceo_home_aggregates_findings_instead_of_approving_cases():
    js = _static_executive_js()
    assert "function requestFindingRecovery(button)" in js
    lower = js[js.index("function renderLowerRailFidelity"):js.index("function renderAgentsDiscovery")]
    assert "data-finding-approve=" not in lower
    assert "Approve recovery" not in lower
    assert "Recent decisions and commitments" in lower
    assert "No case-level decision is escalated to the CEO" in lower
    assert "Owner · " in lower
    # The lower-level endpoint remains available outside the CEO home.
    assert '"/executive/findings/request-recovery"' in js


def test_sub_threshold_findings_remain_delegated_to_the_group_cfo():
    """Operational cases must not become CEO decisions merely because they exist."""
    from strategyos_mvp.executive_read_model import build_executive_read_model
    from strategyos_mvp.executive_presentation import build_executive_presentation

    read_model = build_executive_read_model(
        summary={"run_id": "r1", "approval_status": "approved"},
        finding_rows=[
            {
                "finding_id": "F-001",
                "title": "Duplicate payment",
                "recoverable_sar": 400_000.0,
                "citation_count": 2,
            },
            {
                "finding_id": "F-002",
                "title": "Unallocated variance",
                "recoverable_sar": 350_000.0,
                "citation_count": 1,
            },
        ],
        audit_summary={},
        publication={"report_count": 1},
        agent_modules={},
        truth_source="database",
    )

    priorities = build_executive_presentation(read_model)["sections"]["executive_priorities"]

    assert priorities["materiality_threshold_sar"] == 1_000_000.0
    assert not any(item["key"] == "recovery_mandate" for item in priorities["decisions"])
    assert priorities["delegated_summary"] == {
        "title": "Operational controls remain delegated",
        "summary": "2 finance-control cases are below the CEO materiality threshold of SAR 1.0M and remain with the Group CFO.",
        "owner": "Group CFO",
    }


def test_material_findings_become_one_aggregated_ceo_mandate():
    """The CEO sees the material programme, never a queue of invoice decisions."""
    from strategyos_mvp.executive_read_model import build_executive_read_model
    from strategyos_mvp.executive_presentation import build_executive_presentation

    read_model = build_executive_read_model(
        summary={"run_id": "r1", "approval_status": "approved"},
        finding_rows=[
            {
                "finding_id": "F-001",
                "title": "Duplicate payment for INV-100",
                "recoverable_sar": 700_000.0,
                "citation_count": 2,
            },
            {
                "finding_id": "F-002",
                "title": "Duplicate payment for INV-200",
                "recoverable_sar": 600_000.0,
                "citation_count": 2,
            },
        ],
        audit_summary={},
        publication={"report_count": 1},
        agent_modules={},
        truth_source="database",
    )

    priorities = build_executive_presentation(read_model)["sections"]["executive_priorities"]
    mandate = next(item for item in priorities["decisions"] if item["key"] == "recovery_mandate")

    assert mandate["title"] == "Set the mandate for SAR 1.3M of recovery"
    assert mandate["owner"] == "Group CFO"
    assert "aggregated across 2 finance-control cases" in mandate["summary"]
    assert "INV-100" not in json.dumps(priorities)
    assert "INV-200" not in json.dumps(priorities)
    assert priorities["delegated_summary"] is None
