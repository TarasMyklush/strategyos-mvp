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

  function safeArray(value) { return Array.isArray(value) ? value : []; }

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

  function fetchJson(path) {
    return fetch(path).then(function (response) {
      return response.ok ? response.json() : null;
    });
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
    return firstDefined(contract.label, humanizeToken(personaId), "Group CEO");
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
    var pct = Math.max(0, Math.min(100, Number(firstDefined(driver.pct, 0)) || 0));
    var ringMax = 400 / 3;
    var radius = 15;
    var circumference = 2 * Math.PI * radius;
    var frac = Math.max(0.02, Math.min(pct, ringMax) / ringMax);
    var dash = circumference * frac;
    var tickAngle = (100 / ringMax) * 360 - 90;
    var tickRad = (tickAngle * Math.PI) / 180;
    var cx = 18;
    var cy = 18;
    var cos = Math.cos(tickRad);
    var sin = Math.sin(tickRad);
    var tcos = -sin;
    var tsin = cos;
    var apexR = radius + 3.25;
    var baseR = radius + 8.25;
    var halfWidth = 2.8;
    var ax = (cx + apexR * cos).toFixed(2);
    var ay = (cy + apexR * sin).toFixed(2);
    var b1x = (cx + baseR * cos + halfWidth * tcos).toFixed(2);
    var b1y = (cy + baseR * sin + halfWidth * tsin).toFixed(2);
    var b2x = (cx + baseR * cos - halfWidth * tcos).toFixed(2);
    var b2y = (cy + baseR * sin - halfWidth * tsin).toFixed(2);
    return '<svg class="driver-ring" viewBox="0 0 36 36" aria-hidden="true"><circle class="driver-ring__track" cx="18" cy="18" r="15"></circle><circle class="driver-ring__value" cx="18" cy="18" r="15" stroke-dasharray="' + dash + ' ' + circumference + '" transform="rotate(-90 18 18)"></circle><polygon class="driver-ring__tick" points="' + ax + ',' + ay + ' ' + b1x + ',' + b1y + ' ' + b2x + ',' + b2y + '"></polygon></svg>';
  }

  function buildAssistantReply(message) {
    var cleanMessage = String(message || "").trim();
    var driver = getActiveDriver() || {};
    var publication = getPublication();
    var boardPortal = getBoardPortal();
    var planHealth = getPlanHealth();
    var persona = getPersonaContract(state.activePersona);
    var blueprint = getPersonaBlueprint(state.activePersona);
    var assistantName = firstDefined(persona.assistant, blueprint.assistant, "Hermes");
    var assistantRole = firstDefined(persona.assistant_role, blueprint.assistantRole, "chief of staff");
    var challenged = firstDefined(publication.challenged_cases, (getDrilldown().owed_upward || {}).challenge_count, 0);
    var mood = firstDefined(blueprint.quote, blueprint.brief, planHealth.summary, "The governed packet is the only room we answer from.");
    var thread = threadStore()[currentThreadKey()] || {};
    var messageCount = safeArray(thread.messages).length;
    return [
      assistantName + " speaking as " + assistantRole + " for " + getPersonaLabel(state.activePersona) + ": " + firstDefined(driver.label, planHealth.label, "current posture") + " is still the active lens.",
      firstDefined(driver.detail, planHealth.summary, blueprint.brief, mood),
      "Board state is " + humanizeToken(firstDefined(state.activeBoard, boardPortal.presentation_state, boardPortal.state, "pre")) + ", publication is " + humanizeToken(firstDefined(publication.publish_state, "draft")) + ", and " + challenged + " challenged item(s) still shape the room.",
      "This thread now carries " + messageCount + " message(s) of bounded context for this persona.",
      cleanMessage ? "Follow-up captured: “" + cleanMessage + "”." : "Prompt captured for the current lane."
    ].join(" ");
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

  function ensureWritableThread() {
    ensureThreads();
    var current = threadStore()[currentThreadKey()];
    if (current && !current.readOnly) return current;
    return createWritableThread();
  }

  function createWritableThread(seedTitle) {
    var blueprint = getPersonaBlueprint(state.activePersona);
    var persona = getPersonaContract(state.activePersona);
    var assistantName = firstDefined((getChatContract().assistant || {}).name, persona.assistant, blueprint.assistant, "Hermes");
    var key = state.activePersona + ":followup-" + Date.now();
    threadStore()[key] = {
      key: key,
      title: seedTitle || (getPersonaLabel(state.activePersona) + " follow-up"),
      preview: "Writable board-safe thread.",
      route: firstDefined(getPublication().preview_route, "/public/runs/latest/report-preview"),
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
    if (!thread) return;
    thread.messages.push({ role: role, text: text, timestamp: new Date().toISOString() });
    thread.preview = String(text || thread.preview || "").slice(0, 84);
    thread.lastUpdated = new Date().toISOString();
    saveStoredThreads();
  }

  function friendlyThreadTime(value) {
    if (!value) return "now";
    var parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) return parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return value;
  }

  function renderTopbar() {
    var activePersona = getPersonaContract(state.activePersona);
    var blueprint = getPersonaBlueprint(state.activePersona);
    var org = $("brand-org");
    var personaLabel = $("persona-label");
    var list = $("pm-list");
    var btn = $("persona-btn");
    var askToggle = $("ask-toggle");
    var viewNav = $("view-nav");
    var launcher = $("chat-launcher-cta");
    var launcherPrompt = document.querySelector("#chat-launcher .chat-launcher__prompt");
    var themeToggle = $("theme-toggle");
    var userName = $("topbar-user-name");
    var userRole = $("topbar-user-role");
    var avatar = $("topbar-avatar");
    var userMeta = document.querySelector("#topbar-user .tb-user-meta");
    var assistantName = firstDefined(activePersona.assistant, blueprint.assistant, "Hermes");
    var assistantGlyph = firstDefined(activePersona.assistant_glyph, blueprint.assistantGlyph, "◆");
    var initials = executiveIdentityInitials(state.activePersona);

    if (org) org.textContent = "Mizan Group";
    if (personaLabel) personaLabel.textContent = firstDefined(activePersona.label, "Group CEO");
    if (askToggle) {
      askToggle.innerHTML = '<span class="assistant-glyph" aria-hidden="true">' + escapeHtml(assistantGlyph) + '</span><span>' + escapeHtml(assistantName) + '</span>';
      askToggle.classList.toggle("is-on", state.drawerOpen);
      askToggle.onclick = function () {
        state.drawerOpen = !state.drawerOpen;
        renderTopbar();
        renderAssistantStudio();
      };
    }
    if (launcher) {
      if (state.activePersona === "board") {
        launcher.textContent = "Ask " + assistantName;
      } else {
        launcher.innerHTML = '<span class="asst-avatar sm">' + escapeHtml(firstDefined(activePersona.assistant_glyph, blueprint.assistantGlyph, '◆')) + '</span> Ask ' + escapeHtml(assistantName);
      }
    }
    if (launcherPrompt) launcherPrompt.hidden = state.activePersona !== "board";
    if (themeToggle) {
      themeToggle.textContent = state.theme === "dark" ? "☾" : "☀";
      themeToggle.onclick = function () {
        state.theme = state.theme === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", state.theme);
        renderTopbar();
      };
    }
    if (userName) userName.textContent = "";
    if (userRole) userRole.textContent = "";
    if (avatar) avatar.textContent = initials;
    if (userMeta) userMeta.hidden = true;
    if (viewNav) viewNav.hidden = state.activePersona === "board";
    if (!list || !btn) return;

    list.innerHTML = "";
    safeArray(state.personas).forEach(function (persona) {
      var isActive = persona.persona_id === state.activePersona;
      var item = document.createElement("button");
      item.type = "button";
      item.className = "persona-item" + (isActive ? " is-active" : "");
      item.setAttribute("role", "menuitem");
      item.innerHTML = "<span>" + escapeHtml(firstDefined(persona.label, persona.persona_id, "Persona")) + "</span><span class=\"persona-item__tag\">" + escapeHtml(persona.persona_id || "") + "</span>";
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
    });
  }

  function renderViewPanels() {
    safeArray(document.querySelectorAll("[data-view-panel]")).forEach(function (panel) {
      var isActive = panel.getAttribute("data-view-panel") === state.activeView;
      panel.hidden = !isActive;
      panel.classList.toggle("is-active", isActive);
    });
  }

  function renderHomeComposition() {
    var blueprint = getPersonaBlueprint(state.activePersona);
    var driverHeading = $("driver-heading");
    var lowerHeading = $("lower-rail-heading");
    if (driverHeading) driverHeading.textContent = firstDefined(blueprint.indexLabel, "The group index");
    if (lowerHeading) lowerHeading.textContent = "Mid / lower rail";
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
        '<div class="network-summary"><div class="network-score"><strong>' + escapeHtml(String(avg)) + '</strong><span>company AI adoption</span></div><div class="network-meta"><span class="pill-inline ok">up to date &amp; deep</span><span class="pill-inline warn">needs attention</span><span class="pill-inline danger">stale · ' + escapeHtml(String(stale)) + ' leader(s)</span></div></div>',
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
    scroll.innerHTML = safeArray(active.messages).map(function (message) {
      var mine = firstDefined(message.from, '') === assistantName;
      return '<div class="a2a-msg' + (mine ? ' mine' : '') + '"><span class="a2a-from">' + escapeHtml(firstDefined(message.from, 'Assistant')) + '</span><div class="a2a-bubble">' + escapeHtml(firstDefined(message.text, '')) + '</div></div>';
    }).join('');
    scroll.scrollTop = scroll.scrollHeight;
    if (footNote) footNote.textContent = '⇄ ' + assistantName + ' is following up automatically';
    if (followup) {
      followup.onclick = function () {
        var prompt = 'Set a follow-up task for ' + firstDefined(active.with, 'the assistant') + ' on ' + firstDefined(active.topic, 'the active coordination thread') + '.';
        pushThreadMessage('user', prompt);
        pushThreadMessage('assistant', buildAssistantReply(prompt));
        state.drawerOpen = true;
        renderTopbar();
        renderAssistantStudio();
      };
    }
  }

  function renderKnowledgeGraph() {
    var card = $("knowledge-graph-card");
    var graph = getKnowledgeGraph();
    if (!card) return;
    var focusQuestion = graph.questions[state.knowledgeQuestionIndex || 0] || null;
    var focused = focusQuestion ? new Set(safeArray(focusQuestion.focus)) : null;
    var nodes = safeArray(graph.nodes);
    var nodeMap = {};
    nodes.forEach(function (node) { nodeMap[node.id] = node; });
    card.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Knowledge graph</p><h3 class="detail-title">How your data relates</h3><p class="section-note">Shaped by the questions you ask — proof the system reasons across everything.</p></div><span class="pill-inline ok">under the hood</span></div>'
      + '<div class="kg-questions">' + safeArray(graph.questions).map(function (question, index) {
        return '<button type="button" class="kg-question' + (focusQuestion && focusQuestion.id === question.id ? ' is-active' : '') + '" data-kg-question="' + index + '">' + escapeHtml(firstDefined(question.label, 'Question')) + '</button>';
      }).join('') + '</div>'
      + '<div class="kg-stage"><svg viewBox="0 0 100 88" class="kg-svg" aria-hidden="true">'
      + safeArray(graph.edges).map(function (edge) {
        var from = nodeMap[edge[0]];
        var to = nodeMap[edge[1]];
        if (!from || !to) return '';
        var mx = ((Number(from.x || 0) + Number(to.x || 0)) / 2).toFixed(1);
        var my = (((Number(from.y || 0) + Number(to.y || 0)) / 2) - 4).toFixed(1);
        var active = !focused || (focused.has(edge[0]) && focused.has(edge[1]));
        return '<path class="kg-edge' + (active ? ' on' : '') + '" d="M' + escapeHtml(String(from.x)) + ',' + escapeHtml(String(from.y)) + ' Q' + escapeHtml(mx) + ',' + escapeHtml(my) + ' ' + escapeHtml(String(to.x)) + ',' + escapeHtml(String(to.y)) + '"></path>';
      }).join('')
      + nodes.map(function (node) {
        var active = !focused || focused.has(node.id);
        return '<g class="kg-node' + (active ? ' on' : ' off') + '"><circle class="kg-node-dot" cx="' + escapeHtml(String(node.x)) + '" cy="' + escapeHtml(String(node.y)) + '" r="' + escapeHtml(String(Math.max(2.4, Number(node.r || 8) / 2.4))) + '"></circle></g>';
      }).join('')
      + '</svg><div class="kg-labels">' + nodes.map(function (node) {
        var active = !focused || focused.has(node.id);
        return '<span class="kg-label' + (active ? ' on' : ' off') + '" style="left:' + escapeHtml(String(node.x)) + '%;top:' + escapeHtml(String(node.y)) + '%">' + escapeHtml(firstDefined(node.label, 'Node')) + '</span>';
      }).join('') + '</div></div>'
      + '<div class="kg-legend"><span>plan</span><span>KPI</span><span>business unit</span><span>finding</span><span>document</span><span>vendor</span><span>invoice</span><span>contract</span></div>';
    safeArray(card.querySelectorAll('[data-kg-question]')).forEach(function (button) {
      button.onclick = function () {
        state.knowledgeQuestionIndex = Number(button.getAttribute('data-kg-question') || 0) || 0;
        renderKnowledgeGraph();
      };
    });
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
      { label: "Board state", value: humanizeToken(firstDefined(state.activeBoard, boardPortal.presentation_state, boardPortal.state, "pre")) },
      { label: "Reports", value: String(firstDefined(publication.report_count, 0)) + " surfaced" },
      { label: "Agents", value: String(firstDefined((agents.summary || {}).running_count, diagnostics.agents && diagnostics.agents.running_count, 0)) + " running" },
      { label: "Next move", value: humanizeToken(firstDefined(getPlanHealth().next_action, (boardPortal.state_detail || {}).title, "review")) }
    ];

    $("hero-eyebrow").textContent = state.activePersona === "board"
      ? "Board portal · governed packet posture"
      : "Good morning, " + firstName + " · the week so far";
    $("hero-head").textContent = firstDefined(preferredHero.headline, hero.summary, hero.label, getPlanHealth().label, "Plan health overview");
    $("hero-body").textContent = firstDefined(preferredHero.body, hero.body, getPlanHealth().summary, "Awaiting executive diagnostics.");
    $("hero-score").textContent = String(clampedScore || 0);
    $("hero-cap").textContent = firstDefined(preferredHero.scoreNote, hero.score_note, getPlanHealth().badge, "plan health");
    var byline = $("hero-byline");
    if (byline) {
      var bylineText = firstDefined(blueprint.by, "");
      byline.textContent = bylineText;
      byline.hidden = !bylineText;
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
    if (arc) arc.setAttribute("stroke-dasharray", dash + " " + (circumference - dash));

    var promptRow = $("hero-prompts");
    if (promptRow) {
      promptRow.innerHTML = "";
      prompts.slice(0, 3).forEach(function (prompt) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "prompt-chip";
        button.textContent = prompt;
        button.onclick = function () {
          pushThreadMessage("user", prompt);
          pushThreadMessage("assistant", buildAssistantReply(prompt));
          renderAssistantStudio();
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
    drivers.forEach(function (driver, index) {
      var key = String(driver.driver_key || driver.key || "");
      var spark = buildDriverSparkline(driver, index);
      var tile = document.createElement("button");
      tile.type = "button";
      tile.className = "driver-tile" + (activeDriver && String(activeDriver.driver_key || activeDriver.key || "") === key ? " is-selected" : "");
      tile.innerHTML = [
        '<div class="driver-topline"><span class="driver-overline">' + escapeHtml(firstDefined(driver.status, driver.sub, "status")) + '</span>' + driverRingMarkup(driver) + '</div>',
        '<span class="driver-metric">' + escapeHtml(firstDefined(driver.metric, "—")) + '</span>',
        '<strong class="driver-label">' + escapeHtml(firstDefined(driver.label, "Driver")) + '</strong>',
        '<p class="driver-detail">' + escapeHtml(firstDefined(driver.detail, "")) + '</p>',
        '<div class="sparkline-wrap"><svg class="driver-sparkline" viewBox="0 0 124 30" aria-hidden="true"><polygon class="driver-sparkline__fill" points="' + escapeHtml(spark.area) + '"></polygon><polyline class="driver-sparkline__line" points="' + escapeHtml(spark.line) + '"></polyline></svg></div>',
        '<div class="driver-footer"><span>' + escapeHtml(firstDefined(driver.trendLabel, "Governed trend")) + '</span><strong>' + escapeHtml(firstDefined(driver.pct, "—")) + '%</strong></div>'
      ].join("");
      tile.onclick = function () {
        state.activeDriverKey = key;
        updateHistory();
        renderDriverGrid();
        renderMetrics();
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
        value: humanizeToken(firstDefined(state.activeBoard, boardPortal.presentation_state, boardPortal.state, "pre")),
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
      var actualPath = chartPoints(actualSeries).map(function (pair, idx) {
        return (idx ? "L" : "M") + pair[0].toFixed(1) + "," + pair[1].toFixed(1);
      }).join(" ");
      var planPath = chartPoints(planSeries).map(function (pair, idx) {
        return (idx ? "L" : "M") + pair[0].toFixed(1) + "," + pair[1].toFixed(1);
      }).join(" ");
      var groupMarkup = function (label, tone, rows) {
        return '<div class="drill-ledger"><div class="drill-ledger__head"><span class="pill-inline ' + (tone === 'up' ? 'ok' : 'warn') + '">' + escapeHtml(label) + '</span><span>' + escapeHtml(tone === 'up' ? 'what is helping the number' : 'what is still dragging it') + '</span></div>' + (rows.length ? rows.map(function (item) {
          var noteKey = firstDefined(driver.driver_key, driver.key, '') + ':' + firstDefined(item.name, 'mover');
          var noteOpen = state.openDriverNoteKey === noteKey;
          var gm = item.gm || null;
          return '<div class="drill-mover ' + (noteOpen ? 'is-open' : '') + '"><div class="drill-mover__main"><span class="drill-mover__dot ' + escapeHtml(tone) + '"></span><strong>' + escapeHtml(firstDefined(item.name, 'Signal')) + '</strong><span class="drill-mover__delta">' + escapeHtml(firstDefined(item.delta, '')) + '</span>' + (gm ? '<button type="button" class="gm-chip' + (noteOpen ? ' is-open' : '') + '" data-driver-note="' + escapeHtml(noteKey) + '">“ GM note</button>' : '<span class="gm-none">—</span>') + '</div>' + (gm && noteOpen ? '<blockquote class="gm-note"><span class="gm-note-who">' + escapeHtml(firstDefined(gm.who, 'GM')) + '</span>' + escapeHtml(firstDefined(gm.note, '')) + '<span class="gm-note-tail">↑ travels up with this number</span></blockquote>' : '') + '</div>';
        }).join('') : '<div class="discovery-empty">No movement is attached yet.</div>') + '</div>';
      };
      drillCard.innerHTML = [
        '<div class="drill-surface">',
        '<div class="drill-headline"><div><h3 class="detail-title">' + escapeHtml(firstDefined(driver.label, 'Driver drill')) + '</h3><p class="section-note">' + escapeHtml(String(firstDefined(driver.pct, '—')) + '% of plan · ' + firstDefined(driver.metric, '—') + ' · ' + firstDefined(driver.sub, 'current measure')) + '</p></div><button class="assistant-tool-chip assistant-tool-chip--button" type="button" data-driver-show-work="true">Show the work ⌕</button></div>',
        '<p class="detail-copy">' + escapeHtml(firstDefined(driver.detail, 'Awaiting drill detail.')) + '</p>',
        '<div class="drill-grid-v2"><div class="drill-trend-panel"><div class="mini-head">' + escapeHtml(firstDefined(driver.trendLabel, 'Trend')) + '<span class="trend-legend"><span class="lg actual"></span> actual <span class="lg plan"></span> plan</span></div><svg class="drill-trend-chart" viewBox="0 0 320 156" aria-hidden="true"><path class="trend-chain__plan" d="' + escapeHtml(planPath) + '"></path><path class="trend-chain__actual" d="' + escapeHtml(actualPath) + '"></path></svg><div class="trend-unit">' + escapeHtml(firstDefined(driver.unit, '')) + '</div></div><div class="drill-movers-panel"><div class="mini-head">What moved it <span class="mini-hint">tap a note — the GM’s commentary rides up with the number</span></div>' + groupMarkup('Lifting', 'up', lifting) + groupMarkup('Dragging', 'down', dragging) + '</div></div>',
        '<div class="chips"><span class="chips-label">Ask on:</span>' + safeArray(driver.chips).map(function (chip) { return '<button class="chip" type="button" data-driver-chip="' + escapeHtml(chip) + '">' + escapeHtml(chip) + '</button>'; }).join('') + '</div>',
        '<form class="chips-own" id="driver-composer"><label class="sr-only" for="driver-input">Ask about driver</label><input id="driver-input" class="driver-input" type="text" placeholder="Ask your own about ' + escapeHtml(String(firstDefined(driver.label, 'this driver')).toLowerCase()) + '…" /><button type="submit">Send</button></form>',
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
          var prompt = 'On ' + firstDefined(driver.label, 'this driver') + ' (' + firstDefined(driver.pct, '—') + '% of plan): ' + (button.getAttribute('data-driver-chip') || '');
          pushThreadMessage('user', prompt);
          pushThreadMessage('assistant', buildAssistantReply(prompt));
          state.drawerOpen = true;
          renderTopbar();
          renderAssistantStudio();
        };
      });
      var showWork = drillCard.querySelector('[data-driver-show-work]');
      var evidence = drillCard.querySelector('.drill-evidence');
      if (showWork && evidence) {
        showWork.onclick = function () {
          evidence.hidden = !evidence.hidden;
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
          pushThreadMessage('user', prompt);
          pushThreadMessage('assistant', buildAssistantReply(prompt));
          input.value = '';
          state.drawerOpen = true;
          renderTopbar();
          renderAssistantStudio();
        });
      }
    }
    if (gravityPanel) {
      var vlogs = [
        { topic: 'Reading margin pressure before the board', who: 'Dr. Amal Faris', role: 'former Group CFO, regional pharma', dur: '4:12' },
        { topic: 'When to hedge — and when to wait', who: 'Tariq Bensalem', role: 'treasury advisor', dur: '6:38' },
        { topic: 'Recognising GMs without distorting incentives', who: 'Huda Karim', role: 'leadership coach', dur: '3:55' }
      ];
      gravityPanel.innerHTML = [
        '<div class="detail-head"><div><p class="detail-eyebrow">Gravity and guardrails</p><h3 class="detail-title">Think and model on your data</h3><p class="detail-copy">A sovereign sandbox that runs in your chat — on Mizan’s figures, with no side effects.</p></div><span class="pill-inline ' + toneClass(firstDefined(publication.publish_state, board.presentation_state, "draft")) + '">' + escapeHtml(firstDefined(publication.publish_state, board.presentation_state, "draft")) + '</span></div>',
        '<div class="gravity-grid-v2"><section class="gravity-play-card"><div class="play-badge">◇ Thinking mode</div><div class="play-title">Type a what-if and play</div><p class="play-body">Keep the room inside governed packet truth while you model scenarios and request missing data.</p><div class="pill-row">' + safeArray(gravity.rails).map(function (item) { return '<span class="pill-inline ' + toneClass(item) + '">' + escapeHtml(item) + '</span>'; }).join('') + '</div><div class="mini-list">' + safeArray(gravity.prompts).slice(0, 3).map(function (prompt) { return '<button class="timeline-chip" type="button" data-chat-prompt="' + escapeHtml(prompt) + '"><strong>' + escapeHtml(prompt) + '</strong><span>Send to assistant</span></button>'; }).join('') + '</div></section><section class="leaders-card"><div class="leaders-badge">✦ Leaders’ Corner · vlog</div><div class="leaders-title">Short counsel, senior practitioners</div><div class="leaders-list">' + vlogs.map(function (item) { return '<button class="leader-row" type="button" data-vlog-topic="' + escapeHtml(item.topic) + '"><span class="leader-row__play">▶</span><span class="leader-row__copy"><strong>' + escapeHtml(item.topic) + '</strong><span>' + escapeHtml(item.who + ' · ' + item.role) + '</span></span><span class="leader-row__dur">' + escapeHtml(item.dur) + '</span></button>'; }).join('') + '</div></section></div>'
      ].join("");
      safeArray(gravityPanel.querySelectorAll("[data-chat-prompt]")).forEach(function (button) {
        button.onclick = function () {
          var prompt = button.getAttribute("data-chat-prompt") || "";
          pushThreadMessage("user", prompt);
          pushThreadMessage("assistant", buildAssistantReply(prompt));
          renderAssistantStudio();
        };
      });
      safeArray(gravityPanel.querySelectorAll('[data-vlog-topic]')).forEach(function (button) {
        button.onclick = function () {
          var topic = button.getAttribute('data-vlog-topic') || '';
          var prompt = 'From the Leaders’ Corner reel “' + topic + '” — how does this apply to Mizan right now?';
          pushThreadMessage('user', prompt);
          pushThreadMessage('assistant', buildAssistantReply(prompt));
          state.drawerOpen = true;
          renderTopbar();
          renderAssistantStudio();
        };
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
      '<div class="board-head"><div><p class="detail-eyebrow">Reports</p><h3 class="board-title">' + escapeHtml(firstDefined((board.state_detail || {}).title, board.state_label, "Governed board packet")) + '</h3><p class="board-copy">' + escapeHtml(firstDefined((board.state_detail || {}).summary, board.board_summary, "Board posture stays bounded to the current packet.")) + '</p></div><span class="pill-inline ' + toneClass(firstDefined(board.presentation_state, board.state, "pre")) + '">' + escapeHtml(firstDefined(board.state_label, board.presentation_state, board.state, "pre")) + '</span></div>',
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
      '<div class="snapshot-grid"><div class="snapshot-card"><strong>Deck release</strong><span>' + escapeHtml(humanizeToken(firstDefined(deckRelease.status, 'pending'))) + '</span><span class="panel-note">' + escapeHtml(String(firstDefined(deckRelease.report_count, 0)) + ' surfaced report(s) · ' + firstDefined(deckRelease.preview_route, '/public/runs/latest/report-preview')) + '</span></div><div class="snapshot-card"><strong>Frozen snapshot</strong><span>' + escapeHtml(humanizeToken(firstDefined(snapshot.status, 'live_packet'))) + '</span><span class="panel-note">' + escapeHtml(firstDefined(snapshot.summary, 'Closed meetings retain a bounded frozen snapshot.')) + '</span></div></div>',
      '<div class="board-action-grid">' + safeArray(stateDetail.primary_actions).slice(0, 2).concat(safeArray(stateDetail.secondary_actions).slice(0, 2)).map(function (item) {
        return '<span class="assistant-tool-chip">' + escapeHtml(humanizeToken(item)) + '</span>';
      }).join("") + '</div>',
      '<div class="board-detail-grid"><section class="board-panel"><p class="detail-eyebrow">Meeting posture</p><div class="mini-list"><div class="board-deck"><div><strong>' + escapeHtml(firstDefined((board.meeting || {}).design_title, (board.meeting || {}).title, "Board meeting")) + '</strong><p class="list-copy">' + escapeHtml(firstDefined((board.meeting || {}).date, (board.meeting || {}).when, "Board timing pending")) + '</p></div><span class="pill-inline ok">' + escapeHtml(firstDefined((board.meeting || {}).room, "board-safe")) + '</span></div></div></section><section class="board-panel"><p class="detail-eyebrow">Lifecycle actions</p><div class="mini-list">' + (actions.length ? actions.map(function (item) {
        return '<div class="board-action"><div><strong>' + escapeHtml(firstDefined(item.item, "Action")) + '</strong><small>' + escapeHtml(firstDefined(item.owner, "Owner")) + '</small></div><span class="pill-inline warn">' + escapeHtml(firstDefined(item.due, "next")) + '</span></div>';
      }).join("") : '<div class="discovery-empty">No lifecycle actions are attached to this state.</div>') + '</div></section></div>',
      stateSpecific
    ].join("");
    safeArray(portal.querySelectorAll('[data-board-prompt]')).forEach(function (button) {
      button.onclick = function () {
        var prompt = button.getAttribute('data-board-prompt') || '';
        pushThreadMessage('user', prompt);
        pushThreadMessage('assistant', buildAssistantReply(prompt));
        renderAssistantStudio();
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

    if (findingsPanel) {
      findingsPanel.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Findings &amp; concerns</p><h3 class="detail-title">What the room should notice</h3></div><span class="pill-inline warn">board-safe</span></div><div class="mini-list">' + findings.map(function (item) {
        return '<div class="list-item"><div><strong>' + escapeHtml(firstDefined(item.title, "Finding")) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(item.detail, "Awaiting detail.")) + '</p></div><span class="pill-inline ' + toneClass(item.tone) + '">' + escapeHtml(firstDefined(item.tag, humanizeToken(item.tone), "signal")) + '</span></div>';
      }).join("") + '</div>';
    }

    if (developmentsPanel) {
      developmentsPanel.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Developments since you were here</p><h3 class="detail-title">Fresh movement across the group</h3></div><span class="pill-inline ok">live signal</span></div><div class="mini-list">' + developments.map(function (item) {
        return '<div class="list-item"><div><strong>' + escapeHtml(firstDefined(item.title, "Development")) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(item.impact, item.detail, "Awaiting detail.")) + '</p></div><span class="pill-inline ' + toneClass(firstDefined(item.kind, (item.chips || [])[0])) + '">' + escapeHtml(firstDefined(item.meta, item.kind, "update")) + '</span></div>';
      }).join("") + '</div>';
    }

    if (weekPanel) {
      var openIndex = Math.min(state.openWeekIndex || 0, Math.max(weekAhead.length - 1, 0));
      var activeEvent = weekAhead[openIndex] || null;
      weekPanel.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Week ahead</p><h3 class="detail-title">Upcoming decision moments</h3></div><span class="pill-inline warn">time-bound</span></div><div class="week-rail-v2">' + weekAhead.map(function (item, index) {
        return '<button class="event-chip' + (index === openIndex ? ' is-open' : '') + (item.urgent ? ' urgent' : '') + '" type="button" data-week-index="' + index + '"><span class="event-day">' + escapeHtml(firstDefined(item.day, '')) + '</span><span class="event-title">' + escapeHtml(firstDefined(item.title, item.label, 'Event')) + '</span><span class="event-when">' + escapeHtml(firstDefined(item.when, item.detail, 'soon')) + '</span></button>';
      }).join('') + '</div>' + (activeEvent ? '<div class="prep"><div class="prep-head"><span class="prep-flag">⚑ prep</span> ' + escapeHtml(firstDefined(activeEvent.title, 'Event')) + ' · ' + escapeHtml(firstDefined(activeEvent.when, 'soon')) + '</div><p class="prep-body">' + escapeHtml(firstDefined(activeEvent.prep, activeEvent.foot, '')) + '</p><div class="prep-actions"><button class="timeline-chip" type="button" data-chat-prompt="Open thinking mode for “' + escapeHtml(firstDefined(activeEvent.title, 'this event')) + '”: model the options and what I should walk in having decided."><strong>◇ Open in thinking mode</strong><span>no side effects</span></button><button class="timeline-chip" type="button" data-chat-prompt="For “' + escapeHtml(firstDefined(activeEvent.title, 'this event')) + '”, what data am I missing and who should I request it from?"><strong>⤓ Request missing data</strong><span>ask StrategyOS</span></button></div></div>' : '');
      safeArray(weekPanel.querySelectorAll('[data-week-index]')).forEach(function (button) {
        button.onclick = function () {
          state.openWeekIndex = Number(button.getAttribute('data-week-index') || 0) || 0;
          renderLowerRailFidelity();
        };
      });
      safeArray(weekPanel.querySelectorAll("[data-chat-prompt]")).forEach(function (button) {
        button.onclick = function () {
          var prompt = button.getAttribute("data-chat-prompt") || "";
          pushThreadMessage("user", prompt);
          pushThreadMessage("assistant", buildAssistantReply(prompt));
          renderAssistantStudio();
        };
      });
    }

  }

  function renderAgentsDiscovery() {
    var modules = getAgentsModule();
    var activityCard = $("agents-activity");
    var runningCard = $("running-agents");
    var discoveryCard = $("discovery-panel");
    var subtoolsCard = $("subtools-panel");
    var filterRow = $("discovery-filter-row");
    var activity = getAgentActivitySummary();
    var discoverable = getDiscoverableAgents();
    var running = getRunningAgents();
    var approvals = getApprovalAgents();
    var subtools = getSubtools();

    if (filterRow) {
      filterRow.innerHTML = ["all", "executive", "review", "operate", "system"].map(function (lane) {
        var isActive = state.discoveryFilter === lane;
        return '<button type="button" class="filter-chip' + (isActive ? ' is-active' : '') + '" data-discovery-filter="' + lane + '">' + escapeHtml(lane === 'all' ? 'All surfaces' : humanizeToken(lane)) + '</button>';
      }).join("");
      safeArray(filterRow.querySelectorAll("[data-discovery-filter]")).forEach(function (button) {
        button.onclick = function () {
          state.discoveryFilter = button.getAttribute("data-discovery-filter") || "all";
          renderAgentsDiscovery();
        };
      });
    }

    if (activityCard) {
      activityCard.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Agents</p><h3 class="detail-title">Runtime activity</h3><p class="detail-copy">' + escapeHtml(firstDefined(activity.line, 'What is working on your data right now — and a universe more to deploy.')) + '</p></div><span class="pill-inline ok">sovereign</span></div><div class="activity-metrics">' + safeArray(activity.metrics).map(function (item) {
        return '<div class="mini-stat"><strong>' + escapeHtml(firstDefined(item.v, item.value, '0')) + '</strong><span>' + escapeHtml(firstDefined(item.k, item.label, 'metric')) + '</span></div>';
      }).join('') + '</div><ol class="activity-log">' + safeArray(activity.log).map(function (item) { return '<li><span>' + escapeHtml(firstDefined(item.t, 'now')) + '</span><strong>' + escapeHtml(firstDefined(item.who, 'agent')) + '</strong><p>' + escapeHtml(firstDefined(item.a, 'activity')) + '</p></li>'; }).join('') + '</ol>';
    }

    if (runningCard) {
      var runningFiltered = running.filter(function (item) {
        return state.discoveryFilter === 'all' || !item.lane || item.lane === state.discoveryFilter;
      });
      runningCard.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Running now</p><h3 class="detail-title">What is actively working</h3></div><span class="pill-inline ok">' + escapeHtml(String(runningFiltered.length)) + ' visible</span></div><div class="agent-card-list">' + runningFiltered.map(function (item) {
        return '<div class="agent-card"><div class="agent-card__head"><strong>' + escapeHtml(firstDefined(item.name, item.label, item.module_id, 'Agent')) + '</strong><span class="pill-inline ' + toneClass(item.status) + '">' + escapeHtml(firstDefined(item.status, 'running')) + '</span></div><p class="list-copy">' + escapeHtml(firstDefined(item.doing, item.summary, 'Governed activity in progress.')) + '</p><div class="agent-card__meta"><span>' + escapeHtml(firstDefined(item.by, 'StrategyOS')) + '</span><span>' + escapeHtml(firstDefined(item.tag, 'runtime')) + '</span></div><div class="agent-progress"><i style="width:' + escapeHtml(String(Math.max(6, Number(firstDefined(item.progress, 0)) || 0))) + '%"></i></div><ol class="agent-card__trail">' + safeArray(item.log).slice(0, 3).map(function (entry) { return '<li><span>' + escapeHtml(firstDefined(entry.t, 'now')) + '</span><p>' + escapeHtml(firstDefined(entry.a, 'audit entry')) + '</p></li>'; }).join('') + '</ol></div>';
      }).join('') + '</div><div class="agents-sovereign"><span class="sov-dot"></span> sovereign · runs in-tenant · every action logged</div>';
    }

    if (discoveryCard) {
      var filtered = discoverable.filter(function (item) {
        return state.discoveryFilter === 'all' || !item.lane || item.lane === state.discoveryFilter;
      });
      var nativeAgents = filtered.filter(function (item) { return item.source === 'native'; });
      var marketAgents = filtered.filter(function (item) { return item.source !== 'native'; });
      var renderDiscoveryGroup = function (title, items) {
        return '<div class="discovery-group"><div class="discovery-group__label">' + escapeHtml(title) + '</div><div class="discovery-list discovery-list--cards">' + items.map(function (item) {
          return '<div class="discovery-card"><span class="discovery-card__glyph">' + escapeHtml(firstDefined(item.glyph, '◇')) + '</span><div class="discovery-card__meta"><div class="discovery-card__head"><strong>' + escapeHtml(firstDefined(item.name, item.label, item.module_id, 'Agent')) + '</strong><span>' + escapeHtml(firstDefined(item.source === 'native' ? 'StrategyOS' : item.by, item.connector, 'connector')) + '</span></div><p class="list-copy">' + escapeHtml(firstDefined(item.desc, item.summary, 'Discoverable agent surface.')) + '</p><small>' + escapeHtml(firstDefined(item.connector, item.route, 'connector')) + '</small></div><button type="button" class="discovery-card__action">' + escapeHtml(item.source === 'native' ? '+ deploy' : '+ add') + '</button></div>';
        }).join('') + '</div></div>';
      };
      discoveryCard.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Discover agents</p><h3 class="detail-title">Deploy on your data</h3></div><span class="pill-inline warn">expandable</span></div><div class="discovery-search">⌕ Search the agent universe…</div>' + renderDiscoveryGroup('Native on StrategyOS', nativeAgents) + renderDiscoveryGroup('From the marketplace', marketAgents) + '<button type="button" class="browse-agents">Browse all agents →</button>';
    }

    if (subtoolsCard) {
      subtoolsCard.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Sub-agents and approvals</p><h3 class="detail-title">What the chiefs call as tools</h3></div><span class="pill-inline ok">traceable</span></div><div class="subtools-list">' + subtools.map(function (item) {
        return '<div class="subtool-card"><span class="subtool-card__glyph">' + escapeHtml(firstDefined(item.glyph, '▦')) + '</span><div><strong>' + escapeHtml(firstDefined(item.name, 'Tool')) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(item.desc, 'Named sub-agent')) + '</p></div></div>';
      }).join('') + '</div><div class="approval-list">' + approvals.map(function (item) {
        return '<div class="approval-row"><strong>' + escapeHtml(firstDefined(item.label, item.approval_id, 'Approval')) + '</strong><span class="pill-inline ' + toneClass(item.status) + '">' + escapeHtml(firstDefined(item.status, 'waiting')) + '</span><p class="list-copy">Next action: ' + escapeHtml(firstDefined(item.next_action, 'continue')) + '</p></div>';
      }).join('') + '</div>';
    }
  }

  function renderOperatingModelPanel() {
    var row = $('operating-board-state-row');
    var panel = $('operating-model-panel');
    var board = getBoardPortal();
    var modes = safeArray(board.lifecycle_flow).length ? safeArray(board.lifecycle_flow) : (((state.latestPacket || {}).executive_modes || {}).board_states || []);
    var personaEntries = safeArray(state.personas).length ? safeArray(state.personas) : ['ceo', 'cfo', 'gm', 'bucfo', 'logistics', 'board'].map(function (id) { return { persona_id: id, label: humanizeToken(id), active: id === state.activePersona }; });
    if (row) {
      row.innerHTML = modes.map(function (mode) {
        var isActive = mode.state_id === state.activeBoard;
        return '<button type="button" class="state-tab' + (isActive ? ' is-active' : '') + '" data-operating-board="' + escapeHtml(firstDefined(mode.state_id, 'pre')) + '"><span class="state-tab__copy"><strong>' + escapeHtml(firstDefined(mode.label, mode.state_id, 'State')) + '</strong><span>' + escapeHtml(firstDefined(mode.summary, mode.detail, '')) + '</span></span></button>';
      }).join('');
      safeArray(row.querySelectorAll('[data-operating-board]')).forEach(function (button) {
        button.onclick = function () {
          state.activeBoard = button.getAttribute('data-operating-board') || state.activeBoard;
          renderBoardStateTabs();
          renderBoardPortal();
          renderOperatingModelPanel();
          updateHistory();
        };
      });
    }
    if (panel) {
      panel.innerHTML = '<div class="operating-model"><div class="operating-model__lane"><p class="detail-eyebrow">Persona lanes</p><div class="persona-pill-row">' + personaEntries.map(function (persona) {
        return '<button type="button" class="persona-pill' + (persona.persona_id === state.activePersona ? ' is-active' : '') + '" data-operating-persona="' + escapeHtml(firstDefined(persona.persona_id, 'ceo')) + '">' + escapeHtml(firstDefined(persona.label, humanizeToken(persona.persona_id), 'Persona')) + '</button>';
      }).join('') + '</div><p class="list-copy">Switch between operating personas without losing the board-safe packet frame.</p></div><div class="operating-model__lane"><p class="detail-eyebrow">Board lifecycle</p><div class="lifecycle-inline">' + modes.map(function (mode) {
        return '<div class="lifecycle-step' + (mode.state_id === state.activeBoard ? ' is-presented' : '') + '"><div><strong>' + escapeHtml(firstDefined(mode.label, mode.state_id, 'State')) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(mode.summary, mode.detail, '')) + '</p></div></div>';
      }).join('') + '</div><p class="list-copy">Explicit pre / live / closed handling stays visible from the executive surface.</p></div></div>';
      safeArray(panel.querySelectorAll('[data-operating-persona]')).forEach(function (button) {
        button.onclick = function () {
          var personaId = button.getAttribute('data-operating-persona') || 'ceo';
          if (personaId === state.activePersona) return;
          state.activePersona = personaId;
          state.activeView = personaId === 'board' ? 'knowledge' : 'home';
          state.activeDriverKey = '';
          state.activeThreadKey = '';
          refresh(true);
        };
      });
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
    var closeButton = $("assistant-close");
    var threads = personaThreadRecords();
    var current = threadStore()[currentThreadKey()];

    if (drawer) {
      drawer.hidden = !state.drawerOpen;
      drawer.classList.toggle("is-open", state.drawerOpen);
    }
    if (scrim) {
      scrim.hidden = !state.drawerOpen;
      scrim.classList.toggle("is-open", state.drawerOpen);
      scrim.onclick = function () {
        state.drawerOpen = false;
        renderTopbar();
        renderAssistantStudio();
      };
    }
    if (launcher) {
      launcher.hidden = state.drawerOpen || state.activeView === "assistants";
      launcher.onclick = function () {
        state.drawerOpen = true;
        renderTopbar();
        renderAssistantStudio();
      };
    }
    if (closeButton) {
      closeButton.onclick = function () {
        state.drawerOpen = false;
        renderTopbar();
        renderAssistantStudio();
      };
    }

    if (assistantHeading) assistantHeading.textContent = assistantName;
    if (assistantSubtitle) assistantSubtitle.textContent = getPersonaLabel(state.activePersona) + " · " + assistantRole + " · named, threaded chief-of-staff follow-up";
    if (assistantState) assistantState.textContent = humanizeToken(firstDefined(state.activeBoard, "ready"));

    if (threadList) {
      threadList.innerHTML = '<button type="button" class="assistant-thread assistant-thread--new" data-thread-new="true"><strong>＋ New conversation</strong><span>Open a writable, board-safe thread for this persona.</span></button>' + threads.map(function (record) {
        var active = record.key === currentThreadKey();
        return '<button type="button" class="assistant-thread' + (active ? ' is-active' : '') + '" data-thread-key="' + escapeHtml(record.key) + '"><div class="assistant-thread__top"><strong>' + escapeHtml(firstDefined(record.title, 'Thread')) + '</strong><span>' + escapeHtml(friendlyThreadTime(record.lastUpdated)) + '</span></div><span>' + escapeHtml(firstDefined(record.preview, 'Board-safe follow-up')) + '</span><small>' + escapeHtml(String(safeArray(record.messages).length)) + ' message(s) · ' + escapeHtml((record.readOnly ? 'read only' : 'send and receive')) + '</small></button>';
      }).join("");
      safeArray(threadList.querySelectorAll("[data-thread-new]")) .forEach(function (button) {
        button.onclick = function () {
          createWritableThread();
          renderAssistantStudio();
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
      tools.push('<span class="assistant-tool-chip">' + escapeHtml(humanizeToken(firstDefined(state.activeBoard, (getChatContract().assistant || {}).board_state, 'pre'))) + '</span>');
      tools.push('<span class="assistant-tool-chip">' + escapeHtml((current && current.readOnly) ? 'read only thread' : 'send and receive') + '</span>');
      tools.push('<button type="button" class="assistant-tool-chip assistant-tool-chip--button" data-thread-new-inline="true">New conversation</button>');
      if (current && current.route) tools.push('<span class="assistant-tool-chip">' + escapeHtml(current.route) + '</span>');
      threadTools.innerHTML = tools.join('');
      safeArray(threadTools.querySelectorAll('[data-thread-new-inline]')).forEach(function (button) {
        button.onclick = function () {
          createWritableThread();
          renderAssistantStudio();
        };
      });
    }

    if (messages) {
      messages.innerHTML = safeArray(current && current.messages).map(function (message) {
        return '<div class="assistant-message assistant-message--' + escapeHtml(firstDefined(message.role, 'assistant')) + '"><span class="assistant-message__role">' + escapeHtml(firstDefined(message.role, 'assistant')) + ' · ' + escapeHtml(friendlyThreadTime(firstDefined(message.timestamp, 'now'))) + '</span><p>' + escapeHtml(firstDefined(message.text, '')) + '</p></div>';
      }).join("");
      messages.scrollTop = messages.scrollHeight;
    }

    if (promptRow) {
      promptRow.innerHTML = getHeroPrompts().slice(0, 3).map(function (prompt) {
        return '<button class="prompt-chip" type="button" data-assistant-prompt="' + escapeHtml(prompt) + '">' + escapeHtml(prompt) + '</button>';
      }).join("");
      safeArray(promptRow.querySelectorAll("[data-assistant-prompt]")).forEach(function (button) {
        button.onclick = function () {
          var prompt = button.getAttribute("data-assistant-prompt") || "";
          pushThreadMessage("user", prompt);
          pushThreadMessage("assistant", buildAssistantReply(prompt));
          renderAssistantStudio();
        };
      });
    }
  }

  function renderReportSurface() {
    var reportCard = $("report-surface-card");
    var publication = getPublication();
    if (!reportCard) return;
    reportCard.innerHTML = [
      '<div class="detail-head"><div><p class="detail-eyebrow">Report surface</p><h3 class="detail-title">Previewable report routes</h3></div><span class="pill-inline ' + toneClass(firstDefined(publication.publish_state, 'draft')) + '">' + escapeHtml(firstDefined(publication.publish_state, 'draft')) + '</span></div>',
      '<p class="detail-copy">Overview, cases, evidence, and reports now sing as one workspace. This rail keeps the board-safe output explicit.</p>',
      '<div class="mini-list">' + safeArray(publication.available_artifacts).slice(0, 5).map(function (item) {
        return '<div class="list-item"><div><strong>' + escapeHtml(firstDefined(item.title, item.artifact_key, 'Artifact')) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(item.category, 'report')) + ' · ' + escapeHtml(firstDefined(item.format, 'file')) + '</p></div><span class="pill-inline ' + (item.restricted ? 'warn' : 'ok') + '">' + escapeHtml(item.restricted ? 'restricted' : 'board-safe') + '</span></div>';
      }).join("") + '</div>',
      '<a class="summary-link" href="' + escapeHtml(firstDefined(publication.preview_route, '/public/runs/latest/report-preview')) + '">Open report preview</a>'
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
    if (link) link.href = firstDefined(getPublication().preview_route, "/public/runs/latest/report-preview");
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
    renderOperatingModelPanel();
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
      pushThreadMessage("user", message);
      pushThreadMessage("assistant", buildAssistantReply(message));
      input.value = "";
      renderAssistantStudio();
    });
  }

  function bindViewNav() {
    safeArray(document.querySelectorAll("[data-view-target]")).forEach(function (link) {
      link.addEventListener("click", function () {
        state.activeView = link.getAttribute("data-view-target") || "home";
        renderTopbar();
        renderViewNav();
        renderViewPanels();
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
      theme: document.documentElement.getAttribute("data-theme") || "light",
      discoveryFilter: "all",
      selectedAgentModuleKey: "",
      knowledgeQuestionIndex: 0,
      personaOutsideListenerBound: false,
      openDriverNoteKey: "",
      openWeekIndex: 0
    };

  bindAssistantForm();
  bindViewNav();
  refresh(false);
  window.setInterval(function () { refresh(false); }, 60000);
})();
