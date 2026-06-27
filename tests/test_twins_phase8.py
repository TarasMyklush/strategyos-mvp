"""Phase 8 tests for StrategyOS data integration across twin surfaces."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
from strategyos_mvp.config import load_config
from strategyos_mvp.twins.store import build_repositories


client = TestClient(api_module.app)


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


def _phase8_env(tmp_path) -> dict[str, str]:
    return {
        "STRATEGYOS_API_AUTH_ENABLED": "false",
        "STRATEGYOS_TWINS_DATA_DIR": str(tmp_path / "app-data"),
    }


def _fake_summary() -> dict[str, object]:
    return {
        "run_id": "run-20260627",
        "run_dir": "/tmp/strategyos/run-20260627",
        "approval_status": "approved",
        "current_stage": "awaiting_review",
        "requires_human_review": True,
        "created_at": "2026-06-27T12:34:56+00:00",
    }


def _fake_report_contracts() -> dict[str, object]:
    return {
        "tenant_id": "strategyos-live",
        "run_id": "run-20260627",
        "evidence": [
            {"artifact_key": "evidence-1"},
            {"artifact_key": "evidence-2"},
        ],
        "reports": [
            {"artifact_key": "report-1"},
            {"artifact_key": "report-2"},
        ],
    }


def _fake_findings_payload() -> dict[str, object]:
    return {
        "status": "ok",
        "run_id": "run-20260627",
        "finding_count": 2,
        "approval_status": "approved",
        "requires_human_review": True,
        "metrics": {
            "total_recoverable_sar": 223676,
            "finding_count": 2,
            "citation_count": 3,
            "resolved_count": 2,
            "challenged_count": 1,
            "report_count": 2,
            "evidence_count": 2,
        },
        "kpi_cards": [
            {"card_id": "recoverable_value", "label": "Recoverable value", "value": 223676, "unit": "SAR", "trend_hint": "bounded_finance_snapshot"},
            {"card_id": "governed_cases", "label": "Governed cases", "value": 2, "unit": "count", "trend_hint": "case_worklist"},
            {"card_id": "citation_resolution", "label": "Citation resolution", "value": {"resolved": 2, "total": 3}, "unit": "count", "trend_hint": "evidence_chain"},
            {"card_id": "challenged_cases", "label": "Challenged cases", "value": 1, "unit": "count", "trend_hint": "review_attention"},
        ],
        "publication": {
            "run_id": "run-20260627",
            "status": "approved_for_release",
            "publish_state": "approved_for_release",
            "approval_status": "approved",
            "report_count": 2,
            "evidence_count": 2,
            "board_pack": {
                "status": "ready",
                "preview_route": "/public/runs/latest/report-preview",
                "allowed_actions": ["view_board_pack_preview"],
            },
            "preview_route": "/public/runs/latest/report-preview",
        },
        "plan_health": {"status": "review_gate_visible", "label": "Review gate visible"},
        "board_portal": {
            "state": "live",
            "presentation_state": "pre",
            "meeting": {"run_id": "run-20260627", "title": "Governed board packet"},
            "state_detail": {"summary": "Operate only inside the approved packet."},
            "deck_release": {"status": "ready"},
            "supplementary": {"question_count": 1},
        },
        "trend": {
            "latest_point": {
                "run_id": "run-20260627",
                "recoverable_sar": 223676,
                "locked_findings": 2,
            }
        },
        "findings": [
            {
                "finding_id": "F-001",
                "title": "Duplicate payment for invoice INV-1",
                "pattern_label": "Duplicate payment",
                "pattern_type": "duplicate_payment",
                "owner": "Premier Packaging LLC",
                "citation_count": 2,
                "challenged": True,
                "recoverable_sar": 177188,
                "case_href": "/runs/latest/cases/F-001",
                "evidence_preview_href": "/data/evidence-preview?run_id=run-20260627&finding_id=F-001",
                "report_preview_href": "/public/runs/latest/report-preview",
                "contracts": {
                    "evidence": {"preview_href": "/data/evidence-preview?run_id=run-20260627&finding_id=F-001", "evidence_qa_href": "/runs/latest/findings?domain=evidence_qa#case=F-001"},
                    "report": {"preview_href": "/public/runs/latest/report-preview"},
                },
            },
            {
                "finding_id": "F-002",
                "title": "FX hedge not applied for INV-2",
                "pattern_label": "FX hedge not applied",
                "pattern_type": "fx_hedge_unapplied",
                "owner": "Treasury",
                "citation_count": 1,
                "challenged": False,
                "recoverable_sar": 46488,
                "case_href": "/runs/latest/cases/F-002",
                "evidence_preview_href": "/data/evidence-preview?run_id=run-20260627&finding_id=F-002",
                "report_preview_href": "/public/runs/latest/report-preview",
                "contracts": {
                    "evidence": {"preview_href": "/data/evidence-preview?run_id=run-20260627&finding_id=F-002", "evidence_qa_href": "/runs/latest/findings?domain=evidence_qa#case=F-002"},
                    "report": {"preview_href": "/public/runs/latest/report-preview"},
                },
            },
        ],
    }


def _install_strategyos_mocks(monkeypatch):
    monkeypatch.setattr(api_module, "_latest_summary", _fake_summary)
    monkeypatch.setattr(
        api_module,
        "_latest_run_findings_payload",
        lambda summary, include_run_dir, public_safe, domain_filter=None, view_state=None: _fake_findings_payload(),
    )
    monkeypatch.setattr(api_module, "_summary_report_contracts", lambda summary: _fake_report_contracts())


def test_kpi_endpoint_uses_real_strategyos_payload(monkeypatch, tmp_path):
    original = _apply_env(_phase8_env(tmp_path))
    try:
        _install_strategyos_mocks(monkeypatch)
        response = client.get("/twin/api/kpis/ceo")
        assert response.status_code == 200
        payload = response.json()
        assert payload["data_source"] == "strategyos"
        assert payload["bounded_fallback"] is False
        assert payload["run_context"]["run_id"] == "run-20260627"
        assert payload["board"]["report_count"] == 2
        assert payload["kpis"]["citation_resolution"]["value"] == "2 / 3"
        assert payload["kpis"]["board_packet_reports"]["value"] == 2
        assert payload["kpis"]["board_packet_reports"]["threshold"] == ">= 1 surfaced report"
    finally:
        _restore_env(original)


def test_investigation_links_real_evidence_and_run_context(monkeypatch, tmp_path):
    original = _apply_env(_phase8_env(tmp_path))
    try:
        _install_strategyos_mocks(monkeypatch)
        response = client.post("/twin/api/investigate/ceo?query=duplicate+payment")
        assert response.status_code == 200
        payload = response.json()
        assert payload["data_source"] == "strategyos"
        assert payload["run_context"]["run_id"] == "run-20260627"
        assert payload["board"]["preview_route"] == "/public/runs/latest/report-preview"
        assert payload["evidence"][0]["finding_id"] == "F-001"
        assert payload["evidence"][0]["evidence_preview_href"].endswith("finding_id=F-001")
        assert "Duplicate payment for invoice INV-1" in payload["response"]["summary"]

        repositories = build_repositories(tmp_path / "app-data")
        stored = next(item for item in repositories.investigations.list("ceo") if item.get("query") == "duplicate payment")
        assert stored["linked_run_id"] == "run-20260627"
        assert stored["run_context"]["approval_status"] == "approved"
        assert stored["evidence"][0]["finding_id"] == "F-001"
    finally:
        _restore_env(original)


def test_status_surface_exposes_board_run_and_consistency(monkeypatch, tmp_path):
    original = _apply_env(_phase8_env(tmp_path))
    try:
        _install_strategyos_mocks(monkeypatch)
        response = client.get("/twin/api/status/gm")
        assert response.status_code == 200
        payload = response.json()
        assert payload["strategyos"]["data_source"] == "strategyos"
        assert payload["strategyos"]["board"]["status"] == "ready"
        assert payload["strategyos"]["run_context"]["run_id"] == "run-20260627"
        assert payload["strategyos"]["consistency"]["aligned"] is True
    finally:
        _restore_env(original)


def test_phase0_to_phase7_contracts_still_hold_with_phase8_data(monkeypatch, tmp_path):
    original = _apply_env(_phase8_env(tmp_path))
    try:
        _install_strategyos_mocks(monkeypatch)
        status = client.get("/twin/api/status/ceo")
        inbox = client.get("/twin/api/inbox/ceo")
        approve = client.post(
            "/twin/api/approve/ceo",
            json={"item_id": "dec-900", "title": "Board-ready packet", "rationale": "Evidence is sufficient."},
        )
        dashboard = client.get("/twin/ceo")

        assert status.status_code == 200
        assert inbox.status_code == 200
        assert approve.status_code == 200
        assert dashboard.status_code == 200
        assert set(["role", "display_name", "status", "cycle_count", "active_investigations", "pending_requests"]).issubset(status.json())
        assert "strategyos" in status.json()
        assert "/static/twin_live.js" in dashboard.text
    finally:
        _restore_env(original)
