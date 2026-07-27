import json

from strategyos_mvp.qa_regression_corpus import load_ceo_questions, run_ceo_question_corpus


def test_question_corpus_loader_and_contract_scoring(tmp_path):
    path = tmp_path / "questions.json"
    path.write_text(json.dumps({"questions": [{"id": "q1", "question": "What moved revenue?"}]}))

    questions = load_ceo_questions(path)
    report = run_ceo_question_corpus(
        questions,
        lambda question: {
            "matched": True,
            "answer": f"Answered: {question}",
            "determinism_tier": "derived_insight",
        },
    )

    assert questions == [{"id": "q1", "question": "What moved revenue?"}]
    assert report["question_count"] == 1
    assert report["answered_count"] == 1
    assert report["tiered_count"] == 1
    assert report["derivability_violation_count"] == 0


def test_question_corpus_loader_accepts_delivered_workbook_headers(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "CEO_Questions.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["#", "Theme", "Question", "Answer type"])
    sheet.append([1, "Revenue", "What moved revenue?", "Driver analysis"])
    workbook.save(path)

    questions = load_ceo_questions(path)

    assert questions[0]["id"] == "1"
    assert questions[0]["question"] == "What moved revenue?"
    assert questions[0]["Theme"] == "Revenue"
