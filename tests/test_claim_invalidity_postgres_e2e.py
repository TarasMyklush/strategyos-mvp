from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from strategyos_mvp.source_claims import ClaimAssessment, ClaimDraft, ClaimQuery
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake

pytestmark = pytest.mark.integration


def test_invalid_input_blocks_direct_derived_snapshot_and_whole_run(ledger, monkeypatch):
    import psycopg
    repo, context, occurrence, source, policy = setup_intake(ledger)
    draft = ClaimDraft(tenant_id=context.tenant_id,assertion_namespace='invalidity-proof',
        subject_type='enterprise',subject_key='group',metric_key='qa.invalidity',
        claim_kind='actual',production_method='imported',value_numeric=100,
        unit='SAR',currency='SAR',source_occurrence_keys=(occurrence,))
    first = repo.record_claim(draft,traceability='present',context=context)['claim_revision_id']
    derived = repo.record_claim(replace(draft,metric_key='qa.invalidity.derived',
        production_method='calculated',source_occurrence_keys=(),input_revision_ids=(first,),
        formula_key='identity',formula_version='1'),traceability='present',context=context)['claim_revision_id']
    run = str(uuid4())
    with psycopg.connect(ledger[1]) as conn:
        snapshot = conn.execute("INSERT INTO strategyos_analysis_snapshots(tenant_id,snapshot_key,as_of_at,policy_version,created_by) VALUES(%s,%s,now(),'qa','qa') RETURNING id",(context.tenant_id,'run:'+run)).fetchone()[0]
        conn.execute("INSERT INTO strategyos_analysis_snapshot_claims(snapshot_id,claim_family_id,claim_revision_id,selection_reason) SELECT %s,claim_family_id,id,'qa' FROM strategyos_claim_revisions WHERE id=ANY(%s::uuid[])",(snapshot,[first,derived]))
    query = ClaimQuery(tenant_id=context.tenant_id,metric_key=draft.metric_key,
        allowed_claim_kinds=frozenset({'actual'}),purpose=context.purpose,as_of_at=datetime.now(UTC))
    assert repo.query(query,context=context)
    assert repo.run_source_access(run,context=context)['allowed']
    assessment = ClaimAssessment(claim_revision_id=first,assessment_type='validation',
        result='failed',rule_version='semantic-v2',assessed_by='system:semantic-validator',
        assessed_at=datetime.now(UTC),reasons=('Mixed Actual/Est cannot be certified as actual.',))
    receipt = repo.assess_claim(assessment,effect_key='qa-invalidity:'+first)
    assert receipt['created']
    assert not repo.assess_claim(assessment,effect_key='qa-invalidity:'+first)['created']
    assert repo.query(query,context=context)==[]
    assert repo.query(replace(query,metric_key='qa.invalidity.derived'),context=context)==[]
    assert repo.snapshot('run:'+run,context=context)['records']==[]
    assert 'bulk_invalid_evidence' in repo.run_source_access(run,context=context)['reasons']
    with psycopg.connect(ledger[1]) as conn:
        values=conn.execute('SELECT value_numeric FROM strategyos_claim_revisions WHERE id=ANY(%s::uuid[])',([first,derived],)).fetchall()
        members=conn.execute('SELECT count(*) FROM strategyos_analysis_snapshot_claims WHERE snapshot_id=%s',(snapshot,)).fetchone()[0]
    assert values==[(100,),(100,)]
    assert members==2  # Eligibility changed; immutable history did not.
    from strategyos_mvp import finance_semantics_audit as audit, claim_store
    monkeypatch.setattr(audit,'database_connection',lambda:(psycopg.connect(ledger[1]),None))
    monkeypatch.setattr(claim_store,'ClaimRepository',lambda:repo)
    # Source byte verification has separate parser tests; here the real ledger
    # proves repeated negative assessments preserve their event identity/time.
    monkeypatch.setattr(audit,'audit_run',lambda _: {'audit_digest':'fixture-digest',
        'source_semantics_version':'2','approved_snapshot_modified':False,
        'review_required':[{'claim_revision_id':first,'reason':'Mixed Actual/Est'}]})
    applied = audit.record_invalidity(run,expected_audit_digest='fixture-digest')
    retried = audit.record_invalidity(run,expected_audit_digest='fixture-digest')
    assert applied['assessments'][0]['created']
    assert not retried['assessments'][0]['created']
    assert applied['assessments'][0]['assessment_id']==retried['assessments'][0]['assessment_id']
    assert not applied['source_values_reclassified']
    assert not applied['analysis_published']
