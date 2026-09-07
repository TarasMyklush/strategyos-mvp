# Preview migration/runtime separation

The preview deployment uses four database authority levels:

- `strategyos-migrate`: an explicit, one-shot deployment container, using the
  existing migration account. It applies ordered migrations, prepares the four
  existing auxiliary schemas, records a schema fingerprint, and provisions the
  three preview runtime roles. It does not mount application datasets or the Docker
  socket, has a read-only root filesystem and drops Linux capabilities.
- API: `strategyos_preview_runtime`, marked with request scope. Each pooled
  checkout binds the verified tenant UUID; governed source-and-claim tables use
  PostgreSQL row policies so an omitted tenant predicate cannot cross tenants.
- Background worker: `strategyos_preview_worker`, marked with worker scope. It
  may process explicitly queued work across tenants and is the only runtime
  identity allowed to create governed source/claim rows without request context.
- Claim projector: `strategyos_preview_projector`, marked with projector scope.
  It can read claim lineage/source policy, lease/update the projection outbox and
  maintain projection cache. It cannot read legacy finance tables, delete claims,
  or create business claims.

All three runtime roles lack schema ownership, privileged role membership,
CREATE, TEMP, role administration, replication and RLS-bypass capability. Each
has exactly one no-login scope membership used by the RLS policy; PostgreSQL's
constant-time membership check avoids a catalogue lookup for every scanned row.
Startup verifies the prepared fingerprint, exact role marker and sole scope
membership, and refuses DDL. None can
edit migration history/schema contracts, rewrite immutable claim revisions or
assessments, or truncate tables.

The migration job runs before the new application starts. It writes a private,
0600 runtime connection file outside the source deployment directory:
`/opt/strategyos-branch/runtime-database/runtime.env`. Retries preserve its secret.
Do not print this file or put it in Git. The migration connection is not passed
to application containers. The job writes three distinct runtime connection
strings. Final composed configuration is checked after all provider overlays:
API must use request scope, the worker worker scope and the projector projector
scope; all target the same database through different usernames in verify mode.

Each managed role is marked explicitly. Provisioning refuses an existing role
with an unrelated marker instead of taking it over. It revokes PUBLIC schema
creation and database temporary-table privileges in the **preview database**;
the migration owner retains its ownership authority. Migration 0014 applies
tenant RLS to the common governed source-and-claim ledger: evidence, policies,
registration versions, claim families/revisions/lineage/assessments, snapshots,
projection state, receipts, exceptions, reconciliations and priority policy.
Claim eligibility and source-use permission remain repository responsibilities
above this database isolation layer. This does not claim RLS on every legacy
application table.

Production configuration is unchanged. Preview requires the exact deployment
directory/project and a release image; it cannot fall back to owner-mode local
builds. If migration, role verification or startup fails, the preview fail-closed
recovery procedure applies. No historical business claim is reclassified by this
operation, and no source rights, approval policy or outbound connector is enabled.

Before release, run the non-owner PostgreSQL proofs, complete service suite,
effective Compose checks and online regression suite. Isolated proofs alone do
not establish that the live deployment has switched roles.

## Request context at the pool boundary

In verified runtime mode, every pooled connection checkout binds the middleware's
verified tenant reference and canonical UUID. A UUID cannot be interpreted as
another tenant's slug. The context survives application commits and rollbacks,
but is explicitly cleared before the connection returns to the pool. Failed
binding or cleanup discards the connection. Missing request context receives an
empty scope, not the previously connected tenant or a default executive identity.

`test_database_tenant_context_postgres_e2e.py` proves pool cleanup/rebinding with
a real single-slot pool. `test_claim_row_level_security_postgres_e2e.py` proves
the real governed-table inventory: reads intentionally omit tenant WHERE clauses,
blank request context sees no rows, workers can see queued cross-tenant work, and
projectors cannot read finance facts or mutate claims. The proof asserts the
exact RLS table inventory so a newly added governed table cannot silently escape
review.
