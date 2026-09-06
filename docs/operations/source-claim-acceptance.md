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
| Explicit typed manual intake cannot self-verify or send | `test_claim_api.py` |
| Independent claim workspace, safe source rendering and explicit claim types | `test_claim_workspace.py`; browser acceptance required |

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

Record the exact workflow SHA and online observations at release sign-off. Test
counts alone do not close these boundaries.
