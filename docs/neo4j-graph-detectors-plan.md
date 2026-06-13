# Neo4j Graph Detectors Plan — generate new findings from the graph (cloud)

**Date:** 2026-06-12
**Status:** Commits 1–3 implemented 2026-06-12 (Option A, in-process structural graph). Commit 4 is a no-op for the Tamween fixture (see below). Backlog detectors (§2) remain open.
**Scope:** cloud deployment only (full stack with Neo4j synced). Local-only runs out of scope. NOTE: Option A executes graph detectors in-process at the analyst stage, so the first detector (`vendor_collusion_ring`) already works on local AND cloud runs — it does not require Neo4j to be up. Neo4j remains the read/serve layer.

**As-built (2026-06-12):**
- §4.1 `build_structural_graph` + `StructuralGraph` (neighbor/edge queries) extracted in `knowledge_graph.py`; `build_knowledge_graph` reuses it.
- §4.2 `strategyos_mvp/skills/graph_controls.py`: `@register_graph_detector` + `GRAPH_DETECTOR_REGISTRY` + `detect_vendor_collusion_ring` (connected-component over SAME_BANK_ACCOUNT_AS/SAME_TAX_ID_AS, size ≥3).
- §4.3 `run_all_finance_skills` calls `_run_graph_detectors` after row detectors (lazy import to avoid circular dep); graph detectors appear in `detector_report.executed_detectors` with `engine: "graph"`; clean skip on missing roles or graph-build failure.
- §4.4 **No answer-key change needed:** the Tamween fixture has only a 2-vendor shared-identifier component (V-1142/V-1187), which stays with pairwise F-004. The ring detector (size ≥3) correctly fires 0 findings on the fixture, so `make poc-acceptance` stays 8/8 unchanged. Verified.
- Tests: `tests/test_graph_controls.py` (registry, pair-only=silent, injected 3-vendor ring = one finding covering all three, ≥3 citations). `tests/test_detector_registry.py` updated to isolate the graph registry. Full suite 207 passed / 2 skipped.
**Depends on:** `docs/neo4j-utilization-plan.md` (the read-only slice — graph query layer, source seam). This plan is the explicitly-named "later step": graph-native detectors that **write new findings back to Postgres**.
**Audience:** any developer or LLM agent implementing this cold. Verify every code reference before relying on it; update this doc on drift.

---

## 1. What this changes (and what the prior slice did not)

The Neo4j read slice added retrieval/explanation, not detection: still 8 findings, just traversable. Confirmed framing:

- **Before & after the read slice:** detectors produce 8 findings (incl. F-004 entity-resolution); Neo4j only lets us *read* the relationships behind them. Zero new findings.
- **This plan:** add detectors that **run Cypher over the graph** and emit `Finding` objects through the same registry/contract as the existing row-wise detectors, so they flow into ranking, auditor challenge, evidence QA, citation audit, deliverables, and Postgres persistence with no special-casing.

The point: pandas detectors are row/pair-shaped. They structurally cannot find **multi-hop and ring patterns**. The graph can. This is net-new leakage detection, not re-explanation.

## 2. Why graph detectors find things row detectors can't (verified against the data)

The synced graph already carries the edges these need: `SAME_BANK_ACCOUNT_AS`, `SAME_TAX_ID_AS` (built by `knowledge_graph.entity_resolution_edges`, neo4j_store syncs them), plus `INVOLVES_VENDOR`, `ISSUED_INVOICE`, `MATCHES_PO`, `HAS_CONTRACT`, `SUPPORTED_BY`, `SHARES_APPROVER` (add if absent).

Today F-004 (`detect_entity_resolution_duplicates`, finance_controls.py:387) only catches **direct pairs** sharing an identifier. The graph generalizes this to patterns that are expensive or impossible in pandas:

