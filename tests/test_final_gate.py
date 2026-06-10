from pathlib import Path
from types import SimpleNamespace

from strategyos_mvp.final_gate import build_final_gate_report, promote_active_evidence


def test_build_final_gate_report_marks_phase7_phase8_and_gate_green(tmp_path: Path):
    acceptance_payload = {
        "run_dir": str(tmp_path),
        "summary": {
            "run_id": None,
            "status": "completed",
            "current_stage": "writer",
            "run_outcome": "completed",
            "deliverables_status": "complete",
            "findings": 8,
            "locked_findings": 8,
            "total_recoverable_sar": 794108.0,
            "checkpoint_count": 6,
            "runtime": {"actual_backend": "local"},
            "state_store": {"status": "skipped"},
            "neo4j": {"status": "skipped"},
            "qdrant": {"status": "skipped"},
        },
        "acceptance": {
            "passed": True,
            "checks": [
                {"name": "deliverable_presence", "passed": True, "detail": "ok"},
                {"name": "resolved_citations_per_finding", "passed": True, "detail": "ok"},
                {"name": "ocr_required_extraction_or_failure_handling", "passed": True, "detail": "ok"},
                {"name": "challenged_findings_when_ping_pong_active", "passed": True, "detail": "ok"},
                {"name": "planted_patterns_medium_plus", "passed": True, "detail": "ok"},
                {"name": "total_recoverable_within_tolerance", "passed": True, "detail": "ok"},
            ],
        },
    }
    fixture_regression_validation = {
        "passed": True,
        "command": "python -m pytest -q tests/test_poc_acceptance.py tests/test_final_gate.py",
        "returncode": 0,
        "output": "4 passed",
        "tests": ["tests/test_poc_acceptance.py", "tests/test_final_gate.py"],
    }
    generic_health_validation = {
        "passed": True,
        "command": "python -m pytest -q tests/test_runtime_governance.py",
        "returncode": 0,
        "output": "1 passed",
        "tests": ["tests/test_runtime_governance.py"],
    }

    report = build_final_gate_report(
        acceptance_payload=acceptance_payload,
        fixture_regression_validation=fixture_regression_validation,
        generic_health_validation=generic_health_validation,
    )

    assert report["passed"] is True
    assert report["decision"] == "go"
    assert report["phase_status"]["phase_7_task3"]["passed"] is True
    assert report["phase_status"]["fixture_regression"]["passed"] is True
    assert report["phase_status"]["generic_health"]["passed"] is True
    assert report["phase_status"]["phase_9_final_gate"]["passed"] is True


def test_promote_active_evidence_replaces_stale_files_and_writes_readme(tmp_path: Path, monkeypatch):
    output_root = tmp_path / "outputs"
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "run_summary.json").write_text("{}", encoding="utf-8")
    (run_dir / "StrategyOS Final Gate Report.md").write_text("gate", encoding="utf-8")

    monkeypatch.setattr(
        "strategyos_mvp.final_gate.CONFIG",
        SimpleNamespace(output_root=output_root),
    )
    active_dir = output_root / "StrategyOS Active Run Evidence"
    active_dir.mkdir(parents=True)
    (active_dir / "stale.txt").write_text("stale", encoding="utf-8")

    report = {
        "passed": True,
        "decision": "go",
        "summary": {"findings": 8, "locked_findings": 8, "total_recoverable_sar": 794108.0},
        "phase_status": {
            "phase_7_task3": {"passed": True},
            "fixture_regression": {"passed": True},
            "generic_health": {"passed": True},
            "phase_2_ocr": {"passed": True},
            "phase_4_evidence_chain": {"passed": True},
        },
    }

    promoted = promote_active_evidence(run_dir, report)

    assert promoted == active_dir
    assert not (active_dir / "stale.txt").exists()
    assert (active_dir / "run_summary.json").exists()
    assert (active_dir / "StrategyOS Final Gate Report.md").exists()
    assert "latest local final-gate run" in (active_dir / "README.md").read_text(encoding="utf-8")
