import os
from pathlib import Path

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
import strategyos_mvp.run_registry as run_registry_module
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


def _client_with_auth():
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-key",
        }
    )
    return original, TestClient(api_module.app)


def test_qa_requires_auth(monkeypatch):
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {"bundle": object(), "findings": [], "run_id": run_id, "run_mode": "full"},
        )

        response = client.post("/qa", json={"question": "total invoices"})

        assert response.status_code == 401
    finally:
        _restore_env(original)


def test_qa_endpoint_returns_answer_and_suggestions(monkeypatch):
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {"bundle": object(), "findings": [], "run_id": "run-1", "run_mode": "full"},
        )

        def fake_answer(question, *, bundle, findings):
            if question == "gibberish xyz":
                return {"matched": False, "answer": "Try one of these:", "suggestions": ["Top 5 vendors by spend"], "citations": []}
            return {
                "matched": True,
                "answer": "The total AP invoice amount is SAR 133,646,616.03 across 1,397 invoices.",
                "value": 133_646_616.03,
                "unit": "SAR",
                "basis": "sum of Amount_SAR over 1,397 AP rows.",
                "intent": "invoice_metric",
                "citations": [{"source_path": "02_ERP_Extracts/AP_Invoices_H1_2026.xlsx", "locator": "Amount_SAR"}],
            }

        monkeypatch.setattr(api_module.qa_engine, "answer_question", fake_answer)

        answered = client.post(
            "/qa",
            json={"question": "what is the total amount of invoices?"},
            headers={"X-API-Key": "operator-key"},
        )
        assert answered.status_code == 200
        assert answered.json()["value"] == 133_646_616.03
        assert answered.json()["citations"][0]["source_path"].endswith("AP_Invoices_H1_2026.xlsx")

        unmatched = client.post(
            "/qa",
            json={"question": "gibberish xyz"},
            headers={"X-API-Key": "reviewer-key"},
        )
        assert unmatched.status_code == 200
        assert unmatched.json()["matched"] is False
        assert unmatched.json()["suggestions"]
    finally:
        _restore_env(original)


def test_latest_run_audit_summary_reads_citation_and_audit_artifacts(monkeypatch, tmp_path):
    citation_audit = tmp_path / "citation_audit.json"
    citation_audit.write_text(
        (
            '{"summary": {"citation_count": 7, "resolved_count": 6}, '
            '"records": []}'
        ),
        encoding="utf-8",
    )
    audit_log = tmp_path / "audit_log.json"
    audit_log.write_text(
        (
            '['
            '{"action": "challenge", "status": "challenged", "finding_id": "F-002"},'
            '{"action": "response", "status": "responded", "finding_id": "F-002"},'
            '{"action": "challenge", "status": "challenged", "finding_id": "F-001"}'
            ']'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api_module,
        "_latest_summary",
        lambda: {
            "run_id": "run-1",
            "run_dir": str(tmp_path / "run"),
            "artifacts": {
                "citation_audit": str(citation_audit),
                "audit_log": str(audit_log),
            },
        },
    )
    original, client = _client_with_auth()
    try:
        response = client.get(
            "/runs/latest/audit-summary",
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        assert response.json()["citation_count"] == 7
        assert response.json()["resolved_count"] == 6
        assert response.json()["challenged_finding_ids"] == ["F-001", "F-002"]
    finally:
        _restore_env(original)


def test_qa_context_resolves_explicit_run_id_from_state_store(monkeypatch, tmp_path):
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    captured: dict[str, object] = {}
    api_module._QA_CONTEXT_CACHE.clear()

    def fake_run_detail(run_id: str):
        return {
            "run_id": run_id,
            "dataset_root": str(dataset_root),
            "run_dir": str(tmp_path / "run"),
            "summary_json": {"run_mode": "partial"},
        }

    def fake_load_dataset(path: Path, *, strict: bool):
        captured["path"] = path
        captured["strict"] = strict
        return object()

    monkeypatch.setattr(api_module.state_store, "get_run_detail", fake_run_detail)
    monkeypatch.setattr(api_module, "load_dataset", fake_load_dataset)
    monkeypatch.setattr(api_module, "run_all_finance_skills", lambda bundle: ["finding"])

    context = api_module._resolve_qa_context("run-77")

    assert context["run_id"] == "run-77"
    assert context["run_mode"] == "partial"
    assert captured == {"path": dataset_root, "strict": False}
    assert context["findings"] == ["finding"]
