(function () {
  window.STRATEGYOS_PLAN = {
    updated: "2026-07-01",
    liveStatus: {
      state: "Overall live truth: the final COPY-001 copy-polish row is complete on the source surface. All behavior, UX, and copy work in this tranche now lives in shipped history.",
      lastVerified: "2026-07-01",
      note: "0 active UI rows remain, 0 UI rows are parked outside the tranche, and 9 shipped history entries remain visible below."
    },
    criticalBlockers: [],
    activeActionItems: [],
    hostedVerificationState: {
      summary: "Pass — COPY-001 is closed in source: the oversized plan headline and adjacent copy were tightened, no active action items remain, and prior behavior/UX work stays in shipped history.",
      lastChecked: "2026-07-01",
      checks: [
        {
          label: "Hosted /static/executive.js, /static/executive.css, and /static/plan_data.js now hash-match the local source tranche.",
          result: "pass",
          note: "Direct asset comparison confirmed the hosted executive and plan assets are byte-for-byte identical to the local release candidate."
        },
        {
          label: "Hosted executive assets expose the expected UI fixes: findings/developments expansion, show-the-work toggle, chart axes/tooltips, GM-note empty state, theme label, feedback path, and Hermes scroll affordances.",
          result: "pass",
          note: "Direct hosted inspection found the live executive HTML/JS/CSS markers for the 11-row behaviour tranche, so those rows no longer belong in active execution."
        },
        {
          label: "COPY-001 is closed after the final source copy pass.",
          result: "pass",
          note: "The active tranche is now empty; keep /plan focused on that closure truth instead of repeating already-hosted UI fixes or stale residual-work language."
        }
      ]
    },
    backlog: {
      title: "Later hardening / backlog",
      summary: "No UI rows are intentionally parked outside the active tranche right now. Leave this section empty rather than pretending hidden backlog does not exist.",
      rows: []
    },
    completedHistory: [
      {
        id: "DONE-009",
        date: "2026-07-01",
        label: "Final copy-polish row closed",
        summary: "COPY-001 is complete: the plan headline is tightened, the adjacent copy is concise, and the active-action table now truthfully shows no remaining plan-scope rows.",
        items: [
          "Reduced the /plan hero headline scale and vertical weight so it no longer dominates the tracker.",
          "Replaced the adjacent hero copy with a concise closure statement tied to shipped-history truth.",
          "Moved COPY-001 out of active execution state; no critical blockers or active action items remain for this tranche."
        ]
      },
      {
        id: "DONE-008",
        date: "2026-06-30",
        label: "Hosted executive tranche verified for BUG-005/006/007 and UX-001..UX-008",
        summary: "The live executive surface now proves the queued 11-row UI behaviour tranche; only COPY-001 remains active above.",
        items: [
          "Hosted /static/executive.js, /static/executive.css, and /static/plan_data.js were re-checked and hash-match the local source tranche byte-for-byte.",
          "Hosted executive HTML shows the live Theme and Report bug controls plus the expected ux-20260630 cache marker.",
          "Hosted executive JS proves findings/developments expansion, show-the-work toggle wiring, chart axes/tooltips, explicit No GM note state, real send-and-receive flow, and the Hermes feedback/report-bug paths.",
          "Hosted executive CSS proves the widened Hermes drawer, added bottom page clearance, and scroll-gradient affordances that were part of the UX tranche.",
          "BUG-005, BUG-006, BUG-007, and UX-001 through UX-008 are therefore closed out of active execution state on the live surface."
        ]
      },
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
