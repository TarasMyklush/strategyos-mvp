import os
import json
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
import strategyos_mvp.reviewer_runtime as reviewer_runtime
import strategyos_mvp.run_poc as run_poc_module
import strategyos_mvp.run_registry as run_registry_module
import strategyos_mvp.state_store as state_store
import strategyos_mvp.storage as storage
from strategyos_mvp.config import load_config


def _artifact_access_audit_lines(output_root: Path) -> list[dict]:
    path = output_root / api_module.ARTIFACT_ACCESS_AUDIT_LOG
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
    state_store.CONFIG = config
    storage.CONFIG = config


def _auth_header(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _client_with_auth_env():
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_BU_API_KEYS": "bu-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-a111,reviewer-b222",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    return original, TestClient(api_module.app)


def _write_local_review_summary(
    tmp_path: Path,
    *,
    approval_status: str = "pending",
    claimed_by: str | None = None,
) -> dict:
    output_root = tmp_path / "outputs"
    run_dir = output_root / "local-review-run"
    dataset_root = tmp_path / "dataset"
    run_dir.mkdir(parents=True)
    dataset_root.mkdir()
    run_id = "local-review-run"
    state_json = {
        "run_id": run_id,
        "dataset_root": str(dataset_root),
        "source_pack_id": None,
        "run_dir": str(run_dir),
        "workflow_status": "awaiting_review",
        "current_stage": "awaiting_review",
        "requires_human_review": True,
        "approval_status": approval_status,
        "findings": [],
        "audit_events": [],
        "artifact_paths": {},
    }
    summary = api_module.annotate_governance_state(
        {
            "run_id": run_id,
            "dataset": str(dataset_root),
            "run_dir": str(run_dir),
            "findings": 1,
            "locked_findings": 1,
            "total_recoverable_sar": 80.0,
            "artifacts": {},
            "status": "awaiting_review",
            "current_stage": "awaiting_review",
            "requires_human_review": True,
            "approval_status": approval_status,
            "checkpoint_count": 1,
            "run_outcome": "awaiting_review",
            "deliverables_status": "paused_before_writer",
            "local_review_checkpoint": {
                "checkpoint_id": f"local-checkpoint:{run_id}:awaiting_review",
                "run_id": run_id,
                "stage": "awaiting_review",
                "status": "awaiting_review",
                "state_json": state_json,
                "summary_json": {},
                "persistence": "local",
            },
            "review_assignment": {
                "claimed": bool(claimed_by),
                "claimed_by": claimed_by,
                "claimed_at": "2026-06-18T00:00:00Z" if claimed_by else None,
            },
        }
    )
    summary_path = run_dir / "run_summary.json"
    summary["pointer_metadata"] = run_registry_module.update_run_pointers(
        summary, summary_path
    )
    summary["latest_pointer"] = summary["pointer_metadata"]["latest"]
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {"summary": summary, "summary_path": summary_path, "run_id": run_id}


def test_pending_reviews_requires_api_key():
    original, client = _client_with_auth_env()
    try:
        response = client.get("/reviewer/pending-reviews")

        assert response.status_code == 401
    finally:
        _restore_env(original)


def test_pending_reviews_returns_items_for_reviewer(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "list_pending_reviews",
            lambda: [{
                "run_id": "run-1",
                "checkpoint_id": "cp-1",
                "review_assignment": {
                    "claimed": True,
                    "claimed_by": "api-key:reviewer:a111",
                    "claimed_at": "2026-06-05T10:00:00Z",
                },
            }],
        )

        response = client.get(
            "/reviewer/pending-reviews", headers=_auth_header("reviewer-a111")
        )

        assert response.status_code == 200
        assert response.json()["items"][0]["run_id"] == "run-1"
        assert response.json()["items"][0]["review_assignment"]["claimed"] is True
        assert response.json()["viewer_role"] == "reviewer"
    finally:
        _restore_env(original)


def test_bu_pending_reviews_returns_items_read_only(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "list_pending_reviews",
            lambda: [{
                "run_id": "run-1",
                "checkpoint_id": "cp-1",
                "review_assignment": {
                    "claimed": True,
                    "claimed_by": "api-key:reviewer:a111",
                    "claimed_at": "2026-06-05T10:00:00Z",
                },
            }],
        )

        response = client.get("/bu/pending-reviews", headers=_auth_header("bu-key"))

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["run_id"] == "run-1"
        assert payload["viewer_role"] == "bu"
        assert payload["read_only"] is True
    finally:
        _restore_env(original)


def test_pending_reviews_includes_latest_local_summary_when_store_skipped(tmp_path):
    original = _apply_env(
        {
            "DATABASE_URL": None,
            "STRATEGYOS_OUTPUT_ROOT": str(tmp_path / "outputs"),
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-a111",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    client = TestClient(api_module.app)
    try:
        local = _write_local_review_summary(tmp_path)

        response = client.get(
            "/reviewer/pending-reviews", headers=_auth_header("reviewer-a111")
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["store_status"] == "skipped"
        assert payload["items"][0]["run_id"] == local["run_id"]
        assert payload["items"][0]["source"] == "local_summary"
    finally:
        _restore_env(original)


def test_reviewer_lists_tolerate_unconfigured_store(monkeypatch):
    # Local-only mode (no DATABASE_URL): the dashboard list endpoints must return
    # an empty list with store_status='skipped', NOT a 503 that would trip the
    # "Partial backend data loaded" warning banner.
    original, client = _client_with_auth_env()
    try:
        skipped = {"status": "skipped", "reason": "DATABASE_URL is not configured."}
        monkeypatch.setattr(api_module.state_store, "list_pending_reviews", lambda: skipped)
        monkeypatch.setattr(api_module.state_store, "list_recent_runs", lambda limit=12: skipped)

        pending = client.get("/reviewer/pending-reviews", headers=_auth_header("reviewer-a111"))
        runs = client.get("/reviewer/runs?limit=5", headers=_auth_header("reviewer-a111"))

        assert pending.status_code == 200
        assert pending.json()["items"] == []
        assert pending.json()["store_status"] == "skipped"
        assert runs.status_code == 200
        assert runs.json()["items"] == []
        assert runs.json()["store_status"] == "skipped"
    finally:
        _restore_env(original)


def test_reviewer_runs_returns_recent_run_index(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "list_recent_runs",
            lambda limit=12: [
                {
                    "run_id": "run-1",
                    "status": "awaiting_review",
                    "current_stage": "governed_review",
                    "approval_status": "pending",
                }
            ],
        )

        response = client.get(
            "/reviewer/runs?limit=5", headers=_auth_header("reviewer-a111")
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["run_id"] == "run-1"
        assert payload["items"][0]["approval_status"] == "pending"
        assert payload["viewer_role"] == "reviewer"
    finally:
        _restore_env(original)


def test_claim_run_records_reviewer_assignment(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        captured = {}

        def fake_claim(run_id, reviewer_subject):
            captured["args"] = (run_id, reviewer_subject)
            return {
                "run_id": run_id,
                "status": "awaiting_review",
                "review_assignment": {
                    "claimed": True,
                    "claimed_by": reviewer_subject,
                    "claimed_at": "2026-06-05T10:00:00Z",
                },
            }

        monkeypatch.setattr(api_module.state_store, "claim_pending_review", fake_claim)

        response = client.post(
            "/reviewer/runs/run-1/claim",
            headers=_auth_header("reviewer-a111"),
        )

        assert response.status_code == 200
        assert response.json()["review_assignment"]["claimed"] is True
        assert captured["args"] == ("run-1", "api-key:reviewer:a111")
    finally:
        _restore_env(original)


def test_unclaim_run_records_reviewer_assignment_release(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "unclaim_pending_review",
            lambda run_id, reviewer_subject: {
                "run_id": run_id,
                "status": "awaiting_review",
                "review_assignment": {
                    "claimed": False,
                    "claimed_by": None,
                    "claimed_at": None,
                },
            },
        )

        response = client.post(
            "/reviewer/runs/run-1/unclaim",
            headers=_auth_header("reviewer-a111"),
        )

        assert response.status_code == 200
        assert response.json()["review_assignment"]["claimed"] is False
    finally:
        _restore_env(original)


def test_claim_run_returns_not_found_when_missing(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "claim_pending_review",
            lambda run_id, reviewer_subject: {"status": "missing", "run_id": run_id},
        )

        response = client.post(
            "/reviewer/runs/run-404/claim",
            headers=_auth_header("reviewer-a111"),
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Run 'run-404' was not found."
    finally:
        _restore_env(original)


def test_claim_run_forbids_operator():
    original, client = _client_with_auth_env()
    try:
        response = client.post(
            "/reviewer/runs/run-1/claim",
            headers=_auth_header("operator-secret"),
        )

        assert response.status_code == 403
    finally:
        _restore_env(original)


def test_claim_run_forbids_bu_role():
    original, client = _client_with_auth_env()
    try:
        response = client.post(
            "/reviewer/runs/run-1/claim",
            headers=_auth_header("bu-key"),
        )

        assert response.status_code == 403
    finally:
        _restore_env(original)


def test_run_detail_allows_operator(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "get_run_detail",
            lambda run_id: {"run_id": run_id, "status": "awaiting_review"},
        )

        response = client.get(
            "/reviewer/runs/run-1", headers=_auth_header("operator-secret")
        )

        assert response.status_code == 200
        assert response.json()["run_id"] == "run-1"
    finally:
        _restore_env(original)


def test_run_detail_adds_fixed_lifecycle_timeline(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "get_run_detail",
            lambda run_id: {
                "run_id": run_id,
                "created_at": "2026-06-05T09:00:00Z",
                "status": "awaiting_review",
                "current_stage": "awaiting_review",
                "approval": {"approval_status": "pending"},
                "latest_checkpoint": {
                    "checkpoint_id": "cp-1",
                    "stage": "awaiting_review",
                    "status": "awaiting_review",
                    "created_at": "2026-06-05T10:00:00Z",
                },
            },
        )

        response = client.get(
            "/reviewer/runs/run-1", headers=_auth_header("operator-secret")
        )

        assert response.status_code == 200
        timeline = response.json()["lifecycle_timeline"]
        assert [item["stage"] for item in timeline] == [
            "created",
            "ingest",
            "analyst",
            "auditor",
            "evidence_qa",
            "knowledge_graph",
            "awaiting_review",
            "writer",
        ]
        assert timeline[0]["state"] == "completed"
        assert timeline[6]["state"] == "blocked"
        assert timeline[7]["state"] == "pending"
    finally:
        _restore_env(original)


def test_bu_run_detail_sanitizes_artifact_paths(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "get_run_detail",
            lambda run_id: {
                "run_id": run_id,
                "run_dir": "/tmp/private-run",
                "dataset_root": "/tmp/private-dataset",
                "artifacts": {"case_file": "/tmp/private-run/case.md"},
                "summary_json": {
                    "run_id": run_id,
                    "run_dir": "/tmp/private-run",
                    "artifacts": {"case_file": "/tmp/private-run/case.md"},
                },
                "approval": {"approval_status": "pending"},
                "current_stage": "awaiting_review",
                "requires_human_review": True,
            },
        )

        response = client.get("/bu/runs/run-1", headers=_auth_header("bu-key"))

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_id"] == "run-1"
        assert "run_dir" not in payload
        assert "artifacts" not in payload
        assert "run_dir" not in payload["summary_json"]
        assert "artifacts" not in payload["summary_json"]
        assert payload["read_only"] is True
    finally:
        _restore_env(original)


def test_run_detail_uses_latest_local_summary_when_store_skipped(tmp_path):
    original = _apply_env(
        {
            "DATABASE_URL": None,
            "STRATEGYOS_OUTPUT_ROOT": str(tmp_path / "outputs"),
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-a111",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    client = TestClient(api_module.app)
    try:
        local = _write_local_review_summary(tmp_path)

        response = client.get(
            f"/reviewer/runs/{local['run_id']}", headers=_auth_header("operator-secret")
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_id"] == local["run_id"]
        assert payload["summary_json"]["run_id"] == local["run_id"]
        assert payload["latest_checkpoint"]["checkpoint_id"].startswith("local-checkpoint:")
    finally:
        _restore_env(original)


def test_run_lifecycle_timeline_keeps_rejected_runs_out_of_completed_state():
    timeline = api_module._run_lifecycle_timeline(
        {
            "created_at": "2026-06-05T09:00:00Z",
            "status": "awaiting_review",
            "current_stage": "awaiting_review",
            "approval": {"approval_status": "rejected"},
        }
    )

    awaiting_review = next(item for item in timeline if item["stage"] == "awaiting_review")
    writer = next(item for item in timeline if item["stage"] == "writer")
    assert awaiting_review["state"] == "rejected"
    assert writer["state"] == "pending"


def test_checkpoint_detail_requires_auth(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "get_checkpoint_detail",
            lambda checkpoint_id: {"checkpoint_id": checkpoint_id, "run_id": "run-1"},
        )

        response = client.get("/reviewer/checkpoints/cp-1")

        assert response.status_code == 401
    finally:
        _restore_env(original)


def test_checkpoint_detail_uses_latest_local_summary_when_store_skipped(tmp_path):
    original = _apply_env(
        {
            "DATABASE_URL": None,
            "STRATEGYOS_OUTPUT_ROOT": str(tmp_path / "outputs"),
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-a111",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    client = TestClient(api_module.app)
    try:
        local = _write_local_review_summary(tmp_path)
        checkpoint_id = local["summary"]["local_review_checkpoint"]["checkpoint_id"]

        response = client.get(
            f"/reviewer/checkpoints/{checkpoint_id}",
            headers=_auth_header("operator-secret"),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["checkpoint_id"] == checkpoint_id
        assert payload["run_id"] == local["run_id"]
        assert payload["stage"] == "awaiting_review"
    finally:
        _restore_env(original)


def test_run_artifact_preview_returns_json_payload_with_config_patch(monkeypatch, tmp_path):
    original, client = _client_with_auth_env()
    try:
        artifact = tmp_path / "StrategyOS Knowledge Graph.json"
        artifact.write_text('{"nodes": [{"id": "n-1"}], "edges": []}', encoding="utf-8")
        monkeypatch.setattr(api_module, "CONFIG", replace(api_module.CONFIG, output_root=tmp_path))
        monkeypatch.setattr(
            api_module.state_store,
            "get_run_detail",
            lambda run_id: {
                "run_id": run_id,
                "review_assignment": {"claimed": False, "claimed_by": None, "claimed_at": None},
                "summary_json": {"artifacts": {"knowledge_graph": str(artifact)}},
            },
        )

        response = client.get(
            "/reviewer/runs/run-1/artifacts/knowledge_graph",
            headers=_auth_header("reviewer-a111"),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["artifact_key"] == "knowledge_graph"
        assert payload["scope"] == "run"
        assert payload["preview_kind"] == "json"
        assert payload["preview_json"]["nodes"][0]["id"] == "n-1"
        audit_lines = _artifact_access_audit_lines(tmp_path)
        assert audit_lines[-1]["artifact_key"] == "knowledge_graph"
        assert audit_lines[-1]["allowed"] is True
        assert audit_lines[-1]["restricted"] is False
    finally:
        _restore_env(original)


def test_bu_artifact_preview_denies_restricted_artifact(monkeypatch, tmp_path):
    original, client = _client_with_auth_env()
    try:
        artifact = tmp_path / "case_file.md"
        artifact.write_text("restricted", encoding="utf-8")
        monkeypatch.setattr(api_module, "CONFIG", replace(api_module.CONFIG, output_root=tmp_path))
        monkeypatch.setattr(
            api_module.state_store,
            "get_run_detail",
            lambda run_id: {
                "run_id": run_id,
                "review_assignment": {"claimed": False, "claimed_by": None, "claimed_at": None},
                "summary_json": {"artifacts": {"case_file": str(artifact)}},
            },
        )

        response = client.get(
            "/bu/runs/run-1/artifacts/case_file",
            headers=_auth_header("bu-key"),
        )

        assert response.status_code == 403
    finally:
        _restore_env(original)


def test_checkpoint_artifact_preview_returns_text_payload_for_operator(monkeypatch, tmp_path):
    original, client = _client_with_auth_env()
    try:
        artifact = tmp_path / "StrategyOS Cash Leakage Case File.md"
        artifact.write_text("# StrategyOS Cash Leakage Case File\n", encoding="utf-8")
        monkeypatch.setattr(api_module, "CONFIG", replace(api_module.CONFIG, output_root=tmp_path))
        monkeypatch.setattr(
            api_module.state_store,
            "get_checkpoint_detail",
            lambda checkpoint_id: {
                "checkpoint_id": checkpoint_id,
                "run_id": "run-1",
                "state_json": {"artifact_paths": {"case_file": str(artifact)}},
            },
        )
        monkeypatch.setattr(
            api_module.state_store,
            "get_run_detail",
            lambda run_id: {
                "run_id": run_id,
                "review_assignment": {"claimed": False, "claimed_by": None, "claimed_at": None},
            },
        )

        response = client.get(
            "/reviewer/checkpoints/cp-1/artifacts/case_file",
            headers=_auth_header("operator-secret"),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["artifact_key"] == "case_file"
        assert payload["scope"] == "checkpoint"
        assert payload["preview_kind"] == "text"
        assert "Cash Leakage Case File" in payload["preview_text"]
        audit_lines = _artifact_access_audit_lines(tmp_path)
        assert audit_lines[-1]["artifact_key"] == "case_file"
        assert audit_lines[-1]["allowed"] is True
        assert audit_lines[-1]["restricted"] is True
    finally:
        _restore_env(original)


def test_restricted_case_file_preview_denies_unclaimed_reviewer_and_audits(monkeypatch, tmp_path):
    original, client = _client_with_auth_env()
    try:
        artifact = tmp_path / "Final consolidated case file.md"
        artifact.write_text("# restricted\n", encoding="utf-8")
        monkeypatch.setattr(api_module, "CONFIG", replace(api_module.CONFIG, output_root=tmp_path))
        monkeypatch.setattr(
            api_module.state_store,
            "get_run_detail",
            lambda run_id: {
                "run_id": run_id,
                "review_assignment": {"claimed": False, "claimed_by": None, "claimed_at": None},
                "summary_json": {"artifacts": {"case_file": str(artifact)}},
            },
        )

        response = client.get(
            "/reviewer/runs/run-1/artifacts/case_file",
            headers=_auth_header("reviewer-a111"),
        )

        assert response.status_code == 403
        assert "claimed reviewer" in response.json()["detail"]
        audit_lines = _artifact_access_audit_lines(tmp_path)
        assert audit_lines[-1]["artifact_key"] == "case_file"
        assert audit_lines[-1]["allowed"] is False
        assert audit_lines[-1]["restricted"] is True
    finally:
        _restore_env(original)


def test_claimed_reviewer_can_access_restricted_data_quality_json_and_audits(monkeypatch, tmp_path):
    original, client = _client_with_auth_env()
    try:
        artifact = tmp_path / "StrategyOS Data Quality Report.json"
        artifact.write_text(
            json.dumps(
                {
                    "ocr_required": [{"source_path": "scan.pdf", "ocr_status": {"required": True}}],
                    "unresolved_citations": [{"excerpt": "page 1 sensitive excerpt"}],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(api_module, "CONFIG", replace(api_module.CONFIG, output_root=tmp_path))
        monkeypatch.setattr(
            api_module.state_store,
            "get_run_detail",
            lambda run_id: {
                "run_id": run_id,
                "review_assignment": {
                    "claimed": True,
                    "claimed_by": "api-key:reviewer:a111",
                    "claimed_at": "2026-06-05T10:00:00Z",
                },
                "summary_json": {"artifacts": {"data_quality_json": str(artifact)}},
            },
        )

        response = client.get(
            "/reviewer/runs/run-1/artifacts/data_quality_json",
            headers=_auth_header("reviewer-a111"),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["preview_kind"] == "json"
        assert payload["preview_json"]["unresolved_citations"][0]["excerpt"] == "page 1 sensitive excerpt"
        audit_lines = _artifact_access_audit_lines(tmp_path)
        assert audit_lines[-1]["artifact_key"] == "data_quality_json"
        assert audit_lines[-1]["allowed"] is True
        assert audit_lines[-1]["restricted"] is True
    finally:
        _restore_env(original)


def test_run_artifact_preview_returns_json_payload(monkeypatch, tmp_path):
    output_root = tmp_path / "outputs"
    run_dir = output_root / "run-1"
    run_dir.mkdir(parents=True)
    artifact = run_dir / "summary.json"
    artifact.write_text('{"status":"ok"}', encoding="utf-8")

    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_OUTPUT_ROOT": str(output_root),
        }
    )
    try:
        client = TestClient(api_module.app)
        monkeypatch.setattr(
            api_module.state_store,
            "get_run_detail",
            lambda run_id: {
                "run_id": run_id,
                "summary_json": {"artifacts": {"summary": str(artifact)}},
            },
        )

        response = client.get(
            "/reviewer/runs/run-1/artifacts/summary",
            headers=_auth_header("reviewer-secret"),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["artifact_key"] == "summary"
        assert payload["scope"] == "run"
        assert payload["preview_kind"] == "json"
        assert payload["preview_json"]["status"] == "ok"
    finally:
        _restore_env(original)


def test_run_artifact_preview_uses_latest_local_summary_when_store_skipped(tmp_path):
    output_root = tmp_path / "outputs"

    original = _apply_env(
        {
            "DATABASE_URL": None,
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_OUTPUT_ROOT": str(output_root),
        }
    )
    client = TestClient(api_module.app)
    try:
        local = _write_local_review_summary(tmp_path)
        artifact = local["summary_path"].parent / "summary.json"
        artifact.write_text('{"status":"ok"}', encoding="utf-8")
        summary = json.loads(local["summary_path"].read_text(encoding="utf-8"))
        summary.setdefault("artifacts", {})["summary"] = str(artifact)
        local["summary_path"].write_text(json.dumps(summary, indent=2), encoding="utf-8")

        response = client.get(
            f"/reviewer/runs/{local['run_id']}/artifacts/summary",
            headers=_auth_header("operator-secret"),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["artifact_key"] == "summary"
        assert payload["preview_json"]["status"] == "ok"
    finally:
        _restore_env(original)


def test_checkpoint_artifact_preview_rejects_paths_outside_output_root(monkeypatch, tmp_path):
    output_root = tmp_path / "outputs"
    output_root.mkdir(parents=True)
    unsafe_artifact = tmp_path / "outside.md"
    unsafe_artifact.write_text("outside", encoding="utf-8")

    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_OUTPUT_ROOT": str(output_root),
        }
    )
    try:
        client = TestClient(api_module.app)
        monkeypatch.setattr(
            api_module.state_store,
            "get_checkpoint_detail",
            lambda checkpoint_id: {
                "checkpoint_id": checkpoint_id,
                "run_id": "run-1",
                "state_json": {"artifact_paths": {"case_file": str(unsafe_artifact)}},
            },
        )
        monkeypatch.setattr(
            api_module.state_store,
            "get_run_detail",
            lambda run_id: {
                "run_id": run_id,
                "review_assignment": {"claimed": False, "claimed_by": None, "claimed_at": None},
            },
        )

        response = client.get(
            "/reviewer/checkpoints/cp-1/artifacts/case_file",
            headers=_auth_header("reviewer-secret"),
        )

        assert response.status_code == 404
        assert "output boundary" in response.json()["detail"]
    finally:
        _restore_env(original)


def test_approve_run_records_reviewer_decision(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "latest_checkpoint",
            lambda run_id: {
                "checkpoint_id": "cp-1",
                "run_id": run_id,
                "stage": "awaiting_review",
                "status": "awaiting_review",
            },
        )
        captured = {}

        def fake_record_approval(*args):
            captured["args"] = args
            return {"approval_id": "ap-1", "decision": "approved", "run_id": args[0]}

        monkeypatch.setattr(
            api_module.state_store, "record_approval", fake_record_approval
        )

        response = client.post(
            "/reviewer/runs/run-1/approve",
            headers=_auth_header("reviewer-a111"),
            json={"comment": "ready"},
        )

        assert response.status_code == 200
        assert response.json()["decision"] == "approved"
        assert captured["args"][0] == "run-1"
        assert captured["args"][2] == "api-key:reviewer:a111"
        assert captured["args"][4] == "reviewer"
    finally:
        _restore_env(original)


def test_approve_run_returns_conflict_when_not_claimed(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "latest_checkpoint",
            lambda run_id: {
                "checkpoint_id": "cp-1",
                "run_id": run_id,
                "stage": "awaiting_review",
                "status": "awaiting_review",
            },
        )
        monkeypatch.setattr(
            api_module.state_store,
            "record_approval",
            lambda *args: {
                "status": "conflict",
                "reason": "Run 'run-1' must be claimed before a reviewer decision can be recorded.",
            },
        )

        response = client.post(
            "/reviewer/runs/run-1/approve",
            headers=_auth_header("reviewer-a111"),
            json={"comment": "ready"},
        )

        assert response.status_code == 409
        assert "must be claimed" in response.json()["detail"]
    finally:
        _restore_env(original)


def test_approve_run_updates_latest_local_summary_when_store_skipped(tmp_path):
    original = _apply_env(
        {
            "DATABASE_URL": None,
            "STRATEGYOS_OUTPUT_ROOT": str(tmp_path / "outputs"),
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-a111",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    client = TestClient(api_module.app)
    try:
        local = _write_local_review_summary(
            tmp_path, claimed_by="api-key:reviewer:a111"
        )

        response = client.post(
            f"/reviewer/runs/{local['run_id']}/approve",
            headers=_auth_header("reviewer-a111"),
            json={"comment": "ready"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["decision"] == "approved"
        assert payload["persistence"] == "local"

        summary = json.loads(local["summary_path"].read_text(encoding="utf-8"))
        assert summary["approval_status"] == "approved"
        assert summary["review_state"] == "approved"
        assert summary["resume_state"] == "ready"
        assert summary["review_decision"]["comment"] == "ready"
        assert summary["review_assignment"]["claimed"] is False
    finally:
        _restore_env(original)


def test_approve_run_returns_conflict_for_unclaimed_local_summary(tmp_path):
    original = _apply_env(
        {
            "DATABASE_URL": None,
            "STRATEGYOS_OUTPUT_ROOT": str(tmp_path / "outputs"),
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-a111",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    client = TestClient(api_module.app)
    try:
        local = _write_local_review_summary(tmp_path)

        response = client.post(
            f"/reviewer/runs/{local['run_id']}/approve",
            headers=_auth_header("reviewer-a111"),
            json={"comment": "ready"},
        )

        assert response.status_code == 409
        assert "must be claimed" in response.json()["detail"]
    finally:
        _restore_env(original)


def test_claim_run_updates_latest_local_summary_when_store_skipped(tmp_path):
    original = _apply_env(
        {
            "DATABASE_URL": None,
            "STRATEGYOS_OUTPUT_ROOT": str(tmp_path / "outputs"),
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-a111",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    client = TestClient(api_module.app)
    try:
        local = _write_local_review_summary(tmp_path)

        response = client.post(
            f"/reviewer/runs/{local['run_id']}/claim",
            headers=_auth_header("reviewer-a111"),
        )

        assert response.status_code == 200
        summary = json.loads(local["summary_path"].read_text(encoding="utf-8"))
        assert summary["review_assignment"]["claimed"] is True
        assert summary["review_assignment"]["claimed_by"] == "api-key:reviewer:a111"
    finally:
        _restore_env(original)


def test_resume_run_uses_latest_local_checkpoint_when_store_skipped(monkeypatch, tmp_path):
    original = _apply_env(
        {
            "DATABASE_URL": None,
            "STRATEGYOS_OUTPUT_ROOT": str(tmp_path / "outputs"),
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-a111",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    client = TestClient(api_module.app)
    try:
        local = _write_local_review_summary(tmp_path, approval_status="approved")
        approved_summary = json.loads(local["summary_path"].read_text(encoding="utf-8"))
        approved_summary["finance_kpi"] = {
            "derived_from": "deterministic_source_finance_kpi_engine",
            "components": {"revenue_actual": "385100000"},
        }
        approved_summary["calendar_agenda"] = {
            "status": "ready",
            "items": [{"date": "2026-07-22", "title": "Executive Committee"}],
        }
        approved_summary["source_pack"] = {
            "source_pack_id": "pack-81",
            "file_accounting": {
                "file_count": 81,
                "accounted_file_count": 81,
                "silent_omission_count": 0,
            },
        }
        local["summary_path"].write_text(json.dumps(approved_summary, indent=2), encoding="utf-8")
        captured = {}

        def fake_resume(run_id, checkpoint):
            captured["run_id"] = run_id
            captured["checkpoint"] = checkpoint
            return {
                "run_id": run_id,
                "status": "completed",
                "current_stage": "writer",
                "approval_status": "approved",
            }

        monkeypatch.setattr(api_module, "resume_reviewed_run", fake_resume)

        response = client.post(
            f"/operator/runs/{local['run_id']}/resume",
            headers=_auth_header("operator-secret"),
            json={},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        assert captured["run_id"] == local["run_id"]
        assert captured["checkpoint"]["persistence"] == "local"
        assert captured["checkpoint"]["state_json"]["current_stage"] == "awaiting_review"
        assert captured["checkpoint"]["summary_json"]["finance_kpi"]["derived_from"] == "deterministic_source_finance_kpi_engine"
        assert len(captured["checkpoint"]["summary_json"]["calendar_agenda"]["items"]) == 1
        assert captured["checkpoint"]["summary_json"]["source_pack"]["file_accounting"]["accounted_file_count"] == 81
    finally:
        _restore_env(original)


def test_resume_run_enriches_hosted_checkpoint_with_latest_approved_summary(monkeypatch, tmp_path):
    original = _apply_env(
        {
            "DATABASE_URL": None,
            "STRATEGYOS_OUTPUT_ROOT": str(tmp_path / "outputs"),
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    client = TestClient(api_module.app)
    try:
        local = _write_local_review_summary(tmp_path, approval_status="approved")
        approved_summary = json.loads(local["summary_path"].read_text(encoding="utf-8"))
        approved_summary["finance_kpi"] = {
            "derived_from": "deterministic_source_finance_kpi_engine",
            "components": {"revenue_actual": "385100000"},
        }
        approved_summary["calendar_agenda"] = {
            "status": "ready",
            "items": [{"date": "2026-07-22", "title": "Executive Committee"}],
        }
        approved_summary["source_pack"] = {
            "source_pack_id": "pack-81",
            "file_accounting": {
                "file_count": 81,
                "accounted_file_count": 81,
                "silent_omission_count": 0,
            },
        }
        local["summary_path"].write_text(json.dumps(approved_summary, indent=2), encoding="utf-8")
        hosted_checkpoint = dict(approved_summary["local_review_checkpoint"])
        hosted_checkpoint["checkpoint_id"] = "hosted-checkpoint-1"
        hosted_checkpoint["persistence"] = "postgres"
        hosted_checkpoint["summary_json"] = {
            "run_id": local["run_id"],
            "status": "awaiting_review",
        }
        captured = {}

        monkeypatch.setattr(
            api_module.state_store,
            "approval_status_for_run",
            lambda run_id: {
                "run_id": run_id,
                "approval_status": "approved",
                "run_status": "awaiting_review",
                "current_stage": "awaiting_review",
            },
        )
        monkeypatch.setattr(
            api_module.state_store,
            "latest_checkpoint",
            lambda run_id: hosted_checkpoint,
        )

        def fake_resume(run_id, checkpoint):
            captured["checkpoint"] = checkpoint
            return {
                "run_id": run_id,
                "status": "completed",
                "current_stage": "writer",
                "approval_status": "approved",
            }

        monkeypatch.setattr(api_module, "resume_reviewed_run", fake_resume)

        response = client.post(
            f"/operator/runs/{local['run_id']}/resume",
            headers=_auth_header("operator-secret"),
            json={},
        )

        assert response.status_code == 200
        assert captured["checkpoint"]["checkpoint_id"] == "hosted-checkpoint-1"
        assert captured["checkpoint"]["persistence"] == "postgres"
        assert captured["checkpoint"]["summary_json"]["finance_kpi"]["derived_from"] == "deterministic_source_finance_kpi_engine"
        assert captured["checkpoint"]["summary_json"]["calendar_agenda"]["items"][0]["title"] == "Executive Committee"
        assert captured["checkpoint"]["summary_json"]["source_pack"]["file_accounting"]["accounted_file_count"] == 81
    finally:
        _restore_env(original)


def test_unclaim_run_returns_conflict_when_claimed_by_another_reviewer(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "unclaim_pending_review",
            lambda run_id, reviewer_subject: {
                "status": "conflict",
                "reason": "Run 'run-1' is claimed by api-key:reviewer:a111; only the current reviewer can unclaim it.",
            },
        )

        response = client.post(
            "/reviewer/runs/run-1/unclaim",
            headers=_auth_header("reviewer-b222"),
        )

        assert response.status_code == 409
        assert "only the current reviewer can unclaim" in response.json()["detail"]
    finally:
        _restore_env(original)


def test_unclaim_run_returns_not_found_when_missing(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "unclaim_pending_review",
            lambda run_id, reviewer_subject: {"status": "missing", "run_id": run_id},
        )

        response = client.post(
            "/reviewer/runs/run-404/unclaim",
            headers=_auth_header("reviewer-a111"),
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Run 'run-404' was not found."
    finally:
        _restore_env(original)


def test_reject_run_forbids_operator(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "latest_checkpoint",
            lambda run_id: {"checkpoint_id": "cp-1", "run_id": run_id},
        )

        response = client.post(
            "/reviewer/runs/run-1/reject",
            headers=_auth_header("operator-secret"),
            json={"comment": "reject"},
        )

        assert response.status_code == 403
    finally:
        _restore_env(original)


def test_resume_run_requires_operator_role():
    original, client = _client_with_auth_env()
    try:
        response = client.post(
            "/operator/runs/run-1/resume",
            headers=_auth_header("reviewer-a111"),
            json={},
        )

        assert response.status_code == 403
    finally:
        _restore_env(original)


def test_resume_run_requires_approved_status(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "approval_status_for_run",
            lambda run_id: {"run_id": run_id, "approval_status": "pending"},
        )

        response = client.post(
            "/operator/runs/run-1/resume",
            headers=_auth_header("operator-secret"),
            json={},
        )

        assert response.status_code == 409
    finally:
        _restore_env(original)


def test_resume_run_rejects_completed_writer_state(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "approval_status_for_run",
            lambda run_id: {
                "run_id": run_id,
                "approval_status": "approved",
                "run_status": "completed",
                "current_stage": "writer",
            },
        )

        response = client.post(
            "/operator/runs/run-1/resume",
            headers=_auth_header("operator-secret"),
            json={},
        )

        assert response.status_code == 409
        assert "already completed" in response.json()["detail"]
    finally:
        _restore_env(original)


def test_resume_run_rejects_non_review_checkpoint(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "approval_status_for_run",
            lambda run_id: {
                "run_id": run_id,
                "approval_status": "approved",
                "run_status": "awaiting_review",
                "current_stage": "awaiting_review",
            },
        )
        monkeypatch.setattr(
            api_module.state_store,
            "latest_checkpoint",
            lambda run_id: {
                "checkpoint_id": "cp-1",
                "run_id": run_id,
                "stage": "writer",
                "state_json": {"dataset_root": "/tmp/data", "run_dir": "/tmp/run"},
            },
        )

        response = client.post(
            "/operator/runs/run-1/resume",
            headers=_auth_header("operator-secret"),
            json={},
        )

        assert response.status_code == 409
        assert "latest checkpoint" in response.json()["detail"]
    finally:
        _restore_env(original)


def test_resume_run_returns_resumed_summary(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "approval_status_for_run",
            lambda run_id: {
                "run_id": run_id,
                "approval_status": "approved",
                "run_status": "awaiting_review",
                "current_stage": "awaiting_review",
            },
        )
        monkeypatch.setattr(
            api_module.state_store,
            "latest_checkpoint",
            lambda run_id: {
                "checkpoint_id": "cp-1",
                "run_id": run_id,
                "stage": "awaiting_review",
                "state_json": {"dataset_root": "/tmp/data", "run_dir": "/tmp/run"},
            },
        )
        monkeypatch.setattr(
            api_module,
            "resume_reviewed_run",
            lambda run_id, checkpoint: {
                "run_id": run_id,
                "status": "completed",
                "checkpoint_id": checkpoint["checkpoint_id"],
            },
        )

        response = client.post(
            "/operator/runs/run-1/resume",
            headers=_auth_header("operator-secret"),
            json={},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "completed"
    finally:
        _restore_env(original)


def test_approve_run_updates_run_summary_pointer_metadata(monkeypatch, tmp_path: Path):
    original, client = _client_with_auth_env()
    try:
        run_dir = tmp_path / "outputs" / "StrategyOS MVP Run-20260608T120000Z"
        run_dir.mkdir(parents=True)
        summary_path = run_dir / "run_summary.json"
        summary_path.write_text(
            json.dumps(
                {
                    "run_id": "run-1",
                    "run_dir": str(run_dir),
                    "status": "awaiting_review",
                    "current_stage": "awaiting_review",
                    "requires_human_review": True,
                    "approval_status": "pending",
                    "run_outcome": "awaiting_review",
                    "deliverables_status": "paused_before_writer",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        config = replace(api_module.CONFIG, output_root=tmp_path / "outputs")
        api_module.CONFIG = config
        run_registry_module.CONFIG = config

        monkeypatch.setattr(
            api_module.state_store,
            "latest_checkpoint",
            lambda run_id: {
                "checkpoint_id": "cp-1",
                "run_id": run_id,
                "stage": "awaiting_review",
                "status": "awaiting_review",
                "state_json": {"run_dir": str(run_dir)},
            },
        )
        monkeypatch.setattr(
            api_module.state_store,
            "record_approval",
            lambda *args, **kwargs: {
                "decision": "approved",
                "comment": "go",
                "reviewer": "api-key:reviewer:a111",
                "reviewer_subject": "api-key:reviewer:a111",
                "created_at": "2026-06-08T12:05:00Z",
            },
        )

        response = client.post(
            "/reviewer/runs/run-1/approve",
            headers=_auth_header("reviewer-a111"),
            json={"comment": "go"},
        )

        assert response.status_code == 200
        updated = json.loads(summary_path.read_text(encoding="utf-8"))
        assert updated["approval_status"] == "approved"
        assert updated["review_state"] == "approved"
        assert updated["resume_state"] == "ready"
        assert updated["resume_ready"] is True
        assert updated["pointer_metadata"]["latest"]["pointer_type"] == "latest"
        assert updated["pointer_metadata"]["current"]["pointer_type"] == "current"
        assert (tmp_path / "outputs" / "latest_run_pointer.json").exists()
        assert (tmp_path / "outputs" / "current_run_pointer.json").exists()
    finally:
        _restore_env(original)


def test_vector_search_returns_ranked_hits_for_selected_run(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module,
            "search_run_vectors",
            lambda run_id, query, limit=5: {
                "status": "ready",
                "run_id": run_id,
                "query": query,
                "results": [
                    {
                        "score": 0.991,
                        "finding_id": "F-002",
                        "title": "Duplicate payment for invoice INV-2026-0341",
                        "pattern_type": "duplicate_payment",
                        "vendor_name": "Premier Packaging LLC",
                        "source": "/tmp/StrategyOS Knowledge Graph.json",
                    }
                ],
                "limit": limit,
            },
        )

        response = client.get(
            "/data/vector-search?query=duplicate%20payment&run_id=run-77&limit=1",
            headers=_auth_header("reviewer-a111"),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert payload["run_id"] == "run-77"
        assert payload["results"][0]["finding_id"] == "F-002"
    finally:
        _restore_env(original)


def test_vector_search_forwards_investigation_filters(monkeypatch):
    original, client = _client_with_auth_env()
    captured = {}
    try:
        def fake_search(run_id, query, limit=5, **filters):
            captured.update(
                {
                    "run_id": run_id,
                    "query": query,
                    "limit": limit,
                    "filters": filters,
                }
            )
            return {
                "status": "ready",
                "run_id": run_id,
                "query": query,
                "filters": filters,
                "results": [],
            }

        monkeypatch.setattr(api_module, "search_run_vectors", fake_search)

        response = client.get(
            "/data/vector-search?query=invoice&run_id=run-77&point_type=citation"
            "&pattern_type=duplicate_payment&vendor_name=Premier%20Packaging%20LLC"
            "&confidence=HIGH&source_path=uploads%2Fap_ledger.csv&finding_id=F-002",
            headers=_auth_header("reviewer-a111"),
        )

        assert response.status_code == 200
        assert captured["run_id"] == "run-77"
        assert captured["filters"]["point_type"] == "citation"
        assert captured["filters"]["vendor_name"] == "Premier Packaging LLC"
        assert captured["filters"]["source_path"] == "uploads/ap_ledger.csv"
    finally:
        _restore_env(original)


def test_evidence_preview_returns_stored_citation_context(monkeypatch):
    original, client = _client_with_auth_env()
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "evidence_preview_for_run",
            lambda run_id, **_: {
                "status": "ok",
                "run_id": run_id,
                "finding_id": "F-002",
                "citation_id": "citation-1",
                "source_path": "uploads/ap_ledger.csv",
                "locator": "row 341",
                "preview_kind": "text",
                "excerpt": "Invoice INV-2026-0341 was paid twice.",
                "resolved_payload": {},
            },
        )

        response = client.get(
            "/data/evidence-preview?run_id=run-77&finding_id=F-002",
            headers=_auth_header("reviewer-a111"),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_id"] == "run-77"
        assert payload["finding_id"] == "F-002"
        assert payload["source_path"] == "uploads/ap_ledger.csv"
        assert payload["excerpt"] == "Invoice INV-2026-0341 was paid twice."
    finally:
        _restore_env(original)


def test_evidence_preview_uses_latest_local_citation_audit_when_store_skipped(tmp_path):
    output_root = tmp_path / "outputs"

    original = _apply_env(
        {
            "DATABASE_URL": None,
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_OUTPUT_ROOT": str(output_root),
        }
    )
    client = TestClient(api_module.app)
    try:
        local = _write_local_review_summary(tmp_path)
        citation_audit = local["summary_path"].parent / "StrategyOS Citation Audit.json"
        citation_audit.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "finding_id": "F-002",
                            "pattern_type": "duplicate_payment",
                            "source_path": "uploads/ap_ledger.csv",
                            "source_hash": "hash-1",
                            "locator": "row 341",
                            "excerpt": "Invoice INV-2026-0341 was paid twice.",
                            "resolved": True,
                            "hash_match": True,
                            "resolved_payload": {"row": {"Invoice_ID": "INV-2026-0341"}},
                        }
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        summary = json.loads(local["summary_path"].read_text(encoding="utf-8"))
        summary.setdefault("artifacts", {})["citation_audit"] = str(citation_audit)
        summary["local_review_checkpoint"]["state_json"]["findings"] = [
            {
                "finding_id": "F-002",
                "title": "Duplicate payment",
                "pattern_type": "duplicate_payment",
                "vendor_id": "V-1",
                "vendor_name": "Vendor One",
                "confidence": "HIGH",
            }
        ]
        local["summary_path"].write_text(json.dumps(summary, indent=2), encoding="utf-8")

        response = client.get(
            f"/data/evidence-preview?run_id={local['run_id']}&finding_id=F-002",
            headers=_auth_header("reviewer-secret"),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_id"] == local["run_id"]
        assert payload["finding_id"] == "F-002"
        assert payload["source_path"] == "uploads/ap_ledger.csv"
        assert payload["excerpt"] == "Invoice INV-2026-0341 was paid twice."
        assert payload["vendor_name"] == "Vendor One"
    finally:
        _restore_env(original)


def test_resume_run_completes_latest_local_summary_without_circular_reference(monkeypatch, tmp_path):
    original = _apply_env(
        {
            "DATABASE_URL": None,
            "STRATEGYOS_OUTPUT_ROOT": str(tmp_path / "outputs"),
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-a111",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    client = TestClient(api_module.app)
    try:
        local = _write_local_review_summary(tmp_path, approval_status="approved")
        approved_summary = json.loads(local["summary_path"].read_text(encoding="utf-8"))
        approved_summary["finance_kpi"] = {
            "derived_from": "deterministic_source_finance_kpi_engine",
            "components": {"revenue_actual": "385100000"},
        }
        approved_summary["calendar_agenda"] = {
            "status": "ready",
            "items": [{"date": "2026-07-22", "title": "Executive Committee"}],
        }
        approved_summary["source_pack"] = {
            "source_pack_id": "pack-81",
            "file_accounting": {
                "file_count": 81,
                "accounted_file_count": 81,
                "silent_omission_count": 0,
            },
        }
        local["summary_path"].write_text(json.dumps(approved_summary, indent=2), encoding="utf-8")

        class FakeBundle:
            pass

        class FakeWriter:
            def write_all(self, bundle, findings, audit_events, run_dir):
                case_file = run_dir / "Final consolidated case file.md"
                case_file.write_text("# Final consolidated case file\n", encoding="utf-8")
                return {"case_file": case_file}

        monkeypatch.setattr(
            api_module.state_store,
            "approval_status_for_run",
            lambda run_id: {
                "run_id": run_id,
                "approval_status": "approved",
                "run_status": "awaiting_review",
                "current_stage": "awaiting_review",
            },
        )
        monkeypatch.setattr(reviewer_runtime, "load_dataset", lambda dataset_root: FakeBundle())
        monkeypatch.setattr(reviewer_runtime, "CaseFileWriter", FakeWriter)

        response = client.post(
            f"/operator/runs/{local['run_id']}/resume",
            headers=_auth_header("operator-secret"),
            json={},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["finance_kpi"]["derived_from"] == "deterministic_source_finance_kpi_engine"
        assert payload["calendar_agenda"]["items"][0]["title"] == "Executive Committee"
        assert payload["source_pack"]["file_accounting"]["accounted_file_count"] == 81
        updated = json.loads(local["summary_path"].read_text(encoding="utf-8"))
        assert updated["status"] == "completed"
        assert updated["current_stage"] == "writer"
        assert updated["calendar_agenda"]["status"] == "ready"
        assert updated["resume"]["checkpoint"]["checkpoint_id"] is None
    finally:
        _restore_env(original)
