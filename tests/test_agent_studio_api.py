from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from strategyos_mvp import agent_studio_api
from strategyos_mvp.api import app


def test_normalize_public_url_defaults_to_https() -> None:
    assert agent_studio_api._normalize_public_url("example.com/about") == "https://example.com/about"


@pytest.mark.parametrize(
    "value",
    [
        "file:///etc/passwd",
        "https://user:password@example.com",
        "https://example.com:8443",
    ],
)
def test_normalize_public_url_rejects_unsafe_shapes(value: str) -> None:
    with pytest.raises(ValueError):
        agent_studio_api._normalize_public_url(value)


def test_private_destination_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_studio_api.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="Private"):
        agent_studio_api._assert_public_destination("https://example.com")


def test_client_rendered_page_uses_metadata_as_business_context() -> None:
    extractor = agent_studio_api._TextExtractor()
    extractor.feed("""
      <html><head>
        <title>LEGION — AI Operating System</title>
        <meta name="description" content="Persistent intelligence for AI-native software delivery.">
        <meta property="og:description" content="Specialist orchestration and multi-repo intelligence.">
        <script type="module" src="/assets/app.js"></script>
      </head><body><div id="root"></div></body></html>
    """)
    context = extractor.visible_text()
    assert "LEGION" in context
    assert "Persistent intelligence" in context
    assert "Specialist orchestration" in context


def test_generated_logic_must_have_canonical_six_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_studio_api,
        "CONFIG",
        SimpleNamespace(model_provider_enabled=True, llm_chat_enabled=True, llm_api_key="test"),
    )
    monkeypatch.setattr(
        agent_studio_api,
        "_call_openai_compatible_chat",
        lambda **_kwargs: """{
          "agent_name":"Maya",
          "summary":"Qualifies callers and books a consultation.",
          "opening_line":"Hello, how can I help?",
          "assumptions":["Transfer during office hours", "Use a 30-minute appointment"],
          "logic":[
            {"id":"trigger","title":"Trigger","description":"Answer inbound calls"},
            {"id":"understand","title":"Understand","description":"Identify need and urgency"},
            {"id":"retrieve","title":"Retrieve","description":"Use approved website knowledge"},
            {"id":"decide","title":"Decide","description":"Answer, book or transfer"},
            {"id":"respond","title":"Respond","description":"Guide the caller to the right step"},
            {"id":"complete","title":"Complete","description":"Save outcome and context"}
          ]
        }""",
    )

    result = agent_studio_api._generate_agent(
        {"url": "https://example.com", "title": "Example", "text": "Business information"},
        "book consultations",
    )

    assert result["agent_name"] == "Maya"
    assert [node["id"] for node in result["logic"]] == list(agent_studio_api.EXPECTED_NODE_IDS)


def test_public_generate_route_allows_only_demo_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    agent_studio_api._request_windows.clear()
    monkeypatch.setattr(
        agent_studio_api,
        "_read_website",
        lambda url: {"url": url, "title": "Example", "text": "Example business context"},
    )
    monkeypatch.setattr(
        agent_studio_api,
        "_generate_agent",
        lambda _context, _outcome: {"agent_name": "Maya", "logic": []},
    )
    response = TestClient(app).post(
        "/public/agent-studio/generate",
        headers={"Origin": "https://demo.strategyos.live"},
        json={"website": "https://example.com", "outcome": "book consultations"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://demo.strategyos.live"


def test_live_chat_uses_current_editable_logic(monkeypatch: pytest.MonkeyPatch) -> None:
    agent_studio_api._request_windows.clear()
    monkeypatch.setattr(agent_studio_api, "_chat_with_agent", lambda request: f"Using: {request.logic[4]['description']}")
    logic = [
        {"id": node_id, "title": node_id.title(), "description": "default"}
        for node_id in agent_studio_api.EXPECTED_NODE_IDS
    ]
    logic[4]["description"] = "Always offer a discovery call"
    response = TestClient(app).post(
        "/public/agent-studio/chat",
        headers={"Origin": "https://demo.strategyos.live"},
        json={
            "business_name": "Example",
            "outcome": "book consultations",
            "logic": logic,
            "messages": [],
            "user_message": "What should I do next?",
        },
    )
    assert response.status_code == 200
    assert response.json()["reply"] == "Using: Always offer a discovery call"
