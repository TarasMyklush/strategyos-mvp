"""Tenant-bound, append-only dimensional Intent workflow backed by PostgreSQL.

Every public operation receives an authenticated principal from the API. Source
paths are resolved from owned registered packs; imported fields grant no rights.
"""
from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import re
import hashlib
from pathlib import Path

from . import state_store
from .config import CONFIG
from .dimensional_plan import (
    Actuals, Plan, actual_source_references, evaluate, fingerprint,
    plan_source_references,
)
from .dimensional_intent_sources import registered_sources

READ_ROLES = {'operator', 'tenant_operator', 'reviewer', 'auditor', 'executive', 'tenant_admin'}
IMPORT_ROLES = {'operator', 'tenant_operator', 'tenant_admin'}
RATIFY_ROLES = {'executive', 'reviewer', 'tenant_admin'}
MAX_BYTES = 2_000_000


class Conflict(ValueError):
    pass


class NotFound(LookupError):
    pass


class Unavailable(RuntimeError):
    pass


def _scope(principal, roles=READ_ROLES):
    tenant, subject = principal.get('tenant_id'), principal.get('subject')
    if (principal.get('auth_disabled') or principal.get('demo_role_login') or
        principal.get('role') not in roles or not subject or subject in {'anonymous', 'auth-disabled'} or
        str(subject).startswith('demo-role:') or not tenant or tenant != CONFIG.tenant_slug):
        raise PermissionError('An authenticated identity with the required tenant role is required.')
    return tenant, subject


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}', value):
        raise ValueError('Use a bounded identifier containing letters, digits, dots, underscores or hyphens.')
    return value


def _encode(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode()) > MAX_BYTES:
        raise ValueError('Dimensional snapshot exceeds the 2 MB limit.')
    return encoded


@contextmanager
def _connection(*, check_schema=True):
    handle, failure = state_store.database_connection()
    if failure or handle is None:
        raise Unavailable('Dimensional Intent requires the durable database.')
    with handle as conn:
        if check_schema:
            row = conn.execute("SELECT to_regclass('strategyos_intent_analyses')").fetchone()
            if not row or row[0] is None:
                raise Unavailable('The dimensional Intent migration has not been installed.')
        yield conn


def initialize():
    """Explicit deployment migration, never invoked by a read or write endpoint."""
    with _connection(check_schema=False) as conn:
        conn.execute(Path(__file__).with_name('sql').joinpath('dimensional_intent.sql').read_text())


def _lock(conn, tenant, plan_id):
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                 (json.dumps([tenant, plan_id]),))


def _row(conn, query, params):
    cur = conn.execute(query, params)
    values = cur.fetchone()
    return dict(zip((col.name for col in cur.description), values)) if values else None


def _checked(row):
    if row is None:
        raise NotFound('Dimensional record not found.')
    if fingerprint(row['payload']) != row['digest']:
        raise Unavailable('Stored dimensional snapshot failed its integrity check.')
    return row


def _plan(conn, tenant, plan_id, version):
    return _checked(_row(conn, '''SELECT * FROM strategyos_intent_plan_versions
        WHERE tenant_key=%s AND plan_id=%s AND version=%s''', (tenant, plan_id, version)))


def _actuals(conn, tenant, revision):
    return _checked(_row(conn, '''SELECT * FROM strategyos_intent_actual_versions
        WHERE tenant_key=%s AND revision=%s''', (tenant, revision)))


def _sources(principal, row, *, kind, verify_bytes=True):
    tenant, _ = _scope(principal)
    value = Plan.model_validate(row['payload']) if kind == 'plan' else Actuals.model_validate(row['payload'])
    references = plan_source_references(value) if kind == 'plan' else actual_source_references(value)
    primary = registered_sources(tenant, row['source_pack_id'], references, verify_bytes=verify_bytes, principal=principal)
    if kind == 'plan' and value.derivation and value.derivation.historical_source_pack_id:
        history_references = [item.basis for item in value.derivation.allocations]
        registered_sources(tenant, value.derivation.historical_source_pack_id, history_references,
                           verify_bytes=verify_bytes, principal=principal)
    return primary


def _public(row):
    return {key: value.isoformat() if isinstance(value, (date, datetime)) else value
            for key, value in row.items() if key != 'tenant_key'}


def _plan_payload(plan):
    payload = plan.model_dump(mode='json')
    payload['cells'].sort(key=lambda c: c['id'])
    payload['price_volume_mix_policies'].sort(key=lambda item: item['bridge_id'])
    for bridge in payload['price_volume_mix_policies']:
        bridge['rows'].sort(key=lambda item: item['member'])
    for members in payload['dimensions'].values():
        members.sort()
    return payload


