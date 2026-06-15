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
    pollTimer: null,
    lastRunSignature: "",
  };

  const byId = (id) => document.getElementById(id);
  const els = {
    appName: byId("app-name"),
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
        : "Exact deterministic answers";
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

  function isAuthDisabled() {
    return Boolean(state.session?.auth_disabled) || !bootstrap.api_auth_enabled;
  }

  function isOperator() {
    return isAuthDisabled() || String(state.session?.role || "") === "operator";
  }

  function isReviewer() {
    return isAuthDisabled() || String(state.session?.role || "") === "reviewer";
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
      operator: "Operator",
      reviewer: "Reviewer",
      anonymous: "Anonymous",
      public: "Public",
    };
    return labels[normalized] || normalized.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase()) || "Unknown";
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
    if (["operator", "reviewer"].includes(role.toLowerCase())) return formatRoleLabel(role);
    return formatSubjectLabel(session?.subject, role);
  }

  function showSignIn(message) {
    if (!bootstrap.api_auth_enabled) return;
    els.signInPanel.classList.remove("hidden");
    els.sessionStatus.textContent = message || "Session not connected.";
  }

  function renderSession() {
    els.appName.textContent = bootstrap.product_name || "StrategyOS";
    els.environmentBadge.textContent = bootstrap.environment || "environment";
    els.sessionToken.value = state.token;
    const session = state.session || {};
    const role = session.role || "anonymous";
    const authDisabled = session.auth_disabled || !bootstrap.api_auth_enabled;
    const displayName = formatSessionIdentity(session);
    els.identity.textContent = authDisabled ? "Auth disabled" : session.authenticated ? displayName : "Not signed in";
    els.sessionStatus.textContent = authDisabled
      ? "API auth is disabled for this environment."
      : session.authenticated
        ? `Connected as ${displayName}.`
        : "Session not connected.";
    els.signInPanel.classList.toggle("hidden", authDisabled || Boolean(session.authenticated));
    els.newRunButton.disabled = !isOperator();
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

    const citations = citationSummary(run);
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
    const mode = run.run_mode && run.run_mode !== "full" ? "Partial analysis" : "Run diagnostics";
    els.partialRunChips.innerHTML = `<span class="pill warn" title="${escapeHtml(diagnostics.join("\n"))}">${escapeHtml(mode)}: ${formatCount(diagnostics.length)} items</span>`;
    els.partialRunChips.classList.remove("hidden");
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
          ${payload.intent ? `<span class="intent">${statusPill(unmatched ? "warn" : "ok", payload.intent)}</span>` : ""}
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
    els.chatInput.focus();
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
      els.kgSummary.textContent = "Connect a session to inspect the knowledge graph.";
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
    const artifacts = state.latestRun?.artifacts || {};
    const entries = Object.entries(artifacts);
    if (!entries.length) {
      els.artifactTabs.innerHTML = '<span class="muted">No artifacts are listed for the latest run.</span>';
      els.artifactViewer.textContent = "No artifact payload.";
      return;
    }
    els.artifactTabs.innerHTML = entries.map(([key]) => (
      `<button class="btn secondary" type="button" data-artifact-key="${escapeHtml(key)}">${escapeHtml(key)}</button>`
    )).join("");
    if (els.artifactViewer.textContent === "Select a run artifact." || els.artifactViewer.textContent === "No artifact payload.") {
      const [firstKey, firstPath] = entries[0];
      els.artifactViewer.textContent = compactJson({ artifact_key: firstKey, path: firstPath });
    }
  }

  async function openArtifact(key) {
    const artifacts = state.latestRun?.artifacts || {};
    const path = artifacts[key];
    if (!path) return;
    els.artifactViewer.textContent = compactJson({ artifact_key: key, path });
    if (!activeRunId()) return;
    try {
      const payload = await requestJson(`/reviewer/runs/${encodeURIComponent(activeRunId())}/artifacts/${encodeURIComponent(key)}`);
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
        setSourcePackStatus("not_started", "Choose files", "Upload a source zip or a folder of finance files.");
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

  function setRailActive(targetId) {
    if (!targetId) return;
    document.querySelectorAll(".rail-nav button").forEach((node) => {
      const matches = node.getAttribute("data-scroll-target") === targetId
        || node.getAttribute("data-drawer-target") === targetId;
      node.classList.toggle("active", matches);
    });
  }

  function scrollToWorkspaceTarget(targetId) {
    if (!targetId) return;
    els.systemDrawer.classList.add("hidden");
    els.newRunDrawer.classList.add("hidden");
    document.getElementById(targetId)?.scrollIntoView({ block: "start" });
    setRailActive(targetId);
  }

  function openDrawer(name, targetId = "") {
    const drawer = name === "system" ? els.systemDrawer : els.newRunDrawer;
    const otherDrawer = name === "system" ? els.newRunDrawer : els.systemDrawer;
    otherDrawer.classList.add("hidden");
    drawer.classList.remove("hidden");
    if (name === "system") {
      requestAnimationFrame(renderKnowledgeGraph);
    }
    if (targetId) {
      setRailActive(targetId);
      requestAnimationFrame(() => {
        document.getElementById(targetId)?.scrollIntoView({ block: "start" });
      });
    }
  }

  function closeDrawer(name) {
    const drawer = name === "system" ? els.systemDrawer : els.newRunDrawer;
    drawer.classList.add("hidden");
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
      renderAll();
      return;
    }
    const previousSignature = state.lastRunSignature;
    const [latestRun, auditSummary, dataStatus, knowledgeGraph, liveStatus, readyStatus, configStatus, dependenciesStatus] = await Promise.all([
      guarded("Latest run", requestJson("/runs/latest"), { status: "missing" }),
      guarded("Audit summary", requestJson("/runs/latest/audit-summary"), { status: "missing" }),
      guarded("Data status", requestJson("/data/status"), null),
      guarded("Knowledge graph", requestJson("/runs/latest/knowledge-graph"), { status: "missing", nodes: [], edges: [], meta: {} }),
      guarded("Live health", requestJson("/health/live"), null),
      guarded("Readiness", readinessProbe(), null),
      guarded("Config", requestJson("/health/config"), null),
      guarded("Dependencies", requestJson("/health/dependencies"), null),
    ]);
    state.latestRun = latestRun;
    state.auditSummary = auditSummary;
    state.dataStatus = dataStatus;
    state.knowledgeGraph = knowledgeGraph;
    state.liveStatus = liveStatus;
    state.readyStatus = readyStatus;
    state.configStatus = configStatus;
    state.dependenciesStatus = dependenciesStatus;
    if (state.latestJob?.job_id && ["queued", "running"].includes(String(state.latestJob.status || "").toLowerCase())) {
      state.latestJob = await guarded(
        "Run job",
        requestJson(`/runs/jobs/${encodeURIComponent(state.latestJob.job_id)}`),
        state.latestJob,
      );
    }
    maybeAppendRunEvent(previousSignature);
    renderAll();
  }

  function renderAll() {
    renderSession();
    renderDashboard();
    renderDataStatus();
    renderKnowledgeGraph();
    renderHealth();
    renderVectorSearch();
    renderSourcePackPanel();
    renderChat();
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
    els.newRunButton.addEventListener("click", () => openDrawer("new-run", "source-pack-section"));
    els.startRunCancel.addEventListener("click", () => closeDrawer("new-run"));
    els.systemDrawerButton.addEventListener("click", () => openDrawer("system"));
    els.systemDrawerClose.addEventListener("click", () => closeDrawer("system"));
    document.querySelectorAll("[data-scroll-target]").forEach((node) => {
      node.addEventListener("click", () => {
        scrollToWorkspaceTarget(node.getAttribute("data-scroll-target") || "");
      });
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
