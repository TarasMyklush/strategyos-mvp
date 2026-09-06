from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from strategyos_mvp import claim_api
from strategyos_mvp.source_claims import ClaimKind, UsePurpose


def test_claim_endpoint_passes_authenticated_policy_context(monkeypatch):
    captured = {}

    class FakeRepository:
        def query(self, query, *, context):
            captured["query"] = query
            captured["context"] = context
            return [{"claim_revision_id": "revision-1", "label": "Actual"}]

    monkeypatch.setattr(claim_api, "ClaimRepository", FakeRepository)
    result = claim_api.query_claims(
        metric_key="revenue",
        claim_kind=[ClaimKind.ACTUAL],
        purpose=UsePurpose.EXECUTIVE_BRIEFING,
        business_unit="tamween",
        scenario_key=None,
        as_of="2026-06-30T23:59:00Z",
        principal={
            "tenant_id": "tenant-1",
            "subject": "ceo-1",
            "role": "executive",
            "business_units": ["tamween"],
        },
    )
    assert result["records"][0]["label"] == "Actual"
    assert captured["query"].as_of_at == datetime(2026, 6, 30, 23, 59, tzinfo=UTC)
    assert captured["context"].business_units == frozenset({"tamween"})


def test_claim_endpoint_rejects_timezone_free_as_of():
    with pytest.raises(HTTPException, match="timezone"):
        claim_api._timestamp("2026-06-30T23:59:00")


def test_claim_router_is_registered_on_application():
    from strategyos_mvp.api import app

    assert "/api/claims" in app.openapi()["paths"]
    assert "/api/claims/snapshots/{run_id}" in app.openapi()["paths"]
    assert "/api/claims/runs/{run_id}/reconciliation" in app.openapi()["paths"]


def test_snapshot_endpoint_uses_same_authenticated_policy_context(monkeypatch):
    captured = {}

    class FakeRepository:
        def snapshot(self, snapshot_key, *, context, metric_keys, limit, offset):
            captured["snapshot_key"] = snapshot_key
            captured["context"] = context
            captured["metric_keys"] = metric_keys
            captured["limit"] = limit
            captured["offset"] = offset
            return {"snapshot_id": "snapshot-1", "records": []}

    monkeypatch.setattr(claim_api, "ClaimRepository", FakeRepository)
    result = claim_api.query_run_snapshot(
        "run-1",
        purpose=UsePurpose.EXECUTIVE_BRIEFING,
        metric_key="ceo.revenue",
        limit=50,
        offset=100,
        principal={
            "tenant_id": "tenant-1",
            "subject": "ceo-1",
            "role": "executive",
            "business_units": ["tamween"],
        },
    )
    assert result["snapshot_id"] == "snapshot-1"
    assert captured["snapshot_key"] == "run:run-1"
    assert captured["context"].purpose == UsePurpose.EXECUTIVE_BRIEFING
    assert captured["metric_keys"] == ["ceo.revenue"]
    assert captured["limit"] == 50
    assert captured["offset"] == 100


def test_reconciliation_endpoint_is_tenant_scoped(monkeypatch):
    captured = {}

    class FakeRepository:
        def reconciliation(self, run_id, *, tenant_id):
            captured["run_id"] = run_id
            captured["tenant_id"] = tenant_id
            return {"status": "passed"}

    monkeypatch.setattr(claim_api, "ClaimRepository", FakeRepository)
    result = claim_api.query_run_reconciliation(
        "run-1",
        principal={
            "tenant_id": "tenant-1",
            "subject": "auditor-1",
            "role": "auditor",
            "business_units": [],
        },
    )
    assert result["reconciliation"]["status"] == "passed"
    assert captured == {"run_id": "run-1", "tenant_id": "tenant-1"}
