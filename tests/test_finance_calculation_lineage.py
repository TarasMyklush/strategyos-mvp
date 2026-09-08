"""Finance projections must retain the exact revisions used by calculations."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from strategyos_mvp.governed_finance import finance_payload_from_claim_snapshot
from strategyos_mvp.scenario_parser import parse_scenario
from test_governed_finance import _claim, _presentation_claim


def context():
    records = [_claim(key, value, kind='plan' if key.endswith('_plan') else 'actual')
               for key, value in {'revenue_actual':'1000','revenue_plan':'900',
                   'ebitda_actual':'200','ebitda_plan':'150','operating_cost_actual':'800',
                   'operating_cost_plan':'750'}.items()]
    for driver, actual, plan in [('revenue','176','171'),('operating_cost','138.2','135.1')]:
        for series, value in [('actual',actual),('plan',plan)]:
            records.append(_presentation_claim('contributor',driver=driver,series=series,
                label='Digital Health',value=value,business_unit='Digital Health'))
    # More than twenty revisions prove batching preserves the complete ranking universe.
    for i in range(12):
        for series, value in [('actual',str(i+10)),('plan',str(i+9))]:
            records.append(_presentation_claim('cost_component',driver='operating_cost',
                series=series,label=f'Cost {i}',value=value,business_unit='Digital Health',
                extra_dimensions={'component':'Cost '+str(i),'driver':'Source-owned explanation'}))
    for record in records:
        record.update(value_type='numeric',subject={'type':'group','key':'mizan'},
                      period={'start':'2026-01-01','end':'2026-06-30'})
    finance=finance_payload_from_claim_snapshot({}, {'records':records})
    return {'run_id':'approved-run','summary':{'finance_kpi':finance},
            'bundle':SimpleNamespace(authorized_claim_records=records)}


@pytest.mark.parametrize('prompt,scenario',[
    ('What are the top three costs in Digital Health?', 'governed_bu_cost_ranking'),
    ('How does Digital Health compare to budget?', 'governed_bu_budget_bridge'),
])
def test_projected_calculation_has_exact_immutable_inputs(prompt,scenario):
    ctx=context()
    result=parse_scenario(prompt,ctx)
    assert result.scenario_id==scenario
    assert result.calculations
    inputs=result.calculations[0].inputs['facts']
    expected={r['claim_revision_id'] for r in ctx['bundle'].authorized_claim_records
              if r['metric_key']=='ceo.presentation.cost_component' or
              (scenario=='governed_bu_budget_bridge' and r['metric_key']=='ceo.presentation.contributor')}
    assert {fact['claim_revision_id'] for fact in inputs}==expected
    assert {c['claim_revision_id'] for c in result.citations}==expected
    assert all(c['source_path'].startswith('claim://') and
               c['href'].startswith('/api/claims/snapshots/approved-run/revisions/') for c in result.citations)
    if scenario=='governed_bu_budget_bridge':
        assert result.calculations[0].result['ebitda_actual_sar']=='37.8'
        assert result.calculations[0].result['ebitda_plan_sar']=='35.9'


@pytest.mark.parametrize('change',['missing','stale','untraceable','missing_run','period','currency'])
@pytest.mark.parametrize('prompt', ['Top three costs in Digital Health', 'Digital Health versus budget'])
def test_incomplete_calculation_lineage_fails_closed(change,prompt):
    ctx=context()
    records=deepcopy(ctx['bundle'].authorized_claim_records)
    if change=='missing': records.pop()
    elif change=='stale': records[-1]['superseded_since_analysis']=True
    elif change=='untraceable': records[-1]['traceability']='missing'
    elif change=='period': records[-1]['period']['end']='2026-05-31'
    elif change=='currency': records[-1]['currency']='USD'
    else: ctx.pop('run_id')
    ctx['bundle'].authorized_claim_records=records
    result=parse_scenario(prompt,ctx)
    assert result.scenario_type=='missing_data'
    assert not result.citations
    assert all(step.result == "missing_governed_inputs" for step in result.calculations)
    assert 'complete immutable inputs' in result.answer


def test_legacy_scenario_cannot_bypass_authenticated_provenance(monkeypatch):
    from strategyos_mvp import scenario_parser
    from strategyos_mvp.models import ScenarioResult
    monkeypatch.setattr(scenario_parser, '_parse_scenario', lambda *args: ScenarioResult(
        scenario_id='legacy', scenario_label='Legacy', matched=True, answer='Profit is SAR 999.',
        citations=[{'source_path':'dataset://unverified-file'}]))
    result=scenario_parser.parse_scenario('profit',context())
    assert result.scenario_type=='missing_data'
    assert '999' not in result.answer


@pytest.mark.parametrize('endpoint',['/qa','/assistant/chat'])
def test_budget_bridge_reaches_http_with_immutable_calculation_inputs(monkeypatch,endpoint):
    from fastapi.testclient import TestClient
    from strategyos_mvp import api, auth, authority_matrix
    from strategyos_mvp.governed_qa_context import claim_backed_bundle
    principal={'tenant_id':'test','subject':'ceo','role':'executive','authenticated':True}
    fixture=context()
    fixture.update(run_mode='full',findings=[],kg_nodes=[],kg_edges=[])
    fixture['bundle']=claim_backed_bundle(fixture['bundle'].authorized_claim_records)
    monkeypatch.setattr(api,'_resolve_qa_context',lambda _:fixture)
    monkeypatch.setattr(api,'_ceo_kpi_cards',lambda *args,**kwargs:[])
    monkeypatch.setattr(api,'_summary_with_governed_claim_snapshot',lambda summary,**kwargs:summary)
    monkeypatch.setattr(api,'get_authority_matrix',lambda _:authority_matrix.default_authority_matrix())
    monkeypatch.setattr(auth,'authenticate_optional_request',lambda **kwargs:principal)
    overrides=dict(api.app.dependency_overrides)
    api.app.dependency_overrides[auth.authenticate_request]=lambda:principal
    api.app.dependency_overrides[api.authenticate_optional_request]=lambda:principal
    try:
        response=TestClient(api.app).post(endpoint,json={'question':'Digital Health versus budget','persona':'ceo','mode':'deterministic'})
        assert response.status_code==200,response.text
        payload=response.json()
        assert payload['scenario_id']=='governed_bu_budget_bridge',payload
        assert payload['calculations'][0]['result']['ebitda_actual_sar']=='37.8'
        assert len(payload['citations'])==28
        assert all(c['href'].startswith('/api/claims/snapshots/approved-run/revisions/') for c in payload['citations'])
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(overrides)
