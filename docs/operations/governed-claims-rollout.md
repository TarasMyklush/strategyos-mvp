# Governed claims rollout

## Preconditions

1. Take and verify a PostgreSQL backup using the existing release process.
2. Confirm Neo4j, Qdrant and the pinned local embedding model are healthy.
3. Provision the release-pinned local model into the governed workspace and set
   `STRATEGYOS_EMBEDDING_MODEL_PATH` to its container path.
4. Deploy the additive schema and code to the preview environment with the
   `governed-claims` Compose profile explicitly enabled.
5. Confirm `strategyos-claim-projector` is healthy before materializing claims.

The projector profile is deliberately opt-in. Without it, source claims and
outbox rows remain durable in PostgreSQL but no graph, vector or cache projection
is attempted. When the profile is enabled the worker fails closed at startup if
the pinned embedding model is absent, changed or incomplete; it never turns an
optional lexical-only installation into dead-lettered vector work.

## Historical preview and application

Preview one run without writes:

```bash
python -m strategyos_mvp.claim_backfill --run-id <run-uuid>
```

Apply that exact run after reviewing document, transaction and balance counts:

```bash
python -m strategyos_mvp.claim_backfill --run-id <run-uuid> --apply
```

`--all` is available for a controlled batch window, but production rollout should
start with one current run. The command is idempotent: replaying an applied run
must report zero created claims and zero created snapshots.

## Required acceptance evidence

Before materializing a historical group-finance run, audit its source semantics:

```sh
python -m strategyos_mvp.finance_semantics_audit --run-id <run-uuid>
```

This command is read-only. It compares the files against the recorded run hashes
and identifies actual claims based on ambiguous Actual/Est inputs. Do not approve
the old classification merely because the numerical reconciliation is zero.
Do not overwrite an approved snapshot. Withdraw invalid assertions with audited
lifecycle events and publish a new analysis only after the source interpretation
has been resolved. The new adapter preserves unresolved values in the unknown
lane and never infers forecast authors or actual boundaries.

- `strategyos_claim_reconciliations.status = 'passed'` for the selected run.
- `difference_sar = 0`, record counts match, and no unreviewed backfill exceptions.
- The snapshot endpoint returns only claims allowed for the test identity.
- CEO cards and authenticated Hermes show the same values, units, periods and
  claim revision IDs.
- Calculated claims disclose exact input revisions and inherited sources.
- Projection outbox has no stale leases or dead letters.
- Neo4j and Qdrant counts are non-zero for the selected run after projection.

## Fail-safe behavior

- A missing source policy blocks retrieval.
- An unresolved KPI source leaves the claim traceability incomplete and excludes
  it from authenticated snapshot reads.
- A missing snapshot, empty eligible headline set or failed reconciliation blocks
  the authenticated briefing with HTTP 503. No legacy financial fallback is sent.
- A denied headline or bulk source policy blocks the complete briefing with HTTP
  403; chart and narrative siblings must not leak the restricted source.
- External-model permission is checked separately before canonical Hermes sends
  evidence. Existing source policies are not automatically upgraded to consent.
- Projection failure does not mutate the source claim. It remains retryable in the
  outbox and becomes a visible dead letter at the retry ceiling.

## Rollback

The rollout is additive. Stop the projector and roll back the application image;
do not delete claim tables or revisions. Existing finance tables and artifacts
remain authoritative for the old application version. Restore the database only
for a verified database-level incident, using the standard restore rehearsal.
