import json
from pathlib import Path
from types import SimpleNamespace

import strategyos_mvp.run_poc as run_poc_module
import strategyos_mvp.run_registry as run_registry_module
from strategyos_mvp.config import RunPolicyConfig
from strategyos_mvp.models import AuditEvent


def _challenge_event(finding_id: str, round_no: int = 1) -> AuditEvent:
    return AuditEvent(
        round_no=round_no,
        actor="Finance Auditor",
        finding_id=finding_id,
        action="challenge",
        detail="Acceptance-sensitive verification sample required before lock.",
        challenge="Acceptance-sensitive verification sample required before lock.",
        status="challenged",
        confidence_before="HIGH",
        confidence_after="HIGH",
    )


def test_run_strategyos_workflow_materializes_ping_pong_audit_log(monkeypatch, tmp_path: Path):
    output_root = tmp_path / "outputs"
    run_poc_module.CONFIG = SimpleNamespace(
        require_human_review=True,
        database_url=None,
        sync_artifacts=False,
        object_store=SimpleNamespace(enabled=False),
        run_policy=RunPolicyConfig(mode="sovereign", approved_external_modes=()),
        model_provider_enabled=False,
        batch_apis_enabled=False,
        hosted_ocr_vision_enabled=False,
        ocr_engine="tesseract",
        tenant_slug="test-tenant",
        output_root=output_root,
    )
    run_registry_module.CONFIG = run_poc_module.CONFIG

    class FakeGovernance:
        def __init__(self, *, dataset_root, source_pack_id=None, run_dir, requires_human_review):
            self.dataset_root = dataset_root
            self.source_pack_id = source_pack_id
            self.run_dir = run_dir
            self.requires_human_review = requires_human_review
            self.checkpoint = lambda stage, state: state
            self.stop_before_writer = True

        def initial_state(self):
            return {
                "dataset_root": self.dataset_root,
                "run_dir": self.run_dir,
                "run_id": "run-123",
                "workflow_status": "running",
                "current_stage": "created",
                "requires_human_review": self.requires_human_review,
                "approval_status": "pending",
                "checkpoints": [],
            }

    class FakeWorkflow:
        runtime_metadata = {"actual_backend": "langgraph"}

        def invoke(self, state):
            return {
                **state,
                "workflow_status": "awaiting_review",
                "current_stage": "awaiting_review",
                "audit_events": [
                    _challenge_event("F-001"),
                    _challenge_event("F-002"),
                    _challenge_event("F-003"),
                    _challenge_event("F-004"),
                ],
                "audit_verification": {
                    "passed": True,
                    "required_challenged_findings": 4,
                    "actual_challenged_findings": 4,
                    "challenged_finding_ids": ["F-001", "F-002", "F-003", "F-004"],
                },
                "artifacts": {},
                "findings": [],
                "bundle": None,
            }

    monkeypatch.setattr(run_poc_module, "RuntimeGovernance", FakeGovernance)
    monkeypatch.setattr(run_poc_module, "build_workflow", lambda **_: FakeWorkflow())
    monkeypatch.setattr(
        run_poc_module,
        "persist_run_summary",
        lambda *args, **kwargs: {"run_id": kwargs.get("run_id")},
    )
    monkeypatch.setattr(
        run_poc_module,
        "sync_knowledge_graph",
        lambda **_: {"status": "skipped"},
    )
    monkeypatch.setattr(
        run_poc_module,
        "sync_findings_vector_store",
        lambda **_: {"status": "skipped"},
    )

    run_dir = tmp_path / "run"
    summary = run_poc_module.run_strategyos_workflow(
        dataset=tmp_path,
        run_dir=run_dir,
        skip_prepare=True,
    )

    audit_log_path = Path(summary["artifacts"]["audit_log"])
    assert audit_log_path.exists()
    assert summary["audit_event_count"] == 8
    assert summary["audit_verification"]["actual_challenged_findings"] == 4
    assert summary["run_policy"]["mode"] == "sovereign"
    assert summary["external_modes"]["object_storage_sync"]["approved"] is False
    payload = audit_log_path.read_text(encoding="utf-8")
    assert payload.count('"action": "challenge"') == 4
    assert "object_storage_sync" in payload
    assert "model_provider_use" in payload
    assert "batch_apis" in payload
    assert "hosted_ocr_vision" in payload


