from copy import deepcopy
import pytest

from strategyos_mvp.strategy_compiler import compile_strategy


def plan(company):
    return {"plan_id": f"{company}-plan", "company_id": company, "version": 1, "title": "Reviewed strategy",
        "commitments": [{"id": "growth", "title": "Service adoption", "driver": "Growth", "owner": "Business owner",
            "approver": "Board", "unit": "%", "cadence": "quarterly", "direction": "higher_is_better",
            "weight": 2, "tolerance": 1, "target": 50, "formula": "ratio", "bindings": ["active", "eligible"],
            "source": {"path": "strategy.pdf", "locator": "page 3", "sha256": "a" * 64}}]}


def test_second_company_compiles_without_client_code_and_requires_approval():
    for company in ("company-a", "company-b"):
        result = compile_strategy(plan(company), available_bindings={"active", "eligible"})
        assert result["company_id"] == company
        assert result["readiness"] == "needs_ratification"
        assert result["changed_commitments"] == ["growth"]


def test_recompile_identifies_changed_targets_and_missing_fields():
    first = plan("company-a")
    changed = deepcopy(first)
    changed["version"] = 2
    changed["commitments"][0]["target"] = 60
    result = compile_strategy(changed, available_bindings={"active"}, previous=first)
    assert result["missing_bindings"] == ["eligible"]
    assert result["changed_commitments"] == ["growth"]
    assert result["downstream_invalidations"][0]["surfaces"] == ["diagnostics", "briefing", "drift"]


def test_unapproved_ratification_arbitrary_code_and_nan_rejected():
    for field, value in (("formula", "eval(source)"), ("weight", 0), ("target", float("nan"))):
        raw = plan("company-a")
        raw["commitments"][0][field] = value
        with pytest.raises(ValueError):
            compile_strategy(raw, available_bindings=set())
    raw = plan("company-a")
    raw["status"] = "ratified"
    with pytest.raises(ValueError, match="Ratification requires"):
        compile_strategy(raw, available_bindings=set())
