from strategyos_mvp.citation_resolver import resolve_citation
from strategyos_mvp.ingestion import load_dataset
from strategyos_mvp.paths import SOURCE_DATASET
from strategyos_mvp.quality import build_data_quality_report
from strategyos_mvp.skills.finance_controls import run_all_finance_skills


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
    emirates = [
        item for item in report["pdf_sources"]
        if "EmiratesNBD_EUR_Jan-Jun_2026.pdf" in item["source_path"]
    ]
    assert emirates
    assert emirates[0]["ocr_used"] or emirates[0]["needs_ocr"]
