# Flexible Invoice Architecture Plan

## Purpose and status

This document is the controlling plan for invoice-path expansion in the current StrategyOS MVP. It is intentionally aligned to the repo's as-built implementation truth, the current canonical README/deployment guidance, and the active controlled-pilot readiness posture.

Current status:

- The product/runtime baseline is broader than invoice work: protected API, governed human review, Postgres-backed run state, Neo4j sync, Qdrant retrieval, MinIO artifact storage, and recovery-proof evidence are already part of the local broader-testing baseline.
- The invoice path is still workbook-native today.
- Source-pack intake, filename-independent classification, and additive canonical invoice headers are not yet implemented in the repo.
- Therefore this plan is an execution-order and blast-radius control document, not a claim that flexible-invoice architecture is already delivered.

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

The repo still depends on fixed dataset assumptions for finance ingestion and invoice-consuming logic:

- `strategyos_mvp/ingestion.py`
  - `load_dataset()` reads fixed known files from the dataset root.
  - `DataBundle` contains workbook-native AP/AR/GL/TB/master-data/PO/cash-forecast collections.
  - There is no source-pack manifest and no canonical invoice header collection today.
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
  - There is no source-pack validation endpoint and no folder-upload intake flow yet.
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

- Fixed dataset-root ingestion is the active path.
- Manual dataset replacement remains the temporary demo mechanism.
- OCR/evidence quality, governed review, Neo4j sync, Qdrant retrieval, and recovery proof are already part of the broader-testing baseline.

### Phase 1 - Source-pack intake and validation (next active tranche)

Goal: let a user select or upload a folder-shaped source pack and have StrategyOS register every supported file without relying on filenames.

Required scope:

1. Add source-pack intake for workspace-bounded folder paths and uploaded folder payloads.
2. Recursively enumerate supported files and build a manifest with stable source ids, hashes, relative paths, file type hints, and extraction status.
3. Run text extraction/OCR before role classification for PDFs/images.
4. Classify document roles from content, not filenames.
5. Add validation/reporting for unsupported files, ambiguous roles, OCR failures, and task-readiness gaps.
6. Add UI/API validation flow before run execution.

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
- new `strategyos_mvp/source_pack.py`
- new `strategyos_mvp/document_classifier.py`
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

## Implementation review: missing work and developer guidance

This review is scoped to the requested local demo:

`user selects a folder with scans/files -> StrategyOS processes supported files regardless of filenames -> user gets Cash Leakage Discovery, Working Capital Drift Check, and Drill-Down Q&A outputs.`

### P0 findings

#### P0-1. Missing folder/source-pack intake API and UI

Current evidence:

- `strategyos_mvp/api.py` exposes `/runs`, but `RunRequest` only accepts `dataset`, `run_dir`, `skip_prepare`, and `sync_artifacts`.
- The UI start-run form only has a text input for `Dataset path`.
- There is no `UploadFile`, multipart route, `source_pack.py`, browser directory picker, or source-pack validation route.

Impact:

- A user cannot select or upload a folder from the browser.
- The current workaround is manual replacement of the fixed dataset folder or typing a server-local path.
- This does not meet the filename-independent scan-folder requirement.

Guidance:

- Add `strategyos_mvp/source_pack.py`.
- Add API routes:
  - `POST /source-packs/validate` for operator-only preflight validation.
  - `POST /source-packs` for uploaded folder payloads.
  - Optional local-dev route: `POST /source-packs/from-path` accepting a workspace-bounded folder path.
- For browser upload, use multipart files and preserve relative paths when the browser provides them.
- For local path mode, enforce the same workspace-boundary rules already used by `_resolve_dataset_path()`.
- Store staged packs under a deterministic local folder such as `CONFIG.output_root / "source_packs" / <source_pack_id>`.
- Return a manifest and task-readiness payload before allowing run execution.

Acceptance tests:

- Upload/select a folder whose files have arbitrary names.
- The API returns every supported file in the manifest.
- Unsupported files are returned as unsupported, not silently dropped.
- A path outside `CONFIG.workspace_root` is rejected.

#### P0-2. Fixed-filename ingestion still blocks arbitrary folders

Current evidence:

