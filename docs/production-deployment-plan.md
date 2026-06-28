# StrategyOS Production Deployment Plan

## Objective

Move StrategyOS from local/QA proof to a controlled production-style deployment that is repeatable, observable, and rollbackable. The immediate deploy target is the Hetzner VM, but the process must stay portable to another Docker host or a future Kubernetes environment.

## Production Runtime Baseline

- Host: Ubuntu VM with Docker Engine and Compose plugin.
- Runtime: Docker Compose project `strategyos`.
- Public edge: Caddy on ports `80` and `443`.
- Private services: Postgres, Redis, Neo4j, Qdrant, MinIO, and the local IDP remain on the Docker network; host-published maintenance ports must bind to `127.0.0.1` only.
- Release artifact: immutable GHCR image referenced by digest, deployed through `deploy/docker-compose.release.yml`.
- Secrets: GitHub environment secrets render `deploy/.env.secrets` at deploy time. Secret files are never committed or rsynced from repo state.
- Human control: production GitHub environments should require reviewers before the deploy job can access environment secrets.

## CI/CD Flow

1. `StrategyOS CI` runs on pull requests, pushes to `main`, and manual dispatch.
2. CI installs Python 3.12, local OCR dependencies, the package, and runs the portable health/security/intake/OCR/deploy-contract test suite.
3. CI validates Compose config for both source-build and release-image modes.
4. CI builds the Docker image without pushing, catching Dockerfile/runtime pin drift before deploy.
5. `StrategyOS Deploy` is manual (`workflow_dispatch`) and environment-scoped.
6. Deploy re-runs tests, builds and pushes a GHCR image, exports the digest image ref, logs the target host into GHCR, deploys with Compose, checks protected readiness, and then verifies the externally visible governed surface with fresh operator and reviewer identity tokens.
7. Optional smoke can call `POST /runs`; leave it off for ordinary deploys unless the dataset and reviewer flow are prepared.
8. Before sync/deploy, the workflow runs `deploy/scripts/validate_deploy_boundary.sh` against the rendered env + secrets so insecure flag drift is rejected before touching the host.
9. If deploy succeeds but readiness fails, the workflow invokes the existing rollback script against the latest pre-deploy backup.

The full acceptance/regression suite still depends on the external synthetic dataset folder under `strategy os/StrategyOS POC/01_Synthetic_Dataset`. Keep running that suite locally until a sanitized fixture pack is committed to the repo or injected into CI as a controlled artifact.

## GitHub Environment Configuration

Create these environments:

- `hetzner-qa`: current configured live deploy surface for `strategyos.live`.
- `production`: keep disabled until it is actually populated with the same deploy contract plus reviewer protections.

Environment variables:

- `HETZNER_HOST`: target host IP or DNS name.
- `HETZNER_USER`: SSH user. `root` works for the current QA VM; use a dedicated deploy user for production.
- `TARGET_DIR`: usually `/opt/strategyos`.
- `STRATEGYOS_PUBLIC_URL`: public URL shown in GitHub deployments.
- `STRATEGYOS_HTTP_PORT`: `80` unless fronted by another proxy.
- `STRATEGYOS_HTTPS_PORT`: `443`.
- `STRATEGYOS_SITE_ADDRESS`: Caddy site address. Use `:80` for IP-only HTTP QA, or the real domain for TLS.
- `STRATEGYOS_IDP_ISSUER`: issuer string for the temporary local IDP.
- `STRATEGYOS_COMPOSE_FILES`: optional override. Default is `deploy/docker-compose.yml deploy/docker-compose.release.yml deploy/docker-compose.hetzner-qa.yml`.

Environment secrets:

- `HETZNER_SSH_KEY`: private deploy key authorized on the target host.
- `HETZNER_KNOWN_HOSTS`: pinned SSH host key line(s) from `ssh-keyscan`.
- `STRATEGYOS_ENV_SECRETS`: full dotenv content matching `deploy/.env.secrets.example`.

Preflight rules now enforced in-repo:

- Required secrets must be non-empty and must not retain `__CHANGE_ME_...` placeholders.
- `STRATEGYOS_API_AUTH_ENABLED=true`
- `STRATEGYOS_REQUIRE_HUMAN_REVIEW=true`
- `STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED=false`
- Hatchet mode additionally requires a real `HATCHET_POSTGRES_PASSWORD` secret and `HATCHET_CLIENT_TOKEN`.
- LLM/model-provider deploys additionally require `STRATEGYOS_RUN_POLICY=external-approved`, `model_provider_use` in `STRATEGYOS_APPROVED_EXTERNAL_MODES`, and `STRATEGYOS_LLM_API_KEY` in secrets.
- `production` additionally requires:
  - `STRATEGYOS_PUBLIC_URL` over `https://`
  - `STRATEGYOS_IDP_ISSUER` over `https://`
  - `STRATEGYOS_SITE_ADDRESS` covering the same public host
  - non-`:80` `STRATEGYOS_SITE_ADDRESS`
  - `STRATEGYOS_PUBLIC_HEALTH_ENABLED=false`
  - non-local identity issuer
  - non-root deploy user

## Production Hardening Before Real Client Data

- Replace the temporary local IDP with production SSO/OIDC.
- Use a non-root deploy user with tightly scoped Docker access.
- Move MinIO to managed object storage or add volume backup/restore automation.
- Add scheduled encrypted backups for Postgres, Neo4j, Qdrant, MinIO, and the workspace volume.
- Add log shipping and alerting for Caddy/API/container health, disk pressure, failed runs, failed OCR, and reviewer backlog.
- Add a domain and real TLS; do not run IP-only HTTP outside QA.
- Define retention and deletion policies for uploaded source files, OCR text, findings, and artifacts.
- Add a staging environment that mirrors production config before the production environment is opened.

## Operational Runbook

1. Merge only after `StrategyOS CI` is green.
2. Open **Actions -> StrategyOS Deploy -> Run workflow**.
3. Select `hetzner-qa`; it is the current live deploy surface for `strategyos.live`. Leave `run_smoke` off for config-only deploys.
4. Confirm readiness passed and the governed-surface verifier stayed green.
5. Do not dispatch to `production` until that environment is populated and reviewer-gated; otherwise the workflow cannot acquire the required Hetzner deploy contract.
6. If the deployment fails after replacing the stack, verify the rollback job ran; otherwise run `deploy/scripts/rollback_stack.sh` with the same `TARGET_HOST` and `COMPOSE_FILES`.
7. Record the image digest, run ID, and readiness output in the release notes.
