from pathlib import Path
import shutil

import pandas as pd
from strategyos_mvp.config import load_config
from strategyos_mvp.ingestion import load_dataset
from strategyos_mvp.paths import SOURCE_DATASET
import strategyos_mvp.skills.finance_controls as finance_controls_module
from strategyos_mvp.skills.finance_controls import (
    compute_working_capital_drifts,
    detect_fx_hedge_unapplied,
    run_all_finance_skills,
    vendor_name_filename_needle,
)


def test_finance_skills_find_core_patterns():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    pattern_types = {f.pattern_type for f in findings}
    assert "duplicate_payment" in pattern_types
    assert "entity_resolution_duplicate" in pattern_types
    assert "off_contract_single_approver" in pattern_types
    assert "price_variance" in pattern_types
    assert "missed_early_pay_discount" in pattern_types
    assert "auto_renewal_escalation" in pattern_types
    assert "fx_hedge_unapplied" in pattern_types
    assert "dormant_credit_balance" in pattern_types


def test_findings_have_minimum_shape():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    assert len(findings) >= 8
    assert all(f.vendor_id for f in findings)
    assert all(f.title for f in findings)
    assert sum(f.recoverable_sar for f in findings) > 600_000


def test_fx_finding_uses_ocr_bank_statement_when_available():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    fx = next(f for f in findings if f.pattern_type == "fx_hedge_unapplied")
    status = bundle.evidence.ocr_status.get("01_Bank_Statements/EmiratesNBD_EUR_Jan-Jun_2026.pdf")
    if not status or any(page.get("status") != "ok" for page in status.get("pages", [])):
        return
    assert any(c.source_path == "01_Bank_Statements/EmiratesNBD_EUR_Jan-Jun_2026.pdf" for c in fx.citations)


def test_fx_finding_downgrades_when_required_bank_ocr_evidence_is_missing():
    bundle = load_dataset(SOURCE_DATASET)
    bank_rel = "01_Bank_Statements/EmiratesNBD_EUR_Jan-Jun_2026.pdf"
    original_pages = bundle.evidence.pdf_text[bank_rel]
    bundle.evidence.pdf_text[bank_rel] = [""] * len(original_pages)
    findings = run_all_finance_skills(bundle)
    fx = next(f for f in findings if f.pattern_type == "fx_hedge_unapplied")
    assert fx.confidence == "LOW"
    assert fx.status == "blocked"
    assert "OCR-required bank statement evidence is missing" in fx.rationale
    assert "Fail-closed evidence gate" in fx.rationale


def test_duplicate_payment_includes_bank_statement_payment_legs():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    finding = next(f for f in findings if f.pattern_type == "duplicate_payment")
    bank_citations = [c for c in finding.citations if c.source_path.startswith("01_Bank_Statements/")]
    assert len(bank_citations) >= 2
    excerpts = " ".join(c.excerpt for c in bank_citations)
    assert "WIRE-9912034" in excerpts
    assert "CHQ-205814" in excerpts


def test_duplicate_entity_includes_both_vendor_master_rows_and_shared_identifier():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    finding = next(f for f in findings if f.pattern_type == "entity_resolution_duplicate")
    vendor_citations = [c for c in finding.citations if c.source_path == "03_Master_Data/Vendor_Master.xlsx"]
    assert len(vendor_citations) == 2
    excerpts = " ".join(c.excerpt for c in vendor_citations)
    assert "V-1142" in excerpts
    assert "V-1187" in excerpts
    assert "Tax_ID_token=hmac:" in excerpts
    assert "Bank_Account_token=hmac:" in excerpts
    assert "shared_tax_id_token=hmac:" in excerpts
    assert "300187452100003" not in excerpts
    assert "SA0380000000608010167519" not in excerpts


def test_price_variance_uses_matching_po_contract_and_ap_rows():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    finding = next(f for f in findings if f.pattern_type == "price_variance")
    excerpts = " \n".join(c.excerpt for c in finding.citations)
    assert "PO-2026-0218" in excerpts
    assert "PO-2026-0247" in excerpts
    assert "INV-2026-1424" in excerpts
    assert "INV-2026-1425" in excerpts
    assert "FG-2241" in excerpts
    assert "32.00" in excerpts


