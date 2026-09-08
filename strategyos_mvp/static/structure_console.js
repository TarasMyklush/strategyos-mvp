/* Guided, versioned organization structure configuration; no raw config editor. */
(function () {
  'use strict';
  var base = '/api/intent/dimensional/advisor/structure-configurations', busy = false, record = null;
  var $ = function (id) { return document.getElementById(id); };
  function node(tag, text) { var item = document.createElement(tag); if (text !== undefined) item.textContent = text; return item; }
  function field(label, name, value, required) {
    var wrapper = node('label'), title = node('span', label), input = node('input');
    wrapper.className = 'vault-field'; input.dataset.field = name; input.value = value || ''; input.maxLength = name.indexOf('label_') === 0 ? 100 : 160;
    if (required !== false) input.required = true; wrapper.append(title, input); return wrapper;
  }
  function removeButton(card) {
    var button = node('button', 'Remove'); button.type = 'button'; button.className = 'secondary';
    button.addEventListener('click', function () { card.remove(); }); return button;
  }
  function valueOf(root, name) { return root.querySelector('[data-field="' + name + '"]').value.trim(); }
  function translation(root) { return { en: valueOf(root, 'label_en'), ar: valueOf(root, 'label_ar') }; }
  function addUnit(value) {
    value = value || {}; var card = node('div'); card.className = 'pack-page structure-unit';
    card.append(field('Business-unit key', 'key', value.key), field('Parent key (optional)', 'parent', value.parent, false),
      field('Label · English', 'label_en', value.label && value.label.en), field('التسمية · العربية', 'label_ar', value.label && value.label.ar), removeButton(card));
    $('structure-business-units').appendChild(card);
  }
  function addMember(container, value) {
    value = value || {}; var card = node('div'); card.className = 'vault-controls structure-member';
    card.append(field('Member key', 'key', value.key), field('Parent key (optional)', 'parent', value.parent, false),
      field('Label · English', 'label_en', value.label && value.label.en), field('التسمية · العربية', 'label_ar', value.label && value.label.ar), removeButton(card));
    container.appendChild(card);
  }
  function addDimension(value) {
    value = value || {}; var card = node('section'), head = node('div'), members = node('div'), add = node('button', 'Add member');
    card.className = 'pack-page structure-dimension'; head.className = 'vault-controls'; members.className = 'structure-members';
    head.append(field('Dimension key', 'key', value.key), field('Label · English', 'label_en', value.label && value.label.en),
      field('التسمية · العربية', 'label_ar', value.label && value.label.ar), removeButton(card));
    add.type = 'button'; add.className = 'secondary'; add.addEventListener('click', function () { addMember(members); });
    card.append(head, members, add); $('structure-dimensions').appendChild(card);
    (value.members || [{}]).forEach(function (member) { addMember(members, member); });
  }
  function addMappingValue(container, value) {
    value = value || {}; var row = node('div'); row.className = 'vault-controls structure-mapping-value';
    row.append(field('Source value', 'source_value', value.source_value), field('Configured target key', 'target', value.target), removeButton(row));
    container.appendChild(row);
  }
  function addMapping(value) {
    value = value || {}; var card = node('section'), head = node('div'), typeLabel = node('label'), type = node('select'), values = node('div'), add = node('button', 'Add value mapping');
    card.className = 'pack-page structure-mapping'; head.className = 'vault-controls'; values.className = 'structure-mapping-values'; typeLabel.className = 'vault-field';
    type.dataset.field = 'target_type'; type.add(new Option('Business unit', 'business_unit')); type.add(new Option('Dimension', 'dimension')); type.value = value.target_type || 'dimension';
    typeLabel.append(node('span', 'Mapping target'), type);
    head.append(field('Registered source key', 'source_key', value.source_key), field('Source field', 'source_field', value.source_field),
      typeLabel, field('Dimension key (blank for business unit)', 'target_key', value.target_key, false), removeButton(card));
    add.type = 'button'; add.className = 'secondary'; add.addEventListener('click', function () { addMappingValue(values); });
    card.append(head, values, add); $('structure-mappings').appendChild(card);
    (value.values || [{}]).forEach(function (item) { addMappingValue(values, item); });
  }
  async function request(path, body) {
    var options = { credentials: 'same-origin', cache: 'no-store' };
    if (body !== undefined) { options.method = 'POST'; options.headers = { 'Content-Type': 'application/json' }; options.body = JSON.stringify(body); }
    var response = await fetch(base + path, options), data = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The organization structure request failed.');
    return data;
  }
  function controls() { $('structure-setup').querySelectorAll('button,input,textarea,select').forEach(function (item) { item.disabled = busy; }); }
  async function action(work) { if (busy) return; busy = true; controls(); try { await work(); } catch (error) { $('structure-status').textContent = error.message; } finally { busy = false; controls(); } }
  function collect() {
    return {
      schema_version: 1, config_id: $('structure-id').value.trim(), version: Number($('structure-version').value),
      company: { en: $('structure-company-en').value.trim(), ar: $('structure-company-ar').value.trim() },
      business_units: Array.from($('structure-business-units').querySelectorAll('.structure-unit')).map(function (row) {
        return { key: valueOf(row, 'key'), parent: valueOf(row, 'parent') || null, label: translation(row) };
      }),
      dimensions: Array.from($('structure-dimensions').querySelectorAll('.structure-dimension')).map(function (section) {
        return { key: valueOf(section, 'key'), label: translation(section),
          members: Array.from(section.querySelectorAll('.structure-member')).map(function (row) {
            return { key: valueOf(row, 'key'), parent: valueOf(row, 'parent') || null, label: translation(row) };
          }) };
      }),
      source_mappings: Array.from($('structure-mappings').querySelectorAll('.structure-mapping')).map(function (section) {
        var type = valueOf(section, 'target_type');
        return { source_key: valueOf(section, 'source_key'), source_field: valueOf(section, 'source_field'),
          target_type: type, target_key: type === 'dimension' ? valueOf(section, 'target_key') : null,
          values: Array.from(section.querySelectorAll('.structure-mapping-value')).map(function (row) {
            return { source_value: valueOf(row, 'source_value'), target: valueOf(row, 'target') };
          }) };
      })
    };
  }
  function resetForm(payload) {
    payload = payload || { business_units: [{}], dimensions: [{}], source_mappings: [{}, {}] };
    $('structure-id').value = payload.config_id || 'organization-structure'; $('structure-version').value = payload.version || 1;
    $('structure-company-en').value = payload.company ? payload.company.en : ''; $('structure-company-ar').value = payload.company ? payload.company.ar : '';
    $('structure-business-units').replaceChildren(); $('structure-dimensions').replaceChildren(); $('structure-mappings').replaceChildren();
    (payload.business_units || [{}]).forEach(addUnit); (payload.dimensions || [{}]).forEach(addDimension); (payload.source_mappings || [{}, {}]).forEach(addMapping);
  }
  function render(value) {
    record = value; $('structure-review').hidden = false; $('structure-review-title').textContent = value.config_id + ' · Version ' + value.version;
    $('structure-review-summary').replaceChildren(
      node('p', value.approval ? 'Approved by ' + value.approval.approved_by : 'Ready for independent approval'),
      node('p', value.payload.business_units.length + ' business units · ' + value.payload.dimensions.length + ' dimensions · ' + value.payload.source_mappings.length + ' source mappings'),
      node('p', value.source_bindings.map(function (item) { return item.source_key; }).join(', ') + ' · registered sources'),
      node('p', value.authoritative ? 'This is the authoritative approved structure.' : 'This version is not authoritative.')
    );
    $('structure-approve-form').hidden = !value.permissions.can_approve;
  }
  async function refresh(preferred) {
    var result = await request(''), selected = preferred || $('structure-select').value;
    $('structure-select').replaceChildren(new Option('Choose a saved structure', ''));
    result.configurations.forEach(function (item) { $('structure-select').add(new Option(item.config_id + ' · v' + item.version + (item.approved ? ' · Approved' : ' · Ready'), item.config_id + ':' + item.version)); });
    if (selected) $('structure-select').value = selected;
    $('structure-form').hidden = !result.permissions.can_create;
  }
  $('structure-add-unit').addEventListener('click', function () { addUnit(); });
  $('structure-add-dimension').addEventListener('click', function () { addDimension(); });
  $('structure-add-mapping').addEventListener('click', function () { addMapping(); });
  $('structure-form').addEventListener('submit', function (event) { event.preventDefault(); action(async function () {
    record = await request('', collect()); await refresh(record.config_id + ':' + record.version); resetForm(record.payload); render(record);
    $('structure-status').textContent = 'Structure saved. A separate tenant administrator must approve it before it becomes authoritative.';
  }); });
  $('structure-open').addEventListener('click', function () { action(async function () {
    var parts = $('structure-select').value.split(':'); if (parts.length !== 2) throw new Error('Choose a saved organization structure.');
    record = await request('/' + encodeURIComponent(parts[0]) + '/versions/' + parts[1]); resetForm(record.payload); render(record);
    $('structure-status').textContent = record.authoritative ? 'Authoritative structure loaded.' : 'Structure version loaded for review.';
  }); });
  $('structure-approve-form').addEventListener('submit', function (event) { event.preventDefault(); action(async function () {
    await request('/' + encodeURIComponent(record.config_id) + '/versions/' + record.version + '/approve',
      { expected_digest: record.digest, note: $('structure-review-note').value.trim() });
    record = await request('/' + encodeURIComponent(record.config_id) + '/versions/' + record.version); render(record); await refresh(record.config_id + ':' + record.version);
    $('structure-status').textContent = 'Organization structure approved and authoritative.';
  }); });
  resetForm(); action(refresh);
})();
