# Flexible Invoice Architecture Plan

## Purpose and status

This document is the controlling plan for invoice-path expansion in the current StrategyOS MVP. It is intentionally aligned to the repo's as-built implementation truth, the current canonical README/deployment guidance, and the active controlled-pilot readiness posture.

Current status (updated 2026-06-10):

- The product/runtime baseline is broader than invoice work: protected API, governed human review, Postgres-backed run state, Neo4j sync, Qdrant retrieval, MinIO artifact storage, and recovery-proof evidence are already part of the local broader-testing baseline.
- **Phase 1 is delivered.** Source-pack intake (folder + upload), filename-independent content classification, OCR-before-classification, schema-tolerant column-alias mapping with operator confirmation, and true-skip partial runs are implemented (`source_pack.py`, `detector_contracts.py`, `ingestion.py`, `api.py`).
- **Deterministic Data Q&A is delivered.** `strategyos_mvp/qa.py` plus `POST /qa` and the dashboard Data Q&A panel provide interactive deterministic finance answers over the selected/latest run data. This is not an LLM chat surface.
- The invoice path remains workbook-native; the **additive canonical invoice-header collection (Phase 2)** is not yet implemented. Downstream consumer migration (Phase 3) is unstarted.
- This plan remains the execution-order and blast-radius control document; Phases 2-3 below are still forward-looking.

## Current as-built StrategyOS architecture

The current verified local broader-testing baseline is:

- Entry boundary: Caddy -> StrategyOS API.
- Identity boundary: local provider-backed IDP issuing operator/reviewer access for protected endpoints.
- Governed runtime: reviewer queue, approval flow, and operator-only resume path.
- State and artifacts: Postgres for run metadata/approvals, Redis for runtime queue/cache needs, MinIO for object artifacts, workspace/output volumes for local execution.
- Retrieval surfaces: Neo4j for run-scoped graph sync/query and Qdrant for finding retrieval.
- Operational proof: protected `/health/ready`, protected `/data/status`, vector search, and recovery-proof artifacts under `artifacts/recovery-proof-20260604T174300Z`.

This matters for invoice work because invoice-path changes must preserve the existing governed runtime, evidence traceability, readiness surfaces, and local-first control boundary.

## Current implementation truth for invoices and evidence

The repo still depends on workbook-native finance structures for the deterministic controls, but source-pack staging now feeds those structures where possible:

- `strategyos_mvp/ingestion.py`
  - `load_dataset()` reads workbook-native role paths from the dataset root.
  - Source-pack staging can create a normalized run-model dataset from arbitrary supported filenames.
  - `DataBundle` contains workbook-native AP/AR/GL/TB/master-data/PO/cash-forecast collections.
  - There is a source-pack manifest/readiness flow today, but no separate canonical invoice header collection yet.
- `strategyos_mvp/skills/finance_controls.py`
  - Deterministic controls read directly from `bundle.ap`.
- `strategyos_mvp/knowledge_graph.py`
  - Invoice nodes are built from `bundle.ap`.
- `strategyos_mvp/state_store.py`
  - AP rows persist as `strategyos_finance_transactions.transaction_type = 'ap_invoice'`.
- `strategyos_mvp/citation_resolver.py`
  - Structured citation mapping still assumes the current fixed workbook/document paths.
- `strategyos_mvp/api.py`
  - `/runs` executes against a dataset path.
  - Source-pack folder/upload validation and mapping confirmation endpoints exist.
- `strategyos_mvp/evidence.py`, `strategyos_mvp/ocr.py`, and `strategyos_mvp/quality.py`
  - Evidence extraction, OCR status capture, and OCR-quality reporting already exist and remain the correct foundation for the next intake tranche.

## Absorbed canonical decisions

The following decisions are now controlling and should be treated as non-negotiable for invoice-path work:

1. **Execution order starts with source-pack intake, not invoice normalization.**
   - The user-facing requirement begins with selecting a folder/source pack and processing supported files regardless of filename.
2. **Filename-independent classification is required.**
   - Filenames and relative paths remain provenance/display only, not routing logic.
