import json
from pathlib import Path
import shutil
import subprocess
import pytest


@pytest.mark.parametrize('outcome', ['ready', 'failed', 'forbidden'])
def test_queued_job_opens_only_its_assigned_review(outcome):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the queued review controller proof')
    source = Path('strategyos_mvp/static/run-review-page.js').read_text()
    harness = r'''
const assert = require('node:assert/strict');
const elements = new Map();
globalThis.document = {getElementById: id => {if(!elements.has(id)) elements.set(id,{textContent:'',appendChild(){}}); return elements.get(id);}};
globalThis.location = {search:'?job_id=selected-job'};
const navigation = [];
globalThis.history = {replaceState: (_state,_title,url) => navigation.push(url)};
const selected = [];
globalThis.window = {setTimeout: resolve => resolve(), KyvernRunReview: {create: options => {
  selected.push(options.runId); return {refresh:async()=>{}};
}}};
let jobReads = 0;
globalThis.fetch = async url => {
  if (url === '/ui/session') return {ok:true,json:async()=>({role:'operator'})};
  if (url === '/reviewer/runs?limit=100') return {ok:true,json:async()=>({items:[]})};
  assert.equal(url, '/runs/jobs/selected-job');
  jobReads++;
  if (OUTCOME === 'forbidden') return {ok:false,status:403};
  return {ok:true,json:async()=>OUTCOME === 'failed'
    ? {status:'failed',failure_reason:'private diagnostic must remain hidden'}
    : jobReads === 1 ? {status:'queued'} : {status:'running',strategyos_run_id:'assigned-run'}};
};
'''.replace('OUTCOME', json.dumps(outcome))
    checks = r'''
done.then(()=>{
  if (OUTCOME === 'ready') {
    assert.deepEqual(selected,['assigned-run']);
    assert.deepEqual(navigation,['/runs/review?review_run=assigned-run']);
    assert.equal(jobReads,2);
  } else {
    assert.deepEqual(selected,[]); assert.deepEqual(navigation,[]);
    assert(!elements.get('review-queue-status').textContent.includes('private diagnostic'));
  }
}).catch(error=>{console.error(error);process.exitCode=1;});
'''.replace('OUTCOME', json.dumps(outcome))
    result = subprocess.run([node, '-e', harness + '\nconst done = ' + source + '\n' + checks], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
