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


def _collect_keys(payload):
    if isinstance(payload, dict):
        keys = set(payload.keys())
        for value in payload.values():
            keys.update(_collect_keys(value))
        return keys
    if isinstance(payload, list):
        keys = set()
        for item in payload:
            keys.update(_collect_keys(item))
        return keys
    return set()


def _collect_strings(payload):
    if isinstance(payload, dict):
        values = []
        for item in payload.values():
            values.extend(_collect_strings(item))
        return values
    if isinstance(payload, list):
        values = []
        for item in payload:
            values.extend(_collect_strings(item))
        return values
    if isinstance(payload, str):
        return [payload]
    return []


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
    assert first["challenged"] is False  # historical audit verification is not current state
    assert rows[1]["pattern_label"] == "FX hedge not applied"
    assert rows[1]["challenged"] is False
    # No raw snake_case pattern_type leaks into the human label.
    assert all("_" not in r["pattern_label"] for r in rows)


def test_evidence_monitor_never_displays_an_impossible_resolution_fraction():
    agents = api_module._agent_modules_payload(
        _FAKE_SUMMARY,
        [{"finding_id": "F-001", "citation_count": 2}],
        {
            "status": "ok",
            "citation_count": 25,
            "resolved_count": 40,
            "challenged_finding_ids": [],
        },
        {"role": "operator", "authenticated": True},
    )
    monitor = next(
        item for item in agents["running"] if item["module_id"] == "evidence-closure-monitor"
    )

    assert monitor["output_metric"] == "Resolution needs reconciliation"
    assert "40 / 25" not in monitor["summary"]


def test_board_reconciliation_gate_checks_arithmetic_citations_and_open_case_links():
    audit = {
        "status": "ok",
        "citation_count": 2,
        "resolved_count": 2,
        "challenged_finding_ids": ["F-001"],
    }
    passed = api_module._board_reconciliation_payload(
        {"total_recoverable_sar": 100},
        [{"finding_id": "F-001", "recoverable_sar": 100, "challenged": True}],
        audit,
    )
    mismatched = api_module._board_reconciliation_payload(
        {"total_recoverable_sar": 177},
        [{"finding_id": "F-001", "recoverable_sar": 100, "challenged": True}],
        audit,
    )

    assert passed["publish_gate_passed"] is True
    assert mismatched["publish_gate_passed"] is False
    arithmetic = next(
        check for check in mismatched["checks"] if check["key"] == "recoverable_arithmetic"
    )
    assert arithmetic["delta_sar"] == -77.0


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
            == "/runs/latest/report-preview"
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
        assert payload["metrics"]["finding_count"] == 2
        assert payload["metrics"]["filtered_finding_count"] == 2
        assert payload["trend"]["count"] == 1
    finally:
        _restore_env(original)


