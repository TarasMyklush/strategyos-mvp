from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from .ingestion import DataBundle
from .models import Citation, Finding


ROW_RE = re.compile(r"(?:Excel|CSV) row\s+(\d+)", re.I)
PAGE_RE = re.compile(r"page\s+(\d+)", re.I)


def resolve_citation(bundle: DataBundle, citation: Citation) -> dict[str, Any]:
    rel_path = citation.source_path
    manifest_entry = bundle.evidence.manifest.get(rel_path, {})
    payload = resolve_payload(bundle, rel_path, citation.locator, citation.excerpt)
    source_hash = manifest_entry.get("sha256")
    return {
        "source_path": rel_path,
        "locator": citation.locator,
        "source_hash": source_hash,
        "citation_hash": citation.source_hash,
        "hash_match": bool(source_hash and citation.source_hash == source_hash),
        "manifest_entry": manifest_entry,
        "excerpt": citation.excerpt,
        "resolved_payload": payload,
        "resolved": bool(source_hash and payload),
    }


def resolve_findings(bundle: DataBundle, findings: list[Finding]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for finding in findings:
        for citation in finding.citations:
            item = resolve_citation(bundle, citation)
            item["finding_id"] = finding.finding_id
            item["pattern_type"] = finding.pattern_type
            resolved.append(item)
    return resolved


def save_citation_audit(bundle: DataBundle, findings: list[Finding], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = resolve_findings(bundle, findings)
    payload = {
        "summary": {
            "citation_count": len(records),
            "resolved_count": sum(1 for record in records if record["resolved"]),
            "hash_match_count": sum(1 for record in records if record["hash_match"]),
        },
        "records": records,
    }
    output_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return output_path


def resolve_payload(bundle: DataBundle, rel_path: str, locator: str, excerpt: str) -> dict[str, Any] | None:
    if rel_path.endswith(".xlsx"):
        if rel_path == "07_Cash_Forecast/CFO_Cash_Forecast_June_2026.xlsx":
            return resolve_workbook_sheet(bundle, locator)
        return resolve_structured_row(table_for_source(bundle, rel_path), locator)
    if rel_path.endswith(".csv"):
        return resolve_structured_row(table_for_source(bundle, rel_path), locator)
    if rel_path.endswith(".pdf"):
        return resolve_pdf_page(bundle, rel_path, locator, excerpt)
    if rel_path.endswith(".txt"):
        return resolve_text_file(bundle, rel_path)
    return {"source_type": "file", "excerpt": excerpt} if excerpt else None


def resolve_structured_row(df: pd.DataFrame | None, locator: str) -> dict[str, Any] | None:
    if df is None:
        return None
    match = ROW_RE.search(locator)
    if not match:
        return {"source_type": "structured_table", "row_count": int(len(df)), "columns": list(df.columns)}
    row_index = int(match.group(1)) - 2
    if row_index < 0 or row_index >= len(df):
        return None
    row = df.iloc[row_index]
    return {
        "source_type": "structured_table",
        "row_index_zero_based": row_index,
        "columns": list(df.columns),
        "row": {str(k): normalize_value(v) for k, v in row.to_dict().items()},
    }


def resolve_workbook_sheet(bundle: DataBundle, locator: str) -> dict[str, Any] | None:
    sheet_name = locator.replace(" sheet", "").strip()
    df = bundle.cash_forecast.get(sheet_name)
    if df is None:
        return None
    records = [
        {str(k): normalize_value(v) for k, v in row.items()}
        for row in df.head(10).to_dict(orient="records")
    ]
    return {
        "source_type": "workbook_sheet",
        "sheet_name": sheet_name,
        "row_count": int(len(df)),
        "columns": list(df.columns),
        "sample_records": records,
    }


def resolve_pdf_page(bundle: DataBundle, rel_path: str, locator: str, excerpt: str) -> dict[str, Any] | None:
    pages = bundle.evidence.pdf_text.get(rel_path, [])
    page_no = page_number(locator) or page_number(excerpt)
    if page_no is None:
        text = " ".join(" ".join(page.split()) for page in pages).strip()
        return {"source_type": "pdf", "page_count": len(pages), "text_excerpt": text[:700]} if text else None
    if page_no < 1 or page_no > len(pages):
        return None
    text = " ".join(pages[page_no - 1].split())
    return {"source_type": "pdf", "page": page_no, "text_excerpt": text[:700]} if text else None


def resolve_text_file(bundle: DataBundle, rel_path: str) -> dict[str, Any] | None:
    path = bundle.dataset_root / rel_path
    if not path.exists():
        return None
    text = " ".join(path.read_text(encoding="utf-8", errors="ignore").split())
    return {"source_type": "text", "text_excerpt": text[:700]} if text else None


def table_for_source(bundle: DataBundle, rel_path: str) -> pd.DataFrame | None:
    mapping = {
        "02_ERP_Extracts/AP_Invoices_H1_2026.xlsx": bundle.ap,
        "02_ERP_Extracts/AR_Invoices_H1_2026.xlsx": bundle.ar,
        "02_ERP_Extracts/GL_Extract_H1_2026.csv": bundle.gl,
        "02_ERP_Extracts/Trial_Balance_June_2026.xlsx": bundle.trial_balance,
        "03_Master_Data/Vendor_Master.xlsx": bundle.vendors,
        "03_Master_Data/Customer_Master.xlsx": bundle.customers,
        "03_Master_Data/Chart_of_Accounts.xlsx": bundle.coa,
        "05_Purchase_Orders/PO_Log_H1_2026.csv": bundle.po,
    }
    return mapping.get(rel_path)


def page_number(text: str) -> int | None:
    match = PAGE_RE.search(text or "")
    return int(match.group(1)) if match else None


def normalize_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value
