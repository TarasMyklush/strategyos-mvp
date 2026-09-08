/* Guided whole-objective decomposition across configured tenant dimensions. */
(function () {
  'use strict';
  var record = null, busy = false;
  var $ = function (id) { return document.getElementById(id); };
  function node(tag, text) { var value = document.createElement(tag); if (text !== undefined) value.textContent = text; return value; }
  function field(label, name, value, type) {
    var wrapper = node('label'), input = node('input'); wrapper.className = 'vault-field';
    input.dataset.field = name; input.type = type || 'text'; input.value = value || ''; input.required = true;
    if (input.type === 'number') input.step = 'any'; else input.maxLength = 160;
    wrapper.append(node('span', label), input); return wrapper;
  }
  function selectField(label, name, options, selected) {
    var wrapper = node('label'), select = node('select'); wrapper.className = 'vault-field'; select.dataset.field = name;
    options.forEach(function (value) { select.add(new Option(value, value)); });
    if (selected) select.value = selected; select.required = true; wrapper.append(node('span', label), select); return wrapper;
  }
  function metric() { return $('objective-decomposition-metric').value; }
  function basisCells() { return record ? record.payload.cells.filter(function (cell) { return cell.metric === metric(); }) : []; }
  function addRow(seed) {
    seed = seed || {}; var card = node('section'), controls = node('div'), remove = node('button', 'Remove');
    card.className = 'pack-page objective-decomposition-row'; controls.className = 'vault-controls';
    controls.append(field('Cell ID', 'cell_id', seed.cell_id), field('Weight', 'weight', seed.weight || '1', 'number'),
      field('Accountable owner', 'owner', seed.owner), field('Tolerance', 'tolerance', seed.tolerance || '0', 'number'));
    Object.keys(record.payload.dimensions).sort().forEach(function (dimension) {
      controls.append(selectField(dimension, 'dimension:' + dimension, record.payload.dimensions[dimension],
        seed.dimensions && seed.dimensions[dimension]));
    });
    controls.append(selectField('Evidence basis cell', 'basis_cell_id', basisCells().map(function (cell) { return cell.id; }), seed.basis_cell_id));
    remove.type = 'button'; remove.className = 'secondary'; remove.addEventListener('click', function () { card.remove(); });
    card.append(controls, remove); $('objective-decomposition-rows').appendChild(card);
  }
  function resetRows() { $('objective-decomposition-rows').replaceChildren(); addRow(); addRow(); }
  function loadPlan(value) {
    record = value; if (!record) return;
    var metrics = Object.keys(record.payload.metrics).filter(function (name) {
      return record.payload.cells.some(function (cell) { return cell.metric === name; });
    }).sort();
    $('objective-decomposition-metric').replaceChildren(); metrics.forEach(function (name) { $('objective-decomposition-metric').add(new Option(name, name)); });
    var fieldset = $('objective-decomposition-dimensions'); fieldset.replaceChildren(node('legend', 'Dimensions to decompose'));
    Object.keys(record.payload.dimensions).sort().forEach(function (dimension) {
      var label = node('label'), input = node('input'); label.className = 'vault-check'; input.type = 'checkbox'; input.value = dimension;
      label.append(input, node('span', dimension)); fieldset.appendChild(label);
    });
    resetRows(); $('objective-decomposition-status').textContent = '';
  }
  function controls() { $('objective-decomposition-form').querySelectorAll('button,input,select').forEach(function (item) { item.disabled = busy; }); }
  async function submit() {
    var split = Array.from($('objective-decomposition-dimensions').querySelectorAll('input:checked')).map(function (item) { return item.value; });
    if (split.length < 2) throw new Error('Choose at least two dimensions to decompose.');
    var rows = Array.from($('objective-decomposition-rows').querySelectorAll('.objective-decomposition-row'));
    if (rows.length < 2) throw new Error('Add at least two accountable cells.');
    var allocations = rows.map(function (row) {
      function value(name) { return row.querySelector('[data-field="' + name + '"]').value.trim(); }
      var dimensions = {}; Object.keys(record.payload.dimensions).forEach(function (name) { dimensions[name] = value('dimension:' + name); });
      return { cell_id: value('cell_id'), dimensions: dimensions, weight: value('weight'), owner: value('owner'),
        tolerance: value('tolerance'), basis_cell_id: value('basis_cell_id') };
    });
    var path = '/api/intent/dimensional/plans/' + encodeURIComponent(record.plan_id) + '/versions/' + record.version + '/decompose-objective';
    var response = await fetch(path, { method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ parent_digest: record.digest, metric: metric(),
        split_dimensions: split, decimal_places: Number($('objective-decomposition-precision').value), allocations: allocations }) });
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The objective proposal could not be created.');
    window.dispatchEvent(new CustomEvent('kyvern-objective-created', { detail: data }));
    $('objective-decomposition-status').textContent = 'Objective proposal created as version ' + data.version + '.';
  }
  $('objective-decomposition-add').addEventListener('click', function () { if (record) addRow(); });
  $('objective-decomposition-metric').addEventListener('change', resetRows);
  $('objective-decomposition-form').addEventListener('submit', function (event) {
    event.preventDefault(); if (busy || !record) return; busy = true; controls();
    submit().catch(function (error) { $('objective-decomposition-status').textContent = error.message; })
      .finally(function () { busy = false; controls(); });
  });
  window.addEventListener('kyvern-plan', function (event) { loadPlan(event.detail); });
})();
