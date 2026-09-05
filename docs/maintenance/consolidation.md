# StrategyOS consolidation receipt

Completed locally on 5 September 2026.

## Canonical state

- Application: this repository on `main`, advanced 121 commits from `9fa5316` to reviewed implementation `c03e958` before applying consolidation changes.
- Product contract: [requirements.md](../requirements.md), replacing the dated technical/design specifications, plans and R2/R4 notes. It records precedence, formulas, acceptance and traceability.
- Current implementation: [architecture.md](../architecture.md). Runtime instructions: [operations.md](../operations.md) and the deployment runbook.
- Current gap source: [gap-register.json](../assessment/gap-register.json); [gap-analysis.md](../assessment/gap-analysis.md) is its generated readable view. Open product gaps have not been relabelled complete.
- Current enriched source data: `data/demo`, with SHA-256 manifest. Legacy finance and exact POC-2 fixtures remain solely as distinct regression contracts.

## Cleanup performed

The active workspace no longer contains the dated requirement/input collections, alternate application prototypes, duplicated extracted datasets, old screenshot collections, failed/historical run copies, multiple final-deck variants, earlier film versions or four redundant Python environments. Unique final communication assets and supporting business materials were retained in clearly named sibling folders. Registered runtime source packs and persisted twin state were retained. Test credentials were moved to the restricted sibling `private` directory, outside this repository.

The removal manifest records approximately **2.05 GB** of obsolete material removed from the active workspace into the cleanup Trash folder. This is workspace reduction, not claimed disk space reclaimed from Trash. The user's explicitly requested deletion of `old-images.tar.gz` permanently removed **7,980,339,221 bytes (7.43 GiB)**; its recovery copies are no longer available. See [the archive receipt](deleted-recovery-archive.json).

Twenty-five old local branch references were retired, and eighteen missing-worktree registrations were pruned. A verified Git bundle retains their full prior history. Some retired branches contained commits not included in the selected release; they were not silently merged or destroyed. Their exact SHAs and counts are in [retired-branches.json](retired-branches.json).

## Changes needed to keep the project usable

- Replaced desktop-date dataset paths with repository-owned paths. The four enrichment tests now fail if required inputs are absent instead of silently returning. The exact 81-file POC-2 fixture now runs locally and in CI.
- Unified portable Make/CI test commands behind a disposable-workspace runner, including separate twin persistence paths and credential/service isolation. Removed stale active-run pointers into old pytest directories.
- Added required fonts and twin HTML to package data, and excluded local secrets/state/environments from Docker build context. The dependency lock and large-module refactoring remain open gaps.
- Updated documentation links, source provenance and data-generation tool paths. Retained final video production inputs with a dependency lock and portable Chromium selection; retired completed migration scripts. No video content was regenerated.

## Validation and scope

See [validation.md](../assessment/validation.md) for final results, skips and evidence. Data hashes and final video-master hash were verified after relocation. Source evidence links refer to the immutable reviewed commit, preserving audit traceability after deleting the duplicate source archive.

No GitHub push, remote-branch deletion, hosted deployment, live source-pack promotion or human-review approval was performed. The external Agent Studio worktree belongs to a separate project and contains unique API work; it was retained outside the canonical application baseline. Concurrent Codex gateway files and deployment-script work appeared during cleanup and were preserved outside this consolidation's change/validation scope.

## Recovery and future maintenance

[cleanup-manifest.json](cleanup-manifest.json) maps every removal/relocation. Obsolete recoverable material is in `/Users/taras/.Trash/StrategyOS-cleanup-20260905`; `pre-cleanup.bundle` contains Git history. The deleted 7.43 GiB image archive is the explicit permanent-deletion exception. Retired requirements can be inspected as provenance in that recovery folder; they are not active specifications.

Update the canonical specification, tests and gap record together. Keep historical versions in Git, not dated competing folders. After changing demo inputs, review their content and regenerate the SHA-256 manifest. Final deliverables and private/runtime state do not belong in the application source history.
