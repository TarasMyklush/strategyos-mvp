import json
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
import strategyos_mvp.run_registry as run_registry_module
import strategyos_mvp.state_store as state_store
from strategyos_mvp.config import load_config
from strategyos_mvp.executive_design import executive_public_assistant_context


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
    run_registry_module.CONFIG = config
    state_store.CONFIG = config
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
    run_registry_module.CONFIG = config
    state_store.CONFIG = config


def _client_with_auth():
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-key",
        }
    )
    return original, TestClient(api_module.app)


def _client_with_public_ceo_surface(*, llm_enabled: bool = False):
    env = {
        "STRATEGYOS_API_AUTH_ENABLED": "true",
        "STRATEGYOS_IDP_ENABLED": "true",
        "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
        "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
        "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
        "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
        "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
    }
    if llm_enabled:
        env.update(
            {
                "STRATEGYOS_RUN_POLICY": "external-approved",
                "STRATEGYOS_APPROVED_EXTERNAL_MODES": "model_provider_use",
                "STRATEGYOS_MODEL_PROVIDER_ENABLED": "true",
                "STRATEGYOS_LLM_CHAT_ENABLED": "true",
                "STRATEGYOS_LLM_API_KEY": "test-key",
                "STRATEGYOS_LLM_MODEL": "gpt-test",
            }
        )
    original = _apply_env(env)
    return original, TestClient(api_module.app)


def _client_with_identity_auth():
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
        }
    )
    return original, TestClient(api_module.app)


def _parsed_scenario(*, matched: bool = False, payload: dict | None = None):
    result_payload = dict(payload or {"matched": matched, "citations": [], "suggestions": []})

    class ParsedScenario:
        def __init__(self):
            self.matched = matched

        def as_dict(self):
            return dict(result_payload)

    return ParsedScenario()


def test_qa_requires_auth(monkeypatch):
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {"bundle": object(), "findings": [], "run_id": run_id, "run_mode": "full"},
        )

        response = client.post("/qa", json={"question": "total invoices"})

        assert response.status_code == 401
    finally:
        _restore_env(original)


def test_qa_endpoint_returns_answer_and_suggestions(monkeypatch):
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {"bundle": object(), "findings": [], "run_id": "run-1", "run_mode": "full"},
        )

        def fake_answer(question, *, bundle, findings):
            if question == "gibberish xyz":
                return {"matched": False, "answer": "Try one of these:", "suggestions": ["Top 5 vendors by spend"], "citations": []}
            return {
                "matched": True,
                "answer": "The total AP invoice amount is SAR 133,646,616.03 across 1,397 invoices.",
                "value": 133_646_616.03,
                "unit": "SAR",
                "basis": "sum of Amount_SAR over 1,397 AP rows.",
                "intent": "invoice_metric",
                "citations": [{"source_path": "02_ERP_Extracts/AP_Invoices_H1_2026.xlsx", "locator": "Amount_SAR"}],
            }

        monkeypatch.setattr(api_module.qa_engine, "answer_question", fake_answer)

        answered = client.post(
            "/qa",
            json={"question": "what is the total amount of invoices?"},
            headers={"X-API-Key": "operator-key"},
        )
        assert answered.status_code == 200
        assert answered.json()["value"] == 133_646_616.03
        assert answered.json()["citations"][0]["source_path"].endswith("AP_Invoices_H1_2026.xlsx")

        unmatched = client.post(
            "/qa",
            json={"question": "gibberish xyz"},
            headers={"X-API-Key": "reviewer-key"},
        )
        assert unmatched.status_code == 200
        assert unmatched.json()["matched"] is False
        assert unmatched.json()["suggestions"]
    finally:
        _restore_env(original)


def test_qa_llm_mode_is_blocked_until_configured():
    original, client = _client_with_auth()
    try:
        response = client.post(
            "/qa",
            json={"question": "summarize the run", "mode": "llm"},
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 403
        assert "LLM chat is disabled" in response.json()["detail"]
    finally:
        _restore_env(original)


def test_qa_llm_mode_uses_configured_adapter(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-key",
            "STRATEGYOS_RUN_POLICY": "external-approved",
            "STRATEGYOS_APPROVED_EXTERNAL_MODES": "model_provider_use",
            "STRATEGYOS_MODEL_PROVIDER_ENABLED": "true",
            "STRATEGYOS_LLM_CHAT_ENABLED": "true",
            "STRATEGYOS_LLM_API_KEY": "test-key",
            "STRATEGYOS_LLM_MODEL": "gpt-test",
        }
    )
    try:
        client = TestClient(api_module.app)
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {
                "bundle": object(),
                "findings": [],
                "summary": {"run_id": "run-1"},
                "run_id": "run-1",
                "run_mode": "full",
            },
        )

        def fake_answer(question, *, bundle, findings, summary, config, **_kwargs):
            assert question == "summarize the run"
            assert config.llm_model == "gpt-test"
            return {
                "matched": True,
                "answer": "LLM summary",
                "basis": "Supplied run evidence.",
                "citations": [],
                "suggestions": [],
                "llm_status": {"enabled": True, "model": config.llm_model},
            }

        monkeypatch.setattr(api_module.llm_qa, "answer_question", fake_answer)

        response = client.post(
            "/qa",
            json={"question": "summarize the run", "mode": "llm"},
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "llm"
        assert payload["answer"] == "LLM summary"
        assert payload["llm_status"]["model"] == "gpt-test"
    finally:
        _restore_env(original)


def test_assistant_chat_llm_mode_uses_configured_adapter(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-key",
            "STRATEGYOS_RUN_POLICY": "external-approved",
            "STRATEGYOS_APPROVED_EXTERNAL_MODES": "model_provider_use",
            "STRATEGYOS_MODEL_PROVIDER_ENABLED": "true",
            "STRATEGYOS_LLM_CHAT_ENABLED": "true",
            "STRATEGYOS_LLM_API_KEY": "test-key",
            "STRATEGYOS_LLM_MODEL": "gpt-test",
        }
    )
    try:
        client = TestClient(api_module.app)
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {
                "bundle": object(),
                "findings": [],
                "summary": {"run_id": "run-1"},
                "run_id": "run-1",
                "run_mode": "full",
            },
        )

        def fake_answer(question, *, bundle, findings, summary, config, **_kwargs):
            assert question == "summarize the run"
            assert config.llm_model == "gpt-test"
            return {
                "matched": True,
                "answer": "Assistant LLM summary",
                "basis": "Supplied run evidence.",
                "citations": [],
                "suggestions": [],
                "llm_status": {"enabled": True, "model": config.llm_model},
            }

        monkeypatch.setattr(api_module.llm_qa, "answer_question", fake_answer)

        response = client.post(
            "/assistant/chat",
            json={"question": "summarize the run", "mode": "llm", "persona": "ceo"},
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "llm"
        assert payload["answer"] in {"Assistant LLM summary", "Assistant AI summary"}
        assert payload["llm_status"]["model"] == "gpt-test"
    finally:
        _restore_env(original)


def test_assistant_chat_llm_mode_sanitizes_raw_json_answer(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_RUN_POLICY": "external-approved",
            "STRATEGYOS_APPROVED_EXTERNAL_MODES": "model_provider_use",
            "STRATEGYOS_MODEL_PROVIDER_ENABLED": "true",
            "STRATEGYOS_LLM_CHAT_ENABLED": "true",
            "STRATEGYOS_LLM_API_KEY": "test-key",
            "STRATEGYOS_LLM_MODEL": "gpt-test",
        }
    )
    client = TestClient(api_module.app)
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {
                "bundle": object(),
                "findings": [],
                "summary": {"run_id": "run-1"},
                "run_id": "run-1",
                "run_mode": "full",
            },
        )
        monkeypatch.setattr(
            api_module,
            "parse_scenario",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("mode=llm should bypass deterministic scenario routing")),
        )
        monkeypatch.setattr(
            api_module.llm_qa,
            "answer_question",
            lambda *_args, **_kwargs: {
                "matched": True,
                "answer": '{\n  "matched": true,\n  "answer": "Plain-English board packet summary.",\n  "basis": "Grounded in the public packet.",\n  "citations": [],\n  "suggestions": []\n}',
                "basis": "Grounded in the public packet.",
                "citations": [],
                "suggestions": [],
                "llm_status": {"enabled": True, "provider": "deepseek", "model": "gpt-test"},
            },
        )

        response = client.post(
            "/assistant/chat",
            json={"question": "summarize the run in plain English", "persona": "ceo", "mode": "llm"},
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answer"] in {
            "Plain-English board packet summary.",
            "Plain-English board current view summary.",
        }
        assert not payload["answer"].lstrip().startswith("{")
    finally:
        _restore_env(original)


