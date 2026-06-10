from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .ingestion import DataBundle
from .models import Finding
from .sensitive_ids import tokenize_sensitive_identifier


@dataclass(frozen=True)
class GraphNode:
    id: str
    label: str
    properties: dict[str, Any]


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    label: str
    properties: dict[str, Any]


def build_knowledge_graph(bundle: DataBundle, findings: list[Finding]) -> dict[str, Any]:
    nodes: dict[str, GraphNode] = {}
    edges: dict[tuple[str, str, str], GraphEdge] = {}

    def add_node(label: str, key: str, **properties: Any) -> str:
        node_id = f"{label}:{key}"
        clean = {k: normalize_value(v) for k, v in properties.items() if not is_empty(v)}
        nodes.setdefault(node_id, GraphNode(node_id, label, clean))
        return node_id

    def add_edge(source: str, target: str, label: str, **properties: Any) -> None:
        edge_key = (source, target, label)
        clean = {k: normalize_value(v) for k, v in properties.items() if not is_empty(v)}
        edges.setdefault(edge_key, GraphEdge(source, target, label, clean))

    evidence_nodes(bundle, add_node)
    vendor_nodes(bundle, add_node, add_edge)
    purchase_order_nodes(bundle, add_node, add_edge)
    invoice_nodes(bundle, add_node, add_edge)
    contract_nodes(bundle, add_node, add_edge)
    entity_resolution_edges(bundle, add_node, add_edge)
    finding_nodes(bundle, findings, add_node, add_edge)

    return {
        "meta": {
            "purpose": "Local strong-node StrategyOS finance knowledge graph export.",
            "node_count": len(nodes),
            "edge_count": len(edges),
            "strong_node_labels": ["Vendor", "Invoice", "PurchaseOrder", "Contract", "Evidence", "Finding", "SKU"],
            "weak_node_policy": "PDF/email evidence is linked as Evidence nodes and must not override structured Vendor, Invoice, or PO facts without review.",
        },
        "nodes": [asdict(node) for node in sorted(nodes.values(), key=lambda n: n.id)],
        "edges": [asdict(edge) for edge in sorted(edges.values(), key=lambda e: (e.source, e.label, e.target))],
    }


