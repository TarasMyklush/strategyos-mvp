from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from strategyos_mvp.source_claims import ClaimDraft, ClaimRevision, ClaimAssessment, forecast_use_status

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def forecast():
    return ClaimRevision(revision_id="revision", revision_number=1, recorded_at=NOW,
        traceability="present", draft=ClaimDraft(tenant_id="tenant", assertion_namespace="cfo",
            subject_type="group", subject_key="group", metric_key="cash", claim_kind="forecast",
            production_method="human_entered", value_numeric=100, unit="SAR",currency="SAR",
            author_identity="CFO"))


def review(**kwargs):
    fields = dict(claim_revision_id="revision", assessment_type="forecast_review", result="accepted",
        rule_version="1", assessed_by="CEO", assessed_at=NOW, scope_key="scenario:base",
        valid_until=NOW+timedelta(days=7))
    fields.update(kwargs)
    return ClaimAssessment(**fields)


def test_acceptance_is_scoped_and_does_not_promote_the_claim():
    result = forecast_use_status(forecast(), assessments=[review()], scope_key="scenario:base",at=NOW)
    assert result["status"] == "accepted_for_scope"
    assert result["eligible_for_scoped_use"] and result["claim_kind"] == "forecast"
    assert not forecast_use_status(forecast(), assessments=[review()],scope_key="scenario:stretch",at=NOW)["eligible_for_scoped_use"]


@pytest.mark.parametrize("items,scope,at,expected", [
    ([],"scenario:base",NOW,"not_reviewed_for_scope"),
    ([review()],None,NOW,"scope_required"),
    ([review(valid_until=None)],"scenario:base",NOW,"review_date_not_supplied"),
    ([review()],"scenario:base",NOW+timedelta(days=7),"review_expired"),
    ([review(result="rejected")],"scenario:base",NOW,"rejected_for_scope"),
    ([review(),review(result="rejected")],"scenario:base",NOW,"conflicting_reviews"),
    ([review(assessed_at=NOW+timedelta(days=1))],"scenario:base",NOW,"not_reviewed_for_scope"),
    ([review(claim_revision_id="other")],"scenario:base",NOW,"not_reviewed_for_scope"),
])
def test_review_fails_closed(items,scope,at,expected):
    result = forecast_use_status(forecast(), assessments=items,scope_key=scope,at=at)
    assert result["status"] == expected and not result["eligible_for_scoped_use"]


def test_source_forecast_expiry_cannot_be_extended_by_acceptance():
    claim=forecast()
    claim=replace(claim,draft=replace(claim.draft,valid_until=NOW))
    assert forecast_use_status(claim,assessments=[review()],scope_key="scenario:base",at=NOW)["status"] == "forecast_expired"


def test_naive_or_backdated_review_expiry_is_rejected():
    for due in (NOW,NOW.replace(tzinfo=None)):
        with pytest.raises(ValueError,match="expiry"):
            review(valid_until=due)
