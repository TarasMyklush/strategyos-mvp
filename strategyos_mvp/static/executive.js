(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var bootstrapScript = $("strategyos-executive-bootstrap");
  var bootstrap = bootstrapScript ? JSON.parse(bootstrapScript.textContent) : {};
  if (bootstrap.environment) {}
  if (bootstrap.api_auth_enabled) {}
  var _tokenKey = "strategyos.ui.token";
  var DESIGN = (window.STRATEGYOS_EXECUTIVE_DESIGN && window.STRATEGYOS_EXECUTIVE_DESIGN.personas) || {};
  var DESIGN_GLOBAL = window.STRATEGYOS_EXECUTIVE_DESIGN || {};
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

  function humanizeToken(token) {
    if (!token) return "—";
    return String(token)
      .replace(/[_-]/g, " ")
      .split(" ")
      .filter(Boolean)
      .map(function (part) { return part.charAt(0).toUpperCase() + part.slice(1); })
      .join(" ");
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
      "live packet": "Live packet",
      "live_packet": "Live packet",
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

  function authHeaders() {
    var token = "";
    try { token = window.localStorage.getItem(_tokenKey) || ""; } catch (_error) { token = ""; }
    if (!token) return {};
    if (bootstrap.idp_enabled || token.indexOf(".") !== -1) return { Authorization: "Bearer " + token };
    return { "X-API-Key": token };
  }

  function fetchJson(path) {
    return fetch(path, { headers: authHeaders() }).then(function (response) {
      return response.ok ? response.json() : null;
    });
  }

  function postJson(path, body) {
    var headers = authHeaders();
    headers["Content-Type"] = "application/json";
    return fetch(path, {
      method: "POST",
      headers: headers,
      body: JSON.stringify(body || {})
    }).then(function (response) {
      return response.ok ? response.json() : null;
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
    /* Guard: no-op if drawer already open — avoid redundant renders */
    if (state.drawerOpen) return;
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
    var cleanPrompt = String(prompt || "").trim();
    if (!cleanPrompt) return;
    var validChip = sourceChip && typeof sourceChip === 'object' && sourceChip.nodeType === 1 ? sourceChip : null;
    var originalText = null;
    if (validChip) {
      originalText = validChip.textContent;
      validChip.textContent = 'loading\u2026';
      validChip.disabled = true;
    }
    ensureWritableThread(threadTitleFromPrompt(cleanPrompt), cleanPrompt);
    pushThreadMessage("user", cleanPrompt);
    var pending = pushThreadMessage("assistant", "Checking the governed run data\u2026");
    openAssistantDrawer(validChip);
    // Show loading state in the input area when no source chip provides feedback
    var form = $("assistant-form");
    var input = $("assistant-input");
    if (!validChip && form && input) {
      input.disabled = true;
      input.placeholder = 'Hermes is thinking\u2026';
      form.classList.add('assistant-form--loading');
    }
    var answer = await buildAssistantReply(cleanPrompt);
    // Clear loading state
    if (!validChip && form && input) {
      input.disabled = false;
      input.placeholder = 'Ask the assistant for the next board-safe move\u2026';
      form.classList.remove('assistant-form--loading');
      focusAssistantInput();
    }
    if (pending) {
      pending.text = answer;
      pending.timestamp = new Date().toISOString();
      var thread = threadStore()[currentThreadKey()];
      if (thread) {
        thread.preview = String(answer || thread.preview || "").slice(0, 84);
        thread.lastUpdated = new Date().toISOString();
      }
      saveStoredThreads();
      renderAssistantStudio();
    }
    if (validChip) {
      validChip.textContent = originalText;
      validChip.disabled = false;
    }
  }


  function switchView(view) {
    state.activeView = view || "home";
    updateHistory();
    renderPersonaView();
    if (state.activeView === "assistants") focusAssistantInput();
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
      portfolio: state.activePortfolio
    });
    window.history.replaceState({}, "", route + query);
  }

  function currentViewParams() {
    return {
      persona: state.activePersona,
      board: state.activeBoard,
      driver: state.activeDriverKey,
      company: state.activeCompany,
      portfolio: state.activePortfolio
    };
  }

  function getPersonaBlueprint(personaId) {
    return DESIGN[personaId] || DESIGN.ceo || {};
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

  function executiveIdentityInitials(personaId) {
    var networkEntry = getAssistantNetwork().find(function (item) {
      return item && item.persona === personaId;
    }) || {};
    var fullName = String(firstDefined(networkEntry.who, "")).trim();
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

    if (personaId === "ceo") return "KA";
    return fallbackInitials || "GC";
  }

  function getExecutiveDiagnostics() {
    return (state.latestPacket && state.latestPacket.executive_diagnostics) || {};
  }

  function getBoardPortal() {
    return (state.latestPacket && state.latestPacket.board_portal) || {};
  }

  function getBoardDesign() {
    return DESIGN_GLOBAL.board || {};
  }

  function getChatContract() {
    return (state.latestPacket && state.latestPacket.chat) || {};
  }

  function getPublication() {
    return (state.latestPacket && state.latestPacket.publication) || {};
  }

  function getAssistantNetworkMeta() {
    return DESIGN_GLOBAL.networkMeta || {};
  }

  function getAssistantNetwork() {
    return safeArray(DESIGN_GLOBAL.network);
  }

  function getAssistantExchanges() {
    return safeArray(DESIGN_GLOBAL.a2a);
  }

  function getKnowledgeGraph() {
    return DESIGN_GLOBAL.graph || { questions: [], nodes: [], edges: [] };
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
    return DESIGN_GLOBAL.activity || {};
  }

  function getRunningAgents() {
    var modules = getAgentsModule();
    return safeArray(modules.running).length ? safeArray(modules.running) : safeArray(DESIGN_GLOBAL.runningAgents);
  }

  function getDiscoverableAgents() {
    var modules = getAgentsModule();
    return safeArray(modules.discoverable).length ? safeArray(modules.discoverable) : safeArray(DESIGN_GLOBAL.discoverAgents);
  }

  function getApprovalAgents() {
    var modules = getAgentsModule();
    return safeArray(modules.approvals);
  }

  function getSubtools() {
    return safeArray(DESIGN_GLOBAL.subtools);
  }

  function getVisibleDrivers() {
    var blueprint = getPersonaBlueprint(state.activePersona);
    var designDrivers = safeArray(blueprint.drivers).map(function (item) {
      return {
        driver_key: item.key,
        label: item.label,
        metric: item.value,
        status: item.vsPlan,
        detail: item.story,
        pct: item.pct,
        tone: item.tone,
        sub: item.sub,
        chips: safeArray(item.chips),
        movers: item.movers || {},
        trend: item.trend || {},
        trendLabel: item.trendLabel,
        unit: item.unit
      };
    });
    var packetDrivers = safeArray(getExecutiveDiagnostics().driver_grid);
    return (designDrivers.length ? designDrivers : packetDrivers).slice(0, 4);
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
    var blueprint = getPersonaBlueprint(state.activePersona);
    var chatPrompts = safeArray(getChatContract().starter_prompts);
    return safeArray(gravity.prompts).length ? safeArray(gravity.prompts) : (chatPrompts.length ? chatPrompts : safeArray(blueprint.prompts));
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
    var pct = Math.max(0, Number(firstDefined(driver.pct, 0)) || 0);
    var radius = 15;
    var circumference = 2 * Math.PI * radius;
    // Full circle = 100% of plan. Values above 100% cap at full ring;
    // the over-plan amount is shown as a badge outside the ring.
    var frac = Math.max(0.02, Math.min(pct, 100) / 100);
    var dash = circumference * frac;
    return '<svg class="driver-ring" viewBox="0 0 36 36" aria-hidden="true"><circle class="driver-ring__track" cx="18" cy="18" r="15"></circle><circle class="driver-ring__value" cx="18" cy="18" r="15" stroke-dasharray="' + dash + ' ' + circumference + '" transform="rotate(-90 18 18)"></circle></svg>';
  }

  function qaAnswerText(payload) {
    if (!payload) return "I could not reach the governed Q&A service. Try again from an authenticated operator or reviewer session.";
    if (state.activePersona === "ceo") {
      var ceoAnswer = String(firstDefined(payload.answer, "")).trim();
      return ceoAnswer || "No answer returned from governed Q&A.";
    }
    var answer = String(firstDefined(payload.answer, "")).trim();
    var mode = payload.mode === "llm" ? "AI fallback" : payload.mode === "deterministic" ? "Deterministic" : "Q&A";
    var parts = [];
    if (answer) parts.push(answer);
    if (payload.mode === "llm") parts.push("Answered by AI fallback because deterministic Q&A did not cover that question.");
    if (payload.matched === false && payload.llm_status && payload.llm_status.reason) {
      parts.push("AI fallback is not available: " + payload.llm_status.reason);
    }
    if (payload.basis) parts.push("Basis: " + payload.basis);
    if (payload.run_id) parts.push("Run: " + payload.run_id + " · " + mode + ".");
    return parts.join(" ") || "No answer returned from governed Q&A.";
  }

  function boardSafeStatusReply(message) {
    if (state.activePersona === "ceo") {
      return "Your board pack is currently under review. Hermes will answer from the approved pack once review clears.";
    }
    var publication = getPublication();
    var planHealth = getPlanHealth();
    var boardPortal = getBoardPortal();
    var runId = activeRunId() || "latest-public";
    var recoverable = firstDefined(state.latestPacket && state.latestPacket.total_recoverable_sar, publication.total_recoverable_sar, 0);
    var findings = firstDefined(state.latestPacket && state.latestPacket.locked_findings, publication.finding_count, "—");
    var challenged = firstDefined(publication.challenged_cases, state.latestPacket && state.latestPacket.challenged_cases, 0);
    return [
      "I could not compute a protected data answer in this executive surface.",
      "Current governed run " + runId + " is " + statusLabel(firstDefined(state.latestPacket && state.latestPacket.current_stage, state.latestPacket && state.latestPacket.status, "governed")) + ".",
      "Recoverable value is " + formatSar(recoverable) + ", findings: " + findings + ", challenged items: " + challenged + ".",
      firstDefined(planHealth.summary, boardPortal.governance_note, "Use /app as operator/reviewer for protected evidence Q&A and simulations."),
      message ? "Question asked: \u201c" + message + "\u201d." : ""
    ].filter(Boolean).join(" ");
  }

  async function buildAssistantReply(message) {
    var cleanMessage = String(message || "").trim();
    if (!cleanMessage) return boardSafeStatusReply("");

    // CEO greeting/small-talk detection
    if (state.activePersona === "ceo") {
      var greetingPatterns = /^(hi|hey|hello|good\s+(morning|afternoon|evening)|how\s+are\s+you|what'?s\s+up|sup|yo|hola|bonjour|namaste)([!.\s]*)$/i;
      if (greetingPatterns.test(cleanMessage)) {
        // Get executive name from assistant network, fallback to KA initials
        var networkEntry = getAssistantNetwork().find(function(item) {
          return item && item.persona === "ceo";
        }) || {};
        var execFirstName = String(firstDefined(networkEntry.who, "")).trim().split(/\s+/)[0] || "Khalid";
        return "Hi " + execFirstName + " \u2014 I can help with board readiness, margin risk, cash, or the knowledge map. What would you like to review?";
      }
    }

    var body = { question: cleanMessage, mode: "auto" };
    var runId = activeRunId();
    if (runId && runId !== "latest-public") body.run_id = runId;
    try {
      var payload = await postJson("/qa", body);
      if (payload && payload.status === "ok") return qaAnswerText(payload);
    } catch (_error) {}
    return boardSafeStatusReply(cleanMessage);
  }

  function threadStore() {
    window.MIZAN_X = window.MIZAN_X || { threads: {}, assistants: {} };
    return window.MIZAN_X.threads;
  }

  function currentThreadKey() {
    return state.activeThreadKey || (state.activePersona + ":briefing");
  }

  function ensureThreads() {
    var chat = getChatContract();
    var blueprint = getPersonaBlueprint(state.activePersona);
    var persona = getPersonaContract(state.activePersona);
    var assistantName = firstDefined(persona.assistant, blueprint.assistant, "Hermes");
    var persisted = loadStoredThreads();
    Object.keys(persisted).forEach(function (key) {
      if (!threadStore()[key]) threadStore()[key] = persisted[key];
    });
    var seededThreads = safeArray(chat.threads).length ? safeArray(chat.threads) : safeArray(blueprint.threads).map(function (thread, index) {
      return {
        thread_id: state.activePersona + ":" + firstDefined(thread.key, "thread-" + (index + 1)),
        title: firstDefined(thread.title, "Thread"),
        preview: firstDefined(thread.preview, blueprint.brief, "Board-safe follow-up"),
        starter_prompt: firstDefined(thread.preview, thread.title, ""),
        read_only: false,
        kind: "starter"
      };
    });
    seededThreads.forEach(function (thread, index) {
      var key = firstDefined(thread.thread_id, state.activePersona + ":" + firstDefined(thread.key, "thread-" + (index + 1)));
      if (!threadStore()[key]) {
        var initial = {
          role: "assistant",
          text: assistantName + " is holding the room in " + getPersonaLabel(state.activePersona) + " mode. Ask for the next governed move, the board-safe summary, or the evidence gap.",
          timestamp: new Date().toISOString()
        };
        if (thread.kind === "system") {
          initial.text = firstDefined(thread.preview, "Governed run status is attached here.");
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

  function ensureWritableThread(seedTitle, seedPreview) {
    ensureThreads();
    var current = threadStore()[currentThreadKey()];
    if (current && !current.readOnly) return current;
    return createWritableThread(seedTitle, seedPreview);
  }

  function createWritableThread(seedTitle, seedPreview) {
    var blueprint = getPersonaBlueprint(state.activePersona);
    var persona = getPersonaContract(state.activePersona);
    var assistantName = firstDefined((getChatContract().assistant || {}).name, persona.assistant, blueprint.assistant, "Hermes");
    var key = state.activePersona + ":followup-" + Date.now();
    var preview = String(firstDefined(seedPreview, "Writable board-safe thread.")).trim();
    threadStore()[key] = {
      key: key,
      title: seedTitle || ("New conversation · " + nowStamp()),
      preview: preview || "Writable board-safe thread.",
      route: state.activePersona === "ceo" ? "" : firstDefined(getPublication().preview_route, "/public/runs/latest/report-preview"),
      readOnly: false,
      kind: "followup",
      assistant: firstDefined((getChatContract().assistant || {}).name, assistantName),
      messages: [
        {
          role: "assistant",
          text: "This writable thread inherits the governed packet and keeps follow-up bounded to the current room.",
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
    var message = { role: role, text: text, timestamp: new Date().toISOString() };
    thread.messages.push(message);
    thread.preview = String(text || thread.preview || "").slice(0, 84);
    thread.lastUpdated = new Date().toISOString();
    saveStoredThreads();
    return message;
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

  function renderTopbar() {
    var activePersona = getPersonaContract(state.activePersona);
    var blueprint = getPersonaBlueprint(state.activePersona);
    var org = $("brand-org");
    var personaLabel = $("persona-label");
    var list = $("pm-list");
    var btn = $("persona-btn");
    var viewNav = $("view-nav");
    var launcher = $("chat-launcher-cta");
    var launcherPrompt = document.querySelector("#chat-launcher .chat-launcher__prompt");
    var userName = $("topbar-user-name");
    var userRole = $("topbar-user-role");
    var avatar = $("topbar-avatar");
    var userMeta = document.querySelector("#topbar-user .tb-user-meta");
    var assistantName = firstDefined(activePersona.assistant, blueprint.assistant, "Hermes");
    var assistantGlyph = firstDefined(activePersona.assistant_glyph, blueprint.assistantGlyph, "◆");
    var initials = executiveIdentityInitials(state.activePersona);

    if (org) org.textContent = "Mizan Group";
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
        tip.innerHTML = '<div class="avatar-tooltip-head"><span class="avatar avatar-lg">' + escapeHtml(initials) + '</span><div><strong>' + escapeHtml(firstDefined(activePersona.label, 'Group CEO')) + '</strong><span>' + escapeHtml(assistantName) + ' · governed run</span></div></div><div class="avatar-tooltip-actions"><button type="button" class="avatar-tooltip-action" data-avatar-action="profile">Profile &amp; settings</button><button type="button" class="avatar-tooltip-action" data-avatar-action="switch">Switch persona</button><button type="button" class="avatar-tooltip-action" data-avatar-action="theme">' + escapeHtml(themeIcon) + ' ' + escapeHtml(themeLabel) + ' theme</button>' + feedbackAction + '</div>';
        avatar.parentNode.appendChild(tip);
        var outsideClick = function (event) {
          if (!event.target.closest('#topbar-user')) { tip.remove(); document.removeEventListener('click', outsideClick); }
        };
        window.setTimeout(function () { document.addEventListener('click', outsideClick); }, 0);
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
    if (nav) nav.hidden = state.activePersona === "board";
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
    if (driverHeading) driverHeading.textContent = firstDefined(blueprint.indexLabel, "The group index");
    if (driverHint) driverHint.textContent = "All figures: % of plan";
    if (lowerHeading) lowerHeading.textContent = "What matters now";
    var footer = $("composed-footer");
    if (footer) footer.hidden = false;
  }

  function renderAssistantNetwork() {
    var card = $("assistant-network-card");
    var meta = getAssistantNetworkMeta();
    var network = getAssistantNetwork().slice().sort(function (left, right) {
      return Number(right.score || 0) - Number(left.score || 0);
    });
    if (card) {
      var avg = network.length ? Math.round(network.reduce(function (sum, item) { return sum + Number(item.score || 0); }, 0) / network.length) : 0;
      var stale = network.filter(function (item) { return Number(item.score || 0) < 70; }).length;
      card.innerHTML = [
        '<div class="detail-head"><div><p class="detail-eyebrow">Assistant network</p><h3 class="detail-title">' + escapeHtml(firstDefined(meta.label, 'Assistant Network')) + '</h3><p class="section-note">' + escapeHtml(firstDefined(meta.hint, 'A read on current usage, freshness, and context depth across Mizan.')) + '</p></div><span class="pill-inline ok">target ' + escapeHtml(String(firstDefined(meta.target, 80))) + '+</span></div>',
        '<div class="network-summary"><div class="network-score"><strong>' + escapeHtml(String(avg)) + '</strong><span>Team readiness score</span></div><div class="network-meta"><span class="pill-inline ok">Healthy</span><span class="pill-inline warn">Check-in needed</span><span class="pill-inline danger">Stale · ' + escapeHtml(String(stale)) + ' leader' + (stale !== 1 ? 's' : '') + '</span></div></div>',
        '<div class="network-list">' + network.map(function (item) {
          return '<div class="network-row"><div class="network-score-badge tone-' + toneClass(item.tone) + '"><strong>' + escapeHtml(String(firstDefined(item.score, 0))) + '</strong></div><div class="network-row__main"><div class="network-row__head"><strong>' + escapeHtml(firstDefined(item.assistant, 'Assistant')) + '</strong><span>· ' + escapeHtml(firstDefined(item.who, 'Leader')) + '</span></div><p class="list-copy">' + escapeHtml(firstDefined(item.unit, 'Mizan Group')) + '</p></div><div class="network-stats"><span><small>freshness</small>' + escapeHtml(firstDefined(item.freshness, 'current')) + '</span><span><small>used</small>' + escapeHtml(firstDefined(item.usage, 'active')) + '</span><span><small>context</small>' + escapeHtml(firstDefined(item.depth, 'good')) + '</span></div></div>';
        }).join('') + '</div>'
      ].join('');
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

    if (fabText) fabText.textContent = assistantName + " ↔ assistants";
    if (title) title.textContent = assistantName + " ↔ assistant network";
    if (subtitle) subtitle.textContent = "Your chief of staff, gathering for you · live";
    if (fabBadge) {
      fabBadge.hidden = !liveCount;
      fabBadge.textContent = String(liveCount || 0);
    }
    if (fab) {
      fab.setAttribute("aria-expanded", state.a2aOpen ? "true" : "false");
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
      return '<button type="button" class="a2a-tab' + (exchange.id === active.id ? ' is-active' : '') + '" data-a2a-id="' + escapeHtml(exchange.id) + '"><span class="a2a-dot ' + escapeHtml(status.toLowerCase()) + '"></span>' + escapeHtml(firstDefined(exchange.with, 'Assistant')) + '<span class="a2a-tab-unit"> · ' + escapeHtml(firstDefined(exchange.unit, 'Mizan lane')) + '</span></button>';
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
  var KG_CATEGORY_COLORS = {
    plan: "#25335c", KPI: "#1a6e54", business_unit: "#8c6a3d", finding: "#9b3434",
    document: "#6b4c9a", vendor: "#2d7d9a", invoice: "#b85c1e", contract: "#4a7c59"
  };
  var KG_CATEGORY_LABELS = {
    plan: "Board Plan", KPI: "KPI", business_unit: "Business Unit", finding: "Finding",
    document: "Document", vendor: "Vendor", invoice: "Invoice", contract: "Contract"
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
    }).filter(Boolean);
    panel.innerHTML =
      '<button type="button" class="kg-inspector__close" aria-label="Close inspector" id="kg-inspector-close">&times;</button>' +
      '<span class="kg-inspector__badge" style="background:' + escapeHtml(getCategoryColor(node)) + ';color:#fff">' + escapeHtml(firstDefined(node.category, "Node")) + '</span>' +
      '<h3 class="kg-inspector__title" id="kg-inspector-title">' + escapeHtml(firstDefined(node.label, "Node")) + '</h3>' +
      '<p class="kg-inspector__meta">' + escapeHtml(firstDefined(KG_CATEGORY_LABELS[node.category], node.category || "Node")) + ' &middot; Connected to ' + connectedIds.length + ' nodes</p>' +
      '<p class="kg-inspector__detail">' + escapeHtml(firstDefined(node.detail, "No additional detail available.")) + '</p>' +
      (connectedLabels.length ? '<div class="kg-inspector__connections"><span class="kg-inspector__connections-label">Connected to</span>' + connectedLabels.map(function (l) { return '<span class="kg-inspector__conn-chip">' + l + '</span>'; }).join('') + '</div>' : '') +
      '<button type="button" class="kg-inspector__ask" id="kg-inspector-ask">Ask Hermes about this &rarr;</button>';
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
  function renderKnowledgeGraph() {
    var graph = getKnowledgeGraph();
    if (!card) return;
    var focusQuestion = graph.questions[state.knowledgeQuestionIndex || 0] || null;
    var focused = focusQuestion ? new Set(safeArray(focusQuestion.focus)) : null;
    var nodes = safeArray(graph.nodes);
    var nodeMap = {};
    nodes.forEach(function (node) { nodeMap[node.id] = node; });

    /* ── Build category color lookup ── */
    var catColors = {};
    nodes.forEach(function (n) {
      if (n.category) catColors[n.category] = KG_CATEGORY_COLORS[n.category] || "var(--accent)";
    });

    var isSelected = state._kgSelectedNodeId || null;

    card.innerHTML =
      '<div class="detail-head"><div><p class="detail-eyebrow">Knowledge graph</p><h3 class="detail-title">Board Intelligence Map</h3><p class="section-note">Showing how the system reasons across your evidence.</p></div><span class="pill-inline ok">Data relationships</span></div>'
      + '<div class="kg-questions" role="tablist" aria-label="Question lenses">' + safeArray(graph.questions).map(function (question, index) {
        var active = focusQuestion && focusQuestion.id === question.id;
        var focusCount = safeArray(question.focus).length;
        return '<button type="button" class="kg-question' + (active ? ' is-active' : '') + '" role="tab" aria-selected="' + (active ? 'true' : 'false') + '" data-kg-question="' + index + '"><span class="kg-question__dot" aria-hidden="true"></span>' + escapeHtml(firstDefined(question.label, 'Question')) + '<span class="kg-question__count">' + focusCount + '</span></button>';
      }).join('') + '</div>'
      + '<div class="kg-stage" tabindex="0" role="application" aria-label="Board Intelligence Map — interactive knowledge graph. Use arrow keys to explore connected nodes, Enter to open details.">'
      + '<svg viewBox="0 0 100 88" class="kg-svg" aria-hidden="true">'
      /* Edges */
      + safeArray(graph.edges).map(function (edge) {
        var from = nodeMap[edge[0]];
        var to = nodeMap[edge[1]];
        if (!from || !to) return '';
        var mx = ((Number(from.x || 0) + Number(to.x || 0)) / 2).toFixed(1);
        var my = (((Number(from.y || 0) + Number(to.y || 0)) / 2) - 4).toFixed(1);
        var active = !focused || (focused.has(edge[0]) && focused.has(edge[1]));
        return '<path class="kg-edge' + (active ? ' on' : '') + '" data-kg-from="' + escapeHtml(edge[0]) + '" data-kg-to="' + escapeHtml(edge[1]) + '" d="M' + escapeHtml(String(from.x)) + ',' + escapeHtml(String(from.y)) + ' Q' + escapeHtml(mx) + ',' + escapeHtml(my) + ' ' + escapeHtml(String(to.x)) + ',' + escapeHtml(String(to.y)) + '"></path>';
      }).join('')
      /* Nodes */
      + nodes.map(function (node) {
        var active = !focused || focused.has(node.id);
        var sizeClass = "";
        var nr = Number(node.r || 8);
        if (nr >= 12) sizeClass = " kg-node--major";
        else if (nr <= 7) sizeClass = " kg-node--minor";
        var selClass = (isSelected === node.id) ? " is-selected" : "";
        return '<g class="kg-node' + (active ? ' on' : ' off') + sizeClass + selClass + '" data-kg-id="' + escapeHtml(node.id) + '" tabindex="0" role="button" aria-label="' + escapeHtml(firstDefined(node.label, 'Node')) + ' — ' + escapeHtml(firstDefined(KG_CATEGORY_LABELS[node.category], node.category || 'node')) + '"><circle class="kg-node-dot kg-node-dot--' + escapeHtml(node.category || 'default') + '" cx="' + escapeHtml(String(node.x)) + '" cy="' + escapeHtml(String(node.y)) + '" r="' + escapeHtml(String(Math.max(2.8, nr / 2.4))) + '"></circle></g>';
      }).join('')
      + '</svg>'
      /* Labels overlaid on SVG */
      + '<div class="kg-labels">' + nodes.map(function (node) {
        var active = !focused || focused.has(node.id);
        return '<span class="kg-label' + (active ? ' on' : ' off') + '" data-kg-label-id="' + escapeHtml(node.id) + '" style="left:' + escapeHtml(String(node.x)) + '%;top:' + escapeHtml(String(node.y)) + '%"><span class="kg-label__dot" style="background:' + escapeHtml(getCategoryColor(node)) + '" aria-hidden="true"></span>' + escapeHtml(firstDefined(node.label, 'Node')) + '</span>';
      }).join('') + '</div>'
      /* Legend */
      + '<div class="kg-legend" aria-label="Node category legend">' + Object.keys(KG_CATEGORY_COLORS).map(function (cat) {
        return '<span class="kg-legend__item"><span class="kg-legend__swatch" style="background:' + escapeHtml(KG_CATEGORY_COLORS[cat]) + '" aria-hidden="true"></span>' + escapeHtml(firstDefined(KG_CATEGORY_LABELS[cat], cat)) + '</span>';
      }).join('') + '</div>'
      + '</div>';

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
        if (e.target === stage || e.target.classList.contains("kg-svg")) {
          closeNodeInspector();
        }
      });
    }
  }

  function renderHero() {
    var diagnostics = getExecutiveDiagnostics();
    var blueprint = getPersonaBlueprint(state.activePersona);
    var hero = diagnostics.hero || {};
    var publication = getPublication();
    var boardPortal = getBoardPortal();
    var agents = getAgentsModule();
    var networkEntry = getAssistantNetwork().find(function (item) { return item && item.persona === state.activePersona; }) || {};
    var fullName = String(firstDefined(networkEntry.who, state.activePersona === "ceo" ? "Khalid Al-Rashed" : "")).trim();
    var firstName = fullName ? fullName.split(/\s+/)[0] : getPersonaLabel(state.activePersona);
    var preferredHero = blueprint.health || {};
    var score = Number(firstDefined(hero.score, 0));
    if (preferredHero && preferredHero.score !== undefined && preferredHero.score !== null && preferredHero.score !== "") {
      score = Number(preferredHero.score);
    }
    var clampedScore = Math.max(0, Math.min(100, score));
    var circumference = 2 * Math.PI * 48;
    var dash = circumference * (clampedScore / 100);
    var prompts = getHeroPrompts();
    var miniStats = [
      { label: "Board state", value: statusLabel(firstDefined(state.activeBoard, boardPortal.presentation_state, boardPortal.state, "pre")) },
      { label: "Reports", value: String(firstDefined(publication.report_count, 0)) + (state.activePersona === "ceo" ? " reports ready" : " surfaced") },
      { label: "Agents", value: String(firstDefined((agents.summary || {}).running_count, diagnostics.agents && diagnostics.agents.running_count, 0)) + (state.activePersona === "ceo" ? " agents active" : " running") },
      { label: state.activePersona === "ceo" ? "Needs review" : "Next move", value: state.activePersona === "ceo" ? String(firstDefined(publication.challenged_cases, safeArray((getDrilldown().owed_upward || {}).items).length, 0)) + " items need review" : humanizeToken(firstDefined(getPlanHealth().next_action, (boardPortal.state_detail || {}).title, "review")) }
    ];

    $("hero-eyebrow").textContent = state.activePersona === "board"
      ? "Board portal · governed packet posture"
      : "Good morning, " + firstName;
    $("hero-head").textContent = firstDefined(preferredHero.headline, hero.summary, hero.label, getPlanHealth().label, "Plan health overview");
    $("hero-body").textContent = firstDefined(preferredHero.body, hero.body, getPlanHealth().summary, "Awaiting executive diagnostics.");
    $("hero-score").textContent = String(clampedScore || 0);
    $("hero-cap").textContent = firstDefined(preferredHero.scoreNote, hero.score_note, getPlanHealth().badge, "plan health");
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
      var dotCx = 60 + 48 * Math.sin(angleRad);
      var dotCy = 60 - 48 * Math.cos(angleRad);
      dot.setAttribute("cx", String(Math.round(dotCx * 10) / 10));
      dot.setAttribute("cy", String(Math.round(dotCy * 10) / 10));
      dot.style.visibility = "visible";
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
      tile.innerHTML = [
        '<div class="driver-ring-stage">' + driverRingMarkup(driver) + '<div class="driver-ring-copy"><div class="driver-pct">' + escapeHtml(firstDefined(driver.pct, '—')) + '<span class="pct-sign">%</span></div></div>' + (Number(firstDefined(driver.pct, 0)) > 100 ? '<span class="driver-over-plan">+' + Math.round(Number(firstDefined(driver.pct, 0)) - 100) + '% vs plan</span>' : '') + '</div>',
        '<div class="driver-meta"><strong class="driver-label">' + escapeHtml(firstDefined(driver.label, "Driver")) + '</strong><div class="driver-foot">' + escapeHtml(firstDefined(driver.metric, '—')) + '<span class="driver-sub"> · ' + escapeHtml(firstDefined(driver.sub, "current measure")) + '</span></div></div>'
      ].join("");
      tile.onclick = function () {
        state.activeDriverKey = key;
        updateHistory();
        renderDriverGrid();
        renderDriverDrillFidelity();
        renderSummary();
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
        value: firstDefined(driver.label, getPlanHealth().label, "Awaiting packet"),
        detail: firstDefined(driver.detail, getPlanHealth().summary, "No governed driver summary yet.")
      },
      {
        label: "Board lifecycle",
        value: statusLabel(firstDefined(state.activeBoard, boardPortal.presentation_state, boardPortal.state, "pre")),
        detail: firstDefined((boardPortal.state_detail || {}).summary, "Board-safe lifecycle stays explicit.")
      },
      {
        label: "Evidence closure",
        value: String(firstDefined((drilldown.owed_upward || {}).challenge_count, publication.challenged_cases, 0)) + " challenged",
        detail: "Questions stay attached to evidence, not theatre."
      },
      {
        label: "Report surface",
        value: String(firstDefined(publication.report_count, 0)) + " routes",
        detail: firstDefined(publication.preview_route, "Board pack preview waits for the current governed packet.")
      }
    ];
    grid.innerHTML = metrics.map(function (metric) {
      return '<article class="metric-card"><span class="metric-label">' + escapeHtml(metric.label) + '</span><strong class="metric-value">' + escapeHtml(metric.value) + '</strong><p class="metric-detail">' + escapeHtml(metric.detail) + '</p></article>';
    }).join("");
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
    if (drillCard) {
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
        '<div class="drill-headline"><div><h3 class="detail-title">What\'s driving ' + escapeHtml(firstDefined(driver.label, 'it')) + '</h3><p class="section-note">' + escapeHtml(String(firstDefined(driver.pct, '—')) + '% of plan · ' + firstDefined(driver.metric, '—') + ' · ' + firstDefined(driver.sub, 'current measure')) + '</p></div><button class="assistant-tool-chip assistant-tool-chip--button" type="button" data-driver-show-work="true">Show the work</button></div>',
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
          var prompt = 'On ' + firstDefined(driver.label, 'this driver') + ' (' + firstDefined(driver.pct, '\u2014') + '% of plan): ' + (button.getAttribute('data-driver-chip') || '');
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
          var prompt = 'On ' + firstDefined(driver.label, 'this driver') + ' (' + firstDefined(driver.pct, '—') + '% of plan): ' + message;
          askAssistant(prompt);
          input.value = '';
        });
      }
    }
    if (gravityPanel) {
      var vlogs = [
        { id: 'uTRKdCY4HdE', title: 'Enterprise AI Strategy and CEO Leadership', speaker: 'McKinsey & Company', theme: 'CEO leadership · enterprise AI strategy', dur: '~45 min', summary: 'CXOTalk #851: How CEOs should think about AI strategy, governance, and organizational alignment.', transcript: 'Full discussion on CEO-level AI strategy: moving from experimentation to enterprise-wide adoption, building AI governance frameworks, and aligning AI initiatives with business strategy.' },
        { id: 'sFSzPE2AOE0', title: 'Aligning AI with Enterprise Strategy', speaker: 'Leon Gordon, CEO at Onyx Data', theme: 'AI & data strategy alignment', dur: '~40 min', summary: 'How organizations can bridge the gap between AI capabilities and strategic goals.', transcript: 'Leon Gordon shares frameworks for aligning AI initiatives with enterprise strategy: data maturity assessment, capability mapping, and building a data-driven culture.' },
        { id: 'pQtdQ6AHn_Q', title: 'Agentic AI Governance and Enterprise-Scale Execution', speaker: 'Industry Panel', theme: 'governance · data quality · enterprise execution', dur: '~50 min', summary: 'Governance models for agentic AI systems, data quality requirements, and scaling patterns.', transcript: 'Panel discussion: agentic AI governance control frameworks, data quality pipelines, human-in-the-loop patterns, and scaling AI execution while maintaining compliance.' },
        { id: 't885M1WB1pg', title: 'Bridge Strategy and Execution with Decision-Ready Views', speaker: 'Strategy Execution Webinar', theme: 'strategy execution · decision-ready views', dur: '~35 min', summary: 'Creating decision-ready views that connect strategic plans to operational execution.', transcript: 'Building decision-ready dashboards, connecting plans to operations, and creating feedback loops that keep strategy alive.' }
      ];
      gravityPanel.innerHTML = [
        '<div class="detail-head"><div><h3 class="detail-title">Explore scenarios</h3><p class="section-note">Ask what-if questions on your live data</p></div></div>',
        '<div class="gravity-grid-v2"><section class="gravity-play-card">' + safeArray(gravity.prompts).slice(0, 3).map(function (prompt) { return '<button class="timeline-chip" type="button" data-chat-prompt="' + escapeHtml(prompt) + '"><strong>' + escapeHtml(prompt) + '</strong><span>Send to assistant</span></button>'; }).join('') + '</section><section class="leaders-card"><div class="leaders-badge">Leaders\' Corner</div><div class="leaders-title">Short counsel, senior practitioners</div><div class="leaders-featured"><div class="leaders-fallback-card" id="leaders-featured-fallback"><p class="leaders-fallback-icon">▶</p><p class="leaders-fallback-msg">Select a video below</p><p class="leaders-fallback-detail">' + escapeHtml(vlogs[0].title) + ' — ' + escapeHtml(vlogs[0].speaker) + '</p></div><div class="video-frame-wrapper" id="leaders-frame-wrapper" hidden><iframe id="leaders-featured-iframe" src="" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share; fullscreen" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen title=""></iframe></div></div><div class="leaders-video-info" id="leaders-video-info"><h4>' + escapeHtml(vlogs[0].title) + '</h4><p class="leaders-video-speaker">' + escapeHtml(vlogs[0].speaker) + '</p><span class="leaders-video-theme">' + escapeHtml(vlogs[0].theme) + '</span><p class="leaders-video-summary">' + escapeHtml(vlogs[0].summary) + '</p><details><summary>Summary</summary><p>' + escapeHtml(vlogs[0].transcript) + '</p></details><div class="leaders-video-ctas"><button class="leaders-hermes-cta" id="leaders-hermes-cta">Ask Hermes about this topic</button><a class="leaders-yt-link" href="https://www.youtube.com/watch?v=' + escapeHtml(vlogs[0].id) + '" target="_blank" rel="noopener">Open on YouTube ↗</a></div></div>' +
        vlogs.slice(1).map(function (v, i) { return '<div class="leaders-thumb" data-video-id="' + escapeHtml(v.id) + '" tabindex="0" role="button"><span class="leaders-thumb__img">▶</span><span class="leaders-thumb__title">' + escapeHtml(v.title) + '</span><span class="leaders-thumb__speaker">' + escapeHtml(v.speaker) + ' · ' + escapeHtml(v.dur) + '</span></div>'; }).join('') +
        '</section></div>'
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
      // Inline embed fallback timer is now handled in selectLeadersVideo; skip initial timer since we start with fallback card
    }
  }

  function selectLeadersVideo(item, vlogs, leadersCard) {
    if (!leadersCard) return;
    var fallback = leadersCard.querySelector('#leaders-featured-fallback');
    var frameWrapper = leadersCard.querySelector('#leaders-frame-wrapper');
    var iframe = leadersCard.querySelector('#leaders-featured-iframe');
    var info = leadersCard.querySelector('#leaders-video-info');
    var thumbGrid = leadersCard.querySelector('#leaders-thumb-grid');

    // Show iframe wrapper, hide fallback
    if (fallback) fallback.hidden = true;
    if (frameWrapper) frameWrapper.hidden = false;

    if (iframe) {
      iframe.src = 'https://www.youtube-nocookie.com/embed/' + escapeHtml(item.id) + '?origin=' + encodeURIComponent(window.location.origin) + '&enablejsapi=1&rel=0&modestbranding=1';
      iframe.setAttribute('title', item.title);
      iframe.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
      iframe.setAttribute('allow', 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share; fullscreen');
      // Reset fallback timer on video switch
      if (_leadersFallbackTimer) {
        window.clearTimeout(_leadersFallbackTimer);
        _leadersFallbackTimer = null;
      }
      _leadersFallbackTimer = window.setTimeout(function () {
        if (frameWrapper && iframe) {
          iframe.src = '';
          frameWrapper.hidden = true;
          if (fallback) {
            fallback.hidden = false;
            fallback.innerHTML = '<p class="leaders-fallback-icon">▶</p><p class="leaders-fallback-msg">This video is not available inline.</p><p class="leaders-fallback-detail">' + escapeHtml(item.title) + '</p><a class="leaders-fallback-link" href="https://www.youtube.com/watch?v=' + escapeHtml(item.id) + '" target="_blank" rel="noopener">Open on YouTube ↗</a>';
          }
        }
      }, 4000);
      iframe.addEventListener('load', function () {
        if (_leadersFallbackTimer) {
          window.clearTimeout(_leadersFallbackTimer);
          _leadersFallbackTimer = null;
        }
      }, { once: true });
    }

    if (info) {
      info.innerHTML = '<h4>' + escapeHtml(item.title) + '</h4><p class="leaders-video-speaker">' + escapeHtml(item.speaker) + '</p><span class="leaders-video-theme">' + escapeHtml(item.theme) + '</span><p class="leaders-video-summary">' + escapeHtml(item.summary) + '</p><details><summary>Summary</summary><p>' + escapeHtml(item.transcript) + '</p></details><div class="leaders-video-ctas"><button class="leaders-hermes-cta" id="leaders-hermes-cta">Ask Hermes about this topic</button><a class="leaders-yt-link" href="https://www.youtube.com/watch?v=' + escapeHtml(item.id) + '" target="_blank" rel="noopener">Open on YouTube ↗</a></div>';
      var hermesCta = info.querySelector('#leaders-hermes-cta');
      if (hermesCta) {
        hermesCta.onclick = function () {
          askAssistant('From the Leaders\' Corner video "' + item.title + '" — how does this apply to our strategy?', hermesCta);
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

  function renderBoardStateTabs() {
    var row = $("board-state-row");
    var board = getBoardPortal();
    var modes = safeArray(board.lifecycle_flow).length ? safeArray(board.lifecycle_flow) : (((state.latestPacket || {}).executive_modes || {}).board_states || []);
    var note = $("board-state-note");
    if (!row) return;
    row.innerHTML = "";
    safeArray(modes).forEach(function (mode) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "state-tab" + (mode.state_id === state.activeBoard ? " is-active" : "");
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", mode.state_id === state.activeBoard ? "true" : "false");
      button.innerHTML = '<span class="state-tab__copy"><strong>' + escapeHtml(firstDefined(mode.label, mode.state_id)) + '</strong><span>' + escapeHtml(firstDefined(mode.summary, mode.detail, "")) + '</span></span>';
      button.onclick = function () {
        if (state.activeBoard === mode.state_id) return;
        state.activeBoard = mode.state_id;
        animateCard("board-portal");
        refresh(true);
      };
      row.appendChild(button);
    });
    if (note) note.textContent = firstDefined((board.state_detail || {}).summary, "Board lifecycle stays explicit from pre-board preparation through frozen close.");
  }

  function renderBoardPortal() {
    var board = getBoardPortal();
    var portal = $("board-portal");
    var note = $("board-note");
    if (note) note.textContent = firstDefined(board.governance_note, "Board-safe lifecycle, materials, and governed memory.");
    if (!portal) return;

    var decks = safeArray(board.decks).slice(0, 4);
    var actions = safeArray(board.actions).slice(0, 3);
    var questions = safeArray(board.supplementary_questions).slice(0, 3);
    var lifecycle = safeArray(board.lifecycle_flow);
    var deckRelease = board.deck_release || {};
    var snapshot = board.frozen_snapshot || {};
    var stateDetail = board.state_detail || {};
    var boardState = String(firstDefined(state.activeBoard, board.presentation_state, board.state, 'pre')).toLowerCase();
    var stateSpecific = '';
    if (boardState === 'pre') {
      stateSpecific = '<div class="board-mode-grid"><section class="board-panel"><p class="detail-eyebrow">CEO-approved material</p><div class="mini-list">' + (decks.length ? decks.map(function (item) {
        return '<div class="board-deck"><div><strong>' + escapeHtml(firstDefined(item.title, 'Deck')) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(item.by, item.tag, 'Board material')) + '</p></div><span class="pill-inline ' + toneClass(item.status) + '">' + escapeHtml(firstDefined(item.status, item.pages ? item.pages + ' pages' : 'ready')) + '</span></div>';
      }).join('') : '<div class="discovery-empty">No board material is released yet.</div>') + '</div></section><section class="board-panel"><p class="detail-eyebrow">Supplementary questions</p><div class="mini-list">' + (questions.length ? questions.map(function (item) {
        return '<div class="board-deck"><div><strong>' + escapeHtml(firstDefined(item.q, 'Question')) + '</strong><p class="list-copy">to ' + escapeHtml(firstDefined(item.to, 'board lane')) + '</p></div><span class="pill-inline ' + toneClass(item.status) + '">' + escapeHtml(firstDefined(item.status, 'governed')) + '</span></div>';
      }).join('') : '<div class="discovery-empty">No supplementary questions are attached to this lifecycle state.</div>') + '</div></section></div>';
    } else if (boardState === 'live') {
      stateSpecific = '<div class="board-live-card"><div class="board-live-card__head"><strong>Live session · Q&amp;A on approved material</strong><span>' + escapeHtml(assistantNameForState()) + ' answers only from the CEO-approved pack</span></div><div class="board-live-card__status"><span class="live-pulse"></span><strong>In session</strong><span>' + escapeHtml(firstDefined((board.meeting || {}).title, 'Board meeting')) + '</span></div><div class="pill-row">' + ['Why is EBITDA 20 bps under plan?', 'Show the hedge downside', 'Is the JV funded from cash?'].map(function (prompt) { return '<button class="prompt-chip" type="button" data-board-prompt="' + escapeHtml(prompt) + '">' + escapeHtml(prompt) + '</button>'; }).join('') + '</div></div>';
    } else {
      stateSpecific = '<div class="board-mode-grid"><section class="board-panel"><p class="detail-eyebrow">Meeting summary &amp; action plan</p><p class="board-copy">' + escapeHtml(firstDefined(board.summary, snapshot.summary, 'Closed meetings retain a bounded frozen snapshot.')) + '</p><div class="mini-list">' + (actions.length ? actions.map(function (item) {
        return '<div class="board-action"><div><strong>' + escapeHtml(firstDefined(item.item, 'Action')) + '</strong><small>' + escapeHtml(firstDefined(item.owner, 'Owner')) + '</small></div><span class="pill-inline warn">' + escapeHtml(firstDefined(item.due, 'next')) + '</span></div>';
      }).join('') : '<div class="discovery-empty">No closed-state actions are attached yet.</div>') + '</div></section><section class="board-panel frozen-panel"><p class="detail-eyebrow">Frozen snapshot</p><strong>' + escapeHtml(humanizeToken(firstDefined(snapshot.status, 'live_packet'))) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(snapshot.summary, 'Between meetings, the board room only sees the frozen snapshot.')) + '</p><button class="timeline-chip" type="button" data-board-prompt="Model a what-if on the frozen board snapshot: if EUR strengthens 5%, what was the hedged outcome?"><strong>◇ What-if on the snapshot</strong><span>No live org data reaches the board</span></button></section></div>';
    }
    portal.innerHTML = [
      '<div class="board-head"><div><p class="detail-eyebrow">Reports</p><h3 class="board-title">' + escapeHtml(firstDefined((board.state_detail || {}).title, board.state_label, "Governed board packet")) + '</h3><p class="board-copy">' + escapeHtml(firstDefined((board.state_detail || {}).summary, board.board_summary, "Board posture stays bounded to the current packet.")) + '</p></div><span class="pill-inline ' + toneClass(statusLabel(firstDefined(board.presentation_state, board.state, "pre"))) + '">' + escapeHtml(statusLabel(firstDefined(board.state_label, board.presentation_state, board.state, "pre"))) + '</span></div>',
      '<div class="board-kpis">' + safeArray(board.kpis).slice(0, 4).map(function (item) {
        return '<div class="board-kpi"><span class="board-kpi__label">' + escapeHtml(firstDefined(item.label, "Metric")) + '</span><strong class="board-kpi__value">' + escapeHtml(firstDefined(item.value, item.pct, "—")) + '</strong><span class="board-kpi__sub">' + escapeHtml(firstDefined(item.sub, item.pct ? String(item.pct) + "%" : "Governed packet")) + '</span></div>';
      }).join("") + '</div>',
      '<div class="board-state-stack">' + lifecycle.map(function (item) {
        var flags = [];
        if (item.actual) flags.push('<span class="pill-inline ok">actual</span>');
        if (item.presented) flags.push('<span class="pill-inline warn">presented</span>');
        if (item.next_action) flags.push('<span class="pill-inline">' + escapeHtml(humanizeToken(item.next_action)) + '</span>');
        return '<div class="lifecycle-step' + (item.presented ? ' is-presented' : '') + '"><div><strong>' + escapeHtml(firstDefined(item.label, item.state_id, 'State')) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(item.detail, 'Governed board posture.')) + '</p></div><div class="lifecycle-step__flags">' + flags.join('') + '</div></div>';
      }).join("") + '</div>',
      '<div class="snapshot-grid"><div class="snapshot-card" data-snapshot="deck" title="Click for details"><strong>Deck release</strong><span>' + escapeHtml(statusLabel(firstDefined(deckRelease.status, 'pending'))) + '</span><span class="panel-note">' + escapeHtml(String(firstDefined(deckRelease.report_count, 0)) + ' surfaced report(s)' + (state.activePersona !== "ceo" ? ' \u00b7 ' + firstDefined(deckRelease.preview_route, '/public/runs/latest/report-preview') : '')) + '</span></div><div class="snapshot-card" data-snapshot="frozen" title="Click for details"><strong>Frozen snapshot</strong><span>' + escapeHtml(statusLabel(firstDefined(snapshot.status, 'live_packet'))) + '</span><span class="panel-note">' + escapeHtml(firstDefined(snapshot.summary, 'Closed meetings retain a bounded frozen snapshot.')) + '</span></div></div>',
      (state.activePersona === "ceo"
        ? '<div class="board-action-grid">' + safeArray(stateDetail.primary_actions).slice(0, 2).map(function (item) {
            return '<button class="assistant-tool-chip assistant-tool-chip--button" type="button" data-board-action="' + escapeHtml(String(item)) + '">Review: ' + escapeHtml(humanizeToken(item)) + '</button>';
          }).join("") + '</div>'
        : '<div class="board-action-grid">' + safeArray(stateDetail.primary_actions).slice(0, 2).concat(safeArray(stateDetail.secondary_actions).slice(0, 2)).map(function (item) {
        return '<button class="assistant-tool-chip assistant-tool-chip--button" type="button" data-board-action="' + escapeHtml(String(item)) + '">' + escapeHtml(humanizeToken(item)) + '</button>';
      }).join("") + '</div>'),
      '<div class="board-detail-grid"><section class="board-panel"><p class="detail-eyebrow">Meeting posture</p><div class="mini-list"><div class="board-deck"><div><strong>' + escapeHtml(firstDefined((board.meeting || {}).design_title, (board.meeting || {}).title, "Board meeting")) + '</strong><p class="list-copy">' + escapeHtml(firstDefined((board.meeting || {}).date, (board.meeting || {}).when, "Board timing pending")) + '</p></div><span class="pill-inline ok">' + escapeHtml(firstDefined((board.meeting || {}).room, "board-safe")) + '</span></div></div></section><section class="board-panel"><p class="detail-eyebrow">Lifecycle actions</p><div class="mini-list">' + (actions.length ? actions.map(function (item) {
        return '<div class="board-action"><div><strong>' + escapeHtml(firstDefined(item.item, "Action")) + '</strong><small>' + escapeHtml(firstDefined(item.owner, "Owner")) + '</small></div><span class="pill-inline warn">' + escapeHtml(firstDefined(item.due, "next")) + '</span></div>';
      }).join("") : '<div class="discovery-empty">No lifecycle actions are attached to this state.</div>') + '</div></section></div>',
      stateSpecific
    ].join("");
    safeArray(portal.querySelectorAll('[data-board-prompt]')).forEach(function (button) {
      button.onclick = function () {
        var prompt = button.getAttribute('data-board-prompt') || '';
        askAssistant(prompt, button);
      };
    });
    safeArray(portal.querySelectorAll('[data-board-action]')).forEach(function (button) {
      button.onclick = function () {
        var action = button.getAttribute('data-board-action') || '';
        var boardState = statusLabel(firstDefined(board.presentation_state, board.state, 'pre'));
        askAssistant('I need to review and act on: ' + action + ' (current board state: ' + boardState + '). What are the next steps?', button);
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
    var lowerRail = (getExecutiveDiagnostics().composition || {}).lower_rail || getDrilldown().lower_rail || {};
    var findingsPanel = $("findings-panel");
    var developmentsPanel = $("developments-panel");
    var weekPanel = $("week-panel");
    var findings = safeArray(blueprint.findings).slice(0, 3);
    var developments = safeArray(blueprint.developments).length ? safeArray(blueprint.developments).slice(0, 3) : safeArray(lowerRail.developments).slice(0, 3);
    var weekAhead = safeArray(blueprint.week).length ? safeArray(blueprint.week).slice(0, 3) : safeArray(lowerRail.week_ahead).slice(0, 3);
    var renderToggleList = function (items, kind) {
      return items.map(function (item, index) {
        var key = kind + ':' + index;
        var open = state.openDriverNoteKey === key;
        var actionPrompt = kind === 'development'
          ? 'Project the impact of “' + firstDefined(item.title, 'this development') + '” on the current plan and what I should prepare for the board.'
          : 'Explain why “' + firstDefined(item.title, 'this finding') + '” matters for the board review and what action I should consider.';
        var actionLabel = kind === 'development' ? 'Project impact on plan' : 'Ask why this matters';
        return '<button type="button" class="rail-toggle' + (open ? ' is-open' : '') + '" data-rail-toggle="' + escapeHtml(key) + '" aria-expanded="' + (open ? 'true' : 'false') + '"><span class="rail-toggle__copy"><strong>' + escapeHtml(firstDefined(item.title, kind === 'finding' ? 'Finding' : 'Development')) + '</strong><span>' + escapeHtml(firstDefined(kind === 'finding' ? item.tag : item.meta, kind === 'finding' ? 'signal' : 'update')) + '</span></span><span class="rail-toggle__plus">' + (open ? '−' : '+') + '</span></button>' + (open ? '<div class="rail-toggle__detail">' + escapeHtml(firstDefined(kind === 'finding' ? item.detail : item.impact, item.detail, 'Awaiting detail.')) + '<div class="rail-toggle__actions"><button type="button" class="rail-inline-action" data-rail-prompt="' + escapeHtml(actionPrompt) + '">' + escapeHtml(actionLabel) + '</button></div></div>' : '');
      }).join('');
    };

    if (findingsPanel) {
      findingsPanel.innerHTML = '<div class="detail-head"><div><h3 class="detail-title">Findings &amp; concerns</h3></div></div><div class="rail-toggle-list">' + renderToggleList(findings, 'finding') + '</div>';
    }

    if (developmentsPanel) {
      developmentsPanel.innerHTML = '<div class="detail-head"><div><h3 class="detail-title">Developments since you were here</h3></div></div><div class="rail-toggle-list">' + renderToggleList(developments, 'development') + '</div>';
    }

    if (weekPanel) {
      var openIndex = Math.min(state.openWeekIndex || 0, Math.max(weekAhead.length - 1, 0));
      var activeEvent = weekAhead[openIndex] || null;
      weekPanel.innerHTML = '<div class="detail-head"><div><h3 class="detail-title">Week ahead</h3></div></div><div class="week-rail-v2">' + weekAhead.map(function (item, index) {
        return '<button class="event-chip' + (index === openIndex ? ' is-open' : '') + (item.urgent ? ' urgent' : '') + '" type="button" data-week-index="' + index + '"><span class="event-day">' + escapeHtml(firstDefined(item.day, '')) + '</span><span class="event-title">' + escapeHtml(firstDefined(item.title, item.label, 'Event')) + '</span><span class="event-when">' + escapeHtml(firstDefined(item.when, item.detail, 'soon')) + '</span></button>';
      }).join('') + '</div>' + (activeEvent ? '<div class="prep"><div class="prep-head"><span class="prep-flag">⚑ prep</span> ' + escapeHtml(firstDefined(activeEvent.title, 'Event')) + ' · ' + escapeHtml(firstDefined(activeEvent.when, 'soon')) + '</div><p class="prep-body">' + escapeHtml(firstDefined(activeEvent.prep, activeEvent.foot, '')) + '</p><div class="prep-actions"><button class="timeline-chip" type="button" data-chat-prompt="Open thinking mode for “' + escapeHtml(firstDefined(activeEvent.title, 'this event')) + '”: model the options and what I should walk in having decided."><strong>Explore scenarios</strong></button><button class="timeline-chip" type="button" data-chat-prompt="For “' + escapeHtml(firstDefined(activeEvent.title, 'this event')) + '”, what data am I missing and who should I request it from?"><strong>⤓ Request missing data</strong></button></div><form class="chips-own chips-own--rail" id="week-composer"><label class="sr-only" for="week-input">Ask StrategyOS to prepare something for this event</label><input id="week-input" class="driver-input" type="text" placeholder="e.g. draft my opening line…" /><button type="submit">Send</button></form></div>' : '');
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
          askAssistant(button.getAttribute("data-chat-prompt") || "", button);
        };
      });
      var weekComposer = weekPanel.querySelector('#week-composer');
      var weekInput = weekPanel.querySelector('#week-input');
      if (weekComposer && weekInput && activeEvent) {
        weekComposer.addEventListener('submit', function (event) {
          event.preventDefault();
          var message = String(weekInput.value || '').trim();
          if (!message) return;
          askAssistant('For “' + firstDefined(activeEvent.title, 'this event') + '”: ' + message);
          weekInput.value = '';
        });
      }
    }

  }

  function renderAgentsDiscovery() {
    var activityCard = $("agents-activity");
    var runningCard = $("running-agents");
    var discoveryCard = $("discovery-panel");
    var subtoolsCard = $("subtools-panel");
    var activity = getAgentActivitySummary();
    var discoverable = getDiscoverableAgents();
    var running = getRunningAgents();
    var approvals = getApprovalAgents();
    var subtools = getSubtools();
    var combined = approvals.concat(running).sort(function (left, right) {
      var order = { approval: 0, running: 1, standing: 2, queued: 3, done: 4 };
      return Number(firstDefined(order[left && left.status], 9)) - Number(firstDefined(order[right && right.status], 9));
    });
    var nativeAgents = discoverable.filter(function (item) { return item.source === 'native'; });
    var marketAgents = discoverable.filter(function (item) { return item.source !== 'native'; });

    function statusLabel(item, approved) {
      var status = String(firstDefined(item && item.status, 'running'));
      if (status === 'approval' && approved) return 'Approved';
      if (status === 'approval') return 'Needs your approval';
      if (status === 'standing') return 'Standing watch';
      if (status === 'running') return 'Running';
      if (status === 'protected') return 'Guarded';
      if (status === 'board_safe_preview' || status === 'board_safe_publication' || status === 'preview' || status === 'preview_only') return 'View only';
      return humanizeToken(status);
    }

    if (activityCard) {
      activityCard.innerHTML = '<div class="agent-activity' + (state.agentSummaryOpen ? ' is-open' : '') + '"><button type="button" class="agent-activity-line" data-agent-summary-toggle="true"><span class="aa-spark">✦</span><span class="aa-text">' + escapeHtml(firstDefined(activity.line, 'What is working on your data right now — and a universe more to deploy.')) + '</span><span class="aa-toggle">' + (state.agentSummaryOpen ? 'hide detail' : 'view detail') + '</span></button>' + (state.agentSummaryOpen ? '<div class="aa-detail"><div class="aa-metrics">' + safeArray(activity.metrics).map(function (item) {
        return '<div class="aa-metric"><span class="aa-metric-v">' + escapeHtml(firstDefined(item.v, item.value, '0')) + '</span><span class="aa-metric-k">' + escapeHtml(firstDefined(item.k, item.label, 'metric')) + '</span></div>';
      }).join('') + '</div><ol class="aa-trail">' + safeArray(activity.log).map(function (item) { return '<li class="aa-trail-item"><span class="trail-time">' + escapeHtml(firstDefined(item.t, 'now')) + '</span><span class="aa-who">' + escapeHtml(firstDefined(item.who, 'agent')) + '</span><span class="aa-act">' + escapeHtml(firstDefined(item.a, 'activity')) + '</span></li>'; }).join('') + '</ol></div>' : '') + '</div>';
      var summaryToggle = activityCard.querySelector('[data-agent-summary-toggle]');
      if (summaryToggle) {
        summaryToggle.onclick = function () {
          state.agentSummaryOpen = !state.agentSummaryOpen;
          renderAgentsDiscovery();
        };
      }
    }

    if (runningCard) {
      var runningCount = combined.filter(function (item) {
        return ['running', 'standing'].indexOf(String(firstDefined(item.status, ''))) !== -1;
      }).length;
      var needsApproval = approvals.filter(function (item) {
        return !state.approvedAgentIds[firstDefined(item.id, item.module_id, item.name, '')];
      }).length;
      runningCard.innerHTML = '<div class="agents-col-head"><span class="ach-title">Running now</span><span class="ach-stats"><span class="agent-pulse running"></span> ' + escapeHtml(String(runningCount)) + ' running' + (needsApproval ? '<span class="ach-needs"> · ' + escapeHtml(String(needsApproval)) + ' need your attention</span>' : '') + '</span></div><div class="agents-clist">' + combined.map(function (item) {
        var id = firstDefined(item.id, item.module_id, item.name, 'agent');
        var isOpen = state.openAgentId === id;
        var logOpen = state.openAgentLogId === id;
        var approved = !!state.approvedAgentIds[id];
        var showBar = ['running', 'approval'].indexOf(String(firstDefined(item.status, ''))) !== -1;
        return '<div class="agent-c' + (isOpen ? ' is-open' : '') + '"><button type="button" class="agent-c-head" data-agent-toggle="' + escapeHtml(id) + '"><span class="agent-pulse ' + escapeHtml(String(firstDefined(item.status, 'running'))) + '"></span><span class="agent-name">' + escapeHtml(firstDefined(item.name, item.label, id)) + '</span><span class="agent-status s-' + escapeHtml(String(firstDefined(item.status, 'running'))) + '">' + escapeHtml(statusLabel(item, approved)) + '</span><span class="agent-caret' + (isOpen ? ' is-open' : '') + '">›</span></button>' + (showBar ? '<div class="agent-prog"><span class="agent-prog-bar tone-' + escapeHtml(toneClass(firstDefined(item.status, 'running'))) + '" style="width:' + escapeHtml(String(Math.max(6, Number(firstDefined(item.progress, 0)) || 0))) + '%"></span></div>' : '') + (isOpen ? '<div class="agent-c-body"><span class="tag agent-tag">' + escapeHtml(firstDefined(item.tag, 'runtime')) + '</span><p class="agent-doing">' + escapeHtml(approved && item.status === 'approval' ? 'Approved — executing now. Audit entry written.' : firstDefined(item.doing, item.summary, 'Governed activity in progress.')) + '</p><div class="agent-c-foot"><span class="agent-by">deployed by ' + escapeHtml(firstDefined(item.by, 'StrategyOS')) + '</span><button type="button" class="agent-log-btn' + (logOpen ? ' is-open' : '') + '" data-agent-log="' + escapeHtml(id) + '">◷ audit log <span class="agent-log-count">' + escapeHtml(String(safeArray(item.log).length)) + '</span></button></div>' + (item.status === 'approval' && !approved ? '<div class="agent-approve"><span class="agent-approve-note">⚠ This agent will <strong>act</strong> — held until you approve.</span><button type="button" class="agent-approve-btn" data-agent-approve="' + escapeHtml(id) + '">Approve &amp; let it execute</button></div>' : '') + (logOpen ? '<ol class="agent-trail">' + safeArray(item.log).map(function (entry) { return '<li class="trail-item"><span class="trail-time">' + escapeHtml(firstDefined(entry.t, 'now')) + '</span><span class="trail-dot"></span><span class="trail-text">' + escapeHtml(firstDefined(entry.a, 'audit entry')) + '</span></li>'; }).join('') + '<li class="trail-foot">every action is logged in-tenant · tap any entry to see its evidence</li></ol>' : '') + '</div>' : '') + '</div>';
      }).join('') + '</div><div class="agents-sovereign"><span class="sov-dot"></span> ' + (state.activePersona === "ceo" ? '' : 'sovereign \u00b7 runs in-tenant \u00b7 every action logged') + '</div>' + (subtools.length ? '<div class="subtools"><div class="subtools-label">Available tools</div><div class="subtools-grid">' + subtools.map(function (item) { return '<div class="subtool"><span class="subtool-glyph">' + escapeHtml(firstDefined(item.glyph, '\u25a6')) + '</span><div class="subtool-meta"><span class="subtool-name">' + escapeHtml(firstDefined(item.name, 'Tool')) + '</span><span class="subtool-desc">' + escapeHtml(firstDefined(item.desc, 'Named sub-agent')) + '</span></div></div>'; }).join('') + '</div></div>' : '');
      safeArray(runningCard.querySelectorAll('[data-agent-toggle]')).forEach(function (button) {
        button.onclick = function () {
          var id = button.getAttribute('data-agent-toggle') || '';
          state.openAgentId = state.openAgentId === id ? '' : id;
          if (state.openAgentId !== id) state.openAgentLogId = '';
          renderAgentsDiscovery();
        };
      });
      safeArray(runningCard.querySelectorAll('[data-agent-log]')).forEach(function (button) {
        button.onclick = function (event) {
          event.stopPropagation();
          var id = button.getAttribute('data-agent-log') || '';
          state.openAgentLogId = state.openAgentLogId === id ? '' : id;
          state.openAgentId = id;
          renderAgentsDiscovery();
        };
      });
      safeArray(runningCard.querySelectorAll('[data-agent-approve]')).forEach(function (button) {
        button.onclick = function (event) {
          event.stopPropagation();
          var id = button.getAttribute('data-agent-approve') || '';
          state.approvedAgentIds[id] = true;
          state.openAgentId = id;
          renderAgentsDiscovery();
        };
      });
    }

    if (discoveryCard) {
      function polishAgentName(name) {
        var m = { 'Tenant runtime watch': 'System health monitor', 'Tenant Runtime Watch': 'System health monitor', 'Runtime watch': 'System health monitor' };
        return m[String(name).trim()] || name;
      }
      var renderDiscoveryGroup = function (title, items) {
        return '<div class="disco-group-label">' + escapeHtml(title) + '</div><div class="disco-list">' + items.map(function (item) {
          return '<div class="disco-card"><span class="disco-glyph">' + escapeHtml(firstDefined(item.glyph, '\u25c7')) + '</span><div class="disco-meta"><div class="disco-name-line"><span class="disco-name">' + escapeHtml(polishAgentName(firstDefined(item.name, item.label, item.module_id, 'Agent'))) + '</span><span class="disco-src ' + escapeHtml(firstDefined(item.source, 'native')) + '">' + escapeHtml(state.activePersona === "ceo" ? 'Built-in' : firstDefined(item.source === 'native' ? 'StrategyOS' : item.by, item.connector, 'connector')) + '</span></div><div class="disco-desc">' + escapeHtml(firstDefined(item.desc, item.summary, 'Discoverable agent surface.')) + '</div><div class="disco-conn"><span class="disco-bolt">\u26a1</span> ' + escapeHtml(state.activePersona === "ceo" ? 'Built-in' : firstDefined(item.connector, item.route, 'connector')) + '</div></div><button type="button" class="disco-add">' + escapeHtml(item.source === 'native' ? '+ deploy' : '+ add') + '</button></div>';
        }).join('') + '</div>';
      };
      discoveryCard.innerHTML = '<div class="agents-col-head"><span class="ach-title">Discover agents</span><span class="ach-hint">Add to your workspace</span></div><div class="disco-search"><span class="disco-search-icon">⌕</span> Search the agent universe…</div>' + renderDiscoveryGroup('Built-in', nativeAgents) + renderDiscoveryGroup('Available agents', marketAgents) + '<button type="button" class="disco-browse">Browse all agents →</button>';
      var browseBtn = discoveryCard.querySelector('.disco-browse');
      if (browseBtn) {
        browseBtn.onclick = function () {
          if (state.activePersona === "ceo") {
            switchView('assistants');
            window.setTimeout(function () {
              askAssistant("Show me the agent catalogue available for my role and what each one does");
            }, 300);
          } else {
            state.discoveryFilter = state.discoveryFilter === 'all' ? 'native' : 'all';
            renderAgentsDiscovery();
          }
        };
      }
      safeArray(discoveryCard.querySelectorAll('.disco-add')).forEach(function (button) {
        button.onclick = function () {
          if (state.activePersona === "ceo") {
            showToast('Agent installation is available from the operator surface.');
          } else {
            showToast('Agent deployment is available from the operator or reviewer surface.');
          }
        };
      });
    }

    if (subtoolsCard) subtoolsCard.hidden = true;
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
    var closeButton = $("assistant-close");
    var threads = personaThreadRecords();
    var current = threadStore()[currentThreadKey()];

    if (drawer) {
      drawer.hidden = !state.drawerOpen;
      drawer.classList.toggle("is-open", state.drawerOpen);
      drawer.setAttribute("aria-modal", state.drawerOpen ? "true" : "false");
      drawer.setAttribute("role", "dialog");
    }
    if (scrim) {
      scrim.hidden = !state.drawerOpen;
      scrim.classList.toggle("is-open", state.drawerOpen);
      scrim.setAttribute("aria-hidden", state.drawerOpen ? "true" : "false");
      scrim.onclick = function () {
        _closeHermesDrawer();
      };
    }
    if (launcher) {
      launcher.hidden = state.drawerOpen || state.activeView === "assistants";
      launcher.onclick = function () {
        _openHermesDrawer(launcher);
      };
    }
    if (closeButton) {
      closeButton.onclick = function () {
        _closeHermesDrawer();
      };
    }
    // Inject thread list toggle for narrow/mobile screens
    var headActions = drawer && drawer.querySelector('.assistant-head__actions');
    if (headActions && !headActions.querySelector('.assistant-threads-toggle')) {
      var toggleBtn = document.createElement('button');
      toggleBtn.type = 'button';
      toggleBtn.className = 'assistant-threads-toggle';
      toggleBtn.setAttribute('aria-label', 'Toggle thread list');
      toggleBtn.setAttribute('aria-expanded', 'true');
      toggleBtn.textContent = '\u2630';
      toggleBtn.onclick = function () {
        var threadsPane = drawer.querySelector('.assistant-threads');
        if (threadsPane) {
          var collapsed = threadsPane.classList.toggle('is-collapsed');
          toggleBtn.setAttribute('aria-expanded', String(!collapsed));
          toggleBtn.textContent = collapsed ? '\u2630' : '\u2715';
        }
      };
      headActions.insertBefore(toggleBtn, closeButton);
    }

    if (assistantHeading) assistantHeading.textContent = assistantName;
    if (assistantSubtitle) assistantSubtitle.textContent = getPersonaLabel(state.activePersona) + " \u00b7 Your AI chief of staff";
    if (assistantState) assistantState.textContent = statusLabel(firstDefined(state.activeBoard, "ready"));

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
      threadList.innerHTML = '<button type="button" class="assistant-thread assistant-thread--new" data-thread-new="true"><strong>＋ New conversation</strong><span>Open a writable, board-safe thread for this persona.</span></button>' + visibleThreads.map(function (record) {
        var active = record.key === currentThreadKey();
        var threadMeta = escapeHtml(String(safeArray(record.messages).length)) + ' message(s)' + (record.readOnly ? '' : ' · writable');
        return '<button type="button" class="assistant-thread' + (active ? ' is-active' : '') + '" data-thread-key="' + escapeHtml(record.key) + '"' + (active ? ' aria-current="page"' : '') + '><div class="assistant-thread__top"><strong>' + escapeHtml(firstDefined(record.title, 'Thread')) + '</strong><span>' + escapeHtml(friendlyThreadTime(record.lastUpdated)) + '</span></div><span>' + escapeHtml(firstDefined(record.preview, 'Board-safe follow-up')) + '</span><small>' + threadMeta + '</small></button>';
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
    if (threadMeta) threadMeta.textContent = firstDefined(current && current.preview, blueprint.brief, "Select a governed follow-up.");
    if (threadTools) {
      var tools = [];
      tools.push('<span class="assistant-tool-chip">' + escapeHtml(firstDefined((getChatContract().assistant || {}).name, assistantName)) + '</span>');
      var boardStateLabel = statusLabel(firstDefined(state.activeBoard, (getChatContract().assistant || {}).board_state, 'pre'));
      tools.push('<span class="assistant-tool-chip">' + escapeHtml(boardStateLabel) + '</span>');
      if (!(current && current.readOnly)) {
        tools.push('<button type="button" class="assistant-tool-chip assistant-tool-chip--button" data-thread-new-inline="true">New conversation</button>');
      }
      if (current && current.route && state.activePersona !== "ceo") tools.push('<span class="assistant-tool-chip">' + escapeHtml(current.route) + '</span>');
      threadTools.innerHTML = tools.join('');
      safeArray(threadTools.querySelectorAll('[data-thread-new-inline]')).forEach(function (button) {
        button.onclick = function () {
          createWritableThread();
          openAssistantDrawer(button);
        };
      });
    }

    if (messages) {
      var visibleMessages = safeArray(current && current.messages).filter(function (message) {
        return String(firstDefined(message && message.text, '')).trim().length > 0;
      });
      messages.innerHTML = visibleMessages.length ? visibleMessages.map(function (message) {
        var role = firstDefined(message.role, 'assistant');
        var roleLabel = role === 'user' ? 'You' : assistantName;
        return '<div class="assistant-message assistant-message--' + escapeHtml(role) + '"><span class="assistant-message__role">' + escapeHtml(roleLabel) + ' · ' + escapeHtml(friendlyThreadTime(firstDefined(message.timestamp, 'now'))) + '</span><p>' + escapeHtml(firstDefined(message.text, '')) + '</p></div>';
      }).join("") : '<div class="assistant-message assistant-message--empty"><span class="assistant-message__role">No visible messages yet</span><p>Start a writable thread and the reply will appear here immediately.</p></div>';
      messages.scrollTop = messages.scrollHeight;
    }

    if (promptRow) {
      promptRow.innerHTML = getHeroPrompts().slice(0, 3).map(function (prompt) {
        return '<button class="prompt-chip" type="button" data-assistant-prompt="' + escapeHtml(prompt) + '">' + escapeHtml(prompt) + '</button>';
      }).join("");
      safeArray(promptRow.querySelectorAll("[data-assistant-prompt]")).forEach(function (button) {
        button.onclick = function () {
          askAssistant(button.getAttribute("data-assistant-prompt") || "", button);
        };
      });
    }
  }

  function renderReportSurface() {
    var reportCard = $("report-surface-card");
    var publication = getPublication();
    if (!reportCard) return;
    reportCard.innerHTML = [
      '<div class="detail-head"><div><p class="detail-eyebrow">' + (state.activePersona === "ceo" ? 'Board reports' : 'Report surface') + '</p><h3 class="detail-title">' + (state.activePersona === "ceo" ? 'Board reports' : 'Previewable report routes') + '</h3></div><span class="pill-inline ' + toneClass(statusLabel(firstDefined(publication.publish_state, 'draft'))) + '">' + escapeHtml(statusLabel(firstDefined(publication.publish_state, 'draft'))) + '</span></div>',
      '<p class="detail-copy">Overview, cases, evidence, and reports now sing as one workspace. This rail keeps the board-safe output explicit.</p>',
      '<div class="mini-list">' + safeArray(publication.available_artifacts).slice(0, 5).map(function (item) {
        var formatLabel = function (fmt) {
          var map = { graph: 'Data relationships', audit: 'Decision trail', other: 'Overview packet', json: 'Structured data', csv: 'Spreadsheet', pdf: 'PDF document', md: 'Markdown note' };
          return map[String(fmt).toLowerCase()] || escapeHtml(fmt);
        };
        var catLabel = REPORT_CATEGORY_MAP[item.category] || humanizeToken(item.category) || 'report';
        var meta = state.activePersona === "ceo"
          ? escapeHtml(catLabel)
          : escapeHtml(catLabel) + ' \u00b7 ' + escapeHtml(firstDefined(item.format, 'file'));
        return '<div class="list-item"><div><strong>' + escapeHtml(firstDefined(item.title, item.artifact_key, 'Artifact')) + '</strong><p class="list-copy">' + meta + '</p></div><span class="pill-inline ' + (item.restricted ? 'warn' : 'ok') + '">' + escapeHtml(item.restricted ? 'restricted' : 'board-safe') + '</span></div>';
      }).join("") + '</div>',
      state.activePersona === "ceo" ? '' : '<a class="summary-link" href="' + escapeHtml(firstDefined(publication.preview_route, '/public/runs/latest/report-preview')) + '">Open report preview</a>'
    ].join("");
  }

  function renderSummary() {
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

  function renderPersonaView() {
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
  }

  async function refresh(withAnimation) {
    try {
      if (withAnimation) {
        animateCard("sheet");
        animateCard("board-portal");
      }
      var params = currentViewParams();
      var response = await Promise.all([
        fetchJson("/public/runs/latest" + buildQuery(params)),
        fetchJson("/ui/session")
      ]);

      state.latestPacket = response[0] || {};
      state.session = response[1] || {};
      state.personas = safeArray((state.latestPacket.executive_modes || {}).personas);
      state.token = firstDefined((state.session || {}).token, state.token, window.localStorage.getItem(_tokenKey));
      state.activePersona = firstDefined((state.latestPacket.executive_modes || {}).active_persona_id, state.activePersona, "ceo");
      if (state.activePersona === "board") state.activeView = "home";
      state.activeBoard = firstDefined((state.latestPacket.executive_modes || {}).active_board_state, (state.latestPacket.board_portal || {}).presentation_state, state.activeBoard, "pre");
      state.activeDriverKey = firstDefined((state.latestPacket.executive_modes || {}).active_driver_key, state.activeDriverKey, "board_packet");
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
      askAssistant(message);
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
      activeView: "home",
      a2aOpen: false,
      activeA2AExchange: "",
      drawerOpen: false,
      drawerReturnFocusEl: null,
      videoModalOpen: false,
      theme: document.documentElement.getAttribute("data-theme") || "light",
      discoveryFilter: "all",
      selectedAgentModuleKey: "",
      knowledgeQuestionIndex: 0,
      personaOutsideListenerBound: false,
      openDriverNoteKey: "",
      openWeekIndex: 0,
      agentSummaryOpen: false,
      openAgentId: "",
      openAgentLogId: "",
      approvedAgentIds: {}
    };

  bindAssistantForm();
  bindViewNav();
  refresh(false);
  window.setInterval(function () { refresh(false); }, 60000);
})();
