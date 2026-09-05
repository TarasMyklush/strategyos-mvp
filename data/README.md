# StrategyOS data

The current synthetic executive demonstration is `demo/01_Synthetic_Dataset`, formerly the enriched July 28 dataset. It includes finance/history, budgets, events, signals, calendar, question bank, document vault, board KPIs, initiatives, daily pulse, assistant profiles and executive-policy inputs. Companion strategy and market context lives in `demo/04_Strategic_Context`.

These files are synthetic source inputs, not approved runtime results. The June 2026 dates are part of the demonstration. Do not describe them as live business data. Loading them requires classification, validation and the normal run/reviewer/publication flow.

The file manifest records SHA-256 identities in `manifest.json`. Source workbooks/PDFs are authoritative for facts; README/answer-key material is evaluator documentation and must remain outside customer answers. Keep executive-policy assumptions and missing/non-financial conversion limits visible.

Two smaller/fixed regression inputs remain under `tests/fixtures`: the original finance-detector fixture and the exact POC-2 intake-accounting fixture. Their different facts and expected counts are intentional. Do not replace them with the current demo just to reduce file count.

The original stale strategic-context README has been replaced with an accurate directory guide. Portfolio facts must come from the strategy PDFs and source workbooks. The application and tests use repository-relative paths; environment overrides are documented in `docs/operations.md`.
