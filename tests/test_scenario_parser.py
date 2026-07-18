from strategyos_mvp.scenario_parser import (
    _parse_numeric_tokens,
    _target_revenue_attainment_from_prompt,
    parse_scenario,
)
from tests.fixtures.executive_demo_packet import executive_demo_packet


def test_parse_scenario_uses_kg_node_properties_domain_for_digital_health_match():
    result = parse_scenario(
        "Simulate digital health flat by end of year",
        {
            "bundle": object(),
            "findings": [],
            "kg_nodes": [
                {
                    "id": "n-1",
                    "label": "Initiative",
                    "properties": {"domain": "digital_health", "name": "Digital Health rollout"},
                }
            ],
        },
    )

    assert result.matched is True
    assert result.scenario_id == "digital_health_eoy_flat"
    assert result.scenario_type == "deterministic"
    assert result.calculations
    assert result.citations
    assert result.answer.startswith("Digital Health findings show")


def test_parse_scenario_handler_errors_return_safe_error_contract():
    result = parse_scenario(
        "Simulate digital health flat by end of year",
        {
            "bundle": object(),
            "findings": [],
            "kg_nodes": [object()],
        },
    )

    assert result.matched is False
    assert result.scenario_type == "error"
    assert result.hallucination_risk is not None
    assert result.hallucination_risk.level.value == "high"
    assert "object has no attribute" not in result.answer
    assert "object has no attribute" not in result.basis


def test_parse_scenario_public_digital_health_uses_shared_public_packet():
    packet = executive_demo_packet()
    result = parse_scenario(
        "Simulate digital health flat by end of year",
        {
            "bundle": packet,
            "findings": [],
            "kg_nodes": packet["kg_nodes"],
            "public_context_packet": packet,
        },
    )

    assert result.matched is True
    assert result.scenario_id == "digital_health_eoy_flat"
    assert result.hallucination_risk is not None
    assert result.hallucination_risk.level.value == "low"
    assert "public executive packet" in result.answer.lower()


def test_parse_scenario_finance_leakage_uses_only_supplied_findings():
    result = parse_scenario(
        "Show the total recoverable value and its breakdown.",
        {
            "bundle": object(),
            "findings": [
                {"title": "Case A", "pattern_type": "duplicate_payment", "recoverable_sar": 600_000},
                {"title": "Case B", "pattern_type": "contract_leakage", "recoverable_sar": 200_000},
            ],
            "kg_nodes": [],
            "public_context_packet": {},
        },
    )
    assert result.matched is True
    assert result.scenario_id == "finance_leakage"
    assert "SAR 800,000.00" in result.answer
    assert "duplicate_payment: SAR 600,000.00" in result.answer
    assert result.hallucination_risk.level.value == "none"


def test_parse_scenario_missing_finance_findings_has_non_none_risk():
    result = parse_scenario(
        "Show evidence for SAR 8.6M recoverable",
        {"bundle": None, "findings": [], "kg_nodes": [], "public_context_packet": {}},
    )

    assert result.matched is True
    assert result.scenario_id == "finance_leakage"
    assert result.hallucination_risk is not None
    assert result.hallucination_risk.level.value != "none"


def test_recovery_realization_applies_user_amount_to_governed_baseline():
    result = parse_scenario(
        "If we recover SAR 400,000 of the current recoverable value, what remains and what changes for board readiness?",
        {
            "bundle": object(),
            "findings": [
                {"pattern_type": "duplicate_payment", "recoverable_sar": 500_000},
                {"pattern_type": "contract_leakage", "recoverable_sar": 294_108},
            ],
            "kg_nodes": [],
            "public_context_packet": {},
        },
    )

    assert result.matched is True
    assert result.scenario_id == "recovery_realization"
    assert "SAR 394,108.00" in result.answer
    assert "Board readiness does not automatically clear" in result.answer
    assert any(step.step_id == "remaining_recoverable" for step in result.calculations)
    remaining = next(step for step in result.calculations if step.step_id == "remaining_recoverable")
    assert remaining.inputs["realized_amount_sar"] == "400000"
    assert {"raw": "SAR 400,000", "value": "400000", "unit": "SAR"} in remaining.inputs["prompt_numbers"]


