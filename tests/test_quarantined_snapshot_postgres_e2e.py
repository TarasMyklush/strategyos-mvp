import pytest
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake
from tests.test_tabular_claims import mapping, row

pytestmark = pytest.mark.integration


def test_quarantined_snapshot_entry_is_excluded_without_query_validation_crash(ledger):
    import psycopg
    repo, context, occurrence, _, _ = setup_intake(ledger)
    result = repo.ingest_mapped_table([row(Kind="Actual/Forecast", Value=100)], mapping(),
        occurrence_key=occurrence, source_hash="c"*64, context=context, apply=True)
    revision = result["claim_revision_ids"][0]
    with psycopg.connect(ledger[1]) as conn, conn.cursor() as cur:
        cur.execute("""insert into strategyos_analysis_snapshots
            (tenant_id,snapshot_key,as_of_at,policy_version,created_by)
            values (%s,'quarantine-proof',now(),'test','test') returning id""", (context.tenant_id,))
        snapshot_id = cur.fetchone()[0]
        cur.execute("""insert into strategyos_analysis_snapshot_claims
            (snapshot_id,claim_family_id,claim_revision_id,selection_reason)
            select %s,claim_family_id,id,'Explicit fixture' from strategyos_claim_revisions where id=%s""",
            (snapshot_id, revision))
    snapshot = repo.snapshot("quarantine-proof", context=context)
    assert snapshot["records"] == []
    assert snapshot["denied_count"] == 1