3. **OCR stays inside StrategyOS and runs before document-role classification for scanned PDFs/images.**
   - OCR is evidence infrastructure, not an external model-provider responsibility.
4. **Canonical invoice work is additive after intake.**
   - The first invoice-domain seam is an optional canonical invoice-header collection added alongside the current AP path.
5. **Current finance controls, workflow orchestration, reviewer flow, and retrieval surfaces stay unchanged in the first invoice tranche.**
   - Consumer migration is deferred.
6. **Provider boundary remains local-first by default.**
   - Source hashing, OCR, parsing, citation resolution, and quantitative validation stay inside the app unless an explicitly enabled external mode is approved.
7. **Quality must fail clearly, not silently.**
   - Unsupported, ambiguous, or missing task-critical sources must be surfaced explicitly.

## Controlled pilot and prod-readiness alignment

Invoice-path work must fit the current controlled-pilot readiness model rather than bypass it.

Already present in the repo/runtime baseline:

- protected readiness and status surfaces,
- provider-backed local identity boundary,
- governed human review requirement,
- durable run state and artifact persistence,
- graph/vector operational proof,
- recovery/restore proof for the local compose baseline.

Controlling readiness principle for this plan:

- evidence foundation before broader automation,
- deterministic quantification before consumer rewiring,
- governed runtime before pilot expansion,
- human review remains mandatory,
- security/identity boundary stays enabled,
- operational proof stays truthful and reproducible.

That means flexible-invoice work must strengthen the evidence path first and must not dilute current fail-closed and reviewer-gated behavior.

## Active phase sequence

### Phase 0 - Current as-built baseline (already true)

- Fixed dataset-root ingestion remains supported for the canonical synthetic baseline and regression tests.
- Source-pack intake is also active for folder/upload-based runs and stages classified sources into the current run model where possible.
- Manual dataset replacement remains only a legacy convenience path.
- OCR/evidence quality, governed review, Neo4j sync, Qdrant retrieval, and recovery proof are already part of the broader-testing baseline.

### Phase 1 - Source-pack intake and validation (delivered)

Goal: let a user select or upload a folder-shaped source pack and have StrategyOS register every supported file without relying on filenames.

Delivered scope:

1. Source-pack intake for workspace-bounded folder paths and uploaded folder payloads.
2. Recursive supported-file enumeration with stable source ids, hashes, relative paths, file type hints, and extraction status.
3. Text extraction/OCR before role classification for PDFs/images.
4. Structured and document role classification from content signals rather than filenames.
5. Validation/reporting for unsupported files, ambiguous roles, OCR failures, duplicate roles, unconfirmed mappings, and task-readiness gaps.
6. UI/API validation flow before run execution.
7. Schema-tolerant structured column mapping with operator confirmation.
8. True-skip partial runs for missing roles, with detector skips reported.

Acceptance bar:

- Renaming files does not change role classification except for weak tie-break metadata.
- Unknown files are reported, not dropped.
- Requested tasks clearly state whether they are executable from the selected source pack.

### Phase 2 - Additive canonical invoice-header normalization

Goal: create the smallest durable invoice contract without breaking current flows.

Required scope:

1. Add an invoice-normalization seam, e.g. `strategyos_mvp/flexible_invoices.py`.
2. Extend `DataBundle` with an optional canonical invoice-header collection.
3. Populate canonical headers from the current AP workbook first, then from sufficiently confident intake/classification outputs.
4. Preserve `source_path` and `source_locator` traceability from day one.
5. Add focused tests proving additive, non-breaking behavior.

Explicitly not in Phase 2:

- consumer migration,
- line-item persistence,
- graph line-item modeling,
- API/reviewer payload redesign,
- generic scan-only line parsing for arbitrary invoice layouts.

### Phase 3 - Downstream rewiring after Phases 1 and 2 are proven

Only after intake and additive canonical headers are stable should the repo open:

- persistence/schema expansion,
- citation rewiring where needed,
- knowledge-graph migration from workbook-native invoice assumptions,
- one-by-one migration of invoice-consuming controls.

### Phase 4 - Further pilot hardening after invoice-path proof

