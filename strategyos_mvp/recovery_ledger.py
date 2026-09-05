"""Reconcile reviewed receipts and reversals against resolving source evidence."""
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
from typing import Iterable, Mapping, Any


def reconcile(events: Iterable[Mapping[str, Any]], *, eligible_cases: set[str], root: Path) -> dict:
    rows=list(events); seen={}; receipts={}; reversals=[]; errors=[]; evidence=[]
    for event in rows:
        identity=str(event.get('event_id') or '')
        if identity in seen:
            if dict(event)!=seen[identity]:errors.append('Conflicting duplicate event: '+identity)
            continue
        seen[identity]=dict(event)
        case=str(event.get('case_id') or '')
        try:
            amount=Decimal(str(event.get('amount_sar')))
            if not amount.is_finite() or amount<=0:raise ValueError()
        except (ValueError,InvalidOperation):
            errors.append('A positive finite SAR amount is required: '+identity);continue
        source=event.get('evidence') or {};path=(root/str(source.get('path') or '')).resolve()
        if not identity or case not in eligible_cases or event.get('status')!='reviewed' or not event.get('reviewed_by'):
            errors.append('Unreviewed or out-of-scope receipt: '+identity);continue
        if not path.is_relative_to(root.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=source.get('sha256'):
            errors.append('Evidence missing or changed: '+identity);continue
        evidence.append({'event_id':identity,'case_id':case,**source})
        if event.get('kind')=='receipt':receipts[identity]={'case_id':case,'amount':amount,'remaining':amount}
        elif event.get('kind')=='reversal':reversals.append((identity,case,amount,event.get('reverses_event_id')))
        else:errors.append('Unsupported receipt event: '+identity)
    for identity,case,amount,target in reversals:
        receipt=receipts.get(target)
        if receipt is None or receipt['case_id']!=case or amount>receipt['remaining']:
            errors.append('Reversal does not reconcile: '+identity);continue
        receipt['remaining']-=amount
    if errors:
        return {'status':'needs_review','recovered_sar':None,'errors':sorted(errors),'evidence':evidence}
    totals={case:Decimal('0') for case in eligible_cases}
    for receipt in receipts.values():totals[receipt['case_id']]+=receipt['remaining']
    return {'status':'reconciled','recovered_sar':float(sum(totals.values(),Decimal('0'))),
            'by_case':{case:float(value) for case,value in sorted(totals.items())},
            'unique_event_count':len(seen),'evidence':evidence,'errors':[]}
