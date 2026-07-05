(function () {
  window.STRATEGYOS_PLAN = {
    updated: "2026-07-05",
    liveStatus: {
      state: "Overall live truth: Ask Hermes assistant hardening is shipped and live-verified; no active assistant-hardening rows remain.",
      lastVerified: "2026-07-05",
      note: "Latest verified release: 1ddd7e1. CI and deploy passed; direct API and browser drawer checks passed for mode=auto, mode=llm, deterministic scenarios, evidence prompts, and UI answer rendering."
    },
    criticalBlockers: [],
    activeActionItems: [],
    hostedVerificationState: {
      summary: "Pass — assistant hardening release 1ddd7e1 is shipped, deployed, and live-verified on the public Ask Hermes surface; no assistant-hardening action rows remain active.",
      lastChecked: "2026-07-05",
      checks: [
        {
          label: "CI succeeded for release 1ddd7e1.",
          result: "pass",
          note: "The assistant hardening regression lane passed before release, including orchestrator, deterministic-vs-LLM boundary, QA transport, API, scenario parser, twin reasoning, fixtures, and smoke coverage."
        },
        {
          label: "Deploy succeeded for release 1ddd7e1.",
          result: "pass",
          note: "Release 1ddd7e1 cleared deploy and the hosted surface now reflects the hardened assistant path and updated /plan copy."
        },
        {
          label: "Working tree is clean at release verification time.",
          result: "pass",
          note: "Release verification recorded a clean working tree so the shipped assistant-hardening summary matches the exact deployed commit."
        },
        {
          label: "Live direct /assistant/chat checks passed for margin variance in mode=auto and mode=llm.",
          result: "pass",
          note: "The hosted assistant returned grounded CEO answers for \"What’s driving the margin variance?\" with citations and low-risk trace instead of collapsing into generic intercept copy."
        },
        {
          label: "Live browser drawer check passed for 'What’s driving the margin variance?'.",
          result: "pass",
          note: "Browser verification confirmed the public Ask Hermes drawer rendered the grounded margin-variance answer, including FX exposure, EUR/SAR, SAR 9k/week, Tamween SAR 1.2M, API costs, citations, and low-risk trace."
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
        id: "DONE-010",
        date: "2026-07-05",
        label: "Ask Hermes assistant hardening shipped and verified",
        summary: "The public CEO Ask Hermes assistant now uses the shared server-side assistant path with deterministic finance/scenario routing first and governed LLM fallback for open-ended prompts, backed by tests, CI, deploy, and live UI verification.",
        items: [
          "Removed brittle persona regex topic interceptors so substantive margin, revenue, cash, risk, KPI, Digital Health, e-Pharmacy, and recovery questions no longer get generic “which part do you want?” replies before QA/LLM can answer.",
          "Kept deterministic-first finance behavior: scenario/math answers and governed public-packet facts stay deterministic; LLM is used only for the unstructured/open-ended tail.",
          "Hardened provider transport with bounded transient retry/backoff and non-blocking assistant API handoff; provider failures now retain trace metadata instead of silently collapsing into canned copy.",
          "Bounded assistant audit memory with a capped audit log and documented the process-local durability boundary.",
          "Wrapped untrusted evidence/public packet text before model egress so prompt-injection-like finding/citation text is treated as evidence, not instructions.",
          "Expanded regression coverage across assistant orchestrator, deterministic-vs-LLM boundary, LLM QA transport/retry/guarding, QA API, scenario parser, twin reasoning, fixtures, and deploy smoke gates.",
          "Released and verified latest commit 1ddd7e1 after CI/deploy success; live /assistant/chat and browser drawer now answer “What’s driving the margin variance?” with a grounded CEO answer including FX exposure, EUR/SAR, SAR 9k/week, Tamween SAR 1.2M, API costs, citations, and low-risk trace."
        ]
      },
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
