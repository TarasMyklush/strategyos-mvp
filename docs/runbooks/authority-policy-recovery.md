# Recovering an unavailable authority policy

Authority database outages, unreadable saved policy files and ambiguous legacy
tenant filenames deny access. Query endpoints return HTTP 503. They do not
substitute default rights for an unavailable saved policy.

## Database-backed deployments

Restore the configured database connection or its installed driver, then verify
the affected tenant's saved matrix and version through the authenticated
`/authority-matrix` endpoint. Keep the database configured throughout recovery.
Do not disable the database or copy local-file permissions over its policy: a
second store may have different grants or an older revision.

## File-backed deployments

The store uses `STRATEGYOS_AUTHORITY_DATA_DIR`, or the workspace's
`.strategyos_mvp_data/authority` directory. Preserve the damaged file and audit
log. Restore the last verified policy for that exact tenant from backup using an
atomic file replacement. Check both the matrix version and its grants through
the authenticated endpoint before reopening access. Deleting the saved file is
not a policy recovery procedure: a genuinely new tenant receives default rights.

Legacy safe tenant names keep their existing filenames. Other tenant identities
use an `=` prefix followed by SHA-256 of the full UTF-8 tenant identifier. The
prefix keeps this namespace separate from legacy safe names. If an unsafe tenant
has only an old lossy filename, the service refuses to guess ownership. Establish
the owner from the tenant registry and policy audit before restoring that tenant's
policy under its new key. A file that may belong to more than one tenant must not
be copied into multiple tenant stores.

## Citation integrity failures

A source-byte mismatch is handled independently of authority storage. Restore
the original approved artifact or ingest and govern a new source version. Do not
change an old manifest hash merely to make modified bytes appear verified.
