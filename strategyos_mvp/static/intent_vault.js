/* Governed Intent Vault. All displayed business values come from authenticated APIs. */
(function () {
  'use strict';
  var base = '/api/intent/dimensional';
  var state = { plans: [], actuals: [], record: null, grant: null, history: null, next: null, busy: false, permissions: {} };
  var $ = function (id) { return document.getElementById(id); };
  function node(tag, text) { var n = document.createElement(tag); if (text !== undefined) n.textContent = String(text); return n; }
  function show(id, visible) { $(id).hidden = !visible; }
  function message(text) { $('vault-message').textContent = text; }
  function text(value) { return value === null || value === undefined ? 'Missing' : String(value); }
  function label(status) { return ({ on_plan: 'On plan', ahead: 'Ahead', behind: 'Behind', incomplete: 'Incomplete', missing: 'Missing', proposed: 'Proposed', ratified: 'Ratified' })[status] || status; }
  function dimensions(value) { return Object.keys(value).sort().map(function (k) { return k + ': ' + value[k]; }).join(' · '); }
  function planPath() { return '/plans/' + encodeURIComponent(state.record.plan_id) + '/versions/' + state.record.version; }
  function safeId(value) { return String(value).toLowerCase().replace(/[^a-z0-9_.-]+/g, '-').replace(/^-|-$/g, '').slice(0, 120) || 'cell'; }
  function seedDecomposition() {
    if (!state.record) return;
    var cell = state.record.payload.cells.find(function (item) { return item.id === $('decomposition-cell').value; });
    var dimension = $('decomposition-dimension').value;
    if (!cell || !dimension) return;
    var original = cell.dimensions[dimension], prefix = safeId(cell.id);
    $('decomposition-rows').value = JSON.stringify([
      { cell_id: prefix + '-' + safeId(original), member: original, weight: '1', owner: cell.owner, tolerance: String(cell.tolerance), basis: cell.source },
      { cell_id: prefix + '-new-member', member: original + '-new', weight: '1', owner: cell.owner, tolerance: String(cell.tolerance), basis: cell.source }
    ], null, 2);
    resetHistory();
  }
  function resetHistory() {
    state.history = null;
    if ($('history-allocations')) $('history-allocations').replaceChildren();
    show('history-allocations', false); show('history-create', false);
    if ($('history-status')) $('history-status').textContent = 'Choose a prior snapshot to inspect the recorded mix.';
  }
  function table(target, headings, rows) {
    var t = node('table'), h = node('thead'), tr = node('tr'), b = node('tbody');
    headings.forEach(function (heading) { var th = node('th', heading); th.scope = 'col'; tr.appendChild(th); });
    h.appendChild(tr); t.appendChild(h);
    rows.forEach(function (row) { var r = node('tr'); row.forEach(function (value) { var cell = node('td'); if (value instanceof Node) cell.appendChild(value); else cell.textContent = text(value); r.appendChild(cell); }); b.appendChild(r); });
    t.appendChild(b); $(target).replaceChildren(t);
  }
  function link(title, path) { var a = node('a', title); a.href = base + path; return a; }
  async function request(path, body, method) {
    var options = { credentials: 'same-origin', cache: 'no-store' };
    if (body !== undefined) { options.method = method || 'POST'; options.headers = { 'Content-Type': 'application/json' }; options.body = JSON.stringify(body); }
    var response = await fetch(base + path, options);
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) { resetSelection(); show('vault-content', false); state.plans = []; state.actuals = []; state.permissions = {}; }
      if (response.status === 401) show('vault-login', true);
      var detail = typeof data.detail === 'string' ? data.detail : 'Check the required fields and numeric formats.';
      if (response.status === 503) detail = 'The Intent Vault is unavailable. Ask the operator to check its database setup.';
      if (response.status === 401) detail = 'Sign in to open your Intent Vault.';
      throw new Error(detail);
    }
    return data;
  }
  function controls() {
    document.querySelectorAll('button, select, input, textarea').forEach(function (control) { control.disabled = state.busy; });
    $('analyse-button').disabled = state.busy || !state.record || state.record.governance_status !== 'ratified' || !$('actual-select').value;
    $('ratify-button').disabled = state.busy || !state.record || !state.record.permissions.can_ratify || !$('reviewed').checked || $('review-note').value.trim().length < 20;
  }
  async function action(work) {
    if (state.busy) return;
    state.busy = true; show('vault-error', false); controls();
    try { await work(); }
    catch (error) { $('vault-error').textContent = error.message || 'The request could not be completed.'; show('vault-error', true); message('The requested action could not be completed.'); }
    finally { state.busy = false; controls(); }
  }
  function resetSelection() {
    state.record = null; state.grant = null; resetHistory();
    window.dispatchEvent(new CustomEvent('kyvern-analysis', { detail: null }));
    ['selected-plan', 'ratifier-panel', 'decomposition-panel', 'decomposition-lineage', 'drift-panel', 'analysis-panel', 'grant-form', 'ratify-form'].forEach(function (id) { show(id, false); });
    ['plan-cells', 'decomposition-allocations', 'analysis-cells', 'analysis-rollups', 'analysis-findings', 'plan-metadata'].forEach(function (id) { $(id).replaceChildren(); });
    $('reviewed').checked = false; $('review-note').value = ''; $('grant-status').textContent = '';
  }
  function options() {
    var previous = $('plan-select').value, actual = $('actual-select').value, history = $('history-actual').value;
    $('plan-select').replaceChildren(new Option('Choose a version', ''));
    state.plans.forEach(function (p) { $('plan-select').add(new Option(p.plan_id + ' · v' + p.version + ' · ' + label(p.governance_status), p.plan_id + ':' + p.version)); });
    $('plan-select').value = previous;
    $('actual-select').replaceChildren(new Option('Choose actuals', ''));
    state.actuals.forEach(function (a) { $('actual-select').add(new Option(a.revision + ' · ' + a.period.start + ' to ' + a.period.end, a.revision)); });
    $('actual-select').value = actual;
    $('history-actual').replaceChildren(new Option('Choose prior actuals', ''));
    state.actuals.forEach(function (a) { $('history-actual').add(new Option(a.revision + ' · ' + a.period.start + ' to ' + a.period.end, a.revision)); });
    $('history-actual').value = history;
    show('empty-plans', !state.plans.length); show('more', state.next !== null);
  }
  async function loadCatalog(append) {
    var data = await request('/catalog?offset=' + (append ? state.next : 0));
    function merge(old, incoming, key) { var map = new Map(); old.concat(incoming).forEach(function (item) { map.set(key(item), item); }); return Array.from(map.values()); }
    state.plans = merge(append ? state.plans : [], data.plans, function (p) { return p.plan_id + ':' + p.version; });
    state.actuals = merge(append ? state.actuals : [], data.actuals, function (a) { return a.revision; });
    state.permissions = data.permissions; state.next = data.next_offset;
    if (!$('as-of').value) $('as-of').value = data.today;
    $('as-of').max = data.today;
    options(); show('vault-content', true); show('vault-login', false); show('import-panel', data.permissions.can_import);
    message(state.plans.length ? 'Select a version to review its targets and approval record.' : 'No dimensional plans are available yet.');
  }
  async function loadPlan() {
    resetSelection();
    var choice = state.plans.find(function (p) { return p.plan_id + ':' + p.version === $('plan-select').value; });
    if (!choice) return;
    state.record = await request('/plans/' + encodeURIComponent(choice.plan_id) + '/versions/' + choice.version);
    var record = state.record, plan = record.payload;
    $('plan-title').textContent = record.plan_id + ' · Version ' + record.version;
    $('plan-metadata').replaceChildren(node('p', label(record.governance_status)), node('p', plan.period.start + ' to ' + plan.period.end), node('p', 'Imported by ' + record.imported_by));
    $('approval-note').textContent = record.ratification ? 'Ratified by ' + record.ratification.approved_by + ' on ' + record.ratification.approved_at.slice(0, 10) + '. ' + record.ratification.note : 'This is a proposal. A separately authorized reviewer must ratify it before drift can be calculated.';
    table('plan-cells', ['Cell / dimensions', 'Metric', 'Owner', 'Target', 'Tolerance', 'Evidence'], plan.cells.map(function (c) {
      return [c.id + ' · ' + dimensions(c.dimensions), c.metric, c.owner, c.target + ' ' + plan.metrics[c.metric].unit, c.tolerance,
              link(c.source.locator, planPath() + '/evidence?cell_id=' + encodeURIComponent(c.id))];
    }));
    if (plan.derivation) {
      var d = plan.derivation;
      var historical = d.engine_version === 'history-adjusted-allocation.v1';
      $('decomposition-summary').textContent = 'Created from ' + d.parent_plan_id + ' v' + d.parent_version + ', cell ' + d.parent_cell_id + ', split by ' + d.split_dimension + '. Engine ' + d.engine_version + '; remainder: ' + d.remainder_rule + '. Parent fingerprint: ' + d.parent_digest + '.' + (historical ? ' Historical actuals: ' + d.historical_actual_revision + ' (' + d.historical_actual_digest + ').' : '');
      table('decomposition-allocations', historical ? ['Result cell', 'Member', 'Historical', 'Adjustment', 'Effective weight', 'Owner / tolerance', 'Historical evidence'] : ['Result cell', 'Member', 'Weight', 'Owner / tolerance', 'Evidence'], d.allocations.map(function (a) {
        return historical ? [a.cell_id, a.member, a.historical_value, a.adjustment_percent + '%', a.effective_weight, a.owner + ' / ' + a.tolerance, a.basis.locator + ' · SHA-256 ' + a.basis.sha256] : [a.cell_id, a.member, a.weight, a.owner + ' / ' + a.tolerance, a.basis.locator + ' · SHA-256 ' + a.basis.sha256];
      }));
      show('decomposition-lineage', true);
    }
    $('decomposition-cell').replaceChildren();
    plan.cells.forEach(function (c) { $('decomposition-cell').add(new Option(c.id + ' · ' + c.metric + ' · ' + c.target, c.id)); });
    $('decomposition-dimension').replaceChildren();
    Object.keys(plan.dimensions).sort().forEach(function (d) { $('decomposition-dimension').add(new Option(d, d)); });
    seedDecomposition();
    show('selected-plan', true); show('drift-panel', true); show('ratify-form', record.permissions.can_ratify);
    show('decomposition-panel', record.governance_status === 'ratified' && state.permissions.can_import);
    show('ratifier-panel', state.permissions.can_manage_ratifiers);
    message('Loaded version ' + record.version + '.');
  }
  function renderAnalysis(result) {
    $('analysis-context').textContent = result.plan_id + ' · Version ' + result.plan_version + ' · Actuals ' + result.actual_revision + ' · As of ' + result.as_of;
    var findings = $('analysis-findings'); findings.replaceChildren();
    result.rollups.forEach(function (r) {
      if (r.offset_detected) findings.appendChild(node('p', r.metric + ': the total is ' + label(r.status).toLowerCase() + ', but its composition differs. Behind: ' + r.behind_cells.join(', ') + '. Ahead: ' + r.ahead_cells.join(', ') + '.'));
      if (r.unplanned_actuals.length) findings.appendChild(node('p', r.metric + ': ' + r.unplanned_actuals.length + ' actual cells have no plan target; the rollup remains incomplete.'));
    });
    table('analysis-rollups', ['Metric', 'Target', 'Actual', 'Variance', 'Status', 'Coverage'], result.rollups.map(function (r) {
      return [r.metric + ' (' + r.unit + ')', r.target, r.actual, r.variance, label(r.status), r.measured_cells + ' / ' + r.planned_cells];
    }));
    table('analysis-cells', ['Cell / dimensions', 'Owner', 'Target', 'Actual', 'Variance', 'Status', 'Evidence'], result.cells.map(function (c) {
      var refs = node('div');
      refs.appendChild(link('Plan', '/analyses/' + result.analysis_hash + '/evidence?side=plan&cell_id=' + encodeURIComponent(c.cell_id)));
      if (c.actual_source) { refs.appendChild(node('span', ' · ')); refs.appendChild(link('Actuals', '/analyses/' + result.analysis_hash + '/evidence?side=actuals&cell_id=' + encodeURIComponent(c.cell_id))); }
      return [c.cell_id + ' · ' + dimensions(c.dimensions), c.owner, c.target + ' ' + c.unit, c.actual, c.variance, label(c.status), refs];
    }));
    var url = new URL(window.location.href); url.search = ''; url.searchParams.set('analysis', result.analysis_hash);
    $('saved-link').href = url.pathname + url.search;
    show('analysis-panel', true);
    window.dispatchEvent(new CustomEvent('kyvern-analysis', { detail: result.analysis_hash }));
  }
  function bind(id, work) { $(id).addEventListener('submit', function (event) { event.preventDefault(); action(work); }); }
  $('plan-select').addEventListener('change', function () { action(loadPlan); });
  $('actual-select').addEventListener('change', function () { show('analysis-panel', false); window.dispatchEvent(new CustomEvent('kyvern-analysis', { detail: null })); controls(); });
  $('decomposition-cell').addEventListener('change', seedDecomposition);
  $('decomposition-dimension').addEventListener('change', seedDecomposition);
  $('history-actual').addEventListener('change', resetHistory);
  $('as-of').addEventListener('change', function () { show('analysis-panel', false); window.dispatchEvent(new CustomEvent('kyvern-analysis', { detail: null })); });
  $('review-note').addEventListener('input', controls); $('reviewed').addEventListener('change', controls);
  $('refresh').addEventListener('click', function () { action(async function () { resetSelection(); await loadCatalog(false); await loadPlan(); }); });
  $('more').addEventListener('click', function () { action(function () { return loadCatalog(true); }); });
  bind('ratify-form', async function () {
    await request(planPath() + '/ratify', { expected_digest: state.record.digest, note: $('review-note').value.trim() });
    await loadCatalog(false); await loadPlan(); message('This plan version has been ratified.');
  });
  bind('analysis-form', async function () {
    var result = await request('/analyses', { plan_id: state.record.plan_id, plan_version: state.record.version, actual_revision: $('actual-select').value, as_of: $('as-of').value });
    renderAnalysis(result); message('Drift calculated and saved.');
  });
  bind('decomposition-form', async function () {
    var allocations = JSON.parse($('decomposition-rows').value);
    if (!Array.isArray(allocations)) throw new Error('Allocation rows must be a JSON array.');
    var result = await request(planPath() + '/decompose', {
      parent_digest: state.record.digest,
      parent_cell_id: $('decomposition-cell').value,
      split_dimension: $('decomposition-dimension').value,
      decimal_places: Number($('decomposition-precision').value),
      allocations: allocations
    });
    await loadCatalog(false);
    $('plan-select').value = result.plan_id + ':' + result.version;
    await loadPlan();
    message('Decomposition proposal created as version ' + result.version + '. An independently authorized reviewer must ratify it.');
  });
  $('history-load').addEventListener('click', function () { action(async function () {
    if (!$('history-actual').value) throw new Error('Choose a prior actual snapshot.');
    var query = '?parent_cell_id=' + encodeURIComponent($('decomposition-cell').value) +
      '&split_dimension=' + encodeURIComponent($('decomposition-dimension').value) +
      '&actual_revision=' + encodeURIComponent($('history-actual').value);
    state.history = await request(planPath() + '/history-candidates' + query);
    var rows = state.history.candidates.map(function (candidate) {
      var cell = safeId($('decomposition-cell').value + '-' + candidate.member);
      function input(field, value, type) { var n = document.createElement('input'); n.dataset.field = field; n.value = value; n.type = type || 'text'; n.required = true; return n; }
      var adjustment = input('adjustment_percent', '0', 'number'); adjustment.step = 'any'; adjustment.min = '-99.999999999999';
      var tolerance = input('tolerance', String(state.record.payload.cells.find(function (item) { return item.id === $('decomposition-cell').value; }).tolerance), 'number'); tolerance.step = 'any'; tolerance.min = '0';
      return [input('cell_id', cell), candidate.member, candidate.historical_value, adjustment,
              input('owner', state.record.payload.cells.find(function (item) { return item.id === $('decomposition-cell').value; }).owner), tolerance,
              candidate.source.locator, candidate.readiness];
    });
    table('history-allocations', ['Result cell', 'Member', 'Historical value', 'Adjustment %', 'Owner', 'Tolerance', 'Evidence', 'Readiness'], rows);
    show('history-allocations', true); show('history-create', state.history.readiness === 'ready');
    $('history-status').textContent = state.history.readiness === 'ready' ? 'Historical mix is complete. Adjustments are disclosed and applied before exact allocation.' : 'This snapshot is blocked because at least one matched value is missing or nonpositive.';
  }); });
  bind('history-form', async function () {
    if (!state.history || state.history.readiness !== 'ready') throw new Error('Load a complete historical mix first.');
    var rows = Array.from($('history-allocations').querySelectorAll('tbody tr'));
    var allocations = rows.map(function (row, index) {
      function value(field) { return row.querySelector('[data-field="' + field + '"]').value.trim(); }
      return { cell_id: value('cell_id'), member: state.history.candidates[index].member,
        owner: value('owner'), tolerance: value('tolerance'), adjustment_percent: value('adjustment_percent') };
    });
    var result = await request(planPath() + '/decompose-from-history', {
      parent_digest: state.history.parent_digest, parent_cell_id: state.history.parent_cell_id,
      split_dimension: state.history.split_dimension, historical_actual_revision: state.history.historical_actual_revision,
      decimal_places: Number($('decomposition-precision').value), allocations: allocations
    });
    await loadCatalog(false); $('plan-select').value = result.plan_id + ':' + result.version; await loadPlan();
    message('History-based proposal created as version ' + result.version + '. An independently authorized reviewer must ratify it.');
  });
  $('ratifier-subject').addEventListener('input', function () { state.grant = null; show('grant-form', false); });
  bind('grant-read-form', async function () {
    state.grant = await request('/plans/' + encodeURIComponent(state.record.plan_id) + '/ratifier?subject=' + encodeURIComponent($('ratifier-subject').value.trim()));
    $('grant-enabled').checked = state.grant.enabled; $('grant-status').textContent = state.grant.enabled ? 'This identity can ratify this plan.' : 'This identity cannot ratify this plan.'; show('grant-form', true);
  });
  bind('grant-form', async function () {
    await request('/plans/' + encodeURIComponent(state.record.plan_id) + '/ratifier', { subject: state.grant.subject, enabled: $('grant-enabled').checked, expected_revision: state.grant.revision }, 'PUT');
    state.grant = null; show('grant-form', false); message('Ratification permission updated.');
  });
  async function fileJSON(id) {
    var file = $(id).files[0];
    if (!file || file.size > 2000000) throw new Error('Choose a JSON file smaller than 2 MB.');
    var value = JSON.parse(await file.text());
    function check(item) { if (typeof item === 'number' && !Number.isSafeInteger(item)) throw new Error('Use decimal strings for amounts and safe integers for version numbers.'); if (item && typeof item === 'object') Object.values(item).forEach(check); }
    check(value); return value;
  }
  bind('plan-import-form', async function () {
    var result = await request('/plans', { source_pack_id: $('plan-pack').value.trim(), plan: await fileJSON('plan-file') });
    await loadCatalog(false); $('plan-select').value = result.plan_id + ':' + result.version; await loadPlan(); message('Plan proposal imported. It has not been ratified.');
  });
  bind('actual-import-form', async function () {
    var result = await request('/actuals', { source_pack_id: $('actual-pack').value.trim(), actuals: await fileJSON('actual-file') });
    await loadCatalog(false); await loadPlan(); $('actual-select').value = result.revision; message('Actual snapshot imported.');
  });
  action(async function () {
    await loadCatalog(false);
    var hash = new URL(window.location.href).searchParams.get('analysis');
    if (hash && /^[a-f0-9]{64}$/.test(hash)) { renderAnalysis(await request('/analyses/' + hash)); message('Opened the saved analysis.'); }
  });
})();
