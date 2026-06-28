(function () {
  window.STRATEGYOS_PLAN = {
    updated: "2026-06-28",
    overallStatus: "in_progress",
    phases: [
      {
        id: "phase-0",
        num: 0,
        title: "Foundation",
        subtitle: "Protocol, state, persona models, integration hooks",
        weeks: "2–3",
        status: "completed",
        stories: [
          { id: "0.1", title: "TwinPersona model + role definitions", description: "Define persona dataclass with role, goals, authority boundaries, escalation path", status: "completed", files: ["twins/persona.py"] },
          { id: "0.2", title: "InterTwinMessage protocol + message store", description: "Structured message envelope with typed fields, PostgreSQL table for audit trail", status: "completed", files: ["twins/protocol.py"] },
          { id: "0.3", title: "Twin state persistence (memory)", description: "Persistent state: working memory, active investigations, pending requests", status: "completed", files: ["twins/memory.py"] },
          { id: "0.4", title: "Integration hooks with existing APIs", description: "Evidence spine, knowledge graph, KPI substrate access from twin context", status: "completed", files: ["twins/tools.py", "api.py"] },
          { id: "0.5", title: "Unit tests for foundation layer", description: "Test persona instantiation, protocol validation, state persistence", status: "completed", files: ["tests/test_twins_foundation.py"] }
        ]
      },
      {
        id: "phase-1",
        num: 1,
        title: "First Two Twins",
        subtitle: "CEO + CFO twins, single KPI resolution flow, minimal dashboard",
        weeks: "2–3",
        status: "completed",
        stories: [
          { id: "1.1", title: "Twin runtime — agent loop", description: "Observe → Orient → Decide → Act loop, wake/sleep cycle, state machine", status: "completed", files: ["twins/runtime.py"] },
          { id: "1.2", title: "KPI resolution engine", description: "Tree traversal, gap detection, ownership routing for single-hop resolution", status: "completed", files: ["twins/resolution.py"] },
          { id: "1.3", title: "CEO Twin persona + first investigation", description: "CEO goals, KPI ownership, ability to trace margin/health and request data", status: "completed", files: ["twins/persona.py", "twins/runtime.py"] },
          { id: "1.4", title: "CFO Twin persona + CEO interaction", description: "CFO goals, financial KPI ownership, response to CEO data requests", status: "completed", files: ["twins/persona.py", "twins/runtime.py"] },
          { id: "1.5", title: "Minimal CEO twin dashboard", description: "Single-page dashboard: KPI health, active investigation, pending requests. Human can query their twin.", status: "completed", files: ["twins/static/ceo.html"] },
          { id: "1.6", title: "Integration + end-to-end test", description: "Full flow: CEO queries margin → twin traces KPI → requests CFO → response", status: "completed", files: ["tests/test_twins_phase1.py"] }
        ]
      },
      {
        id: "phase-2",
        num: 2,
        title: "Expanded Roles",
        subtitle: "Group Manager, Analyst, Strategy, Reviewer twins + multi-hop chains",
        weeks: "2",
        status: "completed",
        stories: [
          { id: "2.1", title: "Group Manager Twin", description: "BU metrics, growth KPIs, operational data ownership", status: "completed", files: ["twins/persona.py"] },
          { id: "2.2", title: "Analyst Twin", description: "Data prep, source validation, evidence quality monitoring", status: "completed", files: ["twins/persona.py"] },
          { id: "2.3", title: "Strategy Twin", description: "KPI tree maintenance, value driver mapping, initiative tracking", status: "completed", files: ["twins/persona.py"] },
          { id: "2.4", title: "Reviewer Twin", description: "Evidence verification, finding adjudication, compliance checks", status: "completed", files: ["twins/persona.py"] },
          { id: "2.5", title: "Multi-hop resolution chains", description: "CEO → CFO → GM → Analyst chain, passing structured requests through hierarchy", status: "completed", files: ["twins/protocol.py", "twins/resolution.py"] },
          { id: "2.6", title: "Escalation + deadline enforcement", description: "Auto-escalate if no response by deadline, configurable timeouts per role", status: "completed", files: ["twins/protocol.py"] }
        ]
      },
      {
        id: "phase-3",
        num: 3,
        title: "Orchestration",
        subtitle: "Scheduled cycles, event triggers, governance gates, board packets",
        weeks: "2",
        status: "completed",
        stories: [
          { id: "3.1", title: "Scheduled review cycles", description: "Daily standup, weekly KPI review, monthly board packet — automatic wake-up and processing", status: "completed", files: ["twins/orchestration.py"] },
          { id: "3.2", title: "Event-driven KPI triggers", description: "Threshold breach → automatic investigation, data staleness → request refresh", status: "completed", files: ["twins/orchestration.py", "twins/resolution.py"] },
          { id: "3.3", title: "Governance gates", description: "Configurable human approval thresholds per role, per action type, per value threshold", status: "completed", files: ["twins/orchestration.py"] },
          { id: "3.4", title: "Board packet generation", description: "Automated strategic report: KPI summary, risk flags, pending decisions, evidence citations", status: "completed", files: ["twins/orchestration.py"] },
          { id: "3.5", title: "Cycle history + audit", description: "All cycle results persisted, searchable, with full evidence trail", status: "completed", files: ["twins/orchestration.py"] }
        ]
      },
      {
        id: "phase-4",
        num: 4,
        title: "Full UI",
        subtitle: "Complete per-role dashboards, conversation views, human override",
        weeks: "2",
        status: "completed",
        stories: [
          { id: "4.1", title: "Complete CEO dashboard", description: "Full KPI health overview, active investigations panel, decision queue, board packet preview", status: "completed", files: ["twins/static/ceo.html"] },
          { id: "4.2", title: "CFO dashboard", description: "Financial metrics, budget variance, cash monitoring, pending approvals", status: "completed", files: ["twins/static/cfo.html"] },
          { id: "4.3", title: "GM dashboard", description: "BU performance, initiative tracking, resource requests, escalations", status: "completed", files: ["twins/static/gm.html"] },
          { id: "4.4", title: "Conversation views for all roles", description: "Twin-to-twin message history with evidence citations, thread view, search", status: "completed", files: ["twins/static/*.html"] },
          { id: "4.5", title: "Human override interface", description: "Approve, redirect, query, escalate controls on every dashboard. Decision audit trail.", status: "completed", files: ["twins/static/*.html"] },
          { id: "4.6", title: "E2E acceptance tests", description: "Full acceptance: all 6 twins, multi-hop resolution, governance gates, UI flows", status: "completed", files: ["tests/test_twins_phase4.py"] }
        ]
      },
      {
        id: "phase-5",
        num: 5,
        title: "Live Integration",
        subtitle: "API routes, auth wiring, live data fetching, deploy dashboards to strategyos.live",
        weeks: "1",
        status: "completed",
        stories: [
          { id: "5.1", title: "Twin API endpoints (status, kpis, inbox, investigate)", description: "FastAPI router at /twin/api/* — live data for dashboards", status: "completed", files: ["twins/api.py"] },
          { id: "5.2", title: "Route integration + auth", description: "Include twin router in main app, serve dashboard HTML at /twin/ceo, /twin/cfo, /twin/gm", status: "completed", files: ["api.py"] },
          { id: "5.3", title: "Live data fetching in dashboards", description: "JavaScript fetch() to twin API — dashboards now show real KPI/inbox/investigation data", status: "completed", files: ["twins/static/*.html"] },
          { id: "5.4", title: "Cross-dashboard navigation", description: "Nav links between CEO/CFO/GM dashboards + plan + architecture", status: "completed", files: ["twins/static/*.html"] },
          { id: "5.5", title: "Integration tests", description: "Test all API endpoints, dashboard routes, live JS, no regressions", status: "completed", files: ["tests/test_twins_phase5.py"] },
          { id: "5.6", title: "Deploy to strategyos.live", description: "Dashboards live at /twin/ceo, /twin/cfo, /twin/gm — authenticated users can query their twins", status: "completed", files: [] }
        ]
      },
      {
        id: "phase-6",
        num: 6,
        title: "Persistent reality layer",
        subtitle: "Replace hardcoded KPI tree, inbox, investigations, and dashboard state with durable persistence",
        weeks: "1–2",
        status: "completed",
        stories: [
          { id: "6.1", title: "Persist KPI tree instead of serving hardcoded structures", description: "Move KPI hierarchy reads from demo fixtures into durable tables and repository-backed queries so dashboard state survives restarts", status: "completed", files: [] },
          { id: "6.2", title: "Replace hardcoded inbox queues with stored twin work items", description: "Back inbox cards with persisted requests, ownership, due dates, and status transitions instead of static response payloads", status: "completed", files: [] },
          { id: "6.3", title: "Store investigations as durable records", description: "Persist investigation threads, evidence links, findings, and status so active cases can be resumed and audited", status: "completed", files: [] },
          { id: "6.4", title: "Introduce repository-backed twin state services", description: "Centralize twin reads/writes behind repositories so APIs and schedulers stop mutating in-memory demo state directly", status: "completed", files: [] },
          { id: "6.5", title: "Rewire dashboards to repository-backed reality", description: "Update KPI, inbox, and investigation screens to render persisted state rather than hardcoded UI/demo data", status: "completed", files: [] }
        ]
      },
      {
        id: "phase-7",
        num: 7,
        title: "Identity and governance integration",
        subtitle: "Enforce real auth, role gating, approval trails, and escalation audit across twin actions",
        weeks: "1–2",
        status: "completed",
        stories: [
          { id: "7.1", title: "Require authenticated access for twin dashboards and APIs", description: "Bind twin routes to real user identity so every read and action is tied to a persisted principal", status: "completed", files: [] },
          { id: "7.2", title: "Gate actions by role and authority", description: "Enforce persona-specific permissions for approve, redirect, escalate, investigate, and publish actions", status: "completed", files: [] },
          { id: "7.3", title: "Persist approval decisions and reviewer rationale", description: "Store who approved what, when, and why so governance decisions stop living only in transient UI state", status: "completed", files: [] },
          { id: "7.4", title: "Audit escalation and redirect flows", description: "Capture redirect, reassignment, escalation, and deadline override history as durable workflow events", status: "completed", files: [] },
          { id: "7.5", title: "Expose governance history in product surfaces", description: "Show approval trail and routing history inside dashboards so operators can inspect the full control path", status: "completed", files: [] }
        ]
      },
      {
        id: "phase-8",
        num: 8,
        title: "StrategyOS data integration",
        subtitle: "Connect twins to real KPI, evidence, board, and runtime records instead of stubbed payloads",
        weeks: "1–2",
        status: "completed",
        stories: [
          { id: "8.1", title: "Bind KPI dashboards to real StrategyOS metrics", description: "Replace placeholder KPI values with live metric, threshold, and trend reads from the StrategyOS data layer", status: "completed", files: [] },
          { id: "8.2", title: "Attach investigations to real evidence records", description: "Load citations, source links, and evidence freshness directly from StrategyOS evidence storage", status: "completed", files: [] },
          { id: "8.3", title: "Wire board packet views to real board/report objects", description: "Render packet summaries and approvals from persisted StrategyOS board and publication records", status: "completed", files: [] },
          { id: "8.4", title: "Connect twin actions to runtime and execution records", description: "Persist asks, follow-ups, and resolution outcomes against real runs instead of standalone twin-only payloads", status: "completed", files: [] },
          { id: "8.5", title: "Validate end-to-end data consistency across surfaces", description: "Confirm KPI, evidence, board, and run views stay consistent when twins inspect and act on the same underlying records", status: "completed", files: [] }
        ]
      },
      {
        id: "phase-9",
        num: 9,
        title: "LLM reasoning + scheduled execution",
        subtitle: "Add LiteLLM-backed reasoning and run twins on scheduled or triggered execution paths",
        weeks: "1–2",
        status: "completed",
        stories: [
          { id: "9.1", title: "Introduce LiteLLM-backed orient and decide steps", description: "Move twin reasoning from scripted-only behavior into model-backed analysis with bounded prompts and outputs", status: "completed", files: [] },
          { id: "9.2", title: "Persist reasoning inputs, outputs, and review state", description: "Store prompts, cited evidence, model responses, and review disposition so reasoning is reproducible and auditable", status: "completed", files: [] },
          { id: "9.3", title: "Run scheduled twin cycles through the real runtime stack", description: "Execute daily, weekly, and monthly review paths via the existing scheduler and job infrastructure", status: "completed", files: [] },
          { id: "9.4", title: "Trigger twin execution from live events", description: "Wake investigations and follow-up tasks from KPI breaches, stale evidence, and approval deadlines instead of manual refreshes", status: "completed", files: [] },
          { id: "9.5", title: "Add guardrails for model-driven actions", description: "Require approval thresholds, fallback handling, and action logging before reasoning outputs can change state or notify humans", status: "completed", files: [] }
        ]
      },
      {
        id: "phase-10",
        num: 10,
        title: "Production hardening",
        subtitle: "Lock down E2E reliability, observability, idempotency, security, and rollout safety before broad release",
        weeks: "1–2",
        status: "completed",
        stories: [
          { id: "10.1", title: "Ship end-to-end regression coverage for twin workflows", description: "Exercise persisted KPI, inbox, investigation, approval, and publication flows through browser and API tests", status: "completed", files: [] },
          { id: "10.2", title: "Add observability across twin execution paths", description: "Instrument dashboards, APIs, jobs, and reasoning steps with logs, traces, and health signals fit for production debugging", status: "completed", files: [] },
          { id: "10.3", title: "Enforce idempotency and retry safety", description: "Protect scheduled jobs, action endpoints, and approval mutations from duplicate execution during retries or restarts", status: "completed", files: [] },
          { id: "10.4", title: "Close security and access-control gaps", description: "Review route protection, sensitive data exposure, audit integrity, and privileged actions before rollout", status: "completed", files: [] },
          { id: "10.5", title: "Prepare staged rollout and rollback controls", description: "Add feature flags, deployment checks, operator runbooks, and fallback steps so production rollout can be controlled safely", status: "completed", files: [] },
          { id: "10.6", title: "Contain and redesign anonymous public findings exposure", description: "Remove vendor-identifying data from anonymous /public findings, evidence, and detail flows; verify containment; ship an allowlist-only anonymous publication contract; then re-verify and correct boundary docs before closure", status: "completed", files: [] }
        ]
      },
      {
        id: "phase-11",
        num: 11,
        title: "Oracle finance ingestion foundation",
        subtitle: "Stand up the Oracle EBS pilot ingestion layer and manual evidence inputs needed for deterministic finance analysis",
        weeks: "1–2",
        status: "in_progress",
        stories: [
          { id: "11.1", title: "Map Oracle EBS module extracts into a canonical finance intake", description: "Define the ingestion contract for GL, AR, AP, CE, FA, PO, and INV so Oracle pilot data lands in one deterministic shape", status: "in_progress", files: [] },
          { id: "11.2", title: "Implement BU and cost-centre flexfield mapping", description: "Resolve Oracle flexfields into StrategyOS business unit and reporting mappings with auditable transformation rules", status: "not_started", files: [] },
          { id: "11.3", title: "Handle reporting cadence and period alignment", description: "Support daily, weekly, monthly, and close-cycle cadence handling so extracts and finance outputs stay period-correct", status: "not_started", files: [] },
          { id: "11.4", title: "Ingest required manual and file-based pilot inputs", description: "Accept budget files, hedge register updates, contracts, covenant terms, board floor assumptions, and management commentary alongside Oracle data", status: "not_started", files: [] },
          { id: "11.5", title: "Prove source coverage and traceability", description: "Show every pilot number can be traced back to Oracle EBS modules or approved manual/file inputs before downstream KPI computation starts", status: "not_started", files: [] }
        ]
      },
      {
        id: "phase-12",
        num: 12,
        title: "Deterministic KPI calculation engine",
        subtitle: "Compute pilot finance metrics from fixed formulas, with narration layered on only after the numbers are settled",
        weeks: "1–2",
        status: "not_started",
        stories: [
          { id: "12.1", title: "Lock deterministic formulas for core profit metrics", description: "Calculate revenue, EBITDA, OpEx, and EBITDA bridge values from approved Oracle-backed sources with no model discretion in the math", status: "not_started", files: [] },
          { id: "12.2", title: "Compute liquidity against the board floor", description: "Measure cash vs floor using CE balances, treasury inputs, and board floor rules so breach status is explicit and reproducible", status: "not_started", files: [] },
          { id: "12.3", title: "Ship working-capital cycle metrics", description: "Derive DSO, DPO, DIO, and CCC directly from AR, AP, and inventory-aligned sources with period-consistent denominators", status: "not_started", files: [] },
          { id: "12.4", title: "Calculate leverage and covenant capacity", description: "Produce net debt / EBITDA and covenant headroom outputs from debt, cash, and covenant-term inputs with visible assumptions", status: "not_started", files: [] },
          { id: "12.5", title: "Separate computation from narration", description: "Keep the engine deterministic for numbers while any LLM-generated explanation stays strictly downstream and evidence-backed", status: "not_started", files: [] }
        ]
      },
      {
        id: "phase-13",
        num: 13,
        title: "Cash leakage engine",
        subtitle: "Detect the pilot’s defined leakage patterns with deterministic rules, evidence, and reviewable findings",
        weeks: "1–2",
        status: "not_started",
        stories: [
          { id: "13.1", title: "Detect duplicate-payment patterns", description: "Implement the duplicate payment and entity-resolution duplicate rules so the same vendor paid twice or across multiple IDs is caught deterministically", status: "not_started", files: [] },
          { id: "13.2", title: "Stop contract and pricing leakage", description: "Detect off-contract spend and price variance by comparing AP invoices and PO lines against approved contract scope, terms, and unit prices", status: "not_started", files: [] },
          { id: "13.3", title: "Recover missed discount and renewal leakage", description: "Flag missed early-pay discounts and auto-renewal escalation when payment timing or contract renewal behavior burns avoidable cash", status: "not_started", files: [] },
          { id: "13.4", title: "Catch treasury and credit-balance leakage", description: "Detect FX hedge not applied and dormant credit balance patterns so treasury slippage and unused credits surface as recoverable value", status: "not_started", files: [] },
          { id: "13.5", title: "Publish evidence-backed leakage reviews", description: "Rank recoverable value and attach deterministic evidence, corroboration, and reviewer workflow for all 8 pilot leakage patterns: duplicate payment, entity-resolution duplicate, off-contract spend, price variance, missed early-pay discount, auto-renewal escalation, FX hedge not applied, and dormant credit balance", status: "not_started", files: [] }
        ]
      },
      {
        id: "phase-14",
        num: 14,
        title: "CEO/CFO pilot surface alignment",
        subtitle: "Refit the product surfaces so the CFO pilot is Oracle-first and the CEO sees Oracle-backed financial rings without pretending operations are automated yet",
        weeks: "1",
        status: "not_started",
        stories: [
          { id: "14.1", title: "Make the CFO surface Oracle-first", description: "Prioritize Oracle-sourced finance ingestion, KPI outputs, and reconciliation context in the CFO pilot experience", status: "not_started", files: [] },
          { id: "14.2", title: "Render CEO financial rings from Oracle-backed data", description: "Drive CEO financial rings and board-level finance views from deterministic Oracle-backed outputs rather than generic twin-era placeholders", status: "not_started", files: [] },
          { id: "14.3", title: "Mark operational movers as manual or deferred", description: "Keep non-finance operational movers visible, but explicitly label them manual/deferred until Oracle-first finance conformance is proven", status: "not_started", files: [] },
          { id: "14.4", title: "Align plan, copy, and UI language to the pilot", description: "Update product messaging so every public and pilot-facing surface reflects the Oracle EBS conformance scope instead of a generic digital twin roadmap", status: "not_started", files: [] },
          { id: "14.5", title: "Preserve history while clarifying the pivot", description: "Keep completed digital-twin phases available as delivery history while clearly showing that active execution now starts at Oracle conformance", status: "not_started", files: [] }
        ]
      },
      {
        id: "phase-15",
        num: 15,
        title: "Production validation for Oracle pilot",
        subtitle: "Validate the Oracle pilot end to end before rollout, with reconciliation, auditability, and controlled release gates",
        weeks: "1–2",
        status: "not_started",
        stories: [
          { id: "15.1", title: "Reconcile Oracle extracts to computed outputs", description: "Verify ingestion totals, KPI calculations, and leakage findings reconcile cleanly back to Oracle source periods and approved manual inputs", status: "not_started", files: [] },
          { id: "15.2", title: "Prove auditability of every pilot number", description: "Expose lineage, assumptions, evidence references, and reviewer actions so finance users can audit every board-facing output", status: "not_started", files: [] },
          { id: "15.3", title: "Run end-to-end Oracle pilot tests", description: "Exercise the CFO and CEO pilot flows from Oracle/file ingestion through KPI calculation, leakage review, and surface rendering", status: "not_started", files: [] },
          { id: "15.4", title: "Install rollout controls and failure gates", description: "Require feature flags, release criteria, rollback paths, and operator sign-offs before widening beyond the Oracle pilot cohort", status: "not_started", files: [] },
          { id: "15.5", title: "Sign off pilot readiness", description: "Close the phase only after reconciliation, auditability, and rollout-control checks all pass for the Oracle EBS pilot scope", status: "not_started", files: [] }
        ]
      }
    ]
  };
})();
