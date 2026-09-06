from dataclasses import replace

import pytest

from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake
from strategyos_mvp.source_claims import EvidenceOccurrence

pytestmark = pytest.mark.integration


def test_create_only_registration_is_idempotent_but_cannot_restore_revoked_rights(ledger):
    repo, context, _, source, policy = setup_intake(ledger)
    replay = repo.register_source(source,policy=policy,recorded_by='operator',rationale='Explicit intake',create_only=True)
    assert not replay['registration_created'] and not replay['policy_created']
    repo.register_source(source,policy=replace(policy,index_allowed=False),recorded_by='steward',rationale='Revocation')
    with pytest.raises(ValueError,match='cannot change its authority'):
        repo.register_source(source,policy=policy,recorded_by='operator',rationale='Stale intake',create_only=True)


def test_atomic_artifact_occurrence_replay_and_conflict_rollback(ledger):
    import psycopg
    repo, context, _, source, policy = setup_intake(ledger)
    evidence = EvidenceOccurrence(tenant_id=context.tenant_id,source_key=source.source_key,
        artifact_hash='d'*64,source_native_id='staged.txt',source_native_version='v1')
    artifact = {'source_path':'staged.txt','file_name':'staged.txt','size_bytes':3,'source_pack_id':'fixture'}
    first = repo.record_occurrence(evidence,context=context,artifact=artifact)
    assert repo.record_occurrence(evidence,context=context,artifact=artifact) == first
    with pytest.raises(ValueError,match='different content'):
        repo.record_occurrence(replace(evidence,artifact_hash='e'*64),context=context,artifact=artifact)
    with psycopg.connect(ledger[1]) as conn, conn.cursor() as cur:
        cur.execute('select count(*) from strategyos_evidence_documents where tenant_id=%s and source_hash=%s',
                    (context.tenant_id,'e'*64))
        assert cur.fetchone()[0] == 0
    repo.register_source(source,policy=replace(policy,storage_allowed=False),recorded_by='steward',rationale='Revocation')
    with pytest.raises(ValueError,match='does not permit storage'):
        repo.record_occurrence(evidence,context=context,artifact=artifact)
