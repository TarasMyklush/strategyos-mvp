import copy
import os
from pathlib import Path

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
import strategyos_mvp.reviewer_runtime as reviewer_runtime
import strategyos_mvp.run_registry as run_registry_module
import strategyos_mvp.runtime_governance as runtime_governance
import strategyos_mvp.state_store as state_store
import strategyos_mvp.workflow as workflow_module
from strategyos_mvp.config import load_config
from strategyos_mvp.models import Finding


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
    run_registry_module.CONFIG = config
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
    run_registry_module.CONFIG = config
    state_store.CONFIG = config


def _auth_header(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _sample_finding() -> Finding:
    return Finding(
        finding_id="F-001",
        title="Test finding",
        pattern_type="duplicate_payment",
        vendor_id="V-001",
        vendor_name="Vendor",
        leakage_sar=100.0,
        recoverable_sar=80.0,
        recoverable_usd=21.33,
        confidence="HIGH",
        classification="test",
        rationale="test",
        remediation="test",
        status="locked",
    )


class InMemoryReviewStore:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}
        self.checkpoints: dict[str, list[dict]] = {}
        self.approvals: dict[str, list[dict]] = {}
        self.run_counter = 0
        self.checkpoint_counter = 0
        self.approval_counter = 0

    def create_run(self, summary_seed: dict, *, requires_human_review: bool) -> dict:
        self.run_counter += 1
        run_id = f"run-{self.run_counter}"
        record = {
            "run_id": run_id,
            "status": str(summary_seed.get("status") or "running"),
            "current_stage": str(summary_seed.get("current_stage") or "created"),
            "requires_human_review": requires_human_review,
            "approved_at": None,
            "approved_by": None,
            "summary_json": dict(summary_seed),
            "approval_status": "pending" if requires_human_review else "not_required",
        }
        self.runs[run_id] = record
        return dict(record)

    def persist_checkpoint(
        self,
        run_id: str,
        stage: str,
        status: str,
        state: dict,
        summary: dict | None = None,
    ) -> dict:
        self.checkpoint_counter += 1
        checkpoint = {
            "checkpoint_id": f"cp-{self.checkpoint_counter}",
            "run_id": run_id,
            "stage": stage,
            "status": status,
            "state_json": copy.deepcopy(state),
            "summary_json": copy.deepcopy(summary or {}),
        }
        self.checkpoints.setdefault(run_id, []).append(checkpoint)
        self.runs[run_id]["status"] = status
        self.runs[run_id]["current_stage"] = stage
        return dict(checkpoint)

    def latest_checkpoint(self, run_id: str) -> dict | None:
        items = self.checkpoints.get(run_id, [])
        if not items:
            return None
        return dict(items[-1])

    def record_approval(
        self,
        run_id: str,
        checkpoint_id: str,
        reviewer: str,
        reviewer_subject: str,
        reviewer_role: str,
        decision: str,
        comment: str | None,
        payload: dict,
    ) -> dict:
        self.approval_counter += 1
        approval = {
            "approval_id": f"ap-{self.approval_counter}",
            "run_id": run_id,
            "checkpoint_id": checkpoint_id,
            "reviewer": reviewer,
            "reviewer_subject": reviewer_subject,
            "reviewer_role": reviewer_role,
            "decision": decision,
            "comment": comment,
            "payload": payload,
            "run_status": {
                "approved": "approved",
                "rejected": "rejected",
            }.get(decision, "awaiting_review"),
            "current_stage": self.runs[run_id]["current_stage"],
        }
        self.approvals.setdefault(run_id, []).append(approval)
        self.runs[run_id]["status"] = approval["run_status"]
        if decision == "approved":
            self.runs[run_id]["approved_by"] = reviewer
        return dict(approval)

    def approval_status_for_run(self, run_id: str) -> dict:
        run = dict(self.runs[run_id])
        latest_approval = None
        approval_status = "pending" if run["requires_human_review"] else "not_required"
        if self.approvals.get(run_id):
            latest_approval = dict(self.approvals[run_id][-1])
            approval_status = str(latest_approval["decision"])
        return {
            "run_id": run_id,
            "run_status": run["status"],
            "current_stage": run["current_stage"],
            "requires_human_review": run["requires_human_review"],
            "approved_at": run["approved_at"],
            "approved_by": run["approved_by"],
            "approval_status": approval_status,
            "latest_approval": latest_approval,
        }

    def update_run_summary(self, run_id: str, summary: dict) -> dict:
        self.runs[run_id]["status"] = str(
            summary.get("status") or self.runs[run_id]["status"]
        )
        self.runs[run_id]["current_stage"] = str(
            summary.get("current_stage") or self.runs[run_id]["current_stage"]
        )
        self.runs[run_id]["summary_json"] = dict(summary)
        self.runs[run_id]["approved_by"] = summary.get("approved_by")
        self.runs[run_id]["approved_at"] = summary.get("approved_at")
        return {
            "run_id": run_id,
            "status": self.runs[run_id]["status"],
            "current_stage": self.runs[run_id]["current_stage"],
            "requires_human_review": self.runs[run_id]["requires_human_review"],
            "approved_at": self.runs[run_id]["approved_at"],
            "approved_by": self.runs[run_id]["approved_by"],
        }


