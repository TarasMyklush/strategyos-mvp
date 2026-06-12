# Knowledge Graph Visualization — Research & Recommendation

**Date:** 2026-06-12
**Status:** Researched recommendation, ready to implement (companion to `docs/chat-dashboard-ui-plan.md`)
**Decision:** Cytoscape.js, vendored as a single local file, rendering a findings-centric subgraph with expand-on-click.

## 1. The data (measured from the real artifact)

`StrategyOS Knowledge Graph.json` (per run, ~2 MB): `{meta, nodes[], edges[]}`.
Nodes: `{id, label, properties}` — 2,360 total: Invoice 1,396, PurchaseOrder 600, Vendor 210, SKU 98, Evidence 42, Finding 8, Contract 6.
Edges: `{source, target, label, properties}` — 5,723 total: SOURCED_FROM 2,206, ISSUED_INVOICE 1,396, MATCHES_PO 871, ORDERS_SKU/ISSUED_PO 600 each, SUPPORTED_BY 31, INVOLVES_VENDOR 9, HAS_CONTRACT 6, SAME_BANK_ACCOUNT_AS/SAME_TAX_ID_AS 2 each.

**The controlling insight:** the analytical value lives in a tiny layer. Findings + their evidence + vendors + contracts + entity-resolution (SAME_*) edges = **39 nodes / 47 edges** (measured). The other ~2,300 nodes are transactional bulk (invoices/POs per vendor) that destroys any full-graph rendering ("hairball"). One naive 1-hop expansion from findings already pulls 2,236 nodes because vendors drag all their invoices.

Therefore the UX is **not** "render the graph" but "render the findings constellation, expand on demand":
- Default view: Finding/Evidence/Vendor/Contract nodes + SUPPORTED_BY/INVOLVES_VENDOR/HAS_CONTRACT/SAME_* edges. Findings sized by `recoverable_sar`; SAME_* edges styled as the fraud signal (red dashed). Vendor invoice-count shown as a badge, not as nodes.
- Tap a vendor → expand its invoices/POs (capped, e.g. top 25 by amount, "+N more").
- This works for any future dataset because it's driven by node labels, not Tamween specifics.

## 2. Options evaluated

