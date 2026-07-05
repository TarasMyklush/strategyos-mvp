"""CRITICAL: Deterministic vs LLM/Hallucination boundary verification.

Verifies that the StrategyOS QA engine (qa.py) is a DETERMINISTIC data engine:
- No LLM calls, no model imports, no API keys used
- Strict keyword/regex matching only
- Every answer carries an exact "basis" describing how it was computed
- Unrecognized questions return suggestions, NOT guesses
- No hallucination path exists in the deterministic engine

This is a SECURITY/CORRECTNESS boundary: the QA engine must NEVER hallucinate.
All LLM paths are gated behind separate config (llm_qa.py) and require explicit
run_policy approval (external-approved mode).

Target architecture: qa.py (deterministic) vs llm_qa.py (LLM-gated)
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

import strategyos_mvp.qa as qa_module
from strategyos_mvp.assistants.orchestrator import _CEO_PATTERNS, _CFO_PATTERNS
from strategyos_mvp import qa


# ─────────────────────────────────────────────────────────────────────────────
# Source-level verification: NO LLM imports in qa.py
# ─────────────────────────────────────────────────────────────────────────────

def test_qa_module_has_no_llm_imports():
    """qa.py must not import any LLM library or API client."""
    qa_source = Path(qa_module.__file__).read_text()
    forbidden = [
        "openai", "httpx", "requests", "anthropic", "google.generativeai",
        "llm_qa", "langchain", "langgraph", "deepseek", "model_provider",
        "api_key", "API_KEY",
    ]
    lines_lower = qa_source.lower()
    for term in forbidden:
        assert term not in lines_lower, (
            f"qa.py contains forbidden import/string: '{term}'. "
            f"This would indicate an LLM dependency in the deterministic QA engine."
        )


def test_qa_module_has_no_http_calls():
    """qa.py must not make HTTP calls — it should be pure computation."""
    qa_source = Path(qa_module.__file__).read_text()
    forbidden_patterns = [
        r"urlopen", r"http\.client", r"httpx", r"requests\.",
        r"urllib\.request", r"aiohttp",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, qa_source), (
            f"qa.py contains HTTP call pattern: '{pattern}'"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Function-level verification: no LLM in answer_question
# ─────────────────────────────────────────────────────────────────────────────

def answer_question_source() -> str:
    """Extract only the answer_question function source for targeted analysis."""
    return inspect.getsource(qa.answer_question)


def test_answer_question_uses_only_keyword_matching():
    """The answer_question function must only use keyword/regex matching.

    It should ONLY call:
    - _normalize() for text cleaning
    - _expand_synonyms() for colloquial phrasing
    - _has() / _has_any() for intent matching (internal regex functions)
    - Intent handler functions from the INTENTS registry

    It must NOT call:
    - Any LLM or API function
    - Any config lookup for model provider
    """
    source = answer_question_source()
    # Verify the core matching primitives are present
    assert "_normalize" in source, "Missing _normalize helper"
    assert "_expand_synonyms" in source, "Missing synonym expansion"
    assert "intent.matcher" in source, "Missing intent matching loop"

    # Verify no LLM fallback
    forbidden = ["llm", "model", "openai", "api_key", "chat", "completion",
                  "gpt", "claude", "deepseek", "hallucin"]
    source_lower = source.lower()
    for term in forbidden:
        assert term not in source_lower, (
            f"answer_question contains '{term}' — this would indicate LLM integration "
            f"in the deterministic path"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ALL intent handlers are deterministic
# ─────────────────────────────────────────────────────────────────────────────

def test_all_intent_handlers_are_deterministic():
    """Every intent handler must compute answers from DataBundle/DataFrame data only.

    No handler should:
    - Import or call LLM functions
    - Access external APIs
    - Use any non-deterministic source
    """
    for intent in qa.INTENTS:
        handler_source = inspect.getsource(intent.handler)
        handler_lower = handler_source.lower()
        forbidden = ["llm", "model", "openai", "api_key", "chat", "completion",
                      "gpt", "claude", "deepseek", "httpx", "requests.", "urlopen"]
        for term in forbidden:
            assert term not in handler_lower, (
                f"Intent handler '{intent.name}' contains forbidden term '{term}'. "
                f"All handlers must be pure computation."
            )


# ─────────────────────────────────────────────────────────────────────────────
# Synonym expansions are deterministic (no model inference)
# ─────────────────────────────────────────────────────────────────────────────

def test_synonym_expansions_are_static_regex_patterns():
    """Synonym expansions must be compile-time static regex patterns.

    They must NOT be generated at runtime, loaded from a model, or inferred.
    """
    expansions = qa._SYNONYM_EXPANSIONS
    assert isinstance(expansions, tuple), "_SYNONYM_EXPANSIONS must be a static tuple"
    assert len(expansions) > 0, "Synonym expansions must not be empty"
    for pattern, canonical in expansions:
        assert isinstance(pattern, str), f"Synonym pattern must be a string: {pattern}"
        assert isinstance(canonical, str), f"Synonym canonical must be a string: {canonical}"
        # Verify the pattern is a valid regex
        try:
            re.compile(pattern)
        except re.error as e:
            pytest.fail(f"Invalid regex pattern '{pattern}': {e}")


def test_synonym_expansion_is_pure():
    """_expand_synonyms must produce deterministic output for any input."""
    # Known mappings
    assert "how much are we losing leakage recoverable" in qa._expand_synonyms(
        "how much are we losing"
    )
    assert "what can we claw back recoverable recovery" in qa._expand_synonyms(
        "what can we claw back"
    )
    # No false positives: "invoice" alone should not expand
    assert qa._expand_synonyms("invoice") == "invoice"
    # Empty input
    assert qa._expand_synonyms("") == ""


# ─────────────────────────────────────────────────────────────────────────────
# Suggestions are static (not model-generated)
# ─────────────────────────────────────────────────────────────────────────────

def test_suggestions_are_static():
    """SUGGESTIONS must be a compile-time tuple, not dynamically generated."""
    assert isinstance(qa.SUGGESTIONS, tuple), "SUGGESTIONS must be a static tuple"
    assert len(qa.SUGGESTIONS) == 9, (
        f"SUGGESTIONS length changed: {len(qa.SUGGESTIONS)} (expected 9)"
    )
    # Every suggestion must be a non-empty string
    for s in qa.SUGGESTIONS:
        assert isinstance(s, str), f"Suggestion is not a string: {s}"
        assert s.strip(), "Suggestion must not be empty"


# ─────────────────────────────────────────────────────────────────────────────
# INTENTS registry is deterministic
# ─────────────────────────────────────────────────────────────────────────────

def test_intents_registry_is_complete_and_ordered():
    """All intents must be defined statically with names matching handlers."""
    expected_intents = [
        "working_capital",
        "overdue",
        "recoverable",
        "findings",
        "top_parties",
        "distinct_parties",
        "named_party_spend",
        "invoice_metric",
    ]
    actual = [i.name for i in qa.INTENTS]
    assert actual == expected_intents, (
        f"INTENTS order mismatch.\n  Got:      {actual}\n  Expected: {expected_intents}"
    )


def test_intents_are_ordered_first_match_wins():
    """INTENTS must be ordered so more-specific matchers come before generic ones.

    For example:
    - 'working_capital' before 'invoice_metric' (DSO-specific vs general invoice)
    - 'overdue' before 'invoice_metric' (overdue is a filtered subset)
    - 'recoverable' before 'findings' (recoverable is more specific)
    - 'named_party_spend' before 'invoice_metric' (party-specific)
    """
    names = [i.name for i in qa.INTENTS]
    # working_capital must come before any broad intent
    assert names.index("working_capital") < names.index("invoice_metric")
    assert names.index("overdue") < names.index("invoice_metric")
    assert names.index("recoverable") < names.index("findings")
    # named_party_spend must come before invoice_metric
    assert names.index("named_party_spend") < names.index("invoice_metric")
    # top_parties must come before distinct_parties
    assert names.index("top_parties") < names.index("distinct_parties")


# ─────────────────────────────────────────────────────────────────────────────
# Separately: verify LLM path IS gated (opposite boundary)
# ─────────────────────────────────────────────────────────────────────────────

def test_llm_qa_module_exists_and_is_separate():
    """llm_qa.py must exist as a SEPARATE module with its own answer_question.

    The deterministic engine (qa.py) and LLM engine (llm_qa.py) are separate
    modules with separate answer_question functions. The API layer (api.py)
    decides which to call based on run_policy and config.
    """
    import strategyos_mvp.llm_qa as llm_qa
    assert hasattr(llm_qa, "answer_question"), "llm_qa must have its own answer_question"
    # llm_qa.answer_question MUST require config parameter
    sig = inspect.signature(llm_qa.answer_question)
    assert "config" in sig.parameters, "llm_qa.answer_question must require config"
    # qa.answer_question must NOT accept config
    qa_sig = inspect.signature(qa.answer_question)
    assert "config" not in qa_sig.parameters, (
        "qa.answer_question must NOT accept config (it is deterministic)"
    )


def test_persona_regex_layer_no_longer_intercepts_generic_finance_topics():
    ceo_patterns = " ".join(pattern for pattern, _ in _CEO_PATTERNS)
    cfo_patterns = " ".join(pattern for pattern, _ in _CFO_PATTERNS)
    forbidden = ["margin", "revenue", "cash", "risk", "growth", "kpi", "budget", "forecast"]
    for token in forbidden:
        assert token not in ceo_patterns.lower(), f"CEO regex still intercepts generic finance term: {token}"
        assert token not in cfo_patterns.lower(), f"CFO regex still intercepts generic finance term: {token}"


def test_deterministic_engine_surface_area():
    """The deterministic engine exposes ONLY these public functions."""
    public = sorted(
        name for name in dir(qa)
        if not name.startswith("_") and callable(getattr(qa, name))
    )
    expected = {"answer_question"}
    assert set(public) == expected, (
        f"Deterministic engine public API changed.\n"
        f"  Got:      {public}\n"
        f"  Expected: {expected}\n"
        f"If new public functions were added, review whether they remain deterministic."
    )


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end: verify deterministic QA never falls back to LLM
# ─────────────────────────────────────────────────────────────────────────────

def test_deterministic_qa_has_no_llm_fallback_path(monkeypatch):
    """Even with a malformed bundle, answer_question must never call an LLM.

    If someone tries to inject a model into the deterministic path, the engine
    should still produce a deterministic response (either matched or unmatched).
    """
    from types import SimpleNamespace

    import pandas as pd
    from strategyos_mvp.ingestion import DataBundle

    empty_bundle = DataBundle(
        dataset_root=Path("."),
        evidence=None,
        ap=pd.DataFrame(),
        ar=pd.DataFrame(),
        gl=pd.DataFrame(),
        trial_balance=pd.DataFrame(),
        vendors=pd.DataFrame(),
        customers=pd.DataFrame(),
        coa=pd.DataFrame(),
        po=pd.DataFrame(),
        cash_forecast={},
        run_metadata={"available_roles": []},
    )

    # All questions should return deterministic responses (matched or suggestions)
    for question in [
        "total invoices", "recoverable", "top vendors",
        "how many findings", "working capital drift",
        "completely random gibberish xyz123",
    ]:
        result = qa.answer_question(question, bundle=empty_bundle, findings=[])
        # Must have matched (True/False) — never an exception
        assert "matched" in result, f"Result missing 'matched' for '{question}'"
        assert isinstance(result["matched"], bool)
        # Must NEVER contain LLM indicators
        assert "hallucin" not in str(result).lower(), (
            f"Result for '{question}' contains 'hallucination' indicator"
        )
        assert result.get("llm_status") is None, (
            f"Deterministic result for '{question}' has llm_status"
        )
