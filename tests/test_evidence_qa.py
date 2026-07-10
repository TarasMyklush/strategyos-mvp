from pathlib import Path

import pytest

from strategyos_mvp.citation_resolver import resolve_citation, validate_quantitative_claims
from strategyos_mvp.ingestion import check_quality, load_dataset
from strategyos_mvp.paths import SOURCE_DATASET
from strategyos_mvp.quality import build_data_quality_report
from strategyos_mvp.skills.finance_controls import run_all_finance_skills


OCR_CRITICAL_PDFS = (
    "01_Bank_Statements/EmiratesNBD_EUR_Jan-Jun_2026.pdf",
    "08_Invoices/Invoice_AlRashidCo_V1187_INV-2026-1404.pdf",
)


def test_citation_resolver_resolves_structured_row():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    citation = next(c for f in findings for c in f.citations if c.source_path.endswith("AP_Invoices_H1_2026.xlsx"))
    resolved = resolve_citation(bundle, citation)
    assert resolved["resolved"]
    assert resolved["hash_match"]
    assert resolved["resolved_payload"]["source_type"] == "structured_table"
    assert "Invoice_ID" in resolved["resolved_payload"]["row"]


def test_quality_report_tracks_ocr_and_citation_health():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    report = build_data_quality_report(bundle, findings)
    assert report["citation_summary"]["citation_count"] > 0
    assert report["citation_summary"]["resolved_count"] > 0
    assert report["quantitative_claim_summary"]["failed_count"] == 0
    emirates = [
        item for item in report["pdf_sources"]
        if "EmiratesNBD_EUR_Jan-Jun_2026.pdf" in item["source_path"]
    ]
    assert emirates
    assert emirates[0]["ocr_used"] or emirates[0]["needs_ocr"]
    assert emirates[0]["verification"]["verified"] or emirates[0]["needs_ocr"]
    invoice = [
        item for item in report["pdf_sources"]
        if "Invoice_AlRashidCo_V1187_INV-2026-1404.pdf" in item["source_path"]
    ]
    assert invoice
    assert invoice[0]["verification"]["verified"] or invoice[0]["needs_ocr"]


@pytest.mark.parametrize("rel_path", OCR_CRITICAL_PDFS)
def test_ocr_acceptance_harness_verifies_default_dataset_critical_pdfs(rel_path: str):
    target = SOURCE_DATASET / Path(rel_path)
    assert target.exists(), f"Missing OCR-critical file under default dataset path: {target}"

    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    report = build_data_quality_report(bundle, findings)

    pdf_source = next(item for item in report["pdf_sources"] if item["source_path"] == rel_path)
    verification = pdf_source["verification"]
    ocr_status = bundle.evidence.ocr_status.get(rel_path)

    assert ocr_status, f"Expected OCR status for acceptance-critical PDF: {rel_path}"
    assert ocr_status["required"]
    assert pdf_source["ocr_used"]
    if ocr_status.get("pages"):
        assert not pdf_source["needs_ocr"]
        assert verification and verification["verified"]
        assert verification["excerpt"]
        assert all(page["status"] == "ok" for page in ocr_status.get("pages", []))
    else:
        assert pdf_source["needs_ocr"]
        assert verification and not verification["verified"]
        assert not verification["excerpt"]
        assert ocr_status.get("blocked_reason")


def test_check_quality_does_not_flag_ocr_verifications_for_files_absent_from_the_dataset():
    """OCR_REQUIRED_VERIFICATIONS names two exact filenames from the synthetic
    fixture. check_quality() used to iterate that dict unconditionally, so a
    real dataset that simply doesn't contain a file with those exact names
    got a spurious 'OCR-required evidence missing' issue on every run, for a
    file that was never part of the dataset in the first place. It must only
    check files that actually exist in the dataset's evidence manifest."""
    bundle = load_dataset(SOURCE_DATASET)
    bundle.evidence.manifest = {
        rel: value
        for rel, value in bundle.evidence.manifest.items()
        if rel not in OCR_CRITICAL_PDFS
    }
    for rel in OCR_CRITICAL_PDFS:
        bundle.evidence.pdf_text.pop(rel, None)
        bundle.evidence.ocr_status.pop(rel, None)

    issues = check_quality(bundle)

    flagged_paths = {issue.source for issue in issues}
    for rel in OCR_CRITICAL_PDFS:
        assert rel not in flagged_paths, (
            f"check_quality() flagged {rel!r} as missing OCR-required evidence, "
            "but this dataset never contained that file -- OCR_REQUIRED_VERIFICATIONS "
            "entries must be skipped when the file isn't in the dataset's manifest"
        )


def test_quantitative_claim_validations_pass_for_repaired_findings():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    validations = {
        item["pattern_type"]: item
        for item in validate_quantitative_claims(bundle, findings)
        if item["pattern_type"] in {"duplicate_payment", "entity_resolution_duplicate", "price_variance"}
    }
    assert validations["duplicate_payment"]["status"] == "pass"
    assert validations["entity_resolution_duplicate"]["status"] == "pass"
    assert validations["price_variance"]["status"] == "pass"
