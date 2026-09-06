from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from strategyos_mvp.source_claims import (
    CaptureMethod,
    ClaimAssessment,
    ClaimDraft,
    ClaimKind,
    ClaimQuery,
    ClaimRevision,
    EvidenceOccurrence,
    OriginCategory,
    PolicyContext,
    ProductionMethod,
    SourceAccessPolicy,
    SourceRegistration,
    TraceabilityState,
    UsePurpose,
    claim_is_eligible,
    explicit_claim_kind,
    provenance_view,
)
from strategyos_mvp.source_pack import (
    _deterministic_source_pack_id,
    normalize_source_contract,
)


NOW = datetime(2026, 6, 7, 12, tzinfo=UTC)


def test_exact_query_period_cannot_mix_months_or_unknown_periods():
    from dataclasses import replace
    selected = query(period_start=date(2026,6,1),period_end=date(2026,6,30))
    def eligible(draft):
        return claim_is_eligible(revision(draft),query=selected,context=context(),source_policies=[policy()])
    assert eligible(actual_draft()).eligible
    assert 'period_mismatch' in eligible(actual_draft(period_start=date(2026,1,1))).reasons
    assert 'period_mismatch' in eligible(actual_draft(period_start=None,period_end=None)).reasons
    for fields in [{'period_start':date(2026,6,1)},
                   {'period_start':date(2026,6,30),'period_end':date(2026,6,1)},
                   {'period_start':NOW,'period_end':NOW}]:
        with pytest.raises(ValueError):
            query(**fields)
    strict = replace(selected,fiscal_calendar='group-fiscal-v1')
    assert 'fiscal_calendar_mismatch' in claim_is_eligible(revision(),query=strict,context=context(),source_policies=[policy()]).reasons


def actual_draft(**overrides):
    values = {
        "tenant_id": "tenant-1",
        "assertion_namespace": "erp-finance",
        "subject_type": "business_unit",
        "subject_key": "tamween",
        "metric_key": "revenue",
        "claim_kind": ClaimKind.ACTUAL,
        "production_method": ProductionMethod.IMPORTED,
        "value_numeric": Decimal("1179200000"),
        "unit": "SAR",
        "scale": 1,
        "currency": "SAR",
        "business_unit": "tamween",
        "period_start": date(2026, 6, 1),
        "period_end": date(2026, 6, 30),
        "as_of_at": NOW,
        "source_occurrence_keys": ("occurrence:1",),
    }
    values.update(overrides)
    return ClaimDraft(**values)


def revision(draft=None, **overrides):
    values = {
        "revision_id": "revision-1",
        "revision_number": 1,
        "recorded_at": NOW,
        "draft": draft or actual_draft(),
        "traceability": TraceabilityState.PRESENT,
    }
    values.update(overrides)
    return ClaimRevision(**values)


def policy(**overrides):
    values = {
        "source_key": "finance-erp",
        "storage_allowed": True,
        "index_allowed": True,
        "allowed_roles": frozenset({"executive", "analyst"}),
        "allowed_purposes": frozenset({UsePurpose.EXECUTIVE_BRIEFING, UsePurpose.ANALYSIS}),
        "allowed_business_units": frozenset({"tamween"}),
    }
    values.update(overrides)
    return SourceAccessPolicy(**values)


def context(**overrides):
    values = {
        "tenant_id": "tenant-1",
        "principal_id": "ceo-1",
        "roles": frozenset({"executive"}),
        "purpose": UsePurpose.EXECUTIVE_BRIEFING,
        "business_units": frozenset({"tamween"}),
    }
    values.update(overrides)
    return PolicyContext(**values)


def query(**overrides):
    values = {
        "tenant_id": "tenant-1",
        "metric_key": "revenue",
        "purpose": UsePurpose.EXECUTIVE_BRIEFING,
        "as_of_at": NOW + timedelta(hours=1),
        "allowed_claim_kinds": frozenset({ClaimKind.ACTUAL}),
        "business_unit": "tamween",
    }
    values.update(overrides)
    return ClaimQuery(**values)


