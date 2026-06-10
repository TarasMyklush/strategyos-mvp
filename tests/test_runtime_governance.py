import os
from pathlib import Path

import strategyos_mvp.runtime_governance as runtime_governance
import strategyos_mvp.workflow as workflow_module
from strategyos_mvp.config import load_config
from strategyos_mvp.models import Finding


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


def test_runtime_governance_initial_state_noops_without_database():
    import strategyos_mvp.state_store as state_store

    original_config = state_store.CONFIG
    original_env = {
        key: os.environ.get(key) for key in ["DATABASE_URL", "STRATEGYOS_DATABASE_URL"]
    }
    try:
        for key in original_env:
            os.environ.pop(key, None)
        state_store.CONFIG = load_config()
        governance = runtime_governance.RuntimeGovernance(
            dataset_root=Path("/tmp/dataset"),
            run_dir=Path("/tmp/run"),
        )
        state = governance.initial_state()
        assert state["run_id"] is None
        assert state["workflow_status"] == "running"
        assert state["approval_status"] == "pending"
        assert state["runtime_record"]["status"] == "skipped"
    finally:
        for key, value in original_env.items():
            if value is not None:
                os.environ[key] = value
        state_store.CONFIG = original_config


def test_runtime_governance_checkpoint_updates_lifecycle_without_database():
    import strategyos_mvp.state_store as state_store

    original_config = state_store.CONFIG
    original_env = {
        key: os.environ.get(key) for key in ["DATABASE_URL", "STRATEGYOS_DATABASE_URL"]
    }
    try:
        for key in original_env:
            os.environ.pop(key, None)
        state_store.CONFIG = load_config()
        governance = runtime_governance.RuntimeGovernance(
            dataset_root=Path("/tmp/dataset"),
            run_dir=Path("/tmp/run"),
        )
        state = {
            **governance.initial_state(),
            "findings": [_sample_finding()],
            "artifacts": {"manifest": Path("/tmp/run/source_hash_manifest.json")},
        }
        updated = governance.checkpoint("knowledge_graph", state)

        assert updated["current_stage"] == "knowledge_graph"
        assert updated["workflow_status"] == "running"
        assert updated["approval_status"] == "pending"
        assert len(updated["checkpoints"]) == 1
        assert updated["checkpoints"][0]["persistence"] == "skipped"
    finally:
        for key, value in original_env.items():
            if value is not None:
                os.environ[key] = value
        state_store.CONFIG = original_config


def test_build_workflow_stops_before_writer_when_review_required(monkeypatch, tmp_path):
    writer_called = {"value": False}

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
            writer_called["value"] = True
            return {"case_file": run_dir / "case.md"}

    monkeypatch.setattr(
        workflow_module, "load_dataset", lambda dataset_root: FakeBundle()
    )
    monkeypatch.setattr(workflow_module, "FinanceAnalystAgent", FakeAnalyst)
    monkeypatch.setattr(workflow_module, "FinanceAuditorAgent", FakeAuditor)
    monkeypatch.setattr(workflow_module, "EvidenceQAAgent", FakeEvidenceQA)
    monkeypatch.setattr(workflow_module, "KnowledgeGraphAgent", FakeKG)
    monkeypatch.setattr(workflow_module, "CaseFileWriter", FakeWriter)

    workflow = workflow_module.build_workflow(stop_before_writer=True)
    result = workflow.invoke(
        {
            "dataset_root": tmp_path,
            "run_dir": tmp_path,
            "requires_human_review": True,
            "workflow_status": "running",
            "approval_status": "pending",
        }
    )

    assert writer_called["value"] is False
    assert result["current_stage"] == "awaiting_review"
    assert result["workflow_status"] == "awaiting_review"
    assert result["approval_status"] == "pending"
    assert "knowledge_graph" in result["artifacts"]


def test_build_workflow_runs_writer_when_review_not_required(monkeypatch, tmp_path):
    writer_called = {"value": False}

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
            return {}

    class FakeKG:
        def build(self, bundle, findings, run_dir):
            kg_path = run_dir / "kg.json"
            kg_path.write_text("{}", encoding="utf-8")
            return kg_path

    class FakeWriter:
        def write_all(self, bundle, findings, audit_events, run_dir):
            writer_called["value"] = True
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

    workflow = workflow_module.build_workflow(stop_before_writer=True)
    result = workflow.invoke(
        {
            "dataset_root": tmp_path,
            "run_dir": tmp_path,
            "requires_human_review": False,
            "workflow_status": "running",
            "approval_status": "not_required",
        }
    )

    assert writer_called["value"] is True
    assert result["current_stage"] == "writer"
    assert result["workflow_status"] == "completed"
    assert "case_file" in result["artifacts"]
