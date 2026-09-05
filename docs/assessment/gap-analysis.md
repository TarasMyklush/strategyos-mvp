# StrategyOS gap analysis

Assessment date: 2026-09-05. Reviewed baseline: `c03e95816dedf6dedf05778cb725d42a84c29de2`.

StrategyOS has substantive governed finance analysis, executive surfaces and specialist runtime code. It has not substantiated the complete reusable, continuously operating enterprise System of Intent. Local consolidation aligns code, requirements and source data; it does not itself close hosted-release or product gaps.

The register contains **33 gaps: 8 P0, 21 P1 and 4 P2**. 4 have partial remediation and 0 are closed. These are risk priorities, not a completion percentage.

## Baseline and validation limits

The baseline assessment compared main `9fa5316` and candidate `c03e958`, inspected requirements, ran portable tests, reproduced targeted defects offline and sampled authenticated preview behavior. The live executive JavaScript matched the candidate; the backend image was not attested. The selected preview run awaited review and lacked enriched strategy/calendar/plan data. Logout returned 404 and the session could still read a protected run. No approval, upload, deployment, board-close mutation or destructive live security test was performed.

Baseline testing recorded 1,569 passes, 77 skips and one harness-path failure, followed by 10 passing configuration tests after correcting the harness path. [Current validation](validation.md) records consolidation results. Portable tests do not establish service integration, factual assistant acceptance or operational certification. Immutable source links preserve the reviewed evidence after local cleanup.

The [canonical specification](../requirements.md) resolves earlier requirement conflicts. This report is generated from [gap-register.json](gap-register.json); update the register and run `python scripts/render_gap_analysis.py` instead of editing this file.

## Prioritized register

