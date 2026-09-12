"""Exercise run-bound decisions and asynchronous controls with the actual controller."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('creation_fails', [False, True])
def test_selected_review_never_substitutes_latest_run_or_repeats_pending_action(creation_fails):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the browser controller regression')
    source = Path('strategyos_mvp/static/run-review.js').read_text()
    harness = r'''
const assert = require('node:assert/strict');
class Element {
  constructor(tag) {this.tag = tag; this.children = []; this.attrs = {}; this.events = {}; this.disabled = false;}
  appendChild(child) {this.children.push(child); return child;}
  replaceChildren() {this.children = [];}
  setAttribute(key, value) {this.attrs[key] = value;}
  addEventListener(key, fn) {this.events[key] = fn;}
  querySelectorAll(selector) {
    const tags = selector.split(',');
    return this.children.flatMap(child => [
      ...(tags.includes(child.tag) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) {
    const attr = selector.slice(1,-1);
    for (const child of this.children) {
      if (attr in child.attrs) return child;
      const match = child.querySelector(selector); if (match) return match;
    }
    return null;
  }
}
globalThis.document = {createElement: tag => new Element(tag)};
'''
    checks = r'''
(async () => {
  const element = new Element('section');
  const calls = [];
  let current = {run_id: 'selected', current_stage: 'awaiting_review', status: 'paused',
    approval: {approval_status: 'pending'}, latest_checkpoint: {state_json: {findings: [
      {title: '<script>source</script>', recoverable_sar: 12, citations: [{excerpt: 'Quoted evidence'}]}]}}};
  let release;
  let hold = false;
  const request = async (url, options = {}) => {
    calls.push([url, options.method || 'GET']);
    if (options.method === 'POST' && url.endsWith('/claim') && hold) await new Promise(resolve => {release = resolve;});
    if (url.endsWith('/approve')) current = {...current, approval: {approval_status: 'approved'}};
    if (url.endsWith('/resume')) current = {...current, status: 'completed', current_stage: 'writer', summary_json: {source_pack_id: 'original-source'}};
    if (url === '/runs') {
      assert.deepEqual(JSON.parse(options.body), {source_pack_id: 'original-source', sync_artifacts: true});
      await new Promise(resolve => {release = resolve;});
      if (CREATION_FAILS) throw new Error('Connection lost after submission');
      return {run_id: 'new-analysis'};
    }
    return current;
  };
  let rights = {review: true, operate: false};
  const ui = KyvernRunReview.create({element, runId: 'selected', request, permissions: () => rights});
  await ui.refresh();
  const buttons = () => element.querySelectorAll('button');
  const find = text => buttons().find(item => item.textContent === text);
  assert(find('Approve selected run'));
  assert(!find('Resume selected run'));
  assert(!find('Analyze this source again'));
  hold = true;
  const approval = find('Approve selected run').events.click();
  assert(buttons().every(item => item.disabled));
  await ui.refresh(); // Background polling cannot replace a pending decision.
  assert.equal(calls.filter(item => item[1] === 'GET').length, 1);
  release();
  await approval;
  assert.deepEqual(calls.filter(item => item[1] === 'POST'), [
    ['/reviewer/runs/selected/claim', 'POST'], ['/reviewer/runs/selected/approve', 'POST']]);
  assert(!find('Approve selected run'));
  rights = {review: false, operate: true};
  await ui.refresh();
  assert(find('Resume selected run'));
  await find('Resume selected run').events.click();
  assert.equal(calls.at(-2)[0], '/operator/runs/selected/resume');
  assert(!find('Resume selected run'));
  const newRun = find('Analyze this source again').events.click();
  assert(buttons().every(item => item.disabled));
  await find('Analyze this source again').events.click();
  assert.equal(calls.filter(([url]) => url === '/runs').length, 1);
  release();
  await newRun;
  assert(!find('Analyze this source again'));
  assert.equal(element.querySelectorAll('a').at(-1).href, CREATION_FAILS ? '/runs/review' : '/runs/review?review_run=new-analysis');
  current = {...current, run_id: 'different-latest'};
  await ui.refresh();
  assert(!find('Approve selected run') && !find('Resume selected run'));
  assert.match(element.querySelector('[data-review-status]').textContent, /does not match/);
  assert(calls.every(([url]) => !url.includes('latest')));
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    checks = checks.replace('CREATION_FAILS', json.dumps(creation_fails))
    result = subprocess.run([node, '-e', harness + '\n' + source + '\n' + checks], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_review_workspace_requires_explicit_authority_and_preserves_selected_route():
    from fastapi import HTTPException
    from strategyos_mvp import api
    with pytest.raises(HTTPException) as error:
        api.run_review_workspace({'authenticated': True, 'role': 'executive'})
    assert error.value.status_code == 403
    response = api.run_review_workspace({'authenticated': True, 'role': 'reviewer'})
    assert response.status_code == 200 and response.headers['cache-control'] == 'private, no-store'
    assert 'Selected run review' in response.body.decode()
    redirect = api.dashboard(lane='review', review_run='selected',
                             principal={'authenticated': True, 'role': 'reviewer'})
    assert redirect.headers['location'] == '/runs/review?review_run=selected'