def test_working_capital_drift_analysis_returns_phase6_shape():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    signals = compute_working_capital_drifts(bundle, findings)
    assert len(signals) == 3
    assert {signal["metric"] for signal in signals} == {"DSO", "DPO"} or "DSO" in {signal["metric"] for signal in signals}
    for signal in signals:
        assert signal["classification"] in {"systemic", "one-time"}
        assert signal["cash_effect"] in {"absorbed", "released"}
        assert signal["drivers"]
        assert len(signal["drivers"]) <= 3
        assert "invoice_ids" in signal["task1_overlap"]


def test_role_guards_skip_detectors_missing_required_roles():
    bundle = load_dataset(SOURCE_DATASET)
    bundle.run_metadata = {
        "available_roles": ["ap_ledger"],
        "missing_roles": ["vendor_master", "purchase_orders", "cash_forecast", "gl_extract"],
        "run_mode": "partial",
    }

    findings = run_all_finance_skills(bundle)
    pattern_types = {f.pattern_type for f in findings}

    assert "duplicate_payment" in pattern_types
    assert "entity_resolution_duplicate" not in pattern_types
    assert "price_variance" not in pattern_types
    assert "fx_hedge_unapplied" not in pattern_types
    skipped = bundle.detector_report["skipped_detectors"]
    assert any(item["detector"] == "detect_entity_resolution_duplicates" for item in skipped)
    assert any(item["missing_roles"] == ["cash_forecast"] for item in skipped if item["detector"] == "detect_fx_hedge_unapplied")


def test_threshold_config_can_override_business_rule_defaults(monkeypatch):
    original_config = finance_controls_module.CONFIG
    monkeypatch.setenv("STRATEGYOS_FINANCE_OFF_CONTRACT_MIN_INVOICES", "999")
    monkeypatch.setenv("STRATEGYOS_FINANCE_PRICE_VARIANCE_MIN_EXCESS_SAR", "999999")
    monkeypatch.setenv("STRATEGYOS_FINANCE_EARLY_PAY_DISCOUNT_WINDOW_DAYS", "999")
    monkeypatch.setenv("STRATEGYOS_FINANCE_WORKING_CAPITAL_MIN_DRIFT_DAYS", "999")
    finance_controls_module.CONFIG = load_config()
    try:
        bundle = load_dataset(SOURCE_DATASET)
        findings = run_all_finance_skills(bundle)
        pattern_types = {f.pattern_type for f in findings}
        assert "off_contract_single_approver" not in pattern_types
        assert "price_variance" not in pattern_types
        assert "missed_early_pay_discount" not in pattern_types
        assert compute_working_capital_drifts(bundle, findings) == []
    finally:
        finance_controls_module.CONFIG = original_config


