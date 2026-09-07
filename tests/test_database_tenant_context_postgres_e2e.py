"""Actual single-slot pool and row-policy proof, with synthetic tenant rows."""
from dataclasses import replace
import os
from uuid import uuid4

import pytest

from strategyos_mvp import access_scope, database_schema, database_tenant, state_store

pytestmark=pytest.mark.integration


@pytest.fixture
def tenant_runtime(monkeypatch,tmp_path):
    import psycopg
    from psycopg import sql
    from psycopg_pool import ConnectionPool
    url=os.environ.get('STRATEGYOS_POSTGRES_E2E_DATABASE_URL')
    if not url:
        pytest.skip('Dedicated Postgres proof endpoint required.')
    role='strategyos_preview_runtime_'+uuid4().hex[:12]
    suffix=role.removeprefix('strategyos_preview_runtime')
    roles=(role,'strategyos_preview_worker'+suffix,'strategyos_preview_projector'+suffix)
    table='qa_tenant_pool_'+uuid4().hex
    tenant_ids=[uuid4(),uuid4()]
    slugs=['pool-a-'+uuid4().hex,'pool-b-'+uuid4().hex]
    path=tmp_path/'runtime.env'
    monkeypatch.setenv('STRATEGYOS_DEPLOYMENT_BOUNDARY','preview')
    monkeypatch.setattr(state_store,'CONFIG',replace(state_store.CONFIG,database_url=url))
    pool=None
    try:
        with psycopg.connect(url) as owner:
            database_schema.prepare_schema(owner)
            for identifier,slug in zip(tenant_ids,slugs):
                owner.execute("INSERT INTO strategyos_tenants(id,slug,display_name) VALUES(%s,%s,'Pool fixture')",(identifier,slug))
            owner.execute(sql.SQL('CREATE TABLE {} (tenant_id uuid NOT NULL,value integer NOT NULL)').format(sql.Identifier(table)))
            owner.execute(sql.SQL('INSERT INTO {} VALUES(%s,1),(%s,2)').format(sql.Identifier(table)),tenant_ids)
            owner.execute(sql.SQL('ALTER TABLE {} ENABLE ROW LEVEL SECURITY').format(sql.Identifier(table)))
            owner.execute(sql.SQL("CREATE POLICY bound_tenant ON {} USING(tenant_id=nullif(current_setting('strategyos.tenant_uuid',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('strategyos.tenant_uuid',true),'')::uuid)").format(sql.Identifier(table)))
            owner.commit()
            database_schema.provision_preview_runtime(owner,path,role=role)
        runtime_entries=dict(line.split('=',1) for line in path.read_text().splitlines())
        runtime_url=runtime_entries['STRATEGYOS_RUNTIME_DATABASE_URL']
        pool=ConnectionPool(runtime_url,min_size=1,max_size=1,timeout=3,open=True)
        pool.wait()
        monkeypatch.setattr(state_store,'_get_pool',lambda:pool)
        monkeypatch.setattr(state_store,'CONFIG',replace(state_store.CONFIG,database_url=runtime_url,database_schema_mode='verify'))
        yield pool,table,tenant_ids,slugs
    finally:
        if pool is not None:
            pool.close()
        with psycopg.connect(url) as owner:
            owner.execute(sql.SQL('DROP TABLE IF EXISTS {}').format(sql.Identifier(table)))
            for login in roles:
                if owner.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(login,)).fetchone():
                    owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(login)))
                    owner.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(login)))


def identity(tenant,**overrides):
    return {'subject':'fixture:executive','role':'executive','tenant_id':tenant,
        '_verified_for_request':True,**overrides}


def test_single_slot_pool_never_reuses_previous_tenant_context(tenant_runtime):
    from psycopg import sql
    pool,table,ids,slugs=tenant_runtime
    select=sql.SQL('SELECT value FROM {} ORDER BY value').format(sql.Identifier(table))
    for principal,expected in [(identity(slugs[0]),[1]),(identity(str(ids[1])),[2]),(None,[]),(identity(slugs[0]),[1])]:
        token=access_scope.principal_scope.set(principal)
        try:
            handle,failure=state_store.database_connection()
            assert failure is None
            with handle as conn:
                assert [row[0] for row in conn.execute(select)]==expected
                conn.commit()
                assert [row[0] for row in conn.execute(select)]==expected
                conn.rollback()
                assert [row[0] for row in conn.execute(select)]==expected
        finally:
            access_scope.principal_scope.reset(token)
        with pool.connection() as conn:
            assert conn.execute("SELECT current_setting('strategyos.tenant_uuid',true),current_setting('strategyos.tenant_key',true)").fetchone()==('','')
            assert conn.execute(select).fetchall()==[]


@pytest.mark.parametrize('invalid',[
    identity('missing-tenant'), identity('ignored',_verified_for_request=False),
    identity('ignored',auth_disabled=True), identity(''),
])
def test_failed_binding_discards_connection_without_pool_leak(tenant_runtime,invalid):
    _,_,_,slugs=tenant_runtime
    token=access_scope.principal_scope.set(invalid)
    try:
        handle,failure=state_store.database_connection()
        assert handle is None and failure['status']=='failed'
    finally:
        access_scope.principal_scope.reset(token)
    token=access_scope.principal_scope.set(identity(slugs[1]))
    try:
        handle,failure=state_store.database_connection()
        assert failure is None
        with handle as conn:
            assert conn.execute("SELECT current_setting('strategyos.tenant_key')").fetchone()[0]==slugs[1]
    finally:
        access_scope.principal_scope.reset(token)


def test_rollback_and_clear_failure_do_not_return_authorized_session(tenant_runtime,monkeypatch):
    from psycopg import sql
    pool,table,_,slugs=tenant_runtime
    token=access_scope.principal_scope.set(identity(slugs[0]))
    try:
        handle,failure=state_store.database_connection()
        assert failure is None
        with pytest.raises(ValueError,match='cancelled'):
            with handle as conn:
                conn.execute(sql.SQL('UPDATE {} SET value=99').format(sql.Identifier(table)))
                raise ValueError('cancelled')
        handle,failure=state_store.database_connection()
        assert failure is None
        with handle as conn:
            assert conn.execute(sql.SQL('SELECT value FROM {}').format(sql.Identifier(table))).fetchall()==[(1,)]
        with monkeypatch.context() as patch:
            def failed_clear(conn):
                raise RuntimeError('synthetic cleanup failure')
            patch.setattr(database_tenant,'clear_connection_context',failed_clear)
            handle,failure=state_store.database_connection()
            assert failure is None
            with pytest.raises(RuntimeError,match='synthetic cleanup failure'):
                with handle as conn:
                    pass
            assert conn.closed
    finally:
        access_scope.principal_scope.reset(token)
    handle,failure=state_store.database_connection()
    assert failure is None
    with handle as conn:
        assert conn.execute(sql.SQL('SELECT value FROM {}').format(sql.Identifier(table))).fetchall()==[]
