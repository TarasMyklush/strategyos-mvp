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
        assert payload["findings"][0]["case_href"] == "/runs/latest/cases/F-001"
        assert (
            payload["findings"][0]["evidence_preview_href"]
            == "/data/evidence-preview?run_id=run-test&finding_id=F-001"
        )
        assert (
            payload["findings"][0]["report_preview_href"]
            == "/public/runs/latest/report-preview"
        )
        assert payload["findings"][0]["contracts"]["evidence"]["evidence_qa_href"].startswith(
            "/runs/latest/findings?domain=evidence_qa"
        )
    finally:
        _restore_env(original)


def test_findings_endpoint_supports_domain_filters_and_kpi_contracts(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: _FAKE_SUMMARY)
        monkeypatch.setattr(
            api_module, "_load_knowledge_graph_artifact", lambda summary: (None, _FAKE_GRAPH)
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)
        monkeypatch.setattr(
            api_module,
            "discover_run_history",
            lambda limit=6: [
                {
                    "run_id": "run-test",
                    "total_recoverable_sar": 223676,
                    "locked_findings": 2,
                    "approval_status": "approved",
                }
            ],
        )

        client = TestClient(api_module.app)
        response = client.get("/runs/latest/findings?domain=evidence_qa")

        assert response.status_code == 200
        payload = response.json()
        assert payload["domain_filter"] == "evidence_qa"
        assert payload["finding_count"] == 2
        assert any(item["active"] is True for item in payload["domain_filters"])
        assert payload["kpi_cards"][0]["card_id"] == "recoverable_value"
        assert payload["trend"]["count"] == 1
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


def test_public_findings_endpoint_is_anonymous_safe_when_auth_enabled(monkeypatch):
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
        response = client.get("/public/runs/latest/findings")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["public_safe"] is True
        assert payload["findings"][0]["finding_id"] == "F-001"
        assert payload["findings"][0]["case_href"] == "/public/runs/latest/cases/F-001"
        assert (
            payload["findings"][0]["evidence_preview_href"]
            == "/public/data/evidence-preview?run_id=run-test&finding_id=F-001"
        )
        assert "run_dir" not in payload
    finally:
        _restore_env(original)


def test_case_detail_endpoint_returns_role_safe_case_contract(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: _FAKE_SUMMARY)
        monkeypatch.setattr(
            api_module, "_load_knowledge_graph_artifact", lambda summary: (None, _FAKE_GRAPH)
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        client = TestClient(api_module.app)
        response = client.get("/runs/latest/cases/F-001")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["case"]["finding_id"] == "F-001"
        assert payload["case"]["case_href"] == "/runs/latest/cases/F-001"
        assert (
            payload["case"]["evidence_preview_href"]
            == "/data/evidence-preview?run_id=run-test&finding_id=F-001"
        )
    finally:
        _restore_env(original)


def test_public_evidence_preview_sanitizes_payload(monkeypatch):
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
            api_module.state_store,
            "evidence_preview_for_run",
            lambda run_id, **_: {
                "status": "ok",
                "run_id": run_id,
                "finding_id": "F-001",
                "citation_id": "c-1",
                "title": "Duplicate payment for invoice INV-1",
                "pattern_type": "duplicate_payment",
                "vendor_name": "Premier Packaging LLC",
                "confidence": "HIGH",
                "source_path": "uploads/ap_ledger.csv",
                "source_hash": "secret-hash",
                "locator": "row 341",
                "resolved": True,
                "hash_match": True,
                "preview_kind": "text",
                "excerpt": "Invoice INV-2026-0341 was paid twice.",
                "resolved_payload": {"raw": "hidden"},
            },
        )

        client = TestClient(api_module.app)
        response = client.get("/public/data/evidence-preview?finding_id=F-001")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["public_safe"] is True
        assert payload["source_path"] == "ap_ledger.csv"
        assert payload["source_hash"] is None
        assert payload["resolved_payload"] == {}
        assert payload["excerpt"] == "Invoice INV-2026-0341 was paid twice."
    finally:
        _restore_env(original)


def test_public_report_preview_returns_board_safe_summary(monkeypatch):
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
        response = client.get("/public/runs/latest/report-preview")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["public_safe"] is True
        assert payload["artifact_key"] == "executive_summary"
        assert "Recoverable value identified" in payload["preview_text"]
        assert "Top case: Duplicate payment for invoice INV-1" in payload["preview_text"]
    finally:
        _restore_env(original)


def test_executive_latest_run_uses_public_safe_summary(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": None,
            "STRATEGYOS_REVIEWER_API_KEYS": None,
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: _FAKE_SUMMARY)

        client = TestClient(api_module.app)
        response = client.get("/runs/latest", headers={"X-API-Key": "executive"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["public_safe"] is True
        assert "run_dir" not in payload
    finally:
        _restore_env(original)


def test_executive_findings_route_stays_public_safe(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": None,
            "STRATEGYOS_REVIEWER_API_KEYS": None,
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: _FAKE_SUMMARY)
        monkeypatch.setattr(
            api_module, "_load_knowledge_graph_artifact", lambda summary: (None, _FAKE_GRAPH)
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        client = TestClient(api_module.app)
        response = client.get("/runs/latest/findings", headers={"X-API-Key": "executive"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["public_safe"] is True
        assert "run_dir" not in payload
        assert payload["findings"][0]["case_href"] == "/public/runs/latest/cases/F-001"
        assert payload["findings"][0]["evidence_preview_href"] == "/public/data/evidence-preview?run_id=run-test&finding_id=F-001"
    finally:
        _restore_env(original)