Invoice expansion remains subordinate to the broader controlled-pilot hardening plan, including stronger checkpointing/runtime durability, production identity boundary replacement, CI/smoke coverage, and later pilot-gate evidence.

## Concrete code surfaces by phase

### Phase 1 direct surfaces

- `strategyos_mvp/api.py`
- `strategyos_mvp/source_pack.py`
- `strategyos_mvp/data_roles.py`
- `strategyos_mvp/tasks.py`
- `strategyos_mvp/evidence.py`
- `strategyos_mvp/ocr.py`
- `strategyos_mvp/quality.py`
- UI/assets served from the current API surface
- targeted tests for intake, OCR, and classification behavior

### Phase 2 direct surfaces

- `strategyos_mvp/ingestion.py`
- new `strategyos_mvp/flexible_invoices.py`
- `strategyos_mvp/models.py` only if typed canonical contracts are needed
- targeted normalization and regression tests

### Phase 3 likely surfaces

- `strategyos_mvp/state_store.py`
- `deploy/postgres/schema.sql`
- `strategyos_mvp/citation_resolver.py`
- `strategyos_mvp/knowledge_graph.py`
- `strategyos_mvp/skills/finance_controls.py`

## Implementation review: status and remaining developer guidance

This review is scoped to the requested local demo:

`user selects a folder with scans/files -> StrategyOS processes supported files regardless of filenames -> user gets Cash Leakage Discovery, Working Capital Drift Check, and Drill-Down Q&A outputs.`

### Delivered P0 findings

#### P0-1. Folder/source-pack intake API and UI — delivered

Current evidence:

- `strategyos_mvp/api.py` exposes source-pack upload, path staging, validation, mapping confirmation, and source-pack-backed run creation.
- `RunRequest` accepts `source_pack_id` and `allow_partial_source_pack`.
- `strategyos_mvp/source_pack.py` builds manifests, classifies supported files, attaches OCR/text extraction, writes task readiness, and stages normalized datasets.
- The dashboard exposes source-pack upload/path staging, validation, mapping confirmation, and partial-run controls.

Impact:

- The filename-independent source-pack requirement is implemented for supported file extensions.
- Unsupported files are retained and reported rather than silently dropped.

Guidance:

- Preserve the current source-pack boundary as the controlling intake path.
- Add first-class parsing for currently unsupported office/email/archive formats only after the current supported path remains green.

Acceptance tests:

- Upload/select a folder whose files have arbitrary names.
- The API returns every supported file in the manifest.
- Unsupported files are returned as unsupported, not silently dropped.
- A path outside `CONFIG.workspace_root` is rejected.

#### P0-2. Legacy fixed-path ingestion is retained, source-pack staging handles arbitrary filenames

Current evidence:

- `strategyos_mvp/ingestion.py::load_dataset()` still supports the canonical fixed paths used by the regression fixture:
  - `02_ERP_Extracts/AP_Invoices_H1_2026.xlsx`
  - `02_ERP_Extracts/AR_Invoices_H1_2026.xlsx`
  - `02_ERP_Extracts/GL_Extract_H1_2026.csv`
  - `02_ERP_Extracts/Trial_Balance_June_2026.xlsx`
  - `03_Master_Data/Vendor_Master.xlsx`
  - `05_Purchase_Orders/PO_Log_H1_2026.csv`
  - `07_Cash_Forecast/CFO_Cash_Forecast_June_2026.xlsx`
- `strategyos_mvp/source_pack.py` now stages arbitrary supported filenames into those canonical target paths when content-based role classification succeeds.
- `strategyos_mvp/data_roles.py` centralizes run-model roles, target paths, labels, column signatures, aliases, and document role folders.

Impact:

- Renamed structured source files can run through source-pack staging when their columns map to required roles.
- Scan-only/document-only folders can be classified as evidence, but they still do not by themselves populate every workbook-native `DataBundle` frame needed for all current deterministic controls.
- The three business outputs still depend on compatible workbook-native run-model data until Phase 2 canonical invoice headers and later consumer migration are implemented.

Guidance:

