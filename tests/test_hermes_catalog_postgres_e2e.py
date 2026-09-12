"""The semantic directory cannot broaden tenant, domain or source permissions."""
from dataclasses import replace
from datetime import datetime, UTC
from uuid import uuid4
import pytest
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake
from strategyos_mvp.source_claims import ClaimDraft, UsePurpose

pytestmark = pytest.mark.integration


def test_complete_catalog_is_scoped_and_revocation_is_immediate(ledger):
    import psycopg
    repo, context, occurrence, source, policy = setup_intake(ledger)
    policy = replace(policy, external_model_allowed=True,
        allowed_purposes=frozenset({UsePurpose.OPERATIONS, UsePurpose.EXTERNAL_MODEL}))
    repo.register_source(source, policy=policy, recorded_by='test', rationale='Model directory test')
    base = ClaimDraft(tenant_id=context.tenant_id, assertion_namespace='directory-proof',
        subject_type='group', subject_key='group', metric_key='ceo.ebitda',
        claim_kind='actual', production_method='imported', value_numeric=617, unit='SAR',
        currency='SAR', business_unit='east', source_occurrence_keys=(occurrence,))
    ids = [repo.record_claim(replace(base, metric_key=metric), traceability='present', context=context)['claim_revision_id']
           for metric in ('ceo.ebitda', 'newly_ingested.unexpected_metric')]
    run_id = str(uuid4())
    with psycopg.connect(ledger[1]) as conn:
        sid = conn.execute("insert into strategyos_analysis_snapshots(tenant_id,snapshot_key,as_of_at,policy_version,created_by) values(%s,%s,%s,'test','qa') returning id",
            (context.tenant_id, 'run:'+run_id, datetime.now(UTC))).fetchone()[0]
        conn.execute("insert into strategyos_analysis_snapshot_claims(snapshot_id,claim_family_id,claim_revision_id,selection_reason) select %s,claim_family_id,id,'test' from strategyos_claim_revisions where id=any(%s::uuid[])", (sid,ids))
    external = replace(context, purpose=UsePurpose.EXTERNAL_MODEL)
    catalog = repo.snapshot_metric_catalog(run_id, context=external)
    assert {item['metric_key'] for item in catalog} == {'ceo.ebitda', 'newly_ingested.unexpected_metric'}
    assert sum(item['record_count'] for item in catalog) == 2
    finance = repo.snapshot_metric_catalog(run_id, context=replace(external, allowed_domains=frozenset({'finance'})))
    assert {item['metric_key'] for item in finance} == {'ceo.ebitda'}
    with psycopg.connect(ledger[1]) as conn:
        other = str(conn.execute("insert into strategyos_tenants(slug,display_name) values(%s,'Other') returning id", ('other-'+str(uuid4()),)).fetchone()[0])
    with pytest.raises(PermissionError):
        repo.snapshot_metric_catalog(run_id, context=replace(external, tenant_id=other))
    repo.register_source(source, policy=replace(policy, external_model_allowed=False),
        recorded_by='test', rationale='Consent revoked')
    with pytest.raises(PermissionError):
        repo.snapshot_metric_catalog(run_id, context=external)


def test_record_type_scope_keeps_all_matching_rows_and_unfiltered_headlines(ledger):
    import psycopg
    repo, context, occurrence, source, policy = setup_intake(ledger)
    base = ClaimDraft(tenant_id=context.tenant_id, assertion_namespace='type-scope-proof',
        subject_type='ar_invoice', subject_key='AR-1', metric_key='finance.transaction.amount',
        claim_kind='actual', production_method='imported', value_numeric=100, unit='SAR', currency='SAR',
        business_unit='east', source_occurrence_keys=(occurrence,))
    drafts = [replace(base, subject_key=f'AR-{number}') for number in range(85)]
    drafts += [replace(base, subject_type='ap_invoice', subject_key='AP-1'),
               replace(base, subject_type='enterprise', subject_key='group', metric_key='ceo.revenue')]
    ids = [repo.record_claim(draft, traceability='present', context=context)['claim_revision_id'] for draft in drafts]
    run_id = str(uuid4())
    with psycopg.connect(ledger[1]) as conn:
        sid = conn.execute("insert into strategyos_analysis_snapshots(tenant_id,snapshot_key,as_of_at,policy_version,created_by) values(%s,%s,%s,'test','qa') returning id",
            (context.tenant_id, 'run:'+run_id, datetime.now(UTC))).fetchone()[0]
        conn.execute("insert into strategyos_analysis_snapshot_claims(snapshot_id,claim_family_id,claim_revision_id,selection_reason) select %s,claim_family_id,id,'test' from strategyos_claim_revisions where id=any(%s::uuid[])", (sid,ids))
    result = repo.snapshot('run:'+run_id, context=context,
        metric_keys=['finance.transaction.amount', 'ceo.revenue'],
        metric_subject_types={'finance.transaction.amount': ['ar_invoice']})
    assert len(result['records']) == 86  # Every AR row, including those beyond 80, plus the headline.
    assert {record['subject']['type'] for record in result['records']} == {'ar_invoice', 'enterprise'}
    assert all(record['subject']['key'] != 'AP-1' for record in result['records'])
    injected = repo.snapshot('run:'+run_id, context=context, metric_keys=['finance.transaction.amount'],
        metric_subject_types={'finance.transaction.amount': ["ar_invoice' OR true --"]})
    assert injected['records'] == []
    repo.register_source(source, policy=replace(policy, allowed_roles=frozenset({'auditor'})),
        recorded_by='test', rationale='Revoke reader role')
    denied = repo.snapshot('run:'+run_id, context=context,
        metric_subject_types={'finance.transaction.amount': ['ar_invoice']})
    assert denied['records'] == [] and denied['policy_denied_count'] > 0
