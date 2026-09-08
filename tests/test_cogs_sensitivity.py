from types import SimpleNamespace
import pytest
from strategyos_mvp.scenario_parser import parse_scenario, has_scenario_intent

QUESTION='How sensitive is group EBITDA to a 1% change in COGS?'


def records():
    common={'traceability':'present','value_type':'numeric','scale':'1','unit':'SAR','currency':'SAR',
        'claim_kind':'actual','label':'Actual','subject':{'type':'enterprise','key':'group'},
        'period':{'start':'2026-01-01','end':'2026-06-30'},'sources':[]}
    return [{**common,'claim_revision_id':'cogs','metric_key':'ceo.cogs','value':'10000'},
            {**common,'claim_revision_id':'ebitda','metric_key':'ceo.ebitda','value':'2000'}]


def test_cogs_sensitivity_has_exact_arithmetic_and_immutable_inputs():
    assert has_scenario_intent(QUESTION)
    result=parse_scenario(QUESTION,{'run_id':'run','bundle':SimpleNamespace(authorized_claim_records=records())})
    assert result.scenario_type=='governed_calculation'
    step=result.calculations[0]
    assert step.result=={'ebitda_change_sar':'100.00','ebitda_after_cogs_increase_sar':'1900.00','ebitda_after_cogs_decrease_sar':'2100.00'}
    assert {fact['claim_revision_id'] for fact in step.inputs['facts']}=={'cogs','ebitda'}
    assert step.inputs['rate']['kind']=='user_assumption'
    assert all(c['href'].startswith('/api/claims/snapshots/run/revisions/') for c in result.citations)


@pytest.mark.parametrize('change',[
    {'business_unit':'east'}, {'scenario':'budget'}, {'claim_kind':'plan'},
    {'currency':'USD'}, {'unit':'percent'}, {'value':'-10000'},
    {'period':{'start':'2025-01-01','end':'2025-06-30'}},
    {'subject':{'type':'enterprise','key':'other'}}, {'traceability':'missing'},
])
def test_sensitivity_cannot_mix_period_scope_currency_or_unapproved_inputs(change):
    items=records();items[0].update(change)
    result=parse_scenario(QUESTION,{'run_id':'run','bundle':SimpleNamespace(authorized_claim_records=items)})
    assert result.scenario_type=='missing_data' and not result.citations
    assert '100.00' not in result.answer


def test_sensitivity_does_not_infer_missing_group_cogs_from_legacy_display():
    result=parse_scenario(QUESTION,{'summary':{'finance_kpi':{'components':{
        'revenue_actual':20000,'operating_cost_actual':8000,'ebitda_actual':2000}}}})
    assert result.scenario_type=='missing_data'


@pytest.mark.parametrize('endpoint',['/qa','/assistant/chat'])
def test_sensitivity_reaches_the_real_http_scenario_route(monkeypatch,endpoint):
    from fastapi.testclient import TestClient
    from strategyos_mvp import api, auth, authority_matrix
    from strategyos_mvp.governed_qa_context import claim_backed_bundle
    principal={'tenant_id':'test','subject':'ceo','role':'executive','authenticated':True}
    context={'run_id':'run','run_mode':'full','summary':{'run_id':'run'},
        'bundle':claim_backed_bundle(records()),'findings':[],'kg_nodes':[],'kg_edges':[]}
    monkeypatch.setattr(api,'_resolve_qa_context',lambda _:context)
    monkeypatch.setattr(api,'_ceo_kpi_cards',lambda *args,**kwargs:[])
    monkeypatch.setattr(api,'_summary_with_governed_claim_snapshot',lambda summary,**kwargs:summary)
    monkeypatch.setattr(api,'get_authority_matrix',lambda _:authority_matrix.default_authority_matrix())
    monkeypatch.setattr(auth,'authenticate_optional_request',lambda **kwargs:principal)
    overrides=dict(api.app.dependency_overrides)
    api.app.dependency_overrides[auth.authenticate_request]=lambda:principal
    api.app.dependency_overrides[api.authenticate_optional_request]=lambda:principal
    try:
        response=TestClient(api.app).post(endpoint,json={'question':QUESTION,'persona':'ceo','mode':'deterministic'})
        assert response.status_code==200,response.text
        payload=response.json()
        assert payload['scenario_id']=='consolidated_cogs_sensitivity',payload
        assert 'SAR 1,900.00' in payload['answer']
        assert payload['calculations'][0]['inputs']['facts'][0]['claim_revision_id']=='cogs'
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(overrides)
