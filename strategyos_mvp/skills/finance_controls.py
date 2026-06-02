from __future__ import annotations

import math
import re
from typing import Iterable

import pandas as pd

from ..evidence import row_locator
from ..ingestion import DataBundle
from ..models import Citation, Finding

USD_RATE = 3.75


def usd(sar: float) -> float:
    return round(float(sar) / USD_RATE, 2)


def rel_invoice_pdf(name_contains: str, bundle: DataBundle) -> str | None:
    needle = name_contains.lower()
    for rel in bundle.evidence.manifest:
        if rel.startswith("08_Invoices/") and rel.lower().endswith(".pdf") and needle in rel.lower():
            return rel
    return None


def rel_contract_pdf(name_contains: str, bundle: DataBundle) -> str | None:
    needle = name_contains.lower()
    for rel in bundle.evidence.manifest:
        if rel.startswith("04_Contracts/") and rel.lower().endswith(".pdf") and needle in rel.lower():
            return rel
    return None


def excel_citation(bundle: DataBundle, rel_path: str, row_index: int, excerpt: str) -> Citation:
    return bundle.evidence.citation(rel_path, row_locator(row_index), excerpt)


def run_all_finance_skills(bundle: DataBundle) -> list[Finding]:
    skills = [
        detect_duplicate_payments,
        detect_entity_resolution_duplicates,
        detect_off_contract_single_approver,
        detect_price_variance,
        detect_missed_early_pay_discounts,
        detect_auto_renewal_escalation,
        detect_fx_hedge_unapplied,
        detect_dormant_credit_balance,
    ]
    findings: list[Finding] = []
    for skill in skills:
        findings.extend(skill(bundle))
    findings.sort(key=lambda f: (f.recoverable_sar, f.leakage_sar), reverse=True)
    for i, finding in enumerate(findings, start=1):
        finding.finding_id = f"F-{i:03d}"
    return findings


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
                "02_ERP_Extracts/AP_Invoices_H1_2026.xlsx",
                int(idx),
                f"{invoice_id} paid {row.Amount_SAR:,.2f} on {row.Payment_Date.date() if pd.notna(row.Payment_Date) else 'n/a'}",
            )
            for idx, row in rows.iterrows()
        ]
        pdf = rel_invoice_pdf(str(invoice_id).replace("INV-", "").replace("2026-", ""), bundle)
        if pdf:
            citations.append(bundle.evidence.citation(pdf, "PDF invoice", bundle.evidence.pdf_excerpt(pdf, [str(invoice_id)])))
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
            citations = [
                excel_citation(
                    bundle,
                    "03_Master_Data/Vendor_Master.xlsx",
                    int(idx),
                    f"{row.Vendor_ID} {row.Vendor_Name}; {field}={key}; contract={row.Contract_Reference}",
                )
                for idx, row in group.iterrows()
            ]
            for idx, row in paid.head(3).iterrows():
                citations.append(
                    excel_citation(
                        bundle,
                        "02_ERP_Extracts/AP_Invoices_H1_2026.xlsx",
                        int(idx),
                        f"{row.Invoice_ID} {row.Vendor_ID} {row.Amount_SAR:,.2f}",
                    )
                )
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
                    calculation={"identity_field": field, "identity_value": str(key), "paid_exposure_sar": exposure},
                )
            )
    unique: dict[str, Finding] = {}
    for finding in candidates:
        unique.setdefault(finding.vendor_id, finding)
    return list(unique.values())


