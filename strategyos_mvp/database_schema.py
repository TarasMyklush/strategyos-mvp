"""Explicit migration command and read-only, unprivileged runtime verification.

Migration credentials belong to the deployment job, never the API configuration.
Preview role provisioning requires an explicit deployment boundary and CLI flag.
This module does not choose tenant policies or enable RLS.
"""
import argparse
import hashlib
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit, urlunsplit, quote, unquote

from . import state_store


def auxiliary_scripts():
    from . import board_memory, conversation_state, decision_lifecycle, inference_audit
    return [board_memory.SCHEMA, conversation_state.SCHEMA,
            decision_lifecycle.SCHEMA, inference_audit.SCHEMA]


_LANGGRAPH_CHECKPOINT_TABLES = (
    'checkpoint_migrations',
    'checkpoints',
    'checkpoint_blobs',
    'checkpoint_writes',
)

_LANGGRAPH_CHECKPOINT_DATA_TABLES = _LANGGRAPH_CHECKPOINT_TABLES[1:]


def _langgraph_checkpoint_migrations():
    from langgraph.checkpoint.postgres import PostgresSaver
    return tuple(PostgresSaver.MIGRATIONS)


def schema_fingerprint():
    digest = hashlib.sha256()
    for payload in [state_store.schema_path().read_bytes(),
                    *[p.read_bytes() for p in sorted(state_store.migration_path().glob('[0-9][0-9][0-9][0-9]_*.sql'))],
                    *[script.encode() for script in auxiliary_scripts()],
                    *[script.encode() for script in _langgraph_checkpoint_migrations()]]:
        digest.update(len(payload).to_bytes(8,'big'))
        digest.update(payload)
    return digest.hexdigest()


def verify_langgraph_checkpoint_schema(conn):
    """Read-only proof that the release-owned LangGraph schema is current."""
    from psycopg.rows import tuple_row
    expected_version = len(_langgraph_checkpoint_migrations()) - 1
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT array_agg(name ORDER BY name) FROM unnest(%s::text[]) name "
            "WHERE to_regclass('public.' || name) IS NULL",
            (list(_LANGGRAPH_CHECKPOINT_TABLES),),
        )
        missing = cur.fetchone()[0]
        if missing:
            raise RuntimeError(
                'LangGraph checkpoint schema is missing release-owned tables: '
                + ', '.join(missing)
            )
        cur.execute('SELECT max(v) FROM public.checkpoint_migrations')
        row = cur.fetchone()
        if not row or row[0] != expected_version:
            raise RuntimeError(
                'LangGraph checkpoint schema does not match this release; runtime DDL is disabled.'
            )
        cur.execute("""SELECT
            EXISTS(SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='checkpoint_writes'
                     AND column_name='task_path' AND is_nullable='NO'),
            (SELECT is_nullable='YES' FROM information_schema.columns
             WHERE table_schema='public' AND table_name='checkpoint_blobs'
               AND column_name='blob'),
            (SELECT count(*)=3 FROM pg_indexes
             WHERE schemaname='public' AND indexname IN (
               'checkpoints_thread_id_idx','checkpoint_blobs_thread_id_idx',
               'checkpoint_writes_thread_id_idx'))""")
        contract = cur.fetchone()
        if not contract or not all(contract):
            raise RuntimeError(
                'LangGraph checkpoint schema is incomplete; runtime DDL is disabled.'
            )


def prepare_langgraph_checkpoint_schema(conn):
    """Install LangGraph checkpoint migrations using deployment-owner authority."""
    expected_version = len(_langgraph_checkpoint_migrations()) - 1
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.checkpoint_migrations')")
        exists = cur.fetchone()[0] is not None
        current_version = None
        if exists:
            cur.execute('SELECT max(v) FROM public.checkpoint_migrations')
            current_version = cur.fetchone()[0]
    conn.commit()
    if current_version != expected_version:
        from langgraph.checkpoint.postgres import PostgresSaver
        previous_autocommit = conn.autocommit
        conn.autocommit = True
        try:
            conn.execute('SET search_path TO public,pg_catalog')
            PostgresSaver(conn).setup()
        finally:
            conn.autocommit = previous_autocommit
    verify_langgraph_checkpoint_schema(conn)
    conn.commit()


