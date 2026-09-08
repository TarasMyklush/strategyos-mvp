# Strategic Advisor configuration console specification

Status: WP11 specification for review, 8 September 2026. The organization and
dimension workstream described below has an implemented first slice in the Intent
Vault; the rest of this document is the product contract for later increments.

## Purpose and operating model

The console turns client setup into a Strategy Advisor activity that does not
depend on engineering tickets. It uses one common client catalog. Selecting a
client opens a project space with governed client documents on one side and a
fixed set of guided workstreams on the other. The system may ask structured
follow-up questions, but it does not expose a free-form configuration chat.

The pipeline is **capture → configure → ratify**. Capture indexes and digests the
Discovery Pack. Configure converts advisor answers into validated declarative
records. Ratify asks an independently authorized client reviewer to approve an
immutable version. Ingestion, validation and advisor review never imply client
approval.

## Common configuration envelope

Every workstream produces a record with this envelope:

```json
{
  "schema_version": 1,
  "configuration_type": "organization-structure",
  "configuration_id": "client-primary",
  "version": 1,
  "tenant_id": "derived-from-session",
  "status": "ready_for_ratification",
  "payload": {},
  "source_bindings": [{"source_key": "registered-source", "digest": "derived"}],
  "created_by": "derived-from-session",
  "created_at": "server-time",
  "digest": "server-derived"
}
```

Tenant, actor, timestamps, registered source identities, access policy and digest
are server-derived. The advisor supplies only the typed payload. Versions are
consecutive and append-only. Approval is a separate record containing the exact
configuration digest, reviewer identity, review note and server time. Sector terms
and client vocabulary remain in payloads and configuration packs, never in core
code.

## Predetermined workstreams and outputs

| Workstream | Guided flow | Versioned template produced |
| --- | --- | --- |
| Discovery digest | Select captured documents; resolve classification and missing core context | `DiscoveryContext`: company identity, reporting period, source references, stated constraints and unresolved questions |
| Objectives, KPIs and owners | Confirm each objective, metric, direction, unit, period, owner and approver | `IntentDefinition`: objective graph, KPI dictionary, accountable owners and ratification path |
| Organization and dimensions | Define business units, dimension/member hierarchies and registered-source value mappings | `TenantStructureConfiguration`: the implemented WP7b schema, consumed by plan import and decomposition |
| Thresholds and materiality | Enter effective thresholds by metric/scope; preview deterministic classification examples | `MaterialityPolicy`: unit-safe tolerances, escalation bands, effective period and approval evidence |
| Data-source contracts | Select registered source or named provider; set expected cadence, freshness and responsibility | `DataSourceContract`: source type, KPI/property, cadence, freshness threshold, provider and outreach policy |
| Authority matrix | Assign view, analyse, recommend and act-with-approval rights by role, scope and tool | `AuthorityPolicy`: explicit grants, approver chains, effective period and policy version |
| Context pack | Select ratified configuration records and approved client terminology | `ContextPackDefinition`: bounded facts, definitions, exclusions, source bindings and expiry |
| Board-pack template | Choose sections, persona scope, language and client terminology | `BoardTemplate`: ordered sections, persona scope and bilingual display config; figures remain graph/evidence bindings |

WP7b is authored through the Organization and dimensions workstream. The guided
form writes `TenantStructureConfiguration` directly, validates hierarchy and full
mapping coverage, resolves source keys against registered systems, and requires
independent tenant-admin approval. WP8b follows the same envelope and approval
pattern for `DataSourceContract`; connector credentials and mailbox permissions
remain outside the console payload.

## State and gauge logic

Each required workstream advances through four objective states:

| State | Score | Condition |
| --- | ---: | --- |
| Not supplied | 0 | No saved version |
| Supplied | 25 | A version exists |
| Valid | 50 | Schema, source bindings and cross-record checks pass |
| Reviewed | 75 | Advisor records completion and all blocking questions are resolved |
| Ratified | 100 | An authorized independent reviewer approves the exact digest |

The workstream gauge displays the current state and blocking checks. The basic
go-live score is the arithmetic mean of the latest required workstream scores,
shown with its denominator. Go-live is **Ready** only when every required
workstream is ratified; optional workstreams appear separately and cannot inflate
readiness. A superseded dependency or revoked source access moves the affected
workstream to **Action required** while preserving its historical approval.

## Missing-information routing

Validation and live operation emit a typed `ConfigurationGap` containing tenant,
workstream, affected object, question, reason, severity, detected time, source
reference when available and suggested advisor action. The routing service assigns
the gap to the client's Strategy Advisor and displays it in the client project
space. The advisor can link a captured document, enter a typed value, start a named
provider outreach under WP8, or mark the item inapplicable with review evidence.
Only a new validated and ratified configuration version closes a ratification-level
gap. Engineering receives product defects and unsupported schema capabilities;
ordinary missing client context remains with the advisor.

## Ongoing mode

After go-live, the advisor sees a permission-scoped mirror of the client's current
dashboard, configuration freshness, open gaps and recent ratified versions. A test
question runs against the same tenant scope and evidence rules as the client's
product; test output is labelled and cannot issue actions. Missing-information
flags from KPI evaluation and outreach link back to the workstream and exact
configuration property that needs attention.

## Acceptance and operating measures

Acceptance requires a Strategy Advisor to configure a synthetic client through all
required workstreams without editing JSON or requesting engineering changes. Tests
must prove immutable version history, independent approval, source-policy
non-escalation, sector neutrality, deterministic gauges, missing-gap routing and
successful use of approved WP7b and WP8b records. Product analytics record setup
elapsed time, advisor rework, unresolved mappings and engineering interventions so
deployment cost and margin can be measured.

## Roadmap: partner command center

The same catalog and guided workstream model can later become a delivery surface
for authorized implementation partners such as consultancies and ERP implementers.
Partner tenancy, commercial controls and cross-client administration require a
separate design and are outside this specification.