def detect_off_contract_single_approver(bundle: DataBundle) -> list[Finding]:
    vm = bundle.vendors[["Vendor_ID", "Contract_Reference"]]
    ap = bundle.ap.merge(vm, on="Vendor_ID", how="left")
    no_contract = ap[ap["Contract_Reference"].isna() & ap["PO_Reference"].isna() & ap["Status"].eq("Paid")]
    findings: list[Finding] = []
    for vendor_id, rows in no_contract.groupby("Vendor_ID"):
        if len(rows) < 5:
            continue
        top_approver = rows["Approver_Email"].mode().iloc[0]
        approver_rows = rows[rows["Approver_Email"].eq(top_approver)]
        if len(approver_rows) / len(rows) < 0.8:
            continue
        exposure = float(rows["Amount_SAR"].sum())
        vendor_name = str(rows.iloc[0]["Vendor_Name"])
        citations = []
        vm_rows = bundle.vendors[bundle.vendors["Vendor_ID"].astype(str).eq(str(vendor_id))]
        for idx, row in vm_rows.iterrows():
            citations.append(excel_citation(bundle, "03_Master_Data/Vendor_Master.xlsx", int(idx), f"{row.Vendor_ID} has no contract reference."))
        for idx, row in rows.head(3).iterrows():
            citations.append(excel_citation(bundle, "02_ERP_Extracts/AP_Invoices_H1_2026.xlsx", int(idx), f"{row.Invoice_ID}; no PO; approver {row.Approver_Email}; SAR {row.Amount_SAR:,.2f}"))
        for rel in bundle.evidence.manifest:
            if rel.startswith("06_Email_Correspondence/"):
                text = (bundle.dataset_root / rel).read_text(encoding="utf-8", errors="ignore")
                if vendor_name.split()[0].lower() in text.lower() or str(top_approver).split("@")[0].lower() in text.lower():
                    citations.append(bundle.evidence.citation(rel, "text file", " ".join(text.split())[:400]))
                    break
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
        if excess < 10000:
            continue
        citations = [
            excel_citation(bundle, "05_Purchase_Orders/PO_Log_H1_2026.csv", int(idx), f"{row.PO_ID}; {sku}; {row.Quantity} units @ SAR {row.Unit_Price:,.2f}")
            for idx, row in rows.iterrows()
        ]
        contract = rel_contract_pdf(vendor_name.split()[0], bundle)
        if contract:
            citations.append(bundle.evidence.citation(contract, "PDF contract", bundle.evidence.pdf_excerpt(contract, [str(sku)])))
        for po_id in rows["PO_ID"].astype(str):
            inv = bundle.ap[bundle.ap["PO_Reference"].astype(str).eq(po_id)]
            for idx, row in inv.head(1).iterrows():
                citations.append(excel_citation(bundle, "02_ERP_Extracts/AP_Invoices_H1_2026.xlsx", int(idx), f"{row.Invoice_ID}; {row.Memo}; SAR {row.Amount_SAR:,.2f}"))
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


def detect_missed_early_pay_discounts(bundle: DataBundle) -> list[Finding]:
    discount_vendors = []
    for rel, pages in bundle.evidence.pdf_text.items():
        if not rel.startswith("04_Contracts/"):
            continue
        text = " ".join(pages)
        if re.search(r"2\s*/\s*10\s+net\s+30", text, re.I):
            match = re.search(r"Vendor ID .*?:\s*(V-\d+)", text, re.I)
            if match:
                discount_vendors.append((match.group(1), rel))
    findings: list[Finding] = []
    for vendor_id, contract in discount_vendors:
        rows = bundle.ap[
            bundle.ap["Vendor_ID"].astype(str).eq(vendor_id)
            & bundle.ap["Status"].eq("Paid")
            & bundle.ap["Payment_Date"].notna()
        ].copy()
        rows["days_to_pay"] = (rows["Payment_Date"] - rows["Invoice_Date"]).dt.days
        missed = rows[(rows["days_to_pay"] > 10) & (rows["Memo"].astype(str).str.contains("2/10", na=False))]
        if missed.empty:
            continue
        recoverable = float((missed["Amount_SAR"] * 0.02).sum())
        vendor_name = str(missed.iloc[0]["Vendor_Name"])
        citations = [
            bundle.evidence.citation(contract, "PDF contract payment terms", bundle.evidence.pdf_excerpt(contract, ["2/10", "net 30"]))
        ]
        for idx, row in missed.head(5).iterrows():
            citations.append(excel_citation(bundle, "02_ERP_Extracts/AP_Invoices_H1_2026.xlsx", int(idx), f"{row.Invoice_ID}; paid in {int(row.days_to_pay)} days; SAR {row.Amount_SAR:,.2f}; 2%={row.Amount_SAR*0.02:,.2f}"))
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
                calculation={"discount_rate": 0.02, "invoice_count": len(missed), "recoverable_sar": recoverable},
            )
        )
    return findings


