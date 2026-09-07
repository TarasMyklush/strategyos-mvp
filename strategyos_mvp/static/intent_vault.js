/* Governed Intent Vault. All displayed business values come from authenticated APIs. */
(function () {
  'use strict';
  var base = '/api/intent/dimensional';
  var state = { plans: [], actuals: [], record: null, grant: null, next: null, busy: false, permissions: {} };
  var $ = function (id) { return document.getElementById(id); };
  function node(tag, text) { var n = document.createElement(tag); if (text !== undefined) n.textContent = String(text); return n; }
  function show(id, visible) { $(id).hidden = !visible; }
  function message(text) { $('vault-message').textContent = text; }
  function text(value) { return value === null || value === undefined ? 'Missing' : String(value); }
  function label(status) { return ({ on_plan: 'On plan', ahead: 'Ahead', behind: 'Behind', incomplete: 'Incomplete', missing: 'Missing', proposed: 'Proposed', ratified: 'Ratified' })[status] || status; }
  function dimensions(value) { return Object.keys(value).sort().map(function (k) { return k + ': ' + value[k]; }).join(' · '); }
  function planPath() { return '/plans/' + encodeURIComponent(state.record.plan_id) + '/versions/' + state.record.version; }
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
    state.record = null; state.grant = null;
    ['selected-plan', 'ratifier-panel', 'drift-panel', 'analysis-panel', 'grant-form', 'ratify-form'].forEach(function (id) { show(id, false); });
    ['plan-cells', 'analysis-cells', 'analysis-rollups', 'analysis-findings', 'plan-metadata'].forEach(function (id) { $(id).replaceChildren(); });
    $('reviewed').checked = false; $('review-note').value = ''; $('grant-status').textContent = '';
  }
  function options() {
    var previous = $('plan-select').value, actual = $('actual-select').value;
    $('plan-select').replaceChildren(new Option('Choose a version', ''));
    state.plans.forEach(function (p) { $('plan-select').add(new Option(p.plan_id + ' · v' + p.version + ' · ' + label(p.governance_status), p.plan_id + ':' + p.version)); });
    $('plan-select').value = previous;
    $('actual-select').replaceChildren(new Option('Choose actuals', ''));
    state.actuals.forEach(function (a) { $('actual-select').add(new Option(a.revision + ' · ' + a.period.start + ' to ' + a.period.end, a.revision)); });
    $('actual-select').value = actual;
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
    show('selected-plan', true); show('drift-panel', true); show('ratify-form', record.permissions.can_ratify);
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
  }
  function bind(id, work) { $(id).addEventListener('submit', function (event) { event.preventDefault(); action(work); }); }
  $('plan-select').addEventListener('change', function () { action(loadPlan); });
  $('actual-select').addEventListener('change', function () { show('analysis-panel', false); controls(); });
  $('as-of').addEventListener('change', function () { show('analysis-panel', false); });
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
