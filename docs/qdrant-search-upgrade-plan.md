# StrategyOS Qdrant Search Upgrade Plan

Date: 2026-06-13

## Scope

This plan covers the first four upgrades for StrategyOS search:

1. Index citation excerpts and evidence chunks, not only findings.
2. Add filters in the UI and API for finding type, vendor, confidence, run, and source file.
3. Add hybrid search so exact finance terms and semantic-ish queries both work.
4. Add an "open evidence" action from each search result.

The goal is to make the existing Qdrant-backed search useful for investigation. Search must stay deterministic and cited. Qdrant is a retrieval index/cache; Postgres evidence records, run artifacts, and source files remain the source of truth.

## Current State

The current implementation is intentionally small:

- `strategyos_mvp/vector_store.py` creates one Qdrant point per finding in the `strategyos_findings` collection.
- The embedding is local and deterministic: `_embed_text()` hashes tokens into a fixed 256-dimensional vector.
- Each point payload currently carries fields like `run_id`, `tenant_slug`, `finding_id`, `title`, `pattern_type`, `vendor_id`, `vendor_name`, `source`, and `text`.
- `search_run_vectors()` only filters by `run_id`.
- `GET /data/vector-search` exposes that search to the frontend.
- `strategyos_mvp/static/app.js` renders vector search in the Advanced drawer, but without structured filters or evidence-opening actions.
- Evidence/citation data already exists in Postgres, especially `strategyos_finding_citations`, which includes `run_id`, `finding_id`, `evidence_document_id`, `source_path`, `source_hash`, `locator`, `excerpt`, `resolved`, `hash_match`, and `resolved_payload`.
- The deployment currently pins `qdrant/qdrant:v1.9.5`. Qdrant's native Query API and documented hybrid query support start at v1.10.0, so native hybrid search requires either a Qdrant upgrade or a compatibility implementation in application code.

## Non-Goals

- Do not add an LLM to answer questions.
- Do not expose arbitrary filesystem paths or raw uploaded files through search results.
- Do not make Qdrant the durable record of evidence.
- Do not remove the existing `/data/vector-search` contract until the frontend and tests have moved to the upgraded response shape.
- Do not require a neural embedding provider for phase one. The current deterministic embedding can remain until there is an explicit policy decision to use local or external embedding models.

## Target Search Model

Create a new search projection that can represent three result types:

- `finding`: one searchable record per detector finding.
- `citation`: one searchable record per finding citation excerpt.
- `evidence_chunk`: one searchable record per chunk of uploaded/source evidence text.

Prefer a new Qdrant collection named `strategyos_search_chunks` instead of overloading `strategyos_findings`. Keep `strategyos_findings` temporarily for backward compatibility, or have the old endpoint search only `point_type=finding` in the new collection after migration.

Each Qdrant payload should use a common shape:

```json
{
  "run_id": "uuid",
  "tenant_slug": "local-demo",
  "point_type": "finding | citation | evidence_chunk",
  "finding_id": "F-002",
  "citation_id": "uuid-or-null",
  "evidence_document_id": "uuid-or-null",
  "title": "Duplicate payment for invoice INV-2026-0341",
  "text": "searchable excerpt or chunk text",
  "pattern_type": "duplicate_payment",
  "vendor_id": "vendor-id-or-null",
  "vendor_name": "Premier Packaging LLC",
  "confidence": "high | medium | low | null",
  "recoverable_sar": 794108,
  "source_path": "uploads/ap_ledger.csv",
  "source_hash": "sha256-or-null",
  "locator": "row 341",
  "chunk_index": 0,
  "artifact_key": "optional-artifact-key",
  "created_at": "iso timestamp"
}
```

Use deterministic point IDs, for example UUIDv5 over:

```text
run_id:point_type:finding_id:citation_id:evidence_document_id:source_hash:locator:chunk_index
```

This makes sync idempotent and safe to rerun.

## Phase 0: Version and Migration Guardrails

Before changing search behavior, add guardrails around Qdrant version and collection migration.

Tasks:

