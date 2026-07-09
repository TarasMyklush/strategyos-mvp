# Tamween Distribution Co. — Synthetic H1 2026 Finance Dataset

**For human use during ExOS / Legion-Rights POC validation. NOT to be shown to the agents.**

This dataset simulates six months of finance data for a fictional GCC consumer-packaged-goods distributor. It is the playground for testing whether the Legion-Rights orchestration harness, running a Finance Analyst agent and a Finance Auditor agent in ping-pong mode, can detect cash leakage and produce defensible, evidence-cited findings.

## The fictional company

**Tamween Distribution Co. (TDC)** — Riyadh, KSA. Privately held. ~$250M USD annual revenue. ~600 employees. 12 regional warehouses across KSA. ~210 active vendors. ~85 institutional customers (modern trade chains, hospitality groups, government commissaries). Reporting currency SAR. Significant USD and EUR import exposure.

Banks used:

- **Saudi National Bank (SNB)** — operating account, SAR
- **Riyad Bank** — FX trading account, USD
- **Arab National Bank (ANB)** — payroll account, SAR
- **Emirates NBD (UAE branch)** — EUR account for European supplier payments

H1 2026 is the period covered (Jan–Jun 2026).

## File index

| Folder | File | Format | Purpose |
|---|---|---|---|
| 01_Bank_Statements | SNB_Operating_SAR_Jan-Mar_2026.pdf | PDF (SNB green) | Q1 SAR ops + Pattern 1 leg 1, Pattern 2, Pattern 3 |
| 01_Bank_Statements | SNB_Operating_SAR_Apr-Jun_2026.pdf | PDF (SNB green) | Q2 SAR ops + Pattern 1 leg 2, Pattern 4, Pattern 5, Pattern 6 |
| 01_Bank_Statements | RiyadBank_FX_USD_Jan-Jun_2026.pdf | PDF (blue, serif) | USD FX trading account, distinct layout |
| 01_Bank_Statements | ANB_Payroll_SAR_Jan-Jun_2026.pdf | PDF (minimal) | Payroll batches, monthly aggregates only |
| 01_Bank_Statements | EmiratesNBD_EUR_Jan-Jun_2026.pdf | PDF (scanned, image-only first 2 pages) | EUR account + Pattern 7; first 2 pages REQUIRE OCR |
| 02_ERP_Extracts | AP_Invoices_H1_2026.xlsx | Excel | 1,403 AP invoices; Patterns 1, 2, 3, 4, 5, 6, 7, 8 all visible |
| 02_ERP_Extracts | AR_Invoices_H1_2026.xlsx | Excel | 800 AR invoices; 25% have DSO drift (daily-life noise) |
| 02_ERP_Extracts | GL_Extract_H1_2026.csv | CSV | ~8,500 GL lines; contains CR-2024-091 dormant balance (Pattern 8) |
| 02_ERP_Extracts | Trial_Balance_June_2026.xlsx | Excel | 175 accounts at end-June, ties to GL |
| 03_Master_Data | Vendor_Master.xlsx | Excel | 210 vendors; Patterns 2, 3, 8 visible at master-data level |
| 03_Master_Data | Customer_Master.xlsx | Excel | 85 customers |
| 03_Master_Data | Chart_of_Accounts.xlsx | Excel | 180 accounts |
| 04_Contracts | Premier_Packaging_Master_Agreement_2024.pdf | PDF | Clean supply agreement |
| 04_Contracts | Saudi_Trading_Co_Distribution_Agreement_2025.pdf | PDF | 2/10 net 30 terms — Pattern 5 source of truth |
| 04_Contracts | Gulf_Logistics_Services_Agreement_2023.pdf | PDF | Auto-renew + CPI+3% no-cap clause — Pattern 6 source |
| 04_Contracts | Al_Rashid_Trading_Supply_Agreement_2024.pdf | PDF | V-1142 contract only (V-1187 has no contract — Pattern 2 hook) |
| 04_Contracts | Gulf_Cosmetics_Master_Agreement_2024.pdf | PDF | Fixed price schedule incl. FG-2241 @ SAR 32 — Pattern 4 source |
| 04_Contracts | Bordeaux_Wines_Spirits_Agreement_2025.pdf | PDF | EUR supplier context — Pattern 7 |
| 05_Purchase_Orders | PO_Log_H1_2026.csv | CSV | 602 POs; PO-2026-0218 and PO-2026-0247 carry Pattern 4 price variance |
| 06_Email_Correspondence | Email_1_QuickPrint_Approval_Feb_2026.txt | Plain text | Pattern 3 evidence — Omar Faridi off-contract approval |
| 06_Email_Correspondence | Email_2_BordeauxWines_Payment_May_2026.txt | Plain text | Pattern 7 supporting — confirms spot rate, no hedge mention |
| 06_Email_Correspondence | Email_3_Vendor_Dispute_Mar_2026.txt | Plain text | NOISE — routine Najd Foodstuff dispute, not a leakage |
| 07_Cash_Forecast | CFO_Cash_Forecast_June_2026.xlsx | Excel | Hedges sheet has HD-2026-019 (Pattern 7); 3 deliberate cell errors |
| 08_Invoices | Invoice_PremierPackaging_INV-2026-0341.pdf | PDF (Template A) | Pattern 1 — the duplicate-paid invoice document |
| 08_Invoices | Invoice_AlRashid_V1142_INV-2026-1401.pdf | PDF (Template E, AR/EN bilingual) | Pattern 2 — V-1142 variant under contract CT-2024-031 |
| 08_Invoices | Invoice_AlRashidCo_V1187_INV-2026-1404.pdf | PDF (Template E, SCANNED — OCR required) | Pattern 2 — V-1187 variant, no contract; same products as V-1142 |
| 08_Invoices | Invoice_QuickPrint_INV-2026-1408.pdf | PDF (Template B) | Pattern 3 — off-contract, Omar Faridi approval cited |
| 08_Invoices | Invoice_QuickPrint_INV-2026-1413.pdf | PDF (Template B) | Pattern 3 — second off-contract Quick Print invoice |
| 08_Invoices | Invoice_GulfCosmetics_INV-2026-1424_PO-0218.pdf | PDF (Template A) | Pattern 4 — contract-priced invoice (SAR 32.00/unit) |
| 08_Invoices | Invoice_GulfCosmetics_INV-2026-1425_PO-0247.pdf | PDF (Template A) | Pattern 4 — inflated-price invoice (SAR 41.00/unit, "emergency restock") |
| 08_Invoices | Invoice_SaudiTrading_INV-2026-0488.pdf | PDF (Template A) | Pattern 5 — 2/10 net 30 terms printed in payment block |
| 08_Invoices | Invoice_SaudiTrading_INV-2026-0631.pdf | PDF (Template A) | Pattern 5 — second Saudi Trading invoice with same terms |
| 08_Invoices | Invoice_GulfLogistics_INV-2026-1421.pdf | PDF (Template C, logistics) | Pattern 6 — monthly service invoice, CPI+3% escalation note visible |
| 08_Invoices | Invoice_BordeauxWines_INV-2026-0577.pdf | PDF (Template D, FR/EN, EUR) | Pattern 7 — EUR invoice, IBAN/SWIFT, hedge cooperation clause |
| 08_Invoices | Invoice_MediterraneanFoods_INV-2026-1426.pdf | PDF (Template B) | Pattern 8 — references open credit balance CR-2024-091 in footer |
| 08_Invoices | CreditNote_MediterraneanFoods_CR-2024-091.pdf | PDF (Template B, Credit Note) | Pattern 8 — the SAR 128,000 dormant credit document itself |
| 08_Invoices | Invoice_NajdFoodstuff_INV-NF-2026-0824.pdf | PDF (Template A) | Noise — unrelated supplier |
| 08_Invoices | Invoice_FalconBeverages_INV-FB-2026-0112.pdf | PDF (Template B) | Noise — unrelated supplier |
| 08_Invoices | Invoice_OasisHygiene_INV-OH-2026-0091.pdf | PDF (Template A) | Noise — unrelated supplier |
| 08_Invoices | Invoice_ArabianDairy_INV-AD-2026-0445.pdf | PDF (Template A) | Noise — unrelated supplier |
| 08_Invoices | Invoice_HijazPaper_INV-HP-2026-0234.pdf | PDF (Template B) | Noise — unrelated supplier |

