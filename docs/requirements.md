# StrategyOS product requirements

Canonical specification · consolidated 5 September 2026 · implementation baseline `c03e958`

This is the single active requirements document. It replaces the dated technical/design specifications, execution plans and R2/R4 punch lists. It defines intended behavior; it does not certify that every requirement is implemented. The [gap register](assessment/gap-register.json) and [assessment](assessment/gap-analysis.md) record the evidence and remaining work. Architecture belongs in [architecture.md](architecture.md); release and operating instructions belong in [operations.md](operations.md) and the deployment runbook.

## Authority and change rules

The original Technical & Agent Requirements and KPI Calculation Specification establish the product and financial formulas. The July 13 decisions, July 23 backlog and July 27 execution plan refine the experience. Legion v3 (July 28), followed by R2 and R4, supersede conflicting earlier surface requirements. Folder dates are not approval dates. Full standalone R3 and WO-2 sources were not available; references to them do not establish unseen requirements. Source hashes and original locations are recorded in [the source register](maintenance/source-register.json).

Resolved conflicts:

| Topic | Canonical rule |
|---|---|
| Plan Health | Ten board commitments, direction-adjusted, evidence-backed coverage; supersedes the old four-ring composite. The four financial rings remain diagnostics. |
| Palette | Sage, ochre and terracotta. Earlier red/amber/green wording and v3's green achievement wording do not override R4. |
| Preview personas | CEO and Board are the supported executive preview. Other personas may be visibly unavailable. This does not fulfill the four-persona enterprise requirement. |
| Assistant | Deterministic arithmetic and permission checks remain authoritative; provider-backed narrative must answer the actual question from permitted evidence. External context is separately labelled. |
| Authority | A published matrix is a policy requirement, not proof of complete enforcement. G06/G07 remain open. |
| Decisions | A recorded approval is distinct from an executed business action. Demo/session state must be identified as such. |
| Product identity | StrategyOS remains the application name. KYVERN video exports are presentation assets; they do not constitute an application rename. A configurable name/logo remains R4 work. |
| Delivery claims | Earlier “complete”, “production-ready” and historical green test reports are superseded by the current evidence and open gaps. |

Changes must update this file, the affected acceptance criteria, implementation and tests in the same change. Do not introduce another dated plan/specification as an active authority. Keep experimental branches temporary; `main` is the canonical application branch.

## Product and release scope

**REQ-01 — System of Intent.** Compile a company's board-approved strategy into a shared operating picture: strategy → objectives → commitments → initiatives → KPIs → actuals → drift → decisions → verified outcomes. The common driver families are Growth, Margin, Capital and Resilience, with promotable Sustainability. Company-specific leaves, targets, owners, cadence and materiality are data, not hardcoded client IDs. A second company must recompile without application edits. Current generic compiler gap: G12.

**REQ-02 — Personas.** Group CEO, BU CEO/GM, Group CFO and BU CFO share facts but have distinct altitude, permissions and workflows. Board members see approved board material through Minerva. A COO is outside initial scope. Finance roles use actual financial lenses; unavailable roles show an honest coming state, including direct URL access. CEO uses Hermes, CFO Atlas, BU GM Iris; remaining assistant names come from the profile source. Greeting uses the person's name when known. G25 tracks completion.

**REQ-03 — Commercial scope.** The initial scope is core intelligence plus Cash-Leakage Discovery. Marketplace discovery is browse-only until an explicit product decision authorizes installation. Catalog entries must distinguish implemented workers from proposed products. Native/third-party split, client systems, supported volume, model validation and contractual tier promises remain explicit decisions (G33); old indicative prices are not approved offers.

## Data, intent and evidence

**REQ-04 — Two builders.** The KPI compiler resolves intent; the knowledge-graph builder resolves entities. Both use the same governed sources. A knowledge engineer reviews uncertain content classification, field mapping and entity matches. Ambiguity must not silently become approved mapping. Typed invoice-header normalization should be additive to the current workbook path, with currency, vendor/customer, amount, date, confidence and provenance fields; downstream controls migrate only after parity. G12/G16.

