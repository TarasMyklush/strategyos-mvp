# Hermes Governed Scenario Engine — Implementation Plan

**Date:** 2026-07-10  
**Scope:** Authenticated StrategyOS CEO experience and `/assistant/chat`  
**Objective:** Allow a CEO to model numerical what-if scenarios against actual governed company data, with deterministic calculations, transparent assumptions, and source-level traceability.

## 1. Executive outcome

Hermes must operate as a natural-language interface to a governed scenario engine. It may interpret a question and explain a result, but it must not perform or invent financial calculations inside a generated narrative.

The target interaction is:

1. The CEO asks a numerical what-if question.
2. Hermes extracts a structured scenario request.
3. StrategyOS validates the metric, period, scope, units, and required inputs.
4. The system loads the baseline from the authenticated governed run.
5. Deterministic, versioned code performs the calculation.
6. The result carries formulas, inputs, assumptions, citations, run identity, and data timestamp.
7. Hermes converts the verified result into concise executive language.
8. The CEO can inspect the calculation and evidence directly in the UI.

```mermaid
flowchart LR
    Q["CEO question"] --> P["Scenario input extraction"]
    P --> V["Schema and data validation"]
    V --> D["Governed baseline resolver"]
    D --> C["Deterministic calculation engine"]
    C --> E["Evidence and calculation trace"]
    E --> H["Hermes executive explanation"]
    H --> U["CEO scenario result card"]
```

## 2. Current production gaps

Production verification identified four material problems:

1. A recovery question containing a hypothetical SAR 400,000 adjustment returned the unchanged SAR 794,108 baseline instead of SAR 394,108 remaining.
2. A 60% EUR hedge question was misrouted to the recoverable-leakage total.
3. A revenue-down/cost-up question could not run because the current evidence did not contain the necessary income-statement inputs. Refusal was appropriate, but the UI did not provide a structured missing-input path.
4. A Digital Health question used a synthetic external benchmark when actual run data was unavailable.

The current CEO drawer also suppresses response provenance: `qaAnswerMeta()` returns an empty string, so calculation basis, citations, risk, and assumptions are not visible to the CEO.

## 3. Non-negotiable design principles

- **Deterministic mathematics:** All financial calculations run in governed code, never in free-form model output.
- **Actual data by default:** Authenticated production scenarios use only the selected governed run unless the CEO explicitly enables an illustrative mode.
- **No silent substitution:** Missing company data must result in a clear refusal or data request, not synthetic values.
- **No false matches:** A scenario is `matched=true` only when every material user input was parsed, validated, and applied.
- **Visible provenance:** Every result identifies baseline sources, formulas, assumptions, reporting period, run ID, and data freshness.
- **Separation of duties:** The language model extracts intent and explains results; calculators calculate; policy code governs access and release.
- **Fail closed:** Ambiguous units, time periods, entities, or metrics require clarification before calculation.

## 4. Target scenario contract

Introduce a validated request model such as:

```json
{
  "scenario_id": "generated-request-id",
  "scenario_family": "recovery_realization",
  "target_metrics": ["recoverable_value", "board_readiness"],
  "scope": {
    "tenant_id": "authenticated-tenant",
    "business_unit": null,
    "portfolio": null
  },
  "baseline": {
    "run_id": "current-governed-run",
    "period": "current-board-period"
  },
  "changes": [
    {
      "metric": "recoverable_value",
      "operation": "realize",
      "amount": "400000.00",
      "unit": "SAR"
    }
  ],
  "assumptions": [],
  "requested_outputs": ["remaining_value", "percentage_change", "board_readiness_effect"]
}
```

The contract must validate:

- Target metric and operation
- Absolute versus percentage changes
- Currency and unit
- Reporting period and scenario horizon
- Group, BU, portfolio, vendor, or case scope
- Baseline run selection
- Required dependent metrics
- Explicit assumptions
- Requested outputs

## 5. Delivery plan

### Phase 0 — Production safety patch

**Goal:** Stop incorrect scenario answers before expanding capability.

Deliverables:

- Detect scenario language such as `if`, `assume`, `increase`, `decrease`, `recover`, `hedge`, `change by`, and `what would happen`.
- Route scenario-intent prompts exclusively through scenario validation.
- Prevent scenario prompts from falling through to unrelated factual Q&A handlers.
- Require extracted scenario parameters before returning `matched=true`.
- Verify that all numeric user inputs appear in the calculation trace.
- Disable synthetic scenario baselines for authenticated production requests unless `illustrative_mode=true` was explicitly selected.
- Return a structured missing-data response when required inputs are unavailable.
- Add regression tests for the four production failures.

Acceptance gate:

- No tested scenario prompt may return an unrelated baseline answer.
- Unsupported or under-specified scenarios must fail clearly and safely.

### Phase 1 — Metric and formula registry

**Goal:** Establish a semantic layer connecting business metrics to actual governed data and formulas.

Create a versioned metric registry containing:

