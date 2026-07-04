from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from strategyos_mvp.config import EXTERNAL_MODE_MODEL_PROVIDER, RunPolicyConfig
from strategyos_mvp.executive_design import executive_public_assistant_packet
from strategyos_mvp.ingestion import DataBundle
from strategyos_mvp.models import Citation, Finding
from strategyos_mvp import api as api_module
from strategyos_mvp import llm_qa


def _config(**overrides):
    values = {
        "llm_chat_enabled": True,
        "model_provider_enabled": True,
        "run_policy": RunPolicyConfig(
            mode="external-approved",
            approved_external_modes=(EXTERNAL_MODE_MODEL_PROVIDER,),
        ),
        "llm_api_key": "test-key",
        "llm_provider": "openai-compatible",
        "llm_base_url": "https://api.openai.test/v1",
        "llm_model": "gpt-test",
        "llm_timeout_seconds": 3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _bundle() -> DataBundle:
    ap = pd.DataFrame(
        [
            {"Vendor_Name": "Acme", "Amount_SAR": 120.0},
            {"Vendor_Name": "Beta", "Amount_SAR": 80.0},
        ]
    )
    ar = pd.DataFrame([{"Customer_Name": "Client", "Amount_SAR": 50.0}])
    return DataBundle(
        dataset_root=Path("dataset"),
        evidence=None,
        ap=ap,
        ar=ar,
        gl=pd.DataFrame(),
        trial_balance=pd.DataFrame(),
        vendors=pd.DataFrame(),
        customers=pd.DataFrame(),
        coa=pd.DataFrame(),
        po=pd.DataFrame(),
        cash_forecast={},
        data_contracts={
            "ap_ledger": {"relative_path": "ap.xlsx"},
            "ar_ledger": {"relative_path": "ar.xlsx"},
        },
        run_metadata={"available_roles": ["ap_ledger", "ar_ledger"]},
    )


def _finding() -> Finding:
    return Finding(
        finding_id="F-001",
        title="Duplicate payment",
        pattern_type="duplicate_payment",
        vendor_id="V-1",
        vendor_name="Acme",
        leakage_sar=120.0,
        recoverable_sar=120.0,
        recoverable_usd=32.0,
        confidence="HIGH",
        classification="recoverable",
        rationale="Same invoice paid twice.",
        remediation="Recover duplicate payment.",
        citations=[Citation("ap.xlsx", "row 2", "Acme duplicate row")],
    )


def test_llm_chat_status_requires_policy_and_key():
    assert llm_qa.chat_status(_config(llm_chat_enabled=False))["enabled"] is False
    assert llm_qa.chat_status(_config(model_provider_enabled=False))["enabled"] is False
    assert llm_qa.chat_status(_config(llm_api_key=None))["enabled"] is False
    assert llm_qa.chat_status(_config())["enabled"] is True


def test_llm_answer_uses_openai_compatible_chat(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "matched": True,
                                        "answer": "Acme has SAR 120.00 recoverable.",
                                        "basis": "Finding F-001 in supplied evidence.",
                                        "citations": [
                                            {
                                                "source_path": "ap.xlsx",
                                                "locator": "row 2",
                                                "finding_id": "F-001",
                                            }
                                        ],
                                        "suggestions": [],
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["auth"] = request.headers["Authorization"]
        return FakeResponse()

    monkeypatch.setattr(llm_qa, "urlopen", fake_urlopen)

    result = llm_qa.answer_question(
        "What is recoverable for Acme?",
        bundle=_bundle(),
        findings=[_finding()],
        summary={"run_id": "run-1", "total_recoverable_sar": 120.0},
        config=_config(),
    )

    assert captured["url"] == "https://api.openai.test/v1/chat/completions"
    assert captured["timeout"] == 3
    assert captured["auth"] == "Bearer test-key"
    assert captured["body"]["model"] == "gpt-test"
    assert result["matched"] is True
    assert result["citations"][0]["source_path"] == "ap.xlsx"
    assert result["llm_status"]["enabled"] is True


def test_public_llm_answer_uses_minimal_public_packet_prompt(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "matched": True,
                                        "answer": "Board-safe answer from the public packet.",
                                        "basis": "Grounded in public packet facts.",
                                        "citations": [
                                            {
                                                "source_path": "public_packet://executive_surface",
                                                "locator": "public_context_packet.facts[0]",
                                            }
                                        ],
                                        "suggestions": [],
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    captured = {}

    def fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(llm_qa, "urlopen", fake_urlopen)

    result = llm_qa.answer_question(
        "give me numbers for last week",
        bundle=_bundle(),
        findings=[_finding()],
        summary={"run_id": "latest-public", "run_mode": "public-safe"},
        config=_config(),
        public_context_packet={
            "packet_id": "public-executive:ceo",
            "persona_id": "ceo",
            "assistant": "Hermes",
            "facts": ["SAR 8.6M is recoverable across the group."],
            "kpis": [{"key": "revenue", "value": "SAR 2.09B"}],
            "drivers": [{"key": "ebitda", "story": "FX is the main drag."}],
            "findings": [{"title": "Tamween audit", "detail": "SAR 1.2M recoverable."}],
            "developments": [{"title": "NUPCO awards confirmed"}],
            "week": [{"title": "Board meeting", "prep": "Margin narrative still open."}],
            "board_portal": {"summary": "Board packet summary"},
            "agent_activity": {"line": "5 agents active"},
            "running_agents": [{"name": "Board pack composer", "progress": 80}],
            "kg_nodes": [{"id": "kpi:revenue"}],
            "kg_edges": [{"source": "a", "target": "b", "label": "LINKS"}],
            "public_facts": {"source_boundary": "Public-safe executive packet only."},
            "view_state": {"persona": "ceo"},
        },
        persona="ceo",
    )

    assert captured["timeout"] == 3
    assert "board-safe ceo assistant" in captured["body"]["messages"][0]["content"].lower()
    assert captured["body"]["messages"][1]["content"].find("public_context") != -1
    assert result["public_safe"] is True
    assert result["citations"][0]["locator"] == "public_context_packet.facts[0]"


def test_public_llm_answer_uses_public_packet_prompt(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "matched": True,
                                        "answer": "Last week looked healthy on revenue, but margin still needs the FX and Tamween clean-up story.",
                                        "basis": "Grounded in the public executive packet facts, KPI cards, and weekly board-prep items.",
                                        "citations": [
                                            {
                                                "source_path": "public_packet://latest-public",
                                                "locator": "public_context_packet.kpis[1]",
                                            }
                                        ],
                                        "suggestions": ["What changed since last week?"],
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(llm_qa, "urlopen", fake_urlopen)

    result = llm_qa.answer_question(
        "give me numbers for last week",
        bundle=_bundle(),
        findings=[_finding()],
        summary={"run_id": "latest-public", "run_mode": "public-safe"},
        config=_config(),
        public_context_packet=executive_public_assistant_packet("ceo"),
        persona="ceo",
    )

    assert captured["body"]["messages"][0]["content"] == llm_qa.PUBLIC_SYSTEM_PROMPT
    evidence = json.loads(captured["body"]["messages"][1]["content"])["evidence"]
    assert evidence["public_context"]["persona_id"] == "ceo"
    assert evidence["public_context"]["public_safe"] is True
    assert evidence["kpis"]
    assert evidence["drivers"]
    assert evidence["week"]
    assert evidence["public_facts"]["group_recoverable_sar"] == 8_600_000.0
    assert result["answer"].lower().startswith("last week looked healthy")
    assert result["citations"][0]["locator"] == "public_context_packet.kpis[1]"


def test_llm_answer_parses_markdown_wrapped_json(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "```json\n{\"matched\": true, \"answer\": \"Board-safe answer.\", \"basis\": \"Packet evidence.\", \"citations\": [], \"suggestions\": []}\n```"
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr(llm_qa, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    result = llm_qa.answer_question(
        "summarize the board packet in plain English",
        bundle=_bundle(),
        findings=[_finding()],
        summary={"run_id": "latest-public", "run_mode": "public-safe"},
        config=_config(),
        public_context_packet=executive_public_assistant_packet("ceo"),
        persona="ceo",
    )

    assert result["matched"] is True
    assert result["answer"] == "Board-safe answer."
    assert result["basis"] == "Packet evidence."


def test_empty_provider_content_retries_with_plain_text_prompt(monkeypatch):
    responses = [
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": "The public packet shows revenue ahead, margin soft, and FX still on the board agenda."}}]},
    ]
    captured_bodies = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured_bodies.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse(responses[len(captured_bodies) - 1])

    monkeypatch.setattr(llm_qa, "urlopen", fake_urlopen)

    result = llm_qa.answer_question(
        "what should I worry about before the board meeting?",
        bundle=_bundle(),
        findings=[_finding()],
        summary={"run_id": "latest-public", "run_mode": "public-safe"},
        config=_config(),
        public_context_packet=executive_public_assistant_packet("ceo"),
        persona="ceo",
    )

    assert len(captured_bodies) == 2
    assert captured_bodies[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in captured_bodies[1]
    assert "do not return json" in captured_bodies[1]["messages"][0]["content"].lower()
    assert result["answer"].startswith("The public packet shows revenue ahead")
    assert result["citations"]


def test_malformed_json_like_provider_content_retries_with_plain_text_prompt(monkeypatch):
    responses = [
        {"choices": [{"message": {"content": '{ "matched": true, "answer": "The'}}]},
        {"choices": [{"message": {"content": "The public packet shows revenue ahead, margin soft, and FX still on the board agenda."}}]},
    ]
    captured_bodies = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured_bodies.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse(responses[len(captured_bodies) - 1])

    monkeypatch.setattr(llm_qa, "urlopen", fake_urlopen)

    result = llm_qa.answer_question(
        "summarize the board packet in plain English",
        bundle=_bundle(),
        findings=[_finding()],
        summary={"run_id": "latest-public", "run_mode": "public-safe"},
        config=_config(),
        public_context_packet=executive_public_assistant_packet("ceo"),
        persona="ceo",
    )

    assert len(captured_bodies) == 2
    assert captured_bodies[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in captured_bodies[1]
    assert result["answer"].startswith("The public packet shows revenue ahead")


def test_empty_provider_content_after_retry_raises_clear_error(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": ""}}]}).encode("utf-8")

    monkeypatch.setattr(llm_qa, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    with pytest.raises(RuntimeError, match="empty answer after retry"):
        llm_qa.answer_question(
            "give me numbers for last week",
            bundle=_bundle(),
            findings=[_finding()],
            summary={"run_id": "latest-public", "run_mode": "public-safe"},
            config=_config(),
            public_context_packet=executive_public_assistant_packet("ceo"),
            persona="ceo",
        )


def test_double_encoded_json_answer_is_unwrapped(monkeypatch):
    nested = {
        "matched": True,
        "answer": "Since last week revenue stayed ahead while FX still pressures margin.",
        "basis": "Grounded in public packet week items.",
        "citations": [{"source_path": "public_packet://latest-public", "locator": "public_context_packet.week[0]"}],
        "suggestions": [],
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(json.dumps(nested))}}]}
            ).encode("utf-8")

    monkeypatch.setattr(llm_qa, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    result = llm_qa.answer_question(
        "what changed since last week?",
        bundle=_bundle(),
        findings=[_finding()],
        summary={"run_id": "latest-public", "run_mode": "public-safe"},
        config=_config(),
        public_context_packet=executive_public_assistant_packet("ceo"),
        persona="ceo",
    )

    assert result["answer"] == nested["answer"]
    assert result["basis"] == nested["basis"]
    assert result["citations"][0]["locator"] == "public_context_packet.week[0]"


@pytest.mark.parametrize(
    "question,answer",
    [
        ("give me numbers for last week", "Last week the visible packet shows revenue ahead, margin slightly below plan, and FX still acting as a drag."),
        ("what changed since last week?", "Since last week, NUPCO awards were confirmed, the board pack moved forward, and FX remains the watch item."),
        ("what should I worry about before the board meeting?", "Before the board meeting, worry about the margin narrative, the hedge decision, and Tamween follow-through."),
        ("summarize the board packet in plain English", "In plain English: revenue is ahead, margin is soft, SAR 8.6M is recoverable, and two board decisions are still open."),
    ],
)
def test_natural_public_prompts_return_clean_answer_text_not_raw_json(monkeypatch, question, answer):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "matched": True,
                                        "answer": json.dumps(
                                            {
                                                "matched": True,
                                                "answer": answer,
                                                "basis": "Grounded in the public packet.",
                                                "citations": [{"source_path": "public_packet://latest-public", "locator": "public_context_packet.facts[0]"}],
                                                "suggestions": [],
                                            }
                                        ),
                                        "basis": "Outer wrapper should be ignored.",
                                        "citations": [],
                                        "suggestions": [],
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr(llm_qa, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    result = llm_qa.answer_question(
        question,
        bundle=_bundle(),
        findings=[_finding()],
        summary={"run_id": "latest-public", "run_mode": "public-safe"},
        config=_config(),
        public_context_packet=executive_public_assistant_packet("ceo"),
        persona="ceo",
    )

    assert result["answer"] == answer
    assert not result["answer"].lstrip().startswith("{")
    assert result["basis"] == "Grounded in the public packet."


def test_provider_health_status_reports_failed_provider_runtime(monkeypatch):
    monkeypatch.setattr(
        llm_qa,
        "_call_openai_compatible_chat",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError('LLM provider returned HTTP 402: {"error":{"message":"Insufficient Balance"}}')
        ),
    )

    status = llm_qa.provider_health_status(_config())

    assert status["status"] == "failed"
    assert status["enabled"] is True
    assert status["checked"] is True
    assert "Insufficient Balance" in status["reason"]

def test_data_qa_auto_invokes_llm_when_deterministic_misses(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "_resolve_qa_context",
        lambda _run_id: {
            "run_id": "run-auto",
            "run_mode": "full",
            "bundle": _bundle(),
            "findings": [_finding()],
            "summary": {"run_id": "run-auto", "total_recoverable_sar": 120.0},
        },
    )
    monkeypatch.setattr(
        api_module.qa_engine,
        "answer_question",
        lambda *_args, **_kwargs: {
            "matched": False,
            "answer": "No deterministic answer.",
            "citations": [],
            "suggestions": [],
        },
    )
    monkeypatch.setattr(
        api_module.llm_qa,
        "chat_status",
        lambda _config: {"enabled": True, "provider": "test", "model": "ai-test"},
    )
    monkeypatch.setattr(
        api_module.llm_qa,
        "answer_question",
        lambda *_args, **_kwargs: {
            "matched": True,
            "answer": "AI fallback answered from supplied evidence.",
            "basis": "supplied run evidence",
            "citations": [],
            "suggestions": [],
        },
    )

    result = api_module.data_qa(
        api_module.QaRequest(question="Explain this in plain English", mode="auto"),
        _={"role": "executive"},
    )

    assert result["status"] == "ok"
    assert result["mode"] == "llm"
    assert result["requested_mode"] == "auto"
    assert result["deterministic_matched"] is False
    assert result["answer"] == "AI fallback answered from supplied evidence."


def test_llm_answer_retries_plain_text_when_structured_response_is_empty(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

    calls: list[dict[str, object]] = []
    responses = [
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": "Last week from the public packet, margin is still the issue and FX remains the live watch item."}}]},
    ]

    def fake_urlopen(request, timeout):
        calls.append({"timeout": timeout, "body": json.loads(request.data.decode("utf-8"))})
        return FakeResponse(responses[len(calls) - 1])

    monkeypatch.setattr(llm_qa, "urlopen", fake_urlopen)

    result = llm_qa.answer_question(
        "give me numbers for last week",
        bundle=_bundle(),
        findings=[_finding()],
        summary={"run_id": "latest-public", "run_mode": "public-safe"},
        config=_config(),
        public_context_packet=executive_public_assistant_packet("ceo"),
        persona="ceo",
    )

    assert len(calls) == 2
    assert calls[0]["body"]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[1]["body"]
    assert result["answer"].startswith("Last week from the public packet")
    assert result["basis"] == "LLM answer grounded in supplied public executive packet."


def test_parse_json_answer_unwraps_double_encoded_payload():
    raw = json.dumps(
        json.dumps(
            {
                "matched": True,
                "answer": "Since last week, NUPCO awards were confirmed and the board pack moved forward.",
                "basis": "Grounded in the public packet.",
                "citations": [],
                "suggestions": [],
            }
        )
    )

    parsed = llm_qa._parse_json_answer(raw)

    assert parsed["matched"] is True
    assert parsed["answer"].startswith("Since last week")
    assert parsed["basis"] == "Grounded in the public packet."


def test_parse_json_answer_unwraps_nested_answer_json():
    raw = json.dumps(
        {
            "matched": True,
            "answer": json.dumps(
                {
                    "matched": True,
                    "answer": "The board meeting risk is still the margin narrative and hedge decision.",
                    "basis": "Grounded in public drivers and board context.",
                    "citations": [],
                    "suggestions": [],
                }
            ),
            "basis": "placeholder",
            "citations": [],
            "suggestions": [],
        }
    )

    parsed = llm_qa._parse_json_answer(raw)

    assert parsed["answer"].startswith("The board meeting risk")
    assert parsed["basis"] == "Grounded in public drivers and board context."


def test_public_natural_prompts_return_clean_visible_answers(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

    prompts = {
        "give me numbers for last week": {
            "content": json.dumps(
                {
                    "matched": True,
                    "answer": "Last week from the public packet: revenue stayed ahead, EBITDA margin was 19.2% versus 19.4% plan, and FX remained a weekly drag.",
                    "basis": "Grounded in KPI cards and weekly items.",
                    "citations": [],
                    "suggestions": [],
                }
            ),
            "must_contain": ["19.2%", "fx"],
        },
        "what changed since last week?": {
            "content": json.dumps(
                {
                    "matched": True,
                    "answer": json.dumps(
                        {
                            "matched": True,
                            "answer": "Since last week, NUPCO awards were confirmed, cold-chain stayed at 99.4%, and the board pack moved closer to ready.",
                            "basis": "Grounded in public developments and weekly items.",
                            "citations": [],
                            "suggestions": [],
                        }
                    ),
                    "basis": "placeholder",
                    "citations": [],
                    "suggestions": [],
                }
            ),
            "must_contain": ["nupco", "99.4%"],
        },
        "what should i worry about before the board meeting?": {
            "content": json.dumps(
                json.dumps(
                    {
                        "matched": True,
                        "answer": "Before the board meeting, the main worry is still the margin narrative: FX, API cost leakage, and the open hedge decision.",
                        "basis": "Grounded in drivers and board context.",
                        "citations": [],
                        "suggestions": [],
                    }
                )
            ),
            "must_contain": ["margin narrative", "hedge"],
        },
        "summarize the board packet in plain english": {
            "content": "```json\n{\"matched\": true, \"answer\": \"In plain English: revenue is ahead, margin is the soft spot, SAR 8.6M is recoverable, and the live decisions are the hedge and the JV.\", \"basis\": \"Grounded in the board portal and public facts.\", \"citations\": [], \"suggestions\": []}\n```",
            "must_contain": ["plain english", "sar 8.6m"],
        },
    }

    def fake_urlopen(request, timeout):
        del timeout
        body = json.loads(request.data.decode("utf-8"))
        question = json.loads(body["messages"][1]["content"])["question"].lower()
        return FakeResponse({"choices": [{"message": {"content": prompts[question]["content"]}}]})

    monkeypatch.setattr(llm_qa, "urlopen", fake_urlopen)

    for question, expectation in prompts.items():
        result = llm_qa.answer_question(
            question,
            bundle=_bundle(),
            findings=[_finding()],
            summary={"run_id": "latest-public", "run_mode": "public-safe"},
            config=_config(),
            public_context_packet=executive_public_assistant_packet("ceo"),
            persona="ceo",
        )
        answer_lower = result["answer"].lower()
        assert not result["answer"].lstrip().startswith("{"), question
        assert '"matched"' not in answer_lower, question
        for token in expectation["must_contain"]:
            assert token in answer_lower, f"Missing {token!r} for {question}"


def test_provider_content_block_prefers_structured_json_part(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "reasoning", "text": "I should answer from the public packet only."},
                                    {
                                        "type": "text",
                                        "text": json.dumps(
                                            {
                                                "matched": True,
                                                "answer": "Tamween Distribution is the clearest margin drag in the public packet.",
                                                "basis": "Grounded in public findings and drivers.",
                                                "citations": [],
                                                "suggestions": [],
                                            }
                                        ),
                                    },
                                ]
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr(llm_qa, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    result = llm_qa.answer_question(
        "which business unit is dragging margin?",
        bundle=_bundle(),
        findings=[_finding()],
        summary={"run_id": "latest-public", "run_mode": "public-safe"},
        config=_config(),
        public_context_packet=executive_public_assistant_packet("ceo"),
        persona="ceo",
    )

    assert result["answer"] == "Tamween Distribution is the clearest margin drag in the public packet."
    assert result["basis"] == "Grounded in public findings and drivers."


def test_clean_visible_answer_extracts_answer_from_truncated_jsonish_text():
    raw = '{\n  "matched": true,\n  "answer": "Since last week, NUPCO awards were confirmed and FX remains the main margin watch item.",\n  "basis": "Grounded in public developments."'

    cleaned = llm_qa._clean_visible_answer(raw)

    assert cleaned == "Since last week, NUPCO awards were confirmed and FX remains the main margin watch item."
