import os

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


def test_live_health_is_public_when_enabled():
    original = _apply_env(
        {
            "STRATEGYOS_PUBLIC_HEALTH_ENABLED": "true",
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-key",
        }
    )
    try:
        client = TestClient(api_module.app)
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    finally:
        _restore_env(original)


def test_live_health_requires_operator_when_public_disabled():
    original = _apply_env(
        {
            "STRATEGYOS_PUBLIC_HEALTH_ENABLED": "false",
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-key",
        }
    )
    try:
        client = TestClient(api_module.app)
        unauthorized = client.get("/health/live")
        assert unauthorized.status_code == 401

        authorized = client.get("/health/live", headers={"X-API-Key": "operator-key"})
        assert authorized.status_code == 200
    finally:
        _restore_env(original)


def test_ready_health_requires_auth_and_surfaces_failed_dependencies(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-key",
            "STRATEGYOS_REQUIRE_HUMAN_REVIEW": "true",
            "DATABASE_URL": None,
            "REDIS_URL": None,
            "NEO4J_URI": None,
            "STRATEGYOS_OBJECT_ENDPOINT": None,
            "STRATEGYOS_OBJECT_BUCKET": None,
        }
    )
    try:
        monkeypatch.setattr(
            api_module,
            "_check_postgres",
            lambda: {"status": "failed", "reason": "db down"},
        )
        monkeypatch.setattr(api_module, "_check_redis", lambda: {"status": "skipped"})
        monkeypatch.setattr(api_module, "_check_neo4j", lambda: {"status": "skipped"})
        monkeypatch.setattr(api_module, "_check_qdrant", lambda: {"status": "skipped"})
        monkeypatch.setattr(
            api_module, "_check_object_store", lambda: {"status": "skipped"}
        )
        monkeypatch.setattr(api_module, "_check_workspace", lambda: {"status": "ok"})
        monkeypatch.setattr(
            api_module,
            "_check_runtime_dependencies",
            lambda: {"status": "ok", "checks": {}},
        )

        client = TestClient(api_module.app)
        unauthorized = client.get("/health/ready")
        assert unauthorized.status_code == 401

        response = client.get("/health/ready", headers={"X-API-Key": "operator-key"})
        assert response.status_code == 503
        payload = response.json()
        assert payload["status"] == "failed"
        assert payload["checks"]["postgres"]["status"] == "failed"
        assert payload["checks"]["governance"]["status"] == "ok"
    finally:
        _restore_env(original)


def test_ready_health_is_ok_when_human_review_is_intentionally_disabled(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-key",
            "STRATEGYOS_REQUIRE_HUMAN_REVIEW": "false",
        }
    )
    try:
        for check_name in [
            "_check_postgres",
            "_check_redis",
            "_check_neo4j",
            "_check_qdrant",
            "_check_object_store",
            "_check_workspace",
        ]:
            monkeypatch.setattr(api_module, check_name, lambda: {"status": "ok"})
        monkeypatch.setattr(
            api_module,
            "_check_runtime_dependencies",
            lambda: {"status": "ok", "checks": {}},
        )

        client = TestClient(api_module.app)
        response = client.get("/health/ready", headers={"X-API-Key": "operator-key"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["checks"]["governance"]["status"] == "ok"
        assert payload["checks"]["governance"]["require_human_review"] is False
    finally:
        _restore_env(original)


def test_dependencies_health_requires_auth_and_reports_runtime_deps(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-key",
        }
    )
    try:
        monkeypatch.setattr(
            api_module,
            "runtime_dependency_status",
            lambda: {
                "status": "ok",
                "requested_ocr_engine": "tesseract",
                "resolved_ocr_engines": ["tesseract"],
                "checks": {
                    "tesseract": {
                        "status": "ok",
                        "installed_version": "5.5.0-1+b1",
                    }
                },
            },
        )

        client = TestClient(api_module.app)
        unauthorized = client.get("/health/dependencies")
        assert unauthorized.status_code == 401

        authorized = client.get(
            "/health/dependencies", headers={"X-API-Key": "operator-key"}
        )
        assert authorized.status_code == 200
        payload = authorized.json()
        assert payload["status"] == "ok"
        assert payload["checks"]["tesseract"]["installed_version"] == "5.5.0-1+b1"
    finally:
        _restore_env(original)


def test_check_neo4j_uses_authenticated_cypher_probe(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "check_neo4j_ready",
        lambda: {"status": "ok", "probe": "RETURN 1 AS ok", "uri": "bolt://neo4j:7687"},
    )

    payload = api_module._check_neo4j()

    assert payload["status"] == "ok"
    assert payload["probe"] == "RETURN 1 AS ok"


def test_check_qdrant_uses_http_probe(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "check_qdrant_ready",
        lambda: {"status": "ok", "url": "http://qdrant:6333", "collections": 1},
    )

    payload = api_module._check_qdrant()

    assert payload["status"] == "ok"
    assert payload["url"] == "http://qdrant:6333"
