from strategyos_mvp.assistants.orchestrator import compose_persona_answer


def test_cascade_precedence_order_deterministic_grounding_stays_ahead_of_llm_and_persona():
    result = compose_persona_answer(
        qa_result={"matched": True, "answer": "tabular", "basis": "qa", "citations": [], "answered_by": "tabular"},
        graph_result={"matched": True, "answer": "graph", "basis": "graph", "citations": [{"source_path": "neo4j://run", "locator": "Finding:F-001"}], "answered_by": "graph"},
        retrieval_result={"matched": True, "answer": "vector", "basis": "vector", "citations": [{"source_path": "qdrant://run", "locator": "pt-1"}], "answered_by": "vector"},
        llm_result={"matched": True, "answer": "llm", "basis": "llm", "citations": [{"source_path": "llm://evidence", "locator": "1"}], "answered_by": "llm"},
        scenario_result={"matched": True, "answer": "scenario", "basis": "scenario", "citations": []},
        persona="ceo",
        question="What's driving this?",
    )

    assert result.answer == "scenario"
    assert result.answered_by == "scenario"


def test_cascade_precedence_graph_beats_vector_tabular_llm_and_persona():
    result = compose_persona_answer(
        qa_result={"matched": True, "answer": "tabular", "basis": "qa", "citations": [], "answered_by": "tabular"},
        graph_result={"matched": True, "answer": "graph", "basis": "graph", "citations": [{"source_path": "neo4j://run", "locator": "Finding:F-001"}], "answered_by": "graph"},
        retrieval_result={"matched": True, "answer": "vector", "basis": "vector", "citations": [{"source_path": "qdrant://run", "locator": "pt-1"}], "answered_by": "vector"},
        llm_result={"matched": True, "answer": "llm", "basis": "llm", "citations": [{"source_path": "llm://evidence", "locator": "1"}], "answered_by": "llm"},
        persona="ceo",
        question="Show me evidence for F-001",
    )

    assert result.answer == "graph"
    assert result.answered_by == "graph"


def test_persona_canned_and_fallback_answered_by_are_truthful():
    persona_result = compose_persona_answer(None, persona="ceo", question="hello")
    fallback_result = compose_persona_answer(None, persona="ceo", question="something unmatched with no routes")

    assert persona_result.answered_by == "persona_canned"
    assert fallback_result.answered_by == "fallback"
