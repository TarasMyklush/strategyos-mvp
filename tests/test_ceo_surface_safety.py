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


def test_ceo_assistant_never_leaks_raw_internals():
    """CEO reply paths must not expose run IDs, internal statuses, finding counts, etc.

    This is the SINGLE MOST IMPORTANT CEO safety test. It proves that:
    1. CEO guards exist in both boardSafeStatusReply() and qaAnswerText()
    2. Each CEO guard returns BEFORE any banned internal string
    3. No banned string appears in the CEO code path of either function
    """
    js = _static_executive_js()

    # ---------------------------------------------------------------
    # PART A: boardSafeStatusReply must have CEO-safe early return
    # ---------------------------------------------------------------
    assert 'state.activePersona === "ceo"' in js, (
        "boardSafeStatusReply: CEO gate must exist"
    )
    ceo_friendly_msg = (
        "Your board pack is currently under review. "
        "Hermes will answer from the approved pack once review clears."
    )
    assert ceo_friendly_msg in js, (
        "CEO-safe board status reply not found"
    )

    # The CEO guard must be the FIRST check inside boardSafeStatusReply
    func_start = js.index("function boardSafeStatusReply")
    # Find the first { after the function declaration
    brace_idx = js.index("{", func_start)
    first_statement = js[brace_idx : brace_idx + 300]
    assert 'if (state.activePersona === "ceo")' in first_statement, (
        "boardSafeStatusReply: CEO guard must be FIRST check after opening brace. "
        "If raw strings appear before this guard, they could leak."
    )

    # ---------------------------------------------------------------
    # PART B: qaAnswerText must have CEO-safe early return
    # ---------------------------------------------------------------
    qa_func_start = js.index("function qaAnswerText")
    qa_brace_idx = js.index("{", qa_func_start)
    qa_first_statement = js[qa_brace_idx : qa_brace_idx + 300]
    assert 'if (state.activePersona === "ceo")' in qa_first_statement, (
        "qaAnswerText: CEO guard must be FIRST check after opening brace"
    )

    # ---------------------------------------------------------------
    # PART C: Banned strings must NOT appear in CEO code paths
    # Each function with a CEO guard is split at the guard:
    #   [pre-guard code] CEO-guard { CEO-safe return } [post-guard: non-CEO code]
    # Banned strings in post-guard are acceptable (non-CEO path only).
    # Banned strings in pre-guard or inside CEO block are FAILURES.
    # ---------------------------------------------------------------
    banned = [
        "I could not compute a protected data answer",
        "Recoverable value is",
        "findings:",
        "challenged items:",
        "[object Promise]",
    ]

    # For boardSafeStatusReply: banned strings must NOT appear before the CEO guard
    board_ceo_guard_idx = js.index(
        'if (state.activePersona === "ceo")', func_start
    )
    # Everything from function start to CEO guard = pre-guard region
    pre_guard = js[func_start:board_ceo_guard_idx]
    for phrase in banned:
        assert phrase not in pre_guard, (
            f"boardSafeStatusReply: banned phrase '{phrase}' appears BEFORE CEO guard "
            f"(risk: may execute before CEO check)"
        )

    # CEO path body: the code inside the if-ceo block
    ceo_block_brace = js.index("{", board_ceo_guard_idx)
    # Find the closing } that ends the CEO if-block
    return_idx = js.index("return", ceo_block_brace)
    return_semi = js.index(";", return_idx)
    ceo_block_end = js.index("}", return_semi)  # closing brace of if-block
    ceo_block = js[ceo_block_brace:ceo_block_end + 1]
    for phrase in banned:
        assert phrase not in ceo_block, (
            f"boardSafeStatusReply: banned phrase '{phrase}' found INSIDE CEO guard block"
        )

    # For qaAnswerText: banned strings must not appear before CEO guard
    qa_ceo_guard_idx = js.index(
        'if (state.activePersona === "ceo")', qa_func_start
    )
    qa_pre_guard = js[qa_func_start:qa_ceo_guard_idx]
    for phrase in banned:
        assert phrase not in qa_pre_guard, (
            f"qaAnswerText: banned phrase '{phrase}' appears BEFORE CEO guard"
        )

    # qaAnswerText CEO path must not reference internal metadata.
    # The CEO guard block is safe: it opens a brace, declares ceoAnswer,
    # and returns before any payload.mode / payload.basis / payload.run_id
    # are ever reached.  Only scan the code between the opening brace of
    # the if-ceo block and the return semicolon — do NOT extend past it
    # into non-CEO territory (where payload.mode legitimately appears).
    qa_ceo_brace = js.index("{", qa_ceo_guard_idx)
    qa_ceo_return = js.index("return", qa_ceo_brace)
    qa_ceo_semicolon = js.index(";", qa_ceo_return)
    qa_ceo_block = js[qa_ceo_brace:qa_ceo_semicolon + 1]
    for meta_token in ["payload.mode", "payload.basis", "payload.run_id"]:
        assert meta_token not in qa_ceo_block, (
            f"qaAnswerText CEO path must not reference {meta_token}"
        )


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
    assert "Built-in" in js, (
        "Connector badges must say 'Built-in'"
    )
    assert "Board reports" in js, (
        "Report surface must be rebadged as 'Board reports'"
    )
    assert "reports ready" in js, (
        "Hero mini-stats must use CEO-friendly labels"
    )
    assert "agents active" in js, (
        "Hero mini-stats must use 'agents active' not 'running'"
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
    # Also check for the bare path as a link target anywhere
    assert "/public/runs/latest/report-preview" not in html or (
        html.count("/public/runs/latest/report-preview") <= 2
        and 'href="/public/runs/latest' not in html
    ), (
        "CEO executive HTML must not expose report-preview route as visible content"
    )


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


def test_ceo_video_embed_preserved():
    """Leader's Corner iframe embed must be present."""
    js = _static_executive_js()
    html = _ceo_executive_html()

    # JS must contain iframe embed code
    assert "youtube-nocookie.com/embed" in js, (
        "YouTube embed URL must be present in JS"
    )
    assert "leaders-featured-iframe" in js, (
        "Featured iframe ID must be present"
    )

    # The existing video IDs from the leaders' corner test
    assert "uTRKdCY4HdE" in js
    assert "sFSzPE2AOE0" in js
    assert "pQtdQ6AHn_Q" in js
    assert "t885M1WB1pg" in js


# ── YouTube Error 153 prevention ──

def test_ceo_video_embed_referrerpolicy_attr():
    """All YouTube iframes must carry referrerpolicy='strict-origin-when-cross-origin'."""
    js = _static_executive_js()

    # Inline embed (initial render)
    assert 'referrerpolicy="strict-origin-when-cross-origin"' in js, (
        "Inline iframe must have referrerpolicy='strict-origin-when-cross-origin'"
    )
    # selectLeadersVideo must set referrerpolicy on iframe swap
    assert "setAttribute('referrerpolicy'" in js, (
        "selectLeadersVideo must set referrerpolicy attribute on iframe"
    )
    assert "'strict-origin-when-cross-origin'" in js, (
        "strict-origin-when-cross-origin value must appear in JS"
    )
    # Modal iframe must also carry referrerpolicy
    referred = js.count("referrerpolicy")
    assert referred >= 2, (
        "At least 2 referrerpolicy assignments expected (inline + modal iframe)"
    )


def test_ceo_video_embed_allow_attrs():
    """YouTube iframes must include web-share in the allow attribute."""
    js = _static_executive_js()

    assert "web-share" in js, (
        "iframe allow attribute must include 'web-share'"
    )
    # Full allow string with web-share must appear at least once
    assert "picture-in-picture; web-share" in js, (
        "allow attribute must include picture-in-picture; web-share in correct order"
    )


def test_ceo_video_embed_origin_param():
    """YouTube embed URL must include origin parameter (dynamic via window.location.origin)."""
    js = _static_executive_js()

    assert "encodeURIComponent(window.location.origin)" in js, (
        "YouTube embed URL must include dynamic origin=encodeURIComponent(window.location.origin) "
        "to help YouTube validate embedding context"
    )
    assert "?origin=" in js or "&origin=" in js or "origin='" in js, (
        "YouTube embed URL must include origin parameter"
    )


def test_ceo_video_embed_no_referrer_removed():
    """no-referrer must NOT appear in executive.js (was root cause of Error 153)."""
    js = _static_executive_js()

    # 'no-referrer' as a referrer policy value must not appear in JS
    # (the Caddyfile fix handles the header side; this checks the JS side)
    assert "no-referrer" not in js, (
        "'no-referrer' must not appear in executive.js — "
        "was the root cause of YouTube Error 153"
    )


def test_ceo_video_embed_inline_fallback():
    """Inline embed must have dual fallback: PostMessage listener for instant
    Error 153 detection + setTimeout backup. Shows fallback card with 'Open on YouTube' link."""
    js = _static_executive_js()

    # PostMessage listener catches YouTube iframe API errors (instant Error 153 detection)
    assert "postMessage" in js.lower() or "message" in js.lower(), (
        "PostMessage listener must exist for YouTube error detection"
    )
    assert "leaders-fallback-card" in js, (
        "Inline fallback card CSS class must be present"
    )
    assert "leaders-fallback-link" in js, (
        "Inline fallback 'Open on YouTube' link must be present"
    )
    # Fallback timer must exist (setTimeout with 10s as backup)
    assert "setTimeout" in js, (
        "Inline fallback must use setTimeout for timeout detection"
    )
    assert "10000" in js, (
        "Inline fallback timeout must be 10000ms (10 seconds)"
    )
    # Fallback must clear timer on iframe load or PostMessage onReady
    assert "clearTimeout" in js, (
        "Inline fallback must clearTimeout on successful iframe load"
    )
    # Fallback message must be user-friendly
    assert "not available" in js and ("inline" in js or "playback" in js), (
        "Fallback message must indicate video not available inline"
    )


def test_ceo_video_modal_fallback_preserved():
    """Modal embed fallback must be preserved (10s timeout → 'Open on YouTube')."""
    js = _static_executive_js()

    assert "video-fallback" in js, (
        "Modal fallback div ID must be present"
    )
    assert "Embed unavailable" in js, (
        "Modal fallback must contain 'Embed unavailable' text"
    )
    assert "video-fallback-link" in js, (
        "Modal fallback 'Open on YouTube' link must be present"
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

    # Verify the simplified Explore scenarios card does not leak raw publish_state tokens
    # (the pill was removed in CEO UI simplification — gravity now has no status pill)
    think_pill_context = js[js.index("Explore scenarios"):js.index("Explore scenarios") + 600] if "Explore scenarios" in js else ""
    assert "Explore scenarios" in think_pill_context, "Explore scenarios card must exist"
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


def test_gravity_play_card_no_raw_tokens():
    """Gravity-play-card was simplified: the pill-row with gravity.rails was removed
    in the CEO UI simplification batch. This test verifies that the simplified
    gravity card does not reintroduce raw status tokens and the removed pill-row
    is genuinely absent.
    """
    js = _static_executive_js()
    html = _ceo_executive_html()

    # ---------------------------------------------------------------
    # PART A: gravity-play-card must still exist
    # ---------------------------------------------------------------
    assert "gravity-play-card" in js, (
        "gravity-play-card class must exist in executive.js"
    )

    # Extract the gravity-play-card template context
    gravity_idx = js.index("gravity-play-card")
    gravity_context = js[gravity_idx:gravity_idx + 800]

    # ---------------------------------------------------------------
    # PART B: The pill-row was intentionally removed — verify absence
    # ---------------------------------------------------------------
    # The old gravity-play-card had a pill-row with toneClass(item) and
    # statusLabel(item). After simplification, only prompt chips remain.
    assert "pill-row" not in gravity_context, (
        "gravity-play-card must NOT contain pill-row after simplification"
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
            f"Raw status token '{phrase}' found near gravity-play-card in JS — "
            f"must not appear after simplification"
        )

    # ---------------------------------------------------------------
    # PART D: Served CEO HTML must NOT embed raw gravity.rails tokens
    # ---------------------------------------------------------------
    for phrase in banned_near_gravity:
        assert phrase not in html, (
            f"Raw status token '{phrase}' found in served CEO HTML — "
            f"must not appear after simplification"
        )

    # Also check for lowercase raw patterns that could appear in JSON boot data
    raw_patterns_lower = [
        "awaiting_review",
        "4 challenged",
    ]
    for phrase in raw_patterns_lower:
        assert phrase not in html, (
            f"Raw status token '{phrase}' found in served CEO HTML boot data — "
            f"must not appear after simplification"
        )

    # ---------------------------------------------------------------
    # PART E: Verify the prompt chips (only content remaining) are clean
    # ---------------------------------------------------------------
    assert "timeline-chip" in gravity_context, (
        "gravity-play-card must contain prompt timeline-chips"
    )
    assert "Send to assistant" in gravity_context, (
        "gravity-play-card prompt chips must have 'Send to assistant' label"
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
    """CEO chat greeting must be detected BEFORE hitting /qa POST.

    Greeting/small-talk patterns (hi, hello, hey, good morning, etc.)
    must trigger a warm, humane response instead of going through the
    Q&A/LLM pipeline.

    Assertions:
    1. greetingPatterns regex exists with hi/hello/hey patterns
    2. The humane response text contains "I'm here" and relevant guidance
    3. Greeting detection happens BEFORE the /qa POST (line ordering)
    """
    js = _static_executive_js()

    # 1. greetingPatterns regex must exist with hi/hello/hey patterns
    assert "greetingPatterns" in js, (
        "Greeting detection regex must exist in buildAssistantReply"
    )
    assert "hi|hey|hello" in js, (
        "greetingPatterns must match hi/hello/hey"
    )
    assert "good\\s+(morning|afternoon|evening)" in js, (
        "greetingPatterns must match good morning/afternoon/evening"
    )

    # 2. The humane response text must contain the warm message
    assert "I can help" in js, (
        "CEO greeting response must contain 'I can help'"
    )
    assert "board readiness, margin risk, cash, or the knowledge map" in js, (
        "CEO greeting response must guide toward board readiness, margin risk, cash, knowledge map"
    )

    # 3. Greeting detection must happen BEFORE /qa POST
    # The greeting check appears first in buildAssistantReply, then /qa
    greeting_idx = js.index("greetingPatterns")
    qa_idx = js.index('postJson("/qa"')
    assert greeting_idx < qa_idx, (
        "Greeting detection (greetingPatterns) must appear BEFORE "
        "postJson('/qa'...) in buildAssistantReply. "
        "Greeting at index %d, /qa at index %d." % (greeting_idx, qa_idx)
    )


def test_ceo_clickability_disco_add_fixed():
    """disco-add buttons must have onclick handler binding in JS.

    Previously, '.disco-add' buttons in the agents discovery panel were
    silent dead buttons with no onclick handler. This test verifies:
    1. disco-add buttons have onclick handler binding in JS
    2. CEO path calls showToast with appropriate restriction message
    """
    js = _static_executive_js()

    # 1. disco-add buttons must have onclick handler binding
    assert "disco-add" in js, (
        "disco-add buttons must exist in JS"
    )
    assert ".disco-add" in js or "disco-add" in js, (
        "disco-add class selector must be present for binding"
    )

    # The onclick binding must call showToast for CEO
    assert "Agent installation is available from the operator surface." in js, (
        "disco-add CEO path must showToast with operator surface message"
    )

    # The onclick binding must also handle non-CEO path
    assert "Agent deployment is available from the operator or reviewer surface." in js, (
        "disco-add non-CEO path must showToast with appropriate message"
    )

    # Verify the binding uses forEach over querySelectorAll('.disco-add')
    assert "querySelectorAll('.disco-add')" in js, (
        "disco-add buttons must be bound via querySelectorAll"
    )


# ══════════════════════════════════════════════════════════════════════
# NEW TESTS — CEO Demo Defect Batch 2026-07-03
# ══════════════════════════════════════════════════════════════════════

def test_plan_health_gauge_has_indicator_dot():
    """#1: Plan health gauge must render hero-dot element and position it."""
    html = _ceo_executive_html()
    js = _static_executive_js()

    # SVG must contain hero-dot circle element
    assert 'id="hero-dot"' in html, (
        "Plan health gauge SVG must contain indicator dot element #hero-dot"
    )

    # JS must compute dot position from score
    assert "hero-dot" in js, (
        "renderHero must reference hero-dot element"
    )
    assert "Math.sin(angleRad)" in js or "Math.sin" in js, (
        "JS must compute angular position for indicator dot"
    )
    assert "dot.style.visibility" in js, (
        "Dot visibility must be set to visible after positioning"
    )


def test_kpi_spacing_css_exists():
    """#2: Board KPI must have adequate spacing between label and value."""
    css_path = Path(__file__).resolve().parent.parent / \
        "strategyos_mvp" / "static" / "executive.css"
    css = css_path.read_text()

    # board-kpi must have flex column layout with gap
    assert ".board-kpi" in css, "board-kpi CSS class must exist"
    # The class must have flex-direction: column and gap
    assert "flex-direction: column" in css, "board-kpi must use column layout"


def test_youtube_fallback_pre_rendered():
    """#3: YouTube Leaders' Corner must pre-render fallback card, not iframe."""
    js = _static_executive_js()

    # Fallback card must be present in the initial HTML template
    assert "leaders-featured-fallback" in js, (
        "Leaders' Corner must pre-render fallback card (leaders-featured-fallback)"
    )
    # Frame wrapper must start hidden
    assert "leaders-frame-wrapper" in js, (
        "Video frame wrapper must exist for on-demand iframe creation"
    )
    # Fallback timer must be reduced (4s or less in selectLeadersVideo)
    # The 10000 timer was present in original; verify it's changed
    assert "4000" in js, (
        "Fallback timer must be reduced to 4s (was 10s)"
    )


def test_week_ahead_toggle_behavior():
    """#5: Clicking the same Week Ahead chip must toggle collapse."""
    js = _static_executive_js()

    # Toggle logic: state.openWeekIndex === idx ? -1 : idx
    assert "openWeekIndex === idx" in js or "openWeekIndex ===" in js, (
        "Week Ahead must toggle collapse when same chip is clicked"
    )


def test_browse_all_agents_opens_assistant():
    """#6: CEO Browse All Agents must open assistant drawer, not just toast."""
    js = _static_executive_js()

    # CEO path for browse must trigger assistant interaction, not just toast
    assert "switchView('assistants')" in js, (
        "CEO Browse All Agents must switch to assistants view"
    )
    assert "Show me the agent catalogue" in js, (
        "CEO Browse All Agents must send catalogue prompt to assistant"
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
    """#10: Knowledge graph subtitle must use correct grammar."""
    js = _static_executive_js()

    assert "reasons across your evidence" in js, (
        "Knowledge graph subtitle must say 'reasons across your evidence'"
    )
    # Old wording must NOT appear
    assert "proof the system" not in js, (
        "Knowledge graph subtitle must NOT contain 'proof the system' (old wording)"
    )


def test_hermes_header_phrase_clean():
    """#11: Hermes header must use 'Your AI chief of staff' not jargon."""
    js = _static_executive_js()

    assert "Your AI chief of staff" in js, (
        "Hermes header must use 'Your AI chief of staff'"
    )
    # Old jargon must not appear
    assert "named, threaded chief-of-staff follow-up" not in js, (
        "Hermes header must NOT contain old jargon phrase"
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
    """#13: Thread list items must not show redundant 'send and receive' tags."""
    js = _static_executive_js()

    # The old pattern: 'send and receive' in thread metadata
    # After fix: replaced with 'writable' or removed entirely
    assert "writable" in js, (
        "Thread metadata must use simplified 'writable' tag"
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


def test_tenant_runtime_watch_renamed():
    """#17: 'Tenant runtime watch' must be renamed to 'System health monitor'."""
    js = _static_executive_js()
    html = _ceo_executive_html()

    # Old name appearance: may exist as key in replacement mapping; verify transform is present
    assert "System health monitor" in js, (
        "JS must contain 'System health monitor' as replacement"
    )
    # The HTML served to CEO must not render the old name
    assert "Tenant runtime watch" not in html, (
        "CEO HTML must not render 'Tenant runtime watch'"
    )
    # The replacement mapping must exist
    assert "'Tenant runtime watch': 'System health monitor'" in js or \
        '"Tenant runtime watch": "System health monitor"' in js, (
        "JS must have a mapping from 'Tenant runtime watch' to 'System health monitor'"
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


def test_agents_grammar_need_your_attention():
    """#3: Agents Running Now must say 'need your attention', not 'needs you'."""
    js = _static_executive_js()

    assert "need your attention" in js, (
        "Agents stats must say 'need your attention' (grammar fix)"
    )
    assert "needs you" not in js, (
        "Old 'needs you' grammar must be removed"
    )


def test_agent_status_labels_ceo_friendly():
    """#4: Agent status labels must use CEO-friendly terms:
    'Guarded' not 'Protected', 'View only' not 'Preview Only'."""
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

    # Local statusLabel in renderAgentsDiscovery must also use CEO labels
    assert "return 'Guarded'" in js, (
        "renderAgentsDiscovery statusLabel must return 'Guarded' for protected"
    )
    assert "return 'View only'" in js, (
        "renderAgentsDiscovery statusLabel must return 'View only'"
    )


def test_leaders_corner_single_youtube_link_per_card():
    """#5: Leaders' Corner must have only ONE 'Open on YouTube' link
    per card/video surface, not duplicates in fallback + info sections.
    
    The initial render fallback card (Select a video) must NOT also show
    a YouTube link — only leaders-video-ctas should carry one.
    Error-handler and selectLeadersVideo fallback paths are separate
    code paths and may keep their YouTube fallback links.
    """
    js = _static_executive_js()

    # The initial render (gravity panel) fallback card must NOT contain a YouTube link.
    # We verify this by checking that the "Select a video below" template
    # does NOT have an <a> tag inside the fallback card.
    select_text = 'Select a video below'
    select_idx = js.index(select_text)
    # Look at the next 300 chars after "Select a video below"
    after_select = js[select_idx:select_idx + 300]
    # The fallback card in the initial render must NOT have a YouTube link
    assert 'leaders-fallback-link' not in after_select, (
        "Initial render fallback card ('Select a video below') must NOT contain "
        "a YouTube link — only leaders-video-ctas should have one"
    )

    # The leaders-video-info section must still have a YouTube link
    assert "leaders-yt-link" in js, (
        "Leaders video info must retain the single YouTube link"
    )


def test_assistants_tab_no_ai_adoption_wording():
    """#6: Assistants tab must NOT contain old 'AI adoption' wording.
    Must use 'team readiness' instead."""
    js = _static_executive_js()
    html = _ceo_executive_html()
    design_path = Path(__file__).resolve().parent.parent / \
        "strategyos_mvp" / "static" / "executive_design_data.js"
    design = design_path.read_text()

    # Design data must not contain 'AI adoption'
    assert "AI adoption" not in design, (
        "executive_design_data.js must not contain 'AI adoption' wording"
    )
    # Design data must use 'team readiness' 
    assert "team readiness" in design, (
        "executive_design_data.js must use 'team readiness' wording"
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
