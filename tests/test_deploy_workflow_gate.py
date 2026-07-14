"""Locks the pre-deploy gate into the deploy workflow.

The deploy pipeline's test gate has been weakened or removed twice:
- 2026-07-09: the gate ran only a hand-picked 15-file subset, letting
  finance-correctness/acceptance regressions ship "green".
- 2026-07-10: commit 8795a20 deleted the pre-deploy test job entirely
  ("skip duplicate tests during manual deploy") with no compensating
  check, so a manual dispatch could deploy an untested or red commit.

The current design intentionally does NOT re-run the suite on deploy --
the same SHA already ran the full suite on push (strategyos-ci.yml).
Instead, a fail-closed `verify-ci` job requires a successful StrategyOS
CI run for the exact deployed SHA before anything builds or ships.
This test fails if that gate is deleted or detached a third time.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "strategyos-deploy.yml"


def _deploy_yaml() -> str:
    return DEPLOY_WORKFLOW.read_text(encoding="utf-8")


def test_deploy_workflow_has_a_fail_closed_ci_verification_gate() -> None:
    text = _deploy_yaml()

    assert "verify-ci:" in text, (
        "strategyos-deploy.yml must keep the verify-ci pre-deploy gate. "
        "Deploys must not ship commits without a green CI run for the same SHA."
    )
    assert "actions/workflows/strategyos-ci.yml/runs?head_sha=${GITHUB_SHA}" in text, (
        "verify-ci must check the StrategyOS CI run for the EXACT deployed SHA"
    )
    assert "Refusing to deploy a commit without a green CI run" in text
    assert "Refusing to deploy unverified code" in text, (
        "verify-ci must fail closed when CI never finishes / never ran"
    )


def test_deploy_jobs_are_actually_gated_on_ci_verification() -> None:
    text = _deploy_yaml()

    image_job = text.split("\n  image:", 1)[1].split("\n  deploy:", 1)[0]
    assert "needs: verify-ci" in image_job, (
        "the image job must depend on verify-ci -- a gate no job needs: on "
        "is decoration, not a gate"
    )
    deploy_job = text.split("\n  deploy:", 1)[1]
    assert "needs:" in deploy_job.split("steps:", 1)[0], (
        "the deploy job must remain chained behind the gated image job"
    )


def test_deploy_verifies_the_anonymous_login_boundary_after_cutover() -> None:
    text = _deploy_yaml()

    assert "STRATEGYOS_LOGIN_REQUIRED: 'true'" in text
    assert '"STRATEGYOS_LOGIN_REQUIRED": os.environ["STRATEGYOS_LOGIN_REQUIRED"]' in text
    assert text.count("--login-required") == 2
    assert "- name: Verify anonymous login boundary" in text
    assert "Anonymous application, API-documentation, and login boundaries are closed." in text
