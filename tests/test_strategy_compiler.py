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


def test_two_company_formulas_are_evaluated_without_client_specific_code():
    from strategyos_mvp.strategy_compiler import evaluate_strategy
    from decimal import Decimal
    for company, actual, expected in [('company-a', 21, 42), ('company-b', 0, 0)]:
        compiled=compile_strategy(plan(company),available_bindings={'active','eligible'})
        result=evaluate_strategy(compiled,{'active':actual,'eligible':50})
        assert result['measurements'][0]['actual']==expected
        assert result['approval_status']=='proposed'
    result=evaluate_strategy(compiled,{'active':0,'eligible':0})
    assert result['measurements'][0]['actual'] is None
    assert 'denominator' in result['measurements'][0]['reason']
    result=evaluate_strategy(compiled,{'active':0})
    assert result['measurements'][0]['missing_inputs']==['eligible']
    result=evaluate_strategy(compiled,{'active':float('inf'),'eligible':50})
    assert result['measurements'][0]['actual'] is None


def test_sum_and_variance_preserve_signed_values_and_source_actual_arity():
    from strategyos_mvp.strategy_compiler import evaluate_strategy
    raw=plan('company-b');raw['commitments'][0].update(formula='variance',unit='SAR')
    compiled=compile_strategy(raw,available_bindings={'active','eligible'})
    assert evaluate_strategy(compiled,{'active':0,'eligible':50})['measurements'][0]['actual']==-50
    raw['commitments'][0]['formula']='source_actual'
    with pytest.raises(ValueError,match='exactly 1'):
        compile_strategy(raw,available_bindings={'active','eligible'})
