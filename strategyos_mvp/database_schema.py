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


def schema_fingerprint():
    digest = hashlib.sha256()
    for payload in [state_store.schema_path().read_bytes(),
                    *[p.read_bytes() for p in sorted(state_store.migration_path().glob('[0-9][0-9][0-9][0-9]_*.sql'))],
                    *[script.encode() for script in auxiliary_scripts()]]:
        digest.update(len(payload).to_bytes(8,'big'))
        digest.update(payload)
    return digest.hexdigest()


def prepare_schema(conn):
    """Deployment-only operation; PostgreSQL enforces DDL authority."""
    with conn.cursor() as cur:
        cur.execute('SET LOCAL search_path TO public,pg_catalog')
        state_store._execute_sql_statements(cur, state_store.schema_path().read_text())
        state_store.apply_schema_migrations(cur)
        for script in auxiliary_scripts():
            state_store._execute_sql_statements(cur, script)
        cur.execute('''INSERT INTO strategyos_runtime_schema_contract(singleton,fingerprint)
            VALUES(true,%s) ON CONFLICT(singleton) DO UPDATE SET fingerprint=excluded.fingerprint,
            prepared_at=now(),prepared_by=current_user''',(schema_fingerprint(),))
    conn.commit()


def verify_runtime_schema(conn):
    """Refuse missing/mismatched schema or a runtime able to bypass its guards."""
    with conn.cursor() as cur:
        cur.execute('''SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls OR rolreplication
            OR EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg_%'
                      AND n.nspname <> 'information_schema' AND has_schema_privilege(current_user,n.oid,'CREATE'))
            OR has_database_privilege(current_user,current_database(),'TEMP')
            OR EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                      WHERE n.nspname='public' AND c.relowner=r.oid)
            OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid)
            FROM pg_roles r WHERE rolname=current_user''')
        row=cur.fetchone()
        if not row or row[0]:
            raise RuntimeError('Runtime database role must not own schema, inherit privileged roles, or bypass database controls.')
        cur.execute("SELECT to_regclass('public.strategyos_runtime_schema_contract')")
        if cur.fetchone()[0] is None:
            raise RuntimeError('Database schema must be prepared by the deployment migration job.')
        cur.execute("SELECT has_table_privilege(current_user,'public.strategyos_runtime_schema_contract','INSERT,UPDATE,DELETE,TRUNCATE') OR has_table_privilege(current_user,'public.strategyos_schema_migrations','INSERT,UPDATE,DELETE,TRUNCATE')")
        if cur.fetchone()[0]:
            raise RuntimeError('Runtime must not modify deployment schema contracts or migration history.')
        cur.execute('SELECT fingerprint FROM public.strategyos_runtime_schema_contract WHERE singleton=true')
        row=cur.fetchone()
        if not row or row[0] != schema_fingerprint():
            raise RuntimeError('Prepared database schema does not match this release; runtime DDL is disabled.')


def provision_preview_runtime(conn, destination: Path, *, role='strategyos_preview_runtime'):
    """Deployment-only provisioning; a private file survives subsequent releases."""
    import psycopg
    from psycopg import sql
    if os.environ.get('STRATEGYOS_DEPLOYMENT_BOUNDARY') != 'preview':
        raise RuntimeError('Runtime provisioning is restricted to the explicit preview deployment boundary.')
    if not role.startswith('strategyos_preview_runtime'):
        raise ValueError('Only a preview runtime role can be provisioned.')
    marker='strategyos-preview-runtime:1'
    owner_url=urlsplit(state_store.CONFIG.database_url or '')
    if owner_url.scheme not in {'postgres','postgresql'} or not owner_url.hostname:
        raise ValueError('Runtime provisioning requires an explicit PostgreSQL URL.')
    password=secrets.token_hex(32)
    if destination.exists():
        entries=dict(line.split('=',1) for line in destination.read_text().splitlines() if '=' in line)
        saved=urlsplit(entries.get('STRATEGYOS_RUNTIME_DATABASE_URL',''))
        if (saved.username!=role or saved.hostname!=owner_url.hostname or saved.port!=owner_url.port
                or saved.path!=owner_url.path or not saved.password):
            raise ValueError('Existing runtime credential target does not match this deployment.')
        password=unquote(saved.password)
    with conn.cursor() as cur:
        cur.execute("SELECT shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname=%s",(role,))
        row=cur.fetchone()
        if row is not None and row[0]!=marker:
            raise RuntimeError('Refusing to modify an unmanaged database role.')
        if row is None:
            cur.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS').format(sql.Identifier(role)))
            cur.execute(sql.SQL('COMMENT ON ROLE {} IS {}').format(sql.Identifier(role),sql.Literal(marker)))
        cur.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(role),sql.Literal(password)))
        cur.execute(sql.SQL('REVOKE TEMP ON DATABASE {} FROM PUBLIC').format(sql.Identifier(conn.info.dbname)))
        cur.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        cur.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(conn.info.dbname),sql.Identifier(role)))
        cur.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
        cur.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}').format(sql.Identifier(role)))
        cur.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(sql.Identifier(role)))
        cur.execute(sql.SQL('REVOKE INSERT,UPDATE,DELETE,TRUNCATE ON strategyos_runtime_schema_contract,strategyos_schema_migrations FROM {}').format(sql.Identifier(role)))
        cur.execute(sql.SQL('REVOKE UPDATE,DELETE,TRUNCATE ON strategyos_claim_revisions,strategyos_claim_assessments,strategyos_board_snapshots FROM {}').format(sql.Identifier(role)))
    conn.commit()
    host=owner_url.hostname
    if ':' in host: host='['+host+']'
    authority=quote(role,safe='')+':'+quote(password,safe='')+'@'+host
    if owner_url.port: authority+=':'+str(owner_url.port)
    runtime_url=urlunsplit((owner_url.scheme,authority,owner_url.path,owner_url.query,''))
    with psycopg.connect(runtime_url) as runtime:
        verify_runtime_schema(runtime)
    destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=destination.with_name(destination.name+'.pending-'+secrets.token_hex(8))
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as handle:
        handle.write('STRATEGYOS_RUNTIME_DATABASE_URL='+runtime_url+'\n')
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
