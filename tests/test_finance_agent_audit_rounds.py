from strategyos_mvp.agents.finance_agents import FinanceAnalystAgent, FinanceAuditorAgent
from strategyos_mvp.models import Citation, Finding
import pytest


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


def test_finance_audit_locks_only_resolved_findings_and_retains_disputes():
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
    assert [finding.status for finding in findings] == ["disputed"] * 3 + ["locked"] * 3
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
    assert last_response == auditor.max_rounds
    assert first_lock.finding_id in {"F-004", "F-005", "F-006"}
    assert all(event.finding_id not in {"F-001", "F-002", "F-003"} for event in events if event.action == "lock")
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


@pytest.mark.parametrize('count,required', [(1, 1), (6, 6), (8, 8), (9, 9), (14, 14)])
def test_auditor_challenges_every_finding(count, required):
    findings = [_finding(i) for i in range(count)]
    auditor = FinanceAuditorAgent()
    events = auditor.run_review_rounds(findings)
    report = auditor.verify_acceptance_coverage(findings, events)
    assert report['required_challenged_findings'] == required
    assert report['actual_challenged_findings'] >= required
    assert report['passed']


def test_unrelated_and_repeated_challenge_events_cannot_satisfy_coverage():
    from dataclasses import replace
    findings = [_finding(i) for i in range(9)]
    auditor = FinanceAuditorAgent()
    challenge = next(event for event in auditor.run_review_rounds(findings) if event.action == 'challenge')
    events = [challenge] * 5 + [replace(challenge, finding_id='unrelated')]
    report = auditor.verify_acceptance_coverage(findings, events)
    assert report['actual_challenged_findings'] == 1
    assert not report['passed']


def test_blocked_finding_cannot_be_unblocked_by_a_challenge_response():
    finding = _finding(1)
    finding.status = "blocked"
    events = FinanceAuditorAgent().run_review_rounds([finding], max_rounds=2)
    assert finding.status == "blocked"
    assert not any(event.action == "lock" for event in events)
    assert any(event.action == "max_rounds" and event.status == "blocked" for event in events)


def test_evidence_repair_is_rechecked_and_can_lock_on_last_round():
    class RepairingAnalyst(FinanceAnalystAgent):
        def respond_to_challenges(self, findings, challenges, *, round_no):
            events = super().respond_to_challenges(findings, challenges, round_no=round_no)
            if round_no == 2:
                findings[0].citations = _finding(1).citations
            return events
    finding = _finding(1, citations=1)
    events = FinanceAuditorAgent().run_review_rounds([finding], analyst=RepairingAnalyst(), max_rounds=2)
    assert finding.status == "locked"
    locks = [event for event in events if event.action == "lock"]
    assert len(locks) == 1 and locks[0].round_no == 2
    assert not any(event.action == "max_rounds" for event in events)


def test_duplicate_citation_locations_do_not_clear_evidence_challenge():
    finding = _finding(1)
    finding.citations = [finding.citations[0]] * 3
    FinanceAuditorAgent().run_review_rounds([finding], max_rounds=1)
    assert finding.status == "disputed"


def test_duplicate_finding_identity_is_rejected_before_review():
    findings = [_finding(1), _finding(1)]
    with pytest.raises(ValueError, match="unique finding"):
        FinanceAuditorAgent().run_review_rounds(findings)
    assert all(finding.status == "draft" for finding in findings)


@pytest.mark.parametrize("rounds", [0, -1, 11, True, 1.5])
def test_invalid_round_limit_is_rejected(rounds):
    with pytest.raises(ValueError, match="one and ten"):
        FinanceAuditorAgent().run_review_rounds([_finding(1)], max_rounds=rounds)
