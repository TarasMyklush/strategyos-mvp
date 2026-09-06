"""Explicit handoff from tenant-scoped staged bytes to governed evidence."""
import hashlib
import json
import mimetypes
from pathlib import Path

from .claim_store import ClaimRepository
from .source_claims import EvidenceOccurrence, PolicyContext, SourceAccessPolicy, SourceRegistration, UsePurpose

MAX_ARTIFACT_BYTES = 5 * 1024 * 1024


def register_staged_evidence(source_pack_id: str, relative_path: str, *,
                             context: PolicyContext, repository: ClaimRepository | None = None) -> dict:
    from .source_pack import _source_pack_dir, normalize_source_contract
    if context.purpose != UsePurpose.OPERATIONS or not context.roles.intersection({'operator', 'tenant_admin', 'system'}):
        raise PermissionError('Operator authority is required to register evidence.')
    root = _source_pack_dir(source_pack_id)
    try:
        payload = json.loads((root / 'summary.json').read_text(encoding='utf8'))
    except (OSError, ValueError):
        raise PermissionError('Staged source is not available in the authorized workspace.') from None
    if (payload.get('tenant_context') or {}).get('tenant_id') != context.tenant_id:
        raise PermissionError('Staged source is not available in the authorized workspace.')
    contract = normalize_source_contract(source_pack_id=source_pack_id,
        source_kind=payload.get('source_kind', 'unknown'), contract=payload.get('source_contract'))
    if contract['classification_status'] != 'confirmed':
        raise ValueError('Confirm the source classification and permissions before registering evidence.')
    rights = contract.get('access_policy') or {}
    policy = SourceAccessPolicy(source_key=contract['source_key'],
        allowed_roles=frozenset(rights.get('allowed_roles') or ()),
        allowed_purposes=frozenset(rights.get('allowed_purposes') or ()),
        allowed_business_units=frozenset(rights.get('allowed_business_units') or ()),
        **{key: rights.get(key, False) for key in ('storage_allowed', 'index_allowed', 'export_allowed', 'quote_allowed', 'external_model_allowed')})
    if not policy.storage_allowed or not context.roles.intersection(policy.allowed_roles) or context.purpose not in policy.allowed_purposes:
        raise PermissionError('Source rights do not permit evidence registration for this principal.')
    if context.business_units and (not policy.allowed_business_units or not policy.allowed_business_units.issubset(context.business_units)):
        raise PermissionError('The source scope exceeds this principal\'s business-unit authority.')
    matches = [item for item in payload.get('manifest', []) if item.get('relative_path') == relative_path]
    if len(matches) != 1:
        raise ValueError('Choose one file from the staged manifest.')
    raw = (root / 'raw').resolve()
    candidate = raw / relative_path
    resolved = candidate.resolve()
    if not resolved.is_relative_to(raw) or resolved == raw or any(part.is_symlink() for part in (candidate, *candidate.parents) if part.is_relative_to(raw)):
        raise ValueError('Evidence must be an unchanged regular file within the staged source.')
    try:
        if not resolved.is_file() or resolved.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ValueError('Evidence registration accepts regular files up to 5 MiB.')
        with resolved.open('rb') as stream:
            content = stream.read(MAX_ARTIFACT_BYTES + 1)
    except OSError:
        raise ValueError('The staged file is no longer available. Stage it again.') from None
    digest = hashlib.sha256(content).hexdigest()
    if len(content) > MAX_ARTIFACT_BYTES or digest != matches[0].get('sha256'):
        raise ValueError('The staged file no longer matches its recorded hash. Stage it again.')
    source = SourceRegistration(tenant_id=context.tenant_id, source_key=contract['source_key'],
        display_name=contract['display_name'], origin_category=contract['origin_category'],
        capture_method=contract['capture_method'], governed_owner=contract['governed_owner'],
        authorization_basis=contract['authorization_basis'], provider_name=contract['provider_name'],
        license_policy_ref=contract['license_policy_ref'])
    repo = repository or ClaimRepository()
    registration = repo.register_source(source, policy=policy, recorded_by=context.principal_id,
        rationale='Explicit staged-file evidence registration', create_only=True)
    occurrence = EvidenceOccurrence(tenant_id=context.tenant_id, source_key=source.source_key,
        artifact_hash=digest, source_native_id=relative_path, source_native_version=digest,
        original_uri=f'source-pack://{source_pack_id}/{relative_path}', locator=relative_path,
        occurrence_metadata={'source_pack_id':source_pack_id, 'recorded_by':context.principal_id})
    recorded = repo.record_occurrence(occurrence, context=context, artifact={
        'source_path':relative_path, 'file_name':Path(relative_path).name, 'size_bytes':len(content),
        'media_type':mimetypes.guess_type(relative_path)[0], 'source_pack_id':source_pack_id})
    return {'status':'registered', **recorded, 'source_key':source.source_key,
        'source_registration_version':registration['registration_version'], 'source_hash':digest,
        'relative_path':relative_path, 'claims_created':0, 'analysis_started':False,
        'outbound_delivery':False, 'notice':'Evidence registered. Interpret its cells separately; no claim has been approved.'}
