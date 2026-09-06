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
