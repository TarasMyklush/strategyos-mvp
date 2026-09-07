from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .ingestion import DataBundle
from .models import Citation, Finding


_TRANSACTION_ROLE = {
    "ap_invoice": "ap_ledger",
    "ar_invoice": "ar_ledger",
    "gl_entry": "gl_extract",
    "purchase_order": "purchase_orders",
}

_FINDING_CONFIDENCE = frozenset({"HIGH", "MEDIUM", "LOW"})
_FINDING_STATUS = frozenset({"draft", "challenged", "locked", "disputed", "approved", "rejected", "blocked"})


def _finding_confidence(value: Any) -> str:
    normalized = str(value or "LOW").upper()
    return normalized if normalized in _FINDING_CONFIDENCE else "LOW"


def _finding_status(value: Any) -> str:
    normalized = str(value or "draft").lower()
    return normalized if normalized in _FINDING_STATUS else "draft"


def _number(record: Mapping[str, Any]) -> float:
    return float(str(record.get("value") or 0)) * float(str(record.get("scale") or 1))


def claim_backed_bundle(records: Iterable[Mapping[str, Any]]) -> DataBundle:
    """Build the deterministic-QA table adapter from authorized claim records.

    This is deliberately not an ingestion fallback. It cannot open a dataset
    path and receives only records already filtered by the claim policy engine.
    """
    rows: dict[str, list[dict[str, Any]]] = {role: [] for role in _TRANSACTION_ROLE.values()}
    trial_balance: list[dict[str, Any]] = []
    cash_forecast: dict[str, list[dict[str, Any]]] = {}
    contracts: dict[str, dict[str, Any]] = {}
    for raw in records:
        record = dict(raw)
        dimensions = record.get("dimensions") if isinstance(record.get("dimensions"), Mapping) else {}
        if record.get("metric_key") == "finance.transaction.amount":
            transaction_type = str(dimensions.get("transaction_type") or "")
            role = _TRANSACTION_ROLE.get(transaction_type)
            if role is None:
                continue
            item = dict(dimensions.get("record") or {}) if isinstance(dimensions.get("record"), Mapping) else {}
            item["Amount_SAR"] = _number(record)
            subject = record.get("subject") if isinstance(record.get("subject"), Mapping) else {}
            if transaction_type == "ap_invoice":
                item.setdefault("Invoice_ID", subject.get("key"))
                item.setdefault("Vendor_ID", dimensions.get("counterparty_key"))
            elif transaction_type == "ar_invoice":
                item.setdefault("Invoice_ID", subject.get("key"))
                item.setdefault("Customer_ID", dimensions.get("counterparty_key"))
            elif transaction_type == "purchase_order":
                item.setdefault("PO_ID", subject.get("key"))
                item.setdefault("Vendor_ID", dimensions.get("counterparty_key"))
            rows[role].append(item)
            source = next((item for item in list(record.get("sources") or []) if isinstance(item, Mapping)), None)
            if source and role not in contracts:
                contracts[role] = {
                    "relative_path": source.get("original_uri") or source.get("display_name") or source.get("source_key"),
                    "source_key": source.get("source_key"),
                    "origin_category": source.get("origin_category"),
                }
        elif record.get("metric_key") == "finance.trial_balance.net":
            item = dict(dimensions.get("record") or {}) if isinstance(dimensions.get("record"), Mapping) else {}
            item["Net"] = _number(record)
            item.setdefault("Account", dimensions.get("account"))
            trial_balance.append(item)
        elif record.get("metric_key") == "finance.cash_forecast.balance":
            item = dict(dimensions.get("record") or {}) if isinstance(dimensions.get("record"), Mapping) else {}
            item["Balance_SAR"] = _number(record)
            sheet = str(dimensions.get("sheet_name") or "forecast")
            cash_forecast.setdefault(sheet, []).append(item)

    frames = {role: pd.DataFrame(items) for role, items in rows.items()}
    available_roles = sorted(role for role, frame in frames.items() if not frame.empty)
    if trial_balance:
        available_roles.append("trial_balance")
    if cash_forecast:
        available_roles.append("cash_forecast")
    return DataBundle(
        dataset_root=Path("governed-claim-ledger"),
        evidence=None,  # type: ignore[arg-type] -- raw artifacts are intentionally unavailable here.
        ap=frames["ap_ledger"],
        ar=frames["ar_ledger"],
        gl=frames["gl_extract"],
        trial_balance=pd.DataFrame(trial_balance),
        vendors=pd.DataFrame(),
        customers=pd.DataFrame(),
        coa=pd.DataFrame(),
        po=frames["purchase_orders"],
        cash_forecast={key: pd.DataFrame(items) for key, items in cash_forecast.items()},
        data_contracts=contracts,
        run_metadata={
            "available_roles": available_roles,
            "data_boundary": "authorized_claim_snapshot",
        },
    )


def persisted_findings(items: Iterable[Mapping[str, Any]]) -> list[Finding]:
    """Hydrate generated findings from persisted read-model rows, never files."""
    result: list[Finding] = []
    for raw in items:
        item = dict(raw)
        citations = [
            Citation(
                source_path=str(citation.get("source_path") or ""),
                locator=str(citation.get("locator") or ""),
                excerpt=str(citation.get("excerpt") or ""),
                source_hash=str(citation.get("source_hash")) if citation.get("source_hash") else None,
            )
            for citation in list(item.get("citations") or [])
            if isinstance(citation, Mapping)
        ]
        result.append(
            Finding(
                finding_id=str(item.get("finding_id") or ""),
                title=str(item.get("title") or "Finding"),
                pattern_type=str(item.get("pattern_type") or "governed_finding"),
                vendor_id=str(item.get("vendor_id") or ""),
                vendor_name=str(item.get("owner") or item.get("vendor_name") or ""),
                leakage_sar=float(item.get("leakage_sar") or 0),
                recoverable_sar=float(item.get("recoverable_sar") or 0),
                recoverable_usd=float(item.get("recoverable_usd") or 0),
                confidence=_finding_confidence(item.get("confidence")),  # type: ignore[arg-type]
                classification=str(item.get("classification") or ""),
                rationale=str(item.get("rationale") or ""),
                remediation=str(item.get("remediation") or ""),
                citations=citations,
                calculation=dict(item.get("calculation") or {}),
                status=_finding_status(item.get("status")),  # type: ignore[arg-type]
            )
        )
    return result
