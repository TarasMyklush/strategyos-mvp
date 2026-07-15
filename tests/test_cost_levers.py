"""Governed cost levers: derived from the run, never invented."""

from strategyos_mvp.cost_levers import derive_cost_levers
from strategyos_mvp.models import Finding


def _finance_kpi():
    """The real prod shape: contributors live under evidence.<scope>.details."""
    return {
        "components": {"operating_cost_actual": "93834910.05", "operating_cost_plan": None},
        "evidence": {
            "operating_cost": {
                "details": {
                    "contributors": {
                        "operating_cost": [
                            {"account": "6000", "label": "Salaries & Wages", "value_sar": "24650975.10", "share_pct": 26.3},
                            {"account": "6100", "label": "Rent Expense", "value_sar": "23731309.95", "share_pct": 25.3},
                            {"account": "6020", "label": "GOSI Contributions", "value_sar": "2507422.35", "share_pct": 2.7},
                            {"label": "Other 121 accounts", "value_sar": "5500000.00", "share_pct": 5.8},
                        ]
                    }
                }
            }
        },
    }


def _finding(finding_id="F-001", title="Auto-renewal escalation", sar=250416.0):
    return Finding(
        finding_id=finding_id, title=title, pattern_type="p", vendor_id="V", vendor_name="V",
        leakage_sar=sar, recoverable_sar=sar, recoverable_usd=1.0, confidence=0.9,
        classification="confirmed", rationale="r", remediation="m", citations=[],
        calculation={}, status="open", challenges=[],
    )


def test_reconciled_findings_outrank_estimated_concentration():
    """Identified money comes before arithmetic on a line's size."""
    result = derive_cost_levers(finance_kpi=_finance_kpi(), findings=[_finding()])

    assert result["status"] == "available"
    kinds = [lever["kind"] for lever in result["levers"]]
    assert kinds[0] == "reconciled_leakage", (
        "a finding carries reconciled evidence and a real amount; a "
        "concentration lever is arithmetic on an assumption and must rank below it"
    )
    assert result["levers"][0]["confidence"] == "reconciled"


def test_concentration_lever_sizes_the_line_without_judging_it():
    """The engine may state a line's share; it must not assert the line is too high."""
    result = derive_cost_levers(finance_kpi=_finance_kpi(), findings=[])
    salaries = next(l for l in result["levers"] if l["line_item"] == "Salaries & Wages")

    assert salaries["share_pct"] == 26.3
    assert salaries["current_sar"] == 24650975.10
    # 5% of 24,650,975.10
    assert round(salaries["addressable_sar"]) == 1232549
    assert salaries["evidence_ref"]["account"] == "6000", "every lever traces to a GL account"
    assert "no benchmark or budget" in salaries["benchmark_basis"], (
        "the lever must disclose that nothing in the run says this line is too high"
    )
    assert salaries["confidence"] == "arithmetic"


def test_immaterial_lines_and_display_rollups_are_not_levers():
    """A 2.7% line is noise; "Other 121 accounts" is a display device."""
    result = derive_cost_levers(finance_kpi=_finance_kpi(), findings=[])
    labels = [lever["line_item"] for lever in result["levers"]]

    assert "GOSI Contributions" not in labels, "below the materiality share"
    assert not any(label.startswith("Other ") for label in labels), (
        "the presentation's tail rollup is not a line an executive can act on"
    )


def test_absent_budget_is_returned_as_a_first_class_answer():
    """What the run cannot tell you is often the most useful thing it can say."""
    result = derive_cost_levers(finance_kpi=_finance_kpi(), findings=[])
    gap = next(l for l in result["levers"] if l["kind"] == "missing_comparator")

    assert gap["confidence"] == "absent"
    assert "no line can be called overspent" in gap["benchmark_basis"].lower()
    assert gap["addressable_sar"] is None, "an absence has no amount to claim"


def test_no_evidence_yields_no_levers_rather_than_a_guess():
    """Fail closed: with nothing proven there is nothing to recommend."""
    result = derive_cost_levers(finance_kpi=None, findings=[])
    assert result["status"] == "unavailable"
    assert result["levers"] == []
    assert "no governed finance kpis" in result["reason"].lower()

    empty = derive_cost_levers(finance_kpi={"components": {"operating_cost_plan": "1"}}, findings=[])
    assert empty["status"] == "unavailable"
    assert empty["levers"] == []


