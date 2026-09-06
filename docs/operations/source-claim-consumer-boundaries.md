# Source-and-claim consumer boundaries

This is a code-audit register, not a universal completion certificate. It records
the boundary protecting a surface, including surfaces intentionally unavailable.
Preview deployment and cross-role browser evidence must be recorded separately.

| Consumer | Current boundary | Remaining work |
| --- | --- | --- |
| Claim query, snapshot and source intake APIs | Claim repository: current tenant/role/BU/purpose, immutable revisions, source occurrences, runtime eligibility | Complete mapping of legacy business semantics; steward decisions cannot be invented |
| Claim graph/vector/cache projections | Canonical revision IDs; outbox; authoritative recheck after candidate retrieval | Operational SLO and ownership sign-off |
| Diagnostics, legacy charts and business prose | Whole-run source authorization plus canonical headline snapshot overlay | Full per-claim view-model adoption remains incomplete; do not describe whole-run denial as granular parity |
| Raw source previews/downloads and review files | Current source/export authorization; unregistered attachments are unavailable | Retention and erasure policy decision |
| Closed board packet list/read/question/download | Frozen content with current source policy; download requires export rights | Online regression acceptance; no real meeting closed for QA |
| Existing twin saved state and interactive tools | Authorized analysis and actor/tenant/role/BU namespace; current rights at request boundary; legacy root files not inherited | Durable authority envelope and explicit release rules for cross-actor/background work |
| Twin background scheduler | Disabled on preview; disabled entry points do not open state | Implement initiating authority, expiry, run binding and retry-time reauthorization before enabling |
| Experimental `/api/v1/agent-conversations`, tasks, network, approvals and stream | Existing default-off feature gates explicitly pinned off on preview | Tenant-level event/task projections are not a per-source grant; implement event-level source/actor authority before enabling |
| Existing Hermes generated-answer browser fallback | Removed; unavailable request cannot become a cached sourced-looking success | None for this retired fallback |
| Private `/api/conversation-state` | Actor/run/persona ownership plus current source rights for reads and writes; runtime persona refusal enforced | Review persisted content classification/retention, without deleting audit/history by default |
| Browser persisted conversation display | Same-run refresh rechecks permission; denial clears displayed private history, not server history | Full online revocation/display acceptance |

The experimental agent API flags do not disable the existing Hermes chat routes
or the newly scoped twin API. Their default was already off; explicitly writing
the values prevents stale deployment configuration from enabling an unaudited
parallel data path. No production flags are changed by this preview workflow.

Migration 0012 adds database rejection of in-place updates/deletes of claim
revision and assessment rows; corrections and review changes must append records.
It does not claim to prevent a privileged database owner from altering DDL or
truncating tables. Runtime role separation/RLS remains required. No administrative
erasure bypass or retention period is invented by this change; authorized disposal
needs a separately reviewed, audited procedure. No existing claim is deleted.

Do not use a blank optional saved-activity surface as proof of an empty business
agenda. It must say unavailable without fabricated zero counts. Business
priorities remain sourced from the authorized briefing's Decisions for you.

## Open governance inputs

The system must retain unknown states until a steward supplies actual/estimate
boundaries for historical finance imports, business source-priority policies,
forecast acceptance scopes and review dates, source rights, and retention/erasure
requirements. Synthetic QA settings do not supply these business decisions.