def _install_fake_workflow(monkeypatch, writer_called: dict[str, int]):
    class FakeEvidence:
        def save_manifest(self, path: Path) -> None:
            path.write_text("{}", encoding="utf-8")

    class FakeBundle:
        def __init__(self) -> None:
            self.evidence = FakeEvidence()

    class FakeAnalyst:
        def draft_findings(self, bundle):
            return [_sample_finding()]

    class FakeAuditor:
        def challenge_findings(self, findings):
            return []

    class FakeEvidenceQA:
        def write_reports(self, bundle, findings, run_dir):
            qa_path = run_dir / "qa.md"
            qa_path.write_text("qa", encoding="utf-8")
            return {"qa": qa_path}

    class FakeKG:
        def build(self, bundle, findings, run_dir):
            kg_path = run_dir / "kg.json"
            kg_path.write_text("{}", encoding="utf-8")
            return kg_path

    class FakeWriter:
        def write_all(self, bundle, findings, audit_events, run_dir):
            writer_called["count"] += 1
            case_file = run_dir / "case.md"
            case_file.write_text("case", encoding="utf-8")
            return {"case_file": case_file}

    monkeypatch.setattr(
        workflow_module, "load_dataset", lambda dataset_root: FakeBundle()
    )
    monkeypatch.setattr(workflow_module, "FinanceAnalystAgent", FakeAnalyst)
    monkeypatch.setattr(workflow_module, "FinanceAuditorAgent", FakeAuditor)
    monkeypatch.setattr(workflow_module, "EvidenceQAAgent", FakeEvidenceQA)
    monkeypatch.setattr(workflow_module, "KnowledgeGraphAgent", FakeKG)
    monkeypatch.setattr(workflow_module, "CaseFileWriter", FakeWriter)
    monkeypatch.setattr(
        reviewer_runtime, "load_dataset", lambda dataset_root: FakeBundle()
    )
    monkeypatch.setattr(reviewer_runtime, "CaseFileWriter", FakeWriter)


def _install_store(monkeypatch, store: InMemoryReviewStore):
    monkeypatch.setattr(runtime_governance, "create_run", store.create_run)
    monkeypatch.setattr(
        runtime_governance, "persist_checkpoint", store.persist_checkpoint
    )
    monkeypatch.setattr(
        api_module.state_store, "latest_checkpoint", store.latest_checkpoint
    )
    monkeypatch.setattr(
        api_module.state_store, "record_approval", store.record_approval
    )
    monkeypatch.setattr(
        api_module.state_store, "approval_status_for_run", store.approval_status_for_run
    )
    monkeypatch.setattr(
        reviewer_runtime, "persist_checkpoint", store.persist_checkpoint
    )
    monkeypatch.setattr(
        reviewer_runtime, "update_run_summary", store.update_run_summary
    )


def _run_until_review(monkeypatch, tmp_path: Path):
    writer_called = {"count": 0}
    store = InMemoryReviewStore()
    _install_fake_workflow(monkeypatch, writer_called)
    _install_store(monkeypatch, store)

    dataset_root = tmp_path / "dataset"
    run_dir = tmp_path / "run"
    dataset_root.mkdir()
    run_dir.mkdir()

    governance = runtime_governance.RuntimeGovernance(
        dataset_root=dataset_root,
        run_dir=run_dir,
        requires_human_review=True,
        stop_before_writer=True,
    )
    workflow = workflow_module.build_workflow(
        checkpoint_handler=governance.checkpoint,
        stop_before_writer=governance.stop_before_writer,
    )
    result = workflow.invoke(governance.initial_state())
    return result, store, writer_called, run_dir


def test_governed_review_flow_approve_then_resume_runs_writer(monkeypatch, tmp_path):
    result, store, writer_called, run_dir = _run_until_review(monkeypatch, tmp_path)
    assert result["current_stage"] == "awaiting_review"
    assert result["workflow_status"] == "awaiting_review"
    assert writer_called["count"] == 0

    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    client = TestClient(api_module.app)
    try:
        run_id = result["run_id"]
        approve_response = client.post(
            f"/reviewer/runs/{run_id}/approve",
            headers=_auth_header("reviewer-secret"),
            json={"comment": "ready for writer"},
        )
        assert approve_response.status_code == 200
        assert approve_response.json()["decision"] == "approved"

        resume_response = client.post(
            f"/operator/runs/{run_id}/resume",
            headers=_auth_header("operator-secret"),
            json={},
        )
        assert resume_response.status_code == 200

        payload = resume_response.json()
        assert payload["status"] == "completed"
        assert payload["current_stage"] == "writer"
        assert payload["approval_status"] == "approved"
        assert payload["review_state"] == "approved"
        assert payload["resume_state"] == "completed"
        assert writer_called["count"] == 1
        assert store.latest_checkpoint(run_id)["stage"] == "writer"
        assert (run_dir / "case.md").exists()
    finally:
        _restore_env(original)


def test_governed_review_flow_reject_blocks_resume(monkeypatch, tmp_path):
    result, store, writer_called, _ = _run_until_review(monkeypatch, tmp_path)
    assert result["current_stage"] == "awaiting_review"
    assert writer_called["count"] == 0

    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    client = TestClient(api_module.app)
    try:
        run_id = result["run_id"]
        reject_response = client.post(
            f"/reviewer/runs/{run_id}/reject",
            headers=_auth_header("reviewer-secret"),
            json={"comment": "needs more evidence"},
        )
        assert reject_response.status_code == 200
        assert reject_response.json()["decision"] == "rejected"
        assert store.approval_status_for_run(run_id)["approval_status"] == "rejected"

        resume_response = client.post(
            f"/operator/runs/{run_id}/resume",
            headers=_auth_header("operator-secret"),
            json={},
        )
        assert resume_response.status_code == 409
        assert writer_called["count"] == 0
        assert store.latest_checkpoint(run_id)["stage"] == "awaiting_review"
    finally:
        _restore_env(original)