- Keep `load_dataset()` for backward compatibility.
- Preserve source-pack staging as the primary arbitrary-folder path.
- Keep using registered `DataRoleSpec` metadata for new structured/document roles rather than adding per-role constants in multiple modules.
- Add additive canonical invoice headers in Phase 2 before migrating consumers away from workbook-native AP/AR frames.

Acceptance tests:

- Copy the current synthetic dataset to a temp folder, rename every source file, and prove classification still identifies the roles needed for the tasks.
- The old fixed dataset path still passes current finance-control tests.

#### P0-3. Content-based classifier is implemented inside source-pack staging

Current evidence:

- `strategyos_mvp/source_pack.py` classifies structured sources from workbook/sheet/column signals and document sources from extracted/OCR text indicators.
- `strategyos_mvp/data_roles.py` defines document roles such as invoice documents, bank statements, contracts, and email correspondence alongside structured run-model roles.
- Filenames remain provenance/display metadata rather than the routing source of truth.

Impact:

- Supported structured and text-bearing document inputs can be classified independently of filenames.
- Ambiguous or unknown evidence is reported in the manifest instead of silently promoted.
- The classifier is intentionally rule-based and bounded; unsupported office/email/archive formats and weak OCR text remain known limitations.

Guidance:

- Keep classification content-first and registry-driven through `DataRoleSpec`.
- Treat new roles as additive registrations with tests for aliases, required columns, target paths, and task-readiness effects.
- Do not auto-promote low-confidence classifications into task-critical inputs without validation warnings or operator confirmation.

Acceptance tests:

- Same content with different filenames produces the same role.
- An ambiguous file returns an ambiguous role with reasons.
- Unknown evidence appears in the manifest.

#### P0-4. OCR-backed PDF/image source-pack intake — delivered with known precision limits

Current evidence:

- `strategyos_mvp/evidence.py` extracts PDF text and calls OCR for PDF pages.
- `strategyos_mvp/ocr.py` supports local Tesseract and macOS Vision fallback.
- `strategyos_mvp/source_pack.py` attaches text extraction for supported PDFs and images before document-role classification.
- Supported OCR image inputs are `.png`, `.jpg`, `.jpeg`, `.tif`, and `.tiff`.

Impact:

- Scanned PDFs/images can feed document classification when OCR succeeds.
- OCR status and failure reasons are tied to the source-pack manifest.
- OCR does not currently provide numeric word/page accuracy confidence, so important finance amounts still require reviewer inspection.

Guidance:

- Keep OCR local and auditable.
- Future work: add numeric OCR confidence scoring or stronger OCR quality checks for scan-heavy finance documents.

Acceptance tests:

- Image-only invoice scan gets OCR text registered in the source manifest.
- OCR failure does not crash the run; it appears as a data-quality issue.
- OCR cache is reused for identical file content.

#### P0-5. Task-readiness validator — delivered

Current evidence:

- `/health/ready` checks infrastructure readiness.
- Source-pack validation returns a task-readiness payload.
- Readiness records supported/unsupported files, role inventory, missing roles, duplicate structured roles, and unconfirmed mappings.
- Partial-run mode records available and missing roles; dependent detectors are skipped instead of crashing or injecting synthetic data.

Impact:

- The UI can show whether a selected pack is ready, partial, blocked, or needs operator mapping confirmation before run.
- "Processed all files" can be confused with "all tasks are computable."

Guidance:

- Preserve the registered `TaskSpec` readiness model and keep statuses explicit:
  - `ready`,
  - `partial`,
  - `blocked`.
- Validate minimum role coverage through task/data-role metadata:
  - Cash Leakage Discovery needs AP data and supporting evidence; richer leakage classes also need vendor master, contracts, bank statements, GL, PO, and cash forecast depending on pattern.
  - Working Capital Drift Check needs AP and AR invoice/settlement dates and amounts.
  - Drill-Down Q&A needs generated findings plus GL/TB baseline fields for EBITDA bridge quality.
- Return missing role names and concrete guidance, not generic errors.
- Add new cases through `TaskSpec` registrations rather than one-off readiness branches.

Acceptance tests:

