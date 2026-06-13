# Neo4j Utilization Plan — make the graph do real work (cloud)

**Date:** 2026-06-12
**Status:** Approved plan, ready to implement
**Scope:** cloud deployment only (full stack: Postgres + Neo4j + Qdrant + Hatchet/LangGraph). Local-only runs are explicitly out of scope.
**Audience:** any developer or LLM agent implementing this cold. Verify each code reference before relying on it; update this doc if you find drift.

---

## 1. Problem (verified 2026-06-12)

The app builds a real knowledge graph and syncs it to Neo4j on cloud runs, then never queries it back.

- **Write path works:** `run_poc.py:377` → `neo4j_store.sync_knowledge_graph()` upserts every node/edge tagged by `run_id`. The cloud full-stack proof run `20260612T193648Z-hatchet-full-stack` shows `run_id=ac3f3108-…` and `neo4j.status=synced`. Schema/constraints exist (`neo4j_store.py:_ensure_schema`); a projection guardrail reconciles graph counts against the state store before accepting the sync.
- **Read path is empty:** the only Neo4j reads in `api.py` are `graph_status_for_run` and `check_neo4j_ready` — they power the "neo4j synced" badge and `/data/status`. **No feature traverses relationships.** `/qa` answers from in-memory pandas; the graph-viz endpoint `GET /runs/latest/knowledge-graph` (`api.py:2027`) reads the ~2 MB artifact JSON via `_load_knowledge_graph_artifact`, not Neo4j.
- **Consequence:** Neo4j is a ~1 GB-heap status badge. The graph's most valuable content — the `SAME_BANK_ACCOUNT_AS` / `SAME_TAX_ID_AS` entity-resolution edges and multi-hop evidence chains — is computed, stored, and ignored. Relationship questions are answered (if at all) by nested pandas loops that do not scale and do not exist for cross-entity cases.

The graph the app already produces (measured from the canonical artifact): nodes — Invoice 1396, PurchaseOrder 600, Vendor 210, SKU 98, Evidence 42, Finding 8, Contract 6; edges — SOURCED_FROM, ISSUED_INVOICE, MATCHES_PO, ORDERS_SKU, ISSUED_PO, SUPPORTED_BY, INVOLVES_VENDOR, HAS_CONTRACT, SAME_BANK_ACCOUNT_AS, SAME_TAX_ID_AS.

## 2. Goal

Neo4j becomes the system of record for **relationship-shaped questions and the graph view** on cloud. Three capabilities, each backed by Cypher against the synced per-run graph:

1. **Graph-query intents in `/qa`** — questions that are natural graph traversals answered by Cypher, with citations, alongside the existing deterministic intents.
2. **Graph viz served from Neo4j** — the existing `GET /runs/latest/knowledge-graph` endpoint reads Neo4j (findings view + capped expansion) instead of parsing the artifact JSON, so it scales (ref `docs/knowledge-graph-viz-research.md` §4).
3. **Entity-resolution surface** — the shared-bank-account / shared-tax-id vendor clusters get a first-class read path (they are the highest-value, hardest-in-pandas query and they map to the duplicate-vendor finding).

