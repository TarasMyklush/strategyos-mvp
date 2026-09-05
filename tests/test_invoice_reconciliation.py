from decimal import Decimal
import pytest
from strategyos_mvp.invoice_reconciliation import reconcile


def test_signed_line_reconciliation_reports_missing_orphan_and_cent_tolerance():
    headers = [{'Invoice_ID': i, 'Amount_SAR': value} for i, value in [('A',100),('B',200),('C',50)]]
    lines = [{'Invoice_ID': i, 'Line_No': n, 'Line amount (SAR)': value} for i,n,value in [('A',1,120),('A',2,-20),('B',1,'199.98'),('D',1,75)]]
    result = reconcile(headers, lines)
    assert result['covered_invoice_count'] == 2
    assert result['missing_lines'] == ['C'] and result['orphan_lines'] == ['D']
    assert result['mismatches'] == [{'invoice_id':'B','header_sar':'200','lines_sar':'199.98','difference_sar':'-0.02'}]
    assert reconcile(list(reversed(headers)), list(reversed(lines))) == result
    lines[2]['Line amount (SAR)'] = '199.99'
    assert not reconcile(headers, lines)['mismatches']
    with pytest.raises(ValueError, match='Duplicate invoice line'):
        reconcile(headers, lines + [lines[0]])
    with pytest.raises(ValueError, match='duplicate header'):
        reconcile(headers + [headers[0]], lines)


def test_failed_calculation_is_not_reported_as_available(monkeypatch):
    from strategyos_mvp import qa
    def fail(*args):
        raise RuntimeError('private source path')
    monkeypatch.setattr(qa, 'INTENTS', (qa._Intent('test', lambda q: True, fail),))
    result = qa.answer_question('calculate', bundle=object(), findings=[])
    assert result['matched'] is False and result['available'] is False
    assert 'private source path' not in str(result)
