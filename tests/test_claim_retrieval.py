from dataclasses import replace
import pytest
from strategyos_mvp.claim_retrieval import search_claims
from test_source_claims import context, query


def test_projection_is_never_returned_without_ledger_authorization():
    class Repository:
        def resolve_context(self, ctx):
            return ctx
        def query(self, q, *, context, revision_ids):
            assert revision_ids == ["denied", "current", "stale"]
            return [{"claim_revision_id": "current", "value": "authoritative"}]
    result = search_claims("revenue", query=query(), context=context(), repository=Repository(),
                           candidates=lambda *a, **k: ["denied", "current", "stale", "current"])
    assert result == [{"claim_revision_id": "current", "value": "authoritative"}]


def test_search_rejects_tenant_and_purpose_laundering_before_embedding():
    for changed in [replace(query(), tenant_id="other"), replace(query(), purpose="external_model")]:
        with pytest.raises(ValueError, match="authenticated"):
            search_claims("revenue", query=changed, context=context())


def test_search_failure_does_not_return_projection_fallback():
    class Repository:
        def resolve_context(self, ctx): return ctx
        def query(self, *a, **k): raise RuntimeError("ledger unavailable")
    with pytest.raises(RuntimeError, match="ledger unavailable"):
        search_claims("revenue", query=query(), context=context(), repository=Repository(),
                      candidates=lambda *a, **k: ["cached-record"])
