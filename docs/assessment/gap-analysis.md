# StrategyOS gap analysis

Assessment date: 2026-09-05. Reviewed baseline: `c03e95816dedf6dedf05778cb725d42a84c29de2`.

The preview now runs the enriched approved synthetic dataset with durable review state, scoped local semantic retrieval, immutable board records and encrypted inference audit. The register below separates verified corrections from incomplete acceptance. It does not claim a complete enterprise product or a passed factual assistant gate.

The register contains **33 gaps: 8 P0, 21 P1 and 4 P2**. 22 have partial remediation and 6 are closed. These are risk priorities, not a completion percentage.

## Current scope

All P0/P1 application work and UI QA; actual external ERP/treasury/calendar connections deferred by user. No real-world dispatch is simulated as completed.

User requires preserving the existing UI. Removed new pages, navigation and language controls on 2026-09-05. Keep existing layouts, CSS, branding and controls; integrate functional corrections through existing surfaces.

[Current validation](validation.md) and the [preview release receipt](evidence/preview-release.json) identify tested behavior and the deployed code/data combination. Historical evidence below is retained for traceability, not as the current deployment status.

## Original assessment and validation limits

The baseline assessment compared main `9fa5316` and candidate `c03e958`, inspected requirements, ran portable tests, reproduced targeted defects offline and sampled authenticated preview behavior. The live executive JavaScript matched the candidate; the backend image was not attested. The selected preview run awaited review and lacked enriched strategy/calendar/plan data. Logout returned 404 and the session could still read a protected run. No approval, upload, deployment, board-close mutation or destructive live security test was performed.

Baseline testing recorded 1,569 passes, 77 skips and one harness-path failure, followed by 10 passing configuration tests after correcting the harness path. [Current validation](validation.md) records consolidation results. Portable tests do not establish service integration, factual assistant acceptance or operational certification. Immutable source links preserve the reviewed evidence after local cleanup.

The [canonical specification](../requirements.md) resolves earlier requirement conflicts. This report is generated from [gap-register.json](gap-register.json); update the register and run `python scripts/render_gap_analysis.py` instead of editing this file.

## Prioritized register