def _validate_structure_binding(conn, tenant, plan, *, require_current=True):
    """Prove that plan granularity comes from an independently approved tenant structure."""
    if plan.structure is None or plan.business_unit is None:
        raise ValueError('New plan imports require an approved organization-structure version and business-unit scope.')
    binding = plan.structure
    row = _checked(_row(conn, '''SELECT * FROM strategyos_intent_structure_configs
        WHERE tenant_key=%s AND config_id=%s AND version=%s''',
        (tenant, binding.config_id, binding.version)))
    if row['digest'] != binding.digest:
        raise Conflict('Organization structure fingerprint differs from the plan binding.')
    approval = _row(conn, '''SELECT config_digest FROM strategyos_intent_structure_approvals
        WHERE tenant_key=%s AND config_id=%s AND version=%s''',
        (tenant, binding.config_id, binding.version))
    if not approval or approval['config_digest'] != row['digest']:
        raise Conflict('Plans can only use an independently approved organization structure.')
    latest_approved = conn.execute('''SELECT COALESCE(MAX(version),0)
        FROM strategyos_intent_structure_approvals WHERE tenant_key=%s AND config_id=%s''',
        (tenant, binding.config_id)).fetchone()[0]
    if require_current and latest_approved != binding.version:
        raise Conflict('The plan structure is superseded; bind the current approved organization structure.')
    from .tenant_structure import TenantStructureConfiguration
    configuration = TenantStructureConfiguration.model_validate(row['payload'])
    units = {unit.key for unit in configuration.business_units}
    if plan.business_unit not in units:
        raise ValueError('Plan business-unit scope is not present in the approved organization structure.')
    definitions = {dimension.key: dimension for dimension in configuration.dimensions}
    configured = {key: {member.key for member in definition.members}
                  for key, definition in definitions.items()}
    unknown_dimensions = sorted(set(plan.dimensions) - set(configured))
    if unknown_dimensions:
        raise ValueError('Plan dimensions are not present in the approved organization structure: '
                         + ', '.join(unknown_dimensions) + '.')
    for dimension, members in plan.dimensions.items():
        unknown = sorted(set(members) - configured[dimension])
        if unknown:
            raise ValueError(dimension + ' contains members outside the approved organization structure: '
                             + ', '.join(unknown) + '.')
    for dimension in plan.dimensions:
        definition = definitions[dimension]
        parents = {member.key: member.parent for member in definition.members}
        groups = {}
        for cell in plan.cells:
            scope = (cell.metric, tuple(sorted((key, value) for key, value in cell.dimensions.items()
                                               if key != dimension)))
            groups.setdefault(scope, set()).add(cell.dimensions[dimension])
        for members in groups.values():
            for member in members:
                ancestor = parents.get(member)
                while ancestor:
                    if ancestor in members:
                        raise ValueError('Plan cells cannot mix parent and child members of dimension '
                                         + dimension + ' in the same scope.')
                    ancestor = parents.get(ancestor)
    return {'status': 'current' if latest_approved == binding.version else 'superseded',
            'config_id': binding.config_id, 'version': binding.version,
            'digest': binding.digest, 'business_unit': plan.business_unit}


def _structure_status(conn, tenant, plan):
    if plan.structure is None:
        return {'status': 'legacy_unbound'}
    return _validate_structure_binding(conn, tenant, plan, require_current=False)


def _validate_existing_structure(conn, tenant, plan):
    """Enforce current bindings while preserving pre-cutover immutable records."""
    if plan.structure is not None:
        return _validate_structure_binding(conn, tenant, plan)
    return {'status': 'legacy_unbound'}