- Canonical metric ID and executive label
- Supported units and currencies
- Time-grain rules
- Source dataset roles and fields
- Baseline resolver
- Formula and dependency graph
- Aggregation rules
- Permitted scenario operations
- Evidence requirements
- Data-quality and freshness constraints

Initial metrics:

- Recoverable value
- Realized recovery
- Revenue
- COGS
- Operating expenses
- EBITDA and EBITDA margin
- EUR exposure
- Hedge coverage and residual exposure
- DSO, DPO, inventory days, and working capital cash effect
- Board-readiness evidence status

Acceptance gate:

- Every supported metric resolves to an actual governed baseline or returns an explicit missing-input result.

### Phase 2 — Deterministic scenario calculators

**Goal:** Implement the first production-grade scenario families.

#### 2.1 Recovery realization

Core calculations:

```text
remaining_recoverable = baseline_recoverable - realized_amount
realization_rate = realized_amount / baseline_recoverable
```

Board-readiness impact must be calculated separately from value realization. Recovering value must not automatically clear challenged evidence or approval gates.

#### 2.2 Revenue, cost, and EBITDA

Core calculations:

```text
scenario_revenue = baseline_revenue × (1 + revenue_change_pct)
scenario_costs = baseline_costs × (1 + cost_change_pct)
scenario_ebitda = scenario_revenue - scenario_costs
scenario_margin = scenario_ebitda / scenario_revenue
```

The calculator must refuse execution when revenue/cost inputs are absent or periods are incompatible.

#### 2.3 FX hedge

Core calculations:

```text
hedged_exposure = eur_exposure × hedge_coverage_pct
residual_exposure = eur_exposure - hedged_exposure
hedged_fx_effect = hedged_exposure × fx_rate_change
residual_fx_effect = residual_exposure × fx_rate_change
```

The calculator must distinguish existing hedge rate, proposed coverage, spot/forward assumptions, hedge cost, and accounting period.

#### 2.4 Working capital

Support DSO, DPO, inventory-days, and cash-release scenarios using explicit daily sales, purchase, and COGS baselines.

Engineering requirements:

- Use decimal arithmetic for financial values.
- Make formulas versioned and independently testable.
- Validate unit, currency, sign, period, and scope consistency.
- Preserve baseline and scenario values separately.
- Produce calculation steps that are reproducible without an LLM.

Acceptance gate:

- Independent recomputation must reproduce every output exactly within the declared rounding policy.

### Phase 3 — Natural-language scenario extraction

**Goal:** Let the CEO ask naturally without allowing the model to become the calculator.

Routing sequence:

1. Classify factual question versus hypothetical scenario.
2. Extract a scenario request into the validated schema.
3. Reject or clarify ambiguous requests.
4. Resolve governed baselines.
5. Run the deterministic calculator.
6. Generate an executive explanation from the verified result only.

Rules:

- The LLM may output only the structured scenario request during extraction.
- Schema validation must reject unknown metrics, invalid operations, and unrecognized units.
- All numbers in the original question must be accounted for.
- An extraction confidence threshold must control whether execution is allowed.
- Clarification is mandatory when multiple interpretations would materially change the answer.

Acceptance gate:

- Paraphrases of a supported scenario must resolve to the same structured request and numerical result.

### Phase 4 — Provenance and governance

**Goal:** Make every scenario decision-grade and auditable.

Each scenario response must contain:

- Tenant and authenticated principal context
- Governed run ID and run mode
- Data timestamp and reporting period
- Actual baseline inputs
- User-provided overrides
- Explicit assumptions
- Formula version
- Calculation steps
- Scenario result and delta from baseline
- Source-level citations and hashes
- Missing-data list
- Hallucination and traceability metadata
- Audit-trail ID

Input values must be visibly classified as:

- `actual_governed`
- `user_assumption`
- `derived`
- `illustrative_external`

Authenticated production should reject `illustrative_external` unless the CEO explicitly opts into an illustrative scenario.

Acceptance gate:

- Every baseline number is traceable to a governed source or visibly identified as a user assumption.

### Phase 5 — CEO scenario experience

**Goal:** Give the CEO a clear result with optional depth, not a black-box paragraph.

The result card should show:

```text
Baseline recoverable:       SAR 794,108
CEO assumption:             SAR 400,000 realized
Remaining recoverable:      SAR 394,108
Change:                     -50.4%
Board evidence status:      Unchanged — 4 cases remain challenged
Data as of:                 <governed period>
```

Required UI controls:

- Show calculation
- Show sources
- Show assumptions
- Edit scenario inputs
- Recalculate
- Compare with baseline
- Request missing data
- Save scenario snapshot

Replace the current empty `qaAnswerMeta()` behavior with rendering for:

- Calculation basis
- Citations
- Assumptions
- Risk state
- Data timestamp
- Run identity

The UI must visibly differentiate:

- Governed actual result
- Scenario assumption
- Illustrative scenario
- Insufficient-data refusal

