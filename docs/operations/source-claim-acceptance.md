# Source-and-claim acceptance evidence

## Scope and boundaries

This register concerns the common source-and-claim foundation. It is not a claim
that live ERP, news-provider, email or chat connectors have been built. Synthetic
public/licensed/correspondence records exercise the same repository contract;
they are explicitly fixtures, not messages received from real people.

The executive application still contains legacy presentation projections.
Whole-run source authorization protects their charts, prose and tables as one
unit. This is deliberately conservative: per-source or BU-restricted users must
use the claim API instead of receiving a potentially leaky partial briefing.
It is not yet a full per-claim rewrite of every legacy presentation component.

## Reproducible checks

| Requirement | Executable evidence |
| --- | --- |
| Source origin independent of capture channel | `test_source_claims.py`, `test_cross_source_postgres_e2e.py` |
| Internal, public, licensed, email and chat source envelopes | `test_cross_source_postgres_e2e.py` |
| Provider and license reference required for licensed registration | `test_cross_source_claims.py` |
| Actual/plan/forecast/assumption/reported separation | `test_source_claims.py`, `test_cross_source_claims.py` |
| Attributed forecast, period, unit and scale retained | `test_cross_source_postgres_e2e.py` |
| Immutable revisions and idempotent replay | `test_claim_store_postgres_e2e.py` |
| Exact calculation lineage and inherited source access | `test_claim_store_postgres_e2e.py`, `test_claim_projection.py` |
| Calculated actual cannot launder nonactual input | `test_cross_source_postgres_e2e.py` |
| Caller tenant cannot be replaced by requested tenant | `test_cross_source_postgres_e2e.py` |
| Evidence artifact tenant/hash validation | `test_cross_source_postgres_e2e.py` |
| Source revocation affects granular and bulk reads | `test_cross_source_postgres_e2e.py` |
| Export, external-model and quotation permissions | `test_cross_source_claims.py`, `test_cross_source_postgres_e2e.py` |
| Raw source downloads and artifact previews enforce export policy and audit denial | `test_governed_claim_adoption.py` |
| No external model request on denied/unavailable source policy | `test_cross_source_claims.py` |
| Missing snapshot/reconciliation cannot return legacy financial values | `test_governed_claim_adoption.py` |
| Both `/qa` and `/assistant/chat` enforce the boundary | `test_governed_claim_adoption.py` |
| Real Neo4j projection and idempotency across source categories | `test_cross_source_postgres_e2e.py` |
| Projection retries, leases, cache and vector serialization | `test_claim_projection.py`, `test_claim_store_postgres_e2e.py` |
| Public-web untrusted label, provider/license, forecast and units in audit UI | `executive.js:governedClaimAuditMarkup`; browser acceptance required |
| Failed briefing refresh hides stale views and offers Retry | `test_frontend_shell.py` |
| Real pinned local model and Qdrant cross-source ranking, with PostgreSQL reauthorization | `test_cross_source_postgres_e2e.py`, `test_claim_retrieval.py` |
| Current withdrawal blocks historical queries and derived claims | `test_cross_source_postgres_e2e.py` |
| Snapshot replay never appends new families | `test_snapshot_immutability.py` |
| Upload/folder policy preservation and strict consent booleans | `test_source_contract_intake.py` |
| Legacy read and list source authorization | `test_legacy_source_scope.py`, `test_cross_source_postgres_e2e.py` |
| Bulk snapshot input-source permissions and lifecycle withdrawal across ingestion batches | `test_bulk_claim_lineage_postgres_e2e.py` |
| KPI component metric/kind/unit/currency/scale and comparison-period validation | `test_governed_finance.py`, `test_governed_claim_adoption.py` |
| Executable calculation contracts, exact result checking and forbidden ratio/time/FX mixing | `test_claim_calculations.py`, `test_bulk_claim_lineage_postgres_e2e.py` |
| Explicit typed manual intake cannot self-verify or send | `test_claim_api.py` |
| Mixed workbook types, ambiguous cells, missing values, exact row locators and mapping revisions | `test_tabular_claims.py` |
| Atomic batch rollback, artifact binding, idempotent receipt and current-policy replay checks | `test_tabular_claims_postgres_e2e.py` |
| Multipart preview-first endpoint and operator screen | `test_workbook_intake_api.py`; browser acceptance required |
| Scoped forecast acceptance remains forecast, with missing/expired review dates failing closed | `test_forecast_review.py`, `test_forecast_review_postgres_e2e.py` |
| Review actor/time runtime binding, no self-authorization payload and no foreign-claim existence leak | `test_forecast_review_api.py` |
| Independent claim workspace, safe source rendering and explicit claim types | `test_claim_workspace.py`; browser acceptance required |
| Legacy mixed Actual/Est group columns cannot become actuals or drive derived actual margin | `test_source_finance_kpis.py`, `test_finance_semantic_quarantine.py` |
| Quarantined snapshot rows are excluded without crashing eligible reads | `test_quarantined_snapshot_postgres_e2e.py` |
| Historical semantic audit verifies original file hashes and never rewrites approved history | `test_finance_semantics_audit.py` |

