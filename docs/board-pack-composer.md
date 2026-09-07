# Board pack composer

The Intent Vault `/plan` page composes a board review from a saved, ratified-plan
analysis. Open a saved analysis, choose English, Arabic or both, preview the pack,
and download editable PPTX or PDF. The same whole-company roles that can read
Intent analyses may compose, provided current source policy also permits export.
This is available to executive, reviewer, auditor and operator workflows; it does
not depend on a CEO-specific surface.

## Client configuration

The expandable Client template editor loads and downloads portable JSON pack
artifacts. Templates contain a version, bilingual client/title, accent colour and
exact-name bilingual metric/dimension labels. They cannot supply figures, formulas,
HTML, filesystem locations or evidence overrides. A template change requires no
release. Save the template file to reuse it; this increment does not yet provide a
server-side client-template registry or the guided Strategic Advisor console.

Labels without translations retain their original names, and the preview lists
those names. Template-provided translations require client review. PDF embeds
licensed Noto fonts and shapes Arabic; editable slides use Noto Sans and Noto Sans
Arabic (install those fonts on the presenting computer). Numeric strings, signs
and ISO dates retain their order in mixed-direction text.

## Binding and freshness

Every composition rechecks the immutable analysis digest, current tenant/source
access, export permission and source byte hashes. Changed evidence or revoked
permission blocks export. Newer visible ratified plans for the same reporting
period generate a warning. Newer actual snapshots also generate a warning; they
are not assumed to supersede an existing snapshot because scope may differ.
Saved figures never silently refresh. Each downloaded file is a fixed snapshot;
recompose to check current freshness.

Every planned cell includes plan/actual evidence reference numbers. Evidence pages
contain paths, locators, SHA-256 and authenticated download links. Rollups derive
from those cells, preserve missing/incomplete status and disclose unplanned tuple
counts. The provenance page records analysis, plan, actuals, template and pack
hashes. PPTX notes also carry the binding and check timestamp. No LLM supplies
numbers. Artifact integrity does not certify the semantic correctness of values.

## Scope and next increments

This first composer supports 200 cells and 30 metrics, one slide per cell and one
per evidence reference. It rejects oversized report lines rather than truncating
figures. It is a granular performance review, not a complete statutory board pack.
Saved pack history, template registry, page-layout customization, claims/graph
narrative sections and real client bilingual acceptance remain next increments.
Plan decomposition, price/volume/mix attribution, the guided advisor configuration
console and permissioned test-domain outreach remain separate roadmap work.
