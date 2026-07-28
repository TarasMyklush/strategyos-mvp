from pathlib import Path

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
    assert len(payload["assistant_profiles"]) == 5
    assert len(payload["achievements"]) == 6
    assert len(payload["daily_pulse"]) == 38
    assert payload["question_bank"]["question_count"] == 500
    assert payload["question_bank"]["theme_count"] == 18
    assert payload["recovery_meter"]["identified_sar"] == 1_210_400
    assert payload["recovery_meter"]["recovered_sar"] == 247_194


def test_three_planted_drifts_surface_without_answer_key_labels() -> None:
    if not DATASET.exists():
        return
    payload = derive_strategy_enrichment(DATASET)
    plan_drifts = [
        item for item in payload["plan_health"]["commitments"]
        if str(item["status_vs_path"]).startswith("BEHIND")
    ]
    assert [item["kpi_id"] for item in plan_drifts] == ["KPI-09"]
    assert any(item["initiative_id"] == "INIT-10" for item in payload["initiative_drifts"])
    assert any(
        item["initiative_id"] == "INIT-07" and str(item["status"]).startswith("LATE")
        for item in payload["milestone_drifts"]
    )
