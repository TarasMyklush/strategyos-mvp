# GitHub Actions review — 12 September 2026

## Observed history

The latest 100 runs cover 9 September 17:35 UTC through 12 September 17:11 UTC. All 100 were manually dispatched: 53 succeeded, 36 failed, 11 were cancelled. This is excessive release fragmentation, not a push/PR trigger loop. Two commits had repeated deployment attempts. Failure metadata includes real deployment, readiness, browser acceptance and test failures; do not delete this history or describe every failure as a build defect.

The current live release 9dc8843 passed CI 34706453205 and deployment 34707384751, including executive, Intent and Hermes UI acceptance. CI 34707504078 was cancelled at the user's request to stop overlapping release sequences. No workflows were active when this review began. A supplemental forecast-coverage browser check on 9dc8843 passed in 21.1 seconds; its context-only answer is not a factual-answer completeness pass.

## Active workflow cleanup

The repository now has two active controls: StrategyOS CI and StrategyOS Deploy. The legacy Branch Deploy, Codex Provider Preview and Codex Provider Production workflows were disabled through GitHub's workflow API. Disabling them does not change the running application/provider or delete their files/history. Re-enable a maintenance workflow only after reviewing its target, pinned image, acceptance proof and approved provider account; the old production provider workflow contains historical image/run pins.

The reusable hosted-human-e2e file remains available in source. Its customer-source mutations target the legacy branch environment; it must not be casually dispatched against live customer data. The active deployment embeds its live UI acceptance checks.

## Release discipline

Use `python scripts/release_strategyos.py --ref BRANCH` for a read-only plan, then the same command with `--execute` for an authorized release. The command:

- Refuses to start while any repository workflow is active, avoiding a new queue.
- Reuses successful CI for the exact commit.
- Waits for CI completion before dispatching deployment.
- Refuses automatic retries of a failed/cancelled commit and duplicate deployment of a previously accepted commit.
- Checks branch identity again before each dispatch and verifies the returned run's commit and conclusion.
- Uses a local process lock and treats uncertain dispatch receipts as a stop condition, never a retry instruction.

All live deployment aliases now use the same noninterrupting concurrency lock as production provider maintenance. GitHub's manual Run workflow button still exists: this helper cannot atomically prevent a different client from manually dispatching after its idle check. The shared deployment lock prevents simultaneous cutovers, while the monitor flags overlapping/repeated sequences. Do not claim a server-wide atomic dispatch lock.

The application CI retains its full service suite and exact-commit deployment gate. Signed package verification remains required; the prior insecure apt-update option was removed. No failing test is suppressed and no history is erased to make Actions appear green.

A thread monitor runs every 30 minutes, remains quiet without actionable change, and never dispatches, retries or cancels workflows itself. It flags duplicates and new release failures.

## Validation status

Release orchestration regression: 11 tests passed locally, including duplicate suppression, active-run refusal, failed CI, cancelled CI and branch movement. Workflow contract tests and the consolidated full suite are recorded after completion. The cleanup source changes have not yet been submitted to CI or deployed; the operational workflow disablement is already applied.
