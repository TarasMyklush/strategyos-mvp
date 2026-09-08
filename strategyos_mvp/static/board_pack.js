/* Immutable template versions and evidence-bound generated pack history. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var analysis = null, template = null, recorded = null, busy = false, internalTemplateWrite = false;
  function node(tag, value) { var n = document.createElement(tag); if (value !== undefined) n.textContent = value; return n; }
  function save(blob, filename) {
    var url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = filename; a.click(); setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }
  function reset() { recorded = null; $('pack-preview').replaceChildren(); $('pack-status').textContent = ''; updateDownloads(); }
  function updateDownloads() { $('pack-pdf').disabled = $('pack-pptx').disabled = !recorded || busy; }
  function setTemplate(value) {
    template = value; internalTemplateWrite = true; $('pack-template').value = JSON.stringify(value, null, 2); internalTemplateWrite = false; reset();
  }
  async function action(work) {
    if (busy) return; busy = true;
    $('board-pack').querySelectorAll('button, input, select, textarea').forEach(function (n) { n.disabled = true; });
    try { await work(); } catch (e) { $('pack-status').textContent = e.message; }
    finally { busy = false; $('board-pack').querySelectorAll('button, input, select, textarea').forEach(function (n) { n.disabled = false; }); updateDownloads(); }
  }
  async function request(path, body, binary) {
    var requestedAnalysis = analysis;
    var options = { credentials: 'same-origin', cache: 'no-store' };
    if (body !== undefined) { options.method = 'POST'; options.headers = { 'Content-Type': 'application/json' }; options.body = JSON.stringify(body); }
    var r = await fetch('/api/intent/dimensional' + path, options);
    if (!r.ok) { var error = await r.json().catch(function () { return {}; }); throw new Error(typeof error.detail === 'string' ? error.detail : 'The board pack request failed.'); }
    var data = await (binary ? r.blob() : r.json());
    if (requestedAnalysis !== analysis) throw new Error('The selected analysis changed. Open its pack history again.');
    return data;
  }
  function render(record) {
    recorded = record; $('pack-preview').replaceChildren();
    record.pack.pages.forEach(function (page) {
      var section = node('section'); section.className = 'pack-page'; section.appendChild(node('h3', page.title));
      page.lines.forEach(function (line, i) { var p = node('p');
        if (page.links[String(i)]) { var a = node('a', line); a.href = page.links[String(i)]; p.appendChild(a); } else p.textContent = line;
        p.dir = 'auto'; section.appendChild(p);
      }); $('pack-preview').appendChild(section);
    });
    var fresh = record.freshness.status === 'current' ? 'Current against governed records.' : 'Stale: ' + record.freshness.reasons.join(', ').replace(/_/g, ' ') + '. Generate a new pack after reviewing the newer records.';
    $('pack-status').textContent = record.pack.pages.length + ' pages · Pack ' + record.pack_id.slice(0, 16) + '… · ' + fresh +
      (record.pack.untranslated_labels.length ? ' Missing EN/AR labels: ' + record.pack.untranslated_labels.join(', ') + '.' : ' All requested labels are translated.');
    updateDownloads();
  }
  async function refreshTemplates(preferred) {
    var result = await request('/board-templates'), selected = preferred || $('pack-template-select').value;
    $('pack-template-select').replaceChildren(new Option('Choose a saved template', ''));
    result.templates.forEach(function (item) {
      var value = item.template_id + ':' + item.version;
      $('pack-template-select').add(new Option(item.template.client.en + ' · ' + item.template_id + ' v' + item.version + ' · ' + item.origin.type, value));
    });
    if (selected && Array.from($('pack-template-select').options).some(function (option) { return option.value === selected; })) $('pack-template-select').value = selected;
    return result;
  }
  async function loadSelectedTemplate() {
    var parts = $('pack-template-select').value.split(':');
    if (parts.length !== 2) throw new Error('Choose a saved template version.');
    var record = await request('/board-templates/' + encodeURIComponent(parts[0]) + '/versions/' + parts[1]); setTemplate(record.template);
  }
  async function refreshHistory(preferred) {
    if (!analysis) return;
    var result = await request('/board-packs?analysis_id=' + encodeURIComponent(analysis));
    $('pack-history-select').replaceChildren(new Option('Choose a generated pack', ''));
    result.packs.forEach(function (item) {
      $('pack-history-select').add(new Option(item.created_at + ' · ' + item.template_id + ' v' + item.template_version + ' · ' + item.language + ' · ' + item.freshness.status, item.pack_id));
    });
    if (preferred) $('pack-history-select').value = preferred;
  }
  window.addEventListener('kyvern-analysis', function (event) {
    analysis = event.detail; reset(); $('board-pack').hidden = !analysis;
    if (analysis) action(async function () {
      if (!template) setTemplate(await request('/board-pack/template'));
      await refreshTemplates(); await refreshHistory();
    });
  });
  window.addEventListener('kyvern-board-template-registered', function (event) { action(async function () {
    var value = event.detail.template_id + ':' + event.detail.version; await refreshTemplates(value); setTemplate(event.detail.template);
    $('pack-status').textContent = 'Approved Advisor template registered. Generate the pack from this immutable version.';
  }); });
  $('pack-template-select').addEventListener('change', function () { if ($('pack-template-select').value) action(loadSelectedTemplate); else reset(); });
  $('pack-history-load').addEventListener('click', function () { action(async function () {
    if (!$('pack-history-select').value) throw new Error('Choose a generated pack.');
    var value = await request('/board-packs/' + encodeURIComponent($('pack-history-select').value));
    $('pack-template-select').value = value.template_id + ':' + value.template_version; setTemplate(value.pack.binding.template); render(value);
  }); });
  $('pack-template').addEventListener('input', function () { if (!internalTemplateWrite) { template = null; $('pack-template-select').value = ''; reset(); } });
  $('pack-language').addEventListener('change', reset);
  $('pack-load-template').addEventListener('change', function () { action(async function () {
    var file = $('pack-load-template').files[0]; if (!file || file.size > 100000) throw new Error('Choose a template JSON file under 100 KB.');
    setTemplate(JSON.parse(await file.text())); $('pack-template-select').value = '';
    $('pack-status').textContent = 'Template loaded. Register this exact version before generating a pack.';
  }); });
  $('pack-register-template').addEventListener('click', function () { action(async function () {
    var value = JSON.parse($('pack-template').value), registered = await request('/board-templates', value);
    await refreshTemplates(registered.template_id + ':' + registered.version); setTemplate(registered.template);
    $('pack-status').textContent = 'Template ' + registered.template_id + ' v' + registered.version + ' registered immutably.';
  }); });
  $('pack-save-template').addEventListener('click', function () { action(async function () {
    var value = JSON.parse($('pack-template').value);
    save(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }), value.template_id + '-v' + value.version + '.json');
    $('pack-status').textContent = 'Portable template JSON downloaded.';
  }); });
  $('pack-preview-button').addEventListener('click', function () { action(async function () {
    var parts = $('pack-template-select').value.split(':'); if (parts.length !== 2) throw new Error('Register or choose an immutable template version first.');
    var value = await request('/analyses/' + analysis + '/board-packs', { template_id: parts[0], template_version: Number(parts[1]), language: $('pack-language').value });
    render(value); await refreshHistory(value.pack_id);
  }); });
  ['pdf', 'pptx'].forEach(function (format) { $('pack-' + format).addEventListener('click', function () { action(async function () {
    if (!recorded) throw new Error('Generate or open a recorded pack first.');
    var blob = await request('/board-packs/' + recorded.pack_id + '/' + format, undefined, true);
    save(blob, 'kyvern-board-' + recorded.pack_id.slice(0, 16) + '.' + format);
    $('pack-status').textContent = format.toUpperCase() + ' downloaded from recorded pack ' + recorded.pack_id.slice(0, 16) + '… · ' + recorded.freshness.status + '.';
  }); }); });
  updateDownloads();
})();
