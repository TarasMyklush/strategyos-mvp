from dataclasses import replace
from datetime import UTC,datetime

import pytest

from strategyos_mvp.source_claims import ClaimDraft,ClaimAssessment,EvidenceOccurrence
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake

pytestmark=pytest.mark.integration


def test_database_rejects_cross_tenant_links_and_wrong_snapshot_families(ledger):
    import psycopg
    repo,context,occurrence,source,policy=setup_intake(ledger)
    with psycopg.connect(ledger[1]) as conn:
        foreign=str(conn.execute("insert into strategyos_tenants(slug,display_name) values ('foreign-constraint-proof','Synthetic foreign tenant') returning id").fetchone()[0])
    other_context=replace(context,tenant_id=foreign)
    repo.register_source(replace(source,tenant_id=foreign),policy=policy,
        recorded_by='qa',rationale='Synthetic foreign fixture')
    foreign_occurrence=repo.record_occurrence(EvidenceOccurrence(tenant_id=foreign,
        source_key=source.source_key,artifact_hash='d'*64,source_native_id='foreign'),
        context=other_context,artifact={'source_path':'foreign.txt','file_name':'foreign.txt','size_bytes':1})['occurrence_key']
    draft=ClaimDraft(tenant_id=context.tenant_id,assertion_namespace='tenant-constraint-proof',
        subject_type='enterprise',subject_key='group',metric_key='qa.tenant',claim_kind='actual',
        production_method='imported',value_numeric=10,unit='SAR',currency='SAR',source_occurrence_keys=(occurrence,))
    first=repo.record_claim(draft,traceability='present',context=context)['claim_revision_id']
    other=repo.record_claim(replace(draft,tenant_id=foreign,source_occurrence_keys=(foreign_occurrence,)),
        traceability='present',context=other_context)['claim_revision_id']
    derived=repo.record_claim(replace(draft,metric_key='qa.tenant.derived',production_method='calculated',
        source_occurrence_keys=(),input_revision_ids=(first,),formula_key='identity',formula_version='1'),
        traceability='present',context=context)['claim_revision_id']
    repo.assess_claim(ClaimAssessment(claim_revision_id=first,assessment_type='validation',result='passed',
        rule_version='qa-only',assessed_by='qa',assessed_at=datetime.now(UTC)),effect_key='qa-constraint-assessment')
    with psycopg.connect(ledger[1]) as conn:
        family=conn.execute('select claim_family_id from strategyos_claim_revisions where id=%s',(first,)).fetchone()[0]
        other_family=conn.execute('select claim_family_id from strategyos_claim_revisions where id=%s',(derived,)).fetchone()[0]
        occurrence_id=conn.execute('select id from strategyos_evidence_occurrences where occurrence_key=%s',(occurrence,)).fetchone()[0]
        foreign_occurrence_id=conn.execute('select id from strategyos_evidence_occurrences where occurrence_key=%s',(foreign_occurrence,)).fetchone()[0]
        snapshot=conn.execute("insert into strategyos_analysis_snapshots(tenant_id,snapshot_key,as_of_at,policy_version,created_by) values (%s,'tenant-proof',now(),'qa','qa') returning id",(context.tenant_id,)).fetchone()[0]
        invalid=[
            ('update strategyos_claim_revisions set tenant_id=%s where id=%s',(foreign,first)),
            ("update strategyos_claim_revisions set claim_kind='plan' where id=%s",(first,)),
            ('update strategyos_claim_revisions set supersedes_revision_id=%s where id=%s',(other,first)),
            ('update strategyos_source_access_policies set tenant_id=%s where tenant_id=%s',(foreign,context.tenant_id)),
            ('update strategyos_source_registration_versions set tenant_id=%s where tenant_id=%s',(foreign,context.tenant_id)),
            ('update strategyos_evidence_occurrences set tenant_id=%s where id=%s',(foreign,occurrence_id)),
            ('update strategyos_claim_assessments set tenant_id=%s where claim_revision_id=%s',(foreign,first)),
            ('update strategyos_claim_projection_outbox set tenant_id=%s where claim_revision_id=%s',(foreign,first)),
            ("insert into strategyos_claim_evidence_links(claim_revision_id,evidence_occurrence_id,relationship_type) values (%s,%s,'supports')",(first,foreign_occurrence_id)),
            ("insert into strategyos_claim_evidence_links(tenant_id,claim_revision_id,evidence_occurrence_id,relationship_type) values (%s,%s,%s,'contradicts')",(foreign,first,foreign_occurrence_id)),
            ("insert into strategyos_claim_dependencies(derived_claim_revision_id,input_claim_revision_id,input_role) values (%s,%s,'qa')",(derived,other)),
            ("insert into strategyos_analysis_snapshot_claims(snapshot_id,claim_family_id,claim_revision_id,selection_reason) values (%s,%s,%s,'qa')",(snapshot,other_family,first)),
            ("insert into strategyos_analysis_snapshot_claims(snapshot_id,claim_family_id,claim_revision_id,selection_reason) select %s,claim_family_id,id,'qa' from strategyos_claim_revisions where id=%s",(snapshot,other)),
            ("insert into strategyos_claim_projection_cache(tenant_id,claim_revision_id,family_key,metric_key,claim_kind,payload) values (%s,%s,'qa','qa','actual','{}')",(foreign,first)),
            ("insert into strategyos_claim_intake_receipts(tenant_id,evidence_occurrence_id,effect_key,mapping_key,mapping_version,mapping_contract,source_hash,recorded_by,result) values (%s,%s,'qa','qa','1','{}','qa','qa','{}')",(foreign,occurrence_id)),
        ]
        for sql,parameters in invalid:
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                with conn.transaction():
                    conn.execute(sql,parameters)
        conn.execute("insert into strategyos_analysis_snapshot_claims(snapshot_id,claim_family_id,claim_revision_id,selection_reason) values (%s,%s,%s,'qa')",(snapshot,family,first))
        assert str(conn.execute('select tenant_id from strategyos_analysis_snapshot_claims where snapshot_id=%s',(snapshot,)).fetchone()[0])==context.tenant_id
        assert str(conn.execute('select tenant_id from strategyos_claim_dependencies where derived_claim_revision_id=%s',(derived,)).fetchone()[0])==context.tenant_id
