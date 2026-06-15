# StrategyOS `/app` — business-user UI fix list

**Date:** 2026-06-15
**Reviewer:** hands-on review of the live app at `https://strategyos.live/app` (operator session, Tamween H1 2026 run: SAR 794,108 recoverable, 8 findings, 4 challenges, 39/41 citations).
**Goal:** close the gap between the deployed command cockpit and the CEO/CFO target (calm, decision-first, plain-language). This is **refinement, not redesign** — the chat + KPI + slide-over architecture is already right.
**Scope note:** all file/line refs verified against the working tree on 2026-06-15; line numbers will drift as code changes — grep the named functions.

---

## How to read this

Each item: **impact** (business-user value) × **effort** (dev cost), the **evidence** from the live review, the **code location**, and the **fix**. Work top-down — P0s are the difference between "engineer's console" and "exec tool."

| Pri | Item | Impact | Effort |
| --- | --- | --- | --- |
| P0 | 1. Light "boardroom" theme | High | M |
| P0 | 2. Natural-language questions fail | High | M–L |
| P0 | 3. Findings as a decision worklist | High | M |
| P1 | 4. Suggestion chips should ask, not fill | Med | XS |
| P1 | 5. "Graph" → "Diagnostics" mislabel + raw graph | Med | S |
| P1 | 6. Upload flow has 3 file pickers for 2 choices | Med | XS |
| P2 | 7. Plain-language relabel pass | Med | S |
| P2 | 8. CEO trend/history view | Med | M (needs endpoint) |

---

## P0 — do these first

### 1. Replace the dark "command cockpit" skin with the light boardroom theme
**Why it matters most:** the dark, mono-font, `RECOVERY CONTROL ONLINE` / `HUMAN GATE` terminal aesthetic reads as an ops console for engineers, not a finance review for a CFO/CEO. This single change moves the perceived audience more than any feature.
**Evidence:** live app is dark slate with neon-green accents and uppercase system eyebrows throughout.
**Code:** `static/styles.css` (the design tokens — backgrounds, accent, surfaces). The reference target already exists: `docs/chat-dashboard-ui-mockup.html` (white surfaces, teal `#0F6E56` on `#E1F5EE`, system font, 0.5px borders). The HTML in `static/index.html` is largely theme-agnostic — most of this is a CSS token swap, not markup surgery.
**Fix:**
- Retheme `styles.css` to the light token set from the mockup. Keep semantic green/amber/red for status only.
- Drop the uppercase "eyebrow" labels (`RECOVERY CONTROL ONLINE`, `HUMAN GATE`, `EVIDENCE MAP`, `SOURCE INTAKE`) or make them sentence-case muted labels.
- Verify `tests/test_frontend_shell.py` still passes — it asserts on element ids/hooks, not colors, so a token swap should be green. Confirm no test asserts on specific hex/theme strings.
**Acceptance:** the page reads as a light finance dashboard; all 15 shell tests green unmodified.