Acceptance gate:

- A CEO can independently determine what was actual, assumed, calculated, and missing without opening developer tools.

### Phase 6 — Verification suite

**Goal:** Prevent regression and misrouting.

#### Golden production scenarios

| Prompt | Required outcome |
|---|---|
| Recover SAR 400,000 from SAR 794,108 | SAR 394,108 remaining; board evidence status evaluated separately |
| Hedge 60% of EUR exposure | Actual saving plus 40% residual exposure, using cited FX inputs |
| Revenue falls 5% and costs rise 3% | Correct EBITDA impact, or a structured refusal listing missing inputs |
| Digital Health stays flat | Actual governed baseline, or refusal; no automatic synthetic substitution |

#### Test layers

- Unit tests for formulas and rounding
- Property tests for mathematical invariants
- Parser paraphrase tests
- Unit/currency/period validation tests
- Data-readiness and missing-input tests
- Misrouting regression tests
- Authentication and tenant-isolation tests
- Provenance completeness tests
- CEO UI rendering tests
- End-to-end production smoke tests

Release criteria:

- 100% of material user inputs appear in the calculation trace.
- 100% of numerical results reproduce independently.
- 100% of baseline inputs carry governed citations.
- Zero unrelated `matched=true` responses in the golden and adversarial prompt suites.
- Unsupported scenarios refuse clearly.
- No authenticated scenario uses synthetic data without explicit opt-in.
- CEO UI displays basis, assumptions, evidence, and data freshness.

### Phase 7 — Controlled production rollout

**Goal:** Introduce the capability without creating decision risk.

Rollout sequence:

1. Ship Phase 0 guardrails immediately.
2. Run calculators in shadow mode and compare results with independent expected outputs.
3. Enable recovery realization for internal authenticated users.
4. Enable FX, EBITDA, and working-capital families individually after their acceptance suites pass.
5. Enable CEO access behind a scenario-engine feature flag.
6. Monitor unmatched prompts, clarification rate, misroutes, missing data, formula failures, and evidence completeness.
7. Expand the allowlist only through versioned metric/formula additions.

Operational safeguards:

- Scenario results are advisory and cannot publish, approve, or execute actions automatically.
- Saved scenario snapshots remain separate from actual run data.
- Each recalculation creates a new audit entry.
- Formula changes require versioning and regression approval.

## 6. Implementation map

Primary code areas:

- `strategyos_mvp/scenario_parser.py` — replace broad keyword matching with structured scenario extraction and validated family routing.
- `strategyos_mvp/models.py` — add request, baseline, input classification, result, and provenance contracts.
- `strategyos_mvp/api.py` — enforce scenario-intent routing, data readiness, authentication context, and fail-closed behavior.
- `strategyos_mvp/assistants/orchestrator.py` — make verified scenario results precede narrative composition and prevent unrelated fallbacks.
- `strategyos_mvp/static/executive.js` — render scenario results, calculations, evidence, assumptions, and risk metadata.
- `tests/test_scenario_parser.py` — scenario extraction and calculation coverage.
- `tests/test_qa_api.py` — authenticated routing, provenance, and production regression coverage.
- `tests/test_ceo_surface_safety.py` and `tests/test_frontend_shell.py` — CEO-visible grounding and scenario-card behavior.

Recommended new modules:

```text
strategyos_mvp/scenarios/
  contracts.py
  registry.py
  validation.py
  baseline_resolver.py
  engine.py
  provenance.py
  calculators/
    recovery.py
    ebitda.py
    fx_hedge.py
    working_capital.py
```

## 7. Suggested delivery sequence

### Sprint 1 — Safety and recovery scenarios

- Phase 0 production guardrails
- Scenario request/result contracts
- Metric registry foundation
- Recovery-realization calculator
- CEO calculation/evidence card foundation
- Four production regression tests

### Sprint 2 — Core financial modelling

- Revenue/cost/EBITDA calculator
- FX hedge calculator
- Working-capital calculator
- Data-readiness reporting
- Provenance completeness and tenant-isolation tests

### Sprint 3 — Executive usability and controlled release

- Natural-language extraction hardening
- Scenario editing and comparison
- Saveable audit snapshots
- Full CEO UI verification
- Shadow-mode production validation
- Feature-flagged rollout

## 8. Definition of done

Hermes scenario modelling is production-ready only when:

1. A CEO can state a supported numerical scenario naturally.
2. Every input is correctly interpreted or explicitly clarified.
3. Baselines come from the authenticated governed run.
4. Deterministic code performs all calculations.
5. The result shows baseline, scenario, delta, formula, assumptions, and board implication.
6. Every actual input is source-cited and time-bounded.
7. Missing data produces a safe, actionable refusal.
8. Synthetic or illustrative data is never silently substituted.
9. The CEO can inspect grounding directly in the product.
10. The production regression suite prevents the four verified failures from returning.

The governing principle is simple: **Hermes interprets and explains; governed deterministic code calculates.**
