import pytest
from strategyos_mvp import access_scope, claim_store


@pytest.mark.parametrize("decision", [True, False, "unavailable"])
def test_legacy_read_uses_current_source_policy(monkeypatch, decision):
    class Repository:
        def run_source_access(self, run_id, *, context):
            assert run_id == "run-1"
            assert context.tenant_id == "tenant-a"
            assert context.roles == frozenset({"executive"})
            assert context.purpose == "executive_briefing"
            if decision == "unavailable":
                raise RuntimeError("unavailable")
            return {"allowed": decision}
    monkeypatch.setattr(claim_store, "ClaimRepository", Repository)
    token = access_scope.principal_scope.set({
        "tenant_id": "tenant-a", "subject": "ceo", "role": "executive",
        "_source_read_request": True,
    })
    try:
        assert access_scope.source_read_allowed("run-1") is (decision is True)
        summary = {"run_id": "run-1", "tenant_context": {"tenant_id": "tenant-a"}}
        if decision is True:
            access_scope.guard_summary(summary)
        else:
            with pytest.raises(PermissionError):
                access_scope.guard_summary(summary)
    finally:
        access_scope.principal_scope.reset(token)


def test_source_check_does_not_prevent_establishing_ingestion_batch(monkeypatch):
    monkeypatch.setattr(claim_store, "ClaimRepository", lambda: pytest.fail("Read-only gate on write"))
    token = access_scope.principal_scope.set({"tenant_id": "tenant-a", "role": "operator"})
    try:
        access_scope.guard_source_read("new-run")
    finally:
        access_scope.principal_scope.reset(token)
