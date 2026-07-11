from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_gitignore_covers_generated_env_files() -> None:
    contents = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "deploy/.env" in contents
    assert "deploy/.env.secrets" in contents


def test_env_example_keeps_secrets_out_of_non_secret_defaults() -> None:
    env_example = (REPO_ROOT / "deploy/.env.example").read_text(encoding="utf-8")
    for secret_key in [
        "POSTGRES_PASSWORD=",
        "NEO4J_PASSWORD=",
        "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY=",
        "MINIO_ROOT_PASSWORD=",
        "STRATEGYOS_IDP_CLIENT_SECRET=",
        "STRATEGYOS_IDP_OPERATOR_PASSWORD=",
        "STRATEGYOS_IDP_REVIEWER_PASSWORD=",
        "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEY=",
        "STRATEGYOS_TRUSTED_PROXY_AUTH_SECRET=",
        "OAUTH2_PROXY_CLIENT_SECRET=",
        "OAUTH2_PROXY_COOKIE_SECRET=",
        "STRATEGYOS_LLM_API_KEY=",
    ]:
        assert secret_key not in env_example


def test_generate_env_splits_config_from_secrets(tmp_path: Path) -> None:
    config_path = tmp_path / ".env"
    secrets_path = tmp_path / ".env.secrets"
    env = os.environ.copy()
    env.update(
        {
            "SECRETS_FILE": str(secrets_path),
            "CONFIG_TEMPLATE": str(REPO_ROOT / "deploy/.env.example"),
            "SECRETS_TEMPLATE": str(REPO_ROOT / "deploy/.env.secrets.example"),
        }
    )

    result = subprocess.run(
        ["bash", "deploy/scripts/generate_env.sh", str(config_path)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    config_contents = config_path.read_text(encoding="utf-8")
    secrets_contents = secrets_path.read_text(encoding="utf-8")

    assert "STRATEGYOS_IDP_CLIENT_SECRET=" not in config_contents
    assert "STRATEGYOS_LLM_API_KEY=" not in config_contents
    assert "POSTGRES_PASSWORD=" not in config_contents
    assert "STRATEGYOS_LLM_API_KEY=" in secrets_contents
    assert "Review non-secret config separately from injected secrets" in result.stdout
    assert "__CHANGE_ME_" not in secrets_contents

    for key in [
        "POSTGRES_PASSWORD",
        "NEO4J_PASSWORD",
        "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY",
        "MINIO_ROOT_PASSWORD",
        "STRATEGYOS_IDP_CLIENT_SECRET",
        "STRATEGYOS_IDP_OPERATOR_PASSWORD",
        "STRATEGYOS_IDP_REVIEWER_PASSWORD",
        "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEY",
        "STRATEGYOS_TRUSTED_PROXY_AUTH_SECRET",
        "OAUTH2_PROXY_CLIENT_SECRET",
        "OAUTH2_PROXY_COOKIE_SECRET",
    ]:
        match = re.search(rf"^{key}=([a-f0-9]{{48}})$", secrets_contents, re.MULTILINE)
        assert match, key


def test_deploy_rsync_uses_ssh_options_for_ci_deploy_key() -> None:
    script = (REPO_ROOT / "deploy/scripts/deploy_stack.sh").read_text(encoding="utf-8")
    assert 'RSYNC_SSH_ARGS=(-e "ssh ${SSH_OPTS}")' in script
    assert 'rsync -az --delete "${RSYNC_SSH_ARGS[@]}"' in script
    assert 'rsync -az "${RSYNC_SSH_ARGS[@]}" "${LOCAL_ENV}"' in script


def test_deploy_release_image_path_does_not_build_on_server() -> None:
    script = (REPO_ROOT / "deploy/scripts/deploy_stack.sh").read_text(encoding="utf-8")
    assert 'if [ -n "${STRATEGYOS_API_IMAGE:-}" ]; then' in script
    assert '"docker pull \'${STRATEGYOS_API_IMAGE}\'"' in script
    assert "up -d --no-build" in script


def test_deploy_reloads_caddy_after_bind_mounted_config_changes() -> None:
    script = (REPO_ROOT / "deploy/scripts/deploy_stack.sh").read_text(encoding="utf-8")
    assert "up -d --no-deps caddy" in script
    assert "--force-recreate caddy" not in script
    assert "exec -T caddy caddy reload --config /etc/caddy/Caddyfile" in script


def test_deploy_scripts_forward_compose_profiles() -> None:
    deploy_script = (REPO_ROOT / "deploy/scripts/deploy_stack.sh").read_text(
        encoding="utf-8"
    )
    rollback_script = (REPO_ROOT / "deploy/scripts/rollback_stack.sh").read_text(
        encoding="utf-8"
    )
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert 'COMPOSE_PROFILES="${COMPOSE_PROFILES:-}"' in deploy_script
    assert 'COMPOSE_PROFILE_ARGS="${COMPOSE_PROFILE_ARGS} --profile ${compose_profile}"' in deploy_script
    assert 'COMPOSE_PROFILES="${COMPOSE_PROFILES:-}"' in rollback_script
    assert "STRATEGYOS_COMPOSE_PROFILES" in workflow
    assert 'COMPOSE_PROFILES="${STRATEGYOS_COMPOSE_PROFILES:-}" \\' in workflow


def test_rollback_forwards_compose_project_name() -> None:
    script = (REPO_ROOT / "deploy/scripts/rollback_stack.sh").read_text(
        encoding="utf-8"
    )
    assert 'COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"' in script
    assert 'PROJECT_NAME_ARG=" --project-name ${COMPOSE_PROJECT_NAME}"' in script
    assert "${COMPOSE_PROFILE_ARGS}${PROJECT_NAME_ARG}" in script


def test_branch_deploy_normalizes_hatchet_profile_for_execution_mode() -> None:
    workflow = (
        REPO_ROOT / ".github/workflows/strategyos-branch-deploy.yml"
    ).read_text(encoding="utf-8")
    assert "- name: Normalize compose profiles for execution mode" in workflow
    assert (
        'if [ "${profile}" = "hatchet" ] && '
        '[ "${STRATEGYOS_RUN_EXECUTION_MODE}" != "hatchet" ]; then'
        in workflow
    )
    assert 'echo "STRATEGYOS_COMPOSE_PROFILES=${normalized_profiles}"' in workflow
    assert (
        'if [ "${STRATEGYOS_RUN_EXECUTION_MODE}" != "hatchet" ]; then'
        in workflow
    )
    assert "--profile '*' --project-name strategyos-branch" in workflow
    assert (
        'if [ "${STRATEGYOS_RUN_EXECUTION_MODE}" = "hatchet" ]; then'
        in workflow
    )


def test_branch_deploy_probes_the_public_url_when_configured() -> None:
    workflow = (
        REPO_ROOT / ".github/workflows/strategyos-branch-deploy.yml"
    ).read_text(encoding="utf-8")
    assert "STRATEGYOS_PROBE_URL: ${{ vars.STRATEGYOS_PROBE_URL || '' }}" in workflow
    assert "HETZNER_HOST: ${{ vars.HETZNER_HOST }}" in workflow
    assert "STRATEGYOS_SITE_ADDRESS: ':80'" in workflow
    assert 'probe_url="${STRATEGYOS_PUBLIC_URL}"' in workflow
    assert 'probe_url="http://${HETZNER_HOST}:${STRATEGYOS_HTTP_PORT}"' in workflow
    assert workflow.count('TARGET_URL="${STRATEGYOS_PROBE_URL}"') >= 4
    assert workflow.count('--base-url "${STRATEGYOS_PROBE_URL}"') == 2
    branch_compose = (REPO_ROOT / "deploy/docker-compose.branch.yml").read_text(
        encoding="utf-8"
    )
    assert "STRATEGYOS_SITE_ADDRESS: ${STRATEGYOS_SITE_ADDRESS:-:80}" in branch_compose
    assert "Caddyfile.branch:/etc/caddy/Caddyfile:ro" in branch_compose
    branch_caddyfile = (REPO_ROOT / "deploy/caddy/Caddyfile.branch").read_text(
        encoding="utf-8"
    )
    assert branch_caddyfile.startswith("{$STRATEGYOS_SITE_ADDRESS} {")
    assert "new.strategyos.live" not in branch_caddyfile
    assert "reverse_proxy strategyos-api:8000" in branch_caddyfile
    assert "reverse_proxy @idp strategyos-idp:9000" in branch_caddyfile


def test_compose_passes_runtime_backend_to_api_and_worker() -> None:
    compose = (REPO_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    assert compose.count(
        "STRATEGYOS_RUNTIME_BACKEND: ${STRATEGYOS_RUNTIME_BACKEND:-langgraph}"
    ) == 2
    assert "STRATEGYOS_PUBLIC_HEALTH_ENABLED: ${STRATEGYOS_PUBLIC_HEALTH_ENABLED:-false}" in compose


def test_release_rollback_does_not_build_on_server() -> None:
    script = (REPO_ROOT / "deploy/scripts/rollback_stack.sh").read_text(
        encoding="utf-8"
    )
    assert "grep -Eq '^STRATEGYOS_API_IMAGE=.' deploy/.env" in script
    assert "up -d --no-build" in script


def test_deploy_workflow_checks_public_readiness_after_domain_cutover() -> None:
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert 'TARGET_URL="${STRATEGYOS_PUBLIC_URL}" \\' in workflow
    assert 'READINESS_AUTH_HEADER="Authorization: Bearer ${token}" \\' in workflow
    assert 'RUN_AUTH_HEADER="Authorization: Bearer ${token}" \\' in workflow
    assert "- name: Validate public edge headers" in workflow
    assert 'bash deploy/scripts/validate_public_edge.sh' in workflow


def test_deploy_workflow_verifies_external_governed_surface_with_both_roles() -> None:
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert "- name: Verify governed cloud surface" in workflow
    assert 'ROLE=operator bash deploy/scripts/remote_idp_token.sh' in workflow
    assert 'ROLE=reviewer bash deploy/scripts/remote_idp_token.sh' in workflow
    assert 'python deploy/scripts/verify_cloud_surface.py \\' in workflow
    assert '--operator-auth-header "Authorization: Bearer ${operator_token}" \\' in workflow
    assert '--reviewer-auth-header "Authorization: Bearer ${reviewer_token}"' in workflow


def test_deploy_workflow_runs_boundary_validation() -> None:
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert "- name: Validate deploy boundary" in workflow
    assert 'TARGET_ENVIRONMENT: ${{ inputs.target_environment }}' in workflow
    assert 'TARGET_DEPLOY_USER: ${{ vars.HETZNER_USER }}' in workflow
    assert "bash deploy/scripts/validate_deploy_boundary.sh" in workflow


def test_deploy_workflow_only_exposes_configured_live_environment() -> None:
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert "default: hetzner-qa" in workflow
    assert "- hetzner-qa" in workflow
    assert "- production" not in workflow


def test_deploy_workflow_pins_hosted_governance_flags() -> None:
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED: 'false'" in workflow
    assert "STRATEGYOS_REQUIRE_HUMAN_REVIEW: 'true'" in workflow
    assert (
        '"STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": '
        'os.environ["STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED"]'
        in workflow
    )
    assert (
        '"STRATEGYOS_REQUIRE_HUMAN_REVIEW": '
        'os.environ["STRATEGYOS_REQUIRE_HUMAN_REVIEW"]'
        in workflow
    )


def test_deploy_workflow_derives_hosted_idp_issuer_from_public_url() -> None:
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert (
        "STRATEGYOS_IDP_ISSUER: ${{ vars.STRATEGYOS_IDP_ISSUER || vars.STRATEGYOS_PUBLIC_URL }}"
        in workflow
    )
    assert "http://localhost:8089" not in workflow.split("STRATEGYOS_IDP_ISSUER:", 1)[1].splitlines()[0]


def test_deploy_workflow_pins_hosted_tenant_and_identity_labels() -> None:
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert "STRATEGYOS_TENANT_SLUG: ${{ vars.STRATEGYOS_TENANT_SLUG || 'strategyos-live' }}" in workflow
    assert "STRATEGYOS_TENANT_NAME: ${{ vars.STRATEGYOS_TENANT_NAME || 'StrategyOS Live' }}" in workflow
    assert "STRATEGYOS_IDP_OPERATOR_USERNAME: ${{ vars.STRATEGYOS_IDP_OPERATOR_USERNAME || 'operator.hosted' }}" in workflow
    assert "STRATEGYOS_IDP_REVIEWER_USERNAME: ${{ vars.STRATEGYOS_IDP_REVIEWER_USERNAME || 'reviewer.hosted' }}" in workflow
    assert "STRATEGYOS_IDP_TEST_USERS: ${{ secrets.STRATEGYOS_IDP_TEST_USERS }}" in workflow
    assert 'upsert("STRATEGYOS_IDP_TEST_USERS", os.environ.get("STRATEGYOS_IDP_TEST_USERS", ""))' in workflow
    assert '"STRATEGYOS_TENANT_SLUG": os.environ["STRATEGYOS_TENANT_SLUG"]' in workflow
    assert '"STRATEGYOS_TENANT_NAME": os.environ["STRATEGYOS_TENANT_NAME"]' in workflow
    assert '"STRATEGYOS_IDP_OPERATOR_USERNAME": os.environ["STRATEGYOS_IDP_OPERATOR_USERNAME"]' in workflow
    assert '"STRATEGYOS_IDP_REVIEWER_USERNAME": os.environ["STRATEGYOS_IDP_REVIEWER_USERNAME"]' in workflow


def test_deploy_workflow_renders_environment_label() -> None:
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    compose = (REPO_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    assert "STRATEGYOS_ENVIRONMENT_LABEL" in workflow
    assert '"STRATEGYOS_ENVIRONMENT_LABEL": os.environ["STRATEGYOS_ENVIRONMENT_LABEL"]' in workflow
    assert (
        "STRATEGYOS_ENVIRONMENT_LABEL: ${STRATEGYOS_ENVIRONMENT_LABEL:-Local development}"
        in compose
    )


def test_deploy_workflow_renders_proxy_oidc_boundary_flags() -> None:
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert "STRATEGYOS_AUTH_MODE" in workflow
    assert "STRATEGYOS_TRUST_PROXY_AUTH" in workflow
    assert "STRATEGYOS_OPERATOR_EMAILS" in workflow
    assert "STRATEGYOS_REVIEWER_EMAILS" in workflow
    assert "OAUTH2_PROXY_OIDC_ISSUER_URL" in workflow
    assert "OAUTH2_PROXY_CLIENT_ID" in workflow
    assert "OAUTH2_PROXY_REDIRECT_URL" in workflow
    assert "STRATEGYOS_READINESS_AUTH_HEADER" in workflow
    assert "STRATEGYOS_RUN_AUTH_HEADER" in workflow


def test_deploy_workflow_renders_runtime_and_hatchet_flags() -> None:
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert (
        "STRATEGYOS_RUNTIME_BACKEND: "
        "${{ vars.STRATEGYOS_RUNTIME_BACKEND || 'langgraph' }}"
        in workflow
    )
    assert (
        "STRATEGYOS_RUN_POLICY: "
        "${{ vars.STRATEGYOS_RUN_POLICY || 'sovereign' }}"
        in workflow
    )
    assert (
        '"STRATEGYOS_RUNTIME_BACKEND": os.environ["STRATEGYOS_RUNTIME_BACKEND"]'
        in workflow
    )
    assert (
        '"STRATEGYOS_RUN_EXECUTION_MODE": '
        'os.environ["STRATEGYOS_RUN_EXECUTION_MODE"]'
        in workflow
    )


def test_deploy_workflow_renders_twin_rollout_flags() -> None:
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    compose = (REPO_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    assert "STRATEGYOS_TWINS_ENABLED" in workflow
    assert "STRATEGYOS_TWINS_MUTATIONS_ENABLED" in workflow
    assert "STRATEGYOS_TWINS_SCHEDULER_ENABLED" in workflow
    assert '"STRATEGYOS_TWINS_ENABLED": os.environ["STRATEGYOS_TWINS_ENABLED"]' in workflow
    assert '"STRATEGYOS_TWINS_MUTATIONS_ENABLED": os.environ["STRATEGYOS_TWINS_MUTATIONS_ENABLED"]' in workflow
    assert '"STRATEGYOS_TWINS_SCHEDULER_ENABLED": os.environ["STRATEGYOS_TWINS_SCHEDULER_ENABLED"]' in workflow
    assert "STRATEGYOS_TWINS_ENABLED: ${STRATEGYOS_TWINS_ENABLED:-true}" in compose
    assert "STRATEGYOS_TWINS_MUTATIONS_ENABLED: ${STRATEGYOS_TWINS_MUTATIONS_ENABLED:-true}" in compose
    assert "STRATEGYOS_TWINS_SCHEDULER_ENABLED: ${STRATEGYOS_TWINS_SCHEDULER_ENABLED:-true}" in compose


def test_deploy_workflow_renders_llm_chat_config_without_committed_secret() -> None:
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    compose = (REPO_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    assert "STRATEGYOS_MODEL_PROVIDER_ENABLED" in workflow
    assert "STRATEGYOS_LLM_CHAT_ENABLED" in workflow
    assert "STRATEGYOS_LLM_MODEL" in workflow
    assert "deepseek-v4-pro" in workflow
    assert "https://api.deepseek.com" in workflow
    assert "STRATEGYOS_LLM_MODEL: ${STRATEGYOS_LLM_MODEL:-deepseek-v4-pro}" in compose
    assert "STRATEGYOS_LLM_API_KEY: ${{ secrets.STRATEGYOS_LLM_API_KEY }}" in workflow
    assert "STRATEGYOS_LLM_API_KEY: ${STRATEGYOS_LLM_API_KEY:-}" in compose


def test_remote_smoke_run_forwards_auth_header() -> None:
    script = (REPO_ROOT / "deploy/scripts/run_remote_workflow.sh").read_text(
        encoding="utf-8"
    )
    assert 'RUN_AUTH_HEADER="${RUN_AUTH_HEADER:-}"' in script
    assert 'RUN_PAYLOAD="${RUN_PAYLOAD:-}"' in script
    assert 'curl -fsS -X POST "${base_url}/runs" -H "${RUN_AUTH_HEADER}"' in script
    assert "run_id=\"$(printf '%s' \"${response}\" | json_field run_id || true)\"" in script
    assert 'case "${run_status}:${current_stage}" in' in script
    assert 'awaiting_review:*|*:awaiting_review)' in script


def test_protected_readiness_script_retries_transient_failures() -> None:
    script = (REPO_ROOT / "deploy/scripts/check_health.sh").read_text(
        encoding="utf-8"
    )
    assert 'READINESS_MAX_ATTEMPTS="${READINESS_MAX_ATTEMPTS:-30}"' in script
    assert 'READINESS_WAIT_SECONDS="${READINESS_WAIT_SECONDS:-2}"' in script
    assert 'while [ "${attempt}" -le "${READINESS_MAX_ATTEMPTS}" ]; do' in script
    assert 'Readiness attempt ${attempt}/${READINESS_MAX_ATTEMPTS} returned HTTP ${http_status}.' in script


def test_compose_healthcheck_uses_protected_ready_endpoint() -> None:
    compose = (REPO_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    assert "/health/ready" in compose
    strategyos_api_block = compose.split("strategyos-api:", 1)[1].split(
        "strategyos-worker:", 1
    )[0]
    assert "/health/dependencies" not in strategyos_api_block


def test_remote_deploy_waits_for_container_health_before_returning() -> None:
    script = (REPO_ROOT / "deploy/scripts/deploy_stack.sh").read_text(
        encoding="utf-8"
    )
    assert 'COMPOSE_WAIT_TIMEOUT_SECONDS="${COMPOSE_WAIT_TIMEOUT_SECONDS:-180}"' in script
    assert '--wait --wait-timeout' in script


def test_caddy_sets_basic_security_headers() -> None:
    caddyfile = (REPO_ROOT / "deploy/caddy/Caddyfile").read_text(encoding="utf-8")
    assert 'Strict-Transport-Security "max-age=31536000; includeSubDomains"' in caddyfile
    assert 'X-Content-Type-Options "nosniff"' in caddyfile
    assert 'X-Frame-Options "DENY"' in caddyfile
    assert 'Referrer-Policy "strict-origin-when-cross-origin"' in caddyfile
    assert 'Content-Security-Policy' in caddyfile
    assert 'frame-src https://www.youtube-nocookie.com https://www.youtube.com' in caddyfile
    assert "-Server" in caddyfile
    assert "header_down -Server" in caddyfile
    assert "@idp path /.well-known/openid-configuration /oauth/*" in caddyfile
    assert "reverse_proxy @idp strategyos-idp:9000" in caddyfile


def test_proxy_oidc_overlay_mounts_alternate_caddy_and_oauth2_proxy() -> None:
    compose = (REPO_ROOT / "deploy/docker-compose.proxy-oidc.yml").read_text(
        encoding="utf-8"
    )
    caddyfile = (REPO_ROOT / "deploy/caddy/Caddyfile.proxy-oidc").read_text(
        encoding="utf-8"
    )
    assert "oauth2-proxy:" in compose
    assert "Caddyfile.proxy-oidc" in compose
    assert "forward_auth @protected oauth2-proxy:4180" in caddyfile
    assert "X-StrategyOS-Proxy-Auth" in caddyfile
    assert 'Strict-Transport-Security "max-age=31536000; includeSubDomains"' in caddyfile


def test_public_edge_validation_script_checks_header_contract() -> None:
    script = (REPO_ROOT / "deploy/scripts/validate_public_edge.sh").read_text(
        encoding="utf-8"
    )
    assert 'x-content-type-options' in script
    assert 'x-frame-options' in script
    assert 'referrer-policy' in script
    assert 'permissions-policy' in script
    assert 'strict-transport-security' in script
    assert 'Server header should be stripped at the public edge' in script


def test_deploy_workflow_derives_https_site_address_from_public_url() -> None:
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert 'from urllib.parse import urlparse' in workflow
    assert 'site_address in {"", ":80"}' in workflow
    assert 'parsed_public_url.scheme == "https"' in workflow
    assert 'overrides["STRATEGYOS_SITE_ADDRESS"]' in workflow


def test_validate_deploy_boundary_rejects_insecure_production_flags(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    secrets_path = tmp_path / ".env.secrets"
    env_path.write_text(
        "\n".join(
            [
                "STRATEGYOS_API_AUTH_ENABLED=true",
                "STRATEGYOS_REQUIRE_HUMAN_REVIEW=true",
                "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED=false",
                "STRATEGYOS_PUBLIC_HEALTH_ENABLED=true",
                "STRATEGYOS_IDP_ENABLED=true",
                "STRATEGYOS_IDP_ISSUER=http://localhost:8089",
                "STRATEGYOS_SITE_ADDRESS=:80",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    secrets_path.write_text(
        "\n".join(
            [
                "POSTGRES_PASSWORD=" + "a" * 48,
                "NEO4J_PASSWORD=" + "b" * 48,
                "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY=" + "c" * 48,
                "MINIO_ROOT_PASSWORD=" + "d" * 48,
                "STRATEGYOS_IDP_CLIENT_SECRET=" + "e" * 48,
                "STRATEGYOS_IDP_OPERATOR_PASSWORD=" + "f" * 48,
                "STRATEGYOS_IDP_REVIEWER_PASSWORD=" + "1" * 48,
                "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEY=" + "2" * 48,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "deploy/scripts/validate_deploy_boundary.sh"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "ENV_FILE": str(env_path),
            "SECRETS_FILE": str(secrets_path),
            "TARGET_ENVIRONMENT": "production",
            "TARGET_PUBLIC_URL": "http://strategyos.example.test",
            "TARGET_DEPLOY_USER": "root",
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "BOUNDARY VALIDATION FAILED" in result.stderr
    assert "https://" in result.stderr
    assert "non-root deploy user" in result.stderr


def test_validate_deploy_boundary_allows_hardened_qa_config(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    secrets_path = tmp_path / ".env.secrets"
    env_path.write_text(
        "\n".join(
            [
                "STRATEGYOS_API_AUTH_ENABLED=true",
                "STRATEGYOS_REQUIRE_HUMAN_REVIEW=true",
                "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED=false",
                "STRATEGYOS_PUBLIC_HEALTH_ENABLED=false",
                "STRATEGYOS_IDP_ENABLED=true",
                "STRATEGYOS_IDP_ISSUER=https://strategyos-qa.example.test",
                "STRATEGYOS_TENANT_SLUG=strategyos-qa",
                "STRATEGYOS_TENANT_NAME=StrategyOS QA",
                "STRATEGYOS_IDP_OPERATOR_USERNAME=operator.hosted",
                "STRATEGYOS_IDP_REVIEWER_USERNAME=reviewer.hosted",
                "STRATEGYOS_ENVIRONMENT_LABEL=hetzner-qa",
                "STRATEGYOS_SITE_ADDRESS=:80",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    secrets_path.write_text(
        "\n".join(
            [
                "POSTGRES_PASSWORD=" + "a" * 48,
                "NEO4J_PASSWORD=" + "b" * 48,
                "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY=" + "c" * 48,
                "MINIO_ROOT_PASSWORD=" + "d" * 48,
                "STRATEGYOS_IDP_CLIENT_SECRET=" + "e" * 48,
                "STRATEGYOS_IDP_OPERATOR_PASSWORD=" + "f" * 48,
                "STRATEGYOS_IDP_REVIEWER_PASSWORD=" + "1" * 48,
                "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEY=" + "2" * 48,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "deploy/scripts/validate_deploy_boundary.sh"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "ENV_FILE": str(env_path),
            "SECRETS_FILE": str(secrets_path),
            "TARGET_ENVIRONMENT": "hetzner-qa",
            "TARGET_PUBLIC_URL": "http://strategyos-qa.example.test",
            "TARGET_DEPLOY_USER": "deployer",
        },
        capture_output=True,
        text=True,
        check=True,
    )

    assert "Deploy boundary validation passed." in result.stdout


def test_validate_deploy_boundary_rejects_incomplete_proxy_oidc_config(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    secrets_path = tmp_path / ".env.secrets"
    env_path.write_text(
        "\n".join(
            [
                "STRATEGYOS_API_AUTH_ENABLED=true",
                "STRATEGYOS_AUTH_MODE=proxy_oidc",
                "STRATEGYOS_TRUST_PROXY_AUTH=false",
                "STRATEGYOS_REQUIRE_HUMAN_REVIEW=true",
                "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED=false",
                "STRATEGYOS_PUBLIC_HEALTH_ENABLED=false",
                "STRATEGYOS_OPERATOR_EMAILS=",
                "STRATEGYOS_REVIEWER_EMAILS=",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    secrets_path.write_text(
        "\n".join(
            [
                "POSTGRES_PASSWORD=" + "a" * 48,
                "NEO4J_PASSWORD=" + "b" * 48,
                "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY=" + "c" * 48,
                "MINIO_ROOT_PASSWORD=" + "d" * 48,
                "STRATEGYOS_IDP_CLIENT_SECRET=" + "e" * 48,
                "STRATEGYOS_IDP_OPERATOR_PASSWORD=" + "f" * 48,
                "STRATEGYOS_IDP_REVIEWER_PASSWORD=" + "1" * 48,
                "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEY=" + "2" * 48,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "deploy/scripts/validate_deploy_boundary.sh"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "ENV_FILE": str(env_path),
            "SECRETS_FILE": str(secrets_path),
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "proxy_oidc requires STRATEGYOS_TRUST_PROXY_AUTH=true" in result.stderr


def test_validate_deploy_boundary_uses_default_env_file_paths(tmp_path: Path) -> None:
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir()
    (deploy_dir / ".env").write_text(
        "\n".join(
            [
                "STRATEGYOS_API_AUTH_ENABLED=true",
                "STRATEGYOS_REQUIRE_HUMAN_REVIEW=true",
                "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED=false",
                "STRATEGYOS_PUBLIC_HEALTH_ENABLED=false",
                "STRATEGYOS_IDP_ENABLED=true",
                "STRATEGYOS_IDP_ISSUER=http://localhost:8089",
                "STRATEGYOS_SITE_ADDRESS=:80",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (deploy_dir / ".env.secrets").write_text(
        "\n".join(
            [
                "POSTGRES_PASSWORD=" + "a" * 48,
                "NEO4J_PASSWORD=" + "b" * 48,
                "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY=" + "c" * 48,
                "MINIO_ROOT_PASSWORD=" + "d" * 48,
                "STRATEGYOS_IDP_CLIENT_SECRET=" + "e" * 48,
                "STRATEGYOS_IDP_OPERATOR_PASSWORD=" + "f" * 48,
                "STRATEGYOS_IDP_REVIEWER_PASSWORD=" + "1" * 48,
                "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEY=" + "2" * 48,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    for key in [
        "ENV_FILE",
        "SECRETS_FILE",
        "TARGET_ENVIRONMENT",
        "TARGET_PUBLIC_URL",
        "TARGET_DEPLOY_USER",
        "STRATEGYOS_PUBLIC_URL",
        "HETZNER_USER",
    ]:
        env.pop(key, None)

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "deploy/scripts/validate_deploy_boundary.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "Deploy boundary validation passed." in result.stdout


def test_validate_deploy_boundary_rejects_hatchet_mode_without_runtime_secrets(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    secrets_path = tmp_path / ".env.secrets"
    env_path.write_text(
        "\n".join(
            [
                "STRATEGYOS_API_AUTH_ENABLED=true",
                "STRATEGYOS_REQUIRE_HUMAN_REVIEW=true",
                "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED=false",
                "STRATEGYOS_PUBLIC_HEALTH_ENABLED=false",
                "STRATEGYOS_IDP_ENABLED=true",
                "STRATEGYOS_IDP_ISSUER=http://localhost:8089",
                "STRATEGYOS_RUN_EXECUTION_MODE=hatchet",
                "STRATEGYOS_SITE_ADDRESS=:80",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    secrets_path.write_text(
        "\n".join(
            [
                "POSTGRES_PASSWORD=" + "a" * 48,
                "NEO4J_PASSWORD=" + "b" * 48,
                "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY=" + "c" * 48,
                "MINIO_ROOT_PASSWORD=" + "d" * 48,
                "STRATEGYOS_IDP_CLIENT_SECRET=" + "e" * 48,
                "STRATEGYOS_IDP_OPERATOR_PASSWORD=" + "f" * 48,
                "STRATEGYOS_IDP_REVIEWER_PASSWORD=" + "1" * 48,
                "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEY=" + "2" * 48,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "deploy/scripts/validate_deploy_boundary.sh"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "ENV_FILE": str(env_path),
            "SECRETS_FILE": str(secrets_path),
            "TARGET_ENVIRONMENT": "hetzner-qa",
            "TARGET_PUBLIC_URL": "https://strategyos-qa.example.test",
            "TARGET_DEPLOY_USER": "deployer",
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "HATCHET_POSTGRES_PASSWORD" in result.stderr
    assert "HATCHET_CLIENT_TOKEN" in result.stderr


def test_validate_deploy_boundary_rejects_llm_chat_without_external_approval(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    secrets_path = tmp_path / ".env.secrets"
    env_path.write_text(
        "\n".join(
            [
                "STRATEGYOS_API_AUTH_ENABLED=true",
                "STRATEGYOS_REQUIRE_HUMAN_REVIEW=true",
                "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED=false",
                "STRATEGYOS_PUBLIC_HEALTH_ENABLED=false",
                "STRATEGYOS_IDP_ENABLED=true",
                "STRATEGYOS_IDP_ISSUER=http://localhost:8089",
                "STRATEGYOS_LLM_CHAT_ENABLED=true",
                "STRATEGYOS_MODEL_PROVIDER_ENABLED=true",
                "STRATEGYOS_RUN_POLICY=sovereign",
                "STRATEGYOS_SITE_ADDRESS=:80",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    secrets_path.write_text(
        "\n".join(
            [
                "POSTGRES_PASSWORD=" + "a" * 48,
                "NEO4J_PASSWORD=" + "b" * 48,
                "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY=" + "c" * 48,
                "MINIO_ROOT_PASSWORD=" + "d" * 48,
                "STRATEGYOS_IDP_CLIENT_SECRET=" + "e" * 48,
                "STRATEGYOS_IDP_OPERATOR_PASSWORD=" + "f" * 48,
                "STRATEGYOS_IDP_REVIEWER_PASSWORD=" + "1" * 48,
                "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEY=" + "2" * 48,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "deploy/scripts/validate_deploy_boundary.sh"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "ENV_FILE": str(env_path),
            "SECRETS_FILE": str(secrets_path),
            "TARGET_ENVIRONMENT": "hetzner-qa",
            "TARGET_PUBLIC_URL": "https://strategyos-qa.example.test",
            "TARGET_DEPLOY_USER": "deployer",
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "external-approved" in result.stderr
    assert "model_provider_use" in result.stderr
    assert "STRATEGYOS_LLM_API_KEY" in result.stderr


def test_validate_deploy_boundary_rejects_production_identity_over_http(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    secrets_path = tmp_path / ".env.secrets"
    env_path.write_text(
        "\n".join(
            [
                "STRATEGYOS_API_AUTH_ENABLED=true",
                "STRATEGYOS_REQUIRE_HUMAN_REVIEW=true",
                "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED=false",
                "STRATEGYOS_PUBLIC_HEALTH_ENABLED=false",
                "STRATEGYOS_IDP_ENABLED=true",
                "STRATEGYOS_IDP_ISSUER=http://idp.strategyos.example.test",
                "STRATEGYOS_SITE_ADDRESS=strategyos.example.test",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    secrets_path.write_text(
        "\n".join(
            [
                "POSTGRES_PASSWORD=" + "a" * 48,
                "NEO4J_PASSWORD=" + "b" * 48,
                "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY=" + "c" * 48,
                "MINIO_ROOT_PASSWORD=" + "d" * 48,
                "STRATEGYOS_IDP_CLIENT_SECRET=" + "e" * 48,
                "STRATEGYOS_IDP_OPERATOR_PASSWORD=" + "f" * 48,
                "STRATEGYOS_IDP_REVIEWER_PASSWORD=" + "1" * 48,
                "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEY=" + "2" * 48,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "deploy/scripts/validate_deploy_boundary.sh"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "ENV_FILE": str(env_path),
            "SECRETS_FILE": str(secrets_path),
            "TARGET_ENVIRONMENT": "production",
            "TARGET_PUBLIC_URL": "https://strategyos.example.test",
            "TARGET_DEPLOY_USER": "deployer",
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "identity issuer" in result.stderr
    assert "https://" in result.stderr


def test_validate_deploy_boundary_rejects_localish_environment_label_for_hosted_target(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    secrets_path = tmp_path / ".env.secrets"
    env_path.write_text(
        "\n".join(
            [
                "STRATEGYOS_API_AUTH_ENABLED=true",
                "STRATEGYOS_REQUIRE_HUMAN_REVIEW=true",
                "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED=false",
                "STRATEGYOS_PUBLIC_HEALTH_ENABLED=false",
                "STRATEGYOS_IDP_ENABLED=true",
                "STRATEGYOS_IDP_ISSUER=http://localhost:8089",
                "STRATEGYOS_SITE_ADDRESS=:80",
                "STRATEGYOS_ENVIRONMENT_LABEL=Local broader-testing",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    secrets_path.write_text(
        "\n".join(
            [
                "POSTGRES_PASSWORD=" + "a" * 48,
                "NEO4J_PASSWORD=" + "b" * 48,
                "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY=" + "c" * 48,
                "MINIO_ROOT_PASSWORD=" + "d" * 48,
                "STRATEGYOS_IDP_CLIENT_SECRET=" + "e" * 48,
                "STRATEGYOS_IDP_OPERATOR_PASSWORD=" + "f" * 48,
                "STRATEGYOS_IDP_REVIEWER_PASSWORD=" + "1" * 48,
                "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEY=" + "2" * 48,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "deploy/scripts/validate_deploy_boundary.sh"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "ENV_FILE": str(env_path),
            "SECRETS_FILE": str(secrets_path),
            "TARGET_ENVIRONMENT": "hetzner-qa",
            "TARGET_PUBLIC_URL": "https://strategyos.live",
            "TARGET_DEPLOY_USER": "deployer",
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "STRATEGYOS_ENVIRONMENT_LABEL" in result.stderr


def test_validate_deploy_boundary_rejects_local_identity_and_tenant_values_for_hosted_target(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    secrets_path = tmp_path / ".env.secrets"
    env_path.write_text(
        "\n".join(
            [
                "STRATEGYOS_API_AUTH_ENABLED=true",
                "STRATEGYOS_REQUIRE_HUMAN_REVIEW=true",
                "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED=false",
                "STRATEGYOS_PUBLIC_HEALTH_ENABLED=false",
                "STRATEGYOS_AUTH_MODE=identity_provider",
                "STRATEGYOS_IDP_ENABLED=true",
                "STRATEGYOS_IDP_ISSUER=http://localhost:8089",
                "STRATEGYOS_TENANT_SLUG=local-poc",
                "STRATEGYOS_TENANT_NAME=StrategyOS Local POC",
                "STRATEGYOS_IDP_OPERATOR_USERNAME=operator.local",
                "STRATEGYOS_IDP_REVIEWER_USERNAME=reviewer.local",
                "STRATEGYOS_ENVIRONMENT_LABEL=Hosted QA",
                "STRATEGYOS_SITE_ADDRESS=strategyos.live",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    secrets_path.write_text(
        "\n".join(
            [
                "POSTGRES_PASSWORD=" + "a" * 48,
                "NEO4J_PASSWORD=" + "b" * 48,
                "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY=" + "c" * 48,
                "MINIO_ROOT_PASSWORD=" + "d" * 48,
                "STRATEGYOS_IDP_CLIENT_SECRET=" + "e" * 48,
                "STRATEGYOS_IDP_OPERATOR_PASSWORD=" + "f" * 48,
                "STRATEGYOS_IDP_REVIEWER_PASSWORD=" + "1" * 48,
                "STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEY=" + "2" * 48,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "deploy/scripts/validate_deploy_boundary.sh"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "ENV_FILE": str(env_path),
            "SECRETS_FILE": str(secrets_path),
            "TARGET_ENVIRONMENT": "hetzner-qa",
            "TARGET_PUBLIC_URL": "https://strategyos.live",
            "TARGET_DEPLOY_USER": "deployer",
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "identity issuer" in result.stderr
    assert "STRATEGYOS_TENANT_SLUG" in result.stderr
    assert "STRATEGYOS_TENANT_NAME" in result.stderr
    assert "STRATEGYOS_IDP_OPERATOR_USERNAME" in result.stderr
    assert "STRATEGYOS_IDP_REVIEWER_USERNAME" in result.stderr


def test_source_dataset_sync_omits_macos_metadata_files() -> None:
    script = (REPO_ROOT / "deploy/scripts/sync_source_dataset.sh").read_text(
        encoding="utf-8"
    )
    assert 'COPYFILE_DISABLE="${COPYFILE_DISABLE:-1}" tar' in script
    assert '--exclude "._*"' in script
    assert '--exclude ".DS_Store"' in script
    assert "rm -rf /workspace/source_dataset && mkdir -p /workspace/source_dataset" in script
