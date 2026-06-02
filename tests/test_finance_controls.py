from pathlib import Path

from strategyos_mvp.ingestion import load_dataset
from strategyos_mvp.paths import SOURCE_DATASET
from strategyos_mvp.skills.finance_controls import run_all_finance_skills


def test_finance_skills_find_core_patterns():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    pattern_types = {f.pattern_type for f in findings}
    assert "duplicate_payment" in pattern_types
    assert "entity_resolution_duplicate" in pattern_types
    assert "off_contract_single_approver" in pattern_types
    assert "price_variance" in pattern_types
    assert "missed_early_pay_discount" in pattern_types
    assert "auto_renewal_escalation" in pattern_types
    assert "fx_hedge_unapplied" in pattern_types
    assert "dormant_credit_balance" in pattern_types


def test_findings_have_minimum_shape():
    bundle = load_dataset(SOURCE_DATASET)
    findings = run_all_finance_skills(bundle)
    assert len(findings) >= 8
    assert all(f.vendor_id for f in findings)
    assert all(f.title for f in findings)
    assert sum(f.recoverable_sar for f in findings) > 600_000

