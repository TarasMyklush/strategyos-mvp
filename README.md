# StrategyOS MVP

Production-shaped MVP scaffold for the StrategyOS finance-analysis POC, now centered on a truthful, locally verified acceptance baseline.

## What This Implements

- Sanitized analysis-input preparation (`agent_input` runtime folder).
- Human-only evaluation answer-key separation.
- Source hash manifest.
- Citation resolver and citation audit.
- Data-quality and OCR gap report.
- Structured ingestion for AP, AR, GL, trial balance, master data, POs, and treasury workbook.
- Folder/upload source-pack intake (`POST /source-packs`, `/source-packs/from-path`, `/source-packs/validate`) with content-based (filename-independent) role classification and per-task readiness.
- Schema-tolerant ingestion: per-role column-alias contracts (`detector_contracts.py`) match differently-named real files and rename columns to canonical so detectors stay unchanged; roles can be discovered by columns/sheet-names.
- Operator-confirm mapping gate: low-confidence role mappings block the run until confirmed via `POST /source-packs/confirm-mapping` (editable per-column UI).
- True-skip partial runs (`allow_partial_source_pack`): absent roles load as empty canonical frames, dependent detectors are skipped and reported in `run_summary.json`; no synthetic baseline is ever injected.
- Untrusted-input guarding (`prompt_injection.py`) and sensitive-ID pseudonymization (`sensitive_ids.py`).
- PDF/text evidence extraction with citation IDs.
- Deterministic finance skills for planted leakage classes.
- Deterministic finance analysis and challenge-review stages.
- Knowledge-graph export stage with a local strong-node graph export.
- Postgres-backed run state with governed review/resume flow.
- Optional Neo4j sync plus live query surfacing through `/data/status` when a real `run_id`, matching Postgres KG rows, and the emitted knowledge-graph evidence file are all present.
- Optional Qdrant-backed persistent local vector retrieval when Qdrant is configured.
- Optional provider-backed local identity boundary for operator/reviewer access.
- LangGraph-compatible workflow adapter with a local fallback when LangGraph is not installed.
- Case file, working-capital memo, generated Q&A transcript, knowledge graph, and ping-pong audit log generation.
- Canonical POC acceptance harness and a local final-gate runner.
- Cloud-agnostic configuration, API, S3-compatible artifact sync, Postgres schema, Docker image, and Docker Compose deployment scaffold.

## Verified Local-Only MVP Baseline

- Canonical local POC acceptance harness passes against the synthetic dataset.
- Local final gate can be executed with `make final-gate`; it runs the canonical acceptance harness, Phase 8 runtime/governance validation tests, and emits a final go/no-go report.
- Latest canonical run evidence is promoted under `../outputs/StrategyOS Active Run Evidence/`.
- The current local-only baseline does **not** assume Postgres, Neo4j, Qdrant, MinIO, or the local identity provider are running. When those services are unconfigured, the code records that truthfully in the run summary as `skipped`.

## Live Architecture Snapshot

- Entry boundary: local CLI or API -> StrategyOS workflow.
- Identity boundary: API-key or provider-backed auth is available, but the local-only final gate does not require external auth infrastructure.
- Runtime state: local workflow/governance path is the canonical MVP baseline; Postgres-backed persistence remains optional and is used only when configured.
- Retrieval layer: knowledge-graph export is always emitted; Neo4j and Qdrant sync remain optional local extensions. Postgres rows plus emitted evidence files remain the durable source of truth, and Neo4j is projection-only.
- Workspace/output layer: timestamped run directories under `../outputs/` plus a promoted canonical evidence pack.
- Current invoice path remains AP-workbook-native for deterministic controls, while the next invoice expansion path is controlled by `docs/flexible-invoice-architecture-plan.md`.

## Current Controlling Plan Alignment

Traceability source: `docs/flexible-invoice-architecture-plan.md`.

## Product Messaging Boundary

- **Deterministic analysis is the default StrategyOS product behavior.** Source intake, OCR, parsing, citation resolution, quantitative controls, findings, and evidence-backed reporting run inside the local application boundary.
- **Human review is explicit and governed.** Reviewer approval is a workflow control, not an implied model judgment.
- **Optional LLM review is a secondary path only.** If enabled later, it must stay behind the provider boundary, remain disabled by default, and never replace the deterministic evidence path.
- **Generated Q&A is not a live chat product surface today.** The current MVP emits a precomputed transcript from run artifacts rather than an interactive conversational interface.

