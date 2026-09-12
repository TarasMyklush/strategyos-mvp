# Next implementation increments from the 7 September direction

## Prioritized backlog

| Priority | Deliverable | Definition of done | Dependency |
| --- | --- | --- | --- |
| Closed P0 | History-derived decomposition | Deployed: one selected prior snapshot produces disclosed weights; adjustments bridge from history to proposal; missing values never become zero | Hosted acceptance recorded |
| Closed P0 | Organization/dimension structure | Deployed: guided immutable versions, independent approval, registered-source mappings and current approved structure bindings govern new plans | Hosted service and edge acceptance recorded |
| Closed P0 | Granular plan completion | Deployed: whole-objective multidimensional decomposition, per-cell drift/explanation, offset and concentration findings | Hosted service and edge acceptance recorded |
| Spec complete | Strategic Advisor console | Capture → configure → ratify workstreams, template outputs, gauges and missing-info routing are specified; implementation remains incremental | `strategic-advisor-console-spec.md` |
| Closed P1 | Board template registry and pack history | Deployed: tenant template versions and generated pack records are durable, permissioned, downloadable and stale-aware | Hosted acceptance recorded |
| Closed P0 | Synthetic outreach surface | Deployed: typed draft/approval/send/reply/flag lifecycle, structured outcomes and named people coverage with connector disabled | Hosted service and edge acceptance recorded |
| Closed P1 | Healthcare/pharma demo pack | Deployed: three synthetic stories run from governed evidence through cell drift and bilingual board pack, with sector details confined to configuration | Hosted acceptance recorded |
| Closed P1 | Price/volume/mix bridge | Deployed: exact, unit-safe bridge reconciles price, volume and mix effects to observed variance with direct input evidence | Hosted acceptance recorded |
| P2 | Executive adoption loop | One executive request creates an accountable owner task; reply proposes a governed update and closure remains reviewable | Advisor configuration and outreach workflow |
| Blocked | Minimal email connector | Allowlisted test-domain draft/send/reply/commitment path passes security and retention acceptance | Test domain access and connector credentials |

All currently unblocked P0 and P1 increments are deployed. The email connector is
the remaining blocked item and can start when test-domain access and credentials are available.

## 1. Plan decomposition: engine proposes, Vault records

Status: explicit, history-derived and whole-objective multidimensional slices are
implemented and hosted. They create a new immutable plan proposal from the latest
ratified parent, preserve the approved total exactly, record complete lineage,
expose the result on `/plan`, reuse independent ratification and block stale-parent
approval. Matching actuals produce cell drift, offset/concentration findings and
deterministic explanations for the board composer and executive Plan Health link.

Keep the approved plan of record in the Intent Vault. Put split computation in a
pure engine module so historical weights, seasonality and explicit adjustments
never mutate the approved record. The operator starts from a ratified total and
selects the product, region, channel and client dimensions. Each proposed cell
carries its owner, target, tolerance, evidence and allocation method.

Remaining decomposition backlog, in order:

1. Verify the separate seasonal-profile implementation in production: registered
   evidence, a disclosed factor per child, independent review, exact reconciliation
   and readable historical/seasonal evidence links. Candidate implementation and
   focused tests are recorded in `assessment/input-requirements-delivery-2026-09-12.md`.
2. Add large realistic dataset acceptance and client terminology review; concurrency,
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

The deployed configuration pack and synthetic evidence now cover the three stories
in the direction paper: regional miss offset by institutional business, commercial
mix hidden by aggregate growth, and regional miss linked to a credit hold. The mix
story carries history-derived plan lineage. Every story runs through deterministic
cell drift and the bilingual board composer, while all sector terms remain in the
configuration pack.

The deployed price/volume/mix engine requires explicit unit-tagged price and volume
source fields, uses a disclosed calculation order and reconciles exactly to observed
variance. Plan revenue, actual revenue, planned and actual price, and planned and
actual volume are separately openable from the product and board pack.

The remaining work in this section is the P2 executive adoption loop: demonstrate
an executive request pulling an accountable owner into the review, then close it
with a recorded response and approved change.

## 5. Minimal permissioned outreach connector

The connector-free `/outreach` surface is implemented and hosted. Its typed,
sector-neutral read model covers named provider coverage and every required state,
including approved send/re-ask events, structured commitment/forecast projections,
and unparseable/no-response risk flags. It is explicitly synthetic, performs no
external action, stores no raw reply text and has no business authority effect.

Once the proposed test domain and access are available, implement one bounded
outreach workflow: allowlisted test personas, draft, explicit approved send,
response extraction and evidence-backed proposed commitment update. Keep connector
credentials server-side, use least-privilege access, and store only the approved
structured extraction and provenance required by the agreed retention policy.
Do not make a connected domain or a received email sufficient authority to ratify
a target, update a forecast or widen access. Demonstrate who asked whom, what came
back and which proposed record changed. Keep the HTML demo available until the
real connector's end-to-end acceptance passes.
