from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from strategyos_mvp import auth, outreach
from strategyos_mvp.outreach_api import router


def _client(role="executive"):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[auth.authenticate_request] = lambda: {
        "tenant_id": "test-tenant",
        "subject": "test-user",
        "role": role,
        "authenticated": True,
        "auth_disabled": False,
    }
    return TestClient(app)


def test_synthetic_catalog_covers_the_complete_governed_lifecycle():
    catalog = outreach.build_catalog()

    assert catalog["controls"] == {
        "mode": "synthetic",
        "connector_enabled": False,
        "mailbox_class": "dedicated_agent",
        "approval_required_before_send": True,
        "delete_capability": False,
        "raw_reply_stored": False,
        "authority_effect": "none",
    }
    assert catalog["coverage"] == {
        "named_provider_count": 7,
        "connected_count": 6,
        "contacted_count": 6,
        "responding_count": 2,
        "flagged_count": 2,
        "status_counts": {
            "drafted": 1,
            "awaiting_approval": 1,
            "sent": 1,
            "replied": 2,
            "flagged": 2,
        },
    }
    assert len(catalog["catalog_digest"]) == 64
    assert catalog["catalog_digest"] == outreach.build_catalog()["catalog_digest"]

    for thread in catalog["threads"]:
        statuses = [event["status"] for event in thread["lifecycle"]]
        if thread["current_status"] in {"sent", "replied", "flagged"}:
            assert "awaiting_approval" in statuses
            sent = [event for event in thread["lifecycle"] if event["action"] in {"sent", "reasked"}]
            assert sent and all(event["approved_by"] for event in sent)


def test_replies_become_only_structured_commitment_forecast_or_risk_entries():
    catalog = outreach.build_catalog()
    outcomes = [thread["outcome"] for thread in catalog["threads"] if thread.get("outcome")]

    assert {item["kind"] for item in outcomes} == {
        "confirmed_commitment", "updated_forecast", "flagged_risk"
    }
    assert {item["knowledge_entry"]["kind"] for item in outcomes} == {
        "commitment", "forecast", "risk"
    }
    def keys(value):
        if isinstance(value, dict):
            return set(value) | {key for item in value.values() for key in keys(item)}
        if isinstance(value, list):
            return {key for item in value for key in keys(item)}
        return set()

    for prohibited in ("raw_reply", "reply_text", "message_body", "mail_body"):
        assert prohibited not in keys(catalog)
    no_reply = next(item for item in catalog["threads"] if item["thread_id"] == "thread-no-reply-flagged")
    assert [item["action"] for item in no_reply["lifecycle"]][-2:] == ["reasked", "flagged"]
    assert no_reply["outcome"]["knowledge_entry"]["value"] == "response_gap_requires_human_review"


def test_contract_rejects_raw_reply_payload_and_unauthorized_send_shapes():
    body = outreach.load_pack().model_dump(mode="json")
    body["threads"][3]["raw_reply"] = "unstructured inbound text"
    with pytest.raises(ValidationError):
        outreach.OutreachPack.model_validate(body)

    body = outreach.load_pack().model_dump(mode="json")
    del body["threads"][2]["lifecycle"][-1]["approved_by"]
    with pytest.raises(ValidationError, match="named approver"):
        outreach.OutreachPack.model_validate(body)


def test_sector_detail_is_pack_data_and_core_contract_remains_neutral():
    source = Path(outreach.__file__).read_text(encoding="utf-8").lower()
    for sector_word in ("pharma", "healthcare", "hospital", "exchange", "security_type"):
        assert sector_word not in source

    base = outreach.load_pack().model_dump(mode="json")
    healthcare = deepcopy(base)
    healthcare["pack_id"] = "client-pack-health"
    healthcare["label"] = "Client distribution outreach"
    healthcare["providers"][0]["role"] = "Institutional account lead"
    exchange = deepcopy(base)
    exchange["pack_id"] = "client-pack-market"
    exchange["label"] = "Client market outreach"
    exchange["providers"][0]["role"] = "Issuer services lead"

    assert outreach.OutreachPack.model_validate(healthcare).providers[0].role == "Institutional account lead"
    assert outreach.OutreachPack.model_validate(exchange).providers[0].role == "Issuer services lead"


def test_authenticated_api_exposes_catalog_thread_and_knowledge_drilldown():
    with _client() as client:
        catalog = client.get("/api/outreach/synthetic")
        assert catalog.status_code == 200
        digest = catalog.json()["catalog_digest"]

        thread = client.get("/api/outreach/synthetic/threads/thread-commitment-replied")
        assert thread.status_code == 200
        assert thread.json()["catalog_digest"] == digest
        assert thread.json()["provider"]["name"] == "Omar Haddad"

        entry = client.get("/api/outreach/synthetic/knowledge/kg-commitment-delivery")
        assert entry.status_code == 200
        assert entry.json()["entry"]["predicate"] == "committed_delivery_date"
        assert entry.json()["source_thread"]["thread_id"] == "thread-commitment-replied"
        assert client.get("/api/outreach/synthetic/knowledge/missing").status_code == 404


def test_api_rejects_roles_without_product_read_access():
    with _client("bu") as client:
        assert client.get("/api/outreach/synthetic").status_code == 403


def test_outreach_ui_is_linked_and_exposes_required_demo_truths():
    root = Path(outreach.__file__).parent / "static"
    html = (root / "outreach.html").read_text(encoding="utf-8")
    js = (root / "outreach.js").read_text(encoding="utf-8")
    executive = (root / "executive.html").read_text(encoding="utf-8")

    assert 'href="/outreach"' in executive
    assert "Synthetic demonstration" in html
    assert "Connector disabled" in html
    assert "Raw reply text is never retained" in html
    assert "/api/outreach/synthetic" in js
    assert "Why this outreach exists" in js


def test_executive_can_create_a_tenant_scoped_data_request(monkeypatch, tmp_path):
    monkeypatch.setattr(outreach, "CONFIG", replace(outreach.CONFIG, output_root=tmp_path))
    with _client() as api:
        created = api.post("/api/outreach/requests", json={
            "kpi_label": "Cash vs floor",
            "provider": "Group Treasury",
            "formula": "Cash headroom = reported cash minus approved floor.",
            "missing_inputs": ["Current reported cash"],
            "source_contract_id": "Treasury source registry",
        })
        assert created.status_code == 201
        assert created.json()["status"] == "drafted"
        catalog = api.get("/api/outreach/synthetic").json()
        assert catalog["data_requests"][0]["request_id"] == created.json()["request_id"]
        assert catalog["data_requests"][0]["approval_required_before_send"] is True


def test_outreach_request_schema_is_tenant_scoped_and_immutable():
    migration = (Path(outreach.__file__).parent / "sql" / "dimensional_intent.sql").read_text(encoding="utf-8")
    runtime = (Path(outreach.__file__).parent / "database_schema.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS strategyos_outreach_requests" in migration
    assert "PRIMARY KEY(tenant_key, request_id)" in migration
    assert "'strategyos_outreach_requests'" in migration
    assert "governed_request_tables=intent_tables+',strategyos_outreach_requests'" in runtime
    assert "Worker and projector roles must not access executive outreach requests." in runtime
