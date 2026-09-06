from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
import uuid
import pytest
from fastapi import HTTPException
from strategyos_mvp import access_scope, state_store, conversation_state as store
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake


def test_private_workspace_scope_and_concurrent_device_conflict(monkeypatch, tmp_path):
    url=os.getenv('STRATEGYOS_POSTGRES_E2E_DATABASE_URL')
    if not url: pytest.skip('Dedicated Postgres proof endpoint required.')
    import psycopg
    monkeypatch.setattr(state_store,'database_connection',lambda:(psycopg.connect(url),None))
    with psycopg.connect(url) as conn:
        conn.execute(store.SCHEMA)
    tenant='threads-'+uuid.uuid4().hex
    monkeypatch.setattr(state_store,'CONFIG',replace(state_store.CONFIG,tenant_slug=tenant))
    run=state_store.create_run({'run_dir':str(tmp_path),'dataset_root':str(tmp_path)},requires_human_review=True)['run_id']
    principal={'tenant_id':tenant,'subject':'executive-a','role':'executive','authenticated':True}
    from strategyos_mvp import api
    monkeypatch.setattr(api,'_assistant_authority_refusal',lambda *args:None)
    # This test isolates ownership and optimistic concurrency. Real source
    # authorization and revocation are exercised separately below.
    monkeypatch.setattr(store, 'authorize_sources', lambda *args: None)
    def write(index):
        token=access_scope.principal_scope.set(principal)
        try:
            return store.write(store.ThreadState(run_id=run,persona='ceo',version=0,threads={'message':{'text':str(index)}}),principal)
        except HTTPException as exc:
            return {'status':exc.status_code}
        finally:access_scope.principal_scope.reset(token)
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(write,[1,2]))
    assert sorted(x.get('status',200) for x in results)==[200,409]
    token=access_scope.principal_scope.set(principal)
    try:
        assert store.read(run,'ceo',principal)['version']==1
        assert store.read(run,'ceo',{**principal,'subject':'executive-b'})['threads']=={}
        access_scope.principal_scope.set({**principal,'tenant_id':'foreign'})
        with pytest.raises(PermissionError):store.read(run,'ceo',{**principal,'tenant_id':'foreign'})
    finally:access_scope.principal_scope.reset(token)


def test_current_source_revocation_blocks_persisted_history_reads_and_writes(ledger, monkeypatch):
    import psycopg
    from strategyos_mvp import api, claim_store
    from strategyos_mvp.source_claims import ClaimDraft
    repo, context, occurrence, source, policy = setup_intake(ledger)
    revision = repo.record_claim(ClaimDraft(tenant_id=context.tenant_id,
        assertion_namespace='thread-proof',subject_type='enterprise',subject_key='group',
        metric_key='qa.thread',claim_kind='actual',production_method='imported',
        value_numeric=100,unit='SAR',currency='SAR',source_occurrence_keys=(occurrence,)),
        traceability='present',context=context)['claim_revision_id']
    with psycopg.connect(ledger[1]) as conn:
        conn.execute(store.SCHEMA)
        run = str(conn.execute("""INSERT INTO strategyos_runs
            (tenant_key,run_dir,dataset_root,finding_count,locked_finding_count,total_recoverable_sar,summary_json)
            VALUES (%s,'qa','qa',0,0,0,'{}') RETURNING id""",(context.tenant_id,)).fetchone()[0])
        snapshot = conn.execute("INSERT INTO strategyos_analysis_snapshots(tenant_id,snapshot_key,as_of_at,policy_version,created_by) VALUES(%s,%s,now(),'qa','qa') RETURNING id",(context.tenant_id,'run:'+run)).fetchone()[0]
        conn.execute("INSERT INTO strategyos_analysis_snapshot_claims(snapshot_id,claim_family_id,claim_revision_id,selection_reason) SELECT %s,claim_family_id,id,'qa' FROM strategyos_claim_revisions WHERE id=%s",(snapshot,revision))
    readable = replace(policy,allowed_roles=frozenset({'operator','executive'}),
        allowed_purposes=frozenset({'operations','executive_briefing'}))
    repo.register_source(source,policy=readable,recorded_by='qa',rationale='Synthetic read grant')
    monkeypatch.setattr(claim_store,'ClaimRepository',lambda:repo)
    monkeypatch.setattr(state_store,'database_connection',lambda:(psycopg.connect(ledger[1]),None))
    monkeypatch.setattr(api,'_assistant_authority_refusal',lambda *args:None)
    principal={'tenant_id':context.tenant_id,'subject':'ceo','role':'executive'}
    token=access_scope.principal_scope.set(principal)
    try:
        body=store.ThreadState(run_id=run,persona='ceo',version=0,threads={'qa':{'answer':'synthetic private history'}})
        assert store.write(body,principal)['version']==1
        assert store.read(run,'ceo',principal)['threads']==body.threads
        repo.register_source(source,policy=replace(readable,allowed_roles=frozenset({'operator'})),
            recorded_by='qa',rationale='Synthetic revocation')
        with pytest.raises(PermissionError): store.read(run,'ceo',principal)
        with pytest.raises(PermissionError): store.write(body.model_copy(update={'version':1}),principal)
        with psycopg.connect(ledger[1]) as conn:
            row=conn.execute('SELECT version,threads_json FROM strategyos_executive_threads WHERE tenant_key=%s AND run_id=%s',(context.tenant_id,run)).fetchone()
        assert row == (1,body.threads)  # Denial preserves history; it is not deletion.
    finally: access_scope.principal_scope.reset(token)
