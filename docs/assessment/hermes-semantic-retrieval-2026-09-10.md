# Hermes semantic retrieval — 10 September 2026

The chat repair removes literal-word candidate ranking, the 80-fact cutoff, the transaction-keyword gate, and client-side typo substitution. Sol remains configured as `gpt-5.6-sol` with medium reasoning.

The general/data classifier answers general questions without company evidence. For company questions, the model receives the complete authorized metric directory and selects the operation and relevant categories by meaning. New categories are discoverable without code changes. Fact lookups bypass the old scenario/KPI word rules; actual/budget comparisons and explicit reporting periods cannot be replaced by those rules. Operational Q&A and scoped twin investigation use the same evidence-selection contract.

All eligible records in the selected scope remain available. Large fact packets are split by byte size without dropping records. Every part must complete successfully; a provider failure is not reported as proof that data is missing. The model selects immutable revision references. The server supplies each figure, unit, period, subject and citation from the authorized record. Tenant, domain, source-consent, freshness and conflict checks remain active.

The UI distinguishes **Source-backed fact**, **General AI answer**, **AI advice**, **Evidence unavailable**, and retryable **Service unavailable** outcomes. No missing-evidence or service failure is promoted to a factual success.

## Live verification

Target: https://new.strategyos.live. Account: `executive.tester`.

The first browser pass exposed a remaining scenario override: both a budget comparison and an unavailable-year question incorrectly returned the current EBITDA-margin summary. This was corrected in the shared semantic fact path and successfully retested. The expanded regression run also found a scoped twin caller still importing the removed selector; it now uses the same semantic evidence service.

Verified source period: **2026-01-01 through 2026-06-30**. EBITDA actual is **SAR 617,000,000.00**, revision `64327cbb-e7cb-42d7-b6c7-5e915dafe2fa`; plan is **SAR 608,100,000.00**, revision `688df742-8d7b-4f73-adb6-1ddd294451a4`. The browser opened the actual citation and checked its metric, scaled value and revision identity against the answer.

The reproducible browser harness is `deploy/scripts/verify_hermes_poc_browser.py`. It signs in, opens chat, types and sends questions, checks rendered labels and values, opens the source citation, and saves screenshots and response payloads under `artifacts/hermes-ui-2026-09-10/`. Its final service-error case is explicitly a browser-local fault injection; it does not interrupt the shared model service.

Runtime release **06abb98** deployed successfully. API and worker use image digest `sha256:c310609999c29bd8e9ea353dfe45fa96447b2219b44a4d2cf9eaf21574ddbcc3`; the API is healthy and both services are running. The gateway reports `gpt-5.6-sol` / `medium`.

Final result: **9/9 real-provider UI cases passed, plus the service-error/retry fault-injection test**. No source-backed badge appeared on general answers, missing evidence, or the simulated service failure.

| Browser case | Result | Seconds |
|---|---|---|
| ebitda-typo | Passed | 21.6 |
| gdp | Passed | 6.2 |
| kyiv | Passed | 6.3 |
| ebitda-plain | Passed | 23.3 |
| ebitda-plan | Passed | 22.0 |
| ebitda-arabic | Passed | 26.8 |
| missing-period | Passed | 20.1 |
| greeting | Passed | 4.8 |
| false-number | Passed | 19.8 |
| service-error | Passed (fault injection) | 0.0 |

Company fact questions took **19.8–26.8 seconds** on this final run; general questions took **4.8–6.3 seconds**. This verifies correctness and completion for the exercised POC cases, not instant response times or a load test.

Screenshots: [cited EBITDA](../../artifacts/hermes-ui-2026-09-10/ebitda-typo.png), [actual versus plan](../../artifacts/hermes-ui-2026-09-10/ebitda-plan.png), [general AI answer](../../artifacts/hermes-ui-2026-09-10/gdp.png), [missing period](../../artifacts/hermes-ui-2026-09-10/missing-period.png), [retryable service failure](../../artifacts/hermes-ui-2026-09-10/service-error.png).

## Automated coverage

- Fact selection beyond 80 records, including a relevant fact at the end of the input; informal wording and Arabic passed unchanged to the model.
- Lossless multiple-packet selection and more than 20 returned references; foreign references and provider-authored factual assertions rejected.
- Semantic category/operation contract, including invalid category names and unwanted output fields.
- Company comparisons and unavailable reporting periods bypass legacy scenario rules on both chat and operational Q&A.
- Missing evidence and provider failures retain their non-factual classification.
- Real PostgreSQL tests for catalog tenant/domain boundaries, source-consent revocation, conflict handling and scoped reads.
- Main regression run: 411 passed. Additional operational-Q&A/frontend/fact run: 337 passed.
- Expanded twin/frontend run: 533 passed and three outdated controller test doubles rejected the existing `metric_keys` argument. Their signature was corrected; the complete phase-7 controller tests, twin authority tests and fact tests then passed (32 tests). No production authorization was relaxed to satisfy them.

This is verification of the repaired chat/retrieval scope, not a claim that every product workflow has been re-certified.
