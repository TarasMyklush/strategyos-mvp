import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_governed_layout_retains_all_facts_comparisons_and_escapes_source_text():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the browser renderer proof')
    source = Path('strategyos_mvp/static/executive.js').read_text()
    function = source[source.index('  function renderGovernedFactAnswer('):source.index('  function renderAssistantStructuredAnswer(')]
    fixture = {'fact_cells': [{'display_name': '<script>Measure</script>', 'display_value': 'SAR 12345678901234567890.01',
        'scope_text': 'Same scope', 'claim_kind': kind, 'source_commentary': '<img src=x> Source comment'}
        for kind in ['actual', 'plan']], 'calculated_comparisons': [{'display_text': 'Difference one'}, {'display_text': 'Difference two'}]}
    code = r'''
const assert = require('node:assert/strict');
const safeArray = value => Array.isArray(value) ? value : [];
const escapeHtml = value => String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
''' + function + '\nconst fixture = ' + json.dumps(fixture) + r''';
const html = renderGovernedFactAnswer('Complete answer', fixture);
assert(html.includes('12345678901234567890.01'));
assert(html.includes('Difference one') && html.includes('Difference two'));
assert(!html.includes('<script>') && !html.includes('<img'));
assert.equal((html.match(/Source comment/g) || []).length, 1);
assert(!html.includes('More context'));
fixture.answer_caveat = 'Related context only <script>unsafe()</script>';
const partial = renderGovernedFactAnswer('', fixture);
assert(partial.includes('Related context only &lt;script&gt;'));
assert(partial.indexOf('Related context only') < partial.indexOf('<table'));
assert(partial.includes('12345678901234567890.01') && !partial.includes('<script>'));
fixture.fact_cells = Array.from({length: 85}, (_,i) => ({...fixture.fact_cells[0], display_value: 'Exact '+i}));
const complete = renderGovernedFactAnswer('', fixture);
assert(complete.includes('Exact 84'));
assert.equal((complete.match(/<tr>/g) || []).length, 86);
const old = renderGovernedFactAnswer('First\nline\n\nLast comparison', {fact_cells: []});
assert(old.includes('Last comparison') && old.includes('assistant-fact-paragraph'));
'''
    result = subprocess.run([node, '-e', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
