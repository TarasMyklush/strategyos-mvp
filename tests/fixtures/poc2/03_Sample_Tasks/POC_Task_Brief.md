# POC Task Brief — Tamween Distribution Co. H1 2026 Cash Leakage Review

## Engagement context

You are the Finance Analyst and Finance Auditor agents operating inside ExOS, orchestrated by the Legion-Rights harness. The CFO of Tamween Distribution Co. has engaged the platform to perform a one-time H1 2026 cash-leakage discovery exercise, followed by a working-capital drift check and a conversational drill-down session with the executive team.

The full H1 2026 finance dataset is available in the `01_Synthetic_Dataset/` folder. You may read every file in every subfolder. You may not modify any file or fabricate new evidence. Your interaction protocol is ping-pong: the Analyst drafts, the Auditor challenges, you iterate up to ten rounds per task before producing a final consolidated case file.

The CFO wants three deliverables.

---

## TASK 1 — Cash Leakage Discovery (PRIMARY)

Review the H1 2026 finance dataset for Tamween Distribution Co. Identify every cash leakage pattern present in the data.

For each finding, produce a structured case-file entry containing:

1. **Pattern type** (duplicate payment, entity-resolution duplicate, off-contract spend, price variance, missed early-pay discount, auto-renewal escalation, FX hedge unapplied, dormant credit balance, or other — name it precisely)
2. **Affected vendor or entity** — name and Vendor_ID
3. **Evidence references** — file paths and specific document locations (row/column for Excel, page/paragraph for PDFs, transaction reference for bank statements, line for CSV, paragraph for emails)
4. **Estimated recoverable amount** — SAR and USD (use 3.7500 SAR/USD unless the document gives a different rate)
5. **Confidence level** — HIGH, MEDIUM, or LOW, with a one-sentence rationale
6. **Suggested remediation** — one paragraph describing what the company should do, who owns the action, and what the recovery vector is

Rank findings by recoverable amount, highest first. Classify each finding as CASH (recoverable as clawback or going-forward saving) or CONTROLS ONLY (process gap with no direct cash recovery but high fraud/overpay risk).

The Analyst drafts the case file. The Auditor challenges every finding — demanding three pieces of corroborating evidence per finding, reproducing every quantification, and adding any pattern the Analyst missed. Iterate up to 10 rounds.

Produce a final consolidated PDF case file with:

- A one-page executive summary (total leakage, total recoverable, top 3 findings)
- One section per locked finding
- A "Disputed" appendix for any finding that survived ten rounds with unresolved disagreement
- A methodology note covering files read, entities reconciled, and data quality issues encountered

---

## TASK 2 — Working Capital Drift Check (SECONDARY)

Examine Days Sales Outstanding (DSO) and Days Payable Outstanding (DPO) drift across H1 2026 against a 13-week trailing baseline. Flag the top three drift signals.

For each of the three:

1. State the drift direction and magnitude (e.g. "DSO increased by 11 days from a baseline of 38 to 49")
2. Identify whether the drift is systemic (concentrated in a customer segment, channel, region, or product category) or a one-time event (driven by one or two large transactions)
3. Cite the specific AR or AP rows that drive the signal
4. State the working-capital cash impact in SAR

DSO and DPO must be computed transparently — show the formula and the data window used. Flag any drift you can attribute to a known leakage pattern from Task 1 separately so the CFO does not double-count.

---

## TASK 3 — Drill-Down Q&A (PROOF OF CONVERSATIONAL DEPTH)

Answer the following three questions in conversational form, with evidence citations. Keep each answer to two paragraphs or fewer. The Auditor reviews each answer for evidence quality before it is finalised.

**(a)** Which vendor has the largest single-event cash leakage in H1 2026, and what is the leakage amount?

**(b)** If we recovered every dollar from the top five leakage findings, what would the impact be on H1 2026 EBITDA margin? (You will need to read the GL extract and trial balance to compute the baseline EBITDA, then apply the recoverable amounts.)

**(c)** Which leakage pattern would recur in H2 2026 if not addressed, and what is the projected H2 exposure? Distinguish patterns that are one-time events from patterns that compound or repeat.

---

## Acceptance criteria

For the POC to be considered a pass:

- At least 7 of the 8 deliberately-planted patterns are identified at MEDIUM or higher confidence
- Every identified finding has at least three citations to source documents
- The Auditor has challenged at least 50% of the Analyst's findings at least once
- The total recoverable amount stated falls within ±15% of the validated answer key
- Task 2 produces at least three plausible DSO/DPO drift signals
- Task 3 answers are factually defensible and cite evidence for every numerical claim

A stretch pass: all 8 patterns identified at MEDIUM or higher, and at least one additional non-planted observation (data quality issue, controls weakness, or other) added by the Auditor.

---

## Operating constraints

- **Sovereignty:** All processing must happen inside the ExOS environment. No external API calls. Local LLM inference only.
- **Confidentiality:** Treat the dataset as if it were live client data. Do not hash, exfiltrate, or summarise outside the case-file deliverable.
- **Citations:** Every quantitative claim in the final case file must be traceable to a source file and a specific location within that file.
- **Tone:** Both agents address the CFO directly. Crisp, terse, evidence-first. Avoid hedging language like "it appears" or "may suggest" — either you have the evidence or you don't have the finding.

---

## Deliverable list

At the end of the engagement, ExOS should produce:

1. **Final consolidated case file (PDF)** — Task 1 output
2. **Working capital drift memo (PDF or Markdown)** — Task 2 output
3. **Drill-down Q&A transcript (Markdown)** — Task 3 output
4. **Ping-pong audit log (JSON or Markdown)** — full record of Analyst draft → Auditor challenge → Analyst response per round per finding, for human review and for system-level evaluation

All four deliverables are submitted together. The Legion-Rights harness records the wall-clock and token cost of each ping-pong round for post-engagement performance review.
