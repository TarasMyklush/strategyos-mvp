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


def test_ceo_kpi_answers_are_intent_specific_and_share_governed_truth(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "build_executive_presentation",
        lambda _read_model: {
            "driver_grid": [
                {
                    "key": "revenue",
                    "label": "Revenue",
                    "metric": "SAR 385.1M",
                    "availability": "available",
                    "missing_inputs": ["H1 budget aligned to this reporting scope"],
                    "grounding": {"status": "grounded"},
                    "source_files": ["02_ERP_Extracts/GL_Extract_H1_2026.csv"],
                    "trend": {"actual": [100.0, 120.0], "plan": [], "has_plan_series": False},
                    "movers": {
                        "lifting": [{"name": "Revenue – Catering", "delta": "20.0 SAR"}],
                        "dragging": [{"name": "Revenue – Government", "delta": "-5.0 SAR"}],
                    },
                    "executive_brief": {
                        "readout": "Revenue recognised across four revenue groups.",
                        "drivers": [
                            {"label": "Revenue – Catering", "value": "SAR 123.0M", "share_pct": 31.9},
                            {"label": "Revenue – Government", "value": "SAR 109.9M", "share_pct": 28.5},
                        ],
                        "calculation": {"formula": "Revenue = sum of scoped revenue-account balances."},
                        "audit": {"source_titles": ["General ledger extract", "Chart of accounts"]},
                    },
                }
            ]
        },
    )

    decision = api_module._ceo_kpi_inline_result(
        {"summary": {}},
        kpi_key="revenue",
        public_safe=False,
        question="What requires my decision or attention for revenue?",
    )
    drivers = api_module._ceo_kpi_inline_result(
        {"summary": {}},
        kpi_key="revenue",
        public_safe=False,
        question="What is driving revenue and where is concentration highest?",
    )
    comparison = api_module._ceo_kpi_inline_result(
        {"summary": {}},
        kpi_key="revenue",
        public_safe=False,
        question="How does revenue compare with the approved plan?",
    )
    numeric_key = api_module._free_text_ceo_kpi_key(
        "explainwhere 385,1 is coming from",
        {"summary": {}},
        public_safe=False,
    )
    numeric_answer = api_module._ceo_kpi_inline_result(
        {"summary": {}},
        kpi_key=numeric_key or "",
        public_safe=False,
        question="explainwhere 385,1 is coming from",
    )

    assert decision["kpi_question_intent"] == "decision"
    assert "Movement requiring attention: Revenue – Government (-SAR 5)" in decision["answer"]
    assert "immediate governance gap" in decision["answer"]
    assert "Current composition" not in decision["answer"]

    assert drivers["kpi_question_intent"] == "drivers"
    assert "Revenue – Catering — SAR 123.0M · 31.9%" in drivers["answer"]
    assert "largest reported contributor is Revenue – Catering at 31.9%" in drivers["answer"]
    assert "Positive movement: Revenue – Catering (+SAR 20)" in drivers["answer"]
    assert "No like-for-like plan variance" not in drivers["answer"]

    assert comparison["kpi_question_intent"] == "comparison"
    assert "No like-for-like plan variance is stated" in comparison["answer"]
    assert "No period-aligned revenue plan series is connected" in comparison["answer"]
    assert "H1 budget aligned to this reporting scope" in comparison["answer"]
    assert "Current composition" not in comparison["answer"]

    assert len({decision["answer"], drivers["answer"], comparison["answer"]}) == 3
    assert numeric_key == "revenue"
    assert numeric_answer["answered_by"] == "governed_kpi"
    assert numeric_answer["kpi_question_intent"] == "drivers"
    assert "Revenue is SAR 385.1M" in numeric_answer["answer"]
    assert "Revenue – Catering — SAR 123.0M · 31.9%" in numeric_answer["answer"]
    assert drivers["citations"][0]["source_path"] == "02_ERP_Extracts/GL_Extract_H1_2026.csv"
    assert all(result["grounding_status"] == "grounded" for result in (decision, drivers, comparison))