- Add a Qdrant health/version helper in `vector_store.py`.
- Detect whether the running Qdrant supports the native Query API.
- Keep app startup healthy on Qdrant v1.9.5.
- Create `strategyos_search_chunks` with the same 256-dimensional cosine vector when using the current deterministic embedding.
- Add payload indexes for fields used by filters where supported:
  - `run_id`
  - `tenant_slug`
  - `point_type`
  - `finding_id`
  - `pattern_type`
  - `vendor_id`
  - `vendor_name`
  - `confidence`
  - `source_path`
  - `source_hash`
- If upgrading Qdrant, snapshot or otherwise verify the existing collection before changing the deployment image.

Acceptance:

- Existing finding search still works.
- `/data/status` can report the new search collection status.
- Running against Qdrant v1.9.5 does not crash.
- The code has an explicit branch for native hybrid support versus compatibility hybrid support.

## Phase 1: Index Citations and Evidence Chunks

Add a new indexing pipeline that turns findings, citations, and selected evidence text into Qdrant points.

Backend tasks:

- Replace or extend `sync_findings_vector_store()` with a broader sync function, for example `sync_search_index_for_run()`.
- Continue indexing one `finding` point per finding.
- Query `strategyos_finding_citations` for the run and index one `citation` point per non-empty `excerpt`.
- Include citation metadata in the payload: `citation_id`, `evidence_document_id`, `source_path`, `source_hash`, `locator`, `resolved`, and `hash_match`.
- Use `resolved_payload` when it contains useful structured context, but cap the indexed text size.
- Add a small chunking utility for evidence text:
  - Target 700-1000 characters per chunk.
  - Use roughly 100 characters of overlap.
  - Preserve source path, locator/page/row, hash, and chunk index.
  - Skip empty or binary-only content.
- Start with cited evidence and resolved citation payloads. Avoid indexing every raw AP row or every large uploaded file in the first pass unless it is already parsed as readable evidence.
- Make all indexing idempotent through deterministic point IDs and Qdrant upsert.

Suggested internal model:

```python
@dataclass(frozen=True)
class SearchIndexPoint:
    point_id: str
    point_type: Literal["finding", "citation", "evidence_chunk"]
    text: str
    payload: dict[str, Any]
```

Acceptance:

- A run with 8 findings still has 8 `finding` points.
- Citation excerpts for that run are indexed as `citation` points.
- A query like `duplicate payment invoice` returns both the duplicate-payment finding and its supporting citation/evidence results.
- Re-running index sync does not duplicate points.
- Qdrant payloads contain enough metadata to open the underlying evidence without trusting client-provided paths.

## Phase 2: Search Filters in API and UI

Add structured filters to `GET /data/vector-search` and the Advanced drawer.

API contract:

```text
GET /data/vector-search
  ?query=duplicate payment invoice
  &run_id=<uuid>
  &limit=10
  &point_type=finding,citation,evidence_chunk
  &pattern_type=duplicate_payment
  &vendor_id=<id>
  &vendor_name=Premier Packaging LLC
  &confidence=high
  &source_path=uploads/ap_ledger.csv
  &finding_id=F-002
```

Validation:

- `query` is required and trimmed.
- `limit` is clamped, for example `1..50`.
- `run_id` defaults to the latest run if omitted.
- Multi-value filters may be comma-separated.
- Unknown filter values should return no results, not errors.
- Invalid UUIDs or malformed limits should return `400`.
- Auth rules stay the same as the existing endpoint.

Qdrant filter mapping:

- Always include `run_id` in `must`.
- Add `tenant_slug` if tenant scoping is active.
- Add `point_type`, `pattern_type`, `vendor_id`, `confidence`, `source_path`, and `finding_id` as exact payload matches.
- Treat `vendor_name` as an exact match initially. Add contains/fuzzy vendor matching later only if needed.

Frontend tasks:

- Keep the existing Advanced drawer location.
- Add compact controls:
  - Query input.
  - Result type segmented control: `All`, `Findings`, `Citations`, `Evidence`.
  - Finding type select.
  - Vendor select or text filter.
  - Confidence select.
  - Source file select.
  - Limit stepper or select.
- Populate filter options from the current run where possible:
  - Finding types from current findings.
  - Vendors from current finding payloads.
  - Source files from citation/evidence payloads or a new search-facets endpoint.
- Keep the empty state short.
- Result cards should show:
  - Result type.
  - Score.
  - Finding ID when present.
  - Vendor.
  - Pattern/finding type.
  - Source file and locator.
  - A short excerpt.
  - `Open evidence` action when available.

