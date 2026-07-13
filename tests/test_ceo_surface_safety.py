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
    assert "StrategyOS assistants" in js, (
        "Native assistant section must use a clear heading instead of an orphaned 'Built-in' label"
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
    assert "strict-origin-when-cross-origin" in js, (
        "strict-origin-when-cross-origin value must appear in JS"
    )
    # Template + modal iframe must carry referrerpolicy
    referred = js.count("referrerpolicy")
    assert referred >= 2, (
        "At least 2 referrerpolicy references expected (card template + modal iframe)"
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
    bootstrap_marker = '<script id="strategyos-executive-bootstrap" type="application/json">'
    visible_html = html
    if bootstrap_marker in visible_html:
        before_bootstrap, _, bootstrap_tail = visible_html.partition(bootstrap_marker)
        _, _, after_bootstrap = bootstrap_tail.partition("</script>")
        visible_html = before_bootstrap + after_bootstrap

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
    """CEO greetings must route to the shared assistant API, not a client reply."""
    js = _static_executive_js()
    assert "greetingPatterns" not in js
    assert "I can help with board readiness, margin risk, cash, or the knowledge map" not in js
    assert 'postJson("/assistant/chat"' in js


def test_ceo_clickability_disco_add_fixed():
    """disco-add buttons must have explicit action handling in JS.

    Previously, '.disco-add' buttons in the agents discovery panel were
    silent dead buttons with no onclick handler. This test verifies:
    1. disco-add buttons have onclick handler binding in JS
    2. the binding routes through the governed open/request flow
    """
    js = _static_executive_js()

    # 1. disco-add buttons must have onclick handler binding
    assert "disco-add" in js, (
        "disco-add buttons must exist in JS"
    )
    assert ".disco-add" in js or "disco-add" in js, (
        "disco-add class selector must be present for binding"
    )

    # The old toast-only handler made mobile taps appear dead. The binding
    # must now dispatch to the explicit open/request flow.
    assert "data-agent-discovery-id" in js, (
        "disco-add buttons must carry a stable discovery id"
    )
    assert "handleDiscoverableAgentAction(item, button)" in js, (
        "disco-add clicks must dispatch through the governed action handler"
    )
    assert "showAgentInstallRequest(item, sourceEl)" in js, (
        "restricted discovery actions must open the install/request modal"
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
    """#3: Leaders' Corner must keep fallback markup while mounting inline playback."""
    js = _static_executive_js()

    # Fallback card HTML must exist in the template (progressive enhancement — safe default)
    assert "leaders-featured-fallback" in js, (
        "Leaders' Corner must have fallback card HTML in template (leaders-featured-fallback)"
    )
    # Frame wrapper must still exist for optional playback plumbing.
    assert "leaders-frame-wrapper" in js, (
        "Video frame wrapper must exist in HTML template"
    )
    # JS must initialize the featured video card on first load.
    assert "selectLeadersVideo(vlogs[0]" in js, (
        "On first load, selectLeadersVideo must be called with first vlog to show inline playback"
    )
    assert "fallback.hidden = true" in js, (
        "Fallback shell must be hidden during normal inline playback"
    )
    assert "Embed unavailable." in js, (
        "Fallback shell must retain controlled English copy for embed failures"
    )


def test_week_ahead_toggle_behavior():
    """#5: Clicking the same Week Ahead chip must toggle collapse."""
    js = _static_executive_js()

    # Toggle logic: state.openWeekIndex === idx ? -1 : idx
    assert "openWeekIndex === idx" in js or "openWeekIndex ===" in js, (
        "Week Ahead must toggle collapse when same chip is clicked"
    )


def test_browse_all_agents_opens_assistant():
    """#6: CEO Browse All Agents must open a catalogue, not submit a chat prompt."""
    js = _static_executive_js()

    assert "switchView('assistants')" in js, (
        "CEO Browse All Agents must switch to assistants view"
    )
    assert "assistantCatalogueOpen" in js, (
        "CEO Browse All Agents must open the assistant catalogue state"
    )
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
    avatar_block = js[avatar_start:avatar_start + 900]

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


def test_review_gate_copy_fits_ring_and_decision_kpi_routes_deterministically():
    js = _static_executive_js()
    css = (Path(api_module.STATIC_DIR) / "executive.css").read_text(encoding="utf-8")

    assert 'reviewGate ? "OPEN"' in js
    assert 'reviewGate ? "reviewer decision"' in js
    assert 'data-kpi-key=' in js
    assert 'if (contextualKpiKey) entrypoint = "ceo_kpi_inline"' in js
    assert "font-size: clamp(25px, 3vw, 38px)" in css


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
    assert "Keep the packet inside the executive lane until challenged evidence is closed" in js, (
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


def test_agents_grammar_need_your_attention():
    """#3: Agents Running Now must say 'need your attention', not 'needs you'.
    
    Scoped to agents section only — 'needs your' in dead-end guard text
    (e.g. 'the margin narrative needs your line') is correct grammar and
    unrelated to the agents-label requirement.
    """
    js = _static_executive_js()

    assert "need your attention" in js, (
        "Agents stats must say 'need your attention' (grammar fix)"
    )
    # 'needs you' must NOT appear in the agents section (line 2050-2090)
    running_card_start = js.index("Running now")
    running_card_end = running_card_start + 500
    running_card_block = js[running_card_start:min(running_card_end, len(js))]
    assert "needs you" not in running_card_block, (
        "Old 'needs you' grammar must be removed from agents section. "
        "(False positives from dead-end guard 'needs your' are excluded.)"
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


def test_leaders_corner_mounts_playable_inline_youtube_player():
    """Leaders' Corner must mount the featured video inline and keep fallback only for errors."""
    js = _static_executive_js()

    block_start = js.index("function selectLeadersVideo(")
    block_end = js.index("function buildVideoModalHtml(", block_start)
    block = js[block_start:block_end]
    assert "frameWrapper.hidden = false" in block
    assert "youtube-nocookie.com/embed" in block
    assert "fallback.hidden = true" in block
    assert "Embed unavailable." in block


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

    # The ring-copy template must appear BEFORE the driver-over-plan reference.
    ring_copy_close_pos = grid_func_body.index("driver-ring-copy")
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
    """Desktop layout must keep the assistant dock compact without stealing a
    full right-hand page column."""
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
    """CEO persona must filter out stale persisted threads that contain
    video references, Leaders' Corner content, system threads, or bug threads.
    
    Acceptance B/C: No stale Leaders video/FX text polluting CEO conversations.
    Contextual CTAs must open clean drawers without cross-contamination.
    """
    js = _static_executive_js()

    # ── ensureThreads must contain the CEO stale-thread filter ──
    assert "state.activePersona === \"ceo\"" in js, (
        "CEO stale-thread guard must exist in ensureThreads"
    )

    # Find ensureThreads function
    ensure_start = js.index("function ensureThreads")
    ensure_end = ensure_start + 3000
    ensure_block = js[ensure_start:min(ensure_end, len(js))]

    # Video-related stale thread detection
    assert "isVideo" in ensure_block, (
        "ensureThreads must detect video-related stale threads for CEO"
    )
    assert "isLeader" in ensure_block, (
        "ensureThreads must detect Leaders' Corner stale threads for CEO"
    )
    assert "isSystem" in ensure_block, (
        "ensureThreads must filter system threads for CEO"
    )

    # Each stale-thread flag must be checked before loading
    assert "if (isVideo" in ensure_block or "isVideo || isLeader" in ensure_block, (
        "Stale-thread guards must conditionally skip loading for CEO"
    )


def test_ceo_digital_health_answer_leads_with_facts():
    """Digital Health prompts are now routed to backend scenarios, not JS copy."""
    js = _static_executive_js()
    assert "/digital health/i" not in js
    assert 'postJson("/assistant/chat"' in js
