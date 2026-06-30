import os
from pathlib import Path
from unittest.mock import patch

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


def _proxy_auth_headers(email: str, role_secret: str = "proxy-secret") -> dict[str, str]:
    return {
        "X-Auth-Request-Email": email,
        "X-Auth-Request-User": email,
        "X-StrategyOS-Proxy-Auth": role_secret,
    }


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


def test_demo_role_login_accepts_literal_multi_role_tokens(monkeypatch):
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
        bu_session = client.get("/ui/session", headers=_auth_header("bu"))
        analyst_session = client.get("/ui/session", headers=_auth_header("analyst"))
        executive_session = client.get("/ui/session", headers=_auth_header("executive"))

        assert operator_session.status_code == 200
        assert operator_session.json()["role"] == "operator"
        assert operator_session.json()["subject"] == "demo-role:operator"
        assert reviewer_session.status_code == 200
        assert reviewer_session.json()["role"] == "reviewer"
        assert bu_session.status_code == 200
        assert bu_session.json()["role"] == "bu"
        assert analyst_session.status_code == 200
        assert analyst_session.json()["role"] == "analyst"
        assert executive_session.status_code == 200
        assert executive_session.json()["role"] == "executive"
        assert client.post("/inputs/prepare", headers=_auth_header("operator")).status_code == 200
        assert client.get("/runs/latest", headers=_auth_header("reviewer")).status_code == 200
        assert client.get("/runs/latest", headers=_auth_header("executive")).status_code == 200
        assert client.get("/data/vector-search?query=test", headers=_auth_header("analyst")).status_code != 401
        assert client.post("/runs", headers=_auth_header("reviewer"), json={}).status_code == 403
    finally:
        _restore_env(original)


def test_tenant_admin_can_reach_connector_and_runtime_surfaces(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_TENANT_ADMIN_API_KEYS": "tenant-admin-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": None,
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    try:
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
        monkeypatch.setattr(api_module, "readiness_payload", lambda: {"status": "ok"})
        monkeypatch.setattr(
            api_module,
            "_latest_summary",
            lambda: {
                "run_id": "run-1",
                "current_stage": "awaiting_review",
                "approval_status": "approved",
                "artifacts": {"working_capital": "/tmp/Working Capital Memo.md"},
            },
        )

        client = TestClient(api_module.app)

        connectors = client.get(
            "/ingestion/connectors", headers=_auth_header("tenant-admin-secret")
        )
        runtime = client.get("/data/status", headers=_auth_header("tenant-admin-secret"))
        ready = client.get("/health/ready", headers=_auth_header("tenant-admin-secret"))
        live = client.get("/health/live", headers=_auth_header("tenant-admin-secret"))
        report_preview = client.get(
            "/runs/latest/report-preview", headers=_auth_header("tenant-admin-secret")
        )

        assert connectors.status_code == 200
        assert runtime.status_code == 200
        assert ready.status_code == 200
        assert live.status_code == 200
        assert report_preview.status_code == 200
        assert report_preview.json()["publication"]["status"] == "approved_for_release"
    finally:
        _restore_env(original)


def test_proxy_oidc_headers_map_email_allowlists(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_AUTH_MODE": "proxy_oidc",
            "STRATEGYOS_TRUST_PROXY_AUTH": "true",
            "STRATEGYOS_TRUSTED_PROXY_AUTH_SECRET": "proxy-secret",
            "STRATEGYOS_OPERATOR_EMAILS": "operator@example.com",
            "STRATEGYOS_REVIEWER_EMAILS": "reviewer@example.com",
            "STRATEGYOS_TENANT_ADMIN_EMAILS": "admin@example.com",
            "OAUTH2_PROXY_OIDC_ISSUER_URL": "https://accounts.google.com",
            "OAUTH2_PROXY_CLIENT_ID": "client-id",
            "OAUTH2_PROXY_REDIRECT_URL": "https://strategyos.example.com/oauth2/callback",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1"})
        monkeypatch.setattr(
            api_module,
            "prepare_agent_input",
            lambda: (Path("/tmp/agent_input"), Path("/tmp/evaluation")),
        )
        client = TestClient(api_module.app)

        operator = client.post(
            "/inputs/prepare", headers=_proxy_auth_headers("operator@example.com")
        )
        reviewer = client.get("/runs/latest", headers=_proxy_auth_headers("reviewer@example.com"))
        admin = client.get("/data/status", headers=_proxy_auth_headers("admin@example.com"))
        blocked = client.get("/runs/latest", headers=_proxy_auth_headers("intruder@example.com"))
        missing_secret = client.get(
            "/runs/latest",
            headers={"X-Auth-Request-Email": "reviewer@example.com"},
        )

        assert operator.status_code == 200
        assert reviewer.status_code == 200
        assert admin.status_code in {200, 503}
        assert blocked.status_code == 403
        assert missing_secret.status_code == 401
    finally:
        _restore_env(original)


def test_proxy_oidc_optional_session_uses_forwarded_identity_headers() -> None:
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_AUTH_MODE": "proxy_oidc",
            "STRATEGYOS_TRUST_PROXY_AUTH": "true",
            "STRATEGYOS_TRUSTED_PROXY_AUTH_SECRET": "proxy-secret",
            "STRATEGYOS_OPERATOR_EMAILS": "operator@example.com",
            "STRATEGYOS_REVIEWER_EMAILS": "reviewer@example.com",
            "OAUTH2_PROXY_OIDC_ISSUER_URL": "https://accounts.google.com",
            "OAUTH2_PROXY_CLIENT_ID": "client-id",
            "OAUTH2_PROXY_REDIRECT_URL": "https://strategyos.example.com/oauth2/callback",
        }
    )
    try:
        client = TestClient(api_module.app)

        response = client.get("/ui/session", headers=_proxy_auth_headers("reviewer@example.com"))

        assert response.status_code == 200
        payload = response.json()
        assert payload["authenticated"] is True
        assert payload["role"] == "reviewer"
        assert payload["subject"] == "oidc:reviewer@example.com"
    finally:
        _restore_env(original)


def test_proxy_oidc_secret_check_uses_compare_digest() -> None:
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_AUTH_MODE": "proxy_oidc",
            "STRATEGYOS_TRUST_PROXY_AUTH": "true",
            "STRATEGYOS_TRUSTED_PROXY_AUTH_SECRET": "proxy-secret",
            "STRATEGYOS_REVIEWER_EMAILS": "reviewer@example.com",
            "OAUTH2_PROXY_OIDC_ISSUER_URL": "https://accounts.google.com",
            "OAUTH2_PROXY_CLIENT_ID": "client-id",
            "OAUTH2_PROXY_REDIRECT_URL": "https://strategyos.example.com/oauth2/callback",
        }
    )
    try:
        headers = _proxy_auth_headers("reviewer@example.com")
        with patch.object(auth_module.hmac, "compare_digest", return_value=True) as compare_digest:
            principal = auth_module._proxy_principal_from_headers(headers)

        assert principal is not None
        assert principal["role"] == "reviewer"
        compare_digest.assert_called_once_with("proxy-secret", "proxy-secret")
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