---

## VAT and currency convention

All SAR `Amount_SAR` figures in `AP_Invoices_H1_2026.xlsx` and `AR_Invoices_H1_2026.xlsx` are recorded **VAT-inclusive (gross payable)**. The invoice PDFs in `08_Invoices/` quote each line VAT-inclusive too, with a back-out note disclosing the embedded 15% VAT amount. Bank-statement debits match the gross figures. The pattern leakage amounts below are stated in gross SAR — the recoverable amount equals what would actually return to the bank account.

EUR-denominated transactions (Bordeaux Wines) use export-zero-rated VAT (TVA 0%), per French export practice. SAR equivalents use the bank's applied spot rate on the value date.

## Visual / template variety in invoices

The 18 invoices in `08_Invoices/` use 5 visually distinct templates so an agent must reason across heterogeneous layouts (similar to the bank-statement layout variety):

- **Template A** — Saudi VAT-compliant corporate (dark blue + gold). Bilingual TAX INVOICE / فاتورة ضريبية badge. Used by Premier Packaging, Saudi Trading, Gulf Cosmetics, Najd, Oasis, Arabian Dairy.
- **Template B** — Spreadsheet-style bespoke (Courier-typeface, plain). Less polished. Used by Quick Print Services (off-contract feel), Mediterranean Foods, Falcon Beverages, Hijaz Paper.
- **Template C** — Logistics monthly service (industrial blue banner). Service breakdown with rate-basis note. Used by Gulf Logistics.
- **Template D** — European elegant FR/EN bilingual (burgundy + cream, Times serif). EUR-denominated, IBAN/SWIFT prominent. Used by Bordeaux Wines.
- **Template E** — Saudi bilingual AR/EN (green + gold). Cooking-oil bulk supplier feel, Arabic right-aligned headers. Used by both Al-Rashid variants. **The V-1187 variant is a scanned-style PDF — page 1 has zero extractable text, requires OCR** (mirrors the Emirates NBD EUR statement OCR test).