| ID | Priority | Area | Gap | Closure |
|---|---|---|---|---|
| [G01](#g01) | P0 | Release and data | Live preview lacks the strategy dataset | open |
| [G02](#g02) | P0 | Release and data | Local release aligned; remote and hosted release identity remain open | partial |
| [G03](#g03) | P0 | Quantitative correctness | Zero values disappear from Plan Health | open |
| [G04](#g04) | P1 | Quantitative correctness | Drift and direction depend on dataset labels and IDs | open |
| [G05](#g05) | P0 | AI assurance | Grounded synthesis accepts fabricated additional numbers | open |
| [G06](#g06) | P0 | Access control | Authority enforcement is weaker than its published contract | open |
| [G07](#g07) | P0 | Access control | Shared multi-tenant run isolation is incomplete | open |
| [G08](#g08) | P0 | Board governance | Frozen board memory is not demonstrated as an immutable snapshot | open |
| [G09](#g09) | P1 | Access control | Live sign-out does not invalidate the session | open |
| [G10](#g10) | P0 | Validation | Question-bank reporting does not measure the required answer quality | open |
| [G11](#g11) | P1 | Validation | Portable datasets fixed; external-service acceptance remains open | partial |
| [G12](#g12) | P1 | Product foundation | A reusable strategy-to-KPI compiler is missing | open |
| [G13](#g13) | P1 | Product foundation | Intent Vault and governed amendments are missing | open |
| [G14](#g14) | P1 | Data integration | Production connectors and incremental ingestion are missing | open |
| [G15](#g15) | P1 | Drift and freshness | Continuous drift and historical Plan Health remain partial | open |
| [G16](#g16) | P1 | Financial domain | Cross-system entity resolution and consolidation need broader proof | open |
| [G17](#g17) | P1 | Financial domain | Recovery meter is limited to the first eight decision rows | open |
| [G18](#g18) | P1 | Financial domain | Working-capital drift uses settlement-day proxies | open |
| [G19](#g19) | P1 | Drift and decisions | Cost-of-drift conversion is a limit, not a completed feature | open |
| [G20](#g20) | P1 | Drift and decisions | Decision Velocity is not implemented | open |
| [G21](#g21) | P1 | Drift and decisions | Recording a decision is not closed-loop execution | open |
| [G22](#g22) | P1 | Agents and memory | Agent experiences are not one continuous state model | open |
| [G23](#g23) | P1 | Retrieval | Configured vector search is still a lexical/hash fallback | open |
| [G24](#g24) | P2 | Thinking Mode | The two R4 structured thinking frameworks are missing | open |
| [G25](#g25) | P1 | Personas | CFO and BU experiences are not a complete four-persona product | open |
| [G26](#g26) | P1 | Sovereignty | Deployment policy exists; tier proof and visible residency do not | open |
| [G27](#g27) | P1 | Localization and access | Arabic/RTL support and complete accessibility acceptance are absent | open |
| [G28](#g28) | P2 | Brand and UX | Rename token and remaining R4 display improvements are incomplete | open |
| [G29](#g29) | P1 | Operations | Application rollback is not a tested data recovery plan | open |
| [G30](#g30) | P1 | Operations | SLOs, capacity, inference audit and cost controls are not demonstrated | open |
| [G31](#g31) | P2 | Maintainability | Packaging cleaned; dependency locking and module separation remain open | partial |
| [G32](#g32) | P1 | Validation and data safety | Test isolation and stale local pointers remediated; broader integration controls remain open | partial |
| [G33](#g33) | P2 | Commercial readiness | Commercial scope and first-client acceptance remain unsettled | open |

<a id="g01"></a>
## G01 · P0 · Live preview lacks the strategy dataset

**Current position:** The authenticated latest-run response is awaiting_review / pending / paused_before_writer. It contains eight locked finance findings, but zero board commitments, no assistant profiles, unavailable calendar, and missing actual-versus-plan comparators and board cash floor. All five executive-policy capability flags are false. The run directory carries an August 8 timestamp; that timestamp is not a current service-health measurement.

**Impact:** The core CEO promise cannot be demonstrated from the current selected run. A working UI and populated finance figures conceal how much strategic context is absent.

**Required work:** Select and validate the intended enriched source pack, rebuild its derived data, complete authorized reviewer sign-off, and promote it through a release manifest. Preserve the existing review gate.

**Acceptance:** The selected release has the intended 10 commitments with honest live/estimated coverage, source-backed plan comparators, calendar and executive policy inputs; the run completes and all visible values trace to that exact pack.

**Suggested owner:** Release owner + data owner + designated reviewer

**Evidence classification:** Live-confirmed

**Evidence:** [Live run snapshot](<evidence/live-run.json>); [Live question probes](<evidence/live-question-probes.json>).

<a id="g02"></a>
## G02 · P0 · Local release aligned; remote and hosted release identity remain open

**Current position:** Local main was fast-forwarded from 9fa5316 to c03e958 (121 commits), then consolidated. GitHub main and the full hosted release/data manifest remain unaligned or unverified; the live frontend alone matched c03e958 during the assessment.

**Impact:** An ordinary main-based deployment can replace newer product behavior with an older build. Review reports, release code, and data are not one reproducible baseline.

**Required work:** Choose one release branch, reconcile the candidate through review, and record commit SHA, immutable image digest, schema version, source-pack hash, run ID and provider configuration together. Expose this manifest to operators.

**Acceptance:** A clean checkout of the designated release recreates the approved application and selected data contract; rollback explicitly covers code, schema compatibility and selected run.

**Suggested owner:** Engineering lead + release owner

**Evidence classification:** Confirmed in local and remote refs

**Evidence:** [Live asset comparison](<evidence/live-access-checks.json>); [Branch deployment workflow](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/.github/workflows/strategyos-branch-deploy.yml#L1>).

<a id="g03"></a>
## G03 · P0 · Zero values disappear from Plan Health

**Current position:** _measurement_status uses value-or-empty, treating numeric zero as missing; _score independently rejects actual == 0. A valid growth KPI at 0 against a 100 target produces score=null, live_count=0 and missing_count=1.

**Impact:** A completely failed commitment can disappear from the measured average. A legitimate zero incident rate also needs explicit lower-is-better semantics.

**Required work:** Distinguish None/unparseable from zero, define zero-denominator and zero-actual rules by metric direction, and preserve valid measurements in coverage.

**Acceptance:** A higher-is-better 0/100 contributes 0%; a lower-is-better zero uses the approved bounded rule; missing input remains visibly missing.

**Suggested owner:** Quantitative engine owner

**Evidence classification:** Reproduced offline

**Evidence:** [Plan Health input and score logic](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L190>); [Reproduction](<evidence/audit-probe-results.json>).

<a id="g04"></a>
## G04 · P1 · Drift and direction depend on dataset labels and IDs

**Current position:** Direction is lower-is-better only for KPI-04 and KPI-10; weights are fixed at 1.0; estimates are partly selected by KPI ID; periods are fixed June-2026 columns. behind_count is copied from the source Status vs path string. A probe with actual 80 versus checkpoint 100 and a stale ON label yields score 80 but zero behind and one holding. A new client cost KPI at 120/100 is scored 120%, despite a lower-is-better direction field.

**Impact:** New client metrics and updated measurements can reverse the intended meaning or leave exceptions hidden.

**Required work:** Introduce versioned metric metadata for direction, unit, weight, cadence, measurement quality and comparator; derive status from arithmetic with explicit tolerance bands.

**Acceptance:** Rename/reorder KPI IDs and change periods without changing results; mutate actuals without editing labels and verify the correct exception; validate weights against the ratified plan.

**Suggested owner:** Quantitative engine + product owner

**Evidence classification:** Reproduced offline / code-confirmed

**Evidence:** [Composite implementation](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L240>); [Reproduction](<evidence/audit-probe-results.json>).

<a id="g05"></a>
## G05 · P0 · Grounded synthesis accepts fabricated additional numbers

**Current position:** The development guard checks that the first two original numbers still occur in WHAT and one expected reference occurs in WHY. It accepts extra invented SAR 999M claims in WHAT, WHY and rich_briefing. Thread summaries and key_figures accept provider replacements without an equivalent numeric check. Both probes were labelled llm-batch-grounded.

**Impact:** An evidence badge can accompany an unsupported quantitative claim, violating the defining deterministic-number contract.

**Required work:** Represent each quantitative claim as a typed reference to an approved fact or calculation. Reject unbound numbers in every model-generated field, including summaries, charts and captions; validate causal claims separately.

**Acceptance:** Adversarial provider responses retaining valid numbers while adding, changing or attaching false units, amounts or causes are rejected. All displayed numerical cells resolve to an approved calculation.

**Suggested owner:** AI platform + quantitative QA

**Evidence classification:** Reproduced offline

**Evidence:** [Synthesis acceptance](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/executive_synthesis.py#L204>); [Probe results](<evidence/audit-probe-results.json>).

<a id="g06"></a>
## G06 · P0 · Authority enforcement is weaker than its published contract

**Current position:** The assistant checks the subject selected from the request persona, rather than intersecting it with an authenticated persona entitlement. A keyword classifier selects a single domain before broad context retrieval. The default CFO policy denies Show employee compensation as HR, but allows Show salaries and bonuses as finance. Board maps to assistant:hermes rather than a separate Minerva subject. The separate /qa path does not call _assistant_authority_refusal.

**Impact:** A caller-controlled persona, alternate endpoint, or differently worded request can change the effective permission decision. The observed classifier mismatch alone does not prove that protected records were returned.

**Required work:** Bind personas to authenticated entitlements, enforce per-resource and per-source permissions at retrieval, intersect user/assistant/tool authority, and apply the same policy to every query endpoint. Give Minerva a separate policy identity.

**Acceptance:** Negative tests across users, personas, aliases, mixed-domain questions and /qa versus /assistant/chat demonstrate identical denials before restricted data is loaded.

**Suggested owner:** Security + backend lead

**Evidence classification:** Local reproduction and code review; no live data-disclosure test

**Evidence:** [Authority classifier](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/authority_matrix.py#L218>); [Assistant boundary](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L16612>); [Published contract](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/docs/authority-matrix-mvp.md#L17>); [Probe results](<evidence/audit-probe-results.json>).

<a id="g07"></a>
## G07 · P0 · Shared multi-tenant run isolation is incomplete

**Current position:** Agent-runtime records and canonical finance tables have tenant scoping, but core strategyos_runs has no tenant_id column; get_run_detail selects by run ID only. Latest-run/output selection also uses deployment-global state. A generic bu role is not equivalent to a specific BU entitlement.

**Impact:** The code does not substantiate the shared multi-tenant tier or per-BU confidentiality claim end to end. Separate deployment isolation can reduce this exposure for an initial pilot.

**Required work:** Add tenant and business-scope ownership to runs, jobs, artifacts, citations, caches and retrieval; enforce the authenticated scope in every lookup, not just in the agent layer.

**Acceptance:** Two tenants and two BUs sharing infrastructure cannot list, resolve, retrieve, search, export or ask about each other’s records, including guessed IDs and latest aliases.

**Suggested owner:** Security + data architecture

**Evidence classification:** Code-confirmed architectural gap

**Evidence:** [Run schema](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/deploy/postgres/schema.sql#L20>); [Run lookup](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/state_store.py#L372>); [Pointer selection](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/run_registry.py#L84>).

<a id="g08"></a>
## G08 · P0 · Frozen board memory is not demonstrated as an immutable snapshot

**Current position:** _board_portal_payload constructs closed/frozen metadata from the supplied current summary and publication status. Its frozen_snapshot object carries status and explanatory text, not a persisted meeting snapshot identifier and immutable content binding. Related payloads still refer to the latest run. The review document marks this invariant protected, but that is not an implementation proof.

**Impact:** A closed meeting may describe a frozen record while later source/run changes alter what is displayed or what the assistant can use.

**Required work:** Persist a meeting snapshot containing the approved data, citations, report versions and content hashes. Resolve every closed-board read and question exclusively through that snapshot.

**Acceptance:** Close a meeting, change/reprocess current company data and restart services; the meeting’s figures, files and answers remain identical and inaccessible data stays unavailable.

**Suggested owner:** Board product owner + backend lead

**Evidence classification:** Code-confirmed gap; live lifecycle not mutated

**Evidence:** [Board payload construction](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L3883>); [Frozen object](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L4017>).

<a id="g09"></a>
## G09 · P1 · Live sign-out does not invalidate the session

**Current position:** The frontend calls POST /auth/logout. On the authenticated preview this returned HTTP 404. A subsequent GET /runs/latest with the same audit session still returned HTTP 200. The inspected source contains a logout handler, so this points to deployment/routing or backend-version mismatch.

**Impact:** Users can believe they signed out while the protected session remains usable.

**Required work:** Align deployed identity routing and handler version, revoke the server token and expire the cookie, and make the UI handle a failed logout explicitly.

**Acceptance:** After sign-out the same cookie cannot access a protected route; the response and browser navigation agree, including proxy and branch deployments.

**Suggested owner:** Identity + deployment owner

**Evidence classification:** Live-reproduced

**Evidence:** [Live logout check](<evidence/live-logout-check.json>); [Frontend logout](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/static/executive.js#L3812>); [Identity logout handler](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/idp.py#L364>).

<a id="g10"></a>
## G10 · P0 · Question-bank reporting does not measure the required answer quality

**Current position:** run_ceo_question_corpus scores non-empty text, visible determinism tier and a self-reported derivability flag. It does not compare numerical truth, resolve citations or score question relevance. A fabricated uncited SAR 999 trillion response is counted as answered and tiered with zero violations. Historical 50/500 reports exist, but do not establish current-build acceptance.

**Impact:** A high answered count can be mistaken for the specified 45/50 correct, resolving-citation and zero-fabrication gate.

**Required work:** Add held-out reference answers, calculation tolerances, actual citation resolution, relevance grading, theme-stratified sampling and per-question adjudication. Bind reports to build, source pack and model versions.

**Acceptance:** The latest approved release answers at least 45 of 50 questions sampled across all 18 themes correctly with resolving citations and no fabricated numbers; publish the failed and refused questions separately.

**Suggested owner:** QA lead + domain reviewer

**Evidence classification:** Reproduced offline

**Evidence:** [Corpus scorer](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/qa_regression_corpus.py#L57>); [Probe results](<evidence/audit-probe-results.json>).

<a id="g11"></a>
## G11 · P1 · Portable datasets fixed; external-service acceptance remains open

**Current position:** Enrichment inputs and the exact POC-2 pack are now repository-owned and portable; the four enrichment tests no longer silently return when data is missing. External-service tests still require dedicated integration environments and cannot be claimed from a portable run.

**Impact:** A green suite is not evidence that persistence, concurrent approval, current enriched data, browser interactions or frozen-board behavior works.

**Required work:** Vendor portable sanitized enrichment fixtures, use explicit skips for genuinely optional checks, and add mandatory isolated integration and browser acceptance jobs for the release.

**Acceptance:** Clean CI executes the enrichment assertions, service-dependent security/transaction tests, and required CEO/board journeys; unexpected skips fail the release gate.

**Suggested owner:** QA + developer experience

**Evidence classification:** Code-confirmed

**Evidence:** [Nonportable enrichment tests](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/tests/test_source_strategy_enrichment.py#L8>); [CI workflow](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/.github/workflows/strategyos-ci.yml#L43>).

<a id="g12"></a>
## G12 · P1 · A reusable strategy-to-KPI compiler is missing

**Current position:** The current executive enrichment reads named workbooks and fixed columns; it does not compile an arbitrary company’s approved strategy into the Growth/Margin/Capital/Resilience/Sustainability tree. The older finance-only plan-health boundary explicitly disclaims a full enterprise strategy compiler.

**Impact:** Onboarding another client remains a custom data-and-code exercise instead of the product’s defining self-composition capability.

**Required work:** Build a versioned intent schema and human-reviewed compiler from strategy text to objectives, targets, measures, leading indicators, ownership, cadence and source bindings.

**Acceptance:** Onboard a second anonymized company without code changes; prove target extraction, owner review, formula binding, recompile diffs and unsupported-input handling.

**Suggested owner:** Product architect + knowledge engineer

**Evidence classification:** Not found in inspected candidate

**Evidence:** [Workbook discovery](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L21>); [Enrichment entry point](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L545>).

<a id="g13"></a>
## G13 · P1 · Intent Vault and governed amendments are missing

**Current position:** No top-level Intent surface, ratified plan version model, amendment log or KPI-to-amendment navigation was found. Authority Matrix is a useful prerequisite, but is not a plan-of-record store.

**Impact:** Users can inspect performance but cannot inspect and govern the intent against which it is measured.

**Required work:** Implement R4 F1 read-only first: versioned plan, commitments, initiatives, owners, ratification and amendment provenance. Reuse one schema for any future workshop-capture flow.

**Acceptance:** Intent is reachable from navigation; every commitment exposes approval and last amendment; at least three real amendments resolve; every diagnostics KPI links to its plan version.

**Suggested owner:** Product + intent/data lead

**Evidence classification:** R4 requirement; not found in inspected candidate

**Evidence:** [R4 feature order](<../requirements.md>); [Executive shell](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/static/executive.html#L1>).

<a id="g14"></a>
## G14 · P1 · Production connectors and incremental ingestion are missing

**Current position:** The ingestion catalog contains workspace folder, browser upload, validated snapshot and a generic placeholder; all declare supports_incremental=False. Oracle canonical ingestion is substantive, but an ingestion API is not a maintained SAP/Oracle/MT940/M365 connector with credentials, cursors and failure recovery.

**Impact:** The continuous intelligence product currently depends on manually prepared extracts and reprocessing.

**Required work:** Choose the first client’s actual ERP/AP/AR, treasury and calendar integrations; implement source contracts, incremental cursors, deduplication, retry/dead-letter handling and reconciliation.

**Acceptance:** Repeated and out-of-order source deliveries are idempotent; transactions, nightly bank balances and calendar updates arrive at their declared cadence with visible freshness and failure state.

**Suggested owner:** Integration lead + client data owner

**Evidence classification:** Code-confirmed

**Evidence:** [Connector catalog](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/platform_foundation.py#L270>); [Oracle ingest authorization](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L9888>).

<a id="g15"></a>
## G15 · P1 · Continuous drift and historical Plan Health remain partial

**Current position:** Enrichment reads current workbook labels, fixed June checkpoints and a fixed June 1–7 virtual clock. Plan Health lacks the R4 13-week composite trajectory. Live assistant monitoring records have July 11 last-wake timestamps and cycle_count=1; this is stored run evidence, not proof that a scheduler is currently healthy.

**Impact:** A one-time dataset snapshot can look like ongoing monitoring; the cadence ladder and automatic escalation are not established.

**Required work:** Separate demo clock from deployment time, persist metric observations and thresholds, schedule refresh/detection, and derive monitoring status from recent successful work and heartbeat evidence.

**Acceptance:** New measurements automatically change drift state, historical trajectory and alerts; stale connectors and stopped workers visibly degrade readiness; slow KPIs do not fake daily movement.

**Suggested owner:** Data platform + runtime owner

**Evidence classification:** Code-confirmed / live evidence

**Evidence:** [Fixed clock and enrichment](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L695>); [Live runtime payload](<evidence/live-run.json>).

<a id="g16"></a>
## G16 · P1 · Cross-system entity resolution and consolidation need broader proof

**Current position:** Finance and graph duplicate-vendor checks and Oracle canonical normalization exist. The inspected evidence does not establish a reusable stewarded identity crosswalk across ERP/procurement/bank/DMS, intercompany eliminations or daily FX revaluation across the whole group.

**Impact:** The finance POC’s successful planted patterns do not establish correct consolidated results for a new client’s messy multi-system records.

**Required work:** Add confidence-scored identity mappings, merge/split review, legal-entity-aware matching, intercompany reconciliation and effective-dated FX policy.

**Acceptance:** A multi-system corpus covers aliases, shared bank accounts, disputed matches, intercompany sweeps and FX-rate dates; every aggregate reconciles without double counting.

**Suggested owner:** Finance data engineering + client finance reviewer

**Evidence classification:** Partial implementation

**Evidence:** [Finance resolution detector](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/skills/finance_controls.py#L515>); [Oracle normalization and controls](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/oracle_finance.py#L1>).

<a id="g17"></a>
## G17 · P1 · Recovery meter is limited to the first eight decision rows

**Current position:** current_audit_rows = remediation_rows[:8] controls the identified, recovered and fallback locked totals and assistant recovery memory. This encodes the original eight-case sample rather than an explicit run/case linkage.

**Impact:** Later valid recoveries can be omitted, and reordering a workbook can change reported totals.

**Required work:** Join recovery events to stable case and run identifiers; distinguish identified, verified, approved, collected and written-off amounts, with no row-position filter.

**Acceptance:** Adding a ninth eligible recovery changes the meter correctly; shuffling rows does not; partial receipts and reversals reconcile to payment evidence.

**Suggested owner:** Finance product + data engineering

**Evidence classification:** Code-confirmed

**Evidence:** [Recovery aggregation](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L653>).

<a id="g18"></a>
## G18 · P1 · Working-capital drift uses settlement-day proxies

**Current position:** compute_working_capital_drifts labels DSO/DPO but computes average settled invoice-to-collection/payment days in weekly invoice cohorts. It excludes unsettled invoices and averages the same trailing window being tested. The KPI specification defines balance/revenue or balance/COGS × period-days. Separate Oracle ratio calculations may exist; they do not remove this reporting mismatch.

**Impact:** A proxy can disagree materially with financial DSO/DPO and understate deterioration in unpaid invoices.

**Required work:** Name settlement-speed metrics explicitly; implement the balance-based ratios with approved periods, open-item treatment and a prior-window baseline. Keep Task-1 overlap exclusions.

**Acceptance:** Compare both metrics with a finance-reviewed example containing large unpaid balances; disclose formulas, weighting and windows and prove cash-impact reconciliation.

**Suggested owner:** Finance engine owner

**Evidence classification:** Code-confirmed requirements mismatch

**Evidence:** [Current drift calculation](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/skills/finance_controls.py#L1039>); [KPI source extract](<evidence/verification-summary.json>).

<a id="g19"></a>
## G19 · P1 · Cost-of-drift conversion is a limit, not a completed feature

**Current position:** _cost_of_drift always returns financial_effect_sar_per_week=None. Optional value-conversion workbooks are inventoried for readiness but are not applied by that calculation. Current live policy inputs are absent. Some event/initiative weekly values can be displayed if supplied.

**Impact:** The product cannot consistently rank strategic drift by monetary consequence or time cost.

**Required work:** Approve per-KPI conversion logic, source inputs and uncertainty bounds; compute where defensible and retain quantified nonfinancial gaps where not. Avoid requiring fabricated monetization.

**Acceptance:** Financial drift reconciles to the variance bridge; nonfinancial conversions cite approved factors; missing factors produce a precise missing-input request, never an invented number.

**Suggested owner:** Domain owner + quantitative engine

**Evidence classification:** Code-confirmed / missing live inputs

**Evidence:** [Drift conversion](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L206>); [Executive policy inputs](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L60>).

<a id="g20"></a>
## G20 · P1 · Decision Velocity is not implemented

**Current position:** Decision recording exists, but no linked surfaced_at → decided_at → first_action_at measurement and no median/trend/queue-aging Decision Velocity card was found.

**Impact:** The headline business problem—decision latency—has no measured outcome in the product.

**Required work:** Instrument immutable lifecycle events and compute the two medians and queue ages per scope; exclude pending actions from completed-duration medians and show their age separately.

**Acceptance:** A recorded decision and subsequent verified first action update the correct metric; overdue open items remain visible; source events drill through from the card.

**Suggested owner:** Product analytics + workflow owner

**Evidence classification:** R4 requirement; not found in inspected candidate

**Evidence:** [Decision record endpoint](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L9614>); [R4 work order](<../requirements.md>).

<a id="g21"></a>
## G21 · P1 · Recording a decision is not closed-loop execution

**Current position:** The newer executive decision endpoint durably records a recommendation/owner/date with idempotency, but returns delivery_status=not_delivered and underlying_issue_status=open. Demo seed choices also have session-state behavior. This is honest and useful, but not ERP execution or confirmed stakeholder delivery.

**Impact:** Users still need an external process to turn approval into assigned work, acknowledged ownership and verified completion.

**Required work:** Build an explicit approved dispatch queue, connector-specific delivery, acknowledgement, escalation and outcome reconciliation. Keep proposal/approval/delivery/completion distinct.

**Acceptance:** Retries cannot duplicate delivery; failures remain pending with a clear owner; a task closes only when authoritative completion evidence arrives.

**Suggested owner:** Workflow + integration lead

**Evidence classification:** Intentional current boundary / product gap

**Evidence:** [Decision outcome contract](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L9614>); [Agent capabilities](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/agent_runtime/registry.py#L96>).

<a id="g22"></a>
## G22 · P1 · Agent experiences are not one continuous state model

**Current position:** There are deterministic analysis stages, durable specialist tasks, digital-twin stores and source-seeded assistant threads. The specialist registry has four actual workers. Live chat reports client_session/sessionStorage with server_memory=false; live twin metrics show no collaboration events and 20 routing gaps. Seeded A2A content is not proof of autonomous live cooperation.

**Impact:** Status can disagree across assistants, tasks and decisions; conversational continuity depends on a browser session and selected run.

**Required work:** Define which runtime owns tasks, messages, decisions and memory; project all UI states from its events. Distinguish seeded/demo conversations from live tasks and implement cross-device authorized memory.

**Acceptance:** One real request traces through delegation, evidence, approval and result; refresh/restart/another authorized device preserves the same task and conversation state.

**Suggested owner:** Agent platform + product architect

**Evidence classification:** Partial implementation / live confirmation

**Evidence:** [Specialist registry](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/agent_runtime/registry.py#L1>); [Seed threads](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L333>); [Live chat and twin state](<evidence/live-run.json>).

<a id="g23"></a>
## G23 · P1 · Configured vector search is still a lexical/hash fallback

**Current position:** vector_store declares hash_fallback, lexical_keyword and native_hybrid_supported=False. The current run’s Qdrant sample also reports hash_fallback. This is real persistent retrieval, but not demonstrated semantic similarity search.

**Impact:** Paraphrases, cross-language questions and semantic entity similarity may miss evidence even when the documents exist.

**Required work:** Add a deployment-approved embedding model, hybrid ranking, metadata/ACL filters and a versioned reindex process; measure recall independently of answer generation.

**Acceptance:** A held-out corpus with paraphrases, entity aliases and Arabic/English queries meets agreed recall@k and citation precision targets without cross-scope leakage.

**Suggested owner:** Retrieval owner

**Evidence classification:** Code and stored live-run evidence

**Evidence:** [Vector contract](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/vector_store.py#L17>); [Live Qdrant sample](<evidence/live-run.json>).

<a id="g24"></a>
## G24 · P2 · The two R4 structured thinking frameworks are missing

**Current position:** Scenario parsing and deterministic calculations exist, as do calendar handoffs. No config-driven Decision One-Pager and Drift Diagnosis templates with editable structured blocks and board-pack export were found.

**Impact:** Thinking Mode is less reusable for executive work than the requested decision-document workflow.

**Required work:** Implement the two templates as governed configuration, seeded from decisions and drifting KPIs, with cited calculations and explicit assumptions.

**Acceptance:** Both launch from their natural anchors, retain context through chat edits and export a reviewable board-pack candidate; neither can execute an operational action.

**Suggested owner:** Product design + scenario owner

**Evidence classification:** Not found in inspected candidate

**Evidence:** [Scenario engine](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/scenario_parser.py#L1>); [R4 frameworks](<../requirements.md>).

<a id="g25"></a>
## G25 · P1 · CFO and BU experiences are not a complete four-persona product

**Current position:** The later executive specification permits coming-soon locks for undifferentiated personas, and differentiated roles/runtime components exist. That satisfies honest preview gating, but not the original Group CFO, BU CEO/GM and BU CFO experience requirements.

**Impact:** The pilot can demonstrate the CEO lane, but should not promise equivalent decision workflows at all four altitudes.

**Required work:** Sequence one real CFO cockpit and one BU operating cockpit, with scope-aware KPIs, owned decisions and upward commentary; retain locks until each is accepted.

**Acceptance:** Persona changes alter data scope, responsibilities and workflow, not just labels; direct URLs cannot substitute another persona’s header or access rights.

**Suggested owner:** Product owner + identity/data teams

**Evidence classification:** Deliberately phased / partial

**Evidence:** [Persona/mode definitions](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L4115>); [Persona source requirements](<evidence/verification-summary.json>).

<a id="g26"></a>
## G26 · P1 · Deployment policy exists; tier proof and visible residency do not

**Current position:** The code includes local-first run policy, external-mode approvals and proxy-OIDC deployment options. The required config-driven residency/model/egress marker was not found. A live run’s historical model-provider flag is not proof of current chat egress: the sampled assistant did use its LLM path.

**Impact:** The four deployment tiers and sovereign/no-egress claim lack a release-specific acceptance record.

**Required work:** Publish truthful per-deployment model, region, storage and egress configuration; verify air-gap operation and approved provider paths using the same release corpus.

**Acceptance:** The screen matches actual deployment configuration; blocked egress cannot trigger an unapproved fallback; each supported local model passes the answer-quality gate.

**Suggested owner:** Deployment architect + security

**Evidence classification:** Partial / not independently verified

**Evidence:** [Run policy](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/config.py#L138>); [R4 residency marker](<../requirements.md>); [Live sample](<evidence/live-question-probes.json>).

<a id="g27"></a>
## G27 · P1 · Arabic/RTL support and complete accessibility acceptance are absent

**Current position:** The technical specification requires Arabic/English and full RTL from day one. The inspected application ships English templates; the Docker image installs English OCR only. Some accessibility features exist, including modal semantics and reduced-motion CSS, but no complete keyboard, screen-reader or RTL acceptance evidence was found.

**Impact:** The current build does not substantiate its stated bilingual launch scope.

**Required work:** Introduce translation catalogs, direction-aware layout and number/date localization; add Arabic OCR where needed and test actual Arabic financial documents. Audit keyboard/focus, contrast and responsive layouts.

**Acceptance:** Core intake, diagnostics, drill, chat, decision and board journeys work in Arabic and English with keyboard and screen reader; exported figures preserve units and meaning.

**Suggested owner:** Frontend + localization QA

**Evidence classification:** Not found / not fully tested

**Evidence:** [Executive shell](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/static/executive.html#L1>); [OCR deployment](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/deploy/Dockerfile#L1>); [NFR requirements](<evidence/verification-summary.json>).

<a id="g28"></a>
## G28 · P2 · Rename token and remaining R4 display improvements are incomplete

**Current position:** Product-name strings remain distributed through templates and output copy; no single PRODUCT_NAME configuration was found. R4’s Plan Health trajectory and a reusable clickable FX reasoning chain are not established. Many later visual improvements are present, so the old blanket word-heavy finding should not be copied unchanged.

**Impact:** Rebranding and new executive elements can reintroduce inconsistent names, internal vocabulary or untraceable displays.

**Required work:** Centralize product identity and design tokens, finish the trajectory and one reusable reasoning-chain component, and verify copy at rendered-payload boundaries rather than banning internal API names in source code.

**Acceptance:** One configuration change renames the product; the FX fact→objective→gap→confidence chain resolves in four taps; selected light/dark screenshots and collapsed-text rules are reviewed.

**Suggested owner:** Design system owner

**Evidence classification:** Code review / requirement gap

**Evidence:** [Executive UI](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/static/executive.js#L1>); [R4 protect/iterate list](<../requirements.md>).

<a id="g29"></a>
## G29 · P1 · Application rollback is not a tested data recovery plan

**Current position:** Deployment and rollback scripts exist and use image references and copied application directories. They do not establish coordinated database, object-store and workspace backup/restore, retention/deletion, or a tested RPO/RTO. Production deployment notes still list these as hardening work.

**Impact:** A bad migration, deleted evidence file or host loss can break provenance and recovery even if the container image rolls back.

**Required work:** Define the authoritative recovery set, encrypted scheduled backups, retention, restore procedures and forward/backward schema compatibility; treat Neo4j/Qdrant as rebuildable projections where appropriate.

**Acceptance:** Restore into a clean environment and reconcile approved runs, evidence hashes, decisions and board snapshots within agreed recovery objectives.

**Suggested owner:** SRE + data platform

**Evidence classification:** Code-confirmed / operational evidence absent

**Evidence:** [Rollback implementation](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/deploy/scripts/rollback_stack.sh#L1>); [Production hardening list](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/docs/production-deployment-plan.md#L73>).

<a id="g30"></a>
## G30 · P1 · SLOs, capacity, inference audit and cost controls are not demonstrated

**Current position:** Health/readiness checks, event trails, provider retries and concurrency tests exist. The review did not find a release acceptance report for the specified 20–50k-invoice envelope, end-to-end latency under load, source-freshness alerts, all-inference audit fields, per-tenant quotas or operating cost. Provider calls use a four-thread executor; bounded request timeouts alone do not prove bounded queued workload.

**Impact:** Production responsiveness, backlog behavior and inference accountability are uncertain.

**Required work:** Instrument queue depth, p50/p95/p99 latency, freshness, OCR failures, reviewer age, provider token/cost usage and per-tenant quotas; test overload, restart and provider outage.

**Acceptance:** Publish agreed SLOs and load results at target volume; alerts fire on seeded failures; inference records identify tenant/user, model/version, time, evidence and protected prompt/response references under a retention policy.

**Suggested owner:** SRE + AI platform + QA

**Evidence classification:** Partial controls / validation gap

**Evidence:** [Provider execution pool](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L138>); [Provider retry implementation](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/llm_qa.py#L1121>); [Concurrency proof tests](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/tests/test_agent_runtime_concurrency_postgres_e2e.py#L1>).

<a id="g31"></a>
## G31 · P2 · Packaging cleaned; dependency locking and module separation remain open

**Current position:** Static font and twin HTML assets are now included in package data; obsolete plans, snapshots and duplicate environments are removed from the active workspace. Dependency locking and separation of oversized API/frontend modules remain open.

**Impact:** Clean installs may differ, wheel distributions may omit fonts, and cross-cutting changes are difficult to review safely.

**Required work:** Produce a reproducible dependency/image manifest and package asset verification; split API modules by domain with a single shared assistant/security contract and clear ownership.

**Acceptance:** A wheel-based clean install includes all referenced assets; builds are reproducible; representative endpoint/UX contracts remain stable as modules are separated.

**Suggested owner:** Engineering lead + developer experience

**Evidence classification:** Code-confirmed

**Evidence:** [Package metadata](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/pyproject.toml#L1>); [Image definition](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/deploy/Dockerfile#L1>); [API module](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L1>).

<a id="g32"></a>
## G32 · P1 · Test isolation and stale local pointers remediated; broader integration controls remain open

**Current position:** The canonical test runner creates and removes isolated application and twin-state workspaces, strips inherited service/provider credentials, and selects explicit regression fixtures. Stale pre-existing latest/current pointers into pytest temporary runs were removed. General service/integration isolation still requires disciplined environment configuration.

**Impact:** Local validation can leave the application pointed at transient test data, and a passing report from a different environment cannot substitute for a clean current run.

**Required work:** Isolate all test output roots and prohibit promotion of temporary test runs to normal pointers. Make pointer writes atomic and validate referenced artifacts before promotion. Keep test harness setup explicit and separate harness failures from product defects.

**Acceptance:** Running the complete suite leaves production/local-business pointers unchanged; interrupted writes cannot corrupt pointers; a clean test harness creates its required directories before importing application configuration.

**Suggested owner:** QA + runtime/data owner

**Evidence classification:** Observed pre-existing state / test results

**Evidence:** [Pointer writer](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/run_registry.py#L47>); [Verification appendix](<evidence/verification-summary.json>).

<a id="g33"></a>
## G33 · P2 · Commercial scope and first-client acceptance remain unsettled

**Current position:** The original spec leaves marketplace self-deployment, native/marketplace split, final input formats, model tiers and supported volumes open. The implementation’s four specialist workers should not be presented as all proposed continuous domain agents or third-party marketplace products. No current signed first-client acceptance package was inspected.

**Impact:** Sales language can outrun tested capability and make custom integration work look included in the subscription.

**Required work:** Publish a supported/preview/roadmap matrix, choose the first-client use case and isolation posture, assign data/stewardship responsibilities, and define measurable commercial acceptance and ongoing support.

**Acceptance:** Proposal, demo, deployment and acceptance checklist use the same capability baseline; marketplace deployment and additional personas are sold only at their verified status.

**Suggested owner:** Product + commercial lead

**Evidence classification:** Requirements/process gap

**Evidence:** [Open scope decisions](<evidence/verification-summary.json>); [Actual specialist registry](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/agent_runtime/registry.py#L1>).
