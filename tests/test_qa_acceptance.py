from strategyos_mvp.qa_acceptance import grade_answer, release_report

REFERENCE = {"expected_answer": "Revenue was SAR 2.4M.", "reviewed_by": "fixture reviewer",
             "required_patterns": [r"Revenue (?:was|is) SAR (?:2\.4M|2,400,000)"],
             "required_sources": ["ledger.csv"]}


def test_self_reported_success_does_not_pass_fabricated_answer():
    result = grade_answer(REFERENCE, {"answer": "Revenue was SAR 2.4M. Profit was SAR 999 trillion.",
        "matched": True, "determinism_tier": "governed_fact", "citations": [{"source_path": "ledger.csv"}]}, lambda _: True)
    assert not result["correct"] and result["fabricated_numbers"]


def test_wrong_metric_label_and_unresolved_citations_fail():
    for answer, resolved in [("Profit was SAR 2.4M.", True), ("Revenue was SAR 2.4M.", False)]:
        assert not grade_answer(REFERENCE, {"answer": answer, "citations": [{"source_path": "ledger.csv"}]}, lambda _: resolved)["correct"]


def test_reference_and_citations_required():
    assert not grade_answer({}, {"answer": "Yes", "matched": True}, lambda _: True)["correct"]
    assert grade_answer(REFERENCE, {"answer": "Revenue was SAR 2,400,000.", "citations": [{"source_path": "ledger.csv"}]}, lambda _: True)["correct"]


def test_gate_requires_50_distinct_questions_18_themes_and_no_fabrication():
    items = [{"id": str(i), "theme": str(i % 18), "grade": {"correct": i < 45}} for i in range(50)]
    assert release_report(items, release="commit", data_hash="sha256")["passed"]
    items[-1]["grade"]["fabricated_numbers"] = True
    assert not release_report(items, release="commit", data_hash="sha256")["passed"]
