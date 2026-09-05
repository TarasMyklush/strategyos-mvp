from dataclasses import replace
import os

import pytest

from strategyos_mvp import access_scope, state_store


def test_shared_database_run_and_bu_isolation(monkeypatch, tmp_path):
    url = os.getenv("STRATEGYOS_POSTGRES_E2E_DATABASE_URL")
    if not url:
        pytest.skip("Dedicated Postgres proof endpoint required.")
    import psycopg
    monkeypatch.setattr(state_store, "database_connection", lambda: (psycopg.connect(url), None))
    import uuid
    suffix = uuid.uuid4().hex
    tenant_a, tenant_b = "scope-a-" + suffix, "scope-b-" + suffix
    baseline = state_store.CONFIG
    runs = []
    for tenant, unit in ((tenant_a, "bu-a"), (tenant_b, "bu-b"), (tenant_a, "bu-c")):
        monkeypatch.setattr(state_store, "CONFIG", replace(baseline, tenant_slug=tenant))
        runs.append(state_store.create_run({"run_dir": str(tmp_path / unit), "dataset_root": str(tmp_path),
            "business_units": [unit], "status": "awaiting_review"}, requires_human_review=True)["run_id"])
    token = access_scope.principal_scope.set({"tenant_id": tenant_a, "role": "bu", "business_units": ["bu-a"]})
    try:
        assert state_store.get_run_detail(runs[0])["run_id"] == runs[0]
        for denied in runs[1:]:
            for operation in (state_store.get_run_detail, state_store.executive_snapshot_for_run,
                              state_store.latest_checkpoint, lambda run_id: state_store.artifact_paths_for_run(None, run_id),
                              state_store.executive_decisions_for_run):
                with pytest.raises(PermissionError):
                    operation(denied)
        assert {run["run_id"] for run in state_store.list_recent_runs()} == {runs[0]}
        assert {run["run_id"] for run in state_store.list_pending_reviews()} == {runs[0]}
        access_scope.principal_scope.set({"tenant_id": tenant_a, "role": "executive"})
        assert {run["run_id"] for run in state_store.list_recent_runs()} == {runs[0], runs[2]}
        access_scope.principal_scope.set({"tenant_id": tenant_a, "role": "bu"})
        with pytest.raises(PermissionError):
            state_store.get_run_detail(runs[0])
    finally:
        access_scope.principal_scope.reset(token)
