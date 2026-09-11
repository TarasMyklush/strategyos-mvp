# Kyvern governed external research and Bedrock implementation plan

Date: 2026-09-11  
Status: closed-template Research Gateway, audit, UI disclosure and Bedrock transport implemented locally; hosted acceptance pending.  
Code baseline inspected: `616c2cdc128475af50d7895e51bfaf4c562124d8`. This review inspected local source, not live infrastructure.

## 1. Outcome and claim boundary

Implement an actual external research capability that can obtain useful public evidence while preventing confidential client content from entering search, crawler or external connector requests. Separately implement and attest a Bedrock inference deployment. A Bedrock switch alone does not meet the research requirement.

The previous implemented-state response was hypothetical, not an implementation receipt. Do not publish it as a verified security statement until the release gates in this plan pass. The current implementation deliberately reports external research as used only after a completed gateway request and durable audit.

There is a logical conflict in the previous wording: “no confidential client context leaves” cannot hold if an approval can authorise sending confidential context. Resolve this in the first release by making confidential-context egress non-overridable. Human review can approve a safe public query or deny research; it cannot bypass the public-data boundary. Any future deliberate disclosure feature must be a separately named mode, with different claims and acceptance.

Even a generic query reveals a topic of interest, and its timing, geography, provider account and network address can be identifying. Do not promise that no client context or metadata of any kind is observable. The defensible target is: external recipients receive only approved public research terms and necessary transport metadata, never raw client questions, private evidence or confidential business facts. Where topic disclosure itself is unacceptable, use scheduled public-source collection independent of client questions, or keep external research disabled.

## 2. Verified starting points

| Existing surface | Finding and implementation implication |
| --- | --- |
| `strategyos_mvp/llm_qa.py` | Evidence-bearing model requests use an OpenAI-compatible HTTP transport. Introduce a provider interface; do not pretend this already supports Bedrock. |
| `strategyos_mvp/model_policy.py` | Checks external-model source access through claim policy. Reuse its authorisation principles; add an independent research purpose and policy. Model consent is not search consent. |
| `strategyos_mvp/inference_audit.py` | Tenant reservations and encrypted diagnostic payloads exist. Research needs its own durable request/attempt events, retention and network evidence. Existing audit can be optional; protected deployment must require audit. |
| `strategyos_mvp/config.py` | Run policy and approved external modes exist. Add explicit research mode and verified deployment posture; flags alone are not proof. |
| `strategyos_mvp/codex_gateway.py`, `docs/codex-provider.md` | Web search/tools disabled; provider service has egress. Bedrock profile must remove alternate-provider credentials and routes. |
| `deploy/docker-compose.yml`, `deploy/docker-compose.codex.yml` | Container separation is present, but inspected configuration is not proof of enforced destination restrictions or AWS residency. |
| `docs/requirements.md` REQ-25; assessment G26 | Deployment-specific residency and egress acceptance remain required. |

No live research gateway or Bedrock adapter was found in the inspected paths. Re-inventory all HTTP clients, subprocesses, workers, browser assets, telemetry, storage/OCR/embedding integrations and provider overlays before implementation closes the egress inventory.

## 3. Architecture and trust boundaries

Private user request → authenticated research service → approved public query compiler → isolated Research Gateway → approved search API/public source → isolated content parser → governed public evidence → private synthesis with client evidence.

Keep private synthesis and public retrieval separate. The internet-facing gateway must never receive the original question, conversation history, document excerpts, tenant names, internal metrics or arbitrary model-authored text. It has no business database credentials, source mounts or inference-provider credentials. An opaque request handle is internal routing metadata and must not be forwarded to providers.

The private research service authenticates the caller and tenant, checks source-use restrictions, applies public disclosure policy and persists the decision. A model may propose a structured intent inside the approved inference boundary; deterministic validation controls whether it can become a request. The gateway independently validates the final contract and owns all external research transport. Agents and browsers cannot invoke external research destinations directly.

### Public query contract

Initial schema: `template_id`, `topic_id`, `public_sector_id`, `public_geography_id`, `public_period_id`, `language`, `approved_source_set_id`. Each value must resolve against a versioned approved catalogue; reject unknown fields and free-text values. Do not accept arbitrary query strings, URLs, headers, filters, callbacks or attachment bodies from users or models.

