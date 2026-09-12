"""Deployment selection must be explicit and confined to known stacks."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy/scripts/manage_codex_provider.py"


def test_only_known_targets():
    spec = importlib.util.spec_from_file_location("codex_deployment", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.TARGETS == {
        "preview": (Path("/opt/strategyos-branch"), "strategyos-branch"),
        "production": (Path("/opt/strategyos"), "strategyos"),
    }


def test_invalid_target_fails_before_host_access():
    result = subprocess.run([sys.executable, str(SCRIPT), "activate", "--target", "/opt"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_preview_remains_default():
    assert 'choices=tuple(TARGETS), default="preview"' in SCRIPT.read_text()


def test_preview_provider_reuses_governed_runtime_database_credentials(tmp_path):
    spec = importlib.util.spec_from_file_location("codex_deployment_runtime", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = tmp_path / "runtime-database/runtime.env"
    runtime.parent.mkdir()
    runtime.write_text(
        "STRATEGYOS_RUNTIME_DATABASE_URL=postgresql://strategyos_preview_runtime:request@postgres/strategyos\n"
        "STRATEGYOS_WORKER_DATABASE_URL=postgresql://strategyos_preview_worker:worker@postgres/strategyos\n"
        "STRATEGYOS_PROJECTOR_DATABASE_URL=postgresql://strategyos_preview_projector:projector@postgres/strategyos\n"
    )

    assert module.runtime_env_args(tmp_path, "preview") == ["--env-file", str(runtime)]
    with pytest.raises(SystemExit, match="credentials are invalid"):
        module.runtime_env_args(tmp_path, "production")
    runtime.write_text(runtime.read_text().replace("strategyos_preview_", "strategyos_production_"))
    assert module.runtime_env_args(tmp_path, "production") == ["--env-file", str(runtime)]
    with pytest.raises(SystemExit, match="credentials are invalid"):
        module.runtime_env_args(tmp_path, "preview")


def test_preview_provider_rejects_missing_or_unscoped_runtime_database_credentials(tmp_path):
    spec = importlib.util.spec_from_file_location("codex_deployment_invalid_runtime", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(SystemExit, match="credentials are missing"):
        module.runtime_env_args(tmp_path, "preview")

    runtime = tmp_path / "runtime-database/runtime.env"
    runtime.parent.mkdir()
    runtime.write_text("STRATEGYOS_RUNTIME_DATABASE_URL=postgresql://unconfigured@postgres/strategyos\n")
    with pytest.raises(SystemExit, match="credentials are invalid"):
        module.runtime_env_args(tmp_path, "preview")
