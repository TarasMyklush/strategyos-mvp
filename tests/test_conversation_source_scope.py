import pytest
from fastapi import HTTPException
from strategyos_mvp import api, claim_store, conversation_state, access_scope, state_store


@pytest.mark.parametrize('result', [False, None, 'true'])
@pytest.mark.parametrize('method', ['read', 'write'])
def test_conversation_read_and_write_reject_unknown_source_rights(monkeypatch, result, method):
    principal = {'tenant_id': 'tenant', 'subject': 'ceo', 'role': 'executive'}
    monkeypatch.setattr(api, '_assistant_authority_refusal', lambda *args: None)
    monkeypatch.setattr(access_scope, 'guard_run', lambda *args, **kwargs: None)
    class Repository:
        def run_source_access(self, run, *, context):
            assert context.principal_id == 'ceo'
            assert str(context.purpose) == 'executive_briefing'
            return {'allowed': result}
    monkeypatch.setattr(claim_store, 'ClaimRepository', Repository)
    monkeypatch.setattr(state_store, 'database_connection', lambda: pytest.fail('Private history opened'))
    with pytest.raises(PermissionError):
        if method == 'read': conversation_state.read('run', 'ceo', principal)
        else: conversation_state.write(conversation_state.ThreadState(run_id='run',persona='ceo',version=0,threads={}),principal)


def test_conversation_respects_persona_authority_refusal(monkeypatch):
    monkeypatch.setattr(api, '_assistant_authority_refusal', lambda *args: {'response_mode':'authority_refusal'})
    monkeypatch.setattr(access_scope, 'guard_run', lambda *args, **kwargs: pytest.fail('History opened'))
    with pytest.raises(HTTPException) as caught:
        conversation_state.access({'role':'executive'}, 'run', 'ceo')
    assert caught.value.status_code == 403


def test_browser_rechecks_same_run_and_hides_unauthorized_history():
    import json
    from pathlib import Path
    import subprocess
    source = (Path(api.STATIC_DIR) / 'executive.js').read_text()
    function = source[source.index('  async function loadDurableThreads()'):source.index('  function personaThreadRecords()')]
    program = '''const assert = require('node:assert/strict');
const state = {session:{authenticated:true},activePersona:'ceo',durableThreadScope:{runId:'run',persona:'ceo'}};
const records = {'ceo:qa':{answer:'old saved answer'},'gm:qa':{answer:'separate scope'}};
const threadStore = () => records;
const activeRunId = () => 'run';
const buildQuery = () => '?run_id=run';
let checked = 0; let notice = '';
const fetchJson = async (path, required) => { checked++; assert.equal(required,true); throw Error('Denied'); };
const showToast = text => { notice = text; };
''' + function + '''
loadDurableThreads().then(() => {
assert.equal(checked,1);
assert.equal(records['ceo:qa'],undefined);
assert.ok(records['gm:qa']);
assert.equal(state.durableThreadScope,null);
assert.match(notice,/has not been deleted/);
}).catch(error => { console.error(error); process.exitCode=1; });
'''
    subprocess.run(['node','-e',program],check=True,capture_output=True,text=True)
