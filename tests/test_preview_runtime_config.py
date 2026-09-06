import importlib.util
from pathlib import Path

import pytest

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('preview_runtime_check',ROOT/'deploy/scripts/validate_preview_runtime_config.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    services={name:{'environment':{'DATABASE_URL':'postgresql://strategyos_preview_runtime:synthetic@postgres/proof',
        'STRATEGYOS_DATABASE_SCHEMA_MODE':'verify'}} for name in ('strategyos-api','strategyos-worker','strategyos-claim-projector')}
    services['strategyos-migrate']={'profiles':['schema-migration'],'read_only':True,'cap_drop':['ALL'],
        'environment':{'DATABASE_URL':'postgresql://migration:synthetic@postgres/proof'}}
    return {'name':'strategyos-branch','services':services}


def test_effective_runtime_connections_are_separate():
    module.validate(fixture())


@pytest.mark.parametrize('service',['strategyos-api','strategyos-worker','strategyos-claim-projector'])
@pytest.mark.parametrize('field,value',[
    ('DATABASE_URL','postgresql://owner:synthetic@postgres/proof'),
    ('STRATEGYOS_DATABASE_SCHEMA_MODE','auto'),
    ('POSTGRES_PASSWORD','synthetic'),
    ('DATABASE_URL','postgresql://strategyos_preview_runtime:synthetic@foreign/proof'),
])
def test_later_overlay_cannot_restore_runtime_migration_authority(service,field,value):
    config=fixture()
    config['services'][service]['environment'][field]=value
    with pytest.raises(ValueError): module.validate(config)


def test_preview_deploy_prepares_role_before_starting_new_application():
    script=(ROOT/'deploy/scripts/deploy_stack.sh').read_text()
    assert script.index('run --rm --no-deps strategyos-migrate') < script.index('validate_preview_runtime_config.py') < script.index('up -d --no-build --wait')
    assert '/opt/strategyos-branch/runtime-database/runtime.env' in script
    lines=[line for line in script.splitlines() if '--profile schema-migration' in line]
    assert len(lines)==1 and 'config --format json' in lines[0]
    assert 'up -d' not in lines[0]


def test_real_compose_inactive_migration_profile_is_included_only_for_inspection(tmp_path):
    import json
    import shutil
    import subprocess
    executable=shutil.which('docker')
    if executable is None:
        pytest.fail('Docker Compose is required for the deployment configuration proof.')
    config=fixture()
    for service in config['services'].values():
        service['image']='synthetic/config-only:unused'
    path=tmp_path/'compose.json'
    path.write_text(json.dumps(config))
    command=[executable,'compose','-f',str(path),'--project-name','strategyos-branch']
    ordinary=json.loads(subprocess.check_output(command+['config','--format','json'],text=True))
    assert 'strategyos-migrate' not in ordinary['services']
    with pytest.raises(ValueError,match='migration database target'):
        module.validate(ordinary)
    inspection=json.loads(subprocess.check_output(command+['--profile','schema-migration','config','--format','json'],text=True))
    module.validate(inspection)
    assert inspection['services']['strategyos-migrate']['profiles']==['schema-migration']
