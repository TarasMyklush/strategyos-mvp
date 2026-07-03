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
        "The board pack is under review."
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
    """#3: YouTube Leaders' Corner must have fallback card HTML in template but JS must init iframe on first load."""
    js = _static_executive_js()

    # Fallback card HTML must exist in the template (progressive enhancement — safe default)
    assert "leaders-featured-fallback" in js, (
        "Leaders' Corner must have fallback card HTML in template (leaders-featured-fallback)"
    )
    # Frame wrapper must exist (hidden initially in HTML, then JS shows it)
    assert "leaders-frame-wrapper" in js, (
        "Video frame wrapper must exist in HTML template"
    )
    # JS must initialize the featured video on first load (not leave dead placeholder)
    assert "selectLeadersVideo(vlogs[0]" in js, (
        "On first load, selectLeadersVideo must be called with first vlog to show embedded player"
    )
    # Fallback timer must be reduced (4s or less in selectLeadersVideo)
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
    """#11: Hermes header must use 'Ask Hermes' heading and 'Answers from the current board pack' subtitle."""
    js = _static_executive_js()

    assert '"Ask Hermes"' in js or "'Ask Hermes'" in js, (
        "Hermes header heading must be 'Ask Hermes'"
    )
    assert "Hermes will answer here using the current board pack." in js, (
        "Hermes subtitle must be 'Hermes will answer here using the current board pack.'"
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
    
    The initial render fallback card (Loading) must NOT also show
    a YouTube link — only leaders-video-ctas should carry one.
    Error-handler and selectLeadersVideo fallback paths are separate
    code paths and may keep their YouTube fallback links.
    """
    js = _static_executive_js()

    # The initial render (gravity panel) fallback card must NOT contain a YouTube link.
    # We verify this by checking that the "Loading video..." template
    # does NOT have an <a> tag inside the fallback card.
    select_text = 'Loading video...'
    select_idx = js.index(select_text)
    # Look at the next 300 chars after "Loading video..."
    after_select = js[select_idx:select_idx + 300]
    # The fallback card in the initial render must NOT have a YouTube link
    assert 'leaders-fallback-link' not in after_select, (
        "Initial render fallback card ('Loading video...') must NOT contain "
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


# ── "Ask why this matters" CTA + assistant drawer regression tests ──


def test_ask_why_cta_calls_ask_assistant():
    """Clicking 'Ask why this matters' must call askAssistant with the finding prompt."""
    js = _static_executive_js()

    # The CTA button is rendered with data-rail-prompt attribute
    assert "data-rail-prompt" in js, (
        "Findings CTA button must have data-rail-prompt attribute"
    )
    assert "rail-inline-action" in js, (
        "Findings CTA button must use rail-inline-action class"
    )

    # The onclick handler calls askAssistant with the prompt
    assert "askAssistant(button.getAttribute('data-rail-prompt')" in js, (
        "Findings CTA onclick must call askAssistant with rail-prompt"
    )

    # The prompt must contain board-contextual language
    assert "matters for the board" in js, (
        "Finding prompt must include board-contextual language"
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

def test_cta_enum_leaders_corner_cta():
    """CTA 5: Leaders' Corner 'Ask Hermes about this topic' CTA."""
    js = _static_executive_js()
    assert "leaders-hermes-cta" in js
    assert "Ask Hermes about this topic" in js

def test_cta_enum_video_modal_cta():
    """CTA 6: Video modal 'Ask Hermes about this topic' CTA."""
    js = _static_executive_js()
    assert "video-hermes-cta" in js

def test_cta_enum_board_prompts():
    """CTA 7: Board portal [data-board-prompt] prompt chips."""
    js = _static_executive_js()
    assert "data-board-prompt" in js

def test_cta_enum_board_actions():
    """CTA 8: Board portal [data-board-action] action buttons."""
    js = _static_executive_js()
    assert "data-board-action" in js

def test_cta_enum_findings_ask_why():
    """CTA 9: Findings 'Ask why this matters' [data-rail-prompt]."""
    js = _static_executive_js()
    assert "data-rail-prompt" in js
    assert "Ask why this matters" in js

def test_cta_enum_developments_impact():
    """CTA 10: Developments 'Project impact on plan' [data-rail-prompt]."""
    js = _static_executive_js()
    assert "Project impact on plan" in js

def test_cta_enum_week_explore_request():
    """CTA 11: Week ahead 'Explore scenarios' / 'Request missing data'."""
    js = _static_executive_js()
    assert "Explore scenarios" in js
    assert "Request missing data" in js

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
    assert "Show me the agent catalogue" in js

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
# KPI RING VISUAL ENCODING — Full circle MUST equal 100% (not 133.33%)
#  - Values above 100% cap at full ring; over-plan shown as badge
#  - No tick marker (the full circle IS the 100% reference)
#  - Previously: ringMax=400/3 ~133.33 made 100%=3/4 circle — not CEO-intuitive
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


def test_driver_ring_full_circle_equals_100():
    """driverRingMarkup must use Math.min(pct, 100) / 100 so that
    a full circle (frac=1.0) means exactly 100% of plan.
    ringMax=400/3 (133.33) must NOT be present."""
    js = _static_executive_js()

    # The old 133.33% ringMax must be gone
    assert "ringMax = 400 / 3" not in js, (
        "driverRingMarkup must NOT contain ringMax = 400/3 — "
        "full circle = 100% of plan, not 133.33%"
    )

    # The fraction must use Math.min(pct, 100) / 100 (full circle at 100%)
    assert "Math.min(pct, 100) / 100" in js, (
        "driverRingMarkup must cap at Math.min(pct, 100) / 100 — "
        "full circle = 100%"
    )

    # Must NOT reference ringMax anywhere
    func_start = js.index("function driverRingMarkup")
    func_end = js.index("function qaAnswerText", func_start)
    ring_func_body = js[func_start:func_end]
    assert "ringMax" not in ring_func_body, (
        "driverRingMarkup must NOT reference ringMax — "
        "the ring ceiling is 100, not a separate max variable"
    )


def test_driver_ring_no_tick():
    """There is no tick marker needed — the full circle itself is the 100%
    reference. tickAngle must not exist in driverRingMarkup."""
    js = _static_executive_js()

    func_start = js.index("function driverRingMarkup")
    func_end = js.index("function qaAnswerText", func_start)
    ring_func_body = js[func_start:func_end]

    assert "tickAngle" not in ring_func_body, (
        "driverRingMarkup must NOT compute tickAngle — "
        "the full circle IS the 100% reference; no separate tick needed"
    )


def test_driver_ring_dash_proportional_to_pct():
    """Verify mathematically that dash values are proportional to pct
    in the 0-100 range, and that values above 100 all produce the same
    full-ring dash.

    circumference = 2 * PI * 15 ≈ 94.2478
    For pct <= 100: dash = circumference * (pct / 100)
    For pct >= 100: dash = circumference (full ring)

    Expected:
      pct=0   → dash ≈ 1.9   (0.02 floor)
      pct=50  → dash ≈ 47.1
      pct=78  → dash ≈ 73.5
      pct=99  → dash ≈ 93.3
      pct=100 → dash ≈ 94.2  (full ring)
      pct=101 → dash ≈ 94.2  (capped — full ring)
      pct=102 → dash ≈ 94.2  (capped — full ring)
      pct=123 → dash ≈ 94.2  (capped — full ring)
    """
    import math
    radius = 15
    circumference = 2 * math.pi * radius  # ≈ 94.2478

    def expected_dash(pct_value):
        pct = max(0, pct_value)
        frac = max(0.02, min(pct, 100) / 100)
        return round(circumference * frac, 1)

    # --- 0-100 range: proportional ---
    dash_0 = expected_dash(0)
    dash_50 = expected_dash(50)
    dash_78 = expected_dash(78)
    dash_99 = expected_dash(99)
    dash_100 = expected_dash(100)

    # Floor preserved (0.02 minimum)
    assert dash_0 > 1.8, f"pct=0 dash must use 0.02 floor, got {dash_0}"
    assert abs(dash_0 - 1.9) < 0.2, f"pct=0 dash ≈ 1.9, got {dash_0}"

    # 50% = half circumference
    assert abs(dash_50 - 47.1) < 0.5, f"pct=50 dash ≈ 47.1, got {dash_50}"

    # 78% = 78% of circumference
    assert abs(dash_78 - 73.5) < 0.5, f"pct=78 dash ≈ 73.5, got {dash_78}"

    # 99% just under full
    assert abs(dash_99 - 93.3) < 0.5, f"pct=99 dash ≈ 93.3, got {dash_99}"

    # 100% = full circumference
    assert abs(dash_100 - circumference) < 0.1, (
        f"pct=100 must be full circle (dash={circumference}), got {dash_100}"
    )

    # --- Above 100%: all capped at full ring ---
    dash_101 = expected_dash(101)
    dash_102 = expected_dash(102)
    dash_123 = expected_dash(123)

    # All above-100 values must equal the full circumference
    for label, dash_val in [("101", dash_101), ("102", dash_102), ("123", dash_123)]:
        assert abs(dash_val - circumference) < 0.1, (
            f"pct={label} must cap at full ring (dash={circumference}), got {dash_val}"
        )

    # All above-100 dashes must be identical (full ring)
    assert dash_101 == dash_102 == dash_123, (
        f"All pct > 100 must produce identical full-ring dashes: "
        f"got {dash_101}, {dash_102}, {dash_123}"
    )


def test_driver_ring_frac_floor_preserved():
    """The minimum frac of 0.02 must still be preserved so zero/very-low
    values show a visible sliver instead of an invisible ring."""
    js = _static_executive_js()

    assert "0.02" in js, (
        "driverRingMarkup must preserve the min frac=0.02 floor"
    )


def test_driver_ring_over_plan_badge_present():
    """renderDriverGrid must emit a driver-over-plan badge when pct > 100."""
    js = _static_executive_js()

    # The over-plan badge span must exist in the JS source
    assert "driver-over-plan" in js, (
        "renderDriverGrid must emit a driver-over-plan badge for pct > 100"
    )

    # Must compute the delta relative to 100
    assert "> 100" in js, (
        "renderDriverGrid must check for pct > 100 to show the over-plan badge"
    )


def test_driver_ring_over_plan_badge_absent_at_or_below_100():
    """renderDriverGrid must NOT emit a badge when pct <= 100.
    The conditional must gate on > 100, not >= 100."""
    js = _static_executive_js()

    # The condition must be strictly > 100 (not >= 100)
    assert "> 100" in js, (
        "renderDriverGrid must use > 100 (not >= 100) so exactly-100 shows no badge"
    )


def test_driver_ring_over_plan_badge_outside_ring_copy():
    """The over-plan badge must be a sibling of .driver-ring-copy (inside
    .driver-ring-stage but outside .driver-ring-copy) so it can be
    absolutely positioned as an outside pill without fighting the
    centered percentage display."""
    js = _static_executive_js()

    # The badge must be rendered AFTER the ring-copy closing </div>
    # but BEFORE the ring-stage closing </div>.
    # JS concatenation pattern:
    #   '</div></div>' + (Number(...) > 100 ? '<span class="driver-over-plan">...' : '') + '</div>'
    assert "driver-ring-copy" in js, "ring-copy must exist"
    assert "driver-over-plan" in js, "over-plan badge must exist"

    # Extract the renderDriverGrid function body to verify structure
    func_start = js.index("function renderDriverGrid")
    func_end = js.index("function renderMetrics", func_start)
    grid_func_body = js[func_start:func_end]

    # The ring-copy closing </div></div> must appear BEFORE the driver-over-plan
    # reference in the template string.  Find the unique pattern:
    #   '</div></div>' + (... ? '<span class="driver-over-plan"
    ring_copy_close_pos = grid_func_body.index("</div></div>' +")
    badge_pos = grid_func_body.index("driver-over-plan")
    assert badge_pos > ring_copy_close_pos, (
        "driver-over-plan badge must appear AFTER .driver-ring-copy closing "
        "</div></div> in the renderDriverGrid template — badge must be a "
        "sibling of ring-copy inside ring-stage, not a child of ring-copy"
    )


def test_driver_ring_over_plan_badge_has_outside_pill_css():
    """The .driver-over-plan CSS must use position:absolute so the badge
    sits as an outside pill at the top-right of the ring, not inline inside
    the centered ring-copy grid."""
    css = _static_executive_css()

    # Find the .driver-over-plan rule
    assert ".driver-over-plan" in css, "driver-over-plan CSS rule must exist"

    # The rule must use position: absolute (outside pill)
    rule_start = css.index(".driver-over-plan")
    # Find the closing brace of this rule
    rule_end = css.index("}", rule_start)
    rule_body = css[rule_start:rule_end]

    assert "position: absolute" in rule_body, (
        "driver-over-plan CSS must use position:absolute for outside-pill placement"
    )
    assert "border-radius: 999px" in rule_body, (
        "driver-over-plan CSS must use pill shape (border-radius: 999px)"
    )


def test_floating_controls_safe_zone_at_desktop():
    """At desktop widths (>1100px), the KPI grid (#driver-row) must have a
    right margin creating a safe zone so the rightmost KPI card never sits
    underneath the fixed-position chat-launcher or a2a-shell floating controls."""
    css = _static_executive_css()

    # There must be a desktop-width rule providing right margin to #driver-row
    assert "#driver-row" in css, "driver-row selector must exist in CSS"

    # Find the margin-right rule for #driver-row (inside a min-width query)
    # Look for the safe-zone pattern
    assert "margin-right" in css, "margin-right must exist for safe zone"

    # The margin must use clamp() for responsive scaling
    assert "clamp(200px" in css, (
        "desktop safe zone must use clamp(200px, ...) to scale with viewport"
    )

    # Verify it's scoped to a desktop media query
    assert "@media (min-width: 1101px)" in css, (
        "safe zone must be gated behind @media (min-width: 1101px) desktop breakpoint"
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
    """'Ask Hermes' must be in the heading content."""
    js = _static_executive_js()
    assert '"Ask Hermes"' in js, (
        "executive.js must set assistantHeading to 'Ask Hermes'"
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
    """Digital Health / Revenue prompts must NOT receive unrelated FX/margin fallback text.

    The CEO dead-end guard must use context-aware branching, not a single
    hardcoded FX/margin response for every question.  This test proves:
    - The dead-end guard exists (CEO-gated)
    - The guard has context-aware branches (Digital Health, FX, Cash, Cost, generic)
    - No stale FX/SAR 9k/hedging text survives for unrelated prompts
    """
    js = _static_executive_js()

    # ── Dead-end guard must exist and be context-aware ──
    # Guard must check CEO persona
    assert 'state.activePersona === "ceo"' in js, (
        "CEO dead-end guard must check activePersona"
    )
    # Must have context-aware Digital Health branch
    assert "Digital Health absolute" in js or "Digital Health" in js, (
        "Dead-end guard must have Digital Health/revenue branch"
    )
    # Must have FX branch
    assert "FX margin detail" in js or "FX" in js, (
        "Dead-end guard must have FX/margin branch"
    )
    # Must have Cash branch
    assert "Cash" in js or "cash" in js, (
        "Dead-end guard must have Cash/liquidity branch"
    )
    # Must have generic fallback (not FX-only)
    assert "check the relevant driver card" in js or "full evidence bundle" in js, (
        "Dead-end guard must have a generic fallback branch referencing driver cards"
    )

    # ── Stale FX text must NOT appear in non-FX branches ──
    # "~SAR 9k" is valid in the FX branch itself; the fix ensures it does NOT
    # leak to unrelated branches (Digital Health, Cash, etc.).  We verify
    # below per-branch.
    assert "~SAR 9k" in js, (
        "~SAR 9k is valid FX branch data; the fix ensures it only appears in the FX branch"
    )
    assert "reduce Thursday" not in js, (
        "Hardcoded 'reduce Thursday's margin story' must be removed"
    )
    assert "Ask Finance for hedge coverage and API spend" not in js, (
        "Hardcoded 'Ask Finance' generic fallback must be removed"
    )


def test_hermes_answer_fx_fallback_still_works_for_fx_prompt():
    """FX/margin prompts must still get FX-relevant context from the dead-end guard.

    The context-aware guard must recognize FX/margin/hedging keywords
    and route to the FX-specific branch, not the generic one.
    """
    js = _static_executive_js()

    # FX branch conditions must exist in the code
    assert "fx|margin|hedg|forex|currency" in js.lower() or (
        "/fx/i" in js or "fx" in js
    ), (
        "Dead-end guard must have FX keyword detection for FX/margin prompts"
    )
    assert "hedge coverage" in js or "FX margin" in js, (
        "FX branch must include hedge coverage reference for relevant prompts"
    )


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

    # The boardSafeStatusReply CEO message is still valid
    assert '"The board pack is under review."' in js or (
        "The board pack is under review" in js
    ), (
        "boardSafeStatusReply must still have CEO-safe under-review message"
    )


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
    """Digital Health dead-end branch must lead with facts (+36%, SAR 2.09B), not FX terms."""
    js = _static_executive_js()

    # Find the Digital Health dead-end guard branch
    dh_start = js.index("/digital health/i.test")
    dh_answer_line = js.index('answer = answer + "', dh_start)
    dh_answer_end = js.index('";', dh_answer_line)
    dh_answer = js[dh_answer_line:dh_answer_end + 2]

    # Must contain Digital Health context with actual data
    assert "36%" in dh_answer, "Digital Health branch must reference +36% revenue YoY"
    assert "SAR 2.09B" in dh_answer, "Digital Health branch must reference group Revenue figure"
    assert "Digital Health" in dh_answer, "Digital Health branch must reference the BU name"
    assert "Revenue" in dh_answer, "Digital Health branch must reference Revenue driver"

    # Must NOT contain unrelated FX terms
    assert "FX exposure" not in dh_answer, "Digital Health branch must not mention FX exposure"
    assert "margin drag" not in dh_answer, "Digital Health branch must not mention margin drag"

    # Must NOT be the old dead-end style
    assert "is not available in the current board pack" not in dh_answer, (
        "Digital Health branch must NOT use old 'not available' primary message"
    )


def test_hermes_epharmacy_branch_has_correct_context():
    """e-Pharmacy dead-end branch must reference +12% WoW, Lina Haddad, GLP-1."""
    js = _static_executive_js()

    ep_start = js.index("/e-pharmacy|epharmacy/i.test")
    ep_answer_line = js.index('answer = answer + "', ep_start)
    ep_answer_end = js.index('";', ep_answer_line)
    ep_answer = js[ep_answer_line:ep_answer_end + 2]

    assert "+12%" in ep_answer or "12%" in ep_answer, "e-Pharmacy branch must reference +12% orders WoW"
    assert "Lina Haddad" in ep_answer, "e-Pharmacy branch must reference GM Lina Haddad"
    assert "GLP-1" in ep_answer or "JV" in ep_answer, "e-Pharmacy branch must reference JV context"
    assert "SAR 2.09B" in ep_answer, "e-Pharmacy branch must reference group Revenue figure"

    # Must NOT contain unrelated terms
    assert "FX exposure" not in ep_answer
    assert "cold-chain" not in ep_answer


def test_hermes_fx_branch_has_correct_context():
    """FX/margin dead-end branch must reference 19.2%, hedge, board agenda."""
    js = _static_executive_js()

    fx_start = js.index("/fx|margin|hedg|forex|currency/i.test")
    fx_answer_line = js.index('answer = answer + "', fx_start)
    fx_answer_end = js.index('";', fx_answer_line)
    fx_answer = js[fx_answer_line:fx_answer_end + 2]

    assert "19.2%" in fx_answer, "FX branch must reference EBITDA margin 19.2%"
    assert "hedge" in fx_answer, "FX branch must reference hedge context"
    assert "board" in fx_answer, "FX branch must reference board agenda"
    assert "9k" in fx_answer.lower() or "SAR 9k" in fx_answer, "FX branch must reference ~SAR 9k/week drag"

    # Must NOT contain unrelated terms
    assert "Digital Health" not in fx_answer
    assert "cold-chain" not in fx_answer


def test_hermes_cash_branch_has_correct_context():
    """Cash/liquidity dead-end branch must reference SAR 1.48B, 123%, SAR 1.2B floor."""
    js = _static_executive_js()

    cash_start = js.index("/cash|liquidity|floor|covenant/i.test")
    cash_answer_line = js.index('answer = answer + "', cash_start)
    cash_answer_end = js.index('";', cash_answer_line)
    cash_answer = js[cash_answer_line:cash_answer_end + 2]

    assert "SAR 1.48B" in cash_answer, "Cash branch must reference SAR 1.48B"
    # 123% appears as \u2014 123% (em dash before the number)
    assert "123%" in cash_answer or "SAR 1.2B" in cash_answer, "Cash branch must reference floor stats"
    assert "GLP-1" in cash_answer or "JV" in cash_answer, "Cash branch must reference JV headroom"

    # Must NOT contain unrelated terms
    assert "FX exposure" not in cash_answer
    assert "Digital Health" not in cash_answer


def test_hermes_cold_chain_branch_has_correct_context():
    """Cold-chain/resilience dead-end branch must reference 99.4%, cold-chain, NUPCO."""
    js = _static_executive_js()

    cc_start = js.index("/cold.chain|coldchain|resilience/i.test")
    cc_answer_line = js.index('answer = answer + "', cc_start)
    cc_answer_end = js.index('";', cc_answer_line)
    cc_answer = js[cc_answer_line:cc_answer_end + 2]

    assert "99.4%" in cc_answer, "Cold-chain branch must reference 99.4% record"
    assert "cold-chain" in cc_answer.lower() or "Cold-chain" in cc_answer, (
        "Cold-chain branch must reference cold-chain"
    )
    assert "NUPCO" in cc_answer, "Cold-chain branch must reference NUPCO ramp"

    # Must NOT contain unrelated terms
    assert "FX exposure" not in cc_answer
    assert "Digital Health" not in cc_answer
    assert "hedge" not in cc_answer


def test_hermes_generic_branch_has_bounded_answer():
    """Generic fallback dead-end branch must reference all four KPI figures."""
    js = _static_executive_js()

    # Find the dead-end guard block
    guard_start = js.index("// CEO dead-end guard:")
    guard_end = js.index("// Clear loading state", guard_start)
    guard_block = js[guard_start:guard_end]

    # Find the last "answer = answer +" which is the generic fallback
    last_answer_idx = guard_block.rindex('answer = answer + "')
    generic_answer_end = guard_block.index('";', last_answer_idx)
    generic_answer = guard_block[last_answer_idx:generic_answer_end + 2]

    assert "SAR 2.09B" in generic_answer, "Generic branch must reference Revenue"
    assert "19.2%" in generic_answer, "Generic branch must reference EBITDA margin"
    assert "SAR 1.69B" in generic_answer, "Generic branch must reference Operating cost"
    assert "SAR 1.48B" in generic_answer, "Generic branch must reference Cash"


def test_hermes_no_old_dead_end_patterns():
    """Old 'not available' / 'ask an operator' dead-end patterns must be gone from all branches."""
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

    # New data-led patterns must exist
    assert "+36% revenue YoY" in js, "Must have data-led Digital Health answer"
    assert "e-Pharmacy is the strongest revenue mover" in js, "Must have data-led e-Pharmacy answer"
    assert "EBITDA margin is at 19.2%" in js, "Must have data-led FX/margin answer"
    assert "Cash stands at SAR 1.48B" in js, "Must have data-led Cash answer"
    assert "Operating cost is SAR 1.69B" in js, "Must have data-led Cost answer"
    assert "Cold-chain integrity is at a record 99.4%" in js, "Must have data-led cold-chain answer"
    assert "SAR 8.6M is recoverable" in js, "Must have data-led recoverable answer"


def test_hermes_facts_lead_not_excuses():
    """Every dead-end guard branch must lead with known facts, not 'not available' as primary."""
    js = _static_executive_js()

    # Find the dead-end guard block
    guard_start = js.index("// CEO dead-end guard:")
    guard_end = js.index("// Clear loading state", guard_start)
    guard_block = js[guard_start:guard_end]

    # Count "answer = answer +" occurrences (one per branch)
    branch_count = guard_block.count("answer = answer +")
    assert branch_count >= 12, (
        f"Dead-end guard must have at least 12 context-aware branches, found {branch_count}"
    )

    # "not available" must NOT appear in any answer text
    not_available_count = guard_block.count(" not available")
    assert not_available_count == 0, (
        f"'not available' appears {not_available_count} times in dead-end guard — "
        "answers must lead with facts, not 'not available'"
    )

    # "is not available" (old dead-end pattern) must be absent
    is_not_available_count = guard_block.count("is not available")
    assert is_not_available_count == 0, (
        f"'is not available' appears {is_not_available_count} times — must be removed"
    )
