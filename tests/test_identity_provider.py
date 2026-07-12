import os

from fastapi.testclient import TestClient

import strategyos_mvp.idp as idp_module
from strategyos_mvp.config import load_config


ALL_TEST_USERS = "operator.tester=op-pass,reviewer.tester=rev-pass,bu.tester=bu-pass,analyst.tester=analyst-pass,auditor.tester=auditor-pass,executive.tester=exec-pass,tenant-operator.tester=tenant-op-pass,tenant-admin.tester=tenant-admin-pass,system.tester=system-pass"


def _apply_env(env_updates: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in env_updates}
    for key, value in env_updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    idp_module.CONFIG = load_config()
    idp_module.app.state.tokens = {}
    idp_module.app.state.login_attempts = {}
    return original


def _restore_env(original: dict[str, str | None]):
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    idp_module.CONFIG = load_config()
    idp_module.app.state.tokens = {}
    idp_module.app.state.login_attempts = {}


def test_local_identity_provider_issues_and_introspects_tokens():
    original = _apply_env(
        {
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
            "STRATEGYOS_IDP_OPERATOR_USERNAME": "operator.local",
            "STRATEGYOS_IDP_OPERATOR_PASSWORD": "operator-pass",
            "STRATEGYOS_IDP_REVIEWER_USERNAME": "reviewer.local",
            "STRATEGYOS_IDP_REVIEWER_PASSWORD": "reviewer-pass",
            "STRATEGYOS_IDP_TOKEN_TTL_SECONDS": "3600",
            "STRATEGYOS_IDP_TEST_USERS": None,
        }
    )
    try:
        client = TestClient(idp_module.app)
        token_response = client.post(
            "/oauth/token",
            data={
                "grant_type": "password",
                "client_id": "strategyos-local-client",
                "client_secret": "local-secret",
                "username": "reviewer.local",
                "password": "reviewer-pass",
            },
        )
        assert token_response.status_code == 200
        token_payload = token_response.json()
        assert token_payload["role"] == "reviewer"
        assert token_payload["subject"] == "reviewer.local"
        access_token = token_payload["access_token"]

        introspection_response = client.post(
            "/oauth/introspect",
            data={
                "client_id": "strategyos-local-client",
                "client_secret": "local-secret",
                "token": access_token,
            },
        )
        assert introspection_response.status_code == 200
        introspection_payload = introspection_response.json()
        assert introspection_payload["active"] is True
        assert introspection_payload["role"] == "reviewer"
        assert introspection_payload["sub"] == "reviewer.local"
    finally:
        _restore_env(original)


def test_login_page_is_human_friendly_and_security_tagged():
    original = _apply_env(
        {
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
            "STRATEGYOS_IDP_TEST_USERS": ALL_TEST_USERS,
        }
    )
    try:
        client = TestClient(idp_module.app)
        response = client.get("/login")
        assert response.status_code == 200
        assert response.headers["content-security-policy"].startswith("default-src 'self'")
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
        assert "Temporary test login" in response.text
        assert "operator.tester" in response.text
        assert "executive.tester" in response.text
        assert "operator.local" not in response.text
        assert "secure browser cookie" in response.text
        assert "localStorage.removeItem" in response.text
    finally:
        _restore_env(original)


def test_auth_login_issues_tokens_for_every_test_role():
    original = _apply_env(
        {
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
            "STRATEGYOS_IDP_TEST_USERS": ALL_TEST_USERS,
        }
    )
    try:
        client = TestClient(idp_module.app)
        cases = {
            "operator.tester": ("op-pass", "operator", "/app"),
            "reviewer.tester": ("rev-pass", "reviewer", "/app"),
            "bu.tester": ("bu-pass", "bu", "/app"),
            "analyst.tester": ("analyst-pass", "analyst", "/app"),
            "auditor.tester": ("auditor-pass", "auditor", "/app"),
            "executive.tester": ("exec-pass", "executive", "/executive"),
            "tenant-operator.tester": ("tenant-op-pass", "tenant_operator", "/app"),
            "tenant-admin.tester": ("tenant-admin-pass", "tenant_admin", "/app"),
            "system.tester": ("system-pass", "system", "/app"),
        }
        for username, (password, role, redirect) in cases.items():
            response = client.post(
                "/auth/login", json={"username": username, "password": password}
            )
            assert response.status_code == 200, username
            payload = response.json()
            assert payload["access_token"]
            assert payload["token_type"] == "Bearer"
            assert payload["role"] == role
            assert payload["subject"] == username
            assert payload["redirect"] == redirect
            set_cookie = response.headers["set-cookie"].lower()
            assert "strategyos_session=" in set_cookie
            assert "httponly" in set_cookie
            assert "secure" in set_cookie
            assert "samesite=lax" in set_cookie
    finally:
        _restore_env(original)


def test_auth_login_rejects_bad_credentials_generically():
    original = _apply_env(
        {
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
            "STRATEGYOS_IDP_TEST_USERS": ALL_TEST_USERS,
        }
    )
    try:
        client = TestClient(idp_module.app)
        response = client.post(
            "/auth/login", json={"username": "operator.tester", "password": "wrong"}
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid credentials for this role."}
    finally:
        _restore_env(original)


def test_auth_login_rate_limits_repeated_failures():
    original = _apply_env(
        {
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
            "STRATEGYOS_IDP_TEST_USERS": ALL_TEST_USERS,
        }
    )
    try:
        client = TestClient(idp_module.app)
        for _ in range(10):
            response = client.post(
                "/auth/login", json={"username": "operator.tester", "password": "wrong"}
            )
            assert response.status_code == 401
        limited = client.post(
            "/auth/login", json={"username": "operator.tester", "password": "op-pass"}
        )
        assert limited.status_code == 429
    finally:
        _restore_env(original)
