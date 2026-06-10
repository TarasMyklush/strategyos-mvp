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
    assert "POSTGRES_PASSWORD=" not in config_contents
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
    ]:
        match = re.search(rf"^{key}=([a-f0-9]{{48}})$", secrets_contents, re.MULTILINE)
        assert match, key
