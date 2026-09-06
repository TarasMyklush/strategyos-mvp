from dataclasses import replace
from uuid import uuid4

import pytest

from strategyos_mvp import board_api, board_memory, claim_store
from strategyos_mvp.source_claims import ClaimDraft
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake

pytestmark = pytest.mark.integration


def test_frozen_board_rechecks_current_rights_without_rewriting_history(ledger, monkeypatch):
    import psycopg
    repo, context, occurrence, source, policy = setup_intake(ledger)
    monkeypatch.setattr(claim_store, 'ClaimRepository', lambda: repo)
    monkeypatch.setattr(board_memory.state_store, 'database_connection', lambda: (psycopg.connect(ledger[1]), None))
    draft = ClaimDraft(tenant_id=context.tenant_id, assertion_namespace='board-source-proof',
        subject_type='enterprise', subject_key='group', metric_key='qa.board.amount',
        claim_kind='actual', production_method='imported', value_numeric=100, unit='SAR', currency='SAR',
        source_occurrence_keys=(occurrence,))
    revision = repo.record_claim(draft, traceability='present', context=context)['claim_revision_id']
    run, meeting = str(uuid4()), str(uuid4())
    with psycopg.connect(ledger[1]) as conn:
        snapshot = conn.execute("insert into strategyos_analysis_snapshots(tenant_id,snapshot_key,as_of_at,policy_version,created_by) values(%s,%s,now(),'qa','qa') returning id", (context.tenant_id, 'run:'+run)).fetchone()[0]
        conn.execute("insert into strategyos_analysis_snapshot_claims(snapshot_id,claim_family_id,claim_revision_id,selection_reason) select %s,claim_family_id,id,'qa' from strategyos_claim_revisions where id=%s", (snapshot, revision))
    board_memory.close_meeting(context.tenant_id, meeting, run_id=run, actor='qa',
        approved_context={'approved_answers': {'Revenue?': 'SAR 100'}},
        files={'qa.txt': b'synthetic only'}, authority={'version': 'qa-only'})
    principal = {'tenant_id':context.tenant_id,'subject':'qa-ceo','role':'executive'}
    with pytest.raises(PermissionError):
        board_memory.read_meeting(context.tenant_id, meeting, principal=principal)
    readable = replace(policy, allowed_roles=frozenset({'executive','operator'}),
        allowed_purposes=frozenset({'executive_briefing','operations','export'}), export_allowed=False)
    repo.register_source(source, policy=readable, recorded_by='qa', rationale='QA read, no export')
    original = board_memory.read_meeting(context.tenant_id, meeting, principal=principal)
    assert [row['meeting_id'] for row in board_api.meetings(principal=principal)['meetings']]==[meeting]
    assert board_memory.answer_from_snapshot(original, 'Revenue?')['answer']=='SAR 100'
    with pytest.raises(PermissionError):
        board_memory.read_meeting(context.tenant_id, meeting, principal=principal, purpose='export')
    repo.record_claim(replace(draft,value_numeric=110), traceability='present', context=context)
    assert board_memory.read_meeting(context.tenant_id, meeting, principal=principal)==original
    with pytest.raises(PermissionError):
        board_memory.read_meeting(context.tenant_id, meeting, principal=principal, purpose='export')
    repo.register_source(source, policy=replace(readable,export_allowed=True), recorded_by='qa', rationale='QA export grant')
    assert board_memory.read_meeting(context.tenant_id, meeting, principal=principal,purpose='export')==original
    repo.register_source(source, policy=replace(readable,allowed_roles=frozenset({'operator'})), recorded_by='qa', rationale='QA revoke read')
    with pytest.raises(PermissionError):
        board_memory.read_meeting(context.tenant_id, meeting, principal=principal)
    assert board_api.meetings(principal=principal)=={'meetings': []}
    # Reauthorization never modifies the immutable archive.
    assert board_memory.read_meeting(context.tenant_id, meeting)==original