def detect_auto_renewal_escalation(bundle: DataBundle) -> list[Finding]:
    findings: list[Finding] = []
    for rel, pages in bundle.evidence.pdf_text.items():
        if not rel.startswith("04_Contracts/"):
            continue
        text = " ".join(pages)
        if "Automatic Renewal" not in text or "CPI" not in text:
            continue
        vendor_match = re.search(r"Vendor ID .*?:\s*(V-\d+)", text)
        base_match = re.search(r"Base monthly service fee SAR\s*([\d,]+)", text)
        if not vendor_match or not base_match:
            continue
        vendor_id = vendor_match.group(1)
        base_fee = float(base_match.group(1).replace(",", ""))
        rows = bundle.ap[bundle.ap["Vendor_ID"].astype(str).eq(vendor_id) & bundle.ap["Status"].eq("Paid")]
        if rows.empty:
            continue
        monthly_fee = float(rows["Amount_SAR"].median())
        excess = float(((rows["Amount_SAR"] - base_fee).clip(lower=0)).sum())
        if excess <= 0:
            continue
        vendor_name = str(rows.iloc[0]["Vendor_Name"])
        citations = [bundle.evidence.citation(rel, "PDF contract renewal/escalation", bundle.evidence.pdf_excerpt(rel, ["Automatic Renewal", "CPI"]))]
        invoice_pdf = rel_invoice_pdf("GulfLogistics", bundle)
        if invoice_pdf:
            citations.append(bundle.evidence.citation(invoice_pdf, "PDF invoice rate basis", bundle.evidence.pdf_excerpt(invoice_pdf, ["base monthly fee", "2026 escalation"])))
        for idx, row in rows.head(3).iterrows():
            citations.append(excel_citation(bundle, "02_ERP_Extracts/AP_Invoices_H1_2026.xlsx", int(idx), f"{row.Invoice_ID}; SAR {row.Amount_SAR:,.2f}; base SAR {base_fee:,.2f}"))
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


def detect_fx_hedge_unapplied(bundle: DataBundle) -> list[Finding]:
    findings: list[Finding] = []
    hedges = bundle.cash_forecast.get("Hedges")
    if hedges is None:
        return findings
    hedge_text = " ".join(str(x) for x in hedges.fillna("").to_numpy().ravel())
    rate_values = [float(x) for x in re.findall(r"\b3\.\d{2,4}\b", hedge_text)]
    hedge_rate = min(rate_values) if rate_values else 3.73
    rows = bundle.ap[
        bundle.ap["Currency"].astype(str).str.upper().eq("EUR")
        & bundle.ap["Vendor_Name"].astype(str).str.contains("Bordeaux Wines", case=False, na=False)
        & bundle.ap["Status"].eq("Paid")
    ].copy()
    if rows.empty:
        return findings
    # Pick the invoice whose SAR/EUR rate diverges most from hedge rate.
    rows["applied_rate"] = rows["Amount_SAR"] / rows["Amount_Original_Currency"]
    rows["rate_delta"] = rows["applied_rate"] - hedge_rate
    target = rows.sort_values("rate_delta", ascending=False).iloc[0]
    exposure = float((target["applied_rate"] - hedge_rate) * float(target["Amount_Original_Currency"]))
    if exposure <= 0:
        return findings
    citations = [
        excel_citation(bundle, "02_ERP_Extracts/AP_Invoices_H1_2026.xlsx", int(target.name), f"{target.Invoice_ID}; EUR {target.Amount_Original_Currency:,.2f}; SAR {target.Amount_SAR:,.2f}; applied rate {target.applied_rate:.4f}"),
        bundle.evidence.citation("07_Cash_Forecast/CFO_Cash_Forecast_June_2026.xlsx", "Hedges sheet", hedge_text[:400]),
    ]
    invoice_pdf = rel_invoice_pdf("BordeauxWines", bundle)
    if invoice_pdf:
        citations.append(bundle.evidence.citation(invoice_pdf, "PDF EUR invoice", bundle.evidence.pdf_excerpt(invoice_pdf, [str(target.Invoice_ID)])))
    email_rel = "06_Email_Correspondence/Email_2_BordeauxWines_Payment_May_2026.txt"
    if email_rel in bundle.evidence.manifest:
        text = (bundle.dataset_root / email_rel).read_text(encoding="utf-8", errors="ignore")
        citations.append(bundle.evidence.citation(email_rel, "text file", " ".join(text.split())[:400]))
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
            confidence="HIGH" if len(citations) >= 3 else "MEDIUM",
            classification="CASH (recoverable going-forward)",
            rationale="EUR invoice was settled at a rate above an available hedge rate in the treasury forecast.",
            remediation="Treasury and AP should enforce hedge application checks before EUR vendor settlement and include hedge IDs in payment approval.",
            citations=citations,
            calculation={"applied_rate": float(target.applied_rate), "hedge_rate": hedge_rate, "eur_amount": float(target.Amount_Original_Currency), "exposure_sar": exposure},
        )
    )
    return findings


