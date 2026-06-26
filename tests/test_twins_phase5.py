"""Phase 5 — integration tests for live twin dashboards and API."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from strategyos_mvp.api import app

client = TestClient(app)


class TestTwinApiEndpoints:
    """Test /twin/api/* endpoints."""

    def test_status_ceo_returns_200(self):
        resp = client.get("/twin/api/status/ceo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "ceo"
        assert data["display_name"] == "CEO Twin"
        assert data["status"] == "active"
        assert "cycle_count" in data
        assert "active_investigations" in data
        assert "pending_requests" in data

    def test_status_cfo_returns_200(self):
        resp = client.get("/twin/api/status/cfo")
        assert resp.status_code == 200
        assert resp.json()["role"] == "cfo"

    def test_status_gm_returns_200(self):
        resp = client.get("/twin/api/status/gm")
        assert resp.status_code == 200
        assert resp.json()["role"] == "gm"

    def test_status_unknown_role_returns_404(self):
        resp = client.get("/twin/api/status/nonexistent")
        assert resp.status_code == 404
        assert "Unknown twin role" in resp.json()["detail"]

    def test_kpis_ceo_returns_data(self):
        resp = client.get("/twin/api/kpis/ceo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "ceo"
        assert "kpis" in data
        assert isinstance(data["kpis"], dict)

    def test_kpis_cfo_returns_data(self):
        resp = client.get("/twin/api/kpis/cfo")
        assert resp.status_code == 200
        data = resp.json()
        assert "kpis" in data
        # CFO should have financial KPIs
        assert len(data["kpis"]) > 0

    def test_kpis_unknown_role_returns_404(self):
        resp = client.get("/twin/api/kpis/unknown")
        assert resp.status_code == 404

    def test_inbox_ceo_returns_messages(self):
        resp = client.get("/twin/api/inbox/ceo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "ceo"
        assert "messages" in data
        assert "message_count" in data
        assert isinstance(data["messages"], list)

    def test_inbox_gm_returns_messages(self):
        resp = client.get("/twin/api/inbox/gm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "gm"
        assert isinstance(data["messages"], list)

    def test_investigate_ceo_with_query(self):
        resp = client.post("/twin/api/investigate/ceo?query=Why+is+margin+down%3F")
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "ceo"
        assert "summary" in data
        assert "cycle_count" in data
        assert data["query"] == "Why is margin down?"

    def test_investigate_cfo_without_query(self):
        resp = client.post("/twin/api/investigate/cfo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "cfo"
        assert "summary" in data

    def test_investigate_unknown_role_returns_404(self):
        resp = client.post("/twin/api/investigate/ghost")
        assert resp.status_code == 404


class TestTwinDashboardRoutes:
    """Test /twin/{role} dashboard HTML routes."""

    def test_ceo_dashboard_loads(self):
        resp = client.get("/twin/ceo")
        assert resp.status_code == 200
        assert "CEO" in resp.text
        assert "twin" in resp.text.lower()

    def test_cfo_dashboard_loads(self):
        resp = client.get("/twin/cfo")
        assert resp.status_code == 200
        assert "CFO" in resp.text

    def test_gm_dashboard_loads(self):
        resp = client.get("/twin/gm")
        assert resp.status_code == 200
        assert "GM" in resp.text

    def test_ceo_dashboard_has_kpi_section(self):
        resp = client.get("/twin/ceo")
        assert "KPI" in resp.text

    def test_cfo_dashboard_has_financial_section(self):
        resp = client.get("/twin/cfo")
        assert "financial" in resp.text.lower() or "KPI" in resp.text

    def test_gm_dashboard_has_bu_section(self):
        resp = client.get("/twin/gm")
        assert "BU" in resp.text or "performance" in resp.text.lower()

    def test_dashboards_have_navigation(self):
        resp = client.get("/twin/ceo")
        assert "/twin/cfo" in resp.text or "/twin/gm" in resp.text

    def test_dashboards_have_live_js(self):
        """Verify dashboards have the live data fetching JavaScript."""
        resp = client.get("/twin/ceo")
        assert "fetch('/twin/api/" in resp.text
        resp2 = client.get("/twin/cfo")
        assert "fetch('/twin/api/" in resp2.text


class TestNoRegression:
    """Ensure Phase 5 does not break existing pages."""

    def test_architecture_still_works(self):
        resp = client.get("/architecture")
        assert resp.status_code == 200
        assert "Architecture" in resp.text

    def test_plan_still_works(self):
        resp = client.get("/plan")
        assert resp.status_code == 200
        assert "Execution Plan" in resp.text

    def test_twin_api_router_is_registered(self):
        """Verify twin endpoints are reachable via the main app."""
        resp = client.get("/twin/api/status/ceo")
        assert resp.status_code == 200
