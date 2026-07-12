from __future__ import annotations

import os

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
from strategyos_mvp.config import load_config


def _apply_env(updates: dict[str, str | None]) -> dict[str, str | None]:
    original = {key: os.environ.get(key) for key in updates}
    for key, value in updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    api_module.CONFIG = config
    auth_module.CONFIG = config
    return original


def _restore_env(original: dict[str, str | None]) -> None:
    _apply_env(original)


def test_login_required_mode_exposes_only_login_until_a_session_exists(monkeypatch) -> None:
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_LOGIN_REQUIRED": "true",
            "STRATEGYOS_AUTH_MODE": "identity_provider",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://idp.test/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-test-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "test-secret",
        }
    )
    try:
        client = TestClient(api_module.app, base_url="https://strategyos.test")

        for path in ("/", "/app", "/dashboard", "/executive", "/guide", "/plan"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 307, path
            assert response.headers["location"] == "/login"

        assert client.get("/ui/session").status_code == 401
        assert client.get("/public/runs/latest").status_code == 401
        assert client.post(
            "/assistant/chat", json={"question": "What is the board status?", "persona": "ceo"}
        ).status_code == 401

        client.cookies.set("strategyos_session", "expired-session", domain="strategyos.test", path="/")
        expired = client.get("/", follow_redirects=False)
        assert expired.status_code == 307
        assert expired.headers["location"] == "/login"

        monkeypatch.setattr(
            auth_module,
            "_introspect_identity_token",
            lambda token: {
                "role": "executive",
                "subject": "idp:executive.tester",
                "tenant_id": "strategyos-test",
            }
            if token == "valid-session"
            else None,
        )
        client.cookies.set("strategyos_session", "valid-session", domain="strategyos.test", path="/")

        assert client.get("/app").status_code == 200
        session = client.get("/ui/session")
        assert session.status_code == 200
        assert session.json()["authenticated"] is True
        assert session.json()["role"] == "executive"
    finally:
        _restore_env(original)
