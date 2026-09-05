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

Tests requiring live Postgres/Neo4j/other services remain explicit integration work. Run those directly using their documented opt-in variables and dedicated disposable services; the isolated local runner deliberately strips those variables. `make postgres-proof` requires `STRATEGYOS_POSTGRES_E2E_DATABASE_URL` and truncates its dedicated proof tables. Never point that target at a business database.

Unit/portable success is not a factual assistant evaluation, immutable-board proof, production capacity result or compliance certification. Record skipped tests and run the acceptance gates in [requirements.md](requirements.md). The current consolidation results are stored under `docs/assessment/evidence`.

## Release contract

Use `main` as the application source. Validate the exact commit, then record commit SHA, image digest, schema identity, source-pack hash, selected run ID, approval state, provider/policy configuration and acceptance results. Reprocessing an enriched pack is a separate operator action; moving its local source files does not promote a new live run or approve findings.

The GitHub CI workflow runs tests, validates Compose and builds an image. The deploy workflow is manually dispatched and environment scoped. The branch-deploy workflow is a temporary preview tool, not an alternative release authority. See [deploy/README.md](../deploy/README.md) for commands and environment contracts.

The 5 September assessment found live executive JavaScript matching `c03e958`, but did not attest the whole backend image or runtime configuration. The selected preview run was awaiting review and lacked enriched strategy data. No deployment or run approval was performed during workspace consolidation. Refer to the gap register for current release blockers.

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

Reprocess the approved source pack to populate the separate 384-dimensional
collection with exact workbook-row and PDF-page citations. Run and tenant filters
apply before search. Source indexing rejects changed files and oversized packs;
its readiness is recorded in the run. The English/Arabic synthetic retrieval gate
is separate from factual answer quality and business approval.
