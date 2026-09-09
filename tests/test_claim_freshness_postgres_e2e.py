from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from strategyos_mvp.source_claims import ClaimDraft, ClaimQuery
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake

pytestmark = pytest.mark.integration


def test_exact_expiry_applies_to_inputs_and_calculated_descendants(ledger):
    repo, context, occurrence, _, _ = setup_intake(ledger)
    deadline = datetime.now(UTC) + timedelta(days=1)
    raw = ClaimDraft(tenant_id=context.tenant_id, assertion_namespace='expiry-proof',
        subject_type='enterprise', subject_key='group', metric_key='expiry.raw',
        claim_kind='actual', production_method='imported', value_numeric=10,
        unit='SAR', currency='SAR', valid_until=deadline,
        source_occurrence_keys=(occurrence,))
    first = repo.record_claim(raw, traceability='present')
    repo.record_claim(replace(raw, metric_key='expiry.derived', valid_until=None,
        production_method='calculated', source_occurrence_keys=(),
        input_revision_ids=(first['claim_revision_id'],), formula_key='identity',
        formula_version='1'), traceability='present')
    for metric in ('expiry.raw', 'expiry.derived'):
        query = ClaimQuery(tenant_id=context.tenant_id, metric_key=metric,
            purpose=context.purpose, allowed_claim_kinds=frozenset({'actual'}),
            as_of_at=deadline-timedelta(microseconds=1))
        assert len(repo.query(query, context=context)) == 1
        assert repo.query(replace(query, as_of_at=deadline), context=context) == []