Example template: `{sector} {topic} benchmarks {geography} {period}`. “Concentration in Modern Trade above the board limit” may map to a public channel-concentration topic only if that topic/geography combination is permitted for disclosure. The outbound request must contain no board-limit reference or breach signal. If the country or period is absent, do not invent it; omit it or use an independently approved research profile.

Use template construction as the primary control. Normalisation, entity detection, secret/number detectors and contextual DLP are defence in depth, not proof that arbitrary prose has been anonymised. Reject ambiguous, encoded, multilingual or obfuscated payloads outside the contract. Validate field combinations: individually public fields can identify a client when combined. Apply query budgets and review repeated patterns that could encode data through otherwise allowed choices.

For the strongest mode, collect a fixed, approved public corpus on a schedule independent of client events. Private analysis searches that corpus locally. Offer live template research only under an explicit tenant disclosure policy acknowledging topic and transport metadata.

### Fetch boundary

Start with one approved search adapter and bounded fetching of approved public sources; no general-purpose autonomous browser. Gateway owns provider credentials and emits fixed headers with no tenant/user tracking identifiers, cookies or private referrers. Pin provider endpoints and define permitted request fields.

Fetched URLs must pass canonicalisation, host/path policy, DNS/IP checks and redirect revalidation on every hop. Block loopback, private/link-local ranges, cloud metadata endpoints, non-HTTP protocols, userinfo, unexpected ports, DNS rebinding and arbitrary query parameters. Validate actual connected addresses, not merely initial DNS results. Disable JS, forms, recursive link following and automatic resource loading. Run document parsing without network access, with size, time, MIME and decompression limits.

Treat results as untrusted evidence, never instructions. A page cannot authorise another query, invoke a tool or change policy. Any follow-up research starts a fresh policy decision. Render safe text and local assets; block browser-side tracking images, remote embeds, scripts and prefetch. Explicit visits to external source sites leave Kyvern's controlled research boundary and must be recognisable as external navigation.

## 4. Ordered delivery work packages

| Package | Concrete deliverables / intended files | Depends on | Exit evidence |
| --- | --- | --- | --- |
| P0: contract and inventory | Egress inventory; threat model; tenant disclosure profiles; approved fields/templates; requirements and claim matrix. Extend `docs/requirements.md`. | None | Every network-capable component and statement mapped to an owner and test; public-only exception rule agreed in code contract. |
| P1: policy and persistence | New `research/contracts.py`, `research/policy.py`, `research/query_compiler.py`, `research/store.py`; extend claim purpose, config and database schema using repository conventions. | P0 | Strict schema, tenant/BU authorisation, public-field provenance and policy-revocation tests pass; no internet enabled. |
| P2: gateway and transport | New `research/gateway.py`, `research/search_adapter.py`, `research/fetcher.py`; gateway image/service; authenticated private requests; independent contract checks, bounded transport, quotas. | P1 | Mock external receiver captures only permitted bytes; direct and indirect SSRF/bypass tests fail closed. |
| P3: network enforcement | Infrastructure definitions under `deploy/` for private application/data services, constrained gateway egress, controlled DNS, endpoint policies and isolated parser. | P2 | Runtime API/worker/agent/parser/browser probes prove forbidden paths blocked, including when app policy is bypassed. |
| P4: Bedrock inference | Provider interface and Bedrock adapter alongside `llm_qa.py`; preserve source consent, response/citation contracts, retries, quotas and required inference audit. Add AWS deployment profile. | P0; integrate P3 | Exact account/region/model/API/retention receipt; private connectivity and incompatible-model/fallback denial tests. |
| P5: governed evidence and UI | Research orchestration in `api.py` and relevant agent interfaces; external-source provenance; existing claim/retrieval integration; research status/detail UI and residency details in executive/board surfaces. | P1–P4 | Real UI flows produce sourced answers; private figures remain sourced from private evidence; denial and unavailable states truthful. |
| P6: acceptance and rollout | Adversarial corpus, network capture harness, audit reconciliation, browser evidence, operational runbook, kill switch and release manifest. | P1–P5 | All mandatory gates pass on the exact deployed image/config before claims change. |

Each package produces a reviewable change and its evidence. P4 can be developed alongside P1/P2, but live protected research is enabled only after integrated network acceptance.

## 5. Bedrock deployment requirements

Select one exact model, API and allowed region based on availability and client requirements. Use workload IAM roles, least-privilege model resources and private VPC endpoints; do not put long-lived AWS credentials into the app image. A non-AWS host calling Bedrock does not make application hosting or storage AWS-resident. For a single AWS boundary claim, deploy the private application, databases, object storage, logs, backups and inference connectivity into the attested AWS environment.

