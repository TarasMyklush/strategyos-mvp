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
