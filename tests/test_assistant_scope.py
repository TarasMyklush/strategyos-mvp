from dataclasses import replace
from types import SimpleNamespace

import pytest

from strategyos_mvp.assistant_scope import bind_assistant, current_scope, restrict_legacy_context
from strategyos_mvp.authority_matrix import default_authority_matrix
from strategyos_mvp.claim_store import ClaimRepository
from strategyos_mvp.source_claims import PolicyContext, ClaimQuery
from datetime import datetime, UTC


def test_bound_authority_cannot_be_widened_and_resets_after_exception(monkeypatch):
    with pytest.raises(RuntimeError):
        with bind_assistant(SimpleNamespace(persona='cfo'), {'subject': 'finance-user'}, default_authority_matrix()):
            context = PolicyContext('tenant', 'finance-user', frozenset({'executive'}), 'executive_briefing', allowed_domains=frozenset({'finance','hr'}))
            assert context.allowed_domains == frozenset({'finance'})
            repo = ClaimRepository(lambda: pytest.fail('Restricted metric reached the database'))
            query = ClaimQuery('tenant','hr.salary','executive_briefing',datetime.now(UTC),frozenset({'actual'}))
            assert repo.query(query,context=context)==[]
            raise RuntimeError('test request failed')
    assert current_scope.get() is None


def test_unclassified_legacy_prose_is_not_an_authority_backdoor():
    with bind_assistant(SimpleNamespace(persona='cfo'), {}, default_authority_matrix()):
        result = restrict_legacy_context({'summary': {'run_id':'run', 'canonical_claim_status':'ready',
            'finance_kpi':{'revenue':120}, 'strategy_enrichment':{'employee_salary':999}},
            'findings':[{'private':'compensation'}], 'kg_nodes':[{'secret':'HR'}]})
        assert result['summary']=={'run_id':'run','canonical_claim_status':'ready','finance_kpi':{'revenue':120}}
        assert result['findings']==[] and result['kg_nodes']==[]


def test_explicit_human_policy_narrows_assistant_retrieval():
    matrix=default_authority_matrix()
    matrix['subjects'].append({'id':'user:restricted','rights':{'contracts':'view'}})
    with bind_assistant(SimpleNamespace(persona='cfo'), {'subject':'restricted'}, matrix):
        assert current_scope.get().domains==frozenset({'contracts'})


def test_finance_adapter_does_not_forward_unclassified_record_fields():
    from strategyos_mvp.governed_qa_context import claim_backed_bundle
    record = {'metric_key':'finance.transaction.amount', 'value':'120', 'scale':'1',
        'subject':{'type':'ap_invoice','key':'invoice'},
        'dimensions':{'transaction_type':'ap_invoice','record':{
            'Invoice_ID':'invoice','Employee_Salary':999,'Private_Notes':'employee medical leave'}},
        'sources':[]}
    with bind_assistant(SimpleNamespace(persona='cfo'), {}, default_authority_matrix()):
        rows = claim_backed_bundle([record]).ap.to_dict('records')
    assert rows[0]['Amount_SAR'] == 120
    assert 'Employee_Salary' not in rows[0] and 'Private_Notes' not in rows[0]


@pytest.mark.parametrize('endpoint', ['/qa', '/assistant/chat'])
@pytest.mark.parametrize('location', ['persona', 'context', 'assistant_context'])
def test_http_scope_is_bound_for_unclassified_paraphrases_and_reset(monkeypatch, endpoint, location):
    from fastapi.testclient import TestClient
    from strategyos_mvp import api, auth
    principal = {'subject':'finance-user','role':'executive','tenant_id':'test','authenticated':True}
    monkeypatch.setattr(api,'get_authority_matrix',lambda _:default_authority_matrix())
    observed=[]
    def capture(*args, **kwargs):
        observed.append(current_scope.get())
        return {'answer':'authorized scope reached'}
    async def capture_async(*args, **kwargs):
        return capture()
    monkeypatch.setattr(api,'_data_qa_scoped',capture)
    monkeypatch.setattr(api,'_assistant_chat_response',capture_async)
    overrides=dict(api.app.dependency_overrides)
    api.app.dependency_overrides[auth.authenticate_request]=lambda:principal
    api.app.dependency_overrides[api.authenticate_optional_request]=lambda:principal
    try:
        body={'question':'Show the amounts associated with our people'}
        body.update({'persona':'cfo'} if location=='persona' else {location:{'active_persona':'cfo'}})
        response=TestClient(api.app).post(endpoint,json=body)
        assert response.status_code==200,response.text
        assert observed and 'hr' not in observed[0].domains
        assert observed[0].subject=='assistant:atlas'
        assert current_scope.get() is None
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(overrides)


def test_human_rights_limit_an_otherwise_permitted_assistant(monkeypatch):
    from strategyos_mvp import api
    matrix=default_authority_matrix()
    matrix['subjects'].append({'id':'user:reader','rights':{'finance':'view'}})
    monkeypatch.setattr(api,'get_authority_matrix',lambda _:matrix)
    result=api._assistant_authority_refusal(
        api.AssistantChatRequest(persona='cfo',question='Why is revenue below forecast?'),
        {'subject':'reader','tenant_id':'test','role':'executive'})
    assert result['response_mode']=='authority_refusal'
    assert result['authority_decision']['subject_id']=='user:reader'


def test_restricted_assistant_cannot_use_legacy_graph_or_vector_index(monkeypatch):
    from strategyos_mvp.access_scope import source_index_allowed
    from strategyos_mvp import claim_store
    monkeypatch.setattr(claim_store,'ClaimRepository',lambda:pytest.fail('Bulk index source policy lookup must not run'))
    with bind_assistant(SimpleNamespace(persona='cfo'),{},default_authority_matrix()):
        assert source_index_allowed('run','tenant') is False


def test_persona_context_is_merged_before_authority_and_answer_routing():
    from strategyos_mvp.assistant_scope import request_persona
    request=SimpleNamespace(persona=None,context={'active_persona':'cfo'},assistant_context={'entrypoint':'drawer'})
    assert request_persona(request)=='cfo'
    with bind_assistant(request,{},default_authority_matrix()):
        assert current_scope.get().subject=='assistant:atlas'
