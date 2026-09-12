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
    assert 'SAR 1,200,000.00' in result['answer']
    assert 'REVENUE' in result['answer'] and 'NUPCO' in result['answer']
    assert '2026-01-01 to 2026-06-30' in result['answer']
    assert result['fact_cells'][0]['value']=='1200000.00'
    assert result['citations'][0]['excerpt']==result['answer']
    assert result['citations'][0]['href']=='/api/claims/snapshots/run/revisions/approved-revision'


def test_nonfinite_or_stale_facts_cannot_be_selected(record):
    for change in ({'value':'NaN'},{'scale':'-1'},{'value':'1E99999'},{'superseded_since_analysis':True},{'traceability':'missing'}):
        assert fact_registry([{**record,**change}])=={}


def test_text_claim_keeps_exact_source_statement_and_claim_status(record):
    statement = 'Supplier reported a delayed shipment; the cause has not been independently verified.'
    source = {**record, 'value_type': 'text', 'value': statement, 'unit': None,
              'currency': None, 'claim_kind': 'reported_claim', 'label': 'Reported claim',
              'metric_key': 'operations.delivery_reason'}
    registry = fact_registry([source])
    source['value'] = 'Unapproved replacement'
    result = render_selection({'matched': True, 'fact_refs': ['approved-revision']}, registry, run_id='run')
    assert statement in result['answer']
    assert '(Reported claim)' in result['answer']
    assert result['fact_cells'][0]['value'] == statement
    assert result['fact_cells'][0]['value_type'] == 'text'
    assert result['citations'][0]['excerpt'] == result['answer']
    assert 'Unapproved replacement' not in result['answer']


@pytest.mark.parametrize('changes', [
    {'value': ''}, {'value': '  '}, {'value': {'answer': 'Not a source statement'}},
    {'traceability': 'missing'}, {'superseded_since_analysis': True}, {'value_type': 'unsupported'},
])
def test_invalid_or_unavailable_text_is_not_selectable(record, changes):
    source = {**record, 'value_type': 'text', 'value': 'Recorded explanation',
              'unit': None, 'currency': None, **changes}
    assert fact_registry([source]) == {}


def test_semantic_selection_receives_numeric_and_text_evidence_without_rewriting(record, monkeypatch):
    from strategyos_mvp import llm_qa, model_policy
    from tests.test_llm_qa import _config
    statement = 'Management attributes the delay to customs clearance.'
    source = {**record, 'claim_revision_id': 'qualitative', 'value_type': 'text',
              'value': statement, 'unit': None, 'currency': None,
              'claim_kind': 'reported_claim', 'label': 'Reported claim'}
    monkeypatch.setattr(model_policy, 'evidence_model_access', lambda _: True)
    def provider(**kwargs):
        packet = json.loads(kwargs['messages'][-1]['content'])
        assert {fact['ref'] for fact in packet['facts']} == {'approved-revision', 'qualitative'}
        assert statement in next(fact['text'] for fact in packet['facts'] if fact['ref'] == 'qualitative')
        return json.dumps({'matched': True, 'fact_refs': ['qualitative'], 'answer_supported': True})
    monkeypatch.setattr(llm_qa, '_call_openai_compatible_chat', provider)
    result = llm_qa.answer_question('What explanation was recorded?',
        bundle=SimpleNamespace(authorized_claim_records=[record, source]), findings=[],
        summary={'run_id': 'run'}, config=_config())
    assert statement in result['answer']
    assert result['retrieval']['facts_considered'] == 2


def test_text_evidence_page_displays_statement_as_escaped_text(record):
    from strategyos_mvp.fact_view import fact_page
    source = {**record, 'value_type': 'text', 'value': '<script>untrusted()</script> سبَب التأخير',
              'unit': None, 'currency': None, 'claim_kind': 'reported_claim', 'label': 'Reported claim'}
    response = fact_page({'record': source, 'analysis_as_of': '2026-06-30'})
    visible = response.body.decode().split('<details>')[0]
    assert '&lt;script&gt;untrusted()&lt;/script&gt;' in visible
    assert '<script>' not in visible and 'سبَب التأخير' in visible
    assert '(Reported claim)' in visible
    assert response.headers['cache-control'] == 'private, no-store'


