from strategyos_mvp.executive_design import executive_public_assistant_context
from strategyos_mvp.scenario_parser import parse_scenario


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
    packet = executive_public_assistant_context()
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


def test_parse_scenario_public_exec_prompts_return_substantive_answers():
    packet = executive_public_assistant_context()

    tamween = parse_scenario(
        'Project the impact of "Tamween audit: SAR 1.2M recoverable" on the current plan and what I should prepare for the board.',
        {
            "bundle": packet,
            "findings": [
                {"title": "SAR 8.6M is recoverable across the group", "pattern_type": "group_recovery", "recoverable_sar": 8_600_000},
                {"title": "Tamween audit: SAR 1.2M recoverable", "pattern_type": "tamween_audit", "recoverable_sar": 1_200_000},
            ],
            "kg_nodes": packet["kg_nodes"],
            "public_context_packet": packet,
        },
    )
    assert tamween.matched is True
    assert "sar 1.2m" in tamween.answer.lower()
    assert "sar 8.6m" in tamween.answer.lower()
    assert "board" in tamween.answer.lower()
    assert tamween.hallucination_risk.level.value == "low"

    epharmacy = parse_scenario(
        "Show e-Pharmacy detail",
        {
            "bundle": packet,
            "findings": [],
            "kg_nodes": packet["kg_nodes"],
            "public_context_packet": packet,
        },
    )
    assert epharmacy.matched is True
    assert epharmacy.scenario_id == "public_exec_epharmacy_detail"
    assert "growth lever" in epharmacy.answer.lower()
    assert "capacity" in epharmacy.answer.lower()


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
