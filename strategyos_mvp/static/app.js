(function () {
  "use strict";

  const bootstrap = JSON.parse(document.getElementById("strategyos-bootstrap").textContent);
  const TOKEN_KEY = "strategyos.ui.token";
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
    auditSummary: null,
    dataStatus: null,
    liveStatus: null,
    readyStatus: null,
    configStatus: null,
    dependenciesStatus: null,
    chatRunKey: "",
    chatThread: [],
    qaLoading: false,
    activeSuggestions: STARTER_SUGGESTIONS.slice(0, 5),
    openCitationKey: "",
    sourcePack: null,
    sourcePackSubmitting: false,
    runSubmitting: false,
    vectorSearch: { status: "idle", payload: null, error: "" },
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
    reviewMessage: byId("review-message"),
    reviewTitle: byId("review-title"),
    reviewDetail: byId("review-detail"),
    reviewComment: byId("review-comment"),
    reviewApprove: byId("review-approve"),
    reviewReject: byId("review-reject"),
    reviewResume: byId("review-resume"),
    newRunButton: byId("new-run-button"),
    newRunDrawer: byId("new-run-drawer"),
    sourcePackUploadForm: byId("source-pack-upload-form"),
    sourcePackFiles: byId("source-pack-files"),
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
    vectorSearchForm: byId("vector-search-form"),
    vectorSearchQuery: byId("vector-search-query"),
    vectorSearchLimit: byId("vector-search-limit"),
    vectorSearchResults: byId("vector-search-results"),
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
    if (["ok", "ready", "synced", "persisted", "completed", "approved", "not_required", "pass"].includes(normalized)) return "ok";
    if (["failed", "error", "rejected", "missing"].includes(normalized)) return "danger";
    if (["skipped", "degraded", "awaiting_review", "pending", "running"].includes(normalized)) return "warn";
    return "neutral";
  }

  function statusPill(status, label) {
    const text = label || String(status || "unknown").replaceAll("_", " ");
    return `<span class="pill ${statusTone(status)}">${escapeHtml(text)}</span>`;
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

  function isOperator() {
    return String(state.session?.role || "") === "operator";
  }

  function isReviewer() {
    return String(state.session?.role || "") === "reviewer";
  }

  function activeRunId() {
    const runId = state.latestRun?.run_id;
    return runId ? String(runId) : null;
  }

  function activeRunKey() {
    const run = state.latestRun || {};
    return String(run.run_id || run.run_dir || run.dataset || "latest");
  }

  function displayRunId(run) {
    if (!run || run.status === "missing") return "no run";
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
      els.runPill.textContent = "No runs yet";
      els.runPill.className = "pill status-pill warn";
      els.kpiRecoverable.textContent = "--";
      els.kpiFindings.innerHTML = "--";
      els.kpiCitations.textContent = "--";
      els.kpiCitations.classList.remove("ok");
      els.kpiChallenged.textContent = "--";
      els.stageStepper.textContent = "No runs yet - start one from New run.";
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
    els.stageStepper.innerHTML = stages.map((stage, index) => {
      const done = completed || index < currentIndex;
      const active = !completed && index === currentIndex;
      const mark = done ? " ✓" : active ? " active" : "";
      const label = String(stage).replaceAll("_", " ");
      return `<span class="stage-node ${done ? "done" : active ? "current" : ""}">${escapeHtml(label)}${mark}</span>`;
    }).join("");
  }

  function renderStoreBadges(run) {
    const stores = [
      ["postgres", run.state_store || state.dataStatus?.state_store],
      ["neo4j", run.neo4j || state.dataStatus?.neo4j],
      ["qdrant", run.qdrant || state.dataStatus?.qdrant],
    ];
    els.storeBadges.innerHTML = stores.map(([name, payload]) => {
      const status = payload?.status || "unknown";
      const label = `${name} ${String(status).replaceAll("_", " ")}`;
      const reason = payload?.reason || payload?.detail || "";
      return `<span class="badge ${statusTone(status)}" title="${escapeHtml(reason)}">${escapeHtml(label)}</span>`;
    }).join("");
  }

  function renderPartialRunChips(run) {
    const chips = [];
    if (run.run_mode && run.run_mode !== "full") chips.push(statusPill("warn", `mode ${run.run_mode}`));
    (run.missing_roles || []).forEach((role) => chips.push(statusPill("warn", `missing ${role}`)));
    (run.detector_report?.skipped_detectors || []).forEach((item) => {
      chips.push(`<span class="pill warn" title="${escapeHtml(item.reason || "")}">skipped ${escapeHtml(item.detector || "detector")}</span>`);
    });
    els.partialRunChips.innerHTML = chips.join("");
    els.partialRunChips.classList.toggle("hidden", chips.length === 0);
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

    if (resumable) {
      els.reviewTitle.textContent = "Run approved - resume is available.";
      els.reviewDetail.textContent = `Operator resume will continue run ${displayRunId(run)} into the writer stage.`;
    } else {
      els.reviewTitle.textContent = "Run paused - human review required.";
      els.reviewDetail.textContent = `Reviewer decision is required before run ${displayRunId(run)} can continue.`;
    }
    els.reviewApprove.classList.toggle("hidden", !needsReview);
    els.reviewReject.classList.toggle("hidden", !needsReview);
    els.reviewResume.classList.toggle("hidden", !resumable);
    els.reviewApprove.disabled = !isReviewer() || !activeRunId();
    els.reviewReject.disabled = !isReviewer() || !activeRunId();
    els.reviewResume.disabled = !isOperator() || !activeRunId();
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
      : `<div class="sysmsg"><span>No questions yet. Use the suggestions below to ask a deterministic finance question.</span></div>`;
    renderSuggestions();
    renderReviewMessage();
    requestAnimationFrame(() => {
      els.chatThread.scrollTop = els.chatThread.scrollHeight;
    });
  }

  function renderChatEntry(entry, index) {
    if (entry.type === "system") {
      return `<div class="sysmsg"><span>${escapeHtml(entry.text || "")}</span></div>`;
    }
    if (entry.type === "user") {
      return `<div class="msg-user">${escapeHtml(entry.text || "")}</div>`;
    }
    const payload = entry.payload || {};
    const valueLabel = formatValue(payload.value, payload.unit);
    const answer = payload.answer || entry.error || "No answer returned.";
    const unmatched = payload.matched === false;
    const citations = Array.isArray(payload.citations) ? payload.citations : [];
    const suggestions = Array.isArray(payload.suggestions) ? payload.suggestions : [];
    const citationHtml = citations.length
      ? `<div class="chips">${citations.map((citation, citationIndex) => renderCitation(citation, `${index}-${citationIndex}`)).join("")}</div>`
      : "";
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
        </div>
        ${citationHtml}
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

  function renderSuggestions() {
    const suggestions = state.activeSuggestions.length ? state.activeSuggestions : STARTER_SUGGESTIONS.slice(0, 5);
    els.chatSuggestions.innerHTML = suggestions.slice(0, 6).map((item) => (
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
      const body = { question };
      const runId = activeRunId();
      if (runId) body.run_id = runId;
      const payload = await requestJson("/qa", {
        method: "POST",
        body: JSON.stringify(body),
      });
      state.chatThread.push({ type: "bot", payload });
      state.activeSuggestions = Array.isArray(payload.suggestions) && payload.suggestions.length
        ? payload.suggestions
        : STARTER_SUGGESTIONS.slice(0, 5);
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
      state.activeSuggestions = STARTER_SUGGESTIONS.slice(0, 5);
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
    els.dataSystemsKv.innerHTML = kvHtml([
      ["Neo4j", statusPill(payload.neo4j?.status || "unknown")],
      ["Qdrant", statusPill(payload.qdrant?.status || "unknown")],
      ["Graph sample", payload.neo4j?.sample_relation?.source_node_key || payload.neo4j?.reason || "--"],
      ["Vector sample", payload.qdrant?.sample_record?.finding_id || payload.qdrant?.reason || "--"],
    ], true);
    els.dataPayloadPreview.textContent = compactJson(payload);
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
        `<div class="item"><strong>${index + 1}. ${escapeHtml(item.finding_id || item.title || "Result")}</strong><span>${escapeHtml(item.summary || item.text || item.vendor_name || "Vector hit")}</span></div>`
      )).join("");
    }
    els.vectorSearchPayloadPreview.textContent = compactJson(vector.payload);
  }

  async function submitVectorSearch(event) {
    event?.preventDefault?.();
    const query = els.vectorSearchQuery.value.trim();
    if (!query) return;
    const limit = Math.max(1, Math.min(10, Number(els.vectorSearchLimit.value || 5)));
    state.vectorSearch = { status: "loading", payload: null, error: "" };
    renderVectorSearch();
    try {
      const params = new URLSearchParams({ query, limit: String(limit) });
      const runId = activeRunId();
      if (runId) params.set("run_id", runId);
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
    els.startRunSubmit.disabled = disabled || state.runSubmitting || hasUnconfirmedMappings();

    const payload = state.sourcePack;
    if (!payload) {
      els.sourcePackSummary.textContent = "Manifest counts appear after upload or local staging.";
      els.sourcePackManifestBody.innerHTML = '<tr><td colspan="5" class="muted">No source-pack manifest yet.</td></tr>';
      els.sourcePackMappings.innerHTML = '<div class="item"><strong>No candidate mappings</strong><span>Upload or validate a source pack to inspect mapping proposals.</span></div>';
      els.sourcePackReadiness.innerHTML = '<div class="item"><strong>No readiness payload</strong><span>Validate a source pack to inspect task readiness.</span></div>';
      return;
    }

    const summary = payload.manifest_summary || {};
    els.sourcePackSummary.innerHTML = [
      `<strong>${escapeHtml(payload.source_pack_id || "source pack")}</strong>`,
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
      : '<tr><td colspan="5" class="muted">No source-pack manifest yet.</td></tr>';

    renderSourcePackMappings(manifest);
    renderSourcePackReadiness(payload.task_readiness || {});
  }

  function hasUnconfirmedMappings() {
    const unconfirmed = state.sourcePack?.task_readiness?.unconfirmed_roles || [];
    return Array.isArray(unconfirmed) && unconfirmed.length > 0;
  }

  function renderSourcePackMappings(manifest) {
    const candidates = manifest.filter((item) => item.classification?.status === "candidate");
    const prefix = hasUnconfirmedMappings()
      ? `<div class="item"><strong>Confirmation required before run</strong><span>${escapeHtml(state.sourcePack.task_readiness.unconfirmed_roles.join(", "))}</span></div>`
      : "";
    if (!candidates.length) {
      els.sourcePackMappings.innerHTML = `${prefix}<div class="item"><strong>No candidate mappings</strong><span>Validated structured mappings appear here when confirmation is required.</span></div>`;
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
          <button class="btn secondary" type="button" data-confirm-mapping="source-pack-mapping-${index}">Confirm mapping</button>
        </div>`;
    }).join("");
  }

  function renderSourcePackReadiness(readiness) {
    const tasks = Array.isArray(readiness.tasks) ? readiness.tasks : [];
    els.sourcePackReadiness.innerHTML = tasks.length
      ? tasks.map((item) => (
        `<div class="item"><strong>${escapeHtml(item.label || item.task_key || "Task")}</strong><span>${statusPill(item.status || "unknown")}</span><span class="muted">${escapeHtml((item.reasons || []).join(" | ") || "No readiness details.")}</span></div>`
      )).join("")
      : '<div class="item"><strong>No readiness payload</strong><span>Validate a source pack to inspect task readiness.</span></div>';
  }

  function setSourcePackStatus(tone, title, message) {
    els.sourcePackStatus.innerHTML = `${statusPill(tone, title)} ${escapeHtml(message || "")}`;
  }

  function setStartRunStatus(tone, title, message) {
    els.startRunStatus.innerHTML = `${statusPill(tone, title)} ${escapeHtml(message || "")}`;
  }

  async function submitSourcePackUpload(event) {
    event?.preventDefault?.();
    if (!isOperator()) return;
    const files = Array.from(els.sourcePackFiles.files || []);
    if (!files.length) {
      setSourcePackStatus("warn", "No files selected", "Choose a folder or file set before uploading.");
      return;
    }
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file, file.webkitRelativePath || file.name));
    state.sourcePackSubmitting = true;
    setSourcePackStatus("warn", "Uploading", "Posting selected files to /source-packs.");
    renderSourcePackPanel();
    try {
      state.sourcePack = await requestMultipart("/source-packs", formData);
      setSourcePackStatus("ok", "Uploaded", `Loaded ${state.sourcePack.source_pack_id || "source pack"}.`);
    } catch (error) {
      setSourcePackStatus("danger", "Upload failed", error?.message || "Unable to upload source pack.");
    } finally {
      state.sourcePackSubmitting = false;
      renderSourcePackPanel();
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
    setSourcePackStatus("warn", "Staging", "Posting folder path to /source-packs/from-path.");
    renderSourcePackPanel();
    try {
      state.sourcePack = await requestJson("/source-packs/from-path", {
        method: "POST",
        body: JSON.stringify({ folder_path: folderPath }),
      });
      setSourcePackStatus("ok", "Staged", `Loaded ${state.sourcePack.source_pack_id || "source pack"}.`);
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
    setSourcePackStatus("warn", "Validating", `Refreshing ${sourcePackId}.`);
    renderSourcePackPanel();
    try {
      state.sourcePack = await requestJson("/source-packs/validate", {
        method: "POST",
        body: JSON.stringify({ source_pack_id: sourcePackId }),
      });
      setSourcePackStatus("ok", "Validated", `Validation refreshed for ${sourcePackId}.`);
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
    setSourcePackStatus("warn", "Confirming", `Applying mapping for ${body.relative_path}.`);
    renderSourcePackPanel();
    try {
      state.sourcePack = await requestJson("/source-packs/confirm-mapping", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setSourcePackStatus("ok", "Confirmed", `Mapping confirmed for ${body.relative_path}.`);
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
    const payload = {
      dataset: els.startRunDataset.value.trim() || null,
      source_pack_id: state.sourcePack?.source_pack_id || null,
      run_dir: els.startRunRunDir.value.trim() || null,
      skip_prepare: els.startRunSkipPrepare.checked,
      sync_artifacts: els.startRunSyncArtifacts.checked,
      allow_partial_source_pack: els.startRunAllowPartialSourcePack.checked,
    };
    if (!payload.dataset && !payload.source_pack_id) payload.skip_prepare = true;
    state.runSubmitting = true;
    setStartRunStatus("warn", "Submitting", "Posting run request to /runs.");
    renderSourcePackPanel();
    try {
      const result = await requestJson("/runs", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setStartRunStatus("ok", "Started", `Run ${displayRunId(result)} started.`);
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
    if (!activeRunId() || !isReviewer()) return;
    const comment = els.reviewComment.value.trim();
    try {
      await requestJson(`/reviewer/runs/${encodeURIComponent(activeRunId())}/${decision}`, {
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

  function openDrawer(name) {
    const drawer = name === "system" ? els.systemDrawer : els.newRunDrawer;
    drawer.classList.remove("hidden");
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
      state.auditSummary = null;
      state.dataStatus = null;
      state.liveStatus = null;
      state.readyStatus = null;
      state.configStatus = null;
      state.dependenciesStatus = null;
      renderAll();
      return;
    }
    const previousSignature = state.lastRunSignature;
    const [latestRun, auditSummary, dataStatus, liveStatus, readyStatus, configStatus, dependenciesStatus] = await Promise.all([
      guarded("Latest run", requestJson("/runs/latest"), { status: "missing" }),
      guarded("Audit summary", requestJson("/runs/latest/audit-summary"), { status: "missing" }),
      guarded("Data status", requestJson("/data/status"), null),
      guarded("Live health", requestJson("/health/live"), null),
      guarded("Readiness", readinessProbe(), null),
      guarded("Config", requestJson("/health/config"), null),
      guarded("Dependencies", requestJson("/health/dependencies"), null),
    ]);
    state.latestRun = latestRun;
    state.auditSummary = auditSummary;
    state.dataStatus = dataStatus;
    state.liveStatus = liveStatus;
    state.readyStatus = readyStatus;
    state.configStatus = configStatus;
    state.dependenciesStatus = dependenciesStatus;
    maybeAppendRunEvent(previousSignature);
    renderAll();
  }

  function renderAll() {
    renderSession();
    renderDashboard();
    renderDataStatus();
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
    const delay = ["running", "awaiting_review"].includes(status) ? 5000 : 30000;
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
    els.chatThread.addEventListener("click", (event) => {
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
    els.newRunButton.addEventListener("click", () => openDrawer("new-run"));
    els.startRunCancel.addEventListener("click", () => closeDrawer("new-run"));
    els.systemDrawerButton.addEventListener("click", () => openDrawer("system"));
    els.systemDrawerClose.addEventListener("click", () => closeDrawer("system"));
    document.querySelectorAll("[data-close-drawer]").forEach((node) => {
      node.addEventListener("click", () => closeDrawer(node.getAttribute("data-close-drawer")));
    });
    els.sourcePackUploadForm.addEventListener("submit", submitSourcePackUpload);
    els.sourcePackPathForm.addEventListener("submit", submitSourcePackPath);
    els.sourcePackValidate.addEventListener("click", revalidateSourcePack);
    els.sourcePackMappings.addEventListener("click", (event) => {
      const button = event.target.closest("[data-confirm-mapping]");
      if (button) confirmSourcePackMapping(button.getAttribute("data-confirm-mapping"));
    });
    els.startRunForm.addEventListener("submit", submitStartRun);
    els.reviewApprove.addEventListener("click", () => sendReviewDecision("approve"));
    els.reviewReject.addEventListener("click", () => sendReviewDecision("reject"));
    els.reviewResume.addEventListener("click", resumeRun);
    els.vectorSearchForm.addEventListener("submit", submitVectorSearch);
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
    activeQaRunId: activeRunId,
  };
})();
