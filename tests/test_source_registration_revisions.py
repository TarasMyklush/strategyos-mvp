from dataclasses import replace
from datetime import UTC, datetime

import pytest

from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake
from tests.test_tabular_claims import mapping, row
from strategyos_mvp.state_store import persist_source_registration_version, record_source_policy_revision
from strategyos_mvp.source_claims import ClaimQuery

pytestmark = pytest.mark.integration


def test_registration_restore_is_new_event_and_refreshes_dependents(ledger):
    import psycopg
    repo, context, occurrence, source, policy = setup_intake(ledger)
    repo.ingest_mapped_table([row()], mapping(), occurrence_key=occurrence,
        source_hash="c" * 64, context=context, apply=True)
    changed = repo.register_source(replace(source, governed_owner="new-owner"),
        policy=policy, recorded_by="steward", rationale="Owner change")
    restored = repo.register_source(source, policy=policy,
        recorded_by="steward", rationale="Restore prior owner metadata")
    replay = repo.register_source(source, policy=policy,
        recorded_by="steward", rationale="Retry same state")
    assert changed["registration_version"] == 2
    assert restored["registration_version"] == 3 and restored["registration_created"]
    assert replay["registration_version"] == 3 and not replay["registration_created"]
    assert replay["policy_id"] == changed["policy_id"]
    with psycopg.connect(ledger[1]) as conn, conn.cursor() as cur:
        cur.execute("""select registration_version, effective_to is null
            from strategyos_source_registration_versions where tenant_id=%s
            order by registration_version""", (context.tenant_id,))
        assert cur.fetchall() == [(1, False), (2, False), (3, True)]
        cur.execute("""select payload->>'registration_version', count(*)
            from strategyos_claim_projection_outbox where tenant_id=%s
            and idempotency_key like 'registration:%%' group by 1 order by 1""", (context.tenant_id,))
        assert cur.fetchall() == [("2", 3), ("3", 3)]
        # Legacy ingestion uses exactly the same serialized revision writer.
        version = persist_source_registration_version(cur, tenant_id=context.tenant_id,
            source_system_id=restored["source_system_id"], source=replace(source, governed_owner="new-owner"),
            recorded_by="ingestion", rationale="Explicit new source mapping")
        assert version == 4


def test_registration_revision_rejects_foreign_source(ledger):
    import psycopg
    repo, context, _, source, policy = setup_intake(ledger)
    registered = repo.register_source(source, policy=policy, recorded_by="test", rationale="Replay")
    with psycopg.connect(ledger[1]) as conn, conn.cursor() as cur:
        with pytest.raises(ValueError, match="authenticated tenant"):
            persist_source_registration_version(cur, tenant_id="00000000-0000-0000-0000-000000000001",
                source_system_id=registered["source_system_id"], source=source,
                recorded_by="test", rationale="Must reject")


def test_historical_provenance_does_not_adopt_later_registration(ledger):
    repo, context, occurrence, source, policy = setup_intake(ledger)
    repo.ingest_mapped_table([row()], mapping(), occurrence_key=occurrence,
        source_hash="c" * 64, context=context, apply=True)
    before_change = datetime.now(UTC)
    repo.register_source(replace(source, display_name="Corrected source", origin_category="public_web"),
        policy=policy, recorded_by="steward", rationale="Explicit provenance correction")
    query = ClaimQuery(tenant_id=context.tenant_id, metric_key=mapping().columns[0].metric_key,
        purpose=context.purpose, as_of_at=before_change, business_unit="retail",
        allowed_claim_kinds=frozenset({"actual"}))
    historical = repo.query(query, context=context)
    current = repo.query(replace(query, as_of_at=datetime.now(UTC)), context=context)
    assert historical and current
    assert historical[0]["sources"][0]["origin_category"] == "internal_system"
    assert historical[0]["sources"][0]["registration_version"] == 1
    assert current[0]["sources"][0]["origin_category"] == "public_web"
    assert current[0]["sources"][0]["registration_version"] == 2
    # Current source permissions still govern historical reads.
    repo.register_source(replace(source, display_name="Corrected source", origin_category="public_web"),
        policy=replace(policy, allowed_roles=frozenset()), recorded_by="steward", rationale="Withdraw access")
    assert repo.query(query, context=context) == []


def test_multiple_source_changes_in_one_transaction_have_adjacent_periods(ledger):
    import psycopg
    repo, context, _, source, policy = setup_intake(ledger)
    registered = repo.register_source(source, policy=policy, recorded_by="test", rationale="Replay")
    with psycopg.connect(ledger[1]) as conn, conn.cursor() as cur:
        for index in range(3):
            persist_source_registration_version(cur, tenant_id=context.tenant_id,
                source_system_id=registered["source_system_id"],
                source=replace(source, governed_owner=f"owner-{index}"),
                recorded_by="steward", rationale="Explicit consecutive change")
            record_source_policy_revision(cur, tenant_id=context.tenant_id,
                source_system_id=registered["source_system_id"],
                policy=replace(policy, export_allowed=index % 2 == 0),
                recorded_by="steward", rationale="Explicit consecutive policy change")
        for table, version in (("strategyos_source_registration_versions", "registration_version"),
                               ("strategyos_source_access_policies", "policy_version")):
            cur.execute(f"select effective_from,effective_to from {table} where tenant_id=%s order by {version}",
                        (context.tenant_id,))
            periods = cur.fetchall()
            assert len(periods) == 4
            for previous, following in zip(periods, periods[1:]):
                assert previous[0] < previous[1] == following[0]
            assert periods[-1][1] is None
