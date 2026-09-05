from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import os
import pytest
from strategyos_mvp import state_store, decision_lifecycle as store, access_scope


def test_durable_decision_retry_scope_and_verified_first_action(monkeypatch, tmp_path):
    url = os.getenv('STRATEGYOS_POSTGRES_E2E_DATABASE_URL')
    if not url:
        pytest.skip('Dedicated Postgres proof endpoint required.')
    import psycopg
    monkeypatch.setattr(state_store, 'database_connection', lambda: (psycopg.connect(url), None))
    monkeypatch.setattr(state_store, 'CONFIG', replace(state_store.CONFIG, tenant_slug='lifecycle-proof'))
    run = state_store.create_run({'run_dir':str(tmp_path), 'dataset_root':str(tmp_path)}, requires_human_review=True)['run_id']
    key='approve-source-mandate'
    store.append(run,key,'surfaced',actor='test-executive',payload={'title':'Source mandate'},effect_key='observe')
    def decide(_):
        return store.append(run,key,'decided',actor='test-executive',payload={'choice':'Approve','owner':'Reviewed owner'},effect_key='retry-1')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(decide,range(4)))
    assert sum(not row['idempotent_replay'] for row in results)==1
    before=store.read(run)
    assert before['velocity']['action_sample_count']==0
    assert before['records'][0]['delivery_status']=='not_connected'
    assert len(before['records'][0]['events'])==2
    with pytest.raises(ValueError,match='different event'):
        store.append(run,key,'decided',actor='test-executive',payload={'choice':'Decline'},effect_key='new-key')
    with pytest.raises(ValueError,match='evidence'):
        store.append(run,key,'action_verified',actor='reviewer',payload={},effect_key='action')
    store.append(run,key,'action_verified',actor='reviewer',payload={'evidence_sha256':'a'*64,'evidence_path':'verified_receipt'},effect_key='action')
    after=store.read(run)  # Fresh independent database connection, not process-local state.
    assert after['velocity']['action_sample_count']==1
    assert after['records'][0]['issue_status']=='open'  # First action is not completed outcome.
    token=access_scope.principal_scope.set({'tenant_id':'another-tenant','role':'executive'})
    try:
        with pytest.raises(PermissionError):
            store.read(run)
    finally:
        access_scope.principal_scope.reset(token)
