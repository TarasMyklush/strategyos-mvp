/* Guided, source-bound Strategic Advisor setup; no configuration JSON is exposed. */
(function () {
  'use strict';
  var base = '/api/intent/dimensional';
  var plan = null, actuals = [], permissions = {}, preview = null, record = null, busy = false;
  var $ = function (id) { return document.getElementById(id); };
  function show(id, visible) { $(id).hidden = !visible; }
  function node(tag, value) { var n = document.createElement(tag); if (value !== undefined) n.textContent = String(value); return n; }
  function safe(value) { return String(value).toLowerCase().replace(/[^a-z0-9_.-]+/g, '-').replace(/^-|-$/g, '').slice(0, 120) || 'cell'; }
  async function request(path, body) {
    var options = { credentials: 'same-origin', cache: 'no-store' };
    if (body !== undefined) { options.method = 'POST'; options.headers = { 'Content-Type': 'application/json' }; options.body = JSON.stringify(body); }
    var response = await fetch(base + path, options), data = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The configuration request failed.');
    return data;
  }
  function controls() { $('advisor-console').querySelectorAll('button,input,textarea,select').forEach(function (item) { item.disabled = busy; }); }
  async function action(work) { if (busy) return; busy = true; controls(); try { await work(); } catch (error) { $('advisor-readiness').textContent = error.message; } finally { busy = false; controls(); } }
  function table(target, headings, rows) {
    var t = node('table'), head = node('thead'), hr = node('tr'), body = node('tbody');
    headings.forEach(function (value) { var th = node('th', value); th.scope = 'col'; hr.appendChild(th); }); head.appendChild(hr); t.appendChild(head);
    rows.forEach(function (values) { var tr = node('tr'); values.forEach(function (value) { var td = node('td'); if (value instanceof Node) td.appendChild(value); else td.textContent = value === null ? 'Missing' : String(value); tr.appendChild(td); }); body.appendChild(tr); });
    t.appendChild(body); $(target).replaceChildren(t);
  }
  function input(field, value, type) { var n = document.createElement('input'); n.dataset.field = field; n.value = value; n.type = type || 'text'; n.required = true; return n; }
  function resetPreview() { preview = null; $('advisor-allocations').replaceChildren(); $('advisor-labels').replaceChildren(); show('advisor-allocations', false); show('advisor-labels', false); show('advisor-save', false); $('advisor-readiness').textContent = 'Mappings have not been checked.'; }
  function planPath() { return '/plans/' + encodeURIComponent(plan.plan_id) + '/versions/' + plan.version; }
  function populatePlan() {
    resetPreview(); show('advisor-form', Boolean(plan && plan.governance_status === 'ratified' && permissions.can_import));
    if (!plan) { $('advisor-source-binding').textContent = 'Select a ratified plan above to begin a client setup.'; return; }
    $('advisor-source-binding').textContent = plan.governance_status === 'ratified' ? 'Plan source is fixed by ' + plan.source_pack_id + ' · SHA-256 ' + plan.digest + '. Choose a prior snapshot; its source is also read only.' : 'This plan is still proposed. Ratify it before configuring a client.';
    $('advisor-cell').replaceChildren(); plan.payload.cells.forEach(function (cell) { $('advisor-cell').add(new Option(cell.id + ' · ' + cell.metric + ' · ' + cell.target, cell.id)); });
    $('advisor-dimension').replaceChildren(); Object.keys(plan.payload.dimensions).sort().forEach(function (name) { $('advisor-dimension').add(new Option(name, name)); });
    $('advisor-metric-en').value = plan.payload.cells[0].metric; $('advisor-dimension-en').value = $('advisor-dimension').value;
  }
  function populateActuals() {
    var selected = $('advisor-actual').value; $('advisor-actual').replaceChildren(new Option('Choose prior actuals', ''));
    actuals.forEach(function (item) { $('advisor-actual').add(new Option(item.revision + ' · ' + item.period.start + ' to ' + item.period.end, item.revision)); }); $('advisor-actual').value = selected;
  }
  async function configurations() {
    var result = await request('/advisor/configurations');
    $('advisor-select').replaceChildren(new Option('Choose a configuration', ''));
    result.configurations.forEach(function (item) { $('advisor-select').add(new Option(item.config_id + ' · v' + item.version + (item.published ? ' · Published' : item.approved ? ' · Approved' : ' · Ready'), item.config_id + ':' + item.version)); });
  }
  window.addEventListener('kyvern-catalog', function (event) { actuals = event.detail.actuals || []; permissions = event.detail.permissions || {}; populateActuals(); populatePlan(); });
  window.addEventListener('kyvern-plan', function (event) { plan = event.detail; populatePlan(); });
  ['advisor-cell','advisor-dimension','advisor-actual'].forEach(function (id) { $(id).addEventListener('change', function () {
    resetPreview();
    if (plan && id === 'advisor-cell') { var selected = plan.payload.cells.find(function (cell) { return cell.id === $('advisor-cell').value; }); if (selected) $('advisor-metric-en').value = selected.metric; }
    if (id === 'advisor-dimension') $('advisor-dimension-en').value = $('advisor-dimension').value;
  }); });
  $('advisor-refresh').addEventListener('click', function () { action(configurations); });
  $('advisor-map').addEventListener('click', function () { action(async function () {
    if (!$('advisor-actual').value) throw new Error('Choose a completed prior actual snapshot.');
    var query = '?parent_cell_id=' + encodeURIComponent($('advisor-cell').value) + '&split_dimension=' + encodeURIComponent($('advisor-dimension').value) + '&actual_revision=' + encodeURIComponent($('advisor-actual').value);
    preview = await request(planPath() + '/history-candidates' + query);
    var parent = plan.payload.cells.find(function (cell) { return cell.id === $('advisor-cell').value; });
    table('advisor-allocations', ['Result cell', 'Member', 'Historical', 'Adjustment %', 'Owner', 'Tolerance', 'Label EN', 'Label AR', 'Evidence'], preview.candidates.map(function (item) {
      var adjustment = input('adjustment_percent', '0', 'number'); adjustment.step = 'any'; adjustment.min = '-99.999999999999';
      var tolerance = input('tolerance', String(parent.tolerance), 'number'); tolerance.step = 'any'; tolerance.min = '0';
      return [input('cell_id', safe(parent.id + '-' + item.member)), item.member, item.historical_value, adjustment,
        input('owner', parent.owner), tolerance, input('label_en', item.member), input('label_ar', item.member), item.source.locator];
    }));
    var covered = new Set([parent.metric, preview.split_dimension].concat(preview.candidates.map(function (item) { return item.member; })));
    var terms = new Set(Object.keys(plan.payload.dimensions));
    plan.payload.cells.forEach(function (cell) { Object.values(cell.dimensions).forEach(function (value) { terms.add(value); }); });
    preview.candidates.forEach(function (item) { terms.add(item.member); });
    var additional = Array.from(terms).filter(function (term) { return !covered.has(term); }).sort();
    table('advisor-labels', ['Additional board term', 'English label', 'Arabic label'], additional.map(function (term) {
      var en = input('label_en', term), ar = input('label_ar', term); en.dataset.term = term; ar.dataset.term = term; return [term, en, ar];
    }));
    show('advisor-allocations', true); show('advisor-labels', additional.length > 0); show('advisor-save', preview.readiness === 'ready');
    $('advisor-readiness').textContent = preview.readiness === 'ready' ? 'Ready: plan ratified; both source packs authorized; history complete; add owners, tolerances and both board languages, then save.' : 'Blocked: the selected historical mix is incomplete or nonpositive.';
  }); });
  $('advisor-form').addEventListener('submit', function (event) { event.preventDefault(); action(async function () {
    if (!preview || preview.readiness !== 'ready') throw new Error('Load a ready source-bound mapping first.');
    var rows = Array.from($('advisor-allocations').querySelectorAll('tbody tr'));
    function field(row, name) { return row.querySelector('[data-field="' + name + '"]').value.trim(); }
    var parent = plan.payload.cells.find(function (cell) { return cell.id === preview.parent_cell_id; });
    var additionalLabels = {};
    Array.from($('advisor-labels').querySelectorAll('tbody tr')).forEach(function (row) {
      var en = row.querySelector('[data-field="label_en"]'), ar = row.querySelector('[data-field="label_ar"]');
      additionalLabels[en.dataset.term] = { en: en.value.trim(), ar: ar.value.trim() };
    });
    var body = { schema_version: 1, config_id: $('advisor-id').value.trim(), version: Number($('advisor-version').value),
      executive_sponsor: $('advisor-sponsor').value.trim(), objective: $('advisor-objective').value.trim(),
      plan_id: plan.plan_id, plan_version: plan.version, plan_digest: plan.digest,
      parent_cell_id: preview.parent_cell_id, split_dimension: preview.split_dimension,
      historical_actual_revision: preview.historical_actual_revision, decimal_places: Number($('advisor-precision').value),
      client: { en: $('advisor-client-en').value.trim(), ar: $('advisor-client-ar').value.trim() },
      board_title: { en: $('advisor-title-en').value.trim(), ar: $('advisor-title-ar').value.trim() },
      metric_label: { en: $('advisor-metric-en').value.trim(), ar: $('advisor-metric-ar').value.trim() },
      dimension_label: { en: $('advisor-dimension-en').value.trim(), ar: $('advisor-dimension-ar').value.trim() },
      additional_labels: additionalLabels,
      allocations: rows.map(function (row, index) { return { cell_id: field(row, 'cell_id'), member: preview.candidates[index].member,
        owner: field(row, 'owner'), tolerance: field(row, 'tolerance'), adjustment_percent: field(row, 'adjustment_percent'),
        label: { en: field(row, 'label_en'), ar: field(row, 'label_ar') } }; }) };
    record = await request('/advisor/configurations', body); await configurations(); $('advisor-select').value = record.config_id + ':' + record.version; render();
    $('advisor-readiness').textContent = 'Configuration saved and ready for independent approval.';
  }); });
  function render() {
    if (!record) return; var payload = record.payload;
    show('advisor-review', true); $('advisor-review-title').textContent = payload.config_id + ' · Version ' + payload.version;
    $('advisor-review-metadata').replaceChildren(node('p', record.readiness.status), node('p', record.approval ? 'Approved by ' + record.approval.approved_by : 'Approval pending'), node('p', record.publication ? 'Published as plan v' + record.publication.plan_version : 'Not published'), node('p', 'Sponsor: ' + payload.executive_sponsor));
    $('advisor-checks').textContent = Object.keys(record.readiness.checks).map(function (key) { return (record.readiness.checks[key] ? '✓ ' : '✕ ') + key.replace(/_/g, ' '); }).join(' · ');
    table('advisor-review-allocations', ['Cell', 'Member', 'Adjustment', 'Owner', 'Tolerance', 'EN / AR'], payload.allocations.map(function (item) { return [item.cell_id, item.member, item.adjustment_percent + '%', item.owner, item.tolerance, item.label.en + ' / ' + item.label.ar]; }));
    show('advisor-approve-form', record.permissions.can_approve); show('advisor-publish', record.permissions.can_publish); show('advisor-use-template', record.permissions.can_register_template);
  }
  $('advisor-load-saved').addEventListener('click', function () { action(async function () { var parts = $('advisor-select').value.split(':'); if (parts.length !== 2) throw new Error('Choose a saved configuration.'); record = await request('/advisor/configurations/' + encodeURIComponent(parts[0]) + '/versions/' + parts[1]); render(); }); });
  $('advisor-approve-form').addEventListener('submit', function (event) { event.preventDefault(); action(async function () { await request('/advisor/configurations/' + encodeURIComponent(record.config_id) + '/versions/' + record.version + '/approve', { expected_digest: record.digest, note: $('advisor-review-note').value.trim() }); record = await request('/advisor/configurations/' + encodeURIComponent(record.config_id) + '/versions/' + record.version); render(); await configurations(); }); });
  $('advisor-publish').addEventListener('click', function () { action(async function () { var publication = await request('/advisor/configurations/' + encodeURIComponent(record.config_id) + '/versions/' + record.version + '/publish', { expected_digest: record.digest }); record = await request('/advisor/configurations/' + encodeURIComponent(record.config_id) + '/versions/' + record.version); render(); await configurations(); $('advisor-readiness').textContent = 'Published as plan proposal v' + publication.plan_version + '. It now requires independent plan ratification.'; }); });
  $('advisor-use-template').addEventListener('click', function () { action(async function () { var registered = await request('/advisor/configurations/' + encodeURIComponent(record.config_id) + '/versions/' + record.version + '/board-template/register', {}); window.dispatchEvent(new CustomEvent('kyvern-board-template-registered', { detail: registered })); document.getElementById('board-pack').scrollIntoView({ behavior: 'smooth' }); $('advisor-readiness').textContent = 'Approved board template registered as ' + registered.template_id + ' v' + registered.version + '.'; }); });
  action(configurations);
})();