def detect_dormant_credit_balance(bundle: DataBundle) -> list[Finding]:
    gl = bundle.gl.copy()
    candidates = gl[
        gl["Reference"].astype(str).str.contains("CR-", na=False)
        & (gl["Credit"].fillna(0) > 0)
    ]
    findings: list[Finding] = []
    for _, credit in candidates.iterrows():
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
            bundle.evidence.citation("02_ERP_Extracts/GL_Extract_H1_2026.csv", "CSV row with credit reference", f"{reference}; credit SAR {amount:,.2f}")
        ]
        credit_pdf = rel_invoice_pdf(reference, bundle)
        if credit_pdf:
            citations.append(bundle.evidence.citation(credit_pdf, "PDF credit note", bundle.evidence.pdf_excerpt(credit_pdf, [reference])))
        for idx, row in ap_rows.head(3).iterrows():
            citations.append(excel_citation(bundle, "02_ERP_Extracts/AP_Invoices_H1_2026.xlsx", int(idx), f"{row.Invoice_ID}; paid SAR {row.Amount_SAR:,.2f}; memo references {reference}"))
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


def compute_working_capital_drifts(bundle: DataBundle) -> list[dict]:
    ar = bundle.ar[bundle.ar["Collection_Date"].notna()].copy()
    ar["days_to_collect"] = (ar["Collection_Date"] - ar["Invoice_Date"]).dt.days
    ap = bundle.ap[bundle.ap["Payment_Date"].notna()].copy()
    ap["days_to_pay"] = (ap["Payment_Date"] - ap["Invoice_Date"]).dt.days
    signals = []
    for label, df, metric, id_col in [
        ("DSO", ar, "days_to_collect", "Invoice_ID"),
        ("DPO", ap, "days_to_pay", "Invoice_ID"),
    ]:
        df["month"] = df["Invoice_Date"].dt.to_period("M").astype(str)
        monthly = df.groupby("month").agg(days=(metric, "mean"), amount=("Amount_SAR", "sum")).reset_index()
        if len(monthly) < 2:
            continue
        baseline = float(monthly.iloc[:3]["days"].mean())
        for _, row in monthly.iloc[3:].iterrows():
            drift = float(row["days"] - baseline)
            if abs(drift) >= 3:
                drivers = df[df["month"].eq(row["month"])].sort_values(metric, ascending=False).head(5)
                signals.append(
                    {
                        "metric": label,
                        "period": row["month"],
                        "baseline_days": round(baseline, 2),
                        "current_days": round(float(row["days"]), 2),
                        "drift_days": round(drift, 2),
                        "cash_impact_sar": round(float(row["amount"]) * drift / max(float(row["days"]), 1), 2),
                        "drivers": drivers[id_col].astype(str).tolist(),
                    }
                )
    return sorted(signals, key=lambda x: abs(x["drift_days"]), reverse=True)[:3]

