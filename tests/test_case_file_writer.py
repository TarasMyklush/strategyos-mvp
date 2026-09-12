from dataclasses import replace
from pathlib import Path

from strategyos_mvp.agents.finance_agents import CaseFileWriter
from strategyos_mvp.ingestion import load_dataset
from strategyos_mvp.models import AuditEvent
from strategyos_mvp.paths import SOURCE_DATASET
from strategyos_mvp.skills.finance_controls import run_all_finance_skills


def test_case_file_writer_emits_phase5_deliverables(tmp_path: Path):
    bundle = load_dataset(SOURCE_DATASET)
    bundle.run_metadata = {
        **(getattr(bundle, "run_metadata", {}) or {}),
        "run_mode": "partial",
    }
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
    from pypdf import PdfReader
    pdf = PdfReader(artifacts['case_file_pdf'])
    summary_page = pdf.pages[0].extract_text()
    assert 'Top three recovery opportunities' in summary_page
    assert 'Pattern type:' not in summary_page
    assert 'Pattern type:' in pdf.pages[1].extract_text()
    for page in pdf.pages:
        lines = page.extract_text().strip().splitlines()
        assert not (lines[-1].startswith('F-') and ' - ' in lines[-1]), 'Finding heading stranded at page end'
    assert 'UNTRUSTED DOCUMENT CONTENT:' not in '\n'.join(page.extract_text() for page in pdf.pages)
    assert 'Methodology and source coverage' in artifacts['case_file'].read_text()
    assert 'Disputed findings' in artifacts['case_file'].read_text()
    assert any(c.excerpt.startswith('UNTRUSTED DOCUMENT CONTENT:') for f in findings for c in f.citations)
    working_capital = artifacts["working_capital"].read_text(encoding="utf-8")
    assert working_capital.startswith("# 13-week settlement-day proxy drift analysis")
    assert "exclude unpaid balances" in working_capital
    assert "not balance-based DSO/DPO" in working_capital
    assert "Formula 1" in working_capital
    assert "Task 1 leakage overlap" in working_capital
    assert "Driver citations" in working_capital
    qa = artifacts["qa"].read_text(encoding="utf-8")
    import re
    answers = re.split(r'^## Q\d\.', qa, flags=re.M)[1:]
    assert len(answers) == 3
    for answer in answers:
        body = answer.split('\n', 1)[1].strip()
        assert len(re.split(r'\n\s*\n', body)) <= 2
        assert not re.search(r'^- ', body, flags=re.M)
    assert "has the largest single-event cash leakage in this run" in qa
    assert str(findings[0].vendor_name) in qa
    assert "Baseline H1 EBITDA from GL/TB: SAR 215,741,310.56" in qa
    assert "EBITDA margin of 56.03% before recovery" in qa
    assert "margin becomes 56.15%" in qa
    assert "Projected H2 recurring exposure is SAR 353,570.00" in qa
    assert "SAR 307,082.00 is EBITDA-linked operating leakage" in qa
    assert "SAR 46,488.00 is treasury/FX exposure below the EBITDA bridge" in qa
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


def test_case_pdf_quotes_untrusted_markup_and_embeds_arabic(tmp_path: Path):
    from strategyos_mvp.agents.finance_agents import _escape_pdf_text, write_markdown_pdf
    from pypdf import PdfReader

    excerpt = 'فاتورة ضريبية <script>alert(1)</script> SAR 177,188.00'
    markup = _escape_pdf_text(excerpt)
    assert 'BoardArabic' in markup
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in markup
    output = write_markdown_pdf('# Evidence\n\n> ' + excerpt, tmp_path / 'quoted.pdf', title='Evidence')
    page = PdfReader(output).pages[0]
    text = page.extract_text()
    assert '177,188.00' in text
    # pypdf reorders punctuation beside RTL spans; the escaped literal is
    # checked above, and the rendered mixed-language page is visually checked.
    assert 'script>alert(1)</script>' in text
    assert any('NotoSansArabic' in str(font.get_object().get('/BaseFont'))
               for font in page['/Resources']['/Font'].get_object().values())
