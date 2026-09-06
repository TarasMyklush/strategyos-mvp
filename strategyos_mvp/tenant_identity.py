"""Unambiguous tenant references for the authoritative source ledger."""
from uuid import UUID


def resolve_tenant_reference(cur, reference):
    value = str(reference or '').strip()
    if not value:
        raise KeyError('Tenant not found.')
    try:
        identifier = str(UUID(value))
    except ValueError:
        cur.execute('select id from strategyos_tenants where slug = %s', (value,))
    else:
        # A UUID is an identity, never a competing tenant's slug alias.
        cur.execute('select id from strategyos_tenants where id = %s::uuid', (identifier,))
    row = cur.fetchone()
    if row is None:
        raise KeyError('Tenant not found.')
    return row[0]
