(function () {
  "use strict";

  const TOKEN_KEY = "strategyos.ui.token";
  const DESIGN = window.STRATEGYOS_EXECUTIVE_DESIGN || {};
  const bootstrap = JSON.parse(document.getElementById("strategyos-executive-bootstrap").textContent);
  const byId = (id) => document.getElementById(id);
  const query = new URLSearchParams(window.location.search);

  const els = {
    railStatus: byId("exec-rail-status"),
    runTitle: byId("exec-run-title"),
    runMeta: byId("exec-run-meta"),
    personaButton: byId("exec-persona-button"),
    personaButtonRole: byId("exec-persona-button-role"),
    topbarBoardState: byId("exec-topbar-board-state"),
    personaMenu: byId("exec-persona-menu"),
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
    planHealthSourceNote: byId("exec-plan-health-source-note"),
    planKpiValue: byId("exec-plan-kpi-value"),
    planKpiValueNote: byId("exec-plan-kpi-value-note"),
    planKpiCases: byId("exec-plan-kpi-cases"),
    planKpiCasesNote: byId("exec-plan-kpi-cases-note"),
    planKpiEvidence: byId("exec-plan-kpi-evidence"),
    planKpiEvidenceNote: byId("exec-plan-kpi-evidence-note"),
    domainSignalNote: byId("exec-domain-signal-note"),
    publicationBadge: byId("exec-publication-badge"),
    kpiTreeStatus: byId("exec-kpi-tree-status"),
    kpiTreeNote: byId("exec-kpi-tree-note"),
    domainBranchCount: byId("exec-domain-branch-count"),
    domainBranchNote: byId("exec-domain-branch-note"),
    publicationStatus: byId("exec-publication-status"),
    publicationNote: byId("exec-publication-note"),
    publicationRoute: byId("exec-publication-route"),
    publicationRouteNote: byId("exec-publication-route-note"),
    domainTree: byId("exec-domain-tree"),
    publicationList: byId("exec-publication-list"),
    valueDriverList: byId("exec-value-driver-list"),
    strategyIntentSummary: byId("exec-strategy-intent-summary"),
    intentReasoningList: byId("exec-intent-reasoning-list"),
    boardLifecycleList: byId("exec-board-lifecycle-list"),
    publishFlowList: byId("exec-publish-flow-list"),
    discoveryModuleList: byId("exec-discovery-module-list"),
    scopeNote: byId("exec-scope-note"),
    companySwitcher: byId("exec-company-switcher"),
    portfolioSwitcher: byId("exec-portfolio-switcher"),
    scopeSummary: byId("exec-scope-summary"),
    scopeBreadcrumb: byId("exec-scope-breadcrumb"),
    heroGreeting: byId("exec-hero-greeting"),
    heroHeadline: byId("exec-hero-headline"),
    heroCopy: byId("exec-hero-copy"),
    heroBoundary: byId("exec-hero-boundary"),
    heroScore: byId("exec-hero-score"),
    heroScoreNote: byId("exec-hero-score-note"),
    driverTiles: byId("exec-driver-tiles"),
    driverDetailTitle: byId("exec-driver-detail-title"),
    driverDetailMetric: byId("exec-driver-detail-metric"),
    driverDetailStory: byId("exec-driver-detail-story"),
    driverDetailChips: byId("exec-driver-detail-chips"),
    personaTitle: byId("exec-persona-title"),
    personaNote: byId("exec-persona-note"),
    personaTabs: byId("exec-persona-tabs"),
    lifecycleTitle: byId("exec-lifecycle-title"),
    lifecycleNote: byId("exec-lifecycle-note"),
    lifecycleTabs: byId("exec-lifecycle-tabs"),
    themeTabs: byId("exec-theme-tabs"),
    densityTabs: byId("exec-density-tabs"),
    moversTabs: byId("exec-movers-tabs"),
    driverStack: byId("exec-driver-stack"),
    gravityPromptList: byId("exec-gravity-prompt-list"),
    gravityQuote: byId("exec-gravity-quote"),
    gravityBy: byId("exec-gravity-by"),
    gravityRails: byId("exec-gravity-rails"),
    boardTitle: byId("exec-board-title"),
    boardMeta: byId("exec-board-meta"),
    boardStateBadge: byId("exec-board-state-badge"),
    boardGovernance: byId("exec-board-governance"),
    boardSummary: byId("exec-board-summary"),
    boardLifecycle: byId("exec-board-lifecycle"),
    boardKpis: byId("exec-board-kpis"),
    boardColumnTitle: byId("exec-board-column-title"),
    boardColumnNote: byId("exec-board-column-note"),
    boardPrimaryList: byId("exec-board-primary-list"),
    boardRailTitle: byId("exec-board-rail-title"),
    boardRailNote: byId("exec-board-rail-note"),
    boardSecondaryList: byId("exec-board-secondary-list"),
    boardRailFoot: byId("exec-board-rail-foot"),
    agentsBadge: byId("exec-agents-badge"),
    agentsActivityLine: byId("exec-agents-activity-line"),
    agentsRunningBadge: byId("exec-agents-running-badge"),
    agentsRunningList: byId("exec-agents-running-list"),
    subagentList: byId("exec-subagent-list"),
    agentsNativeList: byId("exec-agents-native-list"),
    agentsMarketList: byId("exec-agents-market-list"),
    drillTrend: byId("exec-drill-trend"),
    drillMovers: byId("exec-drill-movers"),
    drillPrompts: byId("exec-drill-prompts"),
    moversCaption: byId("exec-movers-caption"),
    lowerMainBadge: byId("exec-lower-main-badge"),
    weekBadge: byId("exec-week-badge"),
    developmentsList: byId("exec-developments-list"),
    weekRail: byId("exec-week-rail"),
    pulseGrid: byId("exec-pulse-grid"),
    owedList: byId("exec-owed-list"),
    secondaryGrid: byId("exec-secondary-grid"),
    pulseTitle: byId("exec-pulse-title"),
    pulseNote: byId("exec-pulse-note"),
    owedTitle: byId("exec-owed-title"),
    owedNote: byId("exec-owed-note"),
    gravityInput: byId("exec-gravity-input"),
    gravitySubmit: byId("exec-gravity-submit"),
    boardStateDetail: byId("exec-board-state-detail"),
    agentsSearchNote: byId("exec-agents-search-note"),
    agentsSearchInput: byId("exec-agents-search"),
    agentsFilterRow: byId("exec-agents-filter-row"),
    agentsBrowseButton: byId("exec-agents-browse-button"),
    agentsSovereignNote: byId("exec-agents-sovereign-note"),
    threadList: byId("exec-thread-list"),
    assistantNetwork: byId("exec-assistant-network"),
    copilotTitle: byId("exec-copilot-title"),
    copilotSubtitle: byId("exec-copilot-subtitle"),
    footerTime: byId("exec-footer-time"),
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
    selectedCompany: query.get("company") || "current",
    selectedPortfolio: query.get("portfolio") || "all",
    publicEvidencePreview: null,
    publicReportPreview: null,
    workspaceContract: null,
    loading: false,
    executivePersona: query.get("persona") || "ceo",
    lifecycleMode: query.get("board") || "pre",
    selectedDriverKey: query.get("driver") || "board_packet",
    themeMode: query.get("theme") || "paper",
    densityMode: query.get("density") || "comfortable",
    moversMode: query.get("movers") || "cards",
    selectedThreadKey: query.get("thread") || "briefing",
    personaMenuOpen: false,
    selectedWeekEventKey: query.get("week") || "board_prep",
    openAgentKey: query.get("agent") || "reviewer_gate_relay",
    discoveryQuery: query.get("discover") || "",
    discoveryFilter: query.get("discover_type") || "all",
    agentLogOpenKey: null,
    approvedAgentKeys: {},
    deployedAgentKeys: {},
  };

  const EXECUTIVE_PERSONAS = [
    { key: "ceo", label: "Group CEO", detail: "Khalid · value, release, board brief", assistant: "Hermes" },
    { key: "cfo", label: "Group CFO", detail: "Sara · margin, hedge, cash", assistant: "Atlas" },
    { key: "gm", label: "e-Pharmacy GM", detail: "Lina · growth, service, capacity", assistant: "Iris" },
    { key: "bucfo", label: "Tamween BU CFO", detail: "Yusuf · leakage, controls, exposure", assistant: "Argus" },
    { key: "logistics", label: "Logistics", detail: "Hassan · cold chain, service, cost", assistant: "Vega" },
    { key: "board", label: "Board room", detail: "Approved pack and frozen board posture", assistant: "Minerva" },
  ];

  const DISPLAY_THEMES = [
    { key: "midnight", label: "Midnight", detail: "dark diagnostic sheet" },
    { key: "paper", label: "Paper", detail: "board-pack light mode" },
  ];

  const DISPLAY_DENSITIES = [
    { key: "comfortable", label: "Comfortable", detail: "gallery spacing" },
    { key: "compact", label: "Compact", detail: "board-room density" },
  ];

  const MOVERS_VIEWS = [
    { key: "cards", label: "Cards", detail: "design tile view" },
    { key: "ledger", label: "Ledger", detail: "up / down list" },
    { key: "bar", label: "Bar", detail: "tornado bars" },
  ];

  const BOARD_LIFECYCLES = [
    { key: "pre", label: "Pre-board", detail: "Prepare" },
    { key: "live", label: "Live", detail: "In session" },
    { key: "closed", label: "Closed", detail: "Memory" },
  ];

  const PERSONA_ALIASES = {
    pharma: "gm",
    distribution: "bucfo",
    boardroom: "board",
  };

  function contractExecutivePersonas() {
    const personas = Array.isArray(state.workspaceContract?.executive_modes?.personas)
      ? state.workspaceContract.executive_modes.personas
      : [];
    if (!personas.length) return EXECUTIVE_PERSONAS;
    return personas.map((item) => ({
      key: item.persona_id,
      label: item.label,
      detail: item.detail,
      assistant: item.assistant,
    }));
  }

  function contractBoardLifecycles() {
    const states = Array.isArray(state.workspaceContract?.executive_modes?.board_states)
      ? state.workspaceContract.executive_modes.board_states
      : [];
    if (!states.length) return BOARD_LIFECYCLES;
    return states.map((item) => ({
      key: item.state_id,
      label: item.label,
      detail: item.detail,
      summary: item.summary,
      route: item.route,
      active: Boolean(item.active),
    }));
  }

  function executiveViewQueryParams() {
    const params = new URLSearchParams();
    const persona = PERSONA_ALIASES[state.executivePersona] || state.executivePersona;
    if (persona) params.set("persona", persona);
    if (state.lifecycleMode) params.set("board", state.lifecycleMode);
    if (state.selectedDriverKey) params.set("driver", state.selectedDriverKey);
    if (state.selectedCompany) params.set("company", state.selectedCompany);
    if (state.selectedPortfolio) params.set("portfolio", state.selectedPortfolio);
    if (state.selectedWeekEventKey) params.set("week", state.selectedWeekEventKey);
    if (state.openAgentKey) params.set("agent", state.openAgentKey);
    if (state.discoveryQuery) params.set("discover", state.discoveryQuery);
    if (state.discoveryFilter && state.discoveryFilter !== "all") params.set("discover_type", state.discoveryFilter);
    if (state.themeMode) params.set("theme", state.themeMode);
    if (state.densityMode) params.set("density", state.densityMode);
    if (state.moversMode) params.set("movers", state.moversMode);
    if (state.selectedThreadKey) params.set("thread", state.selectedThreadKey);
    return params;
  }

  function viewStateRoute(path) {
    const queryString = executiveViewQueryParams().toString();
    return queryString ? `${path}?${queryString}` : path;
  }

  function syncExecutiveRouteState() {
    const nextUrl = viewStateRoute(window.location.pathname || "/executive");
    window.history.replaceState({}, "", nextUrl);
  }

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

  function humanizeToken(token) {
    if (!token) return "--";
    const str = String(token);
    const map = {
      published: "Published", draft: "Draft", pending: "Pending", approved: "Approved",
      rejected: "Rejected", blocked: "Blocked", needs_closure: "Needs closure",
      needs_reviewer_closure: "Needs closure", active: "Active", inactive: "Inactive",
      waiting: "Waiting", running: "Running", completed: "Completed", closed: "Closed",
      pre: "Pre-board", live: "Live", open: "Open", frozen: "Frozen", gated: "Gated",
      ready: "Ready", clear: "Clear", protected: "Protected", governed: "Governed",
      healthy: "Healthy", degraded: "Degraded", identity_provider: "IdP",
      langgraph: "LangGraph", hetzner_qa: "Hetzner QA", strategyos_live: "StrategyOS Live",
      "strategyos-live": "StrategyOS Live", finance_diagnostics: "Finance diagnostics",
      "finance-diagnostics": "Finance diagnostics", release_readiness: "Release readiness",
      "release-readiness": "Release readiness", evidence_governance: "Evidence governance",
      "evidence-governance": "Evidence governance", runtime_governance: "Runtime governance",
      "runtime-governance": "Runtime governance",
    };
    if (map[str]) return map[str];
    return str.replace(/_/g, " ").replace(/-/g, " ").split(" ").map(function(w) {
      return w.charAt(0).toUpperCase() + w.slice(1);
    }).join(" ");
  }

  function numericOrNull(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function sumFindingCitations(rows) {
    const findings = Array.isArray(rows) ? rows : findingsPayload();
    return findings.reduce((sum, item) => sum + (Number(item?.citation_count || 0) || 0), 0);
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

  function normalizedCitationSummary(run, rows) {
    const raw = citationSummary(run);
    const findingLinked = sumFindingCitations(rows);
    const rawCount = numericOrNull(raw.count);
    const rawResolved = numericOrNull(raw.resolved);
    const candidates = [rawCount, rawResolved, findingLinked].filter((value) => value !== null);
    const total = candidates.length ? Math.max(...candidates) : null;
    const resolved = rawResolved !== null ? rawResolved : findingLinked > 0 ? findingLinked : null;
    const mismatch = rawCount !== null && findingLinked > 0 && rawCount !== findingLinked;
    let detail = "Citation posture will reconcile after a governed run surfaces evidence and audit detail.";
    if (total !== null && mismatch) {
      detail = `Audit summary shows ${formatCount(rawResolved ?? resolved ?? 0)} resolved of ${formatCount(rawCount)} surfaced citations; current finding rows expose ${formatCount(findingLinked)} linked cites.`;
    } else if (total !== null) {
      detail = `Executive KPI cards and plan health are using the same governed citation posture: ${formatCount(resolved ?? 0)} / ${formatCount(total)}.`;
    }
    return { count: total, resolved, findingLinked, mismatch, detail };
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

  function publicationContract() {
    return state.workspaceContract?.reports?.publication || state.publicReportPreview?.publication || {};
  }

  function publicationActionLabels(publication) {
    const mapping = {
      view_board_safe_preview: "Board-safe preview",
      view_governed_report_status: "Governed report status",
      view_report_preview: "Report preview",
      open_report_artifact: "Restricted artifact open",
      approve_or_reject_release: "Approve or reject release",
      resume_publication: "Resume publication",
      inspect_publication_boundary: "Inspect publication boundary",
      inspect_artifact_posture: "Inspect artifact posture",
      inspect_runtime_release_state: "Inspect runtime release state",
    };
    return (Array.isArray(publication?.allowed_actions) ? publication.allowed_actions : []).map((action) => mapping[action] || action.replaceAll("_", " "));
  }

  function publicationStatusLabel(status) {
    return {
      published: "Published",
      approved_for_release: "Approved for release",
      awaiting_review: "Awaiting review",
      blocked: "Blocked",
      draft: "Draft",
    }[String(status || "draft").toLowerCase()] || String(status || "draft").replaceAll("_", " ");
  }

  const NEXT_ACTION_LABELS = {
    run_first_governed_packet: "Run the first governed packet",
    close_challenged_cases: "Close challenged cases",
    revise_evidence_and_rerun: "Revise evidence and rerun",
    prepare_board_pack: "Prepare board pack",
    capture_reviewer_decision: "Capture reviewer decision",
    expand_report_surface: "Expand report surface",
    protect_value_signal: "Protect value signal",
    continue_workflow: "Continue workflow",
    operator_resume: "Operator resume",
    review_decision: "Review decision",
    claim_review: "Claim review",
    inspect_published_outputs: "Inspect published outputs",
  };

  function humanizeNextAction(value) {
    const key = String(value || "").trim().toLowerCase();
    if (!key) return "Awaiting next action";
    return NEXT_ACTION_LABELS[key] || key.replaceAll("_", " ");
  }

  function slugifyToken(value) {
    return String(value || "item")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "item";
  }

  function currentTenantContext() {
    return state.workspaceContract?.tenant_context || state.session?.tenant_context || state.runDetail?.summary_json?.tenant_context || {};
  }

  function contractCompanyOptions() {
    const options = state.workspaceContract?.company_switcher?.options;
    return Array.isArray(options) && options.length ? options : [];
  }

  function contractPortfolioOptions() {
    const options = Array.isArray(state.workspaceContract?.portfolio_switcher?.options)
      ? state.workspaceContract.portfolio_switcher.options.slice()
      : [];
    if (!options.find((item) => item?.option_id === "all")) {
      options.unshift({ option_id: "all", label: "All governed portfolios", route: "/executive" });
    }
    return options;
  }

  function badgeTone(tone) {
    if (tone === "ok") return "green";
    if (tone === "warn") return "amber";
    return "blue";
  }

  function filteredDomainNodes() {
    const nodes = Array.isArray(state.workspaceContract?.domain_tree?.nodes)
      ? state.workspaceContract.domain_tree.nodes
      : [];
    if (state.selectedPortfolio === "all") return nodes;
    return nodes.filter((node) => node?.portfolio_id === state.selectedPortfolio);
  }

  function strategyPortfolioViews() {
    return Array.isArray(strategySubstrate()?.portfolio_views)
      ? strategySubstrate().portfolio_views
      : [];
  }

  function selectedStrategyView() {
    if (state.selectedPortfolio === "all") return null;
    return strategyPortfolioViews().find((item) => item?.portfolio_id === state.selectedPortfolio) || null;
  }

  function strategySubstrate() {
    return state.workspaceContract?.strategy_substrate || {};
  }

  function strategyKpiNodes() {
    const nodes = Array.isArray(strategySubstrate()?.kpi_tree?.nodes)
      ? strategySubstrate().kpi_tree.nodes
      : [];
    if (state.selectedPortfolio === "all") return nodes;
    return nodes.filter((node) => node?.portfolio_id === state.selectedPortfolio);
  }

  function strategyValueDrivers() {
    const drivers = Array.isArray(strategySubstrate()?.value_drivers)
      ? strategySubstrate().value_drivers
      : [];
    if (state.selectedPortfolio === "all") return drivers;
    return drivers.filter((driver) => driver?.portfolio_id === state.selectedPortfolio);
  }

  function strategyReasoningItems() {
    const items = Array.isArray(strategySubstrate()?.reasoning)
      ? strategySubstrate().reasoning
      : [];
    if (state.selectedPortfolio === "all") return items;
    return items.filter((item) => item?.portfolio_id === state.selectedPortfolio);
  }

  function currentExecutivePersona() {
    const normalizedKey = PERSONA_ALIASES[state.executivePersona] || state.executivePersona;
    if (normalizedKey !== state.executivePersona) state.executivePersona = normalizedKey;
    const personas = contractExecutivePersonas();
    return personas.find((item) => item.key === normalizedKey) || personas[0] || EXECUTIVE_PERSONAS[0];
  }

  function personaBlueprint() {
    const persona = currentExecutivePersona();
    return (DESIGN.personas && DESIGN.personas[persona.key]) || (DESIGN.personas && DESIGN.personas.ceo) || null;
  }

  function boardBlueprint() {
    return DESIGN.board || null;
  }

  function currentThemeMode() {
    return DISPLAY_THEMES.find((item) => item.key === state.themeMode) || DISPLAY_THEMES[0];
  }

  function currentDensityMode() {
    return DISPLAY_DENSITIES.find((item) => item.key === state.densityMode) || DISPLAY_DENSITIES[0];
  }

  function currentMoversMode() {
    return MOVERS_VIEWS.find((item) => item.key === state.moversMode) || MOVERS_VIEWS[0];
  }

  function currentPersonaModel() {
    const blueprint = personaBlueprint();
    const persona = currentExecutivePersona();
    const publication = publicationContract();
    const findings = findingsPayload();
    const challenged = challengedSummary(state.latestRun || {}) || findings.filter((item) => item?.challenged).length;
    const shared = {
      ceo: {
        greeting: `Good morning, ${blueprint?.health ? "Khalid" : "Khalid"}`,
        title: "Group CEO diagnostics",
        designScore: blueprint?.health?.score || 78,
        assistant: blueprint?.assistant || "Hermes",
        assistantRole: blueprint?.assistantRole || "chief of staff",
        brief: blueprint?.brief || "Revenue holds ahead of plan, EBITDA still needs hedge closure, and the board call remains about confidence in the packet rather than liquidity.",
        quote: blueprint?.quote || "Revenue is carrying the story at 102, EBITDA is still just shy at 99, and cash gives the room confidence at 123 — the call is hedge closure, not liquidity.",
        by: blueprint?.by || "Hermes · Group CEO chief of staff",
        threads: blueprint?.threads || [
          { key: "briefing", title: "Board on Thursday", preview: "Am I on track for the board on Thursday?" },
          { key: "hedge", title: "Hedge downside", preview: "Show the hedge downside before the room." },
          { key: "recognition", title: "Recognition this week", preview: "Who deserves recognition this week?" },
        ],
        prompts: blueprint?.prompts || ["Am I on track for the board on Thursday?", "What is the single biggest risk to plan?", "Who deserves recognition this week?"],
      },
      cfo: {
        greeting: "Good morning, Sara",
        title: "Group CFO diagnostics",
        designScore: blueprint?.health?.score || 76,
        assistant: blueprint?.assistant || "Atlas",
        assistantRole: blueprint?.assistantRole || "finance chief of staff",
        brief: blueprint?.brief || "The packet is now mostly a margin and hedge conversation: value is present, but EBITDA and FX discipline still decide confidence in the deck.",
        quote: blueprint?.quote || "Cash stays above the floor and the hedge is the real board question — not whether the business can fund the move.",
        by: blueprint?.by || "Atlas · CFO assistant",
        threads: blueprint?.threads || [
          { key: "briefing", title: "Margin pressure", preview: "What is the single biggest drag on EBITDA?" },
          { key: "hedge", title: "FX hedge", preview: "Show the hedge downside and action window." },
          { key: "recognition", title: "Cash posture", preview: "Can the JV be funded from cash?" },
        ],
        prompts: blueprint?.prompts || ["What is the single biggest drag on EBITDA?", "Show the hedge downside.", "Can the JV be funded from cash?"],
      },
      gm: {
        greeting: "Good morning, Iris",
        title: "e-Pharmacy GM diagnostics",
        designScore: blueprint?.health?.score || 81,
        assistant: blueprint?.assistant || "Iris",
        assistantRole: blueprint?.assistantRole || "growth chief of staff",
        brief: blueprint?.brief || "Demand is still carrying momentum; the job is to protect service and conversion without leaking the margin signal back out of the packet.",
        quote: blueprint?.quote || "The growth line is healthy, but the board will still ask whether fulfilment and price discipline can protect it.",
        by: blueprint?.by || "Iris · e-Pharmacy assistant",
        threads: blueprint?.threads || [],
        prompts: blueprint?.prompts || [],
      },
      bucfo: {
        greeting: "Good morning, Argus",
        title: "Tamween BU CFO diagnostics",
        designScore: blueprint?.health?.score || 72,
        assistant: blueprint?.assistant || "Argus",
        assistantRole: blueprint?.assistantRole || "distribution chief of staff",
        brief: blueprint?.brief || "Distribution remains the loudest control signal in the packet: leakage and proof discipline matter more than narrative flourish.",
        quote: blueprint?.quote || "The room can tolerate noise in the story, but not ambiguity in leakage or proof.",
        by: blueprint?.by || "Argus · Tamween assistant",
        threads: blueprint?.threads || [],
        prompts: blueprint?.prompts || [],
      },
      logistics: {
        greeting: "Good morning, Vega",
        title: "Logistics resilience diagnostics",
        designScore: blueprint?.health?.score || 80,
        assistant: blueprint?.assistant || "Vega",
        assistantRole: blueprint?.assistantRole || "logistics chief of staff",
        brief: blueprint?.brief || "Cold-chain and service reliability are still the quiet strength in the packet; the concern is keeping cost and continuity aligned as the board asks for confidence.",
        quote: blueprint?.quote || "Cold-chain credibility lets the board focus on strategy instead of firefighting, provided cost stays disciplined.",
        by: blueprint?.by || "Vega · logistics assistant",
        threads: blueprint?.threads || [],
        prompts: blueprint?.prompts || [],
      },
      board: {
        greeting: "Good morning, board room",
        title: "Board room framing",
        designScore: blueprint?.health?.score || 78,
        assistant: boardBlueprint()?.assistant || "Minerva",
        assistantRole: "board-safe assistant",
        brief: "Only the CEO-approved packet belongs here: the board can press on margin, hedge, and cash, but the answers must stay inside approved material.",
        quote: publication.status === "published"
          ? "The packet is now frozen into memory — board follow-up stays bounded to approved outputs."
          : "The room sees only what the CEO has approved, plus the KPIs the board expects to interrogate.",
        by: `${boardBlueprint()?.assistant || "Minerva"} · board-safe assistant`,
        threads: [
          { key: "briefing", title: "Room opener", preview: "How should we open the board conversation?" },
          { key: "hedge", title: "Approved packet only", preview: "What can I answer from the approved deck only?" },
          { key: "recognition", title: "Post-meeting memory", preview: "What should be frozen into the board snapshot?" },
        ],
        prompts: ["How should we open the board conversation?", "What can I answer from the approved deck only?", "What should be frozen into the board snapshot?"],
      },
    };
    return shared[persona.key] || shared.ceo;
  }

  function executiveDriverBaseline() {
    const persona = currentExecutivePersona();
    const blueprint = personaBlueprint();
    if (Array.isArray(blueprint?.drivers) && blueprint.drivers.length) {
      return blueprint.drivers.map((driver) => ({
        key: driver.key,
        title: driver.label,
        percent: driver.pct,
        metric: `${driver.pct}% of plan`,
        sub: `${driver.value} · ${driver.sub}`,
        story: driver.story,
        chips: driver.chips || [],
        vsPlan: driver.vsPlan,
        trendLabel: driver.trendLabel,
        unit: driver.unit,
        movers: driver.movers || { lifting: [], dragging: [] },
      }));
    }
    const publication = publicationContract();
    const approvedMetric = publication.status === "published" ? "packet published" : publication.status === "approved_for_release" ? "packet ready" : "packet preparing";
    const baselines = {
      ceo: [
        { key: "revenue", title: "Revenue", percent: 102, metric: "102% of plan", sub: "topline ahead", chips: ["Topline is ahead", scopeLabel(), approvedMetric] },
        { key: "ebitda", title: "EBITDA", percent: 99, metric: "99% of plan", sub: "FX + API drag", chips: ["Hedge focus", "margin watch", "board question"] },
        { key: "readiness", title: "Board readiness", percent: 101, metric: "101 posture", sub: "room confidence", chips: ["deck coherence", humanizeToken(publication.board_pack?.status || "pending"), "approved narrative"] },
        { key: "cash", title: "Cash", percent: 123, metric: "123% of floor", sub: "liquidity strong", chips: ["JV fundable", "cash cushion", "downside protected"] },
      ],
      cfo: [
        { key: "margin", title: "Margin", percent: 99, metric: "99% of plan", sub: "EBITDA under watch", chips: ["FX drag", "API cost", "pricing discipline"] },
        { key: "cash", title: "Cash floor", percent: 123, metric: "123% of floor", sub: "liquidity strong", chips: ["working capital", "JV funded", "board confidence"] },
        { key: "release", title: "Packet release", percent: 101, metric: "101 posture", sub: "board deck coherence", chips: [approvedMetric, humanizeToken(publication.board_pack?.status || "pending"), "safe release"] },
        { key: "revenue", title: "Revenue", percent: 102, metric: "102% of plan", sub: "topline holds", chips: [scopeLabel(), "demand intact", "read-through to EBITDA"] },
      ],
      gm: [
        { key: "growth", title: "Growth", percent: 112, metric: "112 demand", sub: "digital momentum", chips: ["orders rising", "conversion watch", scopeLabel()] },
        { key: "revenue", title: "Revenue", percent: 102, metric: "102% of plan", sub: "share gain visible", chips: ["basket growth", "channel mix", "quality demand"] },
        { key: "readiness", title: "Board readiness", percent: 101, metric: "101 posture", sub: "growth story clear", chips: [approvedMetric, "evidence-linked", "board-safe"] },
        { key: "cash", title: "Cash", percent: 123, metric: "123% of floor", sub: "fuel for expansion", chips: ["funded growth", "no liquidity panic", "controlled risk"] },
      ],
      bucfo: [
        { key: "controls", title: "Controls", percent: 96, metric: "96 closure", sub: "leakage still active", chips: ["Tamween", "proof discipline", "needs closure"] },
        { key: "revenue", title: "Revenue", percent: 101, metric: "101 posture", sub: "flat but protected", chips: [scopeLabel(), "stabilise first", "board-safe"] },
        { key: "readiness", title: "Board readiness", percent: 98, metric: "98 posture", sub: "board will press", chips: [approvedMetric, "control narrative", "supplementary questions"] },
        { key: "cash", title: "Cash", percent: 123, metric: "123% of floor", sub: "buffer remains", chips: ["liquidity okay", "controls first", "board calm"] },
      ],
      logistics: [
        { key: "service", title: "Service", percent: 101, metric: "101 continuity", sub: "service resilient", chips: ["cold-chain", "continuity", "board confidence"] },
        { key: "cold_chain", title: "Cold-chain", percent: 99, metric: "99.4% integrity", sub: "record reliability", chips: ["record week", "quality preserved", "supply watch"] },
        { key: "readiness", title: "Board readiness", percent: 101, metric: "101 posture", sub: "operations story clear", chips: [approvedMetric, "service proof", "safe narrative"] },
        { key: "cash", title: "Cash", percent: 123, metric: "123% of floor", sub: "cost still funded", chips: ["fuel secure", "resilience funded", "no liquidity strain"] },
      ],
      board: [
        { key: "revenue", title: "Revenue", percent: 102, metric: "102% of plan", sub: "approved topline", chips: ["board KPI", "CEO-approved", approvedMetric] },
        { key: "ebitda", title: "EBITDA", percent: 99, metric: "99% of plan", sub: "watch the gap", chips: ["board question", "hedge focus", "approved answer"] },
        { key: "readiness", title: "Board pack", percent: 101, metric: "101 posture", sub: "room-ready", chips: [humanizeToken(publication.board_pack?.status || "pending"), "CEO-approved material", "supplementary rail"] },
        { key: "cash", title: "Cash", percent: 123, metric: "123% of floor", sub: "liquidity strong", chips: ["board confidence", "frozen memory", "no raw ops data"] },
      ],
    };
    return baselines[persona.key] || baselines.ceo;
  }

  function applyDisplayModes() {
    document.body.setAttribute("data-exec-theme", currentThemeMode().key);
    document.body.setAttribute("data-exec-density", currentDensityMode().key);
  }

  function setCommandPrompt(text) {
    if (els.commandInput) els.commandInput.value = text;
    els.commandOutput.textContent = isAuthenticated()
      ? "Prompt ready. Press Run to ask the deterministic command layer."
      : "Prompt seeded. Connect a session before running commands.";
  }

  function derivedLifecycleMode() {
    const publication = publicationContract();
    const boardPackStatus = String(publication.board_pack?.status || "").toLowerCase();
    const approval = String(approvalSummary(state.latestRun || {})).toLowerCase();
    if (["published", "released", "distributed", "closed"].includes(boardPackStatus) || publication.status === "published") return "closed";
    if (approval === "approved" || publication.status === "approved_for_release") return "live";
    return "pre";
  }

  function currentLifecycleMode() {
    const lifecycles = contractBoardLifecycles();
    if (!lifecycles.find((item) => item.key === state.lifecycleMode)) {
      state.lifecycleMode = derivedLifecycleMode();
    }
    return lifecycles.find((item) => item.key === state.lifecycleMode) || lifecycles[0] || BOARD_LIFECYCLES[0];
  }

  function scopeLabel() {
    return currentTenantContext().tenant_name
      || contractCompanyOptions().find((item) => item.option_id === state.selectedCompany)?.label
      || "current governed portfolio";
  }

  function posturePercent(status) {
    const normalized = String(status || "pending").toLowerCase();
    if (["published", "released", "distributed", "closed", "complete", "completed", "approved"].includes(normalized)) return 92;
    if (["approved_for_release", "ready", "review", "awaiting_review"].includes(normalized)) return 74;
    if (["running", "active", "in_progress"].includes(normalized)) return 61;
    if (["blocked", "failed", "challenge", "rejected"].includes(normalized)) return 38;
    return 48;
  }

  function boundedScore(citations, challenged, publication) {
    const ratio = citations.count ? Math.round((Number(citations.resolved || 0) / Number(citations.count || 1)) * 100) : 52;
    const challengePenalty = Math.min(Number(challenged || 0) * 8, 26);
    const release = posturePercent(publication.status || publication.approval_status || approvalSummary(state.latestRun || {}));
    const board = posturePercent(publication.board_pack?.status || publication.status || "pending");
    return Math.max(38, Math.min(96, Math.round((ratio * 0.38) + (release * 0.34) + (board * 0.18) + 18 - challengePenalty)));
  }

  function executiveDriverModels(run, citations, challenged) {
    const publication = publicationContract();
    const findings = findingsTotals();
    const queueCount = Array.isArray(state.pendingReviews?.items) ? state.pendingReviews.items.length : 0;
    const persona = currentExecutivePersona();
    return executiveDriverBaseline().map((driver) => {
      const stories = {
        revenue: "Revenue can carry the room only if the supporting evidence and release posture remain clean.",
        ebitda: "EBITDA is the designed tension tile: margin discipline, FX drag, and board confidence meet here.",
        readiness: "Board readiness stays bounded to approved material, publication posture, and explicit governed next actions.",
        board_packet: "Board lifecycle parity is bounded to approved materials, publication posture, and the next explicit governed action.",
        cash: "Cash strength should calm the room, but it must not blur the distinction between liquidity comfort and execution discipline.",
        margin: "Margin remains the CFO's pressure line: one disciplined answer matters more than ten decorative metrics.",
        growth: "Growth can stay celebratory only when service, evidence, and release posture are still intact.",
        controls: "Controls belong in the spotlight when leakage or proof discipline are the true board questions.",
        service: "Service resilience should feel calm and precise, not noisy — this is a confidence signal.",
        cold_chain: "Cold-chain reliability belongs in the packet as proof of operational discipline, not as dashboard theatre.",
        release: "Publication posture and board-pack choreography are what make the design feel trustworthy.",
      };
      const metric = driver.metric;
      const sub = driver.key === "cash" && run?.total_recoverable_sar
        ? `${formatSarShort(run.total_recoverable_sar)} recoverable · ${driver.sub}`
        : driver.key === "readiness" || driver.key === "release"
          ? `${humanizeToken(publication.board_pack?.status || "pending")} · ${driver.sub}`
          : driver.key === "ebitda" || driver.key === "margin"
            ? `${formatCount(challenged || 0)} challenge${Number(challenged || 0) === 1 ? "" : "s"} · ${driver.sub}`
            : driver.key === "revenue" && findings.total
              ? `${formatCount(findings.total)} governed cases · ${driver.sub}`
              : driver.sub;
      const chips = (driver.chips || []).concat([
        queueCount ? `${formatCount(queueCount)} pending` : "queue clear",
        citations.count !== null && citations.count !== undefined ? `${formatCount(citations.resolved || 0)} / ${formatCount(citations.count)} cited` : "awaiting citations",
        persona.key === "board" ? humanizeToken(currentLifecycleMode().key) : scopeLabel(),
      ]).slice(0, 4);
      return {
        ...driver,
        metric,
        sub,
        story: stories[driver.key] || "This driver is rendered for design fidelity, then grounded back into the current governed packet.",
        chips,
      };
    });
  }

  function renderExecutiveModes() {
    if (!els.personaTabs || !els.lifecycleTabs || !els.driverStack) return;
    applyDisplayModes();
    const persona = currentExecutivePersona();
    const personaModel = currentPersonaModel();
    const lifecycle = currentLifecycleMode();
    const findings = findingsPayload();
    const citations = normalizedCitationSummary(state.latestRun || {}, findings);
    const publication = publicationContract();
    const challenged = challengedSummary(state.latestRun || {}) || 0;
    const drivers = strategyValueDrivers();
    const domains = domainSummaryRows();
    const derived = derivedLifecycleMode();
    const personaTabs = contractExecutivePersonas();
    const lifecycleTabs = contractBoardLifecycles();

    const personaCopy = {
      ceo: {
        title: "Group CEO framing",
        note: "Khalid's executive frame keeps value, release posture, and board-pack readiness in one designed readout.",
      },
      cfo: {
        title: "Group CFO framing",
        note: "Sara's frame prioritises hedge exposure, margin discipline, and cash confidence before room theatre.",
      },
      gm: {
        title: "e-Pharmacy GM framing",
        note: "Growth, conversion, and service quality stay visible without turning the surface into raw operating clutter.",
      },
      bucfo: {
        title: "Tamween BU CFO framing",
        note: "Leakage, controls, and evidence proof take precedence over decorative momentum in this frame.",
      },
      logistics: {
        title: "Logistics resilience framing",
        note: "Cold-chain confidence, continuity, and service integrity drive the narrative here.",
      },
      board: {
        title: "Board portal framing",
        note: "Only board-safe packet posture is shown here: approved material, meeting readiness, and frozen narrative boundaries.",
      },
      audit: {
        title: "Audit and evidence framing",
        note: "Challenge state, citation integrity, and claim safety take priority over headline value when this frame is active.",
      },
      ops: {
        title: "Operator relay framing",
        note: "This frame makes downstream execution dependencies visible without turning the executive surface into a control plane.",
      },
    }[persona.key];

    const lifecycleCopy = {
      pre: {
        title: "Pre-board preparation",
        note: `Prepare the packet: ${formatCount(challenged)} challenge${Number(challenged) === 1 ? " remains" : "s remain"} and board pack ${humanizeToken(publication.board_pack?.status || "pending")}.`,
      },
      live: {
        title: "Live board session",
        note: "Use approved material only. StrategyOS should answer from the governed packet, not from uncited operator context.",
      },
      closed: {
        title: "Closed meeting memory",
        note: "The packet is in retrospective mode: publication, approved reports, and bounded follow-up can be reviewed without reopening execution controls.",
      },
    }[lifecycle.key];

    els.personaTitle.textContent = personaCopy.title;
    els.personaNote.textContent = personaCopy.note;
    els.lifecycleTitle.textContent = lifecycleCopy.title;
    els.lifecycleNote.textContent = `${lifecycleCopy.note} Derived posture: ${humanizeToken(derived)}.`;
    if (els.personaButtonRole) els.personaButtonRole.textContent = persona.label;
    if (els.topbarBoardState) els.topbarBoardState.textContent = `${lifecycle.label} · ${persona.assistant}`;
    if (els.personaButton) els.personaButton.setAttribute("aria-expanded", state.personaMenuOpen ? "true" : "false");
    if (els.personaMenu) {
      els.personaMenu.hidden = !state.personaMenuOpen;
      els.personaMenu.innerHTML = personaTabs.map((item) => `
        <button class="persona-menu-item${item.key === persona.key ? " is-active" : ""}${item.key === "board" ? " is-board" : ""}" type="button" data-persona-menu-item="${escapeHtml(item.key)}">
          <span class="persona-menu-item-top">
            <strong>${escapeHtml(item.label)}</strong>
            <span class="persona-menu-item-tag">${escapeHtml(item.key === "board" ? "board" : "persona")}</span>
            ${item.key === persona.key ? '<span class="persona-menu-item-check">✓</span>' : ""}
          </span>
          <span>${escapeHtml(item.detail)}</span>
          <span>${escapeHtml(item.assistant || item.label)}</span>
        </button>
      `).join("");
    }

    els.personaTabs.innerHTML = personaTabs.map((item) => `
      <button class="mode-tab${item.key === persona.key ? " is-active" : ""}" type="button" data-exec-persona="${escapeHtml(item.key)}" role="tab" aria-selected="${item.key === persona.key ? "true" : "false"}">
        <strong>${escapeHtml(item.label)}</strong>
        <span>${escapeHtml(item.detail)}</span>
        <small>${escapeHtml(item.assistant || item.label)}</small>
      </button>
    `).join("");
    els.lifecycleTabs.innerHTML = lifecycleTabs.map((item) => `
      <button class="mode-tab${item.key === lifecycle.key ? " is-active" : ""}" type="button" data-board-state="${escapeHtml(item.key)}" role="tab" aria-selected="${item.key === lifecycle.key ? "true" : "false"}">
        <strong>${escapeHtml(item.label)}</strong>
        <span>${escapeHtml(item.detail)}</span>
      </button>
    `).join("");

    const driverRows = (drivers.length
      ? drivers.slice(0, 3).map((driver) => ({
        title: driver.label || "Value driver",
        text: `${driver.metric || "--"} · ${driver.detail || "Awaiting detail"}`,
        amount: humanizeToken(driver.status || "active"),
        tone: driver.tone || driver.status || "safe",
      }))
      : domains.slice(0, 3).map((domain) => ({
        title: domain.label,
        text: `${formatCount(domain.count)} cases · ${formatCount(domain.challenged)} challenged · ${formatSarShort(domain.recoverable)} recoverable`,
        amount: domain.challenged ? "watch" : "stable",
        tone: domain.challenged ? "human" : "safe",
      }))
    );
    const fallbackRows = [
      {
        title: "Board packet readiness",
        text: `${formatCount(publication.report_count ?? 0)} report surfaces · approval ${humanizeToken(publication.approval_status || approvalSummary(state.latestRun || {}))}`,
        amount: humanizeToken(publication.board_pack?.status || "pending"),
        tone: publication.status || "pending",
      },
      {
        title: "Evidence gravity",
        text: citations.detail,
        amount: citations.count !== null && citations.count !== undefined ? `${formatCount(citations.resolved)} / ${formatCount(citations.count)}` : "--",
        tone: challenged ? "human" : "safe",
      },
    ];
    els.driverStack.innerHTML = (driverRows.length ? driverRows : fallbackRows)
      .map((item) => decisionCard(item.title, item.text, item.amount, item.tone))
      .join("");

    if (els.themeTabs) {
      els.themeTabs.innerHTML = DISPLAY_THEMES.map((item) => `
        <button class="mode-tab${item.key === currentThemeMode().key ? " is-active" : ""}" type="button" data-theme-mode="${escapeHtml(item.key)}" role="tab" aria-selected="${item.key === currentThemeMode().key ? "true" : "false"}">
          <strong>${escapeHtml(item.label)}</strong>
          <span>${escapeHtml(item.detail)}</span>
        </button>
      `).join("");
    }
    if (els.densityTabs) {
      els.densityTabs.innerHTML = DISPLAY_DENSITIES.map((item) => `
        <button class="mode-tab${item.key === currentDensityMode().key ? " is-active" : ""}" type="button" data-density-mode="${escapeHtml(item.key)}" role="tab" aria-selected="${item.key === currentDensityMode().key ? "true" : "false"}">
          <strong>${escapeHtml(item.label)}</strong>
          <span>${escapeHtml(item.detail)}</span>
        </button>
      `).join("");
    }
    if (els.moversTabs) {
      els.moversTabs.innerHTML = MOVERS_VIEWS.map((item) => `
        <button class="mode-tab${item.key === currentMoversMode().key ? " is-active" : ""}" type="button" data-movers-mode="${escapeHtml(item.key)}" role="tab" aria-selected="${item.key === currentMoversMode().key ? "true" : "false"}">
          <strong>${escapeHtml(item.label)}</strong>
          <span>${escapeHtml(item.detail)}</span>
        </button>
      `).join("");
    }
    if (els.gravityQuote) els.gravityQuote.textContent = personaModel.quote;
    if (els.gravityBy) els.gravityBy.textContent = personaModel.by;
      if (els.gravityRails) {
        const weekModel = Array.isArray(personaModel.week) ? personaModel.week.find((item) => item.key === state.selectedWeekEventKey) : null;
        els.gravityRails.innerHTML = [
          `<span class="badge blue">${escapeHtml(personaModel.assistant)}</span>`,
          `<span class="badge blue">${escapeHtml(personaModel.assistantRole)}</span>`,
          `<span class="badge blue">${escapeHtml(humanizeToken(lifecycle.key))}</span>`,
          weekModel ? `<span class="badge blue">${escapeHtml(weekModel.title)}</span>` : "",
        ].join("");
      }
    if (els.gravityPromptList) {
      els.gravityPromptList.innerHTML = personaModel.prompts.map((prompt) => `
        <button class="gravity-prompt-btn" type="button" data-exec-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>
      `).join("");
    }
    if (els.gravityInput && !els.gravityInput.value) {
      els.gravityInput.placeholder = persona.key === "board"
        ? "Ask the frozen packet a board-safe what-if…"
        : `Ask ${personaModel.assistant} for a board-safe scenario…`;
    }

    els.personaTabs.querySelectorAll("[data-exec-persona]").forEach((button) => {
      button.addEventListener("click", () => {
        state.executivePersona = button.getAttribute("data-exec-persona") || "ceo";
        state.lifecycleMode = currentLifecycleMode().key;
        state.selectedThreadKey = "briefing";
        state.personaMenuOpen = false;
        syncExecutiveRouteState();
        refreshLiveData();
      });
    });
    if (els.personaButton) els.personaButton.onclick = () => {
      state.personaMenuOpen = !state.personaMenuOpen;
      renderExecutiveModes();
    };
    els.personaMenu?.querySelectorAll("[data-persona-menu-item]").forEach((button) => {
      button.addEventListener("click", () => {
        state.executivePersona = button.getAttribute("data-persona-menu-item") || "ceo";
        state.lifecycleMode = currentLifecycleMode().key;
        state.selectedThreadKey = "briefing";
        state.personaMenuOpen = false;
        syncExecutiveRouteState();
        refreshLiveData();
      });
    });
    els.lifecycleTabs.querySelectorAll("[data-board-state]").forEach((button) => {
      button.addEventListener("click", () => {
        state.lifecycleMode = button.getAttribute("data-board-state") || derivedLifecycleMode();
        syncExecutiveRouteState();
        refreshLiveData();
      });
    });
    els.themeTabs?.querySelectorAll("[data-theme-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        state.themeMode = button.getAttribute("data-theme-mode") || "midnight";
        renderExecutiveModes();
      });
    });
    els.densityTabs?.querySelectorAll("[data-density-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        state.densityMode = button.getAttribute("data-density-mode") || "comfortable";
        renderExecutiveModes();
      });
    });
    els.moversTabs?.querySelectorAll("[data-movers-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        state.moversMode = button.getAttribute("data-movers-mode") || "cards";
        renderExecutiveModes();
        rerenderExecutiveNarrative();
      });
    });
    els.gravityPromptList?.querySelectorAll("[data-exec-prompt]").forEach((button) => {
      button.addEventListener("click", () => {
        const prompt = button.getAttribute("data-exec-prompt") || "";
        setCommandPrompt(prompt);
      });
    });
    if (els.gravitySubmit) els.gravitySubmit.onclick = () => {
      const prompt = String(els.gravityInput?.value || "").trim();
      if (!prompt) return;
      setCommandPrompt(prompt);
    };
    if (els.gravityInput) els.gravityInput.onkeydown = (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      const prompt = String(els.gravityInput?.value || "").trim();
      if (!prompt) return;
      setCommandPrompt(prompt);
    };
  }

  function renderExecutiveHero(run, citations, challenged) {
    if (!els.heroScore || !els.driverTiles) return;
    const persona = currentExecutivePersona();
    const personaModel = currentPersonaModel();
    const publication = publicationContract();
    const blueprint = personaBlueprint();
    const drivers = executiveDriverModels(run, citations, challenged);
    if (!drivers.find((item) => item.key === state.selectedDriverKey)) {
      state.selectedDriverKey = drivers[0]?.key || "board_packet";
    }
    const selected = drivers.find((item) => item.key === state.selectedDriverKey) || drivers[0];
    const score = personaModel.designScore ?? boundedScore(citations, challenged, publication);
    const headline = publication.status === "published"
      ? "The packet is board-safe and closed into memory."
      : challenged && persona.key === "board"
        ? `${formatCount(challenged)} challenge${Number(challenged) === 1 ? " is" : "s are"} still shaping the approved board packet.`
        : blueprint?.health?.headline
          ? blueprint.health.headline
          : personaModel.brief;
    els.heroGreeting.textContent = personaModel.greeting;
    els.heroHeadline.textContent = headline;
    els.heroCopy.textContent = blueprint?.health?.body || selected?.story || "The 22.06 hero composition stays grounded to current governed packet truth: evidence closure, release posture, board-pack readiness, and the latest finance signal only.";
    els.heroBoundary.textContent = `Composed from ${selected?.title || "bounded drivers"}, publication posture, and governed evidence inside ${scopeLabel()}. No enterprise-wide plan compiler claim is made.`;
    els.heroScore.textContent = String(score);
    els.heroScoreNote.textContent = persona.key === "board" ? "CEO-approved board pack" : (blueprint?.health?.scoreNote || personaModel.title);
    els.driverTiles.innerHTML = drivers.map((driver) => `
      <button class="driver-tile${driver.key === selected?.key ? " is-active" : ""}" type="button" data-driver-key="${escapeHtml(driver.key)}">
        <div class="driver-tile-top">
          <span class="badge ${badgeTone(driver.percent >= 80 ? "ok" : driver.percent >= 60 ? "neutral" : "warn")}">${escapeHtml(driver.metric)}</span>
          <span class="driver-ring-mini">${escapeHtml(`${driver.percent}%`)}</span>
        </div>
        <h3>${escapeHtml(driver.title)}</h3>
        <strong>${escapeHtml(driver.sub)}</strong>
        <p>${escapeHtml(driver.story)}</p>
      </button>
    `).join("");
    els.driverDetailTitle.textContent = selected?.title || "Awaiting driver selection";
    els.driverDetailMetric.textContent = selected?.metric || "--";
    els.driverDetailStory.textContent = selected?.story || "Select a driver card to inspect the bounded rationale behind it.";
    els.driverDetailChips.innerHTML = (selected?.chips || []).map((chip) => `<span class="badge blue">${escapeHtml(chip)}</span>`).join("");
    renderDriverDrillFidelity(selected, run, citations, challenged);
    els.driverTiles.querySelectorAll("[data-driver-key]").forEach((button) => {
      button.addEventListener("click", () => {
        state.selectedDriverKey = button.getAttribute("data-driver-key") || drivers[0]?.key || "board_packet";
        syncExecutiveRouteState();
        renderExecutiveHero(run, citations, challenged);
      });
    });
  }

  function renderDriverDrillFidelity(selected, run, citations, challenged) {
    const moversMode = currentMoversMode();
    if (els.moversCaption) els.moversCaption.textContent = `${moversMode.label.toLowerCase()} view`;
    const positive = Array.isArray(selected?.movers?.lifting) ? selected.movers.lifting.map((item) => ({ ...item, tone: "up" })) : [];
    const negative = Array.isArray(selected?.movers?.dragging) ? selected.movers.dragging.map((item) => ({ ...item, tone: "down" })) : [];
    const movers = positive.concat(negative);
    const trendRows = [
      {
        title: `${selected?.title || "Driver"} signal`,
        detail: selected?.vsPlan ? `${selected.sub} · ${selected.vsPlan}` : selected?.sub || "Awaiting driver signal",
        meta: selected?.trendLabel || citations.detail,
      },
      {
        title: "Driver story",
        detail: selected?.story || "Awaiting cited chain",
        meta: challenged ? `${formatCount(challenged)} challenges still visible` : citations.detail,
      },
      {
        title: "Release posture",
        detail: publicationStatusLabel(publicationContract().status || approvalSummary(run || {})),
        meta: `Board pack ${humanizeToken(publicationContract().board_pack?.status || "pending")}`,
      },
    ];
    if (els.drillTrend) {
      els.drillTrend.innerHTML = trendRows.map((row) => `
        <div class="driver-trend-row">
          <strong>${escapeHtml(row.title)}</strong>
          <span>${escapeHtml(row.detail)}</span>
          <small>${escapeHtml(row.meta)}</small>
        </div>
      `).join("");
    }

    const moverHtml = movers.map((item) => {
      const width = Math.max(18, Math.min(96, 50 + (Number(item.contribution || 0) * 1.5)));
      if (moversMode.key === "ledger") {
        return `
          <div class="mover-card">
            <div class="mover-card-top"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.delta)} · ${escapeHtml(String(item.contribution || 0))}</span></div>
            <small>${escapeHtml(item.note || `${item.tone === "up" ? "lifting" : "dragging"} this driver` )}</small>
          </div>
        `;
      }
      if (moversMode.key === "bar") {
        return `
          <div class="mover-card">
            <div class="mover-card-top"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.delta)}</span></div>
            <div class="mover-bar-track"><span class="mover-bar-fill" style="width:${width}%"></span></div>
            <small>${escapeHtml(item.note || `${Math.abs(Number(item.contribution || 0))} contribution points`)}</small>
          </div>
        `;
      }
      return `
        <div class="mover-card">
          <div class="mover-card-top"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.delta)}</span></div>
          <span>${escapeHtml(item.note || `${item.tone === "up" ? "Lift" : "Drag"} on ${selected?.title || "driver"}`)}</span>
          <small>${escapeHtml(item.tone === "up" ? "lifting" : "dragging")} · ${escapeHtml(String(item.contribution || 0))} contribution pts</small>
        </div>
      `;
    }).join("");
    if (els.drillMovers) els.drillMovers.innerHTML = moverHtml;

    const prompts = currentPersonaModel().prompts.slice(0, 3);
    if (els.drillPrompts) {
      els.drillPrompts.innerHTML = prompts.map((prompt) => `
        <button class="drill-prompt-btn" type="button" data-drill-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>
      `).join("");
      els.drillPrompts.querySelectorAll("[data-drill-prompt]").forEach((button) => {
        button.addEventListener("click", () => {
          setCommandPrompt(button.getAttribute("data-drill-prompt") || "");
        });
      });
    }
  }

  function renderLowerRailFidelity(run, citations, challenged) {
    const blueprint = personaBlueprint();
    const publication = publicationContract();
    const persona = currentExecutivePersona();
    const feedRows = [];
    (blueprint?.findings || []).slice(0, 2).forEach((item) => {
      feedRows.push({ title: item.title, detail: item.detail, chips: [item.tag, scopeLabel()] });
    });
    (blueprint?.developments || []).slice(0, 2).forEach((item) => {
      feedRows.push({ title: item.title, detail: `${item.meta} · ${item.impact}`, chips: [item.kind, currentPersonaModel().assistant] });
    });
    if (!feedRows.length) {
      feedRows.push({
        title: `${persona.label} brief`,
        detail: currentPersonaModel().brief,
        chips: [publicationStatusLabel(publication.status || "draft"), citations.count !== null && citations.count !== undefined ? `${formatCount(citations.resolved || 0)} / ${formatCount(citations.count)} cited` : "awaiting citations"],
      });
    }
    if (els.lowerMainBadge) els.lowerMainBadge.textContent = feedRows.length ? `${formatCount(feedRows.length)} live rows` : "Design packet";
    if (els.developmentsList) {
      els.developmentsList.innerHTML = feedRows.map((item) => `
        <button class="lower-feed-row lower-feed-button" type="button" data-lower-prompt="${escapeHtml(item.prompt || `Give me the board-safe follow-through on ${item.title}.`)}">
          <div class="lower-feed-top"><strong>${escapeHtml(item.title)}</strong><span class="badge blue">update</span></div>
          <span>${escapeHtml(item.detail)}</span>
          <div class="lower-feed-chip-row">${item.chips.map((chip) => `<span class="badge blue">${escapeHtml(chip)}</span>`).join("")}</div>
        </button>
      `).join("");
      els.developmentsList.querySelectorAll("[data-lower-prompt]").forEach((button) => {
        button.addEventListener("click", () => {
          setCommandPrompt(button.getAttribute("data-lower-prompt") || "");
        });
      });
    }
    const weekEvents = Array.isArray(blueprint?.week) && blueprint.week.length
      ? blueprint.week.map((item) => ({
          key: item.key,
          day: String(item.day || "").toUpperCase(),
          title: item.title,
          detail: item.when,
          prompt: item.prompt || item.title,
          foot: item.prep,
        }))
      : [
          {
            key: "board_prep",
            day: "TUE",
            title: "Board prep",
            detail: humanizeNextAction(publication.approval?.next_action || "prepare_board_pack"),
            prompt: `${currentPersonaModel().assistant}: prepare the board pack with the latest bounded changes.`,
            foot: `Board pack ${humanizeToken(publication.board_pack?.status || "pending")} · ${formatCount(challenged || 0)} challenges still shape room readiness.`,
          },
        ];
    if (!weekEvents.find((item) => item.key === state.selectedWeekEventKey)) {
      state.selectedWeekEventKey = weekEvents[0]?.key || "board_prep";
    }
    if (els.weekBadge) els.weekBadge.textContent = persona.key === "board" ? "Board cadence" : "Executive cadence";
    if (els.weekRail) {
      els.weekRail.innerHTML = weekEvents.map((item) => `
        <button class="week-event${item.key === state.selectedWeekEventKey ? " is-active" : ""}" type="button" data-week-key="${escapeHtml(item.key)}" data-week-prompt="${escapeHtml(item.prompt)}">
          <div class="week-event-top"><span class="week-day">${escapeHtml(item.day)}</span><strong>${escapeHtml(item.title)}</strong></div>
          <span>${escapeHtml(item.detail)}</span>
          ${item.key === state.selectedWeekEventKey ? `<div class="week-event-detail"><p>${escapeHtml(item.foot)}</p><div class="week-event-actions"><span class="week-action">Prep with ${escapeHtml(currentPersonaModel().assistant)}</span><span class="week-action">Hold to governed packet</span></div></div>` : ""}
        </button>
      `).join("");
      els.weekRail.querySelectorAll("[data-week-key]").forEach((button) => {
        button.addEventListener("click", () => {
          state.selectedWeekEventKey = button.getAttribute("data-week-key") || "board_prep";
          syncExecutiveRouteState();
          renderLowerRailFidelity(run, citations, challenged);
          setCommandPrompt(button.getAttribute("data-week-prompt") || "");
        });
      });
    }
    renderCashPulseAndOwed(run, citations, challenged);
  }

  function renderCashPulseAndOwed(run, citations, challenged) {
    const blueprint = personaBlueprint();
    const drivers = executiveDriverModels(run, citations, challenged).slice(0, 4);
    const publication = publicationContract();
    const persona = currentExecutivePersona();
    const showSecondary = blueprint?.secondaryMode !== "hidden";
    if (els.secondaryGrid) els.secondaryGrid.hidden = !showSecondary;
    if (!showSecondary) return;
    if (els.pulseTitle) els.pulseTitle.textContent = blueprint?.cashPulse?.title || "Driver pressure";
    if (els.pulseNote) els.pulseNote.textContent = blueprint?.cashPulse?.note || "Four designed tiles carrying the current diagnostic pressure downward.";
    if (els.owedTitle) els.owedTitle.textContent = blueprint?.owedUpward?.title || "Owed upward";
    if (els.owedNote) els.owedNote.textContent = blueprint?.owedUpward?.note || "Commentary that still needs to move upward with the number.";
    if (els.pulseGrid) {
      const pulseRows = Array.isArray(blueprint?.cashPulse?.pillars) && blueprint.cashPulse.pillars.length
        ? blueprint.cashPulse.pillars
        : drivers.map((driver) => ({ label: driver.title, value: String(driver.percent), sub: `${driver.metric} · ${driver.sub}`, delta: (driver.chips || [])[0] || scopeLabel(), tone: driver.percent >= 101 ? "up" : driver.percent >= 99 ? "flat" : "down", prompt: `Explain the board-safe pressure behind ${driver.title}.` }));
      els.pulseGrid.innerHTML = pulseRows.map((driver) => {
        const tone = driver.tone || (driver.percent >= 101 ? "up" : driver.percent >= 99 ? "flat" : "down");
        return `
          <button class="pulse-tile tone-${tone}" type="button" data-pulse-prompt="${escapeHtml(driver.prompt || `Explain the board-safe pressure behind ${driver.label}.`)}">
            <span class="pulse-label">${escapeHtml(driver.label)}</span>
            <strong class="pulse-value">${escapeHtml(String(driver.value))}</strong>
            <span class="pulse-sub">${escapeHtml(driver.sub)}</span>
            <span class="pulse-delta">${escapeHtml(driver.delta)}</span>
          </button>
        `;
      }).join("");
      els.pulseGrid.querySelectorAll("[data-pulse-prompt]").forEach((button) => {
        button.addEventListener("click", () => {
          setCommandPrompt(button.getAttribute("data-pulse-prompt") || "");
        });
      });
    }
    const owedRows = Array.isArray(blueprint?.owedUpward?.items) && blueprint.owedUpward.items.length
      ? blueprint.owedUpward.items
      : [
          {
            to: persona.key === "board" ? "To board secretary" : "To Group CEO",
            on: `${humanizeNextAction(publication.approval?.next_action || "prepare_board_pack")}`,
            note: `Current packet posture is ${publicationStatusLabel(publication.status || approvalSummary(run || {}))}; the handoff remains bounded to approved materials and cited evidence.`,
            status: publication.status === "published" ? "authored" : challenged ? "due-today" : "awaiting",
          },
          {
            to: "To CFO / finance lead",
            on: challenged ? "Close the EBITDA and hedge tension before room confidence is claimed." : "Carry forward the approved downside note into the room.",
            note: citations.detail,
            status: challenged ? "due-now" : "authored",
          },
        ];
    if (els.owedList) {
      els.owedList.innerHTML = owedRows.map((item) => `
        <div class="owed-row">
          <div class="owed-meta">
            <span class="owed-to">${escapeHtml(item.to)}</span>
            <strong class="owed-on">${escapeHtml(item.on)}</strong>
          </div>
          <span class="owed-status s-${escapeHtml(item.status)}">${escapeHtml(item.status.replaceAll("-", " "))}</span>
          <p class="owed-note">${escapeHtml(item.note)}</p>
        </div>
      `).join("");
    }
  }

  function renderAssistantNarrative(run, citations, challenged) {
    const persona = currentExecutivePersona();
    const model = currentPersonaModel();
    const threads = model.threads || [];
    if (!threads.find((item) => item.key === state.selectedThreadKey)) {
      state.selectedThreadKey = threads[0]?.key || "briefing";
    }
    const activeThread = threads.find((item) => item.key === state.selectedThreadKey) || threads[0];
    if (els.copilotTitle) els.copilotTitle.textContent = `${model.assistant} · ${model.title}`;
    if (els.copilotSubtitle) {
      els.copilotSubtitle.textContent = `${model.assistantRole} · named, threaded, and board-safe. ${challenged ? `${formatCount(challenged)} challenge${Number(challenged) === 1 ? " is" : "s are"} still visible.` : "Human gates stay visible."}`;
    }
    if (els.threadList) {
      els.threadList.innerHTML = threads.map((thread) => `
        <button class="thread-item${thread.key === state.selectedThreadKey ? " is-active" : ""}" type="button" data-thread-key="${escapeHtml(thread.key)}">
          <strong>${escapeHtml(thread.title)}</strong>
          <span>${escapeHtml(thread.preview)}</span>
        </button>
      `).join("");
      els.threadList.querySelectorAll("[data-thread-key]").forEach((button) => {
        button.addEventListener("click", () => {
          state.selectedThreadKey = button.getAttribute("data-thread-key") || "briefing";
          renderAssistantNarrative(run, citations, challenged);
        });
      });
    }
    if (els.assistantNetwork) {
      els.assistantNetwork.innerHTML = contractExecutivePersonas().filter((item) => item.key !== persona.key).slice(0, 4).map((item) => `
        <button class="network-item" type="button" data-network-persona="${escapeHtml(item.key)}">
          <strong>${escapeHtml(item.assistant || item.label)}</strong>
          <span>${escapeHtml(item.label)} · available for bounded handoff</span>
        </button>
      `).join("");
      els.assistantNetwork.querySelectorAll("[data-network-persona]").forEach((button) => {
        button.addEventListener("click", () => {
          const nextPersona = button.getAttribute("data-network-persona") || "ceo";
          state.executivePersona = nextPersona;
          state.selectedThreadKey = "briefing";
          syncExecutiveRouteState();
          refreshLiveData();
        });
      });
    }
    const messageMap = {
      briefing: [
        message("system", `${model.assistant} · opening brief`, model.brief),
        message("", "Board-safe read", activeThread?.preview || "Awaiting thread prompt."),
      ],
      hedge: [
        message("system", `${model.assistant} · downside read`, "The packet is designed to answer the hard downside question without leaving the approved evidence boundary."),
        message("", "Ask next", activeThread?.preview || "Prompt the hedge scenario."),
      ],
      recognition: [
        message("system", `${model.assistant} · recognition read`, "Use this thread to pull forward one precise win without diluting the packet with noise."),
        message("", "Ask next", activeThread?.preview || "Prompt recognition detail."),
      ],
    };
    els.assistantFeed.innerHTML = (messageMap[state.selectedThreadKey] || messageMap.briefing).join("");
  }

  function boardListItem(title, detail, meta, tone) {
    return `
      <div class="board-list-item">
        <strong>${escapeHtml(title)}</strong>
        <span>${escapeHtml(detail)}</span>
        <small>${escapeHtml(meta)}</small>
        <span class="badge ${badgeTone(tone === "safe" ? "ok" : tone === "watch" ? "warn" : "neutral")}">${escapeHtml(tone)}</span>
      </div>
    `;
  }

  function renderBoardPortal(run, citations, challenged) {
    if (!els.boardLifecycle || !els.boardPrimaryList) return;
    const board = boardBlueprint();
    const lifecycle = currentLifecycleMode();
    const publication = publicationContract();
    const artifacts = Array.isArray(state.workspaceContract?.reports?.artifacts) ? state.workspaceContract.reports.artifacts : [];
    const reasoning = strategyReasoningItems();
    const findings = findingsPayload();
    const queueItems = Array.isArray(state.pendingReviews?.items) ? state.pendingReviews.items : [];
    const drivers = Array.isArray(board?.kpis) && board.kpis.length ? board.kpis : executiveDriverModels(run, citations, challenged).slice(0, 4);
    const boardTitle = lifecycle.key === "live"
      ? `${board?.meeting?.title || scopeLabel()} · live board session`
      : lifecycle.key === "closed"
        ? `${board?.meeting?.title || scopeLabel()} · closed board memory`
        : `${board?.meeting?.title || scopeLabel()} · pre-board packet`;
    const lifecycleNotes = {
      pre: "Only CEO-approved and board-safe material appears before the room opens.",
      live: "Live board Q&A stays attached to approved material only.",
      closed: "The packet is frozen into memory; follow-up can be reviewed without reopening raw execution controls.",
    };
    els.boardTitle.textContent = boardTitle;
    els.boardMeta.textContent = board?.meeting
      ? `${board.meeting.date} · ${board.meeting.room} · ${board.meeting.when}`
      : `${lifecycle.label} posture · board pack ${humanizeToken(publication.board_pack?.status || "pending")} · approval ${humanizeToken(publication.approval_status || approvalSummary(run || {}))}`;
    els.boardStateBadge.textContent = lifecycle.label;
    els.boardGovernance.textContent = board?.governance || (lifecycle.key === "live"
      ? "Answers must remain inside the approved packet; no uncited operator context should leak into the room."
      : lifecycle.key === "closed"
        ? "Between meetings, the board sees a frozen snapshot of the governed packet rather than live operational churn."
        : "Nothing reaches the board until the packet is approved and board-safe surfaces are explicit.");
    els.boardSummary.textContent = lifecycleNotes[lifecycle.key];
    const lifecycleTabs = contractBoardLifecycles();
    const activeLifecycleIndex = lifecycleTabs.findIndex((item) => item.key === lifecycle.key);
    els.boardLifecycle.innerHTML = lifecycleTabs.map((item, index) => `
      <button class="board-lifecycle-step${item.key === lifecycle.key ? " is-active" : ""}${activeLifecycleIndex > index ? " is-past" : ""}" type="button" data-board-lifecycle-step="${escapeHtml(item.key)}">
        <strong>${escapeHtml(item.label)}</strong>
        <span>${escapeHtml(item.summary || item.detail)}</span>
      </button>
    `).join("");
    els.boardKpis.innerHTML = drivers.map((driver) => `
      <div class="board-kpi">
        <span>${escapeHtml(driver.title)}</span>
        <strong>${escapeHtml(driver.metric)}</strong>
      </div>
    `).join("");
    renderBoardStateDetail(run, citations, challenged);
    els.boardLifecycle.querySelectorAll("[data-board-lifecycle-step]").forEach((button) => {
      button.addEventListener("click", () => {
        state.lifecycleMode = button.getAttribute("data-board-lifecycle-step") || lifecycle.key;
        syncExecutiveRouteState();
        refreshLiveData();
      });
    });

    if (lifecycle.key === "pre") {
      els.boardColumnTitle.textContent = "CEO-approved material";
      els.boardColumnNote.textContent = "Decks and documents released to the board — only what the CEO has approved appears.";
      const material = Array.isArray(board?.decks) && board.decks.length ? board.decks : (artifacts.length ? artifacts : [{ artifact_key: "board_safe_preview", title: "Board-safe preview", restricted: false }]).slice(0, 4);
      els.boardPrimaryList.innerHTML = material.map((item) => boardListItem(
        item.title || reportLabel(item.artifact_key),
        item.by ? `${item.by} · ${item.pages} pages` : `${item.restricted ? "Restricted artifact" : "Previewable packet"} · ${publicationStatusLabel(publication.status || "awaiting_review")}`,
        item.tag || item.artifact_key || publication.preview_route || "/public/runs/latest/report-preview",
        String(item.status || "approved").toLowerCase().includes("pending") ? "watch" : (item.restricted ? "watch" : "safe"),
      )).join("");
      els.boardRailTitle.textContent = "Supplementary questions";
      els.boardRailNote.textContent = "Raise prep items to the CEO before the meeting.";
      const questions = Array.isArray(board?.supplementary) && board.supplementary.length
        ? board.supplementary.map((item) => ({ title: item.q, detail: `to ${item.to}`, meta: item.status, tone: item.status === "answered" ? "safe" : "watch" }))
        : (queueItems.map((item) => ({
            title: item.title || item.run_id || "Pending review item",
            detail: `${item.current_stage || item.status || "awaiting_review"} · ${item.approval_status || "pending"}`,
            meta: "Reviewer queue",
            tone: item.approval_status === "approved" ? "safe" : "watch",
          })).concat(findings.filter((item) => item?.challenged).map((item) => ({
            title: item.title || item.finding_id || "Challenge open",
            detail: `${item.owner || "reviewer"} · ${formatCount(item.citation_count || 0)} cites`,
            meta: "Needs closure before board release",
            tone: "watch",
          })))).slice(0, 4);
      els.boardSecondaryList.innerHTML = questions.length
        ? questions.map((item) => boardListItem(item.title, item.detail, item.meta, item.tone)).join("")
        : boardListItem("No outstanding board prep questions", "The current bounded packet has no extra prep rows beyond publication posture.", humanizeNextAction(publication.approval?.next_action || "prepare_board_pack"), "safe");
      els.boardRailFoot.textContent = "If the packet lacks an answer, StrategyOS routes the question back through reviewer or operator surfaces instead of inventing board content.";
      return;
    }

    if (lifecycle.key === "live") {
      els.boardColumnTitle.textContent = "Live session prompts";
      els.boardColumnNote.textContent = "Board-safe prompts stay attached to the approved packet only.";
      const liveRows = Array.isArray(board?.livePrompts) && board.livePrompts.length
        ? board.livePrompts.map((prompt) => ({ title: prompt, owner: board.assistant || "board assistant", challenged: false }))
        : (findings.length ? findings : [{ title: "Latest governed packet", finding_id: compactRunId(run) }]).slice(0, 4);
      els.boardPrimaryList.innerHTML = liveRows.map((item, index) => boardListItem(
        item.title || item.pattern_label || item.finding_id || `Board prompt ${index + 1}`,
        `${item.recoverable_sar ? formatSarShort(item.recoverable_sar) : publicationStatusLabel(publication.status || "approved_for_release")} · ${item.owner || "board assistant"}`,
        item.finding_id || publication.preview_route || "/public/runs/latest/report-preview",
        item.challenged ? "watch" : "safe",
      )).join("");
      els.boardRailTitle.textContent = "Session boundaries";
      els.boardRailNote.textContent = "The room can ask questions, but only from approved material and bounded finance evidence.";
      const boundaries = [
        { title: "Board-safe preview", detail: publication.preview_route || "/public/runs/latest/report-preview", meta: "Approved packet route", tone: "safe" },
        { title: "Allowed actions", detail: publicationActionLabels(publication).join(", ") || "Inspect publication boundary", meta: "No executive control mutation", tone: "watch" },
        { title: "Evidence posture", detail: citations.detail, meta: `${formatCount(challenged || 0)} challenges visible`, tone: challenged ? "watch" : "safe" },
      ];
      els.boardSecondaryList.innerHTML = boundaries.map((item) => boardListItem(item.title, item.detail, item.meta, item.tone)).join("");
      els.boardRailFoot.textContent = "Live Q&A stays board-safe: StrategyOS should answer from the governed packet, not from uncited operator context.";
      return;
    }

    els.boardColumnTitle.textContent = "Meeting summary & action plan";
    els.boardColumnNote.textContent = "Closed-state summary stays grounded to the latest governed outputs and follow-up routes.";
    const summaryRows = (
      Array.isArray(board?.actions) && board.actions.length
        ? board.actions.map((item) => ({ claim: item.item, rationale: item.owner, recommended_route: item.due, status: "published" }))
        : reasoning.length
          ? reasoning
          : [
              { claim: "Publication route", rationale: publication.preview_route || "/public/runs/latest/report-preview", status: publication.status || "published" },
              { claim: "Latest value signal", rationale: formatSarShort(run?.total_recoverable_sar), status: approvalSummary(run || {}) },
            ]
    ).slice(0, 4);
    els.boardPrimaryList.innerHTML = summaryRows.map((item) => boardListItem(
      item.claim || item.title || "Board memory",
      item.rationale || item.detail || "Bounded retrospective summary",
      item.recommended_route || item.route || humanizeNextAction(publication.approval?.next_action || "inspect_published_outputs"),
      item.status === "published" || item.status === "approved" ? "safe" : "neutral",
    )).join("");
    els.boardRailTitle.textContent = "Frozen snapshot";
    els.boardRailNote.textContent = "After the room, StrategyOS should preserve a board-safe memory without reopening raw live data on the board surface.";
    els.boardSecondaryList.innerHTML = [
      boardListItem("Snapshot mode", "What-if thinking can happen here, but fresh operator context should stay outside the board view.", "Board memory only", "neutral"),
      boardListItem("Published outputs", `${formatCount(publication.report_count ?? 0)} surfaces · ${formatCount(publication.restricted_report_count ?? 0)} restricted`, humanizeToken(publication.board_pack?.status || "published"), publication.status === "published" ? "safe" : "watch"),
    ].join("");
    els.boardRailFoot.textContent = "Closed-state follow-up remains bounded to report surfaces, reviewer records, and governed memory routes.";
  }

  function renderBoardStateDetail(run, citations, challenged) {
    if (!els.boardStateDetail) return;
    const lifecycle = currentLifecycleMode();
    const persona = currentPersonaModel();
    const publication = publicationContract();
    if (lifecycle.key === "live") {
      const approvedDecks = Array.isArray(boardBlueprint()?.decks) ? boardBlueprint().decks.filter((item) => String(item.status || "").toLowerCase().includes("approved")).length : 0;
      els.boardStateDetail.innerHTML = `
        <div class="board-state-card">
          <strong>Live session · Q&amp;A on approved material</strong>
          <span>${escapeHtml(persona.assistant)} answers only from the CEO-approved packet. No uncited operator context belongs in the room.</span>
          <div class="board-state-metrics">
            <span class="board-state-metric"><strong>${escapeHtml(String(approvedDecks || 0))}</strong><small>approved decks</small></span>
            <span class="board-state-metric"><strong>${escapeHtml(String((boardBlueprint()?.livePrompts || []).length || 3))}</strong><small>live prompts</small></span>
            <span class="board-state-metric"><strong>${escapeHtml(String(challenged || 0))}</strong><small>challenge${Number(challenged || 0) === 1 ? "" : "s"}</small></span>
          </div>
          <div class="board-chip-row">
            ${(boardBlueprint()?.livePrompts || [
              "Why is EBITDA 20 bps under plan?",
              "Show the hedge downside",
              "Is the JV funded from cash?",
            ]).map((prompt) => `<button class="board-chip live" type="button" data-board-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`).join("")}
          </div>
        </div>
      `;
    } else if (lifecycle.key === "closed") {
      const actionCount = Array.isArray(boardBlueprint()?.actions) ? boardBlueprint().actions.length : 0;
      els.boardStateDetail.innerHTML = `
        <div class="board-state-card">
          <strong>❄ Frozen snapshot</strong>
          <span>Between meetings, ${escapeHtml(persona.assistant)} can model what-if questions on the frozen board packet, but no live org data should re-enter this surface until the next session.</span>
          <div class="board-state-metrics">
            <span class="board-state-metric"><strong>${escapeHtml(String(actionCount || 0))}</strong><small>follow-up actions</small></span>
            <span class="board-state-metric"><strong>${escapeHtml(String(publication.report_count ?? 0))}</strong><small>report surfaces</small></span>
            <span class="board-state-metric"><strong>${escapeHtml(publicationStatusLabel(publication.status || "published"))}</strong><small>publication</small></span>
          </div>
          <div class="board-state-actions">
            <button class="board-chip snapshot" type="button" data-board-prompt="Model a what-if on the frozen board snapshot: if EUR strengthens 5%, what changes?">◇ What-if on the snapshot</button>
            <span class="board-chip snapshot">${escapeHtml(publication.preview_route || "/public/runs/latest/report-preview")}</span>
          </div>
        </div>
      `;
    } else {
      const deckCount = Array.isArray(boardBlueprint()?.decks) ? boardBlueprint().decks.length : 0;
      const supplementaryCount = Array.isArray(boardBlueprint()?.supplementary) ? boardBlueprint().supplementary.length : 0;
      els.boardStateDetail.innerHTML = `
        <div class="board-state-card">
          <strong>Pre-board supplementary rail</strong>
          <span>Questions should rise here before the room: challenge closure, board-pack clarity, and anything the Group CEO must approve explicitly.</span>
          <div class="board-state-metrics">
            <span class="board-state-metric"><strong>${escapeHtml(String(deckCount || 0))}</strong><small>deck rows</small></span>
            <span class="board-state-metric"><strong>${escapeHtml(String(supplementaryCount || 0))}</strong><small>supplementary questions</small></span>
            <span class="board-state-metric"><strong>${escapeHtml(String(challenged || 0))}</strong><small>challenge${Number(challenged || 0) === 1 ? "" : "s"}</small></span>
          </div>
          <div class="board-state-actions">
            <button class="board-chip" type="button" data-board-prompt="Summarise the board deck and the decision it asks of the room.">Summarise the board deck</button>
            <button class="board-chip" type="button" data-board-prompt="What supplementary answer still needs to be prepared before the board?">Ask supplementary question</button>
            <span class="board-chip">${escapeHtml(formatCount(challenged || 0))} challenge${Number(challenged || 0) === 1 ? "" : "s"}</span>
          </div>
        </div>
      `;
    }
    els.boardStateDetail.querySelectorAll("[data-board-prompt]").forEach((button) => {
      button.addEventListener("click", () => {
        setCommandPrompt(button.getAttribute("data-board-prompt") || "");
      });
    });
  }

  function runtimeAgentCard(agent) {
    const key = slugifyToken(agent.key || agent.title);
    const open = state.openAgentKey === key;
    const logOpen = state.agentLogOpenKey === key;
    const approved = Boolean(state.approvedAgentKeys[key]);
    const statusClass = agent.requiresApproval && !approved ? "approval" : (agent.statusClass || "running");
    const toneClass = agent.toneClass || (statusClass === "approval" ? "down" : statusClass === "running" ? "flat" : "up");
    const statusLabel = agent.requiresApproval && !approved ? "needs your approval" : agent.status;
    return `
      <div class="agent-c${open ? " is-open" : ""}${agent.requiresApproval && !approved ? " needs-approval" : ""}">
        <button class="agent-c-head" type="button" data-agent-toggle="${escapeHtml(key)}">
          <span class="agent-pulse ${escapeHtml(statusClass)}" aria-hidden="true"></span>
          <span class="agent-name">${escapeHtml(agent.title)}</span>
          <span class="agent-status s-${escapeHtml(statusClass)}">${escapeHtml(statusLabel)}</span>
          <span class="agent-caret${open ? " is-open" : ""}">›</span>
        </button>
        <div class="agent-prog"><span class="agent-prog-bar tone-${escapeHtml(toneClass)}" style="width:${escapeHtml(String(agent.progress || 0))}%"></span></div>
        ${open ? `
          <div class="agent-c-body">
            <span class="agent-tag">${escapeHtml(agent.tag)}</span>
            <p class="agent-doing">${escapeHtml(agent.requiresApproval && approved ? "Approved — executing now. Audit entry is still visible from the executive surface only as a bounded cue." : agent.detail)}</p>
            <div class="agent-c-foot">
              <span class="agent-by">deployed by ${escapeHtml(agent.by)} · ${escapeHtml(agent.metric)}</span>
              <button class="agent-log-btn" type="button" data-agent-log="${escapeHtml(key)}">◷ audit log <span class="agent-log-count">${escapeHtml(String(agent.log.length))}</span></button>
            </div>
            ${agent.requiresApproval && !approved ? `
              <div class="agent-approve">
                <span class="agent-approve-note">⚠ Downstream approval remains governed. Use the real reviewer lane instead of a fake executive-side mutation.</span>
                <button class="agent-inline-button" type="button" data-agent-approve="${escapeHtml(key)}" data-agent-route="${escapeHtml(agent.route || "/reviewer/pending-reviews")}">Open governed approval lane</button>
              </div>
            ` : ""}
            ${logOpen ? `
              <ol class="agent-trail">
                ${agent.log.map((entry) => `
                  <li class="trail-item">
                    <span class="trail-time">${escapeHtml(entry.time)}</span>
                    <span class="trail-dot"></span>
                    <span class="trail-text">${escapeHtml(entry.text)}</span>
                  </li>
                `).join("")}
                <li class="trail-foot">Every action remains evidence-linked and in-tenant; this view is a parity cue, not a control plane.</li>
              </ol>
            ` : ""}
          </div>
        ` : ""}
      </div>
    `;
  }

  function discoverAgentCard(agent) {
    const key = slugifyToken(agent.key || agent.title);
    const deployed = Boolean(state.deployedAgentKeys[key]);
    return `
      <div class="discover-card">
        <div class="discover-card-body">
          <span class="discover-glyph" aria-hidden="true">${escapeHtml(agent.glyph || "✦")}</span>
          <div>
            <div class="discover-card-top">
              <div>
                <strong>${escapeHtml(agent.title)}</strong>
                <span class="discover-source ${escapeHtml(agent.sourceClass || "native")}">${escapeHtml(agent.source)}</span>
              </div>
              <span class="micro">${escapeHtml(agent.connector)}</span>
            </div>
            <p>${escapeHtml(agent.detail)}</p>
            <div class="discover-meta"><span>${escapeHtml(agent.meta)}</span></div>
          </div>
          <button class="discover-deploy${deployed ? " is-added" : ""}" type="button" data-agent-deploy="${escapeHtml(key)}" data-agent-route="${escapeHtml(agent.route || agent.connector || "/ingestion/connectors")}">${deployed ? "Open route" : "Open route"}</button>
        </div>
      </div>
    `;
  }

  function renderAgentsDiscovery(run, citations, challenged) {
    if (!els.agentsRunningList || !els.agentsNativeList) return;
    const publication = publicationContract();
    const persona = currentExecutivePersona();
    const queueCount = Array.isArray(state.pendingReviews?.items) ? state.pendingReviews.items.length : 0;
    const runningSource = Array.isArray(state.workspaceContract?.agents?.running) && state.workspaceContract.agents.running.length
      ? state.workspaceContract.agents.running
      : (DESIGN.runningAgents || []);
    const running = runningSource.map((agent) => ({
      key: agent.id,
      title: agent.name,
      status: agent.status,
      metric: `${agent.progress}%`,
      detail: agent.doing,
      tag: agent.tag,
      by: agent.by,
      progress: agent.progress,
      requiresApproval: agent.status === "approval",
      statusClass: agent.status,
      toneClass: agent.status === "approval" ? "down" : agent.status === "standing" ? "up" : "flat",
      log: (agent.log || []).map((item) => ({ time: item.t, text: item.a })),
    }));
    const discoverSurface = state.workspaceContract?.agents?.discover || {};
    const nativeSource = Array.isArray(discoverSurface.native) && discoverSurface.native.length
      ? discoverSurface.native
      : (DESIGN.discoverAgents || []).filter((item) => item.source === "native");
    const marketSource = Array.isArray(discoverSurface.marketplace) && discoverSurface.marketplace.length
      ? discoverSurface.marketplace
      : (DESIGN.discoverAgents || []).filter((item) => item.source === "market");
    const native = nativeSource.map((agent) => ({
      key: agent.id || agent.module_id,
      title: agent.name || agent.label,
      source: agent.by || agent.source || "StrategyOS",
      sourceClass: "native",
      glyph: agent.glyph || "◌",
      connector: agent.connector || agent.route,
      detail: agent.desc || agent.summary,
      meta: queueCount ? `${formatCount(queueCount)} review-aware surfaces visible` : (agent.meta || "Deploy on your data via platform connectors."),
    }));
    const market = marketSource.map((agent) => ({
      key: agent.id || agent.module_id,
      title: agent.name || agent.label,
      source: agent.by || agent.source || "Marketplace",
      sourceClass: "market",
      glyph: agent.glyph || "⚡",
      connector: agent.connector || agent.route,
      detail: agent.desc || agent.summary,
      meta: agent.meta || "Marketplace-style discovery only — deployment remains governed.",
    }));
    const subagentSource = Array.isArray(state.workspaceContract?.agents?.sub_agents) && state.workspaceContract.agents.sub_agents.length
      ? state.workspaceContract.agents.sub_agents
      : (DESIGN.subtools || []);
    const subagents = subagentSource.map((item) => ({ title: item.name || item.title, detail: item.desc || item.detail, metric: item.glyph || item.metric, tone: "ok" }));
    const discoverQuery = String(state.discoveryQuery || "").trim().toLowerCase();
    const discoverFilter = ["all", "native", "market"].includes(state.discoveryFilter) ? state.discoveryFilter : "all";
    const matchesDiscovery = (agent) => {
      if (!discoverQuery) return true;
      const haystack = [agent.title, agent.source, agent.connector, agent.detail, agent.meta]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(discoverQuery);
    };
    const filteredNative = discoverFilter === "market" ? [] : native.filter(matchesDiscovery);
    const filteredMarket = discoverFilter === "native" ? [] : market.filter(matchesDiscovery);
    if (!running.find((item) => slugifyToken(item.key || item.title) === state.openAgentKey)) {
      state.openAgentKey = slugifyToken((running.find((item) => item.requiresApproval)?.key || running[0]?.key || "reviewer_gate_relay"));
    }
    if (els.agentsSearchInput) {
      els.agentsSearchInput.value = state.discoveryQuery;
      els.agentsSearchInput.placeholder = persona.key === "board"
        ? "Search the board-safe agent universe…"
        : "Search the agent universe…";
    }
    if (els.agentsSearchNote) {
      const resultCount = filteredNative.length + filteredMarket.length;
      const noun = persona.key === "board" ? "board-safe agents" : "agents";
      els.agentsSearchNote.textContent = discoverQuery
        ? `${formatCount(resultCount)} ${noun} match “${state.discoveryQuery}”.`
        : (persona.key === "board"
            ? (discoverSurface.search_placeholder || "Search the board-safe agent universe…")
            : (discoverSurface.search_placeholder || "Search the agent universe…"));
    }
    if (els.agentsFilterRow) {
      const filters = [
        { key: "all", label: "All" },
        { key: "native", label: "Native" },
        { key: "market", label: "Marketplace" },
      ];
      els.agentsFilterRow.innerHTML = filters.map((item) => `
        <button class="discover-filter${discoverFilter === item.key ? " is-active" : ""}" type="button" data-agent-filter="${escapeHtml(item.key)}" role="tab" aria-selected="${discoverFilter === item.key ? "true" : "false"}">${escapeHtml(item.label)}</button>
      `).join("");
    }
    if (els.agentsBrowseButton) {
      els.agentsBrowseButton.textContent = persona.key === "board" ? "Browse all board-safe agents →" : "Browse all agents →";
      els.agentsBrowseButton.onclick = () => {
        const browseRoute = discoverSurface.deploy_route || "/ingestion/connectors";
        if (isAuthenticated()) {
          window.location.href = browseRoute;
          return;
        }
        setCommandPrompt(`Show the best next agent for ${currentExecutivePersona().label.toLowerCase()} inside the governed packet.`);
      };
    }
    els.agentsBadge.textContent = queueCount ? `${formatCount(queueCount)} review-aware` : (state.workspaceContract?.agents?.status || "bounded discovery");
    els.agentsActivityLine.textContent = state.workspaceContract?.agents?.activity?.line || DESIGN.activity?.line || `Agent activity: ${queueCount ? `${formatCount(queueCount)} review item(s) are waiting` : "the governed packet is stable"} · publication is ${publicationStatusLabel(publication.status || "draft")} · board pack ${humanizeToken(publication.board_pack?.status || "pending")}.`;
    els.agentsRunningBadge.textContent = `${formatCount(running.length)} active views`;
    if (els.agentsSovereignNote) {
      els.agentsSovereignNote.textContent = persona.key === "board"
        ? "Sovereign · board-safe only · every action remains in-tenant and evidence-linked."
        : "Sovereign · runs in-tenant · every action remains evidence-linked.";
    }
    els.agentsRunningList.innerHTML = running.map(runtimeAgentCard).join("");
    els.subagentList.innerHTML = subagents.map((item) => `
      <div class="subagent-card">
        <div class="subagent-card-top">
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <span>${escapeHtml(item.detail)}</span>
          </div>
          <span class="badge ${badgeTone(item.tone)}">${escapeHtml(item.metric)}</span>
        </div>
      </div>
    `).join("");
    els.agentsNativeList.innerHTML = filteredNative.length
      ? filteredNative.map(discoverAgentCard).join("")
      : `<div class="discover-empty-state">No native agents match this filter yet.</div>`;
    els.agentsMarketList.innerHTML = filteredMarket.length
      ? filteredMarket.map(discoverAgentCard).join("")
      : `<div class="discover-empty-state">No marketplace agents match this filter yet.</div>`;
    if (els.agentsSearchInput) {
      els.agentsSearchInput.oninput = () => {
        state.discoveryQuery = els.agentsSearchInput.value || "";
        syncExecutiveRouteState();
        renderAgentsDiscovery(run, citations, challenged);
      };
    }
    els.agentsFilterRow?.querySelectorAll("[data-agent-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        state.discoveryFilter = button.getAttribute("data-agent-filter") || "all";
        syncExecutiveRouteState();
        renderAgentsDiscovery(run, citations, challenged);
      });
    });
    els.agentsRunningList.querySelectorAll("[data-agent-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.getAttribute("data-agent-toggle") || "reviewer_gate_relay";
        state.openAgentKey = state.openAgentKey === key ? "" : key;
        syncExecutiveRouteState();
        renderAgentsDiscovery(run, citations, challenged);
      });
    });
    els.agentsRunningList.querySelectorAll("[data-agent-log]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const key = button.getAttribute("data-agent-log") || "reviewer_gate_relay";
        state.agentLogOpenKey = state.agentLogOpenKey === key ? null : key;
        renderAgentsDiscovery(run, citations, challenged);
      });
    });
    els.agentsRunningList.querySelectorAll("[data-agent-approve]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const key = button.getAttribute("data-agent-approve") || "reviewer_gate_relay";
        const route = button.getAttribute("data-agent-route") || "/reviewer/pending-reviews";
        state.approvedAgentKeys[key] = true;
        syncExecutiveRouteState();
        if (isAuthenticated()) {
          window.location.href = route;
          return;
        }
        setCommandPrompt(`Open the governed approval lane for ${key.replaceAll("_", " ")}.`);
        renderAgentsDiscovery(run, citations, challenged);
      });
    });
    [els.agentsNativeList, els.agentsMarketList].forEach((root) => {
      root?.querySelectorAll("[data-agent-deploy]").forEach((button) => {
        button.addEventListener("click", () => {
          const key = button.getAttribute("data-agent-deploy") || "agent";
          const route = button.getAttribute("data-agent-route") || "/ingestion/connectors";
          state.deployedAgentKeys[key] = true;
          syncExecutiveRouteState();
          if (isAuthenticated()) {
            window.location.href = route;
            return;
          }
          setCommandPrompt(`Open the governed deploy route for ${key.replaceAll("_", " ")}.`);
          renderAgentsDiscovery(run, citations, challenged);
        });
      });
    });
  }

  function renderExecutiveSignalFoundation() {
    const plan = state.workspaceContract?.plan_health || {};
    const root = state.workspaceContract?.domain_tree?.root || {};
    const strategy = strategySubstrate();
    const view = selectedStrategyView();
    const kpiRoot = strategy?.kpi_tree?.root || {};
    const domainNodes = filteredDomainNodes();
    const kpiNodes = strategyKpiNodes();
    const drivers = strategyValueDrivers();
    const reasoning = strategyReasoningItems();
    const publication = publicationContract();
    const boardPack = publication.board_pack || {};
    const publicationActions = publicationActionLabels(publication);
    const nextAction = publication.approval?.next_action || state.workspaceContract?.workflow?.next_action || strategy?.intent?.next_decision;
    const reportsRoute = publication.preview_route || state.workspaceContract?.reports?.preview_route || "/public/runs/latest/report-preview";
    const routes = [
      {
        title: "Board-safe preview",
        text: "Executive publication remains bounded to safe report preview and surfaced release posture.",
        amount: `${reportsRoute} · ${publicationStatusLabel(publication.status)}`,
        status: plan.badge || "preview",
      },
      {
        title: "Reviewer gate",
        text: "Release still depends on governed review queue state, not executive narration alone.",
        amount: state.workspaceContract?.lanes?.reviewer?.pending_reviews_route || "/reviewer/pending-reviews",
        status: "review",
      },
      {
        title: "Runtime lane",
        text: "Connector, graph, vector, and readiness truth remain protected in the tenant-admin / system lane.",
        amount: state.workspaceContract?.lanes?.tenant_admin?.primary_route || "/app?lane=system",
        status: "system",
      },
      {
        title: "Report posture",
        text: `${formatCount(publication.report_count ?? 0)} report surfaces · ${formatCount(publication.restricted_report_count ?? 0)} restricted · board pack ${humanizeToken(boardPack.status || "pending")} · ${publicationActions.join(", ") || "inspect publication boundary"}`,
        amount: `Approval ${approvalSummary(state.latestRun || {})} · ${publicationStatusLabel(publication.status)}`,
        status: publication.status || "draft",
      },
    ];
    if (els.domainSignalNote) {
      els.domainSignalNote.textContent = view?.summary || plan.boundary
        || "StrategyOS can now frame multi-domain finance signal, release posture, and report publication surfaces without claiming portfolio-wide strategic compilation.";
    }
    if (els.publicationBadge) {
      els.publicationBadge.textContent = view?.label || plan.badge || "release posture";
      els.publicationBadge.className = `badge ${badgeTone(view?.status === "needs_closure" || view?.status === "gated" ? "warn" : plan.tone)}`;
    }
    if (els.kpiTreeStatus) {
      els.kpiTreeStatus.textContent = view?.label || kpiRoot.label || plan.label || root.status || "Awaiting governed run";
    }
    if (els.kpiTreeNote) {
      els.kpiTreeNote.textContent = view?.summary || kpiRoot.summary || root.summary || plan.root_summary || "The latest governed run will populate cash recovery, evidence risk, report release, and runtime branches.";
    }
    if (els.domainBranchCount) {
      els.domainBranchCount.textContent = domainNodes.length ? `${formatCount(domainNodes.length)} branches` : "--";
    }
    if (els.domainBranchNote) {
      els.domainBranchNote.textContent = domainNodes.length
        ? `${domainNodes.map((node) => node.label).join(" · ")} are now exposed as bounded executive branches.`
        : "No domain branches are visible yet.";
    }
    if (els.publicationStatus) {
      els.publicationStatus.textContent = view?.metric || (plan.status === "release_posture_clear" ? `Preview available · ${humanizeToken(boardPack.status || "pending")}` : plan.label || "Protected until review");
    }
    if (els.publicationNote) {
      els.publicationNote.textContent = view?.summary || plan.summary || "Public-safe previews and protected artifacts will appear here when the latest run exposes them.";
    }
    if (els.publicationRoute) {
      els.publicationRoute.textContent = view?.route || reportsRoute;
    }
    if (els.publicationRouteNote) {
      els.publicationRouteNote.textContent = view
        ? `${view.label} stays bounded to this governed route; final release still depends on reviewer and operator controls.`
        : `Final release still depends on reviewer and operator runtime controls in the governed workspace. Next valid action: ${humanizeNextAction(nextAction)}.`;
    }
    if (els.domainTree) {
      els.domainTree.innerHTML = domainNodes.length
        ? domainNodes.map((node) => {
          const metricSummary = node.value_display || ((Array.isArray(node.metrics) ? node.metrics : [])
            .slice(0, 2)
            .map((metric) => `${metric.label}: ${metric.value_display}`)
            .join(" · "));
          return decisionCard(
            node.label || "Domain",
            `${node.detail || node.summary || ""}${metricSummary ? ` ${metricSummary}.` : ""}`.trim(),
            metricSummary || node.route || "--",
            node.status || "bounded",
          );
        }).join("")
        : decisionCard(
          "Awaiting bounded domain data",
          "Finance, evidence, release, and runtime posture will appear once the current governed workspace contract is available.",
          "--",
          "pending",
        );
    }
    if (els.publicationList) {
      els.publicationList.innerHTML = routes.map((item) => decisionCard(item.title, item.text, item.amount, item.status)).join("");
    }
    if (els.valueDriverList) {
      els.valueDriverList.innerHTML = drivers.length
        ? drivers.map((driver) => decisionCard(
          driver.label || "Value driver",
          `${driver.detail || ""}${driver.maps_to?.length ? ` Maps to ${driver.maps_to.join(" · ")}.` : ""}${driver.depends_on?.length ? ` Depends on ${driver.depends_on.join(" · ")}.` : ""}`.trim(),
          driver.metric || driver.owner_route || "--",
          driver.status || driver.tone || "bounded",
        )).join("")
        : decisionCard(
          "Awaiting value-driver map",
          "Value-driver mapping will appear once a governed packet exists.",
          "--",
          "pending",
        );
    }
    if (els.strategyIntentSummary) {
      const intent = strategy?.intent || {};
      const guardrail = Array.isArray(intent.guardrails) && intent.guardrails.length ? ` Guardrail: ${intent.guardrails[0]}` : "";
      els.strategyIntentSummary.textContent = `${view?.summary || intent.summary || strategy?.boundary || plan.boundary || "Strategy intent will appear here once the bounded substrate is loaded."}${guardrail}${view?.route ? ` Route: ${view.route}.` : ""}`;
    }
    if (els.intentReasoningList) {
      els.intentReasoningList.innerHTML = reasoning.length
        ? reasoning.map((item) => decisionCard(
          item.claim || "Bounded reasoning",
          `${item.rationale || ""}${item.guardrail ? ` Guardrail: ${item.guardrail}` : ""}`,
          item.recommended_route || (Array.isArray(item.evidence_basis) && item.evidence_basis.length ? item.evidence_basis.join(" · ") : "evidence"),
          item.status || "bounded",
        )).join("")
        : decisionCard(
          "Awaiting strategy reasoning",
          "Reasoning will stay empty until governed evidence exists.",
          "--",
          "pending",
        );
    }
    if (els.scopeNote) {
      els.scopeNote.textContent = view
        ? `Bounded ${view.label} framing inside the current governed tenant surface only. StrategyOS is not mutating cross-company backend context or compiling enterprise strategy.`
        : "Phase 1 truth boundary: the executive cockpit can switch framing inside the current governed tenant surface, but it does not yet mutate cross-company backend context.";
    }
    renderBoardPortalParity(view, publication, nextAction, domainNodes, drivers, reasoning);
  }

  function renderBoardPortalParity(view, publication, nextAction, domainNodes, drivers, reasoning) {
    if (!els.boardLifecycleList || !els.publishFlowList || !els.discoveryModuleList) return;
    const lifecycle = currentLifecycleMode();
    const approval = approvalSummary(state.latestRun || {});
    const boardPack = publication.board_pack || {};
    const queueCount = Array.isArray(state.pendingReviews?.items) ? state.pendingReviews.items.length : 0;
    const challenged = challengedSummary(state.latestRun || {}) || 0;
    const lifecycleRows = [
      {
        title: "Pre-board packet",
        text: `Board pack ${humanizeToken(boardPack.status || "pending")} · ${formatCount(challenged)} challenged case${challenged === 1 ? "" : "s"} still shape room readiness.`,
        amount: boardPack.preview_route || publication.preview_route || "/public/runs/latest/report-preview",
        tone: lifecycle.key === "pre" ? "review" : boardPack.status === "pending" ? "pending" : "bounded",
      },
      {
        title: "Live session posture",
        text: `Approval is ${humanizeToken(approval)} and ${formatCount(queueCount)} additional queue item${queueCount === 1 ? "" : "s"} remain behind the executive frame.`,
        amount: state.workspaceContract?.lanes?.reviewer?.pending_reviews_route || "/reviewer/pending-reviews",
        tone: lifecycle.key === "live" ? "public" : approval === "approved" ? "safe" : "human",
      },
      {
        title: "Closed meeting memory",
        text: `Published outputs stay bounded to ${formatCount(publication.report_count ?? 0)} surfaced report artifact${Number(publication.report_count ?? 0) === 1 ? "" : "s"} and the public-safe preview route.`,
        amount: publication.preview_route || "/public/runs/latest/report-preview",
        tone: lifecycle.key === "closed" ? "safe" : publication.status === "published" ? "safe" : "bounded",
      },
    ];
    const publishRows = [
      {
        title: "1. Reviewer gate",
        text: `Sign-off remains explicit. Approval is ${humanizeToken(publication.approval_status || approval || "pending")}.`,
        amount: state.workspaceContract?.lanes?.reviewer?.primary_route || "/app?lane=review#review",
        tone: publication.status === "awaiting_review" ? "human" : "bounded",
      },
      {
        title: "2. Operator release",
        text: `Resume and report shaping stay in the operator lane. Next valid move: ${humanizeNextAction(nextAction)}.`,
        amount: state.workspaceContract?.lanes?.operator?.primary_route || "/app?lane=operate",
        tone: publication.approval?.resumable ? "safe" : "review",
      },
      {
        title: "3. Board-pack route",
        text: `${formatCount(boardPack.report_count ?? publication.report_count ?? 0)} report surface${Number(boardPack.report_count ?? publication.report_count ?? 0) === 1 ? "" : "s"} · allowed board actions: ${publicationActionLabels({ allowed_actions: boardPack.allowed_actions || [] }).join(", ") || "View board pack preview"}.`,
        amount: boardPack.preview_route || publication.preview_route || "/public/runs/latest/report-preview",
        tone: boardPack.safe_for_board ? "public" : "pending",
      },
      {
        title: "4. Runtime truth",
        text: "Tenant-admin / system keeps connector, store, and readiness truth from leaking into the board surface.",
        amount: state.workspaceContract?.lanes?.tenant_admin?.primary_route || "/app?lane=system",
        tone: "system",
      },
    ];
    const moduleRows = (view ? [view] : []).concat(
      drivers.slice(0, 2).map((driver) => ({
        label: driver.label || "Discovery module",
        summary: driver.detail || "Awaiting module detail",
        metric: driver.metric || "--",
        route: driver.owner_route || publication.preview_route || "/executive",
        status: driver.status || driver.tone || "bounded",
      })),
      reasoning.slice(0, 1).map((item) => ({
        label: item.claim || "Reasoning guardrail",
        summary: item.guardrail || item.rationale || "Awaiting reasoning",
        metric: item.recommended_route || "evidence",
        route: item.recommended_route || publication.preview_route || "/executive",
        status: item.status || "bounded",
      }))
    );
    const fallbackModules = domainNodes.slice(0, 3).map((node) => ({
      label: node.label || "Discovery module",
      summary: node.summary || node.detail || "Awaiting module detail",
      metric: node.value_display || node.route || "--",
      route: node.route || publication.preview_route || "/executive",
      status: node.status || node.tone || "bounded",
    }));
    const discoveryRows = (moduleRows.length ? moduleRows : fallbackModules).slice(0, 4);

    els.boardLifecycleList.innerHTML = lifecycleRows.map((item) => decisionCard(item.title, item.text, item.amount, item.tone)).join("");
    els.publishFlowList.innerHTML = publishRows.map((item) => decisionCard(item.title, item.text, item.amount, item.tone)).join("");
    els.discoveryModuleList.innerHTML = discoveryRows.length
      ? discoveryRows.map((item) => decisionCard(item.label, item.summary, item.metric || item.route || "--", item.status)).join("")
      : decisionCard("Awaiting discovery modules", "Board portal modules will appear once the workspace contract exposes them.", "--", "pending");
  }

  function renderScopeRibbon() {
    const tenant = currentTenantContext();
    const companyOptions = contractCompanyOptions();
    const portfolioOptions = contractPortfolioOptions();
    const companyLabel = companyOptions.find((item) => item.option_id === state.selectedCompany)?.label
      || tenant.tenant_name
      || tenant.tenant_id
      || "Current company";
    if (els.companySwitcher) {
      if (companyOptions.length) {
        if (!companyOptions.find((item) => item.option_id === state.selectedCompany)) {
          state.selectedCompany = companyOptions[0]?.option_id || "current";
        }
        els.companySwitcher.innerHTML = companyOptions.map((item) => `<option value="${escapeHtml(item.option_id)}">${escapeHtml(item.label)}</option>`).join("");
        els.companySwitcher.value = state.selectedCompany;
      } else {
        els.companySwitcher.innerHTML = `<option value="current">${escapeHtml(companyLabel)}</option>`;
        els.companySwitcher.value = "current";
      }
    }
    if (els.portfolioSwitcher) {
      if (!portfolioOptions.find((item) => item.option_id === state.selectedPortfolio)) {
        state.selectedPortfolio = portfolioOptions[0]?.option_id || "all";
      }
      els.portfolioSwitcher.innerHTML = portfolioOptions.map((item) => `<option value="${escapeHtml(item.option_id)}">${escapeHtml(item.label)}</option>`).join("");
      els.portfolioSwitcher.value = state.selectedPortfolio;
    }
    if (els.scopeSummary) {
      const portfolioLabel = portfolioOptions.find((item) => item.option_id === state.selectedPortfolio)?.label || "All governed portfolios";
      els.scopeSummary.textContent = `${companyLabel} · ${portfolioLabel}`;
    }
    if (els.scopeBreadcrumb) {
      els.scopeBreadcrumb.textContent = state.selectedFindingId
        ? `${state.selectedFindingId} → evidence → reports`
        : "Overview → cases → evidence → reports";
    }
  }

  function renderExecutiveFooter() {
    if (!els.footerTime) return;
    const now = new Date();
    const time = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    els.footerTime.textContent = `refreshed today · ${time} · Riyadh`;
  }

  function reportArtifacts() {
    const fromDetail = state.runDetail?.summary_json?.artifacts;
    if (fromDetail && typeof fromDetail === "object") return fromDetail;
    const fromRun = state.latestRun?.artifacts;
    if (fromRun && typeof fromRun === "object") return fromRun;
    return {};
  }

  function domainSummaryRows() {
    const findings = findingsPayload();
    const buckets = [
      { key: "cash_recovery", label: "Cash recovery", test: (item) => Number(item?.recoverable_sar || 0) > 0 },
      { key: "vendor_controls", label: "Vendor controls", test: (item) => /vendor|contract|renewal/i.test(String(item?.pattern_type || "")) },
      { key: "evidence_risk", label: "Evidence risk", test: (item) => Boolean(item?.challenged) || Number(item?.citation_count || 0) === 0 },
      { key: "working_capital", label: "Working capital", test: (item) => /discount|credit|fx/i.test(String(item?.pattern_type || "")) },
    ];
    return buckets.map((bucket) => {
      const items = findings.filter(bucket.test);
      const recoverable = items.reduce((sum, item) => sum + (Number(item?.recoverable_sar) || 0), 0);
      return { key: bucket.key, label: bucket.label, count: items.length, recoverable, challenged: items.filter((item) => item?.challenged).length };
    }).filter((item) => item.count > 0);
  }

  function publicationSurfaceRows() {
    const report = state.publicReportPreview || {};
    const artifacts = reportArtifacts();
    const publication = publicationContract();
    const publicChoices = Array.isArray(report?.available_artifacts) && report.available_artifacts.length ? report.available_artifacts : report?.artifact_key ? [{ artifact_key: report.artifact_key, title: report.title || report.artifact_key }] : [];
    return [
      { title: "Public-safe preview", detail: `${publication.preview_route || "/public/runs/latest/report-preview"} · ${publicationStatusLabel(publication.status)}`, tone: publicChoices.length ? "public" : "pending" },
      { title: "Protected artifact lane", detail: isAuthenticated() ? `${formatCount(publication.report_count ?? Object.keys(artifacts).length)} report surfaces · ${formatCount(publication.restricted_report_count ?? 0)} restricted` : "Authenticate for restricted artifact bodies", tone: Object.keys(artifacts).length ? "review" : "pending" },
      { title: "Review app handoff", detail: `${state.latestRun?.requires_human_review ? "Approval gate visible" : "Human gate optional"} · /app#review`, tone: state.latestRun?.requires_human_review ? "human" : "safe" },
    ];
  }

  function renderExecutiveSignal(config) {
    const domains = domainSummaryRows();
    const publication = publicationSurfaceRows();
    const artifactCount = Object.keys(reportArtifacts()).length;
    els.kpiTreeStatus.textContent = domains.length ? `${formatCount(domains.length)} active finance branches` : config.status;
    els.kpiTreeNote.textContent = domains.length ? "Branches roll up only from governed finance findings, evidence chain, report release, and runtime posture." : "No domain branches are visible until a governed run exposes truthful finance signal.";
    els.domainBranchCount.textContent = domains.length ? formatCount(domains.length) : "--";
    els.domainBranchNote.textContent = domains.length ? `${domains.map((item) => item.label).join(" · ")}` : "No domain branches are visible yet.";
    els.domainSignalNote.textContent = "StrategyOS can now frame multi-domain finance signal, release posture, and report publication surfaces without claiming portfolio-wide strategic compilation.";
    els.publicationBadge.textContent = config.badge;
    els.publicationStatus.textContent = artifactCount ? `${formatCount(artifactCount)} protected artifact${artifactCount === 1 ? "" : "s"}` : config.status;
    els.publicationNote.textContent = artifactCount ? `Public-safe previews and protected artifacts are both visible. Approval is ${approvalSummary(state.latestRun || {})}.` : "Public-safe previews and protected artifacts will appear here when the latest run exposes them.";
    els.publicationRoute.textContent = isAuthenticated() ? "/reviewer/runs/{run_id}/artifacts/{artifact_key}" : "/public/runs/latest/report-preview";
    els.publicationRouteNote.textContent = isAuthenticated() ? "Executive remains read-only; restricted artifact opening still happens through reviewer-protected surfaces." : "Anonymous viewers remain on public-safe report previews only.";
    els.domainTree.innerHTML = domains.length ? domains.map((item) => decisionCard(`${item.label} branch`, `${formatCount(item.count)} cases with ${formatCount(item.challenged)} challenged and ${formatSarShort(item.recoverable)} recoverable signal.`, formatCount(item.count), item.challenged ? "human" : "safe")).join("") : decisionCard("Awaiting finance signal", "Run one governed analysis before showing multi-domain finance branches.", "--", "pending");
    els.publicationList.innerHTML = publication.map((item) => decisionCard(item.title, item.detail, "route", item.tone)).join("");
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
    if (els.planHealthSourceNote) els.planHealthSourceNote.textContent = config.sourceNote || "Executive KPI cards and plan health reconcile against the same governed run boundary.";
    els.planKpiValue.textContent = config.value;
    els.planKpiValueNote.textContent = config.valueNote;
    els.planKpiCases.textContent = config.cases;
    els.planKpiCasesNote.textContent = config.casesNote;
    els.planKpiEvidence.textContent = config.evidence;
    els.planKpiEvidenceNote.textContent = config.evidenceNote;
  }

  function executivePlanHealthConfig(fallback) {
    const plan = state.workspaceContract?.plan_health || {};
    const publication = publicationContract();
    if (!Object.keys(plan).length) return fallback;
    const actions = publicationActionLabels(publication).join(", ");
    return {
      ...fallback,
      badge: plan.badge || fallback.badge,
      status: plan.label || fallback.status,
      note: plan.summary || fallback.note,
      boundary: plan.boundary || fallback.boundary,
      sourceNote: plan.root_summary || fallback.sourceNote,
      evidenceNote: `${fallback.evidenceNote}${actions ? ` Allowed inspection: ${actions}.` : ""}`,
    };
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

  function currentNarrativePayload() {
    const run = state.latestRun || {};
    const findings = findingsPayload();
    const citations = normalizedCitationSummary(run, findings);
    const challenged = challengedSummary(run) || findings.filter((item) => item?.challenged).length;
    return { run, findings, citations, challenged };
  }

  function rerenderExecutiveNarrative() {
    const { run, citations, challenged } = currentNarrativePayload();
    renderExecutiveHero(run, citations, challenged);
    renderExecutiveSignalFoundation();
    renderBoardPortal(run, citations, challenged);
    renderAgentsDiscovery(run, citations, challenged);
    renderLowerRailFidelity(run, citations, challenged);
    renderAssistantNarrative(run, citations, challenged);
    renderScopeRibbon();
    renderExecutiveFooter();
  }

  function renderLocked() {
    displaySession();
    renderExecutiveModes();
    const run = state.latestRun || {};
    const findings = findingsPayload();
    const citations = normalizedCitationSummary(run, findings);
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
      renderPlanHealth(executivePlanHealthConfig({
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
        sourceNote: citations.detail,
      }));
      rerenderExecutiveNarrative();
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
    renderPlanHealth(executivePlanHealthConfig({
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
    }));
    rerenderExecutiveNarrative();
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
    renderExecutiveModes();
    const run = state.latestRun || {};
    const missing = !run || run.status === "missing";
    const citations = normalizedCitationSummary(run, findingsPayload());
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
      rerenderExecutiveNarrative();
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
    const boardPack = publicationContract().board_pack || {};
    const topReasoning = strategyReasoningItems()[0];
    els.memoBody.textContent = `The latest run identifies ${formatSar(recoverable)} recoverable value. Decision quality now depends on ${humanizeToken(boardPack.status || "pending")} board-pack readiness, ${formatCount(challenged || 0)} visible challenge event${Number(challenged || 0) === 1 ? "" : "s"}, and keeping reviewer/operator gates explicit.`;
    els.memoList.innerHTML = [
      `<div>Run: ${escapeHtml(run.run_id || "latest")}.</div>`,
      `<div>Evidence: ${escapeHtml(citationText)}.</div>`,
      `<div>Challenges: ${escapeHtml(formatCount(challenged || 0))} visible events.</div>`,
      `<div>Board pack: ${escapeHtml(humanizeToken(boardPack.status || "pending"))} via ${escapeHtml(boardPack.preview_route || publicationContract().preview_route || "/public/runs/latest/report-preview")}.</div>`,
      `<div>Guardrail: ${escapeHtml(topReasoning?.guardrail || "Publication remains governed across reviewer and operator controls.")}</div>`,
    ].join("");
    renderPlanHealth(executivePlanHealthConfig({
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
      sourceNote: citations.detail,
    }));
    rerenderExecutiveNarrative();
    renderCases(run, citations, challenged);
    renderReports();
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
    const contractArtifacts = Array.isArray(state.workspaceContract?.reports?.artifacts) ? state.workspaceContract.reports.artifacts : [];
    const publication = publicationContract();
    const normalizedArtifacts = contractArtifacts.length
      ? contractArtifacts.map((item) => ({
        artifact_key: item.artifact_key,
        title: item.title || reportLabel(item.artifact_key),
        subtitle: `${item.restricted ? "restricted" : "previewable"} · ${publicationStatusLabel(publication.status)}`,
      }))
      : Object.keys(artifacts).map((key) => ({
        artifact_key: key,
        title: reportLabel(key),
        subtitle: String(artifacts[key] || "").split("/").slice(-1)[0] || "Stored artifact",
      }));
    byId("exec-report-badge").textContent = normalizedArtifacts.length ? `${publicationStatusLabel(publication.status)} · ${normalizedArtifacts.length}` : "no artifacts";
    if (!normalizedArtifacts.length) {
      byId("exec-report-list").innerHTML = "";
      byId("exec-report-preview").textContent = "No latest-run report artifacts are available yet.";
      return;
    }
    byId("exec-report-list").innerHTML = normalizedArtifacts.map((item) => `
      <button class="report-button" type="button" data-artifact-key="${escapeHtml(item.artifact_key)}">
        <strong>${escapeHtml(item.title)}</strong>
        <span>${escapeHtml(item.subtitle)}</span>
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
        : await requestJson(viewStateRoute(`/public/runs/latest/report-preview?artifact_key=${encodeURIComponent(artifactKey)}`));
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
      state.workspaceContract = await guarded("Workspace contract", requestJson(viewStateRoute("/ui/workspace-contract/latest")), null);
      if (!isAuthenticated()) {
        const [publicRun, publicAuditSummary, publicFindings, publicReportPreview] = await Promise.all([
          guarded("Public latest run", requestJson(viewStateRoute("/public/runs/latest")), { status: "missing" }),
          guarded("Public audit summary", requestJson("/public/runs/latest/audit-summary"), { status: "missing", challenged_finding_ids: [] }),
          guarded("Public latest findings", requestJson(viewStateRoute("/public/runs/latest/findings")), { status: "missing", findings: [] }),
          guarded("Public report preview", requestJson(viewStateRoute("/public/runs/latest/report-preview")), { status: "missing" }),
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
        guarded("Latest run", requestJson(viewStateRoute("/runs/latest")), { status: "missing" }),
        guarded("Audit summary", requestJson("/runs/latest/audit-summary"), { status: "missing" }),
        guarded("Knowledge graph", requestJson("/runs/latest/knowledge-graph"), { status: "missing", nodes: [], edges: [], meta: {} }),
        guarded("Latest findings", requestJson(viewStateRoute("/runs/latest/findings")), { status: "missing", findings: [] }),
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
    syncExecutiveRouteState();
    refreshLiveData();
  });

  els.companySwitcher?.addEventListener("change", (event) => {
    state.selectedCompany = event.target.value || "current";
    syncExecutiveRouteState();
    refreshLiveData();
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

  document.addEventListener("click", (event) => {
    if (!state.personaMenuOpen) return;
    if (els.personaMenu?.contains(event.target) || els.personaButton?.contains(event.target)) return;
    state.personaMenuOpen = false;
    renderExecutiveModes();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !state.personaMenuOpen) return;
    state.personaMenuOpen = false;
    renderExecutiveModes();
  });

  refreshLiveData();
})();
