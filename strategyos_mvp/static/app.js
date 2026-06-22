(function () {
  "use strict";

  const bootstrap = JSON.parse(document.getElementById("strategyos-bootstrap").textContent);
  const TOKEN_KEY = "strategyos.ui.token";
  const QA_MODE_KEY = "strategyos.ui.qaMode";
  const STARTER_SUGGESTIONS = [
    "What is the total amount of invoices?",
    "How many AP invoices are there?",
    "What is the total amount of unpaid invoices?",
    "Top 5 vendors by spend",
    "How many distinct vendors are there?",
    "What is the total recoverable?",
    "Show recoverable by pattern",
    "How many findings by confidence?",
    "What are the working capital drift signals?",
  ];
  const DEFAULT_PIPELINE = [
    "ingest",
    "analyst",
    "auditor",
    "evidence_qa",
    "knowledge_graph",
    "awaiting_review",
    "writer",
  ];

  // Plain-language labels for internal identifiers a business user should never
  // see raw (fix-list item 7). Covers detector pattern_type values and the
  // internal pipeline stage names. Anything not present falls back to a
  // title-cased version of the snake_case token via humanizeToken().
  const PATTERN_LABELS = {
    duplicate_payment: "Duplicate payment",
    entity_resolution_duplicate: "Duplicate vendor identity",
    off_contract_single_approver: "Off-contract spend, single approver",
    price_variance: "Price variance vs PO",
    missed_early_pay_discount: "Missed early-payment discount",
    auto_renewal_escalation: "Auto-renewal escalation",
    fx_hedge_unapplied: "FX hedge not applied",
    dormant_credit_balance: "Dormant supplier credit",
    vendor_collusion_ring: "Vendor collusion ring",
  };
  const STAGE_LABELS = {
    ingest: "Data intake",
    analyst: "Analyst review",
    auditor: "Auditor challenge",
    evidence_qa: "Evidence check",
    knowledge_graph: "Relationship map",
    awaiting_review: "Awaiting sign-off",
    writer: "Final report",
  };

  function humanizeToken(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    return text
      .replace(/[_-]+/g, " ")
      .replace(/\s+/g, " ")
      .replace(/\b\w/g, (ch) => ch.toUpperCase());
  }

  function humanizePattern(value) {
    const key = String(value || "").trim().toLowerCase();
    if (!key) return "";
    return PATTERN_LABELS[key] || humanizeToken(key);
  }

  function humanizeStage(value) {
    const key = String(value || "").trim().toLowerCase();
    if (!key) return "";
    return STAGE_LABELS[key] || humanizeToken(key);
  }

  // Deterministic Q&A intent names (qa.py INTENTS) shown as a tag under each
  // answer. Keep these short and business-readable.
  const INTENT_LABELS = {
    working_capital: "Working capital",
    overdue: "Overdue / outstanding",
    recoverable: "Recoverable",
    findings: "Findings",
    top_parties: "Top vendors",
    distinct_parties: "Vendor count",
    named_party_spend: "Vendor spend",
    invoice_metric: "Invoice totals",
  };

  function humanizeIntent(value) {
    const key = String(value || "").trim().toLowerCase();
    if (!key) return "";
    return INTENT_LABELS[key] || humanizeToken(key);
  }

  function reportLabel(key) {
    return humanizeToken(key || "report");
  }

  const state = {
    token: window.localStorage.getItem(TOKEN_KEY) || "",
    session: null,
    latestRun: null,
    latestJob: null,
    auditSummary: null,
    dataStatus: null,
    knowledgeGraph: null,
    kgLoading: false,
    kgCy: null,
    kgSelectedId: "",
    liveStatus: null,
    readyStatus: null,
    configStatus: null,
    dependenciesStatus: null,
    connectorCatalog: null,
    workspaceContract: null,
    chatRunKey: "",
    chatThread: [],
    qaMode: window.sessionStorage.getItem(QA_MODE_KEY) || "deterministic",
    qaLoading: false,
    activeSuggestions: STARTER_SUGGESTIONS.slice(0, 3),
    openCitationKey: "",
    sourcePack: null,
    sourcePackSubmitting: false,
    runSubmitting: false,
    vectorSearch: { status: "idle", payload: null, error: "" },
    vectorEvidence: { status: "idle", payload: null, error: "" },
    findings: null,
    openFindingId: "",
    selectedFindingId: "",
    selectedDomain: "all",
    selectedCompany: "current",
    selectedPortfolio: "all",
    selectedReportKey: "",
    drilldownEvidence: { status: "idle", payload: null, error: "" },
    drilldownReport: { status: "idle", payload: null, error: "" },
    history: null,
    pollTimer: null,
    lastRunSignature: "",
    laneSignature: "",
  };

  const byId = (id) => document.getElementById(id);
  const els = {
    appName: byId("app-name"),
    workspaceSubtitle: byId("workspace-subtitle"),
    workspaceHeadline: byId("workspace-headline"),
    workspaceNote: byId("workspace-note"),
    roleLanePill: byId("role-lane-pill"),
    surfaceCardExecutive: byId("surface-card-executive"),
    surfaceCardReviewer: byId("surface-card-reviewer"),
    surfaceCardOperator: byId("surface-card-operator"),
    surfaceCardTenantAdmin: byId("surface-card-tenant-admin"),
    surfaceBadgeExecutive: byId("surface-badge-executive"),
    surfaceBadgeReviewer: byId("surface-badge-reviewer"),
    surfaceBadgeOperator: byId("surface-badge-operator"),
    surfaceBadgeTenantAdmin: byId("surface-badge-tenant-admin"),
    roleTaskTitle: byId("role-task-title"),
    roleTaskNote: byId("role-task-note"),
    roleTaskPill: byId("role-task-pill"),
    roleTaskList: byId("role-task-list"),
    scopeStatusPill: byId("scope-status-pill"),
    companySwitcher: byId("company-switcher"),
    portfolioSwitcher: byId("portfolio-switcher"),
    scopeSummary: byId("scope-summary"),
    scopeNote: byId("scope-note"),
    scopeChipRow: byId("scope-chip-row"),
    detailBreadcrumb: byId("detail-breadcrumb"),
    planHealthPill: byId("plan-health-pill"),
    planHealthStatus: byId("plan-health-status"),
    planHealthNote: byId("plan-health-note"),
    planHealthSourceNote: byId("plan-health-source-note"),
    planHealthKpiTree: byId("plan-health-kpi-tree"),
    publicationSurfaceSummary: byId("publication-surface-summary"),
    domainKpiGrid: byId("domain-kpi-grid"),
    planHealthTree: byId("plan-health-tree"),
    publicationSurfaceList: byId("publication-surface-list"),
    buSurfacePill: byId("bu-surface-pill"),
    buSurfaceNote: byId("bu-surface-note"),
    buSurfaceKpiGrid: byId("bu-surface-kpi-grid"),
    buWorkflowList: byId("bu-workflow-list"),
    buDomainFilters: byId("bu-domain-filters"),
    buCaseList: byId("bu-case-list"),
    reviewerSurfacePill: byId("reviewer-surface-pill"),
    reviewerSurfaceNote: byId("reviewer-surface-note"),
    reviewerQueueList: byId("reviewer-queue-list"),
    reviewerEvidenceQa: byId("reviewer-evidence-qa"),
    operatorSurfacePill: byId("operator-surface-pill"),
    operatorSurfaceNote: byId("operator-surface-note"),
    operatorIntakeGrid: byId("operator-intake-grid"),
    operatorWorkflowList: byId("operator-workflow-list"),
    systemSurfacePill: byId("system-surface-pill"),
    systemSurfaceNote: byId("system-surface-note"),
    systemPostureGrid: byId("system-posture-grid"),
    systemWorkflowCompact: byId("system-workflow-compact"),
    systemPublicationList: byId("system-publication-list"),
    systemSurfaceList: byId("system-surface-list"),
    drilldownStatusPill: byId("drilldown-status-pill"),
    drilldownCaseTitle: byId("drilldown-case-title"),
    drilldownCaseSummary: byId("drilldown-case-summary"),
    drilldownCaseKv: byId("drilldown-case-kv"),
    drilldownEvidenceTitle: byId("drilldown-evidence-title"),
    drilldownEvidenceSummary: byId("drilldown-evidence-summary"),
    drilldownEvidencePreview: byId("drilldown-evidence-preview"),
    drilldownReportTitle: byId("drilldown-report-title"),
    drilldownReportSummary: byId("drilldown-report-summary"),
    drilldownReportList: byId("drilldown-report-list"),
    drilldownReportPreview: byId("drilldown-report-preview"),
    runPill: byId("run-pill"),
    identity: byId("ui-identity"),
    environmentBadge: byId("environment-badge"),
    signInPanel: byId("sign-in-panel"),
    sessionToken: byId("session-token"),
    sessionStatus: byId("session-status"),
    sessionHelp: byId("session-help"),
    connectButton: byId("connect-button"),
    clearButton: byId("clear-button"),
    kpiRecoverable: byId("kpi-recoverable"),
    kpiFindings: byId("kpi-findings"),
    kpiCitations: byId("kpi-citations"),
    kpiChallenged: byId("kpi-challenged"),
    stageStepper: byId("stage-stepper"),
    storeBadges: byId("store-badges"),
    partialRunChips: byId("partial-run-chips"),
    chatThread: byId("chat-thread"),
    chatMessages: byId("chat-messages"),
    chatForm: byId("chat-form"),
    chatInput: byId("chat-input"),
    chatSend: byId("chat-send"),
    chatSuggestions: byId("chat-suggestions"),
    qaModeSwitch: byId("qa-mode-switch"),
    qaModeStatus: byId("qa-mode-status"),
    reviewMessage: byId("review-message"),
    reviewTitle: byId("review-title"),
    reviewDetail: byId("review-detail"),
    reviewComment: byId("review-comment"),
    reviewApprove: byId("review-approve"),
    reviewReject: byId("review-reject"),
    reviewResume: byId("review-resume"),
    reviewNewRun: byId("review-new-run"),
    newRunButton: byId("new-run-button"),
    newRunDrawer: byId("new-run-drawer"),
    sourcePackUploadForm: byId("source-pack-upload-form"),
    sourcePackFiles: byId("source-pack-files"),
    sourcePackFolderFiles: byId("source-pack-folder-files"),
    sourcePackUploadSubmit: byId("source-pack-upload-submit"),
    sourcePackPathForm: byId("source-pack-path-form"),
    sourcePackPath: byId("source-pack-path"),
    sourcePackPathSubmit: byId("source-pack-path-submit"),
    sourcePackValidate: byId("source-pack-validate"),
    sourcePackStatus: byId("source-pack-status"),
    sourcePackSummary: byId("source-pack-summary"),
    sourcePackManifestBody: byId("source-pack-manifest-body"),
    sourcePackMappings: byId("source-pack-mappings"),
    sourcePackReadiness: byId("source-pack-readiness"),
    startRunForm: byId("start-run-form"),
    startRunDataset: byId("start-run-dataset"),
    startRunRunDir: byId("start-run-run-dir"),
    startRunSkipPrepare: byId("start-run-skip-prepare"),
    startRunSyncArtifacts: byId("start-run-sync-artifacts"),
    startRunAllowPartialSourcePack: byId("start-run-allow-partial-source-pack"),
    startRunSubmit: byId("start-run-submit"),
    startRunCancel: byId("start-run-cancel"),
    startRunStatus: byId("start-run-status"),
    systemDrawerButton: byId("system-drawer-button"),
    systemDrawer: byId("system-drawer"),
    systemDrawerClose: byId("system-drawer-close"),
    adminContextSummary: byId("admin-context-summary"),
    adminContextKv: byId("admin-context-kv"),
    adminCapabilitiesKv: byId("admin-capabilities-kv"),
    adminContextPayloadPreview: byId("admin-context-payload-preview"),
    systemWorkflowSummary: byId("system-workflow-summary"),
    systemWorkflowList: byId("system-workflow-list"),
    systemWorkflowPayloadPreview: byId("system-workflow-payload-preview"),
    connectorsSummary: byId("connectors-summary"),
    connectorsList: byId("connectors-list"),
    connectorsPayloadPreview: byId("connectors-payload-preview"),
    dataSummary: byId("data-summary"),
    dataCountsKv: byId("data-counts-kv"),
    dataSystemsKv: byId("data-systems-kv"),
    dataPayloadPreview: byId("data-payload-preview"),
    kgSummary: byId("kg-summary"),
    kgGraph: byId("kg-graph"),
    kgDetail: byId("kg-detail"),
    kgRefresh: byId("kg-refresh"),
    vectorSearchForm: byId("vector-search-form"),
    vectorSearchQuery: byId("vector-search-query"),
    vectorSearchType: byId("vector-search-type"),
    vectorSearchPattern: byId("vector-search-pattern"),
    vectorSearchVendor: byId("vector-search-vendor"),
    vectorSearchConfidence: byId("vector-search-confidence"),
    vectorSearchSource: byId("vector-search-source"),
    vectorSearchFinding: byId("vector-search-finding"),
    vectorSearchLimit: byId("vector-search-limit"),
    vectorSearchResults: byId("vector-search-results"),
    vectorSearchEvidencePreview: byId("vector-search-evidence-preview"),
    vectorSearchPayloadPreview: byId("vector-search-payload-preview"),
    artifactTabs: byId("artifact-tabs"),
    artifactViewer: byId("artifact-viewer"),
    healthSummary: byId("health-summary"),
    healthChecksKv: byId("health-checks-kv"),
    healthConfigKv: byId("health-config-kv"),
    healthPayloadPreview: byId("health-payload-preview"),
    findingsPanel: byId("findings-panel"),
    findingsTotal: byId("findings-total"),
    findingsSummary: byId("findings-summary"),
    findingsList: byId("findings-list"),
    findingDrawer: byId("finding-drawer"),
    findingDrawerClose: byId("finding-drawer-close"),
    findingDetailEyebrow: byId("finding-detail-eyebrow"),
    findingDetailTitle: byId("finding-detail-title"),
    findingDetailKv: byId("finding-detail-kv"),
    findingDetailExplainer: byId("finding-detail-explainer"),
    findingDetailCitations: byId("finding-detail-citations"),
    findingDetailGraph: byId("finding-detail-graph"),
    findingDetailChallenge: byId("finding-detail-challenge"),
    trendStrip: byId("trend-strip"),
    trendRead: byId("trend-read"),
    trendBars: byId("trend-bars"),
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function compactJson(value) {
    return JSON.stringify(value ?? {}, null, 2);
  }

  function sanitizeUiPayload(value, key = "") {
    if (Array.isArray(value)) return value.map((item) => sanitizeUiPayload(item, key));
    if (value && typeof value === "object") {
      return Object.fromEntries(Object.entries(value).map(([entryKey, entryValue]) => [
        entryKey,
        sanitizeUiPayload(entryValue, entryKey),
      ]));
    }
    if (typeof value !== "string") return value;
    const lowerKey = String(key || "").toLowerCase();
    const lowerValue = value.toLowerCase();
    if (["issuer", "token_url", "introspection_url"].includes(lowerKey)) {
      return "internal identity boundary";
    }
    if (
      lowerValue.includes("localhost")
      || lowerValue.includes("127.0.0.1")
      || lowerValue.includes("strategyos-idp")
      || lowerValue.includes("postgres:")
      || lowerValue.includes("neo4j:")
      || lowerValue.includes("redis:")
      || lowerValue.includes("qdrant:")
      || lowerValue.includes("minio:")
    ) {
      return "internal service";
    }
    return value;
  }

  function basename(path) {
    const raw = String(path || "");
    if (!raw) return "source";
    return raw.split(/[\\/]/).filter(Boolean).pop() || raw;
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

  function formatValue(value, unit) {
    if (value === null || value === undefined) return "";
    if (Array.isArray(value) || typeof value === "object") return "";
    const label = unit === "SAR" ? formatSar(value) : formatCount(value);
    return unit && unit !== "SAR" ? `${label} ${escapeHtml(unit)}` : label;
  }

  function statusTone(status) {
    const normalized = String(status || "").toLowerCase();
    if (normalized === "danger") return "danger";
    if (normalized === "warn") return "warn";
    if (normalized === "neutral") return "neutral";
    if (["ok", "ready", "synced", "persisted", "completed", "approved", "not_required", "pass", "supported"].includes(normalized)) return "ok";
    if (["failed", "error", "rejected", "missing"].includes(normalized)) return "danger";
    if (["skipped", "degraded", "awaiting_review", "pending", "running", "unsupported", "partial", "blocked"].includes(normalized)) return "warn";
    if (["empty", "no_data", "not_started"].includes(normalized)) return "neutral";
    return "neutral";
  }

  function statusPill(status, label) {
    const text = label || String(status || "unknown").replaceAll("_", " ");
    return `<span class="pill ${statusTone(status)}">${escapeHtml(text)}</span>`;
  }

  function llmChatStatus() {
    return bootstrap.qa_modes?.llm || { enabled: false, reason: "LLM chat is not configured." };
  }

  function llmChatEnabled() {
    return Boolean(llmChatStatus().enabled);
  }

  function setQaMode(mode) {
    const normalized = mode === "llm" ? "llm" : "deterministic";
    state.qaMode = normalized === "llm" && !llmChatEnabled() ? "deterministic" : normalized;
    window.sessionStorage.setItem(QA_MODE_KEY, state.qaMode);
    renderQaMode();
  }

  function renderQaMode() {
    if (!els.qaModeSwitch) return;
    const llmStatus = llmChatStatus();
    els.qaModeSwitch.querySelectorAll("[data-qa-mode]").forEach((button) => {
      const mode = button.dataset.qaMode;
      const active = mode === state.qaMode;
      button.classList.toggle("active", active);
      button.disabled = mode === "llm" && !llmStatus.enabled;
      button.setAttribute("aria-pressed", active ? "true" : "false");
      if (mode === "llm" && !llmStatus.enabled) {
        button.title = llmStatus.reason || "LLM chat is not configured.";
      } else {
        button.title = "";
      }
    });
    if (els.qaModeStatus) {
      els.qaModeStatus.textContent = state.qaMode === "llm"
        ? `LLM: ${llmStatus.model || "configured"}`
        : "Cited deterministic answers";
    }
  }

  function numericValue(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function sourcePackBlockingReasons(payload) {
    const reasons = payload?.task_readiness?.blocking_reasons || [];
    return Array.isArray(reasons) ? reasons.map((item) => String(item)).filter(Boolean) : [];
  }

  function sourcePackSupportedCount(payload) {
    const summary = payload?.manifest_summary || {};
    return numericValue(summary.supported_file_count ?? summary.supported_count) ?? 0;
  }

  function sourcePackHasNoReadableFiles(payload) {
    if (!payload) return false;
    const readiness = payload.task_readiness || {};
    const reasons = sourcePackBlockingReasons(payload).join(" ").toLowerCase();
    return sourcePackSupportedCount(payload) <= 0
      || readiness.classification_status === "empty"
      || reasons.includes("no supported files");
  }

  function runHasNoReadableFiles(run) {
    const readiness = run?.source_pack?.task_readiness || {};
    const reasons = Array.isArray(readiness.blocking_reasons)
      ? readiness.blocking_reasons.join(" ").toLowerCase()
      : "";
    return readiness.classification_status === "empty"
      || reasons.includes("no supported files");
  }

  function storeStatusMeta(name, payload) {
    const rawStatus = String(payload?.status || "unknown").toLowerCase();
    const reason = String(payload?.reason || payload?.detail || "");
    const pointCount = numericValue(payload?.point_count);
    const nodeCount = numericValue(payload?.node_count);
    const edgeCount = numericValue(payload?.edge_count);
    const labels = {
      postgres: "Data saved",
      neo4j: "Graph",
      qdrant: "Search index",
    };

    if (name === "qdrant" && (
      rawStatus === "empty"
      || (rawStatus === "missing" && (pointCount === 0 || reason.toLowerCase().includes("no findings")))
    )) {
      return {
        status: "empty",
        label: "No vector data yet",
        reason: reason || "The search index is empty because this run has no findings to index.",
      };
    }

    if (name === "neo4j" && (
      rawStatus === "empty"
      || (rawStatus === "missing" && nodeCount === 0 && edgeCount === 0)
    )) {
      return {
        status: "empty",
        label: "Graph empty",
        reason: reason || "The graph is empty because this run has no nodes or relationships yet.",
      };
    }

    if (name === "postgres" && ["ok", "ready", "synced", "persisted"].includes(rawStatus)) {
      return { status: "ok", label: labels.postgres, reason };
    }

    return {
      status: rawStatus,
      label: `${labels[name] || name} ${rawStatus.replaceAll("_", " ")}`,
      reason,
    };
  }

  function authHeaders() {
    if (!state.token) return {};
    if (bootstrap.idp_enabled || state.token.startsWith("eyJ") || state.token.includes(".")) {
      return { Authorization: `Bearer ${state.token}` };
    }
    return { "X-API-Key": state.token };
  }

  async function requestJson(url, options = {}) {
    const headers = {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {}),
    };
    const response = await fetch(url, { ...options, headers });
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
      const error = new Error(payload.detail || payload.reason || `Request failed: ${response.status}`);
      error.status = response.status;
      error.payload = payload;
      if (response.status === 401) showSignIn("Authentication required.");
      throw error;
    }
    return payload;
  }

  async function requestMultipart(url, formData) {
    const response = await fetch(url, {
      method: "POST",
      headers: authHeaders(),
      body: formData,
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
      const error = new Error(payload.detail || payload.reason || `Request failed: ${response.status}`);
      error.status = response.status;
      error.payload = payload;
      if (response.status === 401) showSignIn("Authentication required.");
      throw error;
    }
    return payload;
  }

  function isAuthed() {
    return !bootstrap.api_auth_enabled || Boolean(state.session?.authenticated);
  }

  function currentRole() {
    return String(state.session?.role || "anonymous").toLowerCase();
  }

  function roleHasAny(role, ...targets) {
    const normalized = String(role || "anonymous").toLowerCase();
    const implied = {
      anonymous: ["anonymous"],
      public: ["public", "anonymous"],
      bu: ["bu"],
      operator: ["operator"],
      reviewer: ["reviewer"],
      analyst: ["analyst"],
      auditor: ["auditor", "reviewer"],
      executive: ["executive"],
      tenant_operator: ["tenant_operator", "operator", "analyst"],
      tenant_admin: ["tenant_admin", "tenant_operator", "operator", "reviewer", "analyst", "auditor", "executive"],
      system: ["system", "tenant_admin", "tenant_operator", "operator", "reviewer", "analyst", "auditor", "executive"],
    };
    const set = new Set(implied[normalized] || [normalized]);
    return targets.some((target) => set.has(String(target || "").toLowerCase()));
  }

  function preferredLaneForRole(role) {
    if (roleHasAny(role, "system", "tenant_admin")) return "system";
    if (roleHasAny(role, "bu")) return "review";
    if (roleHasAny(role, "reviewer")) return "review";
    if (roleHasAny(role, "operator")) return "operate";
    if (roleHasAny(role, "executive")) return "executive";
    return "public";
  }

  function requestedLane() {
    const params = new URLSearchParams(window.location.search);
    return String(params.get("lane") || "").trim().toLowerCase();
  }

  function isAuthDisabled() {
    return Boolean(state.session?.auth_disabled) || !bootstrap.api_auth_enabled;
  }

  function isOperator() {
    return isAuthDisabled() || roleHasAny(currentRole(), "operator");
  }

  function isReviewer() {
    return isAuthDisabled() || roleHasAny(currentRole(), "reviewer");
  }

  function activeRunId() {
    const runId = state.latestRun?.run_id;
    return runId ? String(runId) : null;
  }

  function isLocalRunId(runId) {
    return String(runId || "").startsWith("local-");
  }

  function activeRunKey() {
    const run = state.latestRun || {};
    return String(run.run_id || run.run_dir || run.dataset || "latest");
  }

  function displayRunId(run) {
    if (!run || run.status === "missing") return "no run";
    if (run.job_id) return `job ${String(run.job_id).slice(0, 8)}`;
    if (run.run_id) return String(run.run_id);
    if (run.run_dir) return basename(run.run_dir);
    return "latest";
  }

  function formatRoleLabel(role) {
    const normalized = String(role || "").trim().toLowerCase();
    const labels = {
      bu: "BU leader",
      operator: "Operator",
      reviewer: "Reviewer",
      analyst: "Analyst",
      auditor: "Auditor",
      executive: "Executive",
      tenant_operator: "Tenant operator",
      tenant_admin: "Tenant admin",
      system: "System",
      anonymous: "Anonymous",
      public: "Public",
    };
    return labels[normalized] || normalized.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase()) || "Unknown";
  }

  function formatCapabilityLabel(key) {
    const labels = {
      can_view_overview: "Overview",
      can_view_cases: "Cases",
      can_investigate_evidence: "Evidence",
      can_review: "Review control",
      can_launch_runs: "Run launch",
      can_manage_ingestion: "Ingestion",
    };
    return labels[String(key || "")] || humanizeToken(key);
  }

  function formatSubjectLabel(subject, role) {
    let raw = String(subject || "").trim();
    if (!raw || raw === "anonymous") return "Anonymous";
    if (raw === "auth-disabled") return "Auth disabled";
    if (raw.startsWith("api-key:")) return `${formatRoleLabel(role)} API key`;
    if (raw.includes("://")) raw = raw.split(":").pop() || raw;
    if (raw.endsWith(".local")) raw = raw.slice(0, -".local".length);
    const compact = raw.replaceAll("_", " ").replaceAll(".", " ").trim();
    return compact.replace(/\b\w/g, (char) => char.toUpperCase()) || formatRoleLabel(role);
  }

  function formatSessionIdentity(session) {
    const role = String(session?.role || "anonymous");
    if (session?.display_name) return String(session.display_name);
    if (["bu", "operator", "reviewer"].includes(role.toLowerCase())) return formatRoleLabel(role);
    return formatSubjectLabel(session?.subject, role);
  }

  function currentTenantContext() {
    return state.session?.tenant_context || state.workspaceContract?.tenant_context || {};
  }

  function availableCompanyOptions() {
    const switcher = state.workspaceContract?.company_switcher || state.session?.company_switcher || {};
    const options = Array.isArray(switcher.options) ? switcher.options : [];
    if (options.length) {
      return options.map((item) => ({
        value: String(item.option_id || item.value || "current"),
        label: String(item.label || item.option_name || item.option_id || "Current company"),
        detail: String(item.route || item.detail || ""),
      }));
    }
    const tenant = currentTenantContext();
    const tenantName = tenant.tenant_name || tenant.tenant_id || "Current company";
    const tenantId = tenant.tenant_id || "current";
    return [{ value: "current", label: tenantName, detail: tenantId }];
  }

  function availablePortfolioOptions() {
    const switcher = state.workspaceContract?.portfolio_switcher || state.session?.portfolio_switcher || {};
    const switcherOptions = Array.isArray(switcher.options) ? switcher.options : [];
    const options = switcherOptions.length
      ? switcherOptions.map((item) => ({ value: String(item.option_id || item.value || "all"), label: String(item.label || item.option_name || item.option_id || "Portfolio") }))
      : [{ value: "all", label: "All governed portfolios" }];
    const run = state.latestRun || {};
    const findings = Array.isArray(state.findings?.findings) ? state.findings.findings : [];
    if (findings.length || run.total_recoverable_sar !== undefined) {
      options.push({ value: "finance", label: "Finance diagnostics" });
    }
    if (findings.some((item) => item?.challenged || Number(item?.citation_count || 0) === 0)) {
      options.push({ value: "evidence", label: "Evidence risk" });
    }
    if (Object.keys(state.latestRun?.artifacts || {}).length || Array.isArray(state.workspaceContract?.reports?.artifacts)) {
      options.push({ value: "reports", label: "Release posture" });
    }
    if (state.readyStatus || state.dataStatus) {
      options.push({ value: "runtime", label: "Runtime posture" });
    }
    return options;
  }

  function reportArtifactsFromContract() {
    return Array.isArray(state.workspaceContract?.reports?.artifacts) ? state.workspaceContract.reports.artifacts : [];
  }

  function numericOrNull(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function sumFindingCitations(rows) {
    const findings = Array.isArray(rows) ? rows : currentScopeFindings();
    return findings.reduce((sum, item) => sum + (Number(item?.citation_count || 0) || 0), 0);
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
    let detail = "Citation posture loads after a governed run surfaces evidence.";
    if (total !== null && mismatch) {
      detail = `Audit summary shows ${formatCount(rawResolved ?? resolved ?? 0)} resolved of ${formatCount(rawCount)} surfaced citations; current finding rows expose ${formatCount(findingLinked)} linked cites.`;
    } else if (total !== null) {
      detail = `Citation chain reconciles across the current audit summary and governed finding rows at ${formatCount(resolved ?? 0)} / ${formatCount(total)}.`;
    } else if (findingLinked > 0) {
      detail = `${formatCount(findingLinked)} finding-linked citations are visible while richer audit detail is still loading.`;
    }
    return {
      count: total,
      resolved,
      findingLinked,
      mismatch,
      detail,
    };
  }

  function publicationContract() {
    return state.workspaceContract?.reports?.publication || state.dataStatus?.publication || {};
  }

  function publicationStatusTone(status) {
    const normalized = String(status || "draft").toLowerCase();
    if (["published", "approved_for_release"].includes(normalized)) return "ok";
    if (["awaiting_review", "blocked"].includes(normalized)) return "warn";
    return "neutral";
  }

  function publicationStatusLabel(status) {
    return {
      published: "Published",
      approved_for_release: "Approved for release",
      awaiting_review: "Awaiting review",
      blocked: "Blocked",
      draft: "Draft",
    }[String(status || "draft").toLowerCase()] || humanizeToken(status || "draft");
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
    return (Array.isArray(publication?.allowed_actions) ? publication.allowed_actions : []).map((action) => mapping[action] || humanizeToken(action));
  }

  function publicationSurfaceItems() {
    const contract = state.workspaceContract || {};
    const surfaces = Array.isArray(contract.surfaces) ? contract.surfaces : [];
    const reportsSurface = surfaces.find((item) => item.surface_id === "reports") || {};
    const evidenceSurface = surfaces.find((item) => item.surface_id === "evidence") || {};
    const workflowSurface = surfaces.find((item) => item.surface_id === "workflow") || {};
    const artifacts = reportArtifactsFromContract();
    const publication = publicationContract();
    const approval = humanizeToken(publication.approval_status || state.latestRun?.approval_status || "pending");
    const statusLabel = publicationStatusLabel(publication.status);
    const actionLabels = publicationActionLabels(publication);
    return [
      {
        title: "Public preview",
        detail: `${publication.preview_route || reportsSurface.public_route || contract.reports?.preview_route || "/public/runs/latest/report-preview"} · ${statusLabel}`,
        tone: publication.has_public_preview ? "ok" : "neutral",
      },
      {
        title: "Governed reports",
        detail: `${formatCount(publication.report_count ?? artifacts.length)} reports · ${formatCount(publication.restricted_report_count ?? 0)} restricted · approval ${approval}`,
        tone: publicationStatusTone(publication.status),
      },
      {
        title: "Evidence handoff",
        detail: `${evidenceSurface.primary_route || contract.evidence?.preview_route || "/data/evidence-preview"} · ${formatCount(publication.evidence_count ?? contract.evidence?.count ?? 0)} evidence artifacts`,
        tone: contract.evidence?.count ? "ok" : "neutral",
      },
      {
        title: "Next valid action",
        detail: actionLabels.length ? actionLabels.join(" → ") : (workflowSurface.primary_route || "Workflow route not exposed"),
        tone: workflowSurface.permitted ? "ok" : publicationStatusTone(publication.status),
      },
    ];
  }

  function domainSummaryRows() {
    const findings = Array.isArray(state.findings?.findings) ? state.findings.findings : [];
    const domains = ["cash_recovery", "vendor_controls", "working_capital", "evidence_risk"];
    return domains.map((domain) => {
      const rows = findings.filter((item) => domainKeyForFinding(item) === domain);
      const recoverable = rows.reduce((sum, item) => sum + (Number(item?.recoverable_sar) || 0), 0);
      const challenged = rows.filter((item) => item?.challenged).length;
      const cited = rows.reduce((sum, item) => sum + (Number(item?.citation_count) || 0), 0);
      return { domain, label: domainLabel(domain), count: rows.length, recoverable, challenged, cited };
    }).filter((item) => item.count > 0);
  }

  function boundedPlanHealthModel() {
    const run = state.latestRun || {};
    const findings = currentScopeFindings();
    const citations = normalizedCitationSummary(run, findings);
    const publication = publicationContract();
    const approval = runApprovalStatus(run) || "pending";
    const challenged = challengedSummary(run) || 0;
    const domains = domainSummaryRows();
    const reports = reportArtifactsFromContract();
    const ready = state.readyStatus?.status || "unknown";
    const publicPreview = publication.preview_route || "/public/runs/latest/report-preview";
    let status = "Awaiting governed run";
    let tone = "warn";
    if (activeRunId()) {
      if (challenged > 0 || ["pending", "awaiting_review", "rejected"].includes(String(approval).toLowerCase())) {
        status = "Human gate visible";
      } else if (reports.length && String(ready).toLowerCase() === "ok") {
        status = "Release posture aligned";
        tone = "ok";
      } else {
        status = "Finance signal available";
        tone = "neutral";
      }
    }
    return {
      status,
      tone,
      note: !activeRunId() ? "Load a governed run to populate finance, evidence, release, and runtime branches." : challenged > 0 ? `${formatCount(challenged)} challenged case${challenged === 1 ? " is" : "s are"} keeping plan health bounded by evidence closure.` : `${formatCount(findings.length)} governed case${findings.length === 1 ? " is" : "s are"} informing the current tenant signal while publication stays ${publicationStatusLabel(publication.status).toLowerCase()}.`,
      treeLabel: domains.length ? `${formatCount(domains.length)} domain branch${domains.length === 1 ? "" : "es"}` : "No domain branches yet",
      publicationSummary: `${publicationStatusLabel(publication.status)} · ${formatCount(publication.report_count ?? reports.length)} report surface${Number(publication.report_count ?? reports.length) === 1 ? "" : "s"} · preview at ${publicPreview}`,
      domains,
      approval,
      ready,
      citations,
      publication,
    };
  }

  function domainKeyForFinding(finding) {
    const pattern = String(finding?.pattern_type || "").toLowerCase();
    if (finding?.challenged || Number(finding?.citation_count || 0) === 0) return "evidence_risk";
    if (pattern.includes("vendor") || pattern.includes("contract") || pattern.includes("renewal")) return "vendor_controls";
    if (pattern.includes("discount") || pattern.includes("credit") || pattern.includes("fx")) return "working_capital";
    return "cash_recovery";
  }

  function domainLabel(domain) {
    return {
      all: "All domains",
      cash_recovery: "Cash recovery",
      vendor_controls: "Vendor controls",
      working_capital: "Working capital",
      evidence_risk: "Evidence risk",
    }[domain] || humanizeToken(domain);
  }

  function currentScopeFindings() {
    const findings = Array.isArray(state.findings?.findings) ? state.findings.findings : [];
    return findings.filter((finding) => {
      const domain = domainKeyForFinding(finding);
      if (state.selectedDomain !== "all" && domain !== state.selectedDomain) return false;
      if (state.selectedPortfolio === "finance" && !["cash_recovery", "working_capital", "vendor_controls"].includes(domain)) return false;
      if (state.selectedPortfolio === "evidence" && domain !== "evidence_risk") return false;
      if (state.selectedPortfolio === "reports" && finding?.challenged) return false;
      return true;
    });
  }

  function activeFindingRecord() {
    const rows = currentScopeFindings();
    return rows.find((item) => String(item.finding_id) === String(state.selectedFindingId)) || rows[0] || null;
  }

  function metricCard(label, value, detail, tone) {
    return `<article class="mini-kpi ${tone ? ` ${escapeHtml(tone)}` : ""}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><p>${escapeHtml(detail)}</p></article>`;
  }

  function stageLabelList(run) {
    const pipeline = Array.isArray(run?.runtime?.pipeline) && run.runtime.pipeline.length
      ? run.runtime.pipeline
      : DEFAULT_PIPELINE;
    return (run?.requires_human_review ? pipeline : pipeline.filter((item) => item !== "awaiting_review")).map(humanizeStage);
  }

  function isBuRole() {
    return roleHasAny(currentRole(), "bu") && !roleHasAny(currentRole(), "reviewer", "operator");
  }

  function reviewArtifactBaseRoute() {
    return isBuRole() ? "/bu/runs" : "/reviewer/runs";
  }

  function showSignIn(message) {
    if (!bootstrap.api_auth_enabled) return;
    els.signInPanel.classList.remove("hidden");
    els.sessionStatus.textContent = message || "Session not connected.";
  }

  function renderRoleFrame() {
    const session = state.session || {};
    const role = currentRole();
    const authDisabled = session.auth_disabled || !bootstrap.api_auth_enabled;
    const preferredLane = authDisabled ? "shared" : preferredLaneForRole(role);

    els.surfaceCardExecutive?.classList.toggle("current", preferredLane === "executive");
    els.surfaceCardReviewer?.classList.toggle("current", preferredLane === "review" || preferredLane === "shared");
    els.surfaceCardOperator?.classList.toggle("current", preferredLane === "operate" || preferredLane === "shared");
    els.surfaceCardTenantAdmin?.classList.toggle("current", preferredLane === "system");

    if (els.surfaceBadgeExecutive) els.surfaceBadgeExecutive.textContent = "Read-only";
    if (els.surfaceBadgeReviewer) els.surfaceBadgeReviewer.textContent = preferredLane === "review" || preferredLane === "shared" ? "Current lane" : "Approval lane";
    if (els.surfaceBadgeOperator) els.surfaceBadgeOperator.textContent = preferredLane === "operate" || preferredLane === "shared" ? "Current lane" : "Run control";
    if (els.surfaceBadgeTenantAdmin) els.surfaceBadgeTenantAdmin.textContent = preferredLane === "system" ? "Current lane" : "System health";

    if (authDisabled) {
      els.workspaceSubtitle.textContent = "Shared reviewer + operator lane";
      els.workspaceHeadline.textContent = "Review and operate the latest governed case";
      els.workspaceNote.textContent = "This environment exposes reviewer and operator controls together. Executive narration stays separate on /executive; tenant-system governance stays in the system lane; the bounded BU backend role only applies when auth is enabled.";
      els.roleLanePill.textContent = "Shared operator + reviewer access";
      els.sessionHelp.textContent = "Auth is disabled in this environment. Executive remains read-only on /executive; approvals, run controls, and system inspection stay inside this workspace.";
      return;
    }

    if (isBuRole()) {
      els.workspaceSubtitle.textContent = "BU governed read lane";
      els.workspaceHeadline.textContent = "Review governed case posture before reviewer sign-off";
      els.workspaceNote.textContent = "Inspect queue state, findings, evidence previews, and report posture through the BU-only read lane. Claim, approve/reject, and restricted artifact release remain with reviewer and operator runtime paths.";
      els.roleLanePill.textContent = "BU lane active";
      els.sessionHelp.textContent = "Paste a BU token to inspect governed queue state, or a reviewer token to take approval actions.";
      return;
    }

    if (roleHasAny(role, "tenant_admin", "system")) {
      els.workspaceSubtitle.textContent = "Tenant admin / system lane";
      els.workspaceHeadline.textContent = "Govern connectors, stores, and runtime health";
      els.workspaceNote.textContent = "Use this lane to inspect managed data, graph/search stores, artifact previews, and readiness for the current finance diagnostics tenant. Review and operator controls remain available because this backend role inherits them.";
      els.roleLanePill.textContent = "Tenant admin / system lane active";
      els.sessionHelp.textContent = "Paste a tenant admin or system token to inspect health, connectors, and protected runtime state across the current tenant.";
      return;
    }

    if (roleHasAny(role, "reviewer") && !roleHasAny(role, "operator")) {
      els.workspaceSubtitle.textContent = "BU / reviewer decision lane";
      els.workspaceHeadline.textContent = "Review governed cases before release";
      els.workspaceNote.textContent = "Inspect findings, evidence packets, and challenge state. Approve or reject here; operators resume only after approval. BU leaders now have a separate read-only backend lane into this governed surface.";
      els.roleLanePill.textContent = "BU / reviewer lane active";
      els.sessionHelp.textContent = "Paste a reviewer token to approve or reject governed cases, a BU token for read-only queue access, or an operator token to switch into run-control work.";
      return;
    }

    if (roleHasAny(role, "operator")) {
      els.workspaceSubtitle.textContent = "Operator control plane";
      els.workspaceHeadline.textContent = "Prepare inputs and resume approved runs";
      els.workspaceNote.textContent = "Use this lane for source-pack intake, run launch, runtime inspection, and post-approval resume. Executive narrative stays on /executive; reviewer approval stays separate; tenant-system governance stays in the system lane.";
      els.roleLanePill.textContent = "Operator lane active";
      els.sessionHelp.textContent = "Paste an operator token to start or resume governed runs, or a reviewer token to move into the approval lane.";
      return;
    }

    els.workspaceSubtitle.textContent = "Role-aware governed diagnostics workspace";
    els.workspaceHeadline.textContent = "Choose the truthful StrategyOS lane";
    els.workspaceNote.textContent = "Executive sees board-safe narrative on /executive. BU leaders get a bounded read-only governed lane here, reviewers handle sign-off, operators handle intake and resume, and tenant admin / system governs health and connector truth.";
    els.roleLanePill.textContent = "Sign in for role lanes";
    els.sessionHelp.textContent = "Paste a BU, reviewer, operator, or tenant-admin access token. Executive readout lives at /executive; governed approvals, run controls, and system inspection stay here.";
  }

  function renderHeaderActions() {
    const lane = isAuthDisabled() ? "shared" : preferredLaneForRole(currentRole());
    if (lane === "system") {
      els.systemDrawerButton.textContent = "Governance tools";
      els.newRunButton.textContent = "Open hosted workflow";
      return;
    }
    if (lane === "review") {
      els.systemDrawerButton.textContent = "Evidence + system support";
      els.newRunButton.textContent = "Open governed queue";
      return;
    }
    if (lane === "operate" || lane === "shared") {
      els.systemDrawerButton.textContent = "Runtime + system support";
      els.newRunButton.textContent = isOperator() ? "Prepare source pack" : "Open operator lane";
      return;
    }
    els.systemDrawerButton.textContent = "Lane support";
    els.newRunButton.textContent = "Open current lane";
  }

  function renderRoleTasks() {
    if (!els.roleTaskList) return;
    const lane = isAuthDisabled() ? "shared" : preferredLaneForRole(currentRole());
    const run = state.latestRun || {};
    const findings = Array.isArray(state.findings?.findings) ? state.findings.findings : [];
    const approvalStatus = runApprovalStatus(run);
    const resumable = Boolean(run.requires_human_review) && approvalStatus === "approved" && String(run.current_stage || "") === "awaiting_review";
    const needsReview = Boolean(run.requires_human_review) && ["pending", "awaiting_review", ""].includes(approvalStatus);
    let title = "Role priorities";
    let note = "Concrete next actions appear once session and run state load.";
    let pill = "Awaiting role";
    let tasks = [];

    if (lane === "system") {
      title = "Tenant governance priorities";
      note = "Keep the finance diagnostics tenant truthful: connectors, stores, artifacts, and readiness should agree before broader rollout.";
      pill = "System lane";
      tasks = [
        { title: "Confirm admin context", detail: state.session?.tenant_context?.tenant_id ? `Tenant ${state.session.tenant_context.tenant_id} is in scope. Check role, workspace, and auth posture before changing anything.` : "Open Safe admin context to verify tenant, workspace, and auth posture." },
        { title: "Review connector catalog", detail: Array.isArray(state.connectorCatalog?.connectors) && state.connectorCatalog.connectors.length ? `Inspect ${formatCount(state.connectorCatalog.connectors.length)} truthful ingestion connectors and confirm which ones are permitted for this role.` : "Open Connector catalog to inspect permitted ingestion routes for this tenant." },
        { title: "Check readiness", detail: state.readyStatus?.status ? `Current readiness is ${state.readyStatus.status}. Open Runtime health for dependency detail.` : "Open Runtime health to inspect dependency readiness and auth posture." },
        { title: "Inspect managed data and stores", detail: state.dataStatus?.status === "ok" ? "Managed data is available; verify graph and vector stores reflect the latest governed run." : "Open Managed data to confirm Postgres, graph, and vector-store state for this tenant." },
        { title: "Review protected artifacts", detail: activeRunId() ? `Use the artifact inspector for run ${activeRunId()} to confirm evidence and report surfaces stay aligned.` : "No governed run is loaded yet; verify the platform before onboarding the next run." },
      ];
    } else if (lane === "review") {
      title = isBuRole() ? "BU priorities" : "BU / reviewer priorities";
      note = isBuRole()
        ? "Inspect governed release posture. Reviewer sign-off and operator resume remain downstream from this bounded BU lane."
        : "Decide what is safe to release. Stay on cases, evidence packets, and approval state; operator execution remains downstream.";
      pill = "Review lane";
      tasks = [
        { title: isBuRole() ? "Inspect governed release posture" : needsReview ? "Approve or reject the governed run" : "Review queue posture", detail: isBuRole() ? (needsReview ? `A governed run is waiting for reviewer sign-off${findings.length ? ` across ${formatCount(findings.length)} findings` : ""}.` : findings.length ? `Inspect ${formatCount(findings.length)} governed findings and evidence packets before reviewer release.` : "No governed findings are loaded yet.") : needsReview ? `A governed run is waiting for sign-off${findings.length ? ` across ${formatCount(findings.length)} findings` : ""}.` : resumable ? "Reviewer decision is already recorded; hand off to an operator for resume." : findings.length ? `Inspect ${formatCount(findings.length)} governed findings and evidence packets for the shared BU/reviewer lane.` : "No governed findings are loaded yet." },
        { title: "Open evidence before decision", detail: findings.length ? "Use the evidence map and finding drawer to inspect citations, owners, challenge posture, and release risk before approving." : "When findings appear, open a case row to inspect its evidence thread." },
        { title: "Protect the handoff", detail: isBuRole() ? "Escalate to a reviewer for claim and sign-off when the governed package is ready." : resumable ? "The next valid step is operator resume into writer-stage deliverables." : "Approval should unblock operator resume; rejection should keep the run from publication." },
      ];
    } else if (lane === "operate" || lane === "shared") {
      title = lane === "shared" ? "Workspace priorities" : "Operator priorities";
      note = lane === "shared"
        ? "This environment shares reviewer and operator controls. Keep run prep, approval, and resume explicit."
        : "Drive governed execution: intake, launch, inspect, then resume only after approval.";
      pill = lane === "shared" ? "Shared workspace" : "Operator lane";
      tasks = [
        { title: state.sourcePack ? "Prepare the source pack" : "Stage finance inputs", detail: state.sourcePack ? (sourcePackCanStart(state.sourcePack) ? "Current source pack is ready. Launch analysis when you are ready." : sourcePackBlockingReasons(state.sourcePack).join(" | ") || "Check file support and required roles before launching.") : "Upload a source pack or choose a server folder to begin the next finance diagnostics run." },
        { title: resumable ? "Resume the approved run" : "Track governed run state", detail: resumable ? "Reviewer approval is recorded. Resume now to create writer-stage deliverables." : needsReview ? "This run is waiting on reviewer approval; keep the runtime stable and prepare for resume." : activeRunId() ? `Latest run ${activeRunId()} is loaded. Inspect readiness, stores, and findings before starting the next cycle.` : "No active governed run is loaded yet." },
        { title: "Use operator diagnostics", detail: "Open system tools for managed data, graph, vector search, artifacts, and runtime health when a run needs deeper inspection." },
      ];
    } else if (lane === "executive") {
      title = "Executive handoff";
      note = "Board-safe narrative lives on /executive; this workspace remains for governed execution and evidence inspection.";
      pill = "Executive route";
      tasks = [
        { title: "Use the executive cockpit", detail: "Open /executive for overview, cases, evidence, and reports framed for leadership scan." },
        { title: "Delegate execution here", detail: "Reviewer, operator, and tenant-system work stays in this workspace so the executive surface remains clean." },
      ];
    } else {
      title = "Choose the right StrategyOS lane";
      note = "Anonymous viewers see the lane map only. Sign in for governed review, operator control, or tenant-system inspection.";
      pill = "Public posture";
      tasks = [
        { title: "Executive", detail: "Use /executive for the board-safe narrative surface." },
        { title: "BU / reviewer", detail: "Sign in with a BU token for read-only governed review, or a reviewer token for approval actions." },
        { title: "Operator / tenant admin", detail: "Sign in to stage inputs, resume approved runs, and inspect system health." },
      ];
    }

    els.roleTaskTitle.textContent = title;
    els.roleTaskNote.textContent = note;
    els.roleTaskPill.textContent = pill;
    els.roleTaskList.innerHTML = tasks.map((item) => `
      <div class="item">
        <strong>${escapeHtml(item.title || "Task")}</strong>
        <span>${escapeHtml(item.detail || "")}</span>
      </div>
    `).join("");
  }

  function renderSharedScope() {
    const tenant = currentTenantContext();
    const companyOptions = availableCompanyOptions();
    const portfolioOptions = availablePortfolioOptions();
    if (!companyOptions.find((item) => item.value === state.selectedCompany)) state.selectedCompany = companyOptions[0]?.value || "current";
    if (!portfolioOptions.find((item) => item.value === state.selectedPortfolio)) state.selectedPortfolio = portfolioOptions[0]?.value || "all";

    if (els.companySwitcher) {
      els.companySwitcher.innerHTML = companyOptions.map((item) => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join("");
      els.companySwitcher.value = state.selectedCompany;
    }
    if (els.portfolioSwitcher) {
      els.portfolioSwitcher.innerHTML = portfolioOptions.map((item) => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join("");
      els.portfolioSwitcher.value = state.selectedPortfolio;
    }

    const findings = currentScopeFindings();
    const companyLabel = companyOptions.find((item) => item.value === state.selectedCompany)?.label || tenant.tenant_name || tenant.tenant_id || "Current company";
    const portfolioLabel = portfolioOptions.find((item) => item.value === state.selectedPortfolio)?.label || "All governed portfolios";
    if (els.scopeSummary) els.scopeSummary.textContent = `${companyLabel} · ${portfolioLabel}`;
    if (els.scopeNote) els.scopeNote.textContent = findings.length
      ? `${formatCount(findings.length)} governed cases are visible inside the active tenant surface.`
      : "No governed cases are visible for the current switcher state yet.";
    if (els.scopeStatusPill) els.scopeStatusPill.textContent = tenant.tenant_id ? `Tenant ${tenant.tenant_id}` : "Current tenant only";
    if (els.scopeChipRow) {
      const chips = [
        statusPill(state.session?.authenticated ? "ok" : "neutral", state.session?.authenticated ? formatRoleLabel(currentRole()) : "Anonymous"),
        statusPill(state.selectedPortfolio === "runtime" ? "warn" : "neutral", portfolioLabel),
        statusPill(state.selectedDomain === "all" ? "neutral" : "ok", domainLabel(state.selectedDomain)),
      ];
      els.scopeChipRow.innerHTML = chips.join("");
    }
  }

  function renderPlanSignalPanel() {
    if (!els.planHealthPill) return;
    const model = boundedPlanHealthModel();
    els.planHealthPill.textContent = model.status;
    els.planHealthPill.className = `pill ${statusTone(model.tone)}`;
    els.planHealthStatus.textContent = model.status;
    els.planHealthNote.textContent = model.note;
    if (els.planHealthSourceNote) els.planHealthSourceNote.textContent = model.citations.detail;
    els.planHealthKpiTree.textContent = model.treeLabel;
    els.publicationSurfaceSummary.textContent = model.publicationSummary;
    els.domainKpiGrid.innerHTML = [
      metricCard("Recoverable value", state.latestRun?.total_recoverable_sar !== undefined ? formatSar(state.latestRun.total_recoverable_sar) : "--", "Latest governed finance signal", state.latestRun?.total_recoverable_sar ? "ok" : "warn"),
      metricCard("Evidence chain", model.citations.count !== null && model.citations.count !== undefined ? `${formatCount(model.citations.resolved)} / ${formatCount(model.citations.count)}` : "--", model.citations.detail, model.citations.count && model.citations.resolved === model.citations.count ? "ok" : model.citations.count ? "neutral" : "warn"),
      metricCard("Approval", humanizeToken(model.approval), "Reviewer / operator handoff state", ["approved", "completed"].includes(String(model.approval).toLowerCase()) ? "ok" : "warn"),
      metricCard("Publication", publicationStatusLabel(model.publication.status), `${formatCount(model.publication.report_count ?? 0)} report surfaces · ${formatCount(model.publication.restricted_report_count ?? 0)} restricted`, publicationStatusTone(model.publication.status)),
    ].join("");
    els.planHealthTree.innerHTML = model.domains.length
      ? model.domains.map((item) => `<div class="item"><strong>${statusPill(item.challenged ? "warn" : item.recoverable ? "ok" : "neutral", item.label)}</strong><span>${formatCount(item.count)} cases · ${formatSar(item.recoverable)} · ${formatCount(item.cited)} citations · ${formatCount(item.challenged)} challenged</span></div>`).join("")
      : '<div class="item"><strong>No branches yet</strong><span class="muted">A governed run will create truthful finance-domain branches here.</span></div>';
    els.publicationSurfaceList.innerHTML = publicationSurfaceItems().map((item) => `<div class="item"><strong>${statusPill(item.tone, item.title)}</strong><span>${escapeHtml(item.detail)}</span></div>`).join("");
  }

  function renderBuSurface() {
    if (!els.buCaseList) return;
    const findings = Array.isArray(state.findings?.findings) ? state.findings.findings : [];
    const domains = ["all"].concat(Array.from(new Set(findings.map((item) => domainKeyForFinding(item)))));
    els.buDomainFilters.innerHTML = domains.map((domain) => `
      <button class="btn ${state.selectedDomain === domain ? "primary" : "secondary"}" type="button" data-domain-filter="${escapeHtml(domain)}">${escapeHtml(domainLabel(domain))}</button>
    `).join("");
    const filtered = currentScopeFindings();
    const challenged = filtered.filter((item) => item?.challenged).length;
    const citations = normalizedCitationSummary(state.latestRun, filtered);
    const publication = publicationContract();
    const buLane = state.workspaceContract?.lanes?.bu || {};
    els.buSurfacePill.textContent = filtered.length ? `${formatCount(filtered.length)} cases` : "Awaiting cases";
    els.buSurfaceNote.textContent = filtered.length
      ? `Showing ${formatCount(filtered.length)} governed cases for ${domainLabel(state.selectedDomain)} with ${publicationStatusLabel(publication.status).toLowerCase()} publication posture.`
      : "No governed cases match the current domain and portfolio selection.";
    if (els.buSurfaceKpiGrid) {
      els.buSurfaceKpiGrid.innerHTML = [
        metricCard("Cases in scope", formatCount(filtered.length), `Filtered for ${domainLabel(state.selectedDomain)}`, filtered.length ? "ok" : "warn"),
        metricCard("Evidence QA", citations.count !== null ? `${formatCount(citations.resolved)} / ${formatCount(citations.count)}` : "--", citations.detail, citations.count ? "neutral" : "warn"),
        metricCard("Challenges", formatCount(challenged), challenged ? "Reviewer closure is still needed on challenged packets." : "No challenged packets are visible in this BU slice.", challenged ? "warn" : "ok"),
        metricCard("Report posture", publicationStatusLabel(publication.status), `${formatCount(publication.report_count ?? 0)} report surfaces · ${formatCount(publication.restricted_report_count ?? 0)} restricted`, publicationStatusTone(publication.status)),
      ].join("");
    }
    if (els.buWorkflowList) {
      els.buWorkflowList.innerHTML = [
        `<div class="item"><strong>${statusPill(filtered.length ? "ok" : "neutral", "1. Triage domain worklist")}</strong><span>${escapeHtml(filtered.length ? `${formatCount(filtered.length)} governed cases are visible inside ${domainLabel(state.selectedDomain)}.` : "Load a governed run or widen the current domain filter.")}</span></div>`,
        `<div class="item"><strong>${statusPill(challenged ? "warn" : citations.count ? "ok" : "neutral", "2. Inspect evidence posture")}</strong><span>${escapeHtml(`${buLane.evidence_qa_route || "/runs/latest/findings?domain=evidence_qa"} · ${citations.detail}`)}</span></div>`,
        `<div class="item"><strong>${statusPill(publicationStatusTone(publication.status), "3. Read governed report posture")}</strong><span>${escapeHtml(`${buLane.case_route_template || "/bu/runs/{run_id}"} · allowed actions: ${publicationActionLabels(publication).join(", ") || "View governed report status"}`)}</span></div>`,
        `<div class="item"><strong>${statusPill(challenged || publication.status === "awaiting_review" ? "warn" : "ok", "4. Hand off to reviewer")}</strong><span>${escapeHtml(`${buLane.pending_reviews_route || "/bu/pending-reviews"} remains read-only for BU; approve/reject still belongs to reviewer sign-off.`)}</span></div>`,
      ].join("");
    }
    els.buCaseList.innerHTML = filtered.length
      ? filtered.map((finding) => `
        <div class="item" data-bu-finding-id="${escapeHtml(finding.finding_id)}">
          <strong>${escapeHtml(finding.title || finding.finding_id || "Governed case")}</strong>
          <span>${escapeHtml(domainLabel(domainKeyForFinding(finding)))} · ${escapeHtml(finding.owner || "reviewer")} · ${escapeHtml(formatSar(finding.recoverable_sar))}</span>
          <span>${escapeHtml(`${formatCount(finding.citation_count || 0)} citations · ${finding.challenged ? "challenge open" : finding.status || "review packet"}`)}</span>
        </div>
      `).join("")
      : '<div class="item"><strong>No BU cases</strong><span class="muted">Change the portfolio or domain filter, or load a governed run.</span></div>';
  }

  function renderReviewerSurface() {
    if (!els.reviewerQueueList || !els.reviewerEvidenceQa) return;
    const items = Array.isArray(state.pendingReviews?.items) ? state.pendingReviews.items : [];
    const run = state.latestRun || {};
    const findings = currentScopeFindings();
    const citations = normalizedCitationSummary(run, findings);
    const challenged = challengedSummary(run) || 0;
    els.reviewerSurfacePill.textContent = items.length ? `${formatCount(items.length)} pending` : run.requires_human_review ? (runApprovalStatus(run) || "pending") : "No gate";
    els.reviewerSurfaceNote.textContent = items.length
      ? `Pending reviews stay ahead of report release. Open evidence before approving ${formatCount(items.length)} item${items.length === 1 ? "" : "s"}.`
      : "No extra pending review rows are loaded beyond the current governed run context.";
    els.reviewerQueueList.innerHTML = items.length
      ? items.slice(0, 4).map((item) => `<div class="item"><strong>${escapeHtml(item.run_id || item.title || "Pending review")}</strong><span>${escapeHtml(item.current_stage || item.status || "awaiting_review")} · ${escapeHtml(item.approval_status || "pending")}</span></div>`).join("")
      : `<div class="item"><strong>Latest governed run</strong><span>${escapeHtml(activeRunId() || "No active run")} · ${escapeHtml(runApprovalStatus(run) || "pending")}</span></div>`;
    els.reviewerEvidenceQa.innerHTML = [
      metricCard("Evidence QA", citations.count !== null && citations.count !== undefined ? `${formatCount(citations.resolved)} / ${formatCount(citations.count)}` : "--", citations.detail, citations.count && citations.resolved === citations.count ? "ok" : citations.count ? "neutral" : "warn"),
      metricCard("Challenges", formatCount(challenged), "Auditor challenge events", challenged ? "warn" : "ok"),
      metricCard("Cases in scope", formatCount(findings.length), "Bounded by current BU/reviewer surface", findings.length ? "neutral" : "warn"),
    ].join("");
  }

  function renderOperatorSurface() {
    if (!els.operatorIntakeGrid || !els.operatorWorkflowList) return;
    const run = state.latestRun || {};
    const sourcePack = state.sourcePack;
    const readiness = sourcePack?.task_readiness || {};
    const approval = runApprovalStatus(run) || "pending";
    const stages = stageLabelList(run);
    els.operatorSurfacePill.textContent = activeRunId() ? humanizeStage(run.current_stage || run.status || "created") : "Run prep";
    els.operatorSurfaceNote.textContent = activeRunId()
      ? `Run ${activeRunId()} is in ${humanizeStage(run.current_stage || run.status || "created")}. Resume remains downstream from reviewer approval.`
      : "No governed run is active yet. Stage sources, validate inputs, then launch intentionally.";
    els.operatorIntakeGrid.innerHTML = [
      metricCard("Source pack", sourcePack ? (readiness.ready_for_run ? "Ready" : "Checking") : "Not staged", sourcePack ? (sourcePackBlockingReasons(sourcePack).join(" · ") || "Current pack is staged.") : "Upload a .zip or choose a folder.", sourcePack && readiness.ready_for_run ? "ok" : "warn"),
      metricCard("Approval", approval || "pending", run.requires_human_review ? "Reviewer gate remains visible." : "Human gate optional in this environment.", approval === "approved" ? "ok" : "warn"),
      metricCard("Workflow", activeRunId() ? formatCount(stages.length) : "--", activeRunId() ? "Governed stages are tracked from intake to writer." : "Stages appear after the first run starts.", activeRunId() ? "neutral" : "warn"),
    ].join("");
    els.operatorWorkflowList.innerHTML = stages.length
      ? stages.map((label, index) => `<div class="item"><strong>${escapeHtml(`${index + 1}. ${label}`)}</strong><span>${escapeHtml(index === 0 ? "Launch path" : index === stages.length - 1 ? "Release path" : "Governed checkpoint")}</span></div>`).join("")
      : '<div class="item"><strong>No workflow stages yet</strong><span class="muted">Start a governed run to populate this lane.</span></div>';
  }

  function renderSystemSurface() {
    if (!els.systemPostureGrid || !els.systemSurfaceList) return;
    const connectors = Array.isArray(state.connectorCatalog?.connectors) ? state.connectorCatalog.connectors : [];
    const permitted = connectors.filter((item) => item?.permitted).length;
    const ready = state.readyStatus || {};
    const data = state.dataStatus || {};
    const workflow = data.workflow || {};
    const publication = data.publication || publicationContract();
    const actionLabels = publicationActionLabels(publication);
    const graphStatus = state.dataStatus?.neo4j?.status || "unknown";
    const vectorStatus = state.dataStatus?.qdrant?.status || "unknown";
    const blockedChecks = Object.entries(ready.checks || {})
      .filter(([, value]) => value && !["ok", "ready", "enabled"].includes(String(value.status || "").toLowerCase()))
      .map(([key]) => humanizeToken(key));
    els.systemSurfacePill.textContent = ready.status || data.status || "Posture pending";
    els.systemSurfaceNote.textContent = currentTenantContext().tenant_id
      ? `Tenant ${currentTenantContext().tenant_id} remains the bounded system scope for this release.`
      : "Connect a session to inspect tenant-admin posture.";
    els.systemPostureGrid.innerHTML = [
      metricCard("Readiness", ready.status || "unknown", "Runtime dependency posture", ready.status === "ok" ? "ok" : "warn"),
      metricCard("Connectors", formatCount(connectors.length), `${formatCount(permitted)} permitted for this role`, connectors.length ? "neutral" : "warn"),
      metricCard("Stores", `${graphStatus} / ${vectorStatus}`, "Graph and vector status", graphStatus === "ready" || vectorStatus === "ready" ? "ok" : "warn"),
      metricCard("Publication", publicationStatusLabel(publication.status), `${formatCount(publication.report_count ?? 0)} reports · ${formatCount(publication.restricted_report_count ?? 0)} restricted`, publicationStatusTone(publication.status)),
    ].join("");
    if (els.systemWorkflowCompact) {
      els.systemWorkflowCompact.innerHTML = [
        `<div class="item"><strong>${statusPill(ready.status || "unknown", "Workflow queue")}</strong><span>${escapeHtml(`${formatCount(workflow.pending_reviews ?? 0)} pending reviews · ${formatCount(workflow.recent_runs ?? 0)} recent runs in the store.`)}</span></div>`,
        `<div class="item"><strong>${statusPill(blockedChecks.length ? "warn" : "ok", "Readiness blockers")}</strong><span>${escapeHtml(blockedChecks.length ? blockedChecks.join(", ") : "No blocked dependency checks are visible for the current tenant.")}</span></div>`,
      ].join("");
    }
    if (els.systemPublicationList) {
      els.systemPublicationList.innerHTML = [
        `<div class="item"><strong>${statusPill(publicationStatusTone(publication.status), "Release state")}</strong><span>${escapeHtml(`${publicationStatusLabel(publication.status)} · approval ${humanizeToken(publication.approval_status || "pending")} · stage ${humanizeToken(publication.current_stage || "draft")}`)}</span></div>`,
        `<div class="item"><strong>${statusPill(actionLabels.length ? "ok" : "neutral", "Allowed inspection")}</strong><span>${escapeHtml(actionLabels.length ? actionLabels.join(", ") : "No publication actions are exposed for this lane yet.")}</span></div>`,
      ].join("");
    }
    els.systemSurfaceList.innerHTML = [
      `<div class="item"><strong>Tenant context</strong><span>${escapeHtml(currentTenantContext().tenant_name || currentTenantContext().tenant_id || "Current tenant")} / ${escapeHtml(currentTenantContext().workspace_id || "workspace unknown")}</span></div>`,
      `<div class="item"><strong>Managed data</strong><span>${escapeHtml(data.reason || `${formatCount(data.counts?.findings ?? 0)} findings · ${formatCount(data.counts?.artifacts ?? 0)} artifacts`)}</span></div>`,
      `<div class="item"><strong>Connector posture</strong><span>${escapeHtml(connectors.length ? `${formatCount(permitted)} permitted of ${formatCount(connectors.length)}` : "No connector catalog loaded")}</span></div>`,
      `<div class="item"><strong>Workflow store</strong><span>${escapeHtml(`${formatCount(workflow.pending_reviews ?? 0)} pending reviews · latest run ${workflow.latest?.run_id || workflow.latest?.id || data.runtime_posture?.latest_run_id || "not loaded"}`)}</span></div>`,
      `<div class="item"><strong>Publication boundary</strong><span>${escapeHtml(`${publicationStatusLabel(publication.status)} · ${formatCount(publication.report_count ?? 0)} reports · ${formatCount(publication.evidence_count ?? 0)} evidence artifacts`)}</span></div>`,
    ].join("");
  }

  async function loadDrilldownEvidence(finding) {
    if (!finding || !activeRunId()) {
      state.drilldownEvidence = { status: "idle", payload: null, error: "" };
      return;
    }
    state.drilldownEvidence = { status: "loading", payload: null, error: "" };
    renderSharedDrilldown();
    try {
      const payload = await requestJson(`/data/evidence-preview?run_id=${encodeURIComponent(activeRunId())}&finding_id=${encodeURIComponent(finding.finding_id)}`);
      state.drilldownEvidence = { status: "ready", payload, error: payload.reason || "" };
    } catch (error) {
      state.drilldownEvidence = { status: "failed", payload: error?.payload || null, error: error?.message || "Evidence preview failed." };
    }
    renderSharedDrilldown();
  }

  async function loadDrilldownReport(artifactKey) {
    const key = artifactKey || state.selectedReportKey;
    if (!key || !activeRunId()) {
      state.drilldownReport = { status: "idle", payload: null, error: "" };
      renderSharedDrilldown();
      return;
    }
    state.selectedReportKey = key;
    state.drilldownReport = { status: "loading", payload: null, error: "" };
    renderSharedDrilldown();
    try {
      const payload = await requestJson(`${reviewArtifactBaseRoute()}/${encodeURIComponent(activeRunId())}/artifacts/${encodeURIComponent(key)}`);
      state.drilldownReport = { status: "ready", payload, error: payload.reason || "" };
    } catch (error) {
      state.drilldownReport = { status: "failed", payload: error?.payload || null, error: error?.message || "Report preview failed." };
    }
    renderSharedDrilldown();
  }

  function renderSharedDrilldown() {
    if (!els.drilldownCaseTitle) return;
    const finding = activeFindingRecord();
    const artifacts = state.workspaceContract?.reports?.artifacts || [];
    const reportArtifacts = Array.isArray(artifacts) && artifacts.length
      ? artifacts
      : Object.keys(state.latestRun?.artifacts || {}).map((artifact_key) => ({ artifact_key, title: humanizeToken(artifact_key) }));
    if (els.detailBreadcrumb) {
      els.detailBreadcrumb.textContent = finding
        ? `${finding.finding_id || "Case"} → ${finding.pattern_label || humanizePattern(finding.pattern_type)} → evidence → ${state.selectedReportKey || "report"}`
        : "Case → finding → evidence → report";
    }
    if (!finding) {
      els.drilldownStatusPill.textContent = "Awaiting selection";
      els.drilldownCaseTitle.textContent = "No governed case selected";
      els.drilldownCaseSummary.textContent = "Choose a case from the worklist, BU dashboard, or executive surface to inspect the full governed spine.";
      els.drilldownCaseKv.innerHTML = "";
      els.drilldownEvidenceTitle.textContent = "Evidence preview";
      els.drilldownEvidenceSummary.textContent = "No evidence preview loaded yet.";
      els.drilldownEvidencePreview.textContent = "Select a finding to fetch the latest evidence excerpt.";
      els.drilldownReportTitle.textContent = "Report posture";
      els.drilldownReportSummary.textContent = "No report preview loaded yet.";
      els.drilldownReportList.innerHTML = "";
      els.drilldownReportPreview.textContent = "Select a report artifact to preview it here.";
      return;
    }
    els.drilldownStatusPill.textContent = findingStatus(finding).label;
    els.drilldownCaseTitle.textContent = finding.title || finding.finding_id || "Governed case";
    els.drilldownCaseSummary.textContent = `${domainLabel(domainKeyForFinding(finding))} · ${finding.owner || "reviewer"} · ${formatSar(finding.recoverable_sar)}.`;
    els.drilldownCaseKv.innerHTML = kvHtml([
      ["Finding", finding.finding_id || "--"],
      ["Type", finding.pattern_label || humanizePattern(finding.pattern_type)],
      ["Confidence", finding.confidence || "--"],
      ["Citations", formatCount(finding.citation_count || 0)],
      ["Action", finding.challenged ? "Resolve challenge" : "Review packet"],
    ]);

    const evidence = state.drilldownEvidence;
    els.drilldownEvidenceTitle.textContent = evidence.payload?.title || finding.pattern_label || "Evidence preview";
    if (evidence.status === "loading") {
      els.drilldownEvidenceSummary.textContent = "Loading evidence excerpt from the governed run.";
      els.drilldownEvidencePreview.textContent = "Loading evidence preview…";
    } else if (evidence.status === "ready") {
      els.drilldownEvidenceSummary.textContent = `${evidence.payload?.source_path || "Stored evidence"} · ${evidence.payload?.locator || "no locator"}`;
      els.drilldownEvidencePreview.textContent = evidence.payload?.excerpt || compactJson(evidence.payload?.resolved_payload || evidence.payload);
    } else if (evidence.status === "failed") {
      els.drilldownEvidenceSummary.textContent = evidence.error || "Evidence preview unavailable.";
      els.drilldownEvidencePreview.textContent = compactJson(evidence.payload || { status: "failed", detail: evidence.error });
    } else {
      els.drilldownEvidenceSummary.textContent = "No evidence preview loaded yet.";
      els.drilldownEvidencePreview.textContent = "Select a finding to fetch the latest evidence excerpt.";
    }

    const publication = publicationContract();
    els.drilldownReportTitle.textContent = state.selectedReportKey ? reportLabel(state.selectedReportKey) : "Report posture";
    els.drilldownReportSummary.textContent = reportArtifacts.length
      ? `${formatCount(reportArtifacts.length)} report surface${reportArtifacts.length === 1 ? " is" : "s are"} available for this governed spine. Release is ${publicationStatusLabel(publication.status).toLowerCase()}.`
      : `No report artifacts are available yet. Release is currently ${publicationStatusLabel(publication.status).toLowerCase()}.`;
    els.drilldownReportList.innerHTML = reportArtifacts.map((item) => `
      <button class="btn ${state.selectedReportKey === item.artifact_key ? "primary" : "secondary"}" type="button" data-drilldown-report="${escapeHtml(item.artifact_key)}">${escapeHtml(item.title || reportLabel(item.artifact_key))}</button>
    `).join("");
    const report = state.drilldownReport;
    if (report.status === "loading") {
      els.drilldownReportPreview.textContent = "Loading report preview…";
    } else if (report.status === "ready") {
      els.drilldownReportPreview.textContent = report.payload?.preview_text || compactJson(report.payload?.preview_json || report.payload);
    } else if (report.status === "failed") {
      els.drilldownReportPreview.textContent = compactJson(report.payload || { status: "failed", detail: report.error });
    } else {
      els.drilldownReportPreview.textContent = "Select a report artifact to preview it here.";
    }
  }

  function renderRoleSurfaces() {
    renderSharedScope();
    renderPlanSignalPanel();
    renderBuSurface();
    renderReviewerSurface();
    renderOperatorSurface();
    renderSystemSurface();
    renderSharedDrilldown();
  }

  async function syncSharedDrilldown(findingId) {
    state.selectedFindingId = String(findingId || "");
    const finding = activeFindingRecord();
    if (!state.selectedReportKey) {
      const firstReport = Array.isArray(state.workspaceContract?.reports?.artifacts) && state.workspaceContract.reports.artifacts.length
        ? state.workspaceContract.reports.artifacts[0]?.artifact_key
        : Object.keys(state.latestRun?.artifacts || {})[0];
      state.selectedReportKey = firstReport || "";
    }
    renderRoleSurfaces();
    await loadDrilldownEvidence(finding);
    if (state.selectedReportKey) await loadDrilldownReport(state.selectedReportKey);
  }

  function applyLaneHint() {
    const requested = requestedLane();
    const preferred = preferredLaneForRole(currentRole());
    const lane = requested || (currentRole() !== "anonymous" ? preferred : "");
    const signature = `${lane}:${currentRole()}:${Boolean(state.session?.authenticated)}`;
    if (!lane || state.laneSignature === signature) return;
    state.laneSignature = signature;
    if (lane === "review") {
      document.getElementById("review")?.scrollIntoView({ block: "start" });
      return;
    }
    if (lane === "operate") {
      openDrawer("new-run", "source-pack-section");
      return;
    }
    if (lane === "system") {
      openDrawer("system", "admin-context-panel");
    }
  }

  function renderSession() {
    els.appName.textContent = bootstrap.product_name || "StrategyOS";
    els.environmentBadge.textContent = bootstrap.environment || "environment";
    els.sessionToken.value = state.token;
    const session = state.session || {};
    const role = session.role || "anonymous";
    const authDisabled = session.auth_disabled || !bootstrap.api_auth_enabled;
    const displayName = formatSessionIdentity(session);
    renderRoleFrame();
    renderHeaderActions();
    renderRoleTasks();
    renderRoleSurfaces();
    els.identity.textContent = authDisabled ? "Auth disabled" : session.authenticated ? displayName : "Not signed in";
    els.sessionStatus.textContent = authDisabled
      ? "API auth is disabled for this environment. Reviewer and operator controls share this workspace."
      : session.authenticated
        ? role === "bu"
          ? `Connected as ${displayName}. Inspect governed queue state; reviewer sign-off is still required for release actions.`
          : role === "reviewer"
          ? `Connected as ${displayName}. Approve or reject governed cases in this lane.`
          : role === "operator"
            ? `Connected as ${displayName}. Start analyses and resume only after reviewer approval.`
            : roleHasAny(role, "tenant_admin", "system")
              ? `Connected as ${displayName}. Govern tenant context, connectors, managed data, and runtime posture from this lane.`
              : `Connected as ${displayName}.`
        : "Session not connected.";
    els.signInPanel.classList.toggle("hidden", authDisabled || Boolean(session.authenticated));
    els.reviewApprove.disabled = !isReviewer() || !activeRunId();
    els.reviewReject.disabled = !isReviewer() || !activeRunId();
    els.reviewResume.disabled = !isOperator() || !activeRunId();
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
    const finalGateChecks = run?.final_gate?.phase_status?.phase_4_evidence_chain?.checks || {};
    const detail = finalGateChecks.citation_resolution_rate?.detail || "";
    const match = String(detail).match(/resolved=(\d+)\/(\d+)/);
    if (match) return { resolved: Number(match[1]), count: Number(match[2]) };
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

  function renderDashboard() {
    const run = state.latestRun || {};
    if (!run || run.status === "missing") {
      const job = state.latestJob;
      if (job?.job_id && ["queued", "running", "failed"].includes(String(job.status || "").toLowerCase())) {
        els.runPill.textContent = `${displayRunId(job)} - ${String(job.status).replaceAll("_", " ")}`;
        els.runPill.className = `pill status-pill ${statusTone(job.status)}`;
        els.kpiRecoverable.textContent = "--";
        els.kpiFindings.innerHTML = "--";
        els.kpiCitations.textContent = "--";
        els.kpiCitations.classList.remove("ok");
        els.kpiChallenged.textContent = "--";
        els.stageStepper.textContent = String(job.status || "").toLowerCase() === "failed"
          ? `Worker failed${job.failure_reason ? `: ${job.failure_reason}` : "."}`
          : "Queued analysis - waiting for StrategyOS worker.";
        els.storeBadges.innerHTML = "";
        els.partialRunChips.classList.add("hidden");
        renderReviewMessage();
        renderArtifacts();
        return;
      }
      els.runPill.textContent = "No runs yet";
      els.runPill.className = "pill status-pill warn";
      els.kpiRecoverable.textContent = "--";
      els.kpiFindings.innerHTML = "--";
      els.kpiCitations.textContent = "--";
      els.kpiCitations.classList.remove("ok");
      els.kpiChallenged.textContent = "--";
      els.stageStepper.textContent = "No analyses yet - choose Start analysis.";
      els.storeBadges.innerHTML = "";
      els.partialRunChips.classList.add("hidden");
      renderReviewMessage();
      renderArtifacts();
      return;
    }

    const status = run.status || "unknown";
    els.runPill.textContent = `run ${displayRunId(run)} - ${String(status).replaceAll("_", " ")}`;
    els.runPill.className = `pill status-pill ${statusTone(status)}`;
    els.kpiRecoverable.textContent = formatSar(run.total_recoverable_sar);
    els.kpiFindings.innerHTML = `${formatCount(run.locked_findings ?? run.findings)} <small>of ${formatCount(run.findings)} locked</small>`;

    const citations = normalizedCitationSummary(run, currentScopeFindings());
    if (citations.count !== null && citations.count !== undefined) {
      els.kpiCitations.textContent = `${formatCount(citations.resolved)} / ${formatCount(citations.count)}`;
      els.kpiCitations.classList.toggle("ok", Number(citations.count) > 0 && Number(citations.resolved) === Number(citations.count));
    } else {
      els.kpiCitations.textContent = "--";
      els.kpiCitations.classList.remove("ok");
    }

    const challenged = challengedSummary(run);
    const findings = run.findings ?? run.locked_findings;
    els.kpiChallenged.innerHTML = challenged === null || challenged === undefined
      ? "--"
      : `${formatCount(challenged)} <small>${findings ? `of ${formatCount(findings)}` : "events"}</small>`;

    renderStages(run);
    renderStoreBadges(run);
    renderPartialRunChips(run);
    renderReviewMessage();
    renderArtifacts();
  }

  function renderStages(run) {
    const pipeline = Array.isArray(run.runtime?.pipeline) && run.runtime.pipeline.length
      ? run.runtime.pipeline
      : DEFAULT_PIPELINE;
    const stages = run.requires_human_review ? pipeline : pipeline.filter((item) => item !== "awaiting_review");
    const current = String(run.current_stage || (run.status === "completed" ? "writer" : "")).toLowerCase();
    const currentIndex = Math.max(0, stages.findIndex((item) => String(item).toLowerCase() === current));
    const completed = String(run.status || "").toLowerCase() === "completed";
    const activeStage = completed ? "complete" : String(stages[currentIndex] || current || run.status || "unknown").replaceAll("_", " ");
    els.stageStepper.innerHTML = `<span class="stage-node ${completed ? "done" : "current"}">Stage: ${escapeHtml(activeStage)}</span>`;
  }

  function renderStoreBadges(run) {
    const stores = [
      ["postgres", run.state_store || state.dataStatus?.state_store],
      ["neo4j", run.neo4j || state.dataStatus?.neo4j],
      ["qdrant", run.qdrant || state.dataStatus?.qdrant],
    ];
    els.storeBadges.innerHTML = stores.map(([name, payload]) => {
      const meta = storeStatusMeta(name, payload);
      if (meta.status !== "danger") return "";
      return `<span class="badge ${statusTone(meta.status)}" title="${escapeHtml(meta.reason)}">${escapeHtml(meta.label)}</span>`;
    }).join("");
  }

  function renderPartialRunChips(run) {
    const diagnostics = [];
    if (run.run_mode && run.run_mode !== "full") diagnostics.push(`mode ${run.run_mode}`);
    (run.missing_roles || []).forEach((role) => diagnostics.push(`missing ${role}`));
    (run.detector_report?.skipped_detectors || []).forEach((item) => {
      diagnostics.push(`skipped ${item.detector || "detector"}${item.reason ? `: ${item.reason}` : ""}`);
    });
    if (!diagnostics.length) {
      els.partialRunChips.innerHTML = "";
      els.partialRunChips.classList.add("hidden");
      return;
    }
    const mode = run.run_mode && run.run_mode !== "full" ? "Partial analysis" : "Run notes";
    els.partialRunChips.innerHTML = `<span class="pill warn" title="${escapeHtml(diagnostics.join("\n"))}">${escapeHtml(mode)}: ${formatCount(diagnostics.length)} items</span>`;
    els.partialRunChips.classList.remove("hidden");
  }

  function findingStatus(finding) {
    // Status pill shown on each worklist row, in business language.
    const run = state.findings || {};
    if (run.requires_human_review && ["pending", "awaiting_review", ""].includes(String(run.approval_status || "").toLowerCase())) {
      return { tone: "warn", label: "Needs sign-off" };
    }
    if (finding.challenged) {
      return { tone: "neutral", label: "Auditor challenged" };
    }
    if (Number(finding.recoverable_sar) <= 0) {
      return { tone: "neutral", label: "Control gap" };
    }
    return { tone: "ok", label: "Verified" };
  }

  function renderFindingRow(finding) {
    const status = findingStatus(finding);
    const amount = Number(finding.recoverable_sar) > 0 ? formatSar(finding.recoverable_sar) : "No cash impact";
    const owner = finding.owner ? escapeHtml(finding.owner) : "Unassigned";
    const cites = Number(finding.citation_count) || 0;
    return `
      <li class="finding-row" data-finding-id="${escapeHtml(finding.finding_id)}" role="button" tabindex="0">
        <div class="finding-row-head">
          <span class="finding-title">${escapeHtml(finding.title)}</span>
          ${statusPill(status.tone, status.label)}
        </div>
        <div class="finding-row-meta">
          <span class="finding-amount">${escapeHtml(amount)}</span>
          <span class="finding-owner">${owner}</span>
          <span class="finding-cites">${cites} ${cites === 1 ? "citation" : "citations"}</span>
        </div>
      </li>`;
  }

  function renderTrend() {
    if (!els.trendStrip) return;
    const rows = Array.isArray(state.history?.history) ? state.history.history : [];
    // A single run is a snapshot, not a trend - keep the strip hidden.
    if (rows.length < 2) {
      els.trendStrip.classList.add("hidden");
      els.trendBars.innerHTML = "";
      els.trendRead.textContent = "";
      return;
    }
    const max = rows.reduce((acc, row) => Math.max(acc, Number(row.recoverable_sar) || 0), 0) || 1;
    els.trendBars.innerHTML = rows.map((row) => {
      const value = Number(row.recoverable_sar) || 0;
      const height = Math.max(6, Math.round((value / max) * 100));
      const label = (row.period || "").slice(0, 8);
      return `<span class="trend-bar" title="${escapeHtml(label)}: ${escapeHtml(formatSar(value))}">
        <span class="trend-bar-fill" style="height:${height}%"></span>
      </span>`;
    }).join("");

    const latest = Number(rows[rows.length - 1].recoverable_sar) || 0;
    const prior = Number(rows[rows.length - 2].recoverable_sar) || 0;
    let read;
    if (latest > prior) read = `Up to ${formatSar(latest)} caught this review`;
    else if (latest < prior) read = `Down to ${formatSar(latest)} caught this review`;
    else read = `Holding at ${formatSar(latest)} caught per review`;
    els.trendRead.textContent = `${read} - across ${formatCount(rows.length)} reviews`;
    els.trendStrip.classList.remove("hidden");
  }

  function renderFindings() {
    if (!els.findingsList) return;
    const payload = state.findings;
    const rows = Array.isArray(payload?.findings) ? payload.findings : [];
    const missing = !payload || payload.status === "missing";

    if (missing || !rows.length) {
      els.findingsTotal.textContent = "--";
      els.findingsSummary.textContent = missing
        ? "No analysis yet - choose Start analysis to review findings."
        : "No findings in the latest run.";
      els.findingsList.innerHTML = "";
      state.selectedFindingId = "";
      renderRoleSurfaces();
      return;
    }

    const totalRecoverable = payload.total_recoverable_sar;
    els.findingsTotal.textContent = `${formatCount(rows.length)} findings`;
    els.findingsSummary.textContent = totalRecoverable != null
      ? `${formatSar(totalRecoverable)} recoverable across ${formatCount(rows.length)} findings. Tap a row for evidence.`
      : `${formatCount(rows.length)} findings. Tap a row for evidence.`;
    els.findingsList.innerHTML = rows.map(renderFindingRow).join("");
    if (!rows.find((item) => String(item.finding_id) === String(state.selectedFindingId))) {
      state.selectedFindingId = rows[0]?.finding_id || "";
    }
    renderRoleSurfaces();
  }

  function openFindingDetail(findingId) {
    const rows = Array.isArray(state.findings?.findings) ? state.findings.findings : [];
    const finding = rows.find((row) => String(row.finding_id) === String(findingId));
    if (!finding) return;
    state.openFindingId = String(findingId);

    els.findingDetailEyebrow.textContent = finding.pattern_label || "Finding";
    els.findingDetailTitle.textContent = finding.title || finding.finding_id;

    const kv = [
      ["Finding", finding.finding_id],
      ["Type", finding.pattern_label || humanizePattern(finding.pattern_type)],
      ["Recoverable", Number(finding.recoverable_sar) > 0 ? formatSar(finding.recoverable_sar) : "No cash impact"],
      ["Leakage", Number(finding.leakage_sar) > 0 ? formatSar(finding.leakage_sar) : "-"],
      ["Confidence", finding.confidence ? humanizeToken(finding.confidence) : "-"],
      ["Owner", finding.owner || "Unassigned"],
      ["Classification", finding.classification || "-"],
    ];
    els.findingDetailKv.innerHTML = kv
      .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(String(value))}</dd>`)
      .join("");

    els.findingDetailExplainer.textContent = finding.classification
      ? `${finding.pattern_label || "This finding"} - ${finding.classification}.`
      : `${finding.pattern_label || "This finding"} flagged by the analyst and reviewed by the auditor.`;

    const cites = Number(finding.citation_count) || 0;
    els.findingDetailCitations.textContent = cites
      ? `${cites} source ${cites === 1 ? "citation" : "citations"} support this finding. Open the evidence map to trace each one.`
      : "No source citations were attached to this finding.";

    els.findingDetailChallenge.textContent = finding.challenged
      ? "The auditor challenged this finding during the ping-pong review; it was retained after verification."
      : "No auditor challenge was raised for this finding.";

    els.findingDetailGraph.dataset.kgNode = finding.node_id || `Finding:${finding.finding_id}`;
    openDrawer("finding");
  }

  function runApprovalStatus(run) {
    return String(run?.approval_status || run?.approval?.approval_status || "").toLowerCase();
  }

  function renderReviewMessage() {
    const run = state.latestRun || {};
    const approvalStatus = runApprovalStatus(run);
    const needsReview = Boolean(run.requires_human_review) && ["pending", "awaiting_review", ""].includes(approvalStatus);
    const resumable = Boolean(run.requires_human_review) && approvalStatus === "approved" && String(run.current_stage || "") === "awaiting_review";
    els.reviewMessage.classList.toggle("hidden", !(needsReview || resumable));
    if (!needsReview && !resumable) return;

    const role = String(state.session?.role || "anonymous").toLowerCase();
    const emptyRun = runHasNoReadableFiles(run);
    const reviewerAllowed = needsReview && isReviewer() && Boolean(activeRunId()) && !emptyRun;
    const operatorResumeAllowed = resumable && isOperator() && Boolean(activeRunId());

    els.reviewApprove.classList.toggle("hidden", !reviewerAllowed);
    els.reviewReject.classList.toggle("hidden", !reviewerAllowed);
    els.reviewResume.classList.toggle("hidden", !operatorResumeAllowed);
    els.reviewNewRun.classList.toggle("hidden", !emptyRun);
    els.reviewComment.classList.toggle("hidden", !reviewerAllowed);
    els.reviewComment.disabled = !reviewerAllowed;

    if (emptyRun) {
      els.reviewTitle.textContent = "Upload readable finance files before review.";
      els.reviewDetail.textContent = "Start a new analysis with invoices, ledgers, bank statements, or the sample dataset.";
      els.reviewApprove.disabled = true;
      els.reviewReject.disabled = true;
      els.reviewResume.disabled = true;
      els.reviewApprove.title = "No findings are available to approve.";
      els.reviewReject.title = "No findings are available to reject.";
      els.reviewResume.title = "Start a new analysis with readable files instead.";
      return;
    }

    if (resumable) {
      if (isOperator()) {
        els.reviewTitle.textContent = "Reviewer approved this run.";
        els.reviewDetail.textContent = "Resume now to create the final writer-stage deliverables.";
      } else {
        els.reviewTitle.textContent = "Reviewer approved this run.";
        els.reviewDetail.textContent = "An Operator must resume the run to create the final deliverables.";
      }
    } else if (isReviewer()) {
      els.reviewTitle.textContent = "Please review this run.";
      els.reviewDetail.textContent = "Approve it to let an Operator finish the report, or reject it if the findings need rework.";
    } else if (role === "operator") {
      els.reviewTitle.textContent = "Waiting for reviewer approval.";
      els.reviewDetail.textContent = "You are signed in as Operator. A Reviewer must approve or reject this run before it can continue.";
    } else {
      els.reviewTitle.textContent = "Sign in to review this run.";
      els.reviewDetail.textContent = "Use a Reviewer token to approve or reject. Use an Operator token to resume after approval.";
    }

    els.reviewApprove.disabled = !reviewerAllowed;
    els.reviewReject.disabled = !reviewerAllowed;
    els.reviewResume.disabled = !operatorResumeAllowed;
    els.reviewApprove.title = reviewerAllowed ? "" : "Reviewer role required.";
    els.reviewReject.title = reviewerAllowed ? "" : "Reviewer role required.";
    els.reviewResume.title = operatorResumeAllowed ? "" : "Operator role required after approval.";
  }

  function systemMessageForRun(run) {
    if (!run || run.status === "missing") return "No completed run is loaded yet.";
    const parts = [`run ${String(run.status || "unknown").replaceAll("_", " ")}`];
    if (run.locked_findings !== undefined) parts.push(`${formatCount(run.locked_findings)} findings locked`);
    if (run.total_recoverable_sar !== undefined) parts.push(`${formatSar(run.total_recoverable_sar)} recoverable`);
    const challenged = challengedSummary(run);
    if (challenged !== null && challenged !== undefined) parts.push(`${formatCount(challenged)} auditor challenges`);
    return parts.join(" - ");
  }

  function loadChatForRun() {
    const key = activeRunKey();
    if (state.chatRunKey === key) return;
    state.chatRunKey = key;
    state.openCitationKey = "";
    const stored = window.sessionStorage.getItem(`strategyos.chat.${key}`);
    try {
      state.chatThread = stored ? JSON.parse(stored) : [];
    } catch (_error) {
      state.chatThread = [];
    }
    if (!state.chatThread.length && state.latestRun && state.latestRun.status !== "missing") {
      state.chatThread.push({ type: "system", text: systemMessageForRun(state.latestRun) });
      saveChat();
    }
  }

  function saveChat() {
    if (!state.chatRunKey) return;
    window.sessionStorage.setItem(`strategyos.chat.${state.chatRunKey}`, JSON.stringify(state.chatThread.slice(-60)));
  }

  function maybeAppendRunEvent(previousSignature) {
    const run = state.latestRun || {};
    const signature = `${run.status || "missing"}:${run.current_stage || ""}:${run.approval_status || ""}:${run.locked_findings || ""}:${run.audit_event_count || ""}`;
    if (!previousSignature || previousSignature === signature) {
      state.lastRunSignature = signature;
      return;
    }
    loadChatForRun();
    state.chatThread.push({ type: "system", text: systemMessageForRun(run) });
    state.lastRunSignature = signature;
    saveChat();
  }

  function renderChat() {
    loadChatForRun();
    if (state.qaMode === "llm" && !llmChatEnabled()) {
      setQaMode("deterministic");
    }
    if (bootstrap.api_auth_enabled && !state.session?.authenticated) {
      els.chatInput.disabled = true;
      els.chatSend.disabled = true;
    } else if (!state.latestRun || state.latestRun.status === "missing") {
      els.chatInput.disabled = true;
      els.chatSend.disabled = true;
    } else {
      els.chatInput.disabled = state.qaLoading;
      els.chatSend.disabled = state.qaLoading;
    }

    els.chatMessages.innerHTML = state.chatThread.length
      ? state.chatThread.map(renderChatEntry).join("")
      : `<div class="sysmsg"><span>No command history for this run.</span></div>`;
    els.chatInput.placeholder = state.qaMode === "llm"
      ? "Ask grounded LLM questions about the latest analysis"
      : "Ask deterministic finance questions about invoices, vendors, findings, or working capital";
    renderQaMode();
    renderSuggestions();
    renderReviewMessage();
    requestAnimationFrame(() => {
      els.chatThread.scrollTop = els.chatThread.scrollHeight;
    });
  }

  function renderChatEntry(entry, index) {
    if (entry.type === "system") {
      return "";
    }
    if (entry.type === "user") {
      return `<div class="msg-user">${escapeHtml(entry.text || "")}</div>`;
    }
    const payload = entry.payload || {};
    const valueLabel = formatValue(payload.value, payload.unit);
    const answer = payload.answer || entry.error || "No answer returned.";
    const unmatched = payload.matched === false;
    const modeLabel = payload.mode === "llm" ? "LLM" : payload.mode === "deterministic" ? "Deterministic" : "";
    const citations = Array.isArray(payload.citations) ? payload.citations : [];
    const suggestions = Array.isArray(payload.suggestions) ? payload.suggestions : [];
    const citationHtml = citations.length
      ? `<div class="chips">${citations.map((citation, citationIndex) => renderCitation(citation, `${index}-${citationIndex}`)).join("")}</div>`
      : "";
    const graphHtml = renderGraphChips(citations);
    const suggestionHtml = unmatched && suggestions.length
      ? `<div class="chips">${suggestions.map((item) => `<button class="btn secondary" type="button" data-suggestion="${escapeHtml(item)}">${escapeHtml(item)}</button>`).join("")}</div>`
      : "";
    return `
      <div class="msg-bot">
        <div class="bubble">
          ${valueLabel ? `<span class="big">${escapeHtml(valueLabel)}</span>` : ""}
          <span>${escapeHtml(answer)}</span>
          ${payload.basis ? `<span class="basis">Basis: ${escapeHtml(payload.basis)}</span>` : ""}
          ${payload.intent ? `<span class="intent">${statusPill(unmatched ? "warn" : "ok", humanizeIntent(payload.intent))}</span>` : ""}
          ${modeLabel ? `<span class="intent">${statusPill(payload.mode === "llm" ? "warn" : "neutral", modeLabel)}</span>` : ""}
        </div>
        ${citationHtml}
        ${graphHtml}
        ${suggestionHtml}
      </div>`;
  }

  function renderCitation(citation, key) {
    const source = basename(citation.source_path || citation.source || "");
    const locator = citation.locator ? ` - ${citation.locator}` : "";
    const active = state.openCitationKey === key;
    const excerpt = active
      ? `<div class="excerpt">${escapeHtml(citation.excerpt || "No excerpt returned for this citation.")}</div>`
      : "";
    return `
      <span>
        <button class="cite ${active ? "active" : ""}" type="button" data-citation-key="${escapeHtml(key)}">
          ${escapeHtml(source + locator)}
        </button>
        ${excerpt}
      </span>`;
  }

  function renderGraphChips(citations) {
    const findingIds = Array.from(new Set(citations.map((citation) => citation.finding_id).filter(Boolean)));
    if (!findingIds.length) return "";
    return `<div class="chips">${findingIds.map((findingId) => (
      `<button class="btn secondary" type="button" data-kg-node="Finding:${escapeHtml(findingId)}">Show ${escapeHtml(findingId)} in graph</button>`
    )).join("")}</div>`;
  }

  function renderSuggestions() {
    const suggestions = state.activeSuggestions.length ? state.activeSuggestions : STARTER_SUGGESTIONS.slice(0, 3);
    els.chatSuggestions.innerHTML = suggestions.slice(0, 3).map((item) => (
      `<button class="btn secondary" type="button" data-suggestion="${escapeHtml(item)}">${escapeHtml(item)}</button>`
    )).join("");
  }

  async function submitChat(event) {
    event?.preventDefault?.();
    const question = els.chatInput.value.trim();
    if (!question || state.qaLoading) return;
    state.chatThread.push({ type: "user", text: question });
    state.qaLoading = true;
    saveChat();
    renderChat();
    try {
      const body = { question, mode: state.qaMode };
      const runId = activeRunId();
      if (runId) body.run_id = runId;
      const payload = await requestJson("/qa", {
        method: "POST",
        body: JSON.stringify(body),
      });
      state.chatThread.push({ type: "bot", payload });
      state.activeSuggestions = Array.isArray(payload.suggestions) && payload.suggestions.length
        ? payload.suggestions
        : STARTER_SUGGESTIONS.slice(0, 3);
      els.chatInput.value = "";
    } catch (error) {
      state.chatThread.push({
        type: "bot",
        error: error?.message || "Q&A failed.",
        payload: {
          matched: false,
          answer: error?.message || "Q&A failed.",
          suggestions: STARTER_SUGGESTIONS,
          citations: [],
        },
      });
      state.activeSuggestions = STARTER_SUGGESTIONS.slice(0, 3);
    } finally {
      state.qaLoading = false;
      saveChat();
      renderChat();
    }
  }

  function setSuggestion(value) {
    els.chatInput.value = value;
    if (state.qaLoading) {
      els.chatInput.focus();
      return;
    }
    submitChat();
  }

  function renderDataStatus() {
    const payload = state.dataStatus;
    if (!isAuthed()) {
      els.dataSummary.textContent = "Connect a session to inspect managed data.";
      els.dataCountsKv.innerHTML = "";
      els.dataSystemsKv.innerHTML = "";
      els.dataPayloadPreview.textContent = "Authentication required.";
      return;
    }
    if (!payload) {
      els.dataSummary.textContent = "Data status has not loaded.";
      els.dataPayloadPreview.textContent = "No data payload.";
      return;
    }
    const counts = payload.counts || payload.entity_counts || payload.store_counts || {};
    els.dataSummary.innerHTML = `Run ${escapeHtml(payload.run_id || displayRunId(state.latestRun))} ${statusPill(payload.status || "loaded")}`;
    els.dataCountsKv.innerHTML = kvHtml([
      ["Evidence documents", counts.evidence_documents ?? counts.documents ?? "--"],
      ["Findings", counts.findings ?? "--"],
      ["Artifacts", counts.artifacts ?? "--"],
      ["KG nodes / edges", `${counts.kg_nodes ?? counts.nodes ?? "--"} / ${counts.kg_edges ?? counts.edges ?? "--"}`],
    ]);
    const graphMeta = storeStatusMeta("neo4j", payload.neo4j);
    const vectorMeta = storeStatusMeta("qdrant", payload.qdrant);
    els.dataSystemsKv.innerHTML = kvHtml([
      ["Graph", statusPill(graphMeta.status, graphMeta.label)],
      ["Search index", statusPill(vectorMeta.status, vectorMeta.label)],
      ["Graph sample", payload.neo4j?.sample_relation?.source_node_key || payload.neo4j?.reason || "--"],
      ["Vector sample", payload.qdrant?.sample_record?.finding_id || payload.qdrant?.reason || "--"],
    ], true);
    els.dataPayloadPreview.textContent = compactJson(payload);
  }

  function renderAdminContext() {
    if (!isAuthed()) {
      els.adminContextSummary.textContent = "Connect a session to inspect tenant admin context.";
      els.adminContextKv.innerHTML = "";
      els.adminCapabilitiesKv.innerHTML = "";
      els.adminContextPayloadPreview.textContent = "Authentication required.";
      return;
    }
    const session = state.session || {};
    const tenant = session.tenant_context || {};
    const capabilities = session.capabilities || {};
    const enabledCapabilities = Object.entries(capabilities)
      .filter(([, enabled]) => Boolean(enabled))
      .map(([key]) => formatCapabilityLabel(key));
    els.adminContextSummary.innerHTML = [
      `${escapeHtml(formatRoleLabel(session.role || "anonymous"))} ${statusPill(session.authenticated ? "ok" : "warn", session.authenticated ? "authenticated" : "not connected")}`,
      `Altitude ${statusPill("neutral", session.altitude || "workspace")}`,
    ].join(" - ");
    els.adminContextKv.innerHTML = kvHtml([
      ["Tenant", tenant.tenant_name || tenant.tenant_id || "--"],
      ["Tenant ID", tenant.tenant_id || "--"],
      ["Workspace", tenant.workspace_id || "--"],
      ["Environment", session.environment || bootstrap.environment || "--"],
      ["Auth mode", session.auth_mode || "--"],
      ["Public live health", statusPill(session.public_health_enabled ? "enabled" : "protected")],
      ["Human review", statusPill(session.require_human_review ? "required" : "optional")],
    ], true);
    els.adminCapabilitiesKv.innerHTML = kvHtml([
      ["Allowed here", enabledCapabilities.length ? enabledCapabilities.join(", ") : "No protected capabilities exposed"],
      ["Identity", formatSessionIdentity(session)],
    ]);
    els.adminContextPayloadPreview.textContent = compactJson(sanitizeUiPayload(session));
  }

  function connectorCapabilityChips(connector) {
    const chips = [];
    chips.push(statusPill(connector?.permitted ? "ok" : "neutral", connector?.permitted ? "Permitted" : "Not permitted"));
    if (connector?.source_boundary) chips.push(statusPill("neutral", humanizeToken(connector.source_boundary)));
    if (connector?.supports_manual_upload) chips.push(statusPill("ok", "Manual upload"));
    if (connector?.supports_incremental) chips.push(statusPill("ok", "Incremental"));
    return chips.join(" ");
  }

  function workflowStep(status, title, detail, targetId) {
    const target = targetId
      ? `<button class="btn secondary" type="button" data-workflow-target="${escapeHtml(targetId)}">Open panel</button>`
      : "";
    return `
      <div class="item">
        <strong>${statusPill(status, title)}</strong>
        <span>${escapeHtml(detail)}</span>
        ${target}
      </div>`;
  }

  function renderSystemWorkflow() {
    if (!isAuthed()) {
      els.systemWorkflowSummary.textContent = "Connect a session to inspect the hosted admin workflow.";
      els.systemWorkflowList.innerHTML = "";
      els.systemWorkflowPayloadPreview.textContent = "Authentication required.";
      return;
    }
    const contract = state.workspaceContract;
    if (!contract) {
      els.systemWorkflowSummary.textContent = "Hosted workflow has not loaded.";
      els.systemWorkflowList.innerHTML = "";
      els.systemWorkflowPayloadPreview.textContent = "No workspace contract payload.";
      return;
    }

    const connectors = Array.isArray(state.connectorCatalog?.connectors) ? state.connectorCatalog.connectors : [];
    const permittedConnectors = connectors.filter((item) => item?.permitted);
    const reports = Array.isArray(contract.reports?.artifacts) ? contract.reports.artifacts : [];
    const evidence = Array.isArray(contract.evidence?.artifacts) ? contract.evidence.artifacts : [];
    const dataStatus = state.dataStatus || {};
    const counts = dataStatus.counts || {};
    const ready = state.readyStatus || {};
    const checks = ready.checks || {};
    const session = state.session || {};
    const tenant = session.tenant_context || contract.tenant_context || {};
    const runId = activeRunId();
    const workflowSurface = Array.isArray(contract.surfaces)
      ? contract.surfaces.find((surface) => surface.surface_id === "workflow")
      : null;
    const blockedChecks = Object.entries(checks)
      .filter(([, value]) => value && !["ok", "ready", "enabled"].includes(String(value.status || "").toLowerCase()))
      .map(([key]) => humanizeToken(key));

    const workflowItems = [
      workflowStep(
        session.authenticated && tenant.tenant_id ? "ok" : "warn",
        "1. Confirm admin context",
        `${formatRoleLabel(session.role || "anonymous")} on ${tenant.tenant_name || tenant.tenant_id || "current tenant"} / ${tenant.workspace_id || "workspace unknown"}. Auth mode: ${session.auth_mode || "unknown"}.`,
        "admin-context-panel"
      ),
      workflowStep(
        permittedConnectors.length ? "ok" : connectors.length ? "warn" : "neutral",
        "2. Review connector posture",
        permittedConnectors.length
          ? `${formatCount(permittedConnectors.length)} permitted connectors available${workflowSurface?.permitted ? "; workflow surface stays inside existing governed routes." : "."}`
          : connectors.length
            ? "Connector catalog loaded, but none are currently permitted for this role."
            : "No connector catalog is available for this tenant yet.",
        "connectors-panel"
      ),
      workflowStep(
        dataStatus.status === "ready" ? "ok" : dataStatus.status === "missing" ? "warn" : statusTone(dataStatus.status || "unknown"),
        "3. Check data posture",
        dataStatus.status === "ready"
          ? `${formatCount(counts.evidence_documents ?? 0)} evidence docs, ${formatCount(counts.findings ?? 0)} findings, graph ${state.dataStatus?.neo4j?.status || "unknown"}, search ${state.dataStatus?.qdrant?.status || "unknown"}.`
          : dataStatus.reason || "Managed data posture is not ready yet.",
        "data-panel"
      ),
      workflowStep(
        ready.status === "ok" ? "ok" : ready.status === "degraded" ? "warn" : statusTone(ready.status || "unknown"),
        "4. Verify runtime readiness",
        blockedChecks.length
          ? `Readiness is ${ready.status || "unknown"}; investigate ${blockedChecks.join(", ")}.`
          : `Readiness is ${ready.status || "unknown"}; health, config, and dependency posture are aligned.`,
        "health-panel"
      ),
      workflowStep(
        runId && (reports.length || evidence.length) ? "ok" : runId ? "warn" : "neutral",
        "5. Inspect governed artifacts",
        runId
          ? `${formatCount(reports.length)} report artifacts and ${formatCount(evidence.length)} evidence artifacts are exposed for governed preview on run ${runId}.`
          : "No governed run is loaded yet, so artifact preview remains limited.",
        "health-panel"
      ),
    ];

    els.systemWorkflowSummary.innerHTML = [
      `${escapeHtml(tenant.tenant_name || tenant.tenant_id || "Current tenant")}`,
      statusPill(ready.status || "unknown", `Readiness ${ready.status || "unknown"}`),
      statusPill(runId ? "ok" : "neutral", runId ? `Run ${runId}` : "No active run"),
    ].join(" - ");
    els.systemWorkflowList.innerHTML = workflowItems.join("");
    els.systemWorkflowPayloadPreview.textContent = compactJson(sanitizeUiPayload(contract));
  }

  function renderPublicationGovernance() {
    if (!els.publicationSummary) return;
    if (!isAuthed()) {
      els.publicationSummary.textContent = "Connect a session to inspect publication governance.";
      els.publicationList.innerHTML = "";
      els.publicationPayloadPreview.textContent = "Authentication required.";
      return;
    }
    const contract = state.workspaceContract || {};
    const items = publicationSurfaceItems();
    const reports = reportArtifactsFromContract();
    const publication = publicationContract();
    els.publicationSummary.innerHTML = `${statusPill(publicationStatusTone(publication.status), publicationStatusLabel(publication.status))} · ${formatCount(publication.report_count ?? reports.length)} report artifact${Number(publication.report_count ?? reports.length) === 1 ? "" : "s"} · ${statusPill(["approved", "completed"].includes(String(publication.approval_status || "").toLowerCase()) ? "ok" : "warn", `Approval ${humanizeToken(publication.approval_status || "pending")}`)}`;
    els.publicationList.innerHTML = items.map((item) => `<div class="item"><strong>${statusPill(item.tone, item.title)}</strong><span>${escapeHtml(item.detail)}</span></div>`).join("") + (reports.length ? reports.map((item) => `<div class="item"><strong>${statusPill(item.restricted ? "warn" : "ok", item.title || reportLabel(item.artifact_key))}</strong><span>${escapeHtml(`${item.category || "report"} · ${item.format || "file"}${item.restricted ? " · restricted" : " · previewable"}`)}</span></div>`).join("") : '<div class="item"><strong>No report artifacts</strong><span class="muted">Load a governed run to inspect publication surfaces.</span></div>');
    els.publicationPayloadPreview.textContent = compactJson(sanitizeUiPayload({ reports: contract.reports, evidence: contract.evidence, surfaces: Array.isArray(contract.surfaces) ? contract.surfaces.filter((item) => ["reports", "evidence", "workflow"].includes(item.surface_id)) : [] }));
  }

  function renderConnectors() {
    if (!isAuthed()) {
      els.connectorsSummary.textContent = "Connect a session to inspect the connector catalog.";
      els.connectorsList.innerHTML = "";
      els.connectorsPayloadPreview.textContent = "Authentication required.";
      return;
    }
    const payload = state.connectorCatalog;
    if (!payload) {
      els.connectorsSummary.textContent = "Connector catalog has not loaded.";
      els.connectorsList.innerHTML = "";
      els.connectorsPayloadPreview.textContent = "No connector payload.";
      return;
    }
    const connectors = Array.isArray(payload.connectors) ? payload.connectors : [];
    const tenant = payload.tenant_context || state.session?.tenant_context || {};
    els.connectorsSummary.innerHTML = `${formatCount(connectors.length)} connectors for ${escapeHtml(tenant.tenant_name || tenant.tenant_id || "current tenant")}`;
    if (!connectors.length) {
      els.connectorsList.innerHTML = '<div class="item"><strong>No connectors</strong><span class="muted">No ingestion connectors are exposed for this tenant.</span></div>';
    } else {
      els.connectorsList.innerHTML = connectors.map((connector) => {
        const capabilities = Array.isArray(connector?.capabilities) && connector.capabilities.length
          ? connector.capabilities.map((item) => humanizeToken(item)).join(", ")
          : "No write actions listed";
        return `
          <div class="item">
            <strong>${escapeHtml(connector.display_name || connector.connector_id || "Connector")}</strong>
            <span>${connectorCapabilityChips(connector)}</span>
            <span>${escapeHtml(capabilities)}</span>
          </div>`;
      }).join("");
    }
    els.connectorsPayloadPreview.textContent = compactJson(payload);
  }

  function destroyKnowledgeGraph() {
    if (state.kgCy) {
      state.kgCy.destroy();
      state.kgCy = null;
    }
  }

  function kgClass(label) {
    return `kg-${String(label || "node").toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  }

  function kgElements(payload) {
    const nodes = Array.isArray(payload?.nodes) ? payload.nodes : [];
    const edges = Array.isArray(payload?.edges) ? payload.edges : [];
    return nodes.map((node) => ({
      group: "nodes",
      classes: kgClass(node.label),
      data: {
        id: String(node.id || ""),
        label: String(node.label || ""),
        display: String(node.display || node.id || "node"),
        sublabel: String(node.sublabel || ""),
        recoverable_sar: Number(node.recoverable_sar || 0),
        invoice_count: Number(node.invoice_count || 0),
        payload: node,
      },
    })).concat(edges.map((edge) => ({
      group: "edges",
      classes: [
        kgClass(edge.label),
        String(edge.label || "").startsWith("SAME_") ? "kg-risk-edge" : "",
      ].join(" "),
      data: {
        id: String(edge.id || `${edge.source}|${edge.label}|${edge.target}`),
        source: String(edge.source || ""),
        target: String(edge.target || ""),
        label: String(edge.label || ""),
        payload: edge,
      },
    })));
  }

  function kgStyle(maxRecoverable) {
    const maxValue = Math.max(1, Number(maxRecoverable || 1));
    return [
      {
        selector: "node",
        style: {
          "background-color": "#768393",
          "border-width": 1,
          "border-color": "#d7e3ee",
          "color": "#f4f7fa",
          "font-size": 10,
          "font-weight": "bold",
          "label": "data(display)",
          "text-background-color": "#05080b",
          "text-background-opacity": 0.82,
          "text-background-padding": 3,
          "text-max-width": 110,
          "text-valign": "bottom",
          "text-wrap": "wrap",
          "width": 34,
          "height": 34,
        },
      },
      {
        selector: ".kg-finding",
        style: {
          "background-color": "#ff6b7a",
          "shape": "ellipse",
          "width": `mapData(recoverable_sar, 0, ${maxValue}, 42, 78)`,
          "height": `mapData(recoverable_sar, 0, ${maxValue}, 42, 78)`,
        },
      },
      {
        selector: ".kg-vendor",
        style: {
          "background-color": "#41d69f",
          "shape": "round-rectangle",
          "width": 50,
          "height": 36,
        },
      },
      {
        selector: ".kg-evidence",
        style: {
          "background-color": "#a8b4c2",
          "shape": "round-rectangle",
          "width": 44,
          "height": 28,
          "font-size": 9,
        },
      },
      {
        selector: ".kg-contract",
        style: {
          "background-color": "#b48cff",
          "shape": "diamond",
          "width": 38,
          "height": 38,
        },
      },
      {
        selector: ".kg-invoice",
        style: {
          "background-color": "#f4b860",
          "shape": "rectangle",
          "width": 34,
          "height": 24,
          "font-size": 8,
        },
      },
      {
        selector: ".kg-purchaseorder",
        style: {
          "background-color": "#58a6ff",
          "shape": "hexagon",
          "width": 34,
          "height": 28,
          "font-size": 8,
        },
      },
      {
        selector: "edge",
        style: {
          "curve-style": "bezier",
          "line-color": "#768393",
          "target-arrow-color": "#768393",
          "target-arrow-shape": "triangle",
          "width": 1.4,
          "label": "data(label)",
          "font-size": 7,
          "color": "#d7e3ee",
          "text-rotation": "autorotate",
          "text-background-color": "#05080b",
          "text-background-opacity": 0.82,
          "text-background-padding": 2,
        },
      },
      {
        selector: ".kg-risk-edge",
        style: {
          "line-color": "#ff6b7a",
          "target-arrow-color": "#ff6b7a",
          "line-style": "dashed",
          "width": 2.2,
        },
      },
      {
        selector: "node:selected",
        style: {
          "border-color": "#41d69f",
          "border-width": 3,
        },
      },
      {
        selector: ".faded",
        style: {
          "opacity": 0.2,
        },
      },
    ];
  }

  function selectedKnowledgeGraphNode() {
    const nodes = Array.isArray(state.knowledgeGraph?.nodes) ? state.knowledgeGraph.nodes : [];
    return nodes.find((node) => node.id === state.kgSelectedId) || null;
  }

  function renderKnowledgeGraphDetail(node) {
    const selected = node || selectedKnowledgeGraphNode();
    if (!selected) {
      els.kgDetail.textContent = "Select a graph node to inspect details.";
      return;
    }
    const chips = [
      statusPill("neutral", selected.label || "node"),
      selected.invoice_count ? statusPill("neutral", `${formatCount(selected.invoice_count)} invoices`) : "",
      selected.recoverable_sar ? statusPill("ok", formatSar(selected.recoverable_sar)) : "",
    ].filter(Boolean).join(" ");
    els.kgDetail.innerHTML = `
      <strong>${escapeHtml(selected.display || selected.id)}</strong>
      <div>${chips}</div>
      <div class="muted">${escapeHtml(selected.sublabel || selected.id || "")}</div>
      <pre class="code-block">${escapeHtml(compactJson(selected.properties || {}))}</pre>`;
  }

  function renderKnowledgeGraph() {
    if (!isAuthed()) {
      destroyKnowledgeGraph();
      els.kgSummary.textContent = "Connect a session to inspect the evidence map.";
      els.kgGraph.classList.add("empty");
      els.kgGraph.textContent = "Authentication required.";
      els.kgDetail.textContent = "Authentication required.";
      return;
    }

    const payload = state.knowledgeGraph || {};
    const nodes = Array.isArray(payload.nodes) ? payload.nodes : [];
    const edges = Array.isArray(payload.edges) ? payload.edges : [];
    const meta = payload.meta || {};
    const loading = state.kgLoading ? `${statusPill("warn", "loading")} ` : "";
    els.kgRefresh.disabled = state.kgLoading;
    els.kgSummary.innerHTML = [
      loading + statusPill(payload.status || "missing"),
      `${formatCount(meta.view_node_count ?? nodes.length)} view nodes`,
      `${formatCount(meta.view_edge_count ?? edges.length)} view edges`,
      `${formatCount(meta.source_node_count ?? meta.node_count ?? "--")} source nodes`,
      payload.expansion?.truncated ? `${formatCount(payload.expansion.truncated)} expansion results hidden by cap` : "",
    ].filter(Boolean).join(" - ");

    if (payload.status !== "ok" || !nodes.length || !edges.length) {
      destroyKnowledgeGraph();
      els.kgGraph.classList.add("empty");
      els.kgGraph.textContent = payload.reason || "No graph payload is available for the latest run.";
      renderKnowledgeGraphDetail();
      return;
    }

    if (els.systemDrawer.classList.contains("hidden")) {
      return;
    }

    if (!window.cytoscape) {
      destroyKnowledgeGraph();
      els.kgGraph.classList.add("empty");
      els.kgGraph.textContent = "Graph renderer did not load.";
      renderKnowledgeGraphDetail();
      return;
    }

    els.kgGraph.classList.remove("empty");
    els.kgGraph.textContent = "";
    destroyKnowledgeGraph();
    const maxRecoverable = nodes.reduce((max, node) => Math.max(max, Number(node.recoverable_sar || 0)), 0);
    state.kgCy = window.cytoscape({
      container: els.kgGraph,
      elements: kgElements(payload),
      style: kgStyle(maxRecoverable),
      layout: {
        name: "cose",
        animate: false,
        fit: true,
        padding: 28,
        nodeRepulsion: 9000,
        idealEdgeLength: 110,
        componentSpacing: 90,
      },
    });
    state.kgCy.on("tap", "node", (event) => {
      const nodePayload = event.target.data("payload");
      state.kgSelectedId = nodePayload?.id || "";
      renderKnowledgeGraphDetail(nodePayload);
      const neighborhood = event.target.closedNeighborhood();
      state.kgCy.elements().addClass("faded");
      neighborhood.removeClass("faded");
      if (nodePayload?.label === "Vendor") {
        expandKnowledgeGraph(nodePayload.id);
      }
    });
    state.kgCy.on("tap", (event) => {
      if (event.target !== state.kgCy) return;
      state.kgCy.elements().removeClass("faded");
    });
    renderKnowledgeGraphDetail();
    focusKnowledgeGraphSelection();
  }

  function focusKnowledgeGraphSelection() {
    if (!state.kgCy || !state.kgSelectedId) return;
    const node = state.kgCy.getElementById(state.kgSelectedId);
    if (!node || !node.length) return;
    node.select();
    state.kgCy.center(node);
    state.kgCy.animate({ zoom: Math.max(state.kgCy.zoom(), 1.25), center: { eles: node } }, { duration: 250 });
  }

  async function refreshKnowledgeGraph(expandId = "") {
    state.kgLoading = true;
    renderKnowledgeGraph();
    try {
      const params = new URLSearchParams();
      if (expandId) params.set("expand", expandId);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      state.knowledgeGraph = await requestJson(`/runs/latest/knowledge-graph${suffix}`);
    } catch (error) {
      state.knowledgeGraph = {
        status: "failed",
        reason: error?.message || "Knowledge graph request failed.",
        nodes: [],
        edges: [],
        meta: {},
      };
    } finally {
      state.kgLoading = false;
      renderKnowledgeGraph();
    }
  }

  async function expandKnowledgeGraph(nodeId) {
    if (!nodeId || state.kgLoading || state.knowledgeGraph?.expansion?.node_id === nodeId) return;
    state.kgSelectedId = nodeId;
    await refreshKnowledgeGraph(nodeId);
  }

  async function focusKnowledgeGraphNode(nodeId) {
    if (!nodeId) return;
    openDrawer("system", "kg-panel");
    state.kgSelectedId = nodeId;
    if (!state.knowledgeGraph || state.knowledgeGraph.status === "idle") {
      await refreshKnowledgeGraph();
    }
    renderKnowledgeGraph();
  }

  function kvHtml(rows, trustedValues = false) {
    return rows.map(([key, value]) => (
      `<div><dt>${escapeHtml(key)}</dt><dd>${trustedValues ? value : escapeHtml(value)}</dd></div>`
    )).join("");
  }

  function renderHealth() {
    if (!isAuthed()) {
      els.healthSummary.textContent = "Connect a session to inspect readiness.";
      els.healthChecksKv.innerHTML = "";
      els.healthConfigKv.innerHTML = "";
      els.healthPayloadPreview.textContent = "Authentication required.";
      return;
    }
    const live = state.liveStatus;
    const ready = state.readyStatus;
    const config = state.configStatus;
    const dependencies = state.dependenciesStatus;
    els.healthSummary.innerHTML = [
      `Live ${statusPill(live?.status || "unknown")}`,
      `Ready ${statusPill(ready?.status || "unknown")}`,
      `Config ${statusPill(config?.status || "unknown")}`,
    ].join(" ");
    const checks = ready?.checks || {};
    els.healthChecksKv.innerHTML = kvHtml([
      ["Postgres", statusPill(checks.postgres?.status || "unknown")],
      ["Redis", statusPill(checks.redis?.status || "unknown")],
      ["Neo4j / Qdrant", `${escapeHtml(checks.neo4j?.status || "unknown")} / ${escapeHtml(checks.qdrant?.status || "unknown")}`],
      ["OCR runtime", statusPill(dependencies?.status || checks.ocr_runtime?.status || "unknown")],
    ], true);
    els.healthConfigKv.innerHTML = kvHtml([
      ["API auth", statusPill((config?.api_auth_enabled ?? bootstrap.api_auth_enabled) ? "enabled" : "disabled")],
      ["Human review", statusPill((config?.require_human_review ?? bootstrap.require_human_review) ? "required" : "optional")],
      ["LLM chat", statusPill(config?.llm_chat?.enabled ? "enabled" : "disabled")],
      ["Public live health", statusPill((live?.public_health_enabled ?? bootstrap.public_health_enabled) ? "enabled" : "protected")],
      ["Object store", statusPill(config?.object_store?.status || "unknown")],
    ], true);
    els.healthPayloadPreview.textContent = compactJson(sanitizeUiPayload({ live, ready, config, dependencies }));
  }

  function renderArtifacts() {
    const contract = state.workspaceContract || {};
    const evidence = Array.isArray(contract.evidence?.artifacts) ? contract.evidence.artifacts : [];
    const reports = Array.isArray(contract.reports?.artifacts) ? contract.reports.artifacts : [];
    const contractEntries = evidence.concat(reports).filter((item) => item?.artifact_key);
    const fallbackEntries = Object.entries(state.latestRun?.artifacts || {}).map(([artifact_key, path]) => ({ artifact_key, title: humanizeToken(artifact_key), category: "artifact", restricted: false, path }));
    const entries = contractEntries.length ? contractEntries : fallbackEntries;
    if (!entries.length) {
      els.artifactTabs.innerHTML = '<span class="muted">No artifacts are listed for the latest run.</span>';
      els.artifactViewer.textContent = "No artifact payload.";
      return;
    }
    els.artifactTabs.innerHTML = entries.map((item) => (
      `<button class="btn secondary" type="button" data-artifact-key="${escapeHtml(item.artifact_key)}">${escapeHtml(item.title || item.artifact_key)} · ${escapeHtml(humanizeToken(item.category || "artifact"))}${item.restricted ? " · Restricted" : ""}</button>`
    )).join("");
    if (els.artifactViewer.textContent === "Select a run artifact." || els.artifactViewer.textContent === "No artifact payload.") {
      const first = entries[0];
      els.artifactViewer.textContent = compactJson(first);
    }
  }

  async function openArtifact(key) {
    const contract = state.workspaceContract || {};
    const catalog = []
      .concat(Array.isArray(contract.evidence?.artifacts) ? contract.evidence.artifacts : [])
      .concat(Array.isArray(contract.reports?.artifacts) ? contract.reports.artifacts : []);
    const selected = catalog.find((item) => item?.artifact_key === key) || null;
    const path = selected?.path || state.latestRun?.artifacts?.[key];
    if (!path && !selected) return;
    els.artifactViewer.textContent = compactJson(selected || { artifact_key: key, path });
    if (!activeRunId()) return;
    try {
      const payload = await requestJson(`${reviewArtifactBaseRoute()}/${encodeURIComponent(activeRunId())}/artifacts/${encodeURIComponent(key)}`);
      els.artifactViewer.textContent = compactJson(payload);
    } catch (error) {
      els.artifactViewer.textContent = compactJson({
        artifact_key: key,
        path,
        preview_error: error?.message || "Artifact preview unavailable.",
      });
    }
  }

  function renderVectorSearch() {
    const vector = state.vectorSearch;
    if (vector.status === "idle") {
      els.vectorSearchResults.innerHTML = '<div class="item"><strong>No vector search yet</strong><span class="muted">Submit a query to inspect ranked hits.</span></div>';
      els.vectorSearchPayloadPreview.textContent = "Awaiting vector search payload.";
      els.vectorSearchEvidencePreview.textContent = "Select a search result evidence link.";
      return;
    }
    if (vector.status === "loading") {
      els.vectorSearchResults.innerHTML = '<div class="item"><strong>Searching</strong><span class="muted">Querying /data/vector-search.</span></div>';
      return;
    }
    const results = vector.payload?.results || [];
    if (!results.length) {
      els.vectorSearchResults.innerHTML = `<div class="item"><strong>No hits</strong><span class="muted">${escapeHtml(vector.error || "No ranked hits returned.")}</span></div>`;
    } else {
      els.vectorSearchResults.innerHTML = results.map((item, index) => (
        vectorSearchResultHtml(item, index)
      )).join("");
    }
    renderVectorEvidence();
    els.vectorSearchPayloadPreview.textContent = compactJson(vector.payload);
  }

  function vectorSearchResultHtml(item, index) {
    const score = Number(item.score);
    const scoreLabel = Number.isFinite(score) ? score.toFixed(3) : "--";
    const type = String(item.result_type || "finding").replaceAll("_", " ");
    const title = item.title || item.finding_id || "Search result";
    const meta = [
      type,
      item.finding_id,
      item.pattern_type,
      item.vendor_name,
      item.confidence,
      item.source_path ? basename(item.source_path) : "",
      item.locator,
      `score ${scoreLabel}`,
    ].filter(Boolean);
    const evidence = item.open_evidence?.href
      ? `<button class="btn secondary" type="button" data-open-evidence="${escapeHtml(item.open_evidence.href)}">Open evidence</button>`
      : "";
    return `<div class="item">
      <strong>${index + 1}. ${escapeHtml(title)}</strong>
      <span>${escapeHtml(item.excerpt || item.summary || item.text || "Search hit")}</span>
      <div class="item-meta">${meta.map((value) => `<span>${escapeHtml(value)}</span>`).join("")}</div>
      ${evidence ? `<div class="item-actions">${evidence}</div>` : ""}
    </div>`;
  }

  function renderVectorEvidence() {
    const evidence = state.vectorEvidence;
    if (evidence.status === "idle") {
      els.vectorSearchEvidencePreview.textContent = "Select a search result evidence link.";
      return;
    }
    if (evidence.status === "loading") {
      els.vectorSearchEvidencePreview.textContent = "Loading evidence preview.";
      return;
    }
    els.vectorSearchEvidencePreview.textContent = compactJson(evidence.payload || {
      status: evidence.status,
      error: evidence.error,
    });
  }

  async function openSearchEvidence(href) {
    if (!href) return;
    state.vectorEvidence = { status: "loading", payload: null, error: "" };
    renderVectorEvidence();
    try {
      const payload = await requestJson(href);
      state.vectorEvidence = { status: "ready", payload, error: payload.reason || "" };
    } catch (error) {
      state.vectorEvidence = {
        status: "failed",
        payload: error?.payload || { status: "failed", detail: error?.message || "Evidence preview failed." },
        error: error?.message || "Evidence preview failed.",
      };
    }
    renderVectorEvidence();
  }

  async function submitVectorSearch(event) {
    event?.preventDefault?.();
    const query = els.vectorSearchQuery.value.trim();
    if (!query) return;
    const limit = Math.max(1, Math.min(50, Number(els.vectorSearchLimit.value || 5)));
    state.vectorSearch = { status: "loading", payload: null, error: "" };
    state.vectorEvidence = { status: "idle", payload: null, error: "" };
    renderVectorSearch();
    try {
      const params = new URLSearchParams({ query, limit: String(limit) });
      const runId = activeRunId();
      if (runId) params.set("run_id", runId);
      const filterInputs = [
        ["point_type", els.vectorSearchType.value],
        ["pattern_type", els.vectorSearchPattern.value],
        ["vendor_name", els.vectorSearchVendor.value],
        ["confidence", els.vectorSearchConfidence.value],
        ["source_path", els.vectorSearchSource.value],
        ["finding_id", els.vectorSearchFinding.value],
      ];
      filterInputs.forEach(([key, value]) => {
        const normalized = String(value || "").trim();
        if (normalized) params.set(key, normalized);
      });
      const payload = await requestJson(`/data/vector-search?${params.toString()}`);
      state.vectorSearch = { status: "ready", payload, error: payload.reason || "" };
    } catch (error) {
      state.vectorSearch = {
        status: "failed",
        payload: error?.payload || { status: "failed", detail: error?.message || "Vector search failed." },
        error: error?.message || "Vector search failed.",
      };
    }
    renderVectorSearch();
  }

  function renderSourcePackPanel() {
    const operator = isOperator();
    const disabled = state.sourcePackSubmitting || !operator;
    [
      els.sourcePackFiles,
      els.sourcePackFolderFiles,
      els.sourcePackUploadSubmit,
      els.sourcePackPath,
      els.sourcePackPathSubmit,
      els.sourcePackValidate,
      els.startRunDataset,
      els.startRunRunDir,
      els.startRunSkipPrepare,
      els.startRunSyncArtifacts,
      els.startRunAllowPartialSourcePack,
      els.startRunSubmit,
    ].forEach((node) => {
      if (node) node.disabled = disabled;
    });
    els.sourcePackValidate.disabled = disabled || !state.sourcePack?.source_pack_id;
    const canStart = canStartRunFromCurrentInputs();
    els.startRunSubmit.disabled = disabled || state.runSubmitting || !canStart;
    els.startRunSubmit.title = canStart ? "" : startRunDisabledReason();

    const payload = state.sourcePack;
    if (!payload) {
      if (!state.sourcePackSubmitting) {
        setSourcePackStatus("not_started", "Ready", "Pick a .zip or a folder above, then start analysis.");
      }
      els.sourcePackSummary.textContent = "";
      els.sourcePackManifestBody.innerHTML = '<tr><td colspan="5" class="muted">No file details yet.</td></tr>';
      els.sourcePackMappings.innerHTML = "";
      els.sourcePackReadiness.innerHTML = "";
      return;
    }

    if (!state.sourcePackSubmitting) {
      renderSourcePackStatus(payload);
    }
    const summary = payload.manifest_summary || {};
    els.sourcePackSummary.innerHTML = [
      "<strong>Selected files</strong>",
      `${formatCount(summary.file_count)} total files`,
      `${formatCount(summary.supported_count)} supported`,
      `${formatCount(summary.unsupported_count)} unsupported`,
    ].join(" - ");

    const manifest = Array.isArray(payload.manifest) ? payload.manifest : [];
    els.sourcePackManifestBody.innerHTML = manifest.length
      ? manifest.slice(0, 12).map((item) => `
        <tr>
          <td><span class="mono">${escapeHtml(item.source_id || "--")}</span></td>
          <td><span class="mono">${escapeHtml(item.relative_path || "--")}</span></td>
          <td>${escapeHtml(item.file_type_hint || "unknown")}</td>
          <td>${statusPill(item.supported ? "supported" : "unsupported")}</td>
          <td>${statusPill(item.extraction_status || "unknown")}</td>
        </tr>`).join("")
      : '<tr><td colspan="5" class="muted">No file details yet.</td></tr>';

    renderSourcePackMappings(manifest);
    renderSourcePackReadiness(payload.task_readiness || {});
  }

  function hasUnconfirmedMappings() {
    const unconfirmed = state.sourcePack?.task_readiness?.unconfirmed_roles || [];
    return Array.isArray(unconfirmed) && unconfirmed.length > 0;
  }

  function sourcePackNeedsPartialRun(payload) {
    const readiness = payload?.task_readiness || {};
    return Boolean(payload)
      && !sourcePackHasNoReadableFiles(payload)
      && !readiness.ready_for_run;
  }

  function sourcePackCanStart(payload) {
    const readiness = payload?.task_readiness || {};
    if (!payload || sourcePackHasNoReadableFiles(payload) || hasUnconfirmedMappings()) return false;
    if (readiness.ready_for_run) return true;
    return Boolean(els.startRunAllowPartialSourcePack.checked);
  }

  function canStartRunFromCurrentInputs() {
    if (els.startRunDataset.value.trim()) return true;
    return sourcePackCanStart(state.sourcePack);
  }

  function startRunDisabledReason() {
    if (!isOperator()) return "Operator role required.";
    if (state.runSubmitting) return "Analysis is already starting.";
    if (!state.sourcePack && !els.startRunDataset.value.trim()) return "Choose files before starting analysis.";
    if (state.sourcePack && sourcePackHasNoReadableFiles(state.sourcePack)) return "No readable finance files were found.";
    if (hasUnconfirmedMappings()) return "Confirm the suggested column mappings first.";
    if (sourcePackNeedsPartialRun(state.sourcePack) && !els.startRunAllowPartialSourcePack.checked) {
      return "Required finance files are missing. Use a complete file set or enable partial analysis in Advanced settings.";
    }
    return "Choose files before starting analysis.";
  }

  function renderSourcePackStatus(payload) {
    const readiness = payload?.task_readiness || {};
    const reasons = sourcePackBlockingReasons(payload);
    if (sourcePackHasNoReadableFiles(payload)) {
      setSourcePackStatus("danger", "No readable finance files", "Upload invoices, ledgers, statements, ERP exports, or use the sample dataset.");
    } else if (hasUnconfirmedMappings()) {
      setSourcePackStatus("warn", "Column check needed", "Confirm the suggested spreadsheet columns before starting analysis.");
    } else if (readiness.ready_for_run) {
      setSourcePackStatus("ok", "Ready to analyze", "Start analysis when you are ready.");
    } else if (sourcePackNeedsPartialRun(payload) && els.startRunAllowPartialSourcePack.checked) {
      setSourcePackStatus("warn", "Partial analysis selected", "StrategyOS will analyze the readable files and clearly report missing roles.");
    } else {
      setSourcePackStatus("warn", "More finance files needed", reasons.join(" ") || "Some required finance files are missing.");
    }
  }

  function renderSourcePackMappings(manifest) {
    const candidates = manifest.filter((item) => item.classification?.status === "candidate");
    const prefix = hasUnconfirmedMappings()
      ? `<div class="item"><strong>Column confirmation required</strong><span>${escapeHtml(state.sourcePack.task_readiness.unconfirmed_roles.join(", "))}</span></div>`
      : "";
    if (!candidates.length) {
      els.sourcePackMappings.innerHTML = prefix;
      return;
    }
    els.sourcePackMappings.innerHTML = prefix + candidates.map((item, index) => {
      const classification = item.classification || {};
      const proposal = classification.column_mapping_proposal || {};
      const proposed = proposal.column_mapping || {};
      const sourceColumns = Array.isArray(proposal.source_columns) ? proposal.source_columns : [];
      const canonicalColumns = Array.from(new Set(Object.keys(proposed).concat(proposal.missing_required || [])));
      const role = classification.role || proposal.role || "";
      const rel = item.relative_path || "";
      const selects = canonicalColumns.length
        ? canonicalColumns.map((canonical) => {
          const chosen = proposed[canonical] || "";
          const options = ['<option value="">-- unmapped --</option>'].concat(sourceColumns.map((sourceColumn) => (
            `<option value="${escapeHtml(sourceColumn)}" ${sourceColumn === chosen ? "selected" : ""}>${escapeHtml(sourceColumn)}</option>`
          ))).join("");
          return `<label>${escapeHtml(canonical)}<select class="mapping-select" data-canonical="${escapeHtml(canonical)}">${options}</select></label>`;
        }).join("")
        : '<span class="muted">No column proposal returned.</span>';
      return `
        <div class="item" data-mapping-row="true" data-rel="${escapeHtml(encodeURIComponent(rel))}" data-role="${escapeHtml(role)}" id="source-pack-mapping-${index}">
          <strong>${escapeHtml(rel || "source")}</strong>
          <span>${statusPill(role || "candidate")} ${statusPill("pending", "needs confirmation")}</span>
          <div class="form-stack">${selects}</div>
          <button class="btn secondary" type="button" data-confirm-mapping="source-pack-mapping-${index}">Confirm columns</button>
        </div>`;
    }).join("");
  }

  function renderSourcePackReadiness(readiness) {
    const tasks = Array.isArray(readiness.tasks) ? readiness.tasks : [];
    els.sourcePackReadiness.innerHTML = tasks.length
      ? tasks.map((item) => (
        `<div class="item"><strong>${escapeHtml(item.label || item.task_key || "Task")}</strong><span>${statusPill(item.status || "unknown")}</span><span class="muted">${escapeHtml((item.reasons || []).join(" | ") || "No readiness details.")}</span></div>`
      )).join("")
      : "";
  }

  function setSourcePackStatus(tone, title, message) {
    els.sourcePackStatus.innerHTML = `${statusPill(tone, title)} ${escapeHtml(message || "")}`;
  }

  function setStartRunStatus(tone, title, message) {
    els.startRunStatus.classList.remove("hidden");
    els.startRunStatus.innerHTML = `${statusPill(tone, title)} ${escapeHtml(message || "")}`;
  }

  async function submitSourcePackUpload(event) {
    event?.preventDefault?.();
    if (!isOperator()) return;
    const files = [
      ...Array.from(els.sourcePackFiles.files || []),
      ...Array.from(els.sourcePackFolderFiles.files || []),
    ];
    if (!files.length) {
      setSourcePackStatus("warn", "No files selected", "Choose a zip file or folder before uploading.");
      return;
    }
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file, file.webkitRelativePath || file.name));
    state.sourcePackSubmitting = true;
    setSourcePackStatus("warn", "Starting", "Uploading and checking files.");
    renderSourcePackPanel();
    let shouldStart = false;
    try {
      state.sourcePack = await requestMultipart("/source-packs", formData);
      shouldStart = sourcePackCanStart(state.sourcePack);
      renderSourcePackStatus(state.sourcePack);
    } catch (error) {
      setSourcePackStatus("danger", "Upload failed", error?.message || "Unable to upload source pack.");
    } finally {
      state.sourcePackSubmitting = false;
      renderSourcePackPanel();
    }
    if (shouldStart) {
      await submitStartRun();
    }
  }

  async function submitSourcePackPath(event) {
    event?.preventDefault?.();
    if (!isOperator()) return;
    const folderPath = els.sourcePackPath.value.trim();
    if (!folderPath) {
      setSourcePackStatus("warn", "No path", "Enter a workspace-bounded folder path.");
      return;
    }
    state.sourcePackSubmitting = true;
    setSourcePackStatus("warn", "Checking folder", "Reading files from the selected server folder.");
    renderSourcePackPanel();
    try {
      state.sourcePack = await requestJson("/source-packs/from-path", {
        method: "POST",
        body: JSON.stringify({ folder_path: folderPath }),
      });
      renderSourcePackStatus(state.sourcePack);
    } catch (error) {
      setSourcePackStatus("danger", "Staging failed", error?.message || "Unable to stage source pack.");
    } finally {
      state.sourcePackSubmitting = false;
      renderSourcePackPanel();
    }
  }

  async function revalidateSourcePack() {
    if (!isOperator()) return;
    const sourcePackId = state.sourcePack?.source_pack_id;
    if (!sourcePackId) {
      setSourcePackStatus("warn", "No source pack", "Upload or stage a source pack first.");
      return;
    }
    state.sourcePackSubmitting = true;
    setSourcePackStatus("warn", "Rechecking files", "Refreshing file readiness.");
    renderSourcePackPanel();
    try {
      state.sourcePack = await requestJson("/source-packs/validate", {
        method: "POST",
        body: JSON.stringify({ source_pack_id: sourcePackId }),
      });
      renderSourcePackStatus(state.sourcePack);
    } catch (error) {
      setSourcePackStatus("danger", "Validation failed", error?.message || "Unable to validate source pack.");
    } finally {
      state.sourcePackSubmitting = false;
      renderSourcePackPanel();
    }
  }

  async function confirmSourcePackMapping(rowId) {
    if (!isOperator()) return;
    const sourcePackId = state.sourcePack?.source_pack_id;
    const row = byId(rowId);
    if (!sourcePackId || !row) return;
    const body = {
      source_pack_id: sourcePackId,
      relative_path: decodeURIComponent(row.getAttribute("data-rel") || ""),
    };
    const role = row.getAttribute("data-role") || "";
    if (role) body.role = role;
    const columnMapping = {};
    row.querySelectorAll("select.mapping-select").forEach((select) => {
      const canonical = select.getAttribute("data-canonical");
      if (canonical && select.value) columnMapping[canonical] = select.value;
    });
    if (Object.keys(columnMapping).length) body.column_mapping = columnMapping;
    state.sourcePackSubmitting = true;
    setSourcePackStatus("warn", "Confirming columns", `Applying choices for ${body.relative_path}.`);
    renderSourcePackPanel();
    try {
      state.sourcePack = await requestJson("/source-packs/confirm-mapping", {
        method: "POST",
        body: JSON.stringify(body),
      });
      renderSourcePackStatus(state.sourcePack);
    } catch (error) {
      setSourcePackStatus("danger", "Confirmation failed", error?.message || "Unable to confirm mapping.");
    } finally {
      state.sourcePackSubmitting = false;
      renderSourcePackPanel();
    }
  }

  async function submitStartRun(event) {
    event?.preventDefault?.();
    if (!isOperator()) return;
    if (!canStartRunFromCurrentInputs()) {
      setStartRunStatus("warn", "Cannot start yet", startRunDisabledReason());
      return;
    }
    const datasetInput = els.startRunDataset.value.trim();
    const payload = {
      dataset: datasetInput || null,
      source_pack_id: datasetInput ? null : state.sourcePack?.source_pack_id || null,
      run_dir: els.startRunRunDir.value.trim() || null,
      skip_prepare: els.startRunSkipPrepare.checked,
      sync_artifacts: els.startRunSyncArtifacts.checked,
      allow_partial_source_pack: els.startRunAllowPartialSourcePack.checked,
    };
    if (!payload.dataset && !payload.source_pack_id) payload.skip_prepare = true;
    state.runSubmitting = true;
    setStartRunStatus("warn", "Starting analysis", "StrategyOS is analyzing the selected files.");
    renderSourcePackPanel();
    try {
      const result = await requestJson("/runs", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (result.execution_mode === "hatchet" && result.job_id) {
        state.latestJob = result;
        setStartRunStatus("ok", "Analysis queued", `${displayRunId(result)} is waiting for a StrategyOS worker.`);
      } else {
        state.latestJob = null;
        setStartRunStatus("ok", "Analysis started", `Current run ${displayRunId(result)} is now running.`);
      }
      closeDrawer("new-run");
      await refreshAll();
    } catch (error) {
      setStartRunStatus("danger", "Run failed", error?.message || "Unable to start run.");
    } finally {
      state.runSubmitting = false;
      renderSourcePackPanel();
    }
  }

  async function sendReviewDecision(decision) {
    const runId = activeRunId();
    if (!runId || !isReviewer()) return;
    const comment = els.reviewComment.value.trim();
    try {
      if (!isLocalRunId(runId)) {
        await requestJson(`/reviewer/runs/${encodeURIComponent(runId)}/claim`, { method: "POST" });
      }
      await requestJson(`/reviewer/runs/${encodeURIComponent(runId)}/${decision}`, {
        method: "POST",
        body: JSON.stringify({ comment }),
      });
      state.chatThread.push({ type: "system", text: `Reviewer ${decision} recorded for run ${displayRunId(state.latestRun)}.` });
      saveChat();
      await refreshAll();
    } catch (error) {
      state.chatThread.push({ type: "system", text: error?.message || `Review ${decision} failed.` });
      saveChat();
      renderChat();
    }
  }

  async function resumeRun() {
    if (!activeRunId() || !isOperator()) return;
    try {
      await requestJson(`/operator/runs/${encodeURIComponent(activeRunId())}/resume`, { method: "POST" });
      state.chatThread.push({ type: "system", text: `Operator resume requested for run ${displayRunId(state.latestRun)}.` });
      saveChat();
      await refreshAll();
    } catch (error) {
      state.chatThread.push({ type: "system", text: error?.message || "Resume failed." });
      saveChat();
      renderChat();
    }
  }

  function drawerByName(name) {
    if (name === "system") return els.systemDrawer;
    if (name === "finding") return els.findingDrawer;
    return els.newRunDrawer;
  }

  function openDrawer(name, targetId = "") {
    const drawer = drawerByName(name);
    if (!drawer) return;
    // Only one drawer open at a time.
    [els.systemDrawer, els.newRunDrawer, els.findingDrawer].forEach((other) => {
      if (other && other !== drawer) other.classList.add("hidden");
    });
    drawer.classList.remove("hidden");
    if (name === "system") {
      requestAnimationFrame(renderKnowledgeGraph);
    }
    if (targetId) {
      requestAnimationFrame(() => {
        document.getElementById(targetId)?.scrollIntoView({ block: "start" });
      });
    }
  }

  function closeDrawer(name) {
    const drawer = drawerByName(name);
    if (drawer) drawer.classList.add("hidden");
  }

  async function loadSession() {
    try {
      state.session = await requestJson("/ui/session");
    } catch (_error) {
      state.session = {
        authenticated: false,
        role: "anonymous",
        subject: "anonymous",
        api_auth_enabled: bootstrap.api_auth_enabled,
      };
    }
    renderSession();
  }

  async function readinessProbe() {
    try {
      return await requestJson("/health/ready");
    } catch (error) {
      if (error.status === 503 && error.payload?.status) return error.payload;
      throw error;
    }
  }

  async function guarded(label, promise, fallback) {
    try {
      return await promise;
    } catch (error) {
      const base = fallback && typeof fallback === "object" ? fallback : {};
      return { ...base, status: base.status || "failed", reason: `${label}: ${error?.message || "failed"}` };
    }
  }

  async function loadRuntimeData() {
    if (!isAuthed()) {
      state.latestRun = null;
      state.latestJob = null;
      state.auditSummary = null;
      state.dataStatus = null;
      state.knowledgeGraph = null;
      state.liveStatus = null;
      state.readyStatus = null;
      state.configStatus = null;
      state.dependenciesStatus = null;
      state.connectorCatalog = null;
      state.workspaceContract = null;
      renderAll();
      return;
    }
    const previousSignature = state.lastRunSignature;
    const buRole = roleHasAny(currentRole(), "bu") && !roleHasAny(currentRole(), "reviewer", "operator", "tenant_admin", "system");
    const [latestRun, auditSummary, findings, history, dataStatus, knowledgeGraph, liveStatus, readyStatus, configStatus, dependenciesStatus, connectorCatalog, workspaceContract] = await Promise.all([
      guarded("Latest run", requestJson("/runs/latest"), { status: "missing" }),
      guarded("Audit summary", requestJson("/runs/latest/audit-summary"), { status: "missing" }),
      guarded("Findings", requestJson("/runs/latest/findings"), { status: "missing", findings: [] }),
      guarded("Run history", requestJson("/runs/history"), { status: "empty", history: [] }),
      buRole ? Promise.resolve(null) : guarded("Data status", requestJson("/data/status"), null),
      buRole ? Promise.resolve({ status: "restricted", reason: "Knowledge graph stays outside the bounded BU lane." }) : guarded("Knowledge graph", requestJson("/runs/latest/knowledge-graph"), { status: "missing", nodes: [], edges: [], meta: {} }),
      buRole ? Promise.resolve(null) : guarded("Live health", requestJson("/health/live"), null),
      buRole ? Promise.resolve(null) : guarded("Readiness", readinessProbe(), null),
      buRole ? Promise.resolve(null) : guarded("Config", requestJson("/health/config"), null),
      buRole ? Promise.resolve(null) : guarded("Dependencies", requestJson("/health/dependencies"), null),
      buRole ? Promise.resolve(null) : guarded("Connector catalog", requestJson("/ingestion/connectors"), null),
      guarded("Workspace contract", requestJson("/ui/workspace-contract/latest"), null),
    ]);
    state.latestRun = latestRun;
    state.auditSummary = auditSummary;
    state.findings = findings;
    state.history = history;
    state.dataStatus = dataStatus;
    state.knowledgeGraph = knowledgeGraph;
    state.liveStatus = liveStatus;
    state.readyStatus = readyStatus;
    state.configStatus = configStatus;
    state.dependenciesStatus = dependenciesStatus;
    state.connectorCatalog = connectorCatalog;
    state.workspaceContract = workspaceContract;
    if (state.latestJob?.job_id && ["queued", "running"].includes(String(state.latestJob.status || "").toLowerCase())) {
      state.latestJob = await guarded(
        "Run job",
        requestJson(`/runs/jobs/${encodeURIComponent(state.latestJob.job_id)}`),
        state.latestJob,
      );
    }
    maybeAppendRunEvent(previousSignature);
    renderAll();
    const nextFinding = activeFindingRecord()?.finding_id || currentScopeFindings()[0]?.finding_id || "";
    if (nextFinding && (!state.drilldownEvidence.payload || state.selectedFindingId !== nextFinding)) {
      syncSharedDrilldown(nextFinding);
    }
  }

  function renderAll() {
    renderSession();
    renderDashboard();
    renderTrend();
    renderFindings();
    renderRoleTasks();
    renderAdminContext();
    renderSystemWorkflow();
    renderPublicationGovernance();
    renderConnectors();
    renderDataStatus();
    renderKnowledgeGraph();
    renderHealth();
    renderVectorSearch();
    renderSourcePackPanel();
    renderChat();
    renderRoleSurfaces();
    applyLaneHint();
  }

  async function refreshAll() {
    await loadSession();
    await loadRuntimeData();
    schedulePoll();
  }

  function schedulePoll() {
    window.clearTimeout(state.pollTimer);
    if (document.visibilityState === "hidden") return;
    const status = String(state.latestRun?.status || "").toLowerCase();
    const jobStatus = String(state.latestJob?.status || "").toLowerCase();
    const delay = ["running", "awaiting_review"].includes(status) || ["queued", "running"].includes(jobStatus) ? 5000 : 30000;
    state.pollTimer = window.setTimeout(() => {
      loadRuntimeData().then(schedulePoll).catch(() => schedulePoll());
    }, delay);
  }

  function bindEvents() {
    els.companySwitcher?.addEventListener("change", (event) => {
      state.selectedCompany = event.target.value || "current";
      renderRoleSurfaces();
    });
    els.portfolioSwitcher?.addEventListener("change", (event) => {
      state.selectedPortfolio = event.target.value || "all";
      state.selectedDomain = "all";
      const nextFinding = currentScopeFindings()[0]?.finding_id || "";
      syncSharedDrilldown(nextFinding);
    });
    els.connectButton.addEventListener("click", async () => {
      state.token = els.sessionToken.value.trim();
      if (state.token) window.localStorage.setItem(TOKEN_KEY, state.token);
      else window.localStorage.removeItem(TOKEN_KEY);
      await refreshAll();
    });
    els.clearButton.addEventListener("click", async () => {
      state.token = "";
      state.session = null;
      window.localStorage.removeItem(TOKEN_KEY);
      await refreshAll();
    });
    els.chatForm.addEventListener("submit", submitChat);
    els.qaModeSwitch.addEventListener("click", (event) => {
      const button = event.target.closest("[data-qa-mode]");
      if (!button || button.disabled) return;
      setQaMode(button.getAttribute("data-qa-mode") || "deterministic");
      renderChat();
    });
    els.chatThread.addEventListener("click", (event) => {
      const graphNode = event.target.closest("[data-kg-node]");
      if (graphNode) {
        focusKnowledgeGraphNode(graphNode.getAttribute("data-kg-node") || "");
        return;
      }
      const suggestion = event.target.closest("[data-suggestion]");
      if (suggestion) {
        setSuggestion(suggestion.getAttribute("data-suggestion") || "");
        return;
      }
      const citation = event.target.closest("[data-citation-key]");
      if (citation) {
        const key = citation.getAttribute("data-citation-key") || "";
        state.openCitationKey = state.openCitationKey === key ? "" : key;
        renderChat();
      }
    });
    if (els.findingsList) {
      els.findingsList.addEventListener("click", (event) => {
        const row = event.target.closest("[data-finding-id]");
        if (row) {
          const findingId = row.getAttribute("data-finding-id") || "";
          syncSharedDrilldown(findingId);
          openFindingDetail(findingId);
        }
      });
      els.findingsList.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const row = event.target.closest("[data-finding-id]");
        if (row) {
          event.preventDefault();
          const findingId = row.getAttribute("data-finding-id") || "";
          syncSharedDrilldown(findingId);
          openFindingDetail(findingId);
        }
      });
    }
    els.buDomainFilters?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-domain-filter]");
      if (!button) return;
      state.selectedDomain = button.getAttribute("data-domain-filter") || "all";
      const nextFinding = currentScopeFindings()[0]?.finding_id || "";
      syncSharedDrilldown(nextFinding);
    });
    els.buCaseList?.addEventListener("click", (event) => {
      const row = event.target.closest("[data-bu-finding-id]");
      if (!row) return;
      const findingId = row.getAttribute("data-bu-finding-id") || "";
      syncSharedDrilldown(findingId);
      openFindingDetail(findingId);
    });
    els.drilldownReportList?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-drilldown-report]");
      if (button) loadDrilldownReport(button.getAttribute("data-drilldown-report") || "");
    });
    if (els.findingDrawerClose) {
      els.findingDrawerClose.addEventListener("click", () => closeDrawer("finding"));
    }
    if (els.findingDetailGraph) {
      els.findingDetailGraph.addEventListener("click", () => {
        const nodeId = els.findingDetailGraph.dataset.kgNode || "";
        if (nodeId) {
          closeDrawer("finding");
          focusKnowledgeGraphNode(nodeId);
        }
      });
    }
    els.newRunButton.addEventListener("click", () => {
      const lane = isAuthDisabled() ? "shared" : preferredLaneForRole(currentRole());
      if (lane === "review") {
        document.getElementById("review")?.scrollIntoView({ block: "start" });
        return;
      }
      if (lane === "system") {
        openDrawer("system", "system-workflow-panel");
        return;
      }
      openDrawer("new-run", "source-pack-section");
    });
    els.startRunCancel.addEventListener("click", () => closeDrawer("new-run"));
    els.systemDrawerButton.addEventListener("click", () => openDrawer("system"));
    els.systemDrawerClose.addEventListener("click", () => closeDrawer("system"));
    els.systemWorkflowList.addEventListener("click", (event) => {
      const button = event.target.closest("[data-workflow-target]");
      if (button) openDrawer("system", button.getAttribute("data-workflow-target") || "system-workflow-panel");
    });
    document.querySelectorAll("[data-open-drawer]").forEach((node) => {
      node.addEventListener("click", () => {
        const drawerName = node.getAttribute("data-open-drawer") || "system";
        const targetId = node.getAttribute("data-drawer-target") || "";
        openDrawer(drawerName, targetId);
      });
    });
    document.querySelectorAll("[data-close-drawer]").forEach((node) => {
      node.addEventListener("click", () => closeDrawer(node.getAttribute("data-close-drawer")));
    });
    els.sourcePackUploadForm.addEventListener("submit", submitSourcePackUpload);
    els.sourcePackPathForm.addEventListener("submit", submitSourcePackPath);
    els.sourcePackValidate.addEventListener("click", revalidateSourcePack);
    els.startRunDataset.addEventListener("input", renderSourcePackPanel);
    els.startRunAllowPartialSourcePack.addEventListener("change", renderSourcePackPanel);
    els.sourcePackMappings.addEventListener("click", (event) => {
      const button = event.target.closest("[data-confirm-mapping]");
      if (button) confirmSourcePackMapping(button.getAttribute("data-confirm-mapping"));
    });
    els.startRunForm.addEventListener("submit", submitStartRun);
    els.reviewApprove.addEventListener("click", () => sendReviewDecision("approve"));
    els.reviewReject.addEventListener("click", () => sendReviewDecision("reject"));
    els.reviewResume.addEventListener("click", resumeRun);
    els.reviewNewRun.addEventListener("click", () => openDrawer("new-run", "source-pack-section"));
    els.kgRefresh.addEventListener("click", () => refreshKnowledgeGraph());
    els.vectorSearchForm.addEventListener("submit", submitVectorSearch);
    els.vectorSearchResults.addEventListener("click", (event) => {
      const button = event.target.closest("[data-open-evidence]");
      if (button) openSearchEvidence(button.getAttribute("data-open-evidence"));
    });
    els.artifactTabs.addEventListener("click", (event) => {
      const button = event.target.closest("[data-artifact-key]");
      if (button) openArtifact(button.getAttribute("data-artifact-key"));
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        loadRuntimeData().then(schedulePoll).catch(schedulePoll);
      } else {
        window.clearTimeout(state.pollTimer);
      }
    });
  }

  bindEvents();
  renderAll();
  refreshAll().catch((error) => {
    showSignIn(error?.message || "Unable to load dashboard.");
    renderAll();
  });

  window.strategyosDashboard = {
    requestJson,
    submitChat,
    submitSourcePackUpload,
    submitSourcePackPath,
    revalidateSourcePack,
    confirmSourcePackMapping,
    submitStartRun,
    refreshKnowledgeGraph,
    focusKnowledgeGraphNode,
    activeQaRunId: activeRunId,
  };
})();
