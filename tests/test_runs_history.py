import json
import os

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
import strategyos_mvp.config as config_module
import strategyos_mvp.run_registry as run_registry
from strategyos_mvp.config import load_config


def _apply_env(env_updates: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in env_updates}
    for key, value in env_updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    api_module.CONFIG = config
    auth_module.CONFIG = config
    config_module.CONFIG = config
    run_registry.CONFIG = config
    return original


def _restore_env(original: dict[str, str | None]):
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    api_module.CONFIG = config
    auth_module.CONFIG = config
    config_module.CONFIG = config
    run_registry.CONFIG = config


def _write_run(root, dir_name, *, recoverable, findings):
    run_dir = root / dir_name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "run_id": dir_name,
                "total_recoverable_sar": recoverable,
                "locked_findings": findings,
            }
        ),
        encoding="utf-8",
    )


def test_discover_run_history_is_chronological_and_skips_untimestamped(tmp_path):
    original = _apply_env({"STRATEGYOS_OUTPUT_ROOT": str(tmp_path)})
    try:
        _write_run(tmp_path, "Run-20260601T100000Z", recoverable=500000, findings=6)
        _write_run(tmp_path, "Run-20260615T100000Z", recoverable=794108, findings=8)
        # Out of order on disk; a non-timestamped dir must be skipped.
        _write_run(tmp_path, "Run-20260608T100000Z", recoverable=650000, findings=7)
        _write_run(tmp_path, "scratch-notes", recoverable=999999, findings=99)

        history = run_registry.discover_run_history(limit=12)

        periods = [row["period"] for row in history]
        assert periods == ["20260601T100000Z", "20260608T100000Z", "20260615T100000Z"]
        assert history[0]["recoverable_sar"] == 500000
        assert history[-1]["recoverable_sar"] == 794108
        assert history[-1]["finding_count"] == 8
        # identified falls back to recoverable when no leakage field present.
        assert history[-1]["identified_sar"] == 794108
    finally:
        _restore_env(original)


def test_discover_run_history_limit_keeps_most_recent(tmp_path):
    original = _apply_env({"STRATEGYOS_OUTPUT_ROOT": str(tmp_path)})
    try:
        for day in range(1, 6):
            _write_run(
                tmp_path,
                f"Run-202606{day:02d}T100000Z",
                recoverable=100000 * day,
                findings=day,
            )

        history = run_registry.discover_run_history(limit=3)

        assert len(history) == 3
        assert [row["period"] for row in history] == [
            "20260603T100000Z",
            "20260604T100000Z",
            "20260605T100000Z",
        ]
    finally:
        _restore_env(original)


def test_runs_history_endpoint_returns_history(tmp_path):
    original = _apply_env(
        {"STRATEGYOS_OUTPUT_ROOT": str(tmp_path), "STRATEGYOS_API_AUTH_ENABLED": "false"}
    )
    try:
        _write_run(tmp_path, "Run-20260601T100000Z", recoverable=500000, findings=6)
        _write_run(tmp_path, "Run-20260615T100000Z", recoverable=794108, findings=8)

        client = TestClient(api_module.app)
        response = client.get("/runs/history")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["count"] == 2
        assert payload["history"][0]["period"] == "20260601T100000Z"
        assert payload["history"][-1]["recoverable_sar"] == 794108
    finally:
        _restore_env(original)


def test_runs_history_endpoint_empty_when_no_runs(tmp_path):
    original = _apply_env(
        {"STRATEGYOS_OUTPUT_ROOT": str(tmp_path), "STRATEGYOS_API_AUTH_ENABLED": "false"}
    )
    try:
        client = TestClient(api_module.app)
        response = client.get("/runs/history")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "empty"
        assert payload["history"] == []
    finally:
        _restore_env(original)


def test_runs_history_endpoint_requires_auth_when_enabled(tmp_path):
    original = _apply_env(
        {
            "STRATEGYOS_OUTPUT_ROOT": str(tmp_path),
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
        }
    )
    try:
        client = TestClient(api_module.app)
        assert client.get("/runs/history").status_code == 401
        ok = client.get("/runs/history", headers={"X-API-Key": "reviewer-secret"})
        assert ok.status_code == 200
    finally:
        _restore_env(original)
