"""Validate effective Compose output without printing connection secrets."""
import json
import sys
from urllib.parse import urlsplit


def validate(config):
    if config.get('name')!='strategyos-branch':
        raise ValueError('Only the preview Compose project is permitted')
    services=config.get('services',{})
    migration=services.get('strategyos-migrate',{})
    target=urlsplit(migration.get('environment',{}).get('DATABASE_URL',''))
    if target.scheme not in ('postgres','postgresql') or not target.hostname or not target.username:
        raise ValueError('Explicit migration database target is required')
    runtime_contracts={
        'strategyos-api':('strategyos_preview_runtime','request'),
        'strategyos-worker':('strategyos_preview_worker','worker'),
        'strategyos-claim-projector':('strategyos_preview_projector','projector'),
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
        if (runtime.scheme,runtime.hostname,runtime.port,runtime.path)!=(target.scheme,target.hostname,target.port,target.path):
            raise ValueError(name+': runtime and migration database targets differ')
        if environment.get('STRATEGYOS_DATABASE_SCHEMA_MODE')!='verify':
            raise ValueError(name+': runtime schema verification is required')
        if environment.get('STRATEGYOS_DATABASE_RUNTIME_SCOPE')!=expected_scope:
            raise ValueError(name+': runtime database scope does not match its identity')
        if 'POSTGRES_PASSWORD' in environment:
            raise ValueError(name+': migration password must not enter runtime environment')
    if 'schema-migration' not in migration.get('profiles',[]):
        raise ValueError('Migration service must not start as an ordinary application service')
    if not migration.get('read_only') or 'ALL' not in migration.get('cap_drop',[]):
        raise ValueError('Migration container filesystem/capability isolation is required')
    if urlsplit(migration.get('environment',{}).get('DATABASE_URL','')).username=='strategyos_preview_runtime':
        raise ValueError('Migration and application credentials must remain separate')


if __name__=='__main__':
    try:
        validate(json.load(sys.stdin))
    except (ValueError,TypeError,KeyError) as error:
        print('Preview runtime configuration rejected: '+str(error),file=sys.stderr)
        raise SystemExit(1)
    print('Preview runtime/migration credential separation verified.')
