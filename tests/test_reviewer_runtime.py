from pathlib import Path

import strategyos_mvp.reviewer_runtime as reviewer_runtime


def test_resume_preserves_the_approved_finance_calendar_and_source_context(
    monkeypatch,
    tmp_path: Path,
):
    dataset_root = tmp_path / "dataset"
    run_dir = tmp_path / "run"
    dataset_root.mkdir()
    run_dir.mkdir()

    class FakeWriter:
        def write_all(self, bundle, findings, audit_events, target_dir):
            assert target_dir == run_dir
            return {}

    monkeypatch.setattr(reviewer_runtime, "_validate_checkpoint_for_resume", lambda *args: None)
    monkeypatch.setattr(reviewer_runtime, "load_dataset", lambda path: object())
    monkeypatch.setattr(reviewer_runtime, "CaseFileWriter", FakeWriter)
    monkeypatch.setattr(reviewer_runtime, "remove_legacy_artifacts", lambda path: None)
    monkeypatch.setattr(
        reviewer_runtime,
        "build_run_summary",
        lambda state: {
            "run_id": state["run_id"],
            "status": "completed",
            "current_stage": "writer",
            "finance_kpi": {"derived_from": "incorrectly_rebuilt"},
        },
    )
    monkeypatch.setattr(
        reviewer_runtime,
        "persist_checkpoint",
        lambda *args: {
            "checkpoint_id": "cp-writer",
            "run_id": "run-1",
            "stage": "writer",
            "status": "completed",
            "created_at": "2026-07-17T12:00:00+00:00",
            "persistence": "database",
        },
    )
    monkeypatch.setattr(
        reviewer_runtime,
        "update_run_summary",
        lambda run_id, summary: {"status": "updated", "run_id": run_id},
    )
    monkeypatch.setattr(reviewer_runtime, "annotate_governance_state", lambda summary: summary)
    monkeypatch.setattr(
        reviewer_runtime,
        "update_run_pointers",
        lambda summary, path: {"latest": {"run_id": summary["run_id"]}},
    )

    approved_finance = {
        "derived_from": "deterministic_source_finance_kpi_engine",
        "components": {"revenue_actual": "385100000"},
    }
    approved_calendar = {
        "status": "ready",
        "items": [{"date": "2026-07-22", "title": "Executive Committee"}],
    }
    approved_source_pack = {
        "source_pack_id": "pack-81",
        "normalized_dataset_root": str(dataset_root),
        "file_accounting": {
            "file_count": 81,
            "accounted_file_count": 81,
            "silent_omission_count": 0,
        },
        "task_readiness": {"ready_for_run": True},
    }
    monkeypatch.setattr(
        reviewer_runtime,
        "approval_status_for_run",
        lambda run_id: {
            "approved_by": "reviewer.hosted",
            "approved_at": "2026-07-17T11:59:00+00:00",
            # This is the hosted/Postgres shape: the runtime checkpoint was
            # written before these post-processing payloads existed, while the
            # approved run record contains the complete enriched summary.
            "summary_json": {
                "finance_kpi": approved_finance,
                "calendar_agenda": approved_calendar,
                "historic_context": {"status": "ready", "periods": [2023, 2024, 2025]},
                "source_pack": approved_source_pack,
                "detector_report": {"status": "complete"},
                "run_mode": "full",
            },
        },
    )
    checkpoint = {
        "checkpoint_id": "cp-review",
        "run_id": "run-1",
        "stage": "awaiting_review",
        "state_json": {
            "run_id": "run-1",
            "dataset_root": str(dataset_root),
            "source_pack_id": "pack-81",
            "run_dir": str(run_dir),
            "findings": [],
            "audit_events": [],
            "artifact_paths": {},
            "artifact_integrity": {},
            "requires_human_review": True,
        },
        "summary_json": {
            "run_id": "run-1",
            "status": "awaiting_review",
            "current_stage": "awaiting_review",
            "checkpoint_count": 1,
        },
    }

    summary = reviewer_runtime.resume_reviewed_run("run-1", checkpoint)

    assert summary["status"] == "completed"
    assert summary["current_stage"] == "writer"
    assert summary["finance_kpi"] == approved_finance
    assert summary["calendar_agenda"] == approved_calendar
    assert summary["historic_context"]["periods"] == [2023, 2024, 2025]
    assert summary["source_pack"] == approved_source_pack
    assert summary["detector_report"] == {"status": "complete"}
    assert summary["checkpoint_count"] == 2
