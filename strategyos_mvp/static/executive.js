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
    planHealthBadge: byId("exec-plan-health-badge"),
    planHealthStatus: byId("exec-plan-health-status"),
    planHealthNote: byId("exec-plan-health-note"),
    planHealthBoundary: byId("exec-plan-health-boundary"),
    planKpiValue: byId("exec-plan-kpi-value"),
    planKpiValueNote: byId("exec-plan-kpi-value-note"),
    planKpiCases: byId("exec-plan-kpi-cases"),
    planKpiCasesNote: byId("exec-plan-kpi-cases-note"),
    planKpiEvidence: byId("exec-plan-kpi-evidence"),
    planKpiEvidenceNote: byId("exec-plan-kpi-evidence-note"),
    scopeNote: byId("exec-scope-note"),
    companySwitcher: byId("exec-company-switcher"),
    portfolioSwitcher: byId("exec-portfolio-switcher"),
    scopeSummary: byId("exec-scope-summary"),
    scopeBreadcrumb: byId("exec-scope-breadcrumb"),
  };

  const state = {
    token: window.localStorage.getItem(TOKEN_KEY) || "",
    session: null,
    latestRun: null,
    auditSummary: null,
    knowledgeGraph: null,
    latestFindings: null,
    pendingReviews: null,
    runDetail: null,
    selectedFindingId: null,
    selectedPortfolio: "all",
    publicEvidencePreview: null,
    publicReportPreview: null,
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

  function findingsPayload() {
    return state.latestFindings && Array.isArray(state.latestFindings.findings)
      ? state.latestFindings.findings
      : [];
  }

  function approvalSummary(run) {
    return run?.approval_status || run?.approval?.approval_status || "pending";
  }

  function currentTenantContext() {
    return state.session?.tenant_context || state.runDetail?.summary_json?.tenant_context || {};
  }

  function renderScopeRibbon() {
    const tenant = currentTenantContext();
    const companyLabel = tenant.tenant_name || tenant.tenant_id || "Current company";
    const portfolios = [
      { value: "all", label: "All governed portfolios" },
      { value: "finance", label: "Finance diagnostics" },
      { value: "evidence", label: "Evidence posture" },
      { value: "reports", label: "Report posture" },
    ];
    if (els.companySwitcher) {
      els.companySwitcher.innerHTML = `<option value="current">${escapeHtml(companyLabel)}</option>`;
      els.companySwitcher.value = "current";
    }
    if (els.portfolioSwitcher) {
      els.portfolioSwitcher.innerHTML = portfolios.map((item) => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join("");
      els.portfolioSwitcher.value = state.selectedPortfolio;
    }
    if (els.scopeSummary) {
      const portfolioLabel = portfolios.find((item) => item.value === state.selectedPortfolio)?.label || "All governed portfolios";
      els.scopeSummary.textContent = `${companyLabel} · ${portfolioLabel}`;
    }
    if (els.scopeBreadcrumb) {
      els.scopeBreadcrumb.textContent = state.selectedFindingId
        ? `${state.selectedFindingId} → evidence → reports`
        : "Overview → cases → evidence → reports";
    }
  }

  function reportArtifacts() {
    const fromDetail = state.runDetail?.summary_json?.artifacts;
    if (fromDetail && typeof fromDetail === "object") return fromDetail;
    const fromRun = state.latestRun?.artifacts;
    if (fromRun && typeof fromRun === "object") return fromRun;
    return {};
  }

  function reportLabel(key) {
    return String(key || "report").replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
  }

  function findingsTotals() {
    const findings = findingsPayload();
    if (!findings.length) {
      return { ready: 0, challenged: 0, review: 0, total: 0 };
    }
    return findings.reduce((totals, finding) => {
      totals.total += 1;
      if (finding?.challenged) {
        totals.challenged += 1;
      } else if (String(finding?.status || "").toLowerCase().includes("review") || String(finding?.confidence || "").toLowerCase() === "review") {
        totals.review += 1;
      } else {
        totals.ready += 1;
      }
      return totals;
    }, { ready: 0, challenged: 0, review: 0, total: 0 });
  }

  function renderPlanHealth(config) {
    els.planHealthBadge.textContent = config.badge;
    els.planHealthStatus.textContent = config.status;
    els.planHealthNote.textContent = config.note;
    els.planHealthBoundary.textContent = config.boundary;
    els.planKpiValue.textContent = config.value;
    els.planKpiValueNote.textContent = config.valueNote;
    els.planKpiCases.textContent = config.cases;
    els.planKpiCasesNote.textContent = config.casesNote;
    els.planKpiEvidence.textContent = config.evidence;
    els.planKpiEvidenceNote.textContent = config.evidenceNote;
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
      ? "Auth disabled in this environment. Executive remains read-only while live data loads."
      : session.authenticated
        ? `Connected as ${display}. Executive remains read-only; use /app for approvals or run control.`
        : "Paste an operator or reviewer token to unlock live run data. Executive remains read-only.";
    els.railStatus.textContent = isAuthenticated() ? "SYSTEM ONLINE" : "AUTH REQUIRED";
    renderScopeRibbon();
  }

  function renderLocked() {
    displaySession();
    const run = state.latestRun || {};
    const findings = findingsPayload();
    const citations = citationSummary(run);
    const challenged = Array.isArray(state.auditSummary?.challenged_finding_ids)
      ? state.auditSummary.challenged_finding_ids.length
      : findings.filter((item) => item?.challenged).length;
    const totals = findingsTotals();
    if (run?.status === "ok" || findings.length) {
      els.runTitle.textContent = run?.run_id ? `public preview · ${compactRunId(run)}` : "Public preview";
      els.runMeta.textContent = "Anonymous-safe snapshot of the latest governed run";
      els.headline.textContent = findings.length
        ? `${formatCount(findings.length)} governed case${Number(findings.length) === 1 ? "" : "s"} are visible on the anonymous demo path.`
        : "A governed run is available on the anonymous demo path.";
      els.lead.textContent = "This route now shows a truthful public-safe slice: latest cases, one sanitized evidence drill-down, and a board-safe report note. Protected controls still require authentication.";
      els.primaryObjective.textContent = formatSarShort(run?.total_recoverable_sar);
      els.primaryCaption.textContent = "Latest recoverable value from the governed run.";
      els.commandOutput.textContent = "Connect a session before running commands.";
      byId("exec-overview-status").textContent = run?.approval_status ? `Latest run ${run.approval_status}` : "Latest run available";
      byId("exec-overview-note").textContent = "Anonymous viewers see only a sanitized demo slice of the latest run.";
      byId("exec-queue-count").textContent = formatCount(findings.length || run?.locked_findings);
      byId("exec-queue-note").textContent = "Public queue mirrors governed findings only, not reviewer assignments.";
      byId("exec-evidence-status").textContent = state.publicEvidencePreview?.resolved ? "resolved" : "public-safe";
      byId("exec-evidence-note").textContent = "Excerpt and locator are sanitized for public demo use. Full packet stays protected.";
      byId("exec-report-status").textContent = "board-safe preview";
      byId("exec-report-note").textContent = "This note is synthesized for anonymous demo use; protected artifact bodies remain gated.";
      const citationText = citations.count !== null && citations.count !== undefined
        ? `${formatCount(citations.resolved)} / ${formatCount(citations.count)} citations`
        : `${formatCount(findings.reduce((sum, item) => sum + Number(item?.citation_count || 0), 0))} cites`;
      els.citationBadge.textContent = citationText;
      els.radarFound.textContent = formatSarShort(run?.total_recoverable_sar).replace("SAR ", "");
      els.radarReady.textContent = formatCount(findings.length || run?.locked_findings);
      els.radarBlocked.textContent = formatCount(challenged || 0);
      els.radarReview.textContent = run?.approval_status || "pending";
      els.radarHold.textContent = run?.requires_human_review ? "review gate" : "open";
      els.radarCitations.textContent = formatCount(citations.count);
      els.kpiRecoverable.textContent = formatSarShort(run?.total_recoverable_sar);
      els.kpiFindings.textContent = formatCount(findings.length || run?.locked_findings);
      els.kpiChallenges.textContent = formatCount(challenged || 0);
      els.decisionBadge.textContent = "public-safe";
      els.decisionList.innerHTML = [
        decisionCard("1. Latest governed cases", "Anonymous viewers can see the top governed findings without crossing the auth boundary.", formatCount(findings.length || run?.locked_findings), "public"),
        decisionCard("2. Sanitized evidence drill-down", "One evidence preview stays truthful but strips protected payload details.", formatCount(citations.count), "sanitized"),
        decisionCard("3. Board-safe report note", "The anonymous path now shows a report summary without exposing restricted artifact bodies.", run?.approval_status || "pending", "public"),
      ].join("");
      els.assistantFeed.innerHTML = [
        message("system", "Anonymous surface", "The latest governed run now exposes a narrow, public-safe hero story without weakening protected controls."),
        message("", "Evidence boundary", "Detailed citation payloads, reviewer actions, and protected artifacts still require an operator or reviewer session."),
      ].join("");
      renderCases(run, citations, challenged);

      const evidence = state.publicEvidencePreview;
      if (evidence?.status === "ok") {
        byId("exec-evidence-badge").textContent = evidence?.hash_match === false ? "check source" : "public-safe excerpt";
        byId("exec-evidence-title").textContent = evidence.title || evidence.finding_id || "Governed evidence packet";
        byId("exec-evidence-summary").textContent = `${evidence.finding_id || "finding"} · ${evidence.vendor_name || evidence.vendor_id || "reviewer"} · ${evidence.confidence || "review"}`;
        byId("exec-evidence-source").textContent = evidence.source_path || "Stored evidence";
        byId("exec-evidence-locator").textContent = evidence.locator || "No locator";
        byId("exec-evidence-confidence").textContent = evidence.confidence || "review";
        byId("exec-evidence-resolution").textContent = evidence.resolved ? "Resolved citation" : "Stored citation";
        byId("exec-evidence-preview").textContent = evidence.excerpt || "Stored evidence excerpt unavailable.";
      } else {
        setEvidencePreviewFallback("No public-safe evidence preview is available yet.", "awaiting evidence");
      }

      const report = state.publicReportPreview;
      const reportChoices = Array.isArray(report?.available_artifacts) && report.available_artifacts.length
        ? report.available_artifacts
        : [{ artifact_key: report?.artifact_key || "executive_summary", title: report?.title || "Executive summary" }];
      byId("exec-report-badge").textContent = `${reportChoices.length} public preview${reportChoices.length === 1 ? "" : "s"}`;
      byId("exec-report-list").innerHTML = reportChoices.map((item) => `
        <button class="report-button" type="button" data-artifact-key="${escapeHtml(item.artifact_key || "executive_summary")}">
          <strong>${escapeHtml(item.title || item.artifact_key || "Executive summary")}</strong>
          <span>Anonymous-safe preview</span>
        </button>
      `).join("");
      byId("exec-report-list").querySelectorAll("[data-artifact-key]").forEach((button) => {
        button.addEventListener("click", () => loadReportPreview(button.getAttribute("data-artifact-key")));
      });
      byId("exec-report-preview").textContent = report?.preview_text || "No board-safe report preview is available yet.";
      els.memoBody.textContent = "The anonymous route now tells one truthful story: governed cases exist, evidence is cited, and outputs stay under human control.";
      els.memoList.innerHTML = [
        `<div>Run: ${escapeHtml(run?.run_id || "latest")}</div>`,
        `<div>Cases: ${escapeHtml(formatCount(findings.length || run?.locked_findings))}</div>`,
        `<div>Boundary: protected reviewer controls still require authentication.</div>`,
      ].join("");
      renderPlanHealth({
        badge: "bounded KPI layer",
        status: challenged ? "Human gate visible" : "Finance signal available",
        note: challenged
          ? `${formatCount(challenged)} challenge${Number(challenged) === 1 ? " is" : "s are"} keeping the public story bounded to finance evidence and review posture.`
          : "The public story can now show value, case count, and evidence posture without pretending broader enterprise plan logic exists.",
        boundary: "Finance-derived signal only — StrategyOS is summarizing current case, evidence, and report posture, not a full enterprise strategy compiler.",
        value: formatSarShort(run?.total_recoverable_sar),
        valueNote: "Current value signal comes from the latest governed finance run, not from portfolio-wide planning data.",
        cases: totals.total ? `${formatCount(totals.total)} cases` : formatCount(findings.length || run?.locked_findings),
        casesNote: totals.total
          ? `${formatCount(totals.ready)} ready · ${formatCount(totals.review)} in review · ${formatCount(totals.challenged)} challenged.`
          : "Public-safe case count mirrors the governed queue, without reviewer assignment detail.",
        evidence: citations.count !== null && citations.count !== undefined
          ? `${formatCount(citations.resolved)} / ${formatCount(citations.count)} cited`
          : `${formatCount(challenged || 0)} challenges`,
        evidenceNote: "Evidence and release posture stay deliberately narrow here: citation chain, challenge state, and board-safe preview only.",
      });
      renderScopeRibbon();
      return;
    }
    els.runTitle.textContent = "Anonymous executive demo";
    els.runMeta.textContent = "Public posture only · live evidence remains protected";
    els.headline.textContent = "See how StrategyOS turns finance evidence into governed executive action.";
    els.lead.textContent = "The anonymous surface shows the real workflow shape — overview, cases, evidence, and reports — while live run data, citations, approvals, and board artifacts stay behind operator or reviewer access.";
    els.primaryObjective.textContent = "4-stage flow";
    renderScopeRibbon();
    els.primaryCaption.textContent = "Intake → governed findings → evidence packet → board-ready report.";
    els.commandOutput.textContent = "Connect a session before running commands.";
    byId("exec-overview-status").textContent = "Anonymous demo mode";
    byId("exec-overview-note").textContent = "StrategyOS can show the governed surface shape publicly, but it exposes no live recovery data without authentication.";
    byId("exec-queue-count").textContent = "4 stages";
    byId("exec-queue-note").textContent = "Follow the public story below, then authenticate to load the real review queue.";
    byId("exec-evidence-status").textContent = "Boundary intact";
    byId("exec-evidence-note").textContent = "Evidence packets, excerpts, and citation payloads stay hidden until a trusted session is present.";
    byId("exec-report-status").textContent = "Preview posture only";
    byId("exec-report-note").textContent = "Board-ready files and report previews remain protected on the public surface.";
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
    els.decisionBadge.textContent = "story mode";
    els.decisionList.innerHTML = [
      decisionCard("1. Intake source pack", "Operators upload a governed source pack and start analysis in the review app.", "Input", "public"),
      decisionCard("2. Produce governed findings", "StrategyOS converts source material into reviewable finance cases with recoverable value and risk posture.", "Cases", "public"),
      decisionCard("3. Inspect evidence packet", "Every claim stays attached to citations, excerpts, and challenge state before action is approved.", "Evidence", "protected"),
      decisionCard("4. Release board-ready report", "Reports and outbound actions stay behind human control until the reviewer boundary is satisfied.", "Reports", "protected"),
    ].join("");
    els.assistantFeed.innerHTML = [
      message("system", "Anonymous surface", "You are seeing the executive demo path only. Live findings, evidence, and report data remain hidden."),
      message("", "Hero story", "A StrategyOS run moves from source intake to governed cases, then to evidence review, and finally to report publication."),
      message("", "Boundary", "Protected controls are still real. Authenticate with an operator or reviewer session before loading any live packet."),
    ].join("");
    els.caseBody.innerHTML = `
      <tr>
        <td><strong>Source intake</strong><small>Operator uploads finance pack</small></td>
        <td>Operator</td>
        <td><span class="badge blue">Protected input</span></td>
        <td>Start governed analysis</td>
        <td>Boundary held</td>
      </tr>
      <tr>
        <td><strong>Governed findings</strong><small>StrategyOS creates reviewable cases</small></td>
        <td>Reviewer</td>
        <td><span class="badge green">Cases + citations</span></td>
        <td>Open evidence packet</td>
        <td>Needs live session</td>
      </tr>
      <tr>
        <td><strong>Evidence packet</strong><small>Excerpt, locator, confidence, challenge state</small></td>
        <td>Reviewer</td>
        <td><span class="badge amber">Restricted</span></td>
        <td>Approve or challenge</td>
        <td>Human gate</td>
      </tr>
      <tr>
        <td><strong>Board report</strong><small>Board-safe memo and stored report artifacts</small></td>
        <td>Executive</td>
        <td><span class="badge amber">Restricted</span></td>
        <td>Release after approval</td>
        <td>Protected output</td>
      </tr>
    `;
    byId("exec-evidence-badge").textContent = "story preview";
    byId("exec-evidence-title").textContent = "Governed evidence packet";
    byId("exec-evidence-summary").textContent = "Publicly visible workflow shape only. Authenticate to load the real citation packet for a specific finding.";
    byId("exec-evidence-source").textContent = "Protected source";
    byId("exec-evidence-locator").textContent = "Hidden until auth";
    byId("exec-evidence-confidence").textContent = "Reviewer-controlled";
    byId("exec-evidence-resolution").textContent = "Human gate required";
    byId("exec-evidence-preview").textContent = "Evidence preview remains intentionally blank on the anonymous surface. Use an operator or reviewer session to reveal cited excerpts and challenge state.";
    byId("exec-report-badge").textContent = "protected";
    byId("exec-report-list").innerHTML = `
      <button class="report-button" type="button" disabled>
        <strong>Board pack snapshot</strong>
        <span>Visible as workflow posture only on the public route.</span>
      </button>
      <button class="report-button" type="button" disabled>
        <strong>Evidence report packet</strong>
        <span>Unlocks only after reviewer/operator authentication.</span>
      </button>
    `;
    byId("exec-report-preview").textContent = "Report previews stay protected until an authenticated session confirms the latest governed run and artifact boundary.";
    els.memoBody.textContent = "The public demo now reads as a coherent executive story: source pack in, governed cases out, evidence reviewed, report released under human control.";
    els.memoList.innerHTML = [
      "<div>Overview: public shell shows the real product posture without exposing live finance data.</div>",
      "<div>Cases: anonymous viewers can understand the case-review step before seeing any real queue items.</div>",
      "<div>Evidence and reports: both remain clearly present in the workflow and clearly protected.</div>",
    ].join("");
    renderPlanHealth({
      badge: "story mode",
      status: "Awaiting governed run",
      note: "This first plan-health layer stays intentionally honest: no broad strategic health score appears until real finance cases and evidence exist.",
      boundary: "Finance-derived signal only — StrategyOS is summarizing current case, evidence, and report posture, not a full enterprise strategy compiler.",
      value: "--",
      valueNote: "Recoverable value appears only after a governed finance run exists.",
      cases: "Workflow shape",
      casesNote: "The anonymous surface shows how cases progress before any live queue is revealed.",
      evidence: "Boundary intact",
      evidenceNote: "Evidence and release remain visible as workflow stages, not as fabricated KPI output.",
    });
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
    const findings = findingsPayload();
    if (findings.length) {
      els.caseBadge.textContent = `${findings.length} governed cases`;
      els.caseBody.innerHTML = findings.map((finding, index) => {
        const title = finding.title || finding.pattern_label || finding.finding_id || `Finding ${index + 1}`;
        const risk = finding.challenged
          ? "Challenge open"
          : finding.confidence || finding.status || "Review";
        return `
          <tr>
            <td>
              <strong>${escapeHtml(title)}</strong>
              <small>${escapeHtml(finding.finding_id || finding.node_id || "latest finding")}</small>
              <button class="case-action" type="button" data-finding-id="${escapeHtml(finding.finding_id || "")}">View evidence</button>
            </td>
            <td>${escapeHtml(finding.owner || "reviewer")}</td>
            <td><span class="badge green">${escapeHtml(formatCount(finding.citation_count ?? citations.resolved ?? "--"))} cites</span></td>
            <td>${escapeHtml(finding.challenged ? "Resolve challenge" : "Review packet")}</td>
            <td>${escapeHtml(finding.recoverable_sar ? formatSarShort(finding.recoverable_sar) : risk)}</td>
          </tr>
        `;
      }).join("");
      els.caseBody.querySelectorAll("[data-finding-id]").forEach((button) => {
        button.addEventListener("click", () => selectFinding(button.getAttribute("data-finding-id")));
      });
      return;
    }

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
    const queueCount = Array.isArray(state.pendingReviews?.items) ? state.pendingReviews.items.length : 0;
    const artifactCount = Object.keys(reportArtifacts()).length;
    const approval = approvalSummary(run);
    const totals = findingsTotals();

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
    byId("exec-overview-status").textContent = missing ? "No governed run yet" : `${formatCount(findings)} findings · ${approval}`;
    byId("exec-overview-note").textContent = missing
      ? "Run one governed analysis, then this view becomes the executive narrative surface."
      : `Latest run ${compactRunId(run)} is ${status}. StrategyOS is emphasizing evidence-backed action before more analysis.`;
    byId("exec-queue-count").textContent = formatCount(queueCount);
    byId("exec-queue-note").textContent = queueCount
      ? `${queueCount} review item${queueCount === 1 ? "" : "s"} are waiting in the governed queue.`
      : "No extra review queue items are currently waiting beyond the latest run context.";
    byId("exec-evidence-status").textContent = citationText;
    byId("exec-evidence-note").textContent = challenged
      ? `${formatCount(challenged)} challenge${Number(challenged) === 1 ? "" : "s"} keep this packet in human hands.`
      : "Citation chain looks intact enough for executive drill-down.";
    byId("exec-report-status").textContent = artifactCount ? `${formatCount(artifactCount)} artifacts` : "No report artifacts";
    byId("exec-report-note").textContent = artifactCount
      ? "Preview what is safe, then use the review app for restricted board-ready files."
      : "The latest run has not yet surfaced report artifacts for executive inspection.";

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
    renderPlanHealth({
      badge: missing ? "no run" : challenged ? "human gate" : approval === "approved" ? "release posture" : "bounded KPI layer",
      status: missing
        ? "Awaiting governed run"
        : challenged
          ? "Needs reviewer closure"
          : approval === "approved"
            ? "Release posture is clear"
            : "Finance plan signal is actionable",
      note: missing
        ? "Run one governed analysis before promoting any plan-health view beyond workflow posture."
        : challenged
          ? `${formatCount(challenged)} challenge${Number(challenged) === 1 ? " is" : "s are"} still open, so plan health remains constrained by evidence closure.`
          : queueCount
            ? `${formatCount(queueCount)} additional review item${queueCount === 1 ? " is" : "s are"} still queued behind the latest packet.`
            : "Current finance evidence is strong enough to frame the next move without inventing broader strategic reasoning.",
      boundary: "Finance-derived signal only — StrategyOS is summarizing current case, evidence, and report posture, not a full enterprise strategy compiler.",
      value: formatSar(recoverable),
      valueNote: missing
        ? "Recoverable value will load from the latest governed analysis."
        : `${formatCount(findings)} finding${Number(findings || 0) === 1 ? "" : "s"} are supporting this value signal in the current finance packet.`,
      cases: missing ? "--" : `${formatCount(totals.ready)} ready · ${formatCount(totals.review)} review`,
      casesNote: missing
        ? "Case readiness appears after the first governed packet lands."
        : `${formatCount(totals.challenged)} challenged · ${formatCount(queueCount)} queued beyond the latest run context.`,
      evidence: missing
        ? "--"
        : citations.count !== null && citations.count !== undefined
          ? `${formatCount(citations.resolved)} / ${formatCount(citations.count)} cited`
          : formatCount(challenged || 0),
      evidenceNote: missing
        ? "Evidence and release posture load with the governed run."
        : artifactCount
          ? `${formatCount(artifactCount)} report artifact${artifactCount === 1 ? " is" : "s are"} visible; approval is ${approval}.`
          : `Approval is ${approval}; report artifacts are not yet surfaced for executive inspection.`,
    });
    renderCases(run, citations, challenged);
    renderReports();
    renderScopeRibbon();
  }

  function setEvidencePreviewFallback(message, badge) {
    byId("exec-evidence-badge").textContent = badge || "awaiting selection";
    byId("exec-evidence-summary").textContent = message;
    byId("exec-evidence-preview").textContent = message;
  }

  async function selectFinding(findingId) {
    const finding = findingsPayload().find((item) => item.finding_id === findingId);
    state.selectedFindingId = findingId || null;
    if (!finding || !state.latestRun?.run_id) {
      byId("exec-evidence-title").textContent = "No finding selected";
      setEvidencePreviewFallback("Choose a case from the matrix to load cited evidence and validation posture.");
      return;
    }
    byId("exec-evidence-badge").textContent = finding.challenged ? "challenge open" : "evidence ready";
    byId("exec-evidence-title").textContent = finding.title || finding.pattern_label || finding.finding_id;
    byId("exec-evidence-summary").textContent = `${finding.finding_id} · ${finding.owner || "reviewer"} · ${finding.recoverable_sar ? formatSar(finding.recoverable_sar) : "value pending"}`;
    byId("exec-evidence-source").textContent = "Loading…";
    byId("exec-evidence-locator").textContent = "Loading…";
    byId("exec-evidence-confidence").textContent = finding.confidence || "review";
    byId("exec-evidence-resolution").textContent = finding.challenged ? "Challenge open" : (finding.status || "Ready for review");
    byId("exec-evidence-preview").textContent = "Loading evidence preview…";
    try {
      const payload = await requestJson(`${isAuthenticated() ? "/data/evidence-preview" : "/public/data/evidence-preview"}?run_id=${encodeURIComponent(state.latestRun.run_id)}&finding_id=${encodeURIComponent(finding.finding_id)}`);
      if (!isAuthenticated()) state.publicEvidencePreview = payload;
      byId("exec-evidence-source").textContent = payload.source_path || "Stored evidence";
      byId("exec-evidence-locator").textContent = payload.locator || "No locator";
      byId("exec-evidence-confidence").textContent = payload.confidence || finding.confidence || "review";
      byId("exec-evidence-resolution").textContent = payload.resolved ? "Resolved citation" : "Stored citation";
      const preview = payload.excerpt || JSON.stringify(payload.resolved_payload || {}, null, 2) || "No preview available.";
      byId("exec-evidence-preview").textContent = preview;
    } catch (error) {
      setEvidencePreviewFallback(`Evidence preview unavailable: ${error.message}`, "preview blocked");
      byId("exec-evidence-source").textContent = finding.owner || "--";
      byId("exec-evidence-locator").textContent = "--";
    }
  }

  function renderReports() {
    const artifacts = reportArtifacts();
    const keys = Object.keys(artifacts);
    byId("exec-report-badge").textContent = keys.length ? `${keys.length} available` : "no artifacts";
    if (!keys.length) {
      byId("exec-report-list").innerHTML = "";
      byId("exec-report-preview").textContent = "No latest-run report artifacts are available yet.";
      return;
    }
    byId("exec-report-list").innerHTML = keys.map((key) => `
      <button class="report-button" type="button" data-artifact-key="${escapeHtml(key)}">
        <strong>${escapeHtml(reportLabel(key))}</strong>
        <span>${escapeHtml(String(artifacts[key] || "").split("/").slice(-1)[0] || "Stored artifact")}</span>
      </button>
    `).join("");
    byId("exec-report-list").querySelectorAll("[data-artifact-key]").forEach((button) => {
      button.addEventListener("click", () => loadReportPreview(button.getAttribute("data-artifact-key")));
    });
  }

  async function loadReportPreview(artifactKey) {
    if (!artifactKey || !state.latestRun?.run_id) return;
    byId("exec-report-preview").textContent = "Loading report preview…";
    try {
      const payload = isAuthenticated()
        ? await requestJson(`/reviewer/runs/${encodeURIComponent(state.latestRun.run_id)}/artifacts/${encodeURIComponent(artifactKey)}`)
        : await requestJson(`/public/runs/latest/report-preview?artifact_key=${encodeURIComponent(artifactKey)}`);
      if (!isAuthenticated()) state.publicReportPreview = payload;
      const preview = payload.preview_text
        || (payload.preview_json ? JSON.stringify(payload.preview_json, null, 2) : "Preview unavailable for this artifact.");
      byId("exec-report-preview").textContent = preview;
    } catch (error) {
      byId("exec-report-preview").textContent = `Preview blocked: ${error.message}. Use the review app for restricted artifacts.`;
    }
  }

  async function refreshLiveData() {
    state.loading = true;
    els.refresh.disabled = true;
    els.refresh.textContent = "Refreshing...";
    try {
      state.session = await guarded("Session", requestJson("/ui/session"), { authenticated: false });
      if (!isAuthenticated()) {
        const [publicRun, publicAuditSummary, publicFindings, publicReportPreview] = await Promise.all([
          guarded("Public latest run", requestJson("/public/runs/latest"), { status: "missing" }),
          guarded("Public audit summary", requestJson("/public/runs/latest/audit-summary"), { status: "missing", challenged_finding_ids: [] }),
          guarded("Public latest findings", requestJson("/public/runs/latest/findings"), { status: "missing", findings: [] }),
          guarded("Public report preview", requestJson("/public/runs/latest/report-preview"), { status: "missing" }),
        ]);
        state.latestRun = publicRun;
        state.auditSummary = publicAuditSummary;
        state.knowledgeGraph = null;
        state.latestFindings = publicFindings;
        state.pendingReviews = { items: [] };
        state.runDetail = null;
        state.publicReportPreview = publicReportPreview;
        const preferredFinding = Array.isArray(publicFindings?.findings) ? publicFindings.findings[0]?.finding_id : null;
        state.publicEvidencePreview = preferredFinding
          ? await guarded(
            "Public evidence preview",
            requestJson(`/public/data/evidence-preview?run_id=${encodeURIComponent(publicRun?.run_id || "")}&finding_id=${encodeURIComponent(preferredFinding)}`),
            null,
          )
          : null;
        renderLocked();
        return;
      }
      state.publicEvidencePreview = null;
      state.publicReportPreview = null;
      const [latestRun, auditSummary, knowledgeGraph, latestFindings, pendingReviews] = await Promise.all([
        guarded("Latest run", requestJson("/runs/latest"), { status: "missing" }),
        guarded("Audit summary", requestJson("/runs/latest/audit-summary"), { status: "missing" }),
        guarded("Knowledge graph", requestJson("/runs/latest/knowledge-graph"), { status: "missing", nodes: [], edges: [], meta: {} }),
        guarded("Latest findings", requestJson("/runs/latest/findings"), { status: "missing", findings: [] }),
        guarded("Pending reviews", requestJson("/reviewer/pending-reviews"), { items: [] }),
      ]);
      state.latestRun = latestRun;
      state.auditSummary = auditSummary;
      state.knowledgeGraph = knowledgeGraph;
      state.latestFindings = latestFindings;
      state.pendingReviews = pendingReviews;
      state.runDetail = latestRun?.run_id
        ? await guarded("Run detail", requestJson(`/reviewer/runs/${encodeURIComponent(latestRun.run_id)}`), null)
        : null;
      renderLive();
      const preferredFinding = findingsPayload()[0]?.finding_id;
      if (preferredFinding) {
        selectFinding(preferredFinding);
      }
      const preferredArtifact = ["working_capital", "qa", "summary", "knowledge_graph"].find((key) => reportArtifacts()[key]) || Object.keys(reportArtifacts())[0];
      if (preferredArtifact) {
        loadReportPreview(preferredArtifact);
      }
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

  els.portfolioSwitcher?.addEventListener("change", (event) => {
    state.selectedPortfolio = event.target.value || "all";
    renderScopeRibbon();
  });

  els.evidenceCommand.addEventListener("click", () => {
    els.commandInput.value = "What is the total recoverable?";
    submitCommand(els.commandInput.value);
  });

  byId("exec-open-report-app").addEventListener("click", () => {
    window.location.href = "/app";
  });

  els.commandForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitCommand(els.commandInput.value);
  });

  refreshLiveData();
})();
