"""Exercise async control ownership independently of network timing."""
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1] / 'strategyos_mvp' / 'static'


def test_board_analysis_change_waits_for_inflight_work_without_losing_new_selection():
    source = (ROOT / 'board_pack.js').read_text()
    action = source[source.index('  function action(work)'):source.index('  async function request(')]
    program = r'''
const assert = require('assert');
let analysis = 'old', busy = false, workQueue = Promise.resolve(), pendingWork = 0;
const button = {disabled:false};
const status = {textContent:''};
const $ = id => id === 'board-pack' ? {querySelectorAll:()=>[button]} : status;
const updateDownloads = () => {};
ACTION
(async () => {
  let release;
  const blocked = new Promise(resolve => release = resolve);
  const calls = [];
  const first = action(async () => { calls.push('old-start'); await blocked; throw Error('old response'); });
  await Promise.resolve();
  analysis = 'new';
  const second = action(async () => { assert(button.disabled); calls.push('new-loaded'); });
  assert(button.disabled);
  release();
  await Promise.all([first,second]);
  assert.deepStrictEqual(calls,['old-start','new-loaded']);
  assert.strictEqual(status.textContent,'');
  assert.strictEqual(button.disabled,false);
  assert.strictEqual(busy,false);
  const stale = action(async () => {throw Error('obsolete action ran');});
  analysis = 'latest';
  await stale;
  assert.strictEqual(status.textContent,'');
})().catch(error=>{console.error(error);process.exit(1)});
'''.replace('ACTION', action)
    subprocess.run([shutil.which('node') or 'node', '-e', program], check=True, capture_output=True, text=True)


def test_intent_completion_cannot_enable_controls_owned_by_another_busy_panel():
    source = (ROOT / 'intent_vault.js').read_text()
    controls = source[source.index('  function controls()'):source.index('  function seasonalityControls()')]
    program = r'''
const assert = require('assert');
const own = {disabled:true,closest:()=>null};
const other = {disabled:true,closest:()=>({})};
const document = {querySelectorAll:()=>[own,other]};
const state = {busy:false,record:null};
const $ = ()=>({disabled:false,value:'',checked:false});
const seasonalityControls = ()=>{};
CONTROLS
controls();
assert.strictEqual(own.disabled,false);
assert.strictEqual(other.disabled,true);
'''.replace('CONTROLS', controls)
    subprocess.run([shutil.which('node') or 'node', '-e', program], check=True, capture_output=True, text=True)
    html = (ROOT / 'plan.html').read_text()
    for owner in ('board', 'advisor', 'structure', 'objective', 'source-package'):
        assert f'data-control-owner="{owner}"' in html
