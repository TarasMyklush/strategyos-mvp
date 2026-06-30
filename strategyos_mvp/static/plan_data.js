(function () {
  window.STRATEGYOS_PLAN = {
    updated: "2026-06-30",
    liveStatus: {
      state: "Source corrected to the exact six-section tracker structure; main handoff, deploy, and hosted re-verification are still pending.",
      lastVerified: "2026-06-30",
      note: "Current truth: this local source now matches the required tracker shape, but strategyos.live is not yet re-verified against it."
    },
    criticalBlockers: [
      {
        id: "BLK-001",
        title: "Hosted /plan is not yet on the corrected six-section source",
        status: "in_progress",
        detail: "The source fix is prepared locally, but main handoff and deploy still need to run before the hosted tracker matches this structure."
      },
      {
        id: "BLK-002",
        title: "CEO interaction defects still keep the tranche open",
        status: "in_progress",
        detail: "Navigation, Hermes panel, prompt, evidence, inline ask, chart, and feedback defects remain active execution work."
      },
      {
        id: "BLK-003",
        title: "Oracle correctness sweep still needs redeploy plus live verification",
        status: "in_progress",
        detail: "The reviewed Oracle/public-route/math fixes must be rechecked on the hosted surface before closure can be claimed."
      }
    ],
    activeActionItems: [
      { id: "BUG-001", assignee: "Frontend", status: "in_progress", percentDone: 50, description: "Fix broken Assistants and Knowledge nav tabs." },
      { id: "BUG-002", assignee: "Frontend", status: "in_progress", percentDone: 50, description: "Fix Hermes conversation panel overflow and broken layout." },
      { id: "BUG-003", assignee: "Frontend", status: "in_progress", percentDone: 50, description: "Fix the broken new conversation button." },
      { id: "BUG-004", assignee: "Frontend", status: "in_progress", percentDone: 50, description: "Fix suggested question chips so they trigger usable prompts." },
      { id: "BUG-007", assignee: "Frontend", status: "in_progress", percentDone: 50, description: "Fix the broken show-the-work action." },
      { id: "BUG-008", assignee: "Frontend", status: "in_progress", percentDone: 50, description: "Fix inline Ask so send produces a visible response instead of clearing silently." },
      { id: "UX-002", assignee: "Frontend", status: "in_progress", percentDone: 50, description: "Add axes, markers, and usable tooltips to charts." },
      { id: "UX-003", assignee: "Frontend", status: "in_progress", percentDone: 50, description: "Add a clear and usable scroll affordance in the Hermes panel." },
      { id: "UX-004", assignee: "Frontend", status: "in_progress", percentDone: 50, description: "Show an explicit GM note availability state." },
      { id: "UX-005", assignee: "Frontend", status: "in_progress", percentDone: 50, description: "Make the send-and-receive affordance real or remove it." },
      { id: "UX-006", assignee: "Frontend", status: "in_progress", percentDone: 50, description: "Add a visible label or tooltip to the theme toggle." },
      { id: "UX-007", assignee: "Frontend", status: "in_progress", percentDone: 50, description: "Remove orphaned Hermes sender labels and empty message bubbles." },
      { id: "UX-008", assignee: "Frontend", status: "in_progress", percentDone: 50, description: "Add a feedback or report-bug escape hatch." },
      { id: "ORACLE-VERIFY", assignee: "Release + QA", status: "in_progress", percentDone: 50, description: "Redeploy and live-verify the reviewed Oracle correctness sweep." },
      { id: "SEC-001", assignee: "Backend", status: "in_progress", percentDone: 50, description: "Replace proxy-secret equality checks with constant-time comparison in auth.py." },
      { id: "SEC-002", assignee: "Backend", status: "in_progress", percentDone: 50, description: "Remove the hardcoded public-scrub literal and rely on explicit allow-listing." }
    ],
    hostedVerificationState: {
      summary: "Fail — the corrected six-section tracker source is ready locally, but the hosted page has not yet been redeployed and re-verified.",
      lastChecked: "2026-06-30",
      checks: [
        {
          label: "Live /plan shows the exact six required sections in the required order.",
          result: "fail",
          note: "Pending main handoff, deploy, and direct hosted check."
        },
        {
          label: "Hosted active tranche table shows ID, description, assignee, status, and %done.",
          result: "fail",
          note: "Corrected in local source only until redeploy is complete."
        },
        {
          label: "Hosted tracker still represents CEO interaction defects, Oracle verification, and security findings truthfully.",
          result: "fail",
          note: "Must be verified again on strategyos.live after deployment."
        }
      ]
    },
    backlog: {
      title: "Later hardening / backlog",
      summary: "Open items not active in this tranche stay here, sorted by priority.",
      rows: [
        { id: "BUG-005", priority: "high", status: "open", title: "Fix findings expand buttons" },
        { id: "BUG-006", priority: "high", status: "open", title: "Fix broken developments projection rows" },
        { id: "UX-001", priority: "medium", status: "open", title: "Move or restyle the floating Hermes button so it stops obscuring KPI data" },
        { id: "COPY-001", priority: "medium", status: "open", title: "Tighten the oversized headline and adjacent copy already in scope" }
      ]
    },
    completedHistory: [
      {
        id: "DONE-006",
        date: "2026-06-30",
        label: "Live /plan backlog-history sync deployed and verified",
        summary: "The approved tracker rewrite was previously deployed and independently verified against the hosted surface.",
        items: [
          "Approved GitHub Actions lane deployed commit 503f8c66c7d9e55694f3fc0ae4db1881398af565 to strategyos.live.",
          "Live /plan showed current backlog first and shipped history below it.",
          "Hosted plan_data payload exposed the CEO bug list, UX bug list, Oracle verification row, and open security rows as active backlog truth."
        ]
      },
      {
        id: "DONE-004",
        date: "2026-06-30",
        label: "Recent tracker truth fixes shipped",
        summary: "Earlier /plan truth corrections already moved aggregate status and roadmap closure into the correct historical posture.",
        items: [
          "Phase 1 aggregate status drift corrected to match completed child stories.",
          "Oracle roadmap closure retained in delivery history instead of pretending it was still active execution."
        ]
      },
      {
        id: "DONE-002",
        date: "2026-06-29",
        label: "CEO demo package shipped",
        summary: "The CEO walkthrough artifact pack was completed and belongs in history, not in the active backlog.",
        items: [
          "Final CEO demo package published under artifacts/ceo-demo.",
          "Supporting video, screenshots, and package notes bundled together.",
          "Demo boundary conditions disclosed truthfully in the package materials."
        ]
      },
      {
        id: "DONE-003",
        date: "2026-06-29",
        label: "Audit, cleanup, and handoff pack shipped",
        summary: "Post-backlog closure materials for the Oracle pilot were documented and preserved for handoff.",
        items: [
          "Post-backlog audit and handoff pack published.",
          "Cleanup recommendations and operator next steps recorded for follow-through."
        ]
      },
      {
        id: "DONE-001",
        date: "2026-06-28 and earlier",
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
        id: "DONE-005",
        date: "2026-06-28 and earlier",
        label: "Foundation through Oracle pilot delivery shipped",
        summary: "The earlier roadmap remains complete history: platform foundation, Oracle ingestion, deterministic finance KPIs, leakage review, and CEO/CFO pilot alignment and validation.",
        items: [
          "Core runtime, persistence, orchestration, governance, and UI foundations.",
          "Oracle EBS ingestion, deterministic KPI calculation, and cash-leakage detection.",
          "CEO/CFO pilot alignment, production validation, and pilot readiness work."
        ]
      }
    ]
  };
})();
