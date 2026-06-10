from strategyos_mvp.agents.finance_agents import FinanceAnalystAgent, FinanceAuditorAgent
from strategyos_mvp.models import Citation, Finding


def _finding(index: int, *, citations: int = 3, calculation: bool = True) -> Finding:
    return Finding(
        finding_id=f"F-{index:03d}",
        title=f"Finding {index}",
        pattern_type="duplicate_payment",
        vendor_id=f"V-{index:03d}",
        vendor_name=f"Vendor {index}",
        leakage_sar=1000.0 + index,
        recoverable_sar=800.0 + index,
        recoverable_usd=200.0 + index,
        confidence="HIGH",
        classification="test",
        rationale="deterministic rationale",
        remediation="deterministic remediation",
        citations=[
            Citation(
                source_path=f"source-{index}.xlsx",
                locator=f"Sheet1!A{row}",
                excerpt="excerpt",
            )
            for row in range(1, citations + 1)
        ],
        calculation={"basis": "test"} if calculation else {},
    )


def test_finance_audit_runs_ping_pong_rounds_and_locks_findings():
    findings = [
        _finding(1, citations=2),
        _finding(2, calculation=False),
        _finding(3, citations=1),
        _finding(4),
        _finding(5),
        _finding(6),
    ]

    auditor = FinanceAuditorAgent()
    analyst = FinanceAnalystAgent()

    events = auditor.run_review_rounds(findings, analyst=analyst)

    assert events
    assert {event.actor for event in events} >= {"Finance Auditor", "Finance Analyst"}
    assert all(finding.status == "locked" for finding in findings)
    challenged = {
        event.finding_id
        for event in events
        if event.actor == auditor.name and event.action == "challenge"
    }
    assert len(challenged) >= 4
    first_lock = next(event for event in events if event.action == "lock")
    last_response = max(
        event.round_no for event in events if event.actor == analyst.name and event.action == "response"
    )
    assert first_lock.round_no > last_response
    assert auditor.last_verification["passed"] is True
    assert auditor.last_verification["actual_challenged_findings"] >= 4


def test_audit_log_records_structured_fields_for_challenge_and_response():
    findings = [_finding(1, citations=2), _finding(2), _finding(3), _finding(4)]

    auditor = FinanceAuditorAgent()
    events = auditor.run_review_rounds(findings, analyst=FinanceAnalystAgent())

    challenge = next(event for event in events if event.action == "challenge")
    response = next(event for event in events if event.action == "response")

    assert challenge.round_no == 1
    assert challenge.challenge
    assert challenge.status == "challenged"
    assert challenge.started_at
    assert challenge.completed_at
    assert challenge.prompt_tokens is None
    assert challenge.estimated_cost_usd is None

    assert response.challenge
    assert response.response
    assert response.status == "responded"
    assert response.confidence_change in {"UNCHANGED", "HIGH->MEDIUM", "MEDIUM->LOW"}


def test_audit_challenges_weak_findings_before_strong_sample_findings():
    findings = [
        _finding(1),
        _finding(2, citations=2),
        _finding(3, calculation=False),
        _finding(4, citations=1),
        _finding(5),
    ]

    auditor = FinanceAuditorAgent()
    events = auditor.run_review_rounds(findings, analyst=FinanceAnalystAgent())

    challenged_in_round_one = [
        event.finding_id
        for event in events
        if event.actor == auditor.name and event.action == "challenge" and event.round_no == 1
    ]

    assert {"F-002", "F-003", "F-004"}.issubset(set(challenged_in_round_one))
