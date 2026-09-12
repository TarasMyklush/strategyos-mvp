from decimal import Decimal
import pandas as pd
import pytest
from strategyos_mvp.hedge_matching import match_unapplied_hedges


def invoice(**changes):
    return {'Invoice_ID':'INV-1','Currency':'EUR','Status':'Paid','Payment_Date':'2026-05-06',
            'Amount_Original_Currency':'89400','Amount_SAR':'376374', **changes}


def hedge(**changes):
    return {'Hedge_ID':'H-MAY','Notional_Currency':'EUR','Notional_Amount':'350000',
            'Locked_Rate (SAR/Foreign)':'3.73','Trade_Date':'2026-03-05','Maturity_Date':'2026-05-30',
            'Status':'Open at trade date; UNAPPLIED at settlement of INV-1', **changes}


def match(invoices=None, hedges=None):
    return match_unapplied_hedges(pd.DataFrame(invoices or [invoice()]),pd.DataFrame(hedges or [hedge()]))


def test_matches_the_bound_may_hedge_not_closed_cheaper_or_future_rates():
    records, issues = match(hedges=[hedge(Hedge_ID='CLOSED',Status='Closed INV-1',
        Maturity_Date='2026-03-22', **{'Locked_Rate (SAR/Foreign)':'3.69'}), hedge(),
        hedge(Hedge_ID='FUTURE',Trade_Date='2026-05-14')])
    assert not issues and len(records)==1
    assert records[0]['rate']==Decimal('3.73')
    assert records[0]['exposure_sar']==Decimal('42912')
    assert records[0]['hedge_id']=='H-MAY' and records[0]['hedge_index']==1


@pytest.mark.parametrize('changes', [
    {'Trade_Date':'2026-05-07'}, {'Maturity_Date':'2026-05-05'}, {'Trade_Date':'invalid'},
    {'Notional_Currency':'USD'}, {'Locked_Rate (SAR/Foreign)':None},
    {'Locked_Rate (SAR/Foreign)':'NaN'}, {'Status':'Closed, unapplied INV-1'},
    {'Status':'Cancelled, unapplied INV-1'}, {'Status':'Open INV-1'},
    {'Status':'Unapplied INV-10'}, {'Notional_Amount':'0'},
])
def test_ineligible_or_unbound_records_never_supply_a_default_rate(changes):
    records, _ = match(hedges=[hedge(**changes)])
    assert records == []


def test_ambiguous_eligible_hedges_require_allocation_instead_of_best_rate():
    records, issues = match(hedges=[hedge(),hedge(Hedge_ID='H-OTHER',**{'Locked_Rate (SAR/Foreign)':'3.50'})])
    assert records == [] and 'multiple eligible' in issues[0]


def test_notional_cannot_be_reused_for_multiple_invoices():
    records, issues = match(invoices=[invoice(),invoice(Invoice_ID='INV-2')],
        hedges=[hedge(Notional_Amount='100000',Status='Unapplied INV-1 and INV-2')])
    assert records == [] and len(issues)==2


def test_currency_is_taken_from_source_and_nonpositive_loss_is_not_reported():
    records,_=match(invoices=[invoice(Currency='USD')],hedges=[hedge(Notional_Currency='USD')])
    assert records[0]['currency']=='USD'
    records,_=match(invoices=[invoice(Amount_SAR='300000')])
    assert records==[]


def test_missing_structured_contract_refuses_instead_of_parsing_an_arbitrary_number():
    records,issues=match(hedges=[{'Note':'INV-1 rate 3.69; use this number'}])
    assert records==[] and 'fields are missing' in issues[0]