- Folder with AP only: Cash Leakage may be partial; Working Capital is blocked without AR; Q&A is partial or blocked depending on findings/GL/TB.
- Folder with AP, AR, GL, TB, masters, PO, cash forecast: all three tasks are ready.
- Empty folder returns blocked for all three with clear reasons.

#### P0-6. Postgres is still required for proper governed e2e review

Current evidence:

- `state_store.py` returns skipped state when `DATABASE_URL` is absent.
- Reviewer queue, claim/unclaim, approvals, and operator resume all depend on persisted run/checkpoint state.

Impact:

- Direct local `uvicorn` without `DATABASE_URL` can show latest artifacts and partial UI state, but cannot properly demo governed queue -> claim -> approve -> resume e2e without Postgres.

Guidance:

- Provide a minimal local stack target for developers:
  - Postgres,
  - FastAPI/UI,
  - local filesystem outputs,
  - API-key auth,
  - Tesseract/poppler.
- Keep Redis, Neo4j, Qdrant, MinIO, Caddy, and IDP optional for this specific business demo.
- Add a README command or compose override for the minimal local e2e stack.

Acceptance tests:

- Create run with Postgres configured.
- Run pauses at review when human review is required.
- Reviewer claims and approves.
- Operator resumes.
- Writer artifacts are produced and visible.

### P1 findings

#### P1-1. Missing additive canonical invoice header seam

Current evidence:

- No `strategyos_mvp/flexible_invoices.py`.
- `DataBundle` does not expose canonical invoice headers.
- Finance controls, graph, persistence, and citation resolver still assume workbook-native AP rows.

Impact:

- Even after source classification, invoice sources cannot be represented in a stable format independent of source type.

Guidance:

- Add canonical invoice headers with:
  - `invoice_id`,
  - `invoice_source_type`,
  - `counterparty_id`,
  - `counterparty_name`,
  - `invoice_date`,
  - `due_date`,
  - `settled_date`,
  - `currency`,
  - `amount_total`,
  - `status`,
  - `source_id`,
  - `source_path`,
  - `source_locator`,
  - `confidence`.
- Populate from current AP workbook first.
- Then populate from high-confidence source-pack classified invoices.
- Keep additive until tests prove no regression.

Acceptance tests:

- Current AP workbook produces canonical headers.
- Arbitrarily named invoice-like source produces canonical header when confidence is sufficient.
- Every canonical header has source traceability.

#### P1-2. Finance controls still consume workbook-native AP/AR shapes

Current evidence:

- `strategyos_mvp/skills/finance_controls.py` reads `bundle.ap`, `bundle.ar`, `bundle.gl`, `bundle.vendors`, `bundle.po`, and `bundle.cash_forecast`.

Impact:

- Source-pack support alone will not make the business tasks execute unless the intake layer produces compatible data structures or controls are migrated.

Guidance:

- MVP path: generate compatibility DataFrames from classified structured sources where possible.
- Later path: migrate controls one by one to canonical finance collections.
- Keep current finance-control tests as non-regression tests.

Acceptance tests:

- Existing synthetic dataset results remain stable.
- Source-pack-staged equivalent dataset produces the same or intentionally explained result deltas.

#### P1-3. Deterministic interactive Q&A — delivered

Current evidence:

- `CaseFileWriter` writes `Drill-down Q&A transcript.md`.
- `strategyos_mvp/qa.py` implements a deterministic intent registry and answer handlers.
- `POST /qa` accepts `{question, run_id?}` and returns answer, value, unit, basis, intent, citations, and suggestions.
- The dashboard **Data Q&A** panel submits questions and renders a thread with basis/source lines.

Impact:

- The product now supports deterministic interactive finance Q&A over the selected/latest run data.
- The Q&A surface is intentionally bounded; unsupported questions return suggestions instead of guessed answers.

Guidance:

- Keep `/qa` deterministic and local-first.
- Do not add LLM-backed Q&A unless it is explicitly behind the provider boundary and audit flag.
- Future work: add more curated intents only where answers can be computed and cited.

Acceptance tests:

