# StrategyOS deployment runbook

This is the operational command reference for the current repository. Product requirements and remaining release blockers are maintained in [requirements](../docs/requirements.md) and the [gap assessment](../docs/assessment/gap-analysis.md). Historical local-stack and recovery claims have been removed; verify the target environment on each release.

## Runtime contract

The Compose stack includes the API, identity boundary, Postgres, Redis, Neo4j, Qdrant, MinIO and Caddy, with optional Hatchet services. Postgres stores business/workflow state; Neo4j/Qdrant are projections. OCR runs locally in the container. Source data and output state live in the configured workspace volume. Production images do not include demo datasets, test fixtures, documentation or local environments. Supply data explicitly.

Keep private services on the container network; any maintenance port must bind only to loopback. TLS ingress, identity, secret management, egress policy and tier residency must match the deployed environment. A working health endpoint does not establish business acceptance.

## Configuration and source-built local stack

From the repository root:

```sh
deploy/scripts/generate_env.sh
docker compose -f deploy/docker-compose.yml --env-file deploy/.env --env-file deploy/.env.secrets config -q
docker compose -f deploy/docker-compose.yml --env-file deploy/.env --env-file deploy/.env.secrets up -d --build
```

Review `deploy/.env.example` and `deploy/.env.secrets.example` for the complete contract. Generated `.env` files are private and ignored. Configure paths, identity, hostnames and credentials for the target. Do not reuse demonstration passwords. Preserve human review and disable demonstration role login in a hosted customer environment.

Expected hosted controls include `STRATEGYOS_API_AUTH_ENABLED=true`, `STRATEGYOS_LOGIN_REQUIRED=true`, `STRATEGYOS_REQUIRE_HUMAN_REVIEW=true` and `STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED=false`. Production boundary validation additionally checks HTTPS URLs, non-local identity, secret placeholders and the deployment user. See `deploy/scripts/validate_deploy_boundary.sh` for executable validation. Proxy-OIDC configuration uses the dedicated Compose/Caddy files and trusted proxy secret; the application must not trust arbitrary caller-supplied identity headers.

## Optional providers and workers

Model-provider use requires `STRATEGYOS_RUN_POLICY=external-approved`, `model_provider_use` in `STRATEGYOS_APPROVED_EXTERNAL_MODES`, explicit model/chat enablement and the selected provider/model/base URL. Store `STRATEGYOS_LLM_API_KEY` only in the secret configuration. Object-storage sync, hosted OCR and batch APIs have separate policy permissions. Sovereign deployments must not silently enable external fallbacks.

For Hatchet, select `STRATEGYOS_RUN_EXECUTION_MODE=hatchet`, configure the service address/TLS strategy, enable the Compose `hatchet` profile and provision a valid tenant token. `bootstrap_hatchet_token.sh` requires explicit bootstrap opt-in. Keep the token in the secret manager and preserve Hatchet state/config volumes; ordinary deployments must not regenerate identity or tokens. Check the worker with `deploy/scripts/check_hatchet_worker.sh`.

## Remote deployment and dataset sync

The scripts below are explicit operations against the configured host. Replace `YOUR_SERVER` and set the remaining target environment fields before invoking them.

```sh
TARGET_HOST=deploy@YOUR_SERVER deploy/scripts/bootstrap_hetzner.sh
TARGET_HOST=deploy@YOUR_SERVER deploy/scripts/deploy_stack.sh
TARGET_HOST=deploy@YOUR_SERVER SOURCE_DATASET="$PWD/data/demo/01_Synthetic_Dataset" deploy/scripts/sync_source_dataset.sh
```

Bootstrap is for initial setup. Dataset sync copies inputs; it does not prove an approved run. Reprocess via the operator workflow, verify pack identity/readiness, then use the normal reviewer/publication gate. The companion strategy context and any client-specific inputs must be staged through the governed intake contract when needed.

Health and workflow helpers accept protected authentication headers. Supply a valid token through secure runtime configuration; do not paste credentials into tracked documents:

```sh
TARGET_HOST=deploy@YOUR_SERVER deploy/scripts/check_health.sh
TARGET_HOST=deploy@YOUR_SERVER deploy/scripts/run_remote_workflow.sh
```

Set `READINESS_AUTH_HEADER` and `RUN_AUTH_HEADER`, respectively, as required by the scripts. `run_remote_workflow.sh` launches work and can create application state. Leave smoke/run launch disabled during a configuration-only release unless data and review flow are prepared.

## GitHub release workflow

`strategyos-ci.yml` runs the complete portable suite, Compose contract checks and an image build. `strategyos-deploy.yml` is manually dispatched and uses a fail-closed `verify-ci` job that requires successful CI for the exact deployed SHA before building/publishing. It then deploys the immutable image, checks readiness and verifies the anonymous login and protected application boundaries. `strategyos-branch-deploy.yml` supports temporary preview work and uses the same isolated test runner.

Configure the target GitHub environment with host/user/target directory, public URL/ports, identity issuer, Compose selection, pinned SSH host keys, deploy SSH key and the split environment-secret content. Consult workflow inputs and the example files for exact names. Production should use environment reviewer protection and a dedicated deploy identity. Do not assume a named environment is configured merely because a workflow offers it.

Every release must record commit, image digest, schema identity, source-pack hash, run ID, approval status and provider/policy configuration together. Local consolidation does not deploy the application or select/approve live data.

## Recovery

```sh
TARGET_HOST=deploy@YOUR_SERVER deploy/scripts/rollback_stack.sh
```

This helper uses the applicable pre-deploy backup. Establish image/schema/data compatibility before rollback. Keep tested backups for Postgres, source uploads, object storage and workspace state, plus a projection rebuild procedure. Define retention, RPO/RTO and restore validation with the operational owner. Do not treat an old screenshot or successful image rollback as a current data recovery drill.

The server-image recovery archive from 2 September was permanently deleted on 5 September at the user's request. It is no longer a recovery source; the deletion receipt is under `docs/maintenance`.
