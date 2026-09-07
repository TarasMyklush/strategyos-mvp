"""Database-enforced isolation for request, worker and projector identities."""
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from strategyos_mvp import database_schema, state_store
from strategyos_mvp.agents.pipeline import AgentStage
from strategyos_mvp.workflow import LangGraphStrategyOSWorkflow
from tests.test_cross_source_postgres_e2e import ledger

pytestmark=pytest.mark.integration


def _entries(path: Path) -> dict[str,str]:
    return dict(line.split('=',1) for line in path.read_text().splitlines())


@pytest.fixture
def isolated_roles(ledger,monkeypatch,tmp_path):
    import psycopg
    from psycopg import sql
    _,url,_=ledger
    suffix='_'+uuid4().hex[:12]
    request_role='strategyos_preview_runtime'+suffix
    roles=(request_role,'strategyos_preview_worker'+suffix,'strategyos_preview_projector'+suffix)
    destination=tmp_path/'runtime.env'
    tenant_ids=(uuid4(),uuid4())
    tenant_slugs=('rls-a-'+uuid4().hex,'rls-b-'+uuid4().hex)
    monkeypatch.setenv('STRATEGYOS_DEPLOYMENT_BOUNDARY','preview')
    monkeypatch.setattr(state_store,'CONFIG',replace(state_store.CONFIG,database_url=url))
    try:
        with psycopg.connect(url) as owner:
            database_schema.prepare_schema(owner)
            for tenant_id,slug,label in zip(tenant_ids,tenant_slugs,('A','B')):
                owner.execute("INSERT INTO strategyos_tenants(id,slug,display_name) VALUES(%s,%s,%s)",(tenant_id,slug,'RLS '+label))
                source_id=owner.execute("""INSERT INTO strategyos_source_systems
                    (tenant_id,name,system_type,source_key) VALUES(%s,%s,'fixture',%s) RETURNING id""",
                    (tenant_id,'RLS source '+label,'rls-source-'+label.lower())).fetchone()[0]
                family_id=owner.execute("""INSERT INTO strategyos_claim_families
                    (tenant_id,family_key,assertion_namespace,claim_kind_lane,subject_type,subject_key,metric_key)
                    VALUES(%s,%s,'rls-proof','actual','enterprise','group','rls.metric') RETURNING id""",
                    (tenant_id,'rls-family-'+label.lower())).fetchone()[0]
                revision_id=owner.execute("""INSERT INTO strategyos_claim_revisions
                    (tenant_id,claim_family_id,revision_number,fingerprint,claim_kind,production_method,
                     value_numeric,unit,traceability_state)
                    VALUES(%s,%s,1,%s,'actual','imported',1,'count','present') RETURNING id""",
                    (tenant_id,family_id,'f'*63+label.lower())).fetchone()[0]
                owner.execute("""INSERT INTO strategyos_claim_projection_outbox
                    (tenant_id,claim_revision_id,projection_type,operation,idempotency_key)
                    VALUES(%s,%s,'cache','upsert',%s)""",
                    (tenant_id,revision_id,'rls-outbox-'+label.lower()))
            owner.commit()
            database_schema.provision_preview_runtime(owner,destination,role=request_role)
        yield url,_entries(destination),tenant_ids,tenant_slugs,roles
    finally:
        with psycopg.connect(url) as owner:
            for login in roles:
                if owner.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(login,)).fetchone():
                    owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(login)))
                    owner.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(login)))


def _bind(conn,tenant_key='',tenant_uuid=''):
    conn.execute("SELECT set_config('strategyos.tenant_key',%s,false),set_config('strategyos.tenant_uuid',%s,false)",
        (str(tenant_key),str(tenant_uuid)))
    conn.commit()


def test_request_role_filters_unqualified_queries_and_pool_rebinding(isolated_roles):
    import psycopg
    _,entries,tenant_ids,tenant_slugs,_=isolated_roles
    with psycopg.connect(entries['STRATEGYOS_RUNTIME_DATABASE_URL']) as conn:
        database_schema.verify_runtime_schema(conn,expected_scope='request')
        for tenant_id,slug in zip(tenant_ids,tenant_slugs):
            _bind(conn,slug,'')
            resolved=conn.execute('SELECT id FROM strategyos_tenants').fetchall()
            assert resolved==[(tenant_id,)]
            _bind(conn,slug,tenant_id)
            assert conn.execute('SELECT count(*) FROM strategyos_source_systems').fetchone()[0]==1
            assert conn.execute('SELECT count(*) FROM strategyos_claim_families').fetchone()[0]==1
            assert conn.execute('SELECT count(*) FROM strategyos_claim_revisions').fetchone()[0]==1
            assert conn.execute('SELECT count(*) FROM strategyos_claim_projection_outbox').fetchone()[0]==1
        _bind(conn)
        for table in ('strategyos_tenants','strategyos_source_systems','strategyos_claim_families',
                      'strategyos_claim_revisions','strategyos_claim_projection_outbox'):
            assert conn.execute('SELECT count(*) FROM '+table).fetchone()[0]==0


