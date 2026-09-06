from __future__ import annotations

from strategyos_mvp import api
import pytest
from fastapi import HTTPException


def test_stale_snapshot_cannot_be_presented_as_current_briefing(monkeypatch):
    class Repository:
        def run_source_access(self, *args, **kwargs):
            return {'allowed':True}
        def snapshot(self, *args, **kwargs):
            return {'records':[{'value':'obsolete'}], 'requires_recompute':True}
        def reconciliation(self, *args, **kwargs):
            return {'status':'passed'}
    monkeypatch.setattr(api, 'ClaimRepository', Repository)
    with pytest.raises(HTTPException) as error:
        api._summary_with_governed_claim_snapshot(
            {'run_id':'old-run','tenant_context':{'tenant_id':'tenant-one'}},
            principal={'tenant_id':'tenant-one','role':'executive'})
    assert error.value.status_code == 409
    assert 'recalculation' in error.value.detail


def test_authenticated_summary_uses_policy_filtered_snapshot_without_legacy_leak(monkeypatch):
    class FakeRepository:
        def run_source_access(self, *args, **kwargs):
            return {"allowed": True}

        def snapshot(self, snapshot_key, *, context, metric_keys=None):
            assert snapshot_key == "run:run-1"
            assert context.roles == frozenset({"executive"})
            assert "ceo.revenue" in metric_keys
            assert "finance.transaction.amount" not in metric_keys
            return {
                "snapshot_id": "snapshot-1",
                "snapshot_key": snapshot_key,
                "analysis_as_of": "2026-07-01T00:00:00+00:00",
                "policy_version": "source-claim-v1",
                "denied_count": 0,
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
                        "currency": "SAR",
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
    assert result["finance_kpi"]["claim_snapshot"]["denied_count"] == 0


def test_missing_snapshot_never_returns_pre_cutover_payload(monkeypatch):
    class MissingRepository:
        def run_source_access(self, *args, **kwargs):
            return {"allowed": True}

        def snapshot(self, snapshot_key, *, context, metric_keys=None):
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
    with pytest.raises(HTTPException) as error:
        api._summary_with_governed_claim_snapshot(
            legacy,
            principal={"tenant_id": "tenant-1", "role": "executive"},
        )
    assert error.value.status_code == 503


def test_invalid_financial_contract_returns_unavailable_without_legacy_fallback(monkeypatch):
    class Repository:
        def run_source_access(self, *args, **kwargs):
            return {"allowed": True}

        def snapshot(self, *args, **kwargs):
            return {"records": [{"metric_key": "ceo.revenue", "claim_kind": "forecast",
                "value": "100", "scale": "1", "unit": "SAR", "currency": "SAR",
                "dimensions": {"component_key": "revenue_actual"}}]}

        def reconciliation(self, *args, **kwargs):
            return {"status": "passed"}

    monkeypatch.setattr(api, "ClaimRepository", Repository)
    with pytest.raises(HTTPException) as error:
        api._summary_with_governed_claim_snapshot(
            {"run_id": "run-1", "finance_kpi": {"components": {"revenue_actual": "999"}}},
            principal={"tenant_id": "tenant-1", "role": "executive"},
        )
    assert error.value.status_code == 503
    assert "display contract" in error.value.detail


@pytest.mark.parametrize("denied,records,reconciliation,expected", [
    (1, [{"value": "100"}], "passed", 403),
    (0, [], "passed", 503),
    (0, [{"value": "100"}], "partial", 503),
    (0, [{"value": "100"}], "failed", 503),
])
def test_incomplete_access_or_reconciliation_blocks_entire_briefing(
    monkeypatch, denied, records, reconciliation, expected
):
    class Repository:
        def run_source_access(self, *args, **kwargs):
            return {"allowed": True}

        def snapshot(self, *args, **kwargs):
            return {"denied_count": denied, "records": records}

        def reconciliation(self, *args, **kwargs):
            return {"status": reconciliation}

    monkeypatch.setattr(api, "ClaimRepository", Repository)
    with pytest.raises(HTTPException) as error:
        api._summary_with_governed_claim_snapshot(
            {"run_id": "run-1", "finance_kpi": {"trend": ["restricted value"]}},
            principal={"tenant_id": "tenant-1", "role": "executive"},
        )
    assert error.value.status_code == expected


@pytest.mark.parametrize("endpoint", ["/assistant/chat", "/qa"])
@pytest.mark.parametrize("allowed,expected", [(False, 403), (True, 503)])
def test_chat_entrypoints_do_not_bypass_canonical_source_gate(monkeypatch, endpoint, allowed, expected):
    from tests.test_qa_api import _client_with_auth, _restore_env

    class Repository:
        def run_source_access(self, *args, **kwargs):
            return {"allowed": allowed}

        def snapshot(self, *args, **kwargs):
            raise KeyError("missing")

    monkeypatch.setattr(api, "ClaimRepository", Repository)
    monkeypatch.setattr(api, "_resolve_qa_context", lambda _run: {
        "bundle": None, "findings": [], "kg_nodes": [], "kg_edges": [],
        "summary": {"run_id": "fixture-run"}, "run_id": "fixture-run", "run_mode": "full",
    })
    original, client = _client_with_auth()
    try:
        response = client.post(endpoint, headers={"X-API-Key": "operator-key"}, json={"question": "Explain current revenue", "mode": "auto"})
        assert response.status_code == expected
    finally:
        _restore_env(original)


def test_raw_file_export_enforces_source_export_permission(monkeypatch):
    from strategyos_mvp.source_claims import UsePurpose

    class Repository:
        def run_source_access(self, run_id, *, context):
            assert run_id == "run-1"
            assert context.purpose == UsePurpose.EXPORT
            return {"allowed": False}

    monkeypatch.setattr(api, "ClaimRepository", Repository)
    monkeypatch.setattr(api, "_latest_summary", lambda: {"run_id": "run-1"})
    with pytest.raises(HTTPException) as error:
        api.download_executive_review_file(
            "file-1", principal={"tenant_id": "tenant-1", "role": "executive"},
        )
    assert error.value.status_code == 403


def test_artifact_preview_source_denial_is_audited(monkeypatch, tmp_path):
    from dataclasses import replace
    artifact = tmp_path / "summary.json"
    artifact.write_text("{}")
    monkeypatch.setattr(api, "CONFIG", replace(api.CONFIG, output_root=tmp_path))
    calls = []
    monkeypatch.setattr(api, "_audit_artifact_access", lambda **event: calls.append(event))
    class Repository:
        def run_source_access(self, *args, **kwargs):
            return {"allowed": False}
    monkeypatch.setattr(api, "ClaimRepository", Repository)
    with pytest.raises(HTTPException) as error:
        api._enforce_artifact_access(
            principal={"tenant_id": "tenant-1", "role": "operator"},
            artifact_key="summary", artifact_path=artifact, scope="run", run_id="run-1",
        )
    assert error.value.status_code == 403
    assert calls[0]["allowed"] is False
    assert calls[0]["restriction_reasons"] == ["source_policy"]
