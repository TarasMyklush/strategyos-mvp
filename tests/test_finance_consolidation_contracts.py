from datetime import date
from decimal import Decimal
from dataclasses import replace
from strategyos_mvp.oracle_finance import (CanonicalFinanceFact,OracleCanonicalSnapshot,FXRateRecord,_sum_metric_facts,_latest_metric_fact)


def snapshot(facts,rates=()):
    return OracleCanonicalSnapshot((),(),(),tuple(facts),tuple(rates),())


def fact(key,amount,bu='A',currency='SAR',kind='cash_balance',**attributes):
    return CanonicalFinanceFact(key,'CE',kind,'2026-06-30','daily',Decimal(amount),currency,'SAR',bu_code=bu,attributes=attributes)


def metric(s,latest=True,kind='cash_balance'):
    return (_latest_metric_fact if latest else _sum_metric_facts)(s,reporting_period_key='2026-06',reporting_cadence='monthly',period_start=date(2026,6,1),period_end=date(2026,6,30),fact_types=(kind,))


def test_two_bu_balances_consolidate_and_ambiguous_accounts_fail_closed():
    a,b=fact('a','100'),fact('b','200',bu='B')
    assert metric(snapshot([a,b]))==Decimal('300')
    assert metric(snapshot([b,a]))==Decimal('300')
    assert metric(snapshot([a,fact('ambiguous','999')])) is None
    assert metric(snapshot([a,fact('distinct','50',bank_account_id='separate')]))==Decimal('150')


def test_exact_dated_fx_required_and_intercompany_pairs_reconcile():
    usd=fact('usd','100',currency='USD')
    rate=FXRateRecord('fx','USD','SAR','reviewed-source',date(2026,6,30),Decimal('3.75'))
    assert metric(snapshot([usd],[rate]))==Decimal('375')
    assert metric(snapshot([usd],[replace(rate,rate_date=date(2026,7,1))])) is None
    assert metric(snapshot([usd],[rate,replace(rate,rate_key='conflict')])) is None
    a=fact('sweep-a','100',kind='cash_flow',intercompany=True,elimination_reference='pair-1')
    b=fact('sweep-b','-100',bu='B',kind='cash_flow',intercompany=True,elimination_reference='pair-1')
    assert metric(snapshot([a,b]),False,'cash_flow')==0
    assert metric(snapshot([a]),False,'cash_flow') is None
