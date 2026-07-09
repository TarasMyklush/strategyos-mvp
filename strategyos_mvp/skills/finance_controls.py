from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from ..config import CONFIG
from ..data_roles import role_target_paths
from ..evidence import page_locator, row_locator
from ..ingestion import DataBundle
from ..models import Citation, Finding
from ..plugins import load_configured_plugins
from ..sensitive_ids import tokenize_sensitive_identifier
from ..quality import apply_fail_closed_evidence_policy


@dataclass(frozen=True)
class DetectorMetadata:
    name: str
    pattern_type: str
    required_roles: tuple[str, ...]
    runner: Callable[[DataBundle], list[Finding]]


DETECTOR_REGISTRY: list[DetectorMetadata] = []
KNOWN_PATTERN_TYPES: frozenset[str] = frozenset()

ROLE_PATH_DEFAULTS = role_target_paths()


def refresh_role_path_defaults() -> None:
    global ROLE_PATH_DEFAULTS
    ROLE_PATH_DEFAULTS = role_target_paths()


def register_detector(pattern_type: str, required_roles: Iterable[str]):
    normalized_roles = tuple(str(role) for role in required_roles)

    def decorator(runner: Callable[[DataBundle], list[Finding]]) -> Callable[[DataBundle], list[Finding]]:
        global KNOWN_PATTERN_TYPES

        metadata = DetectorMetadata(
            name=runner.__name__,
            pattern_type=str(pattern_type),
            required_roles=normalized_roles,
            runner=runner,
        )
        if any(existing.name == metadata.name for existing in DETECTOR_REGISTRY):
            raise ValueError(f"Detector '{metadata.name}' is already registered.")
        if any(existing.pattern_type == metadata.pattern_type for existing in DETECTOR_REGISTRY):
            raise ValueError(f"Pattern type '{metadata.pattern_type}' is already registered.")
        DETECTOR_REGISTRY.append(metadata)
        KNOWN_PATTERN_TYPES = frozenset(detector.pattern_type for detector in DETECTOR_REGISTRY)
        return runner

    return decorator


def usd(sar: float) -> float:
    return round(float(sar) / CONFIG.finance_usd_rate, 2)


def rel_invoice_pdf(name_contains: str, bundle: DataBundle) -> str | None:
    needle = name_contains.lower()
    for rel in bundle.evidence.manifest:
        if rel.startswith("08_Invoices/") and rel.lower().endswith(".pdf") and needle in rel.lower():
            return rel
    return None


def vendor_name_filename_needle(vendor_name: str, *, word_count: int = 2) -> str:
    """Derive a filename-matching needle from a vendor's legal name.

    Invoice/contract PDFs in this evidence set are named from the vendor
    name with whitespace and punctuation stripped (e.g. "Gulf Logistics
    Services Co" -> "GulfLogistics", "Bordeaux Wines & Spirits SARL" ->
    "BordeauxWines") -- i.e. the first couple of significant words,
    concatenated. A single-word needle is too loose: several vendors in a
    real dataset can share a common first word ("Gulf Cosmetics" vs "Gulf
    Logistics" vs "Gulf Trading"), so rel_invoice_pdf's substring match
    would non-deterministically pick whichever matching file happens to
    come first in the manifest. Two words is specific enough to disambiguate
    while still tolerating minor legal-suffix differences (SARL/LLC/Co).
    """
    words = [w for w in re.findall(r"[A-Za-z0-9]+", vendor_name) if w]
    return "".join(words[:word_count])


def rel_contract_pdf(name_contains: str, bundle: DataBundle) -> str | None:
    needle = name_contains.lower()
    for rel in bundle.evidence.manifest:
        if rel.startswith("04_Contracts/") and rel.lower().endswith(".pdf") and needle in rel.lower():
            return rel
    return None


def _extract_vendor_id(text: str) -> str | None:
    match = re.search(r"Vendor ID\s*(?::|#)?\s*(V-\d+)", text, re.I)
    if match:
        return match.group(1)
    match = re.search(r"Vendor ID .*?:\s*(V-\d+)", text, re.I)
    return match.group(1) if match else None


def _invoice_ids_from_text(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"INV-\d{4}-\d+", text, re.I)))


def _pending_pdf_citation(bundle: DataBundle, rel_path: str, label: str, note: str) -> Citation:
    return bundle.evidence.citation(rel_path, label, note)