Run the complete suite against dedicated disposable PostgreSQL, Neo4j and Qdrant,
with the release-pinned local embedding model provisioned:

```sh
python scripts/test.py --services -q tests/ --junitxml=service-results.xml
python scripts/check_test_report.py service-results.xml
```

Never run two suites against the same proof database: older integration fixtures
reset their test state. These must not point at either deployed database.
The preview deployment workflow now runs this service gate before building its
image, and rejects skipped tests as well as failures.

## Remaining boundaries — do not claim universal completion

- Evidence-bearing Hermes and twin model calls share a source-consent gate,
  including legacy summaries and public presentation packets. Missing context
  denies transmission. Local packet answers remain available independently;
  the legacy twin runtime falls back locally until it supplies governed context.
- Arbitrary document extraction is not automatically a typed numerical claim;
  unknown semantics must remain unknown instead of inventing units or kinds.
- Actual third-party connector authentication, delivery, retries and consent
  need real integrations; no live CFO request or reply is simulated as real.
- A full per-claim migration of all legacy UI/read models remains distinct from
  the conservative whole-run authorization boundary.
- Source traceability is labelled “Source traced”, not “Evidence verified”.
  Explicit assessment events remain separately visible; the UI does not infer
  a review from a source's origin or successful retrieval.
- Legacy group budget columns labelled Actual/Est and estimated cash rows need
  explicit classification. The semantic adapter retains these as unknown and
  removes them from actual components. Old approved snapshots require a separate
  source-hash-checked audit and withdrawal/replacement process; new ingestion
  rules do not retroactively correct previously published claims.
- Storage/indexing license rights, complete producer/consumer migration,
  independent corroboration of syndicated material, and full operating/recovery
  acceptance must still be closed before claiming the entire plan complete.

Record the exact workflow SHA and online observations at release sign-off. Test
counts alone do not close these boundaries.

## Preview checkpoint — 6 September 2026

- Release `0dfbfc5557f4e4e66bfc82f324a3e83b2a4b71f7`, GitHub Actions run
  `34052334365`: test, build and preview deployment succeeded. Production was
  not targeted.
- Saved executive-tester login: authenticated claim queries, snapshots and real
  local-model semantic retrieval passed. External-model and quotation use
  returned no claims; executive intake was denied (403), anonymous reads 401.
- Browser: signed in after deployment and checked the claims form and scoped
  forecast empty state. It explicitly reported that no other type was substituted.
  This is not evidence of complete consumer adoption: the legacy executive
  briefing still displays historical financial claims needing semantic review.
- Recovery rehearsal: the preview custom-format PostgreSQL backup was restored
  into the isolated local proof database, with 22,846 revisions, two snapshots,
  zero assessments and passed current-run reconciliation (11,554 / 11,554).
  No deployed database was restored or overwritten.
- Read baseline (five requests per endpoint, concurrency at most two): single
  actual claim median 499 ms, empty forecast 497 ms, 200-record snapshot 4,116 ms.
  These are observations, not an agreed SLO or load certification.
- Historical audit initially refused normalization aliases. Read-only comparison
  found identical hashes under recorded `99_Historic_Context/...` paths for the
  budget and analytics workbooks. Audit alias handling must retain explicit
  recorded paths and reject ambiguity; no approved history was changed.
- Storage/index rights are under development and have not been deployed at this
  checkpoint. New intake is denied without explicit storage permission; search
  rights are separate. Complete legacy-index coverage remains to be verified.

