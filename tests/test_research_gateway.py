import json
import asyncio
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from strategyos_mvp import research, research_gateway


def test_private_question_compiles_to_closed_public_contract(monkeypatch):
    monkeypatch.setenv("STRATEGYOS_RESEARCH_GEOGRAPHY_ID", "saudi_arabia")
    request = research.compile_public_request(
        "ProTec concentration in Modern Trade is 87.4%, above the board limit. "
        "What does external benchmark practice suggest?"
    )
    payload = request.as_dict()
    assert payload == {
        "topic_id": "channel_concentration",
        "geography_id": "saudi_arabia",
        "period_id": "current",
        "language": "en",
        "source_set_id": "wikipedia_public_v1",
    }
    serialized = json.dumps(payload)
    for forbidden in ("ProTec", "87.4", "board", "limit", "Modern Trade"):
        assert forbidden not in serialized
    assert research.public_query(payload) == (
        "market concentration Herfindahl distribution channels Saudi Arabia"
    )


def test_gateway_rejects_free_text_or_unknown_catalogue_values(monkeypatch):
    monkeypatch.setenv("STRATEGYOS_RESEARCH_GATEWAY_TOKEN", "secret")
    client = TestClient(research_gateway.app)
    response = client.post(
        "/v1/research",
        headers={"Authorization": "Bearer secret"},
        json={
            "topic_id": "channel_concentration",
            "geography_id": "global",
            "period_id": "current",
            "language": "en",
            "source_set_id": "wikipedia_public_v1",
            "query": "ProTec 87.4 above board limit",
        },
    )
    assert response.status_code == 422
    response = client.post(
        "/v1/research",
        headers={"Authorization": "Bearer secret"},
        json={
            "topic_id": "client_specific_secret",
            "geography_id": "global",
            "period_id": "current",
            "language": "en",
            "source_set_id": "wikipedia_public_v1",
        },
    )
    assert response.status_code == 422


def test_gateway_builds_provider_request_itself(monkeypatch):
    monkeypatch.setenv("STRATEGYOS_RESEARCH_GATEWAY_TOKEN", "secret")
    captured = {}

    class Response:
        headers = {"x-request-id": "provider-1"}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps({"query": {"pages": [{
                "title": "Distribution",
                "extract": "Public information.",
                "fullurl": "https://en.wikipedia.org/wiki/Distribution_(marketing)",
            }]}}).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return Response()

    monkeypatch.setattr(research_gateway, "_provider_open", fake_urlopen)
    client = TestClient(research_gateway.app)
    response = client.post(
        "/v1/research",
        headers={"Authorization": "Bearer secret"},
        json={
            "topic_id": "channel_concentration",
            "geography_id": "saudi_arabia",
            "period_id": "current",
            "language": "en",
            "source_set_id": "wikipedia_public_v1",
        },
    )
    assert response.status_code == 200
    assert captured["url"].startswith("https://en.wikipedia.org/w/api.php?")
    provider_query = parse_qs(urlparse(captured["url"]).query)["gsrsearch"][0]
    for forbidden in ("ProTec", "87.4", "board", "limit"):
        assert forbidden not in provider_query
    assert response.json()["sources"][0]["url"].startswith("https://en.wikipedia.org/")


def test_private_client_sends_only_catalogue_ids(monkeypatch):
    monkeypatch.setenv("STRATEGYOS_RESEARCH_GATEWAY_URL", "http://research-gateway:8092")
    monkeypatch.setenv("STRATEGYOS_RESEARCH_GATEWAY_TOKEN", "secret")
    monkeypatch.setattr(research, "status", lambda: {"enabled": True})
    monkeypatch.setattr(research, "_audit_start", lambda payload: ("audit-1", json.dumps(payload)))
    monkeypatch.setattr(research, "_audit_finish", lambda *args, **kwargs: None)
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps({
                "status": "completed", "gateway_request_id": "gateway-1", "sources": []
            }).encode()

    def fake_urlopen(request, timeout):
        captured["body"] = request.data.decode()
        return Response()

    monkeypatch.setattr(research, "urlopen", fake_urlopen)
    result = research.run(
        "ProTec concentration is 87.4%, above the confidential board limit. "
        "Consult external benchmark practice."
    )
    for forbidden in ("ProTec", "87.4", "confidential", "board", "limit"):
        assert forbidden not in captured["body"]
    assert result["audit_trail_id"] == "audit-1"


