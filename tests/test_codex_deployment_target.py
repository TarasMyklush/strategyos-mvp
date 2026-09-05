"""Deployment selection must be explicit and confined to known stacks."""
import importlib.util
from pathlib import Path
import subprocess
import sys


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