### 2. Make natural-language questions work (the #1 functional blocker)
**Why:** a business user asks in their own words. The deterministic engine is keyword-bound, so normal phrasing falls through to a "try one of these" chip wall — the curated list effectively *is* the ceiling of the product.
**Evidence:** asked *"How much are we losing and what should I do about it?"* → response *"I don't have a deterministic answer for that yet. Try one of these:"* + suggestion grid. Root cause confirmed in code: `_handle_recoverable` triggers only on literal `recoverable / recovery / leakage / savings` (`qa.py` INTENTS table, ~line 383); "losing" / "losses" / "bleeding" / "where's the money going" don't match. Matching is a linear `for intent in INTENTS` scan using `_has` / `_has_any` exact-term checks (`qa.py:419`); there is no synonym/alias layer.
**Code:** `qa.py` — `INTENTS` tuple (~375), `_has`/`_has_any` (~25–31), `answer_question` (~415).
**Fix — two tracks, do (a) now, scope (b):**
- **(a) Widen the deterministic synonyms (cheap, ship this week).** Add a synonym map so each intent's trigger terms expand: recoverable ← {losing, loss, losses, leaking, bleeding, "going out the door", clawback}; vendor ← {supplier, payee, who we pay}; findings ← {issues, problems, what's wrong}; overdue ← {unpaid, outstanding, owed}. Centralize as a `SYNONYMS: dict[str, tuple[str,...]]` consulted in `_has_any`. This alone catches most CFO phrasings. Add tests in `tests/test_qa.py` for 8–10 paraphrases of existing intents.
- **(b) Decide the LLM-mode default for this persona (bigger call).** The gated LLM Q&A already exists (commit `670f22f` "Add DeepSeek LLM Q&A mode"; `mode` is already sent in the `/qa` body — `app.js:851`). Question for the team: should the business-user surface **default** to gated LLM (evidence-grounded, falls back to deterministic) instead of defaulting to deterministic? That removes the wall entirely but has cost/policy implications. Keep deterministic as the auditable fallback. Document the decision either way.
**Acceptance:** the three paraphrases "how much are we losing", "what's wrong here", "who do we pay the most" all return a real cited answer, not a chip wall.

### 3. Present the 8 findings as an actionable decision worklist
**Why:** the cockpit answers *questions* well but doesn't show the findings as **rows you act on** (cash impact · owner · evidence · approve/reject). That worklist is the core CFO job and the heart of the mocked CFO workspace. Today, when nothing needs approval, the right-hand "Review control" panel is just empty and the findings aren't browsable at all.
**Evidence:** live app has no finding list; the only way to learn a finding exists is to ask the chat or open the raw graph. Right panel showed "No approval needed" with nothing else.
**Code:** new component in `static/index.html` + `app.js`. Data already exists: `run_summary.json` carries `findings`/`locked_findings`; per-finding detail (amount, pattern, confidence, citations, challenge) is in the run artifacts (`Final consolidated case file`, `StrategyOS Ping Pong Audit Log.json`). The challenge/citation summaries are the same ones item 6 of `chat-dashboard-ui-plan.md` already specced (`GET /runs/latest/audit-summary` is a permitted additive endpoint).
**Fix:**
- Add a "Findings" panel: one row per finding — plain-language title, recoverable amount, owner, citation count (click → evidence), status pill (needs sign-off / approved / control gap).
- For runs that require review, surface Approve/Reject inline (endpoints exist: `/reviewer/runs/{id}/approve|reject`).
- Build the evidence drill-down (calculation + source excerpts + the ping-pong challenge) — reference mockup already designed.
- Relabel pattern types to human titles via a lookup (see item 7).
**Acceptance:** a CFO can scan all 8 findings, see cash + owner per row, click into evidence, and (when applicable) approve/reject without using the chat.

---

## P1 — high-value, low cost

### 4. Suggestion chips should ask the question, not just fill the box
**Evidence:** clicking "What is the total amount of invoices?" only populated the input; required a second click on Send.
**Code:** `app.js` — `setSuggestion(value)` (~882) currently does `els.chatInput.value = value; els.chatInput.focus();`. The click handler at `app.js:1941` routes `[data-suggestion]` here.
**Fix:** change `setSuggestion` to fill **and submit** — set the value then invoke the same submit path the form uses (the `askQuestion`/submit function around `app.js:843`). Keep the keyboard-fill behavior only if a chip is focused via keyboard and the user hasn't pressed enter; simplest is fill-then-send on click.
**Acceptance:** one click on any chip produces an answer.

