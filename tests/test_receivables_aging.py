from datetime import date
from decimal import Decimal
import pytest
from strategyos_mvp.receivables_aging import reconcile_aging


def invoice(identity,amount,due,customer='C1',issued='2026-01-01'):
    return dict(Invoice_ID=identity,Amount_SAR=amount,Due_Date=due,Customer_ID=customer,Invoice_Date=issued)


def receipt(identity,invoice,amount,when='2026-06-20'):
    return dict(Receipt_ID=identity,Applied_Invoice=invoice,Amount_SAR=amount,Receipt_Date=when)


def test_aging_applied_partial_receipts_reversals_future_dates_and_segments():
    invoices=[invoice('A',100,'2026-03-01'),invoice('B',200,'2026-06-10','C2'),invoice('C',300,'2026-07-10'),invoice('D',500,'2026-08-01',issued='2026-07-01')]
    receipts=[receipt('R1','A',40),receipt('R2','A',-10),receipt('R3','B',200,'2026-07-01')]
    result=reconcile_aging(invoices,[{'Customer_ID':'C1','Segment':'Government'},{'Customer_ID':'C2','Segment':'Retail'}],receipts+[receipts[0]],as_of=date(2026,6,30))
    assert Decimal(result['total_open_sar'])==570
    by={r['segment']:r for r in result['rows']}
    assert Decimal(by['Government']['90+ days'])==70
    assert Decimal(by['Government']['Current'])==300
    assert Decimal(by['Retail']['1–30 days'])==200
    assert result['open_invoice_count']==3
    shuffled=reconcile_aging(list(reversed(invoices)),[{'Customer_ID':'C1','Segment':'Government'},{'Customer_ID':'C2','Segment':'Retail'}],list(reversed(receipts)),as_of=date(2026,6,30))
    assert shuffled['rows']==result['rows']


def test_aging_does_not_silently_net_overpayment_or_ambiguous_ids():
    invoices=[invoice('A',100,'2026-01-01')]
    result=reconcile_aging(invoices,[],[receipt('R','A',120)],as_of=date(2026,6,30))
    assert result['total_open_sar']=='0' and result['excess_applied_receipts_sar']=='20'
    with pytest.raises(ValueError,match='Conflicting invoice'):
        reconcile_aging(invoices+[invoice('A',200,'2026-01-01')],[],[],as_of=date(2026,6,30))
    with pytest.raises(ValueError,match='Conflicting receipt'):
        reconcile_aging(invoices,[],[receipt('R','A',10),receipt('R','A',20)],as_of=date(2026,6,30))
    with pytest.raises(ValueError,match='Nonfinite'):
        reconcile_aging([invoice('A','NaN','2026-01-01')],[],[],as_of=date(2026,6,30))
