"""Validate effective Compose output without printing connection secrets."""
import json
import sys
from urllib.parse import urlsplit


def validate(config, target='preview'):
    projects = {'preview': 'strategyos-branch', 'production': 'strategyos'}
    if target not in projects or config.get('name') != projects[target]:
        raise ValueError('Only the selected Compose project is permitted')
    prefix = 'strategyos_preview' if target == 'preview' else 'strategyos_production'
    services=config.get('services',{})
    migration=services.get('strategyos-migrate',{})
    database=urlsplit(migration.get('environment',{}).get('DATABASE_URL',''))
    if database.scheme not in ('postgres','postgresql') or not database.hostname or not database.username:
        raise ValueError('Explicit migration database target is required')
    runtime_contracts={
        'strategyos-api':(prefix+'_runtime','request'),
        'strategyos-worker':(prefix+'_worker','worker'),
        'strategyos-claim-projector':(prefix+'_projector','projector'),
    }
    seen_users=set()
    for name,(expected_user,expected_scope) in runtime_contracts.items():
        environment=services.get(name,{}).get('environment',{})
        value=environment.get('DATABASE_URL','')
        runtime=urlsplit(value)
        if runtime.username!=expected_user or not runtime.password:
            raise ValueError(name+': missing isolated runtime connection')
        if runtime.username in seen_users:
            raise ValueError(name+': runtime database identity must be distinct')
        seen_users.add(runtime.username)
        if (runtime.scheme,runtime.hostname,runtime.port,runtime.path)!=(database.scheme,database.hostname,database.port,database.path):
            raise ValueError(name+': runtime and migration database targets differ')
        if environment.get('STRATEGYOS_DATABASE_SCHEMA_MODE')!='verify':
            raise ValueError(name+': runtime schema verification is required')
        if environment.get('STRATEGYOS_DATABASE_RUNTIME_SCOPE')!=expected_scope:
            raise ValueError(name+': runtime database scope does not match its identity')
        if name == 'strategyos-api':
            public = urlsplit(environment.get('STRATEGYOS_PUBLIC_URL', ''))
            if public.scheme != 'https' or not public.hostname or public.username or public.password:
                raise ValueError('Explicit HTTPS public URL is required for browser session writes')
            if target == 'production' and public.hostname != 'strategyos.live':
                raise ValueError('Production must serve strategyos.live')
        if 'POSTGRES_PASSWORD' in environment:
            raise ValueError(name+': migration password must not enter runtime environment')
    if 'schema-migration' not in migration.get('profiles',[]):
        raise ValueError('Migration service must not start as an ordinary application service')
    if not migration.get('read_only') or 'ALL' not in migration.get('cap_drop',[]):
        raise ValueError('Migration container filesystem/capability isolation is required')
    if database.username in seen_users:
        raise ValueError('Migration and application credentials must remain separate')


if __name__=='__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', choices=['preview', 'production'], default='preview')
    args = parser.parse_args()
    try:
        validate(json.load(sys.stdin), target=args.target)
    except (ValueError,TypeError,KeyError) as error:
        print('Runtime configuration rejected: '+str(error),file=sys.stderr)
        raise SystemExit(1)
    print('Runtime/migration credential separation verified.')
