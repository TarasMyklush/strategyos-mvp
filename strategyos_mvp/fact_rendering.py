"""Render immutable fact selections without accepting provider-authored assertions.

The model selects references. Metric, entity, period, units, source locations and
calculation lineage come exclusively from the authorized snapshot.
"""
from copy import deepcopy
import json
from decimal import Decimal, InvalidOperation, localcontext
from typing import Mapping
from urllib.parse import quote

CONTRACT = 'governed-fact-selection-v1'


def _numeric_value(record):
    value, scale = Decimal(str(record['value'])), Decimal(str(record['scale']))
    if (not value.is_finite() or not scale.is_finite() or scale <= 0
            or abs(value.adjusted()) > 100 or abs(scale.adjusted()) > 100):
        raise ValueError('Invalid numeric fact.')
    with localcontext() as ctx:
        ctx.prec = max(50, len(value.as_tuple().digits) + len(scale.as_tuple().digits))
        return format(value * scale, 'f')


def fact_registry(records):
    result = {}
    for raw in records:
        ref = str(raw.get('claim_revision_id') or '')
        if not ref or ref in result:
            raise ValueError('Fact revisions must be present and unique.')
        record = deepcopy(dict(raw))
        if record.get('traceability') != 'present' or record.get('superseded_since_analysis'):
            continue
        value_type = record.get('value_type')
        if value_type not in {'numeric', 'text'}:
            continue
        try:
            if value_type == 'text':
                if not isinstance(record.get('value'), str) or not record['value'].strip():
                    continue
                normalized = record['value']
            else:
                normalized = _numeric_value(record)
        except (KeyError, ValueError, InvalidOperation):
            continue
        subject = record.get('subject') or {}
        if not record.get('metric_key') or not subject.get('key'):
            continue
        if value_type == 'numeric' and not record.get('unit'):
            continue
        period = record.get('period') or {}
        when = ' to '.join(str(period[key]) for key in ('start','end') if period.get(key))
        when = when or str(period.get('as_of') or 'period not specified')
        unit = str(record.get('currency') or record.get('unit') or '')
        if record.get('currency') and record.get('unit') not in {record['currency'], 'currency', 'money'}:
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
        metric_name = str(dimensions.get('component') or dimensions.get('driver_key') or record['metric_key'].split('.')[-1]).replace('_', ' ').upper()
        label = str(record.get('label') or record.get('claim_kind') or '')
        display_scope = [when, str(subject['key'])]
        if record.get('business_unit'):
            display_scope.append(str(record['business_unit']))
        if record.get('scenario'):
            display_scope.append(str(record['scenario']))
        display_scope.extend(f'{key.replace("_", " ")}: {value}' for key, value in identity_dimensions.items()
                             if key not in {'driver_key', 'component_key', 'presentation_component'}
                             and not (key == 'series' and str(value).casefold() in {
                                 label.casefold(), str(record.get('claim_kind') or '').casefold()}))
        displayed_value = f'{unit} {Decimal(normalized):,f}' if value_type == 'numeric' else normalized
        display_text = f'{metric_name} ({label}): {displayed_value}\n' + ' · '.join(display_scope)
        if isinstance(dimensions.get('driver'), str) and dimensions['driver'].strip():
            display_text += '\nRecorded source commentary: ' + dimensions['driver']
        # The semantic selector must also see recorded context, not only a
        # hand-picked subset of dimension names. It remains untrusted evidence.
        context_text = json.dumps(dimensions, ensure_ascii=False, sort_keys=True, default=str)
        result[ref] = {'ref':ref, 'text':' · '.join(parts) + f': {normalized} {unit}\nRecorded context: {context_text}',
                       'display_text':display_text, 'record':record, 'value':normalized, 'unit':unit}
    return result


def fact_batches(registry, *, max_bytes=180_000):
    """Pack every fact into bounded requests; never discard or shorten a fact."""
    batch, size = {}, 0
    for ref, fact in registry.items():
        encoded_size = len(json.dumps({'ref': ref, 'text': fact['text'],
            'formula': fact['record'].get('formula')}, ensure_ascii=False).encode('utf-8'))
        if batch and size + encoded_size > max_bytes:
            yield batch
            batch, size = {}, 0
        batch[ref] = fact
        size += encoded_size
    if batch:
        yield batch


def render_selection(selection, registry, *, run_id):
    if (not isinstance(selection, Mapping) or set(selection) != {'matched','fact_refs'}
            or not isinstance(selection['matched'], bool)
            or not isinstance(selection['fact_refs'], list)):
        raise ValueError('Only the governed fact-selection contract is accepted.')
    refs = selection['fact_refs']
    if (any(not isinstance(ref,str) or ref not in registry for ref in refs)
            or len(set(refs)) != len(refs) or bool(refs) != selection['matched']):
        raise ValueError('Every selected fact must belong to this authorized snapshot.')
    if not refs:
        return {'matched':False,'answer':"I could not find a source-backed answer to that question in the available evidence.",
                'basis':'Authorized claim snapshot.','citations':[],'suggestions':[], 'fact_contract':CONTRACT}
    citations=[]
    facts=[]
    for ref in refs:
        fact=registry[ref]
        record=fact['record']
        href='/api/claims/snapshots/'+quote(str(run_id),safe='')+'/revisions/'+quote(ref,safe='')
        citations.append({'source_path':'claim://'+ref,'locator':'immutable revision '+ref,
                          'excerpt':fact['display_text'],'claim_revision_id':ref,'href':href,'resolved':True})
        facts.append({'claim_revision_id':ref,'metric_key':record['metric_key'],
                      'subject':record['subject'],'period':record.get('period'),
                      'value':fact['value'],'value_type':record['value_type'],
                      'unit':fact['unit'],'claim_kind':record.get('claim_kind'),
                      'formula':record.get('formula'),'business_unit':record.get('business_unit'),
                      'scenario':record.get('scenario'),'dimensions':record.get('identity_dimensions',{})})
    from .fact_comparison import selected_comparisons
    comparisons = selected_comparisons(refs, registry)
    answer_parts = [registry[ref]['display_text'] for ref in refs]
    answer_parts.extend(item['display_text'] for item in comparisons)
    return {'matched':True,'answer':'\n\n'.join(answer_parts),
            'basis':'Immutable source facts; any labelled comparison is calculated as actual minus plan from compatible input revisions.', 'citations':citations,
            'calculated_comparisons': comparisons,
            'suggestions':[], 'fact_contract':CONTRACT,'fact_cells':facts,
            '_orchestrator_force_answer':True}
