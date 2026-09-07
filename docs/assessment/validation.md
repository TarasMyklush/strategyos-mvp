# Validation record

## Hosted board pack composer — 7 September 2026

The deployed additive release connects the saved Intent analysis to an EN/AR preview,
PPTX and PDF exports, portable JSON client templates, per-cell evidence links and
freshness warnings. There is no database migration or new connector.

- Focused regression: **240 passed**, four warnings, 10.43 seconds.
- Additional mixed-direction rendering regression covers signed decimals and dates.
- Real disposable PostgreSQL proofs cover immutable figure binding, newer plan and
  actual warnings, missing values, tenant/role denial, current source export
  revocation, evidence byte changes, input validation and session CSRF.
- Bilingual PDF and PPTX were generated from synthetic source-bound analysis and
  all nine pages inspected. PPTX was rendered with bundled LibreOffice, not PowerPoint.
- Full hosted service gate on application `13c6624`: **2,330 passed, zero skips**,
  six warnings, 473.20 seconds. Image build, rollout, worker health and public HTTPS
  readiness all passed. Workflow: https://github.com/TarasMyklush/strategyos-mvp/actions/runs/34149926129.
- Browser proof also exercised both downloads, Arabic preview, client/metric template
  changes, rejected numeric overrides and template download. See
  [local acceptance](evidence/board-pack-local-acceptance.json).

- Hosted acceptance passed **18 recorded HTTPS checks**, plus anonymous and
  cross-origin denial. All six EN/AR/bilingual PDF/PPTX exports opened structurally,
  carried the saved analysis binding and included protected evidence links. Operator,
  reviewer and auditor composition succeeded; BU access and numeric template overrides
  were rejected. The saved analysis remained byte-for-byte equal as parsed JSON.
- Runtime revision `13c6624da42091a49c1f02b2dd14802ae8cb7089`, image
  `sha256:410d67f9f25ffcd716e144e16ba0b970d47f9796399e5ca753e0a0f0b172ab72`,
  is healthy at https://new.strategyos.live/plan. Schema verification passed.
  Selected run/source/receipt and production image identities were preserved.

Evidence: [hosted acceptance](evidence/board-pack-hosted-acceptance.json),
[runtime](evidence/board-pack-runtime.json), [before rollout](evidence/board-pack-predeploy.json).

Scope and limitations: [composer contract](../board-pack-composer.md).

## Hosted Intent Vault — 7 September 2026

The reused `/plan` Intent Vault is deployed to **https://new.strategyos.live/plan**.
Application revision `1240f84` passed the complete service gate: **2,322 passed,
zero skips**, six warnings, 498.37 seconds. The image build and preview deployment
workflow succeeded. Deployment configuration correction `c8b8715` then propagated
the public HTTPS URL into the API without changing its image or other settings;
**103 focused checks passed** for that correction and its affected boundaries.

- The migration job prepared all five Intent tables. The live request database role
  has SELECT/INSERT only, with tenant RLS; UPDATE/DELETE/TRUNCATE are denied.
- Hosted acceptance used existing configured tester identities and synthetic data.
  Thirteen recorded HTTPS session-cookie checks covered import, explicit separate
  ratification, analysis/readback, evidence bytes and restricted-role denial. Anonymous
  catalog access was also rejected. Source staging/registration used the existing APIs.
- The synthetic approved plan shows 200 SAR actual against 200 SAR target, while
  flagging the regional miss and institutional offset. The saved analysis reopened
  identically. The test ratification explicitly disclaims business/board authority.
- Selected-run pointer and previous release-receipt hashes remained identical.
  The selected executive run remains awaiting review; this release did not approve it.
  Production API/worker image identities also remained unchanged.
- The selected run has no approved source-release manifest, so the approved-run
  attestation helper was not used. The separate runtime receipt records its pending
  state and actual source snapshot hash without fabricating approval.

Evidence: [release](evidence/intent-vault-release.json),
[runtime/schema](evidence/intent-vault-runtime.json),
[hosted acceptance](evidence/intent-vault-hosted-acceptance.json),
[predeployment identities](evidence/intent-vault-predeploy.json).
The broader factual QA, real client ratification, Authority Matrix and board composer
acceptance remain separate open work.

## Local governed Intent Vault — 7 September 2026

The next local increment adds durable dimensional APIs and repurposes the existing
`/plan` execution tracker as the Intent Vault. It includes version/evidence review,
separate authorized ratification, operator imports, administrator permission controls
and saved granular drift. The retired tracker API redirects to the authenticated
catalog. No hosted deployment, business database migration or active-run change was made.

- Broader isolated portable suite: **1,744 passed, 81 skipped, no failures**,
  149.77 seconds, six warnings. Command: `.venv/bin/python scripts/test.py -q
  --ignore=tests/test_codex_gateway.py`. Skips are not passing service integration
  proof; the new dimensional PostgreSQL tests ran against their own disposable
  cluster. The separately maintained Codex gateway suite was excluded.
- Focused regression suite: **114 passed**, no skips. This includes the dimensional
  evaluator, isolated real-PostgreSQL service proof, authentication boundaries and
  affected Plan-page contracts. One Starlette/httpx deprecation warning remains.
- Browser verification used a disposable local server, synthetic company/evidence,
  named test principals and a private socket-only PostgreSQL cluster. A separately
  authorized executive ratified the operator's proposal, then calculated 200 SAR
  actual against 200 SAR target while exposing +60/-60 SAR cell offsets. The saved
  analysis reopened with the same results. Operator/admin controls were role-gated;
  a restricted BU identity was denied with no plan data displayed.
- The temporary browser proof server and database were stopped and removed.
  This is local synthetic proof, not real client approval or deployed acceptance.
- JavaScript syntax and `git diff --check` passed. Source hashes establish artifact
  integrity; exact semantic value verification remains outstanding. Full Authority
  Matrix integration, finer scope and the broader G12/G13/G15 acceptance remain open.

## Local dimensional foundation — 7 September 2026

The read-only operator module `strategyos_mvp.dimensional_plan` and portable
synthetic fixture were added locally. No deployment, active-run change, database
migration, email integration or executive UI change was performed.

- **75 tests passed**, no skips, in 1.50 seconds using the isolated runner:
  `tests/test_dimensional_plan.py`, `tests/test_strategy_compiler.py`,
  `tests/test_metric_claim_contracts.py`, `tests/test_platform_foundation.py`,
  `tests/test_source_governance.py`. One Starlette/httpx deprecation warning remains.
- The documented CLI example returned 200 SAR actual against 200 SAR plan,
  exposing the 60 SAR regional miss offset by institutional overperformance.
- New tests cover exact decimal values, missing versus zero, signed variance,
  reconciliation, duplicate/unknown tuples, unplanned actuals, units and periods,
  scope mismatch, future metadata, evidence integrity/path escapes, revision
  identity, row-order invariance, a second sector and read-only CLI success/failure.
- Source hashes validate bytes, not semantic correctness or approval authority.
  Approval status is imported metadata, explicitly labelled unverified. This
  foundation does not close G12/G13/G15 or replace the deployed factual QA gate.

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
