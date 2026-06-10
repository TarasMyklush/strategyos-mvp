# StrategyOS Cloud-Agnostic Deployment

This deployment package is designed for Hetzner first, but keeps the runtime portable to any VM, Docker host, or Kubernetes cluster. The same compose stack is now verified locally as the as-built baseline for broader testing.

## Stack

- StrategyOS API container
- Postgres for run metadata, approvals, artifacts, and LangGraph checkpoint storage
- Redis for LangGraph/runtime queues and cache
- Neo4j for the production knowledge graph
- Qdrant for persistent vector retrieval over StrategyOS run data
- MinIO for local S3-compatible object storage, replaceable with Hetzner Object Storage
- Caddy for TLS/reverse proxy
- Linux OCR through `pdftoppm` plus `tesseract`
- Pinned OCR/runtime packages with health-reportable version checks (`ca-certificates`, `curl`, `poppler-utils`, `tesseract-ocr`, `tesseract-ocr-eng`)

## As-Built Local Broader-Testing Baseline

- Compose project: `strategyos`
- Verified running services: `strategyos-api`, `strategyos-idp`, `postgres`, `redis`, `neo4j`, `qdrant`, `minio`, `caddy`
- Verified healthy services in the current local stack: `strategyos-api`, `strategyos-idp`, `postgres`, `redis`, `neo4j`
- Local published ports in the verified environment:
  - Caddy HTTP: `http://localhost:8088`
  - Caddy HTTPS: `https://localhost:8444`
  - Local identity provider token/introspection boundary: `http://localhost:8089`
- Runtime boundary verified in local env:
  - `STRATEGYOS_API_AUTH_ENABLED=true`
  - `STRATEGYOS_IDP_ENABLED=true`
  - `STRATEGYOS_PUBLIC_HEALTH_ENABLED=false`
  - `STRATEGYOS_REQUIRE_HUMAN_REVIEW=true`
- Recovery proof directory: `artifacts/recovery-proof-20260604T174300Z`

## Verified Progress For Broader Testing

- Compose runtime is up locally and being used as the active proof environment.
- Provider-backed local identity boundary is in place for operator and reviewer flows.
- Neo4j sync/query proof is complete through `/data/status` with ready-state graph counts and a sample live relation.
- Qdrant runtime proof is complete through `/data/status` plus vector search against current-run findings.
- Recovery proof is complete: backup, volume restore, stack restart, latest-run preservation, and governed rerun evidence are captured under `artifacts/recovery-proof-20260604T174300Z`.
- Recovery comparison result is `match=True` for the preserved latest completed run before and after restore.
- Smoke rerun result after restore is recorded as completed with approval, `data_status=ready`, `neo4j_status=ready`, and `qdrant_status=ready`.

## Local / Hetzner VM Pilot

1. Generate split local config and secret files:

```bash
deploy/scripts/generate_env.sh
```