def save_knowledge_graph(graph: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    return output_path


def evidence_nodes(bundle: DataBundle, add_node) -> None:
    for rel, meta in bundle.evidence.manifest.items():
        add_node(
            "Evidence",
            rel,
            source_path=rel,
            source_group=meta.get("source_group"),
            sha256=meta.get("sha256"),
            size_bytes=meta.get("size_bytes"),
            ingested_at=meta.get("ingested_at"),
        )


def vendor_nodes(bundle: DataBundle, add_node, add_edge) -> None:
    for _, row in bundle.vendors.iterrows():
        vendor_id = str(row["Vendor_ID"])
        node_id = add_node(
            "Vendor",
            vendor_id,
            vendor_id=vendor_id,
            vendor_name=row.get("Vendor_Name"),
            status=row.get("Status"),
            contract_reference=row.get("Contract_Reference"),
            tax_id_hash=hash_identifier(row.get("Tax_ID"), field_name="Tax_ID"),
            bank_account_hash=hash_identifier(row.get("Bank_Account"), field_name="Bank_Account"),
        )
        add_edge(node_id, f"Evidence:03_Master_Data/Vendor_Master.xlsx", "SOURCED_FROM", locator=f"Excel row {int(row.name) + 2}")


def purchase_order_nodes(bundle: DataBundle, add_node, add_edge) -> None:
    for _, row in bundle.po.iterrows():
        po_id = str(row["PO_ID"])
        vendor_id = str(row["Vendor_ID"])
        po_node = add_node(
            "PurchaseOrder",
            po_id,
            po_id=po_id,
            vendor_id=vendor_id,
            po_date=row.get("PO_Date"),
            delivery_date=row.get("Delivery_Date"),
            status=row.get("Status"),
            total=row.get("Total"),
            currency=row.get("Currency"),
        )
        vendor_node = add_node("Vendor", vendor_id, vendor_id=vendor_id, vendor_name=row.get("Vendor_Name"))
        add_edge(vendor_node, po_node, "ISSUED_PO")
        if not is_empty(row.get("SKU")):
            sku_node = add_node("SKU", str(row["SKU"]), sku=str(row["SKU"]))
            add_edge(po_node, sku_node, "ORDERS_SKU", quantity=row.get("Quantity"), unit_price=row.get("Unit_Price"))
        add_edge(po_node, f"Evidence:05_Purchase_Orders/PO_Log_H1_2026.csv", "SOURCED_FROM", locator=f"CSV row {int(row.name) + 2}")


def invoice_nodes(bundle: DataBundle, add_node, add_edge) -> None:
    for _, row in bundle.ap.iterrows():
        invoice_id = str(row["Invoice_ID"])
        vendor_id = str(row["Vendor_ID"])
        invoice_node = add_node(
            "Invoice",
            invoice_id,
            invoice_id=invoice_id,
            vendor_id=vendor_id,
            invoice_date=row.get("Invoice_Date"),
            due_date=row.get("Due_Date"),
            payment_date=row.get("Payment_Date"),
            amount_sar=row.get("Amount_SAR"),
            original_amount=row.get("Amount_Original_Currency"),
            currency=row.get("Currency"),
            status=row.get("Status"),
            po_reference=row.get("PO_Reference"),
            approver=row.get("Approver_Email"),
        )
        vendor_node = add_node("Vendor", vendor_id, vendor_id=vendor_id, vendor_name=row.get("Vendor_Name"))
        add_edge(vendor_node, invoice_node, "ISSUED_INVOICE")
        if not is_empty(row.get("PO_Reference")):
            po_node = add_node("PurchaseOrder", str(row["PO_Reference"]), po_id=str(row["PO_Reference"]))
            add_edge(invoice_node, po_node, "MATCHES_PO")
        add_edge(invoice_node, f"Evidence:02_ERP_Extracts/AP_Invoices_H1_2026.xlsx", "SOURCED_FROM", locator=f"Excel row {int(row.name) + 2}")


def contract_nodes(bundle: DataBundle, add_node, add_edge) -> None:
    for rel, pages in bundle.evidence.pdf_text.items():
        if not rel.startswith("04_Contracts/"):
            continue
        text = " ".join(pages)
        vendor_id = extract_vendor_id(text)
        contract_ref = extract_contract_ref(text)
        contract_node = add_node("Contract", rel, source_path=rel, contract_reference=contract_ref, vendor_id=vendor_id)
        add_edge(contract_node, f"Evidence:{rel}", "SUPPORTED_BY")
        if vendor_id:
            vendor_node = add_node("Vendor", vendor_id, vendor_id=vendor_id)
            add_edge(vendor_node, contract_node, "HAS_CONTRACT")


def entity_resolution_edges(bundle: DataBundle, add_node, add_edge) -> None:
    for field, label in [("Tax_ID", "SAME_TAX_ID_AS"), ("Bank_Account", "SAME_BANK_ACCOUNT_AS")]:
        candidates = bundle.vendors.dropna(subset=[field])
        for key, group in candidates.groupby(field):
            if len(group) < 2:
                continue
            vendor_nodes = [
                add_node("Vendor", str(row["Vendor_ID"]), vendor_id=str(row["Vendor_ID"]), vendor_name=row.get("Vendor_Name"))
                for _, row in group.iterrows()
            ]
            for left, right in pairwise(vendor_nodes):
                add_edge(left, right, label, identifier_hash=hash_identifier(key, field_name=field))
                add_edge(right, left, label, identifier_hash=hash_identifier(key, field_name=field))


def finding_nodes(bundle: DataBundle, findings: list[Finding], add_node, add_edge) -> None:
    for finding in findings:
        finding_node = add_node(
            "Finding",
            finding.finding_id,
            finding_id=finding.finding_id,
            title=finding.title,
            pattern_type=finding.pattern_type,
            confidence=finding.confidence,
            status=finding.status,
            leakage_sar=finding.leakage_sar,
            recoverable_sar=finding.recoverable_sar,
            classification=finding.classification,
        )
        for vendor_id in str(finding.vendor_id).split("/"):
            vendor_id = vendor_id.strip()
            if vendor_id:
                vendor_node = add_node("Vendor", vendor_id, vendor_id=vendor_id, vendor_name=finding.vendor_name)
                add_edge(finding_node, vendor_node, "INVOLVES_VENDOR")
        for citation in finding.citations:
            evidence_node = add_node("Evidence", citation.source_path, source_path=citation.source_path, sha256=citation.source_hash)
            add_edge(finding_node, evidence_node, "SUPPORTED_BY", locator=citation.locator)


def extract_vendor_id(text: str) -> str | None:
    import re

    match = re.search(r"Vendor ID .*?:\s*(V-\d+)", text, re.I)
    return match.group(1) if match else None


def extract_contract_ref(text: str) -> str | None:
    import re

    match = re.search(r"Contract Reference:\s*([A-Z]+-\d{4}-\d+)", text, re.I)
    return match.group(1) if match else None


def pairwise(values: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for i, left in enumerate(values):
        for right in values[i + 1 :]:
            pairs.append((left, right))
    return pairs


def hash_identifier(value: Any, *, field_name: str = "identifier") -> str | None:
    if is_empty(value):
        return None
    return tokenize_sensitive_identifier(value, field_name=field_name)


def normalize_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except TypeError:
        return False
    return False
