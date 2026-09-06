from dataclasses import replace
from uuid import uuid4

import pytest

from strategyos_mvp import access_scope, api, claim_store
from strategyos_mvp.source_claims import ClaimDraft
from strategyos_mvp.twins import source_scope, store
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake

pytestmark = pytest.mark.integration


def test_saved_twin_state_is_actor_run_scoped_and_revocation_blocks_replay(ledger,monkeypatch,tmp_path):
    import psycopg
    repo, context, occurrence, source, policy = setup_intake(ledger)
    draft = ClaimDraft(tenant_id=context.tenant_id,assertion_namespace='twin-scope-proof',
        subject_type='enterprise',subject_key='group',metric_key='qa.twin',claim_kind='actual',
        production_method='imported',value_numeric=100,unit='SAR',currency='SAR',source_occurrence_keys=(occurrence,))
    revision = repo.record_claim(draft,traceability='present',context=context)['claim_revision_id']
    run = str(uuid4())
    with psycopg.connect(ledger[1]) as conn:
        snapshot = conn.execute("insert into strategyos_analysis_snapshots(tenant_id,snapshot_key,as_of_at,policy_version,created_by) values(%s,%s,now(),'qa','qa') returning id",(context.tenant_id,'run:'+run)).fetchone()[0]
        conn.execute("insert into strategyos_analysis_snapshot_claims(snapshot_id,claim_family_id,claim_revision_id,selection_reason) select %s,claim_family_id,id,'qa' from strategyos_claim_revisions where id=%s",(snapshot,revision))
    readable = replace(policy,allowed_roles=frozenset({'operator','executive','tenant_admin'}),
        allowed_purposes=frozenset({'operations','executive_briefing'}))
    repo.register_source(source,policy=readable,recorded_by='qa',rationale='Synthetic source-read grant')
    monkeypatch.setattr(claim_store,'ClaimRepository',lambda:repo)
    monkeypatch.setattr(api,'_latest_summary',lambda:{'run_id':run})
    # Headline interpretation is tested separately; this fixture proves real
    # source ACLs and on-disk cached-work isolation, without a fake ACL decision.
    monkeypatch.setattr(api,'_summary_with_governed_claim_snapshot',lambda summary,**kwargs:summary)
    monkeypatch.setattr(store,'get_app_data_dir',lambda:tmp_path)
    legacy = store.build_repositories(tmp_path)
    legacy.states.save('ceo',{'role':'ceo','working_memory':{'private':'unclassified legacy'}})
    principal = {'tenant_id':context.tenant_id,'subject':'ceo-one','role':'executive'}
    token = access_scope.principal_scope.set(principal)
    binding = source_scope.bound_surface.set(None)
    try:
        scoped = store.build_app_repositories()
        assert scoped.states.load('ceo') is None
        scoped.states.save('ceo',{'role':'ceo','working_memory':{'private':'synthetic actor-one work'}})
        assert store.build_app_repositories().states.load('ceo')['working_memory']['private']=='synthetic actor-one work'
        access_scope.principal_scope.set({**principal,'subject':'ceo-two'})
        source_scope.bound_surface.set(None)
        assert store.build_app_repositories().states.load('ceo') is None
        access_scope.principal_scope.set(principal)
        source_scope.bound_surface.set(None)
        repo.register_source(source,policy=replace(readable,allowed_roles=frozenset({'operator'})),
            recorded_by='qa',rationale='Synthetic read revocation')
        with pytest.raises(PermissionError): store.build_app_repositories()
        assert legacy.states.load('ceo')['working_memory']['private']=='unclassified legacy'
    finally:
        source_scope.bound_surface.reset(binding)
        access_scope.principal_scope.reset(token)