def _ocr_required_bank_statement(bundle: DataBundle) -> str | None:
    bank_rel = "01_Bank_Statements/EmiratesNBD_EUR_Jan-Jun_2026.pdf"
    if bank_rel in bundle.evidence.manifest:
        return bank_rel
    candidates = [
        rel
        for rel, status in bundle.evidence.ocr_status.items()
        if rel.startswith("01_Bank_Statements/") and status.get("required")
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def excel_citation(bundle: DataBundle, rel_path: str, row_index: int, excerpt: str) -> Citation:
    return bundle.evidence.citation(rel_path, row_locator(row_index), excerpt)


def pdf_citation(bundle: DataBundle, rel_path: str, label: str, terms: Iterable[str]) -> Citation | None:
    excerpt = bundle.evidence.pdf_excerpt(rel_path, terms)
    if not excerpt:
        return None
    page_match = re.search(r"page\s+(\d+)", excerpt, re.I)
    locator = page_locator(int(page_match.group(1)), label) if page_match else label
    return bundle.evidence.citation(rel_path, locator, excerpt)


def pdf_citation_with_anchor(
    bundle: DataBundle,
    rel_path: str,
    label: str,
    required_terms: Iterable[str],
    preferred_terms: Iterable[str] = (),
    max_chars: int = 500,
) -> Citation | None:
    pages = bundle.evidence.pdf_text.get(rel_path, [])
    lowered_required = [str(term).lower() for term in required_terms if str(term).strip()]
    lowered_preferred = [str(term).lower() for term in preferred_terms if str(term).strip()]
    for page_no, text in enumerate(pages, start=1):
        compact = " ".join(text.split())
        compact_low = compact.lower()
        if not all(term in compact_low for term in lowered_required):
            continue
        anchor_term = next((term for term in lowered_preferred if term in compact_low), None)
        if anchor_term is not None:
            anchor = compact_low.rfind(anchor_term)
        else:
            anchor_positions = [compact_low.rfind(term) for term in lowered_required if term in compact_low]
            anchor = max(anchor_positions) if anchor_positions else 0
        start = max(anchor - 80, 0)
        excerpt = f"page {page_no}: {compact[start:start + max_chars]}"
        return bundle.evidence.citation(rel_path, page_locator(page_no, label), excerpt)
    return None


def unique_citations(citations: Iterable[Citation | None]) -> list[Citation]:
    ordered: list[Citation] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for citation in citations:
        if citation is None:
            continue
        key = (citation.source_path, citation.locator, citation.excerpt, citation.source_hash)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(citation)
    return ordered


def first_matching_ap_row(bundle: DataBundle, vendor_id: str, po_id: str) -> tuple[int, pd.Series] | None:
    matches = bundle.ap[
        bundle.ap["Vendor_ID"].astype(str).eq(str(vendor_id))
        & bundle.ap["PO_Reference"].astype(str).eq(str(po_id))
    ].copy()
    if matches.empty:
        return None
    row = matches.sort_values(["Payment_Date", "Invoice_Date"], na_position="last").iloc[0]
    return int(row.name), row


def bank_payment_leg_citations(
    bundle: DataBundle,
    invoice_id: str,
    vendor_name: str,
    amount: float,
    payment_dates: Iterable[pd.Timestamp],
    payment_memos: Iterable[str] = (),
) -> list[Citation]:
    amount_text = f"{amount:,.2f}"
    paired_memos = list(payment_memos)
    citations: list[Citation] = []
    for position, payment_date in enumerate(payment_dates):
        if pd.isna(payment_date):
            continue
        date_text = payment_date.date().isoformat()
        memo_text = str(paired_memos[position]).strip() if position < len(paired_memos) else ""
        memo_terms: list[str] = []
        token_match = re.search(r"\b(?:WIRE|CHQ)-[A-Z0-9-]+\b", memo_text, re.I)
        if token_match:
            memo_terms.append(token_match.group(0))
        if re.search(r"che(?:q|ck)", memo_text, re.I):
            memo_terms.append("cheque payment")
        elif memo_text:
            memo_terms.append("wire payment")
        if memo_text:
            memo_terms.append(memo_text)
        match: Citation | None = None
        for rel in sorted(bundle.evidence.manifest):
            if not rel.startswith("01_Bank_Statements/") or not rel.lower().endswith(".pdf"):
                continue
            match = None
            for memo_term in memo_terms:
                match = pdf_citation_with_anchor(
                    bundle,
                    rel,
                    "bank statement payment leg",
                    [date_text, memo_term, amount_text],
                    [memo_term, date_text, invoice_id, vendor_name],
                )
                if match:
                    break
            if not match:
                match = pdf_citation_with_anchor(
                    bundle,
                    rel,
                    "bank statement payment leg",
                    [date_text, invoice_id, amount_text],
                    [date_text, invoice_id, vendor_name],
                )
            if not match and vendor_name:
                match = pdf_citation_with_anchor(
                    bundle,
                    rel,
                    "bank statement payment leg",
                    [date_text, vendor_name, amount_text],
                    [date_text, vendor_name],
                )
            if match:
                citations.append(match)
                break
    return unique_citations(citations)


def missing_ocr_required_evidence(bundle: DataBundle, rel_path: str, terms: Iterable[str]) -> bool:
    status = bundle.evidence.ocr_status.get(rel_path, {})
    if not status.get("required"):
        return False
    return not bool(bundle.evidence.pdf_excerpt(rel_path, terms))


def _available_roles(bundle: DataBundle) -> set[str] | None:
    available_roles = bundle.run_metadata.get("available_roles")
    if not isinstance(available_roles, list):
        return None
    return {str(role) for role in available_roles}


def _missing_required_roles(bundle: DataBundle, required_roles: Iterable[str]) -> list[str]:
    available_roles = _available_roles(bundle)
    if available_roles is None:
        return []
    return sorted(str(role) for role in required_roles if str(role) not in available_roles)


def detector_registry() -> tuple[DetectorMetadata, ...]:
    return tuple(DETECTOR_REGISTRY)


def _role_source_path(bundle: DataBundle, role: str) -> str:
    contract = bundle.data_contracts.get(role) if hasattr(bundle, "data_contracts") else None
    if isinstance(contract, dict) and contract.get("relative_path"):
        return str(contract["relative_path"])
    return ROLE_PATH_DEFAULTS[role]


def _first_manifest_entry(bundle: DataBundle, prefix: str, suffix: str = "") -> str | None:
    for rel in sorted(bundle.evidence.manifest):
        if rel.startswith(prefix) and (not suffix or rel.lower().endswith(suffix.lower())):
            return rel
    return None


def _find_email_text_citation(bundle: DataBundle, *terms: str) -> Citation | None:
    lowered_terms = [term.lower() for term in terms if term]
    for rel in sorted(bundle.evidence.manifest):
        if not rel.startswith("06_Email_Correspondence/"):
            continue
        text = (bundle.dataset_root / rel).read_text(encoding="utf-8", errors="ignore")
        compact = " ".join(text.split())
        lowered = compact.lower()
        if lowered_terms and not all(term in lowered for term in lowered_terms):
            continue
        return bundle.evidence.citation(rel, "text file", compact[:400])
    return None


def _find_pdf_by_excerpt(bundle: DataBundle, prefix: str, label: str, terms: Iterable[str]) -> tuple[str, Citation] | None:
    for rel in sorted(bundle.evidence.manifest):
        if not rel.startswith(prefix) or not rel.lower().endswith(".pdf"):
            continue
        citation = pdf_citation(bundle, rel, label, terms)
        if citation is not None:
            return rel, citation
    return None


def run_all_finance_skills(bundle: DataBundle) -> list[Finding]:
    load_configured_plugins()
    refresh_role_path_defaults()
    findings: list[Finding] = []
    executed_detectors: list[dict[str, object]] = []
    skipped_detectors: list[dict[str, object]] = []
    for detector in detector_registry():
        missing_roles = _missing_required_roles(bundle, detector.required_roles)
        if missing_roles:
            skipped_detectors.append(
                {
                    "detector": detector.name,
                    "pattern_type": detector.pattern_type,
                    "required_roles": list(detector.required_roles),
                    "missing_roles": missing_roles,
                    "reason": "Source pack did not provide all required structured roles for this detector.",
                }
            )
            continue
        detector_findings = detector.runner(bundle)
        findings.extend(detector_findings)
        executed_detectors.append(
            {
                "detector": detector.name,
                "pattern_type": detector.pattern_type,
                "required_roles": list(detector.required_roles),
                "finding_count": len(detector_findings),
            }
        )
    _run_graph_detectors(bundle, findings, executed_detectors, skipped_detectors)
    findings.sort(key=lambda f: (f.recoverable_sar, f.leakage_sar), reverse=True)
    for i, finding in enumerate(findings, start=1):
        finding.finding_id = f"F-{i:03d}"
    apply_fail_closed_evidence_policy(bundle, findings)
    bundle.detector_report = {
        "executed_detectors": executed_detectors,
        "skipped_detectors": skipped_detectors,
    }
    return findings


def _run_graph_detectors(
    bundle: DataBundle,
    findings: list[Finding],
    executed_detectors: list[dict[str, object]],
    skipped_detectors: list[dict[str, object]],
) -> None:
    """Run graph-native detectors over the in-memory structural graph and merge
    their findings into the same list (before sort/re-ID). Imported lazily to
    avoid a circular import (graph_controls depends on this module). Degrades
    cleanly: a structural-graph build failure skips graph detectors and leaves
    row findings untouched."""
    from ..knowledge_graph import build_structural_graph
    from .graph_controls import graph_detector_registry

    registry = graph_detector_registry()
    if not registry:
        return
    try:
        graph = build_structural_graph(bundle)
    except Exception as exc:  # pragma: no cover - defensive
        for detector in registry:
            skipped_detectors.append(
                {
                    "detector": detector.name,
                    "pattern_type": detector.pattern_type,
                    "required_roles": list(detector.required_roles),
                    "missing_roles": [],
                    "reason": f"Structural graph could not be built: {exc}",
                }
            )
        return
    for detector in registry:
        missing_roles = _missing_required_roles(bundle, detector.required_roles)
        if missing_roles:
            skipped_detectors.append(
                {
                    "detector": detector.name,
                    "pattern_type": detector.pattern_type,
                    "required_roles": list(detector.required_roles),
                    "missing_roles": missing_roles,
                    "reason": "Source pack did not provide all required structured roles for this detector.",
                }
            )
            continue
        detector_findings = detector.runner(graph, bundle)
        findings.extend(detector_findings)
        executed_detectors.append(
            {
                "detector": detector.name,
                "pattern_type": detector.pattern_type,
                "required_roles": list(detector.required_roles),
                "finding_count": len(detector_findings),
                "engine": "graph",
            }
        )


@register_detector("duplicate_payment", ("ap_ledger",))
def detect_duplicate_payments(bundle: DataBundle) -> list[Finding]:
    ap = bundle.ap[bundle.ap["Status"].eq("Paid")].copy()
    results: list[Finding] = []
    grouped = ap.groupby("Invoice_ID", dropna=True)
    for invoice_id, rows in grouped:
        if len(rows) < 2:
            continue
        amounts = rows["Amount_SAR"].round(2).unique()
        if len(amounts) != 1:
            continue
        amount = float(amounts[0])
        vendor_id = str(rows.iloc[0]["Vendor_ID"])
        vendor_name = str(rows.iloc[0]["Vendor_Name"])
        duplicate_count = len(rows) - 1
        recoverable = amount * duplicate_count
        citations = [
            excel_citation(
                bundle,
                _role_source_path(bundle, "ap_ledger"),
                int(idx),
                f"{invoice_id}; {row.PO_Reference}; paid {row.Amount_SAR:,.2f} on {row.Payment_Date.date().isoformat() if pd.notna(row.Payment_Date) else 'n/a'}; memo {row.Memo}",
            )
            for idx, row in rows.iterrows()
        ]
        pdf = rel_invoice_pdf(str(invoice_id).replace("INV-", "").replace("2026-", ""), bundle)
        if pdf:
            citations.append(pdf_citation(bundle, pdf, "invoice page", [str(invoice_id)]))
        vendor_rows = bundle.vendors[bundle.vendors["Vendor_ID"].astype(str).eq(vendor_id)]
        if not vendor_rows.empty:
            vendor_row = vendor_rows.iloc[0]
            citations.append(
                excel_citation(
                    bundle,
                    _role_source_path(bundle, "vendor_master"),
                    int(vendor_row.name),
                    f"{vendor_row.Vendor_ID}; {vendor_row.Vendor_Name}; contract={vendor_row.Contract_Reference}",
                )
            )
        citations.extend(
            bank_payment_leg_citations(
                bundle,
                str(invoice_id),
                vendor_name,
                amount,
                rows["Payment_Date"].tolist(),
                rows["Memo"].astype(str).tolist(),
            )
        )
        citations = unique_citations(citations)
        results.append(
            Finding(
                finding_id="draft",
                title=f"Duplicate payment for invoice {invoice_id}",
                pattern_type="duplicate_payment",
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                leakage_sar=recoverable,
                recoverable_sar=recoverable,
                recoverable_usd=usd(recoverable),
                confidence="HIGH" if len(citations) >= 3 else "MEDIUM",
                classification="CASH (recoverable now)",
                rationale="Same paid Invoice_ID appears more than once in AP at the same amount.",
                remediation="AP should immediately recover the duplicate payment from the vendor or offset it against the next payable; AP controls owner should block duplicate Invoice_ID payments.",
                citations=citations,
                calculation={"duplicate_count": duplicate_count, "amount_sar": amount},
            )
        )
    return results


@register_detector("entity_resolution_duplicate", ("ap_ledger", "vendor_master"))
def detect_entity_resolution_duplicates(bundle: DataBundle) -> list[Finding]:
    vendors = bundle.vendors.copy()
    candidates: list[Finding] = []
    for field in ["Tax_ID", "Bank_Account"]:
        for key, group in vendors.dropna(subset=[field]).groupby(field):
            if len(group) < 2:
                continue
            vendor_ids = group["Vendor_ID"].astype(str).tolist()
            ap_rows = bundle.ap[bundle.ap["Vendor_ID"].astype(str).isin(vendor_ids)]
            if ap_rows.empty:
                continue
            paid = ap_rows[ap_rows["Status"].eq("Paid")]
            exposure = float(paid["Amount_SAR"].sum())
            shared_token = tokenize_sensitive_identifier(key, field_name=field) or "none"
            citations = [
                excel_citation(
                    bundle,
                    _role_source_path(bundle, "vendor_master"),
                    int(idx),
                    f"{row.Vendor_ID}; {row.Vendor_Name}; Tax_ID_token={tokenize_sensitive_identifier(row.Tax_ID, field_name='Tax_ID') or 'none'}; Bank_Account_token={tokenize_sensitive_identifier(row.Bank_Account, field_name='Bank_Account') or 'none'}; shared_{field.lower()}_token={shared_token}; contract={row.Contract_Reference}",
                )
                for idx, row in group.iterrows()
            ]
            for vendor_id in vendor_ids:
                vendor_paid = paid[paid["Vendor_ID"].astype(str).eq(vendor_id)].sort_values("Payment_Date")
                if vendor_paid.empty:
                    continue
                idx, row = int(vendor_paid.iloc[0].name), vendor_paid.iloc[0]
                citations.append(
                    excel_citation(
                        bundle,
                        _role_source_path(bundle, "ap_ledger"),
                        idx,
                        f"{row.Invoice_ID}; {row.Vendor_ID}; shared_{field.lower()}_token={shared_token}; paid SAR {row.Amount_SAR:,.2f}; memo {row.Memo}",
                    )
                )
            citations = unique_citations(citations)
            candidates.append(
                Finding(
                    finding_id="draft",
                    title=f"Duplicate vendor identity across {', '.join(vendor_ids)}",
                    pattern_type="entity_resolution_duplicate",
                    vendor_id="/".join(vendor_ids),
                    vendor_name=" / ".join(group["Vendor_Name"].astype(str).tolist()),
                    leakage_sar=exposure,
                    recoverable_sar=exposure,
                    recoverable_usd=usd(exposure),
                    confidence="HIGH",
                    classification="CASH (recoverable/control dependent)",
                    rationale=f"Multiple active vendor records share the same {field}, creating duplicate-payment and contract-bypass risk.",
                    remediation="Vendor master owner should merge the duplicate records, freeze the non-contract vendor, and review paid invoices for duplicate or off-contract recovery.",
                    citations=citations,
                    calculation={"identity_field": field, "identity_value": shared_token, "paid_exposure_sar": exposure},
                )
            )
    unique: dict[str, Finding] = {}
    for finding in candidates:
        unique.setdefault(finding.vendor_id, finding)
    return list(unique.values())


@register_detector("off_contract_single_approver", ("ap_ledger", "vendor_master"))
def detect_off_contract_single_approver(bundle: DataBundle) -> list[Finding]:
    vm = bundle.vendors[["Vendor_ID", "Contract_Reference"]]
    ap = bundle.ap.merge(vm, on="Vendor_ID", how="left")
    no_contract = ap[ap["Contract_Reference"].isna() & ap["PO_Reference"].isna() & ap["Status"].eq("Paid")]
    findings: list[Finding] = []
    for vendor_id, rows in no_contract.groupby("Vendor_ID"):
        if len(rows) < CONFIG.finance_off_contract_min_invoices:
            continue
        top_approver = rows["Approver_Email"].mode().iloc[0]
        approver_rows = rows[rows["Approver_Email"].eq(top_approver)]
        if len(approver_rows) / len(rows) < CONFIG.finance_off_contract_single_approver_ratio:
            continue
        exposure = float(rows["Amount_SAR"].sum())
        vendor_name = str(rows.iloc[0]["Vendor_Name"])
        citations = []
        vm_rows = bundle.vendors[bundle.vendors["Vendor_ID"].astype(str).eq(str(vendor_id))]
        for idx, row in vm_rows.iterrows():
            citations.append(excel_citation(bundle, _role_source_path(bundle, "vendor_master"), int(idx), f"{row.Vendor_ID} has no contract reference."))
        for idx, row in rows.head(3).iterrows():
            citations.append(excel_citation(bundle, _role_source_path(bundle, "ap_ledger"), int(idx), f"{row.Invoice_ID}; no PO; approver {row.Approver_Email}; SAR {row.Amount_SAR:,.2f}"))
        email_citation = _find_email_text_citation(bundle, vendor_name.split()[0], str(top_approver).split("@")[0])
        if email_citation is not None:
            citations.append(email_citation)
        findings.append(
            Finding(
                finding_id="draft",
                title=f"Off-contract spend approved by single approver at {vendor_name}",
                pattern_type="off_contract_single_approver",
                vendor_id=str(vendor_id),
                vendor_name=vendor_name,
                leakage_sar=exposure,
                recoverable_sar=0.0,
                recoverable_usd=0.0,
                confidence="HIGH" if len(citations) >= 3 else "MEDIUM",
                classification="CONTROLS ONLY",
                rationale="Paid AP spend has no contract, no PO reference, and is concentrated under one approver.",
                remediation="Procurement and AP should block future no-PO spend, require dual approval, and run a pricing reasonableness review before renewal or recovery discussions.",
                citations=citations,
                calculation={"paid_exposure_sar": exposure, "invoice_count": len(rows), "approver": top_approver},
            )
        )
    return findings


@register_detector("price_variance", ("ap_ledger", "purchase_orders"))
def detect_price_variance(bundle: DataBundle) -> list[Finding]:
    po = bundle.po.copy()
    po["month"] = po["PO_Date"].dt.to_period("M")
    findings: list[Finding] = []
    for (vendor_id, sku, month), rows in po.groupby(["Vendor_ID", "SKU", "month"]):
        if len(rows) < 2:
            continue
        min_price = float(rows["Unit_Price"].min())
        max_price = float(rows["Unit_Price"].max())
        if max_price <= min_price:
            continue
        high_rows = rows[rows["Unit_Price"].eq(max_price)]
        vendor_name = str(rows.iloc[0]["Vendor_Name"])
        excess = float(((high_rows["Unit_Price"] - min_price) * high_rows["Quantity"]).sum())
        if excess < CONFIG.finance_price_variance_min_excess_sar:
            continue
        baseline_row = rows.sort_values(["Unit_Price", "PO_Date", "PO_ID"]).iloc[0]
        high_row = high_rows.sort_values(["PO_Date", "PO_ID"]).iloc[0]
        citations = [
            excel_citation(
                bundle,
                _role_source_path(bundle, "purchase_orders"),
                int(baseline_row.name),
                f"{baseline_row.PO_ID}; {sku}; {baseline_row.Quantity} units @ SAR {baseline_row.Unit_Price:,.2f}; vendor {vendor_id}",
            ),
            excel_citation(
                bundle,
                _role_source_path(bundle, "purchase_orders"),
                int(high_row.name),
                f"{high_row.PO_ID}; {sku}; {high_row.Quantity} units @ SAR {high_row.Unit_Price:,.2f}; vendor {vendor_id}",
            ),
        ]
        contract = rel_contract_pdf(vendor_name.split()[0], bundle)
        if contract:
            citations.append(pdf_citation(bundle, contract, "contract price schedule", [str(sku), f"{min_price:.2f}"]))
        for po_row in [baseline_row, high_row]:
            match = first_matching_ap_row(bundle, str(vendor_id), str(po_row.PO_ID))
            if match is None:
                continue
            idx, row = match
            citations.append(
                excel_citation(
                    bundle,
                    _role_source_path(bundle, "ap_ledger"),
                    idx,
                    f"{row.Invoice_ID}; {row.PO_Reference}; SAR {row.Amount_SAR:,.2f}; memo {row.Memo}",
                )
            )
        citations = unique_citations(citations)
        findings.append(
            Finding(
                finding_id="draft",
                title=f"Price variance for {sku} at {vendor_name}",
                pattern_type="price_variance",
                vendor_id=str(vendor_id),
                vendor_name=vendor_name,
                leakage_sar=excess,
                recoverable_sar=excess,
                recoverable_usd=usd(excess),
                confidence="HIGH" if len(citations) >= 3 else "MEDIUM",
                classification="CASH (recoverable now)",
                rationale="Same vendor and SKU were bought in the same month at a higher unit price than the comparable baseline.",
                remediation="AP should claim the contract/baseline price variance from the vendor and require procurement approval for emergency restock price overrides.",
                citations=citations,
                calculation={"baseline_unit_price": min_price, "high_unit_price": max_price, "excess_sar": excess},
            )
        )
    return findings


@register_detector("missed_early_pay_discount", ("ap_ledger",))
def detect_missed_early_pay_discounts(bundle: DataBundle) -> list[Finding]:
    discount_vendors = []
    for rel, pages in bundle.evidence.pdf_text.items():
        if not rel.startswith("04_Contracts/"):
            continue
        text = " ".join(pages)
        if re.search(r"2\s*/\s*10\s+net\s+30", text, re.I):
            vendor_id = _extract_vendor_id(text)
            if vendor_id:
                discount_vendors.append((vendor_id, rel))
    findings: list[Finding] = []
    for vendor_id, contract in discount_vendors:
        rows = bundle.ap[
            bundle.ap["Vendor_ID"].astype(str).eq(vendor_id)
            & bundle.ap["Status"].eq("Paid")
            & bundle.ap["Payment_Date"].notna()
        ].copy()
        rows["days_to_pay"] = (rows["Payment_Date"] - rows["Invoice_Date"]).dt.days
        missed = rows[
            (rows["days_to_pay"] > CONFIG.finance_early_pay_discount_window_days)
            & (rows["Memo"].astype(str).str.contains("2/10", na=False))
        ]
        if missed.empty:
            continue
        recoverable = float(
            (missed["Amount_SAR"] * CONFIG.finance_early_pay_discount_rate).sum()
        )
        vendor_name = str(missed.iloc[0]["Vendor_Name"])
        citations = []
        contract_citation = pdf_citation(
            bundle,
            contract,
            "contract payment terms",
            ["2/10", "net 30"],
        )
        if contract_citation is not None:
            citations.append(contract_citation)
        for idx, row in missed.head(5).iterrows():
            citations.append(excel_citation(bundle, _role_source_path(bundle, "ap_ledger"), int(idx), f"{row.Invoice_ID}; paid in {int(row.days_to_pay)} days; SAR {row.Amount_SAR:,.2f}; {CONFIG.finance_early_pay_discount_rate:.0%}={row.Amount_SAR*CONFIG.finance_early_pay_discount_rate:,.2f}"))
        findings.append(
            Finding(
                finding_id="draft",
                title=f"Missed 2/10 net 30 discounts at {vendor_name}",
                pattern_type="missed_early_pay_discount",
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                leakage_sar=recoverable,
                recoverable_sar=recoverable,
                recoverable_usd=usd(recoverable),
                confidence="HIGH",
                classification="CASH (recoverable going-forward)",
                rationale="Contract and invoice memos establish 2/10 net 30 terms, but invoices were paid after the discount window.",
                remediation="Treasury/AP should prioritize these invoices in payment runs and negotiate any retroactive recovery with the vendor.",
                citations=citations,
                calculation={"discount_rate": CONFIG.finance_early_pay_discount_rate, "invoice_count": len(missed), "recoverable_sar": recoverable},
            )
        )
    return findings


@register_detector("auto_renewal_escalation", ("ap_ledger",))
def detect_auto_renewal_escalation(bundle: DataBundle) -> list[Finding]:
    findings: list[Finding] = []
    for rel, pages in bundle.evidence.pdf_text.items():
        if not rel.startswith("04_Contracts/"):
            continue
        text = " ".join(pages)
        if "Automatic Renewal" not in text or "CPI" not in text:
            continue
        vendor_id = _extract_vendor_id(text)
        base_match = re.search(r"Base monthly service fee SAR\s*([\d,]+)", text)
        if not vendor_id or not base_match:
            continue
        base_fee = float(base_match.group(1).replace(",", ""))
        rows = bundle.ap[bundle.ap["Vendor_ID"].astype(str).eq(vendor_id) & bundle.ap["Status"].eq("Paid")]
        if rows.empty:
            continue
        monthly_fee = float(rows["Amount_SAR"].median())
        excess = float(((rows["Amount_SAR"] - base_fee).clip(lower=0)).sum())
        if excess <= 0:
            continue
        vendor_name = str(rows.iloc[0]["Vendor_Name"])
        citations = []
        contract_citation = pdf_citation(
            bundle,
            rel,
            "contract renewal/escalation",
            ["Automatic Renewal", "CPI"],
        )
        if contract_citation is not None:
            citations.append(contract_citation)
        invoice_pdf = rel_invoice_pdf(vendor_name_filename_needle(vendor_name), bundle)
        if invoice_pdf:
            invoice_citation = pdf_citation(
                bundle,
                invoice_pdf,
                "invoice rate basis",
                ["base monthly fee", "2026 escalation"],
            )
            if invoice_citation is not None:
                citations.append(invoice_citation)
        for idx, row in rows.head(3).iterrows():
            citations.append(excel_citation(bundle, _role_source_path(bundle, "ap_ledger"), int(idx), f"{row.Invoice_ID}; SAR {row.Amount_SAR:,.2f}; base SAR {base_fee:,.2f}"))
        findings.append(
            Finding(
                finding_id="draft",
                title=f"Auto-renewal escalation at {vendor_name}",
                pattern_type="auto_renewal_escalation",
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                leakage_sar=excess,
                recoverable_sar=excess,
                recoverable_usd=usd(excess),
                confidence="HIGH",
                classification="CASH (recoverable going-forward)",
                rationale="Auto-renewal clause escalated the monthly service fee above the prior baseline without renegotiation.",
                remediation="Legal/procurement should renegotiate or terminate the renewed contract and capture going-forward savings in the logistics run rate.",
                citations=citations,
                calculation={"base_fee_sar": base_fee, "current_monthly_fee_sar": monthly_fee, "months": len(rows), "excess_sar": excess},
            )
        )
    return findings


@register_detector("fx_hedge_unapplied", ("ap_ledger", "cash_forecast"))
def detect_fx_hedge_unapplied(bundle: DataBundle) -> list[Finding]:
    findings: list[Finding] = []
    hedges = bundle.cash_forecast.get("Hedges")
    if hedges is None:
        return findings
    hedge_text = " ".join(str(x) for x in hedges.fillna("").to_numpy().ravel())
    rate_values = [float(x) for x in re.findall(r"\b3\.\d{2,4}\b", hedge_text)]
    hedge_rate = min(rate_values) if rate_values else CONFIG.finance_fx_hedge_default_rate
    invoice_ids = _invoice_ids_from_text(hedge_text)
    rows = bundle.ap[
        bundle.ap["Currency"].astype(str).str.upper().eq("EUR")
        & bundle.ap["Status"].eq("Paid")
    ].copy()
    if invoice_ids:
        rows = rows[rows["Invoice_ID"].astype(str).isin(invoice_ids)].copy()
    if rows.empty:
        return findings
    # Pick the invoice whose SAR/EUR rate diverges most from hedge rate. When
    # the hedge note names no specific invoice, this selection alone (across
    # every EUR/Paid row) is the general case -- no vendor-name literal
    # needed to narrow it down.
    rows["applied_rate"] = rows["Amount_SAR"] / rows["Amount_Original_Currency"]
    rows["rate_delta"] = rows["applied_rate"] - hedge_rate
    target = rows.sort_values("rate_delta", ascending=False).iloc[0]
    exposure = float((target["applied_rate"] - hedge_rate) * float(target["Amount_Original_Currency"]))
    if exposure <= 0:
        return findings
    vendor_name = str(target.Vendor_Name)
    eur_amount_text = f"{float(target.Amount_Original_Currency):,.2f}"
    applied_rate_text = f"{float(target.applied_rate):.4f}"
    # Two-word vendor-name prefix, e.g. "Bordeaux Wines": specific enough to
    # anchor the OCR/email excerpt search to this vendor without needing the
    # full legal name (which may be truncated or abbreviated in scanned bank
    # statement text -- see vendor_name_filename_needle for the matching
    # filename-oriented derivation).
    vendor_prefix_words = [w for w in re.findall(r"[A-Za-z0-9]+", vendor_name) if w][:2]
    vendor_prefix = " ".join(vendor_prefix_words)
    bank_ocr_terms = [vendor_prefix, eur_amount_text, applied_rate_text]

    citations = [
        excel_citation(bundle, _role_source_path(bundle, "ap_ledger"), int(target.name), f"{target.Invoice_ID}; EUR {target.Amount_Original_Currency:,.2f}; SAR {target.Amount_SAR:,.2f}; applied rate {target.applied_rate:.4f}"),
        bundle.evidence.citation(_role_source_path(bundle, "cash_forecast"), "Hedges sheet", hedge_text[:400]),
    ]
    invoice_pdf = rel_invoice_pdf(vendor_name_filename_needle(vendor_name), bundle)
    if invoice_pdf:
        invoice_citation = pdf_citation(
            bundle,
            invoice_pdf,
            "EUR invoice",
            [str(target.Invoice_ID)],
        )
        if invoice_citation is not None:
            citations.append(invoice_citation)
    bank_rel = _ocr_required_bank_statement(bundle)
    bank_match = None
    missing_bank_ocr = False
    if bank_rel and bank_rel in bundle.evidence.manifest:
        missing_bank_ocr = missing_ocr_required_evidence(bundle, bank_rel, bank_ocr_terms)
        bank_citation = pdf_citation(bundle, bank_rel, "OCR bank statement settlement row", bank_ocr_terms)
        if bank_citation is not None:
            bank_match = (bank_rel, bank_citation)
    if bank_match is None:
        bank_match = _find_pdf_by_excerpt(bundle, "01_Bank_Statements/", "OCR bank statement settlement row", bank_ocr_terms)
    if bank_match is not None:
        bank_rel, bank_citation = bank_match
        citations.append(bank_citation)
        if not missing_bank_ocr:
            missing_bank_ocr = missing_ocr_required_evidence(bundle, bank_rel, bank_ocr_terms)
    elif bank_rel and bank_rel in bundle.evidence.manifest:
        missing_bank_ocr = True
        citations.append(
            _pending_pdf_citation(
                bundle,
                bank_rel,
                "OCR bank statement settlement row (verification pending)",
                f"OCR-required bank statement evidence pending verification for {vendor_prefix} / EUR {eur_amount_text} / {applied_rate_text}.",
            )
        )
    email_citation = _find_email_text_citation(bundle, vendor_prefix.lower())
    if email_citation is not None:
        citations.append(email_citation)
    confidence = "LOW" if missing_bank_ocr else "HIGH" if len(citations) >= 3 else "MEDIUM"
    rationale = "EUR invoice was settled at a rate above an available hedge rate in the treasury forecast."
    if missing_bank_ocr:
        rationale += " OCR-required bank statement evidence is missing, so the finding is downgraded pending verified OCR output."
    findings.append(
        Finding(
            finding_id="draft",
            title=f"FX hedge not applied for {target.Invoice_ID}",
            pattern_type="fx_hedge_unapplied",
            vendor_id=str(target.Vendor_ID),
            vendor_name=str(target.Vendor_Name),
            leakage_sar=exposure,
            recoverable_sar=exposure,
            recoverable_usd=usd(exposure),
            confidence=confidence,
            classification="CASH (recoverable going-forward)",
            rationale=rationale,
            remediation="Treasury and AP should enforce hedge application checks before EUR vendor settlement and include hedge IDs in payment approval.",
            citations=citations,
            calculation={"applied_rate": float(target.applied_rate), "hedge_rate": hedge_rate, "eur_amount": float(target.Amount_Original_Currency), "exposure_sar": exposure},
        )
    )
    return findings


@register_detector("dormant_credit_balance", ("ap_ledger", "gl_extract"))
def detect_dormant_credit_balance(bundle: DataBundle) -> list[Finding]:
    gl = bundle.gl.copy()
    candidates = gl[
        gl["Reference"].astype(str).str.contains("CR-", na=False)
        & (gl["Credit"].fillna(0) > 0)
    ]
    findings: list[Finding] = []
    for idx, credit in candidates.iterrows():
        reference = str(credit["Reference"])
        amount = float(credit["Credit"])
        ap_rows = bundle.ap[
            bundle.ap["Memo"].astype(str).str.contains(reference, case=False, na=False)
            & bundle.ap["Status"].eq("Paid")
        ]
        if ap_rows.empty:
            continue
        vendor_id = str(ap_rows.iloc[0]["Vendor_ID"])
        vendor_name = str(ap_rows.iloc[0]["Vendor_Name"])
        citations = [
            excel_citation(
                bundle,
                _role_source_path(bundle, "gl_extract"),
                int(idx),
                f"{reference}; credit SAR {amount:,.2f}",
            )
        ]
        credit_pdf = rel_invoice_pdf(reference, bundle)
        if credit_pdf:
            credit_citation = pdf_citation(bundle, credit_pdf, "credit note", [reference])
            if credit_citation is not None:
                citations.append(credit_citation)
        for idx, row in ap_rows.head(3).iterrows():
            citations.append(excel_citation(bundle, _role_source_path(bundle, "ap_ledger"), int(idx), f"{row.Invoice_ID}; paid SAR {row.Amount_SAR:,.2f}; memo references {reference}"))
        findings.append(
            Finding(
                finding_id="draft",
                title=f"Dormant supplier credit not offset: {reference}",
                pattern_type="dormant_credit_balance",
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                leakage_sar=amount,
                recoverable_sar=amount,
                recoverable_usd=usd(amount),
                confidence="HIGH",
                classification="CASH (recoverable now)",
                rationale="Open supplier credit remained in GL while later invoices from the same vendor were paid in full.",
                remediation="AP should offset the credit against the next payment or request refund; controller should add an aging review for open vendor credits.",
                citations=citations,
                calculation={"credit_reference": reference, "credit_sar": amount, "paid_invoice_count": len(ap_rows)},
            )
        )
    return findings


def _task1_invoice_index(findings: Iterable[Finding]) -> dict[str, set[str]]:
    pattern = re.compile(r"\b(?:INV|AR)-\d{4}-\d+\b")
    invoice_index: dict[str, set[str]] = {}
    for finding in findings:
        text = " ".join(c.excerpt for c in finding.citations) + f" {finding.calculation}"
        for invoice_id in pattern.findall(text):
            invoice_index.setdefault(invoice_id, set()).add(finding.finding_id)
    return invoice_index


def _classify_signal(
    qualifying: pd.DataFrame,
    position: int,
    week_amount: float,
    driver_amount: float,
) -> tuple[str, str]:
    same_sign = 1
    for offset in (-1, 1):
        pointer = position + offset
        while 0 <= pointer < len(qualifying):
            peer = qualifying.iloc[pointer]
            if int(peer["sign"]) != int(qualifying.iloc[position]["sign"]):
                break
            same_sign += 1
            pointer += offset
    concentration = driver_amount / week_amount if week_amount else 0.0
    if (
        qualifying.iloc[position]["count"]
        < CONFIG.finance_working_capital_min_weekly_invoice_count
        or week_amount < CONFIG.finance_working_capital_min_weekly_amount_sar
        or concentration >= CONFIG.finance_working_capital_max_driver_concentration
    ):
        return "one-time", f"thin/concentrated week (top drivers {concentration:.0%} of weekly SAR amount)."
    if same_sign >= CONFIG.finance_working_capital_min_consecutive_drift_weeks:
        return "systemic", f"same-direction drift persisted for {same_sign} consecutive qualifying invoice weeks."
    return "one-time", "adjacent weeks do not show the same-direction drift pattern."


def compute_working_capital_drifts(bundle: DataBundle, findings: list[Finding] | None = None) -> list[dict]:
    findings = findings or []
    task1_invoice_index = _task1_invoice_index(findings)
    candidates: list[dict] = []
    metric_configs = [
        (
            "DSO",
            bundle.ar[bundle.ar["Collection_Date"].notna()].copy(),
            "Collection_Date",
            "Customer_Name",
            _role_source_path(bundle, "ar_ledger"),
        ),
        (
            "DPO",
            bundle.ap[bundle.ap["Payment_Date"].notna()].copy(),
            "Payment_Date",
            "Vendor_Name",
            _role_source_path(bundle, "ap_ledger"),
        ),
    ]
    for label, df, settlement_col, counterparty_col, source_path in metric_configs:
        if df.empty:
            continue
        metric = "days_to_collect" if label == "DSO" else "days_to_pay"
        df[metric] = (df[settlement_col] - df["Invoice_Date"]).dt.days
        df["week_end"] = df["Invoice_Date"].dt.to_period("W-SUN").dt.end_time.dt.normalize()
        trailing = (
            df.groupby("week_end")
            .agg(days=(metric, "mean"), amount=("Amount_SAR", "sum"), count=("Amount_SAR", "size"))
            .reset_index()
            .sort_values("week_end")
            .tail(13)
            .reset_index(drop=True)
        )
        if len(trailing) < 4:
            continue
        baseline = float(trailing["days"].mean())
        trailing["drift_days"] = trailing["days"] - baseline
        qualifying = trailing[
            trailing["drift_days"].abs()
            >= CONFIG.finance_working_capital_min_drift_days
        ].copy().reset_index(drop=True)
        if qualifying.empty:
            continue
        qualifying["sign"] = qualifying["drift_days"].apply(lambda value: 1 if value > 0 else -1)
        for position, row in qualifying.iterrows():
            drivers = df[df["week_end"].eq(row["week_end"])].sort_values(metric, ascending=False).head(3)
            driver_records = []
            overlap_invoices: set[str] = set()
            overlap_findings: set[str] = set()
            for idx, driver in drivers.iterrows():
                invoice_id = str(driver["Invoice_ID"])
                linked_findings = sorted(task1_invoice_index.get(invoice_id, set()))
                overlap_invoices.update([invoice_id] if linked_findings else [])
                overlap_findings.update(linked_findings)
                driver_records.append(
                    {
                        "invoice_id": invoice_id,
                        "counterparty": str(driver[counterparty_col]),
                        "amount_sar": round(float(driver["Amount_SAR"]), 2),
                        "days": int(driver[metric]),
                        "citation": excel_citation(
                            bundle,
                            source_path,
                            int(idx),
                            f"{invoice_id}; {driver[counterparty_col]}; SAR {float(driver['Amount_SAR']):,.2f}; {metric}={int(driver[metric])}",
                        ),
                        "task1_overlap_findings": linked_findings,
                    }
                )
            classification, reason = _classify_signal(
                qualifying,
                position,
                float(row["amount"]),
                float(drivers["Amount_SAR"].sum()) if not drivers.empty else 0.0,
            )
            cash_effect = "absorbed" if label == "DSO" and row["drift_days"] > 0 else "released"
            if label == "DPO":
                cash_effect = "released" if row["drift_days"] > 0 else "absorbed"
            candidates.append(
                {
                    "metric": label,
                    "week_end": row["week_end"].date().isoformat(),
                    "baseline_days": round(baseline, 2),
                    "current_days": round(float(row["days"]), 2),
                    "drift_days": round(float(row["drift_days"]), 2),
                    "weekly_amount_sar": round(float(row["amount"]), 2),
                    "cash_impact_sar": round(float(row["amount"]) * abs(float(row["drift_days"])) / max(float(row["days"]), 1), 2),
                    "cash_effect": cash_effect,
                    "classification": classification,
                    "classification_reason": reason,
                    "drivers": driver_records,
                    "task1_overlap": {
                        "invoice_ids": sorted(overlap_invoices),
                        "finding_ids": sorted(overlap_findings),
                    },
                }
            )
    if not candidates:
        return []
    ranked = sorted(candidates, key=lambda item: item["cash_impact_sar"], reverse=True)
    selected: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    for metric in ("DSO", "DPO"):
        metric_best = next((item for item in ranked if item["metric"] == metric), None)
        if metric_best is None:
            continue
        key = (metric_best["metric"], metric_best["week_end"])
        if key not in seen_keys:
            selected.append(metric_best)
            seen_keys.add(key)
    for item in ranked:
        key = (item["metric"], item["week_end"])
        if key in seen_keys:
            continue
        selected.append(item)
        seen_keys.add(key)
        if len(selected) == 3:
            break
    return sorted(selected[:3], key=lambda item: item["cash_impact_sar"], reverse=True)