### Content-rights candidate verification

- Full dedicated PostgreSQL/Neo4j/Qdrant/local-model suite: **2,015 passed,
  zero skipped**, receipt `/tmp/strategyos-rights-proof2.xml`, 291.46 seconds.
- Current-policy storage and indexing gates cover claim intake, shadow writes,
  graph/vector projectors and legacy bulk indexing. Revocation and subsequent
  re-grant produce audited policy versions; dependent projections are refreshed.
- `test_source_storage_rights.py` proves missing/false/string-valued consent is
  rejected before durable source copying. Storage-only quarantine grants no read,
  indexing, export, quotation or external-model use implicitly.
- Isolated browser proof used synthetic text only: no consent blocked staging;
  storage-only consent staged one file, showed “Stored for classification” and
  did not start analysis. The legacy operator route is unreachable from `/app`;
  a clean authorized intake entry remains a separate UI closure item.
- Read-only audit with explicit normalized-path aliases verified all five
  finance source hashes and identified three historical actual claims for
  correction (cash, cost, revenue). No assessments or snapshots were modified.

### Source-intake and existing-index closure candidate

- Full dedicated service suite: **2,020 passed, zero skipped**, receipt
  `/tmp/strategyos-intake-proof.xml`, 327.04 seconds.
- `/app?lane=operate` now resolves to an operator-authorized, noncacheable
  `/sources/intake` page. The executive route remains unchanged.
- Browser inspection at desktop width verified expandable classification,
  storage-only quarantine, explicit classified staging, safe receipt rendering,
  and disabled analysis for a source without the required dataset mapping.
  Only isolated synthetic files were staged; no analysis was launched.
- Existing legacy vector reads and graph previews recheck indexing permission,
  and source-text indexing checks permission before reading source files.
- This does not yet make staged files independently registered claim evidence:
  that path still requires closure without manual database operations.
- Additional narrow-browser inspection at 462 px verified collapsed and expanded
  source contracts with no horizontally overflowing controls (document width
  also 462 px). Online deployment of this intake candidate remains pending.
- Content-rights release `ffdcc31c6e5f52505138497551a9fa012ef06200`, workflow
  `34053780628`, succeeded. Authenticated snapshot, typed queries, local semantic
  search, denied external-model/quotation access, denied executive intake and
  unauthenticated denial all passed after readiness returned. During backup,
  projector checks briefly timed out and then recovered; a login probe during
  container replacement returned 502 and was repeated successfully afterwards.
  This is not a zero-downtime deployment acceptance claim.

### Source revision and operator sign-in candidate

- Registration-writer consolidation baseline: 2,022 service tests passed,
  receipt `/tmp/strategyos-registration-proof.xml`, 432.48 seconds.
- Subsequent targeted checks cover historical source classification, current
  permission denial on historical reads, consecutive policy/registration changes
  with adjacent effective periods, and manual authorized login without account
  enumeration. These additions require the final frozen-candidate service gate.
- Manual login was visually inspected at 462 px. Operator login routes to source
  intake; CEO login retains its existing executive destination.
- Historical provenance uses registration versions as of the analysis timestamp.
  Current policy remains authoritative. Missing historical registration is
  explicitly unknown, not reconstructed from a later classification.

### Frozen temporal candidate and staged-evidence handoff

- Frozen commit `0d03331`: 2,025 service tests passed, zero skips, receipt
  `/tmp/strategyos-frozen-temporal.xml` (345.17 seconds). Preview workflow
  `34055434827` was dispatched; this entry does not assert deployment completion.
- The operator handoff registers a hash-verified staged file as an evidence
  occurrence, then opens explicit workbook mapping. Existing source contracts
  cannot be changed or re-granted by replaying a stale intake contract.
- Local browser proof against isolated PostgreSQL completed staging, registration,
  actual/forecast mapping preview, recording and separate retrieval. Preview
  created no claims; recording created two unreviewed synthetic claims: SAR 120
  actual and SAR 130 forecast attributed to Synthetic CFO for June 2026. No
  analysis, approval, publication or outbound delivery occurred.
- Re-registering the workbook returned the same occurrence. Narrow-screen visual
  inspection at 390 px showed readable receipt controls and document width 390 px;
  the viewport override was reset afterwards.
