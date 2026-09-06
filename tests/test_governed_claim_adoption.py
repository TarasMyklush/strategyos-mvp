from __future__ import annotations

from strategyos_mvp import api


def test_authenticated_summary_uses_policy_filtered_snapshot_without_legacy_leak(monkeypatch):
    class FakeRepository:
        def snapshot(self, snapshot_key, *, context):
            assert snapshot_key == "run:run-1"
            assert context.roles == frozenset({"executive"})
            return {
                "snapshot_id": "snapshot-1",
                "snapshot_key": snapshot_key,
                "analysis_as_of": "2026-07-01T00:00:00+00:00",
                "policy_version": "source-claim-v1",
                "denied_count": 1,
                "records": [
                    {
                        "claim_revision_id": "revenue-actual-1",
                        "family_key": "revenue-actual",
                        "label": "Actual",
                        "claim_kind": "actual",
                        "metric_key": "ceo.revenue",
                        "value": "100",
                        "scale": "1",
                        "unit": "SAR",
                        "dimensions": {"component_key": "revenue_actual"},
                        "sources": [{"source_key": "erp", "origin_category": "internal_system"}],
                    }
                ],
            }

        def reconciliation(self, run_id, *, tenant_id):
            assert (run_id, tenant_id) == ("run-1", "tenant-1")
            return {"status": "passed", "difference_sar": "0"}

    monkeypatch.setattr(api, "ClaimRepository", FakeRepository)
    result = api._summary_with_governed_claim_snapshot(
        {
            "run_id": "run-1",
            "tenant_context": {"tenant_id": "tenant-1"},
            "finance_kpi": {
                "authoritative": True,
                "derived_from": "deterministic_source_finance_kpi_engine",
                "components": {
                    "revenue_actual": "999",
                    "revenue_plan": "888",
                },
            },
        },
        principal={
            "tenant_id": "tenant-1",
            "subject": "ceo-1",
            "role": "executive",
        },
    )

    assert result["canonical_claim_status"] == "ready"
    assert result["finance_kpi"]["components"] == {"revenue_actual": "100"}
    assert result["finance_kpi"]["claim_snapshot"]["denied_count"] == 1


def test_missing_snapshot_keeps_pre_cutover_payload_and_reports_status(monkeypatch):
    class MissingRepository:
        def snapshot(self, snapshot_key, *, context):
            raise KeyError(snapshot_key)

    monkeypatch.setattr(api, "ClaimRepository", MissingRepository)
    legacy = {
        "run_id": "run-old",
        "tenant_context": {"tenant_id": "tenant-1"},
        "finance_kpi": {
            "authoritative": True,
            "components": {"revenue_actual": "90"},
        },
    }
    result = api._summary_with_governed_claim_snapshot(
        legacy,
        principal={"tenant_id": "tenant-1", "role": "executive"},
    )

    assert result["canonical_claim_status"] == "not_materialized"
    assert result["finance_kpi"] == legacy["finance_kpi"]
