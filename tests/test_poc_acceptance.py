from pathlib import Path
from types import SimpleNamespace
import pytest
import strategyos_mvp.poc_acceptance as acceptance_module

from strategyos_mvp.models import AuditEvent, Citation, Finding
from strategyos_mvp.paths import SOURCE_DATASET
from strategyos_mvp.poc_acceptance import evaluate_poc_acceptance, load_tamween_answer_key
from strategyos_mvp.run_poc import _execute_strategyos_workflow
from strategyos_mvp.ingestion import load_dataset
from strategyos_mvp.skills.finance_controls import run_all_finance_skills
import strategyos_mvp.skills.finance_controls as finance_controls_module


@pytest.mark.parametrize('count,challenged,expected', [(8,0,False),(8,4,True),(10,4,False),(10,5,True)])
def test_acceptance_requires_actual_auditor_challenges_for_half_the_findings(tmp_path,monkeypatch,count,challenged,expected):
    monkeypatch.setattr(acceptance_module,'resolve_findings',lambda *_: [])
    monkeypatch.setattr(acceptance_module,'build_data_quality_report',lambda *_: {'pdf_sources':[],'status':'ok'})
    findings=[SimpleNamespace(finding_id=f'F-{i}',pattern_type=f'pattern-{i}',confidence='HIGH',recoverable_sar=1) for i in range(count)]
    events=[AuditEvent(1,'Finance Auditor',f'F-{i}','challenge','Reproduce the source calculation') for i in range(challenged)]
    # Unrelated IDs cannot manufacture challenge coverage.
    events += [AuditEvent(1,'Finance Auditor','unrelated','challenge','Not in this case file')]
    report=evaluate_poc_acceptance(summary={},findings=findings,bundle=None,audit_events=events)
    check=next(c for c in report['checks'] if c['name']=='challenged_findings_when_ping_pong_active')
    assert check['passed'] is expected
    if challenged==0:
        empty=evaluate_poc_acceptance(summary={},findings=findings,bundle=None,audit_events=[])
        assert not next(c for c in empty['checks'] if c['name']=='challenged_findings_when_ping_pong_active')['passed']


@pytest.mark.parametrize('kind',['directory','empty','file'])
def test_acceptance_deliverables_must_be_nonempty_files(tmp_path,monkeypatch,kind):
    monkeypatch.setattr(acceptance_module,'resolve_findings',lambda *_: [])
    monkeypatch.setattr(acceptance_module,'build_data_quality_report',lambda *_: {'pdf_sources':[],'status':'ok'})
    artifact=tmp_path/'artifact'
    if kind=='directory': artifact.mkdir()
    else: artifact.write_text('reviewed output' if kind=='file' else '')
    report=evaluate_poc_acceptance(summary={'artifacts':{k:str(artifact) for k in acceptance_module.REQUIRED_DELIVERABLE_KEYS}},findings=[],bundle=None,audit_events=[])
    check=next(c for c in report['checks'] if c['name']=='deliverable_presence')
    assert check['passed'] is (kind=='file')


def test_poc_acceptance_full_writer_run_fails_closed_when_required_ocr_is_unavailable(
    tmp_path: Path,
    monkeypatch,
):
    # Simulate the governed OCR verifier being unable to resolve the required
    # bank row. The test must not depend on whether local Tesseract happens to
    # be installed or how it tokenizes the synthetic scan.
    monkeypatch.setattr(
        finance_controls_module,
        "missing_ocr_required_evidence",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        finance_controls_module,
        "pdf_citation_with_anchor",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        finance_controls_module,
        "_find_pdf_by_anchor",
        lambda *_args, **_kwargs: None,
    )
    try:
        _execute_strategyos_workflow(
            dataset=SOURCE_DATASET,
            run_dir=tmp_path / "acceptance",
            skip_prepare=True,
            local_only_fallback=True,
            require_human_review=False,
        )
    except ValueError as exc:
        assert "Cannot produce polished outputs from weak evidence" in str(exc)
        assert "F-006" in str(exc)
    else:
        raise AssertionError("Expected the full fixture workflow to fail closed when OCR-required evidence is unavailable.")


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
