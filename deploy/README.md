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
- Repo/deploy tooling now also supports a **proxy-OIDC cutover path** for production-grade human access: trusted edge auth via `oauth2-proxy`, StrategyOS role mapping by email allowlist, and fail-closed deploy validation when that mode is selected.
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

## Optional Hatchet Worker Mode

The default `/runs` path remains synchronous. Hatchet mode is available for long-running run execution, but should be treated as an explicit production-hardening path until a dated Hetzner proof is captured.

1. Generate `deploy/.env` and `deploy/.env.secrets`, then set:

```bash
STRATEGYOS_RUN_EXECUTION_MODE=hatchet
HATCHET_CLIENT_TLS_STRATEGY=none
HATCHET_CLIENT_HOST_PORT=hatchet-lite:7077
```

To include MinIO/S3 artifact sync in a proof run, also set:

```bash
STRATEGYOS_RUN_POLICY=external-approved
STRATEGYOS_APPROVED_EXTERNAL_MODES=object_storage_sync
```

To enable LLM chat for testing, approve model-provider use and keep the API key
only in the secrets file:

```bash
STRATEGYOS_RUN_POLICY=external-approved
STRATEGYOS_APPROVED_EXTERNAL_MODES=model_provider_use
STRATEGYOS_MODEL_PROVIDER_ENABLED=true
STRATEGYOS_LLM_CHAT_ENABLED=true
STRATEGYOS_LLM_PROVIDER=deepseek
STRATEGYOS_LLM_BASE_URL=https://api.deepseek.com
STRATEGYOS_LLM_MODEL=deepseek-v4-pro
```

```bash
# deploy/.env.secrets
STRATEGYOS_LLM_API_KEY=<server-side API key>
```

2. Start the stack with the Hatchet profile:

```bash
docker compose --profile hatchet \
  -f deploy/docker-compose.yml \
  --env-file deploy/.env \
  --env-file deploy/.env.secrets \
  up -d --build
```

3. Bootstrap a token once for the persisted Hatchet tenant, store it in the environment secret manager as `HATCHET_CLIENT_TOKEN`, and restart the API and worker containers. Normal deploys must preserve the Hatchet Postgres and config volumes and must never regenerate the token:

```bash
ALLOW_HATCHET_TOKEN_BOOTSTRAP=true \
COMPOSE_PROFILES=hatchet \
bash deploy/scripts/bootstrap_hatchet_token.sh \
  | gh secret set HATCHET_CLIENT_TOKEN --env hetzner-branch
```

The bootstrap command persists Hatchet's generated cookie, master-encryption, and JWT keysets in the local secrets file, then emits only the client token on stdout; operational messages go to stderr. Hosted deployments must store those four `HATCHET_SERVER_*` values in dedicated environment secrets alongside `HATCHET_CLIENT_TOKEN`. Destructive volume recovery is a separate, explicitly authorized operation and is not part of deployment.

For a non-default Hatchet tenant, set `HATCHET_TENANT_ID` explicitly before running the bootstrap script.

If Docker volumes already exist from an older local stack, do not mix those persisted volumes with a newly generated secrets file unless you intentionally reset the volumes. Align `deploy/.env.secrets` with the passwords used to initialize the existing Postgres, Neo4j, and MinIO volumes, or run the proof under a fresh compose project/volume set.

4. Submit a run as usual. In Hatchet mode the API returns `202 Accepted` with `job_id`, `hatchet_run_id`, and `status_url`. Poll the job:

```bash
curl http://localhost:${STRATEGYOS_HTTP_PORT:-80}/runs/jobs/${JOB_ID} \
  -H "Authorization: Bearer ${TOKEN}"
```

Local proof from 2026-06-12 is recorded at `../outputs/StrategyOS Runtime Proofs/20260612T193648Z-hatchet-full-stack/`. Production use should still prove the same path on Hetzner and add a failed-worker/retry case before enabling non-conservative retry behavior.

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

## Proxy-OIDC production-boundary overlay

When moving beyond the disposable local identity provider, switch StrategyOS to trusted edge auth:

1. Add the proxy overlay compose file to the deploy set:

```bash
docker compose \
  -f deploy/docker-compose.yml \
  -f deploy/docker-compose.proxy-oidc.yml \
  --env-file deploy/.env \
  --env-file deploy/.env.secrets \
  up -d
```

2. Set at minimum in `deploy/.env`:

```bash
STRATEGYOS_AUTH_MODE=proxy_oidc
STRATEGYOS_TRUST_PROXY_AUTH=true
STRATEGYOS_OPERATOR_EMAILS=operator@example.com
STRATEGYOS_REVIEWER_EMAILS=reviewer@example.com
OAUTH2_PROXY_OIDC_ISSUER_URL=https://accounts.google.com
OAUTH2_PROXY_CLIENT_ID=<oidc-client-id>
OAUTH2_PROXY_REDIRECT_URL=https://strategyos.example.com/oauth2/callback
```

3. Keep only in `deploy/.env.secrets`:

