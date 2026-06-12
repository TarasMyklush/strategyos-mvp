import os
from pathlib import Path

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
import strategyos_mvp.run_poc as run_poc_module
import strategyos_mvp.state_store as state_store
import strategyos_mvp.storage as storage
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
    run_poc_module.CONFIG = config
    state_store.CONFIG = config
    storage.CONFIG = config
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
    run_poc_module.CONFIG = config
    state_store.CONFIG = config
    storage.CONFIG = config


def _auth_header(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def test_run_and_data_endpoints_require_auth(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1"})
        monkeypatch.setattr(
            api_module,
            "data_management_status",
            lambda: {"status": "ok", "run_id": "run-1"},
        )
        monkeypatch.setattr(
            api_module,
            "graph_status_for_run",
            lambda run_id: {"status": "ready", "run_id": run_id},
        )
        monkeypatch.setattr(
            api_module,
            "vector_status_for_run",
            lambda run_id: {"status": "ready", "run_id": run_id},
        )
        monkeypatch.setattr(
            api_module,
            "search_run_vectors",
            lambda run_id, query, limit=5: {"run_id": run_id, "query": query, "limit": limit},
        )
        monkeypatch.setattr(
            api_module,
            "prepare_agent_input",
            lambda: (Path("/tmp/agent_input"), Path("/tmp/evaluation")),
        )

        client = TestClient(api_module.app)

        assert client.get("/runs/latest").status_code == 401
        assert client.get("/data/status").status_code == 401
        assert client.get("/data/vector-search?query=test").status_code == 401
        assert client.post("/inputs/prepare").status_code == 401
        assert client.post("/runs", json={}).status_code == 401

        assert (
            client.get("/runs/latest", headers=_auth_header("reviewer-secret")).status_code
            == 200
        )
        assert (
            client.get("/data/status", headers=_auth_header("reviewer-secret")).status_code
            == 200
        )
        assert (
            client.get(
                "/data/vector-search?query=test",
                headers=_auth_header("reviewer-secret"),
            ).status_code
            == 200
        )
        assert (
            client.post("/inputs/prepare", headers=_auth_header("operator-secret")).status_code
            == 200
        )
    finally:
        _restore_env(original)


def test_demo_role_login_requires_explicit_flag():
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": "false",
            "STRATEGYOS_OPERATOR_API_KEYS": None,
            "STRATEGYOS_REVIEWER_API_KEYS": None,
        }
    )
    try:
        client = TestClient(api_module.app)

        assert client.get("/runs/latest", headers=_auth_header("operator")).status_code == 401
        assert client.get("/runs/latest", headers=_auth_header("reviewer")).status_code == 401
    finally:
        _restore_env(original)


def test_demo_role_login_accepts_literal_operator_and_reviewer(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": None,
            "STRATEGYOS_REVIEWER_API_KEYS": None,
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1"})
        monkeypatch.setattr(
            api_module,
            "prepare_agent_input",
            lambda: (Path("/tmp/agent_input"), Path("/tmp/evaluation")),
        )
        monkeypatch.setattr(api_module, "run_strategyos_workflow", lambda **_: {"status": "ok"})
        client = TestClient(api_module.app)

        operator_session = client.get("/ui/session", headers=_auth_header("operator"))
        reviewer_session = client.get("/ui/session", headers=_auth_header("reviewer"))

        assert operator_session.status_code == 200
        assert operator_session.json()["role"] == "operator"
        assert operator_session.json()["subject"] == "demo-role:operator"
        assert reviewer_session.status_code == 200
        assert reviewer_session.json()["role"] == "reviewer"
        assert client.post("/inputs/prepare", headers=_auth_header("operator")).status_code == 200
        assert client.get("/runs/latest", headers=_auth_header("reviewer")).status_code == 200
        assert client.post("/runs", headers=_auth_header("reviewer"), json={}).status_code == 403
    finally:
        _restore_env(original)


def test_role_gated_endpoints_work_when_api_auth_is_disabled(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1"})
        monkeypatch.setattr(
            api_module,
            "data_management_status",
            lambda: {"status": "ok", "run_id": "run-1"},
        )
        monkeypatch.setattr(
            api_module,
            "graph_status_for_run",
            lambda run_id: {"status": "empty", "run_id": run_id},
        )
        monkeypatch.setattr(
            api_module,
            "vector_status_for_run",
            lambda run_id: {"status": "empty", "run_id": run_id},
        )
        monkeypatch.setattr(
            api_module,
            "run_strategyos_workflow",
            lambda **_: {"status": "ok", "run_id": "run-1"},
        )

        client = TestClient(api_module.app)

        assert client.get("/runs/latest").status_code == 200
        assert client.get("/data/status").status_code == 200
        assert client.post("/runs", json={"sync_artifacts": False}).status_code == 200
    finally:
        _restore_env(original)


def test_create_run_requires_operator_role(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "run_strategyos_workflow", lambda **_: {"status": "ok"})
        client = TestClient(api_module.app)

        response = client.post("/runs", headers=_auth_header("reviewer-secret"), json={})

        assert response.status_code == 403
    finally:
        _restore_env(original)


def test_create_run_rejects_paths_outside_workspace(monkeypatch, tmp_path):
    workspace_root = tmp_path / "workspace"
    output_root = workspace_root / "outputs"
    dataset_root = workspace_root / "source_dataset"
    workspace_root.mkdir()
    output_root.mkdir()
    dataset_root.mkdir()
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_WORKSPACE_ROOT": str(workspace_root),
            "STRATEGYOS_OUTPUT_ROOT": str(output_root),
            "STRATEGYOS_SOURCE_DATASET": str(dataset_root),
            "STRATEGYOS_AGENT_INPUT_DIR": str(workspace_root / "agent_input"),
            "STRATEGYOS_EVALUATION_DIR": str(workspace_root / "evaluation"),
            "STRATEGYOS_RUN_DIR": str(output_root / "latest"),
        }
    )
    try:
        called = {"count": 0}

        def fake_run_strategyos_workflow(**kwargs):
            called["count"] += 1
            return {"status": "ok", "run_dir": str(kwargs["run_dir"])}

        monkeypatch.setattr(api_module, "run_strategyos_workflow", fake_run_strategyos_workflow)
        client = TestClient(api_module.app)

        outside_dataset = tmp_path / "outside-dataset"
        outside_dataset.mkdir()
        response = client.post(
            "/runs",
            headers=_auth_header("operator-secret"),
            json={"dataset": str(outside_dataset), "skip_prepare": True},
        )

        assert response.status_code == 400
        assert "workspace boundary" in response.json()["detail"]
        assert called["count"] == 0

        outside_run_dir = tmp_path / "outside-output"
        response = client.post(
            "/runs",
            headers=_auth_header("operator-secret"),
            json={"run_dir": str(outside_run_dir)},
        )

        assert response.status_code == 400
        assert "output boundary" in response.json()["detail"]
        assert called["count"] == 0

        allowed_run_dir = output_root / "manual-run"
        response = client.post(
            "/runs",
            headers=_auth_header("operator-secret"),
            json={"run_dir": str(allowed_run_dir)},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert called["count"] == 1
    finally:
        _restore_env(original)