Optional helper endpoint:

```text
GET /data/vector-search/facets?run_id=<uuid>
```

Response:

```json
{
  "run_id": "uuid",
  "point_types": ["finding", "citation", "evidence_chunk"],
  "pattern_types": ["duplicate_payment"],
  "vendors": [{"vendor_id": "v-1", "vendor_name": "Premier Packaging LLC"}],
  "confidence": ["high", "medium", "low"],
  "source_paths": ["uploads/ap_ledger.csv"]
}
```

Acceptance:

- Filters visibly change the result set.
- Query plus `point_type=citation` returns only citation/evidence-style cards.
- Query plus `finding_id=F-002` returns only results connected to that finding.
- Frontend tests preserve existing shell coverage and add assertions for new filter hooks.

## Phase 3: Hybrid Search

There are two implementation tracks.

### Track A: Compatibility Hybrid on Current Qdrant

Use this first if deployment remains on `qdrant/qdrant:v1.9.5`.

Tasks:

- Keep the current vector search call.
- Add lexical scoring in Python over returned candidates and/or a larger candidate pool.
- Use a simple deterministic score initially:
  - normalized exact token overlap
  - phrase boosts for exact finance terms
  - field boosts for `title`, `finding_id`, `vendor_name`, `source_path`, and `locator`
- Fuse vector and lexical ranking with reciprocal rank fusion or a weighted score.
- Return score details in each result:

```json
{
  "score": 0.82,
  "ranking": {
    "mode": "hybrid_compat",
    "vector_score": 0.49,
    "lexical_score": 0.77,
    "fused_score": 0.82
  }
}
```

Acceptance:

- Exact query `INV-2026-0341` ranks the matching citation/evidence above unrelated semantic matches.
- Query `duplicate payment invoice` still ranks the duplicate-payment finding highly.
- Search behavior is deterministic in tests.

### Track B: Native Qdrant Hybrid

Use this after upgrading Qdrant to a version with Query API support.

Tasks:

- Upgrade Qdrant in `deploy/docker-compose.yml` after validating migration in a non-production environment.
- Add named vectors if needed:
  - `dense` for the existing deterministic vector or a future approved embedding.
  - `sparse` for keyword-style sparse vectors.
- Use Qdrant Query API `prefetch` and RRF fusion for dense+sparse search.
- Keep Track A as a fallback if Qdrant version detection says native hybrid is unavailable.

Acceptance:

- App reports native hybrid support in diagnostics.
- Hybrid search works through one backend API, regardless of whether the implementation path is compatibility or native.
- Existing tests do not require a live Qdrant instance unless explicitly marked integration.

## Phase 4: Open Evidence From Search Result

Add a safe evidence-preview path from search result to source context.

API design:

```text
GET /data/search-results/{point_id}/evidence?run_id=<uuid>
```

Alternative if point IDs are not exposed:

```text
GET /data/evidence-preview
  ?run_id=<uuid>
  &finding_id=F-002
  &citation_id=<uuid>
  &source_hash=<sha256>
  &locator=row%20341
```

Response:

```json
{
  "run_id": "uuid",
  "point_id": "uuid",
  "finding_id": "F-002",
  "citation_id": "uuid-or-null",
  "source_path": "uploads/ap_ledger.csv",
  "source_hash": "sha256-or-null",
  "locator": "row 341",
  "preview_kind": "text",
  "title": "Duplicate payment evidence",
  "excerpt": "short cited excerpt",
  "resolved_payload": {},
  "artifact_key": "optional-artifact-key",
  "actions": {
    "open_artifact": "/reviewer/runs/<run_id>/artifacts/<artifact_key>"
  }
}
```

Security requirements:

- Require the same auth boundary as reviewer/operator data endpoints.
- Require `run_id`.
- Resolve evidence by stored citation/evidence IDs, source hash, or artifact key. Do not open arbitrary paths supplied by the browser.
- Reject path traversal.
- Return sanitized previews, not raw local filesystem paths.
- Keep excerpts bounded.
- If the original source cannot be previewed safely, show metadata and a clear unsupported state.

Frontend tasks:

