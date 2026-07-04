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
