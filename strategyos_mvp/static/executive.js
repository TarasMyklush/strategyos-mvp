(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var bootstrapScript = $("strategyos-executive-bootstrap");
  var bootstrap = bootstrapScript ? JSON.parse(bootstrapScript.textContent) : {};
  if (bootstrap.environment) {}
  if (bootstrap.api_auth_enabled) {}
  var _tokenKey = "strategyos.ui.token";
  var DESIGN = (window.STRATEGYOS_EXECUTIVE_DESIGN && window.STRATEGYOS_EXECUTIVE_DESIGN.personas) || {};

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

  function getExecutiveDiagnostics() {
    return (state.latestPacket && state.latestPacket.executive_diagnostics) || {};
  }

  function getBoardPortal() {
    return (state.latestPacket && state.latestPacket.board_portal) || {};
  }

  function getChatContract() {
    return (state.latestPacket && state.latestPacket.chat) || {};
  }

  function getPublication() {
    return (state.latestPacket && state.latestPacket.publication) || {};
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
        sub: item.sub,
        chips: safeArray(item.chips),
        movers: item.movers || {},
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
    var session = state.session || {};
    var packet = state.latestPacket || {};
    var activePersona = getPersonaContract(state.activePersona);
    var org = $("brand-org");
    var badge = $("state-badge");
    var personaLabel = $("persona-label");
    var list = $("pm-list");
    var btn = $("persona-btn");

    if (org) org.textContent = firstDefined(session.tenant_context && session.tenant_context.tenant_name, bootstrap.product_name, "StrategyOS");
    if (badge) badge.textContent = firstDefined((packet.plan_health || {}).badge, "Governed executive view");
    if (personaLabel) personaLabel.textContent = firstDefined(activePersona.label, "Group CEO");
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

  function renderWorkspaceNav() {
    safeArray(document.querySelectorAll("[data-nav-target]")).forEach(function (link) {
      link.classList.toggle("is-active", link.getAttribute("data-nav-target") === state.activeNav);
    });
  }

  function renderHero() {
    var diagnostics = getExecutiveDiagnostics();
    var hero = diagnostics.hero || {};
    var publication = getPublication();
    var boardPortal = getBoardPortal();
    var agents = getAgentsModule();
    var score = Number(firstDefined(hero.score, 0));
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

    $("hero-eyebrow").textContent = getPersonaLabel(state.activePersona) + " diagnostics";
    $("hero-head").textContent = firstDefined(hero.summary, hero.label, getPlanHealth().label, "Plan health overview");
    $("hero-body").textContent = firstDefined(hero.body, getPlanHealth().summary, "Awaiting executive diagnostics.");
    $("hero-score").textContent = String(clampedScore || 0);
    $("hero-cap").textContent = firstDefined(hero.score_note, getPlanHealth().badge, "plan health");
    $("hero-byline").textContent = firstDefined(hero.quoted_by, "Governed packet only");

    var quote = $("hero-quote");
    if (quote) {
      if (hero.quote) {
        quote.hidden = false;
        quote.textContent = hero.quote;
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
    var publication = getPublication();
    var gravity = getDrilldown().gravity || {};
    var movers = driver.movers || {};
    var lifting = safeArray(movers.lifting);
    var dragging = safeArray(movers.dragging);
    if (drillCard) {
      var trendSeries = driverTrendSeries(driver);
      var actualSeries = safeArray(trendSeries.actual).length ? safeArray(trendSeries.actual) : [92, 96, 99, 101, 100, 102];
      var planSeries = safeArray(trendSeries.plan).length ? safeArray(trendSeries.plan) : actualSeries.map(function (value) { return value * 0.98; });
      var minSeries = Math.min.apply(null, actualSeries.concat(planSeries));
      var maxSeries = Math.max.apply(null, actualSeries.concat(planSeries));
      var spanSeries = Math.max(1, maxSeries - minSeries);
      var chartWidth = 220;
      var chartHeight = 70;
      var chartPoints = function (series) {
        return series.map(function (value, idx) {
          var x = series.length === 1 ? chartWidth / 2 : (idx * chartWidth) / (series.length - 1);
          var y = chartHeight - (((value - minSeries) / spanSeries) * 54 + 8);
          return [x, y];
        });
      };
      var actualPath = chartPoints(actualSeries).map(function (pair, idx) {
        return (idx ? "L" : "M") + pair[0].toFixed(1) + "," + pair[1].toFixed(1);
      }).join(" ");
      var planPath = chartPoints(planSeries).map(function (pair, idx) {
        return (idx ? "L" : "M") + pair[0].toFixed(1) + "," + pair[1].toFixed(1);
      }).join(" ");
      drillCard.innerHTML = [
        '<div class="detail-head"><div><p class="detail-eyebrow">Cases</p><h3 class="detail-title">' + escapeHtml(firstDefined(driver.label, "Driver drill")) + '</h3></div><span class="pill-inline ' + toneClass(firstDefined(driver.status, publication.publish_state, "governed")) + '">' + escapeHtml(firstDefined(driver.status, publication.publish_state, "governed")) + '</span></div>',
        '<p class="detail-copy">' + escapeHtml(firstDefined(driver.detail, "Awaiting drill detail.")) + '</p>',
        '<div class="detail-stat-row">',
        '<div class="detail-stat-block"><strong class="detail-stat">' + escapeHtml(firstDefined(driver.metric, "—")) + '</strong><span>' + escapeHtml(firstDefined(driver.sub, "Current measure")) + '</span></div>',
        '<div class="detail-stat-block"><strong class="detail-stat">' + escapeHtml(firstDefined(driver.pct, "—")) + '</strong><span>% of plan</span></div>',
        '<div class="detail-stat-block"><strong class="detail-stat">' + escapeHtml(firstDefined(driver.trendLabel, "Governed trend")) + '</strong><span>' + escapeHtml(firstDefined(driver.unit, "packet basis")) + '</span></div>',
        '</div>',
        '<div class="trend-chain"><article class="trend-chain__card"><div class="trend-chain__head"><strong>Trend + evidence chain</strong><span>why this driver moved</span></div><svg class="trend-chain__chart" viewBox="0 0 220 70" aria-hidden="true"><path class="trend-chain__plan" d="' + escapeHtml(planPath) + '"></path><path class="trend-chain__actual" d="' + escapeHtml(actualPath) + '"></path></svg><div class="trend-chain__meta"><div><strong>' + escapeHtml(firstDefined(driver.metric, "—")) + '</strong><span>' + escapeHtml(firstDefined(driver.trendLabel, "Governed trend")) + '</span></div><div><strong>' + escapeHtml(firstDefined(publication.publish_state, 'draft')) + '</strong><span>Release posture</span></div></div></article><article class="trend-chain__card"><div class="trend-chain__head"><strong>Signal read</strong><span>bounded by current packet truth</span></div><div class="trend-chain__stack"><div><strong>' + escapeHtml(firstDefined(driver.label, 'Driver story')) + '</strong><span>' + escapeHtml(firstDefined(driver.detail, 'Awaiting driver story.')) + '</span></div><div><strong>' + escapeHtml(String(firstDefined((getDrilldown().owed_upward || {}).challenge_count, publication.challenged_cases, 0))) + ' challenged</strong><span>Questions still attached to evidence</span></div></div></article></div>',
        '<p class="detail-subtitle">What is lifting</p>',
        '<div class="mini-list">' + (lifting.length ? lifting.map(function (item) {
          return '<div class="mover-card"><div class="mover-card__head"><strong>' + escapeHtml(firstDefined(item.name, "Lift")) + '</strong><span class="pill-inline ok">lifting</span></div>' + moverSourceBadge(item) + '<p class="list-copy">' + escapeHtml(firstDefined(item.note, item.delta, "Momentum visible in the packet.")) + '</p><div class="mover-card__foot"><span>' + escapeHtml(firstDefined(item.delta, 'up')) + '</span><strong>' + escapeHtml(String(firstDefined(item.contribution, ''))) + ' contribution pts</strong></div></div>';
        }).join("") : '<div class="discovery-empty">No lifting signal is attached to this driver yet.</div>') + '</div>',
        '<p class="detail-subtitle">What still drags</p>',
        '<div class="mini-list">' + (dragging.length ? dragging.map(function (item) {
          return '<div class="mover-card mover-card--warn"><div class="mover-card__head"><strong>' + escapeHtml(firstDefined(item.name, "Constraint")) + '</strong><span class="pill-inline warn">dragging</span></div>' + moverSourceBadge(item) + '<p class="list-copy">' + escapeHtml(firstDefined(item.note, item.delta, "Constraint still needs closure.")) + '</p><div class="mover-card__foot"><span>' + escapeHtml(firstDefined(item.delta, 'watch')) + '</span><strong>' + escapeHtml(String(firstDefined(item.contribution, ''))) + ' contribution pts</strong></div></div>';
        }).join("") : '<div class="discovery-empty">No dragging signal is attached to this driver yet.</div>') + '</div>',
        '<p class="detail-subtitle">Tornado view</p>',
        '<div class="detail-tornado">' + lifting.concat(dragging).slice(0, 5).map(function (item, idx) {
          var tone = idx < lifting.length ? '' : ' warn';
          var contribution = Math.abs(Number(firstDefined(item.contribution, 0)) || 0);
          var width = Math.max(14, Math.min(100, contribution * 3.2 || 20));
          return '<div class="mover-bar"><span class="mover-bar__label">' + escapeHtml(firstDefined(item.name, 'Signal')) + '</span><span class="mover-bar__track"><i class="mover-bar__fill' + tone + '" style="width:' + width + '%"></i></span><span class="mover-bar__value">' + escapeHtml(firstDefined(item.delta, item.contribution, 'trend')) + '</span></div>';
        }).join("") + '</div>'
      ].join("");
    }
    if (gravityPanel) {
      gravityPanel.innerHTML = [
        '<div class="detail-head"><div><p class="detail-eyebrow">Evidence</p><h3 class="detail-title">Gravity and guardrails</h3></div><span class="pill-inline ' + toneClass(firstDefined(publication.publish_state, "draft")) + '">' + escapeHtml(firstDefined(publication.publish_state, "draft")) + '</span></div>',
        '<p class="detail-copy">' + escapeHtml(firstDefined(gravity.quote, "Keep the room inside governed packet truth.")) + '</p>',
        '<p class="panel-note">' + escapeHtml(firstDefined(gravity.by, "StrategyOS")) + '</p>',
        '<div class="pill-row">' + safeArray(gravity.rails).map(function (item) {
          return '<span class="pill-inline ' + toneClass(item) + '">' + escapeHtml(item) + '</span>';
        }).join("") + '</div>',
        '<p class="detail-subtitle">Suggested questions</p>',
        '<div class="mini-list">' + safeArray(gravity.prompts).slice(0, 3).map(function (prompt) {
          return '<button class="timeline-chip" type="button" data-chat-prompt="' + escapeHtml(prompt) + '"><strong>' + escapeHtml(prompt) + '</strong><span>Send to assistant</span></button>';
        }).join("") + '</div>'
      ].join("");
      safeArray(gravityPanel.querySelectorAll("[data-chat-prompt]")).forEach(function (button) {
        button.onclick = function () {
          var prompt = button.getAttribute("data-chat-prompt") || "";
          pushThreadMessage("user", prompt);
          pushThreadMessage("assistant", buildAssistantReply(prompt));
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
    var lowerRail = (getExecutiveDiagnostics().composition || {}).lower_rail || getDrilldown().lower_rail || {};
    var developmentsPanel = $("developments-panel");
    var weekPanel = $("week-panel");
    var fidelityPanel = $("lower-rail-fidelity");
    var developments = safeArray(lowerRail.developments).slice(0, 3);
    var weekAhead = safeArray(lowerRail.week_ahead).slice(0, 3);
    var owed = (lowerRail.owed_upward || {}).items || [];

    if (developmentsPanel) {
      developmentsPanel.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Evidence</p><h3 class="detail-title">Developments in focus</h3></div><span class="pill-inline ok">live signal</span></div><div class="mini-list">' + developments.map(function (item) {
        return '<div class="list-item"><div><strong>' + escapeHtml(firstDefined(item.title, "Development")) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(item.detail, "Awaiting detail.")) + '</p></div><span class="pill-inline ' + toneClass((item.chips || [])[0]) + '">' + escapeHtml(firstDefined((item.chips || [])[0], "update")) + '</span></div>';
      }).join("") + '</div>';
    }

    if (weekPanel) {
      weekPanel.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Week ahead</p><h3 class="detail-title">Upcoming decision moments</h3></div><span class="pill-inline warn">time-bound</span></div><div class="mini-list">' + weekAhead.map(function (item) {
        return '<button class="timeline-chip' + (item.urgent ? ' is-urgent' : '') + '" type="button" data-chat-prompt="' + escapeHtml(firstDefined(item.prompt, item.label)) + '"><span><strong>' + escapeHtml(firstDefined(item.label, "Event")) + '</strong><span>' + escapeHtml(firstDefined(item.foot, item.detail, "")) + '</span></span><span>' + escapeHtml(firstDefined(item.detail, "soon")) + '</span></button>';
      }).join("") + '</div>';
      safeArray(weekPanel.querySelectorAll("[data-chat-prompt]")).forEach(function (button) {
        button.onclick = function () {
          var prompt = button.getAttribute("data-chat-prompt") || "";
          pushThreadMessage("user", prompt);
          pushThreadMessage("assistant", buildAssistantReply(prompt));
          renderAssistantStudio();
        };
      });
    }

    if (fidelityPanel) {
      fidelityPanel.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Evidence closure</p><h3 class="detail-title">What is still owed upward</h3></div><span class="pill-inline warn">governed</span></div><div class="mini-list">' + safeArray(owed).slice(0, 3).map(function (item) {
        return '<div class="list-item"><div><strong>' + escapeHtml(firstDefined(item.on, item.to, "Obligation")) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(item.note, "Awaiting authored line.")) + '</p></div><span class="pill-inline ' + toneClass(item.status) + '">' + escapeHtml(firstDefined(item.status, "pending")) + '</span></div>';
      }).join("") + '</div>';
    }
  }

  function renderAgentsDiscovery() {
    var modules = getAgentsModule();
    var activityCard = $("agents-activity");
    var runningCard = $("running-agents");
    var discoveryCard = $("discovery-panel");
    var subtoolsCard = $("subtools-panel");
    var filterRow = $("discovery-filter-row");
    var discoverable = safeArray(modules.discoverable);
    var running = safeArray(modules.running);
    var approvals = safeArray(modules.approvals);
    var selected = state.selectedAgentModuleKey;

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
      activityCard.innerHTML = [
        '<div class="detail-head"><div><p class="detail-eyebrow">Agents</p><h3 class="detail-title">Runtime activity</h3></div><span class="pill-inline ok">active</span></div>',
        '<p class="detail-copy">' + escapeHtml(firstDefined((modules.audit_log || [])[0] && (modules.audit_log || [])[0].detail, "Governed agent activity appears here as visible operating posture.")) + '</p>',
        '<div class="activity-metrics">' + [
          { label: 'Running', value: firstDefined((modules.summary || {}).running_count, running.length, 0) },
          { label: 'Discoverable', value: firstDefined((modules.summary || {}).discoverable_count, discoverable.length, 0) },
          { label: 'Approvals', value: firstDefined((modules.summary || {}).approval_count, approvals.length, 0) },
          { label: 'Boundary', value: 'tenant scoped' }
        ].map(function (item) {
          return '<div class="mini-stat"><strong>' + escapeHtml(item.value) + '</strong><span>' + escapeHtml(item.label) + '</span></div>';
        }).join("") + '</div>'
      ].join("");
    }

    if (runningCard) {
      var runningFiltered = running.filter(function (item) {
        return state.discoveryFilter === 'all' || item.lane === state.discoveryFilter;
      });
      runningCard.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Running</p><h3 class="detail-title">Running agents list</h3></div><span class="pill-inline ok">' + escapeHtml(String(runningFiltered.length)) + ' visible</span></div><div class="running-list">' + runningFiltered.map(function (item) {
        var key = firstDefined(item.module_id, item.label, 'agent');
        return '<button type="button" class="agent-select' + (selected === key ? ' is-active' : '') + '" data-agent-select="' + escapeHtml(key) + '"><div><strong>' + escapeHtml(firstDefined(item.label, item.module_id, 'Agent')) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(item.summary, 'Awaiting agent summary.')) + '</p></div><span class="pill-inline ' + toneClass(item.status) + '">' + escapeHtml(firstDefined(item.status, 'idle')) + '</span></button>';
      }).join("") + '</div>';
    }

    if (discoveryCard) {
      var filtered = discoverable.filter(function (item) {
        return state.discoveryFilter === 'all' || item.lane === state.discoveryFilter;
      });
      discoveryCard.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Discover</p><h3 class="detail-title">Discoverable agents</h3></div><span class="pill-inline warn">expandable</span></div><div class="discovery-list">' + filtered.map(function (item) {
        var key = firstDefined(item.module_id, item.label, 'module');
        return '<button type="button" class="agent-select' + (selected === key ? ' is-active' : '') + '" data-agent-select="' + escapeHtml(key) + '"><div><strong>' + escapeHtml(firstDefined(item.label, item.module_id, 'Module')) + '</strong><p class="list-copy">' + escapeHtml(firstDefined(item.summary, 'Discoverable module surface.')) + '</p></div><span class="pill-inline ' + (item.permitted ? 'ok' : 'warn') + '">' + escapeHtml(item.permitted ? 'permitted' : 'role-bound') + '</span></button>';
      }).join("") + '</div>';
    }

    if (subtoolsCard) {
      var selectedItem = running.concat(discoverable).find(function (item) {
        return firstDefined(item.module_id, item.label, '') === selected;
      }) || running[0] || discoverable[0] || null;
      if (!selected && selectedItem) state.selectedAgentModuleKey = firstDefined(selectedItem.module_id, selectedItem.label, '');
      subtoolsCard.innerHTML = '<div class="detail-head"><div><p class="detail-eyebrow">Governance</p><h3 class="detail-title">Approvals and audit trail</h3></div><span class="pill-inline ok">traceable</span></div>'
        + (selectedItem ? '<div class="agent-detail-grid"><div class="agent-detail-card"><strong>' + escapeHtml(firstDefined(selectedItem.label, selectedItem.module_id, 'Selected agent')) + '</strong><span>' + escapeHtml(firstDefined(selectedItem.summary, 'Governed module surface.')) + '</span><span class="panel-note">' + escapeHtml(firstDefined(selectedItem.route, selectedItem.output_metric, 'Route pending')) + '</span></div><div class="agent-detail-card"><strong>Filter</strong><span>' + escapeHtml(humanizeToken(state.discoveryFilter)) + '</span><span class="panel-note">Running and discover lists now reconcile against the same surface filter.</span></div></div>' : '')
        + '<div class="subtools-list">' + approvals.map(function (item) {
        return '<div class="agent-row"><div class="subtool-head"><strong>' + escapeHtml(firstDefined(item.label, item.approval_id, 'Approval')) + '</strong><span class="pill-inline ' + toneClass(item.status) + '">' + escapeHtml(firstDefined(item.status, 'waiting')) + '</span></div><p class="list-copy">Next action: ' + escapeHtml(firstDefined(item.next_action, 'continue')) + '</p><span class="panel-note">' + escapeHtml(firstDefined(item.route, 'no route')) + '</span></div>';
      }).join("") + '</div>';
    }

    safeArray(document.querySelectorAll('[data-agent-select]')).forEach(function (button) {
      button.onclick = function () {
        state.selectedAgentModuleKey = button.getAttribute('data-agent-select') || '';
        renderAgentsDiscovery();
      };
    });
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
    var threads = personaThreadRecords();
    var current = threadStore()[currentThreadKey()];

    if (assistantHeading) assistantHeading.textContent = assistantName;
    if (assistantSubtitle) assistantSubtitle.textContent = getPersonaLabel(state.activePersona) + " · " + assistantRole + " · simple local thread memory";
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
    renderWorkspaceNav();
    renderHero();
    renderDriverGrid();
    renderMetrics();
    renderDriverDrillFidelity();
    renderBoardStateTabs();
    renderBoardPortal();
    renderLowerRailFidelity();
    renderAgentsDiscovery();
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

  function bindWorkspaceNav() {
    safeArray(document.querySelectorAll("[data-nav-target]")).forEach(function (link) {
      link.addEventListener("click", function () {
        state.activeNav = link.getAttribute("data-nav-target") || "overview";
        renderWorkspaceNav();
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
      activeNav: "overview",
      discoveryFilter: "all",
      selectedAgentModuleKey: "",
      personaOutsideListenerBound: false
    };

  bindAssistantForm();
  bindWorkspaceNav();
  refresh(false);
  window.setInterval(function () { refresh(false); }, 60000);
})();
