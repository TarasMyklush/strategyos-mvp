from dataclasses import replace

import pytest

from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims import mapping, row
from strategyos_mvp.source_claims import EvidenceOccurrence, PolicyContext, SourceAccessPolicy, SourceRegistration, UsePurpose

pytestmark = pytest.mark.integration


def setup_intake(ledger):
    import psycopg
    repo, url, tenant = ledger
    source = SourceRegistration(tenant_id=tenant, source_key="mapped-erp", display_name="Mapped ERP",
                                origin_category="internal_system", capture_method="file_upload")
    policy = SourceAccessPolicy(source_key=source.source_key, allowed_roles=frozenset({"operator"}),
                               storage_allowed=True, index_allowed=True,
                               allowed_purposes=frozenset({UsePurpose.OPERATIONS}))
    registered = repo.register_source(source, policy=policy, recorded_by="test", rationale="Explicit fixture authority")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("""insert into strategyos_evidence_documents
            (tenant_id,source_system_id,source_path,source_group,file_name,media_type,size_bytes,source_hash)
            values (%s,%s,'finance.xlsx','fixture','finance.xlsx','application/octet-stream',10,%s) returning id""",
            (tenant, registered["source_system_id"], "c" * 64))
        document = str(cur.fetchone()[0])
    occurrence = repo.record_occurrence(EvidenceOccurrence(tenant_id=tenant, source_key=source.source_key,
        artifact_hash="c" * 64, source_native_id="finance.xlsx"), evidence_document_id=document)
    context = PolicyContext(tenant_id=tenant, principal_id="steward", roles=frozenset({"operator"}),
                            purpose=UsePurpose.OPERATIONS)
    return repo, context, occurrence["occurrence_key"], source, policy


def test_preview_apply_replay_and_policy_revocation(ledger):
    repo, context, occurrence, source, policy = setup_intake(ledger)
    args = dict(occurrence_key=occurrence, source_hash="c" * 64, context=context)
    rows = [row(), row(Kind="plan", Value=10), row(Kind="Actual/Forecast", Value=20)]
    preview = repo.ingest_mapped_table(rows, mapping(), **args)
    assert preview["status"] == "preview" and preview["created_count"] == 0
    assert preview["quarantined_count"] == 1
    applied = repo.ingest_mapped_table(rows, mapping(), **args, apply=True)
    assert applied["created_count"] == 3 and applied["status"] == "applied_with_exceptions"
    replay = repo.ingest_mapped_table(rows, mapping(), **args, apply=True)
    assert replay["replayed"] and replay["created_count"] == 0
    assert replay["receipt_id"] == applied["receipt_id"]
    with pytest.raises(ValueError, match="match an existing"):
        repo.ingest_mapped_table(rows, mapping(), **{**args, "source_hash": "d" * 64}, apply=True)
    repo.register_source(source, policy=replace(policy, allowed_roles=frozenset({"auditor"})),
                         recorded_by="test", rationale="Revoked operator access")
    with pytest.raises(ValueError, match="does not authorize"):
        repo.ingest_mapped_table(rows, mapping(), **args, apply=True)


def test_mid_batch_failure_rolls_back_revisions_and_receipt(ledger, monkeypatch):
    import psycopg
    repo, context, occurrence, _, _ = setup_intake(ledger)
    original = repo._write_claim
    calls = []
    def failing_write(*args, **kwargs):
        if calls:
            raise ValueError("Injected second-cell failure")
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(repo, "_write_claim", failing_write)
    with pytest.raises(ValueError, match="second-cell"):
        repo.ingest_mapped_table([row(), row(Kind="plan", Value=10)], mapping(),
            occurrence_key=occurrence, source_hash="c" * 64, context=context, apply=True)
    with psycopg.connect(ledger[1]) as conn, conn.cursor() as cur:
        for table in ("strategyos_claim_revisions", "strategyos_claim_intake_receipts"):
            cur.execute(f"select count(*) from {table} where tenant_id=%s", (context.tenant_id,))
            assert cur.fetchone()[0] == 0
