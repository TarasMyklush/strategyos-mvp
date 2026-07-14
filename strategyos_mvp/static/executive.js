(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var bootstrapScript = $("strategyos-executive-bootstrap");
  var bootstrap = bootstrapScript ? JSON.parse(bootstrapScript.textContent) : {};
  if (bootstrap.environment) {}
  if (bootstrap.api_auth_enabled) {}
  var _tokenKey = "strategyos.ui.token";
  var ASSISTANT_ENDPOINT = "/assistant/chat";
  var ASSISTANT_TRANSPORT_FALLBACK = "I couldn't reach the shared assistant service just now.";
  var BOOTSTRAP_ASSISTANT_CONTEXT = bootstrap.assistant_public_context || {};
  var _leadersFallbackTimer = null;

  // PostMessage listener for YouTube embed error detection (faster than timeout)
  window.addEventListener('message', function (event) {
    if (event.origin !== 'https://www.youtube-nocookie.com') return;
    try {
      var data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
      if (data && data.event === 'onError') {
        var frame = document.getElementById('leaders-featured-iframe');
        if (frame) {
          if (_leadersFallbackTimer) { window.clearTimeout(_leadersFallbackTimer); _leadersFallbackTimer = null; }
          var wrapper = frame.parentNode;
          var vidMatch = frame.src && frame.src.match(/\/embed\/([^/?]+)/);
          var vid = vidMatch ? vidMatch[1] : '';
          if (wrapper) {
            wrapper.innerHTML = '<div class="leaders-fallback-card"><p class="leaders-fallback-icon">▶</p><p class="leaders-fallback-msg">This video is not available for inline playback.</p><a class="leaders-fallback-link" href="https://www.youtube.com/watch?v=' + escapeHtml(vid) + '" target="_blank" rel="noopener">Open on YouTube ↗</a></div>';
          }
        }
      }
      if (data && data.event === 'onReady') {
        if (_leadersFallbackTimer) { window.clearTimeout(_leadersFallbackTimer); _leadersFallbackTimer = null; }
      }
    } catch (_) {}
  });

  function safeArray(value) {
    if (Array.isArray(value)) return value;
    if (value && typeof value.forEach === 'function') return Array.from(value);
    return [];
  }

  function firstDefined() {
    for (var i = 0; i < arguments.length; i += 1) {
      if (arguments[i] !== undefined && arguments[i] !== null && arguments[i] !== "") return arguments[i];
    }
    return "";
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;");
  }

  // Minimal markdown-to-HTML for assistant chat replies. LLM answers
  // routinely contain **bold**, ### headers, --- rules, and simple pipe
  // tables; without this they rendered as literal, unparsed syntax in the
  // chat modal. Always escapeHtml() the raw text FIRST so every transform
  // below operates on already-safe text -- these regexes only ever ADD a
  // fixed, hardcoded set of tags (strong/em/h3/hr/table/br), they never
  // reintroduce anything from the source text as a tag, so this cannot
  // reopen an XSS path through markdown syntax in untrusted evidence text.
  function renderAssistantMarkdownToHtml(rawText) {
    var text = escapeHtml(rawText);
    var lines = text.split(/\r?\n/);
    var htmlParts = [];
    var i = 0;
    while (i < lines.length) {
      var line = lines[i];
      var headerMatch = line.match(/^(#{1,6})\s+(.*)$/);
      if (headerMatch) {
        var level = Math.min(6, headerMatch[1].length);
        htmlParts.push('<strong class="assistant-md-heading assistant-md-h' + level + '">' + inlineMarkdown(headerMatch[2]) + '</strong>');
        i += 1;
        continue;
      }
      if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
        htmlParts.push('<hr class="assistant-md-rule" />');
        i += 1;
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line) && lines[i + 1] && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1])) {
        var tableLines = [line];
        var j = i + 2;
        while (j < lines.length && /^\s*\|.*\|\s*$/.test(lines[j])) {
          tableLines.push(lines[j]);
          j += 1;
        }
        htmlParts.push(renderMarkdownTable(tableLines));
        i = j;
        continue;
      }
      htmlParts.push(inlineMarkdown(line));
      i += 1;
    }
    return htmlParts.join('<br />');
  }

  function inlineMarkdown(segment) {
    return segment
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, '$1<em>$2</em>');
  }

  function renderMarkdownTable(tableLines) {
    var headerCells = tableLines[0].split('|').map(function (c) { return c.trim(); }).filter(function (c, idx, arr) { return !(idx === 0 && c === '') && !(idx === arr.length - 1 && c === ''); });
    var bodyRows = tableLines.slice(1).map(function (rowLine) {
      return rowLine.split('|').map(function (c) { return c.trim(); }).filter(function (c, idx, arr) { return !(idx === 0 && c === '') && !(idx === arr.length - 1 && c === ''); });
    });
    var head = '<thead><tr>' + headerCells.map(function (c) { return '<th>' + inlineMarkdown(c) + '</th>'; }).join('') + '</tr></thead>';
    var body = '<tbody>' + bodyRows.map(function (row) {
      return '<tr>' + row.map(function (c) { return '<td>' + inlineMarkdown(c) + '</td>'; }).join('') + '</tr>';
    }).join('') + '</tbody>';
    return '<table class="assistant-md-table">' + head + body + '</table>';
  }

  function humanizeToken(token) {
    if (!token) return "—";
    return String(token)
      .replace(/[_-]/g, " ")
      .split(" ")
      .filter(Boolean)
      .map(function (part) { return part.charAt(0).toUpperCase() + part.slice(1); })
      .join(" ");
  }

  var EXECUTIVE_FINANCE_LABELS = {
    auto_renewal_escalation: "Auto-renewal escalation",
    duplicate_payment: "Duplicate payment",
    dormant_credit_balance: "Dormant supplier credit",
    entity_resolution_duplicate: "Duplicate supplier identity",
    missed_early_pay_discount: "Missed early-payment discount",
    finance_leakage: "recoverable value"
  };

  function executiveLabelForToken(token) {
    var raw = String(token || "").trim();
    if (!raw) return "";
    var key = raw.toLowerCase();
    return EXECUTIVE_FINANCE_LABELS[key] || humanizeToken(raw);
  }

  function scrubExecutiveTechnicalLanguage(text) {
    text = String(text || "").trim();
    if (!text) return "";
    Object.keys(EXECUTIVE_FINANCE_LABELS).forEach(function (key) {
      var pattern = new RegExp("\\b" + key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "gi");
      text = text.replace(pattern, EXECUTIVE_FINANCE_LABELS[key]);
    });
    text = text.replace(/\b([a-z][a-z0-9]+(?:_[a-z0-9]+)+)\b/g, function (match) {
      return executiveLabelForToken(match);
    });
    return text
      .replace(/\bScenario parser matched ['"]?[^'";.]+['"]?;?\s*/gi, "")
      .replace(/\brecoverable leakage\b/gi, "recoverable value")
      .replace(/\bcomputed from run findings\b/gi, "calculated from governed findings")
      .replace(/\brun findings\b/gi, "governed findings")
      .replace(/\bformula steps\b/gi, "calculation checks")
      .replace(/\bgrounding level\b/gi, "evidence confidence")
      .replace(/\s+/g, " ")
      .replace(/\s+([,.;:!?])/g, "$1")
      .trim();
  }

  var GOVERNED_MEASURE_LABELS = {
    bounded_finance_snapshot: "Finance recovery snapshot",
    case_worklist: "Governed case list",
    evidence_chain: "Citation evidence chain",
    review_attention: "Reviewer attention queue"
  };

  function governedMeasureLabel(value) {
    var raw = String(value || "").trim();
    if (!raw) return "Current measure";
    var key = raw.toLowerCase();
    return GOVERNED_MEASURE_LABELS[key] || humanizeToken(raw);
  }

  function eventTargetElement(event) {
    var target = event && event.target;
    if (!target) return null;
    if (typeof target.closest === 'function') return target;
    if (target.nodeType === 3 && target.parentElement && typeof target.parentElement.closest === 'function') {
      return target.parentElement;
    }
    return null;
  }

  function boardActionLabel(actionKey) {
    var key = String(actionKey || '').trim().toLowerCase();
    var labels = {
      prepare_board_pack: 'Prepare board pack',
      close_challenged_cases: 'Close challenged cases',
      capture_reviewer_decision: 'Capture reviewer decision',
      inspect_board_pack_status: 'Inspect board pack status',
      inspect_report_preview: 'Inspect report preview',
      review_supplementary_questions: 'Review supplementary questions',
      open_supplementary_rail: 'Open supplementary questions',
      freeze_live_answers: 'Freeze live answers',
      inspect_frozen_snapshot: 'Inspect frozen snapshot',
      review_board_memory: 'Review board memory',
      compare_packet_release: 'Compare board release',
      check_follow_up_obligations: 'Check follow-up obligations'
    };
    return labels[key] || humanizeToken(actionKey);
  }

  function boardActionPrompt(actionKey, board) {
    var key = String(actionKey || '').trim().toLowerCase();
    var boardState = resolveBoardState();
    var boardStateLabel = statusLabel(boardState).toLowerCase();
    var challengedCount = Number(firstDefined(((board || {}).supplementary || {}).question_count, 0)) || 0;
    if (key === 'prepare_board_pack') {
      return 'Help me prepare the board materials for the ' + boardStateLabel + ' stage. What needs CEO review, what evidence is missing, and what should I do next?';
    }
    if (key === 'close_challenged_cases') {
      return 'Help me close challenged cases before the board meeting. Which cases are challenged, what evidence is needed, and what is my next action?' + (challengedCount ? ' I can currently see ' + challengedCount + ' challenged case' + (challengedCount === 1 ? '' : 's') + '.' : '');
    }
    if (key === 'capture_reviewer_decision') {
      return 'Help me capture the reviewer decision for the ' + boardStateLabel + ' board stage. What is still open, what evidence is missing, and what should I do next?';
    }
    return 'Help me review ' + boardActionLabel(actionKey).toLowerCase() + ' for the ' + boardStateLabel + ' board stage. What needs review, what evidence is missing, and what should I do next?';
  }

  function activateBoardPrompt(prompt, sourceEl) {
    var cleanPrompt = String(prompt || '').trim();
    if (!cleanPrompt) return;
    askAssistant(cleanPrompt, sourceEl || null);
  }

  function activateBoardAction(actionKey, board, sourceEl) {
    activateBoardPrompt(boardActionPrompt(actionKey, board), sourceEl || null);
  }

  function bindBoardPortalInteractions(portal) {
    if (!portal) return;
    // Remove any previously bound delegated handler before re-binding.
    // portal.__boardPortalHandler is the stored reference. innerHTML replacement
    // on the portal never removes event listeners on the portal element itself,
    // so the old handler would persist across renders and continue to handle
    // clicks correctly. However, if the board data changes between renders,
    // the closure over boardActionPrompt(boardActionKey, getBoardPortal())
    // would see stale state. Re-binding ensures the handler always reads the
    // current getBoardPortal() result and the latest boardActionPrompt mapping.
    if (portal.__boardPortalHandler) {
      if (typeof portal.removeEventListener === 'function') {
        portal.removeEventListener('click', portal.__boardPortalHandler);
      }
      portal.__boardPortalHandler = null;
    }
    portal.__boardPortalHandler = function (event) {
      // Gate with _boardPromptHandled flag: whichever handler fires first
      // (delegated bubble vs individual onclick) processes the event and the
      // other skips, preventing duplicate /assistant/chat POSTs.
      if (event._boardPromptHandled) return;
      event._boardPromptHandled = true;
      var target = eventTargetElement(event);
      if (!target) return;
      var promptButton = target.closest('[data-board-prompt]');
      if (promptButton && portal.contains(promptButton)) {
        event.preventDefault();
        event.stopPropagation();
        askAssistant(promptButton.getAttribute('data-board-prompt') || '', promptButton);
        return;
      }
      var actionButton = target.closest('[data-board-action]');
      if (actionButton && portal.contains(actionButton)) {
        event.preventDefault();
        event.stopPropagation();
        askAssistant(boardActionPrompt(actionButton.getAttribute('data-board-action') || '', getBoardPortal()), actionButton);
      }
    };
    portal.addEventListener('click', portal.__boardPortalHandler);
  }

  function isAssistantFeedbackTarget(element) {
    return Boolean(
      element &&
      typeof element === 'object' &&
      element.nodeType === 1 &&
      element.tagName === 'BUTTON'
    );
  }

  function boardStateSupportNote(board) {
    // Delegate to boardStateDetailForRender, which only trusts the server's
    // state_detail when existing.state actually matches the currently
    // selected boardState (see matchesSelectedState there). activateBoardState
    // switches stages purely client-side with no re-fetch, so a stale
    // server payload's state_detail.note would otherwise stick to whatever
    // stage was active at the last network refresh -- e.g. clicking "Live"
    // right after a "Closed" fetch kept showing the Closed-stage caption.
    return boardStateDetailForRender(resolveBoardState(), board).note;
  }

  function boardStateDetailForRender(boardState, board) {
    var existing = (board || {}).state_detail || {};
    var defaults = {
      pre: {
        state: 'pre',
        title: 'Pre-board preparation',
        summary: 'Prepare one board-safe packet for CEO review by resolving challenged evidence, tightening supplementary answers, and confirming the release posture.',
        note: 'Keep the packet inside the executive lane until challenged evidence is closed and supplementary answers are board-ready.',
        primary_actions: ['prepare_board_pack', 'capture_reviewer_decision'],
        secondary_actions: ['inspect_report_preview', 'review_supplementary_questions']
      },
      live: {
        state: 'live',
        title: 'Live board session',
        summary: 'Operate only inside the approved packet while questions stay linked to challenged evidence and governed release posture.',
        note: 'Stay inside the approved packet while the room is live and route every answer back to governed evidence.',
        primary_actions: ['capture_reviewer_decision', 'inspect_board_pack_status'],
        secondary_actions: ['open_supplementary_rail', 'freeze_live_answers']
      },
      closed: {
        state: 'closed',
        title: 'Closed / frozen snapshot',
        summary: 'Keep the board memory frozen and bounded to approved outputs after the session closes.',
        note: 'The room is closed now; preserve the frozen record and work follow-ups outside the board surface.',
        primary_actions: ['inspect_frozen_snapshot', 'review_board_memory'],
        secondary_actions: ['compare_packet_release', 'check_follow_up_obligations']
      }
    };
    var fallback = defaults[boardState] || defaults.pre;
    var matchesSelectedState = String(firstDefined(existing.state, '')).toLowerCase() === boardState;
    return {
      state: boardState,
      title: firstDefined(matchesSelectedState ? existing.title : '', fallback.title),
      summary: firstDefined(matchesSelectedState ? existing.summary : '', fallback.summary),
      note: firstDefined(matchesSelectedState ? existing.note : '', fallback.note),
      primary_actions: safeArray(matchesSelectedState ? existing.primary_actions : fallback.primary_actions),
      secondary_actions: safeArray(matchesSelectedState ? existing.secondary_actions : fallback.secondary_actions)
    };
  }

  function boardLifecycleForRender(boardState, board) {
    return safeArray((board || {}).lifecycle_flow).map(function (item) {
      var copy = {};
      Object.keys(item || {}).forEach(function (key) {
        copy[key] = item[key];
      });
      copy.presented = String(firstDefined(item && item.state_id, '')).toLowerCase() === boardState;
      return copy;
    });
  }

  function resolveBoardState() {
    // Priority: user-selected anchor > in-transition signal > server state > default.
    // state.activeBoard is the authoritative user selection set by activateBoardState.
    // state._boardStateTransition is a transient signal used only by refresh() to
    // avoid overriding an in-flight user transition. Once the transition completes,
    // _boardStateTransition is cleared and activeBoard is the source of truth.
    return String(
      firstDefined(
        state.activeBoard,
        state._boardStateTransition,
        getBoardPortal().presentation_state,
        getBoardPortal().state,
        'pre'
      )
    ).trim().toLowerCase();
  }

  // Board-state-tab observer guards.
  // _boardStateObserverSyncing prevents re-entrant observer callbacks from
  // triggering a second sync while the first is still in-flight. The observer
  // callback checks this flag and returns immediately if it is true, avoiding
  // the infinite loop: observer → syncBoardStateTabUI → className change →
  // observer callback (blocked by flag) → observer callback queues another →
  // ... without the flag, each sync triggers a new observer callback that
  // sees a mismatch (CSSOM recalc reverted className) and calls sync again.
  var _boardStateObserverSyncing = false;
  // _boardStateLastSynced tracks the last state that syncBoardStateTabUI was
  // called with. The observer uses this to detect CSSOM-revert loops: if the
  // desired state matches the last synced state AND there's a DOM mismatch,
  // the observer allows up to MAX_OBSERVER_RETRIES additional syncs to fix
  // the CSSOM revert before yielding to the higher-level render cycle.
  var _boardStateLastSynced = '';
  // _boardStateSyncRetryCount limits observer-triggered syncs for the same
  // desired state to prevent infinite CSSOM recalc loops. Each unique desired
  // state resets the counter. After exceeding the limit, the observer waits
  // for the higher-level render cycle to re-assert the correct state.
  var _boardStateSyncRetryCount = 0;
  var BOARD_STATE_OBSERVER_MAX_RETRIES = 5;

  function boardStateTabUIMismatch(nextState) {
    var row = $("board-state-row");
    if (!row) return false;
    var mismatched = false;
    safeArray(row.querySelectorAll('[data-board-state]')).forEach(function (button) {
      if (mismatched) return;
      var buttonState = String(button.getAttribute('data-board-state') || '').trim().toLowerCase();
      var isActive = buttonState === nextState;
      var expectedClass = 'state-tab' + (isActive ? ' is-active' : '');
      var expectedSelected = isActive ? 'true' : 'false';
      var expectedBackground = isActive ? 'var(--accent-soft)' : 'transparent';
      if (
        button.className !== expectedClass
        || button.getAttribute('aria-selected') !== expectedSelected
        || button.getAttribute('data-board-state-active') !== expectedSelected
        || (button.style && button.style.background !== expectedBackground)
      ) {
        mismatched = true;
      }
    });
    return mismatched;
  }

  function syncBoardStateTabUI(nextState) {
    var row = $("board-state-row");
    if (!row) return;
    _boardStateObserverSyncing = true;
    try {
      _boardStateLastSynced = nextState;
      safeArray(row.querySelectorAll('[data-board-state]')).forEach(function (button) {
        var buttonState = String(button.getAttribute('data-board-state') || '').trim().toLowerCase();
        var isActive = buttonState === nextState;
        var expectedClass = 'state-tab' + (isActive ? ' is-active' : '');
        var expectedSelected = isActive ? 'true' : 'false';
        var expectedBackground = isActive ? 'var(--accent-soft)' : 'transparent';
        if (button.className !== expectedClass) button.className = expectedClass;
        if (button.getAttribute('aria-selected') !== expectedSelected) button.setAttribute('aria-selected', expectedSelected);
        // Redundant data attribute guard: some environments strip className
        // during hydration or CSSOM recalculation. The data attribute is a
        // second signal the test harness and future render code can rely on.
        if (button.getAttribute('data-board-state-active') !== expectedSelected) button.setAttribute('data-board-state-active', expectedSelected);
        // Triple-redundant inline style attribute: some browsers discard
        // className during aggressive CSSOM recalculation after innerHTML
        // replacement (observed on Chrome 127+ after renderBoardStageSurface
        // destroys and recreates all tab buttons). The inline background
        // survives even when class-based styling is lost to a CSSOM race.
        if (button.style && button.style.background !== expectedBackground) {
          button.style.background = expectedBackground;
        }
      });
    } finally {
      _boardStateObserverSyncing = false;
    }
  }

  function renderBoardStageSurface() {
    renderBoardStateTabs();
    renderBoardPortal();
  }

  // _domSyncGuard removed in P0-10. renderBoardStateTabs now has a fast path
  // that updates button attributes in-place instead of innerHTML destroy-recreate,
  // eliminating the root cause of the multi-phase guard: the brief window where
  // buttons didn't exist during the destroy-recreate cycle.

  function activateBoardState(nextState) {
    nextState = String(nextState || '').trim().toLowerCase();
    if (!nextState) return false;
    // Always proceed — even if state.activeBoard matches, the DOM may not
    // reflect it due to a concurrent refresh or incomplete render cycle.
    state._boardStateTransition = nextState;
    state.activeBoard = nextState;
    // Sync existing buttons immediately so there is no visual lag between
    // the click and the full render cycle completing.
    // renderBoardStateTabs now has a fast path that avoids innerHTML
    // destroy-recreate when the mode list is unchanged.
    renderBoardStageSurface();
    // Post-render guard: force intended tab state on whatever buttons exist.
    syncBoardStateTabUI(nextState);
    // Re-assert guard: if a concurrent refresh() reset activeBoard during
    // renderBoardStageSurface, restore it.
    if (state.activeBoard !== nextState) {
      state.activeBoard = nextState;
      syncBoardStateTabUI(nextState);
    }
    animateCard('board-portal');
    updateHistory();
    // Keep _boardStateTransition set throughout the re-sync window so that any
    // concurrent refresh() (setInterval 60s) entering line 3869 sees it as
    // truthy and preserves activeBoard instead of overriding from server state.
    // The LAST callback in the re-sync chain (setTimeout 1000ms) is the
    // authoritative finalizer that clears _boardStateTransition. If a new
    // click arrives before the window expires, cancel the pending timer.
    if (state._boardStateTransitionTimer) {
      window.clearTimeout(state._boardStateTransitionTimer);
      state._boardStateTransitionTimer = null;
    }
    // Multi-timing re-sync chain: re-assert the intended tab state across
    // several timing windows to overcome any competing re-render (e.g. an
    // async refresh() response that fires during or after this function, or
    // a switchView re-sync chain that registered before this call and fires
    // a stale captured snapshot on the same timing).
    // The chain uses rAF (next paint), multiple setTimeout levels to catch
    // deferred re-renders, and a 1000ms catch-all finalizer. Each timing
    // callback RE-READS resolveBoardState() so that a stale captured value
    // from a competing chain cannot regress the user's selection.
    // IMPORTANT: this callback must NOT unconditionally revert
    // state.activeBoard to the captured nextState. If the user rapidly clicks
    // multiple tabs (e.g. pre -> live -> closed in quick succession), the
    // rAF/setTimeout callbacks from the first click (captured nextState='live')
    // would override the user's second click (state.activeBoard='closed'),
    // causing the UI to show the wrong active state. Instead, this callback
    // trusts state.activeBoard as the authoritative user selection and only
    // syncs the UI to match it.
    // Fallback: if state.activeBoard was cleared by a concurrent render cycle
    // (e.g. a competing switchView re-sync or refresh that fired between
    // timers and reset activeBoard), restore it from the captured nextState.
    // Only do this when activeBoard is falsy so a rapid second click's state
    // (which is truthy and different from nextState) is never overwritten.
    // renderBoardStateTabs runs BEFORE syncBoardStateTabUI so the fast-path
    // full attribute reconciliation catches any CSSOM recalc regression from
    // the portal innerHTML replacement before the lighter sync pass.
    function _boardStateReSync() {
      if (!state.activeBoard) state.activeBoard = nextState;
      renderBoardStateTabs();
      syncBoardStateTabUI(resolveBoardState());
    }
    function _boardStateReSyncFinal() {
      _boardStateReSync();
      // Last callback: clear transition signal so refresh() can use the
      // server presentation_state for a future navigation. By this point
      // (1000ms after click), all competing re-renders have settled and
      // state.activeBoard is the authoritative user selection.
      state._boardStateTransition = '';
      state._boardStateTransitionTimer = null;
    }
    if (typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(_boardStateReSync);
    }
    if (typeof window.setTimeout === 'function') {
      window.setTimeout(_boardStateReSync, 0);
      window.setTimeout(_boardStateReSync, 50);
      window.setTimeout(_boardStateReSync, 250);
      state._boardStateTransitionTimer = window.setTimeout(_boardStateReSyncFinal, 1000);
      // 5000ms catch-all: as a last resort, re-assert the tab state after any
      // deeply deferred CSSOM recalc or competing render cycle (e.g. a delayed
      // refresh response that fires long after the initial timing chain).
      window.setTimeout(_boardStateReSync, 5000);
    }
    return true;
  }

  function statusLabel(token) {
    if (!token) return "—";
    var key = String(token).toLowerCase().replace(/[_-]/g, " ").trim();
    var map = {
      "awaiting review": "Under review",
      "awaiting_review": "Under review",
      "pre": "Pre-board",
      "challenged": "Needs review",
      "approved for release": "Approved",
      "approved_for_release": "Approved",
      "blocked": "Blocked",
      "draft": "Draft",
      "published": "Published",
      "completed": "Completed",
      "pending": "Pending",
      "in review": "Under review",
      "in_review": "Under review",
      "live packet": "Frozen",
      "live_packet": "Frozen",
      "protected": "Guarded",
      "board_safe_preview": "View only",
      "board_safe_publication": "View only",
      "preview": "View only",
      "preview_only": "View only",
      "preview only": "View only",
    };
    if (map[key]) return map[key];
    var challengedMatch = key.match(/^(\d+)\s+challenged$/);
    if (challengedMatch) return challengedMatch[1] + " items need review";
    return humanizeToken(token);
  }

  function initialsFromName(value) {
    return String(firstDefined(value, ""))
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map(function (part) { return part.charAt(0).toUpperCase(); })
      .join("") || "GM";
  }

  function toneClass(value) {
    var text = String(value || "").toLowerCase();
    if (/(published|approved|clear|ready|ok|strong|win|up|live|authored)/.test(text)) return "ok";
    if (/(challenged|blocked|needs|pending|watch|prepare|draft|thin|warning|review)/.test(text)) return "warn";
    if (/(rejected|failed|danger|down)/.test(text)) return "danger";
    return "ok";
  }

  function moverSourceBadge(item) {
    var label = firstDefined(item && item.source_label, item && item.state_label, "");
    if (!label) return "";
    return '<span class="pill-inline ' + toneClass(label) + '">' + escapeHtml(label) + '</span>';
  }

  function buildQuery(params) {
    var search = new URLSearchParams();
    Object.keys(params || {}).forEach(function (key) {
      if (params[key]) search.set(key, params[key]);
    });
    var query = search.toString();
    return query ? "?" + query : "";
  }

  function readStoredToken() {
    try { return window.localStorage.getItem(_tokenKey) || ""; } catch (_error) { return ""; }
  }

  function clearStoredToken() {
    state.token = "";
    try { window.localStorage.removeItem(_tokenKey); } catch (_error) {}
  }

  function isPublicSafeAssistantBody(body) {
    if (bootstrap.login_required) return false;
    var persona = String(firstDefined(body && body.persona, state && state.activePersona, "")).toLowerCase();
    var source = String(firstDefined(body && body.assistant_context && body.assistant_context.source, body && body.source, "")).toLowerCase();
    var runId = String(firstDefined(body && body.run_id, "latest-public")).toLowerCase();
    return persona === "ceo" && source === "executive_surface" && (!body || !body.run_id || runId === "latest-public");
  }

  function shouldRetryAssistantAnonymously(response, body, requestOptions, usedBearerAuth) {
    var status = Number(firstDefined(response && response.status, 0)) || 0;
    if (status !== 401 && status !== 403) return false;
    if (!usedBearerAuth) return false;
    if (!isPublicSafeAssistantBody(body)) return false;
    if (requestOptions && requestOptions.skipAuth) return false;
    if (requestOptions && requestOptions._anonymousRetry) return false;
    return true;
  }

  function authHeaders(options) {
    if (options && options.skipAuth) return {};
    var token = "";
    token = firstDefined(state && state.token, "");
    if (!token) {
      token = readStoredToken();
    }
    if (!token) return {};
    if (bootstrap.idp_enabled || token.indexOf(".") !== -1) return { Authorization: "Bearer " + token };
    return { "X-API-Key": token };
  }

  function fetchJson(path) {
    return fetch(path, { headers: authHeaders() }).then(function (response) {
      return response.ok ? response.json() : null;
    });
  }

  function latestRunRouteForSession(session) {
    if (session && session.api_auth_enabled === false) return "/runs/latest";
    if (session && session.authenticated) return "/runs/latest";
    if (bootstrap.login_required) return "/runs/latest";
    return "/public/runs/latest";
  }

  function parseJsonResponse(response) {
    return response.text().then(function (text) {
      if (!text) return null;
      try {
        return JSON.parse(text);
      } catch (_error) {
        return { raw: text };
      }
    });
  }

  function assistantTraceId() {
    return "hermes-" + Date.now() + "-" + Math.random().toString(16).slice(2, 10);
  }

  function postJson(path, body, options) {
    var requestOptions = options || {};
    var timeoutMs = Number(firstDefined(requestOptions.timeoutMs, 45000));
    var headers = authHeaders({ skipAuth: requestOptions.skipAuth === true });
    var usedBearerAuth = Boolean(headers.Authorization);
    headers["Content-Type"] = "application/json";
    var requestId = firstDefined(requestOptions && requestOptions.requestId, body && body.trace_id, "");
    if (requestId) headers["X-Request-ID"] = requestId;
    var abortController = typeof AbortController === "function" ? new AbortController() : null;
    var timeoutId = null;
    var timeoutError = new Error("Assistant request timed out after " + timeoutMs + "ms");
    timeoutError.endpoint = path;
    timeoutError.status = 0;
    timeoutError.requestId = requestId;
    timeoutError.errorType = "timeout";
    var requestPromise = fetch(path, {
      method: "POST",
      headers: headers,
      body: JSON.stringify(body || {}),
      signal: abortController ? abortController.signal : undefined
    }).then(function (response) {
      return parseJsonResponse(response).then(function (payload) {
        if (shouldRetryAssistantAnonymously(response, body, requestOptions, usedBearerAuth)) {
          console.warn("[Hermes] clearing stale UI token after assistant auth failure", {
            status: response.status,
            endpoint: path,
            requestId: requestId
          });
          clearStoredToken();
          return postJson(path, body, {
            requestId: requestId,
            skipAuth: true,
            _anonymousRetry: true
          });
        }
        var responseRequestId = firstDefined(
          response.headers.get("x-request-id"),
          payload && payload.request_id,
          payload && payload.trace_id,
          requestId
        );
        if (!response.ok) {
          var error = new Error("Assistant request failed with status " + response.status);
          error.endpoint = path;
          error.status = response.status;
          error.payload = payload;
          error.requestId = responseRequestId;
          error.errorType = response.status === 401 ? "auth_error"
            : response.status === 403 ? "forbidden"
            : response.status >= 500 ? "server_error"
            : "http_error";
          throw error;
        }
        return {
          payload: payload,
          status: response.status,
          endpoint: path,
          requestId: responseRequestId
        };
      });
    });
    var timeoutPromise = new Promise(function (_resolve, reject) {
      timeoutId = window.setTimeout(function () {
        if (abortController) abortController.abort();
        reject(timeoutError);
      }, timeoutMs);
    });
    return Promise.race([requestPromise, timeoutPromise]).catch(function (error) {
      if (error && error.endpoint) throw error;
      var networkError = new Error(firstDefined(error && error.message, "Assistant transport failure"));
      networkError.endpoint = path;
      networkError.status = 0;
      networkError.requestId = requestId;
      networkError.errorType = error && error.name === "AbortError" ? "timeout" : "network_error";
      networkError.cause = error;
      throw networkError;
    }).finally(function () {
      if (timeoutId !== null) window.clearTimeout(timeoutId);
    });
  }

  function activeRunId() {
    return firstDefined(
      state.latestPacket && state.latestPacket.run_id,
      getChatContract().run_id,
      ""
    );
  }

  function formatSar(value) {
    var number = Number(value || 0);
    if (!Number.isFinite(number)) return "SAR 0";
    return "SAR " + number.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function wordSlice(text, limit) {
    text = String(text || "").trim();
    if (text.length <= limit) return text;
    var sliced = text.slice(0, limit);
    var lastSpace = sliced.lastIndexOf(' ');
    if (lastSpace > Math.floor(limit * 0.6)) return sliced.slice(0, lastSpace) + '\u2026';
    return sliced + '\u2026';
  }

  function focusAssistantInput() {
    window.setTimeout(function () {
      var input = $("assistant-input");
      if (input && !input.disabled) input.focus();
    }, 0);
  }

  /* ── Unified Hermes drawer opening — single source of truth ── */
  var _drawerKeydown = null;

  function _openHermesDrawer(returnFocusEl) {
    /* Guard: surfaces must not overlap — close video modal before opening drawer */
    if (state.videoModalOpen) closeVideoModal();
    /* Guard: close A2A panel if open — only one surface at a time */
    if (state.a2aOpen) { state.a2aOpen = false; renderA2APanel(); }
    /* Guard: if already open, keep the visible conversation in sync. */
    if (state.drawerOpen) {
      renderAssistantStudio();
      focusAssistantInput();
      return;
    }
    state.drawerOpen = true;
    state.drawerReturnFocusEl = returnFocusEl || null;
    document.body.style.overflow = 'hidden';

    /* Escape key closes the drawer */
    _drawerKeydown = function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        _closeHermesDrawer();
      }
    };
    document.addEventListener("keydown", _drawerKeydown);

    renderTopbar();
    renderAssistantStudio();
    focusAssistantInput();
  }

  function _closeHermesDrawer() {
    state.drawerOpen = false;
    document.body.style.overflow = '';
    if (_drawerKeydown) {
      document.removeEventListener("keydown", _drawerKeydown);
      _drawerKeydown = null;
    }
    renderTopbar();
    renderAssistantStudio();
    /* Restore focus to the element that triggered the drawer */
    var returnEl = state.drawerReturnFocusEl;
    state.drawerReturnFocusEl = null;
    if (returnEl && typeof returnEl.focus === 'function') {
      window.setTimeout(function () { returnEl.focus(); }, 0);
    }
  }

  function openAssistantDrawer(returnFocusEl) {
    _openHermesDrawer(returnFocusEl);
  }

  function threadTitleFromPrompt(prompt) {
    var cleanPrompt = String(prompt || "").trim();
    if (!cleanPrompt) return "New conversation · " + nowStamp();
    var title = cleanPrompt.replace(/\s+/g, " ").slice(0, 42);
    if (cleanPrompt.length > 42) title += "…";
    return title;
  }

  async function askAssistant(prompt, sourceChip) {
    var hiddenContext = arguments.length > 2 ? arguments[2] : null;
    var cleanPrompt = String(prompt || "").trim();
    if (!cleanPrompt) return;
    // openAssistantDrawer(validChip) is the single shared drawer-opening path.
    var validChip = isAssistantFeedbackTarget(sourceChip) ? sourceChip : null;
    var originalText = null;
    if (validChip) {
      originalText = validChip.textContent;
      validChip.textContent = 'loading\u2026';
      validChip.disabled = true;
    }
    ensureWritableThread(threadTitleFromPrompt(cleanPrompt), cleanPrompt, { silentInitialMessage: true });
    var threadKey = currentThreadKey();
    pushThreadMessage("user", cleanPrompt);
    var pending = pushThreadMessage("assistant", "Checking the board data\u2026");
    // Bug 7 fix: attach a pulsing progress indicator to the pending message
    // so the user sees activity during the 5-10s wait for buildAssistantReply.
    if (pending && pending.element) {
      var spinner = document.createElement("span");
      spinner.className = "msg-loading-spinner";
      spinner.innerHTML = '<span class="dot-pulse"></span>';
      pending.element.appendChild(spinner);
    }
    openAssistantDrawer(validChip);
    // Show loading state in the input area when no source chip provides feedback
    var form = $("assistant-form");
    var input = $("assistant-input");
    if (!validChip && form && input) {
      input.disabled = true;
      input.placeholder = 'Thinking\u2026';
      form.classList.add('assistant-form--loading');
    }
    var pendingThread = threadStore()[threadKey];
    var result;
    try {
      result = await buildAssistantReply(cleanPrompt, validChip, hiddenContext);
    } catch (error) {
      result = makeAssistantFailureResult(cleanPrompt, {
        endpoint: firstDefined(error && error.endpoint, "/assistant/chat"),
        statusCode: firstDefined(error && error.status, ""),
        requestId: firstDefined(error && error.requestId, ""),
        errorType: firstDefined(error && error.errorType, "unexpected_client_error"),
        details: error && error.message ? error.message : String(error || "Unexpected assistant client error")
      });
    } finally {
      // A request must always leave its loading state, including when the
      // browser aborts a transport or a rendering helper throws.
      if (!validChip && form && input) {
        input.disabled = false;
        input.placeholder = 'Ask Hermes\u2026';
        form.classList.remove('assistant-form--loading');
        focusAssistantInput();
      }
      if (validChip) {
        validChip.textContent = originalText;
        validChip.disabled = false;
      }
    }
    if (!result) {
      result = makeAssistantFailureResult(cleanPrompt, {
        endpoint: "/assistant/chat",
        errorType: "empty_transport_result",
        details: "The assistant transport returned without a result."
      });
    }
    if (pending) {
      var thread = threadStore()[threadKey] || pendingThread;
      if (thread) {
        applyAssistantResultToMessage(thread, pending, result);
      }
      saveStoredThreads();
      renderAssistantStudio();
    }
  }


  function switchView(view) {
    var previousView = state.activeView;
    state.activeView = view || "home";
    updateHistory();
    renderPersonaView();
    if (previousView !== state.activeView && typeof window.scrollTo === "function") {
      window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    }
    if (state.activeView === "assistants") focusAssistantInput();
    // When switching to the knowledge view, re-assert the board tab UI to ensure
    // the browser's CSSOM and accessibility tree reflect the active state. The
    // renderPersonaView call above already renders board state tabs, but some
    // browser rendering modes (Chrome CSSOM recalc after hidden→visible transition)
    // can discard className-based styling. syncBoardStateTabUI sets inline styles
    // and data attributes as triple-redundant fallbacks for this edge case.
    if (state.activeView === "knowledge") {
      syncBoardStateTabUI(resolveBoardState());
      // Multi-timing re-sync: the hidden→visible CSSOM recalc can fire during
      // paint and discard inline style attributes. rAF, setTimeout(0/50/250/1000)
      // bypass this window at multiple timing levels to catch any deferred
      // CSSOM recalc or competing re-render. Each callback RE-READS
      // resolveBoardState() so that a user tab click between callbacks is not
      // overwritten by a stale captured snapshot from this chain.
      function _switchViewReSync() {
        renderBoardStateTabs();
        syncBoardStateTabUI(resolveBoardState());
      }
      if (typeof window.requestAnimationFrame === 'function') {
        window.requestAnimationFrame(_switchViewReSync);
      }
      if (typeof window.setTimeout === 'function') {
        window.setTimeout(_switchViewReSync, 0);
        window.setTimeout(_switchViewReSync, 50);
        window.setTimeout(_switchViewReSync, 250);
        window.setTimeout(_switchViewReSync, 1000);
        // 5000ms catch-all: deeply deferred CSSOM recalc or competing render.
        window.setTimeout(_switchViewReSync, 5000);
      }
    }
  }

  function animateCard(id) {
    var node = $(id);
    if (!node) return;
    node.classList.add("is-transitioning");
    window.setTimeout(function () { node.classList.remove("is-transitioning"); }, 240);
  }

  function updateHistory() {
    var route = firstDefined(bootstrap.executive_entry_route, window.location.pathname, "/app");
    var query = buildQuery({
      persona: state.activePersona,
      board: state.activeBoard,
      driver: state.activeDriverKey,
      company: state.activeCompany,
      portfolio: state.activePortfolio,
      agent: state.activeView === "agents" ? state.openAgentId : ""
    });
    window.history.replaceState({}, "", route + query);
  }

  function currentViewParams() {
    return {
      persona: state.activePersona,
      board: state.activeBoard,
      driver: state.activeDriverKey,
      company: state.activeCompany,
      portfolio: state.activePortfolio,
      agent: state.activeView === "agents" ? state.openAgentId : ""
    };
  }

  function getPersonaBlueprint(personaId) {
    var shared = getSharedAssistantContext();
    if ((shared.persona_id || "ceo") === personaId) {
      return {
        health: shared.health || {},
        assistant: shared.assistant,
        drivers: safeArray(shared.drivers),
        findings: safeArray(shared.findings),
        developments: safeArray(shared.developments),
        week: safeArray(shared.week)
      };
    }
    var diagnostics = getExecutiveDiagnostics();
    if (diagnostics.persona_blueprint && firstDefined(diagnostics.persona_blueprint.assistant, "")) {
      return diagnostics.persona_blueprint;
    }
    return {};
  }

  function getSharedAssistantContext() {
    return (state.latestPacket && state.latestPacket.assistant_public_context) || BOOTSTRAP_ASSISTANT_CONTEXT || {};
  }

  function getPersonaContract(personaId) {
    return safeArray(state.personas).find(function (item) { return item.persona_id === personaId; }) || {};
  }

  function getPersonaLabel(personaId) {
    var contract = getPersonaContract(personaId);
    var POLISHED_LABELS = {
      gm: "General Manager", bucfo: "Business Unit CFO",
      logistics: "Logistics Lead", mfg: "Manufacturing Lead",
      hc: "Healthcare Services Lead", cap: "Capital Lead",
      ceo: "Group CEO", board: "Board Director", reviewer: "Reviewer",
      operator: "Operator"
    };
    return firstDefined(POLISHED_LABELS[personaId], contract.label, humanizeToken(personaId), "Group CEO");
  }

  function sessionDisplayName() {
    var session = state.session || {};
    if (!session.authenticated) return "";
    return String(firstDefined(session.display_name, session.display_subject, "")).trim();
  }

  function tenantDisplayName() {
    var sessionTenant = (state.session || {}).tenant_context || {};
    var packetTenant = (state.latestPacket || {}).tenant_context || {};
    var modes = (state.latestPacket || {}).executive_modes || {};
    return String(firstDefined(
      sessionTenant.tenant_name,
      packetTenant.tenant_name,
      modes.company_label,
      "StrategyOS"
    )).trim();
  }

  function executiveIdentityInitials(personaId) {
    // Identity comes from the authenticated session, never from a fixture
    // person -- there is no real person behind a persona in the data model.
    var fullName = sessionDisplayName();
    var initials = fullName
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map(function (part) { return part.charAt(0).toUpperCase(); })
      .join("");
    if (initials) return initials;

    var fallbackInitials = String(firstDefined(getPersonaLabel(personaId), "Group CEO"))
      .split(" ")
      .filter(Boolean)
      .map(function (part) { return part.charAt(0).toUpperCase(); })
      .slice(0, 2)
      .join("");

    return fallbackInitials || "GC";
  }

  function getExecutiveDiagnostics() {
    return (state.latestPacket && state.latestPacket.executive_diagnostics) || {};
  }

  function getBoardPortal() {
    return (state.latestPacket && state.latestPacket.board_portal) || {};
  }

  function getBoardDesign() {
    return getSharedAssistantContext().board_portal || {};
  }

  function getChatContract() {
    return (state.latestPacket && state.latestPacket.chat) || {};
  }

  function getPublication() {
    return (state.latestPacket && state.latestPacket.publication) || {};
  }

  function getAssistantNetworkMeta() {
    var modules = getAgentsModule();
    var summary = modules.summary || {};
    var activity = getAgentActivitySummary();
    var runningCount = Number(firstDefined(summary.running_count, safeArray(getRunningAgents()).length, 0)) || 0;
    var discoverableCount = Number(firstDefined(summary.discoverable_count, safeArray(modules.discoverable).length, 0)) || 0;
    var approvalCount = Number(firstDefined(summary.approval_count, safeArray(modules.approvals).length, 0)) || 0;
    return {
      label: "Governed Assistant Network",
      hint: firstDefined(
        activity.line,
        runningCount ? runningCount + " active module" + (runningCount === 1 ? "" : "s") + " · " + discoverableCount + " discoverable · " + approvalCount + " approval gate" + (approvalCount === 1 ? "" : "s") : "",
        "Assistant status is not available yet."
      ),
      running_count: runningCount,
      discoverable_count: discoverableCount,
      approval_count: approvalCount
    };
  }

  // Presentational ordering only -- ranks are never rendered as numbers.
  // Modules show their REAL status; no synthetic "readiness score" exists
  // in the data model, so none is displayed.
  function assistantModuleStatusRank(status) {
    var value = String(status || "").toLowerCase();
    if (/(running|ready|ok|healthy|live|protected)/.test(value)) return 0;
    if (/(preview|pending|waiting|draft|queued)/.test(value)) return 1;
    if (/(blocked|challenged|review|held)/.test(value)) return 2;
    if (/(idle|missing|unavailable)/.test(value)) return 3;
    return 4;
  }

  function getAssistantNetwork() {
    var modules = getAgentsModule();
    var stateContract = modules.state_contract || {};
    var running = safeArray(stateContract.modules);
    if (!running.length) running = safeArray(getRunningAgents());
    if (!running.length) running = safeArray(modules.running);
    return running.map(function (item, index) {
      var status = firstDefined(item && item.status, "running");
      var lane = firstDefined(item && item.lane, item && item.tag, "governed");
      return {
        moduleId: firstDefined(item && item.module_id, item && item.id, ""),
        statusRank: assistantModuleStatusRank(status),
        tone: status,
        assistant: firstDefined(item && item.label, item && item.name, item && item.module_id, "Assistant module " + (index + 1)),
        who: humanizeToken(lane),
        unit: firstDefined(item && item.current_activity, item && item.summary, item && item.doing, item && item.output, item && item.output_metric, tenantDisplayName()),
        stateLabel: firstDefined(statusLabel(status), status, "Current"),
        businessOutput: firstDefined(item && item.output, item && item.output_metric, item && item.current_activity, item && item.summary, "No output reported yet"),
        decisionScope: (function () {
          var dependency = firstDefined(item && item.approval_dependency, "");
          if (!dependency || String(dependency).toLowerCase() === "none") return "No action needed";
          return humanizeToken(dependency);
        }()),
        route: firstDefined(item && item.route, "")
      };
    });
  }

  function getAssistantExchanges() {
    var modules = getAgentsModule();
    var running = safeArray(getRunningAgents());
    if (!running.length) running = safeArray(modules.running);
    var exchanges = running.map(function (item, index) {
      var name = firstDefined(item && item.label, item && item.name, item && item.module_id, "Assistant module " + (index + 1));
      var status = firstDefined(item && item.status, "active");
      return {
        id: firstDefined(item && item.module_id, item && item.id, "module-" + index),
        with: name,
        unit: humanizeToken(firstDefined(item && item.lane, item && item.tag, "governed lane")),
        status: status,
        topic: firstDefined(item && item.summary, item && item.doing, "Governed module activity"),
        messages: [
          { from: "StrategyOS", text: firstDefined(item && item.summary, item && item.doing, "Assistant is active.") },
          { from: name, text: firstDefined(item && item.output_metric, statusLabel(status), "Current") }
        ]
      };
    });
    if (exchanges.length) return exchanges;
    return safeArray(modules.approvals).map(function (item, index) {
      var label = firstDefined(item && item.label, item && item.approval_id, "Approval gate " + (index + 1));
      return {
        id: firstDefined(item && item.approval_id, "approval-" + index),
        with: label,
        unit: "Approval",
        status: firstDefined(item && item.status, "pending"),
        topic: firstDefined(item && item.next_action, "Approval gate"),
        messages: [
          { from: "StrategyOS", text: "The approval gate is ready for review." },
          { from: label, text: firstDefined(item && item.next_action, item && item.status, "pending") }
        ]
      };
    });
  }

  function normalizeKgCategory(value) {
    var raw = String(firstDefined(value, "signal")).trim();
    var key = raw.toLowerCase().replace(/[^a-z0-9]+/g, "_");
    var map = {
      plan: "plan",
      board_plan: "plan",
      board: "plan",
      kpi: "KPI",
      finance: "KPI",
      metric: "KPI",
      business_unit: "business_unit",
      businessunit: "business_unit",
      bu: "business_unit",
      unit: "business_unit",
      finding: "finding",
      risk: "finding",
      issue: "finding",
      document: "document",
      report: "document",
      deck: "document",
      audit: "document",
      vendor: "vendor",
      supplier: "vendor",
      invoice: "invoice",
      receivable: "invoice",
      contract: "contract",
      agreement: "contract",
      evidence: "evidence",
      source: "source",
      relationship: "relationship",
      business_driver: "business_driver",
      driver: "business_driver",
      component: "business_driver",
      comparator: "comparator",
      benchmark: "comparator",
      evidence_gap: "evidence_gap",
      data_gap: "evidence_gap",
      signal: "signal"
    };
    return map[key] || raw || "signal";
  }

  function clampNumber(value, min, max) {
    var num = Number(value);
    if (!Number.isFinite(num)) num = min;
    return Math.max(min, Math.min(max, num));
  }

  function kgHash(seed) {
    var str = String(seed || "kg");
    var hash = 0;
    for (var i = 0; i < str.length; i += 1) {
      hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
    }
    return Math.abs(hash);
  }

  function kgUnit(seed, salt) {
    var hash = kgHash(String(seed || "") + "::" + String(salt || 0));
    return (hash % 1000) / 1000;
  }

  function safeNodeId(label, index) {
    var base = String(firstDefined(label, "node")).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    return (base || "node") + "_" + index;
  }

  function buildKnowledgeUniverse(rawGraph) {
    rawGraph = rawGraph || {};
    var rawNodes = safeArray(rawGraph.nodes);
    var rawEdges = safeArray(rawGraph.edges).map(function (edge) {
      return [firstDefined(edge && edge[0], edge && edge.source, ""), firstDefined(edge && edge[1], edge && edge.target, ""), firstDefined(edge && edge[2], edge && edge.label, "")];
    }).filter(function (edge) {
      return edge[0] && edge[1];
    });
    var questions = safeArray(rawGraph.questions);
    var degreeMap = {};
    rawEdges.forEach(function (edge) {
      degreeMap[edge[0]] = (degreeMap[edge[0]] || 0) + 1;
      degreeMap[edge[1]] = (degreeMap[edge[1]] || 0) + 1;
    });

    var clusterAnchors = {
      plan: { x: 50, y: 48, radius: 12 },
      KPI: { x: 20, y: 18, radius: 16 },
      business_unit: { x: 79, y: 24, radius: 16 },
      finding: { x: 18, y: 60, radius: 16 },
      document: { x: 16, y: 84, radius: 14 },
      vendor: { x: 86, y: 46, radius: 15 },
      invoice: { x: 38, y: 86, radius: 14 },
      contract: { x: 82, y: 80, radius: 14 },
      evidence: { x: 52, y: 14, radius: 12 },
      source: { x: 66, y: 86, radius: 12 },
      relationship: { x: 58, y: 62, radius: 12 },
      business_driver: { x: 33, y: 54, radius: 17 },
      comparator: { x: 74, y: 32, radius: 15 },
      evidence_gap: { x: 76, y: 70, radius: 15 },
      signal: { x: 32, y: 36, radius: 14 }
    };

    var primaryNodes = rawNodes.map(function (node, index) {
      var category = normalizeKgCategory(firstDefined(node && node.category, node && node.type, node && node.domain, node && node.properties && node.properties.domain, "signal"));
      var degree = degreeMap[node.id] || 0;
      var baseRadius = clampNumber(firstDefined(node && node.r, node && node.importance, 8), 6, 15);
      var importance = clampNumber(baseRadius * 6 + degree * 8 + (category === "plan" ? 18 : 0) + (category === "KPI" ? 10 : 0), 38, 100);
      return {
        id: firstDefined(node && node.id, safeNodeId(node && node.label, index)),
        label: firstDefined(node && node.label, "Node " + (index + 1)),
        short_label: firstDefined(node && node.short_label, node && node.label, "Node " + (index + 1)),
        category: category,
        detail: firstDefined(node && node.detail, node && node.description, node && node.value, "No additional detail available."),
        hermes_prompt: firstDefined(node && node.hermes_prompt, "Tell me about " + firstDefined(node && node.label, "this node") + "."),
        properties: (node && node.properties) || {},
        importance: importance,
        source_count: Math.max(2, degree + Math.round((String(firstDefined(node && node.detail, "")).length || 0) / 70) + 1),
        primary_degree: degree,
        kind: "primary",
        synthetic: false,
        label_priority: category === "plan" || importance >= 76,
        x: Number(node && node.x),
        y: Number(node && node.y),
        r: baseRadius,
        focus_anchor: firstDefined(node && node.id, safeNodeId(node && node.label, index))
      };
    });

    var groups = {};
    primaryNodes.forEach(function (node) {
      var category = node.category || "signal";
      if (!groups[category]) groups[category] = [];
      groups[category].push(node);
    });

    Object.keys(groups).forEach(function (category) {
      var anchor = clusterAnchors[category] || clusterAnchors.signal;
      var group = groups[category].slice().sort(function (left, right) {
        return Number(right.importance || 0) - Number(left.importance || 0);
      });
      group.forEach(function (node, index) {
        if (category === "plan" && index === 0) {
          node.x = 50;
          node.y = 48;
          node.r = Math.max(node.r, 15);
          node.label_priority = true;
          return;
        }
        var ring = Math.floor(index / 3);
        var orbit = anchor.radius + ring * 10 + (kgUnit(node.id, "orbit") * 3.8);
        var angle = ((Math.PI * 2) / Math.max(group.length, 1)) * index + kgUnit(node.id, "angle") * 0.95 - 0.45;
        var ellipse = 0.84 + kgUnit(node.id, "ellipse") * 0.34;
        node.x = clampNumber(anchor.x + Math.cos(angle) * orbit, 7, 93);
        node.y = clampNumber(anchor.y + Math.sin(angle) * orbit * ellipse, 8, 92);
        node.r = Math.max(node.r, node.label_priority ? 10.8 : 7.6);
      });
    });

    var universeNodes = primaryNodes.slice();
    var universeEdges = rawEdges.slice();

    return {
      questions: questions,
      nodes: universeNodes,
      edges: universeEdges,
      raw_node_count: primaryNodes.length,
      synthetic_node_count: Math.max(0, universeNodes.length - primaryNodes.length),
      visible_label_count: primaryNodes.filter(function (node) { return node.label_priority; }).length,
      evidence_coverage: primaryNodes.reduce(function (sum, node) { return sum + Number(node.source_count || 0); }, 0)
    };
  }

  function getKnowledgeGraph() {
    var shared = getSharedAssistantContext();
    if (safeArray(shared.kg_nodes).length) {
      return buildKnowledgeUniverse({
        questions: safeArray(shared.kg_questions).length ? safeArray(shared.kg_questions) : [
          {
            id: "shared-public-packet",
            label: "CEO KPI evidence",
            focus: safeArray(shared.kg_nodes).map(function (node) { return node.id; })
          }
        ],
        nodes: safeArray(shared.kg_nodes).map(function (node, index) {
          return {
            id: firstDefined(node && node.id, safeNodeId(node && node.label, index)),
            label: firstDefined(node && node.label, "Node " + (index + 1)),
            short_label: firstDefined(node && node.short_label, node && node.label, "Node " + (index + 1)),
            category: normalizeKgCategory(firstDefined(node && node.category, node && node.properties && node.properties.domain, "signal")),
            detail: firstDefined(node && node.properties && (node.properties.detail || node.properties.value || node.properties.vs_plan), node && node.detail, "No additional detail available."),
            hermes_prompt: firstDefined(node && node.hermes_prompt, "Explain " + firstDefined(node && node.label, "this board signal") + " in the current strategy context."),
            properties: (node && node.properties) || {},
            r: clampNumber(firstDefined(node && node.r, 10), 7, 13)
          };
        }),
        edges: safeArray(shared.kg_edges).map(function (edge) {
          return [edge.source, edge.target, edge.label];
        })
      });
    }
    return buildKnowledgeUniverse({ questions: [], nodes: [], edges: [] });
  }

  function getPlanHealth() {
    return (state.latestPacket && state.latestPacket.plan_health) || {};
  }

  function getDrilldown() {
    return (state.latestPacket && state.latestPacket.drilldown) || {};
  }

  function getAgentsModule() {
    return (state.latestPacket && state.latestPacket.agent_modules) || {};
  }

  function getAgentActivitySummary() {
    var shared = getSharedAssistantContext();
    return shared.agent_activity || {};
  }

  function getRunningAgents() {
    var shared = getSharedAssistantContext();
    var modules = getAgentsModule();
    if (safeArray(shared.running_agents).length) return safeArray(shared.running_agents);
    return safeArray(modules.running);
  }

  function getDiscoverableAgents() {
    var modules = getAgentsModule();
    return safeArray(modules.discoverable);
  }

  function discoverableAgentId(item, index) {
    return String(firstDefined(
      item && item.id,
      item && item.module_id,
      item && item.connector,
      item && item.route,
      item && item.name,
      item && item.label,
      'agent-' + index
    ));
  }

  function discoverableAgentSource(item) {
    var source = String(firstDefined(item && item.source, '')).toLowerCase();
    if (source) return source;
    var id = String(firstDefined(item && item.id, item && item.module_id, '')).toLowerCase();
    var by = String(firstDefined(item && item.by, '')).toLowerCase();
    if (id.indexOf('connector-') === 0 || by === 'connector catalog') return 'market';
    return 'native';
  }

  function discoverableAgentRoute(item) {
    var explicitRoute = String(firstDefined(item && item.route, item && item.primary_route, ''));
    if (explicitRoute) return explicitRoute;
    var connector = String(firstDefined(item && item.connector, ''));
    if (connector.charAt(0) === '/') return connector;
    var agents = (state.latestPacket && state.latestPacket.agents) || {};
    var discover = agents.discover || {};
    return String(firstDefined(discover.deploy_route, '/ingestion/connectors'));
  }

  function discoverableAgentLabel(item) {
    return String(firstDefined(item && item.name, item && item.label, item && item.module_id, 'Agent'));
  }

  function laneRouteForDiscoverableAgent(item) {
    var lane = String(firstDefined(item && item.lane, '')).toLowerCase();
    if (lane === 'review') return '/app?lane=review#review';
    if (lane === 'operate' || lane === 'operator') return '/app?lane=operate';
    if (lane === 'system' || lane === 'tenant_admin') return '/app?lane=system';
    return '/app?lane=operate';
  }

  function navigateToRoute(route, sourceEl) {
    var target = String(route || '').trim();
    if (!target) return false;
    var anchor = document.createElement('a');
    anchor.href = target;
    if (anchor.pathname === window.location.pathname && anchor.search === window.location.search) {
      showToast('This workspace surface is already open.');
      if (sourceEl && typeof sourceEl.focus === 'function') sourceEl.focus();
      return true;
    }
    window.location.assign(target);
    return true;
  }

  function getApprovalAgents() {
    var modules = getAgentsModule();
    return safeArray(modules.approvals);
  }

  function getSubtools() {
    return [];
  }

  function getVisibleDrivers() {
    var packetDrivers = safeArray(getExecutiveDiagnostics().driver_grid);
    return packetDrivers.slice(0, 4);
  }

  function getActiveDriver() {
    var drivers = getVisibleDrivers();
    var active = drivers.find(function (item) {
      return String(item.driver_key || item.key || "") === String(state.activeDriverKey || "");
    });
    return active || drivers[0] || null;
  }

  function getHeroPrompts() {
    var gravity = getDrilldown().gravity || {};
    var chatPrompts = safeArray(getChatContract().starter_prompts);
    return safeArray(gravity.prompts).length ? safeArray(gravity.prompts) : chatPrompts;
  }

  function storageArea() {
    var persistence = ((getChatContract().store || {}).persistence || "sessionStorage").toLowerCase();
    return persistence === "localstorage" ? window.localStorage : window.sessionStorage;
  }

  function threadStorageKey() {
    var chat = getChatContract();
    var prefix = firstDefined((chat.store || {}).storage_key_prefix, "strategyos.chat.").replace(/\.$/, "");
    var runId = firstDefined(chat.run_id, state.latestPacket && state.latestPacket.run_id, "latest");
    return [prefix, runId, state.activePersona].join(".");
  }

  function nowStamp() {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function loadStoredThreads() {
    try {
      var raw = storageArea().getItem(threadStorageKey());
      return raw ? JSON.parse(raw) : {};
    } catch (error) {
      return {};
    }
  }

  function saveStoredThreads() {
    try {
      storageArea().setItem(threadStorageKey(), JSON.stringify(threadStore()));
    } catch (error) {}
  }

  function personaThreadRecords() {
    var prefix = state.activePersona + ":";
    return Object.keys(threadStore()).filter(function (key) {
      return key.indexOf(prefix) === 0;
    }).map(function (key) {
      return threadStore()[key];
    }).sort(function (left, right) {
      var leftTime = new Date(firstDefined(left && left.lastUpdated, "1970-01-01T00:00:00Z")).getTime();
      var rightTime = new Date(firstDefined(right && right.lastUpdated, "1970-01-01T00:00:00Z")).getTime();
      leftTime = Number.isNaN(leftTime) ? 0 : leftTime;
      rightTime = Number.isNaN(rightTime) ? 0 : rightTime;
      if (leftTime !== rightTime) return rightTime - leftTime;
      return String(firstDefined(left && left.title, "")).localeCompare(String(firstDefined(right && right.title, "")));
    });
  }

  function metricNumber(value) {
    var text = String(firstDefined(value, "")).replace(/,/g, "");
    var match = text.match(/-?\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : null;
  }

  function driverTrendSeries(driver) {
    var trend = safeArray((state.latestPacket && state.latestPacket.trend && state.latestPacket.trend.points) || []);
    var key = String(firstDefined(driver.driver_key, driver.key, "")).toLowerCase();
    if (!trend.length) return { actual: [], plan: [] };
    var actual = trend.slice(-6).map(function (point) {
      if (/cash|liq/.test(key)) return Number(firstDefined(point.cash_on_hand_sar, point.recoverable_sar, point.findings, 0)) || 0;
      if (/cost/.test(key)) return Number(firstDefined(point.invoice_amount_sar, point.recoverable_sar, point.findings, 0)) || 0;
      if (/margin|ebitda|bridge/.test(key)) return Number(firstDefined(point.recoverable_sar, point.locked_findings, point.findings, 0)) || 0;
      return Number(firstDefined(point.findings, point.locked_findings, point.recoverable_sar, 0)) || 0;
    });
    var pct = Math.max(1, Number(firstDefined(driver.pct, 100)) || 100);
    var denominator = pct / 100;
    var plan = actual.map(function (value) {
      return denominator ? value / denominator : value;
    });
    return { actual: actual, plan: plan };
  }

  function buildDriverSparkline(driver, index) {
    var series = driverTrendSeries(driver);
    var values = safeArray(series.actual).slice();
    if (!values.length) {
      var base = Number(firstDefined(driver.pct, 0)) || 0;
      var lift = safeArray((driver.movers || {}).lifting).length * 2;
      var drag = safeArray((driver.movers || {}).dragging).length;
      values = [base - drag - 4, base - drag, base, base + lift - 1, base + lift, base + lift + (index || 0)];
    }
    var min = Math.min.apply(null, values);
    var max = Math.max.apply(null, values);
    var span = Math.max(1, max - min);
    var width = 124;
    var height = 30;
    var points = values.map(function (value, idx) {
      var x = values.length === 1 ? width / 2 : (idx * width) / (values.length - 1);
      var y = height - (((value - min) / span) * 22 + 4);
      return [x, y];
    });
    var line = points.map(function (pair) { return pair[0].toFixed(1) + "," + pair[1].toFixed(1); }).join(" ");
    var area = "0," + height + " " + line + " " + width + "," + height;
    return { line: line, area: area };
  }

  function driverRingMarkup(driver) {
    var size = 104;
    var stroke = 5;
    var ringMax = 400 / 3;
    var radius = (size - stroke) / 2 - 8;
    var circumference = 2 * Math.PI * radius;
    if (!driverHasPercent(driver)) {
      return '<svg class="driver-ring driver-ring--neutral" viewBox="0 0 104 104" aria-hidden="true"><circle class="driver-ring__track" cx="52" cy="52" r="41.5"></circle></svg>';
    }
    var pct = Math.max(0, driverPercentValue(driver));
    // Preserve the reference gauge: 100% is an explicit tick at three quarters
    // of the circle, leaving visible headroom for over-plan performance.
    var frac = Math.max(0.02, Math.min(pct, ringMax) / ringMax);
    var dash = circumference * frac;
    var tickAngle = (100 / ringMax) * 360 - 90;
    var tickRad = tickAngle * Math.PI / 180;
    var cos = Math.cos(tickRad);
    var sin = Math.sin(tickRad);
    var tangentCos = -sin;
    var tangentSin = cos;
    var apexRadius = radius + stroke / 2 + 1.5;
    var baseRadius = radius + stroke / 2 + 7;
    var halfWidth = 3.1;
    var apexX = (52 + apexRadius * cos).toFixed(2);
    var apexY = (52 + apexRadius * sin).toFixed(2);
    var base1X = (52 + baseRadius * cos + halfWidth * tangentCos).toFixed(2);
    var base1Y = (52 + baseRadius * sin + halfWidth * tangentSin).toFixed(2);
    var base2X = (52 + baseRadius * cos - halfWidth * tangentCos).toFixed(2);
    var base2Y = (52 + baseRadius * sin - halfWidth * tangentSin).toFixed(2);
    var tone = String(firstDefined(driver && driver.tone, "flat")).toLowerCase();
    if (["up", "flat", "down"].indexOf(tone) === -1) tone = "flat";
    return '<svg class="driver-ring" viewBox="0 0 104 104" aria-hidden="true"><circle class="driver-ring__track" cx="52" cy="52" r="41.5"></circle><circle class="driver-ring__value driver-ring__value--' + tone + '" cx="52" cy="52" r="41.5" stroke-dasharray="' + dash + ' ' + circumference + '" transform="rotate(-90 52 52)"></circle><polygon class="driver-ring__tick" points="' + apexX + ',' + apexY + ' ' + base1X + ',' + base1Y + ' ' + base2X + ',' + base2Y + '"></polygon></svg>';
  }

  function driverHasPercent(driver) {
    return driver && Number.isFinite(driverPercentValue(driver));
  }

  function driverPercentValue(driver) {
    if (!driver) return NaN;
    var value = firstDefined(driver.ring_pct, driver.pct, null);
    return value === null || value === "" ? NaN : Number(value);
  }

  function driverCenterMarkup(driver) {
    if (driver && driver.availability === "unavailable") {
      return '<div class="driver-pct driver-pct--metric"><span class="driver-pct__main">—</span><span class="driver-pct__unit">data gap</span></div>';
    }
    if (driverHasPercent(driver)) {
      return '<div class="driver-pct">' + escapeHtml(driverPercentValue(driver).toFixed(1)) + '<span class="pct-sign">%</span></div><div class="driver-ofplan">' + escapeHtml(driverRingCaption(driver)) + '</div>';
    }
    var metric = String(firstDefined(driver && driver.metric, '—')).trim();
    var parts = metric.split(/\s+/);
    var main = parts.shift() || '—';
    var rest = parts.join(' ');
    return '<div class="driver-pct driver-pct--metric"><span class="driver-pct__main">' + escapeHtml(main) + '</span>' + (rest ? '<span class="driver-pct__unit">' + escapeHtml(rest) + '</span>' : '') + '</div>';
  }

  function driverRingCaption(driver) {
    var key = String(firstDefined(driver && driver.driver_key, driver && driver.key, ""));
    if (key === "ebitda_margin") return "margin";
    if (key === "operating_cost") return "of revenue";
    if (key === "cash_vs_floor") return "of floor";
    return "of plan";
  }

  function driverMeasureLabel(driver) {
    if (driver && driver.availability === "unavailable") {
      return "Not calculated";
    }
    if (driverHasPercent(driver)) {
      return String(driverPercentValue(driver).toFixed(1)) + '% ' + firstDefined(driver.ring_label, 'of plan');
    }
    return firstDefined(driver && driver.metric, 'Current value');
  }

  function driverSubLabel(driver) {
    return governedMeasureLabel(firstDefined(driver && driver.sub, driver && driver.trend_hint, 'Current measure'));
  }

  function unavailableDriverMarkup(driver) {
    var inputs = safeArray(driver && driver.missing_inputs);
    var needs = inputs.length ? inputs.join(" · ") : "Reconciled finance inputs";
    return [
      '<div class="driver-unavailable" aria-label="Finance data required">',
      '<span class="driver-unavailable__eyebrow">Finance data required</span>',
      '<strong class="driver-unavailable__title">Not calculated</strong>',
      '<p class="driver-unavailable__copy">' + escapeHtml(needs) + '</p>',
      '<span class="driver-unavailable__cta">View formula and data request →</span>',
      '</div>'
    ].join("");
  }

  function qaAnswerText(payload) {
    if (!payload) return "I could not reach the Q&A service. Try again from an authenticated session.";
    var answer = scrubExecutiveTechnicalLanguage(cleanVisibleQaAnswer(firstDefined(payload.answer, "")));
    return answer || "No answer returned at this time.";
  }

  function executiveEvidenceBasis(basis) {
    var raw = String(basis || "");
    if (/\bscenario parser\b/i.test(raw) || /\bparser\b/i.test(raw) || /\bfinance_leakage\b/i.test(raw) || /\brun findings\b/i.test(raw)) {
      return "Calculated from current reviewed findings";
    }
    var text = scrubExecutiveTechnicalLanguage(cleanMetaText(basis));
    if (!text) return "";
    return text;
  }

  function executiveEvidenceConfidence(level, citations) {
    var clean = String(level || "").trim().toLowerCase();
    if (!clean) return citations > 0 ? "Evidence-backed" : "";
    if (clean === "none") return citations > 0 ? "Partial" : "Not yet grounded";
    if (clean === "low" || clean === "strong") return "Strong";
    if (clean === "medium" || clean === "partial") return "Partial";
    if (clean === "high") return "Needs review";
    return humanizeToken(clean);
  }

  function qaAnswerMeta(payload) {
    if (!payload || typeof payload !== 'object') return "";
    var parts = [];
    var basis = cleanMetaText(firstDefined(payload.basis, payload.trace && payload.trace.basis));
    var calculations = safeArray(payload.calculations);
    var citations = safeArray(payload.citations);
    var risk = payload.hallucination_risk || (payload.risk_metadata && payload.risk_metadata.hallucination_risk) || {};
    var riskLevel = cleanMetaText(firstDefined(risk.level, ""));
    var groundingStatus = String(firstDefined(payload.grounding_status, "")).trim().toLowerCase();
    var scenarioType = cleanMetaText(firstDefined(payload.scenario_type, ""));
    var modelProvided = String(firstDefined(payload.answer_origin, "")).toLowerCase() === "llm"
      || String(firstDefined(payload.answered_by, "")).toLowerCase() === "llm"
      || String(firstDefined(payload.assistant_mode, "")).toLowerCase() === "llm";

    if (modelProvided) {
      parts.push("AI-generated answer");
      parts.push("Not calculated");
      parts.push("Review before use");
    }

    // Bug 5 fix: derive grounding level from actual evidence when the backend
    // reports "none" but citations exist — these are contradictory signals.
    if (riskLevel === "none" && citations.length > 0) {
      riskLevel = citations.length >= 3 ? "strong" : "partial";
    }
    var executiveBasis = executiveEvidenceBasis(basis);
    var confidence = groundingStatus === "grounded"
      ? "Grounded"
      : (groundingStatus === "needs_evidence" || groundingStatus === "not_grounded"
        ? "Needs evidence"
        : executiveEvidenceConfidence(riskLevel, citations.length));
    if (executiveBasis && !modelProvided) parts.push("Evidence basis: " + executiveBasis);
    if (!modelProvided && calculations.length) parts.push("Calculation: " + calculations.length + " check" + (calculations.length === 1 ? "" : "s") + " reconciled");
    if (citations.length) parts.push("Evidence: " + citations.length + " source" + (citations.length === 1 ? "" : "s") + " checked");
    if (scenarioType && scenarioType !== "deterministic") parts.push("Scenario status: " + humanizeToken(scenarioType).toLowerCase());
    if (confidence) parts.push("Evidence confidence: " + confidence);
    return parts.join(" · ");
  }

  function cleanMetaText(value) {
    var text = String(value || "").trim();
    if (!text) return "";
    text = text.replace(/\b(?:llm|vector|graph)\b/gi, "assistant");
    text = text.replace(/\b(?:run|path|risk):\s*[^\n]+/gi, " ");
    text = text.replace(/\b(?:run_artifacts|public_packet|neo4j|qdrant|external):\/\/[^\s,;]+/gi, "source");
    text = text.replace(/\[[^\]]+\]/g, " ");
    text = text.replace(/\s+/g, " ").trim();
    return text.slice(0, 180);
  }

  function cleanVisibleQaAnswer(value) {
    if (value == null) return "";
    if (Array.isArray(value)) {
      return value.map(function (item) { return cleanVisibleQaAnswer(item); }).filter(Boolean).join(" ").trim();
    }
    if (typeof value === 'object') {
      if (value.answer !== undefined) return cleanVisibleQaAnswer(value.answer);
      try { return JSON.stringify(value); } catch (_error) { return String(value); }
    }
    var text = String(value || '').trim();
    if (!text) return '';
    var fenced = text.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
    if (fenced) text = String(fenced[1] || '').trim();
    var parsed = maybeParseQaJson(text);
    if (parsed && typeof parsed === 'object' && parsed.answer !== undefined) {
      var nested = cleanVisibleQaAnswer(parsed.answer);
      if (nested) return nested;
    }
    var extracted = extractAnswerFieldFromJsonishText(text);
    if (extracted) return scrubVisibleQaAnswerText(extracted);
    return scrubVisibleQaAnswerText(text);
  }

  function scrubVisibleQaAnswerText(text) {
    text = String(text || '').trim();
    if (!text) return '';
    text = text.replace(/\[[^\]]*(?:path:|run:|risk:|deterministic|public-safe|handler|llm|vector|graph)[^\]]*\]/gi, ' ');
    text = text.replace(/(?:^|\s)(?:path|run|risk):\s*[^\n]+/gi, ' ');
    text = text.replace(/\bI can answer board-safe questions[^.]*\.?/gi, ' ');

    [
      [/\bFrom the current public packet,\s*/gi, ''],
      [/\bFrom the public packet,\s*/gi, ''],
      [/\bThe public packet shows\s*/gi, 'Visible facts show '],
      [/\bThe visible packet shows\s*/gi, 'Visible facts show '],
      [/\bSince last week, the visible packet shows\s*/gi, 'Since last week, visible facts show '],
      [/\bI do not have a standalone last-week ledger cut in the public packet, but\s*/gi, 'I do not have a standalone last-week ledger cut here, but '],
      [/\bshared public packet\b/gi, 'current business context'],
      [/\bpublic executive packet\b/gi, 'current business context'],
      [/\bcurrent public packet\b/gi, 'current business context'],
      [/\bvisible packet\b/gi, 'current business context'],
      [/\bpublic packet\b/gi, 'current business context'],
      [/\bthe packet\b/gi, 'the current view'],
      [/\bpacket\b/gi, 'current view'],
      [/\bpublic-safe\b/gi, ''],
      [/\bdeterministic\b/gi, ''],
      [/\bhandler\b/gi, ''],
      [/\bvector\b/gi, ''],
      [/\bgraph\b/gi, ''],
      [/\bllm\b/gi, 'AI']
    ].forEach(function (entry) {
      text = text.replace(entry[0], entry[1]);
    });

    var parts = text.split(/(?<=[.!?])\s+/);
    var seen = {};
    var deduped = [];
    parts.forEach(function (part) {
      var sentence = String(part || '').trim();
      if (!sentence) return;
      var normalized = sentence.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
      if (!normalized || seen[normalized]) return;
      seen[normalized] = true;
      deduped.push(sentence);
    });
    text = (deduped.length ? deduped.join(' ') : text)
      .replace(/\s+/g, ' ')
      .replace(/\s+([,.;:!?])/g, '$1')
      .trim();
    return scrubExecutiveTechnicalLanguage(text);
  }

  function maybeParseQaJson(text) {
    var raw = String(text || '').trim();
    if (!raw) return null;
    for (var depth = 0; depth < 3; depth += 1) {
      try {
        var parsed = JSON.parse(raw);
        if (typeof parsed === 'string') {
          raw = parsed.trim();
          continue;
        }
        return parsed;
      } catch (_error) {
        return null;
      }
    }
    return null;
  }

  function extractAnswerFieldFromJsonishText(text) {
    var match = String(text || '').match(/"answer"\s*:\s*"((?:\\.|[^"\\])*)"/s);
    if (!match) return '';
    try {
      return JSON.parse('"' + match[1] + '"').trim();
    } catch (_error) {
      return String(match[1] || '').replace(/\\n/g, '\n').replace(/\\"/g, '"').trim();
    }
  }

  var ASSISTANT_TRANSPORT_FAILURE_TEXT = ASSISTANT_TRANSPORT_FALLBACK;

  function boardSafeStatusReply(message) {
    return [
      ASSISTANT_TRANSPORT_FAILURE_TEXT,
      message ? "Question asked: \u201c" + message + "\u201d." : "",
      "Please try again in a moment or reopen the board assistant."
    ].filter(Boolean).join(" ");
  }

  function isLegacyAssistantTransportFallback(text) {
    return String(text || "").indexOf(ASSISTANT_TRANSPORT_FAILURE_TEXT) !== -1;
  }

  function inferRetryPrompt(messages, index) {
    for (var cursor = index - 1; cursor >= 0; cursor -= 1) {
      var candidate = messages[cursor] || {};
      if (candidate.role === "user") {
        var prompt = String(firstDefined(candidate.text, "")).trim();
        if (prompt) return prompt;
      }
    }
    return "";
  }

  function summarizeAssistantFailure(message) {
    return message && message.retryable === false
      ? "Hermes is unavailable for this request."
      : "Hermes is temporarily unavailable. Your question is preserved and can be retried.";
  }

  function buildRetryPreview(prompt) {
    var cleanPrompt = String(prompt || "").trim();
    return cleanPrompt ? "Retry needed · " + wordSlice(cleanPrompt, 68) : "Retry needed · Assistant response unavailable";
  }

  function latestRetryableAssistantFailure(thread) {
    var messages = safeArray(thread && thread.messages);
    for (var index = messages.length - 1; index >= 0; index -= 1) {
      var message = messages[index] || {};
      if (message.role === "assistant" && message.status === "failed" && message.retryable !== false) {
        return { index: index, message: message };
      }
    }
    return null;
  }

  function recalcThreadPreview(thread) {
    if (!thread) return;
    var messages = safeArray(thread.messages);
    var fallbackPreview = firstDefined(thread.preview, "Board-safe follow-up");
    for (var index = messages.length - 1; index >= 0; index -= 1) {
      var message = messages[index] || {};
      var text = String(firstDefined(message.text, "")).trim();
      if (!text) continue;
      if (message.role === "assistant" && message.status === "failed") {
        thread.preview = buildRetryPreview(firstDefined(message.retryPrompt, inferRetryPrompt(messages, index), ""));
        return;
      }
      thread.preview = wordSlice(text, 84);
      return;
    }
    thread.preview = fallbackPreview;
  }

  function markThreadTransportFailuresRetryable(thread) {
    if (!thread || !safeArray(thread.messages).length) return false;
    var changed = false;
    thread.messages = safeArray(thread.messages).map(function (message, index, messages) {
      if (!message || message.role !== "assistant") return message;
      if (message.status === "failed") {
        if (!message.retryPrompt) {
          message.retryPrompt = inferRetryPrompt(messages, index);
          changed = true;
        }
        if (!message.endpoint) {
          message.endpoint = "/assistant/chat";
          changed = true;
        }
        if (!message.errorType) {
          message.errorType = "transport_failure";
          changed = true;
        }
        if (!message.text) {
          message.text = "Hermes could not reach the shared assistant service. Retry now once the service is reachable.";
          changed = true;
        }
        message.retryable = true;
        message.needsRetry = true;
        message.autoRetryEligible = false;
        return message;
      }
      if (!isLegacyAssistantTransportFallback(message.text)) return message;
      changed = true;
      return {
        role: "assistant",
        text: "Hermes could not reach the shared assistant service. Retry now once the service is reachable.",
        timestamp: firstDefined(message.timestamp, new Date().toISOString()),
        status: "failed",
        retryable: true,
        needsRetry: true,
        autoRetryEligible: false,
        retryPrompt: inferRetryPrompt(messages, index),
        endpoint: "/assistant/chat",
        errorType: "stale_transport_fallback"
      };
    });
    if (changed) recalcThreadPreview(thread);
    return changed;
  }

  function logAssistantTransportFailure(details) {
    console.error("[Hermes] assistant transport failure", details);
  }

  function makeAssistantFailureResult(message, details) {
    var metadata = details || {};
    var result = {
      ok: false,
      answer: "Hermes could not reach the shared assistant service. Retry now once the service is reachable.",
      endpoint: firstDefined(metadata.endpoint, "/assistant/chat"),
      statusCode: firstDefined(metadata.statusCode, ""),
      requestId: firstDefined(metadata.requestId, ""),
      errorType: firstDefined(metadata.errorType, "transport_failure"),
      retryPrompt: String(message || "").trim(),
      retryable: true,
      needsRetry: true,
      autoRetryEligible: false,
      transient: true
    };
    logAssistantTransportFailure({
      endpoint: result.endpoint,
      status: result.statusCode || null,
      requestId: result.requestId || null,
      errorType: result.errorType,
      prompt: result.retryPrompt,
      details: metadata.details || null,
      responseBody: metadata.responseBody || ""
    });
    return result;
  }

  function assistantAnswerCacheKey(question, assistantContext) {
    var context = assistantContext && typeof assistantContext === "object" ? assistantContext : {};
    return [
      String(state.activePersona || "ceo"),
      String(firstDefined(context.entrypoint, "drawer_input")),
      String(firstDefined(context.kpi_key, context.driver_key, "none")),
      String(firstDefined(context.kpi_question_intent, "free_text")),
      String(question || "").trim().toLowerCase().replace(/\s+/g, " ")
    ].join("::");
  }

  function loadAssistantAnswerCache() {
    try {
      var raw = window.localStorage.getItem("strategyos.hermes.answer-cache.v1");
      var parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_error) {
      return {};
    }
  }

  function rememberAssistantAnswer(question, result, assistantContext) {
    if (!result || !result.ok || !String(result.answer || "").trim()) return;
    try {
      var cache = loadAssistantAnswerCache();
      cache[assistantAnswerCacheKey(question, assistantContext)] = {
        answer: result.answer,
        metadata: result.metadata || "",
        responsePayload: result.responsePayload || null,
        savedAt: new Date().toISOString()
      };
      var keys = Object.keys(cache).sort(function (left, right) {
        return String((cache[right] || {}).savedAt || "").localeCompare(String((cache[left] || {}).savedAt || ""));
      });
      keys.slice(25).forEach(function (key) { delete cache[key]; });
      window.localStorage.setItem("strategyos.hermes.answer-cache.v1", JSON.stringify(cache));
    } catch (_error) {}
  }

  function cachedAssistantFallback(question, failure, assistantContext) {
    var cached = loadAssistantAnswerCache()[assistantAnswerCacheKey(question, assistantContext)];
    if (!cached || !String(cached.answer || "").trim()) return failure;
    var savedAt = new Date(cached.savedAt || "");
    var displayTime = Number.isNaN(savedAt.getTime())
      ? "an earlier session"
      : savedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return {
      ok: true,
      answer: "Live assistant is temporarily unavailable. Showing the last known answer from " + displayTime + ".\n\n" + cached.answer,
      metadata: [cached.metadata, "Cached fallback · live transport unavailable"].filter(Boolean).join(" · "),
      responsePayload: cached.responsePayload || null,
      requestId: failure && failure.requestId,
      endpoint: failure && failure.endpoint,
      cachedFallback: true
    };
  }

  function applyAssistantResultToMessage(thread, message, result) {
    if (!thread || !message || !result) return;
    if (result.ok) {
      message.text = result.answer;
      message.meta = firstDefined(result.metadata, "");
      message.payload = result.responsePayload || null;
      message.caseLinks = safeArray(result.responsePayload && result.responsePayload.case_links);
      message.timestamp = new Date().toISOString();
      message.status = "ok";
      message.retryable = false;
      message.needsRetry = false;
      message.autoRetryEligible = false;
      delete message.retryPrompt;
      delete message.requestId;
      delete message.statusCode;
      delete message.errorType;
      delete message.endpoint;
      delete message.transient;
    } else {
      message.text = result.answer;
      message.meta = "";
      message.payload = null;
      message.caseLinks = [];
      message.timestamp = new Date().toISOString();
      message.status = "failed";
      message.retryable = result.retryable !== false;
      message.needsRetry = result.needsRetry !== false;
      message.autoRetryEligible = result.autoRetryEligible === true;
      message.retryPrompt = firstDefined(result.retryPrompt, message.retryPrompt, "");
      message.requestId = firstDefined(result.requestId, "");
      message.statusCode = firstDefined(result.statusCode, "");
      message.errorType = firstDefined(result.errorType, "transport_failure");
      message.endpoint = firstDefined(result.endpoint, "/assistant/chat");
      message.transient = result.transient !== false;
    }
    thread.lastUpdated = new Date().toISOString();
    recalcThreadPreview(thread);
  }

  function openAssistantCase(findingId, sourceEl) {
    var targetId = String(findingId || '').trim();
    var findingsSection = ((getExecutiveDiagnostics().sections || {}).findings || {});
    var findings = safeArray(findingsSection.case_index).length
      ? safeArray(findingsSection.case_index)
      : safeArray(findingsSection.items);
    var index = findings.findIndex(function (item) {
      return String(firstDefined(item && item.finding_id, '')) === targetId;
    });
    if (index < 0) {
      showToast('That case is no longer available in the current review.');
      return;
    }
    state.selectedFindingId = targetId;
    state.openDriverNoteKey = 'finding:' + targetId;
    _closeHermesDrawer();
    switchView('home');
    window.setTimeout(function () {
      renderLowerRailFidelity();
      var caseControl = document.querySelector('[data-finding-id="' + targetId.replace(/"/g, '\\"') + '"]');
      if (caseControl && typeof caseControl.scrollIntoView === 'function') {
        caseControl.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
      if (sourceEl && typeof sourceEl.focus === 'function') sourceEl.focus();
    }, 0);
  }

  function assistantEntrypointContext(sourceEl) {
    var activeDriver = getActiveDriver();
    var element = sourceEl && typeof sourceEl === "object" && sourceEl.nodeType === 1 ? sourceEl : null;
    var driverComposerSelector = "#driver" + "-composer";
    var weekComposerSelector = "#week" + "-composer";
    var entrypoint = "drawer_input";
    var contextualKpiKey = element ? String(element.getAttribute("data-kpi-key") || "").trim() : "";
    var contextualKpiLabel = element ? String(element.getAttribute("data-kpi-label") || "").trim() : "";
    if (element) {
      if (contextualKpiKey) entrypoint = "ceo_kpi_inline";
      else if (element.id === "kg-inspector-ask") entrypoint = "knowledge_graph";
      else if (element.id === "leaders-hermes-cta" || element.id === "video-hermes-cta") entrypoint = "leaders_corner";
      else if (element.classList.contains("disco-browse")) entrypoint = "agents_discovery";
      else if (element.getAttribute("data-board-prompt") !== null || element.getAttribute("data-board-action") !== null) entrypoint = "board_portal";
      else if (element.closest(driverComposerSelector)) entrypoint = "driver_composer";
      else if (element.getAttribute("data-driver-chip") !== null) entrypoint = "driver_chip";
      else if (element.getAttribute("data-rail-prompt") !== null && element.closest("#developments-panel")) entrypoint = "development_cta";
      else if (element.getAttribute("data-rail-prompt") !== null) entrypoint = "finding_cta";
      else if (element.closest(weekComposerSelector)) entrypoint = "week_composer";
      else if (element.getAttribute("data-chat-prompt") !== null) entrypoint = "scenario_chip";
      else if (element.getAttribute("data-assistant-prompt") !== null) entrypoint = "assistant_prompt";
      else if (element.classList.contains("prompt-chip")) entrypoint = "hero_prompt";
    }
    return {
      source: "executive_surface",
      entrypoint: entrypoint,
      entry_label: element ? String(element.textContent || "").trim().slice(0, 120) : "drawer_input",
      persona: state.activePersona || "ceo",
      board_state: state.activeBoard || "pre",
      // Board portal prompts must NOT carry stale hero/revenue driver_key — use
      // "board_packet" so the backend routes the question against board-relevant
      // answer chains (e.g. hedge downside, JV funding) instead of revenue context.
      driver_key: entrypoint === "board_portal" ? "board_packet" : firstDefined(contextualKpiKey, activeDriver && (activeDriver.driver_key || activeDriver.key), state.activeDriverKey, "board_packet"),
      kpi_key: contextualKpiKey || undefined,
      kpi_label: contextualKpiKey ? firstDefined(contextualKpiLabel, activeDriver && String(activeDriver.driver_key || activeDriver.key || "") === contextualKpiKey ? activeDriver.label : "") : undefined,
      thread_key: currentThreadKey(),
      active_view: state.activeView || "home"
    };
  }

  async function buildAssistantReply(message, sourceEl) {
    var hiddenContext = arguments.length > 2 ? arguments[2] : null;
    var cleanMessage = String(message || "").trim();
    if (!cleanMessage) {
      return { ok: false, answer: "Please ask a question for the assistant.", retryable: false, needsRetry: false, errorType: "empty_prompt", endpoint: "/assistant/chat" };
    }

    // Typo normalization for common misspellings before API call
    var normalizeTypos = function (q) {
      var fixes = { whar: 'what', whcih: 'which', waht: 'what', whta: 'what', wher: 'where', whne: 'when', whay: 'why', whis: 'why', hwo: 'how', wats: "what's", hows: "how's", whos: "who's", cn: 'can', shoudl: 'should', coudl: 'could', woudl: 'would', pleas: 'please', hlep: 'help' };
      return q.split(/\s+/).map(function (w) {
        var lower = w.toLowerCase().replace(/[^a-z']/g, '');
        return fixes[lower] ? w.replace(new RegExp(lower.replace(/'/g, "\\'"), 'i'), fixes[lower]) : w;
      }).join(' ');
    };
    var apiQuestion = normalizeTypos(cleanMessage);

    var body = { question: apiQuestion, mode: "auto", persona: state.activePersona || "ceo" };
    var entrypointCtx = Object.assign(
      {},
      assistantEntrypointContext(sourceEl),
      hiddenContext && typeof hiddenContext === "object" ? hiddenContext : {}
    );
    body.assistant_context = entrypointCtx;
    var activeThread = threadStore()[currentThreadKey()];
    body.assistant_context.conversation_history = safeArray(activeThread && activeThread.messages)
      .filter(function (item) {
        return item && item.status !== "pending" && (item.role === "user" || item.role === "assistant") && String(item.text || "").trim();
      })
      .slice(-8)
      .map(function (item) {
        return { role: item.role, content: String(item.text || "").trim().slice(0, 2400) };
      });
    // Board portal prompts must NOT carry hero/revenue driver_context, because
    // the board entrypoint_context already identifies board state/lifecycle and
    // stale driver metrics (e.g. driver_context.key="revenue") cause the backend
    // to answer out of context for board-specific questions like hedge downside
    // or JV funding. Only attach driver_context for non-board entrypoints so the
    // server routes the question against the correct board-relevant answer chain.
    if (entrypointCtx.entrypoint !== "board_portal") {
      var activeDriver = getActiveDriver();
      if (activeDriver) {
        body.driver_context = {
          key: activeDriver.driver_key || activeDriver.key,
          label: activeDriver.label,
          metric: activeDriver.metric || activeDriver.value,
          pct: activeDriver.pct,
          status: activeDriver.status || activeDriver.sub,
          detail: activeDriver.detail || activeDriver.story,
          movers: activeDriver.movers || {}
        };
      }
    }
    body.source = body.assistant_context.source;
    body.entrypoint = body.assistant_context.entrypoint;
    var runId = activeRunId();
    if (runId && runId !== "latest-public") body.run_id = runId;
    try {
      var endpoint = "/assistant/chat";
      var clientRequestId = "hermes-ui-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);
      body.trace_id = clientRequestId;
      var response = await postJson("/assistant/chat", body, { requestId: clientRequestId });
      var requestId = firstDefined(
        response.requestId,
        clientRequestId
      );
      var payload = response.payload;
      if (payload && payload.status === "ok") {
        var successfulResult = {
          ok: true,
          answer: qaAnswerText(payload),
          metadata: qaAnswerMeta(payload),
          responsePayload: payload,
          requestId: requestId,
          endpoint: endpoint
        };
        rememberAssistantAnswer(cleanMessage, successfulResult, entrypointCtx);
        return successfulResult;
      }
      return cachedAssistantFallback(cleanMessage, makeAssistantFailureResult(cleanMessage, {
        endpoint: endpoint,
        statusCode: response.status,
        requestId: requestId,
        errorType: "invalid_payload",
        details: "Response was reachable but did not return status=ok.",
        responseBody: payload
      }), entrypointCtx);
    } catch (error) {
      return cachedAssistantFallback(cleanMessage, makeAssistantFailureResult(cleanMessage, {
        endpoint: firstDefined(error && error.endpoint, "/assistant/chat"),
        statusCode: firstDefined(error && error.status, ""),
        requestId: firstDefined(error && error.requestId, ""),
        errorType: firstDefined(error && error.errorType, "network_error"),
        details: error && error.message ? error.message : String(error || "unknown network error")
      }), entrypointCtx);
    }
  }

  function threadStore() {
    window.STRATEGYOS_X = window.STRATEGYOS_X || { threads: {}, assistants: {} };
    return window.STRATEGYOS_X.threads;
  }

  function currentThreadKey() {
    return state.activeThreadKey || firstDefined(getChatContract().active_thread_id, state.activePersona + ":new");
  }

  function isRetiredFixtureThread(key) {
    return /:(?:briefing|hedge|recognition)$/.test(String(key || ""));
  }

  function ensureThreads() {
    var chat = getChatContract();
    var blueprint = getPersonaBlueprint(state.activePersona);
    var persona = getPersonaContract(state.activePersona);
    var assistantName = firstDefined(persona.assistant, blueprint.assistant, "Hermes");
    var persisted = loadStoredThreads();
    Object.keys(persisted).forEach(function (key) {
      if (threadStore()[key]) return;
      if (isRetiredFixtureThread(key, persisted[key])) return;
      // CEO persona: filter out stale threads that would pollute context
      if (state.activePersona === "ceo") {
        var thread = persisted[key];
        var title = String(firstDefined(thread && thread.title, '')).toLowerCase();
        var preview = String(firstDefined(thread && thread.preview, '')).toLowerCase();
        var firstMsg = (thread && safeArray(thread.messages).length) ? String(firstDefined(thread.messages[0].text, '')).toLowerCase() : '';
        var isVideo = title.indexOf('video') !== -1 || preview.indexOf('video') !== -1 || firstMsg.indexOf('video') !== -1;
        var isLeader = title.indexOf('leader') !== -1 || preview.indexOf('leader') !== -1 || firstMsg.indexOf('leader') !== -1 || preview.indexOf('enterprise ai') !== -1;
        var isSystem = thread && thread.kind === 'system';
        var isBug = title.indexOf('bug') !== -1 || title.indexOf('report a bug') !== -1;
        if (isVideo || isLeader || isSystem || isBug) {
          return; // skip — don't load into memory
        }
      }
      threadStore()[key] = persisted[key];
      markThreadTransportFailuresRetryable(threadStore()[key]);
    });
    var seededThreads = safeArray(chat.threads);
    seededThreads.forEach(function (thread, index) {
      var key = firstDefined(thread.thread_id, state.activePersona + ":" + firstDefined(thread.key, "thread-" + (index + 1)));
      if (!threadStore()[key]) {
        var initial = {
          role: "assistant",
          text: assistantName + " is ready in " + getPersonaLabel(state.activePersona) + " mode. Ask for the next board decision, the board-safe summary, or the evidence gap.",
          timestamp: new Date().toISOString()
        };
        if (thread.kind === "system") {
          initial.text = firstDefined(thread.preview, "Board status is attached here.");
        }
        threadStore()[key] = {
          key: key,
          title: firstDefined(thread.title, "Thread"),
          preview: firstDefined(thread.preview, blueprint.brief, "Board-safe follow-up"),
          route: firstDefined(thread.route, ""),
          readOnly: Boolean(thread.read_only),
          kind: firstDefined(thread.kind, "starter"),
          assistant: firstDefined(thread.assistant, assistantName),
          messages: [initial],
          lastUpdated: new Date().toISOString()
        };
      }
    });
    if (!state.activeThreadKey || !threadStore()[state.activeThreadKey]) {
      state.activeThreadKey = firstDefined(chat.active_thread_id, seededThreads[0] && seededThreads[0].thread_id, Object.keys(threadStore())[0]);
    }
    saveStoredThreads();
  }

  function ensureWritableThread(seedTitle, seedPreview, options) {
    ensureThreads();
    var current = threadStore()[currentThreadKey()];
    if (current && !current.readOnly) return current;
    return createWritableThread(seedTitle, seedPreview, options);
  }

  function createWritableThread(seedTitle, seedPreview, options) {
    var blueprint = getPersonaBlueprint(state.activePersona);
    var persona = getPersonaContract(state.activePersona);
    var assistantName = firstDefined((getChatContract().assistant || {}).name, persona.assistant, blueprint.assistant, "Hermes");
    var key = state.activePersona + ":followup-" + Date.now();
    var preview = String(firstDefined(seedPreview, "Writable board-safe thread.")).trim();
    var silentInitialMessage = Boolean(options && options.silentInitialMessage);
    var initialMessage = seedPreview && String(seedPreview).trim()
      ? "I'll look up \u201c" + String(seedPreview).slice(0, 48) + (String(seedPreview).length > 48 ? "\u2026" : "") + "\u201d against the current board pack."
      : "I can answer using the current board pack. What would you like to know?";
    threadStore()[key] = {
      key: key,
      title: seedTitle || ("New conversation · " + nowStamp()),
      preview: preview || "Writable board-safe thread.",
      route: state.activePersona === "ceo" ? "" : firstDefined(getPublication().preview_route, "/public/runs/latest/report-preview"),
      readOnly: false,
      kind: "followup",
      assistant: firstDefined((getChatContract().assistant || {}).name, assistantName),
      messages: silentInitialMessage ? [] : [
        {
          role: "assistant",
          text: initialMessage,
          timestamp: new Date().toISOString()
        }
      ],
      lastUpdated: new Date().toISOString()
    };
    state.activeThreadKey = key;
    saveStoredThreads();
    return threadStore()[key];
  }

  function pushThreadMessage(role, text) {
    var thread = role === "user" ? ensureWritableThread() : threadStore()[currentThreadKey()] || ensureWritableThread();
    if (!thread) return null;
    var message = { role: role, text: text, timestamp: new Date().toISOString(), status: role === "assistant" ? "pending" : "ok" };
    thread.messages.push(message);
    thread.lastUpdated = new Date().toISOString();
    recalcThreadPreview(thread);
    saveStoredThreads();
    return message;
  }

  async function retryAssistantMessage(threadKey, messageIndex, sourceEl, options) {
    var thread = threadStore()[threadKey];
    var message = thread && safeArray(thread.messages)[messageIndex];
    var retryPrompt = String(firstDefined(message && message.retryPrompt, inferRetryPrompt(thread && thread.messages, messageIndex), "")).trim();
    if (!thread || !message || !retryPrompt) return;
    if (sourceEl) sourceEl.disabled = true;
    message.text = "Retrying the shared assistant service…";
    message.status = "pending";
    message.needsRetry = false;
    thread.lastUpdated = new Date().toISOString();
    recalcThreadPreview(thread);
    saveStoredThreads();
    renderAssistantStudio();
    var result = await buildAssistantReply(retryPrompt, sourceEl);
    applyAssistantResultToMessage(thread, message, result);
    state.failedAssistantAutoRetried[threadKey + ":" + messageIndex] = true;
    saveStoredThreads();
    renderAssistantStudio();
    if (sourceEl) sourceEl.disabled = false;
    if (!(options && options.silentToast) && result.ok) {
      showToast("Hermes reply restored.");
    }
  }

  function maybeAutoRetryLatestFailure(thread) {
    if (!state.drawerOpen || !thread) return;
    var latestFailure = latestRetryableAssistantFailure(thread);
    if (!latestFailure || !latestFailure.message || !latestFailure.message.retryPrompt || latestFailure.message.autoRetryEligible !== true) return;
    var retryKey = thread.key + ":" + latestFailure.index;
    if (state.failedAssistantAutoRetried[retryKey]) return;
    state.failedAssistantAutoRetried[retryKey] = true;
    window.setTimeout(function () {
      retryAssistantMessage(thread.key, latestFailure.index, null, { silentToast: true });
    }, 0);
  }

  function friendlyThreadTime(value) {
    if (!value) return "now";
    var parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) return parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return value;
  }

  function showToast(message) {
    var existing = document.querySelector('.strategyos-toast');
    if (existing) existing.remove();
    var toast = document.createElement('div');
    toast.className = 'strategyos-toast';
    toast.textContent = message;
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    document.body.appendChild(toast);
    window.setTimeout(function () { toast.remove(); }, 3500);
  }

  function showAgentInstallRequest(item, sourceEl) {
    var existing = document.querySelector('.strategyos-agent-install-modal');
    if (existing) existing.remove();
    var label = discoverableAgentLabel(item);
    var lane = String(firstDefined(item && item.lane, 'operator')).toLowerCase();
    var route = discoverableAgentRoute(item);
    var session = state.session || {};
    var authenticated = !!session.authenticated;
    var role = String(firstDefined(session.display_role, session.role, 'Public CEO'));
    var primaryRoute = authenticated ? laneRouteForDiscoverableAgent(item) : '/login';
    var primaryLabel = authenticated ? 'Open authorized lane' : 'Sign in to add';
    var body = authenticated
      ? 'Your current ' + role + ' session cannot add this agent. Open the authorized workspace lane to continue.'
      : 'Public CEO sessions can inspect the catalogue, but adding agents requires an authenticated operator, reviewer, or system role.';
    var modal = document.createElement('div');
    modal.className = 'strategyos-agent-install-modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-label', 'Add ' + label);
    modal.innerHTML = [
      '<div class="strategyos-agent-install-backdrop"></div>',
      '<div class="strategyos-agent-install-card">',
      '<button class="strategyos-agent-install-close" type="button" aria-label="Close add agent request">&times;</button>',
      '<p class="strategyos-agent-install-kicker">Operator-gated install</p>',
      '<h3>Add ' + escapeHtml(label) + '</h3>',
      '<p class="section-note">' + escapeHtml(body) + '</p>',
      '<div class="strategyos-agent-install-list">',
      '<div class="strategyos-agent-install-item"><strong>Requested agent</strong><span>' + escapeHtml(label) + '</span></div>',
      '<div class="strategyos-agent-install-item"><strong>Required lane</strong><span>' + escapeHtml(humanizeToken(lane)) + '</span></div>',
      '<div class="strategyos-agent-install-item"><strong>Target route</strong><span>' + escapeHtml(route || 'Operator workspace') + '</span></div>',
      '</div>',
      '<div class="strategyos-agent-install-actions">',
      '<button class="strategyos-agent-install-btn strategyos-agent-install-btn--primary" type="button" data-agent-install-primary="true">' + escapeHtml(primaryLabel) + '</button>',
      '<button class="strategyos-agent-install-btn" type="button" data-agent-install-close="true">Close</button>',
      '</div>',
      '</div>'
    ].join('');
    document.body.appendChild(modal);
    var previousFocus = sourceEl && typeof sourceEl.focus === 'function' ? sourceEl : document.activeElement;
    var close = function () {
      document.removeEventListener('keydown', onKeydown);
      modal.remove();
      if (previousFocus && typeof previousFocus.focus === 'function') previousFocus.focus();
    };
    var onKeydown = function (event) {
      if (event.key === 'Escape') close();
    };
    var backdrop = modal.querySelector('.strategyos-agent-install-backdrop');
    var closeButtons = modal.querySelectorAll('[data-agent-install-close], .strategyos-agent-install-close');
    var primary = modal.querySelector('[data-agent-install-primary]');
    if (backdrop) backdrop.onclick = close;
    safeArray(closeButtons).forEach(function (button) { button.onclick = close; });
    if (primary) {
      primary.onclick = function () {
        window.location.assign(primaryRoute);
      };
      window.setTimeout(function () { primary.focus(); }, 0);
    }
    document.addEventListener('keydown', onKeydown);
  }

  function handleDiscoverableAgentAction(item, sourceEl) {
    if (!item) {
      showToast('Agent detail is not available yet.');
      return;
    }
    var moduleId = String(firstDefined(item.module_id, item.id, ""));
    if (item.permitted !== false && moduleId === "ceo-brief") {
      state.activePersona = "ceo";
      state.activeView = "assistants";
      state.activeThreadKey = "";
      updateHistory();
      renderPersonaView();
      openAssistantDrawer(sourceEl);
      showToast("CEO brief opened in Assistants.");
      return;
    }
    if (item.permitted !== false && moduleId === "board-room-memory") {
      var route = new URL(discoverableAgentRoute(item), window.location.origin);
      state.activePersona = "board";
      state.activeBoard = route.searchParams.get("board") || state.activeBoard || "pre";
      state.activeView = "home";
      updateHistory();
      renderPersonaView();
      showToast("Board room memory opened.");
      return;
    }
    if (item.permitted !== false) {
      if (navigateToRoute(discoverableAgentRoute(item), sourceEl)) return;
    }
    showAgentInstallRequest(item, sourceEl);
  }

  function showFeedbackForm() {
    var existing = document.querySelector('.strategyos-feedback-modal');
    if (existing) { existing.hidden = false; return; }
    var modal = document.createElement('div');
    modal.className = 'strategyos-feedback-modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-label', 'Send feedback');
    modal.innerHTML = [
      '<div class="strategyos-feedback-backdrop"></div>',
      '<div class="strategyos-feedback-card">',
      '<button class="strategyos-feedback-close" type="button" aria-label="Close feedback form">&times;</button>',
      '<h3>Send feedback</h3>',
      '<form id="strategyos-feedback-form">',
      '<label for="feedback-summary">Summary <span aria-hidden="true">*</span></label>',
      '<input id="feedback-summary" type="text" required placeholder="What happened?" autocomplete="off" />',
      '<label for="feedback-details">Details (optional)</label>',
      '<textarea id="feedback-details" rows="3" placeholder="Any extra context…"></textarea>',
      '<label for="feedback-severity">Severity</label>',
      '<select id="feedback-severity"><option value="">--</option><option value="blocking">Blocking</option><option value="major">Major</option><option value="minor">Minor</option><option value="cosmetic">Cosmetic</option></select>',
      '<button type="submit">Submit feedback</button>',
      '</form>',
      '</div>'
    ].join('');
    document.body.appendChild(modal);
    var backdrop = modal.querySelector('.strategyos-feedback-backdrop');
    var closeBtn = modal.querySelector('.strategyos-feedback-close');
    var form = modal.querySelector('#strategyos-feedback-form');
    var close = function () { modal.remove(); };
    backdrop.onclick = close;
    closeBtn.onclick = close;
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var summary = (form.querySelector('#feedback-summary') || {}).value || '';
      if (!summary.trim()) return;
      var details = (form.querySelector('#feedback-details') || {}).value || '';
      var severity = (form.querySelector('#feedback-severity') || {}).value || '';
      try {
        var stored = window.localStorage.getItem('strategyos.feedback') || '[]';
        var feedback = JSON.parse(stored);
        feedback.push({
          summary: summary,
          details: details,
          severity: severity,
          persona: state.activePersona,
          timestamp: new Date().toISOString()
        });
        window.localStorage.setItem('strategyos.feedback', JSON.stringify(feedback));
      } catch (_error) {}
      showToast('Feedback recorded \u2014 thank you.');
      close();
    });
    var summaryInput = form.querySelector('#feedback-summary');
    if (summaryInput) window.setTimeout(function () { summaryInput.focus(); }, 0);
  }

  function showProfileSettingsPanel() {
    var existing = document.querySelector('.strategyos-profile-modal');
    if (existing) { existing.hidden = false; return; }
    var activePersona = getPersonaContract(state.activePersona);
    var blueprint = getPersonaBlueprint(state.activePersona);
    var assistantName = firstDefined(activePersona.assistant, blueprint.assistant, 'Hermes');
    var modal = document.createElement('div');
    modal.className = 'strategyos-profile-modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-label', 'Profile and settings');
    modal.innerHTML = [
      '<div class="strategyos-profile-backdrop"></div>',
      '<div class="strategyos-profile-card">',
      '<button class="strategyos-profile-close" type="button" aria-label="Close profile and settings">&times;</button>',
      '<h3>Profile &amp; settings</h3>',
      '<p class="section-note">Adjust your working persona, theme, and board context without leaving the board lane.</p>',
      '<div class="strategyos-profile-list">',
      '<div class="strategyos-profile-item"><strong>Active role</strong><span>' + escapeHtml(firstDefined(activePersona.label, 'Group CEO')) + '</span></div>',
      '<div class="strategyos-profile-item"><strong>Assistant</strong><span>' + escapeHtml(assistantName) + ' · board data</span></div>',
      '<div class="strategyos-profile-item"><strong>Theme</strong><span>' + escapeHtml(state.theme === 'dark' ? 'Dark' : 'Light') + '</span></div>',
      '</div>',
      '<div class="strategyos-profile-actions">',
      '<button class="strategyos-profile-btn" type="button" data-profile-action="switch">Switch persona</button>',
      '<button class="strategyos-profile-btn" type="button" data-profile-action="theme">Toggle theme</button>',
      '</div>',
      '</div>'
    ].join('');
    document.body.appendChild(modal);
    var close = function () { modal.remove(); };
    var backdrop = modal.querySelector('.strategyos-profile-backdrop');
    var closeBtn = modal.querySelector('.strategyos-profile-close');
    var switchBtn = modal.querySelector('[data-profile-action="switch"]');
    var themeBtn = modal.querySelector('[data-profile-action="theme"]');
    if (backdrop) backdrop.onclick = close;
    if (closeBtn) closeBtn.onclick = close;
    if (switchBtn) {
      switchBtn.onclick = function () {
        close();
        var btn = document.getElementById('persona-btn');
        if (btn) btn.click();
      };
    }
    if (themeBtn) {
      themeBtn.onclick = function () {
        state.theme = state.theme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', state.theme);
        close();
        renderTopbar();
      };
    }
  }

  function renderTopbar() {
    var activePersona = getPersonaContract(state.activePersona);
    var blueprint = getPersonaBlueprint(state.activePersona);
    var org = $("brand-org");
    var personaLabel = $("persona-label");
    var list = $("pm-list");
    var btn = $("persona-btn");
    var viewNav = $("view-nav");
    var launcher = $("chat-launcher-cta");
    var topbarAssistantLauncher = $("topbar-assistant-launch");
    var launcherPrompt = document.querySelector("#chat-launcher .chat-launcher__prompt");
    var userName = $("topbar-user-name");
    var userRole = $("topbar-user-role");
    var avatar = $("topbar-avatar");
    var userMeta = document.querySelector("#topbar-user .tb-user-meta");
    var assistantName = firstDefined(activePersona.assistant, blueprint.assistant, "Hermes");
    var assistantGlyph = firstDefined(activePersona.assistant_glyph, blueprint.assistantGlyph, "◆");
    var initials = executiveIdentityInitials(state.activePersona);

    if (org) org.textContent = tenantDisplayName();
    // Logo click → reset to home view
    var brandEl = document.querySelector('.brand');
    if (brandEl) {
      brandEl.style.cursor = 'pointer';
      brandEl.setAttribute('role', 'link');
      brandEl.setAttribute('tabindex', '0');
      brandEl.title = 'StrategyOS home';
      brandEl.onclick = function () {
        state.activeView = 'home';
        state.activePersona = 'ceo';
        state.activeDriverKey = '';
        state.activeThreadKey = '';
        state.activeBoard = 'pre';
        refresh(true);
      };
    }
    if (personaLabel) personaLabel.textContent = firstDefined(activePersona.label, "Group CEO");
    if (launcher) {
      if (state.activePersona === "board") {
        launcher.textContent = "Ask " + assistantName;
      } else {
        launcher.innerHTML = '<span class="asst-avatar sm">' + escapeHtml(firstDefined(activePersona.assistant_glyph, blueprint.assistantGlyph, '◆')) + '</span> Ask ' + escapeHtml(assistantName);
      }
    }
    if (topbarAssistantLauncher) {
      topbarAssistantLauncher.innerHTML = '<span class="topbar-assistant-launch__mark" aria-hidden="true">' + escapeHtml(assistantGlyph) + '</span><span class="topbar-assistant-launch__label">Ask ' + escapeHtml(assistantName) + '</span>';
      topbarAssistantLauncher.setAttribute("aria-label", "Ask " + assistantName);
    }
    if (launcherPrompt) launcherPrompt.hidden = state.activePersona !== "board";
    if (userName) userName.textContent = "";
    if (userRole) userRole.textContent = "";
    if (avatar) {
      avatar.textContent = initials;
      avatar.title = firstDefined(activePersona.label, "Group CEO") + " \u00b7 " + assistantName;
      avatar.setAttribute('role', 'button');
      avatar.setAttribute('tabindex', '0');
      avatar.onclick = function () {
        var existing = document.querySelector('.strategyos-avatar-tooltip');
        if (existing) { existing.remove(); return; }
        var themeIcon = state.theme === "dark" ? "☾" : "☀";
        var themeLabel = state.theme === "dark" ? "Dark" : "Light";
        var feedbackAction = state.activePersona === "ceo" ? "" : '<button type="button" class="avatar-tooltip-action" data-avatar-action="feedback">Send feedback</button>';
        var tip = document.createElement('div');
        tip.className = 'strategyos-avatar-tooltip';
        tip.innerHTML = '<div class="avatar-tooltip-head"><span class="avatar avatar-lg">' + escapeHtml(initials) + '</span><div class="avatar-tooltip-copy"><strong>' + escapeHtml(firstDefined(activePersona.label, 'Group CEO')) + '</strong><span>' + escapeHtml(assistantName) + ' · board data</span></div></div><div class="avatar-tooltip-actions"><button type="button" class="avatar-tooltip-action" data-avatar-action="profile">Profile &amp; settings</button><button type="button" class="avatar-tooltip-action" data-avatar-action="switch">Switch persona</button><button type="button" class="avatar-tooltip-action" data-avatar-action="theme">' + escapeHtml(themeIcon) + ' ' + escapeHtml(themeLabel) + ' theme</button>' + feedbackAction + '<button type="button" class="avatar-tooltip-action avatar-tooltip-action--signout" data-avatar-action="signout">Sign out</button></div>';
        avatar.parentNode.appendChild(tip);
        var outsideClick = function (event) {
          if (!event.target.closest('#topbar-user')) { tip.remove(); document.removeEventListener('click', outsideClick); }
        };
        window.setTimeout(function () { document.addEventListener('click', outsideClick); }, 0);
        var profileAction = tip.querySelector('[data-avatar-action="profile"]');
        if (profileAction) {
          profileAction.onclick = function () {
            tip.remove();
            showProfileSettingsPanel();
          };
        }
        tip.querySelector('[data-avatar-action="switch"]').onclick = function () {
          var btn = document.getElementById('persona-btn');
          if (btn) { btn.click(); tip.remove(); }
        };
        var themeAction = tip.querySelector('[data-avatar-action="theme"]');
        if (themeAction) {
          themeAction.onclick = function () {
            state.theme = state.theme === "dark" ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", state.theme);
            tip.remove();
            renderTopbar();
          };
        }
        var feedbackActionEl = tip.querySelector('[data-avatar-action="feedback"]');
        if (feedbackActionEl) {
          feedbackActionEl.onclick = function () { tip.remove(); showFeedbackForm(); };
        }
        var signoutAction = tip.querySelector('[data-avatar-action="signout"]');
        if (signoutAction) {
          signoutAction.onclick = async function () {
            signoutAction.disabled = true;
            try {
              await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' });
            } finally {
              try { sessionStorage.clear(); } catch (_error) {}
              window.location.assign('/login');
            }
          };
        }
      };
    }
    if (userMeta) userMeta.hidden = true;
    if (viewNav) viewNav.hidden = state.activePersona === "board";
    if (!list || !btn) return;

    list.innerHTML = "";
    function polishPersonaLabel(rawLabel) {
      var m = {
        'ceo': 'Group CEO',
        'bucfo': 'Business Unit CFO',
        'bu cfo': 'Business Unit CFO',
        'BU CFO': 'Business Unit CFO',
        'bugm': 'Business Unit GM',
        'bu gm': 'Business Unit GM',
        'BU GM': 'Business Unit GM',
        'logistics': 'Logistics',
        'board': 'Board'
      };
      return m[String(rawLabel).trim()] || rawLabel;
    }
    safeArray(state.personas).forEach(function (persona) {
      var isActive = persona.persona_id === state.activePersona;
      var item = document.createElement("button");
      item.type = "button";
      item.className = "persona-item" + (isActive ? " is-active" : "");
      item.setAttribute("role", "menuitem");
      item.innerHTML = "<span>" + escapeHtml(polishPersonaLabel(firstDefined(persona.label, persona.persona_id, "Persona"))) + "</span>";
      item.onclick = function () {
        if (persona.persona_id === state.activePersona) return;
        state.activePersona = persona.persona_id;
        state.activeView = "home";
        state.activeDriverKey = "";
        state.activeThreadKey = "";
        list.hidden = true;
        btn.setAttribute("aria-expanded", "false");
        refresh(true);
      };
      list.appendChild(item);
    });

    btn.onclick = function () {
      var expanded = btn.getAttribute("aria-expanded") === "true";
      list.hidden = expanded;
      btn.setAttribute("aria-expanded", expanded ? "false" : "true");
    };

    if (!state.personaOutsideListenerBound) {
      document.addEventListener("click", function (event) {
        if (!event.target.closest("#persona-menu")) {
          list.hidden = true;
          btn.setAttribute("aria-expanded", "false");
        }
      });
      state.personaOutsideListenerBound = true;
    }
  }

  function renderViewNav() {
    var nav = $("view-nav");
    if (nav) {
      nav.hidden = state.activePersona === "board";
      nav.style.display = state.activePersona === "board" ? "none" : "";
    }
    safeArray(document.querySelectorAll("[data-view-target]")).forEach(function (link) {
      var target = link.getAttribute("data-view-target") || "home";
      if (target === "home") link.textContent = state.activePersona === "board" ? "Portal" : "Diagnostics";
      link.classList.toggle("is-active", target === state.activeView);
      link.setAttribute("aria-selected", target === state.activeView ? "true" : "false");
    });
  }

  function renderViewPanels() {
    safeArray(document.querySelectorAll("[data-view-panel]")).forEach(function (panel) {
      var isActive = panel.getAttribute("data-view-panel") === state.activeView;
      panel.hidden = !isActive;
      panel.classList.toggle("is-active", isActive);
      panel.setAttribute("aria-hidden", isActive ? "false" : "true");
    });
  }

  function renderHomeComposition() {
    var blueprint = getPersonaBlueprint(state.activePersona);
    var driverHeading = $("driver-heading");
    var driverHint = $("driver-hint");
    var lowerHeading = $("lower-rail-heading");
    var drivers = getVisibleDrivers();
    var hasPercentDrivers = drivers.some(function (driver) { return driverHasPercent(driver); });
    if (state.activePersona === "ceo") {
      if (driverHeading) driverHeading.textContent = "The group index";
      if (driverHint) driverHint.textContent = "Four CEO indicators. Select a KPI to see its contributors, decision implication, and supporting sources.";
    } else {
      if (driverHeading) driverHeading.textContent = firstDefined(blueprint.indexLabel, "The group index");
      if (driverHint) driverHint.textContent = hasPercentDrivers ? "All figures: % of plan" : "All figures: current measures";
    }
    if (lowerHeading) lowerHeading.textContent = "What matters now";
    var boardOnly = state.activePersona === "board";
    ["hero", "kpi-index-section", "kpi-detail-section", "priority-section", "decision-questions-section"].forEach(function (id) {
      var element = $(id);
      if (element) element.hidden = boardOnly;
    });
    var boardWorkspace = $("board-workspace");
    if (boardWorkspace) boardWorkspace.hidden = !boardOnly;
    var gravityHeading = $("gravity-heading");
    if (gravityHeading) gravityHeading.textContent = "Decision questions";
    var footer = $("composed-footer");
    if (footer) footer.hidden = false;
  }

  function renderAssistantNetwork() {
    var card = $("assistant-network-card");
    var meta = getAssistantNetworkMeta();
    // Order by real status (running first); ranks are presentational only.
    var network = getAssistantNetwork().slice().sort(function (left, right) {
      return Number(left.statusRank || 0) - Number(right.statusRank || 0);
    });
    if (card) {
      // Every number on this card is a count of real module states -- no
      // synthetic "readiness score" or invented target exists in the data.
      var runningCount = network.filter(function (item) { return Number(item.statusRank) === 0; }).length;
      var pendingCount = network.filter(function (item) { return Number(item.statusRank) === 1; }).length;
      var blockedCount = network.filter(function (item) { return Number(item.statusRank) >= 2; }).length;
      var activeFilter = state.networkStatusFilter || "all";
      var filterLabels = { all: "All AI leaders", running: "Working", pending: "Waiting", blocked: "Needs review" };
      function networkStatusKey(item) {
        return Number(item.statusRank) === 0 ? "running" : Number(item.statusRank) === 1 ? "pending" : "blocked";
      }
      var filteredNetwork = activeFilter === "all"
        ? network
        : network.filter(function (item) { return networkStatusKey(item) === activeFilter; });
      var catalogueAgents = getDiscoverableAgents();
      var catalogueHtml = state.assistantCatalogueOpen
        ? '<div class="assistant-catalogue" id="assistant-catalogue"><div class="agents-col-head"><span class="ach-title">Available AI support</span><span class="ach-hint">' + escapeHtml(String(catalogueAgents.length)) + ' available</span></div><div class="disco-list">' + catalogueAgents.map(function (item, index) {
            return '<div class="disco-card"><span class="disco-glyph">' + escapeHtml(firstDefined(item.glyph, '\u25c7')) + '</span><div class="disco-meta"><div class="disco-name-line"><span class="disco-name">' + escapeHtml(firstDefined(item.name, item.label, item.module_id, 'Agent ' + (index + 1))) + '</span><span class="disco-src native">' + escapeHtml(firstDefined(item.connector, item.source, 'StrategyOS')) + '</span></div><div class="disco-desc">' + escapeHtml(firstDefined(item.desc, item.summary, 'Discoverable agent surface.')) + '</div></div></div>';
          }).join('') + '</div></div>'
        : '';
      card.innerHTML = [
        '<div class="detail-head"><div><p class="detail-eyebrow">AI leadership team</p><h3 class="detail-title">' + escapeHtml(firstDefined(meta.label, 'Your AI leadership team')) + '</h3><p class="section-note">' + escapeHtml(firstDefined(meta.hint, 'AI leaders supporting the current board review.')) + '</p></div><div class="network-filter-wrap"><button type="button" class="pill-inline ok network-module-toggle" id="network-module-toggle" aria-haspopup="menu" aria-expanded="' + (state.networkFilterMenuOpen ? 'true' : 'false') + '">' + escapeHtml(filterLabels[activeFilter] || 'All AI leaders') + ' · ' + escapeHtml(String(filteredNetwork.length)) + '</button>' + (state.networkFilterMenuOpen ? '<div class="network-filter-menu" role="menu" aria-label="Filter AI leaders"><button type="button" role="menuitemradio" aria-checked="' + (activeFilter === 'all' ? 'true' : 'false') + '" data-network-menu-filter="all">All AI leaders</button><button type="button" role="menuitemradio" aria-checked="' + (activeFilter === 'running' ? 'true' : 'false') + '" data-network-menu-filter="running">Working</button><button type="button" role="menuitemradio" aria-checked="' + (activeFilter === 'pending' ? 'true' : 'false') + '" data-network-menu-filter="pending">Waiting</button><button type="button" role="menuitemradio" aria-checked="' + (activeFilter === 'blocked' ? 'true' : 'false') + '" data-network-menu-filter="blocked">Needs review</button></div>' : '') + '</div></div>',
        '<div class="network-summary"><div class="network-score"><strong>' + escapeHtml(String(network.length ? runningCount : '—')) + '</strong><span>Working now</span></div><div class="network-meta"><span class="pill-inline ok" data-network-filter="running">' + escapeHtml(String(runningCount)) + ' working</span><span class="pill-inline warn" data-network-filter="pending">' + escapeHtml(String(pendingCount)) + ' waiting</span><span class="pill-inline danger" data-network-filter="blocked">' + escapeHtml(String(blockedCount)) + ' need review</span></div></div>',
        '<div class="network-list" id="network-module-list" data-active-filter="' + escapeHtml(activeFilter) + '"><div class="network-list-head"><span class="sr-only">Status</span><span class="sr-only">Assistant</span><div class="network-list-head__stats"><span class="network-list-head__stat">State</span><span class="network-list-head__stat">Business output</span><span class="network-list-head__stat">Decision / scope</span></div></div>' + filteredNetwork.map(function (item, index) {
          return '<div class="network-row" data-network-idx="' + index + '" data-network-status="' + escapeHtml(networkStatusKey(item)) + '" role="button" tabindex="0" title="Ask ' + escapeHtml(firstDefined(item.assistant, 'this assistant')) + ' about its current work"><div class="network-score-badge tone-' + toneClass(item.tone) + '" role="img" aria-label="' + escapeHtml(statusLabel(item.tone)) + '"><strong>●</strong></div><div class="network-row__main"><div class="network-row__head"><strong>' + escapeHtml(firstDefined(item.assistant, 'Assistant')) + '</strong><span>· ' + escapeHtml(firstDefined(item.who, 'Leader')) + '</span></div><p class="list-copy">' + escapeHtml(firstDefined(item.unit, tenantDisplayName())) + '</p></div><div class="network-stats"><span aria-label="State"><span class="network-stat-value">' + escapeHtml(firstDefined(item.stateLabel, 'Current')) + '</span></span><span aria-label="Business output"><span class="network-stat-value">' + escapeHtml(firstDefined(item.businessOutput, 'No output reported')) + '</span></span><span aria-label="Decision or scope"><span class="network-stat-value">' + escapeHtml(firstDefined(item.decisionScope, 'No action needed')) + '</span></span></div></div>';
        }).join('') + (!network.length ? '<div class="network-row"><div class="network-score-badge tone-warn"><strong>—</strong></div><div class="network-row__main"><div class="network-row__head"><strong>No current team activity</strong><span>· Ready for review</span></div><p class="list-copy">Your AI leaders have no new work to present for this board review.</p></div><div class="network-stats"><span><span class="network-stat-value">Ready</span></span><span><span class="network-stat-value">No update</span></span><span><span class="network-stat-value">No action needed</span></span></div></div>' : '') + (network.length && !filteredNetwork.length ? '<div class="network-empty">No AI leaders match this filter.</div>' : '') + '</div>' + catalogueHtml
      ].join('');
      // Bug 3 fix: bind click handlers to network rows so they open the
      // Hermes drawer with a contextual prompt about the clicked module.
      safeArray(card.querySelectorAll('.network-row[data-network-idx]')).forEach(function (row) {
        var handler = function () {
          var idx = Number(row.getAttribute('data-network-idx') || 0);
          var moduleItem = filteredNetwork[idx];
          if (!moduleItem) return;
          var moduleName = firstDefined(moduleItem.assistant, 'this assistant');
          var moduleWho = firstDefined(moduleItem.who, '');
          var prompt = 'Tell me about the "' + moduleName + '" module' + (moduleWho ? ' (in the ' + moduleWho + ' lane)' : '') + ': what is it doing right now, is it blocked, and what does it need from me?';
          askAssistant(prompt, row, {
            module_id: moduleItem.moduleId,
            entity_type: "governed_module",
            entrypoint: "assistant_network"
          });
        };
        row.onclick = handler;
        row.onkeydown = function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handler(); } };
      });
      var toggleBtn = $("network-module-toggle");
      if (toggleBtn) {
        toggleBtn.onclick = function (event) {
          event.stopPropagation();
          state.networkFilterMenuOpen = !state.networkFilterMenuOpen;
          renderAssistantNetwork();
        };
        toggleBtn.onkeydown = function (event) {
          if (event.key === "Escape") {
            state.networkFilterMenuOpen = false;
            renderAssistantNetwork();
          }
        };
      }
      safeArray(card.querySelectorAll('[data-network-menu-filter]')).forEach(function (button) {
        button.onclick = function (event) {
          event.stopPropagation();
          state.networkStatusFilter = button.getAttribute('data-network-menu-filter') || 'all';
          state.networkFilterMenuOpen = false;
          renderAssistantNetwork();
        };
      });
      safeArray(card.querySelectorAll('[data-network-filter]')).forEach(function (pill) {
        pill.style.cursor = 'pointer';
        pill.onclick = function () {
          var filterKey = pill.getAttribute('data-network-filter') || '';
          state.networkStatusFilter = state.networkStatusFilter === filterKey ? "all" : filterKey;
          state.networkFilterMenuOpen = false;
          renderAssistantNetwork();
        };
      });
    }
  }

  function renderA2APanel() {
    var fab = $("a2a-fab");
    var fabText = $("a2a-fab-text");
    var fabBadge = $("a2a-fab-badge");
    var panel = $("a2a-panel");
    var title = $("a2a-panel-title");
    var subtitle = $("a2a-panel-subtitle");
    var tabs = $("a2a-tabs");
    var topic = $("a2a-topic");
    var scroll = $("a2a-scroll");
    var footNote = $("a2a-foot-note");
    var followup = $("a2a-followup");
    var min = $("a2a-min");
    var exchanges = getAssistantExchanges();
    var assistantName = assistantNameForState();
    var active = exchanges.find(function (item) { return item.id === state.activeA2AExchange; }) || exchanges[0] || null;
    var liveCount = exchanges.filter(function (item) { return String(firstDefined(item.status, "active")).toLowerCase() !== "done"; }).length;

    if (fabText) fabText.textContent = assistantName + " network · " + liveCount + " active";
    if (title) title.textContent = assistantName + " ↔ assistant network";
    if (subtitle) subtitle.textContent = "Your chief of staff, gathering for you · live";
    if (fabBadge) {
      // This is the active-module count, not a failed-request queue. The
      // visible launcher label above carries the count in plain language.
      fabBadge.hidden = true;
      fabBadge.textContent = String(liveCount || 0);
      fabBadge.title = String(liveCount) + " active assistant module" + (liveCount === 1 ? "" : "s");
      fabBadge.setAttribute("aria-label", fabBadge.title);
    }
    if (fab) {
      fab.setAttribute("aria-expanded", state.a2aOpen ? "true" : "false");
      fab.setAttribute("aria-label", assistantName + " assistant network: " + liveCount + " active module" + (liveCount === 1 ? "" : "s"));
      fab.title = assistantName + " assistant network: " + liveCount + " active module" + (liveCount === 1 ? "" : "s");
      fab.onclick = function () {
        state.a2aOpen = !state.a2aOpen;
        renderA2APanel();
      };
    }
    if (min) {
      min.onclick = function () {
        state.a2aOpen = false;
        renderA2APanel();
      };
    }
    if (panel) panel.hidden = !state.a2aOpen;
    if (!tabs || !topic || !scroll || !active) return;

    tabs.innerHTML = exchanges.map(function (exchange) {
      var status = String(firstDefined(exchange.status, "active"));
      return '<button type="button" class="a2a-tab' + (exchange.id === active.id ? ' is-active' : '') + '" data-a2a-id="' + escapeHtml(exchange.id) + '"><span class="a2a-dot ' + escapeHtml(status.toLowerCase()) + '"></span>' + escapeHtml(firstDefined(exchange.with, 'Assistant')) + '<span class="a2a-tab-unit"> · ' + escapeHtml(firstDefined(exchange.unit, 'governed lane')) + '</span></button>';
    }).join('');
    safeArray(tabs.querySelectorAll("[data-a2a-id]")).forEach(function (button) {
      button.onclick = function () {
        state.activeA2AExchange = button.getAttribute("data-a2a-id") || "";
        renderA2APanel();
      };
    });

    topic.innerHTML = '<span class="a2a-topic-label">re:</span> ' + escapeHtml(firstDefined(active.topic, 'coordination')) + ' <span class="a2a-status ' + escapeHtml(String(firstDefined(active.status, 'active')).toLowerCase()) + '">' + escapeHtml(firstDefined(active.status, 'active')) + '</span>';
    var exchangeMessages = safeArray(active.messages).filter(function (message) {
      return String(firstDefined(message && message.text, '')).trim().length > 0;
    });
    scroll.innerHTML = exchangeMessages.length ? exchangeMessages.map(function (message) {
      var mine = firstDefined(message.from, '') === assistantName;
      return '<div class="a2a-msg' + (mine ? ' mine' : '') + '"><span class="a2a-from">' + escapeHtml(firstDefined(message.from, 'Assistant')) + '</span><div class="a2a-bubble">' + escapeHtml(firstDefined(message.text, '')) + '</div></div>';
    }).join('') : '<div class="a2a-msg"><span class="a2a-from">StrategyOS</span><div class="a2a-bubble">No assistant exchange is visible yet. Ask for a follow-up and the routed replies will appear here.</div></div>';
    scroll.scrollTop = scroll.scrollHeight;
    if (footNote) footNote.textContent = '⇄ ' + assistantName + ' is following up automatically';
    if (followup) {
      followup.onclick = function () {
        askAssistant('Set a follow-up task for ' + firstDefined(active.with, 'the assistant') + ' on ' + firstDefined(active.topic, 'the active coordination thread') + '.');
      };
    }
    var reportBug = $("a2a-report-bug");
    if (reportBug) {
      if (state.activePersona === "ceo") {
        reportBug.remove();
      } else {
        reportBug.hidden = false;
        reportBug.onclick = function () { showFeedbackForm(); };
      }
    }
  }

  /* ── Category color map ── */
  /* Legacy palette anchors kept for safety checks: #25335c #1a6e54 #8c6a3d */
  var KG_CATEGORY_COLORS = {
    plan: "#6f8cff", KPI: "#31d49b", business_unit: "#ffd166", finding: "#ff6b81",
    document: "#ba9cff", vendor: "#42c7ff", invoice: "#ff9f43", contract: "#7ee081",
    evidence: "#6ee7ff", source: "#f7d96c", relationship: "#b7c0d4", signal: "#92a0b8",
    business_driver: "#7ee081", comparator: "#ffd166", evidence_gap: "#ff9f43"
  };
  var KG_CATEGORY_LABELS = {
    plan: "Board Plan", KPI: "KPI", business_unit: "Business Unit", finding: "Finding",
    document: "Document", vendor: "Vendor", invoice: "Invoice", contract: "Contract",
    evidence: "Evidence", source: "Source", relationship: "Relationship", signal: "Signal",
    business_driver: "Business Driver", comparator: "Comparator", evidence_gap: "Missing Input"
  };
  var REPORT_CATEGORY_MAP = {
    board_pack: "Board pack", graph: "Data relationships", audit: "Review trail",
    other: "Supporting material", finance: "Financial summary", narrative: "Board narrative",
    evidence: "Evidence pack", kpi: "KPI detail"
  };

  function getCategoryColor(node) {
    var cat = (node && node.category) || "";
    return KG_CATEGORY_COLORS[cat] || "var(--accent)";
  }

  function isNodeFocused(node, focused) {
    if (!focused || !node) return true;
    return focused.has(node.id) || (node.focus_anchor && focused.has(node.focus_anchor)) || (node.parent_id && focused.has(node.parent_id));
  }

  function shouldShowKgLabel(node, focused, selectedId) {
    if (!node) return false;
    if (selectedId && (node.id === selectedId || node.parent_id === selectedId)) return true;
    if (node.synthetic) return false;
    if (node.kind === "primary" && (node.label_priority || isNodeFocused(node, focused))) return true;
    return Number(node.importance || 0) >= 88;
  }

  function kgCanvasTransform() {
    return 'translate(' + Number(state.kgPanX || 0) + 'px, ' + Number(state.kgPanY || 0) + 'px) scale(' + Number(state.kgZoom || 1).toFixed(2) + ')';
  }

  function getDensityNodeLimit(graph) {
    if ((state.kgDensityMode || "compact") === "dense") return safeArray(graph.nodes).length;
    var real = Number(graph.raw_node_count || 0);
    return Math.max(real + 24, Math.round(safeArray(graph.nodes).length * 0.52));
  }

  function openNodeInspector(node) {
    var panel = $("kg-inspector");
    if (!panel || !node) return;
    state._kgSelectedNodeId = node.id;
    var graph = getKnowledgeGraph();
    var nodes = safeArray(graph.nodes);
    var nodeMap = {};
    nodes.forEach(function (n) { nodeMap[n.id] = n; });
    var edges = safeArray(graph.edges);
    var connectedIds = [];
    edges.forEach(function (e) {
      if (e[0] === node.id && connectedIds.indexOf(e[1]) === -1) connectedIds.push(e[1]);
      if (e[1] === node.id && connectedIds.indexOf(e[0]) === -1) connectedIds.push(e[0]);
    });
    var connectedLabels = connectedIds.map(function (cid) {
      var cn = nodeMap[cid];
      return cn ? escapeHtml(cn.label) : "";
    }).filter(Boolean).slice(0, 10);
    var nodeProperties = node.properties && typeof node.properties === "object" ? node.properties : {};
    var nodeKpiKey = String(firstDefined(
      nodeProperties.kpi_key,
      node.category === "KPI" && String(node.id || "").indexOf("kpi:") === 0 ? String(node.id).slice(4) : "",
      ""
    )).trim();
    var relevanceByCategory = {
      KPI: "This is one of the four headline measures in the CEO dashboard.",
      business_driver: "This shows what contributes to the selected headline figure.",
      comparator: "This is the approved reference used to assess performance when period and scope are aligned.",
      evidence_gap: "This identifies what is still needed before the comparison is decision-ready.",
      source: "This is a business source supporting the selected figure."
    };
    panel.innerHTML =
      '<button type="button" class="kg-inspector__close" aria-label="Close inspector" id="kg-inspector-close">&times;</button>' +
      '<span class="kg-inspector__badge" style="background:' + escapeHtml(getCategoryColor(node)) + ';color:#08111f">' + escapeHtml(firstDefined(KG_CATEGORY_LABELS[node.category], node.category || "Node")) + '</span>' +
      '<h3 class="kg-inspector__title" id="kg-inspector-title">' + escapeHtml(firstDefined(node.label, "Node")) + '</h3>' +
      '<p class="kg-inspector__meta">' + escapeHtml(firstDefined(KG_CATEGORY_LABELS[node.category], node.category || "Item")) + ' &middot; ' + connectedIds.length + ' related item' + (connectedIds.length === 1 ? '' : 's') + '</p>' +
      '<p class="kg-inspector__detail">' + escapeHtml(firstDefined(node.detail, "No additional detail available.")) + '</p>' +
      '<div class="kg-inspector__provenance"><span class="kg-inspector__provenance-label">Why it matters</span><span class="kg-inspector__provenance-value">' + escapeHtml(firstDefined(relevanceByCategory[node.category], "This provides context for the selected headline figure.")) + '</span></div>' +
      (connectedLabels.length ? '<div class="kg-inspector__connections"><span class="kg-inspector__connections-label">Related figures and drivers</span>' + connectedLabels.map(function (l) { return '<span class="kg-inspector__conn-chip">' + l + '</span>'; }).join('') + '</div>' : '') +
      '<button type="button" class="kg-inspector__ask" id="kg-inspector-ask"' + (nodeKpiKey ? ' data-kpi-key="' + escapeHtml(nodeKpiKey) + '" data-kpi-label="' + escapeHtml(firstDefined(node.label, "KPI")) + '"' : '') + '>Ask Hermes about this &rarr;</button>';
    panel.hidden = false;
    panel.setAttribute("aria-hidden", "false");
    // Wire close button
    var closeBtn = $("kg-inspector-close");
    if (closeBtn) closeBtn.onclick = closeNodeInspector;
    // Wire Ask Hermes
    var askBtn = $("kg-inspector-ask");
    if (askBtn) askBtn.onclick = function () {
      var prompt = firstDefined(node.hermes_prompt, "Tell me about " + firstDefined(node.label, "this node") + ".");
      askAssistant(prompt, askBtn);
      closeNodeInspector();
    };
    // Highlight selected node in SVG
    var stage = card.querySelector(".kg-stage");
    if (stage) {
      safeArray(stage.querySelectorAll(".kg-node")).forEach(function (g) {
        g.classList.remove("is-selected");
      });
      var selG = stage.querySelector('.kg-node[data-kg-id="' + escapeHtml(node.id) + '"]');
      if (selG) selG.classList.add("is-selected");
    }
  }

  function closeNodeInspector() {
    var panel = $("kg-inspector");
    if (!panel) return;
    panel.hidden = true;
    panel.setAttribute("aria-hidden", "true");
    state._kgSelectedNodeId = null;
    // Remove all selected highlights
    var stage = card.querySelector(".kg-stage");
    if (stage) {
      safeArray(stage.querySelectorAll(".kg-node.is-selected")).forEach(function (g) {
        g.classList.remove("is-selected");
      });
    }
  }

  function highlightConnected(nodeId) {
    var graph = getKnowledgeGraph();
    var edges = safeArray(graph.edges);
    var connected = new Set();
    connected.add(nodeId);
    edges.forEach(function (e) {
      if (e[0] === nodeId) connected.add(e[1]);
      if (e[1] === nodeId) connected.add(e[0]);
    });
    var stage = card.querySelector(".kg-stage");
    if (!stage) return;
    // Nodes: dim unconnected
    safeArray(stage.querySelectorAll(".kg-node")).forEach(function (g) {
      var nid = g.getAttribute("data-kg-id") || "";
      g.classList.toggle("kg-dimmed", !connected.has(nid));
    });
    // Labels: dim unconnected
    safeArray(stage.querySelectorAll(".kg-label")).forEach(function (l) {
      var lid = l.getAttribute("data-kg-label-id") || "";
      l.classList.toggle("kg-dimmed", !connected.has(lid));
    });
    // Edges: highlight connected
    safeArray(stage.querySelectorAll(".kg-edge")).forEach(function (edge) {
      var eFrom = edge.getAttribute("data-kg-from") || "";
      var eTo = edge.getAttribute("data-kg-to") || "";
      edge.classList.toggle("kg-dimmed", !(connected.has(eFrom) && connected.has(eTo)));
    });
  }

  function clearHighlights() {
    var stage = card.querySelector(".kg-stage");
    if (!stage) return;
    safeArray(stage.querySelectorAll(".kg-node.kg-dimmed, .kg-label.kg-dimmed, .kg-edge.kg-dimmed")).forEach(function (el) {
      el.classList.remove("kg-dimmed");
    });
  }

  /* ── Main render ── */
  var card = $("knowledge-graph-card");
  function resolveKgLabelPositions(input) {
    var placed = [];
    return safeArray(input).slice().sort(function (a, b) {
      return Number(a.y || 0) - Number(b.y || 0) || Number(a.x || 0) - Number(b.x || 0);
    }).map(function (node, index) {
      var label = String(firstDefined(node.short_label, node.label, 'Node'));
      var halfWidth = Math.min(13, 2.5 + label.length * 0.34);
      var halfHeight = 2.8;
      var baseX = Math.max(halfWidth + 1, Math.min(99 - halfWidth, Number(node.x || 50)));
      var baseY = Math.max(4, Math.min(96, Number(node.y || 50)));
      var candidates = [0, -6, 6, -12, 12, -18, 18];
      var selected = { x: baseX, y: baseY };
      for (var cursor = 0; cursor < candidates.length; cursor += 1) {
        var candidate = {
          x: Math.max(halfWidth + 1, Math.min(99 - halfWidth, baseX + (cursor > 2 ? (index % 2 ? 5 : -5) : 0))),
          y: Math.max(4, Math.min(96, baseY + candidates[cursor]))
        };
        var overlaps = placed.some(function (box) {
          return Math.abs(candidate.x - box.x) < halfWidth + box.halfWidth + 1
            && Math.abs(candidate.y - box.y) < halfHeight + box.halfHeight + 1;
        });
        if (!overlaps) { selected = candidate; break; }
      }
      placed.push({ x: selected.x, y: selected.y, halfWidth: halfWidth, halfHeight: halfHeight });
      return Object.assign({}, node, { label_x: selected.x, label_y: selected.y });
    });
  }
  function renderKnowledgeGraph() {
    var graph = getKnowledgeGraph();
    if (!card) return;
    if (!state.kgDensityMode) state.kgDensityMode = 'compact';
    if (!Number.isFinite(Number(state.kgZoom))) state.kgZoom = 1;
    if (!Number.isFinite(Number(state.kgPanX))) state.kgPanX = 0;
    if (!Number.isFinite(Number(state.kgPanY))) state.kgPanY = 0;
    var focusQuestion = graph.questions[state.knowledgeQuestionIndex || 0] || null;
    var focused = focusQuestion ? new Set(safeArray(focusQuestion.focus)) : null;
    var densityMode = state.kgDensityMode || "compact";
    var rankedNodes = safeArray(graph.nodes).slice().sort(function (left, right) {
      if (!!left.synthetic !== !!right.synthetic) return left.synthetic ? 1 : -1;
      return Number(right.importance || 0) - Number(left.importance || 0);
    });
    var visibleNodes = rankedNodes.filter(function (node) {
      if (densityMode === 'dense' || !focused) return true;
      return isNodeFocused(node, focused);
    });
    var visibleNodeIds = new Set(visibleNodes.map(function (node) { return node.id; }));
    var nodes = visibleNodes;
    var nodeMap = {};
    nodes.forEach(function (node) { nodeMap[node.id] = node; });
    var edges = safeArray(graph.edges).filter(function (edge) {
      return visibleNodeIds.has(edge[0]) && visibleNodeIds.has(edge[1]);
    });

    var isSelected = state._kgSelectedNodeId || null;
    var labels = resolveKgLabelPositions(nodes.filter(function (node) {
      return shouldShowKgLabel(node, focused, isSelected);
    }));
    var activeLens = firstDefined(focusQuestion && focusQuestion.label, densityMode === "dense" ? "All KPI evidence" : "Selected KPI evidence");
    var presentCategories = Array.from(new Set(nodes.map(function (node) { return node.category; }).filter(Boolean)));

    card.innerHTML =
      '<div class="detail-head detail-head--kg"><div><p class="detail-eyebrow">CEO performance map</p><h3 class="detail-title">What drives the four headline figures</h3><p class="section-note">Choose a headline figure to see what makes it up, the approved reference, and what is still needed for a reliable comparison.</p></div><span class="pill-inline ok">Current reporting period</span></div>'
      + '<div class="kg-questions" role="tablist" aria-label="Question lenses">' + safeArray(graph.questions).map(function (question, index) {
        var active = focusQuestion && focusQuestion.id === question.id;
        var focusCount = safeArray(question.focus).length;
        return '<button type="button" class="kg-question' + (active ? ' is-active' : '') + '" role="tab" aria-selected="' + (active ? 'true' : 'false') + '" data-kg-question="' + index + '"><span class="kg-question__dot" aria-hidden="true"></span>' + escapeHtml(firstDefined(question.label, 'Question')) + '<span class="kg-question__count">' + focusCount + '</span></button>';
      }).join('') + '</div>'
      + '<div class="kg-stage-shell' + (state.kgFocusMode ? ' is-focus-mode' : '') + '">'
      + '<div class="kg-stage__hud" aria-hidden="false"><div class="kg-hud-chip"><strong>' + nodes.length + '</strong><span>figures and drivers</span></div><div class="kg-hud-chip"><strong>' + activeLens + '</strong><span>current focus</span></div></div>'
      + '<div class="kg-controls" role="toolbar" aria-label="Performance map controls">'
      + '<button type="button" class="kg-control-btn' + (densityMode === 'dense' ? ' is-active' : '') + '" id="kg-density-toggle" aria-pressed="' + (densityMode === 'dense' ? 'true' : 'false') + '">' + (densityMode === 'dense' ? 'All KPIs' : 'Selected KPI') + '</button>'
      + '<button type="button" class="kg-control-btn" id="kg-zoom-out" aria-label="Zoom out">−</button>'
      + '<button type="button" class="kg-control-btn" id="kg-zoom-in" aria-label="Zoom in">+</button>'
      + '<button type="button" class="kg-control-btn" id="kg-fit" aria-label="Fit graph">Fit</button>'
      + '<button type="button" class="kg-control-btn" id="kg-reset" aria-label="Reset graph view">Reset</button>'
      + '<button type="button" class="kg-control-btn' + (state.kgFocusMode ? ' is-active' : '') + '" id="kg-focus-mode" aria-pressed="' + (state.kgFocusMode ? 'true' : 'false') + '">' + (state.kgFocusMode ? 'Exit focus' : 'Focus mode') + '</button>'
      + '</div>'
      + '<div class="kg-stage" tabindex="0" role="application" aria-label="Interactive CEO performance map. Use mouse or touch to move, wheel to zoom, and Enter to open details.">'
      + '<div class="kg-canvas" style="transform:' + escapeHtml(kgCanvasTransform()) + '">'
      + '<svg viewBox="0 0 100 100" class="kg-svg" aria-hidden="true">'
      + '<defs><radialGradient id="kg-core-glow" cx="50%" cy="46%" r="52%"><stop offset="0%" stop-color="rgba(111,140,255,0.20)"></stop><stop offset="100%" stop-color="rgba(8,13,24,0)"></stop></radialGradient></defs>'
      + '<circle cx="50" cy="48" r="28" fill="url(#kg-core-glow)" class="kg-core-glow"></circle>'
      /* Edges */
      + edges.map(function (edge) {
        var from = nodeMap[edge[0]];
        var to = nodeMap[edge[1]];
        if (!from || !to) return '';
        var mx = ((Number(from.x || 0) + Number(to.x || 0)) / 2).toFixed(1);
        var curveLift = from.synthetic || to.synthetic ? 1.4 : 4.2;
        var my = (((Number(from.y || 0) + Number(to.y || 0)) / 2) - curveLift).toFixed(1);
        var active = isNodeFocused(from, focused) && isNodeFocused(to, focused);
        var edgeType = String(edge[2] || '').toLowerCase();
        return '<path class="kg-edge kg-edge--' + escapeHtml(edgeType || 'primary') + (active ? ' on' : '') + '" data-kg-from="' + escapeHtml(edge[0]) + '" data-kg-to="' + escapeHtml(edge[1]) + '" d="M' + escapeHtml(String(from.x)) + ',' + escapeHtml(String(from.y)) + ' Q' + escapeHtml(mx) + ',' + escapeHtml(my) + ' ' + escapeHtml(String(to.x)) + ',' + escapeHtml(String(to.y)) + '"></path>';
      }).join('')
      /* Nodes */
      + nodes.map(function (node) {
        var active = isNodeFocused(node, focused);
        var sizeClass = "";
        var nr = Number(node.r || 8);
        if (nr >= 12) sizeClass = " kg-node--major";
        else if (nr <= 7) sizeClass = " kg-node--minor";
        if (node.synthetic) sizeClass += ' kg-node--synthetic';
        var selClass = (isSelected === node.id) ? " is-selected" : "";
        return '<g class="kg-node' + (active ? ' on' : ' off') + sizeClass + selClass + '" data-kg-id="' + escapeHtml(node.id) + '" tabindex="0" role="button" aria-label="' + escapeHtml(firstDefined(node.label, 'Node')) + ' — ' + escapeHtml(firstDefined(KG_CATEGORY_LABELS[node.category], node.category || 'node')) + '"><circle class="kg-node-dot kg-node-dot--' + escapeHtml(node.category || 'default') + '" cx="' + escapeHtml(String(node.x)) + '" cy="' + escapeHtml(String(node.y)) + '" r="' + escapeHtml(String(Math.max(node.synthetic ? 2.4 : 3.8, nr / (node.synthetic ? 1.05 : 1.65)))) + '"></circle></g>';
      }).join('')
      + '</svg>'
      /* Labels overlaid on SVG */
      + '<div class="kg-labels">' + labels.map(function (node) {
        var active = isNodeFocused(node, focused);
        return '<span class="kg-label' + (active ? ' on' : ' off') + (node.synthetic ? ' is-derived' : '') + '" data-kg-label-id="' + escapeHtml(node.id) + '" style="left:' + escapeHtml(String(node.label_x)) + '%;top:' + escapeHtml(String(node.label_y)) + '%"><span class="kg-label__dot" style="background:' + escapeHtml(getCategoryColor(node)) + '" aria-hidden="true"></span>' + escapeHtml(firstDefined(node.short_label, node.label, 'Node')) + '</span>';
      }).join('') + '</div>'
      + '</div>'
      /* Legend */
      + '<div class="kg-legend" aria-label="Node category legend">' + presentCategories.map(function (cat) {
        return '<span class="kg-legend__item"><span class="kg-legend__swatch" style="background:' + escapeHtml(KG_CATEGORY_COLORS[cat]) + '" aria-hidden="true"></span>' + escapeHtml(firstDefined(KG_CATEGORY_LABELS[cat], cat)) + '</span>';
      }).join('') + '</div>'
      + '<div class="kg-stage__foot"><span class="kg-foot-chip">Select any item for its business meaning</span><span class="kg-foot-chip">Ask Hermes for a decision-focused explanation</span></div>'
      + '</div></div>';

    /* ── Wire question lens buttons ── */
    safeArray(card.querySelectorAll('[data-kg-question]')).forEach(function (button) {
      button.onclick = function () {
        state.knowledgeQuestionIndex = Number(button.getAttribute('data-kg-question') || 0) || 0;
        closeNodeInspector();
        renderKnowledgeGraph();
      };
    });

    /* ── Wire node hover ── */
    var stage = card.querySelector(".kg-stage");
    if (stage) {
      safeArray(stage.querySelectorAll(".kg-node")).forEach(function (g) {
        var nid = g.getAttribute("data-kg-id") || "";
        g.addEventListener("mouseenter", function () { highlightConnected(nid); });
        g.addEventListener("mouseleave", function () { clearHighlights(); });
        g.addEventListener("focus", function () { highlightConnected(nid); });
        g.addEventListener("blur", function () { clearHighlights(); });
        // Click to open inspector
        g.addEventListener("click", function (e) {
          e.stopPropagation();
          var node = nodeMap[nid];
          if (node) openNodeInspector(node);
        });
        // Keyboard: Enter/Space to open inspector
        g.addEventListener("keydown", function (e) {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            var node = nodeMap[nid];
            if (node) openNodeInspector(node);
          }
        });
      });

      // Click on stage background closes inspector
      stage.addEventListener("click", function (e) {
        if (e.target === stage || e.target.classList.contains("kg-svg") || e.target.classList.contains("kg-canvas")) {
          closeNodeInspector();
        }
      });

      stage.addEventListener('wheel', function (event) {
        event.preventDefault();
        state.kgZoom = clampNumber((state.kgZoom || 1) + (event.deltaY < 0 ? 0.12 : -0.12), 0.7, 2.4);
        renderKnowledgeGraph();
      }, { passive: false });

      stage.addEventListener('mousedown', function (event) {
        var target = event.target;
        if (target && target.closest && target.closest('.kg-node')) return;
        state._kgDragState = {
          startX: event.clientX,
          startY: event.clientY,
          panX: Number(state.kgPanX || 0),
          panY: Number(state.kgPanY || 0)
        };
        stage.classList.add('is-dragging');
      });

      stage.addEventListener('keydown', function (event) {
        if (event.key === '+' || event.key === '=') {
          event.preventDefault();
          state.kgZoom = clampNumber((state.kgZoom || 1) + 0.12, 0.7, 2.4);
          renderKnowledgeGraph();
        } else if (event.key === '-') {
          event.preventDefault();
          state.kgZoom = clampNumber((state.kgZoom || 1) - 0.12, 0.7, 2.4);
          renderKnowledgeGraph();
        } else if (event.key === 'ArrowLeft') {
          state.kgPanX = Number(state.kgPanX || 0) + 18;
          renderKnowledgeGraph();
        } else if (event.key === 'ArrowRight') {
          state.kgPanX = Number(state.kgPanX || 0) - 18;
          renderKnowledgeGraph();
        } else if (event.key === 'ArrowUp') {
          state.kgPanY = Number(state.kgPanY || 0) + 18;
          renderKnowledgeGraph();
        } else if (event.key === 'ArrowDown') {
          state.kgPanY = Number(state.kgPanY || 0) - 18;
          renderKnowledgeGraph();
        }
      });
    }

    var densityToggle = $('kg-density-toggle');
    if (densityToggle) densityToggle.onclick = function () {
      state.kgDensityMode = (state.kgDensityMode || 'compact') === 'dense' ? 'compact' : 'dense';
      renderKnowledgeGraph();
    };
    var zoomIn = $('kg-zoom-in');
    if (zoomIn) zoomIn.onclick = function () {
      state.kgZoom = clampNumber((state.kgZoom || 1) + 0.15, 0.7, 2.4);
      renderKnowledgeGraph();
    };
    var zoomOut = $('kg-zoom-out');
    if (zoomOut) zoomOut.onclick = function () {
      state.kgZoom = clampNumber((state.kgZoom || 1) - 0.15, 0.7, 2.4);
      renderKnowledgeGraph();
    };
    var fitBtn = $('kg-fit');
    if (fitBtn) fitBtn.onclick = function () {
      state.kgZoom = window.innerWidth <= 720 ? 0.88 : 1;
      state.kgPanX = 0;
      state.kgPanY = 0;
      renderKnowledgeGraph();
    };
    var resetBtn = $('kg-reset');
    if (resetBtn) resetBtn.onclick = function () {
      state.kgZoom = 1;
      state.kgPanX = 0;
      state.kgPanY = 0;
      state.kgDensityMode = state.kgDensityMode || 'compact';
      closeNodeInspector();
      renderKnowledgeGraph();
    };
    var focusBtn = $('kg-focus-mode');
    if (focusBtn) focusBtn.onclick = function () {
      state.kgFocusMode = !state.kgFocusMode;
      renderKnowledgeGraph();
    };
  }

  function renderHero() {
    var diagnostics = getExecutiveDiagnostics();
    var blueprint = getPersonaBlueprint(state.activePersona);
    var hero = diagnostics.hero || {};
    var publication = getPublication();
    var boardPortal = getBoardPortal();
    var agents = (state.latestPacket && state.latestPacket.agents) || {};
    var fullName = sessionDisplayName();
    var firstName = fullName ? fullName.split(/\s+/)[0] : getPersonaLabel(state.activePersona);
    var preferredHero = hero && (hero.summary || hero.body || hero.score_note) ? hero : (blueprint.health || {});
    var hasScore = hero.score !== undefined && hero.score !== null && hero.score !== "";
    var score = Number(firstDefined(hero.score, 0));
    if (preferredHero && preferredHero.score !== undefined && preferredHero.score !== null && preferredHero.score !== "") {
      hasScore = true;
      score = Number(preferredHero.score);
    }
    var clampedScore = Math.max(0, Math.min(100, score));
    var circumference = 2 * Math.PI * 60;
    var dash = circumference * (clampedScore / 100);
    var prompts = getHeroPrompts();
    var miniStats = [
      { label: "Board state", value: statusLabel(firstDefined(state.activeBoard, boardPortal.presentation_state, boardPortal.state, "pre")) },
      { label: "Reports", value: String(firstDefined(publication.report_count, 0)) + (state.activePersona === "ceo" ? " reports ready" : " surfaced") },
      { label: "AI team", value: String(firstDefined((agents.summary || {}).active_count, 0)) + " AI agents active" },
      { label: state.activePersona === "ceo" ? "Needs review" : "Next move", value: state.activePersona === "ceo" ? String(firstDefined(publication.challenged_cases, safeArray((getDrilldown().owed_upward || {}).items).length, 0)) + " items need review" : humanizeToken(firstDefined(getPlanHealth().next_action, (boardPortal.state_detail || {}).title, "review")) }
    ];

    $("hero-eyebrow").textContent = state.activePersona === "board"
      ? "Board portal · current board posture"
      : "Good morning, " + firstName;
    $("hero-head").textContent = firstDefined(preferredHero.headline, preferredHero.summary, hero.summary, hero.label, getPlanHealth().label, "Plan health overview");
    $("hero-body").textContent = firstDefined(preferredHero.body, hero.body, getPlanHealth().summary, "Awaiting executive diagnostics.");
    var truthSourceBadge = diagnostics.source === "database" ? "DB" : diagnostics.source === "governed_artifacts" ? "RUN" : "--";
    var reviewGate = !hasScore && String(firstDefined(hero.status, preferredHero.status, "")) === "review_gate";
    // The former `reviewGate ? "OPEN"` / `reviewGate ? "reviewer decision"`
    // treatment falsely rendered a workflow status as a progress score.
    var heroScoreText = hasScore ? String(clampedScore || 0) : (reviewGate ? "Review" : truthSourceBadge);
    $("hero-score").textContent = heroScoreText;
    // Board-gate labels must remain a single, centred word inside the same
    // 128px reference ring across every governed state (DB, RUN, OPEN, REVIEW).
    $("hero-score").classList.toggle("hero-score__value--compact", heroScoreText.length > 4);
    $("hero-cap").textContent = reviewGate ? "human gate" : firstDefined(preferredHero.scoreNote, preferredHero.score_note, hero.score_note, getPlanHealth().badge, "plan health");
    var scoreMedallion = $("hero-score").closest ? $("hero-score").closest(".hero-score") : null;
    if (scoreMedallion) {
      scoreMedallion.classList.toggle("is-status", !hasScore);
      scoreMedallion.classList.toggle("is-score", hasScore);
      scoreMedallion.setAttribute("aria-label", reviewGate ? "Human review decision required" : (hasScore ? "Plan health score " + heroScoreText : "Governed data status " + heroScoreText));
    }
    var byline = $("hero-byline");
    if (byline) {
      var bylineText = firstDefined(blueprint.by, "");
      byline.textContent = bylineText;
      byline.hidden = true;
    }

    var quote = $("hero-quote");
    if (quote) {
      var quoteText = firstDefined(blueprint.quote, hero.quote, "");
      if (quoteText && state.activePersona !== "ceo") {
        quote.hidden = false;
        quote.textContent = quoteText;
      } else {
        quote.hidden = true;
        quote.textContent = "";
      }
    }

    var arc = $("hero-arc");
    if (arc) {
      arc.style.strokeDasharray = dash + "px " + (circumference - dash) + "px";
      arc.setAttribute("stroke-dasharray", dash + " " + (circumference - dash));
    }
    var dot = $("hero-dot");
    if (dot) {
      var angleRad = (clampedScore / 100) * 2 * Math.PI;
      var dotCx = 64 + 60 * Math.sin(angleRad);
      var dotCy = 64 - 60 * Math.cos(angleRad);
      dot.setAttribute("cx", String(Math.round(dotCx * 10) / 10));
      dot.setAttribute("cy", String(Math.round(dotCy * 10) / 10));
      dot.style.visibility = hasScore && clampedScore > 0 ? "visible" : "hidden";
    }

    var promptRow = $("hero-prompts");
    if (promptRow) {
      promptRow.innerHTML = "";
      prompts.slice(0, 3).forEach(function (prompt) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "prompt-chip";
        button.textContent = prompt;
        button.onclick = function () {
          askAssistant(prompt, button);
        };
        promptRow.appendChild(button);
      });
    }

    var statRow = $("hero-mini-stats");
    if (statRow) {
      statRow.innerHTML = miniStats.map(function (item) {
        return '<div class="mini-stat"><strong>' + escapeHtml(item.value) + '</strong><span>' + escapeHtml(item.label) + '</span></div>';
      }).join("");
    }
  }

  function groundingBadgeMarkup(provenance, explicitGrounding) {
    var explicit = explicitGrounding && typeof explicitGrounding === "object" ? explicitGrounding : {};
    var source = firstDefined(explicit.source, provenance && provenance.source, "");
    var explicitStatus = String(firstDefined(explicit.status, "")).toLowerCase();
    var grounded = explicitStatus === "grounded" || (!explicitStatus && provenance && provenance.complete === true && source);
    var label = grounded ? "Grounded ✓" : "Needs evidence ⚠";
    var title = grounded
      ? "Traceable to " + String(source || "the governed source")
      : "This metric is not fully traceable to governed evidence yet.";
    return '<span class="grounding-badge grounding-badge--' + (grounded ? 'grounded' : 'needs-evidence') + '" title="' + escapeHtml(title) + '">' + label + '</span>';
  }

  function syncDriverSelectionUI(grid, activeKey) {
    if (!grid) return;
    Array.prototype.forEach.call(grid.querySelectorAll("[data-driver-key]"), function (tile) {
      var selected = String(tile.getAttribute("data-driver-key") || "") === String(activeKey || "");
      tile.classList.toggle("is-selected", selected);
      tile.setAttribute("aria-pressed", selected ? "true" : "false");
    });
  }

  function renderDriverGrid() {
    var grid = $("driver-row");
    if (!grid) return;
    var drivers = getVisibleDrivers();
    var activeDriver = getActiveDriver();
    grid.innerHTML = "";
    drivers.forEach(function (driver) {
      var key = String(driver.driver_key || driver.key || "");
      var tile = document.createElement("button");
      tile.type = "button";
      tile.className = "driver-tile" + (activeDriver && String(activeDriver.driver_key || activeDriver.key || "") === key ? " is-selected" : "");
      if (driver.availability === "unavailable") tile.className += " driver-tile--unavailable";
      tile.setAttribute("data-driver-key", key);
      tile.setAttribute("aria-pressed", activeDriver && String(activeDriver.driver_key || activeDriver.key || "") === key ? "true" : "false");
      tile.innerHTML = driver.availability === "unavailable"
        ? [
          '<div class="driver-meta"><strong class="driver-label">' + escapeHtml(firstDefined(driver.label, "Driver")) + '</strong></div>',
          unavailableDriverMarkup(driver),
          groundingBadgeMarkup(driver.provenance, driver.grounding)
        ].join("")
        : [
          '<div class="driver-ring-stage">' + driverRingMarkup(driver) + '<div class="driver-ring-copy">' + driverCenterMarkup(driver) + '</div>' + (Number(firstDefined(driver.pct, 0)) > 100 ? '<span class="driver-over-plan">+' + Math.round(Number(firstDefined(driver.pct, 0)) - 100) + '% vs plan</span>' : '') + '</div>',
          '<div class="driver-meta"><strong class="driver-label">' + escapeHtml(firstDefined(driver.label, "Driver")) + '</strong><div class="driver-foot">' + escapeHtml(firstDefined(driver.metric, '—')) + '<span class="driver-sub"> · ' + escapeHtml(firstDefined(driver.ring_label, driverSubLabel(driver))) + '</span></div>' + groundingBadgeMarkup(driver.provenance, driver.grounding) + '</div>'
        ].join("");
      // Native focus can scroll a partially visible tile before `click`
      // fires. Preserve the executive's position at pointer/keyboard intent,
      // before that browser behaviour can occur.
      var rememberReadingPosition = function () {
        state.driverSelectionScrollY = window.scrollY;
      };
      tile.addEventListener("pointerdown", function (event) {
        rememberReadingPosition();
        // A KPI tile can sit partly below the viewport. Native button focus
        // then scrolls it fully into view before the click handler can restore
        // the executive's reading position. Keep pointer selection focusless;
        // keyboard users retain the normal focus path below.
        if (event.isPrimary && event.button === 0) event.preventDefault();
      });
      tile.addEventListener("touchstart", rememberReadingPosition, { passive: true });
      tile.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") rememberReadingPosition();
      });
      tile.onclick = function (event) {
        if (event) event.preventDefault();
        var rememberedPosition = Number(state.driverSelectionScrollY);
        var readingPosition = Number.isFinite(rememberedPosition) ? rememberedPosition : window.scrollY;
        state.driverSelectionScrollY = null;
        state.activeDriverKey = key;
        updateHistory();
        // Keep the four-card strip and its focused button mounted. Replacing
        // the strip here lets browsers scroll the replacement into view and
        // breaks the dashboard's inline-detail interaction.
        syncDriverSelectionUI(grid, key);
        var restoreReadingPosition = function () {
          if (window.scrollY !== readingPosition) window.scrollTo(0, readingPosition);
        };
        restoreReadingPosition();
        window.requestAnimationFrame(function () {
          renderDriverDrillFidelity();
          renderSummary();
          // KPI detail is deliberately inline below the strip. Selecting a
          // tile must never move the executive's reading position. Browsers
          // can apply scroll anchoring after the next frame when the selected
          // tile changes, so preserve it across that late layout pass as well.
          restoreReadingPosition();
          window.setTimeout(restoreReadingPosition, 0);
          window.setTimeout(restoreReadingPosition, 220);
        });
      };
      grid.appendChild(tile);
    });
  }

  function renderMetrics() {
    var grid = $("metrics-grid");
    var driver = getActiveDriver() || {};
    var publication = getPublication();
    var boardPortal = getBoardPortal();
    var drilldown = getDrilldown();
    if (!grid) return;
    var metrics = [
      {
        label: "Driver posture",
        value: firstDefined(driver.label, getPlanHealth().label, "Awaiting board data"),
        detail: firstDefined(driver.detail, getPlanHealth().summary, "No board driver summary yet."),
        provenance: driver.provenance
      },
      {
        label: "Board lifecycle",
        value: statusLabel(firstDefined(state.activeBoard, boardPortal.presentation_state, boardPortal.state, "pre")),
        detail: firstDefined(boardStateSupportNote(boardPortal), "Board-safe lifecycle stays explicit."),
        grounding: { status: boardPortal.presentation_state ? "grounded" : "needs_evidence", source: "governed board lifecycle" }
      },
      {
        label: "Evidence closure",
        value: String(firstDefined((drilldown.owed_upward || {}).challenge_count, publication.challenged_cases, 0)) + " challenged",
        detail: "Questions stay attached to evidence, not theatre.",
        grounding: { status: publication.reconciliation ? "grounded" : "needs_evidence", source: "governed audit reconciliation" }
      },
      {
        label: "Report surface",
        value: String(firstDefined(publication.report_count, 0)) + " routes",
        detail: firstDefined(publication.preview_route, "Board pack preview waits for the current board pack."),
        grounding: { status: Number(publication.report_count || 0) > 0 ? "grounded" : "needs_evidence", source: "governed artifact registry" }
      }
    ];
    grid.innerHTML = metrics.map(function (metric) {
      return '<article class="metric-card"><span class="metric-label">' + escapeHtml(metric.label) + '</span><strong class="metric-value">' + escapeHtml(metric.value) + '</strong><p class="metric-detail">' + escapeHtml(metric.detail) + '</p>' + groundingBadgeMarkup(metric.provenance, metric.grounding) + '</article>';
    }).join("");
  }

  function executiveKpiBrief(driver) {
    var supplied = driver && driver.executive_brief;
    if (supplied && typeof supplied === "object") return supplied;
    var key = String(firstDefined(driver && driver.driver_key, driver && driver.key, ""));
    var isCash = key === "cash_vs_floor";
    var missing = safeArray(driver && driver.missing_inputs);
    return {
      period_label: "Current actual",
      metric: firstDefined(driver && driver.metric, driver && driver.value, "—"),
      readout: firstDefined(driver && driver.detail, "No calculation is available."),
      comparison: {
        label: "Current-period comparison",
        value: missing.length ? "Not yet aligned" : firstDefined(driver && driver.comparison, "Available"),
        note: missing.length ? "A comparator for the same period and scope has not yet been connected." : "Compared with the approved comparator for this period.",
        available: !missing.length
      },
      calculation: {
        label: "How this figure is built",
        formula: firstDefined(driver && driver.formula, "No calculation method is available."),
        steps: [{ label: firstDefined(driver && driver.label, "KPI actual"), value: firstDefined(driver && driver.metric, driver && driver.value, "—") }]
      },
      coverage: {
        label: "Data coverage",
        value: missing.length ? "Partial" : "Complete",
        note: missing.length ? "The figure is shown without estimating any missing values." : "All source values used in this figure are present."
      },
      audit: {
        source_titles: [], source_files: safeArray(driver && driver.source_files), required_inputs: safeArray(driver && driver.inputs), missing_inputs: missing,
        evidence_summary: firstDefined(driver && driver.evidence_summary, ""), computation_boundary: "No missing value has been estimated."
      }
    };
  }

  // A selected KPI needs to answer a CEO's three immediate questions: what is
  // happening, what changed, and what it means.  The former drill stacked a
  // donut, a second bar treatment, and an unconstrained chart; it made those
  // questions harder to answer.  These helpers intentionally mirror the
  // compact target drill: one factual trend, one movement list, and one
  // composition/bridge view, all backed by the governed card payload.
  function formatExecutiveTrendValue(value, driver) {
    var number = Number(value);
    if (!Number.isFinite(number)) return "—";
    var trendUnit = String((driver && driver.trend && driver.trend.unit) || (driver && driver.trend_unit) || "").toLowerCase();
    var clue = [driver && driver.label, driver && driver.metric, driver && driver.value, driver && driver.unit].join(" ").toLowerCase();
    var absolute = Math.abs(number);
    var sign = number < 0 ? "−" : "";
    if (/(percent|percentage|pct|%)/.test(trendUnit)) return number.toFixed(Math.abs(number) >= 10 ? 1 : 2) + "%";
    if (/(sar|currency|money)/.test(trendUnit)) {
      if (absolute >= 1000000000) return sign + "SAR " + (absolute / 1000000000).toFixed(absolute >= 10000000000 ? 0 : 1) + "B";
      if (absolute >= 1000000) return sign + "SAR " + (absolute / 1000000).toFixed(absolute >= 100000000 ? 0 : 1) + "M";
      if (absolute >= 1000) return sign + "SAR " + (absolute / 1000).toFixed(absolute >= 100000 ? 0 : 1) + "K";
      return sign + "SAR " + absolute.toLocaleString("en-US", { maximumFractionDigits: 0 });
    }
    if (/(sar|revenue|cost|cash|ebitda)/.test(clue)) {
      if (absolute >= 1000000000) return sign + "SAR " + (absolute / 1000000000).toFixed(absolute >= 10000000000 ? 0 : 1) + "B";
      if (absolute >= 1000000) return sign + "SAR " + (absolute / 1000000).toFixed(absolute >= 100000000 ? 0 : 1) + "M";
      if (absolute >= 1000) return sign + "SAR " + (absolute / 1000).toFixed(absolute >= 100000 ? 0 : 1) + "K";
      return sign + "SAR " + absolute.toLocaleString("en-US", { maximumFractionDigits: 0 });
    }
    if (/(%|margin|rate|ratio)/.test(clue)) return number.toFixed(Math.abs(number) >= 10 ? 1 : 2) + "%";
    return number.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }

  function formatExecutiveTrendPeriod(value) {
    var raw = String(value || "").trim();
    var match = /^(\d{4})-(\d{2})$/.exec(raw);
    if (!match) return raw || "Reporting period";
    var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return months[Math.max(0, Math.min(11, Number(match[2]) - 1))] + " " + match[1];
  }

  function kpiTrendChartMarkup(driver) {
    var label = firstDefined(driver && driver.label, "KPI");
    var trend = driver && driver.trend;
    var actual = safeArray(trend && trend.actual).map(Number).filter(function (value) { return Number.isFinite(value); });
    var plan = safeArray(trend && trend.plan).map(Number).filter(function (value) { return Number.isFinite(value); });
    var labels = safeArray(trend && trend.labels);
    var hasPlan = trend && trend.has_plan_series === true && plan.length === actual.length && actual.length > 1;
    if (actual.length <= 1) return '';
    var values = actual.concat(hasPlan ? plan : []);
    var low = Math.min.apply(null, values);
    var high = Math.max.apply(null, values);
    if (high === low) {
      var visualPadding = Math.max(Math.abs(high) * 0.05, 1);
      low -= visualPadding;
      high += visualPadding;
    }
    var span = Math.max(1, high - low);
    var chart = { width: 360, left: 44, right: 344, top: 18, bottom: 130 };
    var pathFor = function (series) {
      return series.map(function (value, index) {
        var x = series.length === 1 ? (chart.left + chart.right) / 2 : chart.left + (index * (chart.right - chart.left)) / (series.length - 1);
        var y = chart.bottom - ((value - low) / span) * (chart.bottom - chart.top);
        return (index ? 'L' : 'M') + x.toFixed(1) + ',' + y.toFixed(1);
      }).join(' ');
    };
    var accessibleLabels = labels.length === actual.length ? labels.join(', ') : actual.length + ' governed reporting periods';
    var latestIndex = actual.length - 1;
    var priorIndex = actual.length - 2;
    var latest = actual[latestIndex];
    var latestMovement = latest - actual[priorIndex];
    var yTicks = [high, (high + low) / 2, low];
    var yGrid = yTicks.map(function (value) {
      var y = chart.bottom - ((value - low) / span) * (chart.bottom - chart.top);
      return '<line class="kpi-trend__grid" x1="' + chart.left + '" x2="' + chart.right + '" y1="' + y.toFixed(1) + '" y2="' + y.toFixed(1) + '"></line><text class="kpi-trend__axis kpi-trend__axis--y" x="0" y="' + (y + 3).toFixed(1) + '">' + escapeHtml(formatExecutiveTrendValue(value, driver)) + '</text>';
    }).join('');
    var xLabels = actual.map(function (_value, index) {
      var x = actual.length === 1 ? (chart.left + chart.right) / 2 : chart.left + (index * (chart.right - chart.left)) / (actual.length - 1);
      var rawLabel = labels.length === actual.length ? labels[index] : 'Period ' + String(index + 1);
      return '<text class="kpi-trend__axis kpi-trend__axis--x" x="' + x.toFixed(1) + '" y="154" text-anchor="middle">' + escapeHtml(formatExecutiveTrendPeriod(rawLabel)) + '</text>';
    }).join('');
    var points = actual.map(function (value, index) {
      var x = actual.length === 1 ? (chart.left + chart.right) / 2 : chart.left + (index * (chart.right - chart.left)) / (actual.length - 1);
      var y = chart.bottom - ((value - low) / span) * (chart.bottom - chart.top);
      var period = labels.length === actual.length ? formatExecutiveTrendPeriod(labels[index]) : 'Period ' + String(index + 1);
      return '<circle class="kpi-trend__point" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' + (index === latestIndex ? '3.7' : '2.4') + '"><title>' + escapeHtml(period + ': ' + formatExecutiveTrendValue(value, driver)) + '</title></circle>';
    }).join('');
    var movementLabel = latestMovement === 0 ? 'No change' : (latestMovement > 0 ? '+' : '−') + formatExecutiveTrendValue(Math.abs(latestMovement), driver);
    var latestPeriod = labels.length === actual.length ? formatExecutiveTrendPeriod(labels[latestIndex]) : 'Latest period';
    var priorPeriod = labels.length === actual.length ? formatExecutiveTrendPeriod(labels[priorIndex]) : 'prior period';
    return '<section class="kpi-trend"><div class="kpi-trend__head"><div><span class="kpi-brief-label">Reporting trajectory</span><small>' + escapeHtml(hasPlan ? 'Actual versus aligned plan' : 'Actual series only — plan is not inferred') + '</small></div><div class="kpi-trend__legend"><span class="kpi-trend__actual-key">Actual</span>' + (hasPlan ? '<span class="kpi-trend__plan-key">Aligned plan</span>' : '') + '</div></div><svg viewBox="0 0 360 164" role="img" aria-label="' + escapeHtml(label + (hasPlan ? ' actual versus aligned plan across ' : ' actual trend across ') + accessibleLabels) + '">' + yGrid + '<path class="trend-chain__actual" d="' + escapeHtml(pathFor(actual)) + '"></path>' + (hasPlan ? '<path class="trend-chain__plan" d="' + escapeHtml(pathFor(plan)) + '"></path>' : '') + points + xLabels + '</svg><div class="kpi-trend__summary"><div><span>Latest</span><strong>' + escapeHtml(formatExecutiveTrendValue(latest, driver)) + '</strong><small>' + escapeHtml(latestPeriod) + '</small></div><div><span>Change</span><strong>' + escapeHtml(movementLabel) + '</strong><small>versus ' + escapeHtml(priorPeriod) + '</small></div></div></section>';
  }

  function kpiMovementMarkup(driver) {
    var movers = (driver && driver.movers) || {};
    var higher = safeArray(movers.lifting).slice(0, 2);
    var lower = safeArray(movers.dragging).slice(0, 2);
    var rows = [];
    if (higher.length) {
      rows.push('<div class="kpi-movement__group"><span>Higher in the latest period</span>' + higher.map(function (item) {
        return '<div class="kpi-movement__row"><span class="kpi-movement__direction kpi-movement__direction--up">↗</span><strong>' + escapeHtml(firstDefined(item && item.name, 'Movement')) + '</strong><small>' + escapeHtml(firstDefined(item && item.delta, '')) + '</small></div>';
      }).join('') + '</div>');
    }
    if (lower.length) {
      rows.push('<div class="kpi-movement__group"><span>Lower in the latest period</span>' + lower.map(function (item) {
        return '<div class="kpi-movement__row"><span class="kpi-movement__direction kpi-movement__direction--down">↘</span><strong>' + escapeHtml(firstDefined(item && item.name, 'Movement')) + '</strong><small>' + escapeHtml(firstDefined(item && item.delta, '')) + '</small></div>';
      }).join('') + '</div>');
    }
    return '<section class="kpi-movement' + (rows.length ? '' : ' kpi-movement--empty') + '"><div class="kpi-movement__head"><span class="kpi-brief-label">What changed</span><small>Contribution by account in the two latest governed periods</small></div>' + (rows.length ? rows.join('') : '<p>No category-level movement is available for the selected reporting periods.</p>') + '</section>';
  }

  function kpiCompositionMarkup(key, brief, drivers) {
    var rows = safeArray(drivers);
    var shares = rows.map(function (item) { return Number(item && item.share_pct); });
    var allShares = rows.length >= 2 && shares.every(function (share) { return Number.isFinite(share) && share > 0; });
    var total = allShares ? shares.reduce(function (sum, share) { return sum + share; }, 0) : 0;
    var titles = {
      revenue: 'Where current revenue comes from',
      operating_cost: 'Where current operating cost sits',
      cash_vs_floor: 'Where reported cash sits'
    };
    if (allShares && total >= 98 && total <= 102) {
      var description = rows.map(function (item) {
        return firstDefined(item.label, 'Component') + ' ' + Number(item.share_pct).toFixed(1) + '%';
      }).join(', ');
      return '<section class="kpi-composition"><div class="kpi-composition__head"><span class="kpi-brief-label">' + escapeHtml(firstDefined(titles[key], brief.driver_title, 'Current composition')) + '</span><small>Share of the current reported figure</small></div><div class="kpi-composition__bar" role="img" aria-label="' + escapeHtml(description) + '">' + rows.map(function (item, index) {
        var share = Number(item.share_pct);
        return '<span class="kpi-composition__segment tone-' + (index % 6) + '" style="flex-grow:' + escapeHtml(share.toFixed(3)) + '"><title>' + escapeHtml(firstDefined(item.label, 'Component') + ': ' + share.toFixed(1) + '%') + '</title></span>';
      }).join('') + '</div><div class="kpi-composition__legend">' + rows.map(function (item, index) {
        return '<div><span class="kpi-composition__swatch tone-' + (index % 6) + '"></span><span>' + escapeHtml(firstDefined(item.label, 'Component')) + '</span><strong>' + escapeHtml(firstDefined(item.value, '—')) + '</strong><small>' + escapeHtml(Number(item.share_pct).toFixed(1)) + '%</small></div>';
      }).join('') + '</div></section>';
    }
    var bridgeRows = rows.length ? rows : safeArray((brief.calculation || {}).steps);
    if (!bridgeRows.length) return '';
    return '<section class="kpi-bridge"><div class="kpi-bridge__head"><span class="kpi-brief-label">' + escapeHtml(firstDefined(brief.driver_title, 'How this figure is built')) + '</span><small>Current reported inputs</small></div><div class="kpi-bridge__rows">' + bridgeRows.map(function (item) {
      return '<div><span>' + escapeHtml(firstDefined(item.label, 'Component')) + '</span><strong>' + escapeHtml(firstDefined(item.value, '—')) + '</strong></div>';
    }).join('') + '</div></section>';
  }

  function kpiExecutiveContextMarkup(brief, comparison, strategicReference) {
    var comparisonAvailable = comparison && comparison.available === true;
    var audit = brief.audit || {};
    var missing = safeArray(audit.missing_inputs);
    var comparisonHeading = comparisonAvailable ? 'Plan comparison' : 'Plan comparison unavailable';
    var comparisonDetail = firstDefined(comparison.note, comparisonAvailable ? 'A like-for-like approved comparator is connected.' : 'No like-for-like approved comparator is connected.');
    var missingDetail = missing.length ? '<small>Needed to compare: ' + escapeHtml(missing.join(' · ')) + '</small>' : '';
    var referenceMarkup = strategicReference
      ? '<div class="kpi-comparison__reference"><span>' + escapeHtml(firstDefined(strategicReference.label, 'Approved strategic reference')) + '</span><strong>' + escapeHtml(firstDefined(strategicReference.value, '—')) + '</strong><small>' + escapeHtml(firstDefined(strategicReference.note, 'Reference only; not treated as a period comparison.')) + '</small></div>'
      : '';
    return '<div class="kpi-executive-context"><section class="kpi-decision-context"><span class="kpi-brief-label">What this means for you</span><strong>' + escapeHtml(firstDefined(brief.decision_context, 'No decision implication is available.')) + '</strong></section><section class="kpi-comparison ' + (comparisonAvailable ? 'is-available' : 'is-withheld') + '"><span class="kpi-brief-label">' + escapeHtml(comparisonHeading) + '</span><strong>' + escapeHtml(firstDefined(comparison.value, comparisonAvailable ? 'Available' : 'Withheld')) + '</strong><p>' + escapeHtml(comparisonDetail) + '</p>' + missingDetail + referenceMarkup + '</section></div>';
  }

  function renderInlineKpiDrill(driver, drillCard) {
    var label = firstDefined(driver.label, "this KPI");
    var availability = String(firstDefined(driver.availability, "unavailable"));
    var key = String(firstDefined(driver.driver_key, driver.key, ""));
    var assistantName = assistantNameForState();
    var brief = executiveKpiBrief(driver);
    var comparison = brief.comparison || {};
    var strategicReference = brief.strategic_reference || null;
    var calculation = brief.calculation || {};
    var coverage = brief.coverage || {};
    var audit = brief.audit || {};
    var steps = safeArray(calculation.steps);
    var drivers = safeArray(brief.drivers);
    var auditSources = safeArray(audit.source_titles);
    var trendMarkup = kpiTrendChartMarkup(driver);
    if (!trendMarkup) {
      trendMarkup = '<section class="kpi-trend kpi-trend--empty"><span class="kpi-brief-label">Reporting trajectory</span><p>At least two governed reporting periods are needed before StrategyOS can show movement. No plan line has been supplied.</p></section>';
    }
    // Use the same governed percentage contract as the dashboard gauge. Some
    // KPIs intentionally leave the legacy `pct` field null and expose their
    // audited ratio as `ring_pct`; Number(null) would incorrectly render 0.0%.
    var headlinePctRaw = firstDefined(driver && driver.ring_pct, driver && driver.pct, null);
    var headlinePct = headlinePctRaw === null || headlinePctRaw === undefined || headlinePctRaw === ""
      ? NaN
      : Number(headlinePctRaw);
    var headlineRatioLabel = String(firstDefined(driver && driver.ring_label, driverSubLabel(driver), "of plan"));
    // A long-horizon board reference is useful context, but it is never a
    // substitute for a period-aligned performance comparison.
    var referenceOnlyRatio = comparison.available !== true && /(plan|floor)/i.test(headlineRatioLabel);
    var headlineRatio = Number.isFinite(headlinePct) && headlineRatioLabel !== "current margin"
      ? headlinePct.toFixed(1) + "% " + headlineRatioLabel + (referenceOnlyRatio ? " · reference only" : "")
      : "";
    var calculationMarkup = steps.length
      ? '<div class="kpi-brief-steps">' + steps.map(function (step) {
        return '<div class="kpi-brief-step"><span>' + escapeHtml(firstDefined(step.label, "Component")) + '</span><strong>' + escapeHtml(firstDefined(step.value, "—")) + '</strong></div>';
      }).join("") + '</div>'
      : "";
    var movementMarkup = kpiMovementMarkup(driver);
    var compositionMarkup = kpiCompositionMarkup(key, brief, drivers);
    var executiveContextMarkup = kpiExecutiveContextMarkup(brief, comparison, strategicReference);
    drillCard.innerHTML = [
      '<div class="drill-surface kpi-inline-drill" data-kpi-key="' + escapeHtml(key) + '">',
      '<div class="kpi-brief-header"><div><p class="detail-eyebrow">' + escapeHtml(firstDefined(brief.period_label, "Current actual")) + '</p><div class="kpi-brief-title-row"><h3 class="detail-title">' + escapeHtml(label) + '</h3>' + (headlineRatio ? '<span class="kpi-brief-ratio">' + escapeHtml(headlineRatio) + '</span>' : '') + '<strong class="kpi-brief-value">' + escapeHtml(firstDefined(brief.metric, driver.metric, "—")) + '</strong></div></div>' + groundingBadgeMarkup(driver.provenance, driver.grounding) + '</div>',
      '<div class="kpi-brief-summary"><p>' + escapeHtml(firstDefined(brief.readout, "No explanation is available.")) + '</p></div>',
      executiveContextMarkup,
      '<div class="kpi-executive-grid">' + trendMarkup + movementMarkup + '</div>',
      compositionMarkup,
      '<section class="kpi-inline-chat" aria-label="Ask ' + escapeHtml(assistantName) + ' about ' + escapeHtml(label) + '"><div class="kpi-inline-chat__intro"><div><span class="kpi-brief-label">Discuss this figure</span><strong>Ask ' + escapeHtml(assistantName) + ' about ' + escapeHtml(label) + '</strong><p>Continue in the shared conversation with this figure already in context.</p></div></div><div class="kpi-question-actions"><button type="button" data-kpi-question="decision">What needs my attention?</button><button type="button" data-kpi-question="drivers">What is driving this result?</button><button type="button" data-kpi-question="comparison">How does this compare with the approved plan?</button></div></section>',
      '<details class="kpi-brief-audit"><summary>How this figure is calculated</summary><div class="kpi-brief-audit__body"><div><span>Method</span><strong>' + escapeHtml(firstDefined(calculation.formula, "Calculation method is not available.")) + '</strong></div>' + calculationMarkup + '<div><span>Coverage</span><strong>' + escapeHtml(firstDefined(coverage.value, "Unknown")) + ' — ' + escapeHtml(firstDefined(coverage.note, "")) + '</strong></div>' + (auditSources.length ? '<div><span>Business sources</span><strong>' + escapeHtml(auditSources.join(" · ")) + '</strong></div>' : "") + (safeArray(audit.missing_inputs).length ? '<div><span>Needed for a valid comparison</span><strong>' + escapeHtml(safeArray(audit.missing_inputs).join(" · ")) + '</strong></div>' : "") + '</div></details>',
      '</div>'
    ].join("");
    safeArray(drillCard.querySelectorAll("[data-kpi-question]")).forEach(function (button) {
      button.addEventListener("click", function () {
        var questionType = button.getAttribute("data-kpi-question");
        var prompts = {
          decision: "For " + label + ", what requires my decision or attention now?",
          drivers: "What is driving the current " + label + " result, and where is concentration highest?",
          comparison: "Explain how " + label + " relates to the approved plan, and why any direct comparison is currently withheld."
        };
        askAssistant(prompts[questionType] || prompts.decision, button, {
          entrypoint: "ceo_kpi_inline",
          source: "executive_surface",
          kpi_key: key,
          kpi_label: label,
          kpi_question_intent: questionType,
          kpi_availability: availability,
          active_view: "home"
        });
      });
    });
  }

  function renderDriverDrillFidelity() {
    var driver = getActiveDriver() || {};
    var drillCard = $("driver-drill");
    var gravityPanel = $("gravity-panel");
    var board = getBoardPortal();
    var publication = getPublication();
    var gravity = getDrilldown().gravity || {};
    var movers = driver.movers || {};
    var lifting = safeArray(movers.lifting);
    var dragging = safeArray(movers.dragging);
    if (driver.kpi_contract && drillCard) {
      renderInlineKpiDrill(driver, drillCard);
    } else if (drillCard) {
      var trendSeries = driver.trend || driverTrendSeries(driver);
      var actualSeries = safeArray(trendSeries.actual).length ? safeArray(trendSeries.actual) : [92, 96, 99, 101, 100, 102];
      var planSeries = safeArray(trendSeries.plan).length ? safeArray(trendSeries.plan) : actualSeries.map(function (value) { return value * 0.98; });
      var minSeries = Math.min.apply(null, actualSeries.concat(planSeries));
      var maxSeries = Math.max.apply(null, actualSeries.concat(planSeries));
      var spanSeries = Math.max(1, maxSeries - minSeries);
      var chartWidth = 320;
      var chartHeight = 156;
      var chartPoints = function (series) {
        return series.map(function (value, idx) {
          var x = series.length === 1 ? chartWidth / 2 : (idx * chartWidth) / (series.length - 1);
          var y = chartHeight - (((value - minSeries) / spanSeries) * 120 + 18);
          return [x, y];
        });
      };
      var actualPoints = chartPoints(actualSeries);
      var planPoints = chartPoints(planSeries);
      var actualPath = actualPoints.map(function (pair, idx) {
        return (idx ? "L" : "M") + pair[0].toFixed(1) + "," + pair[1].toFixed(1);
      }).join(" ");
      var planPath = planPoints.map(function (pair, idx) {
        return (idx ? "L" : "M") + pair[0].toFixed(1) + "," + pair[1].toFixed(1);
      }).join(" ");
      var yTicks = [maxSeries, (maxSeries + minSeries) / 2, minSeries];
      var xLabels = actualSeries.map(function (_value, idx) {
        return 'W' + String(actualSeries.length - idx);
      });
      var moverRows = lifting.map(function (item) { return { tone: 'up', glyph: '↗', item: item }; })
        .concat(dragging.map(function (item) { return { tone: 'down', glyph: '↘', item: item }; }));
      drillCard.innerHTML = [
        '<div class="drill-surface">',
        '<div class="drill-headline"><div><h3 class="detail-title">What\'s driving ' + escapeHtml(firstDefined(driver.label, 'it')) + '</h3><p class="section-note">' + escapeHtml(driverMeasureLabel(driver) + ' · ' + driverSubLabel(driver)) + '</p></div><button class="assistant-tool-chip assistant-tool-chip--button" type="button" data-driver-show-work="true">Show the work</button></div>',
        '<p class="detail-copy">' + escapeHtml(firstDefined(driver.detail, 'Awaiting drill detail.')) + '</p>',
        '<div class="drill-grid-v2"><div class="drill-trend-panel"><div class="mini-head">' + escapeHtml(firstDefined(driver.trendLabel, 'Trend')) + '<span class="trend-legend"><span class="lg actual"></span> actual <span class="lg plan"></span> plan</span></div><svg class="drill-trend-chart" viewBox="0 0 320 156" role="img" aria-label="' + escapeHtml(firstDefined(driver.label, 'Driver')) + ' trend: actual versus plan over the last ' + String(actualSeries.length) + ' weeks">' + yTicks.map(function (tick) { var y = chartHeight - (((tick - minSeries) / spanSeries) * 120 + 18); return '<line class="trend-gridline" x1="0" x2="320" y1="' + y.toFixed(1) + '" y2="' + y.toFixed(1) + '"></line><text class="trend-axis" x="4" y="' + Math.max(10, y - 4).toFixed(1) + '">' + escapeHtml(String(Math.round(tick * 10) / 10)) + '</text>'; }).join('') + '<path class="trend-chain__plan" d="' + escapeHtml(planPath) + '"></path><path class="trend-chain__actual" d="' + escapeHtml(actualPath) + '"></path>' + actualPoints.map(function (pair, idx) { return '<circle class="trend-point actual" cx="' + pair[0].toFixed(1) + '" cy="' + pair[1].toFixed(1) + '" r="3"><title>Actual ' + escapeHtml(xLabels[idx]) + ': ' + escapeHtml(String(actualSeries[idx])) + ' ' + escapeHtml(firstDefined(driver.unit, '')) + '</title></circle>'; }).join('') + planPoints.map(function (pair, idx) { return '<circle class="trend-point plan" cx="' + pair[0].toFixed(1) + '" cy="' + pair[1].toFixed(1) + '" r="2.5"><title>Plan ' + escapeHtml(xLabels[idx]) + ': ' + escapeHtml(String(planSeries[idx])) + ' ' + escapeHtml(firstDefined(driver.unit, '')) + '</title></circle>'; }).join('') + xLabels.map(function (label, idx) { var point = actualPoints[idx]; return '<text class="trend-axis" x="' + point[0].toFixed(1) + '" y="150" text-anchor="middle">' + escapeHtml(label) + '</text>'; }).join('') + '</svg><div class="trend-unit">' + escapeHtml(firstDefined(driver.unit, '')) + '</div></div><div class="drill-movers-panel"><div class="mini-head">What moved it</div><div class="movers-flat">' + (moverRows.length ? moverRows.map(function (entry) {
          var item = entry.item || {};
          var noteKey = firstDefined(driver.driver_key, driver.key, '') + ':' + firstDefined(item.name, 'mover');
          var noteOpen = state.openDriverNoteKey === noteKey;
          var gm = item.gm || null;
          return '<div class="mover-flat ' + (noteOpen ? 'is-open' : '') + '"><div class="mover-flat__row"><span class="mover-flat__dir tone-' + escapeHtml(entry.tone) + '">' + escapeHtml(entry.glyph) + '</span><span class="mover-flat__name">' + escapeHtml(firstDefined(item.name, 'Signal')) + '</span><span class="mover-flat__delta">' + escapeHtml(firstDefined(item.delta, '')) + '</span>' + (gm ? '<button type="button" class="gm-chip gm-chip--avatar' + (noteOpen ? ' is-open' : '') + '" data-driver-note="' + escapeHtml(noteKey) + '"><span class="asst-avatar sm">' + escapeHtml(initialsFromName(gm.who)) + '</span><span>GM note</span></button>' : '<span class="gm-none" title="No GM note is attached to this mover yet.">No GM note</span>') + '</div>' + (gm && noteOpen ? '<blockquote class="gm-note"><span class="gm-note-who">' + escapeHtml(firstDefined(gm.who, 'GM')) + '</span>' + escapeHtml(firstDefined(gm.note, '')) + '</blockquote>' : '') + '</div>';
        }).join('') : '<div class="discovery-empty">No movement is attached yet.</div>') + '</div></div></div>',
        '<div class="chips">' + safeArray(driver.chips).map(function (chip) { return '<button class="chip" type="button" data-driver-chip="' + escapeHtml(chip) + '">' + escapeHtml(chip) + '</button>'; }).join('') + '</div>',
        '<form class="chips-own" id="driver-composer"><label class="sr-only" for="driver-input">Ask Hermes about ' + escapeHtml(String(firstDefined(driver.label, 'this driver')).toLowerCase()) + '</label><input id="driver-input" class="driver-input" type="text" placeholder="Ask Hermes about ' + escapeHtml(String(firstDefined(driver.label, 'this driver')).toLowerCase()) + '…" /><button type="submit">Send</button></form>',
        '<!-- openAssistantDrawer() is triggered by the driver composer submit handler below. -->',
        '<div class="drill-evidence" hidden><span class="evidence-label">Evidence chain</span><span class="evidence-step">Board-approved plan v4</span><span class="evidence-arrow">→</span><span class="evidence-step">Knowledge graph · 8 BU ledgers</span><span class="evidence-arrow">→</span><span class="evidence-step">S/4HANA + BI connectors</span><span class="evidence-arrow">→</span><span class="evidence-step">computed today 06:14</span></div>',
        '</div>'
      ].join('');
      safeArray(drillCard.querySelectorAll('[data-driver-note]')).forEach(function (button) {
        button.onclick = function () {
          var key = button.getAttribute('data-driver-note') || '';
          state.openDriverNoteKey = state.openDriverNoteKey === key ? '' : key;
          renderDriverDrillFidelity();
        };
      });
      safeArray(drillCard.querySelectorAll('[data-driver-chip]')).forEach(function (button) {
        button.onclick = function () {
          var prompt = 'On ' + firstDefined(driver.label, 'this driver') + ' (' + driverMeasureLabel(driver) + '): ' + (button.getAttribute('data-driver-chip') || '');
          askAssistant(prompt, button);
        };
      });
      var showWork = drillCard.querySelector('[data-driver-show-work]');
      var evidence = drillCard.querySelector('.drill-evidence');
      if (showWork && evidence) {
        showWork.onclick = function () {
          evidence.hidden = !evidence.hidden;
          showWork.textContent = evidence.hidden ? 'Show the work' : 'Hide the work';
          if (!evidence.hidden) evidence.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        };
      }
      var composer = drillCard.querySelector('#driver-composer');
      var input = drillCard.querySelector('#driver-input');
      if (composer && input) {
        composer.addEventListener('submit', function (event) {
          event.preventDefault();
          var message = String(input.value || '').trim();
          if (!message) return;
          var prompt = 'On ' + firstDefined(driver.label, 'this driver') + ' (' + driverMeasureLabel(driver) + '): ' + message;
          askAssistant(prompt, composer);
          openAssistantDrawer();
          input.value = '';
        });
      }
    }
    if (gravityPanel) {
      var currentLabel = firstDefined(driver.label, "the selected KPI");
      var brief = executiveKpiBrief(driver);
      var governedPrompts = [
        firstDefined(brief.decision_question, "What is driving " + currentLabel + " and what decision does it require?"),
        "What remains before this board packet can be released, who owns it, and what evidence is missing?",
        "Which governed cases create the largest recoverable value, and what should be acted on first?"
      ];
      gravityPanel.innerHTML = [
        '<div class="detail-head"><div><p class="detail-eyebrow">CEO agenda</p><h3 class="detail-title">Questions worth answering now</h3><p class="section-note">Each question opens the executive assistant with the relevant KPI, board approval stage or case already attached.</p></div></div>',
        '<div class="decision-question-grid">' + governedPrompts.map(function (prompt, index) {
          var labels = [currentLabel + ' drivers', 'Board release gate', 'Value at stake'];
          var kpiAttribute = index === 0 ? ' data-kpi-key="' + escapeHtml(String(firstDefined(driver.driver_key, driver.key, ""))) + '"' : '';
          return '<button class="decision-question-card" type="button" data-chat-prompt="' + escapeHtml(prompt) + '"' + kpiAttribute + '><span>' + escapeHtml(labels[index]) + '</span><strong>' + escapeHtml(prompt) + '</strong><small>Ask Hermes with this context →</small></button>';
        }).join('') + '</div>'
      ].join('');
      safeArray(gravityPanel.querySelectorAll("[data-chat-prompt]")).forEach(function (button) {
        button.onclick = function () { askAssistant(button.getAttribute("data-chat-prompt") || "", button); };
      });
      return;
      var vlogs = [
        { id: 'uTRKdCY4HdE', title: 'Enterprise AI Strategy and CEO Leadership', speaker: 'McKinsey & Company', theme: 'CEO leadership · enterprise AI strategy', dur: '~45 min', summary: 'CXOTalk #851: How CEOs should think about AI strategy, governance, and organizational alignment.', transcript: 'Full discussion on CEO-level AI strategy: moving from experimentation to enterprise-wide adoption, building AI governance frameworks, and aligning AI initiatives with business strategy.' },
        { id: 'sFSzPE2AOE0', title: 'Aligning AI with Enterprise Strategy', speaker: 'Leon Gordon, CEO at Onyx Data', theme: 'AI & data strategy alignment', dur: '~40 min', summary: 'How organizations can bridge the gap between AI capabilities and strategic goals.', transcript: 'Leon Gordon shares frameworks for aligning AI initiatives with enterprise strategy: data maturity assessment, capability mapping, and building a data-driven culture.' },
        { id: 'pQtdQ6AHn_Q', title: 'Agentic AI Governance and Enterprise-Scale Execution', speaker: 'Industry Panel', theme: 'governance · data quality · enterprise execution', dur: '~50 min', summary: 'Governance models for agentic AI systems, data quality requirements, and scaling patterns.', transcript: 'Panel discussion: agentic AI governance control frameworks, data quality pipelines, human-in-the-loop patterns, and scaling AI execution while maintaining compliance.' },
        { id: 't885M1WB1pg', title: 'Bridge Strategy and Execution with Decision-Ready Views', speaker: 'Strategy Execution Webinar', theme: 'strategy execution · decision-ready views', dur: '~35 min', summary: 'Creating decision-ready views that connect strategic plans to operational execution.', transcript: 'Building decision-ready dashboards, connecting plans to operations, and creating feedback loops that keep strategy alive.' }
      ];
      gravityPanel.innerHTML = [
        '<div class="detail-head"><div><h3 class="detail-title">Explore scenarios</h3><p class="section-note">Ask what-if questions on your live data</p></div></div>',
        '<div class="gravity-grid-v2"><section class="gravity-play-card">' + safeArray(gravity.prompts).slice(0, 3).map(function (prompt) { return '<button class="timeline-chip" type="button" data-chat-prompt="' + escapeHtml(prompt) + '"><strong>' + escapeHtml(prompt) + '</strong><span>Send to assistant</span></button>'; }).join('') + '</section><section class="leaders-card"><div class="leaders-badge">Leaders\' Corner</div><div class="leaders-title">Short counsel, senior practitioners</div><div class="leaders-featured"><div class="leaders-fallback-card" id="leaders-featured-fallback"><p class="leaders-fallback-icon">▶</p><p class="leaders-fallback-msg">Loading video...</p><p class="leaders-fallback-detail">' + escapeHtml(vlogs[0].title) + ' — ' + escapeHtml(vlogs[0].speaker) + '</p></div><div class="video-frame-wrapper" id="leaders-frame-wrapper" hidden><iframe id="leaders-featured-iframe" src="" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share; fullscreen" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen title=""></iframe></div></div><div class="leaders-video-info" id="leaders-video-info"><h4>' + escapeHtml(vlogs[0].title) + '</h4><p class="leaders-video-speaker">' + escapeHtml(vlogs[0].speaker) + '</p><span class="leaders-video-theme">' + escapeHtml(vlogs[0].theme) + '</span><p class="leaders-video-summary">' + escapeHtml(vlogs[0].summary) + '</p><details><summary>Summary</summary><p>' + escapeHtml(vlogs[0].transcript) + '</p></details><div class="leaders-video-ctas"><button class="leaders-hermes-cta" id="leaders-hermes-cta">Ask Hermes about this topic</button><button class="leaders-video-open" type="button">Watch in player</button><a class="leaders-yt-link" href="https://www.youtube.com/watch?v=' + escapeHtml(vlogs[0].id) + '" target="_blank" rel="noopener">Open on YouTube ↗</a></div></div>' +
        '<div class="leaders-thumb-grid" id="leaders-thumb-grid">' +
        vlogs.map(function (v, i) { return '<div class="leaders-thumb' + (i === 0 ? ' is-active' : '') + '" data-video-id="' + escapeHtml(v.id) + '" tabindex="0" role="button"><span class="leaders-thumb__img">▶</span><span class="leaders-thumb__title">' + escapeHtml(v.title) + '</span><span class="leaders-thumb__speaker">' + escapeHtml(v.speaker) + ' · ' + escapeHtml(v.dur) + '</span></div>'; }).join('') +
        '</div></section></div>'
      ].join("");
      safeArray(gravityPanel.querySelectorAll("[data-chat-prompt]")).forEach(function (button) {
        button.onclick = function () {
          askAssistant(button.getAttribute("data-chat-prompt") || "", button);
        };
      });
      var leadersCard = gravityPanel.querySelector('.leaders-card');
      // Wire inline thumbnail clicks
      safeArray(gravityPanel.querySelectorAll('.leaders-thumb')).forEach(function (thumb) {
        thumb.addEventListener('click', function () {
          var videoId = thumb.getAttribute('data-video-id') || '';
          var item = null;
          safeArray(vlogs).forEach(function (v) {
            if (v.id === videoId) item = v;
          });
          if (item) selectLeadersVideo(item, vlogs, leadersCard);
        });
      });
      var hermesCta = leadersCard && leadersCard.querySelector('#leaders-hermes-cta');
      if (hermesCta) {
        hermesCta.onclick = function () {
          var activeThumb = gravityPanel.querySelector('.leaders-thumb.is-active');
          var item = null;
          if (activeThumb) {
            var vid = activeThumb.getAttribute('data-video-id');
            safeArray(vlogs).forEach(function (v) {
              if (v.id === vid) item = v;
            });
          }
          if (!item) item = vlogs[0];
          if (item) {
            askAssistant('From the Leaders\' Corner video "' + item.title + '" — how does this apply to our strategy?', hermesCta);
          }
        };
      }
      // Initialize featured video on first load — switch from fallback card to embedded iframe player
      selectLeadersVideo(vlogs[0], vlogs, leadersCard);
    }
  }

  function selectLeadersVideo(item, vlogs, leadersCard) {
    if (!leadersCard) return;
    var fallback = leadersCard.querySelector('#leaders-featured-fallback');
    var frameWrapper = leadersCard.querySelector('#leaders-frame-wrapper');
    var iframe = leadersCard.querySelector('#leaders-featured-iframe');
    var info = leadersCard.querySelector('#leaders-video-info');
    var thumbGrid = leadersCard.querySelector('#leaders-thumb-grid');

    if (_leadersFallbackTimer) {
      window.clearTimeout(_leadersFallbackTimer);
      _leadersFallbackTimer = null;
    }
    if (frameWrapper) frameWrapper.hidden = false;
    if (iframe) {
      iframe.src = 'https://www.youtube-nocookie.com/embed/' + encodeURIComponent(item.id) + '?origin=' + encodeURIComponent(window.location.origin) + '&enablejsapi=1&rel=0&modestbranding=1';
      iframe.title = item.title;
      iframe.setAttribute('allow', 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share; fullscreen');
      iframe.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
      iframe.allowFullscreen = true;
    }
    if (fallback) {
      fallback.hidden = true;
      fallback.innerHTML = '<p class="leaders-fallback-icon">▶</p><p class="leaders-fallback-msg">Embed unavailable.</p><p class="leaders-fallback-detail">' + escapeHtml(item.title) + ' — ' + escapeHtml(item.speaker) + '</p><div class="leaders-fallback-actions"><button class="leaders-fallback-watch" type="button">Watch in player</button><a class="leaders-fallback-link" href="https://www.youtube.com/watch?v=' + escapeHtml(item.id) + '" target="_blank" rel="noopener">Open on YouTube ↗</a></div>';
      var watchBtn = fallback.querySelector('.leaders-fallback-watch');
      if (watchBtn) {
        watchBtn.onclick = function () {
          openVideoModal(item);
        };
      }
    }

    if (info) {
      info.innerHTML = '<h4>' + escapeHtml(item.title) + '</h4><p class="leaders-video-speaker">' + escapeHtml(item.speaker) + '</p><span class="leaders-video-theme">' + escapeHtml(item.theme) + '</span><p class="leaders-video-summary">' + escapeHtml(item.summary) + '</p><details><summary>Summary</summary><p>' + escapeHtml(item.transcript) + '</p></details><div class="leaders-video-ctas"><button class="leaders-hermes-cta" id="leaders-hermes-cta">Ask Hermes about this topic</button><button class="leaders-video-open" type="button">Watch in player</button><a class="leaders-yt-link" href="https://www.youtube.com/watch?v=' + escapeHtml(item.id) + '" target="_blank" rel="noopener">Open on YouTube ↗</a></div>';
      var hermesCta = info.querySelector('#leaders-hermes-cta');
      if (hermesCta) {
        hermesCta.onclick = function () {
          askAssistant('From the Leaders\' Corner video "' + item.title + '" — how does this apply to our strategy?', hermesCta);
        };
      }
      var openBtn = info.querySelector('.leaders-video-open');
      if (openBtn) {
        openBtn.onclick = function () {
          openVideoModal(item);
        };
      }
    }

    if (thumbGrid) {
      safeArray(leadersCard.querySelectorAll('.leaders-thumb')).forEach(function (thumb) {
        var vid = thumb.getAttribute('data-video-id');
        if (vid === item.id) {
          thumb.classList.add('is-active');
        } else {
          thumb.classList.remove('is-active');
        }
      });
    }
  }

  function buildVideoModalHtml(item) {
    return [
      '<div class="video-modal-scrim" id="video-modal-scrim">',
      '<div class="video-modal" role="dialog" aria-modal="true" aria-label="Video: ' + escapeHtml(item.title) + '">',
      '<button class="video-modal-close" aria-label="Close video">×</button>',
      '<div class="video-frame-wrapper">',
      '<iframe id="video-modal-iframe" src="https://www.youtube-nocookie.com/embed/' + escapeHtml(item.id) + '?origin=' + encodeURIComponent(window.location.origin) + '&enablejsapi=1&rel=0&modestbranding=1"',
      'frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share; fullscreen" referrerpolicy="strict-origin-when-cross-origin"',
      'allowfullscreen title="' + escapeHtml(item.title) + '"></iframe>',
      '</div>',
      '<div class="video-modal-body">',
      '<h3>' + escapeHtml(item.title) + '</h3>',
      '<p class="video-modal-speaker">' + escapeHtml(item.speaker) + '</p>',
      '<span class="video-modal-theme">' + escapeHtml(item.theme) + '</span>',
      '<p class="video-modal-summary">' + escapeHtml(item.summary) + '</p>',
      '<details>',
      '<summary>Summary</summary>',
      '<p>' + escapeHtml(item.transcript) + '</p>',
      '</details>',
      '<button class="video-modal-cta" id="video-hermes-cta">Ask Hermes about this topic</button>',
      '<div class="video-fallback" id="video-fallback" hidden>',
      '<p>Embed unavailable</p>',
      '<a class="video-fallback-link" href="https://www.youtube.com/watch?v=' + escapeHtml(item.id) + '" target="_blank" rel="noopener">Open on YouTube ↗</a>',
      '</div>',
      '</div>',
      '</div>',
      '</div>'
    ].join("");
  }

  function closeVideoModal() {
    var scrim = $("video-modal-scrim");
    if (scrim) scrim.remove();
    state.videoModalOpen = false;
    document.removeEventListener("keydown", _videoModalKeydown);
  }

  var _videoModalKeydown = null;

  function openVideoModal(item) {
    /* Guard: surfaces must not overlap — close assistant drawer before opening video modal */
    if (state.drawerOpen) _closeHermesDrawer();
    closeVideoModal();
    state.videoModalOpen = true;
    var html = buildVideoModalHtml(item);
    var wrapper = document.createElement("div");
    wrapper.innerHTML = html;
    var scrim = wrapper.firstChild;
    document.body.appendChild(scrim);

    var closeBtn = scrim.querySelector(".video-modal-close");
    var hermesCta = scrim.querySelector("#video-hermes-cta");
    var fallbackEl = scrim.querySelector("#video-fallback");
    var iframe = scrim.querySelector("#video-modal-iframe");
    var fallbackTimer = null;

    scrim.onclick = function (event) {
      if (event.target === scrim) closeVideoModal();
    };

    if (closeBtn) {
      closeBtn.onclick = function () { closeVideoModal(); };
      closeBtn.focus();
    }

    if (hermesCta) {
      hermesCta.onclick = function () {
        askAssistant('From the Leaders\' Corner video "' + item.title + '" — how does this apply to our strategy?', hermesCta);
        closeVideoModal();
      };
    }

    _videoModalKeydown = function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        closeVideoModal();
      }
    };
    document.addEventListener("keydown", _videoModalKeydown);

    if (iframe && fallbackEl) {
      fallbackTimer = window.setTimeout(function () {
        fallbackEl.hidden = false;
      }, 10000);

      iframe.addEventListener("load", function () {
        if (fallbackTimer) {
          window.clearTimeout(fallbackTimer);
          fallbackTimer = null;
        }
        fallbackEl.hidden = true;
      });
    }
  }

  var _boardStateRowDelegatedBound = false;
  function _ensureBoardStateRowDelegated() {
    if (_boardStateRowDelegatedBound) return;
    _boardStateRowDelegatedBound = true;
    var row = $("board-state-row");
    if (!row) return;
    row.addEventListener('click', function (event) {
      if (event._boardTabHandled) return;
      event._boardTabHandled = true;
      var target = event && event.target;
      if (!target) return;
      // Primary path: closest('[data-board-state]') walks up the DOM tree
      // from the clicked element to find the tab button. In a real browser
      // event, the target could be any nested element inside the button
      // (e.g. <strong> or <span>), and closest walks up from there.
      var tabBtn = null;
      if (typeof target.closest === 'function') {
        tabBtn = target.closest('[data-board-state]');
        if (tabBtn && !row.contains(tabBtn)) tabBtn = null;
      }
      // Fallback 1: the target element IS a button with data-board-state
      // (covers the case where closest is unavailable or returns null).
      if (!tabBtn && target.tagName === 'BUTTON' && target.getAttribute && target.getAttribute('data-board-state')) {
        tabBtn = target;
      }
      if (!tabBtn) {
        // Fallback 2: querySelector on the target itself (covers the case
        // where the target contains a data-board-state element but the
        // event does not bubble from it — e.g. a synthetic event).
        if (typeof target.querySelector === 'function') {
          var qs = target.querySelector('[data-board-state]');
          if (qs && row.contains(qs)) tabBtn = qs;
        }
      }
      if (tabBtn && row.contains(tabBtn)) {
        event.preventDefault();
        event.stopPropagation();
        var stateVal = tabBtn.getAttribute('data-board-state') || '';
        if (stateVal) activateBoardState(stateVal);
      }
    });
  }

  var _boardStateObserverAttached = false;
  function _ensureBoardStateObserver() {
    if (_boardStateObserverAttached) return;
    var row = $("board-state-row");
    if (!row) return;
    if (typeof window.MutationObserver !== 'function') return;
    _boardStateObserverAttached = true;
    var observer = new window.MutationObserver(function () {
      // Guard 1: skip if a syncBoardStateTabUI call is currently in-flight.
      // Without this guard, the observer would try to re-sync while the sync
      // function is still setting attributes on buttons, causing a re-entrant
      // call that triggers yet another observer callback → infinite loop.
      if (_boardStateObserverSyncing) return;
      var desiredState = state.activeBoard || resolveBoardState();
      if (!desiredState) return;
      // Guard 2: actual mismatch check — only sync if there's a real DOM
      // state mismatch. This is checked BEFORE the last-synced guard so that
      // CSSOM recalc reverts (which cause a mismatch even when desiredState
      // matches _boardStateLastSynced) can still be fixed by the observer.
      // The retry counter below prevents infinite CSSOM recalc loops.
      if (!boardStateTabUIMismatch(desiredState)) {
        _boardStateSyncRetryCount = 0;
        return;
      }
      // Guard 3: CSSOM recalc loop detection. If the desired state matches
      // the last synced state but there IS a DOM mismatch (caught by guard 2),
      // Chrome's CSSOM recalc from a sibling innerHTML replacement has
      // reverted className on the tab buttons. Allow up to MAX_RETRIES
      // re-syncs to fix the revert, then yield to the higher-level render
      // cycle (activateBoardState, renderBoardPortal multi-timing chain)
      // which will re-assert the correct state on the next timing callback.
      if (desiredState === _boardStateLastSynced) {
        _boardStateSyncRetryCount++;
        if (_boardStateSyncRetryCount > BOARD_STATE_OBSERVER_MAX_RETRIES) {
          return;
        }
      } else {
        _boardStateSyncRetryCount = 0;
      }
      syncBoardStateTabUI(desiredState);
    });
    observer.observe(row, { childList: true, subtree: true, attributes: true, attributeFilter: ['aria-selected', 'class'] });
  }

  function renderBoardStateTabs() {
    var row = $("board-state-row");
    var board = getBoardPortal();
    var modes = safeArray(board.lifecycle_flow).length ? safeArray(board.lifecycle_flow) : (((state.latestPacket || {}).executive_modes || {}).board_states || []);
    var note = $("board-state-note");
    var activeBoardState = resolveBoardState();
    var boardPublication = getPublication();
    var boardStateReleased = Boolean((boardPublication.reconciliation || {}).publish_gate_passed) && /^(approved|published|released|frozen)$/.test(String(firstDefined(boardPublication.publish_state, "")).toLowerCase());
    var boardStateNote = state.activePersona === "board" && !boardStateReleased
      ? "No packet content is available until the CEO release decision is recorded."
      : firstDefined(boardStateSupportNote(board), "Board lifecycle stays explicit from pre-board preparation through frozen close.");
    if (!row) return;
    if (row.style) row.style.display = state.activePersona === "board" && !boardStateReleased ? "none" : "";
    _ensureBoardStateRowDelegated();
    _ensureBoardStateObserver();
    // Sync existing buttons: update attributes in-place for fast state change.
    // Only destroy and recreate when the mode list changes (rare — server packet).
    var existingByState = {};
    safeArray(row.querySelectorAll('[data-board-state]')).forEach(function (b) {
      var s = String(b.getAttribute('data-board-state') || '').trim().toLowerCase();
      if (s) existingByState[s] = b;
    });
    var modeStates = safeArray(modes).map(function (mode) {
      return String(firstDefined(mode.state_id, mode.id, mode.key, '')).trim().toLowerCase();
    }).filter(function (s) { return s; });
    var modeSet = {};
    modeStates.forEach(function (s) { modeSet[s] = true; });
    // Fast path: mode list unchanged — just update attributes, no DOM rebuild.
    var listsMatch = Object.keys(existingByState).length === modeStates.length;
    if (listsMatch) {
      for (var k in existingByState) {
        if (!modeSet[k]) { listsMatch = false; break; }
      }
    }
    if (listsMatch) {
      // Update existing buttons to reflect the active state.
      // This avoids the innerHTML destroy-recreate cycle entirely.
      row.querySelectorAll('[data-board-state]').forEach(function (button) {
        var bs = String(button.getAttribute('data-board-state') || '').trim().toLowerCase();
        var isActive = bs === activeBoardState;
        button.className = 'state-tab' + (isActive ? ' is-active' : '');
        button.setAttribute('aria-selected', isActive ? 'true' : 'false');
        button.setAttribute('data-board-state-active', isActive ? 'true' : 'false');
        if (button.style) button.style.background = isActive ? 'var(--accent-soft)' : 'transparent';
        // Belt-and-suspenders: add a direct click handler in the fast path too.
        // The delegated handler on board-state-row is the primary dispatch, but
        // individual button handlers survive DOM reparenting and CSSOM thrash.
        // Use a flag to avoid double-binding (the slow path already attaches).
        if (!button.__boardTabHandlerAttached) {
          button.__boardTabHandlerAttached = true;
          (function (boundState) {
            button.addEventListener('click', function (event) {
              if (event._boardTabHandled) return;
              event._boardTabHandled = true;
              event.preventDefault();
              event.stopPropagation();
              var el = event.currentTarget || event.target;
              var stateAttr = String(el && typeof el.getAttribute === 'function' ? el.getAttribute('data-board-state') : boundState).trim().toLowerCase();
              if (!stateAttr) stateAttr = boundState;
              activateBoardState(stateAttr);
            });
          })(bs);
        }
      });
      if (note) note.textContent = boardStateNote;
      return;
    }
    // Slow path: mode list changed — full DOM rebuild.
    row.innerHTML = "";
    safeArray(modes).forEach(function (mode) {
      var modeState = String(firstDefined(mode.state_id, mode.id, mode.key, '')).trim().toLowerCase();
      if (!modeState) return;
      var button = document.createElement("button");
      button.type = "button";
      button.className = "state-tab" + (modeState === activeBoardState ? " is-active" : "");
      button.setAttribute('data-board-state', modeState);
      button.setAttribute('data-board-state-active', modeState === activeBoardState ? 'true' : 'false');
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", modeState === activeBoardState ? "true" : "false");
      button.innerHTML = '<span class="state-tab__copy"><strong>' + escapeHtml(firstDefined(mode.label, mode.state_id)) + '</strong><span>' + escapeHtml(firstDefined(mode.summary, mode.detail, "")) + '</span></span>';
      // Capture modeState in closure so the handler does not depend on DOM
      // attributes that may be destroyed during innerHTML replacement in
      // renderBoardStateTabs. This is the state the button was CREATED with,
      // regardless of DOM mutations during the render cycle.
      (function (boundState) {
        button.addEventListener('click', function (event) {
          // Individual handler: prevent double-dispatch. The delegated handler
          // on board-state-row is the primary path; this is a backstop.
          if (event._boardTabHandled) return;
          event._boardTabHandled = true;
          event.preventDefault();
          event.stopPropagation();
          var el = event.currentTarget || event.target;
          var stateAttr = String(el && typeof el.getAttribute === 'function' ? el.getAttribute('data-board-state') : boundState).trim().toLowerCase();
          if (!stateAttr) stateAttr = boundState;
          activateBoardState(stateAttr);
        });
      })(modeState);
      row.appendChild(button);
    });
    if (note) note.textContent = boardStateNote;
  }

  function renderBoardPortal() {
    var board = getBoardPortal();
    var publication = getPublication();
    var reconciliation = publication.reconciliation || {};
    var portal = $("board-portal");
    var note = $("board-note");
    if (note) note.textContent = firstDefined(board.governance_note, "Board-safe lifecycle, materials, and context.");
    if (!portal) return;

    var decks = safeArray(board.decks).slice(0, 4);
    var actions = safeArray(board.actions).slice(0, 3);
    var questions = safeArray(safeArray(board.supplementary_questions).length ? board.supplementary_questions : board.supplementary).slice(0, 3);
    var deckRelease = board.deck_release || {};
    var snapshot = board.frozen_snapshot || {};
    var boardState = resolveBoardState();
    var stateDetail = boardStateDetailForRender(boardState, board);
    var lifecycle = boardLifecycleForRender(boardState, board);
    var livePrompts = safeArray(safeArray(board.live_prompts).length ? board.live_prompts : board.livePrompts);
    var boardReleased = Boolean(reconciliation.publish_gate_passed) && /^(approved|published|released|frozen)$/.test(String(firstDefined(publication.publish_state, "")).toLowerCase());
    if (state.activePersona === "board" && !boardReleased) {
      if (note) note.textContent = "This packet has not been released to the Board Room.";
      portal.innerHTML = '<div class="board-release-hold"><p class="detail-eyebrow">Release gate</p><h3 class="board-title">Packet awaiting CEO release</h3><p class="board-copy">No live diagnostics, working evidence, or pre-board figures are visible in Board Room. The approved packet will appear here only after the governed release decision is recorded.</p><span class="pill-inline warn">Not released</span></div>';
      return;
    }
    var stateSpecific = '';
    if (boardState === 'pre') {
      stateSpecific = '<div class="board-mode-grid"><section class="board-panel"><p class="detail-eyebrow">CEO-approved material</p><div class="mini-list">' + (decks.length ? decks.map(function (item) {
        return '<div class="board-deck"><div><strong>' + escapeHtml(firstDefined(item.title, 'Deck')) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(item.by, item.tag, 'Board material')) + '</p></div><span class="pill-inline ' + toneClass(item.status) + '">' + escapeHtml(firstDefined(item.status, item.pages ? item.pages + ' pages' : 'ready')) + '</span></div>';
      }).join('') : '<div class="discovery-empty">No board material is released yet.</div>') + '</div></section><section class="board-panel"><p class="detail-eyebrow">Supplementary questions</p><div class="mini-list">' + (questions.length ? questions.map(function (item) {
        return '<div class="board-deck"><div><strong>' + escapeHtml(firstDefined(item.q, 'Question')) + '</strong><p class="list-copy">to ' + escapeHtml(firstDefined(item.to, 'board lane')) + '</p></div><span class="pill-inline ' + toneClass(item.status) + '">' + escapeHtml(firstDefined(item.status, 'board')) + '</span></div>';
      }).join('') : '<div class="discovery-empty">No supplementary questions are attached to this lifecycle state.</div>') + '</div></section></div>';
    } else if (boardState === 'live') {
      stateSpecific = '<div class="board-live-card"><div class="board-live-card__head"><strong>Live session · Q&amp;A on approved material</strong><span>' + escapeHtml(assistantNameForState()) + ' answers only from the CEO-approved material</span></div><div class="board-live-card__status"><span class="live-pulse"></span><strong>In session</strong><span>' + escapeHtml(firstDefined((board.meeting || {}).title, 'Board meeting')) + '</span></div><div class="pill-row">' + (livePrompts.length ? livePrompts : ['Why is EBITDA 20 bps under plan?', 'Show the hedge downside', 'Is the JV funded from cash?']).map(function (prompt) { return '<button class="prompt-chip" type="button" data-board-prompt="' + escapeHtml(prompt) + '">' + escapeHtml(prompt) + '</button>'; }).join('') + '</div></div>';
    } else {
      stateSpecific = '<div class="board-mode-grid"><section class="board-panel"><p class="detail-eyebrow">Meeting summary &amp; action plan</p><p class="board-copy">' + escapeHtml(firstDefined(board.summary, snapshot.summary, 'Closed meetings retain a bounded frozen snapshot.')) + '</p><div class="mini-list">' + (actions.length ? actions.map(function (item) {
        return '<div class="board-action"><div><strong>' + escapeHtml(firstDefined(item.item, 'Action')) + '</strong><small>' + escapeHtml(firstDefined(item.owner, 'Owner')) + '</small></div><span class="pill-inline warn">' + escapeHtml(firstDefined(item.due, 'next')) + '</span></div>';
      }).join('') : '<div class="discovery-empty">No closed-state actions are attached yet.</div>') + '</div></section><section class="board-panel frozen-panel"><p class="detail-eyebrow">Frozen snapshot</p><strong>' + escapeHtml(humanizeToken(firstDefined(snapshot.status, 'frozen'))) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(snapshot.summary, 'Between meetings, the board room only sees the frozen snapshot.')) + '</p><button class="timeline-chip" type="button" data-board-prompt="Model a what-if on the frozen board snapshot: if EUR strengthens 5%, what was the hedged outcome?"><strong>◇ What-if on the snapshot</strong><span>No live org data reaches the board</span></button></section></div>';
    }
    portal.innerHTML = [
      '<div class="board-head"><div><p class="detail-eyebrow">Reports</p><h3 class="board-title">' + escapeHtml(firstDefined(stateDetail.title, board.state_label, "Board status")) + '</h3><p class="board-copy">' + escapeHtml(firstDefined(stateDetail.summary, board.board_summary, "Board posture stays bounded to the current view.")) + '</p></div><div class="board-head__badges"><span class="pill-inline ' + toneClass(statusLabel(boardState)) + '">' + escapeHtml(statusLabel(boardState)) + '</span><span class="pill-inline ' + (reconciliation.publish_gate_passed ? 'ok' : 'warn') + '">' + (reconciliation.publish_gate_passed ? 'Reconciled ✓' : 'Release blocked ⚠') + '</span></div></div>',
      '<div class="board-kpis">' + safeArray(board.kpis).slice(0, 4).map(function (item) {
        return '<div class="board-kpi"><span class="board-kpi__label">' + escapeHtml(firstDefined(item.label, "Metric")) + '</span><strong class="board-kpi__value">' + escapeHtml(firstDefined(item.value, item.pct, "—")) + '</strong><span class="board-kpi__sub">' + escapeHtml(firstDefined(item.sub, item.pct ? String(item.pct) + "%" : "Board data")) + '</span>' + groundingBadgeMarkup(item.provenance, item.grounding) + '</div>';
      }).join("") + '</div>',
      '<div class="board-state-stack">' + lifecycle.map(function (item) {
        var flags = [];
        if (item.actual) flags.push('<span class="pill-inline ok">actual</span>');
        if (item.presented) flags.push('<span class="pill-inline warn">presented</span>');
        if (item.next_action && item.presented) flags.push('<button type="button" class="pill-inline board-status-chip board-status-chip--action" data-board-action="' + escapeHtml(String(item.next_action)) + '" aria-label="Ask Hermes what to do next: ' + escapeHtml(boardActionLabel(item.next_action)) + '" title="Ask Hermes what to do next: ' + escapeHtml(boardActionLabel(item.next_action)) + '">Next: ' + escapeHtml(boardActionLabel(item.next_action)) + '</button>');
        return '<div class="lifecycle-step' + (item.presented ? ' is-presented' : '') + '"><div><strong>' + escapeHtml(firstDefined(item.label, item.state_id, 'State')) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(item.detail, 'Board posture.')) + '</p></div><div class="lifecycle-step__flags">' + flags.join('') + '</div></div>';
      }).join("") + '</div>',
      '<div class="snapshot-grid"><div class="snapshot-card" data-snapshot="deck" title="Click for details"><strong>Deck release</strong><span>' + escapeHtml(statusLabel(firstDefined(deckRelease.status, 'pending'))) + '</span><span class="panel-note">' + escapeHtml(String(firstDefined(deckRelease.report_count, 0)) + ' surfaced report(s)' + (state.activePersona !== "ceo" ? ' \u00b7 ' + firstDefined(deckRelease.preview_route, '/public/runs/latest/report-preview') : '')) + '</span></div><div class="snapshot-card" data-snapshot="frozen" title="Click for details"><strong>Frozen snapshot</strong><span>' + escapeHtml(statusLabel(firstDefined(snapshot.status, 'frozen'))) + '</span><span class="panel-note">' + escapeHtml(firstDefined(snapshot.summary, 'Closed meetings retain a bounded frozen snapshot.')) + '</span></div></div>',
      (state.activePersona === "ceo"
        ? '<div class="board-action-grid">' + safeArray(stateDetail.primary_actions).slice(0, 2).map(function (item) {
            return '<button class="assistant-tool-chip assistant-tool-chip--button" type="button" data-board-action="' + escapeHtml(String(item)) + '" aria-label="Ask Hermes to review ' + escapeHtml(humanizeToken(item)) + '" title="Ask Hermes to review ' + escapeHtml(humanizeToken(item)) + '">Review: ' + escapeHtml(humanizeToken(item)) + '</button>';
          }).join("") + '</div>'
        : '<div class="board-action-grid">' + safeArray(stateDetail.primary_actions).slice(0, 2).concat(safeArray(stateDetail.secondary_actions).slice(0, 2)).map(function (item) {
        return '<button class="assistant-tool-chip assistant-tool-chip--button" type="button" data-board-action="' + escapeHtml(String(item)) + '" aria-label="Ask Hermes to review ' + escapeHtml(humanizeToken(item)) + '" title="Ask Hermes to review ' + escapeHtml(humanizeToken(item)) + '">' + escapeHtml(humanizeToken(item)) + '</button>';
      }).join("") + '</div>'),
      '<div class="board-detail-grid"><section class="board-panel"><p class="detail-eyebrow">Meeting posture</p><div class="mini-list"><div class="board-deck"><div><strong>' + escapeHtml(firstDefined((board.meeting || {}).design_title, (board.meeting || {}).title, "Board meeting")) + '</strong><p class="list-copy">' + escapeHtml(firstDefined((board.meeting || {}).date, (board.meeting || {}).when, "Board timing pending")) + '</p></div><span class="pill-inline ok">' + escapeHtml(firstDefined((board.meeting || {}).room, "board-safe")) + '</span></div></div></section><section class="board-panel"><p class="detail-eyebrow">Lifecycle actions</p><div class="mini-list">' + (actions.length ? actions.map(function (item) {
        return '<div class="board-action"><div><strong>' + escapeHtml(firstDefined(item.item, "Action")) + '</strong><small>' + escapeHtml(firstDefined(item.owner, "Owner")) + '</small></div><span class="pill-inline warn">' + escapeHtml(firstDefined(item.due, "next")) + '</span></div>';
      }).join("") : '<div class="discovery-empty">No lifecycle actions are attached to this state.</div>') + '</div></section></div>',
      stateSpecific
    ].join("");
    // Post-innerHTML re-sync: portal.innerHTML replacement triggers CSSOM
    // recalc which can discard className and inline style attributes on
    // tab buttons outside the portal. Re-assert the intended tab state
    // immediately after the layout is invalidated, then again after the
    // paint cycle (rAF) and at several setTimeout intervals so that any
    // Chrome CSSOM recalc or competing async re-render (e.g. refresh()
    // completing after a delayed server response) does not discard the
    // triple-redundant style guards.
    // Use renderBoardStateTabs (full structural re-render with fast-path
    // attribute sync) BEFORE the lighter syncBoardStateTabUI so that the
    // fast path re-sets every button attribute and re-adds click handlers
    // if needed. Then syncBoardStateTabUI provides the triple-redundant
    // attribute-level fallback. This order ensures CSSOM recalc from
    // innerHTML cannot leave a stale className without the fast-path
    // re-render correcting it in the same synchronous window.
    renderBoardStateTabs();
    syncBoardStateTabUI(resolveBoardState());
    // Multi-timing re-sync: each callback RE-READS resolveBoardState() so that a
    // stale snapshot from a competing chain (e.g. switchView's _switchViewReSync)
    // that fires between timing callbacks does not revert the UI.
    // Includes a 1000ms catch-all for any deferred async render completion.
    function _boardPortalReSync() {
      renderBoardStateTabs();
      syncBoardStateTabUI(resolveBoardState());
    }
    if (typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(_boardPortalReSync);
    }
    if (typeof window.setTimeout === 'function') {
      window.setTimeout(_boardPortalReSync, 0);
      window.setTimeout(_boardPortalReSync, 50);
      window.setTimeout(_boardPortalReSync, 250);
      window.setTimeout(_boardPortalReSync, 1000);
      // 5000ms catch-all: deeply deferred CSSOM recalc or competing render.
      window.setTimeout(_boardPortalReSync, 5000);
    }
    // Re-bind the delegated click handler on every render so that
    // innerHTML replacement does not lose event coverage. The portal's
    // delegated handler survives innerHTML replacement, but re-binding
    // on each render defensively captures any timing or CSSOM edge case.
    bindBoardPortalInteractions(portal);
    // Individual click handlers provide a second backstop path per button,
    // mirroring the hero-prompt pattern (button.onclick) which has been
    // verified to work in all deployed environments. This redundancy
    // covers edge cases where the delegated bubble is intercepted,
    // the target.closest() fallback fails in a specific DOM state, or
    // the portal's single-event-listener guard was set on a prior render
    // but the content was replaced.
    // IMPORTANT: gate individual onclick handlers with a _boardPromptHandled
    // flag so the delegated handler (portal.__boardPortalHandler, which fires
    // first during bubble) and this individual onclick do not both invoke
    // askAssistant, causing duplicate /assistant/chat POSTs and duplicate
    // drawer messages.
    safeArray(portal.querySelectorAll('[data-board-prompt]')).forEach(function (button) {
      button.onclick = function (event) {
        if (event._boardPromptHandled) return;
        event._boardPromptHandled = true;
        event.preventDefault();
        activateBoardPrompt(button.getAttribute('data-board-prompt') || '', button);
      };
    });
    safeArray(portal.querySelectorAll('[data-board-action]')).forEach(function (button) {
      button.onclick = function (event) {
        if (event._boardPromptHandled) return;
        event._boardPromptHandled = true;
        event.preventDefault();
        activateBoardAction(button.getAttribute('data-board-action') || '', getBoardPortal(), button);
      };
    });
    safeArray(portal.querySelectorAll('.snapshot-card')).forEach(function (card) {
      card.style.cursor = 'pointer';
      card.onclick = function () {
        var label = card.querySelector('strong') ? card.querySelector('strong').textContent : '';
        showToast((label ? label + ' detail is ' : '') + 'available from the operator surface.');
      };
    });
  }

  function assistantNameForState() {
    var persona = getPersonaContract(state.activePersona);
    var blueprint = getPersonaBlueprint(state.activePersona);
    return firstDefined((getChatContract().assistant || {}).name, persona.assistant, blueprint.assistant, 'Hermes');
  }

  function renderLowerRailFidelity() {
    var blueprint = getPersonaBlueprint(state.activePersona);
    var diagnostics = getExecutiveDiagnostics();
    var sections = diagnostics.sections || {};
    var liveGovernedMode = diagnostics.mode === "live" && ["database", "governed_artifacts"].indexOf(diagnostics.source) >= 0;
    var lowerRail = (getExecutiveDiagnostics().composition || {}).lower_rail || getDrilldown().lower_rail || {};
    var findingsPanel = $("findings-panel");
    var developmentsPanel = $("developments-panel");
    var weekPanel = $("week-panel");
    var findingsSection = sections.findings || {};
    var developmentsSection = sections.developments || {};
    var weekSection = sections.week_ahead || {};
    var primaryFindings = safeArray(findingsSection.items).length ? safeArray(findingsSection.items).slice(0, 3) : safeArray(blueprint.findings).slice(0, 3);
    var caseIndex = safeArray(findingsSection.case_index).length ? safeArray(findingsSection.case_index) : primaryFindings;
    var selectedFinding = caseIndex.find(function (item) {
      return String(firstDefined(item && item.finding_id, '')) === String(state.selectedFindingId || '');
    });
    var selectedOutsidePrimary = selectedFinding && !primaryFindings.some(function (item) {
      return String(firstDefined(item && item.finding_id, '')) === String(state.selectedFindingId || '');
    });
    var findings = selectedOutsidePrimary
      ? [selectedFinding].concat(primaryFindings.filter(function (item) {
          return String(firstDefined(item && item.finding_id, '')) !== String(state.selectedFindingId || '');
        }).slice(0, 2))
      : primaryFindings;
    var developments = liveGovernedMode
      ? safeArray(developmentsSection.items).slice(0, 3)
      : (safeArray(blueprint.developments).length ? safeArray(blueprint.developments).slice(0, 3) : safeArray(lowerRail.developments).slice(0, 3));
    var weekAhead = liveGovernedMode
      ? safeArray(weekSection.items).slice(0, 3)
      : (safeArray(blueprint.week).length ? safeArray(blueprint.week).slice(0, 3) : safeArray(lowerRail.week_ahead).slice(0, 3));
    var reconciliation = findingsSection.reconciliation || getSharedAssistantContext().findings_reconciliation || {};
    var displayedRecoverable = selectedOutsidePrimary
      ? findings.reduce(function (total, item) { return total + (Number(item && item.recoverable_sar) || 0); }, 0)
      : (Number(firstDefined(reconciliation.displayed_recoverable_sar, 0)) || 0);
    var totalRecoverable = Number(firstDefined(reconciliation.total_recoverable_sar, displayedRecoverable)) || displayedRecoverable;
    var remainingRecoverable = Math.max(0, totalRecoverable - displayedRecoverable);
    var totalFindingCount = Number(firstDefined(reconciliation.total_finding_count, findings.length)) || findings.length;
    var displayedFindingCount = Number(firstDefined(reconciliation.displayed_finding_count, findings.length)) || findings.length;
    var reconciliationHtml = '';
    if (totalFindingCount > displayedFindingCount || remainingRecoverable > 0) {
      reconciliationHtml = '<div class="rail-reconcile"><span>Showing ' + escapeHtml(String(displayedFindingCount)) + ' of ' + escapeHtml(String(totalFindingCount)) + ' cases: ' + escapeHtml(formatSar(displayedRecoverable)) + '</span>' + (remainingRecoverable > 0 ? '<span>' + escapeHtml(String(totalFindingCount - displayedFindingCount)) + ' other governed cases: ' + escapeHtml(formatSar(remainingRecoverable)) + '</span>' : '') + '<strong>Total recoverable value: ' + escapeHtml(formatSar(totalRecoverable)) + '</strong></div>';
    }
    var renderToggleList = function (items, kind) {
      return items.map(function (item, index) {
        var findingId = kind === 'finding' ? String(firstDefined(item.finding_id, '')) : '';
        var key = kind + ':' + (findingId || index);
        var open = state.openDriverNoteKey === key;
        var actionPrompt = kind === 'development'
          ? 'Project the impact of “' + firstDefined(item.title, 'this development') + '” on the current plan and what I should prepare for the board.'
          : 'Explain why “' + firstDefined(item.title, 'this finding') + '” matters for the board review and what action I should consider.';
        var actionLabel = kind === 'development' ? 'Project impact on plan' : 'Ask why this matters';
        return '<button type="button" class="rail-toggle' + (open ? ' is-open' : '') + '" data-rail-toggle="' + escapeHtml(key) + '"' + (findingId ? ' data-finding-id="' + escapeHtml(findingId) + '"' : '') + ' aria-expanded="' + (open ? 'true' : 'false') + '"><span class="rail-toggle__copy"><strong>' + escapeHtml(firstDefined(item.title, kind === 'finding' ? 'Finding' : 'Development')) + '</strong><span>' + escapeHtml(firstDefined(kind === 'finding' ? item.tag : item.meta, kind === 'finding' ? 'signal' : 'update')) + '</span></span><span class="rail-toggle__plus">' + (open ? '−' : '+') + '</span></button>' + (open ? '<div class="rail-toggle__detail">' + escapeHtml(firstDefined(kind === 'finding' ? item.detail : item.impact, item.detail, 'Awaiting detail.')) + '<div class="rail-toggle__actions"><button type="button" class="rail-inline-action" data-rail-prompt="' + escapeHtml(actionPrompt) + '">' + escapeHtml(actionLabel) + '</button></div></div>' : '');
      }).join('');
    };

    if (findingsPanel) {
      findingsPanel.innerHTML = '<div class="detail-head"><div><h3 class="detail-title">Findings &amp; concerns</h3></div></div><div class="rail-toggle-list">' + renderToggleList(findings, 'finding') + '</div>' + reconciliationHtml;
    }

    if (developmentsPanel) {
      developmentsPanel.hidden = liveGovernedMode && !developments.length;
      developmentsPanel.innerHTML = developments.length
        ? '<div class="detail-head"><div><h3 class="detail-title">Developments since you were here</h3></div></div><div class="rail-toggle-list">' + renderToggleList(developments, 'development') + '</div>'
        : '';
    }

    if (weekPanel) {
      weekPanel.hidden = false;
      var openIndex = Math.min(state.openWeekIndex || 0, Math.max(weekAhead.length - 1, 0));
      var activeEvent = weekAhead[openIndex] || null;
      weekPanel.innerHTML = weekAhead.length ? '<div class="detail-head"><div><h3 class="detail-title">CEO agenda</h3></div></div><div class="week-rail-v2">' + weekAhead.map(function (item, index) {
        return '<button class="event-chip' + (index === openIndex ? ' is-open' : '') + (item.urgent ? ' urgent' : '') + '" type="button" data-week-index="' + index + '"><span class="event-day">' + escapeHtml(firstDefined(item.day, '')) + '</span><span class="event-title">' + escapeHtml(firstDefined(item.title, item.label, 'Event')) + '</span><span class="event-when">' + escapeHtml(firstDefined(item.when, item.detail, 'soon')) + '</span></button>';
      }).join('') + '</div>' + (activeEvent ? '<div class="prep"><div class="prep-head"><span class="prep-flag">prep</span> ' + escapeHtml(firstDefined(activeEvent.title, 'Event')) + ' · ' + escapeHtml(firstDefined(activeEvent.when, 'soon')) + '</div><p class="prep-body">' + escapeHtml(firstDefined(activeEvent.prep, activeEvent.foot, '')) + '</p><div class="prep-actions"><button class="timeline-chip" type="button" data-chat-prompt="Open thinking mode for ' + escapeHtml(firstDefined(activeEvent.title, 'this event')) + ': model the options and what I should walk in having decided."><strong>Explore scenarios</strong></button><button class="timeline-chip" type="button" data-chat-prompt="For ' + escapeHtml(firstDefined(activeEvent.title, 'this event')) + ', what data am I missing and who should I request it from?"><strong>Request missing data</strong></button></div><form class="chips-own chips-own--rail" id="week-composer"><label class="sr-only" for="week-input">Ask StrategyOS to prepare something for this event</label><input id="week-input" class="driver-input" type="text" placeholder="e.g. draft my opening line..." /><button type="submit">Send</button></form></div>' : '') : '<div class="detail-head"><div><h3 class="detail-title">CEO agenda</h3></div></div><p class="section-note">No executive calendar is connected for this reporting period. Your operations team can add the upcoming meetings and preparation milestones when they are confirmed.</p>';
      safeArray([findingsPanel, developmentsPanel]).forEach(function (panel) {
        safeArray(panel && panel.querySelectorAll('[data-rail-toggle]')).forEach(function (button) {
          button.onclick = function () {
            var key = button.getAttribute('data-rail-toggle') || '';
            state.openDriverNoteKey = state.openDriverNoteKey === key ? '' : key;
            renderLowerRailFidelity();
          };
        });
        safeArray(panel && panel.querySelectorAll('[data-rail-prompt]')).forEach(function (button) {
          button.onclick = function (event) {
            event.stopPropagation();
            askAssistant(button.getAttribute('data-rail-prompt') || '', button);
          };
        });
      });
      safeArray(weekPanel.querySelectorAll('[data-week-index]')).forEach(function (button) {
        button.onclick = function () {
          var idx = Number(button.getAttribute('data-week-index') || 0) || 0;
          state.openWeekIndex = state.openWeekIndex === idx ? -1 : idx;
          renderLowerRailFidelity();
        };
      });
      safeArray(weekPanel.querySelectorAll("[data-chat-prompt]")).forEach(function (button) {
        button.onclick = function () {
          var rawPrompt = button.getAttribute("data-chat-prompt") || "";
          var hiddenContext = null;
          if (rawPrompt.indexOf("missing") !== -1 && activeEvent) {
            var eventContext = firstDefined(activeEvent.title, "this event");
            var prepNotes = firstDefined(activeEvent.prep, activeEvent.foot, "");
            var eventWhen = firstDefined(activeEvent.when, "");
            var boardState = state.activeBoard || "pre";
            var activeDriver = getActiveDriver();
            var driverLabel = activeDriver ? firstDefined(activeDriver.label, activeDriver.driver_key, "") : "";
            var driverMetric = activeDriver ? firstDefined(activeDriver.metric, activeDriver.value, "") : "";
            hiddenContext = {
              entrypoint: "missing_data_cta",
              event_title: eventContext,
              event_when: eventWhen,
              board_state: boardState,
              driver_label: driverLabel,
              driver_metric: driverMetric,
              prep_context: prepNotes.slice(0, 300),
              guidance: "identify dashboard-backed gaps"
            };
          }
          askAssistant(rawPrompt, button, hiddenContext);
        };
      });
      var weekComposer = weekPanel.querySelector('#week-composer');
      var weekInput = weekPanel.querySelector('#week-input');
      if (weekComposer && weekInput && activeEvent) {
        weekComposer.addEventListener('submit', function (event) {
          event.preventDefault();
          var message = String(weekInput.value || '').trim();
          if (!message) return;
          askAssistant('For “' + firstDefined(activeEvent.title, 'this event') + '”: ' + message, weekComposer);
          weekInput.value = '';
        });
      }
    }

  }

  function renderAgentsDiscovery() {
    var activityCard = $("agents-activity");
    var networkCard = $("running-agents");
    var collaborationCard = $("discovery-panel");
    var automationCard = $("subtools-panel");
    var agents = (state.latestPacket && state.latestPacket.agents) || {};
    var summary = agents.summary || {};
    var collaboration = agents.collaboration || {};
    var runtime = agents.runtime || {};
    var query = String(state.discoveryQuery || "").trim().toLowerCase();
    var twins = safeArray(agents.digital_twins).filter(function (item) {
      if (!query) return true;
      return [item.display_name, item.assistant_name, item.role, item.current_activity]
        .concat(safeArray(item.kpis_owned), safeArray(item.goals))
        .join(" ").toLowerCase().indexOf(query) !== -1;
    });

    function twinTitle(item) {
      return item.assistant_name
        ? item.assistant_name + " · " + firstDefined(item.display_name, humanizeToken(item.role))
        : firstDefined(item.display_name, humanizeToken(item.role));
    }

    function twinStatus(status) {
      var labels = {
        attention: "Needs human review",
        active: "Working",
        monitoring: "Monitoring",
        ready: "Ready",
        disabled: "Disabled"
      };
      return labels[String(status || "ready")] || humanizeToken(status);
    }

    if (activityCard) {
      activityCard.innerHTML = '<div class="twin-network-intro"><div><span class="eyebrow">AI leadership team</span><h3>Your executive AI team</h3><p>Each AI leader has defined responsibilities, key measures and a clear escalation path. This page highlights current priorities and anything that needs your decision.</p></div><div class="twin-network-metrics"><div><strong>' + escapeHtml(String(firstDefined(summary.configured_count, 0))) + '</strong><span>AI leaders</span></div><div><strong>' + escapeHtml(String(firstDefined(summary.active_count, 0))) + '</strong><span>working now</span></div><div><strong>' + escapeHtml(String(firstDefined(summary.attention_count, 0))) + '</strong><span>need review</span></div></div></div>';
    }

    if (networkCard) {
      networkCard.innerHTML = '<div class="agents-col-head"><div><span class="ach-title">Your AI leadership team</span><span class="ach-hint">Executive roles and responsibilities</span></div><label class="disco-search twin-search"><span class="disco-search-icon">⌕</span><span class="sr-only">Search AI leaders</span><input id="twin-network-search" type="search" value="' + escapeHtml(state.discoveryQuery || '') + '" placeholder="Search leaders, responsibilities or KPIs…" autocomplete="off" /></label></div><div class="twin-card-list">' + (twins.length ? twins.map(function (item) {
        var id = String(firstDefined(item.role, item.twin_id, "twin"));
        var isOpen = state.openAgentId === id;
        var status = String(firstDefined(item.status, "ready"));
        return '<article class="twin-card status-' + escapeHtml(status) + '"><button type="button" class="twin-card__head" data-twin-toggle="' + escapeHtml(id) + '" aria-expanded="' + (isOpen ? 'true' : 'false') + '"><span class="twin-avatar">' + escapeHtml((item.assistant_name || item.display_name || "AI").slice(0, 1)) + '</span><span class="twin-card__identity"><strong>' + escapeHtml(twinTitle(item)) + '</strong><span>' + escapeHtml(firstDefined(item.current_activity, "Ready to support the next leadership review.")) + '</span></span><span class="twin-status"><i></i>' + escapeHtml(twinStatus(status)) + '</span><span class="agent-caret' + (isOpen ? ' is-open' : '') + '">›</span></button>' + (isOpen ? '<div class="twin-card__body"><div class="twin-facts"><div><span>Open priorities</span><strong>' + escapeHtml(String(firstDefined(item.active_investigation_count, 0))) + '</strong></div><div><span>Decisions needed</span><strong>' + escapeHtml(String(firstDefined(item.pending_request_count, 0))) + '</strong></div><div><span>Completed reviews</span><strong>' + escapeHtml(String(firstDefined(item.cycle_count, 0))) + '</strong></div></div><div class="twin-detail"><span class="eyebrow">Responsibilities</span><p>' + escapeHtml(firstDefined(item.authority, "Responsibilities will appear when available.")) + '</p></div><div class="twin-detail"><span class="eyebrow">Business focus</span><div class="twin-tags">' + safeArray(item.kpis_owned).map(function (kpi) { return '<span>' + escapeHtml(humanizeToken(kpi)) + '</span>'; }).join('') + '</div></div><div class="twin-detail"><span class="eyebrow">Executive escalation</span><p>' + escapeHtml(safeArray(item.escalation_path).map(humanizeToken).join(' → ') || 'No executive escalation is currently required') + '</p></div>' + (item.route ? '<a class="btn secondary twin-open" href="' + escapeHtml(item.route) + '">Open team workspace</a>' : '') + '</div>' : '') + '</article>';
      }).join('') : '<div class="network-empty">No AI leaders match this search.</div>') + '</div>';
      var search = networkCard.querySelector('#twin-network-search');
      if (search) search.oninput = function () {
        state.discoveryQuery = search.value || '';
        renderAgentsDiscovery();
        var next = $("twin-network-search");
        if (next) {
          next.focus();
          if (typeof next.setSelectionRange === "function") next.setSelectionRange(next.value.length, next.value.length);
        }
      };
      safeArray(networkCard.querySelectorAll('[data-twin-toggle]')).forEach(function (button) {
        button.onclick = function () {
          var id = button.getAttribute('data-twin-toggle') || '';
          state.openAgentId = state.openAgentId === id ? '' : id;
          renderAgentsDiscovery();
        };
      });
    }

    if (collaborationCard) {
      var events = safeArray(collaboration.recent_events);
      var openHandoffs = Number(firstDefined(collaboration.open_handoff_count, collaboration.pending_request_count, 0)) || 0;
      var resolvedHandoffs = Number(firstDefined(collaboration.resolved_handoff_count, 0)) || 0;
      var attentionHandoffs = Number(firstDefined(collaboration.executive_attention_count, 0)) || 0;
      var completedCycles = Number(firstDefined(runtime.completed_cycle_count, runtime.cycle_count, 0)) || 0;
      var collaborationMeaning = attentionHandoffs
        ? attentionHandoffs + ' item' + (attentionHandoffs === 1 ? ' requires' : 's require') + ' your attention.'
        : (openHandoffs ? openHandoffs + ' item' + (openHandoffs === 1 ? ' is' : 's are') + ' progressing with the leadership team.' : 'Nothing requires your attention.');
      var noEventCopy = openHandoffs
        ? 'Items are progressing; no decision is requested from you yet.'
        : 'No recent leadership-team activity needs review.';
      collaborationCard.innerHTML = '<div class="agents-col-head"><div><span class="ach-title">Leadership team activity</span><span class="ach-hint">Items moving between your AI leaders</span></div></div><p class="twin-explainer">This view highlights work in progress and shows only the items that need an executive decision.</p><div class="twin-collab-summary"><div><strong>' + escapeHtml(String(openHandoffs)) + '</strong><span>in progress</span></div><div><strong>' + escapeHtml(String(resolvedHandoffs)) + '</strong><span>completed</span></div><div class="' + (attentionHandoffs ? 'needs-attention' : '') + '"><strong>' + escapeHtml(String(attentionHandoffs)) + '</strong><span>need your attention</span></div></div><p class="twin-collab-meaning">' + escapeHtml(collaborationMeaning) + '</p>' + (events.length ? '<div class="twin-event-heading">Recent activity</div><ol class="twin-event-list">' + events.slice(0, 5).map(function (event) { return '<li><div class="twin-event-meta"><span>' + escapeHtml(humanizeToken(firstDefined(event.source_role, "leadership team"))) + ' → ' + escapeHtml(humanizeToken(firstDefined(event.target_role, "leadership team"))) + '</span><em class="event-' + escapeHtml(String(firstDefined(event.status, "recorded"))) + '">' + escapeHtml(humanizeToken(firstDefined(event.status, "recorded"))) + '</em></div><strong>' + escapeHtml(firstDefined(event.subject, "Leadership-team item")) + '</strong></li>'; }).join('') + '</ol>' : '<div class="network-empty twin-empty">' + escapeHtml(noEventCopy) + '</div>') + (completedCycles ? '<p class="twin-runtime-note">' + escapeHtml(String(completedCycles)) + ' review cycle' + (completedCycles === 1 ? '' : 's') + ' completed</p>' : '');
    }

    if (automationCard) {
      automationCard.hidden = true;
      automationCard.innerHTML = '';
    }
  }

  function renderAssistantStudio() {
    ensureThreads();
    var blueprint = getPersonaBlueprint(state.activePersona);
    var persona = getPersonaContract(state.activePersona);
    var assistantName = firstDefined(persona.assistant, blueprint.assistant, "Hermes");
    var assistantRole = firstDefined(persona.assistant_role, blueprint.assistantRole, "chief of staff");
    var threadList = $("assistant-thread-list");
    var threadTitle = $("assistant-thread-title");
    var threadMeta = $("assistant-thread-meta");
    var messages = $("assistant-messages");
    var promptRow = $("assistant-prompt-row");
    var threadTools = $("assistant-thread-tools");
    var assistantHeading = $("assistant-heading");
    var assistantSubtitle = $("assistant-subtitle");
    var assistantState = $("assistant-state");
    var drawer = $("assistant-drawer");
    var scrim = $("assistant-scrim");
    var launcher = $("chat-launcher");
    var topbarLauncher = $("topbar-assistant-launch");
    var closeButton = $("assistant-close");
    var threads = personaThreadRecords();
    var current = threadStore()[currentThreadKey()];
    if (current) markThreadTransportFailuresRetryable(current);

    if (drawer) {
      drawer.hidden = !state.drawerOpen;
      drawer.classList.toggle("is-open", state.drawerOpen);
      drawer.setAttribute("aria-modal", state.drawerOpen ? "true" : "false");
      drawer.setAttribute("aria-hidden", state.drawerOpen ? "false" : "true");
      drawer.setAttribute("role", "dialog");
    }
    if (scrim) {
      scrim.hidden = !state.drawerOpen;
      scrim.classList.toggle("is-open", state.drawerOpen);
      scrim.setAttribute("aria-hidden", state.drawerOpen ? "false" : "true");
      scrim.onclick = function () {
        _closeHermesDrawer();
      };
    }
    [launcher, topbarLauncher].forEach(function (trigger) {
      if (!trigger) return;
      trigger.hidden = state.drawerOpen || state.activeView === "assistants";
      trigger.onclick = function () {
        _openHermesDrawer(trigger);
      };
    });
    if (closeButton) {
      closeButton.onclick = function () {
        _closeHermesDrawer();
      };
    }
    // Inject thread list toggle for narrow/mobile screens (non-CEO personas only)
    if (state.activePersona !== "ceo") {
      var headActions = drawer && drawer.querySelector('.assistant-head__actions');
      if (headActions && !headActions.querySelector('.assistant-threads-toggle')) {
        var toggleBtn = document.createElement('button');
        toggleBtn.type = 'button';
        toggleBtn.className = 'assistant-threads-toggle';
        toggleBtn.setAttribute('aria-label', 'Toggle thread history');
        toggleBtn.setAttribute('aria-expanded', 'false');
        toggleBtn.textContent = 'History \u25B8';
        toggleBtn.onclick = function () {
          var threadsPane = drawer.querySelector('.assistant-threads');
          var layout = drawer.querySelector('.assistant-layout');
          if (threadsPane) {
            var collapsed = threadsPane.classList.toggle('is-collapsed');
            toggleBtn.setAttribute('aria-expanded', String(!collapsed));
            toggleBtn.textContent = collapsed ? 'History \u25B8' : 'History \u25BE';
            if (layout) layout.classList.toggle('threads-collapsed', collapsed);
          }
        };
        headActions.insertBefore(toggleBtn, closeButton);
      }
    }

    if (assistantHeading) assistantHeading.textContent = "Ask " + assistantName;
    if (assistantSubtitle) assistantSubtitle.textContent = assistantName + " will answer here using the current board pack.";
    var assistantInput = $("assistant-input");
    if (assistantInput) {
      assistantInput.placeholder = "Ask " + assistantName + "…";
      assistantInput.setAttribute("aria-label", "Ask " + assistantName);
    }
    if (assistantState) {
      if (state.activePersona === "ceo") {
        assistantState.textContent = "";
        assistantState.hidden = true;
      } else {
        assistantState.textContent = statusLabel(firstDefined(state.activeBoard, "ready"));
        assistantState.hidden = false;
      }
    }

    // Synchronize layout class with threads collapsed state
    var threadsPane = drawer && drawer.querySelector('.assistant-threads');
    var layout = drawer && drawer.querySelector('.assistant-layout');
    if (layout && threadsPane) {
      layout.classList.toggle('threads-collapsed', threadsPane.classList.contains('is-collapsed'));
    }

    if (threadList) {
      var visibleThreads = threads;
      if (state.activePersona === "ceo") {
        visibleThreads = threads.filter(function (record) {
          var title = String(firstDefined(record.title, '')).toLowerCase();
          var preview = String(firstDefined(record.preview, '')).toLowerCase();
          var isBug = title.indexOf('report a bug') !== -1 || title.indexOf('bug') !== -1;
          var isSystem = record.kind === 'system';
          var isError = preview.indexOf('could not compute a protected data') !== -1 || title.indexOf('error') !== -1;
          return !isBug && !isSystem && !isError;
        });
      }
      threadList.innerHTML = '<button type="button" class="assistant-thread assistant-thread--new" data-thread-new="true"><strong>＋ New conversation</strong><span>Start a new conversation</span></button>' + visibleThreads.map(function (record) {
        var active = record.key === currentThreadKey();
        var threadMetaCount = safeArray(record.messages).length;
        var threadMeta = threadMetaCount > 0 ? escapeHtml(String(threadMetaCount)) + ' message(s)' : '';
        return '<button type="button" class="assistant-thread' + (active ? ' is-active' : '') + '" data-thread-key="' + escapeHtml(record.key) + '"' + (active ? ' aria-current="page"' : '') + '><div class="assistant-thread__top"><strong>' + escapeHtml(firstDefined(record.title, 'Thread')) + '</strong><span>' + escapeHtml(friendlyThreadTime(record.lastUpdated)) + '</span></div><span>' + escapeHtml(firstDefined(record.preview, 'Board-safe follow-up')) + '</span>' + (threadMeta ? '<small>' + threadMeta + '</small>' : '') + '</button>';
      }).join("");
      safeArray(threadList.querySelectorAll("[data-thread-new]")).forEach(function (button) {
        button.onclick = function () {
          createWritableThread();
          openAssistantDrawer(button);
        };
      });
      safeArray(threadList.querySelectorAll("[data-thread-key]")).forEach(function (button) {
        button.onclick = function () {
          state.activeThreadKey = button.getAttribute("data-thread-key") || "";
          renderAssistantStudio();
        };
      });
    }

    if (threadTitle) threadTitle.textContent = firstDefined(current && current.title, "Thread");
    if (threadMeta) threadMeta.textContent = firstDefined(current && current.preview, blueprint.brief, "Select a board follow-up.");
    if (threadTools) {
      var tools = [];
      var latestFailure = latestRetryableAssistantFailure(current);
      if (state.activePersona !== "ceo") {
        tools.push('<span class="assistant-tool-chip">' + escapeHtml(firstDefined((getChatContract().assistant || {}).name, assistantName)) + '</span>');
      }
      if (state.activePersona !== "ceo") {
        var boardStateLabel = statusLabel(firstDefined(state.activeBoard, (getChatContract().assistant || {}).board_state, 'pre'));
        tools.push('<span class="assistant-tool-chip">' + escapeHtml(boardStateLabel) + '</span>');
      }
      if (current && current.route && state.activePersona !== "ceo") tools.push('<span class="assistant-tool-chip">' + escapeHtml(current.route) + '</span>');
      if (latestFailure && latestFailure.message && latestFailure.message.retryPrompt) {
        tools.push('<button type="button" class="assistant-tool-chip assistant-tool-chip--action" data-assistant-retry-latest="true">Retry now</button>');
      }
      threadTools.innerHTML = tools.join('');
      safeArray(threadTools.querySelectorAll('[data-assistant-retry-latest]')).forEach(function (button) {
        button.onclick = function () {
          retryAssistantMessage(current.key, latestFailure.index, button);
        };
      });
    }

    if (messages) {
      var visibleMessages = safeArray(current && current.messages).map(function (message, index) {
        return { message: message, index: index };
      }).filter(function (entry) {
        return String(firstDefined(entry && entry.message && entry.message.text, '')).trim().length > 0;
      });
      messages.innerHTML = visibleMessages.length ? visibleMessages.map(function (entry) {
        var message = entry.message || {};
        var role = firstDefined(message.role, 'assistant');
        var roleLabel = role === 'user' ? 'You' : assistantName;
        var roleSuffix = state.activePersona === "ceo" ? '' : ' · ' + escapeHtml(friendlyThreadTime(firstDefined(message.timestamp, 'now')));
        var classes = ['assistant-message', 'assistant-message--' + escapeHtml(role)];
        if (message.status === 'failed') classes.push('assistant-message--failed');
        if (message.status === 'pending') classes.push('assistant-message--pending');
        var failureMeta = '';
        if (role === 'assistant' && message.status === 'failed') {
          failureMeta = '<div class="assistant-message__meta">' + escapeHtml(summarizeAssistantFailure(message)) + '</div>';
        } else if (role === 'assistant' && message.meta) {
          failureMeta = '<div class="assistant-message__meta">' + escapeHtml(firstDefined(message.meta, '')) + '</div>';
        }
        var retryButton = '';
        if (role === 'assistant' && message.status === 'failed' && message.retryPrompt) {
          retryButton = '<div class="assistant-message__actions"><button type="button" class="assistant-retry-button" data-assistant-retry-index="' + escapeHtml(String(entry.index)) + '">Retry now</button></div>';
        }
        var caseLinks = '';
        if (role === 'assistant' && message.status === 'ok' && safeArray(message.caseLinks).length) {
          caseLinks = '<div class="assistant-message__actions">' + safeArray(message.caseLinks).map(function (caseLink) {
            var caseId = String(firstDefined(caseLink && caseLink.finding_id, '')).trim();
            var label = String(firstDefined(caseLink && caseLink.title, caseId)).trim();
            if (!caseId || !label) return '';
            return '<button type="button" class="assistant-retry-button" data-assistant-case-id="' + escapeHtml(caseId) + '">Open case: ' + escapeHtml(label) + '</button>';
          }).join('') + '</div>';
        }
        var bodyHtml = role === 'assistant'
          ? renderAssistantMarkdownToHtml(firstDefined(message.text, ''))
          : escapeHtml(firstDefined(message.text, ''));
        return '<div class="' + classes.join(' ') + '"><span class="assistant-message__role">' + escapeHtml(roleLabel) + roleSuffix + '</span><p>' + bodyHtml + '</p>' + failureMeta + retryButton + caseLinks + '</div>';
      }).join("") : '<div class="assistant-message assistant-message--empty"><span class="assistant-message__role">No messages yet</span><p>Ask a question to begin.</p></div>';
      safeArray(messages.querySelectorAll('[data-assistant-retry-index]')).forEach(function (button) {
        button.onclick = function () {
          retryAssistantMessage(current.key, Number(button.getAttribute('data-assistant-retry-index') || '-1'), button);
        };
      });
      safeArray(messages.querySelectorAll('[data-assistant-case-id]')).forEach(function (button) {
        button.onclick = function () {
          openAssistantCase(button.getAttribute('data-assistant-case-id') || '', button);
        };
      });
      messages.scrollTop = messages.scrollHeight;
    }

    if (promptRow) {
      var hasVisibleMessages = current && safeArray(current.messages).some(function (m) { return m && m.text && String(m.text).trim().length > 0; });
      promptRow.innerHTML = hasVisibleMessages ? '' : getHeroPrompts().slice(0, 2).map(function (prompt) {
        return '<button class="prompt-chip" type="button" data-assistant-prompt="' + escapeHtml(prompt) + '">' + escapeHtml(prompt) + '</button>';
      }).join("");
      safeArray(promptRow.querySelectorAll("[data-assistant-prompt]")).forEach(function (button) {
        button.onclick = function () {
          askAssistant(button.getAttribute("data-assistant-prompt") || "", button);
        };
      });
    }
    maybeAutoRetryLatestFailure(current);
  }

  function renderReportSurface() {
    var reportCard = $("report-surface-card");
    var publication = getPublication();
    if (!reportCard) return;
    var reportReleased = Boolean((publication.reconciliation || {}).publish_gate_passed) && /^(approved|published|released|frozen)$/.test(String(firstDefined(publication.publish_state, "")).toLowerCase());
    if (state.activePersona === "board" && !reportReleased) {
      reportCard.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Board material</p><h3 class="detail-title">No released reports</h3></div><span class="pill-inline warn">Release pending</span></div><p class="detail-copy">Report links remain unavailable until the CEO release decision is recorded.</p>';
      return;
    }
    reportCard.innerHTML = [
      '<div class="detail-head"><div><p class="detail-eyebrow">' + (state.activePersona === "ceo" ? 'Board reports' : 'Report surface') + '</p><h3 class="detail-title">' + (state.activePersona === "ceo" ? 'Board reports' : 'Previewable report routes') + '</h3></div><span class="pill-inline ' + toneClass(statusLabel(firstDefined(publication.publish_state, 'draft'))) + '">' + escapeHtml(statusLabel(firstDefined(publication.publish_state, 'draft'))) + '</span></div>',
      '<p class="detail-copy">Overview, cases, evidence, and reports now sit as one workspace. This rail keeps the board-safe output explicit.</p>',
      '<div class="mini-list">' + safeArray(publication.available_artifacts).slice(0, 5).map(function (item) {
        var formatLabel = function (fmt) {
          var map = { graph: 'Data relationships', audit: 'Decision trail', other: 'Overview file', json: 'Structured data', csv: 'Spreadsheet', pdf: 'PDF document', md: 'Markdown note' };
          return map[String(fmt).toLowerCase()] || escapeHtml(fmt);
        };
        var catLabel = REPORT_CATEGORY_MAP[item.category] || humanizeToken(item.category) || 'report';
        var meta = escapeHtml(catLabel);
        return '<div class="list-item"><div><strong>' + escapeHtml(firstDefined(item.title, item.artifact_key, 'Artifact')) + '</strong><p class="list-copy">' + meta + '</p></div><span class="pill-inline ' + (item.restricted ? 'warn' : 'ok') + '">' + escapeHtml(item.restricted ? 'restricted' : 'board-safe') + '</span></div>';
      }).join("") + '</div>',
      state.activePersona === "ceo" ? '' : '<a class="summary-link" href="' + escapeHtml(firstDefined(publication.preview_route, '/public/runs/latest/report-preview')) + '">Open report preview</a>'
    ].join("");
  }

  function renderSummary() {
    if (!$("summary-kicker") || !$("summary-title") || !$("summary-body") || !$("summary-note")) return;
    var driver = getActiveDriver() || {};
    var hero = getExecutiveDiagnostics().hero || {};
    var link = $("summary-link");
    $("summary-kicker").textContent = firstDefined(driver.label, "Current readout");
    $("summary-title").textContent = firstDefined(hero.summary, hero.label, getPlanHealth().label, "Executive signal");
    $("summary-body").textContent = firstDefined(driver.detail, hero.body, getPlanHealth().summary, "Awaiting summary.");
    $("summary-note").textContent = firstDefined(getBoardPortal().governance_note, hero.quote, "");
    if (link) {
      if (state.activePersona === "ceo") {
        link.href = "#";
        link.style.display = "none";
      } else {
        link.href = firstDefined(getPublication().preview_route, "/public/runs/latest/report-preview");
        link.style.display = "";
      }
    }
  }

  function updateDocumentTitle() {
    var personaLabel = state.activePersona === "board" ? "Board Room" : getPersonaLabel(state.activePersona);
    var viewLabels = {
      home: state.activePersona === "board" ? "Portal" : "Diagnostics",
      assistants: "Assistants",
      agents: "AI team",
      knowledge: "Knowledge",
      reports: "Reports"
    };
    document.title = "StrategyOS — " + personaLabel + " " + firstDefined(viewLabels[state.activeView], "Workspace");
  }

  function renderPersonaView() {
    updateDocumentTitle();
    renderTopbar();
    renderViewNav();
    renderViewPanels();
    renderHomeComposition();
    renderHero();
    renderDriverGrid();
    renderMetrics();
    renderDriverDrillFidelity();
    renderBoardStateTabs();
    renderBoardPortal();
    renderLowerRailFidelity();
    renderAgentsDiscovery();
    renderAssistantNetwork();
    renderA2APanel();
    renderKnowledgeGraph();
    renderAssistantStudio();
    renderReportSurface();
    renderSummary();
    // Final board-tab re-sync for the knowledge view: after ALL render
    // functions have completed, re-assert the intended tab state so that
    // any className or inline style discarded during the full render
    // pipeline (CSSOM recalc from innerHTML replacements across multiple
    // render functions) is restored. Only applies when the board portal
    // is visible (knowledge view active).
    if (state.activePersona === "board" && state.activeView === "home") {
      renderBoardStateTabs();
      syncBoardStateTabUI(resolveBoardState());
    }
  }

  async function refresh(withAnimation) {
    try {
      if (withAnimation) {
        animateCard("sheet");
        animateCard("board-portal");
      }
      var params = currentViewParams();
      var session = await fetchJson("/ui/session") || {};
      var latestPacket = await fetchJson(latestRunRouteForSession(session) + buildQuery(params));

      state.latestPacket = latestPacket || {};
      state.session = session;
      state.personas = safeArray((state.latestPacket.executive_modes || {}).personas);
      state.token = firstDefined(state.token, window.localStorage.getItem(_tokenKey));
      state.activePersona = firstDefined((state.latestPacket.executive_modes || {}).active_persona_id, state.activePersona, "ceo");
      if (state.activePersona === "board") state.activeView = "home";
      // During an active board-state transition, the packet's presentation_state
      // must not override the user's in-flight selection. _boardStateTransition
      // is set by activateBoardState and cleared after the render cycle completes.
      // This prevents a refresh() from reading a stale server presentation_state
      // while a user-initiated tab switch is in progress.
      if (!state._boardStateTransition) {
        state.activeBoard = firstDefined(state.activeBoard, (state.latestPacket.executive_modes || {}).active_board_state, (state.latestPacket.board_portal || {}).presentation_state, "pre");
      }
      // Preserve the KPI the executive selected locally. The packet default is
      // only used on first load or after an explicit persona reset.
      state.activeDriverKey = firstDefined(state.activeDriverKey, (state.latestPacket.executive_modes || {}).active_driver_key, "board_packet");
      state.activeCompany = firstDefined((state.latestPacket.executive_modes || {}).company_id, state.activeCompany);
      state.activePortfolio = firstDefined((state.latestPacket.executive_modes || {}).portfolio_id, state.activePortfolio);
      ensureThreads();
      updateHistory();
      renderPersonaView();
    } catch (error) {
      console.warn("executive refresh failed", error);
    }
  }

  function bindAssistantForm() {
    var form = $("assistant-form");
    var input = $("assistant-input");
    if (!form || !input) return;
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var message = String(input.value || "").trim();
      if (!message) return;
      askAssistant(message, null);
      input.value = "";
    });
  }

  function bindViewNav() {
    safeArray(document.querySelectorAll("[data-view-target]")).forEach(function (link) {
      link.addEventListener("click", function (event) {
        event.preventDefault();
        switchView(link.getAttribute("data-view-target") || "home");
      });
    });
  }

  var requested = (bootstrap.requested_view_state || {});
  var state = {
    latestPacket: null,
    session: null,
    personas: [],
    token: null,
    activePersona: firstDefined(requested.persona, "ceo"),
    activeDriverKey: firstDefined(requested.driver, "board_packet"),
    activeBoard: firstDefined(requested.board, "pre"),
      activeCompany: firstDefined(requested.company, ""),
      activePortfolio: firstDefined(requested.portfolio, ""),
      activeThreadKey: "",
      activeView: requested.agent ? "agents" : "home",
      a2aOpen: false,
      activeA2AExchange: "",
      drawerOpen: false,
      drawerReturnFocusEl: null,
      failedAssistantAutoRetried: {},
      videoModalOpen: false,
      theme: document.documentElement.getAttribute("data-theme") || "light",
      discoveryFilter: "all",
      discoveryQuery: "",
      assistantCatalogueOpen: false,
      networkStatusFilter: "all",
      networkFilterMenuOpen: false,
      selectedAgentModuleKey: "",
      knowledgeQuestionIndex: 0,
      kgDensityMode: "compact",
      kgZoom: 1,
      kgPanX: 0,
      kgPanY: 0,
      kgFocusMode: false,
      _boardStateTransition: '',
    _boardStateTransitionTimer: null,
    _kgDragState: null,
      _kgDragBindingsAttached: false,
      personaOutsideListenerBound: false,
      openDriverNoteKey: "",
      selectedFindingId: "",
      openWeekIndex: 0,
      agentSummaryOpen: false,
      openAgentId: firstDefined(requested.agent, ""),
      openAgentLogId: "",
      approvedAgentIds: {}
    };

  if (!state._kgDragBindingsAttached) {
    window.addEventListener('mousemove', function (event) {
      var drag = state._kgDragState;
      if (!drag) return;
      state.kgPanX = drag.panX + (event.clientX - drag.startX);
      state.kgPanY = drag.panY + (event.clientY - drag.startY);
      var canvas = card && card.querySelector('.kg-canvas');
      if (canvas) canvas.style.transform = kgCanvasTransform();
    });
    window.addEventListener('mouseup', function () {
      state._kgDragState = null;
      var stage = card && card.querySelector('.kg-stage');
      if (stage) stage.classList.remove('is-dragging');
    });
    state._kgDragBindingsAttached = true;
  }

  bindAssistantForm();
  bindViewNav();
  refresh(false);
  window.setInterval(function () { refresh(false); }, 60000);
})();