**REQ-05 — Intake and connectivity.** Day-one folder/upload intake supports content-based classification, arbitrary filenames, stable source identities, hashes, PDF/image OCR and schema aliases. Surface unreadable, unsupported, unmapped, stale and excluded inputs and explain partial-run readiness. Production requires incremental connectors and repeatable cursor/watermark handling, idempotent ingestion, retry and reconciliation. Connector priorities are ERP GL/AP/AR, procurement, bank statements/treasury and available warehouse data; then FX, collections, CRM, HRIS, contracts/DMS and calendar/email. Vendor-specific tables/fields require client validation. A catalog entry is not a working connector (G14).

**REQ-06 — Source boundaries.** Separate current evidence, historical context, restricted context, evaluator/answer-key material and control-plane instructions. Imported documents cannot authorize tools or rewrite policy. Answer keys, planted-pattern terminology and test instructions never enter customer narrative or display fields. Restrict finance claims to the selected run/pack and authorized sources. Calendar, board and HR material retain their own access scope. Restricted artifacts must not leak through searches, downloads, projections or model context (G06/G07).

**REQ-07 — Freshness.** Show source as-of time and refresh cadence. Target transactional refresh is approximately 15 minutes or webhook driven; treasury is normally overnight, intraday only with an actual feed; FX daily, master data nightly, strategy on approved change. These are target cadences pending connector validation, not current service guarantees. Quarterly truths do not acquire fabricated daily movement. Maintain real history separately from demo day selection (G15).

**REQ-08 — Intent Vault.** One schema serves workshop capture and the product's read/govern surface. Read-only MVP shows plan version, ratification, commitments, initiatives, owners, approvers, amendment history and affected KPI/briefing recompilation; every diagnostic KPI links to its commitment. Acceptance includes at least three actual source-backed amendment entries. Phase two adds proposed/amended/ratified transitions with separate proposal/approval rights, versioning and downstream impact. Free-form strategy authoring and multi-plan scenarios are outside this MVP. G13; R4-F1.

**REQ-09 — Evidence contract.** Every business number carries a source reference, calculation, unit/currency, period/as-of, entity scope and measurement status. Drill opens the cited file/location. UI labels use business names, never internal paths or run IDs. Estimates remain labelled and never silently counted as measured facts. A missing conversion or comparator stays unavailable. Explanation chains connect data → commitment → gap → confidence and what would change it. First complete trace is the FX finding, traversable in at most four taps. G03–G05/G19; R4-I3.

## Deterministic financial contract

**REQ-10 — Calculation conventions.** Normalize currency using the appropriate dated reporting-currency rate before aggregation; retain original amount/rate. Resolve BU from the accounting dimension; apply intercompany eliminations at group level. Period and days-in-period are configurable. Distinguish null from zero, ratios from percentages and margin percentage points from basis points. Every variance bridge must reconcile or show its residual. An LLM may propose scenario inputs and narrative, never replace computed outputs. G03/G04/G16/G18.

| Metric | Required calculation / qualification |
|---|---|
| Revenue | Sum revenue-account balances for period and BU. Percent of plan = actual / approved plan × 100. AR/OM run-rate is a leading indicator, not closed GL revenue. |
| EBITDA and margin | Revenue − COGS − operating opex excluding D&A, interest and tax; margin = EBITDA / revenue. Margin-plan difference in bps = (actual margin − plan margin) × 10,000 when ratios are used. |
| Operating cost | Sum operating expense accounts; actual / plan × 100. Lower is better; above 100% is overspend, distinct from its inverted composite attainment. |
| Cash | Cash and equivalents / board-approved floor × 100; show bank and GL source cadence. |
| Revenue quality | Recurring revenue share plus inverse customer concentration; blend/weights must be approved configuration. No invented default blend. |
| DSO / DPO / DIO | AR / revenue × days; AP / approved COGS-or-purchases denominator × days; inventory / COGS × days. Settlement days must be labelled as a proxy, not DSO/DPO. |
| Cash conversion cycle | DSO + DIO − DPO. |
| Net debt / EBITDA | (Interest-bearing debt − cash/equivalents) / trailing-12-month EBITDA. Covenant headroom = covenant limit − leverage. |
| EBITDA bridge | Volume + price/mix + cost + FX + explicit other/residual. Volume = Δunits × base unit margin; price = Δprice × actual units plus separately supported mix; cost = −Δunit cost × actual units; FX = Σ FX amount × Δrate. |
| Cash Pulse | Cash IN = receipts, cash OUT = payments, at-bank = balances at as-of, leaking = open recoverable findings; prevent bank/subledger double counting. |
| Leading indicators | Same-store growth = Δsame-store sales / prior sales; e-Rx share = e-prescriptions / total prescriptions; cold-chain integrity = in-range / total readings; FX drag = exposed amount × (current − hedge/plan rate). Operational denominators require actual connected inputs. |

