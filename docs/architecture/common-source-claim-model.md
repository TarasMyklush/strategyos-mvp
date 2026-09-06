# Common source and claim model

This document describes the contract implemented by `source_claims.py`,
`claim_store.py` and migration `0001_common_source_claim.sql`.

## Authority boundary

PostgreSQL is the source/claim authority. Neo4j, Qdrant, caches, agent context and
UI payloads are projections. They may not broaden access, choose a different
revision or silently change a claim's meaning.

The current finance read paths remain active while the new tables are populated
as shadow records. A read-path cutover requires reconciliation and cross-surface
parity evidence; adding these tables alone is not authorization to change the CEO
surface or deploy.

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

A claim query explicitly states tenant, metric, requested kinds, business unit,
scenario, purpose and as-of timestamp. Selection never substitutes a forecast for
an actual. Future, stale, untraceable, retracted, superseded and unauthorized
revisions are not eligible. The API returns a UI-ready provenance envelope rather
than asking each screen to infer units or meaning from prose.

## Ingestion behavior

Source packs carry an explicit source contract. Capture method comes from the real
intake path; origin remains unknown until an authenticated operator confirms it.
Licensed sources require provider and license-policy references. Source identity
participates in deterministic pack identity so identical content from different
origins can coexist.

Existing trial-balance actuals and CFO cash-forecast rows shadow-write claims with
their source occurrence links. The old finance projections continue to support
existing consumers during reconciliation.

## Operational migration

Migrations are ordered, checksummed and serialized with a PostgreSQL advisory
transaction lock. A changed already-applied migration fails startup rather than
silently drifting the schema. Production rollout must be additive, preview-first,
and backed by a restore rehearsal and data reconciliation report.

The legacy source policy preserves current authenticated read/export roles but
explicitly denies external-model use until a data owner authorizes that purpose.
This avoids silently treating existing application-level model enablement as
source-level consent.