def test_detector_contracts_support_renamed_sources_and_column_aliases(tmp_path: Path):
    dataset_root = tmp_path / "renamed-dataset"
    shutil.copytree(SOURCE_DATASET, dataset_root)

    rename_map = {
        dataset_root / "02_ERP_Extracts" / "AP_Invoices_H1_2026.xlsx": dataset_root / "incoming" / "ap_ledger_alias.xlsx",
        dataset_root / "02_ERP_Extracts" / "AR_Invoices_H1_2026.xlsx": dataset_root / "incoming" / "ar_ledger_alias.xlsx",
        dataset_root / "02_ERP_Extracts" / "GL_Extract_H1_2026.csv": dataset_root / "incoming" / "gl_extract_alias.csv",
        dataset_root / "02_ERP_Extracts" / "Trial_Balance_June_2026.xlsx": dataset_root / "incoming" / "trial_balance_alias.xlsx",
        dataset_root / "03_Master_Data" / "Vendor_Master.xlsx": dataset_root / "masters" / "vendor_master_alias.xlsx",
        dataset_root / "03_Master_Data" / "Customer_Master.xlsx": dataset_root / "masters" / "customer_master_alias.xlsx",
        dataset_root / "03_Master_Data" / "Chart_of_Accounts.xlsx": dataset_root / "masters" / "chart_alias.xlsx",
        dataset_root / "05_Purchase_Orders" / "PO_Log_H1_2026.csv": dataset_root / "purchases" / "po_alias.csv",
        dataset_root / "07_Cash_Forecast" / "CFO_Cash_Forecast_June_2026.xlsx": dataset_root / "treasury" / "cash_forecast_alias.xlsx",
    }
    for source, destination in rename_map.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source, destination)

    ap_frame = pd.read_excel(dataset_root / "incoming" / "ap_ledger_alias.xlsx")
    ap_frame = ap_frame.rename(
        columns={
            "Invoice_ID": "Invoice No",
            "Vendor_ID": "Supplier ID",
            "Amount_SAR": "Amount (SAR)",
            "Payment_Date": "Settlement Date",
            "PO_Reference": "PO Ref",
        }
    )
    ap_frame.to_excel(dataset_root / "incoming" / "ap_ledger_alias.xlsx", index=False)

    vendor_frame = pd.read_excel(dataset_root / "masters" / "vendor_master_alias.xlsx")
    vendor_frame = vendor_frame.rename(columns={"Vendor_ID": "Supplier ID", "Vendor_Name": "Supplier Name", "Tax_ID": "VAT ID", "Bank_Account": "IBAN"})
    vendor_frame.to_excel(dataset_root / "masters" / "vendor_master_alias.xlsx", index=False)

    po_frame = pd.read_csv(dataset_root / "purchases" / "po_alias.csv")
    po_frame = po_frame.rename(columns={"PO_ID": "PO Number", "Vendor_ID": "Supplier ID", "SKU": "Item SKU", "Unit_Price": "Unit Price", "Total": "Total Amount"})
    po_frame.to_csv(dataset_root / "purchases" / "po_alias.csv", index=False)

    shutil.move(
        dataset_root / "01_Bank_Statements" / "EmiratesNBD_EUR_Jan-Jun_2026.pdf",
        dataset_root / "01_Bank_Statements" / "eur_vendor_statement.pdf",
    )
    shutil.move(
        dataset_root / "06_Email_Correspondence" / "Email_2_BordeauxWines_Payment_May_2026.txt",
        dataset_root / "06_Email_Correspondence" / "treasury_followup.txt",
    )

    bundle = load_dataset(dataset_root)
    findings = run_all_finance_skills(bundle)

    assert bundle.data_contracts["ap_ledger"]["resolution"] == "discovered_by_columns"
    assert bundle.data_contracts["vendor_master"]["resolution"] == "discovered_by_columns"
    assert bundle.data_contracts["purchase_orders"]["resolution"] == "discovered_by_columns"
    assert bundle.data_contracts["cash_forecast"]["resolution"] == "discovered_by_sheet_names"
    assert bundle.run_metadata["detector_data_contracts"]["ap_ledger"]["relative_path"].endswith("ap_ledger_alias.xlsx")

    pattern_types = {f.pattern_type for f in findings}
    assert "duplicate_payment" in pattern_types
    assert "price_variance" in pattern_types
    assert "fx_hedge_unapplied" in pattern_types

    duplicate = next(f for f in findings if f.pattern_type == "duplicate_payment")
    assert any(c.source_path.endswith("ap_ledger_alias.xlsx") for c in duplicate.citations)

    price = next(f for f in findings if f.pattern_type == "price_variance")
    assert any(c.source_path.endswith("po_alias.csv") for c in price.citations)

    fx = next(f for f in findings if f.pattern_type == "fx_hedge_unapplied")
    assert any(c.source_path.endswith("eur_vendor_statement.pdf") for c in fx.citations)
    assert any(c.source_path.endswith("treasury_followup.txt") for c in fx.citations)


def test_vendor_name_filename_needle_derives_the_original_hardcoded_anchors():
    """The evidence anchors that used to be literal strings ("BordeauxWines",
    "GulfLogistics") must be exactly reproducible by deriving them from the
    finding's own vendor name -- proving the generalization is a true no-op
    on the fixture rather than a behavior change."""
    assert vendor_name_filename_needle("Bordeaux Wines & Spirits SARL") == "BordeauxWines"
    assert vendor_name_filename_needle("Gulf Logistics Services Co") == "GulfLogistics"


