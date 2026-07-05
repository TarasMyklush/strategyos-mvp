from strategyos_mvp.assistants.orchestrator import (
    AssistantOrchestrator,
    assess_question_for_persona,
    compose_persona_answer,
)


def test_substantive_finance_prompt_falls_through_persona_regex():
    result = assess_question_for_persona("What's driving the margin variance?", persona="ceo")

    assert result.matched is False
    assert result.answer == "__FALLTHROUGH__"


def test_compose_persona_answer_prefers_grounded_qa_over_persona_templates():
    result = compose_persona_answer(
        qa_result={
            "matched": True,
            "answer": "Margin variance is mainly FX and Tamween leakage.",
            "basis": "Deterministic QA answer.",
            "citations": [{"source_path": "public_packet://latest-public", "locator": "public_context_packet.drivers[1]"}],
            "suggestions": [],
            "assistant_mode": "qa_engine",
        },
        persona="ceo",
        question="What's driving the margin variance?",
    )

    assert result.mode == "qa_engine"
    assert "FX" in result.answer or "fx" in result.answer.lower()
    assert "which aspect would you like to examine" not in result.answer.lower()


def test_assistant_orchestrator_audit_log_is_bounded():
    orchestrator = AssistantOrchestrator(audit_log_maxlen=3)

    for index in range(5):
        orchestrator.process(
            question=f"hello {index}",
            persona="ceo",
            qa_result={
                "matched": True,
                "answer": f"answer {index}",
                "basis": f"basis {index}",
                "citations": [],
                "suggestions": [],
                "assistant_mode": "qa_engine",
            },
        )

    audit = orchestrator.get_audit_trail(limit=10)
    assert len(audit) == 3
    assert [item["question"] for item in audit] == ["hello 2", "hello 3", "hello 4"]
