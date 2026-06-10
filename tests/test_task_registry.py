from strategyos_mvp.tasks import (
    evaluate_task_readiness_items,
    registered_task_specs,
)


def test_task_registry_exposes_default_tasks_in_readiness_order():
    assert [spec.task_key for spec in registered_task_specs()] == [
        "cash_leakage_discovery",
        "working_capital_drift_check",
        "drill_down_qa",
    ]


def test_task_readiness_items_preserve_current_partial_run_semantics():
    available_roles = {"ap_ledger"}
    items = evaluate_task_readiness_items(
        has_role=lambda role: role in available_roles,
        run_ready=False,
    )
    by_key = {item["task_key"]: item for item in items}

    assert by_key["cash_leakage_discovery"]["status"] == "partial"
    assert by_key["working_capital_drift_check"]["status"] == "blocked"
    assert by_key["drill_down_qa"]["status"] == "blocked"
    assert "classified vendor master coverage" in by_key["cash_leakage_discovery"]["missing"]
    assert "current run-model normalization coverage" in by_key["drill_down_qa"]["missing"]