def test_display_retains_business_scope_while_internal_components_remain_in_lineage(record):
    record['dimensions'] = {'presentation_component': 'Cost Component', 'series': 'actual',
                            'region': 'Central', 'product': 'Branded Rx', 'client': 'NUPCO'}
    registry = fact_registry([record])
    result = render_selection({'matched': True, 'fact_refs': ['approved-revision']}, registry, run_id='run')
    assert all(value in result['answer'] for value in ('Central', 'Branded Rx', 'NUPCO'))
    assert 'presentation component:' not in result['answer'] and 'series: actual' not in result['answer']
    assert result['fact_cells'][0]['dimensions'] == record['dimensions']
    assert 'presentation_component: Cost Component' in registry['approved-revision']['text']


def test_provider_selection_is_rendered_and_orchestrator_cannot_rewrite_it(record,monkeypatch):
    from strategyos_mvp import llm_qa, api, model_policy
    from tests.test_llm_qa import _config
    monkeypatch.setattr(model_policy,'evidence_model_access',lambda _:True)
    monkeypatch.setattr(llm_qa,'_call_openai_compatible_chat',lambda **kwargs:json.dumps({'matched':True,'fact_refs':['approved-revision'],'answer_supported':True}))
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


def test_human_fact_view_uses_same_authorized_record_and_escapes_source_text(record, monkeypatch):
    from strategyos_mvp import claim_api
    record['label'] = '<script>alert(1)</script>'
    seen = []
    class Repository:
        def snapshot(self, key, **kwargs):
            seen.append(kwargs['context'])
            return {'records': [record], 'snapshot_key': key, 'analysis_as_of': '2026-06-30'}
    monkeypatch.setattr(claim_api, 'ClaimRepository', Repository)
    response = claim_api.resolve_snapshot_fact('run', 'approved-revision', view='human',
        principal={'tenant_id': 'tenant-b', 'subject': 'reader', 'role': 'bu', 'business_units': ['east']})
    text = response.body.decode()
    assert 'SAR 1,200,000.00' in text and 'NUPCO' in text
    assert '<script>' not in text and '&lt;script&gt;' in text
    assert 'approved-revision' not in text.split('<details>')[0]
    assert response.headers['cache-control'] == 'private, no-store'
    assert seen[0].tenant_id == 'tenant-b' and seen[0].business_units == frozenset({'east'})


@pytest.mark.parametrize('question', ['my number for ebidta??', 'what did we earn before financing, tax and depreciation?', 'كم أرباحنا قبل الفوائد والضرائب والإهلاك؟'])
def test_semantic_selection_sees_all_facts_without_literal_or_eighty_record_cutoff(record, monkeypatch, question):
    from strategyos_mvp import llm_qa, model_policy
    from tests.test_llm_qa import _config
    records = [{**record, 'claim_revision_id': f'r-{i}', 'metric_key': 'finance.revenue'} for i in range(160)]
    records.append({**record, 'claim_revision_id': 'last-ebitda', 'metric_key': 'ceo.ebitda', 'value': '617'})
    monkeypatch.setattr(model_policy, 'evidence_model_access', lambda _: True)
    def provider(**kwargs):
        request = json.loads(kwargs['messages'][-1]['content'])
        assert request['question'] == question
        assert {fact['ref'] for fact in request['facts']} == {r['claim_revision_id'] for r in records}
        return json.dumps({'matched': True, 'fact_refs': ['last-ebitda'], 'answer_supported': True})
    monkeypatch.setattr(llm_qa, '_call_openai_compatible_chat', provider)
    result = llm_qa.answer_question(question, bundle=SimpleNamespace(authorized_claim_records=records),
        findings=[], summary={'run_id': 'run'}, config=_config())
    assert result['matched'] and result['fact_cells'][0]['value'] == '617000000'
    assert result['retrieval']['facts_considered'] == 161


def test_large_evidence_packets_are_lossless_and_every_batch_is_validated(record, monkeypatch):
    from strategyos_mvp import llm_qa, model_policy, fact_rendering
    from tests.test_llm_qa import _config
    records = [{**record, 'claim_revision_id': f'r-{i}'} for i in range(27)]
    original_batches = fact_rendering.fact_batches
    monkeypatch.setattr(fact_rendering, 'fact_batches', lambda registry: original_batches(registry, max_bytes=1200))
    monkeypatch.setattr(model_policy, 'evidence_model_access', lambda _: True)
    seen = []
    def provider(**kwargs):
        packet = json.loads(kwargs['messages'][-1]['content'])
        if 'approved_comparisons' in packet:
            assert len(packet['facts']) == 27
            return json.dumps({'answer_supported': True})
        facts = packet['facts']
        seen.extend(fact['ref'] for fact in facts)
        return json.dumps({'matched': True, 'fact_refs': [fact['ref'] for fact in facts], 'answer_supported': False})
    monkeypatch.setattr(llm_qa, '_call_openai_compatible_chat', provider)
    result = llm_qa.answer_question('Show all values', bundle=SimpleNamespace(authorized_claim_records=records),
        findings=[], summary={'run_id': 'run'}, config=_config())
    assert seen == [r['claim_revision_id'] for r in records]
    assert len(result['fact_cells']) == 27  # No hidden 20-result limit either.
    assert result['retrieval']['batches_completed'] > 1
    assert result['retrieval']['complete'] is True
    assert result['matched'] and result['answer_coverage'] == 'supported'


