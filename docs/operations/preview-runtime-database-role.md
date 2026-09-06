# Preview migration/runtime separation

The preview deployment uses two database authority levels:

- `strategyos-migrate`: an explicit, one-shot deployment container, using the
  existing migration account. It applies ordered migrations, prepares the four
  existing auxiliary schemas, records a schema fingerprint, and provisions the
  preview runtime role. It does not mount application datasets or the Docker
  socket, has a read-only root filesystem and drops Linux capabilities.
- API, worker and claim projectors: `strategyos_preview_runtime`, with no schema
  ownership, role membership, CREATE, TEMP, role administration, replication or
  RLS-bypass capability. Runtime startup verifies the prepared fingerprint and
  refuses to run DDL. The role cannot edit migration history/schema contracts,
  rewrite claim revisions/assessments/closed board packets, or truncate tables.

The migration job runs before the new application starts. It writes a private,
0600 runtime connection file outside the source deployment directory:
`/opt/strategyos-branch/runtime-database/runtime.env`. Retries preserve its secret.
Do not print this file or put it in Git. The migration connection is not passed
to application containers. Final composed configuration is checked after all
provider overlays, including database target, runtime username, schema mode,
and migration-service isolation.

The managed role is marked explicitly. Provisioning refuses an existing role
with an unrelated marker instead of taking it over. It revokes PUBLIC schema
creation and database temporary-table privileges in the **preview database**;
the migration owner retains its ownership authority. The role receives CRUD on
legacy application tables and narrowed append/read rights for immutable records.
This is not a claim of per-tenant database RLS: request/source authorization
remains in the repositories, and tenant-context RLS is separate remaining work.

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

`test_database_tenant_context_postgres_e2e.py` proves this with a real single-slot
pool, a non-owner runtime account and a synthetic table protected by PostgreSQL
row policies. Reads intentionally omit tenant WHERE clauses, alternate tenants,
and exercise empty context, rollback and cleanup failure. This proves the pool
mechanism, not application-table RLS coverage. Application row policies and
explicit background-job tenant authority remain separate work before enabling
RLS on existing tables; no business table policy is enabled by this change.