def test_source_registration_keeps_origin_separate_from_capture_channel():
    source = SourceRegistration(
        tenant_id="tenant-1",
        source_key="licensed-research-via-email",
        display_name="Licensed research delivery",
        origin_category=OriginCategory.LICENSED_EXTERNAL,
        capture_method=CaptureMethod.EMAIL,
        provider_name="Provider",
        license_policy_ref="contract:provider-1",
    )
    assert source.origin_category is OriginCategory.LICENSED_EXTERNAL
    assert source.capture_method is CaptureMethod.EMAIL
    assert source.fingerprint == source.fingerprint


def test_identical_artifact_from_two_sources_has_distinct_occurrence_identity():
    digest = "a" * 64
    first = EvidenceOccurrence(
        tenant_id="tenant-1",
        source_key="public-web",
        artifact_hash=digest,
        source_native_id="article-42",
        received_at=NOW,
    )
    second = EvidenceOccurrence(
        tenant_id="tenant-1",
        source_key="licensed-feed",
        artifact_hash=digest,
        source_native_id="article-42",
        received_at=NOW,
    )
    assert first.occurrence_key != second.occurrence_key


def test_numeric_claim_requires_unit_and_forecast_requires_author():
    with pytest.raises(ValueError, match="explicit unit"):
        actual_draft(unit=None)
    with pytest.raises(ValueError, match="attributable author"):
        actual_draft(claim_kind="forecast", author_identity=None)
    with pytest.raises(ValueError, match="scale must be positive"):
        actual_draft(scale=0)
    assert actual_draft(currency="sar").currency == "SAR"


def test_missing_value_is_not_encoded_as_zero_or_empty_claim():
    with pytest.raises(ValueError, match="missing is not a claim value"):
        actual_draft(value_numeric=None, value_text=None)


def test_calculated_claim_requires_versioned_formula_and_input_revisions():
    with pytest.raises(ValueError, match="versioned formula"):
        actual_draft(production_method="calculated", source_occurrence_keys=())
    calculated = actual_draft(
        production_method="calculated",
        source_occurrence_keys=(),
        formula_key="margin",
        formula_version="2",
        input_revision_ids=("revenue-r1", "cost-r1"),
    )
    assert calculated.input_revision_ids == ("revenue-r1", "cost-r1")


def test_explicit_kind_mapping_never_guesses_from_ambiguous_actual_forecast_label():
    assert explicit_claim_kind("actual") is ClaimKind.ACTUAL
    assert explicit_claim_kind("approved plan") is ClaimKind.PLAN
    assert explicit_claim_kind("actual / forecast") is ClaimKind.UNKNOWN
    assert explicit_claim_kind("2026F") is ClaimKind.UNKNOWN


def test_actual_query_does_not_silently_accept_forecast():
    forecast = revision(
        actual_draft(claim_kind="forecast", author_identity="CFO", scenario_key=None)
    )
    result = claim_is_eligible(
        forecast,
        query=query(),
        context=context(),
        source_policies=[policy()],
    )
    assert result.eligible is False
    assert "claim_kind_not_requested" in result.reasons


def test_source_policy_enforces_role_purpose_bu_and_external_model_consent():
    result = claim_is_eligible(
        revision(),
        query=query(purpose=UsePurpose.EXTERNAL_MODEL),
        context=context(roles=frozenset({"contractor"}), purpose=UsePurpose.EXTERNAL_MODEL),
        source_policies=[policy(allowed_purposes=frozenset({UsePurpose.EXTERNAL_MODEL}))],
    )
    assert result.eligible is False
    assert "role_denied:finance-erp" in result.reasons
    assert "external_model_denied:finance-erp" in result.reasons


def test_source_policy_fingerprint_is_stable_and_permission_sensitive():
    assert policy().fingerprint == policy().fingerprint
    assert policy().fingerprint != policy(external_model_allowed=True).fingerprint


def test_source_without_current_access_policy_fails_closed():
    result = claim_is_eligible(
        revision(), query=query(), context=context(), source_policies=[]
    )
    assert result.eligible is False
    assert "source_policy_missing" in result.reasons