| ID | Priority | Area | Gap | Closure |
|---|---|---|---|---|
| [G01](#g01) | P0 | Release and data | Live preview lacks the strategy dataset | closed |
| [G02](#g02) | P0 | Release and data | Local release aligned; remote and hosted release identity remain open | partial |
| [G03](#g03) | P0 | Quantitative correctness | Zero values disappear from Plan Health | closed |
| [G04](#g04) | P1 | Quantitative correctness | Drift and direction depend on dataset labels and IDs | partial |
| [G05](#g05) | P0 | AI assurance | Grounded synthesis accepts fabricated additional numbers | partial |
| [G06](#g06) | P0 | Access control | Authority enforcement is weaker than its published contract | partial |
| [G07](#g07) | P0 | Access control | Shared multi-tenant run isolation is incomplete | partial |
| [G08](#g08) | P0 | Board governance | Frozen board memory is not demonstrated as an immutable snapshot | closed |
| [G09](#g09) | P1 | Access control | Live sign-out does not invalidate the session | closed |
| [G10](#g10) | P0 | Validation | Question-bank reporting does not measure the required answer quality | open |
| [G11](#g11) | P1 | Validation | Portable datasets fixed; external-service acceptance remains open | partial |
| [G12](#g12) | P1 | Product foundation | A reusable strategy-to-KPI compiler is missing | partial |
| [G13](#g13) | P1 | Product foundation | Intent Vault and governed amendments are missing | partial |
| [G14](#g14) | P1 | Data integration | Production connectors and incremental ingestion are missing | deferred |
| [G15](#g15) | P1 | Drift and freshness | Continuous drift and historical Plan Health remain partial | partial |
| [G16](#g16) | P1 | Financial domain | Cross-system entity resolution and consolidation need broader proof | partial |
| [G17](#g17) | P1 | Financial domain | Recovery meter is limited to the first eight decision rows | closed |
| [G18](#g18) | P1 | Financial domain | Working-capital drift uses settlement-day proxies | partial |
| [G19](#g19) | P1 | Drift and decisions | Cost-of-drift conversion is a limit, not a completed feature | partial |
| [G20](#g20) | P1 | Drift and decisions | Decision Velocity is not implemented | partial |
| [G21](#g21) | P1 | Drift and decisions | Recording a decision is not closed-loop execution | partial |
| [G22](#g22) | P1 | Agents and memory | Agent experiences are not one continuous state model | partial |
| [G23](#g23) | P1 | Retrieval | Configured vector search is still a lexical/hash fallback | partial |
| [G24](#g24) | P2 | Thinking Mode | The two R4 structured thinking frameworks are missing | open |
| [G25](#g25) | P1 | Personas | CFO and BU experiences are not a complete four-persona product | partial |
| [G26](#g26) | P1 | Sovereignty | Deployment policy exists; tier proof and visible residency do not | partial |
| [G27](#g27) | P1 | Localization and access | Arabic/RTL support and complete accessibility acceptance are absent | partial |
| [G28](#g28) | P2 | Brand and UX | Rename token and remaining R4 display improvements are incomplete | open |
| [G29](#g29) | P1 | Operations | Application rollback is not a tested data recovery plan | partial |
| [G30](#g30) | P1 | Operations | SLOs, capacity, inference audit and cost controls are not demonstrated | partial |
| [G31](#g31) | P2 | Maintainability | Packaging cleaned; dependency locking and module separation remain open | partial |
| [G32](#g32) | P1 | Validation and data safety | Test isolation and stale local pointers remediated; broader integration controls remain open | closed |
| [G33](#g33) | P2 | Commercial readiness | Commercial scope and first-client acceptance remain unsettled | open |

<a id="g01"></a>
## G01 · P0 · Live preview lacks the strategy dataset

**Current position:** Preview now selects the approved, completed enriched run with 169 hash-verified source files, 10 commitments (7 measured, 3 estimated), exact workbook EBITDA, plan comparators and synthetic executive context. The approval is authorized preview QA, not business ratification.

**Impact:** The core CEO promise cannot be demonstrated from the current selected run. A working UI and populated finance figures conceal how much strategic context is absent.

**Required work:** Select and validate the intended enriched source pack, rebuild its derived data, complete authorized reviewer sign-off, and promote it through a release manifest. Preserve the existing review gate.

**Acceptance:** The selected release has the intended 10 commitments with honest live/estimated coverage, source-backed plan comparators, calendar and executive policy inputs; the run completes and all visible values trace to that exact pack.

**Suggested owner:** Release owner + data owner + designated reviewer

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Live run snapshot](<evidence/live-run.json>); [Live question probes](<evidence/live-question-probes.json>).

<a id="g02"></a>
## G02 · P0 · Local release aligned; remote and hosted release identity remain open

**Current position:** Preview has an attested code/image/schema/source/run receipt. Canonical main and remote reconciliation remain in progress; production is intentionally unchanged.

**Impact:** An ordinary main-based deployment can replace newer product behavior with an older build. Review reports, release code, and data are not one reproducible baseline.

**Required work:** Choose one release branch, reconcile the candidate through review, and record commit SHA, immutable image digest, schema version, source-pack hash, run ID and provider configuration together. Expose this manifest to operators.

**Acceptance:** A clean checkout of the designated release recreates the approved application and selected data contract; rollback explicitly covers code, schema compatibility and selected run.

**Suggested owner:** Engineering lead + release owner

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Live asset comparison](<evidence/live-access-checks.json>); [Branch deployment workflow](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/.github/workflows/strategyos-branch-deploy.yml#L1>).

<a id="g03"></a>
## G03 · P0 · Zero values disappear from Plan Health

**Current position:** Metric contracts distinguish zero, missing and invalid values and apply explicit direction and zero-denominator rules. Regression coverage passes.

**Impact:** A completely failed commitment can disappear from the measured average. A legitimate zero incident rate also needs explicit lower-is-better semantics.

**Required work:** Distinguish None/unparseable from zero, define zero-denominator and zero-actual rules by metric direction, and preserve valid measurements in coverage.

**Acceptance:** A higher-is-better 0/100 contributes 0%; a lower-is-better zero uses the approved bounded rule; missing input remains visibly missing.

**Suggested owner:** Quantitative engine owner

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Plan Health input and score logic](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L190>); [Reproduction](<evidence/audit-probe-results.json>).

<a id="g04"></a>
## G04 · P1 · Drift and direction depend on dataset labels and IDs

**Current position:** Direction, weights, periods and arithmetic-derived status are configurable and tested with renamed metrics. Client plan weights still need owner ratification.

**Impact:** New client metrics and updated measurements can reverse the intended meaning or leave exceptions hidden.

**Required work:** Introduce versioned metric metadata for direction, unit, weight, cadence, measurement quality and comparator; derive status from arithmetic with explicit tolerance bands.

**Acceptance:** Rename/reorder KPI IDs and change periods without changing results; mutate actuals without editing labels and verify the correct exception; validate weights against the ratified plan.

**Suggested owner:** Quantitative engine + product owner

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Composite implementation](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L240>); [Reproduction](<evidence/audit-probe-results.json>).

<a id="g05"></a>
## G05 · P0 · Grounded synthesis accepts fabricated additional numbers

**Current position:** Provider quantities and exact source citations are checked against approved evidence with at most one repair. Workbook units, bounded rounding, ambiguous record locations and missing-source wording were corrected after live QA. Rejected answers remain unmatched. Full factual acceptance is not yet established.

**Impact:** An evidence badge can accompany an unsupported quantitative claim, violating the defining deterministic-number contract.

**Required work:** Represent each quantitative claim as a typed reference to an approved fact or calculation. Reject unbound numbers in every model-generated field, including summaries, charts and captions; validate causal claims separately.

**Acceptance:** Adversarial provider responses retaining valid numbers while adding, changing or attaching false units, amounts or causes are rejected. All displayed numerical cells resolve to an approved calculation.

**Suggested owner:** AI platform + quantitative QA

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Synthesis acceptance](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/executive_synthesis.py#L204>); [Probe results](<evidence/audit-probe-results.json>).

<a id="g06"></a>
## G06 · P0 · Authority enforcement is weaker than its published contract

**Current position:** Shared authorization guards run before scoped loaders and propagate through provider executor threads. Service-backed negative tests pass. Remaining complete multi-persona UI acceptance is tracked in G25.

**Impact:** A caller-controlled persona, alternate endpoint, or differently worded request can change the effective permission decision. The observed classifier mismatch alone does not prove that protected records were returned.

**Required work:** Bind personas to authenticated entitlements, enforce per-resource and per-source permissions at retrieval, intersect user/assistant/tool authority, and apply the same policy to every query endpoint. Give Minerva a separate policy identity.

**Acceptance:** Negative tests across users, personas, aliases, mixed-domain questions and /qa versus /assistant/chat demonstrate identical denials before restricted data is loaded.

**Suggested owner:** Security + backend lead

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Authority classifier](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/authority_matrix.py#L218>); [Assistant boundary](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L16612>); [Published contract](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/docs/authority-matrix-mvp.md#L17>); [Probe results](<evidence/audit-probe-results.json>).

<a id="g07"></a>
## G07 · P0 · Shared multi-tenant run isolation is incomplete

**Current position:** Run, tenant and BU guards and scoped retrieval are implemented and service-tested. Live semantic canary testing excludes foreign tenants and rejects wrong-run/BU scope. Full product-wide multi-persona acceptance remains open.

**Impact:** The code does not substantiate the shared multi-tenant tier or per-BU confidentiality claim end to end. Separate deployment isolation can reduce this exposure for an initial pilot.

**Required work:** Add tenant and business-scope ownership to runs, jobs, artifacts, citations, caches and retrieval; enforce the authenticated scope in every lookup, not just in the agent layer.

**Acceptance:** Two tenants and two BUs sharing infrastructure cannot list, resolve, retrieve, search, export or ask about each other’s records, including guessed IDs and latest aliases.

**Suggested owner:** Security + data architecture

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Run schema](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/deploy/postgres/schema.sql#L20>); [Run lookup](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/state_store.py#L372>); [Pointer selection](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/run_registry.py#L84>).

<a id="g08"></a>
## G08 · P0 · Frozen board memory is not demonstrated as an immutable snapshot

**Current position:** Immutable database snapshots retain approved figures, answers and exact file bytes. The original closed meeting remained byte-identical after an upload, service restart and a newly approved/reprocessed company run. A second meeting closed through the UI and immediately switched to frozen routes.

**Impact:** A closed meeting may describe a frozen record while later source/run changes alter what is displayed or what the assistant can use.

**Required work:** Persist a meeting snapshot containing the approved data, citations, report versions and content hashes. Resolve every closed-board read and question exclusively through that snapshot.

**Acceptance:** Close a meeting, change/reprocess current company data and restart services; the meeting’s figures, files and answers remain identical and inaccessible data stays unavailable.

**Suggested owner:** Board product owner + backend lead

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Board payload construction](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L3883>); [Frozen object](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L4017>).

<a id="g09"></a>
## G09 · P1 · Live sign-out does not invalidate the session

**Current position:** Caddy recreation fixes stale mounted routes; logout invalidates protected access. Cross-tab sign-out and expired-session login redirects passed actual UI QA.

**Impact:** Users can believe they signed out while the protected session remains usable.

**Required work:** Align deployed identity routing and handler version, revoke the server token and expire the cookie, and make the UI handle a failed logout explicitly.

**Acceptance:** After sign-out the same cookie cannot access a protected route; the response and browser navigation agree, including proxy and branch deployments.

**Suggested owner:** Identity + deployment owner

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Live logout check](<evidence/live-logout-check.json>); [Frontend logout](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/static/executive.js#L3812>); [Identity logout handler](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/idp.py#L364>).

<a id="g10"></a>
## G10 · P0 · Question-bank reporting does not measure the required answer quality

**Current position:** The fixed stratified 50-question sample completed on revision 4efaf51. It did not pass factual acceptance: source/citation/retrieval and calculation gaps remain explicit. Earlier audit-context and quota-limited attempts are retained separately. Corrected source retrieval and deterministic reconciliation are being retested; no routing-based pass rate is claimed.

**Impact:** A high answered count can be mistaken for the specified 45/50 correct, resolving-citation and zero-fabrication gate.

**Required work:** Add held-out reference answers, calculation tolerances, actual citation resolution, relevance grading, theme-stratified sampling and per-question adjudication. Bind reports to build, source pack and model versions.

**Acceptance:** The latest approved release answers at least 45 of 50 questions sampled across all 18 themes correctly with resolving citations and no fabricated numbers; publish the failed and refused questions separately.

**Suggested owner:** QA lead + domain reviewer

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Corpus scorer](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/qa_regression_corpus.py#L57>); [Probe results](<evidence/audit-probe-results.json>).

<a id="g11"></a>
## G11 · P1 · Portable datasets fixed; external-service acceptance remains open

**Current position:** The full suite runs against real PostgreSQL and Neo4j with zero skips. The latest completed service suite passed 1,771 tests. Actual CEO/board UI checks cover login/logout, uploads, durable conversations, source details and immutable reports; factual acceptance remains open.

**Impact:** A green suite is not evidence that persistence, concurrent approval, current enriched data, browser interactions or frozen-board behavior works.

**Required work:** Vendor portable sanitized enrichment fixtures, use explicit skips for genuinely optional checks, and add mandatory isolated integration and browser acceptance jobs for the release.

**Acceptance:** Clean CI executes the enrichment assertions, service-dependent security/transaction tests, and required CEO/board journeys; unexpected skips fail the release gate.

**Suggested owner:** QA + developer experience

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Nonportable enrichment tests](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/tests/test_source_strategy_enrichment.py#L8>); [CI workflow](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/.github/workflows/strategyos-ci.yml#L43>).

<a id="g12"></a>
## G12 · P1 · A reusable strategy-to-KPI compiler is missing

**Current position:** Structured strategy compilation, formula binding, invalid-input handling and recompile diffs are tested on two company configurations. Unstructured extraction and a completed client owner-review workflow remain unverified.

**Impact:** Onboarding another client remains a custom data-and-code exercise instead of the product’s defining self-composition capability.

**Required work:** Build a versioned intent schema and human-reviewed compiler from strategy text to objectives, targets, measures, leading indicators, ownership, cadence and source bindings.

**Acceptance:** Onboard a second anonymized company without code changes; prove target extraction, owner review, formula binding, recompile diffs and unsupported-input handling.

**Suggested owner:** Product architect + knowledge engineer

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Workbook discovery](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L21>); [Enrichment entry point](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L545>).

<a id="g13"></a>
## G13 · P1 · Intent Vault and governed amendments are missing

**Current position:** Versioned Intent and amendment APIs exist. Existing navigation and real owner-ratified amendment records do not meet the full acceptance contract; no amendments were fabricated.

**Impact:** Users can inspect performance but cannot inspect and govern the intent against which it is measured.

**Required work:** Implement R4 F1 read-only first: versioned plan, commitments, initiatives, owners, ratification and amendment provenance. Reuse one schema for any future workshop-capture flow.

**Acceptance:** Intent is reachable from navigation; every commitment exposes approval and last amendment; at least three real amendments resolve; every diagnostics KPI links to its plan version.

**Suggested owner:** Product + intent/data lead

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [R4 feature order](<../requirements.md>); [Executive shell](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/static/executive.html#L1>).

<a id="g14"></a>
## G14 · P1 · Production connectors and incremental ingestion are missing

**Current position:** Actual ERP, treasury, banking and calendar connections are explicitly deferred by the user. The release uses a labelled synthetic source pack and does not claim external cadence or delivery.

**Impact:** The continuous intelligence product currently depends on manually prepared extracts and reprocessing.

**Required work:** Choose the first client’s actual ERP/AP/AR, treasury and calendar integrations; implement source contracts, incremental cursors, deduplication, retry/dead-letter handling and reconciliation.

**Acceptance:** Repeated and out-of-order source deliveries are idempotent; transactions, nightly bank balances and calendar updates arrive at their declared cadence with visible freshness and failure state.

**Suggested owner:** Integration lead + client data owner

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Connector catalog](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/platform_foundation.py#L270>); [Oracle ingest authorization](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L9888>).

<a id="g15"></a>
## G15 · P1 · Continuous drift and historical Plan Health remain partial

**Current position:** Historical measurement and drift APIs exist. Automatic operational source cadence and end-to-end freshness degradation require the deferred connection stage.

**Impact:** A one-time dataset snapshot can look like ongoing monitoring; the cadence ladder and automatic escalation are not established.

**Required work:** Separate demo clock from deployment time, persist metric observations and thresholds, schedule refresh/detection, and derive monitoring status from recent successful work and heartbeat evidence.

**Acceptance:** New measurements automatically change drift state, historical trajectory and alerts; stale connectors and stopped workers visibly degrade readiness; slow KPIs do not fake daily movement.

**Suggested owner:** Data platform + runtime owner

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Fixed clock and enrichment](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L695>); [Live runtime payload](<evidence/live-run.json>).

<a id="g16"></a>
## G16 · P1 · Cross-system entity resolution and consolidation need broader proof

**Current position:** Consolidation controls and regression cases cover aliases, intercompany amounts and dated FX. A client multi-system corpus and owner reconciliation remain future acceptance evidence.

**Impact:** The finance POC’s successful planted patterns do not establish correct consolidated results for a new client’s messy multi-system records.

**Required work:** Add confidence-scored identity mappings, merge/split review, legal-entity-aware matching, intercompany reconciliation and effective-dated FX policy.

**Acceptance:** A multi-system corpus covers aliases, shared bank accounts, disputed matches, intercompany sweeps and FX-rate dates; every aggregate reconciles without double counting.

**Suggested owner:** Finance data engineering + client finance reviewer

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Finance resolution detector](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/skills/finance_controls.py#L515>); [Oracle normalization and controls](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/oracle_finance.py#L1>).

<a id="g17"></a>
## G17 · P1 · Recovery meter is limited to the first eight decision rows

**Current position:** Recovery reconciliation includes all eligible rows, independent of visible decision-card limits; partial receipts, reversals and ordering invariance are covered by passing tests.

**Impact:** Later valid recoveries can be omitted, and reordering a workbook can change reported totals.

**Required work:** Join recovery events to stable case and run identifiers; distinguish identified, verified, approved, collected and written-off amounts, with no row-position filter.

**Acceptance:** Adding a ninth eligible recovery changes the meter correctly; shuffling rows does not; partial receipts and reversals reconcile to payment evidence.

**Suggested owner:** Finance product + data engineering

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Recovery aggregation](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L653>).

<a id="g18"></a>
## G18 · P1 · Working-capital drift uses settlement-day proxies

**Current position:** The canonical finance adapter computes DSO/DPO from explicit open balances and denominators, with unpaid-balance regression tests. The legacy audit still exposes clearly labelled collection/payment timing proxies. The new receivables aging reconciliation uses actual invoices, applied receipts and customer segments. Client finance review remains outstanding.

**Impact:** A proxy can disagree materially with financial DSO/DPO and understate deterioration in unpaid invoices.

**Required work:** Name settlement-speed metrics explicitly; implement the balance-based ratios with approved periods, open-item treatment and a prior-window baseline. Keep Task-1 overlap exclusions.

**Acceptance:** Compare both metrics with a finance-reviewed example containing large unpaid balances; disclose formulas, weighting and windows and prove cash-impact reconciliation.

**Suggested owner:** Finance engine owner

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Current drift calculation](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/skills/finance_controls.py#L1039>); [KPI source extract](<evidence/verification-summary.json>).

<a id="g19"></a>
## G19 · P1 · Cost-of-drift conversion is a limit, not a completed feature

**Current position:** Financial drift and approved factor bindings have deterministic contracts; missing factors remain missing inputs. Full client factor approval and end-to-end surface acceptance are not yet established.

**Impact:** The product cannot consistently rank strategic drift by monetary consequence or time cost.

**Required work:** Approve per-KPI conversion logic, source inputs and uncertainty bounds; compute where defensible and retain quantified nonfinancial gaps where not. Avoid requiring fabricated monetization.

**Acceptance:** Financial drift reconciles to the variance bridge; nonfinancial conversions cite approved factors; missing factors produce a precise missing-input request, never an invented number.

**Suggested owner:** Domain owner + quantitative engine

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Drift conversion](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L206>); [Executive policy inputs](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L60>).

<a id="g20"></a>
## G20 · P1 · Decision Velocity is not implemented

**Current position:** Durable decision timestamps and verified first-action velocity are implemented and tested. A source-linked metric in the existing UI remains unverified.

**Impact:** The headline business problem—decision latency—has no measured outcome in the product.

**Required work:** Instrument immutable lifecycle events and compute the two medians and queue ages per scope; exclude pending actions from completed-duration medians and show their age separately.

**Acceptance:** A recorded decision and subsequent verified first action update the correct metric; overdue open items remain visible; source events drill through from the card.

**Suggested owner:** Product analytics + workflow owner

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Decision record endpoint](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L9614>); [R4 work order](<../requirements.md>).

<a id="g21"></a>
## G21 · P1 · Recording a decision is not closed-loop execution

**Current position:** Durable idempotent decisions, approval gates and evidence-based completion state are implemented. External dispatch and authoritative external completion are intentionally deferred.

**Impact:** Users still need an external process to turn approval into assigned work, acknowledged ownership and verified completion.

**Required work:** Build an explicit approved dispatch queue, connector-specific delivery, acknowledgement, escalation and outcome reconciliation. Keep proposal/approval/delivery/completion distinct.

**Acceptance:** Retries cannot duplicate delivery; failures remain pending with a clear owner; a task closes only when authoritative completion evidence arrives.

**Suggested owner:** Workflow + integration lead

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Decision outcome contract](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L9614>); [Agent capabilities](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/agent_runtime/registry.py#L96>).

<a id="g22"></a>
## G22 · P1 · Agent experiences are not one continuous state model

**Current position:** Private conversations persist across refresh and restart, with optimistic conflict detection. The specialist runtime exists, but one continuous delegated task through the existing chat and agent UI is not yet established.

**Impact:** Status can disagree across assistants, tasks and decisions; conversational continuity depends on a browser session and selected run.

**Required work:** Define which runtime owns tasks, messages, decisions and memory; project all UI states from its events. Distinguish seeded/demo conversations from live tasks and implement cross-device authorized memory.

**Acceptance:** One real request traces through delegation, evidence, approval and result; refresh/restart/another authorized device preserves the same task and conversation state.

**Suggested owner:** Agent platform + product architect

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Specialist registry](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/agent_runtime/registry.py#L1>); [Seed threads](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/source_strategy_enrichment.py#L333>); [Live chat and twin state](<evidence/live-run.json>).

<a id="g23"></a>
## G23 · P1 · Configured vector search is still a lexical/hash fallback

**Current position:** Pinned local multilingual E5 now indexes 37,537 eligible source records, including Office text, without evaluator question-bank leakage. Independent English/Arabic acceptance corpus achieved recall@3 0.90; live cross-scope canary tests and no-egress runtime checks passed. Client-agreed targets remain unratified.

**Impact:** Paraphrases, cross-language questions and semantic entity similarity may miss evidence even when the documents exist.

**Required work:** Add a deployment-approved embedding model, hybrid ranking, metadata/ACL filters and a versioned reindex process; measure recall independently of answer generation.

**Acceptance:** A held-out corpus with paraphrases, entity aliases and Arabic/English queries meets agreed recall@k and citation precision targets without cross-scope leakage.

**Suggested owner:** Retrieval owner

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

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

**Current position:** Unsupported personas remain explicitly disabled and an unassigned BU user is denied rather than receiving group data. A complete four-persona workflow is not delivered; no business assignment was guessed.

**Impact:** The pilot can demonstrate the CEO lane, but should not promise equivalent decision workflows at all four altitudes.

**Required work:** Sequence one real CFO cockpit and one BU operating cockpit, with scope-aware KPIs, owned decisions and upward commentary; retain locks until each is accepted.

**Acceptance:** Persona changes alter data scope, responsibilities and workflow, not just labels; direct URLs cannot substitute another persona’s header or access rights.

**Suggested owner:** Product owner + identity/data teams

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Persona/mode definitions](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/api.py#L4115>); [Persona source requirements](<evidence/verification-summary.json>).

<a id="g26"></a>
## G26 · P1 · Deployment policy exists; tier proof and visible residency do not

**Current position:** The release identifies its provider and pinned local embedding model; sealed local embedding runs without network. Separate deployment-tier factual gates and complete visible residency acceptance remain open.

**Impact:** The four deployment tiers and sovereign/no-egress claim lack a release-specific acceptance record.

**Required work:** Publish truthful per-deployment model, region, storage and egress configuration; verify air-gap operation and approved provider paths using the same release corpus.

**Acceptance:** The screen matches actual deployment configuration; blocked egress cannot trigger an unapproved fallback; each supported local model passes the answer-quality gate.

**Suggested owner:** Deployment architect + security

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Run policy](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/strategyos_mvp/config.py#L138>); [R4 residency marker](<../requirements.md>); [Live sample](<evidence/live-question-probes.json>).

<a id="g27"></a>
## G27 · P1 · Arabic/RTL support and complete accessibility acceptance are absent

**Current position:** Arabic source text/search and keyboard/mobile checks have passed selected tests. Complete Arabic/RTL and screen-reader journeys are not verified; new language controls were removed to preserve the required UI.

**Impact:** The current build does not substantiate its stated bilingual launch scope.

**Required work:** Introduce translation catalogs, direction-aware layout and number/date localization; add Arabic OCR where needed and test actual Arabic financial documents. Audit keyboard/focus, contrast and responsive layouts.

**Acceptance:** Core intake, diagnostics, drill, chat, decision and board journeys work in Arabic and English with keyboard and screen reader; exported figures preserve units and meaning.

**Suggested owner:** Frontend + localization QA

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

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

**Current position:** An isolated PostgreSQL restore reconciled all recorded run, artifact, decision, conversation and board row digests. Workspace backup integrity was checked. Recovery times are measured observations, not agreed RPO/RTO commitments.

**Impact:** A bad migration, deleted evidence file or host loss can break provenance and recovery even if the container image rolls back.

**Required work:** Define the authoritative recovery set, encrypted scheduled backups, retention, restore procedures and forward/backward schema compatibility; treat Neo4j/Qdrant as rebuildable projections where appropriate.

**Acceptance:** Restore into a clean environment and reconcile approved runs, evidence hashes, decisions and board snapshots within agreed recovery objectives.

**Suggested owner:** SRE + data platform

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

**Evidence:** [Rollback implementation](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/deploy/scripts/rollback_stack.sh#L1>); [Production hardening list](<https://github.com/TarasMyklush/strategyos-mvp/blob/c03e95816dedf6dedf05778cb725d42a84c29de2/docs/production-deployment-plan.md#L73>).

<a id="g30"></a>
## G30 · P1 · SLOs, capacity, inference audit and cost controls are not demonstrated

**Current position:** Live encrypted inference records now retain authenticated tenant/user, model, timing and hash-verifiable request/response with tenant-bound encryption and expiry. Missing scope blocks provider calls; quota/retention tests pass. Target-volume load and agreed SLOs remain open; reservations are not billed-token or price evidence. A 20-request preview exercise with four concurrent clients completed all 15 permitted business reads and correctly denied five operator-only health reads; no service or transport errors occurred. This is not a target-capacity certification.

**Impact:** Production responsiveness, backlog behavior and inference accountability are uncertain.

**Required work:** Instrument queue depth, p50/p95/p99 latency, freshness, OCR failures, reviewer age, provider token/cost usage and per-tenant quotas; test overload, restart and provider outage.

**Acceptance:** Publish agreed SLOs and load results at target volume; alerts fire on seeded failures; inference records identify tenant/user, model/version, time, evidence and protected prompt/response references under a retention policy.

**Suggested owner:** SRE + AI platform + QA

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

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

**Current position:** The test runner uses disposable application/output state, creates required directories before import and exercises atomic pointer persistence. Full service suites execute with no unexpected skips.

**Impact:** Local validation can leave the application pointed at transient test data, and a passing report from a different environment cannot substitute for a clean current run.

**Required work:** Isolate all test output roots and prohibit promotion of temporary test runs to normal pointers. Make pointer writes atomic and validate referenced artifacts before promotion. Keep test harness setup explicit and separate harness failures from product defects.

**Acceptance:** Running the complete suite leaves production/local-business pointers unchanged; interrupted writes cannot corrupt pointers; a clean test harness creates its required directories before importing application configuration.

**Suggested owner:** QA + runtime/data owner

**Evidence classification:** Remediation evidence, 2026-09-05; see validation.md and release receipt

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