def test_vendor_name_filename_needle_disambiguates_shared_first_words():
    """A single-word needle is too loose: multiple vendors in this dataset
    share a first word ("Gulf Cosmetics", "Gulf Logistics", "Gulf Trading"),
    so a one-word needle would non-deterministically match whichever
    "Gulf*" invoice file the manifest happens to list first. Two words
    must disambiguate them."""
    bundle = load_dataset(SOURCE_DATASET)
    gulf_invoices = [
        rel
        for rel in bundle.evidence.manifest
        if rel.startswith("08_Invoices/") and rel.lower().endswith(".pdf") and "gulf" in rel.lower()
    ]
    assert len(gulf_invoices) > 1, (
        "expected the fixture to still contain multiple Gulf* invoices -- "
        "if this assertion fails the fixture changed and the single-word "
        "ambiguity this test guards against may no longer apply"
    )
    needle = vendor_name_filename_needle("Gulf Logistics Services Co").lower()
    matches = [rel for rel in gulf_invoices if needle in rel.lower()]
    assert matches == ["08_Invoices/Invoice_GulfLogistics_INV-2026-1421.pdf"]


def test_fx_hedge_anchors_derive_from_finding_not_a_hardcoded_vendor_literal():
    """Renaming the vendor on the one EUR/Paid AP row that produces the
    fx_hedge_unapplied finding must change which vendor the finding (and
    its anchor-derived citations) reference. Against the old hardcoded
    code, this finding's vendor filter, invoice-PDF lookup, and OCR/email
    search terms were all the literal "Bordeaux Wines"/"BordeauxWines"
    regardless of what the underlying data said -- this test would have
    caught that: it fails if any of those anchors are still pinned to the
    literal instead of being derived from the finding's own vendor name."""
    bundle = load_dataset(SOURCE_DATASET)
    eur_paid = bundle.ap[
        bundle.ap["Currency"].astype(str).str.upper().eq("EUR") & bundle.ap["Status"].eq("Paid")
    ]
    assert len(eur_paid) == 1, (
        "expected exactly one EUR/Paid AP row in the fixture -- if this "
        "assertion fails the fixture changed and this test's setup "
        "(renaming that single row) needs to be revisited"
    )
    target_index = eur_paid.index[0]
    original_vendor_name = str(bundle.ap.loc[target_index, "Vendor_Name"])
    assert original_vendor_name.startswith("Bordeaux")

    bundle.ap.loc[target_index, "Vendor_Name"] = "Acme Wines International"

    findings = detect_fx_hedge_unapplied(bundle)
    assert len(findings) == 1
    finding = findings[0]

    assert finding.vendor_name == "Acme Wines International"

    # No hardcoded "Bordeaux"/"89,400.00 Bordeaux"-anchored citation should
    # attach for a vendor that is no longer named Bordeaux anything -- the
    # bank-statement page still literally says "Bordeaux Wines & Sp" (only
    # the AP row was renamed, not the source PDF), so a genuinely
    # vendor-derived OCR search for "Acme Wines" must correctly NOT match
    # it, rather than falling back to a literal that still finds Bordeaux.
    bank_citations = [
        c for c in finding.citations if c.source_path.startswith("01_Bank_Statements/")
    ]
    assert bank_citations, "expected a bank-statement citation (even if only a pending/verification-required one)"
    assert all("bordeaux" not in c.excerpt.lower() for c in bank_citations), (
        "a bank-statement citation excerpt still references Bordeaux for a "
        "vendor renamed to Acme Wines -- an anchor is still pinned to the "
        "literal vendor name instead of being derived from the finding"
    )

    # The invoice-PDF lookup must not silently keep resolving to the old
    # Bordeaux invoice file for the renamed vendor.
    invoice_citations = [
        c for c in finding.citations if c.source_path.startswith("08_Invoices/")
    ]
    assert not any("bordeaux" in c.source_path.lower() for c in invoice_citations), (
        "an invoice citation still points at the Bordeaux invoice PDF for "
        "a vendor renamed to Acme Wines"
    )
