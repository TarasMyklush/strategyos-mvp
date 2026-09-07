# Next implementation increments from the 7 September direction

## 1. Plan decomposition: engine proposes, Vault records

Keep the approved plan of record in the Intent Vault. Put split computation in a
pure engine module so historical weights, seasonality and explicit adjustments
never mutate the approved record. The operator starts from a ratified total and
selects the product, region, channel and client dimensions. Each proposed cell
carries its owner, target, tolerance, evidence and allocation method.

Implement in this order:

1. Add a strict decomposition request contract: approved parent plan/version/digest,
   metric and period, allocation dimensions, historical snapshot revision, explicit
   weights where no history exists, decimal precision and owners. Reject mixed units,
   duplicate tuples, zero total weights and missing owners. No invented historical
   values or automatic distribution through unknown cells.
2. Add deterministic allocation with exact decimal reconciliation and a disclosed
   remainder rule. Preserve the approved total exactly. Record method/version,
   source revisions, weights and any operator override separately from result cells.
3. Persist the proposal and its lineage in append-only tenant tables. Carry parent
   digest and historical evidence references. Recheck authorization at calculation,
   read and ratification, including export restrictions.
4. Extend `/plan` with a decomposition review: total, proposed cells, unexplained
   allocation gaps and changed assumptions. Reuse named, independent ratification.
   A proposal becomes a Vault plan version only after explicit approval.
5. Run missing-history, conflicting-unit, tiny-remainder, source-revocation,
   concurrent-ratification, cross-tenant and hosted synthetic workflow checks.
   Deploy as one complete propose → review → ratify → drift → board-pack increment.

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
