from dataclasses import replace
from datetime import datetime, UTC
from types import SimpleNamespace
from uuid import uuid4

from strategyos_mvp.assistant_scope import bind_assistant
from strategyos_mvp.authority_matrix import default_authority_matrix
from strategyos_mvp.source_claims import ClaimDraft, ClaimQuery
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake


def test_assistant_domain_filters_snapshot_before_source_loading_and_checks_lineage(ledger, monkeypatch):
    import psycopg
    repo, context, occurrence, source, policy = setup_intake(ledger)
    repo.register_source(source, policy=replace(policy, allowed_roles=frozenset({'operator','executive'}),
        allowed_purposes=frozenset({'operations','executive_briefing'})), recorded_by='qa', rationale='Synthetic source grant')
    base=ClaimDraft(tenant_id=context.tenant_id,assertion_namespace='authority-proof',subject_type='enterprise',
        subject_key='group',metric_key='finance.revenue',claim_kind='actual',production_method='imported',
        value_numeric=120,unit='SAR',currency='SAR',source_occurrence_keys=(occurrence,))
    finance=repo.record_claim(base,traceability='present',context=context)['claim_revision_id']
    hr=repo.record_claim(replace(base,metric_key='hr.salary',value_numeric=999),traceability='present',context=context)['claim_revision_id']
    derived=repo.record_claim(replace(base,metric_key='finance.derived',value_numeric=999,
        production_method='calculated',source_occurrence_keys=(),input_revision_ids=(hr,),formula_key='identity',formula_version='1'),
        traceability='present',context=context)['claim_revision_id']
    snapshot='run:domain-'+uuid4().hex
    with psycopg.connect(ledger[1]) as conn:
        sid=conn.execute("insert into strategyos_analysis_snapshots(tenant_id,snapshot_key,as_of_at,policy_version,created_by) values (%s,%s,now(),'qa','qa') returning id",(context.tenant_id,snapshot)).fetchone()[0]
        conn.execute("insert into strategyos_analysis_snapshot_claims(snapshot_id,claim_family_id,claim_revision_id,selection_reason) select %s,claim_family_id,id,'qa' from strategyos_claim_revisions where id=any(%s::uuid[])",(sid,[finance,hr,derived]))
    original=repo._source_details
    def source_details(cur,revision,**kwargs):
        assert str(revision) not in {hr,derived}, 'Restricted source or derivative was loaded'
        return original(cur,revision,**kwargs)
    monkeypatch.setattr(repo,'_source_details',source_details)
    with bind_assistant(SimpleNamespace(persona='cfo'),{'subject':'cfo'},default_authority_matrix()):
        reader=replace(context,roles=frozenset({'executive'}),purpose='executive_briefing')
        result=repo.snapshot(snapshot,context=reader)
        assert {r['claim_revision_id'] for r in result['records']}=={finance}
        denied=repo.query(ClaimQuery(context.tenant_id,'hr.salary','executive_briefing',datetime.now(UTC),frozenset({'actual'})),context=reader)
        assert denied==[]
        assert repo.snapshot(snapshot,context=reader,revision_id=hr)['records']==[]
        selected=repo.snapshot(snapshot,context=reader,revision_id=finance)['records']
        assert len(selected)==1 and selected[0]['claim_revision_id']==finance
        from strategyos_mvp import access_scope, api, claim_store
        from strategyos_mvp.twins import source_scope, strategyos_data
        monkeypatch.setattr(claim_store,'ClaimRepository',lambda:repo)
        monkeypatch.setattr(api,'ClaimRepository',lambda:repo)
        monkeypatch.setattr(api,'_latest_summary',lambda:{'run_id':snapshot.removeprefix('run:')})
        monkeypatch.setattr(api,'_summary_with_governed_claim_snapshot',lambda summary,**kwargs:summary)
        actor=access_scope.principal_scope.set({'tenant_id':context.tenant_id,'subject':'cfo',
            'role':'executive','authenticated':True})
        binding=source_scope.bound_surface.set(None)
        try:
            twin=strategyos_data.load_role_surface('cfo')
            assert set(twin['fact_registry'])=={finance}
            assert 'assistant_records' in source_scope.authorized_surface()
        finally:
            source_scope.bound_surface.reset(binding)
            access_scope.principal_scope.reset(actor)
    monkeypatch.setattr(repo,'_source_details',original)
    reader=replace(context,roles=frozenset({'executive'}),purpose='executive_briefing')
    assert {r['claim_revision_id'] for r in repo.snapshot(snapshot,context=reader)['records']}=={finance,hr,derived}

    # Citation resolution must recheck the current policy, even for a revision
    # already displayed in an earlier answer.
    repo.register_source(source,policy=policy,recorded_by='qa',rationale='Revoke executive source access')
    assert repo.snapshot(snapshot,context=reader,revision_id=finance)['records']==[]