def import_plan(principal, plan: Plan, source_pack_id: str):
    tenant, actor = _scope(principal, IMPORT_ROLES)
    if plan.company_id != tenant:
        raise PermissionError('Company scope does not match this tenant.')
    if plan.status != 'proposed' or any((plan.ratified_by, plan.ratified_on, plan.ratification)):
        raise ValueError('API imports must be proposals without ratification metadata; use the ratification workflow.')
    if plan.derivation is not None:
        raise ValueError('Derived plans must be created by the decomposition endpoint so lineage can be verified.')
    _key(plan.plan_id)
    payload = _plan_payload(plan)
    encoded = _encode(payload)
    digest = fingerprint(payload)
    _sources(principal, {'payload': payload, 'source_pack_id': source_pack_id}, kind='plan')
    with _connection() as conn:
        _lock(conn, tenant, plan.plan_id)
        _validate_structure_binding(conn, tenant, plan)
        existing = _row(conn, '''SELECT * FROM strategyos_intent_plan_versions
            WHERE tenant_key=%s AND plan_id=%s AND version=%s''', (tenant, plan.plan_id, plan.version))
        if existing:
            _checked(existing)
            if existing['digest'] != digest or existing['source_pack_id'] != source_pack_id:
                raise Conflict('This plan version already has different content; import a new version.')
            return _public(existing)
        latest = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_plan_versions
            WHERE tenant_key=%s AND plan_id=%s''', (tenant, plan.plan_id)).fetchone()[0]
        if plan.version != latest + 1:
            raise Conflict('Import the next consecutive plan version.')
        overlapping = conn.execute('''SELECT 1 FROM strategyos_intent_plan_versions
            WHERE tenant_key=%s AND plan_id=%s
            AND (payload->'period'->>'start')::date <= %s AND (payload->'period'->>'end')::date >= %s
            AND payload->'period' <> %s::jsonb LIMIT 1''',
            (tenant, plan.plan_id, plan.period.end, plan.period.start, json.dumps(payload['period']))).fetchone()
        if overlapping:
            raise Conflict('Overlapping plan revisions must use the same reporting period.')
        conn.execute('''INSERT INTO strategyos_intent_plan_versions
            (tenant_key,plan_id,version,source_pack_id,payload,digest,imported_by)
            VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s)''',
            (tenant, plan.plan_id, plan.version, source_pack_id, encoded, digest, actor))
        return _public(_plan(conn, tenant, plan.plan_id, plan.version))


def create_decomposition(principal, plan_id, version, request):
    """Create one immutable plan proposal from a ratified parent and verified weights."""
    from .plan_decomposition import decompose
    tenant, actor = _scope(principal, IMPORT_ROLES)
    _key(plan_id)
    with _connection() as conn:
        _lock(conn, tenant, plan_id)
        parent = _plan(conn, tenant, plan_id, version)
        _validate_existing_structure(conn, tenant, Plan.model_validate(parent['payload']))
        if parent['digest'] != request.parent_digest:
            raise Conflict('Parent plan fingerprint differs from the version reviewed.')
        approval = _row(conn, '''SELECT version FROM strategyos_intent_ratifications
            WHERE tenant_key=%s AND plan_id=%s AND version=%s''', (tenant, plan_id, version))
        if not approval:
            raise Conflict('Only a ratified plan version can be decomposed.')
        newest_ratified = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_ratifications
            WHERE tenant_key=%s AND plan_id=%s''', (tenant, plan_id)).fetchone()[0]
        latest = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_plan_versions
            WHERE tenant_key=%s AND plan_id=%s''', (tenant, plan_id)).fetchone()[0]
        proposal = decompose(Plan.model_validate(parent['payload']), request, next_version=latest + 1)
        _validate_existing_structure(conn, tenant, proposal)
        payload = _plan_payload(proposal)
        existing = _row(conn, '''SELECT * FROM strategyos_intent_plan_versions
            WHERE tenant_key=%s AND plan_id=%s
              AND payload->'derivation'->>'request_hash'=%s''',
            (tenant, plan_id, payload['derivation']['request_hash']))
        if existing:
            _checked(existing)
            _sources(principal, existing, kind='plan')
            existing_approval = conn.execute('''SELECT 1 FROM strategyos_intent_ratifications
                WHERE tenant_key=%s AND plan_id=%s AND version=%s''',
                (tenant, plan_id, existing['version'])).fetchone()
            if not existing_approval and newest_ratified != version:
                raise Conflict('A newer ratified plan version exists; decompose that version instead.')
            return {**_public(existing), 'governance_status': 'ratified' if existing_approval else 'proposed', 'created_from': {
                'plan_id': plan_id, 'version': version, 'digest': parent['digest']}}
        if newest_ratified != version:
            raise Conflict('A newer ratified plan version exists; decompose that version instead.')
        encoded, digest = _encode(payload), fingerprint(payload)
        _sources(principal, {'payload': payload, 'source_pack_id': parent['source_pack_id']}, kind='plan')
        conn.execute('''INSERT INTO strategyos_intent_plan_versions
            (tenant_key,plan_id,version,source_pack_id,payload,digest,imported_by)
            VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s)''',
            (tenant, plan_id, proposal.version, parent['source_pack_id'], encoded, digest, actor))
        created = _plan(conn, tenant, plan_id, proposal.version)
        return {**_public(created), 'governance_status': 'proposed', 'created_from': {
            'plan_id': plan_id, 'version': version, 'digest': parent['digest']}}


def history_candidates(principal, plan_id, version, parent_cell_id, split_dimension, actual_revision):
    """Preview the disclosed historical observations used to seed a decomposition."""
    from .plan_decomposition import matching_history
    tenant, _ = _scope(principal, IMPORT_ROLES)
    _key(plan_id)
    _key(actual_revision)
    with _connection() as conn:
        parent = _plan(conn, tenant, plan_id, version)
        _validate_existing_structure(conn, tenant, Plan.model_validate(parent['payload']))
        actual_row = _actuals(conn, tenant, actual_revision)
        approval = conn.execute('''SELECT 1 FROM strategyos_intent_ratifications
            WHERE tenant_key=%s AND plan_id=%s AND version=%s''', (tenant, plan_id, version)).fetchone()
        newest = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_ratifications
            WHERE tenant_key=%s AND plan_id=%s''', (tenant, plan_id)).fetchone()[0]
        if not approval or newest != version:
            raise Conflict('Historical decomposition requires the latest ratified plan version.')
    _sources(principal, parent, kind='plan')
    _sources(principal, actual_row, kind='actuals')
    parent_cell, matched = matching_history(Plan.model_validate(parent['payload']),
                                            Actuals.model_validate(actual_row['payload']),
                                            parent_cell_id=parent_cell_id, split_dimension=split_dimension)
    candidates = []
    for member in sorted(matched):
        observation = matched[member]
        candidates.append({
            'member': member,
            'historical_value': str(observation.value) if observation.value is not None else None,
            'unit': observation.unit,
            'source': observation.source.model_dump(mode='json'),
            'readiness': 'ready' if observation.value is not None and observation.value > 0 else 'blocked',
        })
    return {
        'plan_id': plan_id, 'version': version, 'parent_digest': parent['digest'],
        'parent_cell_id': parent_cell.id, 'split_dimension': split_dimension,
        'historical_actual_revision': actual_revision, 'historical_actual_digest': actual_row['digest'],
        'historical_source_pack_id': actual_row['source_pack_id'], 'candidates': candidates,
        'readiness': 'ready' if len(candidates) >= 2 and all(c['readiness'] == 'ready' for c in candidates) else 'blocked',
    }


