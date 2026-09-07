# StrategyOS operating guide

## Local development

From the repository root, use Python 3.11 or later. CI currently selects Python 3.12. Keep one environment, `.venv`:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e . pytest
.venv/bin/python scripts/test.py -q
.venv/bin/python -m uvicorn strategyos_mvp.api:app --host 127.0.0.1 --port 8000
```

Install local OCR tools for complete ingestion tests: Poppler and Tesseract on Linux; the code also supports the macOS Vision path. Provider-backed answers require an explicitly enabled provider and approved external-use policy. The source-only local startup is a developer mode, not a production security configuration.

The default demo source root is `data/demo/01_Synthetic_Dataset`; the corresponding `STRATEGYOS_POC_ROOT` defaults to `data/demo`. `STRATEGYOS_SOURCE_DATASET` overrides the selected dataset. `STRATEGYOS_WORKSPACE_ROOT` defaults to the parent workspace, and `STRATEGYOS_OUTPUT_ROOT` defaults to its `outputs` directory. Hosted deployments supply explicit paths. Do not use a dated desktop folder as runtime configuration.

## Tests and release evidence

`make test` runs the full portable suite through `scripts/test.py`. The runner removes inherited application/provider credentials and service configuration, creates a disposable workspace and routes general regression tests to the fixed finance fixture. Enrichment tests explicitly use the canonical enriched dataset; POC-2 accounting uses its dedicated fixture. Missing mandatory enrichment inputs cause failures, not silent successes.

For a log and machine-readable result:

```sh
.venv/bin/python scripts/test.py -q --junitxml=outputs/pytest.xml
```

Tests requiring live Postgres/Neo4j/other services remain explicit integration work. Use `scripts/test.py --services` with `STRATEGYOS_POSTGRES_E2E_DATABASE_URL`, `STRATEGYOS_NEO4J_E2E_URI`, `STRATEGYOS_NEO4J_E2E_USER` and `STRATEGYOS_NEO4J_E2E_PASSWORD` pointing at disposable proof services. Without `--services`, the runner deliberately strips them. `make postgres-proof` requires `STRATEGYOS_POSTGRES_E2E_DATABASE_URL` and truncates its dedicated proof tables. Never point that target at a business database.

Unit/portable success is not a factual assistant evaluation, immutable-board proof, production capacity result or compliance certification. Record skipped tests and run the acceptance gates in [requirements.md](requirements.md). The current consolidation results are stored under `docs/assessment/evidence`.

## Release contract

Use `main` as the application source. Validate the exact commit, then record commit SHA, image digest, schema identity, source-pack hash, selected run ID, approval state, provider/policy configuration and acceptance results. Reprocessing an enriched pack is a separate operator action; moving its local source files does not promote a new live run or approve findings.

The GitHub CI workflow runs tests, validates Compose and builds an image. The deploy workflow is manually dispatched and environment scoped. The branch-deploy workflow is a temporary preview tool, not an alternative release authority. See [deploy/README.md](../deploy/README.md) for commands and environment contracts.

The preview now selects an approved, completed synthetic source run. Run `deploy/scripts/record_release.py` on the Docker host after health checks to verify source and image/schema identity; the deployment runbook gives the preview command. The [release receipt](assessment/evidence/preview-release.json) and [validation](assessment/validation.md) supersede the original assessment observations. Production and actual ERP/treasury/calendar connections remain outside this remediation deployment.

## State and cleanup policy

Keep source, current requirements, stable fixtures, required build inputs and current evidence. Generated screenshots, one-off render output, failed test workspaces, stale run pointers, duplicate environments and superseded plans do not belong in source control. History belongs in Git, with stable requirement/gap IDs instead of duplicate dated “canonical” documents.

Local runtime source packs and persisted application state are retained because they may contain unique user work and path-bearing records. Credentials are stored only in ignored private/deployment configuration. Final presentations/video assets are separate deliverables and do not define application behavior.

Consolidation removals and moves are listed in [cleanup-manifest.json](maintenance/cleanup-manifest.json). Obsolete files were removed from the active workspace into a recovery folder in the user's Trash. The 7.4 GiB server-image recovery archive was permanently deleted at the user's explicit request; [its receipt](maintenance/deleted-recovery-archive.json) records that exception. Do not mistake those removed image copies for database backups.

## Remaining operational acceptance

Validate SSO and tenant/BU/data-source authorization, logout revocation, immutable board publication, ingress/TLS/private service boundaries, provider egress and inference audit. Define owner-approved retention, RPO/RTO and SLOs. Exercise restore of database, uploaded source files, object storage and selected run before claiming recoverability. A script that rolls back an application image does not establish a compatible data restore.

### Local semantic search

The release image includes the pinned FastEmbed search extra. Provision the pinned
E5 small model with `python scripts/provision_embeddings.py --destination PATH`,
then set `STRATEGYOS_EMBEDDING_MODEL_PATH` to that readable runtime directory.
Runtime validates the model identity and every file hash and performs no downloads.
An unset path retains the explicitly labelled legacy lexical mode. A configured
but missing or changed model fails; it never substitutes another model.

Index the selected source pack through its governed processing workflow to populate the separate 384-dimensional
collection with exact workbook-row, PDF-page and Office/text citations. Indexing is resumable and excludes evaluator questions; a restart does not require rebuilding unchanged points. Run and tenant filters
apply before search. Source indexing rejects changed files and oversized packs;
its readiness is recorded in the run. The English/Arabic synthetic retrieval gate
is separate from factual answer quality and business approval.

### Dimensional plan import preview

The first dimensional increment is a read-only operator tool, separate from live
run selection and the executive UI. It evaluates one explicitly supplied plan
version and one completed-period actual snapshot. It does not persist/ratify plans,
verify the authority of an imported approver, or publish findings to the application.
Run the portable synthetic example from the repository root:

```sh
.venv/bin/python -m strategyos_mvp.dimensional_plan \
  --plan tests/fixtures/dimensional_plan/plan.json \
  --actuals tests/fixtures/dimensional_plan/actuals.json \
  --source-root tests/fixtures/dimensional_plan \
  --company-id synthetic-company \
  --as-of 2026-06-30