def test_revised_recursive_inputs_hide_current_calculation_but_preserve_history(ledger):
    import psycopg
    repo, context, occurrence, _, _ = setup_intake(ledger)
    raw = ClaimDraft(tenant_id=context.tenant_id, assertion_namespace='freshness-test',
        subject_type='business_unit', subject_key='retail', business_unit='retail',
        metric_key='raw.cost', claim_kind='actual', production_method='imported',
        value_numeric=Decimal(10), unit='SAR', currency='SAR',
        source_occurrence_keys=(occurrence,))
    first = repo.record_claim(raw, traceability='present')
    derived = replace(raw, metric_key='derived.cost', production_method='calculated',
        source_occurrence_keys=(), input_revision_ids=(first['claim_revision_id'],),
        formula_key='identity', formula_version='1')
    second = repo.record_claim(derived, traceability='present')
    recursive = replace(derived, metric_key='headline.cost', input_revision_ids=(second['claim_revision_id'],))
    headline = repo.record_claim(recursive, traceability='present')
    # The ledger clock defines recorded time; a Docker host can differ by ms.
    with psycopg.connect(ledger[1]) as conn:
        before = conn.execute('select clock_timestamp()').fetchone()[0]
    query = ClaimQuery(tenant_id=context.tenant_id, metric_key='headline.cost',
        purpose=context.purpose, allowed_claim_kinds=frozenset({'actual'}), as_of_at=before,
        business_unit='retail')
    assert len(repo.query(query, context=context)) == 1
    with psycopg.connect(ledger[1]) as conn, conn.cursor() as cur:
        cur.execute("""insert into strategyos_analysis_snapshots
            (tenant_id,snapshot_key,as_of_at,policy_version,created_by)
            values (%s,'run:freshness-proof',%s,'test','test') returning id""", (context.tenant_id,before))
        snapshot_id = cur.fetchone()[0]
        cur.execute("""insert into strategyos_analysis_snapshot_claims
            (snapshot_id,claim_family_id,claim_revision_id,selection_reason)
            select %s,claim_family_id,id,'Test frozen selection' from strategyos_claim_revisions where id=%s""",
            (snapshot_id,headline['claim_revision_id']))
    assert not repo.snapshot('run:freshness-proof',context=context)['requires_recompute']
    assert repo.run_source_access('freshness-proof',context=context)['allowed']
    replacement = repo.record_claim(replace(raw,value_numeric=Decimal(12)),traceability='present')
    assert repo.query(replace(query,as_of_at=datetime.now(UTC)),context=context) == []
    assert repo.query(query,context=context)[0]['value'] == '10'
    historical = repo.snapshot('run:freshness-proof',context=context)
    assert historical['requires_recompute']
    assert historical['records'][0]['superseded_since_analysis']
    assert historical['records'][0]['value'] == '10'
    assert historical['denied_count'] == 0
    bulk = repo.run_source_access('freshness-proof',context=context)
    assert not bulk['allowed']
    assert bulk['reasons'] == ['bulk_revised_inputs_require_recompute']
    projection = repo.projection_record(headline['claim_revision_id'],tenant_id=context.tenant_id)
    assert projection['superseded_since_analysis']
    with psycopg.connect(ledger[1]) as conn, conn.cursor() as cur:
        cur.execute("""select count(*) from strategyos_claim_projection_outbox
            where tenant_id=%s and idempotency_key like 'revision-refresh:%%'""", (context.tenant_id,))
        assert cur.fetchone()[0] == 9  # raw and both recursive dependents, three stores
    recomputed_input = repo.record_claim(replace(derived,value_numeric=Decimal(12),
        input_revision_ids=(replacement['claim_revision_id'],)),traceability='present')
    new_headline = repo.record_claim(replace(recursive,value_numeric=Decimal(12),
        input_revision_ids=(recomputed_input['claim_revision_id'],)),traceability='present')
    current = repo.query(replace(query,as_of_at=datetime.now(UTC)),context=context)
    assert len(current) == 1 and current[0]['value'] == '12'
    # Recomputing creates new revisions; it never edits the published selection.
    assert repo.snapshot('run:freshness-proof',context=context)['records'][0]['value'] == '10'
    with psycopg.connect(ledger[1]) as conn, conn.cursor() as cur:
        cur.execute("""insert into strategyos_analysis_snapshots
            (tenant_id,snapshot_key,as_of_at,policy_version,created_by)
            values (%s,'run:recomputed-proof',clock_timestamp(),'test','test') returning id""", (context.tenant_id,))
        new_snapshot = cur.fetchone()[0]
        cur.execute("""insert into strategyos_analysis_snapshot_claims
            (snapshot_id,claim_family_id,claim_revision_id,selection_reason)
            select %s,claim_family_id,id,'Explicit new selection' from strategyos_claim_revisions where id=%s""",
            (new_snapshot,new_headline['claim_revision_id']))
    assert repo.run_source_access('recomputed-proof',context=context)['allowed']


