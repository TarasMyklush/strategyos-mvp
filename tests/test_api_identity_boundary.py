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


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_identity_tokens_gate_reviewer_and_operator_endpoints(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
            "STRATEGYOS_IDP_OPERATOR_USERNAME": "operator.local",
            "STRATEGYOS_IDP_OPERATOR_PASSWORD": "operator-pass",
            "STRATEGYOS_IDP_REVIEWER_USERNAME": "reviewer.local",
            "STRATEGYOS_IDP_REVIEWER_PASSWORD": "reviewer-pass",
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
        monkeypatch.setattr(
            auth_module,
            "_introspect_identity_token",
            lambda token: {
                "reviewer-token": {"role": "reviewer", "subject": "http://localhost:8089:reviewer.local"},
                "operator-token": {"role": "operator", "subject": "http://localhost:8089:operator.local"},
            }.get(token),
        )

        client = TestClient(api_module.app)

        assert client.get("/runs/latest").status_code == 401
        assert client.get("/data/status").status_code == 401
        assert client.post("/inputs/prepare").status_code == 401

        assert client.get("/runs/latest", headers=_auth_header("reviewer-token")).status_code == 200
        assert client.get("/data/status", headers=_auth_header("reviewer-token")).status_code == 200
        assert client.post("/runs", headers=_auth_header("reviewer-token"), json={}).status_code == 403
        assert client.post("/inputs/prepare", headers=_auth_header("operator-token")).status_code == 200
    finally:
        _restore_env(original)