def test_assistant_chat_resolves_locale_formatted_headline_value_before_llm(monkeypatch):
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda _run_id: {
                "bundle": object(),
                "findings": [],
                "kg_nodes": [],
                "kg_edges": [],
                "summary": {"run_id": "finance-run"},
                "run_id": "finance-run",
                "run_mode": "full",
            },
        )
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))
        monkeypatch.setattr(
            api_module,
            "build_executive_presentation",
            lambda _read_model: {
                "driver_grid": [
                    {
                        "key": "revenue",
                        "label": "Revenue",
                        "metric": "SAR 385.1M",
                        "availability": "available",
                        "grounding": {"status": "grounded"},
                        "source_files": ["02_ERP_Extracts/GL_Extract_H1_2026.csv"],
                        "movers": {},
                        "trend": {},
                        "executive_brief": {
                            "readout": "Revenue recognised across four revenue groups.",
                            "drivers": [{"label": "Revenue – Catering", "value": "SAR 123.0M", "share_pct": 31.9}],
                        },
                    }
                ]
            },
        )

        async def forbidden_llm(*_args, **_kwargs):
            raise AssertionError("A displayed KPI value must resolve before LLM fallback")

        monkeypatch.setattr(api_module, "_llm_answer_question_async", forbidden_llm)
        response = client.post(
            "/assistant/chat",
            headers={"X-API-Key": "operator-key"},
            json={
                "question": "explainwhere 385,1 is coming from",
                "persona": "ceo",
                "mode": "auto",
                # A previously opened card must not trap a new, explicit KPI
                # reference inside stale drawer context.
                "assistant_context": {
                    "entrypoint": "ceo_kpi_inline",
                    "kpi_key": "cash_vs_floor",
                },
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] == "governed_kpi"
        assert payload["answer_origin"] == "governed"
        assert payload["human_review_required"] is False
        assert payload["llm_fallback_attempted"] is False
        assert "Revenue is SAR 385.1M" in payload["answer"]
        assert "Revenue – Catering" in payload["answer"]
        assert "provide more details" not in payload["answer"].lower()
    finally:
        _restore_env(original)


def test_ceo_kpi_intent_contract_handles_free_text_and_declared_ui_intent():
    assert api_module._ceo_kpi_question_intent("What needs my attention?") == "decision"
    assert api_module._ceo_kpi_question_intent("Where does this result come from?") == "drivers"
    assert api_module._ceo_kpi_question_intent("What is the variance to budget?") == "comparison"
    assert api_module._ceo_kpi_question_intent("Explain this figure", "drivers") == "drivers"
    # Explicit wording wins over inconsistent client metadata.
    assert api_module._ceo_kpi_question_intent("How does this compare to plan?", "decision") == "comparison"


def test_free_text_ceo_kpi_routing_covers_rendered_finance_cards():
    assert api_module._free_text_ceo_kpi_key("Which revenue stream is largest?") == "revenue"
    assert api_module._free_text_ceo_kpi_key("What data gap blocks cash-versus-floor?") == "cash_vs_floor"
    assert api_module._free_text_ceo_kpi_key("Explain operating cost") == "operating_cost"
    assert api_module._free_text_ceo_kpi_key("Explain the EBITDA bridge") == "ebitda_margin"
    assert api_module._free_text_ceo_kpi_key("Model a 60% EBITDA margin") is None


def test_release_gate_answer_uses_publication_contract():
    result = api_module._governed_release_gate_result(
        {
            "run_id": "run-1",
            "status": "awaiting_review",
            "current_stage": "awaiting_review",
            "approval_status": "pending",
            "requires_human_review": True,
            "findings": 8,
            "locked_findings": 8,
        },
        role="executive",
        public_safe=False,
    )

    assert result["answered_by"] == "governed_release_gate"
    assert "approve or reject" in result["answer"]
    assert "8 locked finding(s)" in result["answer"]
    assert "operator must resume" in result["answer"]
    assert result["grounding_status"] == "grounded"


def test_authenticated_free_text_kpi_and_release_route_before_fallback(monkeypatch):
    original, client = _client_with_auth()
    try:
        context = {
            "bundle": object(),
            "findings": [],
            "kg_nodes": [],
            "kg_edges": [],
            "summary": {
                "run_id": "run-1",
                "status": "awaiting_review",
                "current_stage": "awaiting_review",
                "approval_status": "pending",
                "requires_human_review": True,
                "findings": 8,
                "locked_findings": 8,
            },
            "run_id": "run-1",
            "run_mode": "full",
        }
        monkeypatch.setattr(api_module, "_resolve_qa_context", lambda _run_id: context)
        monkeypatch.setattr(
            api_module,
            "_ceo_kpi_inline_result",
            lambda _context, *, kpi_key, public_safe, question="": {
                "matched": True,
                "answer": f"Governed {kpi_key} answer",
                "basis": "Current CEO finance contract",
                "citations": [{"source_path": "finance://current", "locator": kpi_key, "excerpt": ""}],
                "suggestions": [],
                "answered_by": "governed_kpi",
                "grounding_status": "grounded",
                "_orchestrator_force_answer": True,
            },
        )

        revenue = client.post(
            "/assistant/chat",
            headers={"X-API-Key": "operator-key"},
            json={"question": "Which revenue stream is largest?", "persona": "ceo", "mode": "auto"},
        )
        assert revenue.status_code == 200
        assert revenue.json()["answered_by"] == "governed_kpi"
        assert revenue.json()["answer"] == "Governed revenue answer"
        assert revenue.json()["llm_fallback_attempted"] is False

        release = client.post(
            "/assistant/chat",
            headers={"X-API-Key": "operator-key"},
            json={"question": "What human decision is required before the current board pack can be released?", "persona": "ceo", "mode": "auto"},
        )
        assert release.status_code == 200
        assert release.json()["answered_by"] == "governed_release_gate"
        assert "approve or reject" in release.json()["answer"]
        assert release.json()["llm_fallback_attempted"] is False
    finally:
        _restore_env(original)


def test_authenticated_followup_reference_uses_history_for_kpi_component(monkeypatch):
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda _run_id: {
                "bundle": object(),
                "findings": [],
                "kg_nodes": [],
                "kg_edges": [],
                "summary": {},
                "run_id": "run-1",
                "run_mode": "full",
            },
        )
        monkeypatch.setattr(
            api_module,
            "build_executive_presentation",
            lambda _read_model: {
                "driver_grid": [
                    {
                        "key": "revenue",
                        "label": "Revenue",
                        "metric": "SAR 385.1M",
                        "source_files": ["02_ERP_Extracts/GL_Extract_H1_2026.csv"],
                        "executive_brief": {
                            "readout": "Revenue recognised across four revenue groups.",
                            "drivers": [
                                {"label": "Revenue – Catering", "value": "SAR 123.0M", "share_pct": 31.9},
                                {"label": "Revenue – Government", "value": "SAR 109.9M", "share_pct": 28.5},
                            ],
                            "calculation": {"formula": "Revenue = sum of scoped revenue-account balances."},
                        },
                    }
                ]
            },
        )

        response = client.post(
            "/assistant/chat",
            headers={"X-API-Key": "operator-key"},
            json={
                "question": "Elaborate on SAR 109.9M",
                "persona": "ceo",
                "mode": "auto",
                "history": [
                    {
                        "role": "assistant",
                        "text": "Revenue – Government — SAR 109.9M · 28.5%",
                        "payload": {"assistant_context": {"kpi_key": "revenue"}},
                    }
                ],
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] == "governed_reference"
        assert "Revenue – Government" in payload["answer"]
        assert "28.5%" in payload["answer"]
        assert "GL_Extract_H1_2026.csv" in payload["citations"][0]["source_path"]
        assert payload["assistant_context"]["history_attached"] is True
    finally:
        _restore_env(original)


def test_visible_answer_scrubber_repairs_governed_packet_phrase():
    cleaned = api_module.llm_qa._clean_visible_answer("This depends on the current governed packet.")
    assert "governed current view" not in cleaned
    assert cleaned == "This depends on the current governed view."


def test_authenticated_llm_supplemental_payload_includes_history():
    payload = api_module._supplemental_grounding_payload(
        assistant_history=[
            {"role": "user", "text": "What is driving revenue?"},
            {"role": "assistant", "text": "Revenue – Government — SAR 109.9M", "payload": {"reference": {"kpi_key": "revenue"}}},
        ]
    )
    assert payload["conversation_history"][1]["payload_reference"]["kpi_key"] == "revenue"


def test_external_decision_question_fails_closed_with_actual_governed_scope():
    bundle = type("Bundle", (), {"run_metadata": {"available_roles": ["ap_ledger", "ar_ledger", "gl_extract"]}})()
    result = api_module._unavailable_external_decision_result(
        "Should I acquire a competitor next quarter?",
        {"bundle": bundle, "summary": {"finance_kpi": {"authoritative": True}}},
    )

    assert result is not None
    assert result["matched"] is False
    assert "AP ledger, AR ledger, GL-derived finance KPIs" in result["answer"]
    assert "market, competitive, valuation, legal, or transaction-diligence evidence" in result["answer"]
    assert result["answered_by"] == "evidence_scope_boundary"
    assert api_module._unavailable_external_decision_result(
        "What is driving revenue now?",
        {"bundle": bundle, "summary": {"finance_kpi": {"authoritative": True}}},
    ) is None


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


def test_governed_module_contract_covers_every_visible_module():
    module_payload = api_module._agent_modules_payload(
        None,
        [],
        None,
        {"role": "executive", "authenticated": True},
    )
    contract = api_module._governed_module_state_contract(
        None,
        role="executive",
        public_safe=False,
    )

    assert contract == module_payload["state_contract"]
    modules = {item["module_id"]: item for item in contract["modules"]}
    assert contract["contract_version"] == "governed_module_state.v1"
    assert set(modules) == {
        "cash-recovery-watch",
        "evidence-closure-monitor",
        "board-pack-compiler",
        "runtime-guardrail",
    }
    for module in modules.values():
        assert module["label"]
        assert module["status"]
        assert module["current_activity"]
        assert module["output"]
        assert module["dependency"]
        assert module["provenance"]["source"] == "governed_run_publication_and_review_state"


def test_governed_module_resolver_uses_server_contract_not_client_state():
    result = api_module._resolve_governed_module_status(
        'Tell me about the "Board-pack compiler" module: what is it doing right now, is it blocked, and what does it need from me?',
        summary=None,
        assistant_context={
            "module_id": "board-pack-compiler",
            # This untrusted value must not be used in the response.
            "module_status": "running with no blockers",
        },
        role="executive",
        public_safe=False,
    )

    assert result is not None
    assert result["matched"] is True
    assert result["answered_by"] == "governed_module"
    assert result["module"]["module_id"] == "board-pack-compiler"
    assert "Board-pack compiler is a governed executive module" in result["answer"]
    assert "does not contain any information" not in result["answer"]
    assert "running with no blockers" not in result["answer"]


def test_governed_module_resolver_answers_every_registered_module():
    contract = api_module._governed_module_state_contract(
        None,
        role="executive",
        public_safe=False,
    )

    for module in contract["modules"]:
        result = api_module._resolve_governed_module_status(
            f'What is the status of the "{module["label"]}" module?',
            summary=None,
            assistant_context={"module_id": module["module_id"], "entity_type": "governed_module"},
            role="executive",
            public_safe=False,
        )

        assert result is not None, module["module_id"]
        assert result["module"]["module_id"] == module["module_id"]
        assert "Current state:" in result["answer"]
        assert "What it needs from you:" in result["answer"]


def test_assistant_chat_resolves_structured_module_context_before_llm(monkeypatch):
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda _run_id: {
                "bundle": object(),
                "findings": [],
                "summary": None,
                "run_id": "run-1",
                "run_mode": "full",
                "kg_nodes": [],
                "kg_edges": [],
            },
        )
        monkeypatch.setattr(
            api_module.qa_engine,
            "answer_question",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("module route must precede tabular Q&A")),
        )

        response = client.post(
            "/assistant/chat",
            json={
                "question": 'Tell me about the "Board-pack compiler" module: what is it doing right now, is it blocked, and what does it need from me?',
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {
                    "source": "executive_surface",
                    "entrypoint": "assistant_network",
                    "module_id": "board-pack-compiler",
                    "entity_type": "governed_module",
                },
            },
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] == "governed_module"
        assert payload["assistant_mode"] == "governed_module"
        assert payload["module"]["module_id"] == "board-pack-compiler"
        assert payload["assistant_context"]["module_id"] == "board-pack-compiler"
        assert "Current state:" in payload["answer"]
        assert "What it needs from you:" in payload["answer"]
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


