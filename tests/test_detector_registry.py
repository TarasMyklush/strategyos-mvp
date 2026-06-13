from types import SimpleNamespace

import pytest

from strategyos_mvp.models import Finding
import strategyos_mvp.skills.finance_controls as finance_controls_module
from strategyos_mvp.skills.finance_controls import DetectorMetadata, detector_registry, run_all_finance_skills


def _finding(pattern_type: str, recoverable_sar: float, leakage_sar: float) -> Finding:
    return Finding(
        finding_id="draft",
        title=f"{pattern_type} finding",
        pattern_type=pattern_type,
        vendor_id="V-1",
        vendor_name="Vendor",
        leakage_sar=leakage_sar,
        recoverable_sar=recoverable_sar,
        recoverable_usd=0.0,
        confidence="HIGH",
        classification="CASH",
        rationale="test",
        remediation="test",
    )


def test_detector_registry_exposes_current_detectors_with_required_roles():
    registry = detector_registry()

    assert [item.name for item in registry] == [
        "detect_duplicate_payments",
        "detect_entity_resolution_duplicates",
        "detect_off_contract_single_approver",
        "detect_price_variance",
        "detect_missed_early_pay_discounts",
        "detect_auto_renewal_escalation",
        "detect_fx_hedge_unapplied",
        "detect_dormant_credit_balance",
    ]
    assert {item.pattern_type for item in registry} == finance_controls_module.KNOWN_PATTERN_TYPES
    assert {item.name: item.required_roles for item in registry} == {
        "detect_duplicate_payments": ("ap_ledger",),
        "detect_entity_resolution_duplicates": ("ap_ledger", "vendor_master"),
        "detect_off_contract_single_approver": ("ap_ledger", "vendor_master"),
        "detect_price_variance": ("ap_ledger", "purchase_orders"),
        "detect_missed_early_pay_discounts": ("ap_ledger",),
        "detect_auto_renewal_escalation": ("ap_ledger",),
        "detect_fx_hedge_unapplied": ("ap_ledger", "cash_forecast"),
        "detect_dormant_credit_balance": ("ap_ledger", "gl_extract"),
    }


def test_register_detector_rejects_duplicate_pattern_type():
    with pytest.raises(ValueError, match="Pattern type 'duplicate_payment' is already registered"):
        @finance_controls_module.register_detector("duplicate_payment", ("ap_ledger",))
        def duplicate_pattern_detector(bundle):
            return []


def test_run_all_finance_skills_uses_registry_order_and_preserves_ranked_reid(monkeypatch):
    execution_order: list[str] = []

    def first(bundle):
        execution_order.append("first")
        return [_finding("pattern_b", recoverable_sar=10.0, leakage_sar=3.0)]

    def second(bundle):
        execution_order.append("second")
        return [_finding("pattern_a", recoverable_sar=100.0, leakage_sar=1.0)]

    def skipped(bundle):
        execution_order.append("skipped")
        return [_finding("pattern_skip", recoverable_sar=1.0, leakage_sar=1.0)]

    monkeypatch.setattr(
        finance_controls_module,
        "DETECTOR_REGISTRY",
        [
            DetectorMetadata("first", "pattern_b", ("ap_ledger",), first),
            DetectorMetadata("second", "pattern_a", ("ap_ledger",), second),
            DetectorMetadata("skipped", "pattern_skip", ("vendor_master",), skipped),
        ],
    )
    monkeypatch.setattr(finance_controls_module, "KNOWN_PATTERN_TYPES", frozenset({"pattern_a", "pattern_b", "pattern_skip"}))
    # Isolate the row registry under test: empty the separate graph-detector
    # registry so its skip entries don't leak into this report assertion.
    monkeypatch.setattr("strategyos_mvp.skills.graph_controls.GRAPH_DETECTOR_REGISTRY", [])

    bundle = SimpleNamespace(run_metadata={"available_roles": ["ap_ledger"]})

    findings = run_all_finance_skills(bundle)

    assert execution_order == ["first", "second"]
    assert [finding.pattern_type for finding in findings] == ["pattern_a", "pattern_b"]
    assert [finding.finding_id for finding in findings] == ["F-001", "F-002"]
    assert bundle.detector_report == {
        "executed_detectors": [
            {
                "detector": "first",
                "pattern_type": "pattern_b",
                "required_roles": ["ap_ledger"],
                "finding_count": 1,
            },
            {
                "detector": "second",
                "pattern_type": "pattern_a",
                "required_roles": ["ap_ledger"],
                "finding_count": 1,
            },
        ],
        "skipped_detectors": [
            {
                "detector": "skipped",
                "pattern_type": "pattern_skip",
                "required_roles": ["vendor_master"],
                "missing_roles": ["vendor_master"],
                "reason": "Source pack did not provide all required structured roles for this detector.",
            }
        ],
    }
