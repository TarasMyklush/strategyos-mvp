from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

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