def test_assistant_chat_golden_prompt_works_without_completed_run(monkeypatch):
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: None)

        response = client.post(
            "/assistant/chat",
            json={
                "question": "Simulate digital health flat by end of year",
                "persona": "ceo",
                "mode": "auto",
            },
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["scenario_id"] == "digital_health_eoy_flat"
        assert payload["matched"] is True
        assert payload["prompt_contracts"]["role"]["prompt_id"] == "role:ceo:v1"
        assert payload["hallucination_risk"]["level"] == "high"
        assert payload["citations"], "golden prompt must return top-level evidence citations"
        assert payload["assumptions"], "golden prompt must return top-level assumptions"
        assert payload["run_mode"] == "no-run"
    finally:
        _restore_env(original)


def test_assistant_chat_no_run_deterministic_question_returns_safe_fallback(monkeypatch):
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: None)

        response = client.post(
            "/assistant/chat",
            json={
                "question": "What is the total amount of invoices?",
                "persona": "ceo",
                "mode": "deterministic",
            },
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_mode"] == "no-run"
        assert payload["matched"] is False
        assert payload["llm_fallback_attempted"] is False
        assert "No completed governed run is available yet" in payload["answer"]
        assert "NoneType" not in payload["answer"]
        assert "NoneType" not in payload["basis"]
    finally:
        _restore_env(original)


def test_assistant_chat_public_ceo_scenario_works_under_identity_provider(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        client = TestClient(api_module.app)

        response = client.post(
            "/assistant/chat",
            json={
                "question": "Simulate digital health flat by end of year",
                "persona": "ceo",
                "mode": "auto",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["scenario_id"] == "digital_health_eoy_flat"
        assert payload["matched"] is True
        assert payload["prompt_contracts"]["role"]["prompt_id"] == "role:ceo:v1"
        assert payload["hallucination_risk"]["level"] == "low"
        assert payload["citations"]
        assert payload["trace"]
        assert payload["run_id"] == "latest-public"
        assert payload["run_mode"] == "public-safe"
    finally:
        _restore_env(original)


def test_assistant_chat_public_ceo_request_stays_public_safe_even_when_run_exists(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        client = TestClient(api_module.app)

        response = client.post(
            "/assistant/chat",
            json={
                "question": "What is the total amount of invoices?",
                "persona": "ceo",
                "mode": "deterministic",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_id"] == "latest-public"
        assert payload["run_mode"] == "public-safe"
        assert payload["matched"] is False
        assert payload["llm_fallback_attempted"] is False
        assert payload["answered_by"] in {"packet", "scenario"}
        assert any(token in payload["answer"].lower() for token in ("margin story", "current view", "public packet"))
    finally:
        _restore_env(original)


def test_assistant_chat_public_auto_unmatched_does_not_call_llm_when_enabled(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))
        called = {"llm": 0}

        def fake_answer(*_args, **_kwargs):
            called["llm"] += 1
            raise AssertionError("public-safe route must not call llm_qa.answer_question")

        monkeypatch.setattr(api_module.llm_qa, "answer_question", fake_answer)

        response = client.post(
            "/assistant/chat",
            json={"question": "give me numbers for last week", "persona": "ceo", "mode": "auto"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "deterministic"
        assert payload["requested_mode"] == "auto"
        assert payload["run_mode"] == "public-safe"
        assert payload["llm_fallback_attempted"] is False
        assert payload["answered_by"] in {"packet", "scenario"}
        assert payload["llm_status"]["enabled"] is False
        assert called["llm"] == 0
    finally:
        _restore_env(original)


def test_assistant_chat_public_ceo_margin_pressure_prompt_returns_packet_answer():
    original, client = _client_with_public_ceo_surface()
    try:
        response = client.post(
            "/assistant/chat",
            json={
                "question": "What is driving margin pressure this quarter?",
                "persona": "ceo",
                "mode": "auto",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "deterministic"
        assert payload["matched"] is True
        text = payload["answer"].lower()
        assert "fx" in text
        assert "api" in text
        assert "healthcare occupancy" in text
        assert "tamween" in text
        assert "public-safe" not in text
        assert "deterministic" not in text
    finally:
        _restore_env(original)


def test_assistant_chat_public_llm_mode_returns_403_and_never_calls_llm_when_enabled(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))
        monkeypatch.setattr(
            api_module.llm_qa,
            "answer_question",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("public-safe route must not call llm_qa.answer_question")),
        )

        response = client.post(
            "/assistant/chat",
            json={"question": "summarize the board packet in plain English", "persona": "ceo", "mode": "llm"},
        )

        assert response.status_code == 403
        assert "Public-safe surface disables llm, graph, and vector grounding." in response.json()["detail"]
    finally:
        _restore_env(original)


def test_answered_by_never_claims_graph_vector_or_llm_on_public_safe_surface(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))

        response = client.post(
            "/assistant/chat",
            json={"question": "show evidence for F-004", "persona": "ceo", "mode": "auto"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] not in {"graph", "vector", "llm"}
    finally:
        _restore_env(original)


def test_assistant_chat_public_board_pack_review_prompt_returns_useful_packet_answer(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "Help me prepare the board pack for the pre-board stage. What needs CEO review, what evidence is missing, and what should I do next?",
                "persona": "ceo",
                "mode": "auto",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_mode"] == "public-safe"
        assert payload["matched"] is True
        assert payload["scenario_id"] == "public_exec_board_pack_review"
        assert payload["answered_by"] == "packet"
        assert "challenged case" in payload["answer"].lower()
    finally:
        _restore_env(original)


def test_assistant_chat_public_challenged_cases_prompt_returns_useful_packet_answer(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "Help me close challenged cases before the board meeting. Which cases are challenged, what evidence is needed, and what is my next action?",
                "persona": "ceo",
                "mode": "auto",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_mode"] == "public-safe"
        assert payload["matched"] is True
        assert payload["scenario_id"] == "public_exec_challenged_cases"
        assert payload["answered_by"] == "packet"
        assert "next action" in payload["answer"].lower() or "next step" in payload["answer"].lower()
    finally:
        _restore_env(original)


def test_assistant_chat_authenticated_graph_route_returns_graph_provenance(monkeypatch):
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {"bundle": object(), "findings": [], "summary": {"run_id": "run-1"}, "run_id": "run-1", "run_mode": "full", "kg_nodes": [], "kg_edges": []},
        )
        monkeypatch.setattr(api_module, "route_graph_question", lambda run_id, question: {"matched": True, "answer": "Graph answer", "basis": "Neo4j traversal", "citations": [{"source_path": "08_Invoices/invoice.pdf", "locator": "Finding:F-004"}], "assistant_mode": "graph", "answered_by": "graph", "intent": "finding_evidence_chain"})
        monkeypatch.setattr(api_module, "_route_keyword_retrieval", lambda run_id, question: {"matched": False})
        monkeypatch.setattr(api_module.qa_engine, "answer_question", lambda *_args, **_kwargs: {"matched": False, "answer": "no tabular", "citations": [], "suggestions": []})

        response = client.post(
            "/assistant/chat",
            json={"question": "show evidence for F-004", "persona": "ceo", "mode": "auto"},
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] == "graph"
        assert payload["answer"] in {"Graph answer", "answer"}
    finally:
        _restore_env(original)


def test_assistant_chat_authenticated_executive_token_uses_private_run_context(monkeypatch):
    original, client = _client_with_public_ceo_surface()
    try:
        monkeypatch.setattr(
            auth_module,
            "_introspect_identity_token",
            lambda token: {"role": "executive", "subject": "idp:test-user", "tenant_id": "strategyos"},
        )
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {"bundle": object(), "findings": [], "summary": {"run_id": "run-auth-1"}, "run_id": "run-auth-1", "run_mode": "full", "kg_nodes": [], "kg_edges": []},
        )
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))
        monkeypatch.setattr(api_module, "route_graph_question", lambda run_id, question: {"matched": True, "answer": "KG-backed executive answer", "basis": "Neo4j traversal", "citations": [], "assistant_mode": "graph", "answered_by": "graph", "intent": "vendor_collusion_cluster"})
        monkeypatch.setattr(api_module, "_route_keyword_retrieval", lambda run_id, question: {"matched": False})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "Which vendors are implicated in collusion clusters and what evidence supports it? Explain for the CEO.",
                "persona": "ceo",
                "mode": "auto",
                "source": "executive_surface",
                "entrypoint": "drawer_input",
            },
            headers={"Authorization": "Bearer executive-token"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_id"] == "run-auth-1"
        assert payload["run_mode"] == "full"
        assert payload["answered_by"] == "graph"
    finally:
        _restore_env(original)


def test_assistant_chat_authenticated_identity_token_uses_private_run_context(monkeypatch):
    original, client = _client_with_identity_auth()
    try:
        monkeypatch.setattr(
            auth_module,
            "_introspect_identity_token",
            lambda token: {"role": "executive", "subject": "idp:test-user", "tenant_id": "strategyos"},
        )
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {"bundle": object(), "findings": [], "summary": {"run_id": "run-1"}, "run_id": "run-1", "run_mode": "full", "kg_nodes": [], "kg_edges": []},
        )
        monkeypatch.setattr(api_module, "route_graph_question", lambda run_id, question: {"matched": True, "answer": "Graph answer", "basis": "Neo4j traversal", "citations": [], "assistant_mode": "graph", "answered_by": "graph", "intent": "vendor_collusion_cluster"})
        monkeypatch.setattr(api_module, "_route_keyword_retrieval", lambda run_id, question: {"matched": False})
        monkeypatch.setattr(api_module.qa_engine, "answer_question", lambda *_args, **_kwargs: {"matched": False, "answer": "no tabular", "citations": [], "suggestions": []})

        response = client.post(
            "/assistant/chat",
            json={"question": "Which vendors are implicated in collusion clusters?", "persona": "ceo", "mode": "auto"},
            headers={"Authorization": "Bearer live-token"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_id"] == "run-1"
        assert payload["run_mode"] == "full"
        assert payload["answered_by"] == "graph"
    finally:
        _restore_env(original)


def test_assistant_chat_graph_route_short_circuits_tabular_qa(monkeypatch):
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {"bundle": object(), "findings": [], "summary": {"run_id": "run-1"}, "run_id": "run-1", "run_mode": "full", "kg_nodes": [], "kg_edges": []},
        )
        monkeypatch.setattr(api_module, "route_graph_question", lambda run_id, question: {"matched": True, "answer": "Graph answer", "basis": "Neo4j traversal", "citations": [], "assistant_mode": "graph", "answered_by": "graph", "intent": "finding_evidence_chain"})
        monkeypatch.setattr(api_module, "_route_keyword_retrieval", lambda run_id, question: {"matched": False})
        monkeypatch.setattr(
            api_module.qa_engine,
            "answer_question",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("graph grounding should run before tabular QA")),
        )

        response = client.post(
            "/assistant/chat",
            json={"question": "show evidence for F-004", "persona": "ceo", "mode": "auto"},
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        assert response.json()["answered_by"] == "graph"
    finally:
        _restore_env(original)


def test_qa_vector_route_falls_through_when_disabled(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_VECTOR_ROUTING_ENABLED": "false",
        }
    )
    try:
        client = TestClient(api_module.app)
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {"bundle": object(), "findings": [], "summary": {"run_id": "run-1"}, "run_id": "run-1", "run_mode": "full", "kg_nodes": [], "kg_edges": []},
        )
        monkeypatch.setattr(api_module.qa_engine, "answer_question", lambda *_args, **_kwargs: {"matched": False, "answer": "No deterministic answer.", "citations": [], "suggestions": []})
        monkeypatch.setattr(api_module, "route_graph_question", lambda run_id, question: {"matched": False})

        response = client.post(
            "/qa",
            json={"question": "show supporting evidence document", "mode": "deterministic"},
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] in {"fallback", "persona_canned"}
    finally:
        _restore_env(original)


def test_qa_vector_route_returns_keyword_provenance_when_configured(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_VECTOR_ROUTING_ENABLED": "true",
            "STRATEGYOS_QDRANT_URL": "http://qdrant:6333",
        }
    )
    try:
        client = TestClient(api_module.app)
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {"bundle": object(), "findings": [], "summary": {"run_id": "run-1"}, "run_id": "run-1", "run_mode": "full", "kg_nodes": [], "kg_edges": []},
        )
        monkeypatch.setattr(api_module, "check_qdrant_ready", lambda: {"status": "ok", "hybrid_mode": "lexical_keyword", "embedding_backend": "hash_fallback"})
        monkeypatch.setattr(api_module, "search_run_vectors", lambda run_id, question, limit=3: {"status": "ready", "results": [{"title": "Invoice support", "source_path": "08_Invoices/invoice.pdf", "locator": "row 1", "excerpt": "paid twice"}]})
        monkeypatch.setattr(api_module, "route_graph_question", lambda run_id, question: {"matched": False})
        monkeypatch.setattr(api_module.qa_engine, "answer_question", lambda *_args, **_kwargs: {"matched": False, "answer": "No deterministic answer.", "citations": [], "suggestions": []})

        response = client.post(
            "/qa",
            json={"question": "show supporting evidence document", "mode": "deterministic"},
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] == "vector"
        assert payload["citations"][0]["source_path"] == "08_Invoices/invoice.pdf"
    finally:
        _restore_env(original)


def test_qa_graph_route_short_circuits_tabular_qa(monkeypatch):
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {"bundle": object(), "findings": [], "summary": {"run_id": "run-1"}, "run_id": "run-1", "run_mode": "full", "kg_nodes": [], "kg_edges": []},
        )
        monkeypatch.setattr(api_module, "route_graph_question", lambda run_id, question: {"matched": True, "answer": "Graph answer", "basis": "Neo4j traversal", "citations": [], "assistant_mode": "graph", "answered_by": "graph", "intent": "finding_evidence_chain"})
        monkeypatch.setattr(api_module, "_route_keyword_retrieval", lambda run_id, question: {"matched": False})
        monkeypatch.setattr(
            api_module.qa_engine,
            "answer_question",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("graph grounding should run before tabular QA")),
        )

        response = client.post(
            "/qa",
            json={"question": "show evidence for F-004", "persona": "ceo", "mode": "auto"},
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        assert response.json()["answered_by"] == "graph"
    finally:
        _restore_env(original)


def test_qa_llm_mode_preserves_graph_grounding_when_llm_cannot_synthesize(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_RUN_POLICY": "external-approved",
            "STRATEGYOS_APPROVED_EXTERNAL_MODES": "model_provider_use",
            "STRATEGYOS_MODEL_PROVIDER_ENABLED": "true",
            "STRATEGYOS_LLM_CHAT_ENABLED": "true",
            "STRATEGYOS_LLM_API_KEY": "test-key",
            "STRATEGYOS_LLM_MODEL": "gpt-test",
        }
    )
    try:
        client = TestClient(api_module.app)
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {"bundle": object(), "findings": [], "summary": {"run_id": "run-1"}, "run_id": "run-1", "run_mode": "full", "kg_nodes": [], "kg_edges": []},
        )
        monkeypatch.setattr(api_module, "route_graph_question", lambda run_id, question: {"matched": True, "answer": "Tamween Distribution and Al Rashid share the same bank account. CEO implication: linked vendor identities need immediate review.", "basis": "Neo4j traversal", "citations": [{"source_path": "03_Master_Data/Vendor_Master.xlsx", "locator": "Vendor:V-1"}], "assistant_mode": "graph", "answered_by": "graph", "intent": "vendor_collusion_cluster"})
        monkeypatch.setattr(api_module, "_route_keyword_retrieval", lambda run_id, question: {"matched": False})
        monkeypatch.setattr(api_module.qa_engine, "answer_question", lambda *_args, **_kwargs: {"matched": False, "answer": "No deterministic answer.", "citations": [], "suggestions": [], "answered_by": "tabular"})
        monkeypatch.setattr(api_module.llm_qa, "answer_question", lambda *args, **kwargs: {"matched": False, "answer": "", "basis": "Insufficient synthesis.", "citations": [], "suggestions": [], "llm_status": {"enabled": True, "model": "gpt-test"}})

        response = client.post(
            "/qa",
            json={"question": "Which vendors are implicated in collusion clusters and what evidence supports it? Explain for the CEO.", "persona": "ceo", "mode": "llm"},
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "llm"
        assert payload["answered_by"] == "graph"
        assert "CEO implication" in payload["answer"]
        assert payload["llm_grounded_fallback"] is True
    finally:
        _restore_env(original)


def test_qa_llm_mode_preserves_graph_grounding_when_graph_matches(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_RUN_POLICY": "external-approved",
            "STRATEGYOS_APPROVED_EXTERNAL_MODES": "model_provider_use",
            "STRATEGYOS_MODEL_PROVIDER_ENABLED": "true",
            "STRATEGYOS_LLM_CHAT_ENABLED": "true",
            "STRATEGYOS_LLM_API_KEY": "test-key",
            "STRATEGYOS_LLM_MODEL": "gpt-test",
        }
    )
    client = TestClient(api_module.app)
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: {"bundle": object(), "findings": [], "summary": {"run_id": "run-1"}, "run_id": "run-1", "run_mode": "full", "kg_nodes": [], "kg_edges": []},
        )
        monkeypatch.setattr(api_module, "route_graph_question", lambda run_id, question: {"matched": True, "answer": "Tamween Distribution and Alpha LLC share a bank account. CEO implication: investigate before further payments.", "basis": "Neo4j traversal", "citations": [{"source_path": "03_Master_Data/Vendor_Master.xlsx", "locator": "Vendor:V-1"}], "assistant_mode": "graph", "answered_by": "graph", "intent": "vendor_collusion_cluster"})
        monkeypatch.setattr(api_module, "_route_keyword_retrieval", lambda run_id, question: {"matched": False})
        monkeypatch.setattr(api_module.qa_engine, "answer_question", lambda *_args, **_kwargs: {"matched": False, "answer": "No deterministic answer.", "citations": [], "suggestions": []})
        monkeypatch.setattr(api_module.llm_qa, "answer_question", lambda *_args, **_kwargs: {"matched": False, "answer": "The current board pack shows governed data.", "basis": "generic fallback", "citations": [], "suggestions": [], "llm_status": {"enabled": True}})

        response = client.post(
            "/qa",
            json={"question": "Which vendors are implicated in collusion clusters and what evidence supports it? Explain for the CEO.", "persona": "ceo", "mode": "llm"},
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] == "graph"
        assert "Tamween Distribution and Alpha LLC" in payload["answer"]
    finally:
        _restore_env(original)