```bash
STRATEGYOS_TRUSTED_PROXY_AUTH_SECRET=<shared edge-to-app secret>
OAUTH2_PROXY_CLIENT_SECRET=<oidc-client-secret>
OAUTH2_PROXY_COOKIE_SECRET=<oauth2-proxy-cookie-secret>
```

4. Use the proxy-specific Caddy edge file at `deploy/caddy/Caddyfile.proxy-oidc`. It forwards authenticated identity headers from `oauth2-proxy` and injects a shared trusted-proxy secret upstream so StrategyOS can fail closed if headers are spoofed or the edge is bypassed.

## Controlled Pilot Readiness Contract

### Anonymous-public proof path

- `python deploy/scripts/verify_cloud_surface.py --base-url https://strategyos.example.com`
- With no credentials, this now verifies the locally approved anonymous-public contract only: `/ui/session`, `/ui/workspace-contract/latest`, `/public/runs/latest`, `/public/runs/latest/findings`, `/public/runs/latest/report-preview`, and fail-closed anonymous health behavior. This boundary is enforced by the dedicated anonymous-public publication path, not by treating `public_safe` as a standalone redaction guarantee.
- Add both operator and reviewer credentials only when you intend to validate the authenticated governed surface too.

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
- `STRATEGYOS_RUNTIME_DEP_POPPLER_UTILS_VERSION=25.03.0-5+deb13u3`
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

### Deploy-time boundary validation

- `deploy/scripts/validate_deploy_boundary.sh` is the preflight guard for generated deploy env files.
- It fails fast if required secrets are blank or still use `__CHANGE_ME_...` placeholders.
- It refuses externally deployable configs that disable API auth, disable mandatory human review, or leave demo-role login enabled.
- It refuses Hatchet-mode deploys that omit `HATCHET_POSTGRES_PASSWORD` or `HATCHET_CLIENT_TOKEN`.
- It refuses LLM/model-provider deploys unless run policy is `external-approved`, `model_provider_use` is explicitly approved, and `STRATEGYOS_LLM_API_KEY` is present in secrets.
- For `TARGET_ENVIRONMENT=production`, it also refuses:
  - `STRATEGYOS_AUTH_MODE=api_key`
  - non-HTTPS `STRATEGYOS_PUBLIC_URL`
  - non-HTTPS identity issuers
  - proxy-OIDC configs missing trusted-proxy/email-allowlist/OIDC redirect settings
  - `STRATEGYOS_SITE_ADDRESS` values that do not cover the public host
  - `STRATEGYOS_SITE_ADDRESS=:80`
  - `STRATEGYOS_PUBLIC_HEALTH_ENABLED=true`
  - localhost/container-local identity issuers
  - root deploy user
- Run it manually before shipping env files if needed:

```bash
ENV_FILE=deploy/.env \
SECRETS_FILE=deploy/.env.secrets \
TARGET_ENVIRONMENT=hetzner-qa \
bash deploy/scripts/validate_deploy_boundary.sh
```

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

- The current CI/CD and production rollout plan is maintained in `docs/production-deployment-plan.md`.
- Add source-pack intake and validation so a user-selected folder with arbitrary filenames can be registered, classified, and readiness-checked before run execution.
- Keep OCR local and wire PDF/image extraction ahead of content-based document-role classification.
- Add additive canonical invoice-header normalization only after source-pack intake is in place; keep current invoice-consuming controls unchanged in that tranche.
- Replace the local identity provider with the production SSO authority before exposing reviewer endpoints. The deploy preflight now blocks `production` if the identity issuer is still localhost/container-local.
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
RUN_AUTH_HEADER="Authorization: Bearer ${TOKEN}" TARGET_HOST=root@YOUR_SERVER_IP deploy/scripts/run_remote_workflow.sh
```

Rollback to the latest pre-deploy backup:

```bash
TARGET_HOST=root@YOUR_SERVER_IP deploy/scripts/rollback_stack.sh
```

## External governed-surface verification

Use the post-deploy verifier to prove the cloud-visible auth/governance contract from outside the host:

```bash
OPERATOR_TOKEN="$(TARGET_HOST=root@YOUR_SERVER_IP ROLE=operator deploy/scripts/remote_idp_token.sh)"
REVIEWER_TOKEN="$(TARGET_HOST=root@YOUR_SERVER_IP ROLE=reviewer deploy/scripts/remote_idp_token.sh)"
python deploy/scripts/verify_cloud_surface.py \
  --base-url https://strategyos.example.test \
  --operator-auth-header "Authorization: Bearer ${OPERATOR_TOKEN}" \
  --reviewer-auth-header "Authorization: Bearer ${REVIEWER_TOKEN}"
```

The verifier fails if the external surface drifts into any of the conditions we must not ship:
- unauthenticated health/readiness exposure
- missing operator/reviewer role separation
- `require_human_review=false`
- demo-role authentication on an external surface
- localhost/container-local identity issuer exposed through `/health/ready`

The deploy workflow now runs this verifier automatically after protected readiness, before optional smoke, so a deploy cannot be reported healthy if the externally visible governed surface still drifts.
