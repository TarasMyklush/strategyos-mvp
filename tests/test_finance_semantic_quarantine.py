from strategyos_mvp import state_store
from strategyos_mvp.source_claims import ClaimKind
from strategyos_mvp.governed_finance import finance_payload_from_claim_snapshot
import pytest


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", True, None])
def test_legacy_finance_parser_rejects_nonfinite_or_missing_values(value):
    from strategyos_mvp.source_finance_kpis import _decimal
    assert _decimal(value) is None


def test_invalid_group_source_cannot_silently_change_to_division_scope(monkeypatch, tmp_path):
    from strategyos_mvp import source_finance_kpis as finance
    monkeypatch.setattr(finance, "_group_finance_projection", lambda _: None)
    looked_up = []
    def source(_root, fragment, _suffix):
        looked_up.append(fragment)
        return tmp_path / "group.xlsx"
    monkeypatch.setattr(finance, "_first_matching", source)
    result = finance.derive_source_finance_kpis(tmp_path)
    assert result["authoritative"] is False
    assert "division ledger cannot replace group" in result["reason"]
    assert looked_up == ["bu_group_budget_2026"]


def test_ambiguous_finance_is_retained_as_unknown_without_derived_actual(monkeypatch):
    written = []
    def write(_cur, **kwargs):
        written.append(kwargs)
        return f"revision-{len(written)}", True
    monkeypatch.setattr(state_store, "persist_shadow_claim", write)
    monkeypatch.setattr(state_store, "_kpi_source_document", lambda *_: ("doc-1", "budget.xlsx"))
    result = state_store.persist_finance_kpi_claims(
        None, tenant_id="tenant", batch_id="batch", run_id="run", evidence_ids={},
        recorded_at="2026-07-01T00:00:00Z",
        finance_payload={
            "authoritative": True, "reporting_period_key": "H1 2026",
            "source_semantics_version": "2",
            "components": {"revenue_actual": None, "ebitda_actual": "20", "revenue_plan": "95"},
            "ambiguous_components": {"revenue_actual": {"value": "100", "reason": "Actual/Est is ambiguous"}},
        },
    )
    assert result == {"claims": 3, "exceptions": 0}
    revenue = next(item for item in written if item["metric_key"] == "ceo.revenue" and item["value_numeric"] == 100)
    assert revenue["claim_kind"] == ClaimKind.UNKNOWN
    assert revenue["metadata"]["quarantine_reasons"] == ["Actual/Est is ambiguous"]
    assert not any(item["metric_key"] == "ceo.ebitda_margin" for item in written)


def test_snapshot_overlay_cannot_leak_quarantined_legacy_values():
    result = finance_payload_from_claim_snapshot(
        {"ambiguous_components": {"revenue_actual": {"value": "secret"}}},
        {"records": []},
    )
    assert "ambiguous_components" not in result


def test_old_group_summary_cannot_recreate_an_actual_on_backfill(monkeypatch):
    written = []
    def write(_cur, **kwargs):
        written.append(kwargs)
        return "revision", True
    monkeypatch.setattr(state_store, "persist_shadow_claim", write)
    monkeypatch.setattr(state_store, "_kpi_source_document", lambda *_: ("doc-1", "budget.xlsx"))
    state_store.persist_finance_kpi_claims(
        None, tenant_id="tenant", batch_id="batch", run_id="run", evidence_ids={},
        recorded_at="2026-07-01T00:00:00Z",
        finance_payload={"authoritative": True, "reporting_period_key": "H1 2026",
            "components": {"revenue_actual": "100"},
            "evidence": {"revenue": {"details": {"sheet": "BU_Budget_2026"}}}},
    )
    assert len(written) == 1
    assert written[0]["claim_kind"] == ClaimKind.UNKNOWN
    assert written[0]["metadata"]["quarantine_reasons"]
