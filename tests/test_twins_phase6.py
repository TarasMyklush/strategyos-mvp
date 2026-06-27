"""Phase 6 tests for durable twin persistence."""

from __future__ import annotations

from fastapi.testclient import TestClient

from strategyos_mvp.api import app
from strategyos_mvp.twins.memory import create_twin_state
from strategyos_mvp.twins.persona import CEO_TWIN
from strategyos_mvp.twins.resolution import KPIResolutionEngine, KPI_TREE
from strategyos_mvp.twins.runtime import TwinRuntime, _deliver_to_inbox, _peek_inbox
from strategyos_mvp.twins.store import build_repositories


client = TestClient(app)


class TestRepositories:
    def test_repository_round_trips(self, tmp_path):
        repositories = build_repositories(tmp_path / "twins")

        repositories.kpis.save({
            "margin_q2": {"owner": "cfo", "status": "missing", "value": None},
        })
        assert repositories.kpis.load("margin_q2")["owner"] == "cfo"
        repositories.kpis.update("margin_q2", {"status": "current", "value": 42})
        assert repositories.kpis.load("margin_q2")["value"] == 42
        assert repositories.kpis.list()[0]["node_id"] == "margin_q2"

        repositories.inboxes.append("ceo", {"message_id": "msg-1", "status": "pending"})
        repositories.inboxes.update("ceo", "msg-1", {"status": "read"})
        assert repositories.inboxes.load("ceo")[0]["status"] == "read"
        assert repositories.inboxes.consume("ceo")[0]["message_id"] == "msg-1"

        state = create_twin_state("ceo")
        repositories.states.save("ceo", state)
        repositories.states.update("ceo", {"cycle_count": 7})
        assert repositories.states.load("ceo")["cycle_count"] == 7
        assert repositories.states.list()[0]["role"] == "ceo"

        record = {"id": "inv-1", "status": "open", "context": {"query": "why"}}
        repositories.investigations.save("ceo", record)
        repositories.investigations.update("ceo", "inv-1", {"status": "resolved"})
        assert repositories.investigations.load("ceo", "inv-1")["status"] == "resolved"
        assert repositories.investigations.list("ceo")[0]["id"] == "inv-1"


class TestPersistedKpis:
    def test_resolution_engine_reads_persisted_kpis(self, tmp_path):
        repositories = build_repositories(tmp_path / "twins")
        repositories.kpis.save(KPI_TREE)
        repositories.kpis.update("margin_q2", {
            "status": "current",
            "value": 18.2,
            "last_updated": "2026-06-27",
        })
        repositories.kpis.update("cogs_q2", {"status": "current", "value": 10})
        repositories.kpis.update("raw_materials_q2", {"status": "current", "value": 5})

        engine = KPIResolutionEngine(repository=repositories.kpis)
        assert engine.get_node("margin_q2")["value"] == 18.2
        assert engine.detect_gaps("margin_q2") == []


class TestPersistedInbox:
    def test_inbox_persists_across_runtime_instances(self, tmp_path):
        repositories = build_repositories(tmp_path / "twins")
        repositories.kpis.save(KPI_TREE)

        _deliver_to_inbox("ceo", {
            "message_id": "persisted-msg-1",
            "sender_role": "cfo",
            "subject": "Persist me",
            "body": "Still here.",
            "priority": "normal",
        }, repositories)

        assert _peek_inbox("ceo", repositories) == 1

        runtime = TwinRuntime(CEO_TWIN, create_twin_state("ceo"), repositories=repositories)
        runtime.wake()
        observations = runtime.observe()

        assert observations["inbox"][0]["message_id"] == "persisted-msg-1"
        assert _peek_inbox("ceo", repositories) == 0


class TestPersistedApiState:
    def test_investigations_persist_across_api_calls(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STRATEGYOS_TWINS_DATA_DIR", str(tmp_path / "app-data"))

        first = client.post("/twin/api/investigate/ceo?query=Why+is+margin+down%3F")
        assert first.status_code == 200
        first_data = first.json()
        assert first_data["cycle_count"] >= 1

        status = client.get("/twin/api/status/ceo")
        assert status.status_code == 200
        status_data = status.json()
        assert status_data["cycle_count"] == first_data["cycle_count"]
        assert any(item.startswith("query-") for item in status_data["active_investigations"])

        repositories = build_repositories(tmp_path / "app-data")
        stored_state = repositories.states.load("ceo")
        assert stored_state is not None
        assert stored_state["cycle_count"] == first_data["cycle_count"]

    def test_inbox_endpoint_reads_persisted_messages(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STRATEGYOS_TWINS_DATA_DIR", str(tmp_path / "app-data"))
        repositories = build_repositories(tmp_path / "app-data")
        repositories.kpis.save(KPI_TREE)
        repositories.inboxes.append("ceo", {
            "message_id": "api-msg-1",
            "sender_role": "cfo",
            "message_type": "notification",
            "subject": "Stored inbox item",
            "created_at": "2026-06-27T00:00:00+00:00",
            "priority": "high",
            "status": "pending",
        })

        response = client.get("/twin/api/inbox/ceo")
        assert response.status_code == 200
        data = response.json()
        assert data["message_count"] == 1
        assert data["messages"][0]["subject"] == "Stored inbox item"

    def test_phase5_contract_stays_stable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STRATEGYOS_TWINS_DATA_DIR", str(tmp_path / "app-data"))

        status = client.get("/twin/api/status/ceo")
        inbox = client.get("/twin/api/inbox/ceo")
        dashboard = client.get("/twin/ceo")

        assert status.status_code == 200
        assert set(["role", "display_name", "status", "cycle_count", "active_investigations", "pending_requests"]).issubset(status.json())
        assert inbox.status_code == 200
        assert "messages" in inbox.json()
        assert dashboard.status_code == 200
