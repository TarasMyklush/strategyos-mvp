import os

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
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


# A small but representative knowledge-graph artifact: two finding nodes, a
# vendor node, evidence-support edges (citation count) and a vendor edge (owner).
_FAKE_GRAPH = {
    "nodes": [
        {
            "id": "Finding:F-001",
            "label": "Finding",
            "properties": {
                "finding_id": "F-001",
                "title": "Duplicate payment for invoice INV-1",
                "pattern_type": "duplicate_payment",
                "confidence": "HIGH",
                "status": "locked",
                "recoverable_sar": 177188,
                "leakage_sar": 177188,
                "classification": "CASH (recoverable now)",
            },
        },
        {
            "id": "Finding:F-002",
            "label": "Finding",
            "properties": {
                "finding_id": "F-002",
                "title": "FX hedge not applied for INV-2",
                "pattern_type": "fx_hedge_unapplied",
                "confidence": "MEDIUM",
                "status": "locked",
                "recoverable_sar": 46488,
                "leakage_sar": 46488,
                "classification": "CASH (recoverable going-forward)",
            },
        },
        {
            "id": "Vendor:V-1",
            "label": "Vendor",
            "properties": {"vendor_id": "V-1", "vendor_name": "Premier Packaging LLC"},
        },
        {"id": "Evidence:e1", "label": "Evidence", "properties": {}},
        {"id": "Evidence:e2", "label": "Evidence", "properties": {}},
    ],
    "edges": [
        {"source": "Finding:F-001", "target": "Vendor:V-1", "label": "INVOLVES_VENDOR", "properties": {}},
        {"source": "Finding:F-001", "target": "Evidence:e1", "label": "SUPPORTED_BY", "properties": {}},
        {"source": "Finding:F-001", "target": "Evidence:e2", "label": "SUPPORTED_BY", "properties": {}},
        {"source": "Finding:F-002", "target": "Evidence:e1", "label": "SUPPORTED_BY", "properties": {}},
    ],
}

_FAKE_SUMMARY = {
    "run_id": "run-test",
    "run_dir": "/tmp/run-test",
    "total_recoverable_sar": 223676,
    "locked_findings": 2,
    "requires_human_review": False,
    "approval_status": "approved",
    "audit_verification": {"challenged_finding_ids": ["F-001"]},
}


def test_finding_rows_assembled_from_knowledge_graph(monkeypatch):
    monkeypatch.setattr(
        api_module, "_load_knowledge_graph_artifact", lambda summary: (None, _FAKE_GRAPH)
    )
    monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

    rows = api_module._finding_rows_from_summary(_FAKE_SUMMARY)

    assert [r["finding_id"] for r in rows] == ["F-001", "F-002"]  # sorted by recoverable desc
    first = rows[0]
    assert first["title"] == "Duplicate payment for invoice INV-1"
    assert first["pattern_label"] == "Duplicate payment"  # humanized, no snake_case
    assert first["recoverable_sar"] == 177188
    assert first["citation_count"] == 2  # two SUPPORTED_BY edges
    assert first["owner"] == "Premier Packaging LLC"
    assert first["challenged"] is True  # from audit_verification
    assert rows[1]["pattern_label"] == "FX hedge not applied"
    assert rows[1]["challenged"] is False
    # No raw snake_case pattern_type leaks into the human label.
    assert all("_" not in r["pattern_label"] for r in rows)


def test_findings_endpoint_returns_worklist(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: _FAKE_SUMMARY)
        monkeypatch.setattr(
            api_module, "_load_knowledge_graph_artifact", lambda summary: (None, _FAKE_GRAPH)
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        client = TestClient(api_module.app)
        response = client.get("/runs/latest/findings")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["finding_count"] == 2
        assert payload["total_recoverable_sar"] == 223676
        assert payload["findings"][0]["finding_id"] == "F-001"
        assert payload["findings"][0]["pattern_label"] == "Duplicate payment"
    finally:
        _restore_env(original)


def test_findings_endpoint_handles_missing_run(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: None)

        client = TestClient(api_module.app)
        response = client.get("/runs/latest/findings")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "missing"
        assert payload["findings"] == []
    finally:
        _restore_env(original)


def test_findings_endpoint_requires_auth_when_enabled(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: _FAKE_SUMMARY)
        monkeypatch.setattr(
            api_module, "_load_knowledge_graph_artifact", lambda summary: (None, _FAKE_GRAPH)
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        client = TestClient(api_module.app)
        assert client.get("/runs/latest/findings").status_code == 401
        ok = client.get("/runs/latest/findings", headers={"X-API-Key": "operator-secret"})
        assert ok.status_code == 200
        assert ok.json()["status"] == "ok"
    finally:
        _restore_env(original)