def test_recovery_realization_prefers_number_tied_to_recovery_action():
    result = parse_scenario(
        "Current SAR 794,108 recoverable value: if we recover SAR 400,000, what remains?",
        {
            "bundle": object(),
            "findings": [{"pattern_type": "contract_leakage", "recoverable_sar": 794_108}],
            "kg_nodes": [],
            "public_context_packet": {},
        },
    )

    assert result.scenario_id == "recovery_realization"
    assert "SAR 394,108.00" in result.answer


def test_public_recovery_realization_uses_reconciled_total_and_cash_baseline():
    packet = {
        "is_illustrative": False,
        "public_facts": {
            "total_recoverable_sar": 794_108,
            "total_finding_count": 8,
            "current_cash_sar": "42341408.58",
            "current_cash_complete": False,
        },
        "findings_reconciliation": {
            "total_recoverable_sar": 794_108,
            "displayed_recoverable_sar": 717_020,
            "remaining_recoverable_sar": 77_088,
            "total_finding_count": 8,
            "displayed_finding_count": 5,
        },
    }
    result = parse_scenario(
        "If we collect all recoverable value this quarter, how does that change our cash position?",
        {
            "bundle": packet,
            "public_context_packet": packet,
            "findings": [{"recoverable_sar": 250_416}],
            "summary": {},
            "kg_nodes": [],
        },
    )

    assert result.matched is True
    assert result.scenario_id == "recovery_realization"
    assert "SAR 794,108.00" in result.answer
    assert "SAR 43.1M" in result.answer
    assert "remains partial" in result.answer
    cash_step = next(step for step in result.calculations if step.step_id == "cash_position_after_recovery")
    assert cash_step.result == "SAR 43,135,516.58"


def test_public_value_at_stake_reconciles_cases_and_recommends_first_action():
    amounts = [250_416, 177_188, 120_000, 93_000, 76_416, 40_000, 25_000, 12_088]
    cases = [
        {
            "title": f"Case {index}",
            "recoverable_sar": amount,
            "impact": f"SAR {amount:,.0f} recoverable",
        }
        for index, amount in enumerate(amounts, start=1)
    ]
    packet = {
        "is_illustrative": False,
        "public_facts": {"total_recoverable_sar": 794_108, "total_finding_count": 8},
        "findings_reconciliation": {"total_recoverable_sar": 794_108, "total_finding_count": 8},
        "finding_case_index": cases,
        "findings": cases[:3],
    }
    result = parse_scenario(
        "Which governed cases create the largest recoverable value, and what should be acted on first?",
        {"bundle": packet, "public_context_packet": packet, "findings": cases, "kg_nodes": []},
    )

    assert result.matched is True
    assert result.scenario_id == "governed_recovery_priorities"
    assert result.answer.startswith("The current view shows")
    assert "governed packet" not in result.answer.lower()
    assert "remaining 3 smaller cases total SAR 77,088.00" in result.answer
    assert "Recommended first action" in result.answer
    assert "Group Finance" in result.answer
    assert "Case 1 (SAR 250,416.00)" in result.answer


def test_fx_hedge_scenario_fails_closed_instead_of_returning_leakage_total():
    result = parse_scenario(
        "What would a 60% EUR hedge save?",
        {
            "bundle": object(),
            "findings": [{"pattern_type": "contract_leakage", "recoverable_sar": 794_108}],
            "kg_nodes": [],
            "public_context_packet": {},
        },
    )

    assert result.matched is True
    assert result.scenario_id == "fx_hedge"
    assert result.scenario_type == "missing_data"
    assert "EUR exposure" in result.answer
    assert "SAR 794,108" not in result.answer


