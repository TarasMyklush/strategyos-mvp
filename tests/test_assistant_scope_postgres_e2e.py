from dataclasses import replace
from datetime import datetime, UTC
from types import SimpleNamespace
from uuid import uuid4

from strategyos_mvp.assistant_scope import bind_assistant
from strategyos_mvp.authority_matrix import default_authority_matrix
from strategyos_mvp.source_claims import ClaimDraft, ClaimQuery
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake


def test_assistant_domain_filters_snapshot_before_source_loading_and_checks_lineage(ledger, monkeypatch):
    import psycopg
    repo, context, occurrence, source, policy = setup_intake(ledger)
    repo.register_source(source, policy=replace(policy, allowed_roles=frozenset({'operator','executive'}),
        allowed_purposes=frozenset({'operations','executive_briefing'})), recorded_by='qa', rationale='Synthetic source grant')
    base=ClaimDraft(tenant_id=context.tenant_id,assertion_namespace='authority-proof',subject_type='enterprise',
        subject_key='group',metric_key='finance.revenue',claim_kind='actual',production_method='imported',
        value_numeric=120,unit='SAR',currency='SAR',source_occurrence_keys=(occurrence,))
    finance=repo.record_claim(base,traceability='present',context=context)['claim_revision_id']
    hr=repo.record_claim(replace(base,metric_key='hr.salary',value_numeric=999),traceability='present',context=context)['claim_revision_id']
    derived=repo.record_claim(replace(base,metric_key='finance.derived',value_numeric=999,
        production_method='calculated',source_occurrence_keys=(),input_revision_ids=(hr,),formula_key='identity',formula_version='1'),
        traceability='present',context=context)['claim_revision_id']
    snapshot='domain-'+uuid4().hex
    with psycopg.connect(ledger[1]) as conn:
        sid=conn.execute("insert into strategyos_analysis_snapshots(tenant_id,snapshot_key,as_of_at,policy_version,created_by) values (%s,%s,now(),'qa','qa') returning id",(context.tenant_id,snapshot)).fetchone()[0]
        conn.execute("insert into strategyos_analysis_snapshot_claims(snapshot_id,claim_family_id,claim_revision_id,selection_reason) select %s,claim_family_id,id,'qa' from strategyos_claim_revisions where id=any(%s::uuid[])",(sid,[finance,hr,derived]))
    original=repo._source_details
    def source_details(cur,revision,**kwargs):
        assert str(revision) not in {hr,derived}, 'Restricted source or derivative was loaded'
        return original(cur,revision,**kwargs)
    monkeypatch.setattr(repo,'_source_details',source_details)
    with bind_assistant(SimpleNamespace(persona='cfo'),{'subject':'cfo'},default_authority_matrix()):
        reader=replace(context,roles=frozenset({'executive'}),purpose='executive_briefing')
        result=repo.snapshot(snapshot,context=reader)
        assert {r['claim_revision_id'] for r in result['records']}=={finance}
        denied=repo.query(ClaimQuery(context.tenant_id,'hr.salary','executive_briefing',datetime.now(UTC),frozenset({'actual'})),context=reader)
        assert denied==[]
    monkeypatch.setattr(repo,'_source_details',original)
    reader=replace(context,roles=frozenset({'executive'}),purpose='executive_briefing')
    assert {r['claim_revision_id'] for r in repo.snapshot(snapshot,context=reader)['records']}=={finance,hr,derived}