### 5. Rename "Graph" and don't drop business users into "Diagnostics"
**Evidence:** the header **Graph** button opens a drawer titled `SYSTEM / Diagnostics` containing a force-directed node cloud (`40 view nodes · 48 view edges · 2,357 source nodes`) with unreadable micro-labels, plus "Managed data" and raw run IDs. No CFO will use this.
**Code:** `static/index.html` — the system drawer is `#system-drawer` titled "Diagnostics"; the Graph button (`#graph-drawer-button`) and Diagnostics button (`#system-drawer-button`) both open it (`app.js` drawer wiring ~117–125). Graph rendering: `renderKnowledgeGraph` / `#kg-graph` (cytoscape) ~1092–1134.
**Fix:**
- Separate concerns: a business-facing "Evidence map" (or fold relationships into the finding drill-down) vs. an Admin/Analyst "Diagnostics" drawer (managed data, raw payloads, health). Don't title anything a business user sees "Diagnostics."
- If the raw cytoscape graph stays, give it a business translation layer (e.g. "Gulf Logistics shares a tax ID with another vendor — possible duplicate") instead of `F-001` nodes. Otherwise move the raw graph entirely behind the Analyst view.
**Acceptance:** nothing on the default business path is labeled "Diagnostics"; the relationship insight is readable as a sentence.

### 6. Remove the redundant third file picker in the upload slide-over
**Evidence:** "Start analysis" shows two good choice-cards (Upload .zip / Choose folder) **plus** a third generic "Choose files — Upload a source zip or a folder of finance files" row beneath the primary button. Three pickers for two choices.
**Code:** `static/index.html` `#source-pack-section` — the two `.upload-choice` labels (`#source-pack-files`, `#source-pack-folder-files`) are the keepers; the extra generic input/row below `#source-pack-upload-submit` is the redundant one.
**Fix:** delete the third generic picker; keep the two labeled cards + the single primary "Start analysis" button. Leave the "Details" disclosure (server path / recheck) as-is.
**Acceptance:** exactly two file inputs visible, one per card; one primary action.

---

## P2 — polish

### 7. Plain-language relabel pass
**Why:** business users don't read `fx_hedge_unapplied`, `invoice_metric`, `entity_resolution_duplicate`, "CASH classification", "writer stage", "human gate".
**Code:** a single lookup table (pattern_type → human title + one-line description), consumed by both the findings worklist (item 3) and the chat answer tags. Source of truth for pattern types: the detector registry / `detector_report`.
**Fix:** add `PATTERN_LABELS` map; render human titles everywhere a raw `pattern_type` or internal stage name currently shows. Examples: `fx_hedge_unapplied` → "FX hedge not applied"; `off_contract_single_approver` → "Off-contract spend, single approver"; "writer stage" → "final report".
**Acceptance:** no raw snake_case identifier or internal stage name appears on the business path.

### 8. CEO trend / history view
**Why:** CEOs think in direction of travel ("are we getting better"), not single-run snapshots. The current app is single-run only.
**Code:** needs a new additive endpoint — `GET /runs/history` returning `[{period, identified_sar, recoverable_sar}]`. This is the **one genuinely new backend piece** in this list; everything else binds to existing data. Front-end is a small bar strip (reference mockup exists).
**Fix:** add the history endpoint (read prior `run_summary.json` pointers), then a "Direction of travel" strip on a CEO view. Until earlier runs are loaded, render H1 2026 live + prior periods clearly marked sample.
**Acceptance:** a CEO sees leakage-caught across the last N reviews with a one-line trend read.

---

## What's already good — do not regress

- **Cited deterministic Q&A** — answer + basis line + intent tag + clickable citation chip (`AP_Invoices_H1_2026.xlsx — AP ledger Amount_SAR`). Input clears on send. This is the strongest part of the app; every change above should preserve it.
- **Upload slide-over altitude** — two plain-language choices, advanced settings hidden under "Details."
- **Honest empty states** — "No approval needed" instead of a fake banner.
- **The unmatched-question fallback** (chips) is the *right* failure mode — keep it as the floor even after widening NL matching.

---

## Suggested sequencing

1. **Quick wins bundle** (P1 #4, #6 + P2 #7): one PR, low risk, immediately less "engineer-y". 
2. **Theme** (#1): isolated CSS PR, shell tests as the guard.
3. **NL synonyms** (#2a): `qa.py` + tests; decide #2b separately.
4. **Findings worklist + evidence drill-down** (#3, #5): the big one — this is what makes it a CFO tool.
5. **Trend view** (#8): after the history endpoint exists.
