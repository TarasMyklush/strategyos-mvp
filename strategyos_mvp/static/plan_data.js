(function () {
  window.STRATEGYOS_PLAN = {
    updated: "2026-06-25",
    overallStatus: "in_progress",
    phases: [
      {
        id: "phase-0",
        num: 0,
        title: "Foundation",
        subtitle: "Protocol, state, persona models, integration hooks",
        weeks: "2\u20133",
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
        weeks: "2\u20133",
        status: "completed",
        stories: [
          { id: "1.1", title: "Twin runtime \u2014 agent loop", description: "Observe \u2192 Orient \u2192 Decide \u2192 Act loop, wake/sleep cycle, state machine", status: "completed", files: ["twins/runtime.py"] },
          { id: "1.2", title: "KPI resolution engine", description: "Tree traversal, gap detection, ownership routing for single-hop resolution", status: "completed", files: ["twins/resolution.py"] },
          { id: "1.3", title: "CEO Twin persona + first investigation", description: "CEO goals, KPI ownership, ability to trace margin/health and request data", status: "completed", files: ["twins/persona.py", "twins/runtime.py"] },
          { id: "1.4", title: "CFO Twin persona + CEO interaction", description: "CFO goals, financial KPI ownership, response to CEO data requests", status: "completed", files: ["twins/persona.py", "twins/runtime.py"] },
          { id: "1.5", title: "Minimal CEO twin dashboard", description: "Single-page dashboard: KPI health, active investigation, pending requests. Human can query their twin.", status: "completed", files: ["twins/static/ceo.html"] },
          { id: "1.6", title: "Integration + end-to-end test", description: "Full flow: CEO queries margin \u2192 twin traces KPI \u2192 requests CFO \u2192 response", status: "completed", files: ["tests/test_twins_phase1.py"] }
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
          { id: "2.5", title: "Multi-hop resolution chains", description: "CEO \u2192 CFO \u2192 GM \u2192 Analyst chain, passing structured requests through hierarchy", status: "completed", files: ["twins/protocol.py", "twins/resolution.py"] },
          { id: "2.6", title: "Escalation + deadline enforcement", description: "Auto-escalate if no response by deadline, configurable timeouts per role", status: "completed", files: ["twins/protocol.py"] }
        ]
      },
      {
        id: "phase-3",
        num: 3,
        title: "Orchestration",
        subtitle: "Scheduled cycles, event triggers, governance gates, board packets",
        weeks: "2",
        status: "not_started",
        stories: [
          { id: "3.1", title: "Scheduled review cycles", description: "Daily standup, weekly KPI review, monthly board packet \u2014 automatic wake-up and processing", status: "not_started", files: ["twins/orchestration.py"] },
          { id: "3.2", title: "Event-driven KPI triggers", description: "Threshold breach \u2192 automatic investigation, data staleness \u2192 request refresh", status: "not_started", files: ["twins/orchestration.py"] },
          { id: "3.3", title: "Governance gates", description: "Configurable human approval thresholds per role, per action type, per value threshold", status: "not_started", files: ["twins/orchestration.py", "twins/persona.py"] },
          { id: "3.4", title: "Board packet generation", description: "Automated strategic report: KPI summary, risk flags, pending decisions, evidence citations", status: "not_started", files: ["twins/orchestration.py"] },
          { id: "3.5", title: "Cycle history + audit", description: "All cycle results persisted, searchable, with full evidence trail", status: "not_started", files: ["twins/memory.py", "twins/api.py"] }
        ]
      },
      {
        id: "phase-4",
        num: 4,
        title: "Full UI",
        subtitle: "Complete per-role dashboards, conversation views, human override",
        weeks: "2",
        status: "not_started",
        stories: [
          { id: "4.1", title: "Complete CEO dashboard", description: "Full KPI health overview, active investigations panel, decision queue, board packet preview", status: "not_started", files: ["twins/static/ceo.html"] },
          { id: "4.2", title: "CFO dashboard", description: "Financial metrics, budget variance, cash monitoring, pending approvals", status: "not_started", files: ["twins/static/cfo.html"] },
          { id: "4.3", title: "GM dashboard", description: "BU performance, initiative tracking, resource requests, escalations", status: "not_started", files: ["twins/static/gm.html"] },
          { id: "4.4", title: "Conversation views for all roles", description: "Twin-to-twin message history with evidence citations, thread view, search", status: "not_started", files: ["twins/static/*.html", "twins/api.py"] },
          { id: "4.5", title: "Human override interface", description: "Approve, redirect, query, escalate controls on every dashboard. Decision audit trail.", status: "not_started", files: ["twins/static/*.html"] },
          { id: "4.6", title: "E2E acceptance tests", description: "Full acceptance: all 6 twins, multi-hop resolution, governance gates, UI flows", status: "not_started", files: ["tests/test_twins_acceptance.py"] }
        ]
      }
    ]
  };
})();
