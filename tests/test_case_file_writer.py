from dataclasses import replace
from pathlib import Path

from strategyos_mvp.agents.finance_agents import CaseFileWriter
from strategyos_mvp.ingestion import load_dataset
from strategyos_mvp.models import AuditEvent
from strategyos_mvp.paths import SOURCE_DATASET
from strategyos_mvp.skills.finance_controls import run_all_finance_skills


def test_case_file_writer_emits_phase5_deliverables(tmp_path: Path):
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    audit_events = [
        AuditEvent(
            round_no=1,
            actor="Finance Auditor",
            finding_id=findings[0].finding_id,
            action="challenge",
            detail="Phase 5 output verification sample.",
        )
    ]

    artifacts = CaseFileWriter().write_all(bundle, findings, audit_events, tmp_path)

    assert artifacts["case_file"].name == "Final consolidated case file.md"
    assert artifacts["case_file_pdf"].name == "Final consolidated case file.pdf"
    assert artifacts["working_capital"].name == "Working capital drift memo.md"
    assert artifacts["qa"].name == "Drill-down Q&A transcript.md"
    assert artifacts["audit_log"].name == "StrategyOS Ping Pong Audit Log.json"
    assert artifacts["case_file"].read_text(encoding="utf-8").startswith(
        "# Final consolidated case file"
    )
    assert artifacts["case_file_pdf"].read_bytes().startswith(b"%PDF")
    working_capital = artifacts["working_capital"].read_text(encoding="utf-8")
    assert working_capital.startswith("# 13-week trailing DSO/DPO drift analysis")
    assert "Formula 1" in working_capital
    assert "Task 1 leakage overlap" in working_capital
    assert "Driver citations" in working_capital
    qa = artifacts["qa"].read_text(encoding="utf-8")
    assert "Premier Pharma Packaging LLC (V-1872) has the largest single-event cash leakage" in qa
    assert "Baseline H1 EBITDA from GL/TB: SAR 215,741,310.56" in qa
    assert "EBITDA margin of 56.03% before recovery" in qa
    assert "margin becomes 56.15%" in qa
    assert "Projected H2 recurring exposure is SAR 353,570.00" in qa
    assert "02_ERP_Extracts/Trial_Balance_June_2026.xlsx" in qa


def test_case_file_writer_reports_skipped_detectors_in_deliverables(tmp_path: Path):
    bundle = load_dataset(SOURCE_DATASET)
    bundle.run_metadata = {
        "available_roles": ["ap_ledger"],
        "missing_roles": ["vendor_master", "purchase_orders", "cash_forecast", "gl_extract"],
        "run_mode": "partial",
    }
    findings = run_all_finance_skills(bundle)

    artifacts = CaseFileWriter().write_all(bundle, findings, [], tmp_path)

    case_file = artifacts["case_file"].read_text(encoding="utf-8")
    qa = artifacts["qa"].read_text(encoding="utf-8")
    assert "Detector Coverage" in case_file
    assert "detect_entity_resolution_duplicates (entity_resolution_duplicate): skipped" in case_file
    assert "missing_roles=['vendor_master']" in case_file
    assert "detect_fx_hedge_unapplied (fx_hedge_unapplied) skipped" in qa


def test_case_file_writer_blocks_polished_outputs_when_citation_verification_is_weak(tmp_path: Path):
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    duplicate = next(finding for finding in findings if finding.pattern_type == "duplicate_payment")
    duplicate.citations = [replace(citation, source_hash="mismatch") for citation in duplicate.citations]

    try:
        CaseFileWriter().write_all(bundle, findings, [], tmp_path)
    except ValueError as exc:
        assert "Cannot produce polished outputs from weak evidence" in str(exc)
        assert duplicate.finding_id in str(exc)
    else:
        raise AssertionError("Expected weak citation evidence to block polished output generation.")