**REQ-11 — Plan Health.** Use the ten board commitments. Default glidepath is FY25 actual + (FY28 target − FY25 actual) × elapsed fraction; approved phased glidepaths override it. Normalize higher-is-better as actual/checkpoint and lower-is-better inversely; cap normalized attainment in [0, 1.2]. Compute a weighted mean across commitments with live actuals, then express percent of plan. Weights, direction and effective periods come from governed KPI metadata. Missing/estimated commitments appear in coverage and the drill but do not quietly inflate live coverage. Zero actual remains valid; zero targets require an explicitly approved rule. The drill lists actual, checkpoint, end target, status and sources. The four financial rings remain separate. The current dataset's expected score is a fixture assertion, not a universal product constant. G03/G04.

**REQ-12 — Drift.** Compare actuals to approved trajectory and a rolling 13-week or seasonal baseline. Classify drift from computed values, not source labels alone. Materiality and escalation thresholds are client-policy data with effective date and provenance; draft thresholds in old specifications are illustrative. Hard rule alerts escalate promptly; lower-confidence candidates are triaged; unanswered material outreach escalates on deadline. Show a 13-week Plan Health trajectory and six-week change, consistent with the selected as-of. Monetary cost per time requires defensible unit conversions, operating inputs, direction, period and evidence. Otherwise state the missing inputs without inventing money. G04/G15/G19; R4-I1.

**REQ-13 — Cash-Leakage Discovery.** Cover duplicate payments, cross-ID entity duplicates, off-contract spend, invoice/contract price variance, missed early-payment discounts, unreviewed auto-renewal uplift, unapplied FX hedges and dormant credits. Validate entity linkage and document/payment joins before quantifying. Separate recoverable cash from control weaknesses, counterfactual savings and future opportunity; deduplicate overlapping effects. Rank by recoverable value and provide SAR/original-currency/USD basis as required, confidence, remediation and disputed items.

Analyst and Auditor iterate up to ten rounds; each finding requires at least three corroborating citations and reproducible arithmetic. Fixture acceptance is at least seven of eight planted patterns at medium-or-better confidence, at least half of findings challenged and aggregate recovery within ±15% of the validated answer key. Generic client acceptance cannot depend on planted IDs. Working-capital analysis separately identifies the top three 13-week drift signals, systemic versus one-off causes and cash impact without double counting leakage. G16/G18.

## Executive experience

**REQ-14 — Preserve the approved interaction system.** Maintain ring-to-drill trends and BU movers, attributed GM commentary/BN chips, evidence badges, Show the work, Analyst/Auditor audit, board lifecycle, Thinking Mode, calendar preparation, KPI/evidence graph, threaded Ask, decision chips and review files. Percent of plan plus denominator is primary; absolute amounts are supporting detail. Use sage/ochre/terracotta. Avoid regressions by visual comparison of preserved surfaces and interaction checks. R4-P1–P6.

**REQ-15 — Language and visual answers.** Write concise business language; remove developer jargon, filesystem/API paths, run IDs, writer/stage labels and answer-key vocabulary. Use structured visual blocks for measures, variance contributors, actions, options and evidence, with brief interpretation. Do not collapse meaningful questions into a generic KPI card. G28; Legion-B12; R2-1/2/3/5/6/7.