@pytest.mark.parametrize('response', ['not json', '{"matched":true,"fact_refs":["foreign"]}'])
def test_invalid_provider_selection_is_a_service_failure_not_missing_evidence(record, monkeypatch, response):
    from strategyos_mvp import llm_qa, model_policy
    from tests.test_llm_qa import _config
    monkeypatch.setattr(model_policy, 'evidence_model_access', lambda _: True)
    monkeypatch.setattr(llm_qa, '_call_openai_compatible_chat', lambda **kwargs: response)
    with pytest.raises(RuntimeError, match='invalid evidence selection'):
        llm_qa.answer_question('Our earnings?', bundle=SimpleNamespace(authorized_claim_records=[record]),
            findings=[], summary={'run_id': 'run'}, config=_config())


@pytest.mark.parametrize('result,tier', [
    ({'matched': False, 'fact_contract': 'governed-fact-selection-v1', 'answer': 'No match'}, 'needs_evidence'),
    ({'matched': False, 'answer_status': 'service_error', 'answer': 'Service failed'}, 'service_error'),
    ({'matched': True, 'assistant_scope': 'general', 'answer': 'A general explanation'}, 'general'),
])
def test_unverified_answers_never_get_a_source_backed_badge(result, tier):
    from strategyos_mvp import api
    payload = api._assistant_response_payload(response_mode='llm', question='Question',
        context={'run_id': 'run', 'run_mode': 'full'}, requested_mode='auto', persona='ceo',
        orchestrated=None, base_result=result)
    assert payload['determinism_tier'] == tier
    assert not payload.get('citations')


@pytest.mark.parametrize('supported', [True, False])
def test_related_facts_do_not_automatically_establish_answer(record, monkeypatch, supported):
    from strategyos_mvp import llm_qa, model_policy, api
    from tests.test_llm_qa import _config
    monkeypatch.setattr(model_policy, 'evidence_model_access', lambda _: True)
    monkeypatch.setattr(llm_qa, '_call_openai_compatible_chat', lambda **kwargs: json.dumps({
        'matched': True, 'fact_refs': ['approved-revision'], 'answer_supported': supported}))
    result = llm_qa.answer_question('Whose forecasts are consistently best?',
        bundle=SimpleNamespace(authorized_claim_records=[record]), findings=[],
        summary={'run_id': 'run'}, config=_config())
    original = render_selection({'matched': True, 'fact_refs': ['approved-revision']},
                                fact_registry([record]), run_id='run')
    assert result['fact_cells'] == original['fact_cells']
    assert result['citations'] == original['citations']
    assert result['matched'] is supported
    payload = api._assistant_response_payload(response_mode='llm', question='Forecast accuracy?',
        context={'run_id': 'run', 'run_mode': 'full'}, requested_mode='auto', persona='ceo',
        orchestrated=None, base_result=result)
    assert payload['determinism_tier'] == ('governed_fact' if supported else 'context_only')
    if not supported:
        assert result['answer'].startswith(result['answer_caveat'])
        assert 'SAR 1,200,000.00' in result['answer']


@pytest.mark.parametrize('coverage', [None, 'true', 1, {}, []])
def test_malformed_coverage_cannot_certify_answer(record, monkeypatch, coverage):
    from strategyos_mvp import llm_qa, model_policy
    from tests.test_llm_qa import _config
    monkeypatch.setattr(model_policy, 'evidence_model_access', lambda _: True)
    monkeypatch.setattr(llm_qa, '_call_openai_compatible_chat', lambda **kwargs: json.dumps({
        'matched': True, 'fact_refs': ['approved-revision'], 'answer_supported': coverage}))
    with pytest.raises(RuntimeError, match='invalid evidence selection'):
        llm_qa.answer_question('Forecast accuracy?', bundle=SimpleNamespace(authorized_claim_records=[record]),
            findings=[], summary={'run_id': 'run'}, config=_config())
