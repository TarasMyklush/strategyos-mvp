"""Request-owned PostgreSQL session context, cleared on every pool boundary.

This prepares the connection boundary for row policies; it does not grant a
tenant, enable RLS, or supply authority for background jobs. Context comes only
from verified middleware, never a claim/query parameter or model payload.
"""
from typing import Any, Mapping

from .tenant_identity import resolve_tenant_reference


def _write_context(conn: Any, tenant_key: str, tenant_uuid: str) -> None:
    with conn.cursor() as cur:
        cur.execute("""SELECT set_config('strategyos.tenant_key',%s,false),
            set_config('strategyos.tenant_uuid',%s,false)""",(tenant_key,tenant_uuid))
    # Session scope deliberately survives application commits; the pool return
    # path clears it, including after rollback and failed requests.
    conn.commit()


def bind_connection_context(conn: Any, principal: Mapping[str, Any] | None) -> None:
    from psycopg.pq import TransactionStatus
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise RuntimeError('A database checkout must not inherit an active transaction.')
    if principal is None or principal.get('role') == 'public':
        _write_context(conn,'','')
        return
    if (not principal.get('_verified_for_request') or principal.get('auth_disabled')
            or not principal.get('subject') or not principal.get('role')):
        raise RuntimeError('Database tenant context requires a verified request identity.')
    tenant_key=str(principal.get('tenant_id') or '').strip()
    # The tenants table is itself protected. Bind the signed tenant reference
    # first so PostgreSQL exposes only the matching slug/UUID candidate; then
    # resolve ambiguity and bind the canonical UUID used by all child policies.
    _write_context(conn,tenant_key,'')
    with conn.cursor() as cur:
        tenant_uuid=str(resolve_tenant_reference(cur,tenant_key))
    _write_context(conn,tenant_key,tenant_uuid)


def bind_runtime_context(
    conn: Any,
    *,
    runtime_scope: str,
    principal: Mapping[str, Any] | None,
) -> None:
    """Prepare one pooled checkout for its database-enforced runtime identity.

    Request identities receive only the tenant asserted by verified middleware.
    Background identities receive no request tenant; their narrowly scoped RLS
    authority is derived by PostgreSQL from the provisioned login role, never
    from an application-controlled setting.
    """
    scope = str(runtime_scope or "").strip().lower()
    if scope == "request":
        bind_connection_context(conn, principal)
        return
    if scope in {"worker", "projector"}:
        bind_connection_context(conn, None)
        return
    raise RuntimeError("Unsupported database runtime scope.")


def clear_connection_context(conn: Any) -> None:
    # No work from a failed request may be committed as part of cleanup.
    conn.rollback()
    _write_context(conn,'','')
