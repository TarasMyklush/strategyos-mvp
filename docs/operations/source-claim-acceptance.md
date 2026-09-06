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
  that path still requires closure without manual database operations. Mobile
  visual acceptance and online deployment of this candidate remain pending.
