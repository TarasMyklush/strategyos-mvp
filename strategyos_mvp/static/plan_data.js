(function () {
  window.STRATEGYOS_PLAN = {
    updated: "2026-06-30",
    liveStatus: {
      state: "Combined live tranche is now deployed to strategyos.live and directly re-verified on the hosted surface.",
      lastVerified: "2026-06-30",
      note: "12 active rows remain in progress for the next burn-down tranche, and 7 shipped history entries remain visible below."
    },
    criticalBlockers: [
      {
        id: "BLK-001",
        title: "The next hosted UI tranche still needs BUG-005, BUG-006, and BUG-007 burn-down",
        status: "open",
        detail: "Core CEO interactivity is now live; the remaining broken findings, developments, and evidence-toggle actions are the next highest-leverage defects."
      },
      {
        id: "BLK-002",
        title: "UX follow-ons remain open after the core interactivity tranche",
        status: "open",
        detail: "Chart affordances, Hermes scroll/empty states, floating control positioning, and feedback polish remain in backlog after the hosted proof burn-down."
      },
      {
        id: "BLK-003",
        title: "Tracker copy cleanup remains after the hosted deploy tranche",
        status: "open",
        detail: "The oversized headline/copy treatment still needs a tighter pass after this live interactivity and backend follow-through release."
      }
    ],
    activeActionItems: [
      { id: "BUG-007", description: "Fix the broken show-the-work action", status: "in_progress", percentDone: 0 },
      { id: "BUG-005", description: "Fix findings expand buttons", status: "in_progress", percentDone: 0 },
      { id: "BUG-006", description: "Fix broken developments projection rows", status: "in_progress", percentDone: 0 },
      { id: "UX-002", description: "Add axes, markers, and usable tooltips to charts", status: "in_progress", percentDone: 0 },
      { id: "UX-003", description: "Add a clear and usable scroll affordance in the Hermes panel", status: "in_progress", percentDone: 0 },
      { id: "UX-004", description: "Show an explicit GM note availability state", status: "in_progress", percentDone: 0 },
      { id: "UX-005", description: "Make the send-and-receive affordance real or remove it", status: "in_progress", percentDone: 0 },
      { id: "UX-006", description: "Add a visible label or tooltip to the theme toggle", status: "in_progress", percentDone: 0 },
      { id: "UX-007", description: "Remove orphaned Hermes sender labels and empty message bubbles", status: "in_progress", percentDone: 0 },
      { id: "UX-008", description: "Add a feedback or report-bug escape hatch", status: "in_progress", percentDone: 0 },
      { id: "UX-001", description: "Move or restyle the floating Hermes button so it stops obscuring KPI data", status: "in_progress", percentDone: 0 },
      { id: "COPY-001", description: "Tighten the oversized headline and adjacent copy already in scope", status: "in_progress", percentDone: 0 }
    ],
    hostedVerificationState: {
      summary: "Pass — the combined live tranche is deployed on strategyos.live and the hosted assets now prove the intended source state.",
      lastChecked: "2026-06-30",
      checks: [
        {
          label: "Live /plan shows the exact six required sections in the required order.",
          result: "pass",
          note: "Hosted /plan and hosted plan_data now serve the corrected six-section tracker structure."
        },
        {
          label: "Hosted active tranche table shows ID, description, assignee, status, and %done.",
          result: "pass",
          note: "Hosted tracker keeps the 12-row active tranche visible; this source correction restores the proper In Progress labels without changing the row count."
        },
        {
          label: "Hosted tracker still represents CEO interaction defects, Oracle verification, and security findings truthfully.",
          result: "pass",
          note: "Hosted proof now exists for the deployed CEO interactivity tranche and the ready Oracle/security follow-through."
        }
      ]
    },
    backlog: {
      title: "Later hardening / backlog",
      summary: "No later hardening rows currently sit outside the active 12-row tranche.",
      rows: []
    },
    completedHistory: [
      {
        id: "DONE-007",
        date: "2026-06-30",
        label: "Combined live deploy tranche landed and was re-verified",
        summary: "The hosted surface now proves the core CEO interactivity tranche plus the ready Oracle/security follow-through on main.",
        items: [
          "GitHub main commit 462ff7068a9ee1e9405e506c5d9c3ec244efbbd5 deployed via StrategyOS Deploy run 28441307264.",
          "Hosted executive assets now expose the Assistants/Knowledge nav, Theme label, Report bug action, writable-thread ask flow, empty-state cleanup, and driver follow-up prompts.",
          "Hosted /public/runs/latest/audit-summary now returns the sanitized public-safe payload, and hosted findings remain scrubbed to board-safe signal labels.",
          "BUG-001, BUG-002, BUG-003, BUG-004, BUG-008, ORACLE-VERIFY, SEC-001, and SEC-002 can move out of open execution state after hosted proof."
        ]
      },
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
