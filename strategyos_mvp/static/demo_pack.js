(function () {
  'use strict';
  var panel = document.getElementById('demo-pack-panel');
  if (!panel) return;
  function el(tag, text, className) {
    var value = document.createElement(tag);
    if (text !== undefined) value.textContent = text;
    if (className) value.className = className;
    return value;
  }
  function status(text, error) {
    var value = document.getElementById('demo-pack-status');
    value.textContent = text || '';
    value.classList.toggle('vault-error', Boolean(error));
  }
  async function get(path) {
    var response = await fetch(path, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(response.status === 403 ? 'This identity cannot open configured demo packs.' : 'The configured demo pack could not be loaded.');
    return response.json();
  }
  function badge(text) { return el('span', text, 'hero__badge'); }
  function table(target, headers, rows) {
    var table = el('table'), head = el('thead'), body = el('tbody'), tr = el('tr');
    headers.forEach(function (value) { tr.appendChild(el('th', value)); }); head.appendChild(tr); table.appendChild(head);
    rows.forEach(function (row) {
      var tr = el('tr'); row.forEach(function (value) { var td = el('td'); if (value instanceof Node) td.appendChild(value); else td.textContent = value === null ? 'Missing' : String(value); tr.appendChild(td); }); body.appendChild(tr);
    }); table.appendChild(body); target.replaceChildren(table);
  }
  function dimensions(value) { return Object.keys(value).sort().map(function (key) { return key + ': ' + value[key]; }).join(' · '); }
  function renderCatalog(catalog) {
    document.getElementById('demo-pack-title').textContent = catalog.label;
    document.getElementById('demo-pack-description').textContent = catalog.description;
    document.getElementById('demo-pack-flags').replaceChildren(
      badge('Synthetic data'), badge('Read only'), badge('No authority effect'), badge('Sector configuration layer'));
    var stories = document.getElementById('demo-pack-stories'); stories.replaceChildren();
    catalog.stories.forEach(function (story) {
      var card = el('article', undefined, 'demo-story-card');
      card.append(el('h3', story.title), el('p', story.question),
        el('p', story.rollups[0].metric + ': ' + story.rollups[0].actual + ' vs ' + story.rollups[0].target + ' · ' + story.rollups[0].status));
      var findings = story.finding_types.length ? story.finding_types.join(' · ').replaceAll('_', ' / ') : 'cell drift';
      card.appendChild(el('p', findings + ' · ' + story.context_link_count + ' configured context link(s)', 'vault-note'));
      var button = el('button', 'Open governed story'); button.type = 'button';
      button.addEventListener('click', function () { openStory(story.story_id); }); card.appendChild(button); stories.appendChild(card);
    });
    stories.hidden = false; document.getElementById('demo-story-detail').hidden = true;
    document.getElementById('demo-pack-close').hidden = true; panel.hidden = false;
  }
  function evidenceLinks(detail, cell) {
    var refs = el('div'), evidence = detail.board_pack.evidence.filter(function (item) { return item.cell_id === cell.cell_id; });
    evidence.forEach(function (item, index) {
      if (index) refs.appendChild(el('span', ' · '));
      var link = el('a', item.side === 'plan' ? 'Plan' : 'Actuals'); link.href = item.path; refs.appendChild(link);
    }); return refs;
  }
  async function openStory(storyId) {
    status('Loading the evidence-bound analysis and board snapshot…');
    try {
      var detail = await get('/api/demo-packs/current/stories/' + encodeURIComponent(storyId));
      document.getElementById('demo-story-title').textContent = detail.story.title;
      document.getElementById('demo-story-question').textContent = detail.story.question;
      document.getElementById('demo-story-decision').textContent = 'Decision prompt: ' + detail.story.decision_prompt;
      var links = document.getElementById('demo-story-links'); links.replaceChildren();
      detail.story.context_links.forEach(function (item) { links.appendChild(el('p', item.from_cell_id + ' · ' + item.relationship + ' · ' + item.to_reference + ': ' + item.label, 'vault-note')); });
      table(document.getElementById('demo-story-rollups'), ['Metric', 'Plan', 'Actual', 'Variance', 'Status', 'Coverage'], detail.analysis.rollups.map(function (item) {
        return [item.metric + ' (' + item.unit + ')', item.target, item.actual, item.variance, item.status, item.measured_cells + ' / ' + item.planned_cells];
      }));
      var findings = document.getElementById('demo-story-findings'); findings.replaceChildren();
      detail.analysis.findings.forEach(function (item) {
        var card = el('article', undefined, 'pack-page'); card.append(el('h3', item.finding_type.replaceAll('_', ' / ')), el('p', item.narrative));
        if (item.effects) card.appendChild(el('p', 'Volume ' + item.effects.volume + ' · Mix ' + item.effects.mix + ' · Price ' + item.effects.price + ' · Observed ' + item.effects.observed_variance + ' ' + item.currency_unit));
        findings.appendChild(card);
      });
      table(document.getElementById('demo-story-cells'), ['Cell / dimensions', 'Owner', 'Plan', 'Actual', 'Variance', 'Status', 'Evidence'], detail.analysis.cells.map(function (item) {
        return [item.cell_id + ' · ' + dimensions(item.dimensions), item.owner, item.target + ' ' + item.unit, item.actual, item.variance, item.status, evidenceLinks(detail, item)];
      }));
      var board = document.getElementById('demo-story-board'); board.replaceChildren();
      detail.board_pack.pages.forEach(function (page) {
        var wrapper = el('details'), title = el('summary', page.title), lines = el('ul');
        page.lines.forEach(function (line) { lines.appendChild(el('li', line)); }); wrapper.append(title, lines); board.appendChild(wrapper);
      });
      document.getElementById('demo-pack-stories').hidden = true; document.getElementById('demo-story-detail').hidden = false;
      document.getElementById('demo-pack-close').hidden = false; status('Fixed synthetic snapshot · ' + detail.analysis.analysis_hash);
      panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) { status(error.message, true); }
  }
  document.getElementById('demo-pack-close').addEventListener('click', function () {
    document.getElementById('demo-pack-stories').hidden = false; document.getElementById('demo-story-detail').hidden = true;
    document.getElementById('demo-pack-close').hidden = true; status('');
  });
  get('/api/demo-packs/current').then(renderCatalog).catch(function (error) { status(error.message, true); });
}());