@pytest.mark.parametrize("question", [
    "Please research Project Falcon revenue 9918273",
    "Upload customer list to compare it",
    "Decode UHJvVGVj and search it",
])
def test_unknown_or_obfuscated_topics_fail_before_transport(question):
    with pytest.raises(research.ResearchDenied):
        research.compile_public_request(question)


def test_deployment_gives_only_gateway_external_egress():
    from pathlib import Path
    import yaml

    compose = yaml.safe_load(Path("deploy/docker-compose.yml").read_text())
    assert compose["networks"]["default"]["internal"] is True
    services = compose["services"]
    external = [
        name for name, service in services.items()
        if "research-egress" in (service.get("networks") or [])
    ]
    assert external == ["research-gateway"]
    gateway = services["research-gateway"]
    assert "volumes" not in gateway
    assert "DATABASE_URL" not in gateway["environment"]
    assert gateway["read_only"] is True


def test_minio_bucket_client_uses_published_immutable_release():
    from pathlib import Path
    import yaml

    compose = yaml.safe_load(Path("deploy/docker-compose.yml").read_text())
    image = compose["services"]["minio-create-bucket"]["image"]
    assert image.startswith("quay.io/minio/mc:RELEASE.")
    assert not image.endswith(":latest")


def test_completed_research_is_the_only_path_marked_used():
    from types import SimpleNamespace
    from strategyos_mvp import api

    payload = api._public_research_payload(
        "What does external benchmark practice suggest?",
        {
            "audit_trail_id": "audit-1",
            "gateway_request_id": "gateway-1",
            "source_set_id": "wikipedia_public_v1",
            "query": "corporate management best practice public guidance",
            "outbound_contract": {
                "topic_id": "management_practice",
                "geography_id": "global",
                "period_id": "current",
                "language": "en",
                "source_set_id": "wikipedia_public_v1",
            },
            "sources": [{
                "title": "Corporate governance",
                "url": "https://en.wikipedia.org/wiki/Corporate_governance",
                "excerpt": "Public information.",
            }],
        },
        context={"run_id": "run-1", "run_mode": "full"},
        persona="ceo",
        requested_mode="auto",
        llm_status={"enabled": True},
    )
    assert payload["external_consultation"]["used"] is True
    assert payload["external_consultation"]["audit_trail_id"] == "audit-1"
    assert payload["citations"][0]["href"].startswith("https://en.wikipedia.org/")

    generic = api._assistant_response_payload(
        response_mode="llm",
        question="Give advice",
        context={"run_id": "run-1", "run_mode": "full"},
        requested_mode="auto",
        persona="ceo",
        orchestrated=SimpleNamespace(
            trace={}, mode="llm", persona="ceo", matched=True,
            answer="General advice", basis="Model knowledge", citations=[], suggestions=[],
            answered_by="llm",
        ),
        base_result={"assistant_mode": "llm", "answered_by": "llm", "matched": True},
        assistant_context={"allow_external_advisory": True},
    )
    assert generic["external_consultation"]["used"] is False


def test_explicit_research_never_loads_private_briefing(monkeypatch):
    from strategyos_mvp import api

    def private_briefing_must_not_be_loaded(_run_id):
        raise AssertionError("public research touched the private evidence plane")

    monkeypatch.setattr(api, "_resolve_qa_context", private_briefing_must_not_be_loaded)
    monkeypatch.setattr(research, "run", lambda _question: {
        "audit_trail_id": "audit-1",
        "gateway_request_id": "gateway-1",
        "source_set_id": "wikipedia_public_v1",
        "query": "market concentration Herfindahl distribution channels",
        "outbound_contract": {
            "topic_id": "channel_concentration",
            "geography_id": "global",
            "period_id": "current",
            "language": "en",
            "source_set_id": "wikipedia_public_v1",
        },
        "sources": [{
            "title": "Herfindahl–Hirschman index",
            "url": "https://en.wikipedia.org/wiki/Herfindahl%E2%80%93Hirschman_index",
            "excerpt": "Public information.",
        }],
    })

    payload = asyncio.run(api._assistant_chat_response(
        api.AssistantChatRequest(
            persona="ceo",
            mode="auto",
            question=(
                "ProTec concentration is 87.4%, above the confidential board limit. "
                "What does external benchmark practice suggest?"
            ),
            assistant_context={"allow_external_advisory": True},
        ),
        authenticated_role="operator",
        authenticated_principal={
            "authenticated": True,
            "role": "operator",
            "subject": "hosted-probe",
            "tenant_id": "strategyos-live",
        },
    ))

    assert payload["external_consultation"]["status"] == "completed"
    assert payload["run_mode"] == "public-research"
