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


@pytest.mark.parametrize('candidate',['SAR 999M','USD 42,912','42,912%','SAR 42,912 billion',{'chart':{'caption':'SAR 999 trillion'}}])
def test_invented_values_currency_and_units_fail_closed(candidate):
    assert not claims_supported(candidate,'SAR 42,912')


def test_equivalent_financial_units_are_accepted():
    assert claims_supported('SAR 2,400,000','SAR 2.4M')
