import os

from fastapi.testclient import TestClient

import strategyos_mvp.idp as idp_module
from strategyos_mvp.config import load_config


def _apply_env(env_updates: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in env_updates}
    for key, value in env_updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    idp_module.CONFIG = load_config()
    idp_module.app.state.tokens = {}
    return original


def _restore_env(original: dict[str, str | None]):
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    idp_module.CONFIG = load_config()
    idp_module.app.state.tokens = {}


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
