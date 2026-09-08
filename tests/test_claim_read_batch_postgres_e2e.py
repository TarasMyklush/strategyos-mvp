"""Batching must preserve the reference read contract and current revocation."""
from dataclasses import replace
from datetime import datetime, UTC
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake
from strategyos_mvp.source_claims import ClaimDraft, ClaimQuery
from strategyos_mvp.claim_store import ClaimRepository


def test_leaf_batch_matches_reference_reads_with_constant_round_trips(ledger,monkeypatch):
    import psycopg
    from strategyos_mvp import claim_read_batch
    repo,context,occurrence,source,policy=setup_intake(ledger)
    base=ClaimDraft(tenant_id=context.tenant_id,assertion_namespace='batch-proof',subject_type='invoice',
        subject_key='first',metric_key='finance.invoice.amount',claim_kind='actual',production_method='imported',
        value_numeric=120,unit='SAR',currency='SAR',source_occurrence_keys=(occurrence,))
    ids=[]
    for index in range(30):
        ids.append(repo.record_claim(replace(base,subject_key=str(index),value_numeric=index),
            traceability='present',context=context)['claim_revision_id'])
    at=datetime.now(UTC)
    query=ClaimQuery(context.tenant_id,base.metric_key,'operations',at,frozenset({'actual'}))
    commands=[]
    class CountCursor(psycopg.Cursor):
        def execute(self,query,params=None,**kwargs):
            commands.append(str(query))
            return super().execute(query,params,**kwargs)
    def connect():
        return psycopg.connect(ledger[1],cursor_factory=CountCursor),None
    measured=ClaimRepository(connect)
    measured._schema_ready=True  # The ledger fixture has already applied the schema.
    actual=measured.query(query,context=context)
    assert len(actual)==30
    assert len(commands)<20, f'Per-claim database reads returned: {len(commands)} statements'
    with monkeypatch.context() as reference:
        reference.setattr(claim_read_batch,'load_leaf_batch',lambda *args,**kwargs:{})
        expected=repo.query(query,context=context)
    assert actual==expected
    snapshot_key='batch:'+context.tenant_id
    with psycopg.connect(ledger[1]) as conn:
        sid=conn.execute("insert into strategyos_analysis_snapshots(tenant_id,snapshot_key,as_of_at,policy_version,created_by) values(%s,%s,%s,'test','qa') returning id",(context.tenant_id,snapshot_key,at)).fetchone()[0]
        conn.execute("insert into strategyos_analysis_snapshot_claims(snapshot_id,claim_family_id,claim_revision_id,selection_reason) select %s,claim_family_id,id,'test' from strategyos_claim_revisions where id=any(%s::uuid[])",(sid,ids))
    commands.clear()
    actual_snapshot=measured.snapshot(snapshot_key,context=context)
    assert len(actual_snapshot['records'])==30
    assert len(commands)<30
    with monkeypatch.context() as reference:
        reference.setattr(claim_read_batch,'load_leaf_batch',lambda *args,**kwargs:{})
        assert actual_snapshot==repo.snapshot(snapshot_key,context=context)
    # A previous successful batch must never become a permission cache.
    repo.register_source(source,policy=replace(policy,allowed_roles=frozenset({'reviewer'})),
        recorded_by='qa',rationale='Synthetic revocation proof')
    assert measured.query(query,context=context)==[]
