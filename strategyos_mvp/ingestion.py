from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .detector_contracts import (
    CONTRACTS_BY_ROLE,
    empty_role_frame,
    load_structured_role,
    resolve_detector_contracts,
    resolve_detector_contracts_partial,
)
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


# role -> DataBundle attribute name
_ROLE_ATTRIBUTES: dict[str, str] = {
    "ap_ledger": "ap",
    "ar_ledger": "ar",
    "gl_extract": "gl",
    "trial_balance": "trial_balance",
    "vendor_master": "vendors",
    "customer_master": "customers",
    "chart_of_accounts": "coa",
    "purchase_orders": "po",
    "cash_forecast": "cash_forecast",
}

_ROLE_DATE_COLUMNS: dict[str, list[str]] = {
    "ap_ledger": ["Invoice_Date", "Due_Date", "Payment_Date"],
    "ar_ledger": ["Invoice_Date", "Due_Date", "Collection_Date"],
    "gl_extract": ["Date"],
    "vendor_master": ["Created_Date"],
    "purchase_orders": ["PO_Date", "Delivery_Date"],
}


def load_dataset(dataset_root: Path, *, strict: bool | None = None) -> DataBundle:
    """Load a finance dataset into a DataBundle.

    Strictness controls how absent structured roles are handled:
    - strict=True: every role must resolve (legacy fixed-dataset path).
    - strict=False: absent roles load as empty canonical-column frames and are
      recorded as unavailable in ``run_metadata['available_roles']`` so
      dependent detectors are skipped (partial source-pack runs).

    When ``strict`` is None (default) it is inferred from the run-context file:
    a source-pack run written with ``run_mode='partial'`` loads non-strict;
    everything else stays strict to preserve current behavior.
    """
    evidence = EvidenceStore.build(dataset_root)
    run_metadata = _load_run_metadata(dataset_root)
    if strict is None:
        strict = str(run_metadata.get("run_mode") or "full") != "partial"

    if strict:
        contracts = resolve_detector_contracts(dataset_root)
        unresolved: list[str] = []
    else:
        contracts, unresolved = resolve_detector_contracts_partial(dataset_root)

    frames: dict[str, Any] = {}
    for role, attribute in _ROLE_ATTRIBUTES.items():
        if role in contracts:
            value = load_structured_role(dataset_root, contracts[role])
        elif role == "cash_forecast":
            value = {}
        else:
            value = empty_role_frame(role)
        date_columns = _ROLE_DATE_COLUMNS.get(role)
        if date_columns and isinstance(value, pd.DataFrame):
            value = normalize_dates(value, date_columns)
        frames[attribute] = value

    available_roles = sorted(contracts)
    run_metadata.setdefault(
        "detector_data_contracts",
        {role: resolved.artifact() for role, resolved in contracts.items()},
    )
    # Availability is derived here at load time (single source of truth) so the
    # detector role-guards skip exactly the absent roles. Honor a stricter set
    # already present in the run context if one was written upstream.
    run_metadata.setdefault("available_roles", available_roles)
    run_metadata.setdefault("missing_roles", sorted(unresolved))

    bundle = DataBundle(
        dataset_root=dataset_root,
        evidence=evidence,
        ap=frames["ap"],
        ar=frames["ar"],
        gl=frames["gl"],
        trial_balance=frames["trial_balance"],
        vendors=frames["vendors"],
        customers=frames["customers"],
        coa=frames["coa"],
        po=frames["po"],
        cash_forecast=frames["cash_forecast"],
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
