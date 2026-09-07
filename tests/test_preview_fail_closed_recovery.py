import os
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).parents[1]
SCRIPT=ROOT/'deploy/scripts/quiesce_preview.sh'


def test_preview_failure_never_auto_restores_weaker_reads():
    workflow=(ROOT/'.github/workflows/strategyos-branch-deploy.yml').read_text()
    assert 'bash deploy/scripts/rollback_stack.sh' not in workflow
    assert 'bash deploy/scripts/quiesce_preview.sh' in workflow
    assert "steps.deploy.outcome == 'failure'" in workflow


def test_legacy_rollback_helper_also_refuses_preview():
    result=subprocess.run(['bash',str(ROOT/'deploy/scripts/rollback_stack.sh')],env={**os.environ,
        'TARGET_HOST':'not-contacted.invalid','TARGET_DIR':'/opt/strategyos-branch'},capture_output=True,text=True)
    assert result.returncode==1
    assert 'verified roll-forward' in result.stderr


@pytest.mark.parametrize('target',['/opt/strategyos','/','/opt/strategyos-branch/../strategyos'])
def test_recovery_rejects_non_preview_before_any_ssh(target):
    result=subprocess.run(['bash',str(SCRIPT)],env={**os.environ,'TARGET_HOST':'not-contacted.invalid','TARGET_DIR':target},capture_output=True,text=True)
    assert result.returncode==1
    assert 'Refusing recovery outside' in result.stderr


@pytest.mark.parametrize('wrong_owner',[False,True])
def test_recovery_stops_only_verified_preview_app_containers(tmp_path,wrong_owner):
    # Execute the real remote shell body against a deterministic Docker double.
    # No Docker daemon, SSH server, files/volumes or live application is touched.
    remote=SCRIPT.read_text().split("<<'REMOTE'\n",1)[1].rsplit('\nREMOTE',1)[0]
    docker=tmp_path/'docker'
    docker.write_text('''#!/usr/bin/env bash
set -eu
case "$1" in
 ps) case "$*" in
  *service=strategyos-api*) echo aaaaaaaaaaaa;;
  *service=strategyos-worker*) echo bbbbbbbbbbbb;;
  *service=strategyos-claim-projector*) printf 'cccccccccccc\\ndddddddddddd\\n';;
  *service=postgres*) echo eeeeeeeeeeee;;
 esac;;
 inspect) case "$3" in
  *project*) echo "${PROOF_PROJECT}";;
  *service*) case "$4" in
   aaaaaaaaaaaa) echo strategyos-api;;
   bbbbbbbbbbbb) echo strategyos-worker;;
   eeeeeeeeeeee) echo postgres;;
   *) echo strategyos-claim-projector;;
  esac;;
 esac;;
 stop) echo "$4" >> "$PROOF_LOG";;
 exec) printf '%s\n' "$*" >> "$PROOF_EXEC_LOG"; cat > "$PROOF_SQL_LOG";;
 *) exit 92;;
esac
''')
    docker.chmod(0o700)
    log=tmp_path/'stopped'
    exec_log=tmp_path/'executed'
    sql_log=tmp_path/'sql'
    result=subprocess.run(['bash','-c',remote],env={**os.environ,'PATH':str(tmp_path)+os.pathsep+os.environ['PATH'],
        'PROOF_LOG':str(log),'PROOF_EXEC_LOG':str(exec_log),
        'PROOF_SQL_LOG':str(sql_log),
        'PROOF_PROJECT':'production' if wrong_owner else 'strategyos-branch'},capture_output=True,text=True)
    if wrong_owner:
        assert result.returncode!=0 and not log.exists()
        assert 'ownership mismatch' in result.stderr
    else:
        assert result.returncode==0, result.stderr
        assert log.read_text().splitlines()==['aaaaaaaaaaaa','bbbbbbbbbbbb','cccccccccccc','dddddddddddd']
        assert exec_log.read_text().splitlines()==[
            'exec -i eeeeeeeeeeee sh -lc exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
        ]
        sql=sql_log.read_text()
        assert "set status = 'cancelled'" in sql
        assert "where status in ('queued', 'running')" in sql
        assert 'audit history' in result.stdout


def test_recovery_terminalizes_interrupted_jobs_before_roll_forward():
    script=SCRIPT.read_text()
    assert "status = 'cancelled'" in script
    assert "where status in ('queued', 'running')" in script
    assert 'shutdown_reason' in script
    assert "metadata_json = coalesce(metadata_json" in script
