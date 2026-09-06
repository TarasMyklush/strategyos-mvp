from dataclasses import replace
from datetime import UTC,datetime

import pytest

from strategyos_mvp.claim_priority import PriorityDecision,PriorityConflict,record_priority
from strategyos_mvp.source_claims import ClaimDraft,ClaimQuery,EvidenceOccurrence
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake

pytestmark=pytest.mark.integration


def test_priority_history_retry_and_stale_write_protection(ledger):
    import psycopg
    repo,operator,occurrence,source,policy=setup_intake(ledger)
    context=replace(operator,roles=frozenset({'tenant_admin'}))
    policy=replace(policy,allowed_roles=frozenset({'tenant_admin','operator'}))
    repo.register_source(source,policy=policy,recorded_by='steward',rationale='Synthetic admin review')
    second_source=replace(source,source_key='priority-second')
    second_policy=replace(policy,source_key='priority-second')
    repo.register_source(second_source,policy=second_policy,recorded_by='steward',rationale='Synthetic second origin')
    second_occurrence=repo.record_occurrence(EvidenceOccurrence(tenant_id=context.tenant_id,
        source_key='priority-second',artifact_hash='c'*64,source_native_id='second'),context=context,
        artifact={'source_path':'priority.txt','file_name':'priority.txt','size_bytes':1})['occurrence_key']
    draft=ClaimDraft(tenant_id=context.tenant_id,assertion_namespace='priority-one',
        subject_type='enterprise',subject_key='group',metric_key='qa.priority',claim_kind='actual',
        production_method='imported',value_numeric=10,unit='SAR',currency='SAR',source_occurrence_keys=(occurrence,))
    first=repo.record_claim(draft,traceability='present')['claim_revision_id']
    second=repo.record_claim(replace(draft,assertion_namespace='priority-two',value_numeric=12,
        source_occurrence_keys=(second_occurrence,)),traceability='present')['claim_revision_id']
    with psycopg.connect(ledger[1]) as conn:
        before=conn.execute('select clock_timestamp()').fetchone()[0]
    query=ClaimQuery(tenant_id=context.tenant_id,metric_key='qa.priority',purpose=context.purpose,
        as_of_at=before,allowed_claim_kinds=frozenset({'actual'}))
    assert all(r['comparison']['requires_resolution'] for r in repo.query(query,context=context))
    decision=PriorityDecision(reference_revision_id=first,ranked_source_keys=(source.source_key,'priority-second'),
        required_assessment=None,expected_policy_version=0,rationale='Synthetic explicit precedence')
    with pytest.raises(PermissionError):record_priority(repo,decision,context=operator)
    saved=record_priority(repo,decision,context=context)
    assert saved['created'] and saved['policy_version']==1
    assert not record_priority(repo,decision,context=context)['created']
    def current():
        return repo.query(replace(query,as_of_at=datetime.now(UTC)),context=context)
    assert [r['claim_revision_id'] for r in current() if r['comparison']['selected_by_priority']]==[first]
    updated=decision.model_copy(update={'ranked_source_keys':('priority-second',source.source_key),'expected_policy_version':1})
    assert record_priority(repo,updated,context=context)['policy_version']==2
    with pytest.raises(PriorityConflict):record_priority(repo,decision,context=context)
    assert [r['claim_revision_id'] for r in current() if r['comparison']['selected_by_priority']]==[second]
    assert all(r['comparison']['requires_resolution'] for r in repo.query(query,context=context))
    with psycopg.connect(ledger[1]) as conn:
        assert conn.execute('select count(*) from strategyos_claim_priority_policies where tenant_id=%s',(context.tenant_id,)).fetchone()[0]==2
        assert conn.execute('select count(*) from strategyos_claim_assessments where tenant_id=%s',(context.tenant_id,)).fetchone()[0]==0
    repo.register_source(second_source,policy=replace(second_policy,allowed_roles=frozenset({'auditor'})),
        recorded_by='steward',rationale='Revoke second origin')
    remaining=current()
    assert len(remaining)==1 and remaining[0]['comparison']['requires_resolution']
    assert remaining[0]['comparison']['status']=='unresolved_source_coverage'
    assert 'Synthetic explicit precedence' not in remaining[0]['comparison']['selection_basis']
    with pytest.raises(ValueError):record_priority(repo,updated.model_copy(update={'expected_policy_version':2}),context=context)
