/* Client pack templates contain presentation settings only; all figures are server-bound. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var analysis = null, template = null, busy = false;
  function node(tag, value) { var n = document.createElement(tag); n.textContent = value; return n; }
  function save(blob, filename) {
    var url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = filename; a.click(); setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }
  function reset() { $('pack-preview').replaceChildren(); $('pack-status').textContent = ''; }
  async function action(work) {
    if (busy) return; busy = true;
    $('board-pack').querySelectorAll('button, input, select, textarea').forEach(function (n) { n.disabled = true; });
    try { await work(); } catch (e) { reset(); $('pack-status').textContent = e.message; }
    finally { busy = false; $('board-pack').querySelectorAll('button, input, select, textarea').forEach(function (n) { n.disabled = false; }); }
  }
  async function request(path, body, binary) {
    var options = { credentials: 'same-origin', cache: 'no-store' };
    if (body) { options.method = 'POST'; options.headers = { 'Content-Type': 'application/json' }; options.body = JSON.stringify(body); }
    var r = await fetch('/api/intent/dimensional' + path, options);
    if (!r.ok) { var error = await r.json().catch(function () { return {}; }); throw new Error(typeof error.detail === 'string' ? error.detail : 'Check the template format and required fields.'); }
    return binary ? r.blob() : r.json();
  }
  function body() { return { template: JSON.parse($('pack-template').value), language: $('pack-language').value }; }
  window.addEventListener('kyvern-analysis', function (event) {
    analysis = event.detail; reset(); $('board-pack').hidden = !analysis;
    if (analysis && !template) action(async function () { template = await request('/board-pack/template'); $('pack-template').value = JSON.stringify(template, null, 2); });
  });
  $('pack-template').addEventListener('input', reset); $('pack-language').addEventListener('change', reset);
  $('pack-load-template').addEventListener('change', function () { action(async function () {
    var file = $('pack-load-template').files[0];
    if (!file || file.size > 100000) throw new Error('Choose a template JSON file under 100 KB.');
    var value = JSON.parse(await file.text()); $('pack-template').value = JSON.stringify(value, null, 2); reset();
  }); });
  $('pack-save-template').addEventListener('click', function () { action(async function () {
    // Preview endpoint validates the artifact against the same export contract.
    await request('/analyses/' + analysis + '/board-pack', body());
    save(new Blob([JSON.stringify(body().template, null, 2)], { type: 'application/json' }), 'kyvern-board-template.json');
    $('pack-status').textContent = 'Template downloaded. Reuse it with another saved analysis.';
  }); });
  $('pack-preview-button').addEventListener('click', function () { action(async function () {
    var data = await request('/analyses/' + analysis + '/board-pack', body()); reset();
    data.pages.forEach(function (page) { var section = node('section', ''); section.className = 'pack-page';
      section.appendChild(node('h3', page.title));
      page.lines.forEach(function (line, i) { var p = node('p', '');
        if (page.links[String(i)]) { var a = node('a', line); a.href = page.links[String(i)]; p.appendChild(a); }
        else p.textContent = line;
        p.dir = 'auto'; section.appendChild(p);
      }); $('pack-preview').appendChild(section);
    });
    $('pack-status').textContent = data.pages.length + ' pages. Checked ' + data.checked_at + '. ' +
      (data.binding.warnings.length ? 'Newer records are available; review the warnings in the pack. ' : '') +
      (data.untranslated_labels.length ? 'Client labels remain in their source language. Add EN/AR translations in the template for: ' + data.untranslated_labels.join(', ') : '');
  }); });
  ['pdf', 'pptx'].forEach(function (format) { $('pack-' + format).addEventListener('click', function () { action(async function () {
    var blob = await request('/analyses/' + analysis + '/board-pack/' + format, body(), true);
    save(blob, 'kyvern-board-' + analysis.slice(0, 12) + '.' + format);
    $('pack-status').textContent = format.toUpperCase() + ' downloaded. This is a fixed snapshot; compose again to check for newer records.';
  }); }); });
})();
