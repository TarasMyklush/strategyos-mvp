from pathlib import Path

from strategyos_mvp.final_gate import _run_fixture_regression_validation
from strategyos_mvp.ingestion import load_dataset
from strategyos_mvp.models import AuditEvent
from strategyos_mvp.paths import SOURCE_DATASET
from strategyos_mvp.poc_acceptance import evaluate_poc_acceptance, load_tamween_answer_key
from strategyos_mvp.skills.finance_controls import run_all_finance_skills


def _acceptance_summary() -> dict:
    return {
        "run_id": "acceptance-test",
        "run_dir": str(SOURCE_DATASET),
        "total_recoverable_sar": 794108.0,
        "artifacts": {
            key: str(SOURCE_DATASET)
            for key in {
                "case_file",
                "case_file_pdf",
                "working_capital",
                "qa",
                "audit_log",
                "data_quality_json",
                "data_quality_md",
                "citation_audit",
                "knowledge_graph",
                "manifest",
            }
        },
    }


def _acceptance_audit_events() -> list[AuditEvent]:
    return [
        AuditEvent(
            round_no=1,
            actor="Finance Auditor",
            finding_id=f"F-00{index}",
            action="challenge",
            detail="Acceptance-sensitive verification sample.",
        )
        for index in range(1, 5)
    ]


def test_fixture_gate_skips_for_non_tamween_dataset(tmp_path: Path):
    report = _run_fixture_regression_validation(tmp_path / "non_tamween_dataset")

    assert report["passed"] is True
    assert report["skipped"] is True
    assert report["command"] == "skipped"
    assert "Skipped Tamween fixture regression" in report["output"]


def test_shifted_total_failure_is_isolated_to_total_check():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    baseline = evaluate_poc_acceptance(
        summary=_acceptance_summary(),
        findings=findings,
        bundle=bundle,
        audit_events=_acceptance_audit_events(),
        answer_key=load_tamween_answer_key(),
    )
    baseline_failures = [check["name"] for check in baseline["checks"] if not check["passed"]]
    answer_key = load_tamween_answer_key()
    answer_key["expected_total_recoverable_sar"] += 1.0

    report = evaluate_poc_acceptance(
        summary=_acceptance_summary(),
        findings=findings,
        bundle=bundle,
        audit_events=_acceptance_audit_events(),
        answer_key=answer_key,
    )

    failing_checks = [check["name"] for check in report["checks"] if not check["passed"]]
    assert report["passed"] is False
    assert "total_recoverable_within_tolerance" in failing_checks
    assert set(failing_checks) == set(baseline_failures) | {"total_recoverable_within_tolerance"}