def test_background_roles_are_distinct_and_least_privileged(isolated_roles):
    import psycopg
    _,entries,_,_,roles=isolated_roles
    with psycopg.connect(entries['STRATEGYOS_WORKER_DATABASE_URL']) as conn:
        database_schema.verify_runtime_schema(conn,expected_scope='worker')
        assert conn.execute('SELECT count(*) FROM strategyos_claim_revisions').fetchone()[0]>=2
        conn.execute("""INSERT INTO checkpoints
            (thread_id,checkpoint_ns,checkpoint_id,type,checkpoint,metadata)
            VALUES('role-proof','','checkpoint-proof','json','{}','{}')""")
        assert conn.execute("SELECT count(*) FROM checkpoints WHERE thread_id='role-proof'").fetchone()[0]==1
        conn.execute("DELETE FROM checkpoints WHERE thread_id='role-proof'")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction(): conn.execute('INSERT INTO checkpoint_migrations(v) VALUES(9999)')
    with psycopg.connect(entries['STRATEGYOS_PROJECTOR_DATABASE_URL']) as conn:
        database_schema.verify_runtime_schema(conn,expected_scope='projector')
        assert conn.execute('SELECT count(*) FROM strategyos_claim_revisions').fetchone()[0]>=2
        assert conn.execute('SELECT count(*) FROM strategyos_claim_projection_outbox').fetchone()[0]>=2
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction(): conn.execute('SELECT count(*) FROM strategyos_finance_facts')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction(): conn.execute("DELETE FROM strategyos_claim_revisions WHERE false")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction(): conn.execute('SELECT count(*) FROM checkpoints')
    with psycopg.connect(entries['STRATEGYOS_RUNTIME_DATABASE_URL']) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction(): conn.execute('SELECT count(*) FROM checkpoints')
    assert len(set(roles))==3


def test_worker_runs_langgraph_with_release_owned_checkpoint_schema(isolated_roles):
    import psycopg
    _,entries,_,_,_=isolated_roles
    run_id='langgraph-role-proof-'+uuid4().hex
    proof_stage=AgentStage('checkpoint_role_proof_'+uuid4().hex,'Checkpoint role proof',is_terminal=True)
    workflow=LangGraphStrategyOSWorkflow(
        postgres_url=entries['STRATEGYOS_WORKER_DATABASE_URL'],
        database_schema_mode='verify',
        pipeline=(proof_stage,),
        stage_handlers={proof_stage.name: lambda state: {**state,'workflow_status':'checkpoint-proved'}},
    )

    result=workflow.invoke({'run_id':run_id})

    assert result['workflow_status']=='checkpoint-proved'
    with psycopg.connect(entries['STRATEGYOS_WORKER_DATABASE_URL']) as conn:
        assert conn.execute('SELECT count(*) FROM checkpoints WHERE thread_id=%s',(run_id,)).fetchone()[0]>=1
        conn.execute('DELETE FROM checkpoint_writes WHERE thread_id=%s',(run_id,))
        conn.execute('DELETE FROM checkpoint_blobs WHERE thread_id=%s',(run_id,))
        conn.execute('DELETE FROM checkpoints WHERE thread_id=%s',(run_id,))


def test_runtime_scope_uses_one_constant_time_role_membership(isolated_roles):
    import psycopg
    url,entries,_,_,_=isolated_roles
    with psycopg.connect(url) as owner:
        definition=owner.execute(
            "SELECT pg_get_functiondef('strategyos_database_runtime_scope()'::regprocedure)"
        ).fetchone()[0]
    assert 'pg_has_role' in definition
    assert 'from pg_roles' not in definition.lower()
    for key,scope in (
        ('STRATEGYOS_RUNTIME_DATABASE_URL','request'),
        ('STRATEGYOS_WORKER_DATABASE_URL','worker'),
        ('STRATEGYOS_PROJECTOR_DATABASE_URL','projector'),
    ):
        with psycopg.connect(entries[key]) as conn:
            assert conn.execute('SELECT strategyos_database_runtime_scope()').fetchone()[0]==scope


def test_all_governed_tenant_tables_have_rls_enabled(isolated_roles):
    import psycopg
    url,_,_,_,_=isolated_roles
    expected={
        'strategyos_tenants','strategyos_source_systems','strategyos_ingestion_batches',
        'strategyos_evidence_documents','strategyos_ingestion_batch_documents',
        'strategyos_source_access_policies','strategyos_source_registration_versions',
        'strategyos_evidence_occurrences','strategyos_claim_families','strategyos_claim_revisions',
        'strategyos_claim_evidence_links','strategyos_claim_assessments','strategyos_claim_dependencies',
        'strategyos_analysis_snapshots','strategyos_analysis_snapshot_claims',
        'strategyos_claim_projection_outbox','strategyos_claim_projection_cache',
        'strategyos_claim_intake_receipts','strategyos_claim_backfill_exceptions',
        'strategyos_claim_reconciliations','strategyos_claim_recalculation_receipts',
        'strategyos_claim_priority_policies',
    }
    with psycopg.connect(url) as owner:
        rows=owner.execute("""SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relrowsecurity""").fetchall()
    assert expected <= {row[0] for row in rows}
