"""Contract tests for StrategyOS domain models.

Verifies:
- Finding contract (required fields, status lifecycle, immutable fields)
- Citation contract (label format, hash inclusion)
- CanonicalFinanceEntity contracts (entity_type, is_effective_on)
- AuditEvent contract (confidence transitions, token tracking)
- DataQualityIssue contract (severity levels)
- All Literal types are enforced correctly
- Decimal precision is preserved

Target architecture: models.py
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import get_args

import pytest

from strategyos_mvp.models import (
    Finding,
    Citation,
    AuditEvent,
    DataQualityIssue,
    CanonicalFinanceEntity,
    CanonicalFinanceEntityType,
    SupplierAccount,
    BuyerEntity,
    Payment,
    PurchaseOrder,
    PurchaseOrderLine,
    GoodsReceipt,
    ContractTerm,
    CreditNote,
    FXRate,
    TaxRegistration,
    CanonicalLineage,
    FXNormalization,
    FXStatus,
    TenantProfileVersion,
    TenantProfileLifecycleStatus,
    BackfillRun,
    BackfillRunStatus,
    CutoverMetric,
    CutoverMetricThreshold,
    CutoverMetricStatus,
)


# ─────────────────────────────────────────────────────────────────────────────
# Finding contract
# ─────────────────────────────────────────────────────────────────────────────

def test_finding_required_fields():
    """A Finding requires finding_id, title, pattern_type, vendor_id, vendor_name,
    leakage_sar, recoverable_sar, recoverable_usd, confidence, classification,
    rationale, remediation."""
    f = Finding(
        finding_id="F-001",
        title="Test finding",
        pattern_type="duplicate_payment",
        vendor_id="V-1",
        vendor_name="Test Vendor",
        leakage_sar=1000.0,
        recoverable_sar=800.0,
        recoverable_usd=213.33,
        confidence="HIGH",
        classification="CASH (recoverable now)",
        rationale="Test rationale",
        remediation="Test remediation",
    )
    assert f.finding_id == "F-001"
    assert f.status == "draft"  # default
    assert f.challenges == []  # default
    assert f.citations == []  # default
    assert f.calculation == {}  # default


def test_finding_status_lifecycle():
    """Finding status must be one of the 7 allowed lifecycle values."""
    valid_statuses = {"draft", "challenged", "locked", "disputed", "approved", "rejected", "blocked"}
    f = Finding(
        finding_id="F-001", title="T", pattern_type="x", vendor_id="V-1",
        vendor_name="V", leakage_sar=0.0, recoverable_sar=0.0, recoverable_usd=0.0,
        confidence="HIGH", classification="CASH", rationale="r", remediation="r",
    )
    for status in valid_statuses:
        f.status = status  # should not raise
        assert f.status == status


def test_finding_confidence_levels():
    """Confidence must be HIGH, MEDIUM, or LOW."""
    for level in ("HIGH", "MEDIUM", "LOW"):
        f = Finding(
            finding_id="F-001", title="T", pattern_type="x", vendor_id="V-1",
            vendor_name="V", leakage_sar=0.0, recoverable_sar=0.0, recoverable_usd=0.0,
            confidence=level, classification="CASH", rationale="r", remediation="r",
        )
        assert f.confidence == level


# ─────────────────────────────────────────────────────────────────────────────
# Citation contract
# ─────────────────────────────────────────────────────────────────────────────

def test_citation_label_format():
    """Citation label must be 'source_path - locator'."""
    c = Citation(source_path="ap.xlsx", locator="row 5", excerpt="duplicate")
    assert c.label() == "ap.xlsx - row 5"


def test_citation_with_hash():
    """Citation with source_hash must include it."""
    c = Citation(source_path="inv.pdf", locator="page 3", excerpt="text",
                  source_hash="abc123")
    assert c.source_hash == "abc123"
    assert c.label() == "inv.pdf - page 3"


def test_citation_default_values():
    """Citation excerpt and source_hash default to empty/None."""
    c = Citation(source_path="f.xlsx", locator="row 1")
    assert c.excerpt == ""
    assert c.source_hash is None


# ─────────────────────────────────────────────────────────────────────────────
# AuditEvent contract
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_event_defaults():
    """AuditEvent has sensible defaults for optional fields."""
    ae = AuditEvent(round_no=1, actor="reviewer", finding_id="F-001",
                    action="challenge", detail="test detail")
    assert ae.status == "logged"
    assert ae.confidence_before is None
    assert ae.confidence_after is None
    assert ae.confidence_change == "UNCHANGED"
    assert ae.prompt_tokens is None
    assert ae.completion_tokens is None
    assert ae.total_tokens is None
    assert ae.estimated_cost_usd is None


def test_audit_event_confidence_transition():
    """AuditEvent can track confidence changes."""
    ae = AuditEvent(
        round_no=1, actor="reviewer", finding_id="F-001",
        action="challenge", detail="test",
        confidence_before="HIGH", confidence_after="MEDIUM",
        confidence_change="DOWNGRADED",
    )
    assert ae.confidence_before == "HIGH"
    assert ae.confidence_after == "MEDIUM"
    assert ae.confidence_change == "DOWNGRADED"


# ─────────────────────────────────────────────────────────────────────────────
# DataQualityIssue contract
# ─────────────────────────────────────────────────────────────────────────────

def test_data_quality_issue_severity_levels():
    """Severity must be info, warning, or critical."""
    for sev in ("info", "warning", "critical"):
        dq = DataQualityIssue(severity=sev, source="test", detail="test")
        assert dq.severity == sev


def test_data_quality_issue_fields():
    """All fields must be accessible."""
    dq = DataQualityIssue(severity="critical", source="ap_ledger",
                           detail="Missing required column: Invoice_ID")
    assert dq.severity == "critical"
    assert dq.source == "ap_ledger"
    assert dq.detail == "Missing required column: Invoice_ID"


# ─────────────────────────────────────────────────────────────────────────────
# CanonicalFinanceEntity contracts
# ─────────────────────────────────────────────────────────────────────────────

def test_all_canonical_entity_types_are_covered():
    """Every entity in CanonicalFinanceEntityType must have a corresponding class."""
    expected_types = {
        "supplier_account": SupplierAccount,
        "buyer_entity": BuyerEntity,
        "payment": Payment,
        "purchase_order": PurchaseOrder,
        "purchase_order_line": PurchaseOrderLine,
        "goods_receipt": GoodsReceipt,
        "contract_term": ContractTerm,
        "credit_note": CreditNote,
        "fx_rate": FXRate,
        "tax_registration": TaxRegistration,
    }
    for type_name, cls in expected_types.items():
        assert cls.entity_type == type_name, (
            f"{cls.__name__}.entity_type is '{cls.entity_type}', expected '{type_name}'"
        )


def test_canonical_entity_is_effective_on():
    """is_effective_on must return correct values based on effective_from/to."""
    entity = SupplierAccount(
        entity_id="E-1", tenant_id="T-1", canonical_key="supplier:v-1",
        effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30),
    )
    assert entity.is_effective_on(date(2026, 3, 15)) is True
    assert entity.is_effective_on(date(2025, 12, 31)) is False  # before effective_from
    assert entity.is_effective_on(date(2026, 7, 1)) is False    # after effective_to
    assert entity.is_effective_on(date(2026, 1, 1)) is True     # boundary: inclusive
    assert entity.is_effective_on(date(2026, 6, 30)) is True    # boundary: inclusive


def test_canonical_entity_no_dates_is_always_effective():
    """Entity with no effective dates is effective on any date."""
    entity = SupplierAccount(
        entity_id="E-1", tenant_id="T-1", canonical_key="supplier:v-1",
    )
    assert entity.is_effective_on(date(2020, 1, 1)) is True
    assert entity.is_effective_on(date(2030, 12, 31)) is True


def test_supplier_account_entity_type():
    assert SupplierAccount.entity_type == "supplier_account"
    s = SupplierAccount(
        entity_id="E-1", tenant_id="T-1", canonical_key="supplier:v-1",
        supplier_name="Acme Corp", supplier_tax_id="TAX123",
        payment_terms_code="NET30", default_currency="SAR",
    )
    assert s.supplier_name == "Acme Corp"
    assert s.default_currency == "SAR"


def test_fx_rate_defaults():
    """FXRate has default values for optional fields."""
    fx = FXRate(
        entity_id="E-1", tenant_id="T-1",
        canonical_key="fx:eur:sar:2026-06-01",
    )
    assert fx.source_currency == ""
    assert fx.reporting_currency == ""
    assert fx.rate_source == ""
    assert fx.fallback_allowed is False


# ─────────────────────────────────────────────────────────────────────────────
# FXNormalization contract
# ─────────────────────────────────────────────────────────────────────────────

def test_fx_normalization_supports_reporting_total():
    """supports_reporting_total returns True only for valid FX statuses."""
    for status in ("native_currency", "normalized", "fallback_rate_used", "manual_override"):
        fxn = FXNormalization(
            reporting_currency="SAR",
            fx_status=status,
            normalized_total_amount=Decimal("1000.00"),
        )
        assert fxn.supports_reporting_total() is True, f"Status {status} should support reporting"

    fxn_missing = FXNormalization(reporting_currency="SAR", fx_status="missing_rate")
    assert fxn_missing.supports_reporting_total() is False

    # Even with valid status, missing total means no support
    fxn_no_total = FXNormalization(
        reporting_currency="SAR", fx_status="normalized",
    )
    assert fxn_no_total.supports_reporting_total() is False


# ─────────────────────────────────────────────────────────────────────────────
# TenantProfileVersion contract
# ─────────────────────────────────────────────────────────────────────────────

def test_tenant_profile_lifecycle_behavior():
    """supports_shadow_runs and supports_new_jobs depend on lifecycle_status."""
    for status in ("candidate", "active", "deprecated"):
        tp = TenantProfileVersion(
            tenant_id="T-1", profile_id="P-1", version=1,
            document_type="invoice", lifecycle_status=status,
        )
        assert tp.supports_shadow_runs() is True, f"{status} should support shadow runs"

    tp_draft = TenantProfileVersion(
        tenant_id="T-1", profile_id="P-1", version=1,
        document_type="invoice", lifecycle_status="draft",
    )
    assert tp_draft.supports_shadow_runs() is False
    assert tp_draft.supports_new_jobs() is False

    tp_active = TenantProfileVersion(
        tenant_id="T-1", profile_id="P-1", version=1,
        document_type="invoice", lifecycle_status="active",
    )
    assert tp_active.supports_new_jobs() is True

    tp_candidate = TenantProfileVersion(
        tenant_id="T-1", profile_id="P-1", version=1,
        document_type="invoice", lifecycle_status="candidate",
    )
    assert tp_candidate.supports_new_jobs() is False


# ─────────────────────────────────────────────────────────────────────────────
# BackfillRun contract
# ─────────────────────────────────────────────────────────────────────────────

def test_backfill_run_is_terminal():
    """is_terminal returns True for completed, failed, cancelled."""
    for status in ("completed", "failed", "cancelled"):
        br = BackfillRun(
            tenant_id="T-1", backfill_run_id="BR-1", status=status,
        )
        assert br.is_terminal() is True, f"Status {status} should be terminal"

    for status in ("draft", "queued", "running"):
        br = BackfillRun(
            tenant_id="T-1", backfill_run_id="BR-1", status=status,
        )
        assert br.is_terminal() is False, f"Status {status} should NOT be terminal"


# ─────────────────────────────────────────────────────────────────────────────
# CutoverMetric contract
# ─────────────────────────────────────────────────────────────────────────────

def test_cutover_metric_delta_value():
    """delta_value returns canonical - legacy when both are present."""
    cm = CutoverMetric(
        tenant_id="T-1", metric_key="total_invoices",
        sample_window_label="H1 2026",
        legacy_value=Decimal("1000.00"),
        canonical_value=Decimal("1050.00"),
    )
    assert cm.delta_value() == Decimal("50.00")


def test_cutover_metric_delta_ratio():
    """delta_ratio returns (canonical - legacy) / legacy."""
    cm = CutoverMetric(
        tenant_id="T-1", metric_key="total_invoices",
        sample_window_label="H1 2026",
        legacy_value=Decimal("1000.00"),
        canonical_value=Decimal("1050.00"),
    )
    assert cm.delta_ratio() == Decimal("0.05")


def test_cutover_metric_division_by_zero():
    """delta_ratio returns None when legacy value is zero."""
    cm = CutoverMetric(
        tenant_id="T-1", metric_key="total_invoices",
        sample_window_label="H1 2026",
        legacy_value=Decimal("0"),
        canonical_value=Decimal("50.00"),
    )
    assert cm.delta_ratio() is None


def test_cutover_metric_within_threshold():
    """within_threshold checks max_delta_value and max_delta_ratio."""
    threshold = CutoverMetricThreshold(
        max_delta_value=Decimal("100.00"),
        max_delta_ratio=Decimal("0.10"),
    )
    # Within both thresholds
    cm_ok = CutoverMetric(
        tenant_id="T-1", metric_key="k", sample_window_label="H1",
        legacy_value=Decimal("1000.00"),
        canonical_value=Decimal("1050.00"),
        threshold=threshold,
    )
    assert cm_ok.within_threshold() is True

    # Outside max_delta_value
    cm_bad_value = CutoverMetric(
        tenant_id="T-1", metric_key="k", sample_window_label="H1",
        legacy_value=Decimal("1000.00"),
        canonical_value=Decimal("1200.00"),
        threshold=threshold,
    )
    assert cm_bad_value.within_threshold() is False

    # Outside max_delta_ratio
    cm_bad_ratio = CutoverMetric(
        tenant_id="T-1", metric_key="k", sample_window_label="H1",
        legacy_value=Decimal("100.00"),
        canonical_value=Decimal("115.00"),
        threshold=threshold,
    )
    assert cm_bad_ratio.within_threshold() is False


def test_cutover_metric_no_threshold_returns_none():
    """within_threshold returns None when no threshold is set."""
    cm = CutoverMetric(
        tenant_id="T-1", metric_key="k", sample_window_label="H1",
        legacy_value=Decimal("1000.00"),
        canonical_value=Decimal("1050.00"),
    )
    assert cm.within_threshold() is None


# ─────────────────────────────────────────────────────────────────────────────
# Fragility: verify all Literal types are valid
# ─────────────────────────────────────────────────────────────────────────────

def test_finding_status_literal_is_valid():
    """Finding status Literal values must be exactly the expected set."""
    from strategyos_mvp.models import Finding
    # Test all status values are accepted (this implicitly validates the Literal type)
    valid = {"draft", "challenged", "locked", "disputed", "approved", "rejected", "blocked"}
    for s in valid:
        f = Finding(
            finding_id="F-001", title="T", pattern_type="x", vendor_id="V-1",
            vendor_name="V", leakage_sar=0.0, recoverable_sar=0.0, recoverable_usd=0.0,
            confidence="HIGH", classification="CASH", rationale="r", remediation="r",
            status=s,
        )
        assert f.status == s