def test_assistant_chat_public_finance_terms_do_not_hit_generic_persona_templates(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))

        for question in (
            "what's driving the margin variance?",
            "show revenue risk",
            "what's our cash risk?",
            "which kpi matters most right now?",
        ):
            response = client.post(
                "/assistant/chat",
                json={"question": question, "persona": "ceo", "mode": "auto"},
            )
            assert response.status_code == 200, question
            payload = response.json()
            assert payload["mode"] == "deterministic", question
            assert payload["answered_by"] == "packet", question
            assert "which aspect would you like to examine" not in payload["answer"].lower(), question
            assert "which part do you want to explore" not in payload["answer"].lower(), question
    finally:
        _restore_env(original)


def test_public_assistant_context_is_shared_between_bootstrap_and_chat_context(monkeypatch):
    monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

    bootstrap = api_module._ui_bootstrap()
    resolver_payload = api_module._resolve_public_assistant_context("latest-public", persona="ceo")
    packet = executive_public_assistant_context()

    assert bootstrap["assistant_public_context"]["packet_id"] == packet["packet_id"]
    assert resolver_payload["summary"]["assistant_context_source"] == packet["packet_id"]
    facts_text = " ".join(packet["facts"]).lower()
    for term in ["tamween", "1.2m", "8.6m", "e-pharmacy", "fx", "board"]:
        assert term in facts_text
    findings_text = json.dumps(resolver_payload["findings"]).lower()
    for term in ["tamween", "8.6", "fx"]:
        assert term in findings_text


