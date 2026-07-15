from strategyos_mvp.governed_plans import (
    extract_approved_plan_candidates,
    plan_comparators,
    strategic_references,
    validate_plan_payload,
)


def valid_payload() -> dict:
    return {
        "title": "H1 2026 Group operating plan",
        "reporting_period_key": "H1 2026",
        "period_start": "2026-01-01",
        "period_end": "2026-06-30",
        "currency": "SAR",
        "scope": {"entities": ["Group"]},
        "source": {"name": "Board-approved budget", "reference": "minute-2025-12-18"},
        "targets": {
            "revenue": {"value": "420000000", "unit": "SAR"},
            "ebitda_margin": {"value": "58", "unit": "percent"},
            "operating_cost": {"value": "90000000", "unit": "SAR"},
            "cash_floor": {"value": "50000000", "unit": "SAR"},
        },
    }


def test_plan_validation_requires_all_governed_dimensions() -> None:
    normalized, exceptions = validate_plan_payload({"title": "Incomplete"})
    fields = {item["field"] for item in exceptions}
    assert normalized["targets"] == {}
    assert {"reporting_period_key", "period", "scope.entities", "source"}.issubset(fields)
    assert {"targets.revenue", "targets.ebitda_margin", "targets.operating_cost", "targets.cash_floor"}.issubset(fields)


def test_active_aligned_plan_produces_four_dashboard_comparators() -> None:
    plan, exceptions = validate_plan_payload(valid_payload())
    assert exceptions == []
    plan.update({"id": "plan-1", "version": 4, "status": "active"})
    comparison = plan_comparators(plan, {
        "reporting_period_key": "H1 2026",
        "reporting_currency": "SAR",
        "reporting_scope": {"entities": ["Group"]},
    })
    assert comparison["aligned"] is True
    assert comparison["components"] == {
        "revenue_plan": 420000000.0,
        "ebitda_plan": 243600000.0,
        "operating_cost_plan": 90000000.0,
        "board_floor": 50000000.0,
    }


def test_draft_or_scope_mismatch_never_feeds_dashboard() -> None:
    plan, _ = validate_plan_payload(valid_payload())
    plan["status"] = "draft"
    assert plan_comparators(plan, {})["aligned"] is False
    plan["status"] = "active"
    comparison = plan_comparators(plan, {
        "reporting_period_key": "H1 2026",
        "reporting_currency": "SAR",
        "reporting_scope": {"entities": ["Subsidiary A"]},
    })
    assert comparison["aligned"] is False
    assert "scope" in comparison["reason"].lower()


def test_plan_page_is_financial_governance_not_execution_tracker() -> None:
    html = open("strategyos_mvp/static/financial_plan.html", encoding="utf-8").read()
    assert "Approve the plan that drives the dashboard" in html
    assert "Approve & activate" in html
    assert "/api/financial-plans" in html
    assert "Only a validated, finance-reviewed and CEO-approved active plan" in html


def approved_strategy_source_pack(text: str) -> dict:
    return {
        "source_pack_id": "source-pack-1",
        "manifest": [{
            "relative_path": "04_Strategic_Context/01_Group_Strategy/Group_Strategy.pdf",
            "sha256": "abc123",
            "classification": {"role": "approved_strategy_plan"},
            "text_extraction": {"raw_text": text},
        }],
    }


def test_explicit_board_approval_imports_supplied_targets_without_inference() -> None:
    plans = extract_approved_plan_candidates(approved_strategy_source_pack(
        "Board-approved 12 January 2026. 2026F REVENUE SAR 8,350M. "
        "Complete Group cash must remain above the SAR 1.20B floor."
    ))
    assert len(plans) == 1
    normalized, exceptions = validate_plan_payload(plans[0])
    assert exceptions == []
    assert normalized["plan_type"] == "strategic_reference"
    assert normalized["targets"]["revenue"]["value"] == "8350000000"
    assert normalized["targets"]["cash_floor"]["value"] == "1200000000.00"
    assert "ebitda_margin" not in normalized["targets"]
    assert normalized["source"]["approval_date"] == "2026-01-12"


def test_file_presence_without_explicit_approval_never_auto_approves() -> None:
    plans = extract_approved_plan_candidates(approved_strategy_source_pack(
        "Draft strategy plan. 2026F REVENUE SAR 8,350M."
    ))
    assert plans == []


def test_strategic_plan_is_context_not_like_for_like_variance() -> None:
    plan = extract_approved_plan_candidates(approved_strategy_source_pack(
        "Board-approved 12 January 2026. 2026F REVENUE SAR 8,350M."
    ))[0]
    plan.update({"status": "active", "id": "strategic-1", "version": 1})
    comparison = plan_comparators(plan, {
        "reporting_period_key": "H1 2026",
        "reporting_currency": "SAR",
        "reporting_scope": {"entities": ["Group"]},
    })
    assert comparison["aligned"] is False
    assert "strategic reference" in comparison["reason"]
    assert strategic_references(plan)["revenue"] == {
        "label": "Approved FY2026 Group revenue plan",
        "value": "SAR 8.35B",
        "numeric_value": 8350000000.0,
        "note": "Annual Group progress reference; not a like-for-like H1 variance.",
        "source": "Board-approved Group Strategy 2026–2028",
    }