Disable cross-region profiles for a single-region promise. If a client permits geographic routing, state the actual allowed geography, not one selected region. Prevent accidental global or alternative-model routing through IAM, endpoint restrictions and configuration validation. Test timeout, quota, denied model and unavailable-region cases: no fallback to Codex, DeepSeek, direct model APIs or a more permissive retention mode.

Verify effective zero retention for the exact model/API/account/project and enforce it against configuration changes. Reject models that require retention under the protected profile. Validate any feature-specific retention such as stored responses, batch, caches or agent memory before allowing it. Separately control Kyvern/AWS invocation logging, traces, error reporting and backups: model retention settings do not erase application logs.

AWS documents configurable retention and rejection of incompatible models under `none`; private Bedrock endpoints avoid public internet transit. Cross-region inference has separate routing behaviour. Record the actual deployed settings and tests rather than treating these capabilities as default guarantees.

References, checked 2026-09-11:

- [AWS Bedrock data retention](https://docs.aws.amazon.com/bedrock/latest/userguide/data-retention.html)
- [AWS Bedrock private VPC endpoints](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html)
- [AWS Bedrock cross-region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html)

## 6. Audit, authorisation and operational behaviour

Use server-derived tenant/principal scope, including queued jobs; never trust a browser-supplied tenant ID. Recheck policy at dispatch and before evidence access. Partition evidence, requests and caches by tenant and relevant policy/scope. Only independently public corpus content may use an explicitly designed shared cache; query histories and client-triggered associations remain private.

Persist a durable pre-dispatch record containing opaque request ID, internal tenant/principal, intent/template/policy versions, approved outbound payload or protected representation, destination, decision/reason, relevant public-field provenance and timestamp. Record every attempt, redirect decision, status, provider request ID if supplied, result sources and content hashes. Encrypt sensitive internal audit data with tenant-scoped access; do not send audit context to external logging providers. Use a separate restricted writer and tamper-evident or immutable retention sink. Define retention/deletion for metadata, payloads and evidence independently, including backups.

If policy, audit reservation or gateway authentication is unavailable, deny dispatch. If a post-call audit write fails, mark the operation outcome uncertain, preserve a durable attempt journal and reconcile; do not claim the request never happened or silently retry. Retries remain tied to the same approved payload, current policy and bounded budget. Gateway validates short-lived authorisation bound to exact request digest; policy changes and kill switches invalidate pending work.

The UI shows Disabled, Awaiting safe-query review, Blocked, Running, Completed, Failed or Outcome uncertain. A reviewer sees the exact proposed public request and destination; editing it triggers full validation. First release has no “send confidential context anyway” control. Degraded research does not fabricate current market findings or prevent authorised internal analytics from working.

## 7. Mandatory acceptance matrix

All rows are release gates, not optional demonstrations.

| Claim / risk | Test | Required evidence |
| --- | --- | --- |
| Research actually works | Market benchmark, public regulation and competitor-public-information tasks through the chosen provider | Real sources, fetch time, publication date where available, content hashes and cited answers; unavailable evidence clearly reported. |
| Raw context never reaches research recipients | Synthetic canaries in client names, board thresholds, financial figures, identities, strategy, histories and retrieved excerpts | Receiver-side captured HTTP bytes plus internal request correlation; zero canaries or confidential meaning in outbound payloads. Flow logs alone cannot inspect HTTPS content. |
| Compiler is robust | English, Arabic and Ukrainian; transliteration, Unicode, base64, prompt injection, long/unknown fields and identifying field combinations | Strict rejection or exact approved template output; no free-text escape hatch. |
| One mandatory gateway | Attempt direct outbound calls from API, worker, agents, provider tool calls, parser and browser | Network denial evidence covering IPv4/IPv6, DNS, proxy settings and alternate providers. |
| Fetch cannot become an exfiltration channel | Redirects, encoded URL parameters, internal IPs, metadata, rebinding, tracking pixels and malicious documents | No private destination reached; no context in URL/path/query/headers/body; parsing has no network. |
| Returned content cannot control research | Pages instructing tools to upload evidence or follow attacker URLs | Instructions remain untrusted text; no unauthorised request or action. |
| Source governance and tenancy hold | Cross-tenant/BU access, revoked consent, forged handles, queue replay and cache collision | Denials at API, worker, gateway and evidence retrieval boundaries; no cross-scope results. |
| Review cannot bypass confidentiality | Safe query approval, forbidden-field edit, revoked/expired authorisation and ordinary-user approval attempt | Only authorised public query dispatched; edits revalidated; confidential exception impossible. |
| Audit is complete | Missing audit service, timeout before/after dispatch, retries, process crash and tamper attempt | Every captured dispatch maps to a durable attempt; uncertain outcomes reconciled; no silent unaudited continuation. |
| Bedrock boundary is real | Capture effective region/model/retention/network policy and inject incompatible model, region and provider failures | Exact deployment receipt; forbidden requests denied; no weaker fallback. |
| UI reflects reality | Authenticated browser walkthrough of allowed/blocked/review/failed requests, citations, permissions and residency details | Screenshots or recording tied to release; no remote subresource leaks or false “sovereign” label. |
| Controls survive operation | Restart, configuration drift, key rotation, queue revocation and kill switch during in-flight work | Research stops safely; in-flight sends tracked; internal analytics remains available. |

Use synthetic sensitive facts for interception tests. Do not send real private client data to an external test collector. Inspect actual provider request serialisation as well as mocks. A finite test corpus establishes tested coverage, not a mathematical guarantee of anonymity; narrow contracts and network enforcement carry the main security property.

## 8. Rollout, evidence and completion

1. Develop with research disabled. Add schema changes compatibly and run existing affected governance, Q&A and tenant tests.
2. Run compiler/gateway tests against an isolated receiver. Add infrastructure isolation before any real external credentials are enabled.
3. Deploy exact immutable app/gateway images to a synthetic-data staging environment. Use the intended AWS profile for AWS residency acceptance; an existing preview hostname alone does not prove AWS hosting.
4. Enable one approved provider for one test tenant. Complete end-to-end real research, network and authenticated UI acceptance. Reconcile all sends with audit records.
5. Seal a release evidence manifest: git SHA, image digests, schema version, policy/template/catalogue versions, AWS account/region/model/API, infrastructure policy hashes, provider terms/configuration review, test outputs, browser artifacts and outstanding limitations.
6. Promote those same images/configuration to the intended production environment, repeat deployment-specific boundary probes and UI smoke tests, then enable explicitly configured tenants.
7. Publish only the claims supported by that manifest. Re-attest after model/provider, template, policy, networking or deployment changes. Drift or missing attestation disables research or marks posture unverified, as appropriate.

Rollback disables dispatch first, revokes gateway credentials/routes, cancels pending authorisations and preserves completed/uncertain attempt evidence. Do not roll back to a provider with weaker data handling or drop audit/evidence tables. Separately verify data migration rollback compatibility.

Completion means every acceptance row passes for the deployed release, no unresolved confidentiality/bypass defect remains, the UI matches the real configuration, and the operator can stop research and explain every outbound attempt. A plan, passing unit suite or successful deployment alone is not completion.

## 9. Remaining deployment inputs and estimate

Required before live enablement: target AWS account and permitted region/geography; exact compatible Bedrock model/API; approved public search provider and its query retention/processing terms; tenant public-topic disclosure policy; retention periods; authorised reviewer/operator roles. These do not block implementing the disabled core and synthetic acceptance harness. Do not silently select them from defaults or reuse unrelated credentials.

Planning estimate for one search provider, bounded public fetching and one AWS deployment profile: 18–28 engineering person-days plus 5–8 security/QA person-days, subject to P0 inventory and existing infrastructure reuse. Account/provider provisioning is additional elapsed time. Broad connector support, arbitrary browser automation, deliberate confidential disclosure and attestation of all four deployment tiers are outside this first release.

## 10. Wording unlocked after acceptance

“Kyvern performs external research through a dedicated Research Gateway. It constructs requests from approved public research fields and blocks raw client questions, private evidence and confidential business facts from being sent to external research providers. Every request is subject to access policy, destination restrictions and audit. Unsafe requests are blocked or reviewed for a safe public reformulation. External providers receive approved public query terms and necessary transport metadata. Client evidence is combined with retrieved public material only inside the approved inference environment. This deployment uses the attested AWS Bedrock model, retention policy and processing region shown in its security details.”

This replaces the absolute “no client context of any kind” promise while making the substantive protection concrete, enforceable and testable.