```

Output is JSON on stdout; invalid input exits 2 without a partial result. The
fixture is explicitly proposed synthetic intent, not a real ratification. Its
regional cell misses by 60 SAR while an institutional cell exceeds by 60 SAR;
the aggregate remains on plan and `offset_detected` is true.

The example files specify the import schema. Dimensions and member vocabularies
are configured; every tuple must contain the exact configured dimension keys.
Each additive metric declares its unit, direction, parent planned total and absolute
rollup tolerance. Each cell declares its owner, target, absolute tolerance and
source path/locator/hash. Cell targets must exactly reconcile to the metric total.
Use decimal strings or integers, not floating-point amounts. Currency is part of
the explicit unit; no FX conversion or non-additive aggregation is inferred.

Actuals carry company, period, revision, recorded date and `kind: actual`. Pre-aggregate
source detail to one observation per tuple; duplicates fail. Missing or null actuals
remain missing; known dimension tuples without plan cells are disclosed and block
complete rollups. Unknown members, units, companies and periods fail validation.
Periods must be complete at `as_of`, with no future actual or ratification dates.
Plan effective dates cover the reporting period; historical evaluation is allowed.
A zero target has no percentage variance; signed differences remain available.

Evidence must be a hash-matching local file within `--source-root`; absolute paths,
escaping symlinks and changed bytes fail. A matching hash verifies artifact integrity,
not that a locator's value is semantically correct or that its author could ratify.
Run only on authorized operator inputs: this CLI is not an authenticated multi-tenant
API and must not be exposed directly as a service. It does not apply the application's
source-role classification or retrieval policy. All outputs retain the imported
approval status and explicitly mark authorization as unverified. Plan, actual and
analysis hashes identify the evaluated payloads; durable immutable storage remains
future work. The operator must preserve the source snapshots for reproducibility.

The module performs no network calls or writes. Targeted acceptance:

```sh
.venv/bin/python scripts/test.py -q tests/test_dimensional_plan.py tests/test_strategy_compiler.py tests/test_metric_claim_contracts.py
```

### Authenticated dimensional Intent workflow

The next local increment adds `/api/intent/dimensional` to the application. It uses
PostgreSQL exclusively; no file or in-memory fallback is used when persistence is
unavailable. The hosted preview migration job installs its additive schema before startup and
includes it in the release fingerprint. API credentials receive only SELECT/INSERT
on the tenant-isolated Intent tables; worker/projector roles receive no access.
For a standalone operator environment with migration-owner authority:

```sh
.venv/bin/python -m strategyos_mvp.dimensional_intent_store --initialize
```

This command is idempotent and does not alter existing run or board tables. It has
not been executed against a business database as part of this implementation.
The packaged SQL is `strategyos_mvp/sql/dimensional_intent.sql`. New plan versions,
actual revisions, permission events, ratifications and analyses are append-only;
triggers reject UPDATE, DELETE and TRUNCATE. Normal database backup/recovery and
least-privilege database administration remain necessary.

The initial API is whole-company scoped: `company_id` must equal the authenticated
tenant/deployment identifier. BU users, anonymous/auth-disabled callers, generic
system identities and demonstration-role credentials are denied. Real operator,
reviewer, executive and tenant-administrator identities have the explicitly listed
rights below; being an executive alone does not confer ratification permission.

| Method and path after `/api/intent/dimensional` | Actor | Body / result |
|---|---|---|
| `GET /catalog?offset=0&limit=25` | Allowed whole-company reader | Eligible plan/actual summaries, pagination and caller capabilities |
| `GET /plans/{plan_id}/versions/{version}/evidence?cell_id=...` | Allowed whole-company reader | Hash-checked source attachment for pre-ratification review |
| `POST /plans` | Operator, tenant operator or tenant admin | `{source_pack_id, plan}`; returns immutable proposal, digest and importer |
| `GET /plans/{plan_id}/versions/{version}` | Allowed whole-company reader | Original payload plus separate `governance_status` and ratification receipt |
| `GET /plans/{plan_id}/ratifier?subject=...` | Tenant admin | Current grant revision, or disabled/revision 0 |
| `PUT /plans/{plan_id}/ratifier` | Tenant admin | `{subject, enabled, expected_revision}`; appends grant/revocation event |
| `POST /plans/{plan_id}/versions/{version}/ratify` | Granted executive, reviewer or tenant admin | `{expected_digest, note}`; note is 20–2,000 characters |
| `POST /actuals` | Operator, tenant operator or tenant admin | `{source_pack_id, actuals}`; returns immutable actual revision |
| `GET /actuals/{revision}` | Allowed whole-company reader | Original actual payload and importer |
| `POST /analyses` | Allowed whole-company reader | `{plan_id, plan_version, actual_revision, as_of}`; calculates and persists a snapshot |
| `GET /analyses/{analysis_hash}` | Allowed whole-company reader | Exact saved analysis; does not recalculate |
| `GET /analyses/{analysis_hash}/evidence?cell_id=...&side=plan` | Allowed whole-company reader | Hash-checked source attachment; use `side=actuals` for actual evidence |

Allowed whole-company readers are operator, tenant operator, reviewer, auditor,
executive and tenant admin. They see eligible tenant-wide evidence, so this API
must not be used to serve restricted BU/persona slices. Cell owners are business
metadata, not access grants. The plan-specific ratifier register is an explicit
approval policy surfaced in the Intent Vault; integration into the existing visual Authority Matrix
and finer permissions are still outstanding.

Workflow:

1. Stage evidence using the existing source-pack intake. The API reads that pack's
   registered server metadata and `raw` directory; no request can supply a root.
   Use relative raw-pack source paths in plan/actual references. Eligible registered
   current/historical sources are hash checked. Restricted, evaluator, control,
   quarantined, unsupported and symlinked references fail. A historical disposition
   stays historical; classification is not a finance correctness certificate.
2. Import the plan with `status: proposed` and no ratification fields. Imports start
   at version 1 and advance consecutively. Identical retries return the original
   record; changed content under the same version conflicts. Partially overlapping
   reporting periods within a plan family are rejected; exact-period amendments
   and disjoint periods are supported. Plan IDs and actual revision IDs use at most
   160 letters/digits/dots/underscores/hyphens and begin with a letter or digit.
3. A tenant administrator grants the exact authenticated `subject` permission to
   ratify that plan. Administrators cannot grant themselves permission; an importer
   cannot ratify their own version, even if another administrator grants them rights.
   Grant edits use optimistic revisions; revoked grants prevent future approvals.
4. The designated ratifier reads the proposed version and its evidence, then submits
   its digest and review note. The server records the identity, UTC approval time,
   grant revision and exact plan digest. Submitted fields cannot spoof these values.
   Imported files never establish these rights. A newer ratification prevents later
   ratification of an older version; identical approval retries do not duplicate it.
5. Import completed-period actuals (same schema as the operator CLI). They may come
   from another owned source pack. Actual imports are immutable by revision and
   duplicate tuples fail; plan-specific dimension/unit matching happens at analysis.
6. Create an analysis with an explicit version/revision and UTC calendar `as_of`.
   The plan must have been ratified, and actuals imported, by that day. Future dates
   fail. A newer ratified version for the same period blocks obsolete comparisons.
   Analysis and ratification share a transaction lock to avoid a comparator race.
   Missing/unplanned actuals remain visibly incomplete rather than fabricated totals.
7. Read the saved hash to recover the same figures after later source/plan changes.
   Source eligibility is rechecked; revocation blocks access. Saved figures do not
   require unchanged live bytes, but downloading their evidence does. Retain the
   original source pack and metadata; missing pack metadata blocks access.

All amounts remain decimal strings. Requests and stored snapshots have a 2 MB
limit. Cookie-authenticated writes require a matching Origin. Responses are private
and non-cacheable. An approved analysis distinguishes authenticated ratification
from artifact hash assurance: cited values are not automatically semantically
verified. The existing `/plan` page is now the Intent Vault: choose a version,
review its target/evidence table, ratify with a review note when authorized, choose
an actual snapshot and calculate drift. Saved results have private reopen links.
Operators can expand the JSON import controls; tenant administrators can manage
plan-specific ratifier permissions. The retired `/api/plan/latest` route redirects
to the authenticated catalog. No current-run pointer, graph projection, board
snapshot or external mailbox is changed by this workflow.

Run the isolated service proof (requires local `initdb` and `pg_ctl`):

```sh
.venv/bin/python scripts/test.py -q tests/test_dimensional_intent.py tests/test_dimensional_plan.py
```

The tests create and destroy their own socket-only PostgreSQL cluster and databases;
they never use an existing database or inherited credentials. On machines without
those binaries this proof is explicitly skipped, not counted as passing.

### Incremental delivery policy

Ship end-to-end-ready chunks to the existing preview (`https://new.strategyos.live`)
as part of development. Integrate with its latest deployed revision, run the release
checks, use the migration/runtime separation and verify the hosted workflow. Do not
leave a verified chunk local-only unless a concrete deployment blocker remains.

Intent evidence now rechecks the current registered database source policy on every
read, including storage rights, allowed roles/purposes and whole-company scope.
Downloads additionally require export permission. File metadata alone cannot override
a revoked source policy. This does not create common-ledger claim revisions from the
manually imported dimensional values; exact value/locator certification remains open.
