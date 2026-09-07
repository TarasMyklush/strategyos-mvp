from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from strategyos_mvp import database_schema, state_store
from strategyos_mvp.claim_store import ClaimRepository
from strategyos_mvp.source_claims import ClaimDraft, ClaimQuery
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake

pytestmark=pytest.mark.integration


def test_nonowner_runtime_reads_and_appends_but_cannot_rewrite_schema(ledger,monkeypatch):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    _,context,occurrence,_,_=setup_intake(ledger)
    role='claim_runtime_'+uuid4().hex
    password=uuid4().hex
    with psycopg.connect(ledger[1]) as owner:
        database_schema.prepare_schema(owner)
        db=owner.info.dbname
        owner.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS').format(sql.Identifier(role),sql.Literal(password)))
        owner.execute(sql.SQL("COMMENT ON ROLE {} IS 'strategyos-preview-runtime:1'").format(sql.Identifier(role)))
        owner.execute(sql.SQL('REVOKE TEMP ON DATABASE {} FROM PUBLIC').format(sql.Identifier(db)))
        owner.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(db),sql.Identifier(role)))
        owner.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
        owner.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}').format(sql.Identifier(role)))
        owner.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(sql.Identifier(role)))
        owner.execute(sql.SQL('REVOKE INSERT,UPDATE,DELETE ON strategyos_runtime_schema_contract,strategyos_schema_migrations FROM {}').format(sql.Identifier(role)))
        owner.execute(sql.SQL('REVOKE UPDATE,DELETE,TRUNCATE ON strategyos_claim_revisions,strategyos_claim_assessments,strategyos_board_snapshots FROM {}').format(sql.Identifier(role)))
    runtime_url=make_conninfo(ledger[1],user=role,password=password)
    monkeypatch.setattr(state_store,'CONFIG',replace(state_store.CONFIG,database_schema_mode='verify'))
    try:
        with psycopg.connect(runtime_url) as conn:
            database_schema.verify_runtime_schema(conn)
            for statement in [
                'CREATE TABLE public.must_not_exist(id int)',
                'CREATE TEMP TABLE must_not_exist(id int)',
                'ALTER TABLE strategyos_claim_revisions DISABLE TRIGGER ALL',
                "UPDATE strategyos_runtime_schema_contract SET fingerprint='forged'",
                'DELETE FROM strategyos_schema_migrations',
                'TRUNCATE strategyos_claim_revisions CASCADE',
            ]:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with conn.transaction(): conn.execute(statement)
        def tenant_connection():
            conn=psycopg.connect(runtime_url)
            conn.execute("SELECT set_config('strategyos.tenant_key',%s,false),set_config('strategyos.tenant_uuid',%s,false)",
                (context.tenant_id,context.tenant_id))
            conn.commit()
            return conn,None
        repo=ClaimRepository(tenant_connection)
        draft=ClaimDraft(tenant_id=context.tenant_id,assertion_namespace='nonowner-proof',
            subject_type='enterprise',subject_key='group',metric_key='qa.nonowner',
            claim_kind='actual',production_method='imported',value_numeric=10,
            unit='SAR',currency='SAR',source_occurrence_keys=(occurrence,))
        recorded=repo.record_claim(draft,traceability='present',context=context)
        assert recorded['created']
        assert not repo.record_claim(draft,traceability='present',context=context)['created']
        query=ClaimQuery(tenant_id=context.tenant_id,metric_key='qa.nonowner',
            allowed_claim_kinds=frozenset({'actual'}),purpose=context.purpose,as_of_at=datetime.now(UTC))
        assert repo.query(query,context=context)[0]['value']=='10'
        with psycopg.connect(ledger[1]) as owner:
            with pytest.raises(RuntimeError,match='Runtime database role'):
                database_schema.verify_runtime_schema(owner)
    finally:
        with psycopg.connect(ledger[1]) as owner:
            if owner.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone():
                owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                owner.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_preview_role_provisioning_preserves_secret_on_retry(ledger,monkeypatch,tmp_path):
    import psycopg
    from psycopg import sql
    role='strategyos_preview_runtime_'+uuid4().hex[:12]
    suffix=role.removeprefix('strategyos_preview_runtime')
    roles=(role,'strategyos_preview_worker'+suffix,'strategyos_preview_projector'+suffix)
    path=tmp_path/'private'/'runtime.env'
    monkeypatch.setenv('STRATEGYOS_DEPLOYMENT_BOUNDARY','preview')
    monkeypatch.setattr(state_store,'CONFIG',replace(state_store.CONFIG,database_url=ledger[1]))
    try:
        with psycopg.connect(ledger[1]) as owner:
            database_schema.prepare_schema(owner)
            database_schema.provision_preview_runtime(owner,path,role=role)
            initial=path.read_text()
            assert path.stat().st_mode & 0o777 == 0o600
            assert [line.split('=',1)[0] for line in initial.splitlines()]==[
                'STRATEGYOS_RUNTIME_DATABASE_URL',
                'STRATEGYOS_WORKER_DATABASE_URL',
                'STRATEGYOS_PROJECTOR_DATABASE_URL',
            ]
            database_schema.provision_preview_runtime(owner,path,role=role)
            assert path.read_text()==initial
            monkeypatch.delenv('STRATEGYOS_DEPLOYMENT_BOUNDARY')
            with pytest.raises(RuntimeError,match='preview deployment boundary'):
                database_schema.provision_preview_runtime(owner,path,role=role)
    finally:
        with psycopg.connect(ledger[1]) as owner:
            for login in roles:
                if owner.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(login,)).fetchone():
                    owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(login)))
                    owner.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(login)))


@pytest.mark.parametrize('module_name',[
    'test_governed_review_flow_postgres_e2e',
    'test_agent_runtime_repository_postgres_e2e',
    'test_agent_runtime_evidence_read_postgres_e2e',
    'test_agent_runtime_pr6_postgres_e2e',
    'test_agent_runtime_streaming_postgres_e2e',
    'test_agent_runtime_effect_key_postgres_e2e',
    'test_agent_runtime_handoffs_postgres_e2e',
    'test_agent_runtime_workflows_postgres_e2e',
    'test_agent_runtime_authority_postgres_e2e',
    'test_agent_runtime_api_postgres_e2e',
    'test_agent_runtime_network_postgres_e2e',
    'test_agent_runtime_concurrency_postgres_e2e',
])
def test_fixture_reset_preserves_deployment_history(ledger,module_name):
    """Data cleanup must never leave applied DDL without its checksum ledger."""
    import importlib
    import psycopg
    with psycopg.connect(ledger[1]) as conn:
        database_schema.prepare_schema(conn)
        before=conn.execute('SELECT version,checksum_sha256 FROM strategyos_schema_migrations ORDER BY version').fetchall()
        contract=conn.execute('SELECT fingerprint FROM strategyos_runtime_schema_contract').fetchone()
    importlib.import_module('tests.'+module_name)._truncate_strategyos_tables(ledger[1])
    with psycopg.connect(ledger[1]) as conn:
        assert conn.execute('SELECT version,checksum_sha256 FROM strategyos_schema_migrations ORDER BY version').fetchall()==before
        assert conn.execute('SELECT fingerprint FROM strategyos_runtime_schema_contract').fetchone()==contract
        database_schema.prepare_schema(conn)
