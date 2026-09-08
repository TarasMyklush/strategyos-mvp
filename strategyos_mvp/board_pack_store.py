"""Immutable board template versions and generated pack history."""
from . import board_pack
from . import dimensional_intent_store as intent
from .dimensional_plan import fingerprint
from .dimensional_intent_sources import SourceUnavailable


def _template_row(conn, tenant, template_id, version):
    row = intent._checked(intent._row(conn, '''SELECT * FROM strategyos_intent_board_templates
        WHERE tenant_key=%s AND template_id=%s AND version=%s''',
        (tenant, template_id, version)))
    template = board_pack.PackTemplate.model_validate(row['payload'])
    if template.template_id != template_id or template.version != version:
        raise intent.Unavailable('Stored board template identity failed its integrity check.')
    return row


def _template_public(row):
    result = intent._public(row)
    result['template'] = result.pop('payload')
    return result


def register(principal, template, *, origin=None):
    tenant, actor = intent._scope(principal, intent.IMPORT_ROLES)
    intent._key(template.template_id)
    payload = template.model_dump(mode='json')
    digest = fingerprint(payload)
    origin = origin or {'type': 'manual'}
    with intent._connection() as conn:
        intent._lock(conn, tenant, 'board-template:' + template.template_id)
        existing = intent._row(conn, '''SELECT * FROM strategyos_intent_board_templates
            WHERE tenant_key=%s AND template_id=%s AND version=%s''',
            (tenant, template.template_id, template.version))
        if existing:
            intent._checked(existing)
            if existing['digest'] != digest or existing['origin'] != origin:
                raise intent.Conflict('This board template version already has different content or provenance; create a new version.')
            return _template_public(existing)
        latest = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_board_templates
            WHERE tenant_key=%s AND template_id=%s''', (tenant, template.template_id)).fetchone()[0]
        if template.version != latest + 1:
            raise intent.Conflict('Save the next consecutive board template version.')
        row = intent._row(conn, '''INSERT INTO strategyos_intent_board_templates
            (tenant_key,template_id,version,payload,digest,origin,created_by)
            VALUES (%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s) RETURNING *''',
            (tenant, template.template_id, template.version, intent._encode(payload), digest,
             intent._encode(origin), actor))
    return _template_public(row)


def register_advisor(principal, config_id, version):
    from . import advisor_config_store
    record = advisor_config_store.read(principal, config_id, version)
    if not record['approval']:
        raise intent.Conflict('Approve this configuration before registering its board template.')
    template = board_pack.PackTemplate.model_validate(advisor_config_store.template(principal, config_id, version))
    return register(principal, template, origin={
        'type': 'advisor', 'config_id': config_id, 'version': version,
        'config_digest': record['digest'],
    })


def read_template(principal, template_id, version):
    tenant, _ = intent._scope(principal)
    with intent._connection() as conn:
        return _template_public(_template_row(conn, tenant, template_id, version))


def templates(principal):
    tenant, _ = intent._scope(principal)
    with intent._connection() as conn:
        cursor = conn.execute('''SELECT * FROM strategyos_intent_board_templates
            WHERE tenant_key=%s ORDER BY created_at DESC,template_id,version DESC LIMIT 100''', (tenant,))
        rows = [dict(zip([column.name for column in cursor.description], values)) for values in cursor.fetchall()]
    return {'templates': [_template_public(intent._checked(row)) for row in rows],
            'permissions': {'can_register': principal['role'] in intent.IMPORT_ROLES}}


def _checked_pack(row):
    if row is None:
        raise intent.NotFound('Board pack not found.')
    if fingerprint(row['payload']) != row['digest']:
        raise intent.Unavailable('Stored board pack failed its integrity check.')
    pack = row['payload']
    if pack.get('pack_hash') != row['pack_id'] or fingerprint(pack.get('binding')) != row['pack_id']:
        raise intent.Unavailable('Stored board pack binding failed its integrity check.')
    return row


def _pack_public(principal, row):
    row = _checked_pack(row)
    tenant, _ = intent._scope(principal)
    with intent._connection() as conn:
        template_row = _template_row(conn, tenant, row['template_id'], row['template_version'])
    if fingerprint(row['payload']['binding']['template']) != template_row['digest']:
        raise intent.Unavailable('Stored board pack template binding failed its integrity check.')
    current = board_pack.compose(principal, row['analysis_id'], board_pack.PackRequest(
        template=board_pack.PackTemplate.model_validate(template_row['payload']), language=row['language']))
    result = intent._public(row)
    result['pack'] = result.pop('payload')
    reasons = list(current['binding']['warnings'])
    if current['pack_hash'] != row['pack_id'] and not reasons:
        reasons.append('composition_changed')
    result['freshness'] = {
        'status': 'current' if current['pack_hash'] == row['pack_id'] else 'stale',
        'reasons': reasons, 'current_pack_hash': current['pack_hash'],
        'checked_at': current['checked_at'],
    }
    return result


def create_pack(principal, analysis_id, template_id, template_version, language):
    tenant, actor = intent._scope(principal)
    intent._key(analysis_id); intent._key(template_id)
    with intent._connection() as conn:
        template_row = _template_row(conn, tenant, template_id, template_version)
    pack = board_pack.compose(principal, analysis_id, board_pack.PackRequest(
        template=board_pack.PackTemplate.model_validate(template_row['payload']), language=language))
    digest = fingerprint(pack)
    with intent._connection() as conn:
        intent._lock(conn, tenant, 'board-pack:' + pack['pack_hash'])
        existing = intent._row(conn, '''SELECT * FROM strategyos_intent_board_packs
            WHERE tenant_key=%s AND pack_id=%s''', (tenant, pack['pack_hash']))
        if not existing:
            existing = intent._row(conn, '''INSERT INTO strategyos_intent_board_packs
                (tenant_key,pack_id,analysis_id,template_id,template_version,language,payload,digest,created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s) RETURNING *''',
                (tenant, pack['pack_hash'], analysis_id, template_id, template_version, language,
                 intent._encode(pack), digest, actor))
    return _pack_public(principal, existing)


def read_pack(principal, pack_id):
    tenant, _ = intent._scope(principal)
    with intent._connection() as conn:
        row = intent._row(conn, '''SELECT * FROM strategyos_intent_board_packs
            WHERE tenant_key=%s AND pack_id=%s''', (tenant, pack_id))
    return _pack_public(principal, row)


def packs(principal, analysis_id=None, limit=25):
    tenant, _ = intent._scope(principal)
    if analysis_id is not None:
        intent._key(analysis_id)
    if not 1 <= limit <= 50:
        raise ValueError('Invalid board pack history page.')
    with intent._connection() as conn:
        if analysis_id:
            cursor = conn.execute('''SELECT * FROM strategyos_intent_board_packs
                WHERE tenant_key=%s AND analysis_id=%s ORDER BY created_at DESC LIMIT %s''',
                (tenant, analysis_id, limit))
        else:
            cursor = conn.execute('''SELECT * FROM strategyos_intent_board_packs
                WHERE tenant_key=%s ORDER BY created_at DESC LIMIT %s''', (tenant, limit))
        rows = [dict(zip([column.name for column in cursor.description], values)) for values in cursor.fetchall()]
    visible = []
    for row in rows:
        try:
            item = _pack_public(principal, row)
            item.pop('pack')
            visible.append(item)
        except (PermissionError, SourceUnavailable):
            continue
    return {'packs': visible}