def test_findings_and_workspace_contract_accept_design_persona_aliases(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: _FAKE_SUMMARY)
        monkeypatch.setattr(
            api_module, "_load_knowledge_graph_artifact", lambda summary: (None, _FAKE_GRAPH)
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        client = TestClient(api_module.app)
        workspace = client.get("/ui/workspace-contract/latest?persona=gm&board=closed&driver=owed_upward")
        findings = client.get("/public/runs/latest/findings?persona=bucfo&board=live&driver=cash_pulse")

        assert workspace.status_code == 200
        workspace_payload = workspace.json()
        assert workspace_payload["executive_modes"]["active_persona_id"] == "gm"
        assert workspace_payload["executive_modes"]["active_board_state"] == "closed"
        assert any(item["persona_id"] == "gm" for item in workspace_payload["executive_modes"]["personas"])
        assert any(item["persona_id"] == "bucfo" for item in workspace_payload["executive_modes"]["personas"])
        assert workspace_payload["chat"]["assistant"]["persona_id"] == "gm"
        assert workspace_payload["chat"]["assistant"]["name"] == "Iris"
        assert workspace_payload["chat"]["store"]["storage_key_prefix"] == "strategyos.chat."

        assert findings.status_code == 200
        findings_payload = findings.json()
        assert findings_payload["executive_modes"]["active_persona_id"] == "bucfo"
        assert findings_payload["executive_modes"]["active_board_state"] == "live"
        assert findings_payload["drilldown"]["gravity"]["sandbox"]["persona_id"] == "bucfo"
        assert findings_payload["chat"]["assistant"]["persona_id"] == "bucfo"
        assert findings_payload["chat"]["threads"][0]["thread_id"] == "system:latest-public"
        assert workspace_payload["run_id"] == "latest-public"
        assert workspace_payload["cases"]["items"][0]["case_href"] is None
        assert workspace_payload["drilldown"]["routes"]["case_detail"] is None
        assert workspace_payload["drilldown"]["routes"]["sample_case_detail"] is None
        assert workspace_payload["drilldown"]["routes"]["sample_evidence_preview"] == "/public/data/evidence-preview"
        banned_keys = {"finding_id", "case_id", "owner", "node_id", "resolved"}
        assert banned_keys.isdisjoint(_collect_keys(workspace_payload))
    finally:
        _restore_env(original)


def test_public_latest_run_includes_agents_and_chat_contracts(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: _FAKE_SUMMARY)
        monkeypatch.setattr(
            api_module, "_load_knowledge_graph_artifact", lambda summary: (None, _FAKE_GRAPH)
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        client = TestClient(api_module.app)
        response = client.get("/public/runs/latest?persona=cfo&board=live&driver=cash_pulse")

        assert response.status_code == 200
        payload = response.json()
        assert "running" in payload["agents"]
        assert "discover" in payload["agents"]
        assert payload["chat"]["assistant"]["persona_id"] == "cfo"
        assert payload["chat"]["assistant"]["name"] == "Atlas"
        assert payload["run_id"] == "latest-public"
        assert payload["chat"]["threads"][0]["thread_id"] == "system:latest-public"
        assert payload["chat"]["store"]["server_memory"] is False
    finally:
        _restore_env(original)


def test_public_findings_do_not_depend_on_vendor_name_blacklists(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: _FAKE_SUMMARY)
        monkeypatch.setattr(
            api_module,
            "_load_knowledge_graph_artifact",
            lambda summary: (
                None,
                {
                    "nodes": [
                        {
                            "id": "Finding:F-001",
                            "label": "Finding",
                            "properties": {
                                "finding_id": "F-001",
                                "title": "Acme Industrial Holdings duplicate payment for invoice INV-1",
                                "pattern_type": "duplicate_payment",
                                "confidence": "HIGH",
                                "status": "locked",
                                "recoverable_sar": 177188,
                                "leakage_sar": 177188,
                                "classification": "CASH (recoverable now)",
                            },
                        },
                        {
                            "id": "Vendor:V-1",
                            "label": "Vendor",
                            "properties": {
                                "vendor_id": "V-1",
                                "vendor_name": "Acme Industrial Holdings",
                            },
                        },
                    ],
                    "edges": [
                        {
                            "source": "Finding:F-001",
                            "target": "Vendor:V-1",
                            "label": "INVOLVES_VENDOR",
                            "properties": {},
                        }
                    ],
                },
            ),
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        client = TestClient(api_module.app)
        response = client.get("/public/runs/latest/findings")

        assert response.status_code == 200
        payload = response.json()
        assert payload["findings"][0]["title"] == "Duplicate payment signal"
        assert all("Acme Industrial Holdings" not in value for value in _collect_strings(payload))
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
        assert payload["run_id"] == "latest-public"
        assert payload["findings"][0]["title"] == "Duplicate payment signal"
        assert payload["findings"][0]["case_href"] is None
        assert payload["findings"][0]["evidence_preview_href"] is None
        assert payload["findings"][0]["contracts"]["case"]["href"] is None
        assert payload["findings"][0]["contracts"]["evidence"]["preview_href"] is None
        assert "finding_id" not in payload["findings"][0]
        assert "owner" not in payload["findings"][0]
        assert "run_dir" not in payload
        assert "node_id" not in _collect_keys(payload)
        assert all("/public/runs/latest/cases/" not in value for value in _collect_strings(payload))
    finally:
        _restore_env(original)


def test_public_case_detail_is_unavailable_on_anonymous_surface(monkeypatch):
    original = _apply_env({"STRATEGYOS_API_AUTH_ENABLED": "false"})
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: _FAKE_SUMMARY)
        monkeypatch.setattr(
            api_module, "_load_knowledge_graph_artifact", lambda summary: (None, _FAKE_GRAPH)
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        client = TestClient(api_module.app)
        response = client.get("/public/runs/latest/cases/F-001")

        assert response.status_code == 404
        assert response.json()["detail"] == "Anonymous case detail is unavailable on the public surface."
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
        assert payload["run_id"] == "latest-public"
        assert payload["title"] == "Governed evidence preview"
        assert payload["pattern_label"] == "Duplicate Payment"
        assert payload["source_path"] is None
        assert payload["source_hash"] is None
        assert payload["resolved_payload"] == {}
        assert payload["excerpt"] == api_module.PUBLIC_EVIDENCE_BOUNDARY_NOTE
        assert "finding_id" not in payload
        assert "vendor_name" not in payload
    finally:
        _restore_env(original)


def test_public_evidence_preview_without_selector_returns_boundary_note(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: _FAKE_SUMMARY)

        client = TestClient(api_module.app)
        response = client.get("/public/data/evidence-preview")

        assert response.status_code == 200
        payload = response.json()
        assert payload == {
            "status": "ok",
            "run_id": "latest-public",
            "title": "Governed evidence preview",
            "pattern_label": "Governed Signal",
            "confidence": None,
            "source_path": None,
            "source_hash": None,
            "preview_kind": "text",
            "excerpt": api_module.PUBLIC_EVIDENCE_BOUNDARY_NOTE,
            "resolved_payload": {},
            "public_safe": True,
        }
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
        assert "Top case: Duplicate payment signal" in payload["preview_text"]
        assert "INV-1" not in payload["preview_text"]
        assert payload["publication"]["publish_state"] == "approved_for_release"
        assert payload["board_portal"]["state"] == "live"
        assert "node_id" not in _collect_keys(payload)
        assert all("/public/runs/latest/cases/" not in value for value in _collect_strings(payload))
    finally:
        _restore_env(original)


def test_public_audit_summary_sanitizes_run_identity_and_challenged_ids(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {
            **_FAKE_SUMMARY,
            "acceptance": {
                "citation_count": 9,
                "resolved_citation_count": 4,
            },
            "audit_verification": {
                "challenged_finding_ids": ["finding-1", "finding-2"],
            },
        })

        def _artifact_loader_must_not_run(summary, key):
            raise AssertionError(f"public audit-summary must not load protected artifact {key}")

        monkeypatch.setattr(api_module, "_load_summary_artifact_json", _artifact_loader_must_not_run)

        client = TestClient(api_module.app)
        response = client.get("/public/runs/latest/audit-summary")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["public_safe"] is True
        assert payload["run_id"] == "latest-public"
        assert payload["citation_count"] is None
        assert payload["resolved_count"] is None
        assert "run_dir" not in payload
        assert "challenged_finding_ids" not in payload
    finally:
        _restore_env(original)


def test_authenticated_bu_report_preview_returns_governed_publication_posture(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_BU_API_KEYS": "bu-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {
            **_FAKE_SUMMARY,
            "current_stage": "awaiting_review",
            "artifacts": {
                "case_file": "/tmp/Final consolidated case file.md",
                "working_capital": "/tmp/Working Capital Memo.md",
                "citation_audit": "/tmp/StrategyOS Citation Audit.json",
            },
        })
        client = TestClient(api_module.app)

        response = client.get(
            "/runs/latest/report-preview", headers={"X-API-Key": "bu-key"}
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["public_safe"] is False
        assert payload["publication"]["status"] == "blocked_reconciliation"
        assert payload["publication"]["report_count"] == 2
        assert payload["publication"]["restricted_report_count"] == 1
        assert payload["publication"]["allowed_actions"] == [
            "view_governed_report_status",
            "view_report_preview",
        ]
        assert payload["publication"]["board_pack"]["status"] == "blocked_reconciliation"
        assert payload["publication"]["reconciliation"]["publish_gate_passed"] is False
        assert payload["publication"]["board_pack"]["allowed_actions"] == [
            "view_board_pack_preview",
            "inspect_board_pack_status",
        ]
        assert payload["board_portal"]["deck_release"]["status"] == "blocked_reconciliation"
        assert payload["board_portal"]["supplementary"]["next_action"] == "prepare_board_pack"
        assert payload["agent_modules"]["summary"]["running_count"] >= 4
        reviewer_actions = next(
            section
            for section in payload["role_actions"]["sections"]
            if section["role_id"] == "reviewer"
        )
        assert reviewer_actions["actions"][1]["route"] == "/reviewer/runs/run-test/approve"
        assert payload["plan_health"]["next_action"] == "prepare_board_pack"
        assert payload["strategy_substrate"]["node_count"] >= 8
        assert "governed publication posture" in payload["preview_text"].lower()
    finally:
        _restore_env(original)


def test_latest_run_and_findings_reconcile_to_graph_metrics(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
        }
    )
    try:
        monkeypatch.setattr(
            api_module,
            "_latest_summary",
            lambda: {
                **_FAKE_SUMMARY,
                "locked_findings": 99,
                "total_recoverable_sar": 999999,
                "artifacts": {"working_capital": "/tmp/Working Capital Memo.md"},
            },
        )
        monkeypatch.setattr(
            api_module, "_load_knowledge_graph_artifact", lambda summary: (None, _FAKE_GRAPH)
        )
        monkeypatch.setattr(api_module, "_load_summary_artifact_json", lambda summary, key: None)

        client = TestClient(api_module.app)
        latest = client.get("/runs/latest", headers={"X-API-Key": "operator-secret"})
        findings = client.get(
            "/runs/latest/findings", headers={"X-API-Key": "operator-secret"}
        )

        assert latest.status_code == 200
        assert findings.status_code == 200
        latest_payload = latest.json()
        findings_payload = findings.json()
        assert latest_payload["locked_findings"] == 2
        assert latest_payload["total_recoverable_sar"] == 223676
        assert findings_payload["locked_findings"] == 2
        assert findings_payload["metrics"]["total_recoverable_sar"] == 223676
        assert findings_payload["metrics"]["citation_count"] == 3
    finally:
        _restore_env(original)


def test_pending_review_lists_include_item_workflow_and_publication(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_BU_API_KEYS": "bu-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
        }
    )
    try:
        monkeypatch.setattr(
            api_module.state_store,
            "list_pending_reviews",
            lambda: [
                {
                    "run_id": "run-test",
                    "status": "awaiting_review",
                    "current_stage": "awaiting_review",
                    "approval_status": "pending",
                    "review_assignment": {"claimed": True, "claimed_by": "reviewer-1"},
                    "summary_json": {
                        **_FAKE_SUMMARY,
                        "approval_status": "pending",
                        "artifacts": {"working_capital": "/tmp/Working Capital Memo.md"},
                    },
                }
            ],
        )
        client = TestClient(api_module.app)

        response = client.get("/bu/pending-reviews", headers={"X-API-Key": "bu-key"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["workflow_summary"]["pending_count"] == 1
        assert payload["items"][0]["workflow_summary"]["next_action"] == "review_decision"
        assert payload["items"][0]["publication"]["report_count"] == 1
        assert payload["items"][0]["board_portal"]["state"] == "pre"
        assert payload["items"][0]["role_actions"]["viewer_role"] == "bu"
    finally:
        _restore_env(original)


def test_data_status_includes_workflow_and_publication_posture(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_TENANT_ADMIN_API_KEYS": "tenant-admin-secret",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {
            **_FAKE_SUMMARY,
            "current_stage": "awaiting_review",
            "status": "awaiting_review",
            "artifacts": {"working_capital": "/tmp/Working Capital Memo.md"},
            "tenant_context": {
                "tenant_id": "tenant-alpha",
                "tenant_name": "Tenant Alpha",
                "workspace_id": "tenant-alpha",
            },
        })
        monkeypatch.setattr(
            api_module,
            "data_management_status",
            lambda: {"status": "ready", "run_id": "run-test", "counts": {"findings": 2}},
        )
        monkeypatch.setattr(
            api_module,
            "graph_status_for_run",
            lambda run_id: {"status": "ready", "run_id": run_id},
        )
        monkeypatch.setattr(
            api_module,
            "vector_status_for_run",
            lambda run_id: {"status": "ready", "run_id": run_id},
        )
        monkeypatch.setattr(
            api_module.state_store,
            "list_pending_reviews",
            lambda: [{"run_id": "run-test", "review_assignment": {"claimed": True}}],
        )
        monkeypatch.setattr(
            api_module.state_store,
            "list_recent_runs",
            lambda limit=5: [{"run_id": "run-test", "status": "awaiting_review"}],
        )
        client = TestClient(api_module.app)

        response = client.get(
            "/data/status", headers={"X-API-Key": "tenant-admin-secret"}
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["workflow"]["pending_reviews"] == 1
        assert payload["workflow"]["recent_runs"] == 1
        assert payload["publication"]["report_count"] == 1
        assert payload["board_pack"]["status"] == "blocked_reconciliation"
        assert payload["publication"]["reconciliation"]["publish_gate_passed"] is False
        discover_metric = payload["agents"]["activity"]["metrics"][2]
        discover_lists_total = len(payload["agents"]["discover"]["native"]) + len(payload["agents"]["discover"]["marketplace"])
        assert discover_metric == {"k": "available services", "v": discover_lists_total}
        assert payload["board_portal"]["state"] == "pre"
        assert payload["agent_modules"]["summary"]["discoverable_count"] >= 4
        assert payload["tenant_admin_system"]["managed_data"]["graph_store"]["status"] == "ready"
        assert payload["tenant_admin_system"]["managed_data"]["vector_store"]["status"] == "ready"
        assert payload["tenant_admin_system"]["workflow_posture"]["pending_reviews"] == 1
        assert payload["tenant_admin_system"]["publication_posture"]["board_pack"]["status"] == "blocked_reconciliation"
        assert payload["role_actions"]["viewer_role"] == "tenant_admin"
        assert payload["plan_health"]["next_action"] == "capture_reviewer_decision"
        assert payload["trend"]["truth_basis"] == "reconciled_governed_metrics"
        assert payload["strategy_substrate"]["driver_count"] >= 4
        assert payload["tenant_context"]["tenant_id"] == "tenant-alpha"
        assert payload["runtime_posture"]["latest_run_id"] == "run-test"
    finally:
        _restore_env(original)


def test_latest_run_findings_exposes_reconciled_plan_health_and_publication(monkeypatch):
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
        response = client.get(
            "/runs/latest/findings", headers={"X-API-Key": "operator-secret"}
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["plan_health"]["root_label"] == "Governed plan posture"
        assert payload["publication"]["publish_state"] == "approved_for_release"
        assert payload["board_portal"]["publish_state"] == "approved_for_release"
        assert payload["agent_modules"]["summary"]["approval_count"] == 3
        assert payload["role_actions"]["viewer_role"] == "operator"
        assert payload["trend"]["truth_basis"] == "reconciled_governed_metrics"
        assert payload["trend"]["latest_point"]["recoverable_sar"] == 223676
        assert payload["drilldown"]["cash_pulse"]["value_display"].startswith("SAR ")
        assert payload["drilldown"]["owed_upward"]["next_action"] == "protect_value_signal"
        assert payload["drilldown"]["owed_upward"]["challenge_count"] == 0
        assert payload["drilldown"]["movers"][0]["mover_id"] == "cash_pulse"
    finally:
        _restore_env(original)


def test_authenticated_executive_latest_run_uses_governed_current_summary(monkeypatch):
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
        response = client.get(
            "/runs/latest?persona=cfo&board=closed&driver=cash_pulse",
            headers={"X-API-Key": "executive"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload.get("public_safe") is not True
        assert payload["board_portal"]["state"] == "live"
        assert payload["board_portal"]["presentation_state"] == "closed"
        assert payload["executive_modes"]["active_persona_id"] == "cfo"
        assert payload["executive_modes"]["active_board_state"] == "closed"
        assert payload["executive_modes"]["active_driver_key"] == "cash_pulse"
        assert payload["executive_modes"]["transition_contract"]["sequence"] == ["pre", "live", "closed"]
        assert payload["drilldown"]["gravity"]["sandbox"]["persona_id"] == "cfo"
        assert payload["drilldown"]["gravity"]["quote"]
        assert payload["drilldown"]["lower_rail"]["week_ahead"][0]["detail"]
        assert payload["drilldown"]["lower_rail"]["cash_pulse"]["basis"] == "governed_findings"
        assert payload["executive_diagnostics"]["persona_blueprint"]["assistant"] == "StrategyOS"
        assert payload["executive_diagnostics"]["hero"]["persona_id"] == "cfo"
        assert payload["executive_diagnostics"]["composition"]["board_portal"]["presentation_state"] == "closed"
        assert payload["run_id"] == _FAKE_SUMMARY["run_id"]
        assert payload["interaction_contracts"]["latest_run"]["route"] == "/runs/latest"
        assert payload["interaction_contracts"]["report_preview"]["route"] == "/runs/latest/report-preview"
    finally:
        _restore_env(original)


def test_authenticated_executive_findings_route_uses_governed_current_data(monkeypatch):
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
        assert payload["public_safe"] is False
        assert payload["findings"][0]["case_href"].startswith("/runs/latest/cases/")
        assert payload["findings"][0]["evidence_preview_href"].startswith("/data/evidence-preview?")
        assert payload["findings"][0]["report_preview_href"] == "/runs/latest/report-preview"
        assert payload["publication"]["preview_route"] == "/runs/latest/report-preview"
        assert payload["role_actions"]["viewer_role"] == "executive"
    finally:
        _restore_env(original)
