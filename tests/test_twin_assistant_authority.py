from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from strategyos_mvp import api, auth, authority_matrix
from strategyos_mvp.twins import api as twin_api, source_scope, strategyos_data


def test_twin_investigation_denies_restricted_question_before_saved_work(monkeypatch):
    principal={'role':'operator','subject':'finance','tenant_id':'test','authenticated':True}
    monkeypatch.setattr(api,'get_authority_matrix',lambda _:authority_matrix.default_authority_matrix())
    monkeypatch.setattr(auth,'authenticate_optional_request',lambda **kwargs:principal)
    monkeypatch.setattr(twin_api,'_get_repositories',lambda:pytest.fail('Denied twin request loaded saved work'))
    overrides=dict(api.app.dependency_overrides)
    api.app.dependency_overrides[auth.authenticate_request]=lambda:principal
    try:
        response=TestClient(api.app).post('/twin/api/investigate/cfo',params={'query':'Show salaries and revenue'})
        assert response.status_code==403,response.text
        assert response.json()['detail']['authority_decision']['domain']=='hr'
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(overrides)


def test_scoped_twin_cards_and_answers_use_only_immutable_facts(monkeypatch):
    import json
    from strategyos_mvp import llm_qa, model_policy
    from tests.test_llm_qa import _config
    monkeypatch.setattr(api, 'CONFIG', _config())
    monkeypatch.setattr(model_policy, 'evidence_model_access', lambda _: True)
    selections = iter([{'matched':True,'fact_refs':['r']}, {'matched':False,'fact_refs':[]}])
    monkeypatch.setattr(llm_qa, '_call_openai_compatible_chat', lambda **kwargs: json.dumps(next(selections)))
    record={'claim_revision_id':'r','traceability':'present','value_type':'numeric','value':'120','scale':'1',
        'unit':'SAR','currency':'SAR','metric_key':'finance.revenue','subject':{'type':'client','key':'NUPCO'},
        'claim_kind':'actual','label':'Actual','sources':[]}
    monkeypatch.setattr(source_scope,'authorized_surface',lambda:{'summary':{'run_id':'run'},'assistant_records':(record,)})
    monkeypatch.setattr(api,'_latest_run_findings_payload',lambda *args,**kwargs:pytest.fail('Legacy unclassified findings loaded'))
    cards=strategyos_data.build_role_kpis('cfo')
    assert len(cards)==1 and cards[0]['claim_revision_id']=='r'
    assert cards[0]['raw_value']=='120'
    assert cards[0]['health']=='unassessed' and cards[0]['threshold'] is None
    result=strategyos_data.compose_investigation_payload('cfo','Revenue for NUPCO?')
    assert 'SAR 120' in result['response']['summary']
    assert result['evidence'][0]['claim_revision_id']=='r'
    assert result['board']['status']=='unavailable'
    missing=strategyos_data.compose_investigation_payload('cfo','Unrelated topic?')
    assert '120' not in missing['response']['summary']
    assert missing['evidence']==[]
