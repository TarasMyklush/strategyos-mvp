(function () {
  "use strict";

  const TOKEN_KEY = "strategyos.ui.token";
  const bootstrap = JSON.parse(document.getElementById("strategyos-executive-bootstrap").textContent);
  const byId = (id) => document.getElementById(id);

  const els = {
    railStatus: byId("exec-rail-status"),
    runTitle: byId("exec-run-title"),
    runMeta: byId("exec-run-meta"),
    sessionPanel: byId("exec-session-panel"),
    sessionToken: byId("exec-session-token"),
    sessionStatus: byId("exec-session-status"),
    connect: byId("exec-connect"),
    clear: byId("exec-clear"),
    headline: byId("exec-headline"),
    lead: byId("exec-lead"),
    primaryObjective: byId("exec-primary-objective"),
    primaryCaption: byId("exec-primary-caption"),
    commandForm: byId("exec-command-form"),
    commandInput: byId("exec-command-input"),
    commandOutput: byId("exec-command-output"),
    citationBadge: byId("exec-citation-badge"),
    radarFound: byId("exec-radar-found"),
    radarReady: byId("exec-radar-ready"),
    radarBlocked: byId("exec-radar-blocked"),
    radarReview: byId("exec-radar-review"),
    radarHold: byId("exec-radar-hold"),
    radarCitations: byId("exec-radar-citations"),
    kpiRecoverable: byId("exec-kpi-recoverable"),
    kpiFindings: byId("exec-kpi-findings"),
    kpiChallenges: byId("exec-kpi-challenges"),
    decisionBadge: byId("exec-decision-badge"),
    decisionList: byId("exec-decision-list"),
    assistantFeed: byId("exec-assistant-feed"),
    refresh: byId("exec-refresh"),
    evidenceCommand: byId("exec-evidence-command"),
    caseBadge: byId("exec-case-badge"),
    caseBody: byId("exec-case-body"),
    memoTitle: byId("exec-memo-title"),
    memoBody: byId("exec-memo-body"),
    memoList: byId("exec-memo-list"),
  };

  const state = {
    token: window.localStorage.getItem(TOKEN_KEY) || "",
    session: null,
    latestRun: null,
    auditSummary: null,
    knowledgeGraph: null,
    loading: false,
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function formatCount(value) {
    if (value === null || value === undefined || value === "") return "--";
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString() : String(value);
  }

  function formatSar(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "--";
    return `SAR ${Math.round(number).toLocaleString()}`;
  }

  function formatSarShort(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "--";
    const abs = Math.abs(number);
    if (abs >= 1_000_000) return `SAR ${(number / 1_000_000).toFixed(1)}M`;
    if (abs >= 1_000) return `SAR ${(number / 1_000).toFixed(0)}K`;
    return `SAR ${Math.round(number).toLocaleString()}`;
  }

  function compactRunId(run) {
    const raw = String(run?.run_id || run?.id || "");
    return raw ? raw.slice(0, 8) : "latest";
  }

  function authHeaders(extra = {}) {
    const headers = { Accept: "application/json", ...extra };
    if (state.token) {
      headers.Authorization = `Bearer ${state.token}`;
      headers["X-API-Key"] = state.token;
    }
    return headers;
  }

  async function requestJson(path, options = {}) {
    const method = options.method || "GET";
    const headers = authHeaders(options.body ? { "Content-Type": "application/json" } : {});
    const response = await fetch(path, {
      method,
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    const text = await response.text();
    let payload = {};
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (_error) {
        payload = { detail: text };
      }
    }
    if (!response.ok) {
      const detail = payload?.detail || response.statusText || "Request failed";
      const error = new Error(Array.isArray(detail) ? JSON.stringify(detail) : String(detail));
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  async function guarded(label, promise, fallback) {
    try {
      return await promise;
    } catch (error) {
      return { ...(fallback || {}), status: "failed", reason: `${label}: ${error.message}` };
    }
  }

  function citationSummary(run) {
    if (state.auditSummary?.status === "ok") {
      return {
        count: state.auditSummary.citation_count,
        resolved: state.auditSummary.resolved_count,
      };
    }
    const acceptance = run?.acceptance || {};
    if (acceptance.citation_count !== undefined || acceptance.resolved_citation_count !== undefined) {
      return {
        count: acceptance.citation_count,
        resolved: acceptance.resolved_citation_count,
      };
    }
    return { count: null, resolved: null };
  }

  function challengedSummary(run) {
    if (Array.isArray(state.auditSummary?.challenged_finding_ids)) {
      return state.auditSummary.challenged_finding_ids.length;
    }
    const verification = run?.audit_verification || {};
    if (Array.isArray(verification.challenged_finding_ids)) return verification.challenged_finding_ids.length;
    if (verification.actual_challenged_findings !== undefined) return verification.actual_challenged_findings;
    return run?.audit_event_count ?? null;
  }

  function isAuthenticated() {
    const session = state.session || {};
    return Boolean(session.authenticated || session.auth_disabled || !bootstrap.api_auth_enabled);
  }

  function displaySession() {
    const session = state.session || {};
    const authDisabled = session.auth_disabled || !bootstrap.api_auth_enabled;
    const display = session.display_name || session.display_subject || session.subject || "anonymous";
    els.sessionToken.value = state.token;
    els.sessionPanel.classList.toggle("hidden", authDisabled || Boolean(session.authenticated));
    els.sessionStatus.textContent = authDisabled
      ? "Auth disabled in this environment. Loading live data."
      : session.authenticated
        ? `Connected as ${display}.`
        : "Paste an operator or reviewer token to load live run data.";
    els.railStatus.textContent = isAuthenticated() ? "SYSTEM ONLINE" : "AUTH REQUIRED";
  }

  function renderLocked() {
    displaySession();
    els.runTitle.textContent = "Executive cockpit locked";
    els.runMeta.textContent = "Connect an operator or reviewer session";
    els.headline.textContent = "Connect to load live finance intelligence.";
    els.lead.textContent = "The public preview contains no sensitive run data. This cockpit loads KPIs, evidence, and command answers only after authentication.";
    els.primaryObjective.textContent = "--";
    els.primaryCaption.textContent = "Waiting for authenticated run data.";
    els.commandOutput.textContent = "Connect a session before running commands.";
    els.citationBadge.textContent = "-- citations";
    els.radarFound.textContent = "--";
    els.radarReady.textContent = "--";
    els.radarBlocked.textContent = "--";
    els.radarReview.textContent = "--";
    els.radarHold.textContent = "--";
    els.radarCitations.textContent = "--";
    els.kpiRecoverable.textContent = "--";
    els.kpiFindings.textContent = "--";
    els.kpiChallenges.textContent = "--";
    els.decisionBadge.textContent = "locked";
    els.decisionList.innerHTML = decisionCard("Connect session", "Use the same operator/reviewer token as the dashboard.", "--", "auth");
    els.assistantFeed.innerHTML = message("system", "System readout", "No live data is loaded on the public surface. Connect a session to activate the executive cockpit.");
    els.caseBody.innerHTML = '<tr><td colspan="5">Connect a session to load cases.</td></tr>';
    els.memoBody.textContent = "Live board narrative will load from the latest run state.";
    els.memoList.innerHTML = "";
  }

  function decisionCard(title, text, amount, status) {
    return `
      <article class="decision-card">
        <div>
          <h3>${escapeHtml(title)}</h3>
          <p>${escapeHtml(text)}</p>
        </div>
        <div class="amount">${escapeHtml(amount)}<span>${escapeHtml(status)}</span></div>
      </article>
    `;
  }

  function message(kind, title, text) {
    return `
      <div class="message ${kind === "system" ? "system" : ""}">
        <strong>${escapeHtml(title)}</strong>
        <p>${escapeHtml(text)}</p>
      </div>
    `;
  }

  function extractGraphFindings() {
    const nodes = Array.isArray(state.knowledgeGraph?.nodes) ? state.knowledgeGraph.nodes : [];
    return nodes
      .map((node) => node?.data || node || {})
      .filter((node) => {
        const type = String(node.type || node.kind || node.label || node.group || "").toLowerCase();
        const id = String(node.id || node.finding_id || "");
        return type.includes("finding") || /^F[-_]/i.test(id);
      })
      .slice(0, 6);
  }

  function renderCases(run, citations, challenged) {
    const graphFindings = extractGraphFindings();
    if (graphFindings.length) {
      els.caseBadge.textContent = `${graphFindings.length} graph cases`;
      els.caseBody.innerHTML = graphFindings.map((finding, index) => {
        const title = finding.title || finding.name || finding.finding_type || finding.id || `Finding ${index + 1}`;
        const amount = finding.recoverable_sar || finding.amount_sar || finding.value_sar || finding.value || "";
        const confidence = finding.confidence || finding.risk || "review";
        return `
          <tr>
            <td><strong>${escapeHtml(title)}</strong><small>${escapeHtml(finding.id || finding.finding_id || "knowledge graph")}</small></td>
            <td>${escapeHtml(finding.owner || "reviewer")}</td>
            <td><span class="badge green">${escapeHtml(citations.resolved ?? "--")} cites</span></td>
            <td>${escapeHtml(finding.next_action || "Open evidence")}</td>
            <td>${escapeHtml(amount ? formatSarShort(amount) : confidence)}</td>
          </tr>
        `;
      }).join("");
      return;
    }

    els.caseBadge.textContent = run?.status === "missing" ? "no run" : "latest run";
    if (!run || run.status === "missing") {
      els.caseBody.innerHTML = '<tr><td colspan="5">No completed analysis is available yet.</td></tr>';
      return;
    }
    els.caseBody.innerHTML = `
      <tr>
        <td><strong>Latest run review</strong><small>run ${escapeHtml(compactRunId(run))}</small></td>
        <td>Operator / Reviewer</td>
        <td><span class="badge green">${escapeHtml(citations.resolved ?? "--")} / ${escapeHtml(citations.count ?? "--")}</span></td>
        <td>Review dashboard controls</td>
        <td>${escapeHtml(challenged ? `${challenged} challenges` : "Low")}</td>
      </tr>
      <tr>
        <td><strong>Findings packet</strong><small>${escapeHtml(formatCount(run.locked_findings ?? run.findings))} locked findings</small></td>
        <td>Reviewer</td>
        <td><span class="badge blue">evidence chain</span></td>
        <td>Ask deterministic command</td>
        <td>${escapeHtml(formatSarShort(run.total_recoverable_sar))}</td>
      </tr>
    `;
  }

  function renderLive() {
    displaySession();
    const run = state.latestRun || {};
    const missing = !run || run.status === "missing";
    const citations = citationSummary(run);
    const challenged = challengedSummary(run);
    const recoverable = run.total_recoverable_sar;
    const findings = run.locked_findings ?? run.findings;
    const status = String(run.status || "missing").replaceAll("_", " ");

    els.runTitle.textContent = missing ? "No completed run yet" : `run ${compactRunId(run)} · ${status}`;
    els.runMeta.textContent = `${bootstrap.environment || "environment"} · ${new Date().toLocaleString()}`;
    els.headline.textContent = missing
      ? "No live finance run is ready yet."
      : `${formatCount(challenged || 0)} challenge${Number(challenged || 0) === 1 ? "" : "s"} and ${formatCount(findings)} finding${Number(findings || 0) === 1 ? "" : "s"} need executive attention.`;
    els.lead.textContent = missing
      ? "Start an analysis in the review app, then return here for command-level recovery intelligence."
      : "I checked the latest run, evidence chain, and auditor challenge state. Use the command line to ask only questions answerable from uploaded files.";
    els.primaryObjective.textContent = formatSarShort(recoverable);
    els.primaryCaption.textContent = missing
      ? "Recoverable value will load from the latest run."
      : "Recoverable value identified in the latest governed analysis.";

    const citationText = citations.count !== null && citations.count !== undefined
      ? `${formatCount(citations.resolved)} / ${formatCount(citations.count)} citations`
      : "-- citations";
    els.citationBadge.textContent = citationText;
    els.radarFound.textContent = formatSarShort(recoverable).replace("SAR ", "");
    els.radarReady.textContent = formatCount(findings);
    els.radarBlocked.textContent = formatCount(challenged);
    els.radarReview.textContent = run.approval_status ? String(run.approval_status).slice(0, 7) : "--";
    els.radarHold.textContent = run.current_stage ? String(run.current_stage).slice(0, 6) : "--";
    els.radarCitations.textContent = citations.resolved ?? "--";
    els.kpiRecoverable.textContent = formatSar(recoverable);
    els.kpiFindings.textContent = `${formatCount(run.locked_findings ?? findings)} / ${formatCount(run.findings ?? findings)}`;
    els.kpiChallenges.textContent = challenged === null || challenged === undefined ? "--" : formatCount(challenged);
    els.decisionBadge.textContent = missing ? "no run" : `${formatCount(challenged || 0)} challenge${Number(challenged || 0) === 1 ? "" : "s"}`;

    if (missing) {
      els.decisionList.innerHTML = decisionCard("Start analysis", "Open the review app and upload a source pack before using executive controls.", "--", "missing");
      els.assistantFeed.innerHTML = message("system", "System readout", "No latest run is available. The cockpit is online, but there is no finance intelligence to summarize yet.");
      renderCases(run, citations, challenged);
      return;
    }

    els.decisionList.innerHTML = [
      decisionCard("Review latest recovery packet", `Run status: ${status}. Approval state: ${run.approval_status || "not reported"}.`, formatSarShort(recoverable), "review"),
      decisionCard("Check evidence chain", `Citation status: ${citationText}.`, citations.count && citations.resolved === citations.count ? "closed" : "open", "evidence"),
      decisionCard("Resolve auditor challenges", `${formatCount(challenged || 0)} challenge events are visible to the cockpit.`, formatCount(challenged || 0), "human"),
      decisionCard("Use deterministic command", "Ask questions that can be answered from uploaded files and cited findings.", "QA", "safe"),
    ].join("");

    els.assistantFeed.innerHTML = [
      message("system", "System readout", `Latest run is ${status}. Recoverable value: ${formatSar(recoverable)}.`),
      message("", "Recommended next move", challenged ? "Open the dashboard and resolve auditor challenges before releasing final recovery communications." : "Evidence and challenge state look clear enough to review the recovery packet."),
      message("", "Guardrail", "Do not place uncited claims into vendor letters. Use the command line for cited deterministic answers."),
      message("", "Board note", `The current packet contains ${formatCount(findings)} finding${Number(findings || 0) === 1 ? "" : "s"} and ${citationText}.`),
    ].join("");

    els.memoTitle.textContent = "What to say in the room";
    els.memoBody.textContent = `The latest run identifies ${formatSar(recoverable)} recoverable value. Decision quality now depends on closing reviewer and evidence gates, not more dashboard browsing.`;
    els.memoList.innerHTML = [
      `<div>Run: ${escapeHtml(run.run_id || "latest")}.</div>`,
      `<div>Evidence: ${escapeHtml(citationText)}.</div>`,
      `<div>Challenges: ${escapeHtml(formatCount(challenged || 0))} visible events.</div>`,
    ].join("");
    renderCases(run, citations, challenged);
  }

  async function refreshLiveData() {
    state.loading = true;
    els.refresh.disabled = true;
    els.refresh.textContent = "Refreshing...";
    try {
      state.session = await guarded("Session", requestJson("/ui/session"), { authenticated: false });
      if (!isAuthenticated()) {
        renderLocked();
        return;
      }
      const [latestRun, auditSummary, knowledgeGraph] = await Promise.all([
        guarded("Latest run", requestJson("/runs/latest"), { status: "missing" }),
        guarded("Audit summary", requestJson("/runs/latest/audit-summary"), { status: "missing" }),
        guarded("Knowledge graph", requestJson("/runs/latest/knowledge-graph"), { status: "missing", nodes: [], edges: [], meta: {} }),
      ]);
      state.latestRun = latestRun;
      state.auditSummary = auditSummary;
      state.knowledgeGraph = knowledgeGraph;
      renderLive();
    } finally {
      state.loading = false;
      els.refresh.disabled = false;
      els.refresh.textContent = "Refresh live data";
    }
  }

  function renderCommandResult(payload) {
    const answer = payload?.answer || "No answer returned.";
    const citations = Array.isArray(payload?.citations) ? payload.citations : [];
    const citationHtml = citations.length
      ? `<div><strong>Citations</strong>${citations.slice(0, 5).map((citation) => (
        `<br>${escapeHtml(citation.source_path || "source")} ${escapeHtml(citation.locator || "")}`
      )).join("")}</div>`
      : "<div><strong>Citations</strong><br>No citations returned.</div>";
    const suggestions = Array.isArray(payload?.suggestions) && payload.suggestions.length
      ? `<div><strong>Try</strong>${payload.suggestions.slice(0, 3).map((item) => `<br>${escapeHtml(item)}`).join("")}</div>`
      : "";
    els.commandOutput.innerHTML = `<strong>${payload?.matched === false ? "No deterministic match" : "Answer"}</strong><br>${escapeHtml(answer)}<br><br>${citationHtml}${suggestions ? `<br>${suggestions}` : ""}`;
  }

  async function submitCommand(question) {
    const trimmed = String(question || "").trim();
    if (!trimmed) return;
    if (!isAuthenticated()) {
      els.commandOutput.textContent = "Connect a session before running commands.";
      return;
    }
    els.commandOutput.textContent = "Running deterministic command...";
    try {
      const runId = state.latestRun?.run_id || null;
      const payload = await requestJson("/qa", {
        method: "POST",
        body: { question: trimmed, run_id: runId, mode: "deterministic" },
      });
      renderCommandResult(payload);
    } catch (error) {
      els.commandOutput.textContent = `Command failed: ${error.message}`;
    }
  }

  els.connect.addEventListener("click", async () => {
    state.token = els.sessionToken.value.trim();
    window.localStorage.setItem(TOKEN_KEY, state.token);
    await refreshLiveData();
  });

  els.clear.addEventListener("click", async () => {
    state.token = "";
    window.localStorage.removeItem(TOKEN_KEY);
    await refreshLiveData();
  });

  els.refresh.addEventListener("click", refreshLiveData);

  els.evidenceCommand.addEventListener("click", () => {
    els.commandInput.value = "What is the total recoverable?";
    submitCommand(els.commandInput.value);
  });

  els.commandForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitCommand(els.commandInput.value);
  });

  refreshLiveData();
})();
