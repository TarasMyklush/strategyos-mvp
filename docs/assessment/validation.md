# Validation record

## Preview remediation — 5 September 2026

The [release receipt](evidence/preview-release.json) identifies the deployed image, schema, approved synthetic run and 169-file source digest. The [gap register](gap-register.json) is the single current status record. Original consolidation results below are historical.

- Latest completed full service suite: **1,771 passed, zero skips**, real PostgreSQL and Neo4j, 211.67 seconds. See [JUnit evidence](evidence/remediation-full-services.xml).
- The full service result includes source-inventory and coverage-wording changes. Subsequent invalid-input UI handling passed **11 focused release-contract tests**; it is queued for deployment after the running factual test.
- Local semantic indexing: **37,537 eligible records**; [source index](evidence/source-index-proof.json), [scope test](evidence/live-semantic-scope.json), and [held-out English/Arabic corpus](evidence/semantic-release-results.json). Evaluator questions are excluded from retrieval.
- [Immutable board proof after upload](evidence/board-after-current-upload.json), [restart](evidence/board-after-restart.json), and [reprocessing](evidence/board-after-reprocess.json) retained every recorded file hash and answer. [New closure UI](evidence/ui-new-board-closure.txt) switched immediately to frozen routes.
- [Cross-tab sign-out](evidence/ui-cross-tab-signout.json), [upload form preservation](evidence/ui-upload-refresh.json), and [download byte/zero/Arabic verification](evidence/ui-upload-download.json) passed. The owned synthetic upload was then removed.
- [Live inference audit](evidence/live-inference-audit.json) verifies tenant/user identity, encrypted payloads, content hashes and rejection of wrong-tenant decryption. Missing authenticated scope blocks provider calls.
- [Post-change isolated restore](evidence/postchange-restore-proof.json) reconciled run, artifact, board, conversation and decision digests. Its 116.092-second database restore is an observation, not an agreed RTO.
- The fixed 50-question factual acceptance run is **not yet passed**. The [complete 4efaf51 run](evidence/qa-4efaf51-full-responses.json) exposed further retrieval/citation/calculation gaps. Earlier [audit-context](evidence/qa-pre-audit-fix-partial.json) and [quota-limited](evidence/qa-86475f8-quota-limited.json) attempts remain separately identified; routing matches and safe refusals are not correct-answer counts.

Actual ERP, bank, treasury and calendar connections remain deferred. Client ratification, real amendments, four-persona workflows, full RTL/accessibility and agreed operating targets are not fabricated as completed. HTML/CSS layout and styling remain unchanged from the remediation baseline.

## Original consolidation validation

Verified locally on 5 September 2026.

| Check | Result |
|---|---|
| Final portable suite, isolated application and twin state | **1,572 passed, 76 skipped, 0 failures/errors**, 196.31 seconds |
| Focused configuration/deployment checks | **63 passed** |
| Initial full run before adding explicit twin-path isolation | 1,571 passed, 76 skipped; superseded by the final isolated run |
| Enriched-data identity | All **169 file hashes** match the manifest after relocation |
| POC-2 source accounting | Included in passing suite; fixed 81-file fixture now executes |
| Wheel packaging | Build passed; both fonts, favicon and all three twin HTML pages present; no demo fixtures/private paths in wheel |
| Final video master | SHA-256 unchanged after relocation |
| Persisted local twin state during final tests | All 23 snapshotted files remained byte-identical after the snapshot |

The full suite was invoked with the final isolated runner and `--ignore=tests/test_codex_gateway.py`, excluding concurrent gateway work from a separate task. The newly added repository-default dataset configuration test is included. The final runner sets disposable application, output and twin-state paths and removes inherited application/provider/service settings. The state comparison started during the final run; it is not a before/after assertion for the earlier initial run.

The 76 skipped tests are not passing integration proof. Their exact skip reasons and machine-readable counts are in [consolidation-verification.json](evidence/consolidation-verification.json). Five existing deprecation warnings remain. No live Postgres/Neo4j/Hatchet integration environment, production capacity test, deployment or full factual 50/500-question evaluation was run for this cleanup. Concurrent Codex gateway files and deployment-script edits were preserved and are outside the consolidation release-validation claim.

Evidence: [final pytest log](evidence/final-isolated-pytest.log), [JUnit result](evidence/final-isolated-pytest.xml), [focused checks](evidence/consolidation-focused.log), [packaging checks](evidence/packaging-check.json), [baseline live observations](evidence/live-access-checks.json).

The prior gap-analysis observations remain baseline evidence. Workspace consolidation partially remediates G02, G11, G31 and G32; it does not close the broader product, security or hosted-release gaps.
