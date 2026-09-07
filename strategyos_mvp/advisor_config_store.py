"""Durable approval and publication workflow for Strategic Advisor configuration."""
from .advisor_config import AdvisorConfiguration
from .dimensional_plan import Actuals, Plan, fingerprint
from .plan_decomposition import decompose_from_history, matching_history
from . import dimensional_intent_store as intent


def _config(conn, tenant, config_id, version):
    return intent._checked(intent._row(conn, '''SELECT * FROM strategyos_intent_advisor_configs
        WHERE tenant_key=%s AND config_id=%s AND version=%s''', (tenant, config_id, version)))


def _validate(principal, conn, config, *, require_latest=True):
    tenant, _ = intent._scope(principal)
    if config.plan_id == config.config_id:
        raise ValueError('Configuration and plan identifiers must be distinct.')
    plan = intent._plan(conn, tenant, config.plan_id, config.plan_version)
    actual = intent._actuals(conn, tenant, config.historical_actual_revision)
    if plan['digest'] != config.plan_digest:
        raise intent.Conflict('Plan fingerprint differs from this configuration.')
    newest = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_ratifications
        WHERE tenant_key=%s AND plan_id=%s''', (tenant, config.plan_id)).fetchone()[0]
    if require_latest and newest != config.plan_version:
        raise intent.Conflict('Configuration must use the latest ratified plan version.')
    intent._sources(principal, plan, kind='plan')
    intent._sources(principal, actual, kind='actuals')
    parent, history = matching_history(Plan.model_validate(plan['payload']), Actuals.model_validate(actual['payload']),
                                       parent_cell_id=config.parent_cell_id,
                                       split_dimension=config.split_dimension)
    configured = {item.member for item in config.allocations}
    available = set(history)
    if configured != available:
        missing = sorted(available - configured)
        unknown = sorted(configured - available)
        detail = []
        if missing: detail.append('unconfigured history: ' + ', '.join(missing))
        if unknown: detail.append('members without history: ' + ', '.join(unknown))
        raise ValueError('Configuration is incomplete (' + '; '.join(detail) + ').')
    latest_plan = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_plan_versions
        WHERE tenant_key=%s AND plan_id=%s''', (tenant, config.plan_id)).fetchone()[0]
    preview = decompose_from_history(
        Plan.model_validate(plan['payload']), Actuals.model_validate(actual['payload']),
        config.decomposition_request(), next_version=latest_plan + 1,
        historical_digest=actual['digest'], historical_source_pack_id=actual['source_pack_id'])
    expected_labels = {cell.metric for cell in preview.cells}
    expected_labels.update(preview.dimensions)
    expected_labels.update(member for cell in preview.cells for member in cell.dimensions.values())
    configured_labels = {parent.metric, config.split_dimension, *configured, *config.additional_labels}
    missing_labels = sorted(expected_labels - configured_labels)
    if missing_labels:
        raise ValueError('Bilingual board labels are incomplete: ' + ', '.join(missing_labels) + '.')
    return plan, actual, parent, preview, newest == config.plan_version