- Artifact and occurrence writes are atomic. Hash conflicts roll back new
  artifact metadata; current storage revocation denies registration. This intake
  handoff currently requires group-wide source and operator scope; BU-restricted
  artifact registration is denied, not silently broadened.
- The handoff changes still require their own frozen full-suite and preview
  deployment gate; the earlier 2,025-test result does not cover them.

### Temporal release and stale-calculation candidate

- Preview workflow `34055434827` succeeded at
  `0d03331d0f90437fb62a2099c08370abc6a9186c`. Authenticated snapshot, typed query,
  local semantic retrieval, source-use denial, executive-intake denial and
  anonymous denial probes passed after deployment. Production was untouched.
- The browser controller returned `ERR_BLOCKED_BY_CLIENT` navigating to preview.
  This is not an online visual-QA pass; local browser evidence is recorded separately.
- Stale-calculation candidate: current reads reject calculations with revised
  recursive inputs. Historical as-of reads retain exact values and display a
  visible revised-input warning. Frozen snapshots report `requires_recompute`;
  legacy bulk reads cannot reuse revised inputs as current prose or charts.
- Both claim writers enqueue recursive graph/vector/cache refreshes when an input
  family receives a new revision. Projection annotations retain history; ledger
  reads enforce freshness independently of delivery lag.
- Isolated PostgreSQL checks cover recursive revision invalidation, historical
  snapshot retention, bulk-read refusal, nine dependent projection updates, and
  an explicit new calculation restoring current eligibility without rewriting
  the old snapshot. Browser checks verified current exclusion and historical
  warning at 390 px with no horizontal overflow; viewport reset afterwards.
- This detects the need for recomputation; it does not yet provide an operator
  queue or automatically publish/reapprove a replacement analysis. Those remain
  separate closure work. Full frozen service verification is still required.

### Follow-up gate findings

- Handoff commit `1369e9d`: 2,036 tests passed, zero skips, receipt
  `/tmp/strategyos-handoff-full.xml` (517.40 seconds).
- The first frozen freshness gate stopped on an injected repository-factory
  test: lineage validation referenced a replaceable module-level factory instead
  of its repository instance. The implementation now uses the instance method;
  the failed gate is not counted as acceptance.
- Scoped evidence registration now permits a source wholly inside an operator's
  BU authority. Group-wide, foreign-BU and partially overlapping sources remain
  denied. Current policy is rechecked in the artifact/occurrence transaction;
  claim-level row scope validation remains a separate mandatory check.
- A fresh preview-browser tab also timed out without being created. No browser
  security settings were changed or warnings bypassed. Online visual acceptance
  remains open despite passing authenticated HTTP checks.

### Explicit recalculation candidate

- Frozen freshness/intake commit `dfcd62f`: 2,041 tests passed, zero skips,
  `/tmp/strategyos-scope-full.xml` (752.19 seconds). Preview workflow
  `34057159552` was dispatched; deployment completion is not asserted here.
- Recalculation candidate: 51 focused tests passed. These cover preview without
  writes, exact-preview recording, retry receipts, policy/input changes, cycles,
  transactional rollback, authority denial, cross-tenant receipt constraints,
  server recording clocks and PostgreSQL migration parsing/rollback.
- Local browser QA recorded one synthetic calculated revision from 10 to 12 SAR.
  The result explicitly stated unreviewed and unchanged briefing/approvals. Its
  evidence link preserved operational-review purpose and retrieved current 12.
  This is isolated local evidence, not an online production or preview claim.
- The recalculation candidate still needs its frozen full-suite and preview
  gates. It does not complete automatic replacement analyses, conflict/source
  precedence or all legacy consumer migration.

### Recalculation discovery

- A bounded operator queue scans current calculated families and exposes only
  authorized revised-input candidates. It returns no replacement values and
  does not imply permission to apply; preview repeats the complete checks.
- Fourteen focused tests passed, including tenant isolation, revoked-source
  filtering, pagination and queue clearing after explicit recalculation.
- Local browser discovery opened the correct current calculated revision and
  previewed the next synthetic change, 12 to 14. No second recording was made.
- The attempted viewport override remained 1280 px when measured, so that attempt
  is not mobile acceptance. The temporary override was reset.

