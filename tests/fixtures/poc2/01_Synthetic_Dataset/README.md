# Tamween Pharma Distribution — Synthetic H1 2026 Finance Dataset

**For human use during StrategyOS / Legion-Rights POC validation. NOT to be shown to the agents.**

This dataset simulates six months of finance data for **Tamween Pharma Distribution**, the wholesale pharmaceutical distribution arm of Mizan Group (Mizan's 8th BU since the January 2024 acquisition). It is the playground for testing whether the Legion-Rights orchestration harness, running a Finance Analyst agent and a Finance Auditor agent in ping-pong mode, can detect cash leakage and produce defensible, evidence-cited findings against a realistic pharma-distribution backdrop.

## The fictional company

**Tamween Pharma Distribution** — wholesale pharmaceutical distributor headquartered in Riyadh, KSA. Subsidiary of Mizan Group (the GCC pharma + health platform). ~SAR 2.54B annual revenue 2026F (~$680M USD). 720 employees. 12 regional warehouses (incl. 2 GDP-WHO compliant cold-chain). ~210 active suppliers (APIs, finished pharmaceuticals, cold-chain logistics, packaging). ~85 institutional customers (modern pharmacy chains, hospitals, NUPCO public-sector, HORECA-Rx). Reporting currency SAR. Significant EUR + CHF exposure on European specialty pharma imports.

Banks used:

- **Saudi National Bank (SNB)** — operating account, SAR
- **Riyad Bank** — FX trading account, USD
- **Arab National Bank (ANB)** — payroll account, SAR
- **Emirates NBD (UAE branch)** — EUR account for European supplier payments

H1 2026 is the period covered (Jan–Jun 2026).

For the parent Mizan Group strategy + market context, see `/StrategyOS/POC/04_Strategic_Context/`.

## File index

| Folder | File | Format | Purpose |
|---|---|---|---|
| 01_Bank_Statements | SNB_Operating_SAR_Jan-Mar_2026.pdf | PDF | Q1 SAR ops + Patterns 1, 2, 3 |
| 01_Bank_Statements | SNB_Operating_SAR_Apr-Jun_2026.pdf | PDF | Q2 SAR ops + Patterns 1, 4, 5, 6 |
| 01_Bank_Statements | RiyadBank_FX_USD_Jan-Jun_2026.pdf | PDF | USD FX trading account |
| 01_Bank_Statements | ANB_Payroll_SAR_Jan-Jun_2026.pdf | PDF | Payroll batches |
| 01_Bank_Statements | EmiratesNBD_EUR_Jan-Jun_2026.pdf | PDF (scanned first 2 pages — OCR required) | EUR account + Pattern 7 |
| 02_ERP_Extracts | AP_Invoices_H1_2026.xlsx | Excel | 1,397 AP invoices; all 8 patterns visible |
| 02_ERP_Extracts | AR_Invoices_H1_2026.xlsx | Excel | 800 AR invoices; pharma customer names |
| 02_ERP_Extracts | GL_Extract_H1_2026.csv | CSV | ~8,500 GL lines; CR-2024-091 dormant credit (Pattern 8) |
| 02_ERP_Extracts | Trial_Balance_June_2026.xlsx | Excel | End-of-June TB |
| 03_Master_Data | Vendor_Master.xlsx | Excel | 210 pharma suppliers (Patterns 2, 3, 8 visible at master-data level) |
| 03_Master_Data | Customer_Master.xlsx | Excel | 85 pharma customers (pharmacy chains, hospitals, gov commissary) |
| 03_Master_Data | Chart_of_Accounts.xlsx | Excel | 180 accounts |
| 04_Contracts | Premier_Pharma_Packaging_Master_Agreement_2024.pdf | PDF | Pattern 1 source — clean supply terms |
| 04_Contracts | Saudi_Pharma_Suppliers_Distribution_Agreement_2025.pdf | PDF | Pattern 5 — 2/10 net 30 explicit |
| 04_Contracts | Gulf_ColdChain_Logistics_Services_Agreement_2023.pdf | PDF | Pattern 6 — CPI+3% no-cap auto-renewal |
| 04_Contracts | Al_Rashid_Pharma_Supply_Agreement_2024.pdf | PDF | Pattern 2 — V-1142 contract (V-1187 has none) |
| 04_Contracts | Gulf_BioPharma_Master_Agreement_2024.pdf | PDF | Pattern 4 — fixed Schedule A pricing for FG-2241 |
| 04_Contracts | Servier_Pharmaceuticals_Import_Agreement_2025.pdf | PDF | Pattern 7 — EUR supplier with hedge cooperation clause |
| 05_Purchase_Orders | PO_Log_H1_2026.csv | CSV | 600 POs; PO-2026-0218 and PO-2026-0247 carry Pattern 4 |
| 06_Email_Correspondence | Email_1_QuickPrint_Approval_Feb_2026.txt | TXT | Pattern 3 — Omar Faridi off-contract approval |
| 06_Email_Correspondence | Email_2_BordeauxWines_Payment_May_2026.txt | TXT | Pattern 7 — spot-rate confirmation, no hedge mentioned |
| 06_Email_Correspondence | Email_3_Vendor_Dispute_Mar_2026.txt | TXT | Noise — routine vendor dispute (Najd Pharma) |
| 07_Cash_Forecast | CFO_Cash_Forecast_June_2026.xlsx | Excel | Hedges sheet (HD-2026-019); deliberate cell errors |
| 08_Invoices | Invoice_PremierPharma_INV-2026-0341.pdf | PDF | Pattern 1 — the duplicate-paid invoice |
| 08_Invoices | Invoice_AlRashidPharma_V1142_INV-2026-1401.pdf | PDF | Pattern 2 — V-1142 API supplier (clean PDF) |
| 08_Invoices | Invoice_AlRashidPharmaCo_V1187_INV-2026-1404.pdf | PDF (scanned, OCR required) | Pattern 2 — V-1187, same products |
| 08_Invoices | Invoice_QuickPrint_INV-2026-1408.pdf | PDF | Pattern 3 — off-contract, Omar Faridi approval cited |
| 08_Invoices | Invoice_QuickPrint_INV-2026-1413.pdf | PDF | Pattern 3 — second Quick Print invoice |
| 08_Invoices | Invoice_GulfBioPharma_INV-2026-1424_PO-0218.pdf | PDF | Pattern 4 — ibuprofen FG-2241 @ SAR 32 (contract price) |
| 08_Invoices | Invoice_GulfBioPharma_INV-2026-1425_PO-0247.pdf | PDF | Pattern 4 — ibuprofen FG-2241 @ SAR 41 (inflated "emergency") |
| 08_Invoices | Invoice_SaudiPharma_INV-2026-0488.pdf | PDF | Pattern 5 — 2/10 net 30 in payment block |
| 08_Invoices | Invoice_SaudiPharma_INV-2026-0631.pdf | PDF | Pattern 5 — second Saudi Pharma invoice |
| 08_Invoices | Invoice_GulfColdChain_INV-2026-1421.pdf | PDF | Pattern 6 — cold-chain monthly with CPI+3% rate-basis note |
| 08_Invoices | Invoice_Servier_INV-2026-0577.pdf | PDF (FR/EN, EUR) | Pattern 7 — Servier specialty pharma EUR invoice |
| 08_Invoices | Invoice_MediterraneanPharma_INV-2026-1426.pdf | PDF | Pattern 8 — references open credit CR-2024-091 in footer |
| 08_Invoices | CreditNote_MediterraneanPharma_CR-2024-091.pdf | PDF | Pattern 8 — the SAR 128,000 dormant credit |
| 08_Invoices | Invoice_NajdPharma_*.pdf, FalconVitamins_*.pdf, OasisMedDevices_*.pdf, ArabianDiagnostics_*.pdf, HijazPharmaPkg_*.pdf | PDFs | Noise — unrelated pharma suppliers |

---

## VAT and currency convention

All SAR `Amount_SAR` figures in AP/AR are VAT-inclusive (gross payable). Invoice PDFs quote each line VAT-inclusive with a back-out disclosure of embedded 15% VAT. Bank-statement debits match gross figures. EUR transactions (Servier Pharmaceuticals) use export-zero-rated TVA (French export practice).

---

## VALIDATION ANSWER KEY — DO NOT SHARE WITH AGENTS

Eight cash leakage patterns are deliberately planted. Total planted leakage **~SAR 1,211,000 (~$323,000 USD)**. Realistically recoverable subset **~SAR 825,000 (~$220,000 USD)**.

### Pattern 1 — Exact duplicate payment

- **Vendor:** Premier Pharma Packaging LLC (V-1872)
- **Invoice:** INV-2026-0341 (SAR 177,188 gross)
- **Source:** `08_Invoices/Invoice_PremierPharma_INV-2026-0341.pdf` — single invoice, single PO reference PO-2026-0118
- **Leg 1:** Wire 12-Mar-2026 → SNB Jan-Mar statement
- **Leg 2:** Cheque 14-Mar-2026 → SNB Jan-Mar statement
- Both legs as separate AP rows referencing the same Invoice_ID
- **Recoverable: SAR 177,188 (~$47,250)**

### Pattern 2 — Entity-resolution duplicate vendor (API supplier)

- **Vendor:** Al-Rashid Pharma Trading Co LLC (V-1142) and Al Rashid Pharma Trading Company (V-1187)
- **Shared identity:** Tax ID 300187452100003, bank account SA0380000000608010167519, address P.O. Box 23145 Riyadh — visible in Vendor_Master
- V-1142 has contract CT-2024-031; V-1187 does not
- Both supply paracetamol + ibuprofen API. V-1187 invoice is a **scanned PDF with zero extractable text — OCR required**
- **Combined H1 payments: ~SAR 104,750**
- **Recoverable: SAR ~105,000 (~$28,000)** — primarily a controls finding

### Pattern 3 — Off-contract spend, single-approver

- **Vendor:** Quick Print Services (V-2091) — Contract_Reference blank in Vendor_Master
- 11 H1 payments totalling SAR 420,200
- All approved by omar.faridi@tamween-pharma.sa (Marketing Manager — pharmacy POS material)
- Invoice PDFs cite "Approved per email from Omar Faridi (Marketing)"; `Email_1_QuickPrint_Approval_Feb_2026.txt` is the smoking gun
- **Recoverable: 0 cash (controls finding); ~$112,000 of off-contract spend exposed to fraud / overpay risk**

### Pattern 4 — Price variance (same SKU, same vendor, same month)

- **Vendor:** Gulf BioPharma Co (V-1456)
- **SKU:** FG-2241 (ibuprofen 400mg, 30-tab blister pack)
- **Contract:** `Gulf_BioPharma_Master_Agreement_2024.pdf` Schedule A → SAR 32.00/unit fixed
- PO-2026-0218 dated 8-Apr — 4,200 units @ SAR 32 = SAR 134,400 (correct)
- PO-2026-0247 dated 23-Apr — 3,400 units @ SAR 41 = SAR 139,400 (overpriced; "emergency restock")
- Invoices: contract-priced one cites Schedule A explicitly; inflated one describes itself as "emergency restock — spot pricing"
- **Excess: (41-32) × 3,400 = SAR 30,600 (~$8,200)**

### Pattern 5 — Missed 2/10 net 30 early-pay discounts

- **Vendor:** Saudi Pharma Suppliers Co (V-1003)
- **Contract:** CT-2025-018 §3 — 2/10 net 30 with worked example
- 5 H1 invoices paid on day 24-29 instead of day 10 (totalling SAR 2.83M)
- Invoice PDFs print "2/10 net 30" in the payment block
- **Recoverable: SAR ~56,500 (~$15,100)** — fully recoverable going forward via process fix

### Pattern 6 — Auto-renew CPI+3% no-cap (pharma cold-chain logistics)

- **Vendor:** Gulf Cold-Chain Logistics Co (V-1199)
- **Contract:** CT-2023-014 §3.2 + §3.3 — auto-renew + CPI+3% no cap (the dangerous clause is in the contract PDF)
- 2025 baseline SAR 188,000/month; H1 2026 rate SAR 229,736/month (+22.2%)
- The invoice PDF rate-basis note literally prints **"2025 base SAR 188,000; 2026 +22.20%; effective SAR 229,736"** citing §3.3 — the smoking gun in print
- **Recoverable: SAR ~250,000 (~$67,000)** going forward via renegotiation

### Pattern 7 — FX hedge not applied (EUR specialty pharma)

- **Vendor:** Servier Pharmaceuticals SAS (V-2310)
- **Invoice:** INV-2026-0577 — EUR 89,400 paid 6-May-2026 from Emirates NBD at spot 4.21
- **Hedge HD-2026-019** was open — 60% May EUR coverage at locked 3.73 — visible in CFO_Cash_Forecast Hedges sheet (highlighted exception row)
- Email_2 confirms spot rate applied; no hedge mention
- **Counterfactual leakage: (4.21-3.73) × 89,400 = SAR 42,912 (~$11,500)**

### Pattern 8 — Dormant credit balance never offset

- **Vendor:** Mediterranean Pharma Trading LLC (V-1078)
- **Credit Note:** CR-2024-091 — SAR 128,000 issued November 2024 (expired-stock return + cold-chain breach)
- The Credit Note PDF body text literally states: *"This credit balance is available for offset against any future Tamween Pharma Distribution payable to Mediterranean Pharma Trading LLC. Credit balance does NOT expire."*
- The H1 invoice PDF footer **explicitly flags** the open credit balance — supplier raised it, TDC paid in full anyway
- 5 H1 invoices totalling SAR 396,900 paid in full despite the credit
- **Recoverable: SAR 128,000 (~$34,000)** via offset

### Summary

| Pattern | Vendor | Recoverable SAR | USD |
|---|---|---|---|
| 1 — Duplicate payment | Premier Pharma Packaging | 177,188 | 47,250 |
| 2 — Vendor duplicate | Al-Rashid Pharma (V-1142/V-1187) | ~105,000 | 28,000 |
| 3 — Off-contract | Quick Print Services | 0 (controls) | 0 |
| 4 — Price variance | Gulf BioPharma (FG-2241 ibuprofen) | 30,600 | 8,200 |
| 5 — Missed early-pay | Saudi Pharma Suppliers | ~56,500 | 15,100 |
| 6 — Auto-renew | Gulf Cold-Chain Logistics | ~250,000 | 67,000 |
| 7 — FX hedge unapplied | Servier Pharmaceuticals | ~43,000 | 11,500 |
| 8 — Dormant credit | Mediterranean Pharma | 128,000 | 34,000 |
| **TOTAL** |  | **~790,288** | **~211,050** |

Counting Pattern 3 as controls-only: ~SAR 790K (~$211K) cash. Including a fraction of Pattern 3 as going-forward renegotiation savings: ~SAR 825K (~$220K) total.

---

## Why pharma is a richer playground for the same 8 patterns

Each pattern's relevance to a real pharma distribution business:

- **Pattern 1 (duplicate payment)** — common in pharma where the same emergency-stock invoice gets approved by both the manual hospital-tender desk and the standing PO system
- **Pattern 2 (entity-resolution)** — API suppliers frequently operate via multiple trading entities for Saudi import licensing; entity-resolution is the structural risk
- **Pattern 3 (off-contract)** — emergency stock-out procurement is endemic in pharma; off-contract spend is a real fraud + overpay vector
- **Pattern 4 (price variance)** — "emergency restock" pricing 25-35% above contract is observed across the Saudi pharma distribution industry
- **Pattern 5 (missed discount)** — 2/10 net 30 is the standard generic pharma supplier term
- **Pattern 6 (auto-renew + CPI escalation)** — cold-chain logistics contracts often carry CPI+ escalation clauses, no cap, that compound silently
- **Pattern 7 (FX hedge unapplied)** — European specialty pharma (Servier, Roche, Sanofi, Novartis) is EUR/CHF-denominated; hedge discipline is the operating challenge
- **Pattern 8 (dormant credit)** — expired-stock and cold-chain-breach credit notes are routine in pharma; offsetting is where controls break

The cash-leakage POC is therefore a more natural fit for pharma distribution than for the original FMCG framing.

---

# HISTORIC EXTENSION — FY2023-FY2025 (added July 2026)

Three full years of history preceding the H1 2026 dataset, plus a strategic analytics layer, generated to let StrategyOS answer multi-year questions ("what contributed to revenue over 3 years", "where can we improve costs") with transaction-level evidence.

## Scope framing — IMPORTANT

All ERP extracts, bank statements, invoices and POs in this dataset (both H1 2026 and the historic files) cover **Tamween's Central Region (Riyadh) division only** — 4 of the BU's 12 warehouses, ~30% of BU revenue. BU-level figures (SAR 1,940M 2023 → 2,120M 2024 → 2,340M 2025 → 2,540M 2026F) live in the Strategic Context layer (`/StrategyOS/POC/04_Strategic_Context/`) and `12_Group_Financials/`. The bridge is `11_Strategic_Analytics/Division_to_Group_Reconciliation.xlsx`. This resolves the apparent 3.3x gap between GL revenue (~SAR 770M/yr annualised) and the strategy PDFs.

## New folders

| Folder | Contents |
|---|---|
| 09_Historic_ERP | AP_Invoices_FY2023/24/25.xlsx, AR_Invoices_FY2023/24/25.xlsx, GL_Extract_FY2023/24/25.csv, Trial_Balance_Dec_2023/24/25.xlsx |
| 10_Historic_POs | PO_Log_H2_2024.csv (PO system live Jul-2024), PO_Log_FY2025.csv |
| 11_Strategic_Analytics | Revenue_Analytics, Supplier_Spend, SKU_Price_History, Headcount_Payroll, Division_to_Group_Reconciliation, Data_Dictionary |
| 12_Group_Financials | Mizan_Group_BU_PnL_2023-2026.xlsx (8 BUs, consistent with Group Strategy §02/§04) |
| 13_Historic_Correspondence | 9 emails/memos + 2 board-pack excerpts (FY2024, FY2025) |

Also added: 3 invoice PDFs in 08_Invoices (Premier INV-2025-2841; Bahr Freight INV-BF-2024-0311 + INV-BF-2024-0347); vendors V-2415/V-3001/V-3002, accounts 2900/3900, and the churned-customer status flag in 03_Master_Data.

## Key consistency guarantees

- SNB cash chains exactly: FY2023 close 40.5M → FY2024 close 41.6M → FY2025 close 42.8M = OB-2026 in the existing H1 2026 GL.
- CR-2024-091 is issued in FY2024 GL (18-Nov-2024), brought forward in FY2025 and FY2026 GL.
- Gulf Cold-Chain invoiced 176K/mo (2024), 188K/mo (2025) — matching the "2025 base SAR 188,000" printed on the 2026 invoice.
- Gulf BioPharma FG-2241 at SAR 32.00 in every historic PO — making the Apr-2026 SAR 41 PO an isolated anomaly.
- V-1187 (Al-Rashid duplicate entity) first invoices Q4-2025; QuickPrint off-contract spend ramps 9K (2023) → 13K (2024) → 58K (2025) → 420K (H1 2026).
- Legacy account descriptions ("Revenue – Catering" etc.) are explained in Data_Dictionary.xlsx as retained FMCG-era ERP template names (Memo_1, Jan-2024).

## VALIDATION ANSWER KEY — HISTORIC PATTERNS (H1-H5) — DO NOT SHARE WITH AGENTS

| # | Pattern | Where | Value |
|---|---|---|---|
| H1 | Duplicate payment (precursor of Pattern 1) — Premier Pharma INV-2025-2841 paid by wire 18-Nov-2025 AND cheque #004417 21-Nov-2025; vendor statement query Dec-2025 unresolved | AP FY2025 (two rows, same Invoice_ID), GL FY2025, invoice PDF, Email_10 | SAR 96,600 recoverable; recurrence proof for controls finding |
| H2 | Sole-source price creep — Hijaz Pharma Solutions (V-1153) PKG-1101: SAR 7.70 → 8.40 → 9.16 (+9%/yr vs CPI ~1.9%) | AP memos all 3 years, PO logs, SKU_Price_History, Supplier_Spend | ~SAR 502K cumulative excess vs CPI-indexed baseline (2024-25); ~SAR 340K/yr go-forward |
| H3 | Contribution-negative customer — KAUST Health Centre (C-2023): 12% retro rebate + ~50-day-late collections since 2024 renewal | GL 4110 rebate entries, AR collection dates, Customer_Profitability_FY2025 sheet, board packs | Rebates SAR 6.95M (2024) + 8.24M (2025); account is margin-negative — renegotiation opportunity |
| H4 | 3PL double-billing — Bahr Freight (V-2415), Mar/Apr/May 2024 billed twice per service month; clerk query overruled (Email_4) | AP FY2024 (3 pairs), 2 invoice PDFs, board pack FY2024 | SAR 198,063 never credited |
| H5 | Unrecharged co-location — Qassim WH utilities +35% since Feb-2024 (Mizan Pharmacy Retail occupies 35% of floor; recharge never set up per Memo_2) | GL/AP utilities memos "(incl. co-located retail unit)", Memo_2 | ~SAR 4.43M cumulative (2024-25) recoverable via intercompany recharge |

Seeds of the existing 8 patterns are planted in history: Saudi Pharma 2% discounts captured Feb-Aug 2025 (SAR ~68K) then lost after the AP clerk departure (Email_8); the Gulf Cold-Chain auto-renewal notice arrived 1-Oct-2025 and was never actioned (Email_9); Servier paid at unhedged spot through 2025.

Grand total across H1-H5: ~SAR 5.2M identifiable (dominated by H5 structural recharge + H3 strategic repricing), vs ~SAR 1.2M in the 2026 transactional patterns.

## 14_CEO_Office (added July 2026)

`CEO_Calendar_Mizan_Apr-Jul_2026.xlsx` — Khalid Al-Rashed's calendar, Apr-Jul 2026 ('today' = 1-Jun-2026). ~100 events mixing high-signal meetings (cash-leakage audit readouts, Gulf Cold-Chain renegotiation, KAUST repricing, NUPCO RFP war-rooms, Capital Committee) with deliberate noise (personal, ceremonial, admin). Designed to test whether an agent can rank meeting importance against the business context and connect calendar items to dataset evidence (e.g. the 3-Jun renegotiation meeting ↔ CT-2023-014 escalation; the 9-Jun recharge meeting ↔ Qassim utilities pattern H5).
