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

        def fake_answer(question, *, bundle, findings, summary, config):
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

        def fake_answer(question, *, bundle, findings, summary, config):
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
        assert payload["answer"] == "Assistant LLM summary"
        assert payload["llm_status"]["model"] == "gpt-test"
    finally:
        _restore_env(original)


def test_assistant_chat_llm_mode_sanitizes_raw_json_answer(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
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
            json={"question": "summarize the board packet in plain English", "persona": "ceo", "mode": "llm"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answer"] == "Plain-English board packet summary."
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
        assert "shared public packet" in payload["answer"]
    finally:
        _restore_env(original)


def test_assistant_chat_public_auto_unmatched_uses_llm_fallback_when_enabled(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))
        captured = {}

        def fake_answer(question, *, bundle, findings, summary, config, public_context_packet=None, persona=None):
            captured["question"] = question
            captured["public_context_packet"] = public_context_packet
            captured["persona"] = persona
            assert config.llm_model == "gpt-test"
            return {
                "matched": True,
                "answer": "Last week from the public packet: EBITDA margin is 19.2% versus 19.4% plan, FX is still a ~SAR 9k weekly drag, and e-Pharmacy orders are +12% week on week. I do not have a closed last-week ledger in the public packet, so I am answering from the visible weekly run-rate.",
                "basis": "Grounded in the public executive packet week items, KPI cards, and findings.",
                "citations": [
                    {"source_path": "public_packet://latest-public", "locator": "public_context_packet.kpis[1]"},
                    {"source_path": "public_packet://latest-public", "locator": "public_context_packet.week[0]"},
                ],
                "suggestions": [],
                "llm_status": {"enabled": True, "provider": "deepseek", "model": config.llm_model},
            }

        monkeypatch.setattr(api_module.llm_qa, "answer_question", fake_answer)

        response = client.post(
            "/assistant/chat",
            json={"question": "give me numbers for last week", "persona": "ceo", "mode": "auto"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "llm"
        assert payload["requested_mode"] == "auto"
        assert payload["run_mode"] == "public-safe"
        assert payload["llm_fallback_attempted"] is True
        assert payload["answer"].startswith("Last week from the public packet:")
        assert payload["citations"][0]["source_path"] == "public_packet://latest-public"
        assert captured["question"] == "give me numbers for last week"
        assert captured["persona"] == "ceo"
        assert captured["public_context_packet"]["week"]
        assert captured["public_context_packet"]["kpis"]
    finally:
        _restore_env(original)


def test_assistant_chat_public_llm_mode_bypasses_canned_deterministic_fallback(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))
        monkeypatch.setattr(
            api_module.llm_qa,
            "answer_question",
            lambda *_args, **_kwargs: {
                "matched": True,
                "answer": "Plain-English board packet summary: revenue is ahead, margin is soft because of FX and API cost, and the two live decisions are the hedge and the JV.",
                "basis": "Grounded in the public packet summary and board portal.",
                "citations": [{"source_path": "public_packet://latest-public", "locator": "public_context_packet.board_portal.summary"}],
                "suggestions": [],
                "llm_status": {"enabled": True, "provider": "deepseek", "model": "gpt-test"},
            },
        )

        response = client.post(
            "/assistant/chat",
            json={"question": "summarize the board packet in plain English", "persona": "ceo", "mode": "llm"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "llm"
        assert payload["requested_mode"] == "llm"
        assert "outside the current deterministic public-safe prompt set" not in payload["answer"]
        assert payload["answer"].startswith("Plain-English board packet summary")
    finally:
        _restore_env(original)


def test_assistant_chat_public_llm_mode_returns_403_when_llm_disabled(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=False)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))

        response = client.post(
            "/assistant/chat",
            json={"question": "give me numbers for last week", "persona": "ceo", "mode": "llm"},
        )

        assert response.status_code == 403
        assert "LLM chat is disabled" in response.json()["detail"]
    finally:
        _restore_env(original)


def test_assistant_chat_public_auto_unmatched_returns_canned_fallback_when_llm_disabled(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=False)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))

        response = client.post(
            "/assistant/chat",
            json={"question": "give me numbers for last week", "persona": "ceo", "mode": "auto"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "deterministic"
        assert payload["matched"] is False
        assert payload["llm_fallback_attempted"] is False
        assert payload["llm_status"]["enabled"] is False
        assert "did not match a deterministic public-safe handler" in payload["answer"]
        assert "LLM fallback is unavailable: LLM chat is disabled." in payload["basis"]
    finally:
        _restore_env(original)


def test_assistant_chat_public_natural_ceo_prompts_use_public_llm(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))
        answers = {
            "give me numbers for last week": "Last week from the public packet: revenue is SAR 2.09B quarter to date, EBITDA margin is 19.2% versus 19.4% plan, FX is still a ~SAR 9k weekly drag, and e-Pharmacy orders are +12% week on week.",
            "what changed since last week?": "Since last week, the visible packet shows NUPCO awards confirmed at +SAR 145M annual, cold-chain hit 99.4%, and the board pack moved to 80% composed while FX still pressures margin.",
            "what should i worry about before the board meeting?": "Before the board meeting, I would worry most about the margin narrative: FX is dragging EBITDA, API cost is still leaking, and the board still needs a clear hedge decision and JV line.",
            "which business unit is dragging margin?": "Tamween Distribution is the clearest business-unit drag on margin in the public packet because of the SAR 1.2M leakage, while Healthcare Services is the main operating drag below plan.",
            "summarize the board packet in plain english": "In plain English: revenue is ahead, margin is the soft spot, SAR 8.6M is recoverable across the group, and the two decisions still hanging over the board are the FX hedge and the GLP-1 JV.",
        }

        def fake_answer(question, *, public_context_packet=None, **_kwargs):
            return {
                "matched": True,
                "answer": answers[question.lower()],
                "basis": "Grounded in the public packet facts, findings, developments, and board portal.",
                "citations": [{"source_path": "public_packet://latest-public", "locator": "public_context_packet.findings[0]"}],
                "suggestions": [],
                "llm_status": {"enabled": True, "provider": "deepseek", "model": "gpt-test"},
            }

        monkeypatch.setattr(api_module.llm_qa, "answer_question", fake_answer)

        prompts = {
            "give me numbers for last week": ["19.2%", "sar 9k", "+12% week on week"],
            "what changed since last week?": ["sar 145m", "99.4%", "80% composed"],
            "what should i worry about before the board meeting?": ["margin narrative", "hedge", "jv"],
            "which business unit is dragging margin?": ["tamween", "sar 1.2m", "healthcare"],
            "summarize the board packet in plain english": ["revenue is ahead", "sar 8.6m", "fx hedge"],
        }

        for question, expected_tokens in prompts.items():
            response = client.post(
                "/assistant/chat",
                json={"question": question, "persona": "ceo", "mode": "auto"},
            )
            assert response.status_code == 200, question
            payload = response.json()
            assert payload["mode"] == "llm", question
            assert payload["llm_fallback_attempted"] is True, question
            assert "outside the current deterministic public-safe prompt set" not in payload["answer"], question
            answer_lower = payload["answer"].lower()
            for token in expected_tokens:
                assert token in answer_lower, f"Missing '{token}' for prompt: {question}"
    finally:
        _restore_env(original)


def test_assistant_chat_public_auto_returns_canned_fallback_on_llm_runtime_error(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))

        def fake_answer(*_args, **_kwargs):
            raise RuntimeError(
                'LLM provider returned HTTP 402: {"error":{"message":"Insufficient Balance"}}'
            )

        monkeypatch.setattr(api_module.llm_qa, "answer_question", fake_answer)

        response = client.post(
            "/assistant/chat",
            json={"question": "give me numbers for last week", "persona": "ceo", "mode": "auto"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "deterministic"
        assert payload["matched"] is False
        assert payload["llm_fallback_attempted"] is True
        assert payload["llm_error"].startswith("LLM provider returned HTTP 402")
        assert "did not match a deterministic public-safe handler" in payload["answer"]
        assert "Insufficient Balance" in payload["answer"]
        assert any(str(item.get("locator") or "") == "facts[0]" for item in payload["citations"])
    finally:
        _restore_env(original)


def test_assistant_chat_public_llm_mode_surfaces_provider_error_on_runtime_failure(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(
            api_module,
            "parse_scenario",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("mode=llm should bypass deterministic scenario routing")),
        )

        def fake_answer(*_args, **_kwargs):
            raise RuntimeError(
                'LLM provider returned HTTP 402: {"error":{"message":"Insufficient Balance"}}'
            )

        monkeypatch.setattr(api_module.llm_qa, "answer_question", fake_answer)

        response = client.post(
            "/assistant/chat",
            json={"question": "summarize the board packet in plain English", "persona": "ceo", "mode": "llm"},
        )

        assert response.status_code == 502
        assert "Insufficient Balance" in response.json()["detail"]
    finally:
        _restore_env(original)




def test_assistant_chat_public_auto_unmatched_uses_llm_public_packet(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
            "STRATEGYOS_RUN_POLICY": "external-approved",
            "STRATEGYOS_APPROVED_EXTERNAL_MODES": "model_provider_use",
            "STRATEGYOS_MODEL_PROVIDER_ENABLED": "true",
            "STRATEGYOS_LLM_CHAT_ENABLED": "true",
            "STRATEGYOS_LLM_API_KEY": "test-key",
            "STRATEGYOS_LLM_MODEL": "deepseek-v4-pro",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(
            api_module,
            "parse_scenario",
            lambda *_args, **_kwargs: SimpleNamespace(matched=False, as_dict=lambda: {"matched": False, "citations": [], "suggestions": []}),
        )
        calls = {}

        def fake_answer(question, *, bundle, findings, summary, config, public_context_packet=None, persona=None):
            calls["question"] = question
            calls["packet"] = public_context_packet
            calls["persona"] = persona
            return {
                "matched": True,
                "answer": "Last week the public packet shows revenue still ahead, margin still soft from FX, and Tamween remains the main recovery lever.",
                "basis": "Grounded in the public executive packet KPIs, findings, and weekly board-prep context.",
                "citations": [
                    {"source_path": "public_packet://latest-public", "locator": "public_context_packet.kpis[0]"},
                    {"source_path": "public_packet://latest-public", "locator": "public_context_packet.findings[0]"},
                ],
                "suggestions": ["What changed since last week?"],
                "llm_status": {"enabled": True, "provider": "deepseek", "model": "deepseek-v4-pro"},
            }

        monkeypatch.setattr(api_module.llm_qa, "answer_question", fake_answer)
        client = TestClient(api_module.app)

        response = client.post(
            "/assistant/chat",
            json={"question": "give me numbers for last week", "persona": "ceo", "mode": "auto"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_mode"] == "public-safe"
        assert payload["mode"] == "llm"
        assert payload["requested_mode"] == "auto"
        assert payload["llm_fallback_attempted"] is True
        assert "outside the current deterministic public-safe prompt set" not in payload["answer"]
        assert calls["question"] == "give me numbers for last week"
        assert calls["persona"] == "ceo"
        assert calls["packet"]["kpis"]
        assert calls["packet"]["week"]
        assert any(str(item.get("locator") or "").startswith("public_context_packet.") for item in payload["citations"])
    finally:
        _restore_env(original)


def test_assistant_chat_public_llm_mode_bypasses_canned_fallback(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
            "STRATEGYOS_RUN_POLICY": "external-approved",
            "STRATEGYOS_APPROVED_EXTERNAL_MODES": "model_provider_use",
            "STRATEGYOS_MODEL_PROVIDER_ENABLED": "true",
            "STRATEGYOS_LLM_CHAT_ENABLED": "true",
            "STRATEGYOS_LLM_API_KEY": "test-key",
            "STRATEGYOS_LLM_MODEL": "deepseek-v4-pro",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(
            api_module,
            "parse_scenario",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("mode=llm should bypass deterministic scenario routing")),
        )
        called = {}

        def fake_answer(question, *, bundle, findings, summary, config, public_context_packet=None, persona=None):
            called["question"] = question
            called["packet_id"] = (public_context_packet or {}).get("packet_id")
            return {
                "matched": True,
                "answer": "The public packet does not expose a private week-end ledger cut, but it does show revenue ahead, margin 20 bps below plan, and FX as the live watch item.",
                "basis": "Grounded in the public executive packet only.",
                "citations": [{"source_path": "public_packet://latest-public", "locator": "public_context_packet.public_facts"}],
                "suggestions": [],
                "llm_status": {"enabled": True, "provider": "deepseek", "model": "deepseek-v4-pro"},
            }

        monkeypatch.setattr(api_module.llm_qa, "answer_question", fake_answer)
        client = TestClient(api_module.app)

        response = client.post(
            "/assistant/chat",
            json={"question": "give me numbers for last week", "persona": "ceo", "mode": "llm"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "llm"
        assert payload["requested_mode"] == "llm"
        assert payload["llm_fallback_attempted"] is True
        assert "outside the current deterministic public-safe prompt set" not in payload["answer"]
        assert called["question"] == "give me numbers for last week"
        assert called["packet_id"] == "public-executive:ceo"
    finally:
        _restore_env(original)


def test_assistant_chat_public_auto_unmatched_returns_canned_list_when_llm_disabled(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
            "STRATEGYOS_MODEL_PROVIDER_ENABLED": "false",
            "STRATEGYOS_LLM_CHAT_ENABLED": "false",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(
            api_module,
            "parse_scenario",
            lambda *_args, **_kwargs: SimpleNamespace(matched=False, as_dict=lambda: {"matched": False, "citations": [], "suggestions": []}),
        )
        monkeypatch.setattr(
            api_module.llm_qa,
            "answer_question",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called when disabled")),
        )
        client = TestClient(api_module.app)

        response = client.post(
            "/assistant/chat",
            json={"question": "give me numbers for last week", "persona": "ceo", "mode": "auto"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "deterministic"
        assert payload["matched"] is False
        assert payload["llm_fallback_attempted"] is False
        assert "this prompt did not match" in payload["answer"].lower()
        assert "LLM fallback is unavailable: LLM chat is disabled." in payload["basis"]
    finally:
        _restore_env(original)


def test_assistant_chat_public_natural_ceo_prompts_return_llm_answers(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_IDP_ENABLED": "true",
            "STRATEGYOS_IDP_ISSUER": "http://localhost:8089",
            "STRATEGYOS_IDP_TOKEN_URL": "http://strategyos-idp:9000/oauth/token",
            "STRATEGYOS_IDP_INTROSPECTION_URL": "http://strategyos-idp:9000/oauth/introspect",
            "STRATEGYOS_IDP_CLIENT_ID": "strategyos-local-client",
            "STRATEGYOS_IDP_CLIENT_SECRET": "local-secret",
            "STRATEGYOS_RUN_POLICY": "external-approved",
            "STRATEGYOS_APPROVED_EXTERNAL_MODES": "model_provider_use",
            "STRATEGYOS_MODEL_PROVIDER_ENABLED": "true",
            "STRATEGYOS_LLM_CHAT_ENABLED": "true",
            "STRATEGYOS_LLM_API_KEY": "test-key",
            "STRATEGYOS_LLM_MODEL": "deepseek-v4-pro",
        }
    )
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(
            api_module,
            "parse_scenario",
            lambda *_args, **_kwargs: SimpleNamespace(matched=False, as_dict=lambda: {"matched": False, "citations": [], "suggestions": []}),
        )

        expected = {
            "give me numbers for last week": "last week the public packet shows revenue ahead and margin still 20 bps below plan.",
            "what changed since last week?": "since last week the visible shift is e-Pharmacy strength holding while the FX drag is still on the board agenda.",
            "what should i worry about before the board meeting?": "before the board meeting i would worry about the margin narrative, the fx hedge decision, and tamween recovery follow-through.",
            "which business unit is dragging margin?": "healthcare services remains the main operating drag, while tamween and fx weigh on the margin story.",
            "summarize the board packet in plain english": "in plain english: revenue is ahead, cash is solid, margin is the weak spot, and two board decisions remain open.",
        }

        def fake_answer(question, *, bundle, findings, summary, config, public_context_packet=None, persona=None):
            answer = expected[question.lower()]
            return {
                "matched": True,
                "answer": answer,
                "basis": "Grounded in public KPI cards, findings, weekly items, and board portal context.",
                "citations": [{"source_path": "public_packet://latest-public", "locator": "public_context_packet.kpis[0]"}],
                "suggestions": [],
                "llm_status": {"enabled": True, "provider": "deepseek", "model": "deepseek-v4-pro"},
            }

        monkeypatch.setattr(api_module.llm_qa, "answer_question", fake_answer)
        client = TestClient(api_module.app)

        for question, expected_answer in expected.items():
            response = client.post(
                "/assistant/chat",
                json={"question": question, "persona": "ceo", "mode": "auto"},
            )
            assert response.status_code == 200, question
            payload = response.json()
            assert payload["mode"] == "llm", question
            assert payload["llm_fallback_attempted"] is True, question
            assert payload["answer"].lower() == expected_answer.lower(), question
            assert "outside the current deterministic public-safe prompt set" not in payload["answer"], question
            assert any(str(item.get("locator") or "").startswith("public_context_packet.") for item in payload["citations"]), question
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
