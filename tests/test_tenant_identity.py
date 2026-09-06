from unittest.mock import MagicMock
from uuid import uuid4
import pytest
from strategyos_mvp.tenant_identity import resolve_tenant_reference


def test_uuid_reference_never_matches_another_tenants_slug():
    cur=MagicMock()
    value=str(uuid4())
    cur.fetchone.return_value=(value,)
    assert resolve_tenant_reference(cur,value.upper())==value
    sql,parameters=cur.execute.call_args.args
    assert 'slug' not in sql and parameters==(value,)


def test_ordinary_slug_is_resolved_only_as_a_slug():
    cur=MagicMock()
    cur.fetchone.return_value=('canonical-id',)
    assert resolve_tenant_reference(cur,'tenant-a')=='canonical-id'
    assert cur.execute.call_args.args==('select id from strategyos_tenants where slug = %s',('tenant-a',))


def test_missing_tenant_is_not_guessed():
    cur=MagicMock()
    cur.fetchone.return_value=None
    with pytest.raises(KeyError): resolve_tenant_reference(cur,str(uuid4()))
    with pytest.raises(KeyError): resolve_tenant_reference(cur,'')
