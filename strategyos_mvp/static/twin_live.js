(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  function text(value, fallback) { return value === undefined || value === null || value === "" ? (fallback || "—") : String(value); }
  function safeArray(value) { return Array.isArray(value) ? value : []; }
  function detectRole() {
    if (window.ROLE) return window.ROLE;
    var path = String(window.location.pathname || "").toLowerCase();
    if (path.indexOf("/twin/cfo") !== -1) return "cfo";
    if (path.indexOf("/twin/gm") !== -1) return "gm";
    return "ceo";
  }

  var ROLE = detectRole();

  function statusTone(status) {
    var value = String(status || "unknown").toLowerCase();
    if (value === "current" || value === "healthy") return "green";
    if (value === "missing" || value === "critical") return "red";
    return "amber";
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;");
  }

  function formatValue(value) {
    if (value && typeof value === "object") return escapeHtml(JSON.stringify(value));
    if (typeof value === "number") {
      if (Math.abs(value) >= 1000000) return (value / 1000000).toFixed(1).replace(/\.0$/, "") + "M";
      if (Math.abs(value) >= 1000) return (value / 1000).toFixed(1).replace(/\.0$/, "") + "K";
    }
    return escapeHtml(text(value));
  }

  function fetchJson(path, options) {
    return fetch(path, options).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    });
  }

  function renderKpis(payload) {
    var grid = $("kpi-grid");
    if (!grid || !payload || !payload.kpis) return;
    var items = Object.keys(payload.kpis).map(function (key) { return payload.kpis[key]; });
    grid.innerHTML = items.map(function (item) {
      return ""
        + '<div class="kpi-card">'
        + '  <span class="kpi-dot ' + statusTone(item.status || item.health) + '"></span>'
        + '  <div class="kpi-name">' + escapeHtml(item.label || item.node_id) + '</div>'
        + '  <div class="kpi-value">' + formatValue(item.value) + '</div>'
        + '  <span class="kpi-status ' + escapeHtml(item.status || 'unknown') + '">' + escapeHtml(item.status || item.health || 'unknown') + '</span>'
        + '  <div class="text-sm mt-8">Threshold: ' + escapeHtml(text(item.threshold, 'bounded')) + '</div>'
        + '  <div class="text-sm">Freshness: ' + escapeHtml(text(item.freshness, 'n/a')) + '</div>'
        + '</div>';
    }).join("");
  }

  function renderInvestigations(statusPayload) {
    var list = $("inv-list");
    if (!list) return;
    var details = safeArray(statusPayload && statusPayload.active_investigation_details);
    $("inv-count") && ($("inv-count").textContent = details.length + " active investigations");
    $("inv-count-bar") && ($("inv-count-bar").textContent = String(details.length));
    if (!details.length) {
      list.innerHTML = '<li class="inv-item"><div class="inv-item__info"><div class="inv-item__title">No active investigations</div><div class="inv-item__assignee">Twin state is clear.</div></div><span class="inv-item__status resolved">clear</span></li>';
      return;
    }
    list.innerHTML = details.slice(-6).reverse().map(function (item) {
      var runId = (((item || {}).run_context || {}).run_id);
      var evidenceCount = safeArray(item.evidence).length;
      return ""
        + '<li class="inv-item">'
        + '  <div class="inv-item__info">'
        + '    <div class="inv-item__title">' + escapeHtml(item.query || item.id || 'Investigation') + '</div>'
        + '    <div class="inv-item__assignee">Run: ' + escapeHtml(text(runId, 'none')) + ' · Evidence: ' + evidenceCount + '</div>'
        + '    <div class="progress-bar"><div class="progress-fill active" style="width:' + (runId ? '100' : '40') + '%"></div></div>'
        + '  </div>'
        + '  <span class="inv-item__status ' + (runId ? 'resolved' : 'open') + '">' + (runId ? 'linked' : 'open') + '</span>'
        + '</li>';
    }).join('');
  }

  function renderInbox(payload) {
    var list = $("inbox-list");
    if (!list || !payload) return;
    $("unread-count-bar") && ($("unread-count-bar").textContent = String(payload.message_count || 0));
    list.innerHTML = safeArray(payload.messages).slice(0, 6).map(function (item) {
      var sender = text(item.from, 'Twin');
      return ""
        + '<li class="inbox-item">'
        + '  <div class="inbox-item__icon">' + escapeHtml(sender.charAt(0).toUpperCase()) + '</div>'
        + '  <div class="inbox-item__body">'
        + '    <div class="inbox-item__sender">' + escapeHtml(sender) + '</div>'
        + '    <div class="inbox-item__subject">' + escapeHtml(text(item.subject, 'Message')) + '</div>'
        + '    <div class="inbox-item__meta"><span>' + escapeHtml(text(item.timestamp, '')) + '</span><span class="priority-badge ' + escapeHtml(text(item.priority, 'normal')) + '">' + escapeHtml(text(item.priority, 'normal')) + '</span></div>'
        + '  </div>'
        + '</li>';
    }).join('') || '<li class="inbox-item"><div class="inbox-item__body"><div class="inbox-item__subject">No recent messages.</div></div></li>';
  }

  function renderAudit(payload) {
    if (typeof window.renderAuditHistory === "function") {
      window.renderAuditHistory(payload && payload.governance && payload.governance.history);
    }
  }

  function renderStatus(payload) {
    if (!payload) return;
    $("cycle-count") && ($("cycle-count").textContent = text(payload.cycle_count, "0"));
    $("last-wake") && ($("last-wake").textContent = text(payload.last_wake, "—"));
    $("pending-count-bar") && ($("pending-count-bar").textContent = text(payload.pending_requests, "0"));
    if (payload.status) {
      $("status-label") && ($("status-label").textContent = text(payload.status));
      $("twin-status-value") && ($("twin-status-value").textContent = text(payload.status));
      var dot = $("status-dot");
      if (dot) dot.className = "status-dot " + String(payload.status).toLowerCase();
    }
    renderInvestigations(payload);
  }

  function renderStructuredResponse(target, data) {
    if (!target || !data) return;
    var evidence = safeArray(data.evidence);
    var board = data.board || {};
    var runContext = data.run_context || {};
    var response = data.response || {};
    target.innerHTML = ''
      + '<div class="response-card">'
      + '  <h4>Twin Response</h4>'
      + '  <p>' + escapeHtml(text(response.summary, 'No response available.')) + '</p>'
      + '  <p><strong>Run:</strong> ' + escapeHtml(text(runContext.run_id, 'none')) + ' · <strong>Approval:</strong> ' + escapeHtml(text(runContext.approval_status, 'pending')) + ' · <strong>Board:</strong> ' + escapeHtml(text(board.status, 'pending')) + '</p>'
      + '  <p><strong>Board preview:</strong> ' + escapeHtml(text(board.preview_route, 'not available')) + '</p>'
      + '  <div><strong>Evidence</strong><ul>'
      + (evidence.map(function (item) {
          return '<li>'
            + escapeHtml(text(item.finding_id, 'finding')) + ' — '
            + escapeHtml(text(item.title, 'Untitled'))
            + ' (' + escapeHtml(text(item.citation_count, '0')) + ' citations)'
            + '</li>';
        }).join('') || '<li>No linked evidence records.</li>')
      + '  </ul></div>'
      + '</div>';
  }

  function submitInvestigation(query) {
    return fetchJson('/twin/api/investigate/' + ROLE + '?query=' + encodeURIComponent(query), { method: 'POST' });
  }

  function bindPrimaryQuery() {
    var input = $("query-input");
    var button = $("query-btn");
    var responseBox = $("response-box");
    if (!input || !button || !responseBox) return;

    var cleanButton = button.cloneNode(true);
    button.parentNode.replaceChild(cleanButton, button);

    function run() {
      var query = String(input.value || "").trim();
      if (!query) return;
      responseBox.innerHTML = '<span class="text-muted">Twin is investigating live StrategyOS data…</span>';
      submitInvestigation(query).then(function (data) {
        renderStructuredResponse(responseBox, data);
        input.value = "";
        loadTwinData();
      }).catch(function (error) {
        responseBox.innerHTML = '<span class="text-muted">Failed to investigate: ' + escapeHtml(error.message) + '</span>';
      });
    }

    cleanButton.addEventListener('click', run);
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') run();
    });

    safeArray(document.querySelectorAll('.prompt-chip')).forEach(function (chip) {
      var cleanChip = chip.cloneNode(true);
      chip.parentNode.replaceChild(cleanChip, chip);
      cleanChip.addEventListener('click', function () {
        input.value = cleanChip.getAttribute('data-prompt') || cleanChip.textContent || '';
        run();
      });
    });
  }

  function bindSecondaryQuery() {
    var input = $("twin-query");
    var panel = $("response-panel");
    if (!input || !panel) return;

    function run() {
      var query = String(input.value || "").trim();
      if (!query) return;
      panel.innerHTML = '<p>Investigating live StrategyOS data…</p>';
      submitInvestigation(query).then(function (data) {
        renderStructuredResponse(panel, data);
        input.value = "";
        loadTwinData();
      }).catch(function (error) {
        panel.innerHTML = '<p style="color:var(--red);">Failed to investigate: ' + escapeHtml(error.message) + '</p>';
      });
    }

    window.askTwin = run;
    window.askCFO = run;
    window.askGM = run;
  }

  function loadTwinData() {
    return Promise.all([
      fetchJson('/twin/api/status/' + ROLE),
      fetchJson('/twin/api/kpis/' + ROLE),
      fetchJson('/twin/api/inbox/' + ROLE),
      fetchJson('/twin/api/history/' + ROLE)
    ]).then(function (results) {
      renderStatus(results[0]);
      renderKpis(results[1]);
      renderInbox(results[2]);
      renderAudit(results[3]);
    }).catch(function (error) {
      console.error('Twin live data load failed:', error);
    });
  }

  function init() {
    bindPrimaryQuery();
    bindSecondaryQuery();
    loadTwinData();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
