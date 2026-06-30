(function () {
  window.STRATEGYOS_PLAN = {
    updated: "2026-06-30",
    overallStatus: "in_progress",
    backlog: {
      title: "Remaining work",
      summary: "Only still-open work lives here: CEO interaction defects, UX defects, Oracle redeploy verification, open security fixes, and copy cleanup still in scope.",
      rows: [
        { id: "BUG-001", area: "Navigation", kind: "Bug", status: "open", priority: "high", title: "Fix broken Assistants and Knowledge nav tabs" },
        { id: "BUG-002", area: "Hermes panel", kind: "Bug", status: "open", priority: "high", title: "Fix Hermes conversation panel overflow and broken layout" },
        { id: "BUG-003", area: "Hermes panel", kind: "Bug", status: "open", priority: "high", title: "Fix the broken new conversation button" },
        { id: "BUG-004", area: "Hermes prompts", kind: "Bug", status: "open", priority: "high", title: "Fix suggested question chips so they trigger usable prompts" },
        { id: "BUG-005", area: "Findings", kind: "Bug", status: "open", priority: "high", title: "Fix findings expand buttons" },
        { id: "BUG-006", area: "Developments", kind: "Bug", status: "open", priority: "high", title: "Fix broken developments projection rows" },
        { id: "BUG-007", area: "Evidence", kind: "Bug", status: "open", priority: "high", title: "Fix the broken show-the-work action" },
        { id: "BUG-008", area: "Inline ask", kind: "Bug", status: "open", priority: "high", title: "Fix inline Ask so send produces a visible response instead of clearing silently" },
        { id: "UX-001", area: "Hermes launcher", kind: "UX", status: "open", priority: "medium", title: "Move or restyle the floating Hermes button so it stops obscuring KPI data" },
        { id: "UX-002", area: "Charts", kind: "UX", status: "open", priority: "medium", title: "Add axes, markers, and usable tooltips to charts" },
        { id: "UX-003", area: "Hermes panel", kind: "UX", status: "open", priority: "medium", title: "Add a clear and usable scroll affordance in the Hermes panel" },
        { id: "UX-004", area: "GM note", kind: "UX", status: "open", priority: "medium", title: "Show an explicit GM note availability state" },
        { id: "UX-005", area: "Ask flow", kind: "UX", status: "open", priority: "medium", title: "Make the send-and-receive affordance real or remove it" },
        { id: "UX-006", area: "Theme toggle", kind: "UX", status: "open", priority: "medium", title: "Add a visible label or tooltip to the theme toggle" },
        { id: "UX-007", area: "Hermes messages", kind: "UX", status: "open", priority: "medium", title: "Remove orphaned Hermes sender labels and empty message bubbles" },
        { id: "UX-008", area: "Feedback", kind: "UX", status: "open", priority: "medium", title: "Add a feedback or report-bug escape hatch" },
        {
          id: "ORACLE-VERIFY",
          area: "Oracle correctness",
          kind: "Verification",
          status: "open",
          priority: "high",
          title: "Redeploy and live-verify the reviewed Oracle correctness sweep",
          detailList: [
            "Month-name Oracle period resolution no longer collapses to one-day KPI windows.",
            "Cross-tenant writes on /finance/oracle/ingest are rejected.",
            "Anonymous audit-summary payloads no longer leak internal run IDs or challenged finding IDs.",
            "Leverage and covenant math stays guarded for negative or near-zero EBITDA.",
            "Duplicate-payment fallback and FX quote-direction fixes remain intact.",
            "Negative-quantity inflation guards, payload bounds, and Oracle pilot-flag enforcement stay active."
          ]
        },
        { id: "SEC-001", area: "Auth", kind: "Security", status: "open", priority: "high", title: "Replace proxy-secret equality checks with constant-time comparison in auth.py" },
        { id: "SEC-002", area: "Public scrub", kind: "Security", status: "open", priority: "high", title: "Remove the hardcoded public-scrub literal and rely on explicit allow-listing" },
        { id: "COPY-001", area: "Plan / landing", kind: "Copy", status: "open", priority: "medium", title: "Tighten the oversized headline and adjacent copy already in scope" }
      ]
    },
    completedHistory: [
      {
        id: "DONE-001",
        label: "Reviewed backend correctness sweep shipped",
        summary: "The latest Oracle/public-route/math defect pass is already implemented and should remain visible as shipped history rather than open backlog.",
        items: [
          "Oracle month-name period resolution fixed for real monthly Oracle labels.",
          "Tenant scope enforced on /finance/oracle/ingest.",
          "Anonymous-safe audit summary payload restored.",
          "Leverage and covenant math guarded for negative or near-zero EBITDA.",
          "Duplicate-payment recoverable fallback aligned with grouping logic.",
          "FX hedge quote direction inferred instead of assumed.",
          "Negative-quantity inflation blocked in recoverable math.",
          "Oracle ingest extract and manual-input payload size bounded.",
          "Oracle pilot flag enforced before write acceptance."
        ]
      },
      {
        id: "DONE-002",
        label: "CEO demo package shipped",
        summary: "The CEO walkthrough artifact pack is complete and belongs in history, not in the active backlog.",
        items: [
          "Final CEO demo package published under artifacts/ceo-demo.",
          "Supporting video, screenshots, and package notes bundled together.",
          "Demo boundary conditions disclosed truthfully in the package materials."
        ]
      },
      {
        id: "DONE-003",
        label: "Audit, cleanup, and handoff pack shipped",
        summary: "Post-backlog closure materials for the Oracle pilot were documented and preserved.",
        items: [
          "Post-backlog audit and handoff pack published.",
          "Cleanup recommendations and operator next steps recorded for handoff."
        ]
      },
      {
        id: "DONE-004",
        label: "Recent tracker truth fixes shipped",
        summary: "Earlier /plan truth corrections that are already done stay visible as shipped work.",
        items: [
          "Phase 1 aggregate status drift corrected to match completed child stories.",
          "Oracle roadmap closure retained in delivery history instead of pretending it is still active execution."
        ]
      },
      {
        id: "DONE-005",
        label: "Foundation through Oracle pilot delivery shipped",
        summary: "The earlier roadmap remains complete history: platform foundation, Oracle ingestion, deterministic finance KPIs, leakage review, and CEO/CFO pilot alignment and validation.",
        items: [
          "Core runtime, persistence, orchestration, governance, and UI foundations.",
          "Oracle EBS ingestion, deterministic KPI calculation, and cash-leakage detection.",
          "CEO/CFO pilot alignment, production validation, and pilot readiness work."
        ]
      },
      {
        id: "DONE-006",
        label: "Live /plan backlog-history sync deployed and verified",
        summary: "The approved tracker rewrite is now live on strategyos.live and independently verified against the hosted surface.",
        items: [
          "Approved GitHub Actions lane deployed commit 503f8c66c7d9e55694f3fc0ae4db1881398af565 to strategyos.live.",
          "Live /plan now shows current backlog first and shipped history below it.",
          "Hosted plan_data payload now exposes the CEO bug list, UX bug list, Oracle verification row, and open security rows as active backlog truth."
        ]
      }
    ]
  };
})();