- **Source-pack intake is implemented (2026-06-09/10).** Folder/upload intake with recursive file registration, stable source ids, and filename-independent classification is live (`source_pack.py`, `detector_contracts.py`); schema-tolerant column mapping, operator-confirm gating, and true-skip partial runs are in place. See `docs/flexible-invoice-architecture-plan.md` Phase 1 (now delivered).
- **OCR stays inside StrategyOS and runs before document-role classification for scanned PDFs/images.** OCR is treated as evidence infrastructure, not as an external model-provider responsibility.
- **A user can choose a folder with arbitrary filenames and have StrategyOS process all supported files.** Manual dataset replacement remains only as the legacy fixed-dataset convenience path.
- **Canonical invoice work follows intake as an additive seam.** The next invoice-domain change is an optional canonical invoice-header collection in `DataBundle`, populated from the current AP workbook and qualifying scan-derived invoice sources without breaking current runs.
- **Current finance controls, reviewer flow, and workflow orchestration stay unchanged in the first invoice tranche.** Consumer migration to canonical invoices is deferred until intake plus additive normalization are stable.
- **Quality/reporting constraints are explicit.** Unknown or unsupported files must be reported, not dropped; missing task-critical source roles must be surfaced as clear task-readiness limits instead of silent failure.
- **Provider boundary stays local-first by default.** Source hashing, OCR, parsing, citation resolution, finance controls, and quantitative validation remain inside the app; any external LLM mode is optional, disabled by default, and outside the primary evidence path.

## Current Flexible-Invoice Implementation Sequence

1. Add source-pack intake for workspace-bounded folder paths and uploaded folder payloads.
2. Run local text extraction/OCR for supported PDF/image files before role classification.
3. Classify document roles from content, not filenames, and report task readiness.
4. Add UI/API validation flow for the selected folder before run execution.
5. Add additive canonical invoice-header normalization.
6. Only after intake plus additive normalization pass, open persistence/citation rewiring and later consumer migration.

## Run

From the implementation folder:

```bash
cd "/Users/taras/Desktop/Taras/sp soft/Enterprise OS/strategyos_mvp"
/Users/taras/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m strategyos_mvp.run_poc
```

Outputs are written to:

```text
../outputs/StrategyOS MVP Run-<timestamp>/
```

## Local Gate Commands

```bash
make poc-acceptance
make final-gate
```

## Minimal local Postgres-backed governed source-pack path

This is the thinnest local proof for P0-6 only: local app/test process plus the compose Postgres service. It avoids the broader Redis/Neo4j/Qdrant/MinIO stack.

1. Start Postgres only:

```bash
deploy/scripts/generate_env.sh
POSTGRES_PORT=55432 docker compose -p strategyos-p06 -f deploy/docker-compose.yml --env-file deploy/.env --env-file deploy/.env.secrets up -d postgres
```

2. Point local verification at that database:

```bash
export STRATEGYOS_POSTGRES_E2E_DATABASE_URL="postgresql://strategyos:strategyos@localhost:55432/strategyos"
```

3. Run the governed source-pack persistence proof:

```bash
.venv/bin/python -m pytest -q tests/test_governed_review_flow_postgres_e2e.py -rs
```

What this proves locally under persisted Postgres state:
- source-pack staging from a real workspace path
- `POST /runs` pauses at `awaiting_review`
- reviewer queue + claim
- reviewer approval
- operator resume
- completion at `writer`
- persisted run/checkpoint/approval rows remain queryable after completion

`make final-gate` promotes the latest truthful local evidence pack and writes:

- `StrategyOS POC Acceptance Report.json|md`
- `StrategyOS Final Gate Report.json|md`

## Production Notes

The local fallback workflow is deliberately deterministic. For production, install LangGraph and wire the same nodes through the LangGraph adapter with a durable checkpointer and human approval interrupt.

Cloud deployment assets are under `deploy/`. They remain useful for richer environments, but the controlling MVP truth source is now the local-only gate and its promoted evidence pack rather than older compose-era claims.