### Exact reporting-period query contract

- Typed and semantic reads now accept exact start/end dates and an optional
  fiscal-calendar identity. Both dates are required together. Overlapping and
  unknown periods cannot satisfy an exact-period query; no implicit aggregation
  or calendar inference occurs. Recalculation result links preserve this scope.
- Thirty-six focused unit/API/retrieval/UI tests and one isolated PostgreSQL
  SQL-plus-semantic-candidate proof passed. Local browser QA showed an explicit
  June query declining an undated synthetic claim rather than substituting it.
- These additions still require a frozen full-service gate. They are not a
  substitute for unresolved source-priority/conflict policy work.

### Preview release `dfcd62f` — live browser acceptance

- GitHub workflow `34057159552` completed successfully. Authenticated snapshot,
  typed query, local semantic retrieval and denial probes passed after deployment.
- The in-app browser became available again. Executive sign-in, evidence details
  and the non-substituting forecast empty state were checked visually. Operator
  manual sign-in redirected to source intake correctly.
- Browser staging, exact-file registration, mapping preview and recording passed
  with source `qa-provenance-preview-20260907`, explicitly synthetic and restricted
  to operator/operations. Indexing, export, quotation and model use are denied.
  No analysis or publication was started. Pack:
  `050e3a244db5ccfb5f704b8e82cd8a84e90819b8a04e55ab29ceadad67df5a29`.
- Mapping preview returned zero writes; recording returned two claims under
  metric `qa.preview.amount`: actual SAR 120 and forecast SAR 130, June 2026,
  forecast author Synthetic CFO. Receipt:
  `5d4a2cfa-a05f-4754-ba55-48635aa47d0f`. Browser replay returned that same receipt,
  zero created claims and an explicit no-duplicates message.
- Authenticated probes confirmed exact values, periods, no assessments, and
  denial for executive briefing, export, quotation and external-model purposes.
- This does not close legacy presentation/data issues: the home banner still
  combines a cost warning with a separate on-plan score; historical mixed
  Actual/Estimate source values remain in the old actual snapshot. Both were
  observed rather than counted as successful acceptance.
- Separate frozen recalculation commit `efc8de0` passed 2,055 tests, zero skips,
  `/tmp/strategyos-recalculation-full.xml` (721.79 seconds). The newer combined
  queue/period commit `c95d01a` is undergoing its own gate.

### Conflict disclosure candidate

- Shared ledger queries compare all authorized claims in the exact comparison
  scope before semantic candidate filtering. Search rank and ingestion order
  never resolve disagreement. SQL prefilters metric, kind, BU, scenario and
  requested period before policy evaluation.
- Thirty-four focused tests passed, including real PostgreSQL competing-source
  disclosure and removal after source revocation. Equivalent numeric scales are
  compared exactly; no FX or unit conversion is inferred. Independent-origin
  corroboration remains explicitly not assessed, not inferred from copies.
- Local browser QA displayed separate synthetic 10 and 11 SAR assertions with
  visible amber conflict warnings and no selected definitive value.
- This candidate does not yet implement versioned source-priority decisions or
  complete conflict handling across every snapshot/projection consumer. Existing
  finance headline composition independently refuses competing components.

### Explicit source-priority candidate

- Conflict disclosure commit `f7ba6b6` passed 2,064 tests with zero skips in an
  isolated frozen checkout (`/tmp/strategyos-conflict-full.xml`). Queue/period
  commit `c95d01a` independently passed 2,059 tests with zero skips.
- The priority configuration API accepts an explicit tenant-admin decision for
  one comparison scope, with ranked source identities, an explicit review
  requirement (or null), rationale and expected policy version. Actor and tenant
  come from authentication. System identities cannot self-authorize this action.
- Policies are versioned and time-bounded; stale updates fail, exact retries do
  not duplicate versions, and prior-time reads retain the prior policy state.
  Missing source coverage, missing/expired reviews and conflicting top-ranked
  values remain unresolved. A derived claim uses its weakest contributing
  source, not its strongest. No policy is installed by default.
- Priority is not independent corroboration, verification, approval or a change
  to the underlying evidence. All authorized alternatives remain visible. This
  candidate still needs a full gate and downstream snapshot/consumer integration.
