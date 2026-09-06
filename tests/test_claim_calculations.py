from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from strategyos_mvp.claim_calculations import validate_calculation
from strategyos_mvp.source_claims import ClaimDraft, ClaimRevision, display_label


def inputs():
    common = dict(tenant_id="tenant", claim_kind="actual", unit="SAR", currency="SAR",
        scale="1", subject_type="enterprise", subject_key="group", business_unit=None,
        period_start=date(2026, 1, 1), period_end=date(2026, 6, 30), scenario_key=None)
    return [{**common, "id": "e", "metric_key": "ceo.ebitda", "value_numeric": "20"},
            {**common, "id": "r", "metric_key": "ceo.revenue", "value_numeric": "100"}]


def margin():
    return ClaimDraft(tenant_id="tenant", assertion_namespace="test", subject_type="enterprise",
        subject_key="group", metric_key="ceo.ebitda_margin", claim_kind="actual",
        production_method="calculated", value_numeric="20", unit="percent",
        period_start=date(2026, 1, 1), period_end=date(2026, 6, 30),
        formula_key="ebitda-divided-by-revenue", formula_version="1", input_revision_ids=("e", "r"))


def test_margin_uses_metric_roles_not_database_row_order():
    validate_calculation(margin(), list(reversed(inputs())))


def test_ratio_precision_is_explicit_and_accepts_historical_float_representation_only_at_that_precision():
    from strategyos_mvp.claim_calculations import margin_percent
    rows = inputs()
    rows[0]["value_numeric"] = "215741310.56"
    rows[1]["value_numeric"] = "385079908.90"
    exact = margin_percent(Decimal(rows[0]["value_numeric"]), Decimal(rows[1]["value_numeric"]))
    validate_calculation(replace(margin(), value_numeric=exact), rows)
    historical = Decimal(str(float(rows[0]["value_numeric"]) / float(rows[1]["value_numeric"]) * 100))
    validate_calculation(replace(margin(), value_numeric=historical), rows)
    with pytest.raises(ValueError, match="does not match"):
        validate_calculation(replace(margin(), value_numeric=exact + Decimal("0.000000001")), rows)


@pytest.mark.parametrize("change", [
    {"value_numeric": Decimal("19.5")}, {"unit": "percentage_points"}, {"currency": "SAR"},
    {"formula_version": "2"}, {"formula_key": "model_says_so"},
    {"period_start": None, "period_end": None}, {"business_unit": "other"},
    {"input_revision_ids": ("e", "e")},
])
def test_bad_outputs_never_become_calculated_facts(change):
    with pytest.raises(ValueError):
        validate_calculation(replace(margin(), **change), inputs())


@pytest.mark.parametrize("change", [
    {"tenant_id": "other"}, {"claim_kind": "forecast"},
    {"currency": "USD", "unit": "USD"}, {"period_end": date(2026, 12, 31)},
    {"unit": "percent"}, {"value_numeric": None}, {"scale": "0"},
    {"value_numeric": "NaN"}, {"business_unit": "other"}, {"scenario_key": "optimistic"},
])
def test_input_semantics_cannot_be_laundered(change):
    rows = inputs()
    rows[0].update(change)
    with pytest.raises(ValueError):
        validate_calculation(margin(), rows)


def test_zero_revenue_does_not_create_zero_margin():
    rows = inputs()
    rows[1]["value_numeric"] = "0"
    with pytest.raises(ValueError, match="zero"):
        validate_calculation(replace(margin(), value_numeric=Decimal(0)), rows)


def test_scale_normalization_and_identity_preserve_original_semantics():
    row = {**inputs()[1], "value_numeric": "1.25", "scale": "1000000"}
    draft = replace(margin(), metric_key="ceo.revenue", unit="SAR", currency="SAR",
        formula_key="identity", input_revision_ids=("r",), value_numeric=Decimal("1250000"))
    validate_calculation(draft, [row])


def test_ratio_summing_and_cash_summing_across_periods_are_rejected():
    rows = inputs()
    draft = replace(margin(), formula_key="sum", value_numeric=Decimal("120"))
    for row in rows:
        row.update(unit="percent", currency=None)
    with pytest.raises(ValueError, match="ratios"):
        validate_calculation(draft, rows)
    rows = inputs()
    rows[0].update(metric_key="cash.account.1", period_end=date(2026, 3, 31))
    rows[1].update(metric_key="cash.account.2")
    with pytest.raises(ValueError, match="periods"):
        validate_calculation(replace(draft, unit="SAR", currency="SAR"), rows)


def test_same_metric_from_two_sources_is_not_additive_corroboration():
    rows = inputs()
    rows[0]["metric_key"] = "ceo.revenue"
    with pytest.raises(ValueError, match="Repeated metric"):
        validate_calculation(replace(margin(), formula_key="sum", unit="SAR", currency="SAR",
            value_numeric=Decimal("120")), rows)


def test_reported_claim_label_does_not_invent_external_origin():
    from datetime import UTC, datetime
    draft = replace(margin(), claim_kind="reported_claim", production_method="imported",
        formula_key=None, formula_version=None, input_revision_ids=())
    assert display_label(ClaimRevision(revision_id="r", revision_number=1,
        recorded_at=datetime.now(UTC), draft=draft, traceability="present")) == "Reported claim"
