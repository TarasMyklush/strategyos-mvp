import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
import strategyos_mvp.run_poc as run_poc_module
import strategyos_mvp.run_registry as run_registry_module
import strategyos_mvp.source_pack as source_pack_module
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
    run_registry_module.CONFIG = config
    source_pack_module.CONFIG = config
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
    run_registry_module.CONFIG = config
    source_pack_module.CONFIG = config
    state_store.CONFIG = config
    storage.CONFIG = config


def _auth_header(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _truncate_strategyos_tables(database_url: str) -> None:
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(database_url, autocommit=True) as conn:
        state_store.ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select tablename
                from pg_tables
                where schemaname = 'public'
                  and tablename like 'strategyos_%'
                order by tablename
                """
            )
            tables = [row[0] for row in cur.fetchall()]
            if tables:
                joined = ", ".join(tables)
                cur.execute(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE")


@pytest.mark.integration
def test_postgres_backed_governed_source_pack_flow(tmp_path: Path):
    database_url = os.environ.get("STRATEGYOS_POSTGRES_E2E_DATABASE_URL")
    if not database_url:
        pytest.skip("Set STRATEGYOS_POSTGRES_E2E_DATABASE_URL to run the local Postgres e2e proof.")

    baseline_config = load_config()
    source_dataset = baseline_config.source_dataset.resolve()
    workspace_root = baseline_config.workspace_root.resolve()
    assert source_dataset.exists(), f"Missing source dataset at {source_dataset}"
    assert source_dataset.is_relative_to(workspace_root)

    output_root = tmp_path / "outputs"
    output_root.mkdir(parents=True, exist_ok=True)
    _truncate_strategyos_tables(database_url)

    original = _apply_env(
        {
            "DATABASE_URL": database_url,
            "STRATEGYOS_DATABASE_URL": database_url,
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_REQUIRE_HUMAN_REVIEW": "true",
            "STRATEGYOS_WORKSPACE_ROOT": str(workspace_root),
            "STRATEGYOS_OUTPUT_ROOT": str(output_root),
            "STRATEGYOS_SYNC_ARTIFACTS": "false",
        }
    )
    try:
        client = TestClient(api_module.app)

        staged = client.post(
            "/source-packs/from-path",
            headers=_auth_header("operator-secret"),
            json={"folder_path": str(source_dataset)},
        )
        assert staged.status_code == 200
        source_pack = staged.json()
        assert source_pack["task_readiness"]["ready_for_run"] is True

        created = client.post(
            "/runs",
            headers=_auth_header("operator-secret"),
            json={"source_pack_id": source_pack["source_pack_id"], "sync_artifacts": False},
        )
        assert created.status_code == 200
        created_payload = created.json()
        run_id = created_payload["run_id"]
        assert created_payload["status"] == "awaiting_review"
        assert created_payload["current_stage"] == "awaiting_review"
        assert created_payload["review_state"] == "awaiting_decision"
        assert created_payload["resume_state"] == "blocked_pending_review"
        if api_module.CONFIG.runtime_backend == "langgraph":
            runtime = created_payload.get("runtime") or {}
            assert runtime.get("actual_backend") == "langgraph"
            assert runtime.get("fallback_used") is False

        pending = client.get(
            "/reviewer/pending-reviews",
            headers=_auth_header("reviewer-secret"),
        )
        assert pending.status_code == 200
        pending_items = pending.json()["items"]
        pending_item = next(item for item in pending_items if item["run_id"] == run_id)
        checkpoint_id = pending_item["checkpoint_id"]
        assert pending_item["review_assignment"]["claimed"] is False

        claimed = client.post(
            f"/reviewer/runs/{run_id}/claim",
            headers=_auth_header("reviewer-secret"),
        )
        assert claimed.status_code == 200
        assert claimed.json()["review_assignment"]["claimed"] is True

        approved = client.post(
            f"/reviewer/runs/{run_id}/approve",
            headers=_auth_header("reviewer-secret"),
            json={"comment": "ready for writer"},
        )
        assert approved.status_code == 200
        assert approved.json()["decision"] == "approved"
        assert approved.json()["checkpoint_id"] == checkpoint_id

        resumed = client.post(
            f"/operator/runs/{run_id}/resume",
            headers=_auth_header("operator-secret"),
            json={},
        )
        assert resumed.status_code == 200
        resumed_payload = resumed.json()
        assert resumed_payload["status"] == "completed"
        assert resumed_payload["current_stage"] == "writer"
        assert resumed_payload["approval_status"] == "approved"
        assert resumed_payload["review_state"] == "approved"
        assert resumed_payload["resume_state"] == "completed"
        assert resumed_payload["source_pack_id"] == source_pack["source_pack_id"]

        detail = client.get(
            f"/reviewer/runs/{run_id}",
            headers=_auth_header("reviewer-secret"),
        )
        assert detail.status_code == 200
        detail_payload = detail.json()
        assert detail_payload["latest_checkpoint"]["stage"] == "writer"
        assert detail_payload["approval"]["approval_status"] == "approved"
        assert detail_payload["review_assignment"]["claimed"] is False

        psycopg = pytest.importorskip("psycopg")
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "select status, current_stage, approved_by from strategyos_runs where id = %s",
                    (run_id,),
                )
                run_row = cur.fetchone()
                cur.execute(
                    "select count(*) from strategyos_run_checkpoints where run_id = %s",
                    (run_id,),
                )
                checkpoint_count = cur.fetchone()[0]
                cur.execute(
                    "select count(*) from strategyos_approvals where run_id = %s",
                    (run_id,),
                )
                approval_count = cur.fetchone()[0]

        assert run_row is not None
        assert run_row[0] == "completed"
        assert run_row[1] == "writer"
        assert str(run_row[2]).startswith("api-key:reviewer:")
        assert checkpoint_count >= 2
        assert approval_count == 1
    finally:
        _restore_env(original)
        _truncate_strategyos_tables(database_url)