def test_zero_value_finding_is_not_a_lever():
    """A controls finding with no recoverable amount is not money to act on."""
    result = derive_cost_levers(
        finance_kpi=_finance_kpi(),
        findings=[_finding(finding_id="F-008", title="Off-contract spend", sar=0.0)],
    )
    assert not any(l["kind"] == "reconciled_leakage" for l in result["levers"])


def test_a_lever_cannot_wear_a_fact_badge():
    """Layer 3: advice carries its own provenance class.

    "Revenue is SAR 385.1M" is a fact; "cut travel by 15%" is a judgement.
    If both render Grounded, the badge stops distinguishing anything -- which
    is how a confident recommendation gets mistaken for governed truth.
    """
    from strategyos_mvp.executive_read_model import (
        ALLOWED_LIVE_CLAIM_CLASSES,
        CLAIM_CLASS_DISPLAY,
    )

    assert "db_derived_lever" in ALLOWED_LIVE_CLAIM_CLASSES, (
        "levers must be expressible without inventing a class outside the allow-list"
    )
    assert "db_derived_lever" not in {"db_fact", "db_aggregate", "db_derived"}, (
        "a lever must be distinguishable from a governed fact"
    )
    display = CLAIM_CLASS_DISPLAY["db_derived_lever"]
    assert "Suggested" in display and "not yet reviewed" in display, (
        "the surface must say plainly that a lever is advice, not an approved figure"
    )


def test_every_lever_is_traceable_or_declares_its_absence():
    """No lever may exist without a GL account, a finding, or a stated gap."""
    result = derive_cost_levers(finance_kpi=_finance_kpi(), findings=[_finding()])

    for lever in result["levers"]:
        if lever["kind"] == "missing_comparator":
            assert lever["confidence"] == "absent"
            continue
        ref = lever["evidence_ref"]
        assert ref.get("account") or ref.get("finding_id"), (
            f"{lever['line_item']!r} cites nothing; a lever that cannot be traced "
            "to the run must not render"
        )


def test_cost_action_question_is_answered_with_levers_not_the_total():
    """"How do I decrease operating cost?" names the KPI but is not asking what it is.

    The reference resolver would claim it on the word "operating cost" and
    restate SAR 93.8M -- a fluent answer to a different question. Levers must
    run first.
    """
    import strategyos_mvp.api as api_module

    assert api_module._question_asks_what_to_do_about_cost("How can I decrease operating cost?") is True
    assert api_module._question_asks_what_to_do_about_cost("what can I do about opex") is True
    assert api_module._question_asks_what_to_do_about_cost("where can we cut spend") is True
    # Not cost-action questions: these belong to the KPI contract.
    assert api_module._question_asks_what_to_do_about_cost("What is our revenue?") is False
    assert api_module._question_asks_what_to_do_about_cost("What is operating cost?") is False


def test_lever_answer_leads_with_reconciled_money_and_declares_its_limits():
    """Order and honesty are the product here, not the prose."""
    import strategyos_mvp.api as api_module

    context = {
        "run_id": "run-1",
        "findings": [_finding()],
        "summary": {"run_id": "run-1", "finance_kpi": _finance_kpi()},
    }
    result = api_module._governed_cost_lever_result(
        context, question="How can I decrease operating cost?", public_safe=False
    )

    assert result is not None
    answer = result["answer"]
    assert answer.index("already identified") < answer.index("concentrated"), (
        "reconciled money must lead; concentration arithmetic is an estimate"
    )
    assert "nothing in this run says any of these lines is too high" in answer, (
        "a lever must not imply the run judged the line"
    )
    assert "no line can be called overspent" in answer, (
        "the missing budget is part of the honest answer"
    )
    assert result["claim_class"] == "db_derived_lever"
    assert result["grounding_status"] == "suggested", (
        "advice must not claim the grounded badge a fact carries"
    )
    assert result["citations"], "every lever answer must cite its accounts and findings"


def test_lever_answer_is_withheld_when_the_run_proves_nothing():
    """No evidence, no advice."""
    import strategyos_mvp.api as api_module

    context = {"run_id": "run-1", "findings": [], "summary": {"run_id": "run-1"}}
    assert api_module._governed_cost_lever_result(
        context, question="How can I decrease operating cost?", public_safe=False
    ) is None