| New detector (pattern_type) | Graph pattern only the graph sees | Why pandas can't | Leakage |
| --- | --- | --- | --- |
| `vendor_collusion_ring` | 3+ vendors transitively connected via SAME_BANK_ACCOUNT_AS / SAME_TAX_ID_AS (connected component, not just pairs) | transitive closure over N vendors = graph traversal; pandas does pairwise only (today's F-004) | duplicate/split spend across a ring |
| `circular_payment_flow` | vendor→invoice→…→same beneficiary cycle | cycle detection is a graph primitive | round-tripping / kickback signal |
| `shared_approver_concentration` | one approver across vendors with no contract, weighted by spend | multi-entity join + structural centrality | control-override risk |
| `evidence_reuse_conflict` | one Evidence node supporting findings that contradict (e.g. same invoice cited as paid and unpaid) | requires the finding↔evidence↔finding triangle | double-counted recovery |
| `split_purchase_evasion` | one vendor, many POs each just under an approval threshold, same SKU/window | window+threshold grouping across the PO subgraph | approval-limit circumvention |

Implement at least `vendor_collusion_ring` (the clearest graph-beats-rows case, a true superset of F-004) and one more; the rest are a backlog.

## 3. The hard ordering problem (this is the crux)

Current pipeline order (verified): `analyst → auditor → evidence_qa → knowledge_graph → writer` (`workflow.py`). Findings are produced in the **analyst** stage (`run_all_finance_skills`, finance_controls.py); the graph is built/synced in the **knowledge_graph** stage, *after*. So graph detectors cannot run inside the current analyst stage — the graph doesn't exist yet, and Neo4j isn't synced until `run_poc.py:377`.

`build_knowledge_graph(bundle, findings)` (knowledge_graph.py:30) is a **pure function**. Two options:

- **Option A — in-process graph, recommended for v1.** Build the structural graph (everything except `finding_nodes`) once at the start of the analyst stage, run graph detectors against that in-memory graph (NetworkX or a light adjacency structure — `entity_resolution_edges` logic is reusable directly), and merge their `Finding`s with the row detectors before ranking. No dependency on Neo4j being up; works identically on any backend; deterministic and unit-testable offline. Neo4j remains the read/serve layer (prior plan), not a detector dependency.
- **Option B — query synced Neo4j.** Add a post-graph detector stage that runs Cypher against the synced graph and feeds findings back. Truer to "detectors run Cypher," but: introduces a hard Neo4j runtime dependency into finding generation (violates the clean-degradation property the app is careful about), requires a second findings-merge + re-rank + re-ID pass after `knowledge_graph`, and re-opens the auditor/evidence stages on the new findings.

**Decision: Option A for v1.** Same graph algorithms, same Cypher-expressible patterns (express them in Cypher in `docs` for parity/documentation), but executed in-process so finding generation stays backend-independent and the existing stage order is untouched. Option B becomes viable later once detectors are routinely DB-side at 1M-row scale — record it as the scale path, don't build it now.

## 4. Implementation

### 4.1 Reusable structural graph (`knowledge_graph.py`)
- Extract a `build_structural_graph(bundle)` that produces the node/edge set **without** `finding_nodes` (i.e. everything graph detectors need, available before findings exist). `build_knowledge_graph` keeps its current signature and reuses it. Return an in-memory graph object exposing neighbor/edge-label queries (NetworkX `MultiDiGraph` is fine; it's already an indirect dep, confirm before adding).
- Add `SHARES_APPROVER` edges if the chosen detectors need them and they aren't built yet.

### 4.2 Graph detector registry (`strategyos_mvp/skills/graph_controls.py`, new)
- Mirror the row-detector contract exactly so findings are first-class: a `@register_graph_detector(pattern_type, required_roles)` that appends to the **same** `DETECTOR_REGISTRY` used by `run_all_finance_skills` (finance_controls.py), OR a parallel `GRAPH_DETECTOR_REGISTRY` consumed in the same loop. Each detector: `(graph, bundle) -> list[Finding]`, returns standard `Finding` objects (models.py) with `pattern_type`, `recoverable_sar`, `confidence`, `rationale`, `remediation`, `calculation`, and **citations to the Evidence nodes** reached in the traversal (so the citation audit and ≥3-citation gate pass unchanged).
- `KNOWN_PATTERN_TYPES` already derives from the registry — new graph pattern types register automatically; the open `pattern_type: str` model (models.py) accepts them.

### 4.3 Wire into the analyst stage
- In `run_all_finance_skills` (finance_controls.py): after row detectors, build the structural graph once and run graph detectors against it; extend the same `findings` list **before** the sort/re-ID block, so graph findings get ranked and `F-NNN` ids identically. `detector_report` gains the graph detectors in `executed_detectors`/`skipped_detectors` with their `required_roles` (so partial-run skip works the same way).
- Net effect downstream: auditor challenges them, evidence QA validates them, knowledge_graph stage links them, citation audit checks them, Postgres persists them — **zero special-casing**, because they are ordinary `Finding`s.

### 4.4 Acceptance-gate impact (must handle deliberately)
- New detectors firing on the Tamween fixture **change the finding count and total recoverable SAR** → the fixture-regression gate (`tests/fixtures/tamween_answer_key.json`, `poc_acceptance.py`) will fail until updated. This is expected and is exactly why the gate was split (fixture-regression vs generic-health). Process: (1) implement detectors, (2) review the new fixture findings for correctness, (3) update `tamween_answer_key.json` `expected_pattern_types` + `expected_total_recoverable_sar` **with a documented reason in the commit**, (4) generic-health gate (≥3 citations, reproducible calc, resolution-rate) must pass unchanged for the new findings too. Never weaken the gate to pass — update the answer key intentionally.

### 4.5 Citations & evidence for graph findings
- A graph finding's evidence is the structured sources of the nodes in its pattern (vendor master rows, AP rows, contract PDFs). Reuse `excel_citation`/`pdf_citation` helpers (finance_controls.py) keyed off the node `node_key`s the traversal returns. The fail-closed evidence policy (`apply_fail_closed_evidence_policy`) already withholds findings that can't meet the bar — graph findings go through it unchanged.

## 5. Cloud / scale notes
- Option A holds the structural graph in memory: fine at thousands–~100k nodes; at 1M-invoice scale the structural subgraph for these detectors (vendors+contracts+approvers, not the invoice bulk) stays small, but cycle/ring detection cost grows — cap component size and degree, and document Option B (Cypher against synced Neo4j with `apoc`/GDS) as the scale path.
- Batched Neo4j sync (`UNWIND`, from the read-plan §5.4) is still the write-side prerequisite for large datasets; unrelated to detector execution under Option A.

## 6. Testing & acceptance
1. **Unit (offline, no Neo4j):** seed a synthetic bundle with a known 3-vendor bank-account ring → `vendor_collusion_ring` returns one finding covering all three; assert it's a strict superset of what pairwise F-004 catches. Cycle/approver detectors similarly with crafted fixtures.
2. **Citations:** each graph finding carries ≥3 resolvable citations to real Evidence/structured rows; citation-resolution-rate gate stays green.
3. **Pipeline integration:** full run on the fixture → graph findings appear in `run_summary.json` `detector_report.executed_detectors`, get `F-NNN` ids, are challenged by the auditor, and persist to Postgres (cloud) with a real `run_id`.
4. **Fixture gate update:** `make poc-acceptance` green **after** the answer-key update; generic-health green throughout; diff of new findings reviewed in the PR.
5. **Degradation:** with the structural-graph build failing or empty, graph detectors skip cleanly (reported in `skipped_detectors`), row findings unaffected.
6. **Full suite** `pytest -q` green.

## 7. Out of scope
- Option B (live-Neo4j detector stage) — documented as scale path, not built.
- GDS / community-detection libraries (possible once Option B exists).
- Text-to-Cypher / LLM detection.
- Changing existing row detectors (graph detectors are additive; F-004 stays — `vendor_collusion_ring` generalizes it but both can coexist, or retire F-004 only after the ring detector is proven a superset).
- Local-only mode.

## 8. Suggested commit sequence
1. `Extract build_structural_graph and expose in-memory graph queries` — §4.1, unit-tested.
2. `Add graph_controls detector registry + vendor_collusion_ring detector` — §4.2, §6.1–6.2.
3. `Run graph detectors in analyst stage and merge findings` — §4.3, §6.3, §6.5.
4. `Update Tamween answer key for graph-detector findings (documented)` — §4.4, §6.4.
5. (backlog) additional graph detectors from §2 table, one per commit.