def test_ebitda_scenario_fails_closed_when_income_statement_inputs_are_absent():
    result = parse_scenario(
        "If revenue falls 5% and costs rise 3%, what happens to EBITDA?",
        {
            "bundle": object(),
            "findings": [{"pattern_type": "contract_leakage", "recoverable_sar": 794_108}],
            "kg_nodes": [],
            "public_context_packet": {},
        },
    )

    assert result.matched is True
    assert result.scenario_id == "ebitda_scenario"
    assert result.scenario_type == "missing_data"
    assert "revenue" in result.answer.lower()
    assert "cost baseline" in result.answer.lower()


def test_ebitda_target_margin_uses_governed_dashboard_baseline():
    result = parse_scenario(
        "model what needs to happen so we have 60% margin",
        {
            "bundle": object(),
            "findings": [],
            "kg_nodes": [],
            "public_context_packet": {},
            "summary": {
                "finance_kpi": {
                    "authoritative": True,
                    "reporting_period_key": "H1 2026",
                    "reporting_currency": "SAR",
                    "components": {
                        "revenue_actual": "385079908.90",
                        "cogs_actual": "75503688.29",
                        "operating_cost_actual": "93834910.05",
                        "ebitda_actual": "215741310.56",
                    },
                    "evidence": {
                        "ebitda_margin": {
                            "files": [
                                "02_ERP_Extracts/GL_Extract_H1_2026.csv",
                                "03_Master_Data/Chart_of_Accounts.xlsx",
                            ]
                        }
                    },
                }
            },
        },
    )

    assert result.matched is True
    assert result.scenario_id == "ebitda_target_margin"
    assert result.scenario_type == "deterministic"
    assert "56.0%" in result.answer
    assert "60.0%" in result.answer
    assert "SAR 15.3M" in result.answer
    assert "SAR 78.5M" in result.answer
    assert "16.3%" in result.answer
    assert "SAR 460.1M" in result.answer
    assert "19.5%" in result.answer
    assert "not a forecast" in result.answer
    assert result.hallucination_risk.level.value == "none"
    assert {step.step_id for step in result.calculations} == {
        "governed_ebitda_baseline",
        "target_ebitda",
        "fixed_revenue_cost_path",
        "fixed_opex_growth_path",
    }
    assert {citation["source_path"] for citation in result.citations} == {
        "02_ERP_Extracts/GL_Extract_H1_2026.csv",
        "03_Master_Data/Chart_of_Accounts.xlsx",
    }


def test_revenue_plan_target_returns_exact_gap_and_ceo_action():
    result = parse_scenario(
        "revenue actual is SAR 385.1M. 99.4% of plan. - how to make it 100%?",
        {
            "bundle": object(),
            "findings": [],
            "kg_nodes": [],
            "public_context_packet": {},
            "summary": {
                "finance_kpi": {
                    "authoritative": True,
                    "reporting_period_key": "H1 2026",
                    "reporting_currency": "SAR",
                    "components": {
                        "revenue_actual": "385079908.90",
                        "revenue_plan": "387500000.00",
                    },
                    "evidence": {
                        "revenue": {
                            "files": [
                                "02_ERP_Extracts/GL_Extract_H1_2026.csv",
                                "01_Planning/Revenue_Plan_H1_2026.xlsx",
                            ]
                        }
                    },
                }
            },
        },
    )

    assert result.matched is True
    assert result.scenario_id == "revenue_plan_attainment"
    assert result.scenario_type == "deterministic"
    assert "SAR 385.1M" in result.answer
    assert "SAR 387.5M" in result.answer
    assert "99.4%" in result.answer
    assert "gap to 100.0% is SAR 2.4M" in result.answer
    assert "CEO action:" in result.answer
    assert "CRM pipeline or order-backlog evidence" in result.answer
    assert result.hallucination_risk.level.value == "none"
    assert {step.step_id for step in result.calculations} == {
        "governed_revenue_attainment",
        "revenue_target_gap",
    }
    assert {citation["source_path"] for citation in result.citations} == {
        "02_ERP_Extracts/GL_Extract_H1_2026.csv",
        "01_Planning/Revenue_Plan_H1_2026.xlsx",
    }