def test_authenticated_assistant_auto_mode_falls_back_when_provider_returns_empty_content(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_RUN_POLICY": "external-approved",
            "STRATEGYOS_APPROVED_EXTERNAL_MODES": "model_provider_use",
            "STRATEGYOS_MODEL_PROVIDER_ENABLED": "true",
            "STRATEGYOS_LLM_CHAT_ENABLED": "true",
            "STRATEGYOS_LLM_API_KEY": "test-key",
            "STRATEGYOS_LLM_MODEL": "deepseek-v4-pro",
        }
    )
    client = TestClient(api_module.app)
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda _run_id: {
                "bundle": object(),
                "findings": [],
                "summary": {"run_id": "run-1"},
                "run_id": "run-1",
                "run_mode": "full",
                "kg_nodes": [],
                "kg_edges": [],
            },
        )
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))
        monkeypatch.setattr(api_module, "route_graph_question", lambda *_args, **_kwargs: {"matched": False})
        monkeypatch.setattr(api_module, "_route_keyword_retrieval", lambda *_args, **_kwargs: {"matched": False})
        monkeypatch.setattr(
            api_module.qa_engine,
            "answer_question",
            lambda *_args, **_kwargs: {
                "matched": False,
                "answer": "The governed data cannot supply a board cash floor; no floor was inferred.",
                "basis": "Deterministic governed fallback.",
                "citations": [],
                "suggestions": [],
                "answered_by": "tabular",
            },
        )

        async def failed_provider(*_args, **_kwargs):
            raise RuntimeError("LLM provider returned an empty answer after retrying with a plain-text prompt.")

        monkeypatch.setattr(api_module, "_llm_answer_question_async", failed_provider)

        response = client.post(
            "/assistant/chat",
            json={"question": "What cash is reported and what floor is missing?", "persona": "ceo", "mode": "auto"},
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["mode"] == "deterministic"
        assert payload["llm_fallback_attempted"] is True
        assert payload["trace"]["llm_transport_failed"] is True
        assert "no floor was inferred" in payload["answer"].lower()
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


def test_authenticated_general_question_is_answered_by_the_governed_model(monkeypatch):
    """With a run loaded, the one assistant answers -- including general questions.

    This test previously asserted the opposite: that "What is the capital of
    France?" must reach answer_general_question and that answer_question must
    NOT be called. That contract is what shipped the reported failure --
    answer_general_question is blind by construction (no bundle, findings or
    summary), so any question routed there is answered by a model that cannot
    see the company, and questions like "summarize the board packet" leaked to
    it and came back "that is private company data I do not hold".

    There is one assistant now. It always holds the evidence, uses it for
    company claims, and answers plain general questions from its own knowledge.
    """
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
            lambda run_id: {
                "bundle": object(),
                "findings": [],
                "kg_nodes": [],
                "kg_edges": [],
                "summary": {"run_id": "run-1"},
                "run_id": "run-1",
                "run_mode": "full",
            },
        )
        monkeypatch.setattr(
            api_module.llm_qa,
            "answer_general_question",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("the blind general model must not be reachable while a run is loaded")
            ),
        )
        monkeypatch.setattr(
            api_module.llm_qa,
            "answer_question",
            lambda *_args, **_kwargs: {
                "matched": True,
                "answer": "Paris is the capital of France.",
                "basis": "General knowledge; no company evidence was required.",
                "citations": [],
                "suggestions": [],
                "llm_status": {"enabled": True, "model": "gpt-test"},
            },
        )

        response = client.post(
            "/assistant/chat",
            json={"question": "What is the capital of France?", "persona": "ceo", "mode": "auto"},
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert "Paris" in payload["answer"], (
            "a plain general question must still be answered, by the assistant "
            "that holds the evidence rather than one that cannot see it"
        )
    finally:
        _restore_env(original)


def test_authenticated_assistant_explains_file_processing_workflow(monkeypatch):
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: None)
        monkeypatch.setattr(
            api_module.llm_qa,
            "answer_general_question",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("app workflow help must not depend on general LLM fallback")
            ),
        )
        monkeypatch.setattr(
            api_module.llm_qa,
            "answer_question",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("app workflow help must not depend on board-pack LLM fallback")
            ),
        )

        response = client.post(
            "/assistant/chat",
            json={
                "question": "I want to process new files through the app, how do I do this?",
                "persona": "ceo",
                "mode": "auto",
            },
            headers={"X-API-Key": "operator-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["matched"] is True
        assert payload["answered_by"] == "app_help"
        assert payload["assistant_mode"] == "app_help"
        assert payload["llm_fallback_attempted"] is False
        assert "/app?lane=operate" in payload["answer"]
        assert "/source-packs" in payload["answer"]
        assert "Start analysis" in payload["answer"]
        assert "reviewer approves" in payload["answer"]
        assert "latest governed run" in payload["answer"]
        assert payload["hallucination_risk"]["level"] == "none"
    finally:
        _restore_env(original)


def test_authenticated_executive_app_help_calls_out_operator_role(monkeypatch):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_DEMO_ROLE_LOGIN_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-key",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-key",
        }
    )
    try:
        client = TestClient(api_module.app)
        monkeypatch.setattr(api_module, "_latest_summary", lambda: None)

        response = client.post(
            "/assistant/chat",
            json={
                "question": "How can I upload and process new files in the app?",
                "persona": "ceo",
                "mode": "auto",
            },
            headers={"X-API-Key": "executive"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["matched"] is True
        assert payload["answered_by"] == "app_help"
        assert "current role is executive" in payload["answer"]
        assert "require operator, tenant_operator, tenant_admin, or system access" in payload["answer"]
        assert "/app?lane=operate" in payload["answer"]
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
        assert payload["scenario_type"] == "missing_data"
        assert payload["prompt_contracts"]["role"]["prompt_id"] == "role:ceo:v1"
        assert payload["hallucination_risk"]["level"] == "none"
        assert "Illustrative external benchmarks are disabled" in payload["answer"]
        assert payload["calculations"][0]["step_id"] == "scenario_validation"
        assert "digital_health_baseline" in payload["calculations"][0]["inputs"]["missing_inputs"]
        assert "Enable illustrative mode for external benchmark exploration" in payload["suggestions"]
        assert payload["citations"] == []
        assert payload["assumptions"] == []
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


def test_assistant_chat_public_ceo_scenario_stays_governed_under_identity_provider(monkeypatch):
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
        assert payload["scenario_id"] == "public_exec_governed_packet"
        assert payload["matched"] is True
        assert payload["prompt_contracts"]["role"]["prompt_id"] == "role:ceo:v1"
        assert payload["hallucination_risk"]["level"] == "low"
        assert "current governed" in payload["answer"].lower()
        assert "illustrative" not in payload["answer"].lower()
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
        answer = payload["answer"].lower()
        assert "current reviewed data" in answer
        assert "no values were inferred or substituted" in answer
        assert all(marker.lower() not in answer for marker in ("19.2%", "SAR 8.6M", "60% EUR"))
    finally:
        _restore_env(original)


def test_assistant_chat_public_auto_unmatched_uses_reviewed_llm_with_public_packet(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(
            api_module,
            "parse_scenario",
            lambda *_args, **_kwargs: _parsed_scenario(
                matched=True,
                payload={
                    "matched": True,
                    "scenario_id": "public_exec_governed_packet",
                    "scenario_type": "deterministic",
                    "answer": "Generic packet summary that must not preempt Hermes.",
                    "basis": "Generic public packet catch-all.",
                    "citations": [],
                    "suggestions": [],
                },
            ),
        )
        called = {"llm": 0}

        def fake_answer(*_args, **_kwargs):
            called["llm"] += 1
            assert _kwargs.get("public_context_packet", {}).get("public_safe") is True
            return {
                "matched": False,
                "answer": "The latest public packet does not contain a complete weekly series; the nearest current CEO indicators are available for review.",
                "basis": "Public executive packet only.",
                "citations": [],
                "suggestions": [],
                "llm_status": {"enabled": True, "model": "gpt-test"},
            }

        monkeypatch.setattr(api_module.llm_qa, "answer_question", fake_answer)
        monkeypatch.setattr(api_module.llm_qa, "answer_general_question", fake_answer)

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
        assert payload["answered_by"] == "llm"
        assert payload["answer_origin"] == "llm"
        assert payload["calculation_status"] == "not_calculated"
        assert payload["review_status"] == "required"
        assert payload["human_review_required"] is True
        assert payload["public_packet_only"] is True
        assert payload["llm_matched"] is False
        assert "does not contain a complete weekly series" in payload["answer"]
        assert called["llm"] == 1
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
        assert "current governed drivers" in text
        assert "latest governed run" in text
        assert all(marker not in text for marker in ("fx", "api", "healthcare occupancy", "tamween"))
        assert "public-safe" not in text
        assert "deterministic" not in text
    finally:
        _restore_env(original)


def test_assistant_chat_public_llm_mode_uses_public_packet_and_requires_review(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))
        monkeypatch.setattr(
            api_module.llm_qa,
            "answer_question",
            lambda *_args, **_kwargs: {
                "matched": True,
                "answer": "The board packet is awaiting reviewer decision; the finance evidence is ready.",
                "basis": "Public executive packet only.",
                "citations": [],
                "suggestions": [],
                "llm_status": {"enabled": True, "model": "gpt-test"},
            },
        )
        monkeypatch.setattr(
            api_module.llm_qa,
            "answer_general_question",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("public-safe route must not call llm_qa.answer_general_question")),
        )

        response = client.post(
            "/assistant/chat",
            json={"question": "summarize the board packet in plain English", "persona": "ceo", "mode": "llm"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] == "llm"
        assert payload["public_packet_only"] is True
        assert payload["answer_origin"] == "llm"
        assert payload["review_status"] == "required"
    finally:
        _restore_env(original)


def test_public_safe_llm_never_claims_graph_or_vector_and_is_review_labeled(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(api_module, "parse_scenario", lambda *_args, **_kwargs: _parsed_scenario(matched=False))
        monkeypatch.setattr(
            api_module.llm_qa,
            "answer_question",
            lambda *_args, **_kwargs: {
                "matched": True,
                "answer": "The public packet does not expose a case with that identifier.",
                "basis": "Public executive packet only.",
                "citations": [],
                "suggestions": [],
                "llm_status": {"enabled": True, "model": "gpt-test"},
            },
        )

        response = client.post(
            "/assistant/chat",
            json={"question": "show evidence for F-004", "persona": "ceo", "mode": "auto"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] == "llm"
        assert payload["answered_by"] not in {"graph", "vector"}
        assert payload["public_packet_only"] is True
        assert payload["human_review_required"] is True
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
        assert payload["scenario_id"] == "public_exec_governed_packet"
        assert payload["answered_by"] == "packet"
        assert "current" in payload["answer"].lower()
        assert "illustrative" not in payload["answer"].lower()
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
        assert payload["scenario_id"] == "public_exec_governed_packet"
        assert payload["answered_by"] == "packet"
        assert "current" in payload["answer"].lower()
        assert "illustrative" not in payload["answer"].lower()
    finally:
        _restore_env(original)


def test_authenticated_challenge_closure_uses_current_audit_state_without_qa_reload(monkeypatch):
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(
            api_module,
            "_latest_summary",
            lambda: {"run_id": "run-1", "run_mode": "full"},
        )
        monkeypatch.setattr(
            api_module,
            "_finding_rows_from_summary",
            lambda summary: [
                {
                    "finding_id": "F-001",
                    "title": "Duplicate payment",
                    "citation_count": 2,
                    "recoverable_sar": 100,
                }
            ],
        )
        monkeypatch.setattr(
            api_module,
            "_load_summary_artifact_json",
            lambda summary, key: [
                {"action": "challenge", "finding_id": "F-001", "detail": "Attach invoice proof."},
                {"action": "response", "finding_id": "F-001"},
                {"action": "lock", "finding_id": "F-001"},
            ] if key == "audit_log" else None,
        )
        monkeypatch.setattr(
            api_module,
            "_latest_run_audit_summary_payload",
            lambda summary: {
                "status": "ok",
                "challenged_finding_ids": [],
                "historical_challenged_finding_ids": ["F-001"],
                "closed_challenge_count": 1,
                "citation_count": 2,
                "resolved_count": 2,
            },
        )
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda run_id: (_ for _ in ()).throw(AssertionError("challenge closure must not reload raw QA context")),
        )

        response = client.post(
            "/assistant/chat",
            headers={"X-API-Key": "operator-key"},
            json={
                "question": "What is the current status of challenged cases and evidence closure?",
                "persona": "ceo",
                "mode": "auto",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] == "governed_audit"
        assert payload["llm_fallback_attempted"] is False
        assert payload["grounding_status"] == "grounded"
        assert payload["reconciliation"]["open_challenge_count"] == 0
        assert payload["reconciliation"]["historical_challenge_count"] == 1
        assert "no open challenged cases" in payload["answer"].lower()
        assert payload["citation_resolution"] == {
            "resolved": 2,
            "total": 2,
            "display": "2 of 2 citations resolved",
        }
        assert payload["case_links"] == []
    finally:
        _restore_env(original)


def test_authenticated_challenge_closure_returns_links_for_every_open_case(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "_finding_rows_from_summary",
        lambda summary: [
            {"finding_id": "F-001", "title": "Case one", "citation_count": 1},
            {"finding_id": "F-002", "title": "Case two", "citation_count": 2},
        ],
    )
    monkeypatch.setattr(
        api_module,
        "_load_summary_artifact_json",
        lambda summary, key: [
            {"action": "challenge", "finding_id": "F-001", "detail": "Proof one"},
            {"action": "challenge", "finding_id": "F-002", "detail": "Proof two"},
        ] if key == "audit_log" else None,
    )
    monkeypatch.setattr(
        api_module,
        "_latest_run_audit_summary_payload",
        lambda summary: {
            "status": "ok",
            "challenged_finding_ids": ["F-001", "F-002"],
            "historical_challenged_finding_ids": ["F-001", "F-002"],
        },
    )

    result = api_module._authenticated_challenge_closure_result({"run_id": "run-1"})

    assert result["grounding_status"] == "grounded"
    assert [item["finding_id"] for item in result["case_links"]] == ["F-001", "F-002"]
    assert result["reconciliation"]["open_finding_row_count"] == 2


def test_board_status_thread_does_not_repeat_the_same_lifecycle_value(monkeypatch):
    monkeypatch.setattr(api_module, "_finding_rows_from_summary", lambda summary: [])

    chat = api_module._chat_threads_payload(
        {"run_id": "run-1", "status": "awaiting_review", "current_stage": "awaiting_review"},
        {"role": "operator", "authenticated": True},
        executive_modes={
            "active_persona_id": "ceo",
            "active_board_state": "pre",
            "active_driver_key": "board_packet",
            "personas": [{"persona_id": "ceo", "label": "Group CEO"}],
        },
        board_portal={"presentation_state": "pre"},
        publication={"challenged_cases": 0, "approval_status": "pending", "board_pack": {}},
    )

    assert chat["threads"][0]["preview"] == "Board context is awaiting review."


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
            assert payload["answered_by"] in {"packet", "governed_kpi"}, question
            assert "which aspect would you like to examine" not in payload["answer"].lower(), question
            assert "which part do you want to explore" not in payload["answer"].lower(), question
    finally:
        _restore_env(original)


def test_public_assistant_context_is_shared_between_bootstrap_and_chat_context(monkeypatch):
    monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

    bootstrap = api_module._ui_bootstrap()
    resolver_payload = api_module._resolve_public_assistant_context("latest-public", persona="ceo")
    packet = resolver_payload["public_context_packet"]

    assert bootstrap["assistant_public_context"]["packet_id"] == packet["packet_id"]
    assert resolver_payload["summary"]["assistant_context_source"] == packet["packet_id"]
    assert packet["source"] == "server_public_executive_packet"
    facts_text = " ".join(packet["facts"]).lower()
    for term in ["plan health", "recoverable value", "citation resolution"]:
        assert term in facts_text
    assert packet["data_sources"]["run_summary"]["run_id"] == "latest-public"


def test_public_assistant_context_exposes_kg_and_public_safe_findings(monkeypatch):
    monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

    payload = api_module._resolve_public_assistant_context("latest-public", persona="ceo")

    assert payload["run_id"] == "latest-public"
    assert payload["run_mode"] == "public-safe"
    assert payload["findings"] == []
    assert payload["kg_nodes"], "public-safe assistant context must expose KG summary nodes"
    assert payload["kg_edges"], "public-safe assistant context must expose KG summary edges"
    assert payload["public_context_packet"]["source"] == "server_public_executive_packet"


def test_ceo_knowledge_graph_uses_the_same_four_kpi_contracts_as_dashboard():
    cards = []
    for key, label, metric in (
        ("revenue", "Revenue", "SAR 385.1M"),
        ("ebitda_margin", "EBITDA margin", "31.2%"),
        ("operating_cost", "Operating cost", "SAR 80.0M"),
        ("cash_vs_floor", "Cash vs floor", "SAR 42.3M"),
    ):
        cards.append(
            {
                "driver_key": key,
                "label": label,
                "metric": metric,
                "availability": "partial" if key == "cash_vs_floor" else "verified",
                "formula": f"Governed formula for {label}",
                "missing_inputs": ["Approved board cash floor"] if key == "cash_vs_floor" else [],
                "source_files": [f"source/{key}.xlsx"],
                "executive_brief": {
                    "readout": f"Governed readout for {label}",
                    "decision_question": f"Explain {label}",
                    "drivers": [{"label": f"{label} contributor", "value": metric, "share_pct": 100}],
                    "comparison": {
                        "label": "Board cash floor" if key == "cash_vs_floor" else "Approved plan",
                        "value": "Not supplied" if key == "cash_vs_floor" else "Available",
                        "available": key != "cash_vs_floor",
                    },
                    "coverage": {"value": "Partial" if key == "cash_vs_floor" else "Complete"},
                    "calculation": {"steps": [{"label": f"{label} actual", "value": metric}]},
                    "audit": {
                        "source_titles": ["Governed source extract"],
                        "source_files": [f"source/{key}.xlsx"],
                        "missing_inputs": ["Approved board cash floor"] if key == "cash_vs_floor" else [],
                    },
                },
            }
        )

    nodes, edges, questions = api_module._ceo_kpi_knowledge_graph(cards)
    node_ids = {node["id"] for node in nodes}
    edge_tuples = {(edge["source"], edge["target"], edge["label"]) for edge in edges}

    assert {f"kpi:{card['driver_key']}" for card in cards}.issubset(node_ids)
    assert [question["label"] for question in questions] == [card["label"] for card in cards]
    assert ("kpi:revenue", "kpi:ebitda_margin", "INPUT_TO") in edge_tuples
    assert ("kpi:operating_cost", "kpi:ebitda_margin", "INPUT_TO") in edge_tuples
    assert any(node["category"] == "business_driver" for node in nodes)
    assert any(node["category"] == "comparator" for node in nodes)
    assert any(node["category"] == "evidence_gap" for node in nodes)
    assert any(node["category"] == "source" for node in nodes)
    assert all("vendor" not in str(node.get("category") or "").lower() for node in nodes)


def test_public_safe_legacy_demo_prompts_use_only_governed_answers(monkeypatch):
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
        fixture_markers = ("sar 1.2m", "sar 8.6m", "19.2%", "60% eur", "e-pharmacy", "tamween")

        for question in prompts:
            response = client.post("/assistant/chat", json={"question": question, "persona": "ceo", "mode": "auto"})
            assert response.status_code == 200, question
            payload = response.json()
            answer_lower = payload["answer"].lower()
            assert "no completed governed run is available yet" not in answer_lower, question
            assert "no findings available for leakage analysis" not in answer_lower, question
            assert payload["run_id"] == "latest-public"
            assert payload["run_mode"] == "public-safe"
            assert payload["trace"]["entrypoint_context"]["active_persona"] == "ceo"
            assert payload["hallucination_risk"]["level"] in {"none", "low", "medium", "high"}
            assert answer_lower.strip(), question
            governed_output = json.dumps(
                {
                    "answer": payload.get("answer"),
                    "basis": payload.get("basis"),
                    "suggestions": payload.get("suggestions"),
                }
            ).lower()
            assert all(marker not in governed_output for marker in fixture_markers), question
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
        assert "current governed" in answer
        assert "latest governed run" in answer
        assert all(marker not in answer for marker in ("fx", "api", "healthcare", "occupancy", "tamween"))

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
    assert context["findings"] == []
    assert context["kg_nodes"], "public-safe assistant context must include KG summary nodes"
    assert context["kg_edges"], "public-safe assistant context must include KG summary edges"
    text = json.dumps(packet).lower()
    for needle in ["latest-public", "server_public_executive_packet", "running_agents", "plan health", "citation resolution"]:
        assert needle in text, f"missing shared public packet fact: {needle}"


def test_assistant_chat_public_legacy_prompts_stay_inside_governed_packet(monkeypatch):
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
        fixture_markers = ("sar 1.2m", "sar 8.6m", "19.2%", "60% eur", "tamween", "e-pharmacy")
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
            surfaced = json.dumps(
                {"answer": payload.get("answer"), "basis": payload.get("basis"), "suggestions": payload.get("suggestions")}
            ).lower()
            assert all(marker not in surfaced for marker in fixture_markers), prompt

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
        assert "current governed" in tamween_payload["answer"].lower()
        assert all(marker not in tamween_payload["answer"].lower() for marker in fixture_markers)
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
    assert context["findings"] == []
    assert context["kg_nodes"], "public-safe assistant context must expose KG nodes"
    packet = context["public_context_packet"]
    facts_text = " ".join(packet.get("facts") or [])
    assert "Plan health" in facts_text
    assert "Recoverable value" in facts_text
    assert "Citation resolution" in facts_text


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


def test_assistant_chat_public_ceo_legacy_prompts_use_governed_packet(monkeypatch):
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
        fixture_markers = ("sar 1.2m", "sar 8.6m", "19.2%", "60% eur", "tamween", "e-pharmacy")

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
            assert payload["run_id"] == "latest-public", prompt
            assert payload["run_mode"] == "public-safe", prompt
            assert payload.get("scenario_id") in {None, "public_exec_governed_packet"}, prompt
            assert "No completed governed run is available yet" not in payload["answer"], prompt
            assert "No findings available for leakage analysis" not in payload["answer"], prompt
            assert payload["assistant_context"]["entrypoint"] == "golden_prompt_test", prompt
            surfaced = json.dumps(
                {"answer": payload.get("answer"), "basis": payload.get("basis"), "suggestions": payload.get("suggestions")}
            ).lower()
            assert all(marker not in surfaced for marker in fixture_markers), prompt
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
        assert "current governed" in payload["answer"].lower()
        assert "SAR 1.2M" not in payload["answer"]
        assert "SAR 8.6M" not in payload["answer"]
        assert payload["hallucination_risk"]["level"] in {"low", "medium"}
        assert payload["scenario_id"] == "public_exec_governed_packet"

    finally:
        _restore_env(original)


def test_public_assistant_legacy_prompts_use_governed_context(monkeypatch):
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
            "Show evidence for SAR 8.6M recoverable",
            "Why is the gap widening?",
            "Show e-Pharmacy detail",
            "Risk to full-year plan?",
            "Project FX hedge impact on EBITDA margin",
        ]
        fixture_markers = ("sar 8.6m", "19.2%", "60% eur", "tamween", "e-pharmacy")

        for question in prompts:
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
            surfaced = json.dumps(
                {"answer": payload.get("answer"), "basis": payload.get("basis"), "suggestions": payload.get("suggestions")}
            ).lower()
            assert all(marker not in surfaced for marker in fixture_markers), question

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
        assert "current governed run" in answer
        assert "no illustrative hedge assumptions" in answer
        assert all(marker not in answer for marker in ("sar 9k", "19.2%", "60% eur"))
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
            ("cfo", "What is the current recovery opportunity?"),
            ("gm", "Where is capacity binding first?"),
            ("bucfo", "What is the current recovery path?"),
        ]

        for persona, question in cases:
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
            assert isinstance(payload["matched"], bool), question
            assert payload.get("scenario_id") in {None, "public_exec_governed_packet"}, question
            assert "outside the current deterministic public-safe prompt set" not in payload["answer"], question
            assert "No findings available for leakage analysis" not in payload["answer"], question
            assert "current" in payload["answer"].lower(), question
            assert "sar 8.6m" not in payload["answer"].lower(), question
            assert "sar 1.2m" not in payload["answer"].lower(), question
            assert all(marker not in payload["answer"].lower() for marker in ("sar 8.6m", "sar 1.2m", "eastern hub")), question

        bucfo_payload = client.post(
            "/assistant/chat",
            json={
                "question": "What is the SAR 1.2M recovery path?",
                "persona": "bucfo",
                "mode": "auto",
                "assistant_context": {"source": "executive_surface", "entrypoint": "scenario_chip"},
            },
        ).json()
        assert all(marker not in bucfo_payload["answer"].lower() for marker in ("sar 20.8m", "sar 1.2m"))
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


def test_public_board_portal_hedge_downside_prompt_returns_hedge_answer_not_generic_fallback(monkeypatch):
    """P0 regression: board portal 'Show the hedge downside' must return
    hedge-specific answer, not the canned board catch-all fallback."""
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "Show the hedge downside",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {"source": "executive_surface", "entrypoint": "board_portal", "board_state": "live", "driver_key": "board_packet"},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        answer = payload["answer"].lower()
        assert payload["status"] == "ok"
        assert payload["run_id"] == "latest-public"
        assert payload["run_mode"] == "public-safe"
        # Must NOT return the canned board catch-all
        assert "chief of staff" not in answer
        assert "outside the available" not in answer
        # Must state the governed data boundary instead of inserting demo values.
        assert "hedge" in answer
        assert "current governed run" in answer
        assert "no illustrative hedge assumptions" in answer
        assert all(marker not in answer for marker in ("60%", "15 bps", "sar 9k"))
        assert not payload["citations"]
    finally:
        _restore_env(original)


def test_public_board_portal_jv_funded_from_cash_prompt_returns_jv_answer_not_generic_fallback(monkeypatch):
    """P0 regression: board portal 'Is the JV funded from cash?' must return
    JV/liquidity-specific answer, not the canned board catch-all fallback."""
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "Is the JV funded from cash?",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {"source": "executive_surface", "entrypoint": "board_portal", "board_state": "live", "driver_key": "board_packet"},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        answer = payload["answer"].lower()
        assert payload["status"] == "ok"
        assert payload["run_id"] == "latest-public"
        assert payload["run_mode"] == "public-safe"
        # Must NOT return the canned board catch-all
        assert "chief of staff" not in answer
        assert "outside the available" not in answer
        # Must state the governed data boundary instead of inserting demo values.
        assert any(token in answer for token in ("jv", "joint venture", "fund", "cash", "liquidity"))
        assert "current governed run" in answer
        assert "no illustrative funding assumptions" in answer
        assert not payload["citations"]
    finally:
        _restore_env(original)


def test_public_manual_out_of_domain_prompt_is_answered_not_replaced_with_packet_summary(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})
        monkeypatch.setattr(
            api_module.llm_qa,
            "answer_general_question",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("public-safe questions use the public-packet LLM adapter")),
        )
        monkeypatch.setattr(
            api_module.llm_qa,
            "answer_question",
            lambda *_args, **_kwargs: {
                "matched": True,
                "answer": "Paris is the capital of France. This is a general-knowledge answer.",
                "basis": "Model-provided general knowledge; no board-packet calculation.",
                "citations": [],
                "suggestions": [],
                "llm_status": {"enabled": True, "model": "gpt-test"},
            },
        )

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
        assert "general-knowledge answer" in answer
        assert "revenue remains ahead while the board still needs a clean margin story" not in answer
        assert payload["run_mode"] == "public-safe"
        assert payload["llm_fallback_attempted"] is True
        assert payload["answered_by"] == "llm"
        assert payload["review_status"] == "required"
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
        assert "operator workflow" in answer
        assert "iris" not in answer
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