def prepare_schema(conn):
    """Deployment-only operation; PostgreSQL enforces DDL authority."""
    with conn.cursor() as cur:
        cur.execute('SET LOCAL search_path TO public,pg_catalog')
        state_store._execute_sql_statements(cur, state_store.schema_path().read_text())
        state_store.apply_schema_migrations(cur)
        for script in auxiliary_scripts():
            state_store._execute_sql_statements(cur, script)
    conn.commit()
    prepare_langgraph_checkpoint_schema(conn)
    with conn.cursor() as cur:
        cur.execute('''INSERT INTO strategyos_runtime_schema_contract(singleton,fingerprint)
            VALUES(true,%s) ON CONFLICT(singleton) DO UPDATE SET fingerprint=excluded.fingerprint,
            prepared_at=now(),prepared_by=current_user''',(schema_fingerprint(),))
    conn.commit()


_RUNTIME_MARKERS = {
    'request': 'strategyos-preview-runtime:1',
    'worker': 'strategyos-preview-worker:1',
    'projector': 'strategyos-preview-projector:1',
}

_RUNTIME_SCOPE_ROLES = {
    'request': 'strategyos_preview_request_scope',
    'worker': 'strategyos_preview_worker_scope',
    'projector': 'strategyos_preview_projector_scope',
}

_RUNTIME_SCOPE_MARKERS = {
    scope: f'strategyos-preview-scope:{scope}:1' for scope in _RUNTIME_SCOPE_ROLES
}


