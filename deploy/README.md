# StrategyOS Cloud-Agnostic Deployment

This deployment package is designed for Hetzner first, but keeps the runtime portable to any VM, Docker host, or Kubernetes cluster.

## Stack

- StrategyOS API container
- Postgres for run metadata, approvals, artifacts, and future LangGraph checkpoint storage
- Redis for LangGraph/runtime queues and cache
- Neo4j for the production knowledge graph
- MinIO for local S3-compatible object storage, replaceable with Hetzner Object Storage
- Caddy for TLS/reverse proxy
- Linux OCR through `pdftoppm` plus `tesseract`

## Local / Hetzner VM Pilot

1. Copy `deploy/.env.example` to `deploy/.env`.
2. Replace passwords and object-store values.
3. Mount or copy the source dataset into the `strategyos-workspace` volume path, or post it through the API once upload endpoints are added.
4. Start the stack:

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```

5. Check health through Caddy:

```bash
curl http://localhost/health
```

6. Run the workflow:

```bash
curl -X POST http://localhost/runs \
  -H "Content-Type: application/json" \
  -d '{"skip_prepare": true, "sync_artifacts": true}'
```

## Hetzner Notes

- Use a dedicated private network and firewall rules for Postgres, Redis, Neo4j, and MinIO.
- Expose only Caddy ports `80/443` publicly.
- For production object storage, replace MinIO env values with Hetzner Object Storage S3 endpoint and credentials.
- Use Hetzner volume snapshots plus S3-compatible backup for Postgres, Neo4j, and evidence artifacts.

## Next Production Hardening

- Add SSO/RBAC before exposing reviewer endpoints.
- Add durable LangGraph checkpoint wiring into Postgres.
- Add upload API and source-pack validation.
- Load `StrategyOS Knowledge Graph.json` into Neo4j with constraints and indexes.
- Add CI/CD and smoke tests for `/health`, `/runs`, artifact sync, and citation audit.

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
TARGET_HOST=root@YOUR_SERVER_IP deploy/scripts/check_health.sh
TARGET_HOST=root@YOUR_SERVER_IP deploy/scripts/run_remote_workflow.sh
```

Rollback to the latest pre-deploy backup:

```bash
TARGET_HOST=root@YOUR_SERVER_IP deploy/scripts/rollback_stack.sh
```