def create(principal, config):
    tenant, actor = intent._scope(principal, intent.IMPORT_ROLES)
    intent._key(config.config_id)
    with intent._connection() as conn:
        intent._lock(conn, tenant, 'advisor:' + config.config_id)
        plan, actual, parent, preview, _ = _validate(principal, conn, config)
        existing = intent._row(conn, '''SELECT * FROM strategyos_intent_advisor_configs
            WHERE tenant_key=%s AND config_id=%s AND version=%s''',
            (tenant, config.config_id, config.version))
        payload = config.model_dump(mode='json')
        digest = fingerprint(payload)
        if existing:
            intent._checked(existing)
            if existing['digest'] != digest:
                raise intent.Conflict('This configuration version already has different content; create a new version.')
            return read(principal, config.config_id, config.version)
        latest = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_advisor_configs
            WHERE tenant_key=%s AND config_id=%s''', (tenant, config.config_id)).fetchone()[0]
        if config.version != latest + 1:
            raise intent.Conflict('Save the next consecutive configuration version.')
        conn.execute('''INSERT INTO strategyos_intent_advisor_configs
            (tenant_key,config_id,version,payload,digest,created_by)
            VALUES (%s,%s,%s,%s::jsonb,%s,%s)''',
            (tenant, config.config_id, config.version, intent._encode(payload), digest, actor))
    return read(principal, config.config_id, config.version)


def read(principal, config_id, version):
    tenant, actor = intent._scope(principal)
    with intent._connection() as conn:
        row = _config(conn, tenant, config_id, version)
        config = AdvisorConfiguration.model_validate(row['payload'])
        plan, actual, parent, preview, current = _validate(principal, conn, config, require_latest=False)
        approval = intent._row(conn, '''SELECT * FROM strategyos_intent_advisor_approvals
            WHERE tenant_key=%s AND config_id=%s AND version=%s''', (tenant, config_id, version))
        publication = intent._row(conn, '''SELECT * FROM strategyos_intent_advisor_publications
            WHERE tenant_key=%s AND config_id=%s AND version=%s''', (tenant, config_id, version))
        grant = intent._row(conn, '''SELECT revision,enabled FROM strategyos_intent_ratifier_events
            WHERE tenant_key=%s AND plan_id=%s AND subject=%s ORDER BY revision DESC LIMIT 1''',
            (tenant, config.plan_id, actor))
    result = intent._public(row)
    result.update(
        readiness={'status': 'ready' if current else 'stale', 'checks': {
            'latest_ratified_plan': current, 'authorized_plan_source': True,
            'completed_historical_snapshot': True, 'complete_member_mapping': True,
            'owners_and_tolerances': True, 'bilingual_board_labels': True,
        }, 'preview_plan_digest': fingerprint(preview.model_dump(mode='json'))},
        approval=intent._public(approval) if approval else None,
        publication=intent._public(publication) if publication else None,
        source_bindings={
            'plan': {'source_pack_id': plan['source_pack_id'], 'digest': plan['digest']},
            'historical_actuals': {'source_pack_id': actual['source_pack_id'], 'digest': actual['digest']},
        },
        permissions={
            'can_approve': current and actor != row['created_by'] and not approval and
                           principal['role'] in intent.RATIFY_ROLES and bool(grant and grant['enabled']),
            'can_publish': current and principal['role'] in intent.IMPORT_ROLES and bool(approval) and not publication,
        })
    return result


def catalog(principal):
    tenant, _ = intent._scope(principal)
    visible = []
    with intent._connection() as conn:
        cursor = conn.execute('''SELECT c.config_id,c.version,c.digest,c.created_by,c.created_at,c.payload,
            (a.version IS NOT NULL) approved,(p.version IS NOT NULL) published
            FROM strategyos_intent_advisor_configs c
            LEFT JOIN strategyos_intent_advisor_approvals a USING(tenant_key,config_id,version)
            LEFT JOIN strategyos_intent_advisor_publications p USING(tenant_key,config_id,version)
            WHERE c.tenant_key=%s ORDER BY c.created_at DESC,c.config_id,c.version DESC LIMIT 100''', (tenant,))
        rows = [dict(zip([column.name for column in cursor.description], values)) for values in cursor.fetchall()]
        from .dimensional_intent_sources import SourceUnavailable
        for row in rows:
            config = AdvisorConfiguration.model_validate(row['payload'])
            try:
                plan = intent._plan(conn, tenant, config.plan_id, config.plan_version)
                actual = intent._actuals(conn, tenant, config.historical_actual_revision)
                intent._sources(principal, plan, kind='plan', verify_bytes=False)
                intent._sources(principal, actual, kind='actuals', verify_bytes=False)
            except (PermissionError, SourceUnavailable, intent.NotFound):
                continue
            visible.append(intent._public({key: value for key, value in row.items() if key != 'payload'}))
    return {'configurations': visible}


def approve(principal, config_id, version, expected_digest, note):
    tenant, actor = intent._scope(principal, intent.RATIFY_ROLES)
    with intent._connection() as conn:
        intent._lock(conn, tenant, 'advisor:' + config_id)
        row = _config(conn, tenant, config_id, version)
        if row['digest'] != expected_digest:
            raise intent.Conflict('Configuration fingerprint differs from the version reviewed.')
        if row['created_by'] == actor:
            raise PermissionError('A separate authorized reviewer must approve the configuration.')
        config = AdvisorConfiguration.model_validate(row['payload'])
        grant = intent._row(conn, '''SELECT revision,enabled FROM strategyos_intent_ratifier_events
            WHERE tenant_key=%s AND plan_id=%s AND subject=%s ORDER BY revision DESC LIMIT 1''',
            (tenant, config.plan_id, actor))
        if not grant or not grant['enabled']:
            raise PermissionError('This identity is not authorized to review the configured plan.')
        _validate(principal, conn, config)
        existing = intent._row(conn, '''SELECT * FROM strategyos_intent_advisor_approvals
            WHERE tenant_key=%s AND config_id=%s AND version=%s''', (tenant, config_id, version))
        if existing:
            if existing['approved_by'] != actor or existing['note'] != note:
                raise intent.Conflict('This configuration already has a different approval record.')
            return intent._public(existing)
        approval = intent._row(conn, '''INSERT INTO strategyos_intent_advisor_approvals
            (tenant_key,config_id,version,config_digest,approved_by,note)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING *''',
            (tenant, config_id, version, row['digest'], actor, note))
        return intent._public(approval)


def publish(principal, config_id, version, expected_digest):
    tenant, actor = intent._scope(principal, intent.IMPORT_ROLES)
    with intent._connection() as conn:
        row = _config(conn, tenant, config_id, version)
        if row['digest'] != expected_digest:
            raise intent.Conflict('Configuration fingerprint differs from the approved version.')
        approval = intent._row(conn, '''SELECT * FROM strategyos_intent_advisor_approvals
            WHERE tenant_key=%s AND config_id=%s AND version=%s AND config_digest=%s''',
            (tenant, config_id, version, row['digest']))
        if not approval:
            raise intent.Conflict('Approve this configuration before publishing it.')
        existing = intent._row(conn, '''SELECT * FROM strategyos_intent_advisor_publications
            WHERE tenant_key=%s AND config_id=%s AND version=%s''', (tenant, config_id, version))
        config = AdvisorConfiguration.model_validate(row['payload'])
        _validate(principal, conn, config)
    if existing:
        return intent._public(existing)
    proposal = intent.create_history_decomposition(principal, config.plan_id, config.plan_version,
                                                   config.decomposition_request())
    with intent._connection() as conn:
        intent._lock(conn, tenant, 'advisor:' + config_id)
        conn.execute('''INSERT INTO strategyos_intent_advisor_publications
            (tenant_key,config_id,version,config_digest,plan_id,plan_version,plan_digest,published_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
            (tenant, config_id, version, row['digest'], proposal['plan_id'], proposal['version'],
             proposal['digest'], actor))
        return intent._public(intent._row(conn, '''SELECT * FROM strategyos_intent_advisor_publications
            WHERE tenant_key=%s AND config_id=%s AND version=%s''', (tenant, config_id, version)))


def template(principal, config_id, version):
    record = read(principal, config_id, version)
    if not record['approval']:
        raise intent.Conflict('Approve this configuration before using its board template.')
    config = AdvisorConfiguration.model_validate(record['payload'])
    with intent._connection() as conn:
        plan = intent._plan(conn, principal['tenant_id'], config.plan_id, config.plan_version)
    parent = next(cell for cell in Plan.model_validate(plan['payload']).cells if cell.id == config.parent_cell_id)
    return config.board_template(parent.metric).model_dump(mode='json')
