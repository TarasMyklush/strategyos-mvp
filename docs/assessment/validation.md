# Validation record

## Preview remediation — 5 September 2026

Release **44c9c31** is deployed to **https://new.strategyos.live**. The [receipt](evidence/preview-release.json) binds the immutable image, schema, approved synthetic run and 169-file source digest. [Deployment health](evidence/final-deployment-health.json) records authenticated checks and confirms production images were not changed. The worker process is running; no Docker healthcheck is configured for it.

- **1,781 tests passed, zero skips**, using real PostgreSQL and Neo4j, in 214.88 seconds. [JUnit](evidence/remediation-full-services.xml). [Release CI](evidence/ci-release.json) passed tests, compose validation and image build.
- **24/50 factual answers pass**, below the required 45/50. The [current grading](evidence/qa-release-grading.json) combines the completed fixed c72387d run with explicitly named targeted retests on the same source pack. Fourteen insufficient-evidence answers, ten partial answers and two missing calculations are not counted as passes. Earlier attempts remain historical evidence, not alternate current scores.
- Browser QA confirms [overlong-input validation without retry](evidence/ui-oversized-question-509f47e.txt), [a valid follow-up after failure](evidence/ui-valid-after-oversize.txt), and [complete quarterly revenue with resolved evidence](evidence/ui-quarterly-revenue-44c9c31.txt). The latest 664-pixel viewport had no horizontal overflow. Earlier desktop/mobile, login/logout, upload and persistence checks remain linked below.
- A [new frozen meeting](evidence/ui-final-frozen-meeting.txt) exposes read-only snapshot actions. [Final immutable-board verification](evidence/board-44c9c31.json) preserved all seven original file hashes and the exact approved answer through deployment. The [new report bytes](evidence/board-final-closure.json) match the snapshot. **Report page rendering remains blocked:** [in-app navigation](evidence/ui-final-frozen-report-navigation.txt) and [Chrome](evidence/ui-chrome-frozen-report.txt) both returned ERR_BLOCKED_BY_CLIENT, despite authenticated HTTP 200 with text/plain content. This is an unresolved UI acceptance issue.
- [HTML/CSS preservation](evidence/ui-preservation.json) verifies byte identity against d63fe5b. Functional JavaScript fixes changed validation, session behavior and evidence labels; no layout or stylesheet redesign was made.
- [Cross-tab sign-out](evidence/ui-cross-tab-signout.json), [upload form preservation](evidence/ui-upload-refresh.json), and [download byte/zero/Arabic verification](evidence/ui-upload-download.json) passed. Owned synthetic uploads were removed.
- Local multilingual E5 indexes **37,537 eligible records**. [Index proof](evidence/source-index-proof.json), [live scope test](evidence/live-semantic-scope.json), and [held-out English/Arabic results](evidence/semantic-release-results.json) are retained. Evaluator questions are excluded from retrieval.
- [Encrypted inference audit](evidence/live-inference-audit.json) verifies tenant/user identity, payload hashes and wrong-tenant decryption rejection. The temporary preview QA allowance was 64 million character-equivalent reservation units and 500 requests; this is neither a token count nor a billed-cost measure. Quota and retention enforcement remained enabled.
- [Final isolated database restore](evidence/final-restore-proof.json) reconciled all five checked table digests. [Private file backups](evidence/final-files-backup-proof.json) verified every archived workspace/application/configuration file. The 116.719-second restore is an observation, not an agreed RTO. Qdrant is rebuildable from the sealed source/model; full infrastructure recovery is not certified.

The [gap register](gap-register.json) is the sole current product status record. Actual ERP, bank, treasury and calendar connections remain deferred. Real owner ratification/amendments, complete persona/RTL experiences, target-capacity testing and agreed operating commitments are not fabricated as completed. Current release plus one verified rollback are retained; temporary proof services, duplicate local models and intermediate deployments were removed.

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
