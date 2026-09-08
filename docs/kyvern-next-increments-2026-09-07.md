# Next implementation increments from the 7 September direction

## Prioritized backlog

| Priority | Deliverable | Definition of done | Dependency |
| --- | --- | --- | --- |
| Closed P0 | History-derived decomposition | Deployed: one selected prior snapshot produces disclosed weights; adjustments bridge from history to proposal; missing values never become zero | Hosted acceptance recorded |
| P0 | Organization/dimension structure | Guided immutable versions, independent approval and plan bindings are deployed; finish hosted acceptance before closing | Registered source systems |
| P0 | Granular plan completion | Whole-objective/multi-level decomposition, per-cell drift, concentration and assistant citation acceptance on realistic data | Approved structure contract |
| Spec complete | Strategic Advisor console | Capture → configure → ratify workstreams, template outputs, gauges and missing-info routing are specified; implementation remains incremental | `strategic-advisor-console-spec.md` |
| Closed P1 | Board template registry and pack history | Deployed: tenant template versions and generated pack records are durable, permissioned, downloadable and stale-aware | Hosted acceptance recorded |
| P0 | Synthetic outreach surface | Full draft/approval/send/reply/flag lifecycle and people coverage work with the connector disabled | Typed outreach objects |
| P1 | Healthcare/pharma demo pack | Three synthetic stories run from governed evidence through cell drift and board pack, with sector details confined to configuration | History-derived decomposition for the mix story |
| P1 | Price/volume/mix bridge | Exact, unit-safe bridge reconciles price, volume and mix effects to the observed variance | Explicit price and volume source fields |
| P2 | Executive adoption loop | One executive request creates an accountable owner task; reply proposes a governed update and closure remains reviewable | Advisor configuration and outreach workflow |
| Blocked | Minimal email connector | Allowlisted test-domain draft/send/reply/commitment path passes security and retention acceptance | Test domain access and connector credentials |

P0 should be built and deployed in the order shown. The connector can move into P1
as soon as its dependency is available; the HTML demonstration remains the fallback.

## 1. Plan decomposition: engine proposes, Vault records

Status: explicit and history-derived slices are implemented and hosted. They
create a new immutable plan proposal from the latest ratified parent, preserve
the approved total exactly, record parent/engine/weight/evidence lineage, expose
the result on `/plan`, reuse independent ratification and block ratification if
the parent becomes stale. The proposal can then accept matching actuals, produce
granular drift and feed the board composer.

Keep the approved plan of record in the Intent Vault. Put split computation in a
pure engine module so historical weights, seasonality and explicit adjustments
never mutate the approved record. The operator starts from a ratified total and
selects the product, region, channel and client dimensions. Each proposed cell
carries its owner, target, tolerance, evidence and allocation method.

Remaining decomposition backlog, in order:

1. Add seasonality as a separate governed input from the already disclosed
   historical mix and explicit adjustment bridge.
2. Add whole-objective and multi-level decomposition across product, region,
   channel and client, with bounded proposal size and an approval view that groups
   the resulting cells without hiding any row.
3. Add large realistic dataset acceptance and client terminology review; concurrency,
   historical-unit mismatch and absent-history cases are already automated.

Acceptance: the sum of approved children equals the approved parent; every child
explains its derivation; a changed parent makes a pending proposal stale; neither
import nor decomposition can approve itself. Historical data is an allocation
input, not authorization to change board intent.

## 2. Strategic Advisor configuration console

The first objective/decomposition setup is implemented on `/plan`. The new
organization/dimension workstream adds sector-neutral immutable configuration,
registered-source mappings and independent tenant-admin approval. New plan imports
must bind to the current approved structure. The complete console remains an
incremental build governed by `strategic-advisor-console-spec.md`; the existing
surfaces are foundations, not full WP11 acceptance.

1. Capture company scope, executive sponsor, reporting period, source inventory,
   objectives and accountabilities using existing authorized records.
2. Configure required workstreams, metric/dimension dictionaries, tolerances,
   source mappings and the board template. Keep sector specifics in versioned packs.
3. Show readiness by workstream: supplied, valid, reviewed and ratified. Explain
   each blocking gap with a direct action; do not present ingestion as approval.
4. Preview configuration impact, record reviewer approval, publish a version and
   retain rollback/history. Keep permissions separate from presentation configuration.
5. Measure setup time, engineering intervention count, incomplete mappings and
   rework. Use those measurements to evaluate deployment cost and margin.

First acceptance: a strategy advisor configures a synthetic client and its board
review without editing JSON or opening an engineering ticket. A restricted user
cannot broaden source access through the console.

## 3. Remaining board composer depth

The durable tenant template registry and generated pack history are implemented.
Registered Advisor templates carry configuration provenance; every generated record
keeps its exact payload and rechecks source permission, evidence integrity and
freshness on reopen/download. Follow with reusable page layouts and claims/graph
narrative sections. Keep source bindings and stale warnings through each extension.
Validate client-approved English/Arabic terminology and representative long labels
before calling the complete client board pack ready.

## 4. Sector demonstration and adoption

Create a healthcare/pharma configuration pack and synthetic evidence for the three
stories in the direction paper: regional miss offset by institutional business,
tender win masking retail/margin erosion, and regional miss linked to credit hold
and receivables. Add evidence and calculations before narrative. Demonstrate an
executive request pulling an accountable owner into the review, then closing the
loop with a recorded response and approved change.

Price/volume/mix requires explicit price, volume and mix inputs and a reconciled
bridge. Current variance and offset detection do not implement that attribution.

## 5. Minimal permissioned outreach connector

Once the proposed test domain and access are available, implement one bounded
outreach workflow: allowlisted test personas, draft, explicit approved send,
response extraction and evidence-backed proposed commitment update. Keep connector
credentials server-side, use least-privilege access, and store only the approved
structured extraction and provenance required by the agreed retention policy.
Do not make a connected domain or a received email sufficient authority to ratify
a target, update a forecast or widen access. Demonstrate who asked whom, what came
back and which proposed record changed. Keep the HTML demo available until the
real connector's end-to-end acceptance passes.
