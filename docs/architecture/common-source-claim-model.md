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