2. Review `deploy/.env` for local defaults and `deploy/.env.secrets` for injected secrets. Do not commit either file.
3. Mount or copy the source dataset into the `strategyos-workspace` volume path, or stage a source pack through the folder/upload intake endpoints. Source-pack intake and validation are implemented; the fixed dataset path remains the canonical fixture/regression path.
4. Start the stack:

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env --env-file deploy/.env.secrets up -d --build
```

5. Request a local identity token for the protected local boundary:

```bash
TOKEN=$(curl -s http://localhost:8089/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data "grant_type=password&client_id=$(grep '^STRATEGYOS_IDP_CLIENT_ID=' deploy/.env | cut -d= -f2-)&client_secret=$(grep '^STRATEGYOS_IDP_CLIENT_SECRET=' deploy/.env.secrets | cut -d= -f2-)&username=$(grep '^STRATEGYOS_IDP_OPERATOR_USERNAME=' deploy/.env | cut -d= -f2-)&password=$(grep '^STRATEGYOS_IDP_OPERATOR_PASSWORD=' deploy/.env.secrets | cut -d= -f2-)" \
  | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
```

6. Check liveness and readiness through Caddy:

```bash
curl http://localhost:${STRATEGYOS_HTTP_PORT:-80}/health/live \
  -H "Authorization: Bearer ${TOKEN}"

curl http://localhost:${STRATEGYOS_HTTP_PORT:-80}/health/ready \
  -H "Authorization: Bearer ${TOKEN}"

curl http://localhost:${STRATEGYOS_HTTP_PORT:-80}/health/dependencies \
  -H "Authorization: Bearer ${TOKEN}"
```

7. Run the workflow:

```bash
curl -X POST http://localhost:${STRATEGYOS_HTTP_PORT:-80}/runs \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"skip_prepare": true, "sync_artifacts": true}'
```

## Local Postgres Proof Target

`make postgres-proof` runs the governed source-pack pause/approve/resume e2e against Postgres. It intentionally fails fast unless `STRATEGYOS_POSTGRES_E2E_DATABASE_URL` is set, because the test truncates all `strategyos_*` tables before and after the proof. Use a dedicated disposable proof database, for example:

```bash
export STRATEGYOS_POSTGRES_E2E_DATABASE_URL="postgresql://strategyos:strategyos@localhost:55432/strategyos_proof"
make postgres-proof
```

This target proves persisted run/checkpoint/approval behavior. For LangGraph proof, add `STRATEGYOS_RUNTIME_BACKEND=langgraph`; the test asserts `runtime.actual_backend = "langgraph"` and `runtime.fallback_used = false` for the created run.

Latest local proof recorded on 2026-06-10:
- `make postgres-proof` with `STRATEGYOS_RUNTIME_BACKEND=langgraph`: `1 passed, 0 skipped`
- proof pack: `../outputs/StrategyOS Runtime Proofs/20260610T184252Z-langgraph-postgres/`
- direct proof run: `runtime.actual_backend=langgraph`, `runtime.fallback_used=false`, `state_store.status=persisted`
- boundary: Neo4j and Qdrant were not configured for this proof, so graph/vector sync remain covered only by the older broader-testing proof until re-run with those services active.

## Hetzner Notes

 - Use a dedicated private network and firewall rules for Postgres, Redis, Neo4j, Qdrant, and MinIO.
- Expose only Caddy ports `80/443` publicly.
- For production object storage, replace MinIO env values with Hetzner Object Storage S3 endpoint and credentials.
- Keep `STRATEGYOS_API_AUTH_ENABLED=true` and `STRATEGYOS_REQUIRE_HUMAN_REVIEW=true` for the controlled pilot boundary.
- Use distinct operator and reviewer identities; do not reuse local defaults outside disposable environments.
- Use Hetzner volume snapshots plus S3-compatible backup for Postgres, Neo4j, and evidence artifacts.

## Controlled Pilot Readiness Contract

### Liveness

- `GET /health/live`
- Returns process-level liveness only.
- Public access is allowed only when `STRATEGYOS_PUBLIC_HEALTH_ENABLED=true`.
- If `STRATEGYOS_PUBLIC_HEALTH_ENABLED=false`, an operator identity token is required.

### Readiness

- `GET /health/ready`
- Requires a reviewer or operator identity token when `STRATEGYOS_API_AUTH_ENABLED=true`.
- Performs real checks for:
  - Postgres query execution
  - Redis ping
  - authenticated Neo4j Cypher probe (`RETURN 1`)
  - object-store bucket access
  - writable output root
  - pinned OCR/runtime dependency package versions plus reachable `tesseract` / `pdftoppm`
  - auth boundary config
  - governed runtime / human-review config
- Returns `status: ok | degraded | failed`.
- `failed` responses return HTTP 503.

### Runtime dependency health

- `GET /health/dependencies`
- Requires a reviewer or operator identity token when `STRATEGYOS_API_AUTH_ENABLED=true`.
- Verifies the pinned runtime dependency contract for:
  - `ca-certificates`
  - `curl`
  - `poppler-utils` / `pdftoppm`
  - `tesseract-ocr` / `tesseract`
  - `tesseract-ocr-eng` with `eng` language availability
- Reports expected version, installed package version, reachable binary path, and binary-reported version where applicable.
- Returns HTTP 503 if any pinned runtime dependency is missing or version-drifted.

### Required environment boundary

- `STRATEGYOS_API_AUTH_ENABLED=true`
- `STRATEGYOS_IDP_ENABLED=true`
- `STRATEGYOS_RUNTIME_DEP_CA_CERTIFICATES_VERSION=20250419`
- `STRATEGYOS_RUNTIME_DEP_CURL_VERSION=8.14.1-2+deb13u3`
- `STRATEGYOS_RUNTIME_DEP_POPPLER_UTILS_VERSION=25.03.0-5+deb13u2`
- `STRATEGYOS_RUNTIME_DEP_TESSERACT_VERSION=5.5.0-1+b1`
- `STRATEGYOS_RUNTIME_DEP_TESSERACT_ENG_VERSION=1:4.1.0-2`
- `STRATEGYOS_IDP_TOKEN_URL=http://strategyos-idp:9000/oauth/token`
- `STRATEGYOS_IDP_INTROSPECTION_URL=http://strategyos-idp:9000/oauth/introspect`
- `STRATEGYOS_IDP_CLIENT_ID=<local identity client id>`
- `STRATEGYOS_IDP_CLIENT_SECRET=<injected secret from deploy/.env.secrets>`
- `STRATEGYOS_IDP_OPERATOR_USERNAME=<operator identity username>`
- `STRATEGYOS_IDP_OPERATOR_PASSWORD=<injected secret from deploy/.env.secrets>`
- `STRATEGYOS_IDP_REVIEWER_USERNAME=<reviewer identity username>`
- `STRATEGYOS_IDP_REVIEWER_PASSWORD=<injected secret from deploy/.env.secrets>`
- `STRATEGYOS_PUBLIC_HEALTH_ENABLED=true|false`
- `STRATEGYOS_REQUIRE_HUMAN_REVIEW=true`

### Secrets and config boundary

- `deploy/.env.example` contains non-secret local defaults only.
- `deploy/.env.secrets.example` defines the required secret injection contract.
- `deploy/scripts/generate_env.sh` creates ignored local files `deploy/.env` and `deploy/.env.secrets` without printing secret values.
- Deployment scripts sync `deploy/.env` and `deploy/.env.secrets` explicitly instead of relying on repo state, and repo sync excludes both files.
- Production secret material should be rendered into `deploy/.env.secrets` by your CI/CD or secret manager at deploy time, not committed into the repo.

This hardens the in-repo pilot runtime/auth boundary only. It adds a provider-backed local identity boundary for the compose stack and does not broaden into host provisioning or external secret managers. That boundary is now part of the verified local as-built state for broader testing.

## Neo4j graph sync proof path

1. Run a governed workflow to produce `StrategyOS Knowledge Graph.json`.
2. Ensure `DATABASE_URL`, `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` are set.
3. The workflow completion path now persists KG nodes/edges to Postgres and then loads the same artifact into Neo4j with a run-scoped uniqueness constraint and indexes.
4. Verify readiness:

```bash
curl http://localhost:${STRATEGYOS_HTTP_PORT:-80}/health/ready \
  -H "Authorization: Bearer ${TOKEN}"
```

5. Verify the latest run graph surface:

```bash
curl http://localhost:${STRATEGYOS_HTTP_PORT:-80}/data/status \
  -H "Authorization: Bearer ${TOKEN}"
```

Expected `neo4j` fields for a loaded run:
- `status: ready`
- `node_count`
- `edge_count`
- `sample_relation` proving live query retrieval from Neo4j

Verified local proof values from `artifacts/recovery-proof-20260604T174300Z`:
- `node_count: 2360`
- `edge_count: 5721`
- `sample_relation.relationship_type: INVOLVES_VENDOR`

## Qdrant vector proof path

1. Ensure `QDRANT_URL` is set and the compose stack is running.
2. Run a governed workflow so findings are persisted with a real `run_id`.
3. Verify the latest run vector status:

```bash
curl http://localhost:${STRATEGYOS_HTTP_PORT:-80}/data/status \
  -H "Authorization: Bearer ${TOKEN}"
```

Expected `qdrant` fields for a loaded run:
- `status: ready`
- `point_count`
- `sample_record`

Verified local proof values from `artifacts/recovery-proof-20260604T174300Z`:
- `collection: strategyos_findings`
- `point_count: 8`
- `sample_record` present for the current-run finding surface

4. Verify retrieval against StrategyOS data:

```bash
curl "http://localhost:${STRATEGYOS_HTTP_PORT:-80}/data/vector-search?query=duplicate%20payment%20invoice" \
  -H "Authorization: Bearer ${TOKEN}"
```

Expected result: the top hit should be the duplicate-payment finding from the current run.

## Recovery Proof Path

The latest verified local recovery proof lives in `artifacts/recovery-proof-20260604T174300Z` and includes:

- `baseline/compose-ps.txt`, `baseline/live.json`, `baseline/ready.json`, `baseline/latest.json`, `baseline/data-status.json`
- volume backup tarballs under `backup/`
- restored-state checks under `restored/`
- governed rerun smoke evidence under `smoke/`

Key proof points:

- baseline latest run remained stable across restore (`restored/comparison.txt` reports `match=True`)
- restored `data/status` remained `ready`
- post-restore smoke rerun completed with approval and preserved Neo4j/Qdrant ready state

## Next Production Hardening

- Add source-pack intake and validation so a user-selected folder with arbitrary filenames can be registered, classified, and readiness-checked before run execution.
- Keep OCR local and wire PDF/image extraction ahead of content-based document-role classification.
- Add additive canonical invoice-header normalization only after source-pack intake is in place; keep current invoice-consuming controls unchanged in that tranche.
- Replace the local identity provider with the production SSO authority before exposing reviewer endpoints.
- Extend the 2026-06-10 LangGraph/Postgres proof to a full active Neo4j/Qdrant/object-store sync proof.
- Add CI/CD and smoke tests for `/health/live`, `/health/ready`, `/runs`, source-pack validation, artifact sync, and citation audit.

## Current Flexible-Invoice Control Constraints

Traceability source: `docs/flexible-invoice-architecture-plan.md`.

- Do not rely on filenames as the routing mechanism for invoice or scan intake.
- Preserve original relative paths as provenance only.
- Report unsupported, ambiguous, or unclassified files in quality output rather than dropping them.
- Keep evidence hashing, OCR, parsing, citation resolution, and quantitative validation inside StrategyOS by default.
- Defer persistence/schema expansion, citation rewiring, and control-consumer migration until source-pack intake plus additive canonical invoice headers are proven.

## Repeatable Hetzner Deployment Scripts

Generate a local env file:

```bash
deploy/scripts/generate_env.sh
```

Bootstrap a clean Ubuntu VM:

```bash
TARGET_HOST=root@YOUR_SERVER_IP deploy/scripts/bootstrap_hetzner.sh
```

Deploy the stack:

```bash
TARGET_HOST=root@YOUR_SERVER_IP deploy/scripts/deploy_stack.sh
```

Sync the synthetic source dataset into the Docker workspace volume:

```bash
TARGET_HOST=root@YOUR_SERVER_IP \
SOURCE_DATASET="/Users/taras/Desktop/Taras/sp soft/Enterprise OS/strategy os/StrategyOS POC/01_Synthetic_Dataset" \
deploy/scripts/sync_source_dataset.sh
```

Check health and run the workflow:

```bash
READINESS_AUTH_HEADER="Authorization: Bearer ${TOKEN}" TARGET_HOST=root@YOUR_SERVER_IP deploy/scripts/check_health.sh
TARGET_HOST=root@YOUR_SERVER_IP deploy/scripts/run_remote_workflow.sh
```

Rollback to the latest pre-deploy backup:

```bash
TARGET_HOST=root@YOUR_SERVER_IP deploy/scripts/rollback_stack.sh
```
