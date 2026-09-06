"""Explicit synthetic source grants for twin HTTP controller unit tests."""
import pytest
from strategyos_mvp import api, claim_store
from strategyos_mvp.config import load_config


@pytest.fixture(autouse=True)
def authorized_source_fixture(monkeypatch):
    grant_controller_source(monkeypatch)


def grant_controller_source(monkeypatch):
    # Real ACL/revocation behavior is covered by PostgreSQL source-scope tests.
    class Repository:
        def resolve_context(self, context): return context
        def run_source_access(self, run_id, *, context): return {'allowed': True}
    monkeypatch.setattr(claim_store,'ClaimRepository',Repository)
    monkeypatch.setattr(api,'_latest_summary',lambda:{'run_id':'twin-controller-fixture',
        'tenant_context':{'tenant_id':load_config().tenant_slug}})
    monkeypatch.setattr(api,'_summary_with_governed_claim_snapshot',lambda summary,**kwargs:summary)


def one_scoped_repository(root):
    from strategyos_mvp.twins.store import build_repositories
    scopes = list((root/'governed-v1').iterdir())
    assert len(scopes)==1
    return build_repositories(scopes[0])