- Genuine 390 px local browser checks subsequently passed for conflict warnings
  and recalculation controls, with document width also 390 px. The viewport was
  reset afterwards. This supersedes only the earlier failed viewport attempt.

### Preview release `c95d01a` and snapshot conflict follow-through

- Workflow `34058731984` completed successfully: tests, image build, preview
  deployment and readiness checks. Production was not changed.
- Live operator browser queries verified the synthetic June actual (SAR 120),
  authored forecast (SAR 130), missing-plan empty state and exact-period mismatch
  empty state. Authenticated operator/executive probes passed source-purpose and
  role isolation, snapshot retrieval and local semantic retrieval.
- The fixture receipt lists revision IDs without semantic ordering. Verified
  reads identify actual as `ca693b19-bda0-463e-9aca-ace9bf755d41` and forecast as
  `0a5827c2-e183-48fb-b6f1-12e0f90c2743`; do not infer their types from receipt order.
- Snapshot reads now reuse analysis-time authorized conflict/priority comparison
  before exposing a selected claim as definitive. A paginated frozen selection
  cannot hide a competing assertion outside its selected page. Its recorded
  values remain unchanged, and newer revisions do not rewrite the historical
  disagreement. Current source revocation still removes inaccessible evidence.
- Twenty focused service-backed tests passed with no skips, plus 28 focused
  unit/API/UI tests. This snapshot addition still requires its frozen full gate.

### Expiry and metadata boundary follow-through

- Explicit source-priority commit `49ec82b` passed 2,072 tests with zero skips
  (`/tmp/strategyos-priority-full.xml`, 312.90 seconds). A local 390 px browser
  check showed the preference rationale and the independent-verification
  disclaimer without horizontal overflow; the viewport was restored.
- On the restored preview database, the combined snapshot implementation returned
  ten governed headline records in 1.799 seconds, with no denied or unresolved
  selections. This is an observation, not a contractual latency SLO.
- Claim expiry now uses an exclusive deadline in both direct eligibility and
  recursive input SQL. Boundary tests cover the microsecond before and the exact
  deadline. Twenty-three targeted tests passed, including real PostgreSQL lineage.
- Public snapshot pages require source-scope authorization before exposing page
  metadata. Partial denial returns no hidden counts. Reconciliation totals use
  the same source boundary. A revised-history exception does not admit withdrawal,
  role or purpose denial. Thirty-five targeted API/semantic tests passed.
- These latest expiry and metadata changes are not yet full-gated or deployed.

### Legacy attachment intake retirement candidate

- The legacy CEO Office-file POST route stored files in a tenant vault without
  an evidence occurrence or source policy. It is now explicitly retired (410),
  and its upload-origin download route denies access until governed registration.
  Existing vault files are preserved on disk; no files were deleted.
- Review registries no longer expose legacy-upload filenames, and registered
  source-file lists require run source authorization before registry construction.
  Source-backed view/export links retain their separate permissions.
- The CEO panel uses compact explanatory disclosure instead of the unclassified
  upload form. Authorized operators receive the governed intake link; other
  roles are told that an operator must register source rights first. Intake does
  not automatically add an attachment to an approved briefing.
- 167 focused frontend, attachment and governed-adoption tests passed. This
  candidate still needs the full gate and preview visual acceptance.

### Snapshot volume regression caught before cutover

- Boundary commit `fc26c90` passed 2,082 tests, zero skips
  (`/tmp/strategyos-boundary-full.xml`, 306.70 seconds).
- The 200-record restored-preview benchmark then exposed a 39.435-second read:
  comparison was examining unrelated transaction subjects. Workflow `34059991941`
  for candidate `15049aa` was cancelled during testing, before build/deployment.
  Deployed preview remains `c95d01a`.
- Exact subject scoping reduced the read to 6.540 seconds. Batching up to 200
  subject pairs reduced it further to 2.324 seconds; the prior read without
  comparison took 1.152 seconds. These are isolated measurements, not SLOs.
- Comparisons still include every authorized competing assertion for each
  selected subject. SQL filters unrelated subjects before hydration, and batch
  scope is bounded, explicit and parameterized. Thirty-five focused tests passed
  against a fresh database. An earlier rerun on a reused test database failed on
  an existing fixture tenant; it was not counted as passing evidence.
