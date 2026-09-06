(function () {
  'use strict';
  const form = document.getElementById('source-form');
  const status = document.getElementById('source-status');
  const result = document.getElementById('source-result');
  const start = document.getElementById('source-start');
  const register = document.getElementById('source-register');
  const sourceFile = document.getElementById('source-file');
  const evidenceStatus = document.getElementById('evidence-status');
  const mapLink = document.getElementById('evidence-map');
  let staged = null, busy = false, generation = 0;
  const value = name => form.elements.namedItem(name).value.trim();
  const checked = name => form.elements.namedItem(name).checked;
  const list = name => value(name).split(',').map(item => item.trim()).filter(Boolean);
  function invalidate() { generation += 1; staged = null; start.disabled = true; register.disabled = true; result.hidden = true; mapLink.hidden = true; evidenceStatus.textContent = ''; }
  form.addEventListener('input', invalidate);
  form.addEventListener('change', invalidate);
  async function request(url, options) {
    const response = await fetch(url, {...options, credentials:'same-origin', cache:'no-store'});
    const payload = await response.json();
    if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'The source contract was not accepted. Check your inputs and authority.');
    return payload;
  }
  function show(payload) {
    const contract = payload.source_contract || {};
    const summary = document.getElementById('source-summary'); summary.replaceChildren();
    for (const [label, text] of Object.entries({Source:contract.display_name || 'Unclassified',
      Origin:contract.origin_category || 'unknown', Classification:contract.classification_status || 'unclassified',
      Files:String(payload.manifest_summary?.file_count || 0), 'Source pack':payload.source_pack_id})) {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = label; dd.textContent = text; summary.append(dt, dd);
    }
    document.getElementById('source-detail').textContent = JSON.stringify({
      files:(payload.manifest || []).map(item => ({file:item.relative_path, status:item.processing_status, hash:item.sha256})),
      readiness:payload.task_readiness, permissions:contract.access_policy}, null, 2);
    result.hidden = false;
    sourceFile.replaceChildren();
    for (const file of payload.manifest || []) {
      const option = document.createElement('option'); option.value = file.relative_path;
      option.textContent = file.relative_path; sourceFile.append(option);
    }
    register.disabled = contract.classification_status !== 'confirmed' || !sourceFile.options.length;
    start.disabled = contract.classification_status !== 'confirmed' || !payload.task_readiness?.ready_for_run;
    status.textContent = contract.classification_status === 'confirmed'
      ? 'Source staged. Review the file accounting before starting analysis.'
      : 'Stored for classification only. Complete the source contract and stage again before analysis.';
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    const files = Array.from(form.elements.namedItem('files').files || []), folder = value('folder_path');
    if ((!files.length && !folder) || (files.length && folder)) {
      status.textContent = 'Choose files or a server folder, not both.'; return;
    }
    const contract = {source_key:value('source_key') || undefined, display_name:value('display_name'),
      origin_category:value('origin_category'), governed_owner:value('governed_owner'),
      authorization_basis:value('authorization_basis'), provider_name:value('provider_name') || null,
      license_policy_ref:value('license_policy_ref') || null,
      access_policy:{storage_allowed:checked('storage_allowed'), index_allowed:checked('index_allowed'),
        export_allowed:checked('export_allowed'), external_model_allowed:false, quote_allowed:false,
        allowed_roles:list('allowed_roles'), allowed_purposes:list('allowed_purposes'),
        allowed_business_units:list('allowed_business_units')}};
    const ticket = generation;
    busy = true; start.disabled = true; form.querySelector('[type="submit"]').disabled = true;
    status.textContent = 'Checking permissions and staging files…';
    try {
      let payload;
      if (folder) payload = await request('/source-packs/from-path', {method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({...contract, ...contract.access_policy, source_display_name:contract.display_name, folder_path:folder})});
      else {
        const data = new FormData(); files.forEach(file => data.append('files', file, file.name));
        data.append('source_contract_json', JSON.stringify(contract));
        payload = await request('/source-packs', {method:'POST',body:data});
      }
      if (ticket !== generation) { status.textContent = 'Previous inputs were staged. Inputs changed; stage the current source before analysis.'; return; }
      staged = payload; show(payload);
    } catch (error) { staged = null; result.hidden = true; status.textContent = 'Not confirmed: ' + error.message; }
    finally { busy = false; form.querySelector('[type="submit"]').disabled = false; }
  });
  start.addEventListener('click', async () => {
    if (busy || start.disabled || !staged) return;
    busy = true; start.disabled = true;
    try {
      const run = await request('/runs', {method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({source_pack_id:staged.source_pack_id, sync_artifacts:true})});
      status.textContent = 'Analysis requested: ' + (run.run_id || run.job_id || run.status || 'pending') + '. No approval or publication was performed.';
      staged = null;
    } catch (error) { status.textContent = 'Analysis not confirmed: ' + error.message + ' Check run history before retrying.'; }
    finally { busy = false; register.disabled = !staged; }
  });
  sourceFile.addEventListener('change', () => { mapLink.hidden = true; evidenceStatus.textContent = ''; });
  register.addEventListener('click', async () => {
    if (busy || register.disabled || !staged || !sourceFile.value) return;
    const ticket = generation, selected = sourceFile.value;
    busy = true; register.disabled = true; mapLink.hidden = true;
    evidenceStatus.textContent = 'Checking the staged hash and current source contract…';
    try {
      const receipt = await request('/api/claims/intake/staged-evidence', {method:'POST',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify({source_pack_id:staged.source_pack_id, relative_path:selected})});
      if (ticket !== generation || selected !== sourceFile.value) return;
      evidenceStatus.textContent = 'Evidence registered. No claims were created and no analysis was started.';
      mapLink.href = '/claims/intake?occurrence=' + encodeURIComponent(receipt.occurrence_key);
      mapLink.hidden = !selected.toLowerCase().endsWith('.xlsx');
    } catch (error) { evidenceStatus.textContent = 'Registration not confirmed: ' + error.message; }
    finally { busy = false; register.disabled = !staged || staged.source_contract?.classification_status !== 'confirmed'; }
  });
}());