def verify_runtime_schema(conn, *, expected_scope=None):
    """Refuse missing/mismatched schema or a runtime able to bypass its guards."""
    scope=str(expected_scope or getattr(state_store.CONFIG,'database_runtime_scope','request')).strip().lower()
    if scope not in _RUNTIME_MARKERS:
        raise RuntimeError('Unsupported database runtime scope.')
    with conn.cursor() as cur:
        cur.execute('''SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls OR rolreplication
            OR EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg_%%'
                      AND n.nspname <> 'information_schema' AND has_schema_privilege(current_user,n.oid,'CREATE'))
            OR has_database_privilege(current_user,current_database(),'TEMP')
            OR EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                      WHERE n.nspname='public' AND c.relowner=r.oid)
            OR EXISTS(
                SELECT 1 FROM pg_auth_members m JOIN pg_roles granted ON granted.oid=m.roleid
                WHERE m.member=r.oid AND granted.rolname <> %s
            )
            FROM pg_roles r WHERE rolname=current_user''', (_RUNTIME_SCOPE_ROLES[scope],))
        row=cur.fetchone()
        if not row or row[0]:
            raise RuntimeError('Runtime database role must not own schema, inherit privileged roles, or bypass database controls.')
        cur.execute("SELECT shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname=current_user")
        marker=cur.fetchone()
        if not marker or marker[0] != _RUNTIME_MARKERS[scope]:
            raise RuntimeError('Runtime database role is not provisioned for its declared scope.')
        cur.execute(
            "SELECT pg_has_role(current_user,%s,'MEMBER'), "
            "array_agg(scope_role ORDER BY scope_role) FILTER (WHERE pg_has_role(current_user,scope_role,'MEMBER')) "
            "FROM unnest(%s::text[]) scope_role",
            (_RUNTIME_SCOPE_ROLES[scope], list(_RUNTIME_SCOPE_ROLES.values())),
        )
        membership = cur.fetchone()
        if not membership or not membership[0] or membership[1] != [_RUNTIME_SCOPE_ROLES[scope]]:
            raise RuntimeError('Runtime database role does not have one exact database-enforced scope membership.')
        cur.execute("SELECT to_regclass('public.strategyos_runtime_schema_contract')")
        if cur.fetchone()[0] is None:
            raise RuntimeError('Database schema must be prepared by the deployment migration job.')
        cur.execute("SELECT has_table_privilege(current_user,'public.strategyos_runtime_schema_contract','INSERT,UPDATE,DELETE,TRUNCATE') OR has_table_privilege(current_user,'public.strategyos_schema_migrations','INSERT,UPDATE,DELETE,TRUNCATE')")
        if cur.fetchone()[0]:
            raise RuntimeError('Runtime must not modify deployment schema contracts or migration history.')
        if scope in {'request','worker'}:
            cur.execute("SELECT has_table_privilege(current_user,'public.strategyos_claim_revisions','SELECT,INSERT') AND NOT has_table_privilege(current_user,'public.strategyos_claim_revisions','UPDATE,DELETE,TRUNCATE')")
            if not cur.fetchone()[0]:
                raise RuntimeError('Request and worker roles must append governed claims without rewrite authority.')
        else:
            cur.execute("""SELECT
                has_table_privilege(current_user,'public.strategyos_claim_projection_outbox','SELECT,UPDATE')
                AND has_table_privilege(current_user,'public.strategyos_claim_projection_cache','SELECT,INSERT,UPDATE,DELETE')
                AND NOT has_table_privilege(current_user,'public.strategyos_claim_revisions','INSERT,UPDATE,DELETE,TRUNCATE')
                AND NOT has_table_privilege(current_user,'public.strategyos_claim_assessments','INSERT,UPDATE,DELETE,TRUNCATE')
                AND NOT has_table_privilege(current_user,'public.strategyos_finance_facts','SELECT')""")
            if not cur.fetchone()[0]:
                raise RuntimeError('Projector role exceeds or lacks its projection-only database authority.')
        checkpoint_tables = list(_LANGGRAPH_CHECKPOINT_TABLES)
        checkpoint_data_tables = list(_LANGGRAPH_CHECKPOINT_DATA_TABLES)
        if scope == 'worker':
            cur.execute("""SELECT
                bool_and(has_table_privilege(current_user,'public.' || table_name,'SELECT')),
                (SELECT bool_and(has_table_privilege(current_user,'public.' || data_table,'INSERT'))
                 FROM unnest(%s::text[]) data_table),
                (SELECT bool_and(has_table_privilege(current_user,'public.' || data_table,'UPDATE'))
                 FROM unnest(%s::text[]) data_table),
                (SELECT bool_and(has_table_privilege(current_user,'public.' || data_table,'DELETE'))
                 FROM unnest(%s::text[]) data_table),
                NOT has_table_privilege(current_user,'public.checkpoint_migrations','INSERT'),
                NOT has_table_privilege(current_user,'public.checkpoint_migrations','UPDATE'),
                NOT has_table_privilege(current_user,'public.checkpoint_migrations','DELETE'),
                NOT has_table_privilege(current_user,'public.checkpoint_migrations','TRUNCATE')
                FROM unnest(%s::text[]) table_name""",
                (checkpoint_data_tables, checkpoint_data_tables,
                 checkpoint_data_tables, checkpoint_tables))
            privileges = cur.fetchone()
            if not privileges or not all(privileges):
                raise RuntimeError('Worker role lacks or exceeds its checkpoint data authority.')
            verify_langgraph_checkpoint_schema(conn)
        else:
            cur.execute("""SELECT bool_and(
                NOT has_table_privilege(current_user,'public.' || table_name,'SELECT')
                AND NOT has_table_privilege(current_user,'public.' || table_name,'INSERT')
                AND NOT has_table_privilege(current_user,'public.' || table_name,'UPDATE')
                AND NOT has_table_privilege(current_user,'public.' || table_name,'DELETE')
                AND NOT has_table_privilege(current_user,'public.' || table_name,'TRUNCATE'))
                FROM unnest(%s::text[]) table_name""", (checkpoint_tables,))
            if not cur.fetchone()[0]:
                raise RuntimeError('Request and projector roles must not access workflow checkpoints.')
        cur.execute('SELECT fingerprint FROM public.strategyos_runtime_schema_contract WHERE singleton=true')
        row=cur.fetchone()
        if not row or row[0] != schema_fingerprint():
            raise RuntimeError('Prepared database schema does not match this release; runtime DDL is disabled.')