def test_revenue_plan_target_estimates_from_ceo_stated_attainment_when_plan_is_missing():
    """The live pack has actual Revenue but no aligned plan.

    A CEO who supplies the displayed attainment has supplied enough information
    for a labelled estimate; Hermes should help without presenting it as an
    approved comparator.
    """
    result = parse_scenario(
        "revenue actual is SAR 385.1M. 99.4% of plan. - how to make it 100%?",
        {
            "bundle": object(),
            "findings": [],
            "kg_nodes": [],
            "public_context_packet": {},
            "assistant_context": {"kpi_key": "revenue"},
            "summary": {
                "finance_kpi": {
                    "authoritative": True,
                    "reporting_period_key": "H1 2026",
                    "reporting_currency": "SAR",
                    "components": {"revenue_actual": "385079908.90"},
                    "evidence": {
                        "revenue": {
                            "files": ["02_ERP_Extracts/GL_Extract_H1_2026.csv"]
                        }
                    },
                }
            },
        },
    )

    assert result.matched is True
    assert result.scenario_id == "revenue_plan_attainment"
    assert result.scenario_type == "deterministic"
    assert "your stated 99.4% attainment" in result.answer
    assert "implied plan is approximately SAR 387.4M" in result.answer
    assert "estimated gap to 100.0% is SAR 2.3M" in result.answer
    assert "CEO action:" in result.answer
    assert "not an approved plan comparison" in result.answer
    assert "CRM pipeline and order-backlog evidence" in result.answer
    assert result.hallucination_risk.level.value == "medium"
    assert {step.step_id for step in result.calculations} == {
        "implied_revenue_plan",
        "estimated_revenue_target_gap",
    }
    assert {citation["source_path"] for citation in result.citations} == {
        "02_ERP_Extracts/GL_Extract_H1_2026.csv",
    }


def test_revenue_gap_followup_stays_on_revenue_and_returns_a_ceo_action_plan():
    result = parse_scenario(
        "Fine. What do I decide today, who owns it, and what must be on my desk by tomorrow morning? Give me a 3-step CEO action plan.",
        {
            "bundle": object(),
            "findings": [
                {
                    "finding_id": "F-002",
                    "title": "Duplicate payment",
                    "amount": 177188,
                }
            ],
            "kg_nodes": [],
            "public_context_packet": {},
            "assistant_context": {"driver_key": "revenue", "entrypoint": "drawer_input"},
            "assistant_history": [
                {
                    "role": "user",
                    "text": "revenue actual is SAR 385.1M. 99.4% of plan. - how to make it 100%?",
                    "assistant_context": {"kpi_key": "revenue"},
                },
                {
                    "role": "assistant",
                    "text": "The estimated gap to 100.0% is SAR 2.3M.",
                    "payload": {"scenario_id": "revenue_plan_attainment"},
                },
            ],
            "summary": {
                "finance_kpi": {
                    "authoritative": True,
                    "reporting_period_key": "H1 2026",
                    "reporting_currency": "SAR",
                    "components": {"revenue_actual": "385079908.90"},
                    "evidence": {
                        "revenue": {
                            "files": ["02_ERP_Extracts/GL_Extract_H1_2026.csv"]
                        }
                    },
                }
            },
        },
    )

    assert result.scenario_id == "revenue_plan_attainment_action_plan"
    assert result.scenario_type == "deterministic"
    assert "Decision today:" in result.answer
    assert "SAR 2.3M" in result.answer
    assert "Group commercial/revenue executive" in result.answer
    assert "CFO/Finance" in result.answer
    assert result.answer.count("By tomorrow morning") == 2
    assert "daily gap review" in result.answer
    assert "cannot prove: which revenue stream or deal can close it" in result.answer
    assert "Duplicate payment" not in result.answer
    assert "accounts payable" not in result.answer.lower()
    assert result.hallucination_risk.level.value == "medium"


