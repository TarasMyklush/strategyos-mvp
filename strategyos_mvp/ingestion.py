from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .evidence import EvidenceStore
from .models import DataQualityIssue


@dataclass
class DataBundle:
    dataset_root: Path
    evidence: EvidenceStore
    ap: pd.DataFrame
    ar: pd.DataFrame
    gl: pd.DataFrame
    trial_balance: pd.DataFrame
    vendors: pd.DataFrame
    customers: pd.DataFrame
    coa: pd.DataFrame
    po: pd.DataFrame
    cash_forecast: dict[str, pd.DataFrame]
    quality_issues: list[DataQualityIssue] = field(default_factory=list)


def load_dataset(dataset_root: Path) -> DataBundle:
    evidence = EvidenceStore.build(dataset_root)
    ap = pd.read_excel(dataset_root / "02_ERP_Extracts" / "AP_Invoices_H1_2026.xlsx")
    ar = pd.read_excel(dataset_root / "02_ERP_Extracts" / "AR_Invoices_H1_2026.xlsx")
    gl = pd.read_csv(dataset_root / "02_ERP_Extracts" / "GL_Extract_H1_2026.csv")
    tb = pd.read_excel(dataset_root / "02_ERP_Extracts" / "Trial_Balance_June_2026.xlsx")
    vendors = pd.read_excel(dataset_root / "03_Master_Data" / "Vendor_Master.xlsx")
    customers = pd.read_excel(dataset_root / "03_Master_Data" / "Customer_Master.xlsx")
    coa = pd.read_excel(dataset_root / "03_Master_Data" / "Chart_of_Accounts.xlsx")
    po = pd.read_csv(dataset_root / "05_Purchase_Orders" / "PO_Log_H1_2026.csv")
    cash_forecast = pd.read_excel(
        dataset_root / "07_Cash_Forecast" / "CFO_Cash_Forecast_June_2026.xlsx",
        sheet_name=None,
    )
    bundle = DataBundle(
        dataset_root=dataset_root,
        evidence=evidence,
        ap=normalize_dates(ap, ["Invoice_Date", "Due_Date", "Payment_Date"]),
        ar=normalize_dates(ar, ["Invoice_Date", "Due_Date", "Collection_Date"]),
        gl=normalize_dates(gl, ["Date"]),
        trial_balance=tb,
        vendors=normalize_dates(vendors, ["Created_Date"]),
        customers=customers,
        coa=coa,
        po=normalize_dates(po, ["PO_Date", "Delivery_Date"]),
        cash_forecast=cash_forecast,
    )
    bundle.quality_issues.extend(check_quality(bundle))
    return bundle


def normalize_dates(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    return out


def check_quality(bundle: DataBundle) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []
    required = {
        "AP": ("Invoice_ID", "Vendor_ID", "Amount_SAR"),
        "AR": ("Invoice_ID", "Customer_ID", "Amount_SAR"),
        "Vendor_Master": ("Vendor_ID", "Tax_ID", "Bank_Account"),
        "PO_Log": ("PO_ID", "Vendor_ID", "SKU", "Unit_Price"),
    }
    frames = {
        "AP": bundle.ap,
        "AR": bundle.ar,
        "Vendor_Master": bundle.vendors,
        "PO_Log": bundle.po,
    }
    for name, cols in required.items():
        missing = [c for c in cols if c not in frames[name].columns]
        if missing:
            issues.append(DataQualityIssue("critical", name, f"Missing required columns: {missing}"))
    for rel, status in bundle.evidence.ocr_status.items():
        failed_pages = [
            page
            for page in status.get("pages", [])
            if page.get("status") not in {"ok"}
        ]
        if status.get("blocked_reason"):
            issues.append(DataQualityIssue("warning", rel, status["blocked_reason"]))
        elif failed_pages:
            issues.append(DataQualityIssue("warning", rel, f"OCR attempted but unresolved pages remain: {failed_pages}"))
        else:
            issues.append(DataQualityIssue("info", rel, f"OCR completed with {status.get('engine')} for pages {status.get('empty_pages')}."))
    return issues
