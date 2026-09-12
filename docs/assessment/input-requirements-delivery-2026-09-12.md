# Input requirements delivery — 12 September 2026

This release follows the Input Folder audit. Completion requires deployed acceptance, not just a passing unit test or a source file being registered.

## Release work

| Requirement | Implementation | Acceptance status |
| --- | --- | --- |
| WP10: complete client board packs | Measured table pagination shared by preview, PDF and editable PowerPoint. Every cell and exact value remains present; individual value links resolve governed evidence. Full provenance is retained in a PDF attachment and PowerPoint notes. No silent truncation. | Local full H1: 288 cells, 576 references; EN, AR and bilingual exports. Regression: 576-row tables in all languages. Production acceptance pending. |
| F9: readable evidence | Business labels replace claim UUIDs in chat. The fact link opens a readable page with the same current tenant, source, authority and lineage checks; technical identifiers remain collapsed. | Escaping and authorization regression passed. Production UI acceptance pending. |
| F3: language failure and deterministic fallback | Pending. The fallback must use server-authorized, current facts, preserve their period and scope, and distinguish context from an answer. Browser cached figures cannot establish evidence. | Existing explicit error/retry tests do not close the written fallback requirement. |

## Remaining scope to reconcile

- F6/F7/F13: complete formula/provider/request, answer-label and chart-scope walkthrough.
- WP7: seasonality input, plan-version navigation and sector-pack removal proof.
- WP10: current-data bilingual exports, stale/regenerate lifecycle and persona/issue permissions in production.
- WP11: complete the specified configuration-console specification; this work order labels it SPEC, not a mandatory full console BUILD.
- v2 DOC/SPEC/ROADMAP: trace the specified briefs, decks, diagrams, Discovery Pack and roadmap commitments to their actual artifacts.
- POC task and agent contracts: verify case-file delivery, thirteen-week drift analysis, named drill-down questions and auditor challenge accounting.
- Question-bank coverage and demo-media deliverables: establish the expected acceptance scope and retain evidence for each delivered artifact; do not equate ten chat examples with the complete bank.

Actual email and external-system integrations remain deferred by the user's later instruction. Sol with medium reasoning is the authorized prototype model exception. Current POC monetary values remain SAR and NUPCO remains named, following the later dataset-specific direction.

## Release policy

Target: **https://strategyos.live**. Each chunk requires the full CI service suite, exact-release deployment and browser acceptance. Preserve the dedicated provider account and database runtime-role configuration. Do not replace concurrent development work or queue repeated deployments of failing revisions.
