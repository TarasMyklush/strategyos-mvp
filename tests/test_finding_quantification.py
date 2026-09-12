from dataclasses import replace
import pytest
from strategyos_mvp.finding_quantification import reviewed_amount
from strategyos_mvp.models import Finding
from strategyos_mvp.runtime_governance import build_run_summary


def finding(status, amount=100):
    return Finding('F1','Review example','duplicate_payment','V1','Vendor',amount,amount,0,'HIGH','CASH','Example','Review',status=status)


@pytest.mark.parametrize('status', ['draft','challenged','disputed','rejected','blocked',None,'unknown'])
def test_unreviewed_amount_never_inflates_totals(status):
    original = finding(status)
    assert reviewed_amount(original) == 0
    assert reviewed_amount({'status':status,'recoverable_sar':100}) == 0
    assert original.recoverable_sar == 100
    assert build_run_summary({'findings':[original]})['total_recoverable_sar'] == 0


@pytest.mark.parametrize('status', ['locked','approved'])
def test_reviewed_amount_is_preserved(status):
    assert reviewed_amount(finding(status)) == 100


@pytest.mark.parametrize('value', [float('nan'),float('inf'),-1,'invalid'])
def test_invalid_reviewed_amount_refuses(value):
    with pytest.raises(ValueError):
        reviewed_amount(finding('locked',value))


def test_case_report_and_qa_exclude_disputed_value():
    from strategyos_mvp.agents.finance_agents import render_case_file, render_qa
    from strategyos_mvp.ingestion import load_dataset
    from strategyos_mvp.paths import SOURCE_DATASET
    from strategyos_mvp import qa
    bundle=load_dataset(SOURCE_DATASET)
    accepted=finding('locked',100)
    excluded=replace(finding('disputed',999999),finding_id='F2')
    report=render_case_file([accepted,excluded],bundle)
    assert 'Reviewed recovery and conditional savings opportunities: SAR 100.00' in report
    assert 'Excluded from reviewed totals: 1' in report
    assert 'F2' in report  # Original disputed evidence remains reviewable.
    answers=render_qa([accepted,excluded],bundle)
    assert '999,999' not in answers
    assert '1 unreviewed or excluded' in answers
    result=qa.answer_question('total recoverable?',bundle=bundle,findings=[accepted,excluded])
    assert result['available'] is False
    assert result['value'] is None


def test_zero_total_does_not_allow_unreviewed_board_publication():
    from strategyos_mvp.api import _board_reconciliation_payload
    result=_board_reconciliation_payload({'total_recoverable_sar':0},
        [{'finding_id':'F1','status':'disputed','recoverable_sar':100}],
        {'status':'ok','citation_count':1,'resolved_count':1,'challenged_finding_ids':[]})
    assert result['publish_gate_passed'] is False
    assert next(c for c in result['checks'] if c['key']=='finding_review_status')['status']=='failed'
