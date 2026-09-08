"""Real ledger + HTTP isolation with colliding metric and BU names."""
from dataclasses import replace
from uuid import uuid4
import pytest
import json
from fastapi.testclient import TestClient

from strategyos_mvp import api, auth, claim_api, claim_store, state_store
from strategyos_mvp.source_claims import ClaimDraft, PolicyContext
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake

pytestmark=pytest.mark.integration


def test_two_tenants_two_units_cannot_resolve_each_others_fact_links(ledger,monkeypatch):
    import psycopg
    repo,url,first=ledger
    with psycopg.connect(url) as conn:
        second=str(conn.execute("insert into strategyos_tenants(slug,display_name) values(%s,'Synthetic tenant') returning id",('http-'+uuid4().hex,)).fetchone()[0])
    entries=[]
    for tenant in (first,second):
        _,operator,occurrence,source,policy=setup_intake((repo,url,tenant))
        repo.register_source(source,policy=replace(policy,allowed_roles=frozenset({'operator','bu'}),
            allowed_purposes=frozenset({'operations','executive_briefing','export'}),export_allowed=True),
            recorded_by='qa',rationale='Isolated synthetic proof')
        for unit in ('east','west'):
            draft=ClaimDraft(tenant_id=tenant,assertion_namespace='http-proof',subject_type='client',subject_key='same-client',
                business_unit=unit,metric_key='finance.revenue',claim_kind='actual',production_method='imported',
                value_numeric=100+len(entries),unit='SAR',currency='SAR',source_occurrence_keys=(occurrence,))
            revision=repo.record_claim(draft,traceability='present',context=operator)['claim_revision_id']
            run=str(uuid4())
            with psycopg.connect(url) as conn:
                summary={'run_id':run,'tenant_context':{'tenant_id':tenant},'business_units':[unit],
                         'status':'completed','run_mode':'full'}
                conn.execute("""insert into strategyos_runs(id,run_dir,dataset_root,finding_count,
                    locked_finding_count,total_recoverable_sar,status,summary_json,tenant_key,business_unit_scope)
                    values(%s,'isolated-proof','isolated-proof',0,0,0,'completed',%s::jsonb,%s,%s::jsonb)""",
                    (run,json.dumps(summary),tenant,json.dumps([unit])))
                sid=conn.execute("insert into strategyos_analysis_snapshots(tenant_id,snapshot_key,as_of_at,policy_version,created_by) values(%s,%s,now(),'qa','qa') returning id",(tenant,'run:'+run)).fetchone()[0]
                conn.execute("insert into strategyos_analysis_snapshot_claims(snapshot_id,claim_family_id,claim_revision_id,selection_reason) select %s,claim_family_id,id,'qa' from strategyos_claim_revisions where id=%s",(sid,revision))
            entries.append((tenant,unit,run,revision))
    monkeypatch.setattr(claim_api,'ClaimRepository',lambda:repo)
    monkeypatch.setattr(claim_store,'ClaimRepository',lambda:repo)
    monkeypatch.setattr(state_store,'database_connection',lambda:(psycopg.connect(url),None))
    selected={}
    monkeypatch.setattr(auth,'authenticate_optional_request',lambda **kwargs:selected)
    from strategyos_mvp import claim_read_batch
    original_batch=claim_read_batch.load_leaf_batch
    def checked_batch(cur,rows,**kwargs):
        assert all(str(row['tenant_id'])==selected['tenant_id'] for row in rows)
        assert all(row['business_unit'] in selected['business_units'] for row in rows), 'Foreign BU values reached provenance loading'
        return original_batch(cur,rows,**kwargs)
    monkeypatch.setattr(claim_read_batch,'load_leaf_batch',checked_batch)

    overrides=dict(api.app.dependency_overrides)
    api.app.dependency_overrides[auth.authenticate_request]=lambda:selected
    try:
        client=TestClient(api.app)
        for tenant,unit,run,revision in entries:
            selected.update(tenant_id=tenant,subject='same-user',role='bu',authenticated=True,business_units=[unit])
            for other_tenant,other_unit,other_run,other_revision in entries:
                response=client.get(f'/api/claims/snapshots/{other_run}/revisions/{other_revision}')
                allowed=(tenant,unit)==(other_tenant,other_unit)
                assert response.status_code==(200 if allowed else 404),response.text
                if allowed:
                    assert response.json()['record']['claim_revision_id']==revision
                else:
                    assert other_revision not in response.text and 'same-client' not in response.text
                    for suffix in ('', '/artifacts/board_pack_pdf'):
                        blocked=client.get(f'/bu/runs/{other_run}'+suffix)
                        assert blocked.status_code in {403,404},blocked.text
                    for endpoint in ('/qa','/assistant/chat'):
                        blocked=client.post(endpoint,json={'run_id':other_run,'persona':'gm',
                            'question':'Show revenue','mode':'deterministic'})
                        assert blocked.status_code in {403,404},blocked.text
            for requested_unit in ('east','west'):
                response=client.get('/api/claims',params={'metric_key':'finance.revenue','business_unit':requested_unit})
                assert response.status_code==200,response.text
                found={row['claim_revision_id'] for row in response.json()['records']}
                assert found==({revision} if requested_unit==unit else set())
            # Export uses the same identity binding and cannot widen a BU.
            response=client.get('/api/claims',params={'metric_key':'finance.revenue',
                'business_unit':'west' if unit=='east' else 'east','purpose':'export'})
            assert response.status_code==200 and response.json()['records']==[]
            # Swapping a valid reference into the wrong snapshot must also fail.
            other=next(item for item in entries if item[3]!=revision)
            assert client.get(f'/api/claims/snapshots/{run}/revisions/{other[3]}').status_code==404
        selected['business_units']=[]
        assert client.get(f'/api/claims/snapshots/{run}/revisions/{revision}').status_code==403
        # Even internal callers cannot turn a missing BU scope into group access.
        context=PolicyContext(tenant_id=tenant,principal_id='no-bu',roles=frozenset({'bu'}),purpose='executive_briefing')
        assert repo.snapshot('run:'+run,context=context)['records']==[]
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(overrides)
