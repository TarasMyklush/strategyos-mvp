from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .detector_contracts import load_structured_role, resolve_detector_contracts
from .evidence import EvidenceStore
from .models import DataQualityIssue


OCR_REQUIRED_VERIFICATIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "01_Bank_Statements/EmiratesNBD_EUR_Jan-Jun_2026.pdf": (
        "Bordeaux Wines settlement row",
        ("Bordeaux Wines", "89,400.00", "4.2100"),
    ),
    "08_Invoices/Invoice_AlRashidCo_V1187_INV-2026-1404.pdf": (
        "Al Rashid invoice total",
        ("INV-2026-1404", "300187452100003", "SAR 21,793.20"),
    ),
}
RUN_CONTEXT_FILENAME = ".strategyos_run_context.json"


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
    data_contracts: dict[str, dict[str, Any]] = field(default_factory=dict)
    run_metadata: dict[str, Any] = field(default_factory=dict)
    detector_report: dict[str, Any] = field(default_factory=dict)
    quality_issues: list[DataQualityIssue] = field(default_factory=list)


def load_dataset(dataset_root: Path) -> DataBundle:
    evidence = EvidenceStore.build(dataset_root)
    run_metadata = _load_run_metadata(dataset_root)
    contracts = resolve_detector_contracts(dataset_root)
    ap = load_structured_role(dataset_root, contracts["ap_ledger"])
    ar = load_structured_role(dataset_root, contracts["ar_ledger"])
    gl = load_structured_role(dataset_root, contracts["gl_extract"])
    tb = load_structured_role(dataset_root, contracts["trial_balance"])
    vendors = load_structured_role(dataset_root, contracts["vendor_master"])
    customers = load_structured_role(dataset_root, contracts["customer_master"])
    coa = load_structured_role(dataset_root, contracts["chart_of_accounts"])
    po = load_structured_role(dataset_root, contracts["purchase_orders"])
    cash_forecast = load_structured_role(dataset_root, contracts["cash_forecast"])
    run_metadata.setdefault(
        "detector_data_contracts",
        {role: resolved.artifact() for role, resolved in contracts.items()},
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
        data_contracts={role: resolved.artifact() for role, resolved in contracts.items()},
        run_metadata=run_metadata,
    )
    bundle.quality_issues.extend(check_quality(bundle))
    return bundle


def _load_run_metadata(dataset_root: Path) -> dict[str, Any]:
    path = dataset_root / RUN_CONTEXT_FILENAME
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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
    for rel, (label, terms) in OCR_REQUIRED_VERIFICATIONS.items():
        status = bundle.evidence.ocr_status.get(rel, {})
        excerpt = bundle.evidence.pdf_excerpt(rel, terms)
        if excerpt:
            continue
        severity = "critical" if status.get("required") else "warning"
        issues.append(
            DataQualityIssue(
                severity,
                rel,
                f"OCR-required evidence missing for {label}; expected terms were not verified: {', '.join(terms)}.",
            )
        )
    return issues