- `strategyos_mvp/ingestion.py::load_dataset()` directly reads fixed paths such as:
  - `02_ERP_Extracts/AP_Invoices_H1_2026.xlsx`
  - `02_ERP_Extracts/AR_Invoices_H1_2026.xlsx`
  - `02_ERP_Extracts/GL_Extract_H1_2026.csv`
  - `02_ERP_Extracts/Trial_Balance_June_2026.xlsx`
  - `03_Master_Data/Vendor_Master.xlsx`
  - `05_Purchase_Orders/PO_Log_H1_2026.csv`
  - `07_Cash_Forecast/CFO_Cash_Forecast_June_2026.xlsx`

Impact:

- Renamed source files fail even if content is valid.
- Scan-only folders cannot be processed into the current `DataBundle`.
- The three business outputs depend on this workbook-native `DataBundle`.

Guidance:

- Keep `load_dataset()` for backward compatibility.
- Add a new intake path that builds a `SourcePackManifest`.
- Add a normalization/staging step that maps classified sources into either:
  - the existing workbook-native `DataBundle` fields for MVP compatibility, or
  - additive canonical collections that controls can later consume.
- Do not remove the fixed dataset path until source-pack tests cover the existing synthetic dataset.

Acceptance tests:

- Copy the current synthetic dataset to a temp folder, rename every source file, and prove classification still identifies the roles needed for the tasks.
- The old fixed dataset path still passes current finance-control tests.

#### P0-3. Missing content-based document classifier

Current evidence:

- No `strategyos_mvp/document_classifier.py`.
- No `DocumentRole` or equivalent role enum.
- Current logic relies on fixed paths and source groups rather than content signatures.

Impact:

- The system cannot decide whether arbitrary scanned files are invoices, bank statements, contracts, ledgers, trial balances, PO logs, or unknown evidence.

Guidance:

- Add a classifier that uses content signals first:
  - workbook sheet names and headers,
  - CSV headers,
  - extracted PDF/OCR text,
  - table-like cues,
  - known finance terms such as invoice number, due date, vendor, amount, VAT, IBAN, debit, credit, GL account, trial balance, purchase order.
- Treat extension and filename as weak hints only.
- Return:
  - `document_role`,
  - confidence,
  - evidence snippets that justify the role,
  - parser candidates,
  - ambiguity reasons.
- Do not auto-promote low-confidence classifications into task-critical inputs without validation warnings.

Acceptance tests:

- Same content with different filenames produces the same role.
- An ambiguous file returns an ambiguous role with reasons.
- Unknown evidence appears in the manifest.

#### P0-4. OCR is not yet a complete scan-folder intake layer

Current evidence:

- `strategyos_mvp/evidence.py` extracts PDF text and calls OCR for PDF pages.
- `strategyos_mvp/ocr.py` supports local OCR paths, but the source-pack flow for arbitrary PDFs/images is absent.
- There is no general image-file OCR registration for selected folders.

Impact:

- Scanned images or image-only PDFs cannot reliably feed document classification and task validation.
- OCR status is not yet tied to a source-pack manifest.

Guidance:

- Extend OCR intake to support PDF plus PNG/JPG/TIFF.
- Cache OCR by source hash, engine, and version.
- Store OCR results per source and page/image:
  - status,
  - engine,
  - extracted text,
  - failure reason,
  - verification snippets.
- Run OCR before classification for scans.
- Feed only verified OCR text into parsers, controls, and optional model prompts.

Acceptance tests:

- Image-only invoice scan gets OCR text registered in the source manifest.
- OCR failure does not crash the run; it appears as a data-quality issue.
- OCR cache is reused for identical file content.

#### P0-5. Missing task-readiness validator

Current evidence:

- `/health/ready` checks infrastructure readiness.
- There is no source-pack task-readiness endpoint for Cash Leakage Discovery, Working Capital Drift Check, or Drill-Down Q&A.

Impact:

- The UI cannot tell the user whether a selected folder can support the requested analyses before run.
- "Processed all files" can be confused with "all tasks are computable."

Guidance:

- Add a task-readiness model with statuses:
  - `ready`,
  - `partial`,
  - `blocked`.
