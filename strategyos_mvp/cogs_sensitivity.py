"""Consolidated COGS sensitivity from compatible immutable input revisions."""
from decimal import Decimal, ROUND_HALF_UP, localcontext
import re
from .fact_rendering import fact_registry, render_selection
from .models import CalculationStep, ScenarioResult


def calculate(prompt, context):
    text=prompt.casefold()
    if not ('ebitda' in text and ('cogs' in text or 'cost of goods sold' in text)
            and ('group' in text or 'consolidated' in text)
            and any(word in text for word in ('sensitive','sensitivity','change','increase','decrease'))):
        return None
    missing=ScenarioResult(scenario_id='consolidated_cogs_sensitivity',
        scenario_label='Consolidated COGS sensitivity',matched=True,
        answer='This sensitivity needs one approved consolidated COGS fact and one EBITDA fact for the same subject, period and currency, plus a percentage change. BU rows and inferred residuals cannot replace that consolidated baseline.',
        scenario_type='missing_data',basis='Compatible immutable consolidated inputs are required.')
    rates=re.findall(r'(?<![\w.])([+-]?\d+(?:\.\d+)?)\s*%',prompt)
    if len(rates)!=1:
        return missing
    rate=Decimal(rates[0])/100
    if not Decimal(0)<rate<=1:
        return missing
    records=getattr(context.get('bundle'),'authorized_claim_records',None)
    if records is None:
        return missing
    registry=fact_registry(records)
    chosen=[]
    for metric in ('ceo.cogs','ceo.ebitda'):
        matches=[fact for fact in registry.values() if fact['record']['metric_key']==metric
                 and fact['record'].get('claim_kind')=='actual'
                 and not fact['record'].get('business_unit') and not fact['record'].get('scenario')]
        if len(matches)!=1:
            return missing
        chosen.append(matches[0])
    cogs,ebitda=chosen
    first,second=cogs['record'],ebitda['record']
    period=first.get('period') or {}
    if (first['subject']!=second['subject'] or period!=second.get('period')
            or not period.get('start') or not period.get('end')
            or first.get('currency')!='SAR' or second.get('currency')!='SAR'
            or first.get('unit')!='SAR' or second.get('unit')!='SAR'
            or Decimal(cogs['value'])<0):
        return missing
    with localcontext() as arithmetic:
        arithmetic.prec=512
        delta=(Decimal(cogs['value'])*rate).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        current=Decimal(ebitda['value'])
        lower,higher=current-delta,current+delta
    refs=[fact['ref'] for fact in chosen]
    run_id=context.get('run_id') or (context.get('summary') or {}).get('run_id')
    if not run_id:
        return missing
    citation_result=render_selection({'matched':True,'fact_refs':refs},registry,run_id=run_id)
    assumption='Revenue and all other costs remain constant; the percentage is a user-specified scenario assumption.'
    answer=(f"For {period['start']} to {period['end']}, a {rates[0]}% increase in consolidated COGS "
            f"lowers group EBITDA by SAR {delta:,.2f}, from SAR {current:,.2f} to SAR {lower:,.2f}. "
            f"The same percentage decrease raises EBITDA to SAR {higher:,.2f}. "
            +assumption+' This is a sensitivity calculation, not a forecast.')
    return ScenarioResult(scenario_id='consolidated_cogs_sensitivity',scenario_label='Consolidated COGS sensitivity',
        matched=True,answer=answer,scenario_type='governed_calculation',
        basis='consolidated-cogs-sensitivity-v1; immutable, period-aligned input revisions.',
        citations=citation_result['citations'],assumptions=[assumption],
        calculations=[CalculationStep(step_id='consolidated-cogs-sensitivity-v1',
            description='Apply a symmetric COGS change while holding other income and costs constant.',
            formula='delta = consolidated COGS × rate; EBITDA after increase = EBITDA - delta; after decrease = EBITDA + delta',
            inputs={'facts':citation_result['fact_cells'],'rate':{'value':str(rate),'kind':'user_assumption'}},
            result={'ebitda_change_sar':str(delta),'ebitda_after_cogs_increase_sar':str(lower),
                    'ebitda_after_cogs_decrease_sar':str(higher)},unit='SAR',
            citations=citation_result['citations'],assumptions=[assumption])])
