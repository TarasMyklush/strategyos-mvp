# Next implementation increments from the 7 September direction

## 1. Plan decomposition: engine proposes, Vault records

Status: the first explicit-weight slice is implemented and locally verified. It
creates a new immutable plan proposal from the latest ratified parent, preserves
the approved total exactly, records parent/engine/weight/evidence lineage, exposes
the result on `/plan`, reuses independent ratification and blocks ratification if
the parent becomes stale. The proposal can then accept matching actuals, produce
granular drift and feed the board composer.

Keep the approved plan of record in the Intent Vault. Put split computation in a
pure engine module so historical weights, seasonality and explicit adjustments
never mutate the approved record. The operator starts from a ratified total and
selects the product, region, channel and client dimensions. Each proposed cell
carries its owner, target, tolerance, evidence and allocation method.

Remaining decomposition backlog, in order:

1. Add history-derived weights from one explicitly selected prior actual snapshot,
   plus seasonality and operator adjustments as separate inputs. Show the bridge
   from historical mix to proposed weight; never infer a weight from a missing value.
2. Replace allocation-row JSON with guided editable rows, source selection and
   completeness checks in the Strategic Advisor console.
3. Add whole-objective and multi-level decomposition across product, region,
   channel and client, with bounded proposal size and an approval view that groups
   the resulting cells without hiding any row.
4. Add concurrency pressure, historical-unit mismatch, absent-history and large
   realistic dataset acceptance, followed by client terminology review.

Acceptance: the sum of approved children equals the approved parent; every child
explains its derivation; a changed parent makes a pending proposal stale; neither
import nor decomposition can approve itself. Historical data is an allocation
input, not authorization to change board intent.

## 2. Strategic Advisor configuration console

Extend the existing source intake, configuration and governance controls into one
guided client setup flow. Start with durable configuration versions, not a second
set of business calculations.

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

The initial composer is a saved-analysis performance review with portable template
files. Add a durable tenant template registry and pack history, followed by reusable
page layouts and claims/graph narrative sections. Keep source bindings and stale
warnings through each extension. Validate client-approved English/Arabic terminology
and representative long labels before calling the complete client board pack ready.

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