def test_revenue_card_context_turns_make_it_100_percent_into_target_calculation():
    result = parse_scenario(
        "how to make it 100%?",
        {
            "bundle": object(),
            "findings": [],
            "kg_nodes": [],
            "public_context_packet": {},
            "assistant_context": {"kpi_key": "revenue"},
            "summary": {
                "finance_kpi": {
                    "reporting_period_key": "H1 2026",
                    "components": {
                        "revenue_actual": "385079908.90",
                        "revenue_plan": "387500000.00",
                    },
                }
            },
        },
    )

    assert result.scenario_id == "revenue_plan_attainment"
    assert "gap to 100.0% is SAR 2.4M" in result.answer


def test_revenue_status_question_does_not_treat_decision_to_make_as_a_target():
    prompt = (
        "As CEO, what does revenue's 99.4% of plan mean for me? "
        "Name the largest driver and the decision I need to make."
    )

    target = _target_revenue_attainment_from_prompt(
        prompt,
        _parse_numeric_tokens(prompt),
        {"assistant_context": {"kpi_key": "revenue"}},
    )

    assert target is None


def test_governed_public_ceo_surface_models_target_margin_from_same_dashboard_baseline():
    result = parse_scenario(
        "Model what needs to happen to reach a 60% EBITDA margin using the current governed revenue and cost baseline.",
        {
            "bundle": {"public_safe": True},
            "findings": [],
            "kg_nodes": [],
            "public_context_packet": {
                "is_illustrative": False,
                "public_safe": True,
                "drivers": [],
                "findings": [],
            },
            "summary": {
                "finance_kpi": {
                    "authoritative": True,
                    "reporting_period_key": "H1 2026",
                    "reporting_currency": "SAR",
                    "components": {
                        "revenue_actual": "385079908.90",
                        "cogs_actual": "75503688.29",
                        "operating_cost_actual": "93834910.05",
                        "ebitda_actual": "215741310.56",
                    },
                    "evidence": {
                        "ebitda_margin": {
                            "files": [
                                "02_ERP_Extracts/GL_Extract_H1_2026.csv",
                                "03_Master_Data/Chart_of_Accounts.xlsx",
                            ]
                        }
                    },
                }
            },
        },
    )

    assert result.matched is True
    assert result.scenario_id == "ebitda_target_margin"
    assert result.scenario_type == "deterministic"
    assert result.hallucination_risk.level.value == "none"
    assert "56.0%" in result.answer
    assert "60.0%" in result.answer
    assert "SAR 15.3M" in result.answer
    assert "SAR 460.1M" in result.answer
    assert "Current governed drivers" not in result.answer


def test_ebitda_target_margin_can_complete_one_component_from_governed_identity():
    result = parse_scenario(
        "What needs to change to reach a 60% EBITDA margin?",
        {
            "bundle": object(),
            "findings": [],
            "kg_nodes": [],
            "public_context_packet": {},
            "summary": {
                "finance_kpi": {
                    "reporting_period_key": "H1 2026",
                    "components": {
                        "revenue_actual": "385079908.90",
                        "cogs_actual": "75503688.29",
                        "ebitda_actual": "215741310.56",
                    },
                }
            },
        },
    )

    assert result.scenario_id == "ebitda_target_margin"
    assert "SAR 93.8M" in result.answer
    assert result.scenario_type == "deterministic"


def test_authenticated_digital_health_without_actual_data_does_not_use_synthetic_baseline():
    result = parse_scenario(
        "Simulate Digital Health flat by end of year",
        {
            "bundle": object(),
            "findings": [],
            "kg_nodes": [],
            "public_context_packet": {},
        },
    )

    assert result.matched is True
    assert result.scenario_id == "digital_health_eoy_flat"
    assert result.scenario_type == "missing_data"
    assert "Illustrative external benchmarks are disabled" in result.answer
