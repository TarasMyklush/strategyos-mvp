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


def test_deploy_workflow_renders_demo_role_login_flag() -> None:
    workflow = (REPO_ROOT / ".github/workflows/strategyos-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert (
        "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED: "
        "${{ vars.STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED || 'false' }}"
        in workflow
    )
    assert (
        '"STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": '
        'os.environ["STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED"]'
        in workflow
    )


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


def test_compose_healthcheck_uses_protected_ready_endpoint() -> None:
    compose = (REPO_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    assert "/health/ready" in compose
    strategyos_api_block = compose.split("strategyos-api:", 1)[1].split(
        "strategyos-worker:", 1
    )[0]
    assert "/health/dependencies" not in strategyos_api_block


def test_caddy_sets_basic_security_headers() -> None:
    caddyfile = (REPO_ROOT / "deploy/caddy/Caddyfile").read_text(encoding="utf-8")
    assert 'Strict-Transport-Security "max-age=31536000; includeSubDomains"' in caddyfile
    assert 'X-Content-Type-Options "nosniff"' in caddyfile
    assert 'X-Frame-Options "DENY"' in caddyfile
    assert 'Referrer-Policy "no-referrer"' in caddyfile
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
                "STRATEGYOS_IDP_ISSUER=http://localhost:8089",
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


def test_source_dataset_sync_omits_macos_metadata_files() -> None:
    script = (REPO_ROOT / "deploy/scripts/sync_source_dataset.sh").read_text(
        encoding="utf-8"
    )
    assert 'COPYFILE_DISABLE="${COPYFILE_DISABLE:-1}" tar' in script
    assert '--exclude "._*"' in script
    assert '--exclude ".DS_Store"' in script
    assert "rm -rf /workspace/source_dataset && mkdir -p /workspace/source_dataset" in script
