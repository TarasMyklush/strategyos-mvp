from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
import uuid
import pytest
from fastapi import HTTPException
from strategyos_mvp import access_scope, state_store, conversation_state as store


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
