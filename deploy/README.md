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