## VALIDATION ANSWER KEY — DO NOT SHARE WITH AGENTS

Eight cash leakage patterns are deliberately planted. Total planted leakage is **~SAR 1,211,000 (~$323,000 USD)**. Realistically recoverable subset is **~SAR 825,000 (~$220,000 USD)** — Patterns 5, 6, 7, and 8 plus parts of 1, 2, 4 are clearly clawback-able; Pattern 3 is a controls finding more than a clawback.

### Pattern 1 — Exact duplicate payment

- **Vendor:** Premier Packaging LLC (V-1872)
- **Invoice:** INV-2026-0341 (SAR 177,188 gross)
- **Source document:** `08_Invoices/Invoice_PremierPackaging_INV-2026-0341.pdf` — single invoice, single PO reference PO-2026-0118
- **Leg 1:** Wire payment 12-Mar-2026 → SNB Jan-Mar statement
- **Leg 2:** Cheque payment 14-Mar-2026 → SNB Jan-Mar statement
- **Both legs appear as separate rows in AP_Invoices_H1_2026.xlsx referencing the same Invoice_ID**
- **Recoverable: SAR 177,188 (~$47,250)**

### Pattern 2 — Entity-resolution duplicate vendor

- **Vendor:** Al-Rashid Trading Co LLC (V-1142) and Al Rashid Trading Company (V-1187)
- **Shared identity:** Tax ID 300187452100003, bank account SA0380000000608010167519, address P.O. Box 23145 Riyadh 11543 — all visible in Vendor_Master.xlsx
- **V-1142 has a contract on file (CT-2024-031); V-1187 does not**
- **Source invoices:**
  - `08_Invoices/Invoice_AlRashid_V1142_INV-2026-1401.pdf` — clean PDF, references contract CT-2024-031
  - `08_Invoices/Invoice_AlRashidCo_V1187_INV-2026-1404.pdf` — **scanned PDF (no text layer, OCR required)** with the same products and same products / same bank account on the supplier stamp
