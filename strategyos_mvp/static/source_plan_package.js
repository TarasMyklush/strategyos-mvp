/* Compile registered source-plan packages without bypassing structure review or ratification. */
(function () {
  'use strict';
  var form = document.getElementById('source-plan-package-form');
  if (!form) return;
  var status = document.getElementById('source-plan-package-status');
  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    var button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    status.textContent = 'Verifying and compiling the registered plan package…';
    try {
      var pack = document.getElementById('source-plan-pack').value.trim();
      var tolerance = document.getElementById('source-plan-tolerance').value.trim();
      var response = await fetch('/api/intent/dimensional/source-packs/' + encodeURIComponent(pack) + '/plan-package/import', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cell_tolerance_sar: tolerance })
      });
      var result = await response.json().catch(function () { return {}; });
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'The plan package could not be prepared.');
      if (result.status === 'awaiting_structure_approval') {
        status.textContent = 'Structure ' + result.structure.config_id + ' · Version ' + result.structure.version +
          ' is ready for independent administrator approval. After approval, submit this package again.';
        document.getElementById('structure-setup').open = true;
        document.getElementById('structure-status').textContent = 'Open the staged structure above to review and approve it.';
        document.getElementById('structure-setup').scrollIntoView({ behavior: 'smooth', block: 'start' });
      } else {
        status.textContent = 'Imported ' + result.assertions.plan_rows + ' FY plan cells and ' +
          result.assertions.actual_cells + ' comparable actual cells. The plan remains a proposal until independently ratified.';
        document.getElementById('refresh').click();
      }
    } catch (error) {
      status.textContent = error.message || 'The plan package could not be prepared.';
    } finally {
      button.disabled = false;
    }
  });
})();
