"""Render immutable fact selections without accepting provider-authored assertions.

The model selects references. Metric, entity, period, units, source locations and
calculation lineage come exclusively from the authorized snapshot.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
from typing import Mapping
from urllib.parse import quote

CONTRACT = 'governed-fact-selection-v1'


def fact_registry(records):
    result = {}
    for raw in records:
        ref = str(raw.get('claim_revision_id') or '')
        if not ref or ref in result:
            raise ValueError('Fact revisions must be present and unique.')
        record = deepcopy(dict(raw))
        if record.get('traceability') != 'present' or record.get('superseded_since_analysis'):
            continue
        if record.get('value_type') != 'numeric':
            continue
        try:
            value, scale = Decimal(str(record['value'])), Decimal(str(record['scale']))
            if (not value.is_finite() or not scale.is_finite() or scale <= 0
                    or abs(value.adjusted()) > 100 or abs(scale.adjusted()) > 100):
                continue
            with localcontext() as ctx:
                ctx.prec = max(50, len(value.as_tuple().digits) + len(scale.as_tuple().digits))
                normalized = format(value * scale, 'f')
        except (KeyError, ValueError, InvalidOperation):
            continue
        subject = record.get('subject') or {}
        if not record.get('metric_key') or not subject.get('key') or not record.get('unit'):
            continue
        period = record.get('period') or {}
        when = ' to '.join(str(period[key]) for key in ('start','end') if period.get(key))
        when = when or str(period.get('as_of') or 'period not specified')
        unit = str(record.get('currency') or record['unit'])
        if record.get('currency') and record['unit'] not in {record['currency'], 'currency', 'money'}:
            unit = f"{record['currency']} {record['unit']}"
        dimensions = record.get('dimensions') or {}
        identity_dimensions = {key:dimensions[key] for key in (
            'driver_key','component_key','presentation_component','series','label',
            'transaction_type','counterparty_key','account','region','product','client')
            if key in dimensions and isinstance(dimensions[key], (str,int,float))}
        record['identity_dimensions'] = identity_dimensions
        parts = [str(record['metric_key']), f"{subject.get('type') or 'subject'}: {subject['key']}",
                 str(record.get('label') or record.get('claim_kind') or ''), when]
        if record.get('business_unit'):
            parts.append('business unit: ' + str(record['business_unit']))
        if record.get('scenario'):
            parts.append('scenario: ' + str(record['scenario']))
        parts.extend(f'{key}: {value}' for key,value in identity_dimensions.items())
        result[ref] = {'ref':ref, 'text':' · '.join(parts) + f': {normalized} {unit}',
                       'record':record, 'value':normalized, 'unit':unit}
    return result


def render_selection(selection, registry, *, run_id):
    if (not isinstance(selection, Mapping) or set(selection) != {'matched','fact_refs'}
            or not isinstance(selection['matched'], bool)
            or not isinstance(selection['fact_refs'], list)):
        raise ValueError('Only the governed fact-selection contract is accepted.')
    refs = selection['fact_refs']
    if (len(refs) > 20 or any(not isinstance(ref,str) or ref not in registry for ref in refs)
            or len(set(refs)) != len(refs) or bool(refs) != selection['matched']):
        raise ValueError('Every selected fact must belong to this authorized snapshot.')
    if not refs:
        return {'matched':False,'answer':'The authorized evidence does not contain the fact or approved calculation needed to answer this question.',
                'basis':'Authorized claim snapshot.','citations':[],'suggestions':[], 'fact_contract':CONTRACT}
    citations=[]
    facts=[]
    for ref in refs:
        fact=registry[ref]
        record=fact['record']
        href='/api/claims/snapshots/'+quote(str(run_id),safe='')+'/revisions/'+quote(ref,safe='')
        citations.append({'source_path':'claim://'+ref,'locator':'immutable revision '+ref,
                          'excerpt':fact['text'],'claim_revision_id':ref,'href':href,'resolved':True})
        facts.append({'claim_revision_id':ref,'metric_key':record['metric_key'],
                      'subject':record['subject'],'period':record.get('period'),
                      'value':fact['value'],'unit':fact['unit'],'claim_kind':record.get('claim_kind'),
                      'formula':record.get('formula'),'business_unit':record.get('business_unit'),
                      'scenario':record.get('scenario'),'dimensions':record.get('identity_dimensions',{})})
    return {'matched':True,'answer':'\n\n'.join(registry[ref]['text'] for ref in refs),
            'basis':'Immutable facts from the authorized claim snapshot.', 'citations':citations,
            'suggestions':[], 'fact_contract':CONTRACT,'fact_cells':facts,
            '_orchestrator_force_answer':True}


def select_candidates(registry, question, *, limit=80):
    """Bound provider input while keeping each chosen fact indivisible."""
    import re
    words = set(re.findall(r"[^\W_]+", question.casefold())) - {
        'what','which','how','the','is','are','our','for','and','of','in','to','a'}
    def score(item):
        ref,fact=item
        tokens=set(re.findall(r"[^\W_]+", fact['text'].casefold()))
        return (-len(words & tokens), ref)
    return dict(sorted(registry.items(),key=score)[:limit])