- Both invoices use Template E and look stylistically templated the same — the only difference is the trading name and the missing contract reference
- **Combined H1 payments to both: ~SAR 104,750**
- **Recoverable: SAR ~105,000 (~$28,000)** — primarily a controls finding (consolidate vendor records, recover any duplicate payments)

### Pattern 3 — Off-contract spend, single-approver

- **Vendor:** Quick Print Services (V-2091) — Contract_Reference field is blank in Vendor_Master
- **11 H1 payments totalling SAR 420,200**
- **Every payment approved by omar.faridi@tamween.sa (Marketing Manager) — visible in AP_Invoices Approver_Email column**
- **Source documents:**
  - `08_Invoices/Invoice_QuickPrint_INV-2026-1408.pdf` and `Invoice_QuickPrint_INV-2026-1413.pdf` — both invoices have NO PO reference and footer cites "Approved per email from Omar Faridi (Marketing)"
  - `06_Email_Correspondence/Email_1_QuickPrint_Approval_Feb_2026.txt` is the smoking-gun approval email
- **Recoverable: not recoverable as cash but a high-severity controls finding (~$112,000 of off-contract spend exposed to fraud / overpay risk)**

### Pattern 4 — Price variance same vendor, same SKU, same month

- **Vendor:** Gulf Cosmetics Co (V-1456)
- **SKU:** FG-2241 (premium shampoo 750 ml)
- **Contract price (Gulf_Cosmetics_Master_Agreement_2024.pdf, Schedule A): SAR 32.00/unit, fixed for term**
- **PO-2026-0218 dated 8-Apr — 4,200 units @ SAR 32.00 = SAR 134,400 (correct)**
- **PO-2026-0247 dated 23-Apr — 3,400 units @ SAR 41.00 = SAR 139,400 (overpriced)**
- **Source invoices:**
  - `08_Invoices/Invoice_GulfCosmetics_INV-2026-1424_PO-0218.pdf` — explicitly cites contract CT-2024-052, Schedule A pricing
  - `08_Invoices/Invoice_GulfCosmetics_INV-2026-1425_PO-0247.pdf` — describes itself as "emergency restock — spot pricing" with NO contract reference; unit price prints SAR 41.00
- **Excess at higher rate: (41-32) × 3,400 = SAR 30,600**
- **Both POs in PO_Log_H1_2026.csv; both invoices in AP_Invoices**
- **Recoverable: SAR 30,600 (~$8,200)** by claiming contract price

### Pattern 5 — Missed early-pay 2/10 net 30 discounts

- **Vendor:** Saudi Trading Co (V-1003)
- **Contract:** CT-2025-018, 2/10 net 30 terms (Saudi_Trading_Co_Distribution_Agreement_2025.pdf §3)
- **5 invoices in H1 paid on day 24–29 instead of day 10:**

| Invoice | Date | Amount (SAR) | Payment Date | Days Late vs. Discount Window | 2% Forgone |
|---|---|---|---|---|---|
| INV-2026-0488 | 28-Mar | 522,400 | 24-Apr | 17 | 10,448 |
| INV-2026-0512 | 05-Apr | 476,800 | 29-Apr | 14 | 9,536 |
| INV-2026-0560 | 18-Apr | 548,700 | 15-May | 17 | 10,974 |
| INV-2026-0631 | 09-May | 691,300 | 07-Jun | 19 | 13,826 |
| INV-2026-0688 | 28-May | 594,100 | 24-Jun | 17 | 11,882 |
| **Total** |  | **2,833,300** |  |  | **56,666** |

