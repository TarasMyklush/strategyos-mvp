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
from .dimensional_plan import Actuals, Plan, evaluate, fingerprint
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


def _sources(tenant, row, *, kind, verify_bytes=True):
    value = Plan.model_validate(row['payload']) if kind == 'plan' else Actuals.model_validate(row['payload'])
    references = [c.source for c in value.cells] if kind == 'plan' else [o.source for o in value.observations]
    return registered_sources(tenant, row['source_pack_id'], references, verify_bytes=verify_bytes)


def _public(row):
    return {key: value.isoformat() if isinstance(value, (date, datetime)) else value
            for key, value in row.items() if key != 'tenant_key'}


def _plan_payload(plan):
    payload = plan.model_dump(mode='json')
    payload['cells'].sort(key=lambda c: c['id'])
    for members in payload['dimensions'].values():
        members.sort()
    return payload


def import_plan(principal, plan: Plan, source_pack_id: str):
    tenant, actor = _scope(principal, IMPORT_ROLES)
    if plan.company_id != tenant:
        raise PermissionError('Company scope does not match this tenant.')
    if plan.status != 'proposed' or any((plan.ratified_by, plan.ratified_on, plan.ratification)):
        raise ValueError('API imports must be proposals without ratification metadata; use the ratification workflow.')
    _key(plan.plan_id)
    payload = _plan_payload(plan)
    encoded = _encode(payload)
    digest = fingerprint(payload)
    _sources(tenant, {'payload': payload, 'source_pack_id': source_pack_id}, kind='plan')
    with _connection() as conn:
        _lock(conn, tenant, plan.plan_id)
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
    encoded, digest = _encode(payload), fingerprint(payload)
    _sources(tenant, {'payload': payload, 'source_pack_id': source_pack_id}, kind='actuals')
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
    _sources(tenant, row, kind='plan')
    return {**_public(row), 'governance_status': 'ratified' if approval else 'proposed',
            'ratification': _public(approval) if approval else None,
            'permissions': {'can_ratify': principal['role'] in RATIFY_ROLES and bool(grant and grant['enabled'])
                            and row['imported_by'] != actor and not approval}}


def read_actuals(principal, revision):
    tenant, _ = _scope(principal)
    with _connection() as conn:
        row = _actuals(conn, tenant, revision)
    _sources(tenant, row, kind='actuals')
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
        grant = _row(conn, '''SELECT revision,enabled FROM strategyos_intent_ratifier_events
            WHERE tenant_key=%s AND plan_id=%s AND subject=%s ORDER BY revision DESC LIMIT 1''',
            (tenant, plan_id, actor))
        if not grant or not grant['enabled'] or row['imported_by'] == actor:
            raise PermissionError('A separately authorized ratifier is required.')
        _sources(tenant, row, kind='plan')
        existing = _row(conn, '''SELECT * FROM strategyos_intent_ratifications
            WHERE tenant_key=%s AND plan_id=%s AND version=%s''', (tenant, plan_id, version))
        if existing:
            if existing['approved_by'] != actor or existing['note'] != note:
                raise Conflict('This version already has a different ratification record.')
            return _public(existing)
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
        plan_root, plan_receipt = _sources(tenant, plan_row, kind='plan')
        actual_root, actual_receipt = _sources(tenant, actual_row, kind='actuals')
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
    _sources(tenant, plan_row, kind='plan', verify_bytes=False)
    _sources(tenant, actual_row, kind='actuals', verify_bytes=False)
    result = row['payload']
    if result.get('analysis_hash') != analysis_id or fingerprint({k:v for k,v in result.items() if k != 'analysis_hash'}) != analysis_id:
        raise Unavailable('Stored analysis failed its integrity check.')
    return result


def catalog(principal, offset=0, limit=25):
    tenant, actor = _scope(principal)
    if offset < 0 or not 1 <= limit <= 50:
        raise ValueError('Invalid catalog page.')
    with _connection() as conn:
        plan_cursor = conn.execute("""SELECT p.*, r.approved_at FROM strategyos_intent_plan_versions p
            LEFT JOIN strategyos_intent_ratifications r USING(tenant_key,plan_id,version)
            WHERE p.tenant_key=%s ORDER BY p.imported_at DESC,p.plan_id,p.version DESC LIMIT %s OFFSET %s""",
            (tenant, limit + 1, offset))
        plans = [dict(zip([c.name for c in plan_cursor.description], row)) for row in plan_cursor.fetchall()]
        actual_cursor = conn.execute("""SELECT * FROM strategyos_intent_actual_versions WHERE tenant_key=%s
            ORDER BY imported_at DESC,revision LIMIT %s OFFSET %s""", (tenant, limit + 1, offset))
        actuals = [dict(zip([c.name for c in actual_cursor.description], row)) for row in actual_cursor.fetchall()]
    visible_plans, visible_actuals = [], []
    from .dimensional_intent_sources import SourceUnavailable
    for kind, records, visible in [('plan', plans, visible_plans), ('actuals', actuals, visible_actuals)]:
        for row in records[:limit]:
            _checked(row)
            try:
                _sources(tenant, row, kind=kind, verify_bytes=False)
            except (PermissionError, SourceUnavailable):
                continue  # Do not disclose names from revoked/unavailable sources.
            item = {'period': row['payload']['period'], 'imported_at': row['imported_at'].isoformat()}
            if kind == 'plan':
                item.update(plan_id=row['plan_id'], version=row['version'], digest=row['digest'],
                            governance_status='ratified' if row['approved_at'] else 'proposed')
            else:
                item.update(revision=row['revision'])
            visible.append(item)
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
    root, _ = registered_sources(tenant, record['source_pack_id'], [source])
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
    if side not in {'plan', 'actuals'}:
        raise ValueError('Choose plan or actuals evidence.')
    result = read_analysis(principal, analysis_id)
    cell = next((c for c in result['cells'] if c['cell_id'] == cell_id), None)
    reference = cell.get('plan_source' if side == 'plan' else 'actual_source') if cell else None
    if not reference:
        raise NotFound('Cell evidence not found.')
    from .strategy_compiler import SourceReference
    source = SourceReference.model_validate(reference)
    root, _ = registered_sources(tenant, result['source_receipts'][side]['source_pack_id'], [source])
    return _evidence_content(root, source)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Install the additive dimensional Intent database schema.')
    parser.add_argument('--initialize', action='store_true', required=True)
    parser.parse_args()
    initialize()
    print('Dimensional Intent schema installed.')