def test_pending_run_revisions_do_not_replace_ratified_truth(ledger):
    import psycopg

    repo, context, occurrence, _, _ = setup_intake(ledger)
    raw = ClaimDraft(
        tenant_id=context.tenant_id,
        assertion_namespace='publication-boundary',
        subject_type='enterprise',
        subject_key='group',
        metric_key='publication.revenue',
        claim_kind='actual',
        production_method='imported',
        value_numeric=Decimal(10),
        unit='SAR',
        currency='SAR',
        source_occurrence_keys=(occurrence,),
    )
    first = repo.record_claim(raw, traceability='present')
    derived = repo.record_claim(
        replace(
            raw,
            metric_key='publication.margin',
            production_method='calculated',
            source_occurrence_keys=(),
            input_revision_ids=(first['claim_revision_id'],),
            formula_key='identity',
            formula_version='1',
        ),
        traceability='present',
    )
    with psycopg.connect(ledger[1]) as conn, conn.cursor() as cur:
        cur.execute("select id from strategyos_source_systems where tenant_id=%s", (context.tenant_id,))
        source_system_id = cur.fetchone()[0]
        cur.execute("""insert into strategyos_runs
            (run_dir,dataset_root,finding_count,locked_finding_count,total_recoverable_sar,
             status,current_stage,requires_human_review,approved_at,approved_by,summary_json,tenant_key)
            values ('approved','approved',0,0,0,'completed','writer',true,now(),'reviewer','{}',%s)
            returning id""", (context.tenant_id,))
        approved_run = str(cur.fetchone()[0])
        cur.execute("""insert into strategyos_ingestion_batches
            (tenant_id,source_system_id,run_id,batch_label,dataset_root)
            values (%s,%s,%s,'approved','approved') returning id""",
            (context.tenant_id, source_system_id, approved_run))
        approved_batch = cur.fetchone()[0]
        cur.execute("""insert into strategyos_ingestion_batch_claims
            (tenant_id,ingestion_batch_id,claim_revision_id,selection_reason)
            values (%s,%s,%s,'approved test selection')""",
            (context.tenant_id, approved_batch, first['claim_revision_id']))
        cur.execute("""insert into strategyos_analysis_snapshots
            (tenant_id,snapshot_key,as_of_at,policy_version,created_by)
            values (%s,'run:' || %s,clock_timestamp(),'test','test') returning id""",
            (context.tenant_id, approved_run))
        snapshot_id = cur.fetchone()[0]
        for revision_id in (first['claim_revision_id'], derived['claim_revision_id']):
            cur.execute("""insert into strategyos_analysis_snapshot_claims
                (snapshot_id,claim_family_id,claim_revision_id,selection_reason)
                select %s,claim_family_id,id,'approved test selection'
                from strategyos_claim_revisions where id=%s""", (snapshot_id, revision_id))

    replacement = repo.record_claim(replace(raw, value_numeric=Decimal(12)), traceability='present')
    with psycopg.connect(ledger[1]) as conn, conn.cursor() as cur:
        cur.execute("""insert into strategyos_runs
            (run_dir,dataset_root,finding_count,locked_finding_count,total_recoverable_sar,
             status,current_stage,requires_human_review,summary_json,tenant_key)
            values ('candidate','candidate',0,0,0,'awaiting_review','awaiting_review',true,'{}',%s)
            returning id""", (context.tenant_id,))
        candidate_run = str(cur.fetchone()[0])
        cur.execute("""insert into strategyos_ingestion_batches
            (tenant_id,source_system_id,run_id,batch_label,dataset_root)
            values (%s,%s,%s,'candidate','candidate') returning id""",
            (context.tenant_id, source_system_id, candidate_run))
        candidate_batch = cur.fetchone()[0]
        cur.execute("""insert into strategyos_ingestion_batch_claims
            (tenant_id,ingestion_batch_id,claim_revision_id,selection_reason)
            values (%s,%s,%s,'pending test selection')""",
            (context.tenant_id, candidate_batch, replacement['claim_revision_id']))

    raw_query = ClaimQuery(
        tenant_id=context.tenant_id,
        metric_key='publication.revenue',
        purpose=context.purpose,
        allowed_claim_kinds=frozenset({'actual'}),
        as_of_at=datetime.now(UTC),
    )
    derived_query = replace(raw_query, metric_key='publication.margin')
    assert repo.query(raw_query, context=context)[0]['value'] == '10'
    assert repo.query(derived_query, context=context)[0]['value'] == '10'
    assert not repo.snapshot(f'run:{approved_run}', context=context)['requires_recompute']
    assert repo.run_source_access(approved_run, context=context)['allowed']

    with psycopg.connect(ledger[1]) as conn, conn.cursor() as cur:
        cur.execute("""update strategyos_runs set status='completed',current_stage='writer',
            approved_at=now(),approved_by='reviewer' where id=%s""", (candidate_run,))

    assert repo.query(replace(raw_query, as_of_at=datetime.now(UTC)), context=context)[0]['value'] == '12'
    assert repo.query(replace(derived_query, as_of_at=datetime.now(UTC)), context=context) == []
    assert repo.snapshot(f'run:{approved_run}', context=context)['requires_recompute']
    assert repo.run_source_access(approved_run, context=context)['reasons'] == [
        'bulk_revised_inputs_require_recompute'
    ]
