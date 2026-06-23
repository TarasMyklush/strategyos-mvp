(function () {
  "use strict";

  const $ = function (id) { return document.getElementById(id); };
  const _tokenKey = "strategyos.ui.token";
  const bootstrapScript = $("strategyos-executive-bootstrap");
  const bootstrap = bootstrapScript ? JSON.parse(bootstrapScript.textContent) : {};
  if (bootstrap.environment) {}
  if (bootstrap.api_auth_enabled) {}

  function viewStateRoute(path) { return path; }
  function requestJson(path) { return fetch(path).then(function (r) { return r.json(); }); }
  requestJson(viewStateRoute("/public/runs/latest"));

  const state = {
    latestPacket: null,
    session: null,
    personas: [],
    activePersona: "ceo",
    activeDriver: null,
    token: null,
  };

  let personaOutsideListenerBound = false;

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function humanizeToken(token) {
    if (!token) return "—";
    return String(token)
      .replace(/_/g, " ")
      .replace(/-/g, " ")
      .split(" ")
      .filter(Boolean)
      .map(function (part) { return part.charAt(0).toUpperCase() + part.slice(1); })
      .join(" ");
  }

  function firstDefined() {
    for (let i = 0; i < arguments.length; i += 1) {
      if (arguments[i] !== undefined && arguments[i] !== null && arguments[i] !== "") {
        return arguments[i];
      }
    }
    return "";
  }

  function safeArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function getActiveDriver() {
    if (state.activeDriver) return state.activeDriver;
    const drivers = getVisibleDrivers();
    return drivers.find(function (item) { return item.active; }) || drivers[0] || null;
  }

  function getVisibleDrivers() {
    const drivers = safeArray(state.latestPacket && state.latestPacket.executive_modes && state.latestPacket.executive_modes.driver_focus);
    const filtered = drivers.filter(function (item) {
      const personaIds = safeArray(item.persona_ids);
      return !personaIds.length || personaIds.indexOf(state.activePersona) >= 0;
    });
    return (filtered.length ? filtered : drivers).slice(0, 4);
  }

  function buildMetrics(packet, driver) {
    const planHealth = packet && packet.plan_health ? packet.plan_health : {};
    const publication = packet && packet.publication ? packet.publication : {};
    const boardPack = publication.board_pack || {};
    const lowerRail = packet && packet.drilldown && packet.drilldown.lower_rail ? packet.drilldown.lower_rail : {};
    const owedUpward = lowerRail.owed_upward || {};

    return [
      {
        label: "Plan posture",
        value: firstDefined(planHealth.label, "Awaiting governed run"),
        detail: firstDefined(planHealth.summary, "No current plan posture summary."),
      },
      {
        label: "Governance",
        value: humanizeToken(firstDefined(planHealth.governance_status, publication.approval_status, "pending")),
        detail: firstDefined(planHealth.boundary, "Governed executive view only."),
      },
      {
        label: "Board artifacts",
        value: String(Number(firstDefined(publication.report_count, 0))) + " surfaced",
        detail: firstDefined(boardPack.status ? "Board pack is " + humanizeToken(boardPack.status).toLowerCase() + "." : "Board pack status is waiting."),
      },
      {
        label: "Next action",
        value: humanizeToken(firstDefined(planHealth.next_action, publication.approval && publication.approval.next_action, driver && driver.status, "review")),
        detail: owedUpward.challenge_count ? String(owedUpward.challenge_count) + " challenged item(s) still shape the room." : "No challenged items are currently holding the room open.",
      },
    ];
  }

  function renderTopbar() {
    const session = state.session || {};
    const org = $("brand-org");
    if (org) {
      org.textContent = firstDefined(session.tenant_context && session.tenant_context.tenant_name, bootstrap.product_name, "StrategyOS Live");
    }

    const activePersona = safeArray(state.personas).find(function (persona) {
      return persona.persona_id === state.activePersona;
    });
    const personaLabel = $("persona-label");
    if (personaLabel) {
      personaLabel.textContent = firstDefined(activePersona && activePersona.label, "Group CEO");
    }

    const badge = $("state-badge");
    const packet = state.latestPacket || {};
    if (badge) {
      badge.textContent = firstDefined(packet.plan_health && packet.plan_health.badge, "Governed executive view");
    }

    const list = $("pm-list");
    const btn = $("persona-btn");
    if (!list || !btn) return;

    list.innerHTML = "";
    safeArray(state.personas).forEach(function (persona) {
      const item = document.createElement("button");
      const isActive = persona.persona_id === state.activePersona;
      item.type = "button";
      item.className = "persona-item" + (isActive ? " is-active" : "");
      item.setAttribute("role", "menuitem");
      item.innerHTML = "<span>" + escapeHtml(firstDefined(persona.label, persona.persona_id, "Persona")) + "</span><span class=\"persona-item__tag\">" + escapeHtml(persona.persona_id || "") + "</span>";
      item.onclick = function () {
        state.activePersona = persona.persona_id;
        state.activeDriver = null;
        renderTopbar();
        renderHero();
        renderDriverGrid();
        renderMetrics();
        renderSummary();
        list.hidden = true;
        btn.setAttribute("aria-expanded", "false");
      };
      list.appendChild(item);
    });

    btn.onclick = function () {
      const expanded = btn.getAttribute("aria-expanded") === "true";
      list.hidden = expanded;
      btn.setAttribute("aria-expanded", expanded ? "false" : "true");
    };

    if (!personaOutsideListenerBound) {
      document.addEventListener("click", function (event) {
        const menu = $("persona-menu");
        const panel = $("pm-list");
        const trigger = $("persona-btn");
        if (menu && panel && trigger && !panel.hidden && !event.target.closest("#persona-menu")) {
          panel.hidden = true;
          trigger.setAttribute("aria-expanded", "false");
        }
      });
      personaOutsideListenerBound = true;
    }
  }

  function renderHero() {
    const packet = state.latestPacket || {};
    const hero = packet.executive_diagnostics && packet.executive_diagnostics.hero ? packet.executive_diagnostics.hero : {};
    const score = Number(firstDefined(hero.score, 0));
    const clampedScore = Math.max(0, Math.min(100, score));
    const circumference = 2 * Math.PI * 48;
    const dash = circumference * (clampedScore / 100);

    const activePersona = safeArray(state.personas).find(function (persona) { return persona.persona_id === state.activePersona; }) || {};
    $("hero-eyebrow").textContent = firstDefined(activePersona.label, hero.persona_label, "Group CEO") + " diagnostics";
    $("hero-head").textContent = firstDefined(hero.label, packet.plan_health && packet.plan_health.label, "Plan health overview");
    $("hero-body").textContent = firstDefined(hero.body, hero.summary, packet.plan_health && packet.plan_health.summary, "No governed executive narrative is available yet.");
    $("hero-score").textContent = score || 0;
    $("hero-cap").textContent = firstDefined(hero.score_note, packet.plan_health && packet.plan_health.badge, "plan health");

    const arc = $("hero-arc");
    if (arc) {
      arc.setAttribute("stroke-dasharray", dash + " " + (circumference - dash));
    }
  }

  function renderDriverGrid() {
    const grid = $("driver-row");
    if (!grid) return;

    const drivers = getVisibleDrivers();
    const activeDriver = getActiveDriver();
    grid.innerHTML = "";

    drivers.forEach(function (driver) {
      const tile = document.createElement("button");
      tile.type = "button";
      tile.className = "driver-tile" + (activeDriver && activeDriver.driver_key === driver.driver_key ? " is-selected" : "");
      tile.innerHTML = [
        '<span class="driver-overline">' + escapeHtml(firstDefined(driver.status, "status")) + '</span>',
        '<span class="driver-metric">' + escapeHtml(firstDefined(driver.metric, "—")) + '</span>',
        '<strong class="driver-label">' + escapeHtml(firstDefined(driver.label, "Driver")) + '</strong>',
        '<p class="driver-detail">' + escapeHtml(firstDefined(driver.detail, "")) + '</p>'
      ].join("");
      tile.onclick = function () {
        state.activeDriver = driver;
        renderDriverGrid();
        renderMetrics();
        renderSummary();
      };
      grid.appendChild(tile);
    });
  }

  function renderMetrics() {
    const grid = $("metrics-grid");
    if (!grid) return;
    const metrics = buildMetrics(state.latestPacket || {}, getActiveDriver());
    grid.innerHTML = "";

    metrics.forEach(function (metric) {
      const card = document.createElement("article");
      card.className = "metric-card";
      card.innerHTML = [
        '<span class="metric-label">' + escapeHtml(metric.label) + '</span>',
        '<strong class="metric-value">' + escapeHtml(metric.value) + '</strong>',
        '<p class="metric-detail">' + escapeHtml(metric.detail) + '</p>'
      ].join("");
      grid.appendChild(card);
    });
  }

  function renderSummary() {
    const packet = state.latestPacket || {};
    const planHealth = packet.plan_health || {};
    const hero = packet.executive_diagnostics && packet.executive_diagnostics.hero ? packet.executive_diagnostics.hero : {};
    const driver = getActiveDriver() || {};
    const link = $("summary-link");

    $("summary-kicker").textContent = firstDefined(driver.label, "Current readout");
    $("summary-title").textContent = firstDefined(hero.label, planHealth.label, driver.label, "Executive signal");
    $("summary-body").textContent = firstDefined(driver.detail, hero.body, hero.summary, planHealth.summary, "Awaiting executive summary.");
    $("summary-note").textContent = firstDefined(planHealth.boundary, hero.quote, "");

    if (link) {
      link.href = firstDefined(driver.route, packet.publication && packet.publication.preview_route, "/executive");
    }
  }

  async function refresh() {
    try {
      const response = await Promise.all([
        fetch("/public/runs/latest").then(function (r) { return r.ok ? r.json() : null; }),
        fetch("/ui/session").then(function (r) { return r.ok ? r.json() : null; })
      ]);

      const packet = response[0] || {};
      const session = response[1] || {};
      const personas = safeArray(packet.executive_modes && packet.executive_modes.personas);

      state.latestPacket = packet;
      state.session = session;
      state.personas = personas;
      state.activePersona = personas.some(function (persona) {
        return persona.persona_id === state.activePersona;
      })
        ? state.activePersona
        : firstDefined(packet.executive_modes && packet.executive_modes.active_persona_id, state.activePersona, "ceo");
      state.token = firstDefined(session.token, state.token, localStorage.getItem(_tokenKey));

      if (!state.activeDriver) {
        state.activeDriver = safeArray(packet.executive_modes && packet.executive_modes.driver_focus).find(function (item) { return item.active; }) || null;
      } else {
        const freshDriver = safeArray(packet.executive_modes && packet.executive_modes.driver_focus).find(function (item) {
          return item.driver_key === state.activeDriver.driver_key;
        });
        state.activeDriver = freshDriver || state.activeDriver;
      }

      renderTopbar();
      renderHero();
      renderDriverGrid();
      renderMetrics();
      renderSummary();
    } catch (error) {
      console.warn("executive refresh failed", error);
    }
  }

  refresh();
  setInterval(refresh, 60000);
})();
