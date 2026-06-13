import os

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
import strategyos_mvp.run_poc as run_poc_module
import strategyos_mvp.state_store as state_store
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


def _auth_header(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def test_create_run_returns_accepted_for_hatchet_submission(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
        }
    )
    try:
        monkeypatch.setattr(
            api_module,
            "submit_run",
            lambda **_: {
                "status": "queued",
                "execution_mode": "hatchet",
                "job_id": "job-1",
                "hatchet_run_id": "hatchet-1",
            },
        )
        client = TestClient(api_module.app)

        response = client.post(
            "/runs",
            headers=_auth_header("operator-secret"),
            json={"skip_prepare": True, "sync_artifacts": False},
        )

        assert response.status_code == 202
        assert response.json()["job_id"] == "job-1"
    finally:
        _restore_env(original)


def test_run_job_status_returns_persisted_job(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
        }
    )
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "get_run_job",
            lambda job_id: {
                "job_id": job_id,
                "status": "queued",
                "execution_mode": "hatchet",
                "strategyos_run_id": None,
            },
        )
        client = TestClient(api_module.app)

        response = client.get(
            "/runs/jobs/job-1",
            headers=_auth_header("reviewer-secret"),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "queued"
        assert response.json()["job_id"] == "job-1"
    finally:
        _restore_env(original)
