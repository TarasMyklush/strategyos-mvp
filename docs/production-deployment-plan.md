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
2. CI installs Python 3.12, local OCR dependencies, the package, and runs `pytest -q`.
3. CI validates Compose config for both source-build and release-image modes.
4. CI builds the Docker image without pushing, catching Dockerfile/runtime pin drift before deploy.
5. `StrategyOS Deploy` is manual (`workflow_dispatch`) and environment-scoped.
6. Deploy re-runs tests, builds and pushes a GHCR image, exports the digest image ref, logs the target host into GHCR, deploys with Compose, and checks protected readiness.
7. Optional smoke can call `POST /runs`; leave it off for ordinary deploys unless the dataset and reviewer flow are prepared.
8. If deploy succeeds but readiness fails, the workflow invokes the existing rollback script against the latest pre-deploy backup.

## GitHub Environment Configuration

Create these environments:

- `hetzner-qa`: immediate test target.
- `production`: real external production target; add required reviewers and branch/tag deployment rules before use.

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
3. Select `hetzner-qa` first; leave `run_smoke` off for config-only deploys.
4. Confirm readiness passed.
5. For production, use the `production` environment and require reviewer approval.
6. If the deployment fails after replacing the stack, verify the rollback job ran; otherwise run `deploy/scripts/rollback_stack.sh` with the same `TARGET_HOST` and `COMPOSE_FILES`.
7. Record the image digest, run ID, and readiness output in the release notes.
