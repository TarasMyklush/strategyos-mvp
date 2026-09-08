from copy import deepcopy
from types import SimpleNamespace
import json
import pytest

from strategyos_mvp.fact_rendering import fact_registry, render_selection


@pytest.fixture
def record():
    return {'claim_revision_id':'approved-revision','traceability':'present','value_type':'numeric',
        'value':'1.20','scale':'1000000','unit':'SAR','currency':'SAR','metric_key':'finance.revenue',
        'subject':{'type':'client','key':'NUPCO'},'business_unit':'healthcare','scenario':'approved',
        'claim_kind':'actual','label':'Actual','period':{'start':'2026-01-01','end':'2026-06-30'},
        'formula':None,'sources':[{'source_key':'erp'}]}


@pytest.mark.parametrize('extra',[
    {'answer':'Profit was SAR 1200000'},
    {'basis':'Revenue rose because prices increased'},
    {'suggestions':['Cut workforce by 20%']},
    {'chart':{'caption':'Revenue was USD 1200000'}},
    {'fact_cells':[{'value':'1200000','unit':'USD','period':'2027'}]},
    {'citations':[{'excerpt':'Revenue was caused by a 40% price rise'}]},
])
def test_provider_cannot_relabel_values_or_attach_unapproved_causes(record,extra):
    with pytest.raises(ValueError):
        render_selection({'matched':True,'fact_refs':['approved-revision'],**extra},fact_registry([record]),run_id='run')


@pytest.mark.parametrize('refs',[['foreign-revision'],['approved-revision','approved-revision'],[{}],[]])
def test_selection_rejects_foreign_duplicate_and_invalid_references(record,refs):
    with pytest.raises(ValueError):
        render_selection({'matched':True,'fact_refs':refs},fact_registry([record]),run_id='run')


def test_rendering_binds_value_metric_subject_period_and_citation(record):
    registry=fact_registry([record])
    record['value']='999999'
    result=render_selection({'matched':True,'fact_refs':['approved-revision']},registry,run_id='run')
    assert '1200000.00 SAR' in result['answer']
    assert 'finance.revenue' in result['answer'] and 'NUPCO' in result['answer']
    assert '2026-01-01 to 2026-06-30' in result['answer']
    assert result['fact_cells'][0]['value']=='1200000.00'
    assert result['citations'][0]['excerpt']==result['answer']
    assert result['citations'][0]['href']=='/api/claims/snapshots/run/revisions/approved-revision'


def test_nonfinite_or_stale_facts_cannot_be_selected(record):
    for change in ({'value':'NaN'},{'scale':'-1'},{'value':'1E99999'},{'superseded_since_analysis':True},{'traceability':'missing'}):
        assert fact_registry([{**record,**change}])=={}


def test_provider_selection_is_rendered_and_orchestrator_cannot_rewrite_it(record,monkeypatch):
    from strategyos_mvp import llm_qa, api, model_policy
    from tests.test_llm_qa import _config
    monkeypatch.setattr(model_policy,'evidence_model_access',lambda _:True)
    monkeypatch.setattr(llm_qa,'_call_openai_compatible_chat',lambda **kwargs:json.dumps({'matched':True,'fact_refs':['approved-revision']}))
    answer=llm_qa.answer_question('Revenue for NUPCO?',bundle=SimpleNamespace(authorized_claim_records=(record,)),
        findings=[],summary={'run_id':'run'},config=_config())
    payload=api._assistant_response_payload(response_mode='llm',question='Revenue?',
        context={'run_id':'run','run_mode':'full'},requested_mode='llm',persona='cfo',
        orchestrated=SimpleNamespace(answer='Profit was USD 1200000 because salaries fell'),base_result=answer)
    assert payload['answer']==answer['answer'] and 'Profit' not in payload['answer']
    assert payload['fact_cells']==answer['fact_cells']


def test_claim_citation_endpoint_reauthorizes_identity_and_hides_missing_fact(monkeypatch):
    from strategyos_mvp import claim_api
    from fastapi import HTTPException
    seen=[]
    class Repository:
        def snapshot(self,key,**kwargs):
            seen.append((key,kwargs))
            return {'records':[]}
    monkeypatch.setattr(claim_api,'ClaimRepository',Repository)
    with pytest.raises(HTTPException) as error:
        claim_api.resolve_snapshot_fact('run','foreign-revision',principal={
            'tenant_id':'tenant-b','subject':'reader','role':'bu','business_units':['east']})
    assert error.value.status_code==404
    context=seen[0][1]['context']
    assert context.tenant_id=='tenant-b' and context.business_units==frozenset({'east'})
    assert seen[0][1]['revision_id']=='foreign-revision'
