"""Conflict disclosure for already-authorized claims; never source precedence.

Neither ingestion order, assertion namespace nor search rank resolves a conflict.
No independent-corroboration claim is made from repeated source occurrences.
"""
from decimal import Decimal, InvalidOperation, localcontext

from .source_claims import stable_key


def annotate_conflicts(records: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for record in records:
        period = record.get('period') or {}
        scope = stable_key('comparison-scope-v1',record.get('subject'),record.get('metric_key'),
            record.get('claim_kind'),record.get('business_unit'),record.get('dimensions'),
            record.get('scenario'),{key:period.get(key) for key in
                ('start','end','as_of','timezone','fiscal_calendar')})
        groups.setdefault(scope,[]).append(record)
    output = []
    for scope,members in groups.items():
        values = set()
        for record in members:
            value = record.get('value')
            if record.get('value_type') == 'numeric':
                try:
                    with localcontext() as context:
                        number,scale = Decimal(str(value)),Decimal(str(record.get('scale')))
                        if not number.is_finite() or not scale.is_finite() or scale <= 0:
                            raise ValueError('Invalid quantitative claim')
                        context.prec = max(28,len(number.as_tuple().digits)+len(scale.as_tuple().digits)+2)
                        value = number*scale
                except (InvalidOperation,ValueError):
                    # Invalid numerical semantics cannot be collapsed as equal.
                    value = ('invalid',record.get('claim_revision_id'))
            values.add((record.get('value_type'),record.get('unit'),record.get('currency'),value))
        conflict = len(values)>1
        for record in members:
            output.append({**record,'comparison':{
                'scope_key':scope,'status':'unresolved_conflict' if conflict else
                    ('consistent_values' if len(members)>1 else 'single_claim'),
                'requires_resolution':conflict,
                'authorized_competing_revisions':[item['claim_revision_id'] for item in members
                    if item['claim_revision_id'] != record['claim_revision_id']],
                'selection_basis':'No source-priority decision applied',
                'independent_corroboration':'not_assessed'}})
    by_id = {record['claim_revision_id']:record for record in output}
    return [by_id[record['claim_revision_id']] for record in records]