def provision_preview_runtime(conn, destination: Path, *, role='strategyos_preview_runtime'):
    """Provision separate request, workflow and projection identities."""
    import psycopg
    from psycopg import sql
    if os.environ.get('STRATEGYOS_DEPLOYMENT_BOUNDARY') != 'preview':
        raise RuntimeError('Runtime provisioning is restricted to the explicit preview deployment boundary.')
    if not role.startswith('strategyos_preview_runtime'):
        raise ValueError('Only a preview runtime role can be provisioned.')
    suffix=role.removeprefix('strategyos_preview_runtime')
    role_specs={
        'request':(role,'STRATEGYOS_RUNTIME_DATABASE_URL'),
        'worker':('strategyos_preview_worker'+suffix,'STRATEGYOS_WORKER_DATABASE_URL'),
        'projector':('strategyos_preview_projector'+suffix,'STRATEGYOS_PROJECTOR_DATABASE_URL'),
    }
    owner_url=urlsplit(state_store.CONFIG.database_url or '')
    if owner_url.scheme not in {'postgres','postgresql'} or not owner_url.hostname:
        raise ValueError('Runtime provisioning requires an explicit PostgreSQL URL.')
    saved_entries={}
    if destination.exists():
        saved_entries=dict(line.split('=',1) for line in destination.read_text().splitlines() if '=' in line)
    passwords={}
    for scope,(login,key) in role_specs.items():
        password=secrets.token_hex(32)
        if key in saved_entries:
            saved=urlsplit(saved_entries[key])
            if (saved.username!=login or saved.hostname!=owner_url.hostname or saved.port!=owner_url.port
                    or saved.path!=owner_url.path or not saved.password):
                raise ValueError('Existing runtime credential target does not match this deployment.')
            password=unquote(saved.password)
        passwords[scope]=password
    with conn.cursor() as cur:
        for scope, scope_role in _RUNTIME_SCOPE_ROLES.items():
            marker = _RUNTIME_SCOPE_MARKERS[scope]
            cur.execute("SELECT shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname=%s", (scope_role,))
            row = cur.fetchone()
            if row is not None and row[0] != marker:
                raise RuntimeError('Refusing to modify an unmanaged database scope role.')
            if row is None:
                cur.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS').format(sql.Identifier(scope_role)))
                cur.execute(sql.SQL('COMMENT ON ROLE {} IS {}').format(sql.Identifier(scope_role), sql.Literal(marker)))
        for scope,(login,_) in role_specs.items():
            marker=_RUNTIME_MARKERS[scope]
            cur.execute("SELECT shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname=%s",(login,))
            row=cur.fetchone()
            if row is not None and row[0]!=marker:
                raise RuntimeError('Refusing to modify an unmanaged database role.')
            if row is None:
                cur.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS').format(sql.Identifier(login)))
                cur.execute(sql.SQL('COMMENT ON ROLE {} IS {}').format(sql.Identifier(login),sql.Literal(marker)))
            cur.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(login),sql.Literal(passwords[scope])))
            for candidate in _RUNTIME_SCOPE_ROLES.values():
                cur.execute(sql.SQL('REVOKE {} FROM {}').format(sql.Identifier(candidate), sql.Identifier(login)))
            cur.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(_RUNTIME_SCOPE_ROLES[scope]), sql.Identifier(login)))
        cur.execute(sql.SQL('REVOKE TEMP ON DATABASE {} FROM PUBLIC').format(sql.Identifier(conn.info.dbname)))
        cur.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        for login,_ in role_specs.values():
            cur.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(conn.info.dbname),sql.Identifier(login)))
            cur.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(login)))
        request_role=role_specs['request'][0]
        worker_role=role_specs['worker'][0]
        projector_role=role_specs['projector'][0]
        for login in (request_role,worker_role):
            cur.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}').format(sql.Identifier(login)))
            cur.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(sql.Identifier(login)))
        projector_read_tables='''strategyos_runtime_schema_contract,strategyos_schema_migrations,
            strategyos_tenants,strategyos_source_systems,strategyos_evidence_documents,
            strategyos_source_access_policies,strategyos_source_registration_versions,
            strategyos_evidence_occurrences,strategyos_claim_families,
            strategyos_claim_revisions,strategyos_claim_evidence_links,
            strategyos_claim_assessments,strategyos_claim_dependencies,
            strategyos_claim_projection_outbox,strategyos_claim_projection_cache'''
        cur.execute(sql.SQL('GRANT SELECT ON '+projector_read_tables+' TO {}').format(sql.Identifier(projector_role)))
        cur.execute(sql.SQL('GRANT UPDATE ON strategyos_claim_projection_outbox TO {}').format(sql.Identifier(projector_role)))
        cur.execute(sql.SQL('GRANT INSERT,UPDATE,DELETE ON strategyos_claim_projection_cache TO {}').format(sql.Identifier(projector_role)))
        checkpoint_tables=','.join(_LANGGRAPH_CHECKPOINT_TABLES)
        checkpoint_data_tables=','.join(_LANGGRAPH_CHECKPOINT_DATA_TABLES)
        for login in (request_role,projector_role):
            cur.execute(sql.SQL('REVOKE ALL PRIVILEGES ON '+checkpoint_tables+' FROM {}').format(sql.Identifier(login)))
        cur.execute(sql.SQL('REVOKE ALL PRIVILEGES ON '+checkpoint_tables+' FROM {}').format(sql.Identifier(worker_role)))
        cur.execute(sql.SQL('GRANT SELECT ON '+checkpoint_tables+' TO {}').format(sql.Identifier(worker_role)))
        cur.execute(sql.SQL('GRANT INSERT,UPDATE,DELETE ON '+checkpoint_data_tables+' TO {}').format(sql.Identifier(worker_role)))
        for login in (request_role,worker_role,projector_role):
            cur.execute(sql.SQL('REVOKE INSERT,UPDATE,DELETE,TRUNCATE ON strategyos_runtime_schema_contract,strategyos_schema_migrations FROM {}').format(sql.Identifier(login)))
            cur.execute(sql.SQL('REVOKE UPDATE,DELETE,TRUNCATE ON strategyos_claim_revisions,strategyos_claim_assessments,strategyos_board_snapshots FROM {}').format(sql.Identifier(login)))
    conn.commit()
    host=owner_url.hostname
    if ':' in host: host='['+host+']'
    runtime_urls={}
    for scope,(login,key) in role_specs.items():
        authority=quote(login,safe='')+':'+quote(passwords[scope],safe='')+'@'+host
        if owner_url.port: authority+=':'+str(owner_url.port)
        runtime_url=urlunsplit((owner_url.scheme,authority,owner_url.path,owner_url.query,''))
        with psycopg.connect(runtime_url) as runtime:
            verify_runtime_schema(runtime,expected_scope=scope)
        runtime_urls[key]=runtime_url
    destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=destination.with_name(destination.name+'.pending-'+secrets.token_hex(8))
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as handle:
        for _,key in role_specs.values():
            handle.write(key+'='+runtime_urls[key]+'\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary,destination)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='Prepare schema using deployment-only credentials.')
    parser.add_argument('--preview-runtime-env',type=Path,help='Provision the preview-only runtime role and write a private connection file.')
    args=parser.parse_args()
    handle,failure=state_store.database_connection()
    if failure or handle is None:
        raise RuntimeError('Database unavailable.')
    with handle as conn:
        if args.apply:
            prepare_schema(conn)
            if args.preview_runtime_env:
                provision_preview_runtime(conn,args.preview_runtime_env)
            print('Database schema prepared; no business claims were reclassified.')
        else:
            if args.preview_runtime_env:
                raise ValueError('Runtime provisioning requires the explicit --apply deployment operation.')
            verify_runtime_schema(conn)
            print('Unprivileged runtime schema verification passed.')


if __name__ == '__main__':
    main()