def create_objective_decomposition(principal, plan_id, version, request):
    """Create one immutable whole-objective proposal across multiple dimensions."""
    from .plan_decomposition import decompose_objective
    tenant, actor = _scope(principal, IMPORT_ROLES)
    _key(plan_id)
    with _connection() as conn:
        _lock(conn, tenant, plan_id)
        parent = _plan(conn, tenant, plan_id, version)
        _validate_existing_structure(conn, tenant, Plan.model_validate(parent['payload']))
        if parent['digest'] != request.parent_digest:
            raise Conflict('Parent plan fingerprint differs from the version reviewed.')
        approval = conn.execute('''SELECT 1 FROM strategyos_intent_ratifications
            WHERE tenant_key=%s AND plan_id=%s AND version=%s''', (tenant, plan_id, version)).fetchone()
        if not approval:
            raise Conflict('Only a ratified plan version can be decomposed.')
        newest_ratified = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_ratifications
            WHERE tenant_key=%s AND plan_id=%s''', (tenant, plan_id)).fetchone()[0]
        if newest_ratified != version:
            raise Conflict('A newer ratified plan version exists; decompose that version instead.')
        latest = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_plan_versions
            WHERE tenant_key=%s AND plan_id=%s''', (tenant, plan_id)).fetchone()[0]
        proposal = decompose_objective(Plan.model_validate(parent['payload']), request, next_version=latest + 1)
        _validate_existing_structure(conn, tenant, proposal)
        payload = _plan_payload(proposal)
        existing = _row(conn, '''SELECT * FROM strategyos_intent_plan_versions
            WHERE tenant_key=%s AND plan_id=%s AND payload->'derivation'->>'request_hash'=%s''',
            (tenant, plan_id, payload['derivation']['request_hash']))
        if existing:
            _checked(existing); _sources(principal, existing, kind='plan')
            existing_approval = conn.execute('''SELECT 1 FROM strategyos_intent_ratifications
                WHERE tenant_key=%s AND plan_id=%s AND version=%s''',
                (tenant, plan_id, existing['version'])).fetchone()
            return {**_public(existing), 'governance_status': 'ratified' if existing_approval else 'proposed',
                    'created_from': {'plan_id': plan_id, 'version': version, 'digest': parent['digest']}}
        encoded, digest = _encode(payload), fingerprint(payload)
        _sources(principal, {'payload': payload, 'source_pack_id': parent['source_pack_id']}, kind='plan')
        conn.execute('''INSERT INTO strategyos_intent_plan_versions
            (tenant_key,plan_id,version,source_pack_id,payload,digest,imported_by)
            VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s)''',
            (tenant, plan_id, proposal.version, parent['source_pack_id'], encoded, digest, actor))
        created = _plan(conn, tenant, plan_id, proposal.version)
        return {**_public(created), 'governance_status': 'proposed', 'created_from': {
            'plan_id': plan_id, 'version': version, 'digest': parent['digest']}}


def create_history_decomposition(principal, plan_id, version, request):
    """Create one immutable proposal from a prior actual mix plus explicit adjustments."""
    from .plan_decomposition import decompose_from_history
    tenant, actor = _scope(principal, IMPORT_ROLES)
    _key(plan_id)
    _key(request.historical_actual_revision)
    with _connection() as conn:
        _lock(conn, tenant, plan_id)
        parent = _plan(conn, tenant, plan_id, version)
        _validate_existing_structure(conn, tenant, Plan.model_validate(parent['payload']))
        actual_row = _actuals(conn, tenant, request.historical_actual_revision)
        if parent['digest'] != request.parent_digest:
            raise Conflict('Parent plan fingerprint differs from the version reviewed.')
        approval = conn.execute('''SELECT 1 FROM strategyos_intent_ratifications
            WHERE tenant_key=%s AND plan_id=%s AND version=%s''', (tenant, plan_id, version)).fetchone()
        if not approval:
            raise Conflict('Only a ratified plan version can be decomposed.')
        newest_ratified = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_ratifications
            WHERE tenant_key=%s AND plan_id=%s''', (tenant, plan_id)).fetchone()[0]
        if newest_ratified != version:
            raise Conflict('A newer ratified plan version exists; decompose that version instead.')
        latest = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_plan_versions
            WHERE tenant_key=%s AND plan_id=%s''', (tenant, plan_id)).fetchone()[0]
        _sources(principal, parent, kind='plan')
        _sources(principal, actual_row, kind='actuals')
        proposal = decompose_from_history(
            Plan.model_validate(parent['payload']), Actuals.model_validate(actual_row['payload']), request,
            next_version=latest + 1, historical_digest=actual_row['digest'],
            historical_source_pack_id=actual_row['source_pack_id'])
        _validate_existing_structure(conn, tenant, proposal)
        payload = _plan_payload(proposal)
        existing = _row(conn, '''SELECT * FROM strategyos_intent_plan_versions
            WHERE tenant_key=%s AND plan_id=%s AND payload->'derivation'->>'request_hash'=%s''',
            (tenant, plan_id, payload['derivation']['request_hash']))
        if existing:
            _checked(existing)
            _sources(principal, existing, kind='plan')
            existing_approval = conn.execute('''SELECT 1 FROM strategyos_intent_ratifications
                WHERE tenant_key=%s AND plan_id=%s AND version=%s''',
                (tenant, plan_id, existing['version'])).fetchone()
            return {**_public(existing), 'governance_status': 'ratified' if existing_approval else 'proposed',
                    'created_from': {'plan_id': plan_id, 'version': version, 'digest': parent['digest']}}
        encoded, digest = _encode(payload), fingerprint(payload)
        conn.execute('''INSERT INTO strategyos_intent_plan_versions
            (tenant_key,plan_id,version,source_pack_id,payload,digest,imported_by)
            VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s)''',
            (tenant, plan_id, proposal.version, parent['source_pack_id'], encoded, digest, actor))
        created = _plan(conn, tenant, plan_id, proposal.version)
        return {**_public(created), 'governance_status': 'proposed', 'created_from': {
            'plan_id': plan_id, 'version': version, 'digest': parent['digest']}}


