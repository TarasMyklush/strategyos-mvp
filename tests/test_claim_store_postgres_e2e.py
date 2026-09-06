from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from strategyos_mvp import claim_backfill
from strategyos_mvp.claim_store import ClaimRepository
from strategyos_mvp.source_claims import (
    ClaimAssessment,
    ClaimDraft,
    ClaimKind,
    ClaimQuery,
    EvidenceOccurrence,
    PolicyContext,
    ProductionMethod,
    SourceAccessPolicy,
    SourceRegistration,
    TraceabilityState,
    UsePurpose,
)
from strategyos_mvp.state_store import (
    ensure_data_schema,
    persist_claim_reconciliation,
    persist_finance_kpi_claims,
    persist_run_claim_snapshot,
    persist_transaction_claims,
)


pytestmark = pytest.mark.integration


def _connection_factory(url: str):
    def connect():
        import psycopg

        return psycopg.connect(url), None

    return connect


def test_source_occurrence_claim_revision_and_policy_query_round_trip():
    url = os.environ.get("STRATEGYOS_TEST_POSTGRES_URL") or os.environ.get(
        "STRATEGYOS_POSTGRES_E2E_DATABASE_URL"
    )
    if not url:
        pytest.skip("STRATEGYOS_TEST_POSTGRES_URL is not configured")
    import psycopg

    with psycopg.connect(url) as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_tenants (slug, display_name) values ('claims-e2e', 'Claims E2E') returning id"
            )
            tenant_id = str(cur.fetchone()[0])
        conn.commit()

    repo = ClaimRepository(_connection_factory(url))
    registered = repo.register_source(
        SourceRegistration(
            tenant_id=tenant_id,
            source_key="erp-finance",
            display_name="ERP Finance",
            origin_category="internal_system",
            capture_method="api",
            governed_owner="finance-data-owner",
            authorization_basis="E2E fixture authority",
        ),
        policy=SourceAccessPolicy(
            source_key="erp-finance",
            allowed_roles=frozenset({"executive", "analyst"}),
            allowed_purposes=frozenset(
                {UsePurpose.EXECUTIVE_BRIEFING, UsePurpose.ANALYSIS, UsePurpose.EXTERNAL_MODEL}
            ),
            external_model_allowed=False,
        ),
        recorded_by="test:operator",
        rationale="E2E policy fixture",
    )
    replayed_registration = repo.register_source(
        SourceRegistration(
            tenant_id=tenant_id,
            source_key="erp-finance",
            display_name="ERP Finance",
            origin_category="internal_system",
            capture_method="api",
            governed_owner="finance-data-owner",
            authorization_basis="E2E fixture authority",
        ),
        policy=SourceAccessPolicy(
            source_key="erp-finance",
            allowed_roles=frozenset({"executive", "analyst"}),
            allowed_purposes=frozenset(
                {UsePurpose.EXECUTIVE_BRIEFING, UsePurpose.ANALYSIS, UsePurpose.EXTERNAL_MODEL}
            ),
            external_model_allowed=False,
        ),
        recorded_by="test:operator",
        rationale="E2E policy fixture",
    )
    assert replayed_registration["registration_created"] is False
    assert replayed_registration["policy_created"] is False
    assert replayed_registration["policy_id"] == registered["policy_id"]

    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into strategyos_evidence_documents
                    (tenant_id, source_system_id, source_path, source_group, file_name, media_type,
                     size_bytes, source_hash)
                values (%s, %s, 'erp/revenue.csv', 'erp', 'revenue.csv', 'text/csv', 10, %s)
                returning id
                """,
                (tenant_id, registered["source_system_id"], "a" * 64),
            )
            document_id = str(cur.fetchone()[0])
        conn.commit()

    occurrence = EvidenceOccurrence(
        tenant_id=tenant_id,
        source_key="erp-finance",
        artifact_hash="a" * 64,
        source_native_id="erp/revenue.csv",
        source_native_version="2026-06",
        received_at=datetime(2026, 7, 1, tzinfo=UTC),
        locator="row 2",
    )
    recorded_occurrence = repo.record_occurrence(
        occurrence, evidence_document_id=document_id
    )
    replayed_occurrence = repo.record_occurrence(
        occurrence, evidence_document_id=document_id
    )
    assert replayed_occurrence == recorded_occurrence
    draft = ClaimDraft(
        tenant_id=tenant_id,
        assertion_namespace="erp-finance",
        subject_type="business_unit",
        subject_key="tamween",
        metric_key="revenue",
        claim_kind=ClaimKind.ACTUAL,
        production_method=ProductionMethod.IMPORTED,
        value_numeric=Decimal("1179200000"),
        unit="SAR",
        currency="SAR",
        business_unit="tamween",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        source_occurrence_keys=(recorded_occurrence["occurrence_key"],),
    )
    first = repo.record_claim(draft, traceability=TraceabilityState.PRESENT)
    replay = repo.record_claim(draft, traceability=TraceabilityState.PRESENT)
    changed = repo.record_claim(
        ClaimDraft(**{**draft.__dict__, "value_numeric": Decimal("1180000000")}),
        traceability=TraceabilityState.PRESENT,
    )
    assert first["created"] is True
    assert replay == {
        "claim_revision_id": first["claim_revision_id"],
        "revision_number": 1,
        "created": False,
    }
    assert changed["revision_number"] == 2

    assessment = ClaimAssessment(
        claim_revision_id=changed["claim_revision_id"],
        assessment_type="reconciliation",
        result="passed",
        rule_version="revenue-reconciliation-v1",
        assessed_by="reviewer:1",
        assessed_at=datetime.now(UTC),
        reasons=("Source total reconciles to the governed control total.",),
    )
    first_assessment = repo.assess_claim(assessment, effect_key="reconcile-revenue-june")
    replayed_assessment = repo.assess_claim(
        assessment, effect_key="reconcile-revenue-june"
    )
    assert first_assessment["created"] is True
    assert replayed_assessment["created"] is False
    with pytest.raises(ValueError, match="cannot be reused"):
        repo.assess_claim(
            ClaimAssessment(
                **{**assessment.__dict__, "result": "failed"}
            ),
            effect_key="reconcile-revenue-june",
        )

    as_of = datetime.now(UTC)
    results = repo.query(
        ClaimQuery(
            tenant_id=tenant_id,
            metric_key="revenue",
            purpose=UsePurpose.EXECUTIVE_BRIEFING,
            as_of_at=as_of,
            allowed_claim_kinds=frozenset({ClaimKind.ACTUAL}),
            business_unit="tamween",
        ),
        context=PolicyContext(
            tenant_id=tenant_id,
            principal_id="ceo",
            roles=frozenset({"executive"}),
            purpose=UsePurpose.EXECUTIVE_BRIEFING,
        ),
    )
    assert len(results) == 1
    assert results[0]["revision"] == 2
    assert results[0]["value"] == "1180000000"
    assert results[0]["claim_kind"] == "actual"
    assert len(results[0]["sources"]) == 1
    assert results[0]["sources"][0]["source_key"] == "erp-finance"
    assert results[0]["sources"][0]["origin_category"] == "internal_system"

    denied_external = repo.query(
        ClaimQuery(
            tenant_id=tenant_id,
            metric_key="revenue",
            purpose=UsePurpose.EXTERNAL_MODEL,
            as_of_at=as_of,
            allowed_claim_kinds=frozenset({ClaimKind.ACTUAL}),
            business_unit="tamween",
        ),
        context=PolicyContext(
            tenant_id=tenant_id,
            principal_id="ceo",
            roles=frozenset({"executive"}),
            purpose=UsePurpose.EXTERNAL_MODEL,
        ),
    )
    assert denied_external == []


def test_run_backfill_materializes_kpis_lineage_snapshot_and_reconciliation():
    url = os.environ.get("STRATEGYOS_TEST_POSTGRES_URL") or os.environ.get(
        "STRATEGYOS_POSTGRES_E2E_DATABASE_URL"
    )
    if not url:
        pytest.skip("STRATEGYOS_TEST_POSTGRES_URL is not configured")
    import psycopg

    with psycopg.connect(url) as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_tenants (slug, display_name) values ('backfill-e2e', 'Backfill E2E') returning id"
            )
            tenant_id = str(cur.fetchone()[0])
            cur.execute(
                """
                insert into strategyos_source_systems
                    (tenant_id, name, system_type, source_key, origin_category, capture_method)
                values (%s, 'ERP Finance', 'canonical_source:erp-backfill',
                        'erp-backfill', 'internal_system', 'api')
                returning id
                """,
                (tenant_id,),
            )
            source_system_id = str(cur.fetchone()[0])
            cur.execute(
                """
                insert into strategyos_source_access_policies
                    (tenant_id, source_system_id, policy_version, policy_fingerprint,
                     allowed_roles, allowed_purposes, recorded_by)
                values (%s, %s, 1, 'policy-backfill-e2e',
                        array['executive'], array['executive_briefing'], 'test:operator')
                """,
                (tenant_id, source_system_id),
            )
            cur.execute(
                """
                insert into strategyos_runs
                    (run_dir, dataset_root, finding_count, locked_finding_count,
                     total_recoverable_sar, status, summary_json, tenant_key)
                values ('run', 'dataset', 0, 0, 0, 'completed', '{}'::jsonb, 'backfill-e2e')
                returning id
                """
            )
            run_id = str(cur.fetchone()[0])
            cur.execute(
                """
                insert into strategyos_ingestion_batches
                    (tenant_id, source_system_id, run_id, batch_label, dataset_root)
                values (%s, %s, %s, 'e2e', 'dataset')
                returning id
                """,
                (tenant_id, source_system_id, run_id),
            )
            batch_id = str(cur.fetchone()[0])
            cur.execute(
                """
                insert into strategyos_evidence_documents
                    (tenant_id, source_system_id, source_path, source_group, file_name,
                     media_type, size_bytes, source_hash)
                values (%s, %s, 'erp/revenue.csv', 'erp', 'revenue.csv',
                        'text/csv', 10, %s)
                returning id
                """,
                (tenant_id, source_system_id, "b" * 64),
            )
            document_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into strategyos_ingestion_batch_documents values (%s, %s)",
                (batch_id, document_id),
            )
            cur.execute(
                """
                insert into strategyos_evidence_occurrences
                    (tenant_id, source_system_id, evidence_document_id, ingestion_batch_id,
                     occurrence_key, source_native_id, source_native_version, received_at)
                values (%s, %s, %s, %s, 'occurrence-backfill-e2e',
                        'erp/revenue.csv', '2026-06', now())
                """,
                (tenant_id, source_system_id, document_id, batch_id),
            )
            cur.execute(
                """
                insert into strategyos_finance_transactions
                    (tenant_id, batch_id, transaction_type, natural_key, event_date,
                     amount_sar, currency, source_document_id, source_locator)
                values (%s, %s, 'gl_entry', 'REV-1:0', '2026-06-30',
                        100, 'USD', %s, 'row 2')
                """,
                (tenant_id, batch_id, document_id),
            )

            transaction_result = persist_transaction_claims(
                cur, tenant_id=tenant_id, batch_id=batch_id, run_id=run_id
            )
            kpi_result = persist_finance_kpi_claims(
                cur,
                tenant_id=tenant_id,
                batch_id=batch_id,
                run_id=run_id,
                evidence_ids={"erp/revenue.csv": document_id},
                finance_payload={
                    "authoritative": True,
                    "reporting_period_key": "2026-01-01 to 2026-06-30",
                    "components": {
                        "revenue_actual": "100",
                        "revenue_plan": "95",
                        "ebitda_actual": "20",
                    },
                    "evidence": {
                        "revenue": {"files": ["erp/revenue.csv"]},
                        "ebitda_margin": {"files": ["erp/revenue.csv"]},
                    },
                },
                recorded_at="2026-07-01T00:00:00Z",
            )
            snapshot_count = persist_run_claim_snapshot(
                cur,
                tenant_id=tenant_id,
                batch_id=batch_id,
                run_id=run_id,
                as_of_at="2026-07-01T00:00:00Z",
            )
            reconciliation_count = persist_claim_reconciliation(
                cur, tenant_id=tenant_id, batch_id=batch_id, run_id=run_id
            )
            conn.commit()

            assert transaction_result == {"claims": 1, "exceptions": 0}
            assert kpi_result == {"claims": 4, "exceptions": 0}
            assert snapshot_count == 1
            assert reconciliation_count == 1
            cur.execute(
                "select status, source_record_count, claim_record_count, difference_sar from strategyos_claim_reconciliations where run_id = %s",
                (run_id,),
            )
            assert cur.fetchone() == ("passed", 1, 1, Decimal("0"))
            cur.execute(
                "select count(*) from strategyos_claim_dependencies where input_role = 'input'"
            )
            assert cur.fetchone()[0] == 2
            cur.execute(
                "select count(*) from strategyos_analysis_snapshot_claims where snapshot_id = (select id from strategyos_analysis_snapshots where snapshot_key = %s)",
                (f"run:{run_id}",),
            )
            assert cur.fetchone()[0] == 5

    repo = ClaimRepository(_connection_factory(url))
    snapshot = repo.snapshot(
        f"run:{run_id}",
        context=PolicyContext(
            tenant_id=tenant_id,
            principal_id="ceo",
            roles=frozenset({"executive"}),
            purpose=UsePurpose.EXECUTIVE_BRIEFING,
        ),
    )
    assert len(snapshot["records"]) == 5
    headline_snapshot = repo.snapshot(
        f"run:{run_id}",
        context=PolicyContext(
            tenant_id=tenant_id,
            principal_id="ceo",
            roles=frozenset({"executive"}),
            purpose=UsePurpose.EXECUTIVE_BRIEFING,
        ),
        metric_keys={"ceo.revenue", "ceo.ebitda_margin"},
    )
    assert {item["metric_key"] for item in headline_snapshot["records"]} == {
        "ceo.revenue",
        "ceo.ebitda_margin",
    }
    assert len(headline_snapshot["records"]) == 3
    first_page = repo.snapshot(
        f"run:{run_id}",
        context=PolicyContext(
            tenant_id=tenant_id,
            principal_id="ceo",
            roles=frozenset({"executive"}),
            purpose=UsePurpose.EXECUTIVE_BRIEFING,
        ),
        limit=2,
    )
    second_page = repo.snapshot(
        f"run:{run_id}",
        context=PolicyContext(
            tenant_id=tenant_id,
            principal_id="ceo",
            roles=frozenset({"executive"}),
            purpose=UsePurpose.EXECUTIVE_BRIEFING,
        ),
        limit=2,
        offset=first_page["page"]["next_offset"],
    )
    assert first_page["page"] == {
        "limit": 2,
        "offset": 0,
        "returned_count": 2,
        "evaluated_count": 2,
        "has_more": True,
        "next_offset": 2,
    }
    assert len(second_page["records"]) == 2
    assert {
        item["claim_revision_id"] for item in first_page["records"]
    }.isdisjoint(item["claim_revision_id"] for item in second_page["records"])
    transaction_claim = next(
        item for item in snapshot["records"] if item["metric_key"] == "finance.transaction.amount"
    )
    assert transaction_claim["unit"] == "SAR"
    assert transaction_claim["currency"] == "SAR"
    assert transaction_claim["dimensions"]["source_currency"] == "USD"
    assert transaction_claim["sources"][0]["locator"] == "row 2"
    margin = next(item for item in snapshot["records"] if item["metric_key"] == "ceo.ebitda_margin")
    assert len(margin["formula"]["inputs"]) == 2
    assert margin["sources"][0]["source_key"] == "erp-backfill"
    assert repo.reconciliation(run_id, tenant_id=tenant_id)["status"] == "passed"
    events = repo.lease_projection_batch(worker_id="e2e-worker", limit=100)
    tenant_events = [item for item in events if item["tenant_id"] == tenant_id]
    assert len(tenant_events) == 15
    cache_event = next(item for item in tenant_events if item["projection_type"] == "cache")
    record = repo.projection_record(
        cache_event["claim_revision_id"], tenant_id=tenant_id
    )
    repo.upsert_projection_cache(record)
    repo.mark_projection_published(cache_event["id"], worker_id="e2e-worker")
    projection_health = repo.projection_health()
    assert projection_health["status"] == "ready"
    assert projection_health["pending"] >= 14
    assert projection_health["leased"] == projection_health["pending"]
    assert projection_health["oldest_pending_seconds"] >= 0
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from strategyos_claim_projection_cache where tenant_id = %s",
                (tenant_id,),
            )
            assert cur.fetchone()[0] == 1


def test_historical_backfill_is_preview_first_and_idempotent(monkeypatch):
    url = os.environ.get("STRATEGYOS_TEST_POSTGRES_URL") or os.environ.get(
        "STRATEGYOS_POSTGRES_E2E_DATABASE_URL"
    )
    if not url:
        pytest.skip("STRATEGYOS_TEST_POSTGRES_URL is not configured")
    import psycopg

    with psycopg.connect(url) as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_tenants (slug, display_name) values ('historical-backfill-e2e', 'Historical Backfill E2E') returning id"
            )
            tenant_id = str(cur.fetchone()[0])
            cur.execute(
                """
                insert into strategyos_source_systems
                    (tenant_id, name, system_type, source_key,
                     origin_category, capture_method)
                values (%s, 'Historical ERP', 'finance_dataset', 'historical-erp',
                        'internal_system', 'folder_import')
                returning id
                """,
                (tenant_id,),
            )
            source_system_id = str(cur.fetchone()[0])
            summary = {
                "created_at": "2026-07-01T00:00:00Z",
                "finance_kpi": {
                    "authoritative": True,
                    "reporting_period_key": "H1 2026",
                    "components": {
                        "revenue_actual": "100",
                        "revenue_plan": "95",
                        "ebitda_actual": "20",
                    },
                    "evidence": {
                        "revenue": {"files": ["erp/historical.csv"]},
                        "ebitda_margin": {"files": ["erp/historical.csv"]},
                    },
                },
            }
            cur.execute(
                """
                insert into strategyos_runs
                    (run_dir, dataset_root, finding_count, locked_finding_count,
                     total_recoverable_sar, status, summary_json,
                     tenant_key, created_at)
                values ('historical-run', 'historical-data', 0, 0, 0,
                        'completed', %s::jsonb, 'historical-backfill-e2e',
                        '2026-07-01T00:00:00Z')
                returning id
                """,
                (claim_backfill.json_blob(summary),),
            )
            run_id = str(cur.fetchone()[0])
            cur.execute(
                """
                insert into strategyos_ingestion_batches
                    (tenant_id, source_system_id, run_id, batch_label, dataset_root)
                values (%s, %s, %s, 'historical', 'historical-data')
                returning id
                """,
                (tenant_id, source_system_id, run_id),
            )
            batch_id = str(cur.fetchone()[0])
            cur.execute(
                """
                insert into strategyos_evidence_documents
                    (tenant_id, source_system_id, source_path, source_group,
                     file_name, media_type, size_bytes, source_hash)
                values (%s, %s, 'erp/historical.csv', 'erp', 'historical.csv',
                        'text/csv', 10, %s)
                returning id
                """,
                (tenant_id, source_system_id, "c" * 64),
            )
            document_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into strategyos_ingestion_batch_documents values (%s, %s)",
                (batch_id, document_id),
            )
            cur.execute(
                """
                insert into strategyos_finance_transactions
                    (tenant_id, batch_id, transaction_type, natural_key,
                     event_date, amount_sar, currency, source_document_id, source_locator)
                values (%s, %s, 'ap_invoice', 'AP-1', '2026-06-30',
                        10, 'SAR', %s, 'row 2')
                """,
                (tenant_id, batch_id, document_id),
            )
            cur.execute(
                """
                insert into strategyos_finance_balances
                    (tenant_id, batch_id, balance_type, natural_key, account,
                     amount_sar, source_document_id, source_locator)
                values (%s, %s, 'trial_balance', '1000', '1000',
                        5, %s, 'row 3')
                """,
                (tenant_id, batch_id, document_id),
            )
        conn.commit()

    monkeypatch.setattr(
        claim_backfill,
        "database_connection",
        lambda: (psycopg.connect(url), None),
    )
    preview = claim_backfill.backfill_claims(run_ids=[run_id])
    assert preview["mode"] == "preview"
    assert preview["runs"][0]["existing_claim_revisions"] == 0

    applied = claim_backfill.backfill_claims(run_ids=[run_id], apply=True)
    created = applied["runs"][0]["created"]
    assert created == {
        "transaction_claims": 1,
        "balance_claims": 1,
        "kpi_claims": 4,
        "exceptions": 0,
        "analysis_snapshot": 1,
    }
    assert applied["runs"][0]["result"]["existing_reconciliation"] == "passed"

    replay = claim_backfill.backfill_claims(run_ids=[run_id], apply=True)
    assert replay["runs"][0]["created"] == {
        "transaction_claims": 0,
        "balance_claims": 0,
        "kpi_claims": 0,
        "exceptions": 0,
        "analysis_snapshot": 0,
    }
