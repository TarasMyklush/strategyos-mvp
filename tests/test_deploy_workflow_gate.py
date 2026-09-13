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


def test_preview_deploy_does_not_allow_unsigned_package_indexes() -> None:
    text = (ROOT / '.github/workflows/strategyos-branch-deploy.yml').read_text(encoding='utf-8')
    assert 'AllowInsecureRepositories' not in text
    assert '--allow-unauthenticated' not in text
    assert 'sudo apt-get update' in text


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


def test_production_deploy_atomically_attests_running_release_and_source() -> None:
    import yaml

    workflow = yaml.safe_load(_deploy_yaml())
    steps = workflow['jobs']['deploy']['steps']
    attestation = next(step for step in steps if step.get('name') == 'Attest deployed revision and approved source snapshot')
    assert 'deploy/scripts/record_release.py' in attestation['run']
    assert '--container strategyos-strategyos-api-1' in attestation['run']
    assert '--provider-container strategyos-codex-gateway-1' in attestation['run']
    assert "--provider-image-ref '${STRATEGYOS_CODEX_IMAGE}'" in attestation['run']
    assert 'No new source authorization or business ratification.' in attestation['run']


def test_release_builds_and_deploys_the_gateway_from_the_same_commit() -> None:
    import yaml

    workflow = yaml.safe_load(_deploy_yaml())
    image = workflow['jobs']['image']
    assert image['outputs']['codex-image-ref'] == '${{ steps.codex-image-ref.outputs.value }}'
    gateway = next(step for step in image['steps'] if step.get('name') == 'Build and push Codex gateway image')
    assert gateway['with']['file'] == 'deploy/Dockerfile.codex-gateway'
    assert gateway['with']['push'] is True
    assert 'STRATEGYOS_RELEASE_SHA=${{ github.sha }}' in gateway['with']['build-args']
    deploy = workflow['jobs']['deploy']
    assert deploy['env']['STRATEGYOS_CODEX_IMAGE'] == '${{ needs.image.outputs.codex-image-ref }}'
    deploy_step = next(step for step in deploy['steps'] if step.get('name') == 'Deploy compose stack')
    assert 'deploy/scripts/deploy_stack.sh' in deploy_step['run']


def test_deployment_only_creates_a_customer_run_when_explicitly_requested() -> None:
    import yaml

    workflow = yaml.safe_load(_deploy_yaml())
    steps = workflow['jobs']['deploy']['steps']
    smoke = next(step for step in steps if step.get('name') == 'Verify queued execution')
    assert smoke['if'] == '${{ inputs.run_smoke }}'
    worker = next(step for step in steps if step.get('name') == 'Check Hatchet worker health')
    assert 'check_hatchet_worker.sh' in worker['run']
    assert 'run_smoke' not in worker.get('if', '')


def test_full_factual_corpus_is_explicit_and_release_bound() -> None:
    import yaml

    text = _deploy_yaml()
    assert 'run_factual_corpus:' in text
    assert 'description: Collect the fixed 50-question factual corpus through the deployed UI' in text
    workflow = yaml.safe_load(text)
    steps = workflow['jobs']['research-ui']['steps']
    corpus = next(step for step in steps if step.get('name') == 'Collect the fixed factual corpus through the deployed UI')
    assert corpus['if'] == '${{ !cancelled() && inputs.run_factual_corpus }}'
    assert '--release "${GITHUB_SHA}"' in corpus['run']
    assert 'hosted-factual-corpus-ui/' in next(step for step in steps if step.get('name') == 'Upload screenshot and report')['with']['path']


def test_ci_requires_signed_package_indexes():
    text = (ROOT / '.github/workflows/strategyos-ci.yml').read_text()
    assert 'AllowInsecureRepositories' not in text
    assert '--allow-unauthenticated' not in text


def test_live_environment_aliases_share_the_same_noninterrupting_lock():
    import yaml
    deploy = yaml.safe_load(_deploy_yaml())
    provider = yaml.safe_load((ROOT / '.github/workflows/strategyos-codex-production.yml').read_text())
    assert deploy['concurrency']['group'] == provider['concurrency']['group']
    assert '${{' not in deploy['concurrency']['group']
    assert deploy['concurrency']['cancel-in-progress'] is False
