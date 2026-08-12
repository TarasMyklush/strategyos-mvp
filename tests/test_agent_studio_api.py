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


def test_generated_agent_contains_business_specific_routes(monkeypatch: pytest.MonkeyPatch) -> None:
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
          "flow":[
            {"id":"incoming-call","kind":"entry","title":"Incoming call","condition":"","action":"Greet the caller and ask what they need","test_utterance":"Hello"},
            {"id":"product-question","kind":"route","title":"Product question","condition":"Caller asks what the product does","action":"Answer from approved website knowledge","test_utterance":"What does your product do?"},
            {"id":"qualified-buyer","kind":"route","title":"Qualified buyer","condition":"Caller wants to evaluate the product","action":"Ask one qualifying question and offer a consultation","test_utterance":"Can I see a demo?"},
            {"id":"existing-customer","kind":"route","title":"Existing customer","condition":"Caller needs support","action":"Collect the issue and route to support","test_utterance":"I need help with my account"},
            {"id":"safe-handoff","kind":"fallback","title":"Safe handoff","condition":"No route matches or facts are unavailable","action":"Explain the limit and offer a human handoff","test_utterance":"I have an unusual request"}
          ]
        }""",
    )

    result = agent_studio_api._generate_agent(
        {"url": "https://example.com", "title": "Example", "text": "Business information"},
        "book consultations",
    )

    assert result["agent_name"] == "Maya"
    assert [node["kind"] for node in result["flow"]] == ["entry", "route", "route", "route", "fallback"]
    assert result["flow"][1]["title"] == "Product question"


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
    monkeypatch.setattr(
        agent_studio_api,
        "_chat_with_agent",
        lambda request: {"reply": f"Using: {request.logic[4]['description']}", "active_node_id": "respond", "decision": "Matched response"},
    )
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
    assert response.json()["active_node_id"] == "respond"


def test_live_chat_returns_the_matched_generated_route(monkeypatch: pytest.MonkeyPatch) -> None:
    agent_studio_api._request_windows.clear()
    monkeypatch.setattr(
        agent_studio_api,
        "CONFIG",
        SimpleNamespace(model_provider_enabled=True, llm_chat_enabled=True, llm_api_key="test"),
    )
    monkeypatch.setattr(
        agent_studio_api,
        "_call_openai_compatible_chat",
        lambda **_kwargs: '{"reply":"I can help you book a demo.","active_node_id":"book-demo","decision":"The caller asked to evaluate the product."}',
    )
    flow = [
        {"id": "incoming", "kind": "entry", "title": "Incoming", "condition": "", "action": "Greet", "test_utterance": "Hello"},
        {"id": "questions", "kind": "route", "title": "Questions", "condition": "Asks a question", "action": "Answer", "test_utterance": "What is it?"},
        {"id": "book-demo", "kind": "route", "title": "Book demo", "condition": "Wants a demo", "action": "Qualify and book", "test_utterance": "Show me a demo"},
        {"id": "support", "kind": "route", "title": "Support", "condition": "Needs support", "action": "Collect issue", "test_utterance": "Help me"},
        {"id": "handoff", "kind": "fallback", "title": "Human handoff", "condition": "No safe match", "action": "Offer a human", "test_utterance": "Something else"},
    ]
    response = TestClient(app).post(
        "/public/agent-studio/chat",
        headers={"Origin": "https://demo.strategyos.live"},
        json={
            "business_name": "Example",
            "outcome": "book consultations",
            "flow": flow,
            "messages": [],
            "user_message": "Can I see a demo?",
        },
    )
    assert response.status_code == 200
    assert response.json()["active_node_id"] == "book-demo"
    assert response.json()["decision"] == "The caller asked to evaluate the product."
