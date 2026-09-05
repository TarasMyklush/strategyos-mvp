# Consolidation validation

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