def test_pending_run_uses_immutable_run_dir_without_replacing_published_pointer(
    monkeypatch, tmp_path: Path
):
    output_root = tmp_path / "outputs"
    base_run_dir = output_root / "StrategyOS MVP Run"
    pointer_path = output_root / "latest_run_pointer.json"
    current_pointer_path = output_root / "current_run_pointer.json"
    run_poc_module.CONFIG = SimpleNamespace(
        require_human_review=True,
        database_url=None,
        sync_artifacts=False,
        object_store=SimpleNamespace(enabled=False),
        run_policy=RunPolicyConfig(mode="sovereign", approved_external_modes=()),
        model_provider_enabled=False,
        batch_apis_enabled=False,
        hosted_ocr_vision_enabled=False,
        ocr_engine="tesseract",
        tenant_slug="test-tenant",
        output_root=output_root,
        default_run_dir=base_run_dir,
    )
    run_registry_module.CONFIG = run_poc_module.CONFIG

    class FakeGovernance:
        def __init__(self, *, dataset_root, source_pack_id=None, run_dir, requires_human_review):
            self.dataset_root = dataset_root
            self.source_pack_id = source_pack_id
            self.run_dir = run_dir
            self.requires_human_review = requires_human_review
            self.checkpoint = lambda stage, state: state
            self.stop_before_writer = True

        def initial_state(self):
            return {
                "dataset_root": self.dataset_root,
                "run_dir": self.run_dir,
                "run_id": "run-immutable",
                "workflow_status": "awaiting_review",
                "current_stage": "awaiting_review",
                "requires_human_review": self.requires_human_review,
                "approval_status": "pending",
                "checkpoints": [],
            }

    class FakeWorkflow:
        runtime_metadata = {"actual_backend": "local"}

        def invoke(self, state):
            return {
                **state,
                "artifacts": {},
                "findings": [],
                "audit_events": [],
                "audit_verification": {},
                "bundle": None,
            }

    monkeypatch.setattr(run_poc_module, "RuntimeGovernance", FakeGovernance)
    monkeypatch.setattr(run_poc_module, "build_workflow", lambda **_: FakeWorkflow())
    monkeypatch.setattr(
        run_poc_module,
        "persist_run_summary",
        lambda *args, **kwargs: {"status": "skipped", "run_id": kwargs.get("run_id")},
    )
    monkeypatch.setattr(run_poc_module, "sync_knowledge_graph", lambda **_: {"status": "skipped"})
    monkeypatch.setattr(
        run_poc_module, "sync_findings_vector_store", lambda **_: {"status": "skipped"}
    )

    summary = run_poc_module.run_strategyos_workflow(
        dataset=tmp_path,
        run_dir=base_run_dir,
        skip_prepare=True,
    )

    assert Path(summary["run_dir"]).name.startswith("StrategyOS MVP Run-")
    assert Path(summary["run_dir"]) != base_run_dir
    assert summary["deliverables_status"] == "paused_before_writer"
    assert summary["run_outcome"] == "awaiting_review"
    assert summary["review_state"] == "awaiting_decision"
    assert summary["resume_state"] == "blocked_pending_review"
    assert not pointer_path.exists()
    assert current_pointer_path.exists()
    assert summary["latest_pointer"]["promoted"] is False
    assert summary["latest_pointer"]["candidate_run_id"] == "run-immutable"
    assert summary["pointer_metadata"]["current"]["pointer_type"] == "current"
    assert summary["pointer_metadata"]["latest"]["pointer_type"] == "latest"