- **Recoverable: SAR ~56,500 (~$15,100) — partially recoverable retroactively if vendor agrees; fully recoverable going forward via process fix**
- **Source invoices:** `08_Invoices/Invoice_SaudiTrading_INV-2026-0488.pdf` and `Invoice_SaudiTrading_INV-2026-0631.pdf` — both invoices print the 2/10 net 30 terms in the payment block with a worked example. The matching contract clause is in `04_Contracts/Saudi_Trading_Co_Distribution_Agreement_2025.pdf` §3.

### Pattern 6 — Expired-but-auto-renewing logistics contract with index escalation

- **Vendor:** Gulf Logistics Services Co (V-1199)
- **Contract:** CT-2023-014, expired 31-Dec-2024 nominal initial term
- **Dangerous clause: §3.2 + §3.3 — auto-renews annually with CPI+3% no cap (Gulf_Logistics_Services_Agreement_2023.pdf)**
- **2025 base rate ~SAR 188,000/month; H1 2026 rate SAR 229,736/month (22.2% higher)**
- **6 H1 invoices at inflated rate paid in full**
- **Excess vs. counterfactual renegotiated rate: (229,736 − 188,000) × 6 = SAR 250,416**
- **Recoverable: SAR ~250,000 (~$67,000)** going forward by renegotiating; clawback unlikely but going-forward saving is solid
- **Source invoice:** `08_Invoices/Invoice_GulfLogistics_INV-2026-1421.pdf` — Template C monthly service invoice. The rate-basis note in the body **explicitly states**: "2025 base monthly fee was SAR 188,000; 2026 escalation applied = +22.20%; effective 2026 monthly fee = SAR 229,736.00", citing Contract CT-2023-014 §3.3. This is the smoking gun the agent should cite verbatim.

### Pattern 7 — FX hedge not applied

- **Vendor:** Bordeaux Wines & Spirits SARL (V-2310)
- **Invoice:** INV-2026-0577 — EUR 89,400 paid 6-May-2026 from Emirates NBD
- **Applied rate at settlement: 4.2100 SAR/EUR (spot)**
- **Hedge HD-2026-019 was open at trade date — 60% coverage of May EUR exposure at locked 3.7300 SAR/EUR (see Hedges sheet in CFO_Cash_Forecast_June_2026.xlsx, highlighted row)**
- **Email_2_BordeauxWines_Payment_May_2026.txt confirms spot was applied and does NOT reference the hedge**
- **Counterfactual leakage if hedge applied: (4.21 − 3.73) × 89,400 = SAR 42,912**
- **Recoverable: SAR ~43,000 (~$11,500)** going forward via Treasury-AP process discipline
- **Source invoice:** `08_Invoices/Invoice_BordeauxWines_INV-2026-0577.pdf` — Template D French/English bilingual EUR invoice. Footer §4 ("FX Hedging Cooperation" in `04_Contracts/Bordeaux_Wines_Spirits_Agreement_2025.pdf`) gave Treasury the right to apply hedges to settlements under this agreement.

### Pattern 8 — Dormant credit balance never offset

- **Vendor:** Mediterranean Foods Trading LLC (V-1078)
- **Credit Note:** CR-2024-091 — SAR 128,000 issued November 2024 for returned shipment
- **Appears in GL_Extract as opening 2700 "Credit Notes Outstanding" credit balance dated 2026-01-01 with Reference = CR-2024-091**
- **5 H1 2026 invoices from Mediterranean Foods totalling SAR 396,900 were paid in full despite the open credit — visible in AP_Invoices_H1_2026.xlsx**
- **Recoverable: SAR 128,000 (~$34,000)** by offsetting the credit against future invoices (or claiming a refund)
- **Source documents:**
  - `08_Invoices/CreditNote_MediterraneanFoods_CR-2024-091.pdf` — the actual credit note PDF dated 18 November 2024 for SAR 128,000 (320 cases olive oil + 180 cases canned tomatoes returned). Explicit body text: *"This credit balance is available for offset against any future Tamween Distribution Co. payable to Mediterranean Foods Trading LLC. Credit balance does NOT expire."*
  - `08_Invoices/Invoice_MediterraneanFoods_INV-2026-1426.pdf` — H1 2026 invoice paid in full, with a footer note **"a customer credit balance of SAR 128,000 (Credit Note CR-2024-091, issued November 2024) is currently open on the TDC account with this supplier. Please coordinate offset before next payment."** — the supplier flagged it; TDC paid anyway.

