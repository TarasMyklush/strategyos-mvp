# Common source and claim model

This document describes the contract implemented by `source_claims.py`,
`claim_store.py` and migration `0001_common_source_claim.sql`.

## Authority boundary

PostgreSQL is the source/claim authority. Neo4j, Qdrant, caches, agent context and
UI payloads are projections. They may not broaden access, choose a different
revision or silently change a claim's meaning.

The current finance calculation remains the ingestion projection, while its
headline components are materialized into an immutable run snapshot. Authenticated
CEO and Hermes reads remove the legacy headline values and repopulate them only
from policy-eligible snapshot claims. A missing snapshot, policy or reconciliation
blocks the authenticated briefing with an explicit unavailable response; it does
not return pre-cutover values. Whole-run source authorization additionally
protects legacy narrative and trend siblings. A partially authorized user must
use claim-level reads rather than receive a partially redacted bulk view.

The finance display contract validates each component's metric, actual/plan
kind, unit, currency and finite positive scale. Competing component claims or
misaligned actual/plan periods make the briefing unavailable rather than using
last-write-wins or legacy values. The existing SAR-specific finance presentation
rejects other reporting currencies; the independent claim workspace retains and
displays their native currency and scale without conversion or relabelling.

## Independent dimensions

Source origin, capture channel, claim kind, production method, traceability,
validation and review are independent:

- origin: internal system, public web, licensed external, correspondence, unknown;
- capture: upload, folder, API, email, chat, manual entry, unknown;
- kind: actual, plan, forecast, assumption, reported claim, unknown;
- production: imported, human-entered, extracted, calculated;
- assessment: evidence-bearing review events with actor, rule version, time,
  rationale and optional scope.

Paid, internal and executive-authored sources are not automatically verified.
Imported source text is never an instruction to the runtime. A scenario acceptance
does not turn a forecast into an actual.
Calculated actuals cannot take plan, forecast, assumption or reported inputs.
Licensed-source registration requires both provider identity and a license-policy
reference, including direct repository callers that bypass the upload UI.

## Identity and revisions

Evidence bytes are deduplicated as artifacts. Evidence occurrences retain source,
native version, URI/message identity, author, timestamps and access context, so
identical bytes received under different rights do not collapse their provenance.

A claim family is a stable assertion lane. Its identity includes tenant, assertion
namespace, claim kind, subject, metric, dimensions, period and scenario. This lets
actual and plan coexist and prevents one provider from overwriting another. A
changed value creates an immutable numbered revision. Replaying the same
fingerprint is idempotent.

Calculated claims require a formula key/version and exact input revision IDs.
Dependencies and evidence links allow provenance reconstruction. Projection work
is committed through a transactional outbox.
Supported calculation contracts are executed at both write and eligible-read
boundaries. Version 1 supports identity, same-scope monetary sums and
EBITDA/revenue margin. Inputs must have compatible claim kinds, units, currencies
and periods; ratios cannot be summed, duplicate candidate metrics cannot be
treated as additive corroboration, and no implicit FX is performed. The stored
result must equal the deterministic result. Unsupported formulas are ineligible
until an executable contract is introduced; a formula label alone is not proof.
Margin formula version 1 uses Decimal arithmetic and half-even rounding to 12
decimal places of percentage. Historical ratio representations are checked at
that same explicit precision; monetary inputs are not rounded by this contract.

## Access and selection

Every source has a versioned policy covering roles, purposes, business units,
export, quotation and external-model use. Every contributing source policy is
intersected, including sources inherited through calculated-claim dependencies.
Missing policy fails closed.
Quotation is an explicit use purpose with a separate permission. Query purpose
must equal authenticated context purpose, and repository tenant normalization
must not replace a caller's tenant with a requested tenant.

Authenticated canonical Hermes evidence is checked for external-model permission
before source retrieval or transport. Application-level provider enablement is
not source consent. Denied or unavailable policy returns an explicit local
policy response without sending evidence. The same gate applies to public packets,
legacy Hermes summaries and twin reasoning. Legacy twins without a governed
context use their local fallback, not an implicitly authorized model call.

A claim query explicitly states tenant, metric, requested kinds, business unit,
scenario, purpose and as-of timestamp. Selection never substitutes a forecast for
an actual. Future, stale, untraceable, retracted, superseded and unauthorized
revisions are not eligible. The API returns a UI-ready provenance envelope rather
than asking each screen to infer units or meaning from prose.
Current lifecycle withdrawal also invalidates exact-input descendants and cannot
be bypassed by requesting a historical analysis timestamp. Historical snapshots
retain their membership on replay; a new analysis requires a new snapshot.
Whole-run authorization also follows the snapshot's exact input lineage across
ingestion batches. An input's source restriction or current lifecycle withdrawal
blocks legacy bulk views and model transmission, even when the run's own primary
source still permits access. It does not attempt to redact free-form prose.