- Validate minimum role coverage:
  - Cash Leakage Discovery needs AP data and supporting evidence; richer leakage classes also need vendor master, contracts, bank statements, GL, PO, and cash forecast depending on pattern.
  - Working Capital Drift Check needs AP and AR invoice/settlement dates and amounts.
  - Drill-Down Q&A needs generated findings plus GL/TB baseline fields for EBITDA bridge quality.
- Return missing role names and concrete guidance, not generic errors.

Acceptance tests:

- Folder with AP only: Cash Leakage may be partial; Working Capital is blocked without AR; Q&A is partial or blocked depending on findings/GL/TB.
- Folder with AP, AR, GL, TB, masters, PO, cash forecast: all three tasks are ready.
- Empty folder returns blocked for all three with clear reasons.

#### P0-6. Postgres is still required for proper governed e2e review

Current evidence:

- `state_store.py` returns skipped state when `DATABASE_URL` is absent.
- The currently running local server reports `database_configured=false`.
- Reviewer queue, claim/unclaim, approvals, and operator resume all depend on persisted run/checkpoint state.

Impact:

- Direct local `uvicorn` can show latest artifacts and partial UI state, but cannot properly demo governed queue -> claim -> approve -> resume e2e without Postgres.

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

#### P1-3. Drill-Down Q&A is a generated transcript, not interactive Q&A

Current evidence:

- `CaseFileWriter` writes `Drill-down Q&A transcript.md`.
- No `/qa` endpoint exists.
- No UI chat surface exists for follow-up questions.

Impact:

- The current artifact proves precomputed Q&A depth, not live conversational depth.

Guidance:

- If live conversational proof is required, add `/runs/{run_id}/qa` or `/qa` over selected run artifacts.
- Product messaging must label the shipped surface as a generated evidence review transcript until a real interactive endpoint exists.
- Start deterministic: retrieve from run summary, findings, citations, working-capital memo, and data-quality report.
- Add optional LLM review only behind provider boundary and audit flag.

Acceptance tests:

- Ask "largest single-event leakage" and get answer with finding id and citation.
- Ask "top-five EBITDA impact" and get answer with GL/TB baseline reference.
- Ask unsupported question and receive a bounded "not supported by current evidence" answer.

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

### Suggested implementation order

1. Add models/contracts for `SourcePackManifest`, `SourceFileRecord`, `DocumentRole`, `TaskReadiness`, and `CanonicalInvoiceHeader`.
2. Implement `source_pack.py` for recursive intake, hashing, manifest writing, and workspace-boundary validation.
3. Extend OCR/text extraction for source-pack PDFs/images and attach results to source records.
4. Implement `document_classifier.py` with content-first rules and confidence scoring.
5. Add task-readiness validation for the three requested scenarios.
6. Add operator-only API routes and UI validation before `/runs`.
7. Add compatibility staging so current `load_dataset()` or a new loader can consume classified source packs.
8. Add canonical invoice headers as an additive `DataBundle` field.
9. Wire source-pack id into run summary, data-quality report, and artifacts.
10. Add minimal Postgres local-stack instructions for governed e2e.

### Developer-ready test checklist

- `tests/test_source_pack.py`
  - recursive folder intake,
  - source hashing,
  - unsupported-file reporting,
  - outside-workspace rejection.
- `tests/test_document_classifier.py`
  - role classification from workbook headers,
  - role classification from OCR text,
  - renamed-file stability,
  - ambiguity reporting.
- `tests/test_task_readiness.py`
  - ready/partial/blocked coverage for the three scenarios.
- `tests/test_flexible_invoices.py`
  - AP workbook to canonical headers,
  - scan-derived invoice header where confidence is sufficient,
  - source traceability.
- `tests/test_frontend_shell.py`
  - folder/source-pack validation controls render,
  - run submission can reference validated source-pack id.
- Existing tests must remain green:
  - `tests/test_finance_controls.py`,
  - `tests/test_case_file_writer.py`,
  - `tests/test_run_poc_audit_log.py`,
  - `tests/test_reviewer_api.py`.

## Definition of done for the currently active invoice plan

The current plan is satisfied only when all of the following are true:

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