def test_completed_approved_run_is_promoted_to_executive_pointer(monkeypatch, tmp_path: Path):
    output_root = tmp_path / "outputs"
    run_dir = output_root / "StrategyOS MVP Run-20260608T120000Z"
    run_dir.mkdir(parents=True)
    summary_path = run_dir / "run_summary.json"
    summary = {
        "run_id": "run-approved",
        "run_dir": str(run_dir),
        "status": "completed",
        "requires_human_review": True,
        "approval_status": "approved",
        "run_outcome": "completed",
        "deliverables_status": "published",
    }
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    monkeypatch.setattr(
        run_registry_module,
        "CONFIG",
        SimpleNamespace(output_root=output_root),
    )

    pointers = run_registry_module.update_run_pointers(summary, summary_path)

    assert pointers["latest"]["run_id"] == "run-approved"
    assert pointers["current"]["run_id"] == "run-approved"
    assert run_registry_module.load_latest_run_summary()["run_id"] == "run-approved"
    assert run_registry_module.load_current_run_summary()["run_id"] == "run-approved"


def test_pending_legacy_latest_pointer_recovers_previous_approved_packet(
    monkeypatch, tmp_path: Path
):
    output_root = tmp_path / "outputs"
    approved_dir = output_root / "StrategyOS MVP Run-20260607T120000Z"
    pending_dir = output_root / "StrategyOS MVP Run-20260608T120000Z"
    approved_dir.mkdir(parents=True)
    pending_dir.mkdir(parents=True)
    approved_path = approved_dir / "run_summary.json"
    pending_path = pending_dir / "run_summary.json"
    approved_path.write_text(
        json.dumps(
            {
                "run_id": "run-approved",
                "run_dir": str(approved_dir),
                "status": "completed",
                "requires_human_review": True,
                "approval_status": "approved",
                "run_outcome": "completed",
                "deliverables_status": "published",
            }
        ),
        encoding="utf-8",
    )
    pending_summary = {
        "run_id": "run-pending",
        "run_dir": str(pending_dir),
        "status": "awaiting_review",
        "requires_human_review": True,
        "approval_status": "pending",
        "run_outcome": "awaiting_review",
        "deliverables_status": "paused_before_writer",
    }
    pending_path.write_text(json.dumps(pending_summary), encoding="utf-8")
    monkeypatch.setattr(
        run_registry_module,
        "CONFIG",
        SimpleNamespace(output_root=output_root),
    )
    run_registry_module.update_latest_run_pointer(pending_summary, pending_path)

    recovered = run_registry_module.load_latest_run_summary()

    assert recovered["run_id"] == "run-approved"
    assert recovered["latest_pointer"]["recovered_from_publication_gate"] is True


def test_run_strategyos_workflow_does_not_fail_when_persistence_fails(
    monkeypatch, tmp_path: Path
):
    output_root = tmp_path / "outputs"
    pointer_path = output_root / "latest_run_pointer.json"
    current_pointer_path = output_root / "current_run_pointer.json"
    run_poc_module.CONFIG = SimpleNamespace(
        require_human_review=True,
        database_url="postgresql://example/db",
        sync_artifacts=False,
        object_store=SimpleNamespace(enabled=False),
        run_policy=RunPolicyConfig(mode="sovereign", approved_external_modes=()),
        model_provider_enabled=False,
        batch_apis_enabled=False,
        hosted_ocr_vision_enabled=False,
        ocr_engine="tesseract",
        tenant_slug="test-tenant",
        output_root=output_root,
    )
    run_registry_module.CONFIG = run_poc_module.CONFIG

    class FakeGovernance:
        def __init__(self, *, dataset_root, source_pack_id=None, run_dir, requires_human_review):
            self.dataset_root = dataset_root
            self.source_pack_id = source_pack_id
            self.run_dir = run_dir
            self.requires_human_review = requires_human_review
            self.checkpoint = lambda stage, state: state
            self.stop_before_writer = True

        def initial_state(self):
            return {
                "dataset_root": self.dataset_root,
                "run_dir": self.run_dir,
                "run_id": "run-persist-fails",
                "workflow_status": "awaiting_review",
                "current_stage": "awaiting_review",
                "requires_human_review": self.requires_human_review,
                "approval_status": "pending",
                "checkpoints": [],
            }

    class FakeWorkflow:
        runtime_metadata = {"actual_backend": "local"}

        def invoke(self, state):
            return {
                **state,
                "artifacts": {},
                "findings": [],
                "audit_events": [],
                "audit_verification": {},
                "bundle": None,
            }

    def fail_persistence(*_args, **_kwargs):
        raise RuntimeError("database constraint failed")

    monkeypatch.setattr(run_poc_module, "RuntimeGovernance", FakeGovernance)
    monkeypatch.setattr(run_poc_module, "build_workflow", lambda **_: FakeWorkflow())
    monkeypatch.setattr(run_poc_module, "persist_run_summary", fail_persistence)
    monkeypatch.setattr(run_poc_module, "sync_knowledge_graph", lambda **_: {"status": "skipped"})
    monkeypatch.setattr(
        run_poc_module, "sync_findings_vector_store", lambda **_: {"status": "skipped"}
    )

    summary = run_poc_module.run_strategyos_workflow(
        dataset=tmp_path,
        run_dir=output_root / "StrategyOS MVP Run",
        skip_prepare=True,
    )

    assert summary["run_id"] == "run-persist-fails"
    assert summary["state_store"]["status"] == "failed"
    assert summary["state_store"]["error_type"] == "RuntimeError"
    assert "database constraint failed" in summary["state_store"]["reason"]
    assert not pointer_path.exists()
    assert current_pointer_path.exists()


