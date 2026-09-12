"""Compare unambiguous actual/plan revisions of exactly the same measure.

There is no question-word routing and no model-authored arithmetic. A pair is
eligible only when both references were selected and the entire authorized
registry contains exactly one actual and one plan in that comparison scope.
"""
import json
from decimal import Decimal, localcontext


def selected_comparisons(refs, registry):
    selected = set(refs)
    groups = {}
    for ref, fact in registry.items():
        record = fact['record']
        kind = record.get('claim_kind')
        period = record.get('period') or {}
        series = (record.get('dimensions') or {}).get('series')
        if (record.get('value_type') != 'numeric' or kind not in {'actual', 'plan'}
                or (series is not None and series != kind)
                or not (period.get('as_of') or (period.get('start') and period.get('end')))):
            continue
        scope = {key: record.get(key) for key in
                 ('metric_key', 'subject', 'period', 'business_unit', 'scenario', 'unit', 'currency')}
        scope['dimensions'] = {key: value for key, value in (record.get('dimensions') or {}).items()
                               if key != 'series'}
        key = json.dumps(scope, sort_keys=True, ensure_ascii=False, default=str)
        groups.setdefault(key, {'actual': [], 'plan': []})[kind].append((ref, fact))
    results = []
    for group in groups.values():
        if len(group['actual']) != 1 or len(group['plan']) != 1:
            continue
        actual_ref, actual = group['actual'][0]
        plan_ref, plan = group['plan'][0]
        if not {actual_ref, plan_ref}.issubset(selected):
            continue
        if any((fact['record'].get('comparison') or {}).get('requires_resolution') for fact in (actual, plan)):
            continue
        with localcontext() as arithmetic:
            arithmetic.prec = 512
            difference = Decimal(actual['value']) - Decimal(plan['value'])
        unit = actual['unit']
        if unit.casefold() in {'%', 'percent', 'percentage'}:
            unit = 'percentage points'
        relation = 'above plan' if difference > 0 else 'below plan' if difference < 0 else 'equal to plan'
        subject = actual['record']['subject']['key']
        results.append({'calculation_id': 'actual-minus-plan.v1',
            'formula': 'actual - plan', 'input_claim_revision_ids': [actual_ref, plan_ref],
            'actual': actual['value'], 'plan': plan['value'], 'difference': str(difference),
            'unit': unit, 'subject': actual['record']['subject'], 'period': actual['record']['period'],
            'metric_key': actual['record']['metric_key'],
            'display_text': f'Calculated comparison — {subject}: {unit} {difference.copy_abs():,f} {relation}.'})
    return results