**REQ-16 — Coherent contextual Ask.** All entry points use one request contract carrying persona, authorized entity scope, run/as-of, subject, question and conversation. Questions about a KPI include contributors, chart period and approved comparator. Signal items open their detail/context; the visible composer and submitted text remain synchronized. Follow-ups preserve context and choices. Separate source-backed enterprise facts from explicitly marked external advice; current outside knowledge requires an enabled, approved retrieval/provider path. Unsupported specifics are refused with a concrete data request. Missing information should not prevent answering supported portions. Morning notes are persona-specific, evidence-backed and calendar-aware. G05/G22; July27-WS2–6; Legion-B4.

**REQ-17 — Demo time and activity.** A single explicit virtual clock governs all demo relative dates, morning notes, last visit, feeds and week-ahead. Default June 1, 2026 at 08:00 Riyadh is demo time, not a current refresh claim. Demo scrubber is hidden outside demo mode. Separate analysis from since-last-visit developments and achievements; each event resolves to evidence and impacted KPI. Recognition targets come from source data. Two consecutive days must produce supported visible differences. Empty states do not invent handoffs or activity to avoid zero counters. G15/G28; Legion-B2; R2-4.

**REQ-18 — Calendar, files and decisions.** Calendar items classify business relevance and open event-specific Thinking Mode context; verify three distinct event types and resolving references. Review-file cards identify availability, owner, status and permitted downloads. Operator reprocessing is explicit and audited. Decision approve/decline/hold updates the chip, feed and assistant acknowledgement consistently. Any actual execution remains separately permissioned and confirmed by its result. Recovery meter reconciles all relevant identified/locked/recovered records with per-finding drill; do not slice the first eight decision rows. G17/G21; Legion-B6/B9/B10; July27-WS7/8.

**REQ-19 — Board memory.** Pre-board → live → closed is a governed lifecycle. Board access is limited to CEO-approved versions. Closing creates an immutable packet and context snapshot, with hash/version, approved figures, documents and authority decisions. Closed views and board questions use that snapshot, never changing live data. Supplementary questions and later corrections remain separately versioned. G08; R4-P4.

**REQ-20 — Decision Velocity.** Persist surfaced_at, decided_at and first_action_at independently. Show median surfaced-to-decided and decided-to-acted time, trend and pending-item age from the log. Approval affects decision time; only verified execution affects first action. Backfilled demo timestamps are labelled synthetic. G20; R4-F2.

**REQ-21 — Thinking Mode.** Scenario inputs and assumptions are explicit; derived outputs are deterministic and provenance-backed. Modelled results are separate from actuals and approved plans. Sandbox discussions do not execute business changes. Provide two configuration-driven frameworks: decision one-pager (situation, options/cost-benefit, risks, recommendation, owner/deadline) and drift diagnosis (intent, reality, gap, drivers, options, cost of inaction). Launch from decision/KPI/calendar anchors, support chat edits and export to the board-pack review path. Every quantitative cell cites. G24; R4-F3.

## Agents, governance and operations

**REQ-22 — Durable agents.** An agent has a versioned definition, allowed tools, task handler, policy and observable execution. Required product roles span intent, drift, chief of staff, presentation, visualization, data engineering, scenarios and audit; four existing runtime specialists do not prove all continuous roles. Persist task state, conversations, attempts, typed handoffs, results, approvals and append-only events. Use timeouts, retry budgets, resumable event cursors, idempotency keys and unique effects. Delegation cannot increase authority. Counts/statuses come from runtime facts; seeded collaboration is visibly demonstration content. Chat must ultimately survive refresh/sign-in through server persistence. G22.

**REQ-23 — Readiness and audit.** Assistant readiness shows freshness, context depth and usage, plus explainable group rollup. Activity summary reconciles to per-agent and full audit records. Trace user, tenant, run/pack, model, source accesses, tool calls, approvals and outcome; store sensitive inference details under controlled retention/access. Approval gates and per-process audit remain visible, with a finding-to-trail path in at most two clicks. Legion-B5/B7/B8; R4-P5.

**REQ-24 — Authority and isolation.** Every protected read, question, search, download, recommendation and action checks tenant, BU, user/persona, agent, domain, data-source ACL and policy version before retrieval/execution. Rights are none, view, analyse, recommend and act-with-approval; approval rights do not grant autonomous action. Persist versioned matrix changes and approver chains with optimistic concurrency and audit. Capability tokens bind effective authority to tenant/task/tool/context; replay and scope escalation fail. UI selectors and human-readable matrix assertions do not establish authorization. Session logout must revoke server access. G06/G07/G09.