def test_run_strategyos_workflow_gates_object_storage_sync_until_policy_approval(
    monkeypatch, tmp_path: Path
):
    output_root = tmp_path / "outputs"
    run_poc_module.CONFIG = SimpleNamespace(
        require_human_review=True,
        database_url=None,
        sync_artifacts=False,
        object_store=SimpleNamespace(enabled=True),
        run_policy=RunPolicyConfig(mode="sovereign", approved_external_modes=()),
        model_provider_enabled=False,
        batch_apis_enabled=False,
        hosted_ocr_vision_enabled=False,
        ocr_engine="tesseract",
        tenant_slug="test-tenant",
        output_root=output_root,
    )
    run_registry_module.CONFIG = run_poc_module.CONFIG

    class FakeGovernance:
        def __init__(self, *, dataset_root, source_pack_id=None, run_dir, requires_human_review):
            self.dataset_root = dataset_root
            self.source_pack_id = source_pack_id
            self.run_dir = run_dir
            self.requires_human_review = requires_human_review
            self.checkpoint = lambda stage, state: state
            self.stop_before_writer = True

        def initial_state(self):
            return {
                "dataset_root": self.dataset_root,
                "run_dir": self.run_dir,
                "run_id": "run-sync-gated",
                "workflow_status": "awaiting_review",
                "current_stage": "awaiting_review",
                "requires_human_review": self.requires_human_review,
                "approval_status": "pending",
                "checkpoints": [],
                "artifacts": {},
            }

    class FakeWorkflow:
        runtime_metadata = {"actual_backend": "local"}

        def invoke(self, state):
            return {**state, "artifacts": {}, "findings": [], "audit_events": [], "audit_verification": {}, "bundle": None}

    sync_called = {"value": False}
    monkeypatch.setattr(run_poc_module, "RuntimeGovernance", FakeGovernance)
    monkeypatch.setattr(run_poc_module, "build_workflow", lambda **_: FakeWorkflow())
    monkeypatch.setattr(
        run_poc_module,
        "persist_run_summary",
        lambda *args, **kwargs: {"status": "skipped", "run_id": kwargs.get("run_id")},
    )
    monkeypatch.setattr(run_poc_module, "sync_knowledge_graph", lambda **_: {"status": "skipped"})
    monkeypatch.setattr(run_poc_module, "sync_findings_vector_store", lambda **_: {"status": "skipped"})
    monkeypatch.setattr(
        run_poc_module,
        "sync_artifact_files",
        lambda *args, **kwargs: sync_called.__setitem__("value", True),
    )
    monkeypatch.setattr(run_poc_module, "sync_source_files", lambda *args, **kwargs: [])

    summary = run_poc_module.run_strategyos_workflow(
        dataset=tmp_path,
        run_dir=tmp_path / "run",
        skip_prepare=True,
        sync_artifacts=True,
    )

    assert sync_called["value"] is False
    assert summary["external_modes"]["object_storage_sync"]["requested"] is True
    assert summary["external_modes"]["object_storage_sync"]["approved"] is False
    assert summary["external_modes"]["object_storage_sync"]["enabled"] is False
    assert "blocks external mode 'object_storage_sync'" in summary["external_modes"]["object_storage_sync"]["reason"]


