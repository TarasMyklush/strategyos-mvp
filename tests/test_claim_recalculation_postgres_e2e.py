from dataclasses import replace
from decimal import Decimal

import pytest

from strategyos_mvp.claim_recalculation import recalculate
from strategyos_mvp.source_claims import ClaimDraft
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake

pytestmark = pytest.mark.integration


def calculation(ledger):
    repo,context,occurrence,source,policy = setup_intake(ledger)
    raw = ClaimDraft(tenant_id=context.tenant_id,assertion_namespace='recompute-test',
        subject_type='enterprise',subject_key='group',metric_key='test.raw',
        claim_kind='actual',production_method='imported',value_numeric=10,
        unit='SAR',currency='SAR',source_occurrence_keys=(occurrence,))
    first = repo.record_claim(raw,traceability='present')
    derived = replace(raw,metric_key='test.derived',production_method='calculated',
        source_occurrence_keys=(),formula_key='identity',formula_version='1',
        input_revision_ids=(first['claim_revision_id'],))
    second = repo.record_claim(derived,traceability='present')
    root = repo.record_claim(replace(derived,metric_key='test.headline',
        input_revision_ids=(second['claim_revision_id'],)),traceability='present')
    repo.record_claim(replace(raw,value_numeric=12),traceability='present')
    return repo,context,root['claim_revision_id'],raw,source,policy


def test_preview_apply_and_retry_never_duplicate_or_approve(ledger):
    import psycopg
    repo,context,root,_,source,policy = calculation(ledger)
    args = dict(context=context,rationale='Use the corrected source revision')
    preview = recalculate(repo,root,**args)
    assert preview['created_count'] == 0 and len(preview['changes']) == 2
    assert {item['proposed_value'] for item in preview['changes']} == {'12'}
    with psycopg.connect(ledger[1]) as conn:
        assert conn.execute('select count(*) from strategyos_claim_revisions where tenant_id=%s',(context.tenant_id,)).fetchone()[0] == 4
    applied = recalculate(repo,root,expected_preview=preview['preview_key'],**args)
    assert applied['created_count'] == 2 and applied['review_status'] == 'unreviewed'
    assert not applied['snapshot_changed'] and not applied['outbound_delivery']
    replay = recalculate(repo,root,expected_preview=preview['preview_key'],**args)
    assert replay['created_count'] == 0 and replay['replayed']
    assert replay['claim_revision_id'] == applied['claim_revision_id']
    with psycopg.connect(ledger[1]) as conn:
        for table,count in [('strategyos_claim_revisions',6),('strategyos_claim_recalculation_receipts',1),('strategyos_claim_assessments',0),('strategyos_analysis_snapshots',0)]:
            assert conn.execute(f'select count(*) from {table} where tenant_id=%s',(context.tenant_id,)).fetchone()[0] == count
    repo.register_source(source,policy=replace(policy,allowed_roles=frozenset({'auditor'})),recorded_by='steward',rationale='Revoke operator')
    with pytest.raises(ValueError,match='Source policy'):
        recalculate(repo,root,expected_preview=preview['preview_key'],**args)


def test_changed_inputs_invalidate_preview_without_writing(ledger):
    repo,context,root,raw,_,_ = calculation(ledger)
    args = dict(context=context,rationale='Correct source inputs')
    preview = recalculate(repo,root,**args)
    repo.record_claim(replace(raw,value_numeric=Decimal(13)),traceability='present')
    with pytest.raises(ValueError,match='changed'):
        recalculate(repo,root,expected_preview=preview['preview_key'],**args)
    assert recalculate(repo,root,**args)['changes'][-1]['proposed_value'] == '13'


def test_policy_regrant_requires_a_new_preview_even_if_rights_match(ledger):
    repo,context,root,_,source,policy = calculation(ledger)
    args = dict(context=context,rationale='Recheck policy revision')
    preview = recalculate(repo,root,**args)
    repo.register_source(source,policy=replace(policy,index_allowed=False),recorded_by='steward',rationale='Temporary restriction')
    repo.register_source(source,policy=policy,recorded_by='steward',rationale='Restore explicit rights')
    with pytest.raises(ValueError,match='changed'):
        recalculate(repo,root,expected_preview=preview['preview_key'],**args)


def test_latest_family_cycle_cannot_be_recalculated(ledger):
    repo,context,root,raw,_,_ = calculation(ledger)
    repo.record_claim(replace(raw,production_method='calculated',source_occurrence_keys=(),
        formula_key='identity',formula_version='1',input_revision_ids=(root,)),traceability='present')
    with pytest.raises(ValueError,match='cycle'):
        recalculate(repo,root,context=context,rationale='Must not chase a cyclic family graph')


def test_recalculation_rolls_back_all_children_and_receipt_on_failure(ledger,monkeypatch):
    import psycopg
    repo,context,root,_,_,_ = calculation(ledger)
    args = dict(context=context,rationale='Atomic correction')
    preview = recalculate(repo,root,**args)
    original,calls = repo._write_claim,[]
    def fail_second(*args,**kwargs):
        if calls:
            raise ValueError('Injected failure')
        calls.append(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(repo,'_write_claim',fail_second)
    with pytest.raises(ValueError,match='Injected'):
        recalculate(repo,root,expected_preview=preview['preview_key'],**args)
    with psycopg.connect(ledger[1]) as conn:
        assert conn.execute('select count(*) from strategyos_claim_revisions where tenant_id=%s',(context.tenant_id,)).fetchone()[0] == 4
        assert conn.execute('select count(*) from strategyos_claim_recalculation_receipts where tenant_id=%s',(context.tenant_id,)).fetchone()[0] == 0


def test_executive_cannot_recompute_by_calling_service_directly(ledger):
    repo,context,root,_,_,_ = calculation(ledger)
    with pytest.raises(PermissionError,match='Operator'):
        recalculate(repo,root,context=replace(context,roles=frozenset({'executive'})),rationale='No authority')


def test_receipt_cannot_reference_another_tenants_revision(ledger):
    import psycopg
    from uuid import uuid4
    _,_,root,_,_,_ = calculation(ledger)
    with psycopg.connect(ledger[1]) as conn:
        other = conn.execute("insert into strategyos_tenants(slug,display_name) values(%s,'Other fixture') returning id",(str(uuid4()),)).fetchone()[0]
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute("""insert into strategyos_claim_recalculation_receipts
                (tenant_id,source_claim_revision_id,effect_key,preview_key,recorded_by,rationale,result)
                values (%s,%s,'cross-tenant','preview','test','Must fail','{}')""",(other,root))


def test_new_revision_time_is_recording_time_not_transaction_start(ledger):
    import psycopg
    repo,context,_,raw,_,_ = calculation(ledger)
    with psycopg.connect(ledger[1]) as conn,conn.cursor() as cur:
        cur.execute('select transaction_timestamp()')
        started = cur.fetchone()[0]
        recorded = repo._write_claim(cur,replace(raw,value_numeric=14),traceability='present',
            evidence_relationship='supports',context=context)
        cur.execute('select recorded_at from strategyos_claim_revisions where id=%s',(recorded['claim_revision_id'],))
        assert cur.fetchone()[0] > started
