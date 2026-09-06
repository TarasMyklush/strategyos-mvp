from dataclasses import replace
from datetime import UTC, datetime

import pytest

from strategyos_mvp.source_claims import ClaimDraft,ClaimQuery,EvidenceOccurrence
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake

pytestmark = pytest.mark.integration


def test_shortlist_cannot_hide_an_authorized_conflict_but_revocation_does(ledger,monkeypatch):
    repo,context,occurrence,source,policy = setup_intake(ledger)
    source2 = replace(source,source_key='second-source')
    policy2 = replace(policy,source_key='second-source')
    repo.register_source(source2,policy=policy2,recorded_by='steward',rationale='Synthetic competing source')
    second_occurrence=repo.record_occurrence(EvidenceOccurrence(tenant_id=context.tenant_id,
        source_key='second-source',artifact_hash='b'*64,source_native_id='second-document'),
        context=context,artifact={'source_path':'second.txt','file_name':'second.txt','size_bytes':1})['occurrence_key']
    draft=ClaimDraft(tenant_id=context.tenant_id,assertion_namespace='source-one',
        subject_type='enterprise',subject_key='group',metric_key='qa.conflict',claim_kind='actual',
        production_method='imported',value_numeric=10,unit='SAR',currency='SAR',source_occurrence_keys=(occurrence,))
    first=repo.record_claim(draft,traceability='present')['claim_revision_id']
    second=repo.record_claim(replace(draft,assertion_namespace='source-two',value_numeric=12,
        source_occurrence_keys=(second_occurrence,)),traceability='present')['claim_revision_id']
    unrelated=repo.record_claim(replace(draft,subject_key='unrelated-enterprise',value_numeric=999),
        traceability='present')['claim_revision_id']
    query=ClaimQuery(tenant_id=context.tenant_id,metric_key='qa.conflict',purpose=context.purpose,
        as_of_at=datetime.now(UTC),allowed_claim_kinds=frozenset({'actual'}))
    result=repo.query(query,context=context,revision_ids=[first])
    assert len(result)==1 and result[0]['comparison']['requires_resolution']
    assert result[0]['comparison']['authorized_competing_revisions']==[second]
    scoped=repo.query(query,context=context,subject_scopes=[('enterprise','group')])
    assert {row['claim_revision_id'] for row in scoped}=={first,second}
    assert all(row['comparison']['requires_resolution'] for row in scoped)
    assert repo.query(query,context=context,subject_scopes=[])==[]
    import psycopg
    with psycopg.connect(ledger[1]) as conn:
        snapshot_id=conn.execute('''insert into strategyos_analysis_snapshots
            (tenant_id,snapshot_key,as_of_at,policy_version,created_by)
            values (%s,'conflict-snapshot',%s,'test','test') returning id''',
            (context.tenant_id,query.as_of_at)).fetchone()[0]
        conn.execute('''insert into strategyos_analysis_snapshot_claims
            (snapshot_id,claim_family_id,claim_revision_id,selection_reason)
            select %s,claim_family_id,id,'Frozen single selection' from strategyos_claim_revisions where id=%s''',
            (snapshot_id,first))
    hydrated=[]
    original=repo._hydrate_claim
    def tracking(row):
        claim=original(row)
        hydrated.append(claim.revision_id)
        return claim
    monkeypatch.setattr(repo,'_hydrate_claim',tracking)
    frozen=repo.snapshot('conflict-snapshot',context=context,limit=1)
    assert unrelated not in hydrated  # Database scope filter precedes hydration.
    monkeypatch.setattr(repo,'_hydrate_claim',original)
    assert frozen['requires_resolution']
    assert frozen['records'][0]['claim_revision_id']==first
    assert frozen['records'][0]['comparison']['authorized_competing_revisions']==[second]
    # New revisions cannot retroactively erase an analysis-time disagreement.
    repo.record_claim(replace(draft,assertion_namespace='source-two',value_numeric=10,
        source_occurrence_keys=(second_occurrence,)),traceability='present')
    assert repo.snapshot('conflict-snapshot',context=context)['requires_resolution']
    repo.register_source(source2,policy=replace(policy2,allowed_roles=frozenset({'auditor'})),
        recorded_by='steward',rationale='Revoke competing-source visibility')
    result=repo.query(query,context=context,revision_ids=[first])
    assert result[0]['comparison']['status']=='single_claim'
    assert result[0]['comparison']['authorized_competing_revisions']==[]
    frozen=repo.snapshot('conflict-snapshot',context=context)
    assert not frozen['requires_resolution']
    assert frozen['records'][0]['comparison']['authorized_competing_revisions']==[]
