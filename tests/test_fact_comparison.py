from copy import deepcopy
from types import SimpleNamespace

import pytest

from strategyos_mvp.fact_rendering import fact_registry, render_selection


def records():
    base = {'traceability': 'present', 'value_type': 'numeric', 'scale': '1', 'unit': 'SAR',
            'currency': 'SAR', 'metric_key': 'cost.component', 'subject': {'type': 'bu_cost', 'key': 'BU A:Logistics'},
            'period': {'start': '2026-01-01', 'end': '2026-06-30'}, 'business_unit': 'BU A', 'scenario': None}
    return [{**base, 'claim_revision_id': kind, 'claim_kind': kind, 'label': kind.title(), 'value': value,
             'dimensions': {'series': kind, 'component': 'Logistics', 'driver': 'Delivery subsidies on OTC orders'}}
            for kind, value in [('actual', '42200000'), ('plan', '39300000')]]


def answer(items, refs=('actual', 'plan')):
    return render_selection({'matched': True, 'fact_refs': list(refs)}, fact_registry(items), run_id='run')


def test_comparison_is_exact_and_bound_to_compatible_immutable_inputs():
    result = answer(records())
    calc = result['calculated_comparisons'][0]
    assert calc['difference'] == '2900000'
    assert calc['input_claim_revision_ids'] == ['actual', 'plan']
    assert 'SAR 2,900,000 above plan' in result['answer']
    assert {citation['claim_revision_id'] for citation in result['citations']} == {'actual', 'plan'}
    assert 'Recorded source commentary: Delivery subsidies on OTC orders' in result['answer']
    assert all('Delivery subsidies on OTC orders' in citation['excerpt'] for citation in result['citations'])


@pytest.mark.parametrize('field,value', [
    ('subject', {'type': 'bu_cost', 'key': 'BU B:Logistics'}),
    ('metric_key', 'revenue.component'), ('currency', 'USD'), ('unit', 'USD'),
    ('period', {'start': '2025-01-01', 'end': '2025-06-30'}),
    ('business_unit', 'BU B'), ('scenario', 'alternative'),
    ('dimensions', {'series': 'plan', 'component': 'Other'}),
    ('comparison', {'requires_resolution': True}),
])
def test_incompatible_scopes_and_unresolved_conflicts_never_produce_arithmetic(field, value):
    items = records()
    items[1][field] = value
    assert answer(items)['calculated_comparisons'] == []


def test_model_cannot_select_one_of_multiple_candidates_to_create_false_certainty():
    items = records()
    items.append({**deepcopy(items[0]), 'claim_revision_id': 'competing', 'value': '50000000'})
    assert answer(items)['calculated_comparisons'] == []
    assert answer(records(), refs=('actual',))['calculated_comparisons'] == []


def test_undated_and_forecast_values_are_not_actual_plan_comparisons():
    items = records()
    for item in items:
        item['period'] = {}
    assert answer(items)['calculated_comparisons'] == []
    items = records()
    items[1]['claim_kind'] = 'forecast'
    assert answer(items)['calculated_comparisons'] == []


def test_comparison_badge_is_calculated_not_a_model_statement():
    from strategyos_mvp import api
    result = answer(records())
    payload = api._assistant_response_payload(response_mode='llm', question='Compare?',
        context={'run_id': 'run', 'run_mode': 'full'}, requested_mode='auto', persona='ceo',
        orchestrated=SimpleNamespace(answer='Provider invented a cause'), base_result=result)
    assert payload['determinism_tier'] == 'derived_insight'
    assert payload['answer'] == result['answer'] and 'invented' not in payload['answer']


def test_all_recorded_context_reaches_semantic_selection_without_becoming_model_instructions():
    items = records()
    items[0]['dimensions']['owner_notes'] = 'A recorded explanation absent from the metric title'
    registry = fact_registry(items)
    assert 'owner_notes' in registry['actual']['text']
    assert 'A recorded explanation absent from the metric title' in registry['actual']['text']


def test_non_scalar_series_is_excluded_without_breaking_other_facts():
    items = records()
    items[0]['dimensions']['series'] = ['actual']
    assert answer(items)['calculated_comparisons'] == []


def test_decimal_comparison_keeps_small_differences_at_large_magnitudes():
    items = records()
    items[0]['value'] = '100000000000000000000000000000.01'
    items[1]['value'] = '100000000000000000000000000000.00'
    result = answer(items)
    assert result['calculated_comparisons'][0]['difference'] == '0.01'
    assert 'SAR 0.01 above plan' in result['answer']


def test_percentage_difference_is_labelled_in_points_not_relative_growth():
    items = records()
    for item, value in zip(items, ['15.4', '15.2']):
        item.update(unit='percent', currency=None, value=value)
    result = answer(items)
    assert result['calculated_comparisons'][0]['unit'] == 'percentage points'
    assert 'percentage points 0.2 above plan' in result['answer']
