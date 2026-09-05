import pytest

from strategyos_mvp.claim_contracts import claims_supported
from strategyos_mvp.metric_contracts import MetricDefinition, finite_number, measurement_status
from strategyos_mvp.source_strategy_enrichment import _plan_health


@pytest.mark.parametrize("actual,target,lower,expected", [(0,100,False,0),(0,100,True,1.2),(0,0,True,1),(1,0,True,0),(1,0,False,None),(None,100,False,None)])
def test_zero_and_missing_values_have_distinct_semantics(actual, target, lower, expected):
    metric = MetricDefinition(direction="lower_is_better" if lower else "higher_is_better")
    assert metric.attainment(actual, target) == expected


@pytest.mark.parametrize("value", [float('nan'),float('inf'),True,None,'not supplied'])
def test_invalid_measurements_are_missing(value):
    assert finite_number(value) is None
    assert measurement_status(value) == 'missing'


def test_renamed_metrics_and_stale_labels_do_not_control_status():
    rows=[{'KPI_ID':'client-cost','KPI_Name':'Cost','actual':120,'checkpoint':100,'direction':'lower_is_better','weight':3,'Status vs path':'ON'},
          {'KPI_ID':'client-sales','KPI_Name':'Sales','actual':0,'checkpoint':100,'weight':1,'Status vs path':'AHEAD'}]
    result=_plan_health(rows,'metrics.json')
    assert result['live_count']==2
    assert result['behind_count']==2
    assert result['score']==62.5
    assert all(row['status_vs_path']=='BEHIND' for row in result['commitments'])


@pytest.mark.parametrize('candidate',['SAR 999M','USD 42,912','CHF 42,912','42,912%','SAR 42,912 billion',{'chart':{'caption':'SAR 999 trillion'}}])
def test_invented_values_currency_and_units_fail_closed(candidate):
    assert not claims_supported(candidate,'SAR 42,912')


def test_equivalent_financial_units_are_accepted():
    assert claims_supported('SAR 2,400,000','SAR 2.4M')


def test_workbook_headers_supply_explicit_currency_and_scale():
    assert claims_supported('SAR 758M', 'FY2026 Budget (SAR M): 758; RF1 (SAR M): 782')
    assert not claims_supported('USD 758M', 'FY2026 Budget (SAR M): 758')
    assert not claims_supported('SAR 24M', 'FY2026 Budget (SAR M): 758; RF1 (SAR M): 782')


def test_display_rounding_is_bounded_and_currency_specific():
    assert claims_supported('SAR 794K', 'SAR 794108')
    assert claims_supported('SAR 385.1M', 'SAR 385079908.90')
    assert not claims_supported('SAR 795K', 'SAR 794108')
    assert not claims_supported('USD 794K', 'SAR 794108')
    assert not claims_supported('SAR 1M', 'SAR 794108')
    assert not claims_supported('794000%', '794108%')


def test_delta_inherits_only_unambiguous_same_row_money_unit():
    from strategyos_mvp.claim_contracts import approved_evidence_text
    row = 'Budget (SAR M): 758; RF1 (SAR M): 782; Delta vs budget: +24.0; Basis: demand'
    assert claims_supported('SAR 24M', approved_evidence_text(row))
    assert not claims_supported('SAR 24M', approved_evidence_text(row.replace('RF1 (SAR M)', 'RF1 (USD M)')))


def test_workbook_percentage_and_basis_point_headers_type_only_their_cell():
    row = 'BU: Sample; 2025 EBITDA %: 27.4; EBITDA % 2025A: 39; Headroom (bps): 300; Peer median: 42'
    assert claims_supported('27.4%; 39%; 300 basis points', row)
    assert not claims_supported('42%', row)
    assert not claims_supported('300%', row)
    assert not claims_supported('3 percentage points', row)
    assert not claims_supported('SAR 27.4', row)
    assert not claims_supported('27.4%', 'EBITDA %: unavailable; Revenue: 27.4')
    assert not claims_supported('27.4%', 'EBITDA %: unavailable\nRevenue: 27.4')


def test_question_percentage_is_not_promoted_to_evidence():
    from strategyos_mvp.claim_contracts import approved_evidence_text
    assert not claims_supported('35%', approved_evidence_text({'question': 'Premium %: 35', 'facts': 'No site benchmark supplied'}))


def test_explicit_unit_only_and_impact_headers_do_not_type_exchange_rates():
    assert claims_supported('SAR 2120M','Year: 2024; SAR M impact: 2120; Source: Group strategy')
    assert claims_supported('USD 25K','USD K: 25')
    assert not claims_supported('SAR 2120M','Year: 2024; impact: 2120')
    assert not claims_supported('USD 2120M','SAR M impact: 2120')
    assert not claims_supported('SAR 4.2M','SAR M per EUR: 4.2')