- Ask `What is the total amount of invoices?` and get the exact AP total with basis/citations.
- Ask `Top 5 vendors by spend` and get ranked vendors.
- Ask `What is the total recoverable?` and get the deterministic recoverable amount.
- Ask unsupported text and receive suggestions, not a fabricated answer.

#### P1-4. Source-pack persistence schema is not defined

Current evidence:

- `deploy/postgres/schema.sql` has current run/data tables, but no explicit source-pack manifest table.

Impact:

- Source manifests may only live as files unless schema is added.
- Reviewer/audit surfaces cannot reliably query source-pack provenance.

Guidance:

- Store source-pack manifest as an artifact first.
- Add Postgres tables only after manifest shape stabilizes:
  - `strategyos_source_packs`,
  - `strategyos_source_files`,
  - optional `strategyos_source_extractions`.
- Keep file artifact as source of truth during the first tranche to avoid premature schema lock-in.

Acceptance tests:

- Manifest artifact exists for every source-pack run.
- When Postgres is enabled, source-pack id is linked to the run.

### Remaining implementation order

1. Add canonical invoice headers as an additive `DataBundle` field.
2. Populate canonical headers from the current AP workbook first.
3. Populate canonical headers from high-confidence source-pack invoice documents where reliable fields are available.
4. Wire source traceability from source-pack ids/locators into canonical invoice headers.
5. Add minimal Postgres local-stack instructions for governed e2e if the existing compose guidance is too broad for demo use.
6. Migrate invoice-consuming controls only after canonical headers are test-backed and non-breaking.

### Current and remaining test checklist

Current coverage:

- `tests/test_source_pack.py` and `tests/test_source_pack_api.py` cover recursive intake, hashing, unsupported-file reporting, workspace-boundary rejection, role classification, staging, API validation, and mapping confirmation behavior.
- `tests/test_task_registry.py` covers registered readiness tasks.
- `tests/test_data_roles.py` covers registered source/data roles and role-derived metadata.
- `tests/test_plugins.py` covers plugin module registration for stages, tasks, data roles, and detectors.
- `tests/test_frontend_shell.py` covers source-pack/dashboard controls.
- Existing non-regression coverage remains in `tests/test_finance_controls.py`, `tests/test_case_file_writer.py`, `tests/test_run_poc_audit_log.py`, and `tests/test_reviewer_api.py`.

Remaining coverage for Phase 2:

- `tests/test_flexible_invoices.py` for AP workbook to canonical headers, scan-derived invoice headers where confidence is sufficient, and source traceability.

## Definition of done for the remaining invoice plan

The remaining plan is satisfied only when all of the following are true:

- The repo still supports the current workbook-native run path with no regression.
- A user-selected folder/source pack can be registered and validated without filename dependence.
- Every supported file is processed, classified, or explicitly reported as unsupported/unknown.
- OCR and evidence quality remain local, auditable, and traceable.
- `DataBundle` exposes an additive canonical invoice-header seam.
- Canonical invoice headers remain traceable back to structured rows/documents.
- No current finance-control, reviewer-runtime, readiness, graph, or vector surface is silently broken by the new seam.

## Risks and guardrails

1. **Hidden filename dependency**
   - Mitigation: rename-file tests must be first-class acceptance coverage.
2. **Traceability regression**
   - Mitigation: preserve source ids, source paths, locators, and evidence linkage from intake onward.
3. **Premature downstream migration**
   - Mitigation: keep Phases 1 and 2 additive; do not switch consumers early.
4. **Scan-only completeness gaps**
   - Mitigation: readiness validation must distinguish "all files processed" from "requested analysis computable."
5. **Readiness-story drift**
   - Mitigation: invoice-path work must preserve governed review, auth boundary, truthful readiness checks, and operational proof already present in the broader-testing baseline.
6. **Projection-store authority drift**
   - Mitigation: keep Neo4j/KG strictly projection-only; Postgres rows plus emitted evidence files remain the durable source of truth, and runtime checks must block Neo4j when those authoritative stores are missing or divergent.
7. **Product messaging boundary drift**
   - Mitigation: user-facing copy must distinguish deterministic analysis from optional LLM review and must not describe generated review stages as autonomous agents or live chat when those surfaces do not exist.