def test_public_manual_how_should_i_prepare_for_the_board_meeting_prompt_is_not_canned(monkeypatch):
    original, client = _client_with_public_ceo_surface(llm_enabled=True)
    try:
        monkeypatch.setattr(api_module, "_latest_summary", lambda: {"run_id": "run-1", "dataset": "/tmp/private-dataset"})

        response = client.post(
            "/assistant/chat",
            json={
                "question": "How should I prepare for the board meeting?",
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
        assert "board" in answer
        assert "evidence" in answer
        assert any(token in answer for token in ("next step", "next action", "ceo review"))
        assert "revenue remains ahead while the board still needs a clean margin story" not in answer
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
        assert "current board posture" in answer
        assert "challenged" in answer
        assert "thursday" not in answer
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
        assert "current governed run" in answer
        assert "no illustrative hedge assumptions" in answer
        assert all(marker not in answer for marker in ("19.2%", "15 bps", "sar 9k", "60% eur"))
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
        assert "current governed run" in answer
        assert "no illustrative hedge assumptions" in answer
        assert all(marker not in answer for marker in ("60%", "15 bps", "sar 9k"))
        assert "revenue remains ahead while the board still needs a clean margin story" not in answer
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
        assert response.json()["challenged_finding_ids"] == ["F-001"]
        assert response.json()["historical_challenged_finding_ids"] == ["F-001", "F-002"]
        assert response.json()["closed_challenge_count"] == 1
    finally:
        _restore_env(original)


def test_challenged_case_state_closes_after_response_or_lock():
    events = [
        {"action": "challenge", "finding_id": "F-001"},
        {"action": "response", "finding_id": "F-001"},
        {"action": "lock", "finding_id": "F-001"},
        {"action": "challenge", "finding_id": "F-002"},
    ]

    assert api_module._challenged_finding_ids_from_audit_log(events) == ["F-002"]
    assert api_module._historically_challenged_finding_ids_from_audit_log(events) == [
        "F-001",
        "F-002",
    ]


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


def test_inline_ceo_kpi_chat_uses_server_resolved_contract_and_never_llm(monkeypatch):
    original, client = _client_with_auth()
    api_module._QA_CONTEXT_CACHE.clear()
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda _run_id: {
                "bundle": object(),
                "findings": [],
                "kg_nodes": [],
                "kg_edges": [],
                "summary": {
                    "run_id": "oracle-run",
                    "oracle_kpi": {
                        "derived_from": "deterministic_oracle_kpi_engine",
                        "authoritative": True,
                        "reporting_period_key": "2026-06",
                        "components": {
                            "revenue_actual": "1200000",
                            "revenue_plan": "1000000",
                            "ebitda_actual": "240000",
                            "ebitda_plan": "180000",
                            "operating_cost_actual": "630000",
                            "operating_cost_plan": "600000",
                            "cash_balance": "500000",
                            "board_floor": "400000",
                        },
                    },
                },
                "run_id": "oracle-run",
                "run_mode": "full",
            },
        )

        response = client.post(
            "/assistant/chat",
            headers={"X-API-Key": "operator-key"},
            json={
                "question": "Explain this KPI",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {
                    "source": "executive_surface",
                    "entrypoint": "ceo_kpi_inline",
                    "kpi_key": "revenue",
                    # A client value must not become the assistant's value.
                    "metric": "SAR 999.0B",
                },
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] == "governed_kpi"
        assert payload["llm_fallback_attempted"] is False
        assert "SAR 1.2M" in payload["answer"]
        assert "SAR 999.0B" not in payload["answer"]
        assert payload["assistant_context"]["kpi_key"] == "revenue"
        assert payload["grounding_status"] == "grounded"

        kg_response = client.post(
            "/assistant/chat",
            headers={"X-API-Key": "operator-key"},
            json={
                "question": "What drives this figure?",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {
                    "source": "executive_surface",
                    "entrypoint": "knowledge_graph",
                    "kpi_key": "revenue",
                },
            },
        )
        assert kg_response.status_code == 200
        kg_payload = kg_response.json()
        assert kg_payload["answered_by"] == "governed_kpi"
        assert kg_payload["llm_fallback_attempted"] is False
    finally:
        _restore_env(original)


def test_assistant_chat_models_target_margin_from_governed_finance_kpis_despite_stale_cash_context(monkeypatch):
    original, client = _client_with_auth()
    api_module._QA_CONTEXT_CACHE.clear()
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda _run_id: {
                "bundle": object(),
                "findings": [],
                "kg_nodes": [],
                "kg_edges": [],
                "public_context_packet": {},
                "summary": {
                    "run_id": "source-finance-run",
                    "finance_kpi": {
                        "authoritative": True,
                        "reporting_period_key": "H1 2026",
                        "reporting_currency": "SAR",
                        "components": {
                            "revenue_actual": "385079908.90",
                            "cogs_actual": "75503688.29",
                            "operating_cost_actual": "93834910.05",
                            "ebitda_actual": "215741310.56",
                        },
                        "evidence": {
                            "ebitda_margin": {
                                "files": [
                                    "02_ERP_Extracts/GL_Extract_H1_2026.csv",
                                    "03_Master_Data/Chart_of_Accounts.xlsx",
                                ]
                            }
                        },
                    },
                },
                "run_id": "source-finance-run",
                "run_mode": "full",
            },
        )

        response = client.post(
            "/assistant/chat",
            headers={"X-API-Key": "operator-key"},
            json={
                "question": "model what needs to happen so we have 60% margin",
                "persona": "ceo",
                "mode": "auto",
                "driver_context": {
                    "key": "cash_vs_floor",
                    "label": "Cash vs floor",
                    "metric": "3.5%",
                },
                "assistant_context": {
                    "source": "executive_surface",
                    "entrypoint": "ceo_kpi_inline",
                    "kpi_key": "cash_vs_floor",
                    "kpi_label": "Cash vs floor",
                },
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["scenario_id"] == "ebitda_target_margin"
        assert payload["scenario_type"] == "deterministic"
        assert payload["answered_by"] == "scenario"
        assert payload.get("llm_fallback_attempted", False) is False
        assert payload["hallucination_risk"]["level"] == "none"
        assert payload["grounding_status"] == "grounded"
        assert "56.0%" in payload["answer"]
        assert "60.0%" in payload["answer"]
        assert "SAR 15.3M" in payload["answer"]
        assert "SAR 460.1M" in payload["answer"]
        assert "cannot calculate" not in payload["answer"].lower()
    finally:
        _restore_env(original)


def test_public_ceo_chat_models_target_margin_from_governed_dashboard_baseline(monkeypatch):
    original, client = _client_with_public_ceo_surface()
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_public_assistant_context",
            lambda _run_id, **_kwargs: {
                "bundle": {"public_safe": True},
                "findings": [],
                "kg_nodes": [],
                "kg_edges": [],
                "public_context_packet": {
                    "is_illustrative": False,
                    "public_safe": True,
                    "drivers": [],
                    "findings": [],
                },
                "summary": {
                    "run_id": "latest-public",
                    "finance_kpi": {
                        "authoritative": True,
                        "reporting_period_key": "H1 2026",
                        "reporting_currency": "SAR",
                        "components": {
                            "revenue_actual": "385079908.90",
                            "cogs_actual": "75503688.29",
                            "operating_cost_actual": "93834910.05",
                            "ebitda_actual": "215741310.56",
                        },
                        "evidence": {
                            "ebitda_margin": {
                                "files": [
                                    "02_ERP_Extracts/GL_Extract_H1_2026.csv",
                                    "03_Master_Data/Chart_of_Accounts.xlsx",
                                ]
                            }
                        },
                    },
                },
                "run_id": "latest-public",
                "run_mode": "public-safe",
            },
        )

        response = client.post(
            "/assistant/chat",
            json={
                "question": "Model what needs to happen to reach a 60% EBITDA margin using the current governed revenue and cost baseline.",
                "persona": "ceo",
                "mode": "auto",
                "assistant_context": {
                    "source": "executive_surface",
                    "entrypoint": "ceo_kpi_inline",
                    "kpi_key": "ebitda_margin",
                    "kpi_label": "EBITDA margin",
                },
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_mode"] == "public-safe"
        assert payload["scenario_id"] == "ebitda_target_margin"
        assert payload["scenario_type"] == "deterministic"
        assert payload["hallucination_risk"]["level"] == "none"
        assert "56.0%" in payload["answer"]
        assert "60.0%" in payload["answer"]
        assert "SAR 15.3M" in payload["answer"]
        assert "Current governed drivers" not in payload["answer"]
    finally:
        _restore_env(original)


def test_scenario_question_with_component_amount_reaches_scenario_engine(monkeypatch):
    """A what-if quoting an on-screen amount must not be hijacked by the
    governed reference resolver into a component-lookup answer."""
    original, client = _client_with_auth()
    try:
        monkeypatch.setattr(
            api_module,
            "_resolve_qa_context",
            lambda _run_id: {
                "bundle": object(),
                "findings": [],
                "kg_nodes": [],
                "kg_edges": [],
                "summary": {},
                "run_id": "run-1",
                "run_mode": "full",
            },
        )
        monkeypatch.setattr(
            api_module,
            "build_executive_presentation",
            lambda _read_model: {
                "driver_grid": [
                    {
                        "key": "revenue",
                        "label": "Revenue",
                        "metric": "SAR 385.1M",
                        "source_files": ["gl.csv"],
                        "executive_brief": {
                            "readout": "readout",
                            "drivers": [
                                {"label": "Revenue – Modern Trade", "value": "SAR 103.2M", "share_pct": 26.8},
                            ],
                            "calculation": {"formula": "formula"},
                        },
                    }
                ]
            },
        )

        response = client.post(
            "/assistant/chat",
            headers={"X-API-Key": "operator-key"},
            json={
                "question": "If we recover SAR 103.2M, what remains?",
                "persona": "ceo",
                "mode": "auto",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload.get("answered_by") != "governed_reference", (
            "scenario-intent questions must fall through to the scenario engine "
            "even when they quote an amount visible on a KPI card"
        )
    finally:
        _restore_env(original)


def test_amount_reference_parser_requires_money_shape():
    """Bare counts, years, and percents are not monetary references."""
    parse = api_module._parse_amount_references

    assert parse("Elaborate on SAR 109.9M") == [109_900_000.0]
    assert parse("what about SAR 794,108") == [794_108.0]
    assert parse("drill into 42.3m cash") == [42_300_000.0]
    assert parse("top 3 cases in H1 2026") == []
    assert parse("why is the share 28.5%?") == []


def _governed_finding(**overrides):
    """A real Finding dataclass -- the type the chat context actually holds.

    _resolve_qa_context returns run_all_finance_skills() output, i.e. Finding
    dataclasses, not dicts. Fixtures built from dicts hid a production bug
    where the entity index skipped every finding.
    """
    from strategyos_mvp.models import Finding

    defaults = dict(
        finding_id="F-006",
        title="FX hedge not applied for INV-2026-0577",
        pattern_type="fx_hedge_missing",
        vendor_id="V-900",
        vendor_name="Bordeaux Wines & Spirits SARL",
        leakage_sar=46488.0,
        recoverable_sar=46488.0,
        recoverable_usd=12396.0,
        confidence=0.9,
        classification="confirmed",
        rationale="Invoice settled above an available hedge rate.",
        remediation="Apply the treasury hedge rate and recover the difference.",
        citations=[],
        calculation={},
        status="open",
        challenges=[],
    )
    defaults.update(overrides)
    return Finding(**defaults)


def _findings_context(monkeypatch):
    """Governed run carrying the finding rows the CEO surface shows."""
    monkeypatch.setattr(
        api_module,
        "_resolve_qa_context",
        lambda _run_id: {
            "bundle": object(),
            "findings": [
                _governed_finding(),
                _governed_finding(
                    finding_id="F-001",
                    title="Auto-renewal escalation at Gulf Logistics Services Co",
                    recoverable_sar=250416.0,
                    leakage_sar=250416.0,
                    vendor_name="Gulf Logistics Services Co",
                ),
            ],
            "kg_nodes": [],
            "kg_edges": [],
            "summary": {},
            "run_id": "run-1",
            "run_mode": "full",
        },
    )
    monkeypatch.setattr(api_module, "build_executive_presentation", lambda _rm: {"driver_grid": []})


def test_finding_id_reference_is_grounded_not_hallucinated(monkeypatch):
    """"F-006" must resolve to its governed row.

    It previously reached answer_general_question -- a model call with no
    governed evidence -- which invented finance detail ("Q3 2025 revenue and
    margin analysis") for the id.
    """
    original, client = _client_with_auth()
    try:
        _findings_context(monkeypatch)
        response = client.post(
            "/assistant/chat",
            headers={"X-API-Key": "operator-key"},
            json={"question": "F-006", "persona": "ceo", "mode": "auto"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] == "governed_reference"
        assert "FX hedge not applied" in payload["answer"]
        assert "46" in payload["answer"]
        assert payload["citations"][0]["finding_id"] == "F-006"
        assert "governed view" not in payload["answer"]
    finally:
        _restore_env(original)


def test_pronoun_followup_resolves_against_previous_assistant_turn(monkeypatch):
    """"can you show me it?" must bind to the id named one turn earlier."""
    original, client = _client_with_auth()
    try:
        _findings_context(monkeypatch)
        response = client.post(
            "/assistant/chat",
            headers={"X-API-Key": "operator-key"},
            json={
                "question": "can you show me it?",
                "persona": "ceo",
                "mode": "auto",
                "history": [
                    {"role": "user", "text": "What remains before this board packet can be released?"},
                    {"role": "assistant", "text": "F-006 is still outstanding before release."},
                ],
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] == "governed_reference"
        assert "FX hedge not applied" in payload["answer"]
        assert "not sure what" not in payload["answer"].lower()
    finally:
        _restore_env(original)


def test_document_identifier_in_finding_title_resolves(monkeypatch):
    """An invoice number quoted from a finding title must resolve."""
    original, client = _client_with_auth()
    try:
        _findings_context(monkeypatch)
        response = client.post(
            "/assistant/chat",
            headers={"X-API-Key": "operator-key"},
            json={"question": "What is INV-2026-0577?", "persona": "ceo", "mode": "auto"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] == "governed_reference"
        assert "F-006" in payload["answer"]
    finally:
        _restore_env(original)


def test_finding_amount_reference_resolves_against_findings(monkeypatch):
    """A SAR amount visible in the findings list must resolve there.

    The first resolver searched KPI cards only, so a findings amount fell
    through to the deflection fallback.
    """
    original, client = _client_with_auth()
    try:
        _findings_context(monkeypatch)
        response = client.post(
            "/assistant/chat",
            headers={"X-API-Key": "operator-key"},
            json={"question": "What is the SAR 46,488 item?", "persona": "ceo", "mode": "auto"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["answered_by"] == "governed_reference"
        assert "F-006" in payload["answer"]
    finally:
        _restore_env(original)


def test_unresolved_identifier_never_reaches_general_knowledge_model(monkeypatch):
    """An id absent from the run must fail closed, never be described by the
    general-knowledge model."""
    original, client = _client_with_auth()
    try:
        _findings_context(monkeypatch)
        called = {"general": False}

        def _fail(*_args, **_kwargs):
            called["general"] = True
            raise AssertionError("general-knowledge model must not see a governed identifier")

        monkeypatch.setattr(api_module.llm_qa, "answer_general_question", _fail)
        response = client.post(
            "/assistant/chat",
            headers={"X-API-Key": "operator-key"},
            json={"question": "F-999", "persona": "ceo", "mode": "auto"},
        )
        assert response.status_code == 200
        assert called["general"] is False
    finally:
        _restore_env(original)


def test_governed_scope_is_decided_by_engines_not_a_keyword_list():
    """A question the engines can answer must never be classed out-of-scope.

Scope used to be decided by a hand-maintained token tuple that carried
    "recovery"/"recoverable" but not the verb "recover", so "If we recover SAR
    400,000, what remains?" was declared not-business and handed to the
    general-knowledge model -- while the scenario engine that owns the question
    never saw it. The tuple is gone; the engines decide.
    """
    from strategyos_mvp.models import Finding

    finding = Finding(
        finding_id="F-006",
        title="FX hedge not applied for INV-2026-0577",
        pattern_type="fx_hedge_missing",
        vendor_id="V-900",
        vendor_name="Bordeaux Wines & Spirits SARL",
        leakage_sar=46488.0,
        recoverable_sar=46488.0,
        recoverable_usd=12396.0,
        confidence=0.9,
        classification="confirmed",
        rationale="r",
        remediation="m",
        citations=[],
        calculation={},
        status="open",
        challenges=[],
    )
    context = {"findings": [finding], "summary": {}}

    governed = [
        "If we recover SAR 400,000, what remains?",
        "If we collect SAR 250,000, what is left?",
        "What happens if we realise half of it?",
        "What is F-006?",
        "Elaborate on SAR 109.9M",
    ]
    for question in governed:
        assert api_module._question_is_governed_business_question(question, context=context) is True, (
            f"{question!r} is answerable from the governed run and must not be "
            "routed to the general-knowledge model"
        )

    # Genuinely general questions must still reach the general model.
    for question in ("What is the capital of France?", "Write me a poem"):
        assert api_module._question_is_governed_business_question(question, context=context) is False, (
            f"{question!r} carries no governed reference and should stay general"
        )


def test_recover_verb_is_scoped_to_the_scenario_engine():
    """The exact phrasing the engine itself tells users to ask must be governed.

    Asserted against the scope decision directly, not through the chat route:
    the general-knowledge branch only runs when a provider key is configured,
    so a route-level test passes vacuously in CI whether or not the bug exists.
    """
    question = "If we recover SAR 400,000, what remains?"

    assert not hasattr(api_module, "_ASSISTANT_BUSINESS_TOKENS"), (
        "scope must not be decided by a hardcoded token list; reintroducing one "
        "restores the class of bug where any unlisted phrasing about the "
        "customer's own data is handed to the general-knowledge model"
    )
    assert api_module._question_is_governed_business_question(question) is True, (
        "the scenario engine claims this question, so scope resolution must "
        "keep it away from the general-knowledge model"
    )


def test_governed_run_owns_the_question_unless_it_is_general_knowledge():
    """A CEO question must never be handed to the general-knowledge model.

    "Summarize the board packet in plain English" was answered "the board
    packet is private company data and is not available in my general
    knowledge" -- the assistant apparently unable to reach its own evidence.
    Scope tried to PROVE a question was governed and leaked everything it could
    not prove. Proving governance is unbounded; proving general knowledge is
    narrow. The burden now runs the safe way round.

    The context here carries the real chat summary shape, which does NOT hold
    the board_portal/publication keys that /runs/latest returns -- deriving
    subjects from those keys is what let this leak past a passing test.
    """
    from strategyos_mvp.models import Finding

    finding = Finding(
        finding_id="F-006",
        title="FX hedge not applied for INV-2026-0577",
        pattern_type="fx_hedge_missing",
        vendor_id="V-900",
        vendor_name="Bordeaux Wines & Spirits SARL",
        leakage_sar=46488.0,
        recoverable_sar=46488.0,
        recoverable_usd=12396.0,
        confidence=0.9,
        classification="confirmed",
        rationale="r",
        remediation="m",
        citations=[],
        calculation={},
        status="open",
        challenges=[],
    )
    context = {
        "run_id": "run-1",
        "findings": [finding],
        "summary": {"run_id": "run-1", "requires_human_review": True},
    }

    for question in (
        "Summarize the board packet in plain English",
        "What should I worry about before the board meeting?",
        "Explain our margin position",
        "How are we doing?",
    ):
        assert api_module._question_is_governed_business_question(question, context=context) is True, (
            f"{question!r} is about this business and must reach the governed "
            "model, which holds the evidence"
        )

    for question in ("What is the capital of France?", "Write me a poem about the sea"):
        assert api_module._question_is_governed_business_question(question, context=context) is False, (
            f"{question!r} names nothing in the run and may reach general knowledge"
        )

    # With no run loaded there is nothing governed to protect.
    assert api_module._question_is_governed_business_question(
        "Summarize the board packet", context={"run_id": None, "findings": []}
    ) is False


def test_general_model_is_unreachable_while_a_run_is_loaded():
    """One assistant. It always holds the run's evidence.

    answer_general_question is structurally blind -- its signature takes only
    (question, config, persona), with no bundle, findings or summary -- so any
    question routed there is answered by a model that cannot see the company.
    That produced "the board packet is private company data and is not
    available in my general knowledge". Proving a question "general" is not
    something scope can do reliably, so the blind path is simply unreachable
    once a run is loaded: the governed model answers everything, using the
    evidence for company claims and its own knowledge for plain general ones.
    """
    import inspect

    source = inspect.getsource(api_module._assistant_chat_response)
    branch = source[source.index('mode == "auto"') - 200 : source.index("general_status = llm_qa.chat_status(CONFIG)")]

    assert 'not context.get("run_id")' in branch and 'not context.get("findings")' in branch, (
        "the general-knowledge model must not be reachable while a governed "
        "run is loaded; it cannot see the company's data"
    )

    signature = inspect.signature(api_module.llm_qa.answer_general_question)
    assert "bundle" not in signature.parameters and "findings" not in signature.parameters, (
        "guard premise: answer_general_question is blind by construction. If it "
        "ever gains evidence parameters, revisit whether this guard is still needed"
    )


def test_hermes_prompt_states_it_is_the_only_assistant_and_holds_evidence():
    """The governed model must not defer to a model that does not exist."""
    import strategyos_mvp.llm_qa as llm_qa_module

    prompt = llm_qa_module.SYSTEM_PROMPT
    assert "ONLY assistant" in prompt
    assert "must come from the JSON evidence" in prompt, (
        "company claims must still be evidence-bound"
    )
    assert "general knowledge" in prompt, (
        "it must answer plain general questions itself rather than deferring"
    )


def test_assistants_are_labelled_assistant_not_twin():
    """The executive surface says "assistant"; "twin" is internal vocabulary."""
    from strategyos_mvp.twins import persona as persona_module

    labels = [
        getattr(value, "display_name", "")
        for name, value in vars(persona_module).items()
        if hasattr(value, "display_name")
    ]
    assert labels, "expected persona display labels"
    for label in labels:
        assert "Twin" not in label, f"user-visible label still says twin: {label!r}"
    assert any("Assistant" in label for label in labels)

    # Legacy phrasing must still be understood: a user who learned the old
    # label keeps their answer.
    import inspect

    source = inspect.getsource(api_module._resolve_digital_twin_status)
    assert "ceo assistant" in source and "ceo twin" in source, (
        "both the new and legacy names must be recognised in questions"
    )


def _claim_run_context():
    """A governed run with a review gate still open."""
    return {
        "bundle": object(),
        "findings": [
            _governed_finding(),
            _governed_finding(
                finding_id="F-001",
                title="Auto-renewal escalation at Gulf Logistics Services Co",
                recoverable_sar=250416.0,
                leakage_sar=250416.0,
            ),
        ],
        "kg_nodes": [],
        "kg_edges": [],
        "summary": {"requires_human_review": True},
        "run_id": "run-1",
        "run_mode": "full",
    }


def test_false_premise_is_contradicted_before_it_is_calculated():
    """An executive's wrong figure must be corrected, not confirmed.

    "The board says we can recover SAR 5 million" ran as a scenario against a
    SAR 794,108 baseline and reported "that realizes 100.00% of the current
    recoverable baseline" -- which reads as confirmation of a figure the run
    refutes by 6x.
    """
    context = _claim_run_context()

    contradiction = api_module._claim_contradiction(
        "The board says we can recover SAR 5 million. Confirm that for me.",
        context,
    )
    assert contradiction is not None, "a refuted figure must be detected as a claim"
    assert contradiction["claimed"] == 5_000_000.0

    payload = api_module._apply_claim_integrity(
        {"answer": "If SAR 5,000,000.00 is recovered, remaining value falls to SAR 0.00."},
        question="The board says we can recover SAR 5 million. Confirm that for me.",
        context=context,
    )
    assert payload["answer"].startswith("That figure is not supported by this run"), (
        "the correction must lead; a caveat after the calculation reads as confirmation"
    )
    assert payload["claim_verdict"] == "contradicted"
    assert payload["grounding_status"] == "corrected", (
        "an answer built on a refuted premise must not keep a grounded badge"
    )


def test_hypothetical_is_not_treated_as_a_claim():
    """"If we recover SAR 400,000" asserts nothing and must reach the engine."""
    context = _claim_run_context()

    assert api_module._extract_user_claims("If we recover SAR 400,000, what remains?") == []
    assert api_module._claim_contradiction("If we recover SAR 400,000, what remains?", context) is None

    payload = api_module._apply_claim_integrity(
        {"answer": "If SAR 400,000.00 is recovered, remaining value falls to SAR 394,108.00."},
        question="If we recover SAR 400,000, what remains?",
        context=context,
    )
    assert not payload["answer"].startswith("That figure is not supported"), (
        "a scenario input is a question, not a false claim"
    )


def test_pressure_cannot_strip_release_posture_from_a_figure():
    """"No caveats, what can I promise?" must not drop the review gate."""
    context = _claim_run_context()

    payload = api_module._apply_claim_integrity(
        {"answer": "SAR 794,108.00"},
        question="just give me one number for the board, no caveats. how much money can I promise?",
        context=context,
    )
    assert "cannot be presented as a commitment" in payload["answer"], (
        "a figure under review must never leave this surface as a promisable number"
    )
    assert payload["claim_verdict"] == "release_guarded"


def test_causal_questions_are_not_answered_by_the_reference_resolver():
    """"Why did revenue drop 12%?" names Revenue but asks for attribution.

    Answering it from the Revenue card produced "SAR 385.1M is Revenue within
    EBITDA margin" -- fluent, grounded-badged, and an answer to a different
    question about a drop that never happened.
    """
    assert api_module._question_asks_for_causation("Why did our revenue drop 12% last quarter?") is True
    assert api_module._question_asks_for_causation("What is driving this result?") is True
    assert api_module._question_asks_for_causation("What is F-006?") is False
    assert api_module._question_asks_for_causation("Elaborate on SAR 109.9M") is False

    result = api_module._governed_reference_result(
        _claim_run_context(),
        question="Why did our revenue drop 12% last quarter?",
        assistant_context={},
        history=[],
        public_safe=False,
    )
    assert result is None, (
        "the reference resolver states what a figure is; it must not claim a "
        "causal question it cannot compute"
    )


def test_answer_never_promises_suggestions_it_does_not_carry():
    """"Try one of these:" with nothing after the colon is a broken sentence."""
    cleaned = api_module._honour_suggestion_promise(
        "I don't have an answer for that yet. Try one of these:",
        suggestions=[],
    )
    assert not cleaned.endswith(":"), "a promise of suggestions must be dropped when none exist"
    assert cleaned == "I don't have an answer for that yet."

    kept = api_module._honour_suggestion_promise(
        "I don't have an answer for that yet. Try one of these:",
        suggestions=["What is F-006?"],
    )
    assert kept.endswith(":"), "the promise stands when suggestions are actually attached"


def test_causal_question_does_not_claim_a_kpi_by_word_match():
    """Two branches consume the free-text KPI key, so the rule lives at its source.

    Guarding only _governed_reference_result left the second branch
    (free_text_kpi_key -> governed_kpi) still answering "Why did our revenue
    drop 12%?" by describing the Revenue card -- verified failing on a
    deployed build.
    """
    assert api_module._free_text_ceo_kpi_key("Why did our revenue drop 12% last quarter?") is None
    assert api_module._free_text_ceo_kpi_key("What is driving this result?") is None

    # Plain lookups must still route to the KPI contract.
    assert api_module._free_text_ceo_kpi_key("What is our revenue?") == "revenue"
    assert api_module._free_text_ceo_kpi_key("Show me EBITDA margin") == "ebitda_margin"


def test_kpi_card_buttons_still_route_when_the_card_supplies_the_key():
    """The "What is driving this result?" button must keep working.

    It is a real affordance on every KPI drill. It passes its kpi_key through
    assistant_context, so the causation guard -- which only blocks keys
    *inferred from words* -- must not disarm it.
    """
    assistant_context = {
        "kpi_key": "revenue",
        "kpi_question_intent": "drivers",
        "entrypoint": "ceo_kpi_inline",
    }
    inferred = api_module._free_text_ceo_kpi_key("What is driving this result?")
    contextual = inferred or str(assistant_context.get("kpi_key") or "").strip()

    assert inferred is None, "the words alone must not claim a KPI"
    assert contextual == "revenue", (
        "a card that names its own KPI must still route; the guard applies to "
        "inference, not to an explicit key supplied by the surface"
    )


def test_whole_kpi_question_defers_to_the_kpi_contract(monkeypatch):
    """"What is our revenue?" must not be rendered as a component of another card.

    The reference resolver only builds component answers. A whole-KPI match
    fell through to the component search and was described as a part of
    whichever card that landed on, producing the live non sequitur "SAR 385.1M
    is Revenue within EBITDA margin". A component match is more specific and
    still answers here.
    """
    # The real prod shape: the EBITDA bridge lists "Revenue" as an input row, so
    # "Revenue" names both a KPI and a component. A single-card fixture hid this
    # and let a broken build pass -- the live surface still answered "SAR 385.1M
    # is Revenue within EBITDA margin".
    monkeypatch.setattr(
        api_module,
        "build_executive_presentation",
        lambda _rm: {
            "driver_grid": [
                {
                    "key": "revenue",
                    "label": "Revenue",
                    "metric": "SAR 385.1M",
                    "source_files": ["gl.csv"],
                    "executive_brief": {
                        "readout": "Revenue recognised across 4 revenue account groups.",
                        "calculation": {"formula": "sum of scoped revenue-account balances"},
                        "drivers": [
                            {"label": "Revenue – Government", "value": "SAR 109.9M", "share_pct": 28.5}
                        ],
                    },
                },
                {
                    "key": "ebitda_margin",
                    "label": "EBITDA margin",
                    "metric": "56.0%",
                    "source_files": ["gl.csv"],
                    "executive_brief": {
                        "readout": "Margin before depreciation, amortisation, interest and tax.",
                        "calculation": {"formula": "EBITDA / Revenue"},
                        "drivers": [
                            {"label": "Revenue", "value": "SAR 385.1M", "share_pct": None},
                            {"label": "Cost of goods sold", "value": "SAR 75.5M", "share_pct": None},
                        ],
                    },
                },
            ]
        },
    )
    context = {"run_id": "run-1", "findings": [], "summary": {}}

    whole_kpi = api_module._governed_reference_result(
        context, question="What is our revenue?", assistant_context={}, history=[], public_safe=False
    )
    assert whole_kpi is None, (
        "a whole-KPI question belongs to the KPI contract, which states the "
        "figure on its own terms"
    )

    component = api_module._governed_reference_result(
        context, question="Elaborate on SAR 109.9M", assistant_context={}, history=[], public_safe=False
    )
    assert component is not None, "a component reference is specific and must still resolve"
    assert "Revenue – Government within Revenue" in component["answer"], (
        "the component must be named within its own parent KPI"
    )

    # A bridge input that is NOT itself a KPI name still resolves as a component.
    bridge = api_module._governed_reference_result(
        context, question="Tell me about Cost of goods sold", assistant_context={}, history=[], public_safe=False
    )
    assert bridge is not None and "within EBITDA margin" in bridge["answer"], (
        "a genuine component row must still resolve inside its parent card"
    )