Semantic search ranks up to 200 local-vector candidate IDs, then reauthorizes
those exact revisions in PostgreSQL. Stale candidates never substitute a newer
revision, and projection text is never returned directly as evidence. The
independent `/claims` workspace uses these same query contracts and distinguishes
traceability from independent review.

## Ingestion behavior

Source packs carry an explicit source contract. Capture method comes from the real
intake path; origin remains unknown until an authenticated operator confirms it.
Licensed sources require provider and license-policy references. Source identity
participates in deterministic pack identity so identical content from different
origins can coexist.

Trial-balance actuals, CFO cash forecasts, amount-bearing finance transactions and
CEO KPI actual/plan components write claims with source occurrence links. EBITDA
margin is a calculated claim whose exact EBITDA and revenue revision IDs are
recorded. Each run creates an immutable analysis snapshot and a persisted
record-count/amount reconciliation. Invalid or unresolved rows are quarantined as
backfill exceptions; they are not silently coerced.

Historical materialization is preview-first through `python -m
strategyos_mvp.claim_backfill --run-id <uuid>`. The command writes only when
`--apply` is provided, takes a run-specific advisory lock, creates conservative
legacy finance-source policy only for the known finance-dataset intake, and is
idempotent on replay.

## Projection delivery

### Scoped forecast review

`POST /api/claims/{revision_id}/forecast-review` records an authenticated
executive/reviewer/tenant-admin decision for one exact forecast revision and
one explicitly named analysis scope. Source operations permissions are checked
again in the same transaction. The actor and assessment time come from the
runtime, not the request payload. Revised, withdrawn or expired forecasts cannot
receive new acceptance. Retries use an actor-bound command fingerprint and do
not create duplicate reviews or projection events.

Acceptance never changes the claim kind. A missing review deadline is recorded
as missing, and that forecast is ineligible for accepted-only analysis. A passed
deadline, different scope, conflicting review, or future review likewise cannot
satisfy the query. Both exact and semantic queries accept the same explicit
`forecast_scope_key` and `require_forecast_acceptance` contract. Inspection can
still show an unreviewed forecast with its qualifications. Review events enqueue
the affected claim and calculated descendants for projection refresh.

The evidence workspace offers compact review controls only when the current
source policy and authenticated role permit review. Recording is local to the
ledger: no assignment, email, external delivery or source-system update occurs.

### Explicit mixed-workbook interpretation

Operators can use `/claims/intake` and `POST /api/claims/intake/workbook` to preview
an explicit versioned mapping before recording claims. The workbook's SHA-256
must match an existing evidence occurrence in the authenticated tenant. Neither
the filename nor neighboring cells confer actual/forecast semantics.

Mappings specify each value column's metric, unit, scale, currency and period,
and either a fixed claim kind or a per-row kind column. Forecasts require an
attributable author. Ambiguous kinds, invalid numbers and unresolved periods
are quarantined as unknown; missing values and unresolved subjects receive
explicit no-claim dispositions. Original worksheet row/column locators survive
internal blank rows. Batches are bounded to 500 mapped cells and 5 MiB uploads.

Apply writes claims, evidence links, projection outbox events and an interpretation
receipt in one transaction. Any failure rolls back the batch. The receipt key
contains tenant, evidence occurrence, artifact digest and the complete mapping
contract, making retries idempotent. Current source permissions are checked
before both preview and replay. A new mapping version produces new revisions,
not an overwrite of historical interpretations. Competing rows are rejected
until the operator resolves their semantics. No interpretation self-verifies,
changes an approved snapshot, or authorizes outbound delivery.

The UI clears stale results when inputs change and disables apply until a fresh
preview succeeds. It renders source-provided values as text, never markup.

The claim transaction writes graph, vector and cache work to an outbox. The
`strategyos-claim-projector` service leases rows with `FOR UPDATE SKIP LOCKED`,
commits the lease before external I/O, and acknowledges only its own lease. Failed
delivery uses bounded exponential retry and becomes a visible dead letter after
the attempt ceiling.

- PostgreSQL's projection cache stores the provenance envelope for fast internal
  reads; it is not a second authority.
- Neo4j receives claim, subject, metric, source and calculated-from relationships.
- Qdrant receives a policy-tagged semantic projection only when the pinned local
  embedding model is configured.

Projection health fails on dead letters or stale leases. Authorization and
revision selection always occur in PostgreSQL before any projection is returned
to a user or model.

## Operational migration

Migrations are ordered, checksummed and serialized with a PostgreSQL advisory
transaction lock. A changed already-applied migration fails startup rather than
silently drifting the schema. Production rollout must be additive, preview-first,
and backed by a restore rehearsal and data reconciliation report.

The runtime image copies both `schema.sql` and the immutable migration directory.
The API, workers and projector therefore converge on the same checksummed schema
at startup rather than depending on an out-of-band migration image.

The legacy source policy preserves current authenticated read/export roles but
explicitly denies external-model use until a data owner authorizes that purpose.
This avoids silently treating existing application-level model enablement as
source-level consent.
