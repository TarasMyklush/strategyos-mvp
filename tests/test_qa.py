import pytest

from strategyos_mvp import qa
from strategyos_mvp.ingestion import load_dataset
from strategyos_mvp.paths import SOURCE_DATASET
from strategyos_mvp.skills.finance_controls import run_all_finance_skills


@pytest.fixture(scope="module")
def qa_context():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    return bundle, findings


def test_invoice_totals_counts_and_party_breakdowns_are_exact(qa_context):
    bundle, findings = qa_context

    total_ap = qa.answer_question(
        "what is the total amount of invoices?", bundle=bundle, findings=findings
    )
    assert total_ap["matched"] is True
    assert total_ap["intent"] == "invoice_metric"
    assert total_ap["value"] == pytest.approx(133_646_616.03)
    assert total_ap["basis"] == "sum of Amount_SAR over 1,397 AP rows."
    assert total_ap["citations"]

    ap_count = qa.answer_question(
        "how many AP invoices are there?", bundle=bundle, findings=findings
    )
    assert ap_count["value"] == 1397

    ar_count = qa.answer_question(
        "how many AR invoices are there?", bundle=bundle, findings=findings
    )
    assert ar_count["value"] == 800

    distinct_vendors = qa.answer_question(
        "how many distinct vendors are there?", bundle=bundle, findings=findings
    )
    assert distinct_vendors["value"] == 210

    top_vendors = qa.answer_question(
        "top 5 vendors by spend", bundle=bundle, findings=findings
    )
    assert top_vendors["value"][0]["name"] == "Saudi Pharma Suppliers Co"


def test_recoverable_findings_and_unmatched_questions(qa_context):
    bundle, findings = qa_context

    recoverable = qa.answer_question(
        "what is the total recoverable?", bundle=bundle, findings=findings
    )
    assert recoverable["matched"] is True
    assert recoverable["value"] == pytest.approx(794_108.0)
    assert recoverable["basis"] == "sum of recoverable_sar over 8 findings."

    by_pattern = qa.answer_question(
        "show recoverable by pattern", bundle=bundle, findings=findings
    )
    assert by_pattern["value"][0]["recoverable_sar"] > 0

    no_match = qa.answer_question("gibberish xyz", bundle=bundle, findings=findings)
    assert no_match["matched"] is False
    assert no_match["suggestions"]


def test_partial_run_missing_role_returns_clear_message(qa_context):
    bundle, findings = qa_context
    original_roles = bundle.run_metadata.get("available_roles")
    bundle.run_metadata["available_roles"] = ["ap_ledger"]

    try:
        result = qa.answer_question(
            "what are the working capital drift signals?", bundle=bundle, findings=findings
        )
    finally:
        if original_roles is None:
            bundle.run_metadata.pop("available_roles", None)
        else:
            bundle.run_metadata["available_roles"] = original_roles

    assert result["matched"] is True
    assert result["available"] is False
    assert "needs the AP and AR ledgers" in result["answer"]


def test_colloquial_phrasing_routes_to_the_right_intent(qa_context):
    bundle, findings = qa_context

    # Business-user phrasing for "recoverable" — none of these contain the literal
    # trigger words, so they only match via synonym expansion.
    for phrasing in (
        "how much are we losing?",
        "where is cash going out the door?",
        "what can we claw back?",
        "how much money are we bleeding?",
    ):
        result = qa.answer_question(phrasing, bundle=bundle, findings=findings)
        assert result["matched"] is True, phrasing
        assert result["intent"] == "recoverable", phrasing
        assert result["value"] == pytest.approx(794_108.0), phrasing

    # "supplier" should reach the vendor intents just like "vendor".
    top_suppliers = qa.answer_question(
        "top 5 suppliers by spend", bundle=bundle, findings=findings
    )
    assert top_suppliers["intent"] == "top_parties"
    assert top_suppliers["value"][0]["name"] == "Saudi Pharma Suppliers Co"

    # Colloquial ranking phrasing ("biggest suppliers") also reaches top_parties.
    biggest = qa.answer_question("who are our biggest suppliers?", bundle=bundle, findings=findings)
    assert biggest["intent"] == "top_parties"

    # Guard: a bare ranking word must NOT hijack an unrelated noun into top_parties.
    # "biggest invoice" has no party word, so it should route to invoice_metric.
    biggest_invoice = qa.answer_question(
        "what is the biggest invoice?", bundle=bundle, findings=findings
    )
    assert biggest_invoice["intent"] == "invoice_metric"

    # "issues" / "problems" should reach the findings intent.
    issues = qa.answer_question("what issues did you find?", bundle=bundle, findings=findings)
    assert issues["matched"] is True
    assert issues["intent"] == "findings"

    # Argument extraction must use the original question, not the expanded text:
    # a named-vendor lookup should still parse the real name and not be polluted
    # by injected canonical tokens.
    named = qa.answer_question(
        "how much did we pay Saudi Pharma Suppliers Co?", bundle=bundle, findings=findings
    )
    assert named["matched"] is True
    assert "Saudi Pharma Suppliers Co" in named["answer"]

    # A genuinely unrelated question still falls through to suggestions.
    no_match = qa.answer_question("what is the weather today?", bundle=bundle, findings=findings)
    assert no_match["matched"] is False
    assert no_match["suggestions"]


def test_bare_outstanding_question_does_not_hit_exception_path(qa_context):
    bundle, findings = qa_context

    # "outstanding" routes to the overdue intent via synonym expansion. A bare
    # phrasing with no AP/AR hint must compute (or return a clean _needs message)
    # and never fall into answer_question's generic exception handler, which would
    # surface a "handler '...' raised: ..." basis. Regression for the 4-vs-3 tuple
    # unpack in _handle_overdue.
    result = qa.answer_question("what is outstanding?", bundle=bundle, findings=findings)

    assert result["matched"] is True
    assert result["intent"] == "overdue"
    # available is a real True/False signal, not absent.
    assert result.get("available") in (True, False)
    # The basis must be a genuine computation, not the exception fallback.
    assert "raised:" not in str(result.get("basis"))
    assert result["answer"] != "I could not compute that from the current run."
    # On the default (AP) ledger the answer is computable, so it carries a value.
    assert result["available"] is True
    assert result["value"] is not None

    # Equivalent bare synonyms exercise the same handler and must also stay clean.
    for phrasing in ("what is unpaid?", "what do we owe?", "show me past due amounts"):
        r = qa.answer_question(phrasing, bundle=bundle, findings=findings)
        assert r["matched"] is True, phrasing
        assert r["intent"] == "overdue", phrasing
        assert "raised:" not in str(r.get("basis")), phrasing