- Add an `Open evidence` button to result cards when `open_evidence` metadata is present.
- Open a side panel or modal inside the Advanced drawer.
- Show:
  - source file
  - locator
  - linked finding
  - excerpt
  - resolved structured payload when available
  - artifact preview link when backed by an existing artifact endpoint
- Add loading and error states.

Acceptance:

- Clicking `Open evidence` on a duplicate-payment result opens the cited source context.
- The browser never receives a raw absolute local filesystem path.
- Unauthorized users cannot open evidence previews.
- Missing/deleted evidence returns a controlled `404` or unsupported preview message.

## Response Shape

Upgrade `/data/vector-search` responses to a richer but backward-compatible shape:

```json
{
  "run_id": "uuid",
  "query": "duplicate payment invoice",
  "mode": "hybrid_compat",
  "filters": {
    "point_type": ["finding", "citation"],
    "pattern_type": ["duplicate_payment"]
  },
  "results": [
    {
      "point_id": "uuid",
      "result_type": "citation",
      "score": 0.82,
      "ranking": {
        "mode": "hybrid_compat",
        "vector_score": 0.49,
        "lexical_score": 0.77,
        "fused_score": 0.82
      },
      "finding_id": "F-002",
      "title": "Duplicate payment for invoice INV-2026-0341",
      "pattern_type": "duplicate_payment",
      "vendor_id": "vendor-id",
      "vendor_name": "Premier Packaging LLC",
      "confidence": "high",
      "source_path": "uploads/ap_ledger.csv",
      "locator": "row 341",
      "excerpt": "bounded text preview",
      "open_evidence": {
        "href": "/data/search-results/<point_id>/evidence?run_id=<uuid>"
      }
    }
  ]
}
```

Keep `finding_id`, `title`, `pattern_type`, `vendor_name`, `source`, and `score` during transition so existing frontend code and tests can adapt incrementally.

## Test Plan

Unit tests:

- Search index builder creates `finding`, `citation`, and `evidence_chunk` points.
- Point IDs are deterministic.
- Empty citation excerpts are skipped.
- Qdrant upserts are idempotent.
- Filter parameters compile into the expected Qdrant filter body.
- Compatibility hybrid ranking is deterministic.
- Evidence-preview resolver refuses path traversal and cross-run access.

API tests:

- `/data/vector-search` still requires auth.
- Invalid `limit` and malformed `run_id` return `400`.
- `point_type`, `pattern_type`, `vendor`, `confidence`, `source_path`, and `finding_id` filters are honored.
- Response includes `result_type`, `point_id`, `excerpt`, `source_path`, `locator`, and `open_evidence` where available.
- Evidence preview requires auth and returns bounded sanitized data.

Frontend tests:

- Preserve existing shell assertions for search hooks.
- Add assertions for filter controls.
- Add assertion for result cards and `Open evidence` button.
- Add empty, loading, and error states.

Integration checks:

- Run a sample analysis.
- Confirm Qdrant status reports the new collection.
- Confirm a duplicate-payment query returns the finding plus supporting citations.
- Confirm exact invoice-number search ranks exact evidence highly.
- Confirm source-file filtering narrows results.
- Confirm `Open evidence` opens the cited context.

## Rollout Order

1. Add search point builder and tests without changing the UI.
2. Create and populate `strategyos_search_chunks` alongside the existing collection.
3. Extend `/data/vector-search` to read from the new collection while preserving old response keys.
4. Add filter parameters and backend tests.
5. Add frontend filter controls and result cards.
6. Add compatibility hybrid ranking.
7. Add evidence preview endpoint.
8. Add `Open evidence` UI.
9. Verify locally against a sample run.
10. Deploy.
11. Verify production `/data/status`, `/data/vector-search`, filters, and evidence preview.
12. Only then decide whether to upgrade Qdrant and enable native hybrid.

## Definition of Done

- Search indexes findings, citations, and evidence chunks for a run.
- Filters are available in both API and UI.
- Hybrid ranking improves exact invoice/vendor/source lookups without breaking deterministic behavior.
- Every result that claims evidence can open a safe evidence preview.
- Existing auth boundaries remain intact.
- Tests cover indexing, filtering, ranking, evidence preview, and frontend hooks.
- Production deploy does not require Qdrant native hybrid unless the deployment image has been upgraded and verified.
