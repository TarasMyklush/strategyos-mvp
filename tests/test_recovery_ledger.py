import hashlib
from strategyos_mvp.recovery_ledger import reconcile


def test_ninth_receipt_partial_payment_reversal_order_and_duplicate_delivery(tmp_path):
    proof=tmp_path/'receipts.csv';proof.write_text('test-reviewed-bank-evidence')
    evidence={'path':proof.name,'sha256':hashlib.sha256(proof.read_bytes()).hexdigest()}
    rows=[{'event_id':f'receipt-{i}','case_id':f'case-{i}','kind':'receipt','amount_sar':100,
           'status':'reviewed','reviewed_by':'synthetic-test-review','evidence':evidence} for i in range(9)]
    cases={row['case_id'] for row in rows}
    assert reconcile(rows[:8],eligible_cases=cases,root=tmp_path)['recovered_sar']==800
    rows.append({**rows[-1],'event_id':'reversal-9','kind':'reversal','amount_sar':25,'reverses_event_id':'receipt-8'})
    result=reconcile(rows,eligible_cases=cases,root=tmp_path)
    assert result['recovered_sar']==875
    assert result['by_case']['case-8']==75
    assert reconcile(list(reversed(rows))+[rows[0]],eligible_cases=cases,root=tmp_path)['recovered_sar']==875
    proof.write_text('changed')
    assert reconcile(rows,eligible_cases=cases,root=tmp_path)['recovered_sar'] is None


def test_unreviewed_or_excess_reversal_never_inflates_recovery(tmp_path):
    proof=tmp_path/'receipt.txt';proof.write_text('evidence')
    row={'event_id':'a','case_id':'c','kind':'receipt','amount_sar':100,'status':'reviewed','reviewed_by':'test',
         'evidence':{'path':proof.name,'sha256':hashlib.sha256(proof.read_bytes()).hexdigest()}}
    reversal={**row,'event_id':'b','kind':'reversal','amount_sar':101,'reverses_event_id':'a'}
    assert reconcile([row,reversal],eligible_cases={'c'},root=tmp_path)['recovered_sar'] is None
    assert reconcile([{**row,'status':'proposed'}],eligible_cases={'c'},root=tmp_path)['recovered_sar'] is None