def test_stale_future_and_untraceable_claims_are_ineligible():
    stale = revision(
        actual_draft(valid_until=NOW - timedelta(seconds=1)),
        traceability=TraceabilityState.INCOMPLETE,
        recorded_at=NOW + timedelta(days=1),
    )
    result = claim_is_eligible(
        stale, query=query(), context=context(), source_policies=[policy()]
    )
    assert result.eligible is False
    assert {"stale", "not_known_at_query_time", "traceability_incomplete"}.issubset(result.reasons)


def test_retracted_claim_is_ineligible_and_assessment_is_not_self_reported_confidence():
    assessment = ClaimAssessment(
        claim_revision_id="revision-1",
        assessment_type="lifecycle",
        result="retracted",
        rule_version="review-policy-v1",
        assessed_by="reviewer:42",
        assessed_at=NOW,
        reasons=("Source withdrew the forecast.",),
    )
    result = claim_is_eligible(
        revision(),
        query=query(),
        context=context(),
        source_policies=[policy()],
        assessments=[assessment],
    )
    assert result.eligible is False
    assert "lifecycle:retracted" in result.reasons
    assert assessment.fingerprint.startswith("claim-assessment:")


def test_forecast_ui_view_preserves_author_period_scale_and_traceability():
    claim = revision(
        actual_draft(
            claim_kind="forecast",
            author_identity="CFO",
            value_numeric="120",
            scale="1000000",
            valid_until=NOW + timedelta(days=30),
        )
    )
    view = provenance_view(claim)
    assert view["label"] == "Forecast · CFO"
    assert view["value"] == "120"
    assert view["scale"] == "1000000"
    assert view["unit"] == "SAR"
    assert view["traceability"] == "present"


def test_claim_family_and_revision_fingerprints_are_stable_and_revision_sensitive():
    first = actual_draft()
    equivalent = actual_draft(dimensions={})
    changed = actual_draft(value_numeric="1179200001")
    assert first.family_key == equivalent.family_key == changed.family_key
    assert first.fingerprint == equivalent.fingerprint
    assert first.fingerprint != changed.fingerprint


def test_actual_plan_and_independent_sources_are_distinct_claim_families():
    actual = actual_draft()
    plan = actual_draft(claim_kind="plan")
    other_source = actual_draft(assertion_namespace="licensed-provider")
    assert actual.family_key != plan.family_key
    assert actual.family_key != other_source.family_key


def test_source_pack_origin_stays_unknown_until_operator_confirmation():
    contract = normalize_source_contract(
        source_pack_id="abc123",
        source_kind="workspace_path",
        contract=None,
    )
    assert contract["origin_category"] == "unknown"
    assert contract["capture_method"] == "folder_import"
    assert contract["classification_status"] == "unclassified"


def test_validation_preserves_original_capture_method():
    contract = normalize_source_contract(
        source_pack_id="abc123",
        source_kind="validated",
        contract={
            "source_key": "erp.finance",
            "display_name": "ERP finance",
            "origin_category": "internal_system",
            "capture_method": "folder_import",
            "governed_owner": "finance-data-owner",
            "authorization_basis": "Operator-confirmed source registry",
            "confirmed_by": "operator:1",
            "access_policy": {
                "allowed_roles": ["executive"],
                "allowed_purposes": ["executive_briefing"],
            },
        },
    )
    assert contract["capture_method"] == "folder_import"
    assert contract["classification_status"] == "confirmed"


def test_licensed_source_cannot_be_confirmed_without_license_policy():
    with pytest.raises(HTTPException, match="license-policy"):
        normalize_source_contract(
            source_pack_id="abc123",
            source_kind="browser_upload",
            contract={
                "source_key": "provider.research",
                "display_name": "Provider research",
                "origin_category": "licensed_external",
                "governed_owner": "strategy-data-owner",
                "authorization_basis": "Subscription",
                "provider_name": "Provider",
                "confirmed_by": "operator:1",
            },
        )


def test_identical_pack_bytes_from_distinct_sources_do_not_share_pack_identity():
    entries = [{"relative_path": "report.csv", "sha256": "a" * 64, "size_bytes": 42}]
    first = _deterministic_source_pack_id(entries, source_key="public-web")
    second = _deterministic_source_pack_id(entries, source_key="licensed-feed")
    assert first != second