def import_actuals(principal, actuals: Actuals, source_pack_id: str):
    tenant, actor = _scope(principal, IMPORT_ROLES)
    if actuals.company_id != tenant:
        raise PermissionError('Company scope does not match this tenant.')
    if not actuals.period.end <= actuals.recorded_on <= datetime.now(timezone.utc).date():
        raise ValueError('Actuals must describe a completed period and cannot be future-dated.')
    _key(actuals.revision)
    from .dimensional_plan import cell_key
    keys = [cell_key(o.metric, o.dimensions) for o in actuals.observations]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate actual tuples must be reconciled before import.')
    payload = actuals.model_dump(mode='json')
    payload['observations'].sort(key=lambda o: cell_key(o['metric'], o['dimensions']))
    payload['price_volume_mix'].sort(key=lambda item: item['bridge_id'])
    for bridge in payload['price_volume_mix']:
        bridge['rows'].sort(key=lambda item: item['member'])
    encoded, digest = _encode(payload), fingerprint(payload)
    _sources(principal, {'payload': payload, 'source_pack_id': source_pack_id}, kind='actuals')
    with _connection() as conn:
        conn.execute('''INSERT INTO strategyos_intent_actual_versions
            (tenant_key,revision,source_pack_id,payload,digest,imported_by)
            VALUES (%s,%s,%s,%s::jsonb,%s,%s) ON CONFLICT DO NOTHING''',
            (tenant, actuals.revision, source_pack_id, encoded, digest, actor))
        row = _actuals(conn, tenant, actuals.revision)
        if row['digest'] != digest or row['source_pack_id'] != source_pack_id:
            raise Conflict('This actual revision already has different content; use a new revision.')
        return _public(row)


def read_plan(principal, plan_id, version):
    tenant, actor = _scope(principal)
    with _connection() as conn:
        row = _plan(conn, tenant, plan_id, version)
        grant = _row(conn, '''SELECT enabled FROM strategyos_intent_ratifier_events
            WHERE tenant_key=%s AND plan_id=%s AND subject=%s ORDER BY revision DESC LIMIT 1''',
            (tenant, plan_id, actor))
        approval = _row(conn, '''SELECT approved_by, approved_at, plan_digest, grant_revision, note
            FROM strategyos_intent_ratifications WHERE tenant_key=%s AND plan_id=%s AND version=%s''',
            (tenant, plan_id, version))
        structure = _structure_status(conn, tenant, Plan.model_validate(row['payload']))
    _sources(principal, row, kind='plan')
    return {**_public(row), 'governance_status': 'ratified' if approval else 'proposed',
            'structure': structure,
            'ratification': _public(approval) if approval else None,
            'permissions': {'can_ratify': principal['role'] in RATIFY_ROLES and bool(grant and grant['enabled'])
                            and row['imported_by'] != actor and not approval}}


def read_actuals(principal, revision):
    tenant, _ = _scope(principal)
    with _connection() as conn:
        row = _actuals(conn, tenant, revision)
    _sources(principal, row, kind='actuals')
    return _public(row)


def set_ratifier(principal, plan_id, subject, enabled, expected_revision):
    tenant, actor = _scope(principal, {'tenant_admin'})
    if subject == actor:
        raise PermissionError('Administrators cannot grant ratification rights to themselves.')
    with _connection() as conn:
        _lock(conn, tenant, plan_id)
        if not conn.execute('SELECT 1 FROM strategyos_intent_plan_versions WHERE tenant_key=%s AND plan_id=%s',
                            (tenant, plan_id)).fetchone():
            raise NotFound('Plan not found.')
        row = _row(conn, '''SELECT revision FROM strategyos_intent_ratifier_events
            WHERE tenant_key=%s AND plan_id=%s AND subject=%s ORDER BY revision DESC LIMIT 1''',
            (tenant, plan_id, subject))
        current = row['revision'] if row else 0
        if current != expected_revision:
            raise Conflict('Ratifier permissions changed; refresh before editing.')
        row = _row(conn, '''INSERT INTO strategyos_intent_ratifier_events
            (tenant_key,plan_id,subject,revision,enabled,changed_by) VALUES (%s,%s,%s,%s,%s,%s)
            RETURNING plan_id,subject,revision,enabled,changed_by,changed_at''',
            (tenant, plan_id, subject, current + 1, enabled, actor))
        return _public(row)


def read_ratifier(principal, plan_id, subject):
    tenant, _ = _scope(principal, {'tenant_admin'})
    with _connection() as conn:
        row = _row(conn, '''SELECT plan_id,subject,revision,enabled,changed_by,changed_at
            FROM strategyos_intent_ratifier_events WHERE tenant_key=%s AND plan_id=%s AND subject=%s
            ORDER BY revision DESC LIMIT 1''', (tenant, plan_id, subject))
    return _public(row) if row else {'plan_id': plan_id, 'subject': subject, 'revision': 0, 'enabled': False}


