from uuid import uuid4

import pytest

from strategyos_mvp.source_claims import ClaimKind
from strategyos_mvp.state_store import (
    persist_claim_reconciliation,
    persist_run_claim_snapshot,
    persist_shadow_claim,
)
from tests.test_cross_source_postgres_e2e import ledger


pytestmark = pytest.mark.integration


def test_repeat_ingestion_selects_only_claims_seen_in_the_current_batch(ledger):
    """A shared evidence document must not pull an older semantic lane forward."""
    import psycopg

    _repository, url, tenant_id = ledger
    source_hash = "e" * 64
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into strategyos_source_systems
                (tenant_id, name, system_type, source_key, origin_category, capture_method)
            values (%s, 'Repeat ERP', 'canonical_source:repeat-erp',
                    'repeat-erp', 'internal_system', 'file_upload')
            returning id
            """,
            (tenant_id,),
        )
        source_system_id = cur.fetchone()[0]
        cur.execute(
            """
            insert into strategyos_source_access_policies
                (tenant_id, source_system_id, policy_version, policy_fingerprint,
                 allowed_roles, allowed_purposes, recorded_by, storage_allowed, index_allowed)
            values (%s, %s, 1, %s, array['executive'],
                    array['executive_briefing'], 'test:operator', true, true)
            """,
            (tenant_id, source_system_id, f"repeat-policy-{uuid4()}"),
        )
        cur.execute(
            """
            insert into strategyos_evidence_documents
                (tenant_id, source_system_id, source_path, source_group, file_name,
                 media_type, size_bytes, source_hash)
            values (%s, %s, 'budget.xlsx', 'finance', 'budget.xlsx',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    10, %s)
            returning id
            """,
            (tenant_id, source_system_id, source_hash),
        )
        document_id = cur.fetchone()[0]

        batches = []
        runs = []
        for sequence in (1, 2):
            cur.execute(
                """
                insert into strategyos_runs
                    (run_dir, dataset_root, finding_count, locked_finding_count,
                     total_recoverable_sar, status, summary_json)
                values (%s, 'dataset', 0, 0, 0, 'completed', '{}'::jsonb)
                returning id
                """,
                (f"repeat-{sequence}",),
            )
            run_id = cur.fetchone()[0]
            runs.append(run_id)
            cur.execute(
                """
                insert into strategyos_ingestion_batches
                    (tenant_id, source_system_id, run_id, batch_label, dataset_root)
                values (%s, %s, %s, %s, 'dataset') returning id
                """,
                (tenant_id, source_system_id, run_id, f"repeat-{sequence}"),
            )
            batch_id = cur.fetchone()[0]
            batches.append(batch_id)
            cur.execute(
                """insert into strategyos_ingestion_batch_documents
                   (batch_id, evidence_document_id) values (%s, %s)""",
                (batch_id, document_id),
            )
            cur.execute(
                """
                insert into strategyos_finance_transactions
                    (tenant_id, batch_id, transaction_type, natural_key,
                     amount_sar, currency, source_document_id, source_locator)
                values (%s, %s, 'gl_entry', 'shared-row', 100, 'SAR', %s, 'row 2')
                """,
                (tenant_id, batch_id, document_id),
            )

        cur.execute(
            """
            insert into strategyos_evidence_occurrences
                (tenant_id, source_system_id, evidence_document_id,
                 ingestion_batch_id, occurrence_key, source_native_id,
                 source_native_version, received_at)
            values (%s, %s, %s, %s, %s, 'budget.xlsx', '1', now())
            """,
            (tenant_id, source_system_id, document_id, batches[0], f"repeat-{uuid4()}"),
        )

        first_revision, _ = persist_shadow_claim(
            cur,
            tenant_id=tenant_id,
            batch_id=batches[0],
            subject_type="group",
            subject_key="group",
            metric_key="ceo.revenue",
            claim_kind=ClaimKind.ACTUAL,
            value_numeric=100,
            unit="SAR",
            currency="SAR",
            source_document_id=document_id,
            source_locator="row 2",
            dimensions={"component_key": "revenue_actual"},
            metadata={"legacy_projection": "strategyos_finance_transactions"},
        )
        persist_run_claim_snapshot(
            cur,
            tenant_id=tenant_id,
            batch_id=batches[0],
            run_id=runs[0],
            as_of_at=None,
        )

        second_revision, _ = persist_shadow_claim(
            cur,
            tenant_id=tenant_id,
            batch_id=batches[1],
            subject_type="group",
            subject_key="group",
            metric_key="ceo.revenue",
            claim_kind=ClaimKind.UNKNOWN,
            value_numeric=100,
            unit="SAR",
            currency="SAR",
            source_document_id=document_id,
            source_locator="row 2",
            dimensions={"component_key": "revenue_actual"},
            metadata={
                "legacy_projection": "strategyos_finance_transactions",
                "quarantine_reasons": ["Actual/Est is ambiguous"],
            },
        )
        persist_run_claim_snapshot(
            cur,
            tenant_id=tenant_id,
            batch_id=batches[1],
            run_id=runs[1],
            as_of_at=None,
        )
        persist_claim_reconciliation(
            cur,
            tenant_id=tenant_id,
            batch_id=batches[1],
            run_id=runs[1],
        )

        cur.execute(
            """
            select cr.id, cr.claim_kind
            from strategyos_analysis_snapshots s
            join strategyos_analysis_snapshot_claims sc on sc.snapshot_id = s.id
            join strategyos_claim_revisions cr on cr.id = sc.claim_revision_id
            where s.tenant_id = %s and s.snapshot_key = %s
            """,
            (tenant_id, f"run:{runs[1]}"),
        )
        selected = cur.fetchall()
        assert [(str(revision), kind) for revision, kind in selected] == [
            (second_revision, "unknown")
        ]
        assert str(selected[0][0]) != first_revision
        cur.execute(
            """
            select status, source_record_count, claim_record_count, difference_sar
            from strategyos_claim_reconciliations
            where run_id = %s and ingestion_batch_id = %s
            """,
            (runs[1], batches[1]),
        )
        assert cur.fetchone() == ("passed", 1, 1, 0)
