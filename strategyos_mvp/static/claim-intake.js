(function () {
  'use strict';
  var form = document.getElementById('intake-form');
  var apply = document.getElementById('intake-apply');
  var status = document.getElementById('intake-status');
  var result = document.getElementById('intake-result');
  var preview = null, generation = 0, busy = false;
  var stagedOccurrence = new URLSearchParams(window.location.search).get('occurrence');
  if (stagedOccurrence) form.elements.namedItem('occurrence_key').value = stagedOccurrence;
  document.getElementById('mapping-example').textContent = JSON.stringify({
    mapping_key:'monthly-finance', mapping_version:'1', rationale:'Approved source definitions',
    sheet:'Finance', subject_type:'business_unit', subject_key_column:'BU',
    period_start_column:'From', period_end_column:'To',
    columns:[{column:'Amount',metric_key:'operating_cost',kind_column:'Type',
      unit:'SAR',currency:'SAR',scale:1,author_column:'Author'}]
  }, null, 2);
  function invalidate() { generation += 1; preview = null; apply.disabled = true; result.textContent = ''; }
  form.addEventListener('input', invalidate);
  form.addEventListener('change', invalidate);
  async function submit(record) {
    if (busy || !form.reportValidity() || (record && !preview)) return;
    var ticket = generation;
    var data = record ? preview : new FormData(form);
    data.set('apply', record ? 'true' : 'false');
    busy = true; apply.disabled = true;
    form.querySelector('[type="submit"]').disabled = true;
    result.textContent = ''; status.textContent = record ? 'Recording the reviewed interpretation…' : 'Checking source access and interpreting cells…';
    try {
      var response = await fetch('/api/claims/intake/workbook', {method:'POST',body:data,credentials:'same-origin',cache:'no-store'});
      var payload = await response.json();
      if (ticket !== generation) { status.textContent = record ? 'Submission completed for the previous inputs. Preview the changed inputs before another submission.' : 'Inputs changed. Preview again.'; return; }
      if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'The interpretation could not be accepted. Check the mapping and your source permissions.');
      result.textContent = JSON.stringify(payload, null, 2);
      if (record) {
        preview = null;
        status.textContent = payload.replayed ? 'This interpretation was already recorded; no duplicate claims were created.' : 'Claims recorded as unreviewed. Approved briefings remain unchanged.';
      } else {
        preview = data;
        apply.disabled = payload.claim_count === 0;
        status.textContent = 'Preview only: ' + payload.claim_count + ' claims, ' + payload.quarantined_count + ' unclassified, ' + payload.unmapped_count + ' cells without claims. Review the results before recording.';
      }
    } catch (error) {
      preview = null;
      status.textContent = 'Not confirmed: ' + error.message + (record ? ' Retry the same interpretation to check its idempotent receipt.' : '');
    } finally { busy = false; form.querySelector('[type="submit"]').disabled = false; }
  }
  form.addEventListener('submit', function (event) { event.preventDefault(); submit(false); });
  apply.addEventListener('click', function () { submit(true); });
}());