def ratify(principal, plan_id, version, expected_digest, note):
    tenant, actor = _scope(principal, RATIFY_ROLES)
    with _connection() as conn:
        _lock(conn, tenant, plan_id)
        row = _plan(conn, tenant, plan_id, version)
        if row['digest'] != expected_digest:
            raise Conflict('Plan fingerprint differs from the version reviewed.')
        _validate_existing_structure(conn, tenant, Plan.model_validate(row['payload']))
        grant = _row(conn, '''SELECT revision,enabled FROM strategyos_intent_ratifier_events
            WHERE tenant_key=%s AND plan_id=%s AND subject=%s ORDER BY revision DESC LIMIT 1''',
            (tenant, plan_id, actor))
        if not grant or not grant['enabled'] or row['imported_by'] == actor:
            raise PermissionError('A separately authorized ratifier is required.')
        _sources(principal, row, kind='plan')
        existing = _row(conn, '''SELECT * FROM strategyos_intent_ratifications
            WHERE tenant_key=%s AND plan_id=%s AND version=%s''', (tenant, plan_id, version))
        if existing:
            if existing['approved_by'] != actor or existing['note'] != note:
                raise Conflict('This version already has a different ratification record.')
            return _public(existing)
        derivation = row['payload'].get('derivation')
        if derivation:
            parent = _plan(conn, tenant, derivation['parent_plan_id'], derivation['parent_version'])
            if parent['digest'] != derivation['parent_digest']:
                raise Conflict('The decomposition parent failed its lineage integrity check.')
            newest_parent = conn.execute('''SELECT COALESCE(MAX(version),0)
                FROM strategyos_intent_ratifications WHERE tenant_key=%s AND plan_id=%s''',
                (tenant, derivation['parent_plan_id'])).fetchone()[0]
            if newest_parent != derivation['parent_version']:
                raise Conflict('This decomposition is stale because a newer plan version was ratified.')
            if derivation.get('historical_actual_revision'):
                historical = _actuals(conn, tenant, derivation['historical_actual_revision'])
                if (historical['digest'] != derivation['historical_actual_digest'] or
                        historical['source_pack_id'] != derivation['historical_source_pack_id']):
                    raise Conflict('The historical actual snapshot failed its lineage integrity check.')
                _sources(principal, historical, kind='actuals')
        newest = conn.execute('''SELECT COALESCE(MAX(version),0) FROM strategyos_intent_ratifications
            WHERE tenant_key=%s AND plan_id=%s''', (tenant, plan_id)).fetchone()[0]
        if version <= newest:
            raise Conflict('A newer plan version has already been ratified.')
        approval = _row(conn, '''INSERT INTO strategyos_intent_ratifications
            (tenant_key,plan_id,version,plan_digest,approved_by,grant_revision,note)
            VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
            (tenant, plan_id, version, row['digest'], actor, grant['revision'], note))
        return _public(approval)


def create_analysis(principal, plan_id, version, actual_revision, as_of):
    tenant, actor = _scope(principal)
    if as_of > datetime.now(timezone.utc).date():
        raise ValueError('An actual analysis cannot use a future as-of date.')
    with _connection() as conn:
        # Serialize against ratifications so the approved comparator cannot change mid-analysis.
        _lock(conn, tenant, plan_id)
        plan_row, actual_row = _plan(conn, tenant, plan_id, version), _actuals(conn, tenant, actual_revision)
        approval = _row(conn, '''SELECT * FROM strategyos_intent_ratifications
            WHERE tenant_key=%s AND plan_id=%s AND version=%s AND (approved_at AT TIME ZONE 'UTC')::date <= %s ''',
            (tenant, plan_id, version, as_of))
        if actual_row['imported_at'].astimezone(timezone.utc).date() > as_of:
            raise Conflict('This actual revision was imported after the requested as-of date.')
        if not approval:
            raise Conflict('This plan was not ratified by the requested as-of date.')
        newer = conn.execute('''SELECT 1 FROM strategyos_intent_ratifications r
            JOIN strategyos_intent_plan_versions p USING(tenant_key,plan_id,version)
            WHERE r.tenant_key=%s AND r.plan_id=%s AND r.version>%s
            AND (r.approved_at AT TIME ZONE 'UTC')::date <= %s AND p.payload->'period' = %s::jsonb LIMIT 1''',
            (tenant, plan_id, version, as_of, json.dumps(plan_row['payload']['period']))).fetchone()
        if newer:
            raise Conflict('A newer ratified version applies to this reporting period.')
        plan_root, plan_receipt = _sources(principal, plan_row, kind='plan')
        actual_root, actual_receipt = _sources(principal, actual_row, kind='actuals')
        # Evaluate with separately resolved roots; no copying evidence between packs.
        result = evaluate(Plan.model_validate(plan_row['payload']), Actuals.model_validate(actual_row['payload']),
                          source_root=plan_root, actual_source_root=actual_root, company_id=tenant, as_of=as_of)
        result.update(actual_revision=actual_revision, approval_status='ratified', approval_basis='authenticated_plan_scoped_ratification',
                      comparison_basis='ratified_plan', ratification=_public(approval),
                      plan_import_digest=plan_row['digest'], actual_import_digest=actual_row['digest'],
                      source_receipts={'plan': plan_receipt, 'actuals': actual_receipt})
        result['evidence_assurance'] = 'registered_artifact_integrity_not_semantic_value_verification'
        # Include the assurance contract in the immutable identity.
        result.pop('analysis_hash')
        digest = fingerprint(result)
        result['analysis_hash'] = digest
        conn.execute('''INSERT INTO strategyos_intent_analyses
            (tenant_key,analysis_id,plan_id,plan_version,actual_revision,payload,created_by)
            VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING''',
            (tenant, digest, plan_id, version, actual_revision, _encode(result), actor))
        return result


def read_analysis(principal, analysis_id):
    tenant, _ = _scope(principal)
    with _connection() as conn:
        row = _row(conn, 'SELECT * FROM strategyos_intent_analyses WHERE tenant_key=%s AND analysis_id=%s',
                   (tenant, analysis_id))
        if not row:
            raise NotFound('Analysis not found.')
        plan_row = _plan(conn, tenant, row['plan_id'], row['plan_version'])
        actual_row = _actuals(conn, tenant, row['actual_revision'])
    # Eligibility can be revoked; stored historical numbers do not follow changed live bytes.
    _sources(principal, plan_row, kind='plan', verify_bytes=False)
    _sources(principal, actual_row, kind='actuals', verify_bytes=False)
    result = row['payload']
    if result.get('analysis_hash') != analysis_id or fingerprint({k:v for k,v in result.items() if k != 'analysis_hash'}) != analysis_id:
        raise Unavailable('Stored analysis failed its integrity check.')
    return result


def explain_cell(principal, analysis_id, cell_id):
    """Return a deterministic assistant-ready explanation over one saved cell."""
    result = read_analysis(principal, analysis_id)
    cell = next((item for item in result['cells'] if item['cell_id'] == cell_id), None)
    if cell is None:
        raise NotFound('Analysis cell not found.')
    dimensions = ', '.join(key + '=' + value for key, value in sorted(cell['dimensions'].items()))
    if cell['actual'] is None:
        statement = ('No measured actual is available for ' + dimensions + '; the ratified target is ' +
                     cell['target'] + ' ' + cell['unit'] + '.')
    else:
        statement = (dimensions + ' is ' + cell['status'].replace('_', ' ') + ': actual ' + cell['actual'] +
                     ' ' + cell['unit'] + ' versus ratified target ' + cell['target'] + ', a variance of ' +
                     cell['variance'] + '. Accountable owner: ' + cell['owner'] + '.')
    citations = [{"side": "plan", **cell['plan_source']}]
    if cell['actual_source']:
        citations.append({"side": "actuals", **cell['actual_source']})
    related = [finding['finding_id'] for finding in result.get('findings', [])
               if cell_id == finding.get('cell_id') or any(item.get('cell_id') == cell_id
                                                            for item in finding.get('cells', []))]
    return {
        'analysis_id': analysis_id, 'cell_id': cell_id, 'answer': statement,
        'facts': {key: cell.get(key) for key in ('metric', 'dimensions', 'owner', 'unit', 'target', 'tolerance',
                                                 'actual', 'variance', 'variance_percent', 'status')},
        'plan_citation': {'plan_id': result['plan_id'], 'version': result['plan_version'],
                          'digest': result['plan_import_digest'], 'ratified_by': result['ratification']['approved_by'],
                          'ratified_at': result['ratification']['approved_at']},
        'evidence': citations, 'related_findings': related,
        'assurance': result['evidence_assurance'],
    }


def catalog(principal, offset=0, limit=25, *, qa_plan_id=None):
    tenant, actor = _scope(principal)
    if offset < 0 or not 1 <= limit <= 50:
        raise ValueError('Invalid catalog page.')
    with _connection() as conn:
        plan_cursor = conn.execute("""SELECT p.*, r.approved_at FROM strategyos_intent_plan_versions p
            LEFT JOIN strategyos_intent_ratifications r USING(tenant_key,plan_id,version)
            WHERE p.tenant_key=%s AND (
              (COALESCE(p.payload->>'catalog_visibility','customer')='quality_assurance' AND p.plan_id=%s)
              OR (COALESCE(p.payload->>'catalog_visibility','customer')='customer'
                  AND p.plan_id NOT LIKE 'human-plan-%%' AND p.plan_id NOT LIKE 'SYNTHETIC-%%')
            ) ORDER BY p.imported_at DESC,p.plan_id,p.version DESC LIMIT %s OFFSET %s""",
            (tenant, qa_plan_id, limit + 1, offset))
        plans = [dict(zip([c.name for c in plan_cursor.description], row)) for row in plan_cursor.fetchall()]
        actual_cursor = conn.execute("""SELECT * FROM strategyos_intent_actual_versions WHERE tenant_key=%s
            ORDER BY imported_at DESC,revision LIMIT %s OFFSET %s""", (tenant, limit + 1, offset))
        actuals = [dict(zip([c.name for c in actual_cursor.description], row)) for row in actual_cursor.fetchall()]
        analysis_cursor = conn.execute("""SELECT DISTINCT ON (plan_id,plan_version)
            plan_id,plan_version,analysis_id,actual_revision,payload,created_at
            FROM strategyos_intent_analyses WHERE tenant_key=%s
            ORDER BY plan_id,plan_version,created_at DESC,analysis_id DESC""", (tenant,))
        analyses = [dict(zip([c.name for c in analysis_cursor.description], row))
                    for row in analysis_cursor.fetchall()]
        analysis_actual_cursor = conn.execute("""SELECT * FROM strategyos_intent_actual_versions
            WHERE tenant_key=%s AND revision IN (
              SELECT actual_revision FROM strategyos_intent_analyses WHERE tenant_key=%s
            )""", (tenant, tenant))
        analysis_actuals = {
            row['revision']: row
            for row in (
                dict(zip([c.name for c in analysis_actual_cursor.description], values))
                for values in analysis_actual_cursor.fetchall()
            )
        }
    visible_plans, visible_actuals = [], []
    from .dimensional_intent_sources import SourceUnavailable
    for kind, records, visible in [('plan', plans, visible_plans), ('actuals', actuals, visible_actuals)]:
        for row in records[:limit]:
            _checked(row)
            value = Plan.model_validate(row['payload']) if kind == 'plan' else None
            if kind == 'plan':
                legacy_qa = value.catalog_visibility == 'customer' and row['plan_id'].startswith(
                    ('human-plan-', 'SYNTHETIC-'))
                if value.catalog_visibility == 'quality_assurance':
                    if qa_plan_id != row['plan_id']:
                        continue
                elif legacy_qa:
                    continue
            try:
                _sources(principal, row, kind=kind, verify_bytes=False)
            except (PermissionError, SourceUnavailable):
                continue  # Do not disclose names from revoked/unavailable sources.
            item = {'period': row['payload']['period'], 'imported_at': row['imported_at'].isoformat()}
            if kind == 'plan':
                item.update(plan_id=row['plan_id'], version=row['version'], digest=row['digest'],
                            governance_status='ratified' if row['approved_at'] else 'proposed',
                            display_name=value.display_name or row['plan_id'],
                            planned_totals=[{'metric': key, 'unit': definition.unit,
                                             'planned_total': str(definition.planned_total)}
                                            for key, definition in sorted(value.metrics.items())])
            else:
                item.update(revision=row['revision'])
            visible.append(item)
    analysis_by_plan = {(item['plan_id'], item['plan_version']): item for item in analyses}
    for item in visible_plans:
        analysis = analysis_by_plan.get((item['plan_id'], item['version']))
        actual_row = analysis_actuals.get(analysis['actual_revision']) if analysis else None
        if not analysis or not actual_row:
            continue
        try:
            _checked(actual_row)
            _sources(principal, actual_row, kind='actuals', verify_bytes=False)
        except (PermissionError, SourceUnavailable):
            continue
        payload = analysis['payload']
        if (payload.get('analysis_hash') != analysis['analysis_id'] or fingerprint(
                {key: value for key, value in payload.items() if key != 'analysis_hash'}) != analysis['analysis_id']):
            continue
        item['latest_analysis'] = {
            'analysis_id': analysis['analysis_id'], 'as_of': payload.get('as_of'),
            'period': payload.get('period'),
            'rollups': [
                {key: rollup.get(key) for key in (
                    'metric', 'unit', 'target', 'actual', 'variance', 'status',
                    'planned_cells', 'measured_cells', 'offset_detected',
                )}
                for rollup in (payload.get('rollups') or [])
            ],
            'granular_stories': payload.get('granular_stories') or [],
            'created_at': analysis['created_at'].isoformat(),
        }
    return {'plans': visible_plans, 'actuals': visible_actuals,
            'next_offset': offset + limit if len(plans) > limit or len(actuals) > limit else None,
            'subject': actor, 'today': datetime.now(timezone.utc).date().isoformat(),
            'permissions': {'can_import': principal['role'] in IMPORT_ROLES,
                            'can_manage_ratifiers': principal['role'] == 'tenant_admin'}}


def plan_evidence_bytes(principal, plan_id, version, cell_id):
    tenant, _ = _scope(principal)
    record = read_plan(principal, plan_id, version)
    cell = next((c for c in record['payload']['cells'] if c['id'] == cell_id), None)
    if not cell:
        raise NotFound('Cell evidence not found.')
    from .strategy_compiler import SourceReference
    source = SourceReference.model_validate(cell['source'])
    root, _ = registered_sources(tenant, record['source_pack_id'], [source], principal=principal, purpose='export')
    return _evidence_content(root, source)


def _evidence_content(root, source):
    from .dimensional_intent_sources import SourceUnavailable
    try:
        data = (root / source.path).read_bytes()
    except OSError as exc:
        raise SourceUnavailable('Evidence is no longer available.') from exc
    if hashlib.sha256(data).hexdigest() != source.sha256:
        raise SourceUnavailable('Evidence changed during retrieval.')
    return Path(source.path).name, data


def evidence_bytes(principal, analysis_id, cell_id, side):
    tenant, _ = _scope(principal)
    bridge_sides = {
        'plan_price': 'plan_price_source', 'plan_volume': 'plan_volume_source',
        'actual_price': 'actual_price_source', 'actual_volume': 'actual_volume_source',
    }
    if side not in {'plan', 'actuals', *bridge_sides}:
        raise ValueError('Choose a declared plan, actual, price or volume evidence input.')
    result = read_analysis(principal, analysis_id)
    if side in {'plan', 'actuals'}:
        cell = next((c for c in result['cells'] if c['cell_id'] == cell_id), None)
        reference = cell.get('plan_source' if side == 'plan' else 'actual_source') if cell else None
        pack_side = side
    else:
        row = next((row for bridge in result.get('price_volume_mix', []) for row in bridge.get('rows', [])
                    if row.get('cell_id') == cell_id), None)
        reference = row.get(bridge_sides[side]) if row else None
        pack_side = 'plan' if side.startswith('plan_') else 'actuals'
    if not reference:
        raise NotFound('Cell evidence not found.')
    from .strategy_compiler import SourceReference
    source = SourceReference.model_validate(reference)
    root, _ = registered_sources(tenant, result['source_receipts'][pack_side]['source_pack_id'], [source], principal=principal, purpose='export')
    return _evidence_content(root, source)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Install the additive dimensional Intent database schema.')
    parser.add_argument('--initialize', action='store_true', required=True)
    parser.parse_args()
    initialize()
    print('Dimensional Intent schema installed.')