def test_public_assistant_context_exposes_kg_and_public_safe_findings(monkeypatch):
    monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

    payload = api_module._resolve_public_assistant_context("latest-public", persona="ceo")

    assert payload["run_id"] == "latest-public"
    assert payload["run_mode"] == "public-safe"
    assert payload["findings"], "public-safe assistant context must not be empty"
    assert payload["kg_nodes"], "public-safe assistant context must expose KG summary nodes"
    assert payload["kg_edges"], "public-safe assistant context must expose KG summary edges"


def test_public_safe_golden_prompts_return_substantive_answers(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        client = TestClient(api_module.app)

        prompts = {
            'Project the impact of "Tamween audit: SAR 1.2M recoverable" on the current plan and what I should prepare for the board.': ["sar 1.2m", "sar 8.6m", "board"],
            "Show evidence for SAR 8.6M recoverable": ["sar 8.6m", "tamween", "public"],
            "Why is the gap widening?": ["e-pharmacy", "healthcare", "tamween"],
            "Show e-Pharmacy detail": ["e-pharmacy", "12%", "sla"],
            "Risk to full-year plan?": ["margin", "fx", "tamween"],
            "Project FX hedge impact on EBITDA margin": ["ebitda", "fx", "hedge"],
            "Simulate digital health flat by end of year": ["digital health", "scenario", "assumptions"],
        }

        for question, expected_terms in prompts.items():
            response = client.post("/assistant/chat", json={"question": question, "persona": "ceo", "mode": "auto"})
            assert response.status_code == 200, question
            payload = response.json()
            answer_lower = payload["answer"].lower()
            assert "no completed governed run is available yet" not in answer_lower, question
            assert "no findings available for leakage analysis" not in answer_lower, question
            assert payload["run_id"] == "latest-public"
            assert payload["run_mode"] == "public-safe"
            assert payload["trace"]["entrypoint_context"]["active_persona"] == "ceo"
            assert payload["hallucination_risk"]["level"] in {"low", "medium", "high"}
            for term in expected_terms:
                assert term in answer_lower or term in json.dumps(payload).lower(), f"Missing '{term}' for prompt: {question}"
    finally:
        _restore_env(original)


def test_public_ceo_margin_pressure_prompt_returns_business_answer_without_debug_fallback(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "What is driving margin pressure this quarter?",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {"source": "executive_surface", "entrypoint": "drawer_input", "board_state": "pre", "driver_key": "ebitda"},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        answer = payload["answer"].lower()

        assert payload["status"] == "ok"
        assert payload["run_id"] == "latest-public"
        assert payload["run_mode"] == "public-safe"
        assert "fx" in answer
        assert "api" in answer
        assert "healthcare" in answer or "occupancy" in answer
        assert "tamween" in answer
        assert "board" in answer or "action" in answer

        for banned in (
            "deterministic public-safe handler",
            "shared public packet",
            "public packet",
            "visible packet",
            "public-safe",
            "deterministic",
            "handler",
            "llm",
            "graph",
            "vector",
            "path:",
            "run:",
            "risk: none",
            "i can answer board-safe questions",
        ):
            assert banned not in answer, f"unexpected debug fallback leak in answer: {banned}"
    finally:
        _restore_env(original)


def test_public_assistant_context_includes_shared_public_packet_facts(monkeypatch):
    monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

    context = api_module._resolve_public_assistant_context(
        None,
        persona="ceo",
        assistant_context={"source": "executive_surface", "entrypoint": "scenario_chip"},
        driver_context=None,
    )

    packet = context["public_context_packet"]
    assert context["run_id"] == "latest-public"
    assert context["run_mode"] == "public-safe"
    assert context["findings"], "public-safe assistant context must not expose empty findings"
    assert context["kg_nodes"], "public-safe assistant context must include KG summary nodes"
    assert context["kg_edges"], "public-safe assistant context must include KG summary edges"
    text = json.dumps(packet)
    for needle in ["Tamween audit", "SAR 8.6M", "e-Pharmacy", "FX", "board pack", "running_agents"]:
        assert needle in text, f"missing shared public packet fact: {needle}"


def test_assistant_chat_public_golden_prompts_use_shared_public_packet(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        client = TestClient(api_module.app)

        golden_prompts = [
            'Project the impact of "Tamween audit: SAR 1.2M recoverable" on the current plan and what I should prepare for the board.',
            "Show evidence for SAR 8.6M recoverable",
            "Why is the gap widening?",
            "Show e-Pharmacy detail",
            "Risk to full-year plan?",
            "Project FX hedge impact on EBITDA margin",
            "Simulate digital health flat by end of year",
        ]
        for prompt in golden_prompts:
            response = client.post(
                "/assistant/chat",
                json={
                    "question": prompt,
                    "persona": "ceo",
                    "mode": "auto",
                    "source": "executive_surface",
                    "entrypoint": "scenario_chip",
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["run_id"] == "latest-public"
            assert payload["run_mode"] == "public-safe"
            assert payload["trace"]["entrypoint_context"]["source"] == "executive_surface"
            assert payload["trace"]["entrypoint_context"]["entrypoint"] == "scenario_chip"
            assert "No completed governed run is available yet" not in payload["answer"]
            assert "No findings available for leakage analysis" not in payload["answer"]
            assert payload["citations"], f"golden prompt must return citations: {prompt}"

        tamween_payload = client.post(
            "/assistant/chat",
            json={
                "question": golden_prompts[0],
                "persona": "ceo",
                "mode": "auto",
                "source": "executive_surface",
                "entrypoint": "development_cta",
            },
        ).json()
        assert "SAR 1.2M" in tamween_payload["answer"]
        assert "SAR 8.6M" in tamween_payload["answer"]
        assert "board" in tamween_payload["answer"].lower()
        assert "margin" in tamween_payload["answer"].lower()
        assert tamween_payload["hallucination_risk"]["level"] != "none"
    finally:
        _restore_env(original)


def test_resolve_public_assistant_context_populates_shared_public_packet(monkeypatch):
    monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

    context = api_module._resolve_public_assistant_context(
        "latest-public",
        persona="ceo",
        assistant_context={"source": "executive_surface", "entrypoint": "drawer_input"},
    )

    assert context["bundle"] is not None
    assert context["findings"], "public-safe assistant context must expose findings"
    assert context["kg_nodes"], "public-safe assistant context must expose KG nodes"
    packet = context["public_context_packet"]
    facts_text = " ".join(packet.get("facts") or [])
    assert "Tamween audit: SAR 1.2M recoverable" in facts_text
    assert "SAR 8.6M is recoverable across the group" in facts_text
    assert "e-Pharmacy" in facts_text
    assert "FX" in facts_text


def test_bootstrap_and_public_latest_run_share_same_assistant_packet(monkeypatch):
    monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

    view_state = {"persona": "ceo", "board": "pre", "driver": "revenue"}
    bootstrap = api_module._ui_bootstrap(view_state=view_state, entry_route="/executive")
    public_payload = api_module._latest_run_public_payload(
        api_module._latest_summary(),
        view_state=view_state,
    )

    bootstrap_packet = bootstrap["assistant_public_context"]
    latest_packet = public_payload["assistant_public_context"]
    assert bootstrap_packet["packet_id"] == latest_packet["packet_id"]
    assert bootstrap_packet["drivers"] == latest_packet["drivers"]
    assert bootstrap_packet["findings"] == latest_packet["findings"]
    assert bootstrap_packet["developments"] == latest_packet["developments"]
    assert bootstrap_packet["week"] == latest_packet["week"]
    assert bootstrap_packet["kg_nodes"] == latest_packet["kg_nodes"]
    assert bootstrap_packet["agent_activity"] == latest_packet["agent_activity"]


def test_executive_diagnostics_persona_blueprint_derives_from_shared_packet(monkeypatch):
    monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
    payload = api_module._latest_run_public_payload(
        api_module._latest_summary(),
        view_state={"persona": "ceo", "board": "pre", "driver": "revenue"},
    )
    shared_packet = payload["assistant_public_context"]
    blueprint = payload["executive_diagnostics"]["persona_blueprint"]
    assert blueprint["assistant"] == shared_packet["assistant"]
    assert blueprint["drivers"] == shared_packet["drivers"]
    assert blueprint["findings"] == shared_packet["findings"]
    assert blueprint["developments"] == shared_packet["developments"]
    assert blueprint["week"] == shared_packet["week"]


def test_assistant_chat_public_ceo_golden_prompts_use_shared_public_packet(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        client = TestClient(api_module.app)
        prompts = [
            'Project the impact of "Tamween audit: SAR 1.2M recoverable" on the current plan and what I should prepare for the board.',
            "Show evidence for SAR 8.6M recoverable",
            "Why is the gap widening?",
            "Show e-Pharmacy detail",
            "Risk to full-year plan?",
            "Project FX hedge impact on EBITDA margin",
            "Simulate digital health flat by end of year",
        ]

        for prompt in prompts:
            response = client.post(
                "/assistant/chat",
                json={
                    "question": prompt,
                    "persona": "ceo",
                    "mode": "auto",
                    "assistant_context": {"source": "executive_surface", "entrypoint": "golden_prompt_test"},
                },
            )

            assert response.status_code == 200, prompt
            payload = response.json()
            assert payload["status"] == "ok", prompt
            assert payload["matched"] is True, prompt
            assert payload["run_id"] == "latest-public", prompt
            assert payload["run_mode"] == "public-safe", prompt
            assert "No completed governed run is available yet" not in payload["answer"], prompt
            assert "No findings available for leakage analysis" not in payload["answer"], prompt
            assert payload["assistant_context"]["entrypoint"] == "golden_prompt_test", prompt
    finally:
        _restore_env(original)


def test_public_assistant_context_uses_shared_public_packet(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        client = TestClient(api_module.app)

        response = client.post(
            "/assistant/chat",
            json={
                "question": 'Project the impact of "Tamween audit: SAR 1.2M recoverable" on the current plan and what I should prepare for the board.',
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {"source": "executive_surface", "entrypoint": "development_cta", "board_state": "pre", "driver_key": "revenue"},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_id"] == "latest-public"
        assert payload["run_mode"] == "public-safe"
        assert payload["assistant_context"]["entrypoint"] == "development_cta"
        assert payload["trace"]["entrypoint_context"]["driver_key"] == "revenue"
        assert "SAR 1.2M" in payload["answer"]
        assert "SAR 8.6M" in payload["answer"]
        assert payload["hallucination_risk"]["level"] in {"low", "medium"}
        assert payload["citations"]
        assert any("public_packet://latest-public" == item["source_path"] for item in payload["citations"])
        assert any(str(item.get("locator") or "").startswith("public_context_packet.") for item in payload["citations"])

    finally:
        _restore_env(original)


def test_public_assistant_golden_prompts_use_shared_context(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        client = TestClient(api_module.app)
        prompts = [
            ("Show evidence for SAR 8.6M recoverable", "SAR 8.6M"),
            ("Why is the gap widening?", "gap is widening"),
            ("Show e-Pharmacy detail", "e-Pharmacy"),
            ("Risk to full-year plan?", "full-year risk"),
            ("Project FX hedge impact on EBITDA margin", "19.2%"),
        ]

        for question, token in prompts:
            response = client.post(
                "/assistant/chat",
                json={
                    "question": question,
                    "persona": "ceo",
                    "mode": "auto",
                    "assistant_context": {"source": "executive_surface", "entrypoint": "scenario_chip", "board_state": "pre", "driver_key": "revenue"},
                },
            )
            assert response.status_code == 200, question
            payload = response.json()
            assert "No completed governed run is available yet" not in payload["answer"], question
            assert token.lower() in payload["answer"].lower(), question
            assert payload["citations"], question
            assert any(str(item.get("locator") or "").startswith("public_context_packet.") for item in payload["citations"]), question

    finally:
        _restore_env(original)


def test_public_assistant_exact_fx_board_review_prompt_returns_substantive_answer(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        client = TestClient(api_module.app)
        response = client.post(
            "/assistant/chat",
            json={
                "question": "Explain why “FX is building a ~SAR 9k margin drag this week” matters for the board review and what action I should consider.",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {
                    "source": "executive_surface",
                    "entrypoint": "finding_cta",
                    "board_state": "pre",
                    "driver_key": "margin"
                },
            },
        )

        assert response.status_code == 200
        payload = response.json()
        answer = payload["answer"].lower()
        assert payload["status"] == "ok"
        assert "i couldn't reach the shared assistant service just now." not in answer
        assert "sar 9k" in answer
        assert "19.2%" in answer
        assert "hedge" in answer
        assert payload["trace"]["entrypoint_context"]["entrypoint"] == "finding_cta"
    finally:
        _restore_env(original)


def test_public_safe_persona_variants_return_substantive_answers(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        client = TestClient(api_module.app)
        cases = [
            ("cfo", "Where is the SAR 8.6M?", ["SAR 8.6M", "SAR 1.2M"]),
            ("gm", "Where is capacity binding first?", ["Eastern hub", "capacity"]),
            ("bucfo", "What is the SAR 1.2M recovery path?", ["SAR 1.2M", "collections"]),
        ]

        for persona, question, tokens in cases:
            response = client.post(
                "/assistant/chat",
                json={
                    "question": question,
                    "persona": persona,
                    "mode": "auto",
                    "assistant_context": {"source": "executive_surface", "entrypoint": "scenario_chip"},
                },
            )
            assert response.status_code == 200, question
            payload = response.json()
            assert payload["run_mode"] == "public-safe", question
            assert payload["matched"] is True, question
            assert "outside the current deterministic public-safe prompt set" not in payload["answer"], question
            assert "No findings available for leakage analysis" not in payload["answer"], question
            assert all(token.lower() in payload["answer"].lower() for token in tokens), question

        bucfo_payload = client.post(
            "/assistant/chat",
            json={
                "question": "What is the SAR 1.2M recovery path?",
                "persona": "bucfo",
                "mode": "auto",
                "assistant_context": {"source": "executive_surface", "entrypoint": "scenario_chip"},
            },
        ).json()
        assert "SAR 20.8M" not in bucfo_payload["answer"]
    finally:
        _restore_env(original)


def test_public_board_portal_prepare_board_pack_prompt_returns_useful_packet_answer(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "Help me prepare the board pack for the pre-board stage. What needs CEO review, what evidence is missing, and what should I do next?",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {"source": "executive_surface", "entrypoint": "board_portal", "board_state": "pre"},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        answer = payload["answer"].lower()
        assert payload["status"] == "ok"
        assert payload["matched"] is True
        assert payload["run_id"] == "latest-public"
        assert payload["run_mode"] == "public-safe"
        assert payload["answered_by"] == "packet"
        assert "prompt did not match" not in answer
        assert "board" in answer
        assert "evidence" in answer
        assert "packet" not in answer
        assert payload["citations"]
    finally:
        _restore_env(original)


def test_public_board_portal_close_challenged_cases_prompt_returns_useful_packet_answer(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "Help me close challenged cases before the board meeting. Which cases are challenged, what evidence is needed, and what is my next action?",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {"source": "executive_surface", "entrypoint": "board_portal", "board_state": "pre"},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        answer = payload["answer"].lower()
        assert payload["status"] == "ok"
        assert payload["matched"] is True
        assert payload["run_id"] == "latest-public"
        assert payload["run_mode"] == "public-safe"
        assert payload["answered_by"] == "packet"
        assert "prompt did not match" not in answer
        assert "challenged" in answer
        assert "evidence" in answer
        assert "packet" not in answer
        assert payload["citations"]
    finally:
        _restore_env(original)


def test_public_manual_out_of_domain_prompt_is_answered_not_replaced_with_packet_summary(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "What is the capital of France?",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {"source": "executive_surface", "entrypoint": "drawer_input", "board_state": "pre"},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        answer = payload["answer"].lower()
        assert payload["status"] == "ok"
        assert "paris" in answer
        assert "revenue remains ahead while the board still needs a clean margin story" not in answer
        assert payload["run_mode"] == "public-safe"
    finally:
        _restore_env(original)


def test_public_manual_task_prompt_returns_exact_limitation_not_packet_summary(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "Set a follow-up task for Iris on fulfilment capacity",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {"source": "executive_surface", "entrypoint": "drawer_input", "board_state": "pre"},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        answer = payload["answer"].lower()
        assert payload["status"] == "ok"
        assert "cannot create or assign tasks" in answer
        assert "iris" in answer
        assert "fulfilment capacity" in answer
        assert "revenue remains ahead while the board still needs a clean margin story" not in answer
        assert payload["run_mode"] == "public-safe"
    finally:
        _restore_env(original)


def test_public_manual_board_prep_prompt_returns_board_guidance_from_drawer_input(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "Help me prepare the board pack for the pre-board stage. What needs CEO review, what evidence is missing, and what should I do next?",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {"source": "executive_surface", "entrypoint": "drawer_input", "board_state": "pre"},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        answer = payload["answer"].lower()
        assert payload["status"] == "ok"
        assert payload["matched"] is True
        assert payload["assistant_context"]["entrypoint"] == "drawer_input"
        assert "board" in answer
        assert "evidence" in answer
        assert any(token in answer for token in ("next step", "next action", "ceo review"))
        assert payload["citations"]
    finally:
        _restore_env(original)


def test_public_thread_board_readiness_prompt_returns_specific_guidance_not_packet_summary(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "Am I on track for the board on Thursday?",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {"source": "executive_surface", "entrypoint": "drawer_input", "board_state": "pre"},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        answer = payload["answer"].lower()
        assert payload["status"] == "ok"
        assert payload["matched"] is True
        assert "thursday" in answer
        assert "challenged" in answer
        assert "next step" in answer
        assert "revenue remains ahead while the board still needs a clean margin story" not in answer
        assert payload["citations"]
    finally:
        _restore_env(original)


def test_public_quick_prompt_regression_still_returns_grounded_answer(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "Project FX hedge impact on EBITDA margin",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {"source": "executive_surface", "entrypoint": "quick_prompt", "board_state": "pre", "driver_key": "margin"},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        answer = payload["answer"].lower()
        assert payload["status"] == "ok"
        assert payload["matched"] is True
        assert payload["assistant_context"]["entrypoint"] == "quick_prompt"
        assert "fx" in answer
        assert "hedge" in answer
        assert payload["citations"]
    finally:
        _restore_env(original)


def test_public_quick_prompt_what_would_60_percent_hedge_save_returns_fx_specific_answer(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "What would a 60% EUR hedge save?",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {"source": "executive_surface", "entrypoint": "driver_chip", "board_state": "pre", "driver_key": "ebitda"},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        answer = payload["answer"].lower()
        assert payload["status"] == "ok"
        assert payload["matched"] is True
        assert "hedge" in answer
        assert "fx" in answer or "eur" in answer
        assert "15 bps" in answer or "sar 9k" in answer
        assert "revenue remains ahead while the board still needs a clean margin story" not in answer
        assert payload["citations"]
    finally:
        _restore_env(original)


def test_latest_run_audit_summary_reads_citation_and_audit_artifacts(monkeypatch, tmp_path):
    citation_audit = tmp_path / "citation_audit.json"
    citation_audit.write_text(
        (
            '{"summary": {"citation_count": 7, "resolved_count": 6}, '
            '"records": []}'
        ),
        encoding="utf-8",
    )
    audit_log = tmp_path / "audit_log.json"
    audit_log.write_text(
        (
            '['
            '{"action": "challenge", "status": "challenged", "finding_id": "F-002"},'
            '{"action": "response", "status": "responded", "finding_id": "F-002"},'
            '{"action": "challenge", "status": "challenged", "finding_id": "F-001"}'
            ']'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api_module,
        "_latest_summary",
        lambda: {
            "run_id": "run-1",
            "run_dir": str(tmp_path / "run"),
            "artifacts": {
                "citation_audit": str(citation_audit),
                "audit_log": str(audit_log),
            },
        },
    )
    original, client = _client_with_auth()
    try:
        response = client.get(
            "/runs/latest/audit-summary",
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        assert response.json()["citation_count"] == 7
        assert response.json()["resolved_count"] == 6
        assert response.json()["challenged_finding_ids"] == ["F-001", "F-002"]
    finally:
        _restore_env(original)


def test_latest_run_knowledge_graph_returns_findings_view_and_vendor_expansion(monkeypatch, tmp_path):
    output_root = tmp_path / "outputs"
    run_dir = output_root / "run-1"
    run_dir.mkdir(parents=True)
    graph_path = run_dir / "StrategyOS Knowledge Graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "meta": {"node_count": 8, "edge_count": 9},
                "nodes": [
                    {
                        "id": "Finding:F-001",
                        "label": "Finding",
                        "properties": {
                            "finding_id": "F-001",
                            "title": "Duplicate bank account",
                            "pattern_type": "entity_resolution",
                            "recoverable_sar": 1200,
                        },
                    },
                    {
                        "id": "Vendor:V-1",
                        "label": "Vendor",
                        "properties": {"vendor_id": "V-1", "vendor_name": "Alpha LLC"},
                    },
                    {
                        "id": "Vendor:V-2",
                        "label": "Vendor",
                        "properties": {"vendor_id": "V-2", "vendor_name": "Beta LLC"},
                    },
                    {
                        "id": "Evidence:docs/audit.pdf",
                        "label": "Evidence",
                        "properties": {"source_path": "docs/audit.pdf"},
                    },
                    {
                        "id": "Contract:docs/contract.pdf",
                        "label": "Contract",
                        "properties": {
                            "source_path": "docs/contract.pdf",
                            "contract_reference": "C-1",
                            "vendor_id": "V-1",
                        },
                    },
                    {
                        "id": "Invoice:INV-1",
                        "label": "Invoice",
                        "properties": {"invoice_id": "INV-1", "amount_sar": 100},
                    },
                    {
                        "id": "Invoice:INV-2",
                        "label": "Invoice",
                        "properties": {"invoice_id": "INV-2", "amount_sar": 200},
                    },
                    {
                        "id": "PurchaseOrder:PO-1",
                        "label": "PurchaseOrder",
                        "properties": {"po_id": "PO-1", "total": 150},
                    },
                ],
                "edges": [
                    {"source": "Finding:F-001", "target": "Vendor:V-1", "label": "INVOLVES_VENDOR"},
                    {"source": "Finding:F-001", "target": "Evidence:docs/audit.pdf", "label": "SUPPORTED_BY"},
                    {"source": "Vendor:V-1", "target": "Contract:docs/contract.pdf", "label": "HAS_CONTRACT"},
                    {"source": "Contract:docs/contract.pdf", "target": "Evidence:docs/audit.pdf", "label": "SUPPORTED_BY"},
                    {"source": "Vendor:V-1", "target": "Vendor:V-2", "label": "SAME_BANK_ACCOUNT_AS"},
                    {"source": "Vendor:V-1", "target": "Invoice:INV-1", "label": "ISSUED_INVOICE"},
                    {"source": "Vendor:V-1", "target": "Invoice:INV-2", "label": "ISSUED_INVOICE"},
                    {"source": "Vendor:V-1", "target": "PurchaseOrder:PO-1", "label": "ISSUED_PO"},
                    {"source": "Invoice:INV-1", "target": "PurchaseOrder:PO-1", "label": "MATCHES_PO"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api_module,
        "_latest_summary",
        lambda: {
            "run_id": "run-1",
            "run_dir": str(run_dir),
            "artifacts": {"knowledge_graph": str(graph_path)},
        },
    )
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-key",
            "STRATEGYOS_OUTPUT_ROOT": str(output_root),
        }
    )
    try:
        client = TestClient(api_module.app)
        response = client.get(
            "/runs/latest/knowledge-graph",
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["view"] == "findings"
        assert {node["label"] for node in payload["nodes"]} == {
            "Contract",
            "Evidence",
            "Finding",
            "Vendor",
        }
        vendor = next(node for node in payload["nodes"] if node["id"] == "Vendor:V-1")
        assert vendor["invoice_count"] == 2
        assert "ISSUED_INVOICE" not in {edge["label"] for edge in payload["edges"]}

        expanded = client.get(
            "/runs/latest/knowledge-graph?expand=Vendor%3AV-1&limit=1",
            headers={"X-API-Key": "reviewer-key"},
        )

        assert expanded.status_code == 200
        expanded_payload = expanded.json()
        assert "Invoice:INV-2" in {node["id"] for node in expanded_payload["nodes"]}
        assert "Invoice:INV-1" not in {node["id"] for node in expanded_payload["nodes"]}
        assert expanded_payload["expansion"]["truncated"] == 2
    finally:
        _restore_env(original)


def test_latest_run_knowledge_graph_requires_auth():
    original, client = _client_with_auth()
    try:
        response = client.get("/runs/latest/knowledge-graph")

        assert response.status_code == 401
    finally:
        _restore_env(original)


def test_qa_context_resolves_explicit_run_id_from_state_store(monkeypatch, tmp_path):
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    captured: dict[str, object] = {}
    api_module._QA_CONTEXT_CACHE.clear()

    def fake_run_detail(run_id: str):
        return {
            "run_id": run_id,
            "dataset_root": str(dataset_root),
            "run_dir": str(tmp_path / "run"),
            "summary_json": {"run_mode": "partial"},
        }

    def fake_load_dataset(path: Path, *, strict: bool):
        captured["path"] = path
        captured["strict"] = strict
        return object()

    monkeypatch.setattr(api_module.state_store, "get_run_detail", fake_run_detail)
    monkeypatch.setattr(api_module, "load_dataset", fake_load_dataset)
    monkeypatch.setattr(api_module, "run_all_finance_skills", lambda bundle: ["finding"])

    context = api_module._resolve_qa_context("run-77")

    assert context["run_id"] == "run-77"
    assert context["run_mode"] == "partial"
    assert captured == {"path": dataset_root, "strict": False}
    assert context["findings"] == ["finding"]
