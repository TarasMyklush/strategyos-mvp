from pathlib import Path
from types import SimpleNamespace

import strategyos_mvp.hatchet_runtime as hatchet_runtime
import strategyos_mvp.run_executor as run_executor


def test_hatchet_dependency_probe_requires_active_worker(monkeypatch):
    active_worker = SimpleNamespace(name="strategyos-worker", status=SimpleNamespace(value="ACTIVE"))
    fake_hatchet = SimpleNamespace(
        workers=SimpleNamespace(list=lambda: SimpleNamespace(rows=[active_worker]))
    )
    monkeypatch.setattr(hatchet_runtime, "hatchet", fake_hatchet)
    monkeypatch.setattr(hatchet_runtime, "_HATCHET_IMPORT_ERROR", None)

    status = hatchet_runtime.hatchet_dependency_status(
        SimpleNamespace(
            run_execution_mode="hatchet",
            hatchet_client_token="token",
            hatchet_worker_name="strategyos-worker",
            hatchet_worker_slots=1,
            hatchet_client_tls_strategy="none",
            hatchet_dashboard_url="http://hatchet-lite:8888",
        ),
        verify_connection=True,
    )

    assert status["status"] == "ok"
    assert status["connection_verified"] is True
    assert status["registered_worker_count"] == 1


def test_hatchet_dependency_probe_rejects_missing_active_worker(monkeypatch):
    inactive_worker = SimpleNamespace(
        name="strategyos-worker", status=SimpleNamespace(value="INACTIVE")
    )
    fake_hatchet = SimpleNamespace(
        workers=SimpleNamespace(list=lambda: SimpleNamespace(rows=[inactive_worker]))
    )
    monkeypatch.setattr(hatchet_runtime, "hatchet", fake_hatchet)
    monkeypatch.setattr(hatchet_runtime, "_HATCHET_IMPORT_ERROR", None)

    status = hatchet_runtime.hatchet_dependency_status(
        SimpleNamespace(
            run_execution_mode="hatchet",
            hatchet_client_token="token",
            hatchet_worker_name="strategyos-worker",
            hatchet_worker_slots=1,
            hatchet_client_tls_strategy="none",
            hatchet_dashboard_url="http://hatchet-lite:8888",
        ),
        verify_connection=True,
    )

    assert status["status"] == "failed"
    assert "not registered" in status["reason"]


def test_sync_execution_mode_delegates_to_existing_runner(tmp_path: Path):
    calls = {}

    def fake_runner(**kwargs):
        calls.update(kwargs)
        return {"status": "completed", "run_id": "run-1"}

    result = run_executor.submit_run(
        dataset=tmp_path / "dataset",
        source_pack_id=None,
        run_dir=tmp_path / "runs",
        skip_prepare=True,
        sync_artifacts=False,
        allow_partial_source_pack=False,
        submitted_by="operator",
        config=SimpleNamespace(run_execution_mode="sync"),
        sync_runner=fake_runner,
    )

    assert result["run_id"] == "run-1"
    assert calls["dataset"] == tmp_path / "dataset"
    assert calls["skip_prepare"] is True


def test_hatchet_execution_mode_creates_job_and_enqueues(monkeypatch, tmp_path: Path):
    created_payloads = []
    updates = []

    def fake_create_run_job(request_payload, **kwargs):
        created_payloads.append((request_payload, kwargs))
        return {
            "job_id": "job-1",
            "status": "queued",
            "request_hash": "hash-1",
        }

    def fake_update_run_job(job_id, **kwargs):
        updates.append((job_id, kwargs))
        return {
            "job_id": job_id,
            "status": kwargs.get("status", "queued"),
            "hatchet_run_id": kwargs.get("hatchet_run_id"),
            "request_hash": "hash-1",
        }

    monkeypatch.setattr(run_executor.state_store, "create_run_job", fake_create_run_job)
    monkeypatch.setattr(run_executor.state_store, "update_run_job", fake_update_run_job)
    monkeypatch.setattr(
        hatchet_runtime,
        "enqueue_strategyos_run",
        lambda payload: {"hatchet_run_id": "hatchet-1", "payload_job": payload["job_id"]},
    )

    result = run_executor.submit_run(
        dataset=tmp_path / "dataset",
        source_pack_id=None,
        run_dir=tmp_path / "runs",
        skip_prepare=True,
        sync_artifacts=False,
        allow_partial_source_pack=False,
        submitted_by="operator",
        config=SimpleNamespace(run_execution_mode="hatchet"),
        sync_runner=lambda **_: {"status": "unexpected"},
    )

    assert result == {
        "status": "queued",
        "execution_mode": "hatchet",
        "job_id": "job-1",
        "hatchet_run_id": "hatchet-1",
        "strategyos_run_id": None,
        "request_hash": "hash-1",
        "detail": "StrategyOS run queued for Hatchet worker execution.",
    }
    assert created_payloads[0][0]["dataset"] == str(tmp_path / "dataset")
    assert created_payloads[0][1]["submitted_by"] == "operator"
    assert updates[0][0] == "job-1"
    assert updates[0][1]["hatchet_run_id"] == "hatchet-1"


def test_hatchet_worker_task_updates_job_lifecycle(monkeypatch, tmp_path: Path):
    updates = []

    def fake_update_run_job(job_id, **kwargs):
        updates.append((job_id, kwargs))
        return {"job_id": job_id, **kwargs}

    monkeypatch.setattr(hatchet_runtime.state_store, "update_run_job", fake_update_run_job)
    monkeypatch.setattr(
        hatchet_runtime,
        "run_strategyos_workflow",
        lambda **_: {
            "status": "completed",
            "run_id": "11111111-1111-1111-1111-111111111111",
            "run_dir": str(tmp_path / "runs" / "run-1"),
        },
    )

    output = hatchet_runtime.execute_strategyos_run_job(
        hatchet_runtime.StrategyOSRunInput(
            job_id="job-1",
            dataset=str(tmp_path / "dataset"),
            run_dir=str(tmp_path / "runs"),
            skip_prepare=True,
            sync_artifacts=False,
        )
    )

    assert output.status == "succeeded"
    assert output.strategyos_run_id == "11111111-1111-1111-1111-111111111111"
    assert updates[0][1]["status"] == "running"
    assert updates[-1][1]["status"] == "succeeded"
    assert updates[-1][1]["strategyos_run_id"] == "11111111-1111-1111-1111-111111111111"
