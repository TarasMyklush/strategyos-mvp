from uuid import uuid4
import pytest
from strategyos_mvp.source_claims import PolicyContext
from tests.test_cross_source_postgres_e2e import ledger

pytestmark=pytest.mark.integration


def test_uuid_shaped_tenant_slug_cannot_redirect_ledger_authority(ledger):
    import psycopg
    repo,url,tenant=ledger
    missing=str(uuid4())
    with psycopg.connect(url) as conn:
        conn.execute("INSERT INTO strategyos_tenants(slug,display_name) VALUES (%s,'Synthetic alias collision'),(%s,'Synthetic missing-id alias')",(tenant,missing))
    def context(reference):
        return PolicyContext(tenant_id=reference,principal_id='qa',roles=frozenset({'executive'}),purpose='executive_briefing')
    assert repo.resolve_context(context(tenant)).tenant_id==tenant
    with pytest.raises(KeyError): repo.resolve_context(context(missing))
