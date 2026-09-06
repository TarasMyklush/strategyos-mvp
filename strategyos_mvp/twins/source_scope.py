"""Bind persisted twin work to an authorized tenant and immutable run context.

Legacy root-level JSON files are preserved but never inherited by an
authenticated workspace. This prevents cached work from bypassing revocation.
"""
from contextvars import ContextVar
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

bound_surface: ContextVar[dict[str, Any] | None] = ContextVar('twin_source_surface', default=None)


def authorized_surface() -> dict[str, Any] | None:
    from ..access_scope import principal_scope
    from ..config import load_config
    from ..claim_store import ClaimRepository
    from ..source_claims import PolicyContext, UsePurpose
    from .. import api
    actor = principal_scope.get()
    config = load_config()
    if (actor and actor.get('auth_disabled')) or (actor is None and not config.api_auth_enabled):
        return None  # Explicit isolated/offline runtime, not authenticated HTTP.
    if actor is None:
        raise PermissionError('Twin execution needs an authenticated source scope; background work cannot invent one.')
    identity = (str(actor.get('tenant_id') or ''), str(actor.get('subject') or ''), str(actor.get('role') or ''),
                tuple(sorted(actor.get('business_units') or ())))
    if not all(identity[:3]):
        raise PermissionError('An authenticated, source-authorized twin workspace is required.')
    cached = bound_surface.get()
    if cached and cached['identity'] == identity:
        return cached
    summary = api._latest_summary()
    run = str((summary or {}).get('_backing_run_id') or (summary or {}).get('run_id') or '')
    if not run:
        raise PermissionError('No source-authorized analysis is available for this twin workspace.')
    try:
        repo = ClaimRepository()
        context = repo.resolve_context(PolicyContext(tenant_id=identity[0],principal_id=identity[1],
            roles=frozenset({identity[2]}),business_units=frozenset(identity[3]),
            purpose=UsePurpose.EXECUTIVE_BRIEFING))
        access = repo.run_source_access(run, context=context)
    except (RuntimeError, KeyError, ValueError):
        raise PermissionError('Twin source permissions are unavailable; saved work was not returned.') from None
    if access.get('allowed') is not True:
        raise PermissionError('Twin source permissions do not allow this analysis or saved work.')
    summary = api._summary_with_governed_claim_snapshot(summary, principal={
        **actor, 'tenant_id':context.tenant_id})
    result = {'identity':identity,'tenant_id':context.tenant_id,'run_id':run,'summary':summary}
    if principal_scope.get() is not None:
        bound_surface.set(result)  # Reset at the HTTP request boundary.
    return result


def scoped_directory(root: Path) -> Path:
    scope = authorized_surface()
    if scope is None:
        return root
    # Source scope and actor are part of cache identity; neither source roles nor
    # guesses about organization-wide sharing grant access to another inbox.
    identity = json.dumps([scope['tenant_id'],scope['run_id'],scope['identity']], separators=(',',':'))
    return root / 'governed-v1' / sha256(identity.encode()).hexdigest()
