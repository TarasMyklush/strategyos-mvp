from dataclasses import replace
from datetime import UTC, datetime

import pytest

from strategyos_mvp.source_claims import ClaimDraft, ClaimAssessment
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake

pytestmark = pytest.mark.integration


def test_revision_and_assessment_changes_require_new_records(ledger):
    import psycopg
    repo, context, occurrence, _, _ = setup_intake(ledger)
    draft = ClaimDraft(tenant_id=context.tenant_id, assertion_namespace='immutable-proof',
        subject_type='enterprise', subject_key='group', metric_key='qa.immutable',
        claim_kind='actual', production_method='imported', value_numeric=10,
        unit='SAR', currency='SAR', source_occurrence_keys=(occurrence,))
    original = repo.record_claim(draft,traceability='present',context=context)['claim_revision_id']
    assessment = ClaimAssessment(claim_revision_id=original,assessment_type='validation',
        result='failed',rule_version='qa:1',assessed_by='qa',assessed_at=datetime.now(UTC))
    repo.assess_claim(assessment,effect_key='immutable-proof')
    with psycopg.connect(ledger[1]) as conn:
        attacks = [
            ('update strategyos_claim_revisions set value_numeric=999 where id=%s',(original,)),
            ("update strategyos_claim_revisions set claim_kind='forecast' where id=%s",(original,)),
            ('delete from strategyos_claim_revisions where id=%s',(original,)),
            ("update strategyos_claim_assessments set result='passed' where claim_revision_id=%s",(original,)),
            ('delete from strategyos_claim_assessments where claim_revision_id=%s',(original,)),
        ]
        for sql, args in attacks:
            with pytest.raises(psycopg.errors.CheckViolation,match='Immutable claim record'):
                with conn.transaction():
                    conn.execute(sql,args)
        assert conn.execute('select value_numeric from strategyos_claim_revisions where id=%s',(original,)).fetchone()[0] == 10
        assert conn.execute('select result from strategyos_claim_assessments where claim_revision_id=%s',(original,)).fetchone()[0] == 'failed'
    corrected = repo.record_claim(replace(draft,value_numeric=12),traceability='present',context=context)
    assert corrected['claim_revision_id'] != original
    assert not repo.record_claim(replace(draft,value_numeric=12),traceability='present',context=context)['created']
