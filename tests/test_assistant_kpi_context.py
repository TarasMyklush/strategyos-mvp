import pytest

from strategyos_mvp.assistant_kpi_context import read_context
from strategyos_mvp.source_claims import PolicyContext, UsePurpose


def policy():
    return PolicyContext(tenant_id='tenant-a', principal_id='reader', roles=frozenset({'bu'}),
                         business_units=frozenset({'east'}), purpose=UsePurpose.EXECUTIVE_BRIEFING)


def fact(**changes):
    return {'claim_revision_id':'cash-actual', 'traceability':'present', 'value_type':'numeric',
            'value':'1410', 'scale':'1000000', 'unit':'SAR', 'currency':'SAR',
            'metric_key':'ceo.cash_balance', 'subject':{'type':'company','key':'Synthetic company'},
            'claim_kind':'actual', 'label':'Cash balance', 'business_unit':'east',
            'period':{'as_of':'2026-06-30'}, 'dimensions':{'component_key':'cash_balance',
            'source_contract_provider':'Synthetic Treasury'}, **changes}


def test_context_uses_only_authorized_contract_facts_and_retains_scope():
    seen = []
    class Repository:
        def snapshot(self, key, **kwargs):
            seen.append((key, kwargs))
            return {'records':[fact(), fact(claim_revision_id='floor', metric_key='ceo.cash_floor',
                claim_kind='plan', value='1200', label='Cash floor'),
                fact(claim_revision_id='other', metric_key='ceo.revenue', value='999999')],
                'analysis_as_of':'2026-06-30'}
    result = read_context(Repository(), run_id='run', key='cash_vs_floor', context=policy())
    assert seen[0][1]['context'].tenant_id == 'tenant-a'
    assert seen[0][1]['context'].business_units == frozenset({'east'})
    assert seen[0][1]['metric_keys'] == {'ceo.cash_balance','ceo.cash_floor'}
    assert result['context_only'] and result['determinism_tier'] == 'governed_context'
    assert '1,410,000,000' in result['answer'] and '1,200,000,000' in result['answer']
    assert '999999' not in result['answer']
    assert 'Synthetic company' in result['answer'] and '2026-06-30' in result['answer']
    assert 'east' in result['answer']
    assert result['source_providers'] == ['Synthetic Treasury']
    assert 'language answer to your question is not complete' in result['answer_caveat']
    assert {c['claim_revision_id'] for c in result['citations']} == {'cash-actual','floor'}


@pytest.mark.parametrize('flag', ['requires_resolution', 'requires_recompute'])
def test_context_refuses_unresolved_or_revised_facts(flag):
    class Repository:
        def snapshot(self, *args, **kwargs): return {flag: True, 'records':[fact()]}
    with pytest.raises(PermissionError):
        read_context(Repository(), run_id='run', key='cash_vs_floor', context=policy())


def test_empty_scope_and_unknown_kpi_cannot_fabricate_a_fallback():
    class Repository:
        def snapshot(self, *args, **kwargs): return {'records':[]}
    with pytest.raises(LookupError):
        read_context(Repository(), run_id='foreign-run', key='cash_vs_floor', context=policy())
    with pytest.raises(ValueError):
        read_context(Repository(), run_id='run', key='invented-kpi', context=policy())


def test_context_endpoint_binds_persona_and_human_domains(monkeypatch):
    from strategyos_mvp import api
    captured = []
    class Repository:
        def snapshot(self, key, **kwargs):
            captured.append(kwargs['context'])
            return {'records':[fact()]}
    monkeypatch.setattr(api, 'ClaimRepository', Repository)
    monkeypatch.setattr(api, 'get_authority_matrix', lambda _: {'subjects':[
        {'id':'assistant:hermes', 'rights':{'finance':'view'}},
        {'id':'user:reader', 'rights':{'finance':'view'}}]})
    from strategyos_mvp.assistant_scope import human_domains
    token = human_domains.set(frozenset())
    try:
        api.assistant_kpi_context(api.AssistantKpiContextRequest(run_id='run', kpi_key='cash_vs_floor', persona='gm'),
            principal={'tenant_id':'tenant-a', 'subject':'reader', 'role':'bu', 'business_units':['east']})
    finally:
        human_domains.reset(token)
    assert captured[0].allowed_domains == frozenset()
    assert captured[0].tenant_id == 'tenant-a'
    assert captured[0].business_units == frozenset({'east'})


def test_disabled_language_layer_goes_directly_to_authorized_kpi_context(monkeypatch):
    import asyncio
    from strategyos_mvp import api
    class Repository:
        def snapshot(self, *args, **kwargs): return {'records':[fact()]}
    monkeypatch.setattr(api, 'ClaimRepository', Repository)
    monkeypatch.setattr(api, 'get_authority_matrix', lambda _: {'subjects':[]})
    monkeypatch.setattr(api, '_assistant_authority_refusal', lambda *args:None)
    monkeypatch.setattr(api.llm_qa, 'chat_status', lambda _: {'enabled':False})
    async def forbidden(*args, **kwargs):
        pytest.fail('Disabled language handling must not invoke classification or model generation.')
    monkeypatch.setattr(api, '_assistant_chat_response', forbidden)
    result = asyncio.run(api.assistant_chat(api.AssistantChatRequest(question='Do I need to intervene?',
        run_id='run', persona='ceo', assistant_context={'kpi_key':'cash_vs_floor'},
        driver_context={'metric':'SAR 999M'}), principal={'authenticated':True,
        'tenant_id':'tenant-a','subject':'reader','role':'executive'}))
    assert result['context_only'] and result['language_status']=='unavailable'
    assert result['answer_caveat'].startswith('The language layer is unavailable.')
    assert '1,410,000,000' in result['answer'] and '999M' not in result['answer']


@pytest.mark.parametrize('role,persona,allowed', [('bu','ceo',None), ('executive','cfo',['ceo']), ('executive','board',None)])
def test_context_cannot_widen_persona_entitlement_or_replace_frozen_board_snapshot(role,persona,allowed):
    from strategyos_mvp import api
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        api.assistant_kpi_context(api.AssistantKpiContextRequest(run_id='run',kpi_key='revenue',persona=persona),
            principal={'tenant_id':'tenant-a','subject':'reader','role':role,'personas':allowed})
    assert error.value.status_code == 403
