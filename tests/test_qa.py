from pathlib import Path

import pytest

from strategyos_mvp import qa
from strategyos_mvp.ingestion import load_dataset
from strategyos_mvp.skills.finance_controls import run_all_finance_skills


DATASET_ROOT = (
    Path(__file__).resolve().parents[2]
    / "strategy os"
    / "StrategyOS POC"
    / "01_Synthetic_Dataset"
)


@pytest.fixture(scope="module")
def qa_context():
    bundle = load_dataset(DATASET_ROOT)
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
    assert top_vendors["value"][0]["name"] == "Saudi Trading Co"


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