### Summary

| Pattern | Vendor | Planted SAR | Recoverable SAR | Recoverable USD |
|---|---|---|---|---|
| 1 — Duplicate payment | Premier Packaging | 177,188 | 177,188 | 47,250 |
| 2 — Vendor duplicate | Al-Rashid (V-1142/V-1187) | 104,750 | ~105,000 | 28,000 |
| 3 — Off-contract spend | Quick Print Services | 420,200 | 0 (controls) | 0 |
| 4 — Price variance | Gulf Cosmetics | 30,600 | 30,600 | 8,200 |
| 5 — Missed early-pay | Saudi Trading Co | 56,666 | ~56,500 | 15,100 |
| 6 — Auto-renew escalation | Gulf Logistics | 250,416 | ~250,000 | 67,000 |
| 7 — FX hedge unapplied | Bordeaux Wines | 42,912 | ~43,000 | 11,500 |
| 8 — Dormant credit | Mediterranean Foods | 128,000 | 128,000 | 34,000 |
| **TOTAL** |  | **1,210,732** | **~790,288** | **~211,050** |

Counting Pattern 3 as "controls only" (no cash clawback), realistic recoverable cash is ~SAR 790K (~$211K). If a fraction of Pattern 3 is treated as a contract-renegotiation savings going forward, recoverable rises to ~SAR 825K (~$220K).

### Daily-life noise

- ~25% of AR invoices have Collection_Date > Due_Date + 30 days. This creates a DSO drift signal that supports Task 2 of the POC Brief but is NOT a planted leakage.
- 3 deliberate cell errors in CFO_Cash_Forecast_June_2026.xlsx (Cash_Position last row formula, Vendor_CF_Forecast row 4 sum range, Vendor_CF_Forecast row 7 #REF). Minor variances of a few thousand SAR — realistic analyst workbook artefacts.
- Email_3_Vendor_Dispute_Mar_2026.txt is a routine vendor dispute with no leakage implication.

---

## Cross-system entity resolution required

Several patterns require the agents to reason across documents. The new invoice PDFs strengthen these chains by giving agents the actual transactional document, not just a header row:

- **Pattern 1** — same Invoice_ID across the invoice PDF AND two AP rows AND two distinct bank-statement payment legs (wire + cheque)
- **Pattern 2** — same Tax_ID and Bank_Account across two Vendor_IDs in Vendor_Master AND two invoice PDFs (one clean, one scanned — OCR required) describing the same goods
- **Pattern 3** — vendor master shows no contract; invoice PDFs show no PO reference and cite Omar Faridi's verbal approval; the approval email exists; same approver across all 11 invoices in AP
- **Pattern 4** — contract Schedule A (PDF) → PO (CSV) → AP invoice (Excel) → invoice PDF (showing the actual SAR 41.00 unit price in print)
- **Pattern 5** — contract §3 (PDF) → invoice PDF footer (prints 2/10 net 30) → AP Invoice_Date − Payment_Date arithmetic (Excel)
- **Pattern 6** — contract §3.2/§3.3 (PDF) → invoice PDF rate-basis note (citing CPI+3% escalation explicitly) → AP invoice rate (Excel) → 2025 baseline reasoning
- **Pattern 7** — Hedges sheet (Excel) → invoice PDF (EUR-denominated) → bank statement rate (PDF) → email confirming spot was used (TXT)
- **Pattern 8** — credit note PDF (Nov-2024) → opening GL credit balance (CSV) → invoice PDF footer flag → vendor master active flag (Excel) → unoffset H1 AP invoices (Excel)
