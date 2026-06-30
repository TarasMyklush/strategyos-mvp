(function () {
  window.STRATEGYOS_PLAN = {
    updated: "2026-06-30",
    liveStatus: {
      state: "The current deploy lane is still rolling; the next UI tranche is prepared locally so hosted deploy can roll straight into it.",
      lastVerified: "2026-06-30",
      note: "11 active UI rows are staged for the next deployable tranche, 1 later backlog row is parked below, and 7 shipped history entries remain visible below."
    },
    criticalBlockers: [
      {
        id: "BLK-001",
        title: "The next deployable UI tranche centers on BUG-005, BUG-006, and BUG-007",
        status: "open",
        detail: "The source tranche already carries the findings expand, developments projection, and evidence-toggle fixes; hosted proof must wait for the current deploy lane to clear."
      },
      {
        id: "BLK-002",
        title: "The remaining UX backlog is active in source but not yet proved on the hosted surface",
        status: "open",
        detail: "The next tranche keeps UX-001 through UX-008 explicit and active while deploy sequencing catches up with the already-prepared local fixes."
      },
      {
        id: "BLK-003",
        title: "Tracker copy cleanup stays later backlog until this tranche ships cleanly",
        status: "open",
        detail: "COPY-001 remains visible, but it is intentionally parked outside the active UI tranche so the next deploy stays clean and bounded."
      }
    ],
    activeActionItems: [
      { id: "BUG-007", description: "Fix the broken show-the-work action", status: "in_progress", percentDone: 85, assignee: "Salvador / UI lane" },
      { id: "BUG-005", description: "Fix findings expand buttons", status: "in_progress", percentDone: 85, assignee: "Salvador / UI lane" },
      { id: "BUG-006", description: "Fix broken developments projection rows", status: "in_progress", percentDone: 85, assignee: "Salvador / UI lane" },
      { id: "UX-002", description: "Add axes, markers, and usable tooltips to charts", status: "in_progress", percentDone: 85, assignee: "Salvador / UI lane" },
      { id: "UX-003", description: "Add a clear and usable scroll affordance in the Hermes panel", status: "in_progress", percentDone: 85, assignee: "Salvador / UI lane" },
      { id: "UX-004", description: "Show an explicit GM note availability state", status: "in_progress", percentDone: 85, assignee: "Salvador / UI lane" },
      { id: "UX-005", description: "Make the send-and-receive affordance real or remove it", status: "in_progress", percentDone: 85, assignee: "Salvador / UI lane" },
      { id: "UX-006", description: "Add a visible label or tooltip to the theme toggle", status: "in_progress", percentDone: 85, assignee: "Salvador / UI lane" },
      { id: "UX-007", description: "Remove orphaned Hermes sender labels and empty message bubbles", status: "in_progress", percentDone: 85, assignee: "Salvador / UI lane" },
      { id: "UX-008", description: "Add a feedback or report-bug escape hatch", status: "in_progress", percentDone: 85, assignee: "Salvador / UI lane" },
      { id: "UX-001", description: "Move or restyle the floating Hermes button so it stops obscuring KPI data", status: "in_progress", percentDone: 85, assignee: "Salvador / UI lane" }
    ],
    hostedVerificationState: {
      summary: "Pending — the next UI tranche is prepared locally, but strategyos.live is still serving the earlier hosted lane until deploy sequencing reaches this source set.",
      lastChecked: "2026-06-30",
      checks: [
        {
          label: "This source revision keeps /plan on the exact six-section tracker while splitting active rows from later backlog truthfully.",
          result: "pending",
          note: "Local source now carries an 11-row active UI tranche with COPY-001 parked below as later backlog; hosted proof still waits on the next deploy handoff."
        },
        {
          label: "Hosted active tranche must prove BUG-005, BUG-006, BUG-007, and the UX follow-ons rather than only the earlier core interactivity lane.",
          result: "pending",
          note: "The current hosted assets still lag this next tranche, so these rows stay active and not historical until the deploy lane lands them."
        },
        {
          label: "Hosted verification remains open until the current deploy tranche clears and this prepared UI lane is actually served live.",
          result: "pending",
          note: "This source tranche is deployable and locally prepared, but it is not yet honest to claim hosted proof for the new UI fixes."
        }
      ]
    },
    backlog: {
      title: "Later hardening / backlog",
      summary: "COPY-001 stays visible as later backlog while the next deployable UI tranche remains bounded to BUG-005/006/007 and UX-001..008.",
      rows: [
        {
          id: "COPY-001",
          priority: "medium",
          status: "pending",
          title: "Tighten the oversized headline and adjacent copy already in scope",
          detail: "Do the copy-polish pass only after the active UI tranche ships and hosted proof is back in sync."
        }
      ]
    },
    completedHistory: [
      {
        id: "DONE-007",
        date: "2026-06-30",
        label: "Earlier live deploy tranche landed and was re-verified",
        summary: "The hosted surface currently proves the earlier core lane plus the Oracle/security follow-through; the next UI tranche remains active above until it is actually deployed.",
        items: [
          "GitHub main commit 462ff7068a9ee1e9405e506c5d9c3ec244efbbd5 deployed via StrategyOS Deploy run 28441307264.",
          "Hosted executive assets currently prove the earlier shipped core lane rather than the queued BUG-005/006/007 plus UX follow-on tranche.",
          "Hosted /public/runs/latest/audit-summary now returns the sanitized public-safe payload with internal counts withheld, and hosted findings remain scrubbed to board-safe signal labels.",
          "BUG-001, BUG-002, BUG-003, BUG-004, and BUG-008 are backed by hosted proof from that deploy.",
          "ORACLE-VERIFY, SEC-001, and SEC-002 are backed by hosted proof from that deploy and are closed out of active execution state."
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
