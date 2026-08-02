from __future__ import annotations

from strategyos_mvp.executive_display import (
    executive_display_text,
    executive_source_label,
    executive_text_has_internal_leak,
    sanitize_executive_payload,
)


def test_answer_key_and_internal_workflow_language_never_reaches_executive_copy() -> None:
    raw = (
        "PLANTED DRIFT — payer lag (Pattern 7). The source pack was "
        "server-resolved from the current governed run."
    )
    visible = executive_display_text(raw)

    assert visible == (
        "Payer lag. The connected business records were verified from the "
        "current verified review."
    )
    assert executive_text_has_internal_leak(visible) is False


def test_source_paths_receive_stable_business_labels_without_losing_audit_reference() -> None:
    source_path = "08_Invoices/Invoice_Servier_INV-2026-0577.pdf"
    payload = sanitize_executive_payload(
        {"citations": [{"source_path": source_path, "locator": "invoice total"}]}
    )

    citation = payload["citations"][0]
    assert citation["source_path"] == source_path
    assert citation["source_label"] == "Servier invoice INV-2026-0577"


def test_paths_embedded_in_prose_are_humanized_at_the_boundary() -> None:
    visible = executive_display_text(
        "Review 15_Budgets_Forecasts/BU_Group_Budget_2026.xlsx before the call."
    )

    assert "15_Budgets_Forecasts" not in visible
    assert ".xlsx" not in visible
    assert "Division budget" in visible


def test_source_display_label_is_generic_for_new_dataset_files() -> None:
    assert executive_source_label("24_Executive_Policy/Materiality_Thresholds.xlsx") == (
        "Materiality Thresholds · Executive policy"
    )


def test_folder_only_tokens_are_humanized_in_executive_copy() -> None:
    visible = executive_display_text(
        "Missing connections: 20_Board_KPIs, 17_Signals, Inventory_Movements."
    )

    assert visible == (
        "Missing connections: Board KPI records, Business signals, Inventory movements."
    )
    assert executive_text_has_internal_leak(visible) is False


def test_business_unit_note_hides_internal_budget_folder() -> None:
    visible = executive_display_text(
        "Revenue ahead; margin behind — division bridge in 15_Budgets_Forecasts"
    )

    assert visible == "Revenue ahead; margin behind — division bridge in Division budget"
    assert executive_text_has_internal_leak(visible) is False
