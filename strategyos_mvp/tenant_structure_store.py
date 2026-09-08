"""Append-only tenant structure configuration and independent approval."""
from . import dimensional_intent_store as intent
from .dimensional_plan import fingerprint
from .tenant_structure import TenantStructureConfiguration


def _row(conn, tenant, config_id, version):
    return intent._checked(intent._row(conn, '''SELECT * FROM strategyos_intent_structure_configs
        WHERE tenant_key=%s AND config_id=%s AND version=%s''', (tenant, config_id, version)))


def _source_bindings(conn, tenant, configuration):
    source_keys = sorted({mapping.source_key for mapping in configuration.source_mappings})
    cursor = conn.execute('''SELECT s.source_key,s.id FROM strategyos_source_systems s
        JOIN strategyos_tenants t ON t.id=s.tenant_id
        WHERE t.slug=%s AND s.source_key=ANY(%s) ORDER BY s.source_key''', (tenant, source_keys))
    bindings = [{'source_key': values[0], 'source_system_id': values[1]} for values in cursor.fetchall()]
    found = {binding['source_key'] for binding in bindings}
    missing = sorted(set(source_keys) - found)
    if missing:
        raise ValueError('Register these source systems before mapping them: ' + ', '.join(missing) + '.')
    return bindings


def create(principal, configuration):
    tenant, actor = intent._scope(principal, intent.IMPORT_ROLES)
    intent._key(configuration.config_id)
    payload = configuration.model_dump(mode='json')
    digest = fingerprint(payload)
    with intent._connection() as conn:
        intent._lock(conn, tenant, 'structure:' + configuration.config_id)
        bindings = _source_bindings(conn, tenant, configuration)
        existing = intent._row(conn, '''SELECT * FROM strategyos_intent_structure_configs
            WHERE tenant_key=%s AND config_id=%s AND version=%s''',
            (tenant, configuration.config_id, configuration.version))
        if existing:
            intent._checked(existing)
            if existing['digest'] != digest:
                raise intent.Conflict('This organization structure version already has different content; create a new version.')
            return read(principal, configuration.config_id, configuration.version)
        latest = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_structure_configs
            WHERE tenant_key=%s AND config_id=%s''', (tenant, configuration.config_id)).fetchone()[0]
        if configuration.version != latest + 1:
            raise intent.Conflict('Save the next consecutive organization structure version.')
        conn.execute('''INSERT INTO strategyos_intent_structure_configs
            (tenant_key,config_id,version,payload,digest,created_by)
            VALUES (%s,%s,%s,%s::jsonb,%s,%s)''',
            (tenant, configuration.config_id, configuration.version,
             intent._encode(payload), digest, actor))
    return read(principal, configuration.config_id, configuration.version)


def read(principal, config_id, version):
    tenant, actor = intent._scope(principal)
    with intent._connection() as conn:
        row = _row(conn, tenant, config_id, version)
        configuration = TenantStructureConfiguration.model_validate(row['payload'])
        bindings = _source_bindings(conn, tenant, configuration)
        approval = intent._row(conn, '''SELECT * FROM strategyos_intent_structure_approvals
            WHERE tenant_key=%s AND config_id=%s AND version=%s''', (tenant, config_id, version))
        latest_approved = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_structure_approvals
            WHERE tenant_key=%s AND config_id=%s''', (tenant, config_id)).fetchone()[0]
    result = intent._public(row)
    result.update(
        approval=intent._public(approval) if approval else None,
        readiness={'status': 'approved' if approval else 'ready', 'checks': {
            'business_unit_scope': True, 'dimension_hierarchies': True,
            'registered_source_mappings': True, 'bilingual_labels': True,
        }},
        source_bindings=bindings,
        authoritative=bool(approval and version == latest_approved),
        permissions={'can_approve': principal['role'] == 'tenant_admin'
                     and actor != row['created_by'] and not approval},
    )
    return result


def approve(principal, config_id, version, expected_digest, note):
    tenant, actor = intent._scope(principal, {'tenant_admin'})
    if len(note.strip()) < 20:
        raise ValueError('Explain the organization structure review in at least 20 characters.')
    with intent._connection() as conn:
        intent._lock(conn, tenant, 'structure:' + config_id)
        row = _row(conn, tenant, config_id, version)
        if row['digest'] != expected_digest:
            raise intent.Conflict('Organization structure fingerprint differs from the version reviewed.')
        if row['created_by'] == actor:
            raise PermissionError('A separate tenant administrator must approve the organization structure.')
        configuration = TenantStructureConfiguration.model_validate(row['payload'])
        _source_bindings(conn, tenant, configuration)
        existing = intent._row(conn, '''SELECT * FROM strategyos_intent_structure_approvals
            WHERE tenant_key=%s AND config_id=%s AND version=%s''', (tenant, config_id, version))
        if existing:
            if existing['approved_by'] != actor or existing['note'] != note:
                raise intent.Conflict('This organization structure already has a different approval.')
            return intent._public(existing)
        approval = intent._row(conn, '''INSERT INTO strategyos_intent_structure_approvals
            (tenant_key,config_id,version,config_digest,approved_by,note)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING *''',
            (tenant, config_id, version, row['digest'], actor, note.strip()))
    return intent._public(approval)


def catalog(principal):
    tenant, _ = intent._scope(principal)
    with intent._connection() as conn:
        cursor = conn.execute('''SELECT c.config_id,c.version,c.digest,c.created_by,c.created_at,
            (a.version IS NOT NULL) approved
            FROM strategyos_intent_structure_configs c
            LEFT JOIN strategyos_intent_structure_approvals a USING(tenant_key,config_id,version)
            WHERE c.tenant_key=%s ORDER BY c.created_at DESC,c.config_id,c.version DESC LIMIT 100''',
            (tenant,))
        rows = [intent._public(dict(zip([column.name for column in cursor.description], values)))
                for values in cursor.fetchall()]
    return {'configurations': rows,
            'permissions': {'can_create': principal['role'] in intent.IMPORT_ROLES}}
