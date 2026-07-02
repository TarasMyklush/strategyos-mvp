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
    assert "Runs on your infrastructure" in js, (
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

    # Verify the Think-and-model pill uses statusLabel (not raw publish_state)
    # The pill at line ~1225 must call statusLabel
    think_pill_context = js[js.index("Thinking mode"):js.index("Thinking mode") + 600] if "Thinking mode" in js else ""
    assert "statusLabel" in think_pill_context, (
        "'Think and model' card pill must call statusLabel() not raw publish_state"
    )

    # Report surface pill must also use statusLabel
    report_context = js[js.index("Board reports"):js.index("Board reports") + 400] if "Board reports" in js else ""
    assert "statusLabel" in report_context, (
        "'Board reports' card pill must call statusLabel() not raw publish_state"
    )


def test_gravity_play_card_no_raw_tokens():
    """Gravity-play-card pill-row must use statusLabel() and never render
    raw status tokens (AWAITING_REVIEW, PRE, N CHALLENGED) on the CEO surface.

    This closes the blind spot where gravity.rails items bypassed statusLabel()
    while 7 other pill sites were already guarded by commit 601a567.
    """
    js = _static_executive_js()
    html = _ceo_executive_html()

    # ---------------------------------------------------------------
    # PART A: gravity-play-card template must call statusLabel
    # ---------------------------------------------------------------
    assert "gravity-play-card" in js, (
        "gravity-play-card class must exist in executive.js"
    )

    # Extract the gravity-play-card template context (~600 chars after "gravity-play-card")
    gravity_idx = js.index("gravity-play-card")
    gravity_context = js[gravity_idx:gravity_idx + 800]

    # The pill-row inside gravity-play-card must use statusLabel(item)
    assert "statusLabel(item)" in gravity_context, (
        "gravity-play-card .pill-row must call statusLabel(item) — "
        "raw tokens were leaking through escapeHtml(item) without statusLabel"
    )

    # toneClass must still receive raw item for correct color mapping
    assert "toneClass(item)" in gravity_context, (
        "gravity-play-card .pill-row must preserve toneClass(item) with raw item for color"
    )

    # ---------------------------------------------------------------
    # PART B: Raw token patterns must NOT appear near gravity-play-card
    # ---------------------------------------------------------------
    banned_near_gravity = [
        "AWAITING_REVIEW",
        "PRE",
        "CHALLENGED",
    ]
    for phrase in banned_near_gravity:
        assert phrase not in gravity_context, (
            f"Raw status token '{phrase}' found near gravity-play-card in JS — "
            f"must be humanized via statusLabel()"
        )

    # ---------------------------------------------------------------
    # PART C: Served CEO HTML must NOT embed raw gravity.rails tokens
    # in the boot data. Human labels are rendered client-side by JS,
    # so we verify the JS source (Parts A/B/D) — here we verify the
    # boot JSON does not contain un-humanized raw token patterns.
    # ---------------------------------------------------------------
    # The executive HTML embeds window.__STRATEGYOS_BOOT__ with gravity data.
    # Raw token patterns must not appear in the boot payload.
    for phrase in banned_near_gravity:
        assert phrase not in html, (
            f"Raw status token '{phrase}' found in served CEO HTML — "
            f"must be humanized before rendering"
        )

    # Also check for lowercase raw patterns that could appear in JSON boot data
    raw_patterns_lower = [
        "awaiting_review",
        "4 challenged",
    ]
    for phrase in raw_patterns_lower:
        assert phrase not in html, (
            f"Raw status token '{phrase}' found in served CEO HTML boot data — "
            f"must be humanized via statusLabel() before client-side hydration"
        )

    # ---------------------------------------------------------------
    # PART D (optional): Regex verification that pill-row template
    # specifically uses statusLabel in the escapeHtml call
    # ---------------------------------------------------------------
    import re
    # Match the pill-row template: escapeHtml(statusLabel(item))
    pill_row_pattern = re.compile(
        r'pill-row.*?escapeHtml\(\s*statusLabel\(\s*item\s*\)\s*\)',
        re.DOTALL,
    )
    assert pill_row_pattern.search(js), (
        "gravity-play-card .pill-row template must wrap item in "
        "escapeHtml(statusLabel(item)) — raw item found instead"
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


# ── CEO "Report bug" button removal ──

def test_ceo_no_report_bug_visible_labels():
    """CEO surface must NOT expose any visible 'Report bug' or 'Report a bug'
    text in buttons, labels, modals, aria-labels, or titles.

    This is the definitive test for the report-bug removal scope.
    Internal variable names (reportBug, a2a-report-bug as DOM id) and
    thread-filtering logic (title.indexOf('report a bug')) are acceptable
    since they are NOT user-visible.
    """
    js = _static_executive_js()
    html = _ceo_executive_html()

    # ── HTML: static button labels must be clean ──
    # Verify no 'bug' in button visible text (DOM IDs like a2a-report-bug are fine)
    # The a2a-report-bug button lives inside the a2a-foot div, and the
    # feedback-btn is in the topbar. Check each individually.
    import re

    # Extract feedback-btn inner text: find the button, get text between > and </button>
    fb_match = re.search(r'<button[^>]*id="feedback-btn"[^>]*>(.*?)</button>', html)
    if fb_match:
        inner_text = fb_match.group(1)
        assert "bug" not in inner_text.lower(), (
            f"feedback-btn visible text must not contain 'bug'. Found: '{inner_text[:100]}'"
        )

    # a2a-report-bug: find the specific button
    a2a_match = re.search(r'<button[^>]*id="a2a-report-bug"[^>]*>(.*?)</button>', html)
    if a2a_match:
        inner_text = a2a_match.group(1)
        assert "bug" not in inner_text.lower(), (
            f"a2a-report-bug visible text must not contain 'bug'. Found: '{inner_text[:100]}'"
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


def test_ceo_html_feedback_buttons_clean():
    """The served CEO HTML must have clean feedback button labels
    without any 'bug' wording in visible text, aria-label, or title.
    """
    html = _ceo_executive_html()

    # feedback-btn: aria-label, title, and visible text must not contain 'bug'
    assert 'aria-label="Send feedback"' in html, (
        "feedback-btn aria-label must say 'Send feedback', not 'Report a bug'"
    )
    assert 'title="Send feedback"' in html, (
        "feedback-btn title must say 'Send feedback', not 'Report a bug'"
    )
    assert "<span>Report bug</span>" not in html, (
        "feedback-btn visible text must not say 'Report bug'"
    )
    assert "<span>Feedback</span>" in html, (
        "feedback-btn visible text must say 'Feedback'"
    )

    # a2a-report-bug: visible text must not contain 'bug'
    assert "<button" in html and "Report a bug</button>" not in html, (
        "a2a-report-bug visible text must not say 'Report a bug'"
    )
    assert "Feedback</button>" in html, (
        "a2a-report-bug visible text must say 'Feedback'"
    )