**REQ-25 — Sovereignty and deployment.** Support shared cloud, dedicated cloud, client private cloud and on-prem/air-gap as separately validated tiers. The product does not silently fall back to external inference. External model/storage/OCR/batch use requires explicit deployment policy. A truthful configuration-driven residency chip shows hosting location, inference mode and egress posture on executive/board surfaces, linking to plain-language detail. No sovereign label is inferred from a configuration flag alone; tier acceptance requires network and operational evidence. G26; R4-I2.

**REQ-26 — Localization, accessibility and identity.** Arabic/English, full RTL, localized numbers/dates, keyboard access, focus behavior, responsive layouts and light/dark contrast require acceptance. Customer sign-in must not expose internal/test-role credentials. A single product-name token and logo slot must govern the application when rename readiness is implemented; assistant naming is a deliberate consistent system. G25/G27/G28; R4-I4.

**REQ-27 — Release quality.** One reviewed release records commit SHA, immutable image digest, schema identity, source-pack hash, run ID, approval state, provider/policy configuration and validation evidence. Local tests must be isolated from active source packs, credentials and run pointers. Critical portable dataset tests cannot silently return success when data is missing. Service-dependent tests require dedicated environments and visible skip reporting. A 50-question sample across all 18 themes must produce at least 45 correct answers, resolving citations and zero fabricated numbers; route-match flags are not correctness scores. Verify all three planted strategic drifts from source data and the preserved UI surfaces. G01/G02/G10/G11/G32.

**REQ-28 — Reliability and capacity.** Validate agreed client volumes before sizing: original modelling envelope was approximately 500–1,000 invoices/day, 20,000–50,000 per period and 10–100 reports of 3,000–5,000 lines. Measure ingest, graph-build and answer latency under concurrency, error/retry rates and model cost. Agree SLOs, RPO/RTO, retention and ownership; exercise backup restore and code/schema/data rollback. Packaging must include all runtime assets and dependencies must become reproducibly locked. A successful local test suite does not establish production capacity or recovery. G29/G30/G31.

## Traceability and delivery gates

| Previous requirement family | Canonical requirements |
|---|---|
| Technical specification §§0–2 | REQ-01–04, REQ-08, REQ-22 |
| Technical §§3–4; sourcing map | REQ-05–07, REQ-10, REQ-28 |
| Technical §§5–8; KPI specification | REQ-09–13, REQ-21–28 |
| July13 WS0–7; July23 SOS-001–026 | REQ-14–18, REQ-22–28 |
| July27 WS2–8 | REQ-16, REQ-18, REQ-24, REQ-27 |
| Legion B1–B4 | REQ-11, REQ-17, REQ-02, REQ-16 |
| Legion B5–B8 | REQ-22/23, REQ-18, REQ-23, REQ-23 |
| Legion B9–B12 | REQ-18, REQ-18/21, REQ-02, REQ-15/26 |
| R2-1–7; later referenced freeze requirement | REQ-16, REQ-06/15, REQ-15, REQ-17/18, REQ-15, REQ-11/14, REQ-26; REQ-19 |
| R4 P1–P6 | REQ-14, REQ-19, REQ-23 |
| R4 I1–I4 | REQ-12, REQ-25, REQ-09, REQ-26 |
| R4 F1–F3 | REQ-08, REQ-20, REQ-21 |
| Agent/invoice/graph/search/scenario technical plans | REQ-04–10, REQ-16, REQ-21–24, REQ-28 |

Gate 1 establishes release/data truth and closes trust defects: G01–G10, including quantitative validation, authorization and board freeze. Gate 2 proves a controlled client pilot: connectors/data readiness, governance, actual workflow outcomes and service tests. Gate 3 expands the reusable enterprise platform, four personas, Intent Vault, continuous operation and tier guarantees. The current gap register is the sole backlog for these gaps; preserve stable Gxx IDs and attach closure evidence instead of declaring entire waves complete.
