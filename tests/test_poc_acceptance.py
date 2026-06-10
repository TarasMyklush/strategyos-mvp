from pathlib import Path

from strategyos_mvp.models import AuditEvent, Citation, Finding
from strategyos_mvp.paths import SOURCE_DATASET
from strategyos_mvp.poc_acceptance import evaluate_poc_acceptance, load_tamween_answer_key
from strategyos_mvp.run_poc import _execute_strategyos_workflow
from strategyos_mvp.ingestion import load_dataset
from strategyos_mvp.skills.finance_controls import run_all_finance_skills


def test_poc_acceptance_passes_on_full_writer_run(tmp_path: Path):
    summary, result = _execute_strategyos_workflow(
        dataset=SOURCE_DATASET,
        run_dir=tmp_path / "acceptance",
        skip_prepare=True,
        local_only_fallback=True,
        require_human_review=False,
    )

    report = evaluate_poc_acceptance(
        summary=summary,
        findings=result["findings"],
        bundle=result["bundle"],
        audit_events=result["audit_events"],
    )

    assert report["passed"] is True
    assert {check["name"] for check in report["checks"]} >= {
        "planted_patterns_medium_plus",
        "total_recoverable_within_tolerance",
        "resolved_citations_per_finding",
        "citation_resolution_rate",
        "challenged_findings_when_ping_pong_active",
        "deliverable_presence",
        "ocr_required_extraction_or_failure_handling",
    }


def test_poc_acceptance_fails_when_finding_has_too_few_resolved_citations():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    failing = []
    for finding in findings:
        if finding.finding_id == "F-001":
            failing.append(
                Finding(
                    **{
                        **finding.__dict__,
                        "citations": [
                            Citation(
                                source_path="missing-source.pdf",
                                locator="page 1",
                                excerpt="missing",
                                source_hash="missing",
                            )
                        ],
                    }
                )
            )
            continue
        failing.append(finding)

    summary = {
        "run_id": "test-run",
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
    audit_events = [
        AuditEvent(
            round_no=1,
            actor="Finance Auditor",
            finding_id=f"F-00{index}",
            action="challenge",
            detail="Acceptance-sensitive verification sample.",
        )
        for index in range(1, 5)
    ]

    report = evaluate_poc_acceptance(
        summary=summary,
        findings=failing,
        bundle=bundle,
        audit_events=audit_events,
    )

    citation_check = next(
        check for check in report["checks"] if check["name"] == "resolved_citations_per_finding"
    )
    assert report["passed"] is False
    assert citation_check["passed"] is False
    assert "F-001" in citation_check["detail"]


def test_poc_acceptance_fails_when_citation_locator_is_unparseable():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    target = max(findings, key=lambda finding: len(finding.citations))
    patched_findings = []
    for finding in findings:
        if finding.finding_id != target.finding_id:
            patched_findings.append(finding)
            continue
        broken_citation = Citation(
            source_path=finding.citations[0].source_path,
            locator="bare locator without page or row",
            excerpt=finding.citations[0].excerpt,
            source_hash=finding.citations[0].source_hash,
        )
        patched_findings.append(
            Finding(
                **{
                    **finding.__dict__,
                    "citations": [broken_citation, *finding.citations[1:]],
                }
            )
        )

    summary = {
        "run_id": "test-run",
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
    audit_events = [
        AuditEvent(
            round_no=1,
            actor="Finance Auditor",
            finding_id=f"F-00{index}",
            action="challenge",
            detail="Acceptance-sensitive verification sample.",
        )
        for index in range(1, 5)
    ]

    report = evaluate_poc_acceptance(
        summary=summary,
        findings=patched_findings,
        bundle=bundle,
        audit_events=audit_events,
    )

    rate_check = next(
        check for check in report["checks"] if check["name"] == "citation_resolution_rate"
    )
    assert report["passed"] is False
    assert rate_check["passed"] is False
    assert "required=1.000" in rate_check["detail"]


def test_load_tamween_answer_key_uses_fixture_file():
    answer_key = load_tamween_answer_key()

    assert answer_key["expected_total_recoverable_sar"] == 794108.0
    assert answer_key["expected_citation_resolution_min_rate"] == 1.0
    assert "off_contract_single_approver" in answer_key["expected_pattern_types"]
    assert answer_key["answer_key_path"].endswith("tests/fixtures/tamween_answer_key.json")
