"""Tests for refreshing twin KPI_TREE values from a real governed run.

Covers the honesty contract: nodes with a real source in the run summary
get real values; nodes with no honest source (the Oracle-shaped
revenue/margin/COGS nodes) are marked "unavailable" rather than left
holding fabricated placeholder data.
"""

from __future__ import annotations

from strategyos_mvp.twins.kpi_ingest import (
    UNMAPPED_ORACLE_SHAPED_NODES,
    refresh_kpis_from_run,
)
from strategyos_mvp.twins.resolution import KPI_TREE
from strategyos_mvp.twins.store import build_repositories


def _repository(tmp_path):
    return build_repositories(tmp_path).kpis


def test_refresh_maps_audit_verification_onto_finding_adjudication(tmp_path):
    repository = _repository(tmp_path)
    summary = {
        "run_id": "run-abc",
        "total_recoverable_sar": 794_108.0,
        "locked_findings": 5,
        "audit_verification": {
            "passed": True,
            "required_challenged_findings": 4,
            "actual_challenged_findings": 4,
            "challenged_finding_ids": ["F-001", "F-002", "F-003", "F-004"],
            "rounds_completed": 2,
            "detail": "Acceptance-sensitive verification required 4 challenged findings; observed 4.",
        },
    }

    updated = refresh_kpis_from_run(repository=repository, summary=summary)

    node = repository.load("finding_adjudication")
    assert node["status"] == "current"
    assert node["value"] == 4
    assert node["run_id"] == "run-abc"
    assert node["challenged_finding_ids"] == ["F-001", "F-002", "F-003", "F-004"]
    assert "finding_adjudication" in updated


def test_refresh_marks_compliance_status_attention_needed_when_verification_failed(tmp_path):
    repository = _repository(tmp_path)
    summary = {
        "run_id": "run-xyz",
        "audit_verification": {
            "passed": False,
            "required_challenged_findings": 4,
            "actual_challenged_findings": 2,
            "challenged_finding_ids": ["F-001", "F-002"],
            "rounds_completed": 1,
            "detail": "Acceptance-sensitive verification required 4 challenged findings; observed 2.",
        },
    }

    refresh_kpis_from_run(repository=repository, summary=summary)

    node = repository.load("compliance_status")
    assert node["status"] == "attention_needed"
    assert node["value"] is False


def test_refresh_maps_total_recoverable_onto_leakage_node(tmp_path):
    repository = _repository(tmp_path)
    summary = {
        "run_id": "run-abc",
        "total_recoverable_sar": 794_108.0,
        "locked_findings": 5,
    }

    refresh_kpis_from_run(repository=repository, summary=summary)

    node = repository.load("recoverable_leakage_q2")
    assert node["status"] == "current"
    assert node["value"] == 794_108.0
    assert node["owner"] == "cfo"
    assert node["locked_findings"] == 5


def test_refresh_marks_unmapped_oracle_shaped_nodes_as_unavailable_not_fabricated(tmp_path):
    repository = _repository(tmp_path)
    # Seed the hardcoded structural fallback first, as the real KPIResolutionEngine does.
    repository.ensure_seeded(KPI_TREE)
    assert repository.load("revenue_q2")["value"] == 2_100_000_000  # the old fixture value

    refresh_kpis_from_run(repository=repository, summary={"run_id": "run-abc"})

    for node_id in UNMAPPED_ORACLE_SHAPED_NODES:
        node = repository.load(node_id)
        assert node["status"] == "unavailable"
        assert node["value"] is None
        assert "no persisted-snapshot" in node["detail"].lower() or "no governed-run source" in node["detail"].lower()


def test_refresh_does_not_re_flag_a_node_already_marked_unavailable(tmp_path):
    repository = _repository(tmp_path)
    refresh_kpis_from_run(repository=repository, summary={"run_id": "run-1"})
    first_timestamp = repository.load("margin_q2")["last_updated"]

    # A second refresh with a different run should not churn the timestamp
    # for a node that's already honestly marked unavailable.
    refresh_kpis_from_run(repository=repository, summary={"run_id": "run-2"})
    second_timestamp = repository.load("margin_q2")["last_updated"]

    assert first_timestamp == second_timestamp


def test_refresh_is_a_noop_when_no_run_exists(tmp_path, monkeypatch):
    repository = _repository(tmp_path)
    repository.ensure_seeded(KPI_TREE)
    monkeypatch.setattr(
        "strategyos_mvp.twins.kpi_ingest.load_latest_run_summary", lambda: None
    )

    updated = refresh_kpis_from_run(repository=repository, summary=None)

    assert updated == {}
    # Existing (seeded) values are left untouched, not overwritten with a
    # blanket "unavailable" -- there's no run to make that verdict from.
    assert repository.load("revenue_q2")["value"] == 2_100_000_000


def test_refresh_is_a_noop_when_summary_status_is_missing(tmp_path):
    repository = _repository(tmp_path)

    updated = refresh_kpis_from_run(
        repository=repository,
        summary={"status": "missing", "reason": "no pointer"},
    )

    assert updated == {}