- The optimized combined candidate still requires a full gate and live QA.

### Optimized gate and replacement-write authority

- Optimized commit `53fc3a5` passed 2,086 tests with zero skips in the frozen
  checkout (`/tmp/strategyos-subject-full.xml`, 308.16 seconds). Preview workflow
  `34060246580` performs its separate full gate before deployment.
- The next write-boundary change checks permissions on the preceding assertion
  as well as replacement evidence, while the claim family is locked. A permitted
  new source cannot overwrite an assertion whose existing source is restricted.
  Failed checks roll back without a new revision or outbox work.
- Fourteen focused PostgreSQL intake/recalculation/conflict tests passed for this
  additional guard. Its full gate and deployment remain pending.

### Preview origin acceptance and additional ownership controls

- Release `53fc3a58a29b2e18c5bfe64a764dccb887773f08`, workflow
  `34060246580`, completed successfully. Live executive/operator probes passed
  typed retrieval, snapshot access, exact period selection, semantic retrieval,
  intake-role denial and legacy-attachment denial. Restricted snapshot uses
  returned 403 without hidden record counts. Production was not targeted.
- Four synthetic source packs were staged and recorded online through the real
  intake APIs: internal, public, licensed and correspondence origins, all captured
  by file upload. Equal bytes retained four distinct occurrences and source rights.
  Only tenant-admin operational review is allowed; CEO/system, briefing, export,
  quotation, indexing and external-model uses are not granted. No analysis,
  approval, publication, message or real connector was triggered.
- Metric `qa.origin.proof.20260907` and policy receipt
  `9469fa27-124b-415e-a622-cc41571c67f8` are explicitly synthetic QA. Priority retry
  was idempotent; copied evidence remained `independent_corroboration=not_assessed`.
  Browser inspection confirmed all four origin labels and the preference-not-
  verification qualification. This does not configure business source precedence.
- Replacement authority commit `06d158b` passed 2,087 tests, zero skips
  (`/tmp/strategyos-replacement-full.xml`, 304.96 seconds). Workflow `34060816975`
  is a separate preview rollout; confirm its completion before release sign-off.
- Migration 0011 adds composite tenant/family constraints. The restored preview
  data migrated without inconsistent rows. Twenty-five targeted service-backed
  tests passed, including fifteen rejected cross-tenant/wrong-family SQL writes.
  Frozen full-suite candidate `4be409b` remains under verification.
- Technical claim provenance now collapses independently; origin, value, units,
  period, author and material qualifications remain visible. Local browser opening
  and closing worked at a measured 462 px without overflow. A requested 390 px
  override did not change that tab's measured width; do not count it as a 390 px
  pass. Five focused workspace tests passed.
- Board-memory candidate reauthorizes frozen reads, questions, lists and exports
  with current source policy. Thirty-one targeted tests passed including real
  PostgreSQL read/revoke/export/revision scenarios and meeting-list isolation.
  Frozen bytes and answers were unchanged. Full and online verification of this
  candidate remain pending; no real meeting was closed during QA.

## Saved-work source scope follow-up

- Frozen `64a7bd0` passed 2,107 tests with zero skips in 676.54 seconds;
  `/tmp/strategyos-board-full.xml` passed the service-report gate. This covers
  migration 0011 and board reauthorization, not the subsequent twin changes.
- Twin saved state is now namespaced by authenticated tenant, actor, role, BU
  scope and authorized analysis. Old unclassified root files are preserved but
  not inherited. Current source permission is rechecked at every request.
- The real PostgreSQL twin test verifies actor isolation and read revocation.
  Controller fixtures are explicitly synthetic and are not ACL evidence.
- Legacy background twin jobs lack a durable initiating-authority envelope.
  The preview scheduler is therefore disabled, including already-queued entry
  points. Implement that envelope before re-enabling it; production is unchanged.
- Missing saved-work authority returns an unavailable optional surface without
  counts or history. It does not break session metadata or claim no business
  attention is needed. Hermes uses the same unavailable response without sources.
- Browser generated-answer fallback caches are retired: network failure cannot
  replay an old answer as a currently authorized success. Durable conversation
  history is preserved and is being audited separately.
- The frontend/CEO regression subset passed 321 tests. Combined full-service and
  preview browser acceptance for these subsequent changes are still pending.
