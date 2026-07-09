(function () {
  window.STRATEGYOS_PLAN = {
    updated: "2026-07-09",
    liveStatus: {
      state: "Overall live truth: executive-surface UI audit fixes are shipped and live-verified; no active rows remain from that tranche.",
      lastVerified: "2026-07-09",
      note: "Latest verified release: 922497e. CI and deploy passed; direct API and browser checks passed for the Assistants header layout, Board room persona data, the board-state caption sync, and Ask Hermes markdown rendering."
    },
    criticalBlockers: [],
    activeActionItems: [],
    hostedVerificationState: {
      summary: "Pass — executive-surface UI audit fixes (release 922497e) are shipped, deployed, and live-verified on strategyos.live; no rows remain active from that tranche.",
      lastChecked: "2026-07-09",
      checks: [
        {
          label: "CI succeeded for release 922497e.",
          result: "pass",
          note: "Full suite passed (1142 passed, 4 skipped) including new regression tests for each of the five fixed bugs, each verified to fail against the pre-fix code and pass against the fix."
        },
        {
          label: "Deploy succeeded for release 922497e.",
          result: "pass",
          note: "Release 922497e cleared deploy to Hetzner (hetzner-qa); protected readiness, governed cloud surface, and public edge header checks all passed with no rollback triggered."
        },
        {
          label: "Live Assistants-page header layout check passed.",
          result: "pass",
          note: "Measured .network-list-head__stats on strategyos.live: full 280px column width with Freshness/Used/Context each occupying a distinct ~87px slot, no overlap."
        },
        {
          label: "Live Board room persona differentiation check passed.",
          result: "pass",
          note: "/public/runs/latest?persona=board now returns a distinct headline (\"Board endorsed the margin plan and ratified the hedge.\") and assistant (Minerva), confirmed different from the CEO persona's payload."
        },
        {
          label: "Live board-state caption sync check passed.",
          result: "pass",
          note: "Clicked Closed then Live on the hosted Board portal stage tiles; the caption below the tiles updated to the Live-stage text immediately, with no stale Closed-stage text lingering."
        },
        {
          label: "Live Ask Hermes markdown rendering check passed.",
          result: "pass",
          note: "Exercised the deployed renderAssistantMarkdownToHtml against headers, bold text, and a pipe table: all rendered as real HTML tags, not literal ** / ### / | syntax; a raw <img> test payload remained safely escaped."
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
        id: "DONE-013",
        date: "2026-07-09",
        label: "Executive-surface UI audit: five bugs fixed and live-verified",
        summary: "A user-reported audit of the executive persona surface (Assistants, Knowledge, Board portal, Ask Hermes) turned up five reproducible bugs; each was root-caused, fixed, covered with a regression test proven to fail pre-fix and pass post-fix, and independently re-verified against the live deployed site.",
        items: [
          "Assistants page: the Freshness/Used/Context column headers rendered as garbled overlapping text because .network-list-head__stats auto-placed into the wrong (56px) grid column behind two visually-hidden sr-only labels; fixed with an explicit grid-column: 3, confirmed live at full 280px width with no overlap.",
          "Board reports copy: corrected \"now sing as one workspace\" to \"now sit as one workspace\".",
          "Board room persona was byte-for-byte identical to Group CEO (same headline, Plan Health score, greeting) because EXECUTIVE_DESIGN[\"personas\"] had no \"board\" entry and silently fell back to CEO's blueprint; added a real board persona (Minerva, governance framing, KPIs/decks/actions) grounded in the existing board-portal fixture data, confirmed live via /public/runs/latest?persona=board returning a genuinely distinct headline and assistant.",
          "Board-state stage-selector caption stuck on stale text after switching stages, because activateBoardState() switches lifecycle stages purely client-side with no re-fetch while boardStateSupportNote() trusted the last-fetched packet's state_detail.note unconditionally; fixed by delegating to the already-guarded boardStateDetailForRender(), confirmed live by clicking Closed then Live and observing the caption update instantly.",
          "Ask Hermes chat showed raw, unparsed markdown (**bold**, ### headers, ---, pipe tables) because message rendering only ever did escapeHtml() into a <p>; added renderAssistantMarkdownToHtml() (escape first, then safe regex transforms for headers/bold/rules/tables), confirmed live against the deployed function with headers, bold, a table, and a raw-HTML-injection safety check.",
          "Investigated and confirmed already-fixed or not reproducible on the live site: Knowledge Graph node-label overlap, previously-hidden Lifecycle/Supplementary panels, board-state click handling, Ask Hermes canned responses, non-interactive-looking list rows (no cursor:pointer or click handler found), and the /executive login gate (unauthenticated visitors only see data explicitly labeled is_illustrative; real findings/evidence stay behind the existing /app auth).",
          "Released and verified commit 922497e after CI/deploy success; all five fixes independently re-checked against the live hosted surface, not just local tests."
        ]
      },
      {
        id: "DONE-012",
        date: "2026-07-09",
        label: "Login page control overflow fixed and live-verified",
        summary: "The /login page's password field and Sign in button rendered wider than the card and bled past its right edge on strategyos.live.",
        items: [
          "Root cause: input/select/button had CSS padding but no box-sizing rule, so the browser's default content-box sizing added that padding on top of each element's width instead of the intended border-box behavior.",
          "Fixed with a universal box-sizing: border-box reset plus explicit width: 100% on the form controls.",
          "Verified by rendering the actual login_page() HTML output and measuring getBoundingClientRect(): select/input/button now sit flush at identical left/right edges as the form column.",
          "Released and verified commit 2b01071; confirmed live on https://strategyos.live/login with no overflow."
        ]
      },
      {
        id: "DONE-011",
        date: "2026-07-09",
        label: "Persistence, retrieval, and hardcode fixes shipped and live-verified",
        summary: "A persistence/retrieval/hardcode gap analysis found a bare psycopg.connect() per call with no pooling, a lost-update race in two JSON-store mutators, and finance-detector evidence anchors hardcoded to the synthetic fixture's vendor names; all three were fixed, tested, and verified against the live deployed site.",
        items: [
          "Added a process-wide psycopg_pool.ConnectionPool to database_connection(), with a _PooledConnectionHandle wrapper verified against a real Postgres instance to correctly return connections to the pool (a bare pool.getconn() + with-block loop was empirically confirmed to leak connections and raise PoolTimeout after max_size calls).",
          "Routed KpiRepository.update and InvestigationRepository.save through the existing _mutate_file lock helper, closing a lost-update race verified with a threading.Barrier concurrency test that reliably dropped writes pre-fix.",
          "De-pinned FX-hedge and auto-renewal detector evidence anchors from hardcoded fixture literals (\"Bordeaux Wines\", \"GulfLogistics\") to values derived from the finding's own vendor data, and fixed check_quality() spuriously flagging two fixture-only filenames as missing OCR evidence on any dataset that doesn't contain them.",
          "Released and verified commit c549b63; confirmed live via strategyos.live's authenticated /runs/latest/findings and /data/evidence-preview endpoints showing the FX-hedge and auto-renewal findings with correctly resolved, hash-matched citations (41/41 citations resolved run-wide)."
        ]
      },
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