| Option | License | Fit | Verdict |
| --- | --- | --- | --- |
| **Cytoscape.js** | MIT | Single UMD file (~360 KB min) served locally, zero build, canvas renderer comfortable to ~5k elements, selector-based styling maps directly to node labels, expand/collapse trivial, graph algorithms included. v3.34.0 released June 2026; monthly feature / weekly patch cadence; ~500k weekly downloads | **Recommended** |
| vis-network | MIT/Apache-2.0 | Simplest API of all, single standalone file; community-maintenance mode, heavier file, perf degrades past ~2k nodes | Solid runner-up if Cytoscape's API feels heavy |
| Sigma.js v3 + graphology | MIT | WebGL, scales to 100k+ nodes; ESM/bundler-oriented — friction with the no-build constraint | Only if full-graph rendering ever becomes a requirement (it shouldn't) |
| force-graph (vasturiano) | MIT | Tiny API, single file, d3-force; weaker styling/selector model | Fine for a quick spike, less room to grow |
| D3.js force | ISC | Build-everything-yourself | Most work, not "easiest" |
| ECharts graph series | Apache-2.0 | Works, but graph interaction is not its core | No advantage here |
| G6 (AntV) | MIT | Capable but heavy, larger API surface | Unneeded complexity |
| neovis.js / Neo4j Browser | MIT / — | Render straight from Neo4j. **Rejected as primary:** canonical local runs skip Neo4j (`neo4j.status=skipped`); the artifact JSON is the only always-present source. Neo4j Browser (already in compose at :7474) stays the free **ops-level** explorer when the full stack is up | Secondary only |
| pyvis (Python) | BSD | Generates a self-contained interactive HTML file — zero JS work. Use `cdn_resources="in_line"` to keep it CDN-free | Optional Phase-0 quick win: emit `Knowledge Graph.html` as a run artifact from the writer stage |
| Gephi / Graphistry / yFiles / Linkurious | mixed/commercial | Desktop tool / GPU SaaS / commercial licenses | Out of scope |

Constraints that drove the decision (from `docs/chat-dashboard-ui-plan.md` §2–3): vanilla JS, **no build toolchain, no CDN at runtime** (VPN-only deployment, sovereignty), all assets served by the app, no new heavy backend.

## 3. Implementation spec (≤1 day on top of UI-plan Phase 1)

1. **Vendor the library:** download `cytoscape.min.js` (latest 3.x) into `strategyos_mvp/static/vendor/`, served by the existing StaticFiles mount. License (MIT) permits redistribution; keep the license header in the file. Implemented with Cytoscape.js `3.34.0`; SHA-256 `9c2a3bf2592e0b14a1f7bec07c03a54f16dedf32af9cd0af155c716aa6c87bc3`.
2. **Backend (additive only):** `GET /runs/latest/knowledge-graph?view=findings|full&expand=<node_id>` in `api.py`:
   - reads the run's `StrategyOS Knowledge Graph.json` (path from run summary `artifacts.knowledge_graph`),
   - `view=findings` (default): the 39-node constellation per §1, with `invoice_count` per vendor computed server-side,
   - `expand=<vendor_id>`: that vendor's invoices/POs capped at 25 by amount + `truncated: N`,
   - response shape: `{nodes:[{id,label,display,sublabel,recoverable_sar?}], edges:[{source,target,label}]}` — already UI-shaped, keep the 2 MB raw artifact out of the browser. Operator/reviewer role required, same as `/runs/latest`.
3. **Frontend:** a "Graph" panel in the chat+dashboard shell (`docs/chat-dashboard-ui-plan.md` §6 — add it to the component table). Style by `label` selector: Finding coral circles sized by SAR, Vendor teal circles, Evidence gray round-rects, Contract purple diamonds, SAME_* edges red dashed. Layout: built-in `cose` (good enough at this scale; `fcose` extension optional later). Tap finding → highlight its neighborhood + show the finding card; tap vendor → call `expand=` and add nodes incrementally.
4. **Chat integration (cheap, high value):** Q&A answers that reference a finding get a "show in graph" chip that opens the graph panel centered on that finding.
5. **Tests:** endpoint contract test (findings view returns exactly the label/edge whitelist; expand caps at 25; 401 without role); shell test asserts `#kg-panel` hook + local vendor script path (and that no external origins appear in served HTML).

## 4. Scaling to millions of rows (added 2026-06-12)

Measured baseline: 1,396 invoices → 2,360 nodes / 5,723 edges → 1.9 MB artifact (≈251 bytes/element). Linear projection:

| Dataset | Graph | Artifact JSON |
| --- | --- | --- |
| 1,396 invoices (today) | 2.4k nodes / 5.7k edges | 1.9 MB |
| 100k invoices | ~170k nodes / ~410k edges | ~0.15 GB |
| 1M invoices | ~1.7M nodes / ~4.1M edges | ~1.5 GB |

**What survives unchanged:** the findings-centric view and the entire frontend. The rendered element count is bounded by *findings* (8 findings → 39 nodes) plus capped expansions — it does not grow with dataset size. Cytoscape never sees more than a few hundred elements regardless of scale. The endpoint contract (`view=findings`, `expand=<id>` capped) is scale-proof.

**What must swap above ~50k nodes (~12 MB artifact):** the endpoint's data source. Parsing the artifact JSON per request stops being viable. Replace it with a store-backed query — both stores are ALREADY in the architecture:
- **Postgres KG mirror:** `strategyos_kg_nodes` / `strategyos_kg_edges` (deploy/postgres/schema.sql:331,342) with label indexes (schema.sql:372–373). The findings view is one label-filtered indexed query; vendor expand is one edge query with `LIMIT 25`.
- **Neo4j:** same queries in Cypher when the full stack runs.

**Implementation requirement:** build the §3.2 endpoint behind a small data-access seam (`KnowledgeGraphSource` with `findings_view()` / `expand(node_id, cap)`), with two implementations: `ArtifactJsonSource` (today) and `PostgresKGSource` (later). The swap then never touches the UI.

**Adjacent 1M-row realities (outside viz scope but flag them now):**
1. The KG JSON artifact itself (~1.5 GB at 1M invoices) should become optional/summary-only above a threshold — the stores become the KG of record.
2. Neo4j/Postgres KG sync must be batched (`UNWIND` batches / `COPY`); per-row writes take hours at that scale.
3. Intake: `.xlsx` has a hard 1,048,576-row cap — million-row ledgers must arrive as CSV (already a supported source-pack format) or as a DB extract; openpyxl on huge workbooks costs minutes.
4. The pandas in-memory detector model holds at ~1M rows (a few hundred MB) but is tight on an 8 GB shared VM alongside Neo4j — DB-side detector queries are the eventual move, not a v1 concern.

## 5. Verification of claims in this doc

- Graph shape/counts: measured directly from `outputs/StrategyOS Active Run Evidence/StrategyOS Knowledge Graph.json` on 2026-06-12.
- Cytoscape.js maintenance: v3.34.0 (June 2026), monthly/weekly release cadence — js.cytoscape.org and the cytoscape/cytoscape.js GitHub releases page.
- Library comparison: PkgPulse 2026 comparison and Cylynx JS graph-library survey (Cytoscape ≈500k weekly downloads vs vis-network ≈200k; Sigma.js positioned for 100k+ node WebGL rendering).