Non-goal: moving the detectors onto Cypher (that's a separate, larger effort). This plan reads the graph; it does not change how findings are produced.

## 3. Hard constraints

1. **No LLM required.** Graph intents use deterministic question→Cypher matching (same pattern as the existing `Intent` registry in `qa.py:91`), not text-to-Cypher generation. Curated parameterized queries only.
2. **Cloud-gated, honest degradation.** Every graph capability checks `CONFIG.neo4j_uri` and the run's `neo4j.status`. When Neo4j is absent/`skipped`/`empty`, the feature returns a clear "graph not available for this run" payload — never an unstyled 500. Reuse the existing `skipped/synced/blocked/empty/failed` status vocabulary.
3. **Run-scoped, injection-safe.** Every query filters by `run_id` and passes user values only as Cypher **parameters** — never string-interpolated. Relationship-type/label allowlists already exist for the viz endpoint (`api.py:111` `KNOWLEDGE_GRAPH_EXPAND_EDGE_LABELS`); reuse them.
4. **Read-only.** These paths never write to Neo4j; the only writer remains `sync_knowledge_graph`.
5. **Backward compatible.** `/data/status`, the badge, and the artifact JSON keep working. The viz endpoint keeps its response shape; only its data source changes (behind a seam — §5.2).
6. **Bounded results.** Every traversal has a `LIMIT`; expansion stays capped (existing `KNOWLEDGE_GRAPH_EXPAND_LIMIT=25`, max 100).

## 4. Capabilities (the Cypher catalog)

All queries assume the synced schema: `(:StrategyOSNode {run_id, node_key, domain_label})`, relationships carry `run_id` + `original_label`. Each is a named, parameterized, run-scoped read. Examples (finalize exact property names against `neo4j_store._upsert_node` during implementation):

| Intent / capability | Question it answers | Cypher shape |
| --- | --- | --- |
| `vendor_collusion_cluster` | "Which vendors share a bank account or tax id?" | `MATCH (a:StrategyOSNode {run_id:$rid, domain_label:'Vendor'})-[r]->(b) WHERE r.original_label IN ['SAME_BANK_ACCOUNT_AS','SAME_TAX_ID_AS'] RETURN a,b,r.original_label` — return clusters + the finding(s) that involve them |
| `finding_evidence_chain` | "What evidence supports F-004 and how is it connected?" | `MATCH (f {run_id:$rid, node_key:$fid})-[:SUPPORTED_BY|INVOLVES_VENDOR*1..2]-(n) RETURN ...` (bounded depth) |
| `vendor_finding_exposure` | "Which findings touch vendor V-1142, and total recoverable?" | `MATCH (f {domain_label:'Finding'})-[:INVOLVES_VENDOR]->(v {node_key:$vid}) RETURN f.finding_id, f.recoverable_sar` |
| `shared_evidence_findings` | "Which findings rely on the same source document?" | `MATCH (f1)-[:SUPPORTED_BY]->(e)<-[:SUPPORTED_BY]-(f2) WHERE f1<>f2 RETURN e, collect(...)` — surfaces correlated findings |
| `vendor_contract_gap` | "Vendors with invoices but no contract" (off-contract spend) | `MATCH (v {domain_label:'Vendor'}) WHERE NOT (v)-[:HAS_CONTRACT]->() RETURN v` |
| viz `findings` view | graph panel default | findings + 1-hop SUPPORTED_BY/INVOLVES_VENDOR/HAS_CONTRACT + SAME_* edges, vendor invoice-count as a property |
| viz `expand=<vendor>` | tap-to-expand | that vendor's invoices/POs `LIMIT $cap` + truncation count |

Citations: graph-intent answers cite the `Evidence` nodes' `source_path` reached in the traversal, so they stay consistent with the existing citation contract (`/qa` answers already carry `citations[]`).

## 5. Implementation

### 5.1 New module `strategyos_mvp/graph_queries.py`
- A `GraphQuerySource` protocol with `neo4j_uri`-gated implementation: `Neo4jGraphSource` (reuses `neo4j_store._graph_driver()`).
- One function per capability in §4: named, parameterized, run-scoped, `LIMIT`-bounded; returns UI-shaped dicts (`{answer, value, unit, basis, citations, nodes?, edges?}`), mirroring the `/qa` result contract.
- A `graph_capability_status(run_id)` returning the same status vocabulary so callers can degrade.
- Unit-tested against a Neo4j test instance gated like the existing Postgres e2e (env var `STRATEGYOS_NEO4J_E2E_URI`; skip when unset — mirror `test_governed_review_flow_postgres_e2e.py`).

### 5.2 Viz endpoint: read Neo4j behind a seam
- Refactor `_knowledge_graph_payload` (`api.py:1345`) to call a `KnowledgeGraphSource` interface with two impls: `ArtifactJsonSource` (current behavior, fallback) and `Neo4jKGSource` (new). Select Neo4j when the run's `neo4j.status=synced` and `CONFIG.neo4j_uri` is set; else fall back to the artifact. Response shape unchanged → existing viz tests stay green.
- This is the §4 item from `docs/knowledge-graph-viz-research.md` and the answer to the 1M-row scaling question (no 1.5 GB JSON parse per request).

### 5.3 Wire graph intents into `/qa`
- Add a `GRAPH_INTENTS` tuple parallel to `INTENTS` (`qa.py:375`). `answer_question` tries deterministic data intents first (unchanged), then graph intents when `neo4j_uri` is configured and the run is synced. Each graph intent: `matcher` (keyword test) + `handler` (calls a `graph_queries` function with the resolved `run_id`).
- `run_id` resolution: the `/qa` endpoint already resolves the latest run; pass its persisted `run_id` through to graph handlers. On cloud this is always present (verified: proof run has a real `run_id`).
- Unmatched/graph-unavailable → existing suggestion path, plus graph-specific suggestions ("which vendors share a bank account?").

### 5.4 Performance: batch the sync writer (prerequisite at scale)
- `neo4j_store._upsert_node`/`_upsert_edge` issue one `session.run` per element — ~1.7M round-trips at 1M invoices (hours). Before any large cloud dataset, convert to batched `UNWIND $rows AS row MERGE ...` (e.g. 1–5k rows/call) inside one transaction per batch. Contained to `neo4j_store.py`; the read plan above does not depend on it but the cloud target does.

### 5.5 UI
- Graph-query answers render in the chat thread like any other `/qa` answer (the chat+dashboard plan already handles `citations[]` and a "show in graph" affordance — `docs/chat-dashboard-ui-plan.md`). Entity-resolution clusters get a distinct system-message style (they're fraud signals).

## 6. Testing & acceptance

1. **`graph_queries` e2e** (gated on `STRATEGYOS_NEO4J_E2E_URI`): seed the fixture graph, assert each §4 query returns the known Tamween answer — e.g. `vendor_collusion_cluster` returns the V-1142/V-1187 pair; `vendor_finding_exposure(V-1142)` returns F-004.
2. **Degradation tests** (no Neo4j): every graph intent and the viz Neo4j source return the documented "not available" payload, never raise.
3. **Injection test:** a malicious `expand`/question value is passed as a parameter and cannot alter the query (assert allowlist + parameterization).
4. **Viz parity:** `GET /runs/latest/knowledge-graph` returns the same node/edge shape from Neo4j as from the artifact for the fixture run (existing viz tests green; add one comparing both sources).
5. **Suite:** full `pytest -q` green; `make poc-acceptance` untouched (detectors unchanged).
6. **Cloud acceptance:** on the full stack, ask the 5 graph questions in chat → each returns a cited answer; open the graph panel → served from Neo4j; confirm `state_store`/`neo4j` synced with a real `run_id` in `run_summary.json`.

## 7. Out of scope

- Moving detectors/finding-generation onto Cypher (separate effort).
- Text-to-Cypher / LLM query generation.
- Local-only mode (this plan is cloud-only by directive).
- Graph data science (GDS) algorithms, community detection — possible later once read paths exist.
- Qdrant changes (tracked separately; today's hashing embedding is non-semantic — see the store-optimization discussion).

## 8. Suggested commit sequence

1. `Add graph_queries module with run-scoped Cypher catalog + Neo4j e2e (gated)` — §5.1, §6.1–6.3.
2. `Serve knowledge-graph viz from Neo4j behind a source seam (artifact fallback)` — §5.2, §6.4.
3. `Wire graph-query intents into /qa with honest degradation` — §5.3, §6.5.
4. `Batch Neo4j sync writes with UNWIND for large cloud datasets` — §5.4.