def test_run_strategyos_workflow_allows_object_storage_sync_after_policy_approval(
    monkeypatch, tmp_path: Path
):
    output_root = tmp_path / "outputs"
    run_poc_module.CONFIG = SimpleNamespace(
        require_human_review=True,
        database_url=None,
        sync_artifacts=False,
        object_store=SimpleNamespace(enabled=True),
        run_policy=RunPolicyConfig(
            mode="external-approved",
            approved_external_modes=("object_storage_sync",),
        ),
        model_provider_enabled=False,
        batch_apis_enabled=False,
        hosted_ocr_vision_enabled=False,
        ocr_engine="tesseract",
        tenant_slug="test-tenant",
        output_root=output_root,
    )
    run_registry_module.CONFIG = run_poc_module.CONFIG

    class FakeGovernance:
        def __init__(self, *, dataset_root, source_pack_id=None, run_dir, requires_human_review):
            self.dataset_root = dataset_root
            self.source_pack_id = source_pack_id
            self.run_dir = run_dir
            self.requires_human_review = requires_human_review
            self.checkpoint = lambda stage, state: state
            self.stop_before_writer = True

        def initial_state(self):
            return {
                "dataset_root": self.dataset_root,
                "run_dir": self.run_dir,
                "run_id": "run-sync-approved",
                "workflow_status": "awaiting_review",
                "current_stage": "awaiting_review",
                "requires_human_review": self.requires_human_review,
                "approval_status": "pending",
                "checkpoints": [],
                "artifacts": {},
            }

    class FakeWorkflow:
        runtime_metadata = {"actual_backend": "local"}

        def invoke(self, state):
            return {**state, "artifacts": {}, "findings": [], "audit_events": [], "audit_verification": {}, "bundle": None}

    sync_calls = {"artifacts": 0, "sources": 0}
    monkeypatch.setattr(run_poc_module, "RuntimeGovernance", FakeGovernance)
    monkeypatch.setattr(run_poc_module, "build_workflow", lambda **_: FakeWorkflow())
    monkeypatch.setattr(
        run_poc_module,
        "persist_run_summary",
        lambda *args, **kwargs: {"status": "skipped", "run_id": kwargs.get("run_id")},
    )
    monkeypatch.setattr(run_poc_module, "sync_knowledge_graph", lambda **_: {"status": "skipped"})
    monkeypatch.setattr(run_poc_module, "sync_findings_vector_store", lambda **_: {"status": "skipped"})
    monkeypatch.setattr(
        run_poc_module,
        "sync_artifact_files",
        lambda *args, **kwargs: sync_calls.__setitem__("artifacts", sync_calls["artifacts"] + 1) or [{"artifact": "run_summary.json", "uri": "s3://bucket/run_summary.json"}],
    )
    monkeypatch.setattr(
        run_poc_module,
        "sync_source_files",
        lambda *args, **kwargs: sync_calls.__setitem__("sources", sync_calls["sources"] + 1) or [],
    )

    summary = run_poc_module.run_strategyos_workflow(
        dataset=tmp_path,
        run_dir=tmp_path / "run",
        skip_prepare=True,
        sync_artifacts=True,
    )

    assert sync_calls["artifacts"] == 1
    assert sync_calls["sources"] == 1
    assert summary["external_modes"]["object_storage_sync"]["requested"] is True
    assert summary["external_modes"]["object_storage_sync"]["approved"] is True
    assert summary["external_modes"]["object_storage_sync"]["enabled"] is True
    assert summary["object_store_uploads"] == [{"artifact": "run_summary.json", "uri": "s3://bucket/run_summary.json"}]
