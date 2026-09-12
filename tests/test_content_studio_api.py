import json
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient

from strategyos_mvp import auth, content_studio_api
from strategyos_mvp.api import app


TOKEN = "content-studio-test-" + "x" * 32


def configured(monkeypatch):
    monkeypatch.setenv("STRATEGYOS_CONTENT_STUDIO_TOKEN", TOKEN)
    monkeypatch.setattr(
        content_studio_api,
        "CONFIG",
        SimpleNamespace(
            model_provider_enabled=True,
            llm_chat_enabled=True,
            llm_provider="codex_cli",
            llm_api_key="private-gateway-key",
            llm_base_url="http://codex-gateway:8091/v1",
            llm_model="gpt-5.6-sol",
        ),
    )
    content_studio_api._request_times.clear()


def test_integration_requires_dedicated_token(monkeypatch):
    configured(monkeypatch)
    response = TestClient(app).post(
        "/integrations/evidence-content/research", json={"query": "evidence-led content"}
    )
    assert response.status_code == 401


def test_research_uses_live_search_and_returns_sources(monkeypatch):
    configured(monkeypatch)
    captured = {}

    def fake_call(messages, *, live_search, max_tokens):
        captured.update(messages=messages, live_search=live_search, max_tokens=max_tokens)
        return json.dumps({
            "summary": "Current sources agree on evidence quality.",
            "results": [{
                "title": "Primary source",
                "url": "https://example.com/report",
                "publisher": "Example",
                "published_at": "2026-09-01",
                "claim": "Evidence should be traceable.",
                "evidence_excerpt": "A short source-grounded passage.",
                "why_it_matters": "Supports the trust phase.",
            }],
            "gaps": ["Independent replication"],
        })

    monkeypatch.setattr(content_studio_api, "_call_codex", fake_call)
    response = TestClient(app).post(
        "/integrations/evidence-content/research",
        headers={"Authorization": "Bearer " + TOKEN},
        json={"query": "evidence-led content", "audience": "editors", "promise": "publish safely"},
    )
    assert response.status_code == 200
    assert captured["live_search"] is True
    assert response.json()["search_mode"] == "live-web"
    assert response.json()["results"][0]["url"] == "https://example.com/report"


def test_integration_token_bypasses_interactive_identity_boundary(monkeypatch):
    configured(monkeypatch)

    def reject_as_identity(**_kwargs):
        raise HTTPException(401, "A valid identity token is required.")

    monkeypatch.setattr(auth, "authenticate_optional_request", reject_as_identity)
    monkeypatch.setattr(
        content_studio_api,
        "_call_codex",
        lambda *_args, **_kwargs: json.dumps({
            "summary": "The dedicated integration credential was accepted.",
            "results": [{
                "title": "Primary source",
                "url": "https://example.com/report",
                "publisher": "Example",
                "published_at": "2026-09-01",
                "claim": "The protected route is reachable.",
                "evidence_excerpt": "A short source-grounded passage.",
                "why_it_matters": "Proves the server-to-server boundary.",
            }],
            "gaps": [],
        }),
    )
    response = TestClient(app).post(
        "/integrations/evidence-content/research",
        headers={"Authorization": "Bearer " + TOKEN},
        json={"query": "evidence-led content"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"


def test_generation_uses_saved_evidence_without_search(monkeypatch):
    configured(monkeypatch)
    captured = {}

    def fake_call(messages, *, live_search, max_tokens):
        captured.update(messages=messages, live_search=live_search, max_tokens=max_tokens)
        return json.dumps({
            "article_markdown": "# Evidence-led article\n\n" + "A supported paragraph. " * 12,
            "editorial_note": "Review the remaining claim.",
            "claims_to_verify": ["One unresolved benchmark"],
        })

    monkeypatch.setattr(content_studio_api, "_call_codex", fake_call)
    response = TestClient(app).post(
        "/integrations/evidence-content/generate",
        headers={"Authorization": "Bearer " + TOKEN},
        json={
            "title": "Evidence-led article",
            "audience": "content leaders",
            "promise": "build a defensible workflow",
            "evidence": [{
                "claim": "Evidence should be traceable",
                "source_title": "Primary source",
                "source_url": "https://example.com/report",
                "passage": "Trace every material claim.",
            }],
        },
    )
    assert response.status_code == 200
    assert captured["live_search"] is False
    assert response.json()["claims_to_verify"] == ["One unresolved benchmark"]
