from pathlib import Path

from strategyos_mvp.source_finance_kpis import derive_source_finance_kpis
from strategyos_mvp.source_strategy_enrichment import derive_strategy_enrichment


DATASET = Path(
    "/Users/taras/Desktop/Taras/SPsoft/Enterprise OS/28.07.2026/01_Synthetic_Dataset-3"
)


def test_legion_enrichment_contract_is_data_derived() -> None:
    if not DATASET.exists():
        return
    payload = derive_strategy_enrichment(DATASET)
    assert payload["status"] == "ready"
    plan = payload["plan_health"]
    assert plan["commitment_count"] == 10
    assert plan["live_count"] == 7
    assert plan["estimated_count"] == 3
    assert len(payload["operational_actuals"]["kpi_ids"]) == 5
    assert payload["operational_actuals"]["row_count"] == 250
    assert len(payload["assistant_threads"]["threads"]) == 2
    assert all(len(thread["turns"]) == 8 for thread in payload["assistant_threads"]["threads"])
    factual_turns = [
        turn
        for thread in payload["assistant_threads"]["threads"]
        for turn in thread["turns"]
        if turn.get("evidence_ref") not in {None, "", "—"}
    ]
    assert factual_turns
    assert all(turn["evidence_refs"] for turn in factual_turns)
    assert all(
        (DATASET / reference["file"]).is_file()
        for turn in factual_turns
        for reference in turn["evidence_refs"]
    )
    assert len(payload["assistant_profiles"]) == 5
    assert len(payload["achievements"]) == 6
    assert len(payload["daily_pulse"]) == 38
    assert payload["question_bank"]["question_count"] == 500
    assert payload["question_bank"]["theme_count"] == 18
    assert payload["recovery_meter"]["identified_sar"] == 1_210_400
    assert payload["recovery_meter"]["recovered_sar"] == 247_194
    assert all(profile["evidence"]["file"].endswith("Assistant_Profiles.xlsx") for profile in payload["assistant_profiles"])
    assert payload["assistant_memory"]["record_id"] == "RD-01"
    assert "SAR 88,594" in payload["assistant_memory"]["text"]
    assert payload["assistant_memory"]["evidence"]["sheet"] == "Decision_Log"


def test_revenue_plan_health_uses_the_reconciled_h1_budget_comparator() -> None:
    if not DATASET.exists():
        return
    finance = derive_source_finance_kpis(DATASET)
    payload = derive_strategy_enrichment(DATASET, finance_kpi=finance)
    revenue = next(
        item
        for item in payload["plan_health"]["commitments"]
        if item["kpi_id"] == "KPI-01"
    )

    assert revenue["actual"] == 4006.0
    assert revenue["checkpoint"] == 3904.0
    assert revenue["score"] == 102.6
    assert revenue["comparator_evidence"]["files"] == [
        "15_Budgets_Forecasts/BU_Group_Budget_2026.xlsx"
    ]


def test_three_planted_drifts_surface_without_answer_key_labels() -> None:
    if not DATASET.exists():
        return
    payload = derive_strategy_enrichment(DATASET)
    plan_drifts = [
        item for item in payload["plan_health"]["commitments"]
        if str(item["status_vs_path"]).startswith("BEHIND")
    ]
    assert [item["kpi_id"] for item in plan_drifts] == ["KPI-09"]
    cost_of_drift = plan_drifts[0]["cost_of_drift"]
    assert cost_of_drift["gap"] == 1.8
    assert cost_of_drift["gap_unit"] == "percentage points"
    assert cost_of_drift["financial_effect_sar_per_week"] is None
    assert cost_of_drift["financial_effect_status"] == "not_supplied"
    assert "does not supply a defensible SAR-per-week conversion" in cost_of_drift["statement"]
    assert any(item["initiative_id"] == "INIT-10" for item in payload["initiative_drifts"])
    assert any(
        item["initiative_id"] == "INIT-07" and str(item["status"]).startswith("LATE")
        for item in payload["milestone_drifts"]
    )


def test_legion_decisions_carry_visible_session_statuses() -> None:
    if not DATASET.exists():
        return
    payload = derive_strategy_enrichment(DATASET)
    decisions = {item["key"]: item for item in payload["decision_seeds"]}
    assert decisions["apply-june-eur-hedge"]["status_labels"] == {
        "Approve": "Approved for the June payment run",
        "Decline": "Declined",
    }
    assert decisions["cold-chain-renegotiation-mandate"]["status_labels"] == {
        "Approve": "Memo approved",
        "Hold": "Held for further review",
    }
    assert all(
        (DATASET / reference["file"]).is_file()
        for decision in decisions.values()
        for reference in decision["evidence_refs"]
    )
