"""Offline source acceptance: real local ledger, synthetic records, no connectors."""
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
import os
from uuid import uuid4

import pytest

from strategyos_mvp.claim_store import ClaimRepository
from strategyos_mvp.source_claims import (
    ClaimAssessment, ClaimDraft, ClaimQuery, EvidenceOccurrence, PolicyContext,
    SourceAccessPolicy, SourceRegistration, UsePurpose,
)
from strategyos_mvp.state_store import ensure_data_schema

pytestmark = pytest.mark.integration


@pytest.fixture
def ledger():
    url = os.environ.get("STRATEGYOS_POSTGRES_E2E_DATABASE_URL")
    if not url:
        pytest.skip("Dedicated Postgres proof endpoint required.")
    import psycopg
    with psycopg.connect(url) as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_tenants (slug, display_name) values (%s, 'Offline proof') returning id",
                (f"cross-source-{uuid4()}",),
            )
            tenant = str(cur.fetchone()[0])
    return ClaimRepository(lambda: (psycopg.connect(url), None)), url, tenant


@pytest.mark.parametrize("origin,channel,kind", [
    ("internal_system", "file_upload", "actual"),
    ("public_web", "file_upload", "reported_claim"),
    ("licensed_external", "folder_import", "reported_claim"),
    ("correspondence", "email", "forecast"),
    ("correspondence", "chat", "assumption"),
])
def test_source_to_ledger_to_authorized_envelope(ledger, monkeypatch, origin, channel, kind):
    import psycopg
    repo, url, tenant = ledger
    source = SourceRegistration(
        tenant_id=tenant, source_key="offline-fixture", display_name="Synthetic source",
        origin_category=origin, capture_method=channel,
        provider_name="Fixture provider" if origin == "licensed_external" else None,
        license_policy_ref="fixture-contract:1" if origin == "licensed_external" else None,
    )
    access = SourceAccessPolicy(
        source_key=source.source_key, allowed_roles=frozenset({"executive"}),
        allowed_purposes=frozenset(UsePurpose),
    )
    registered = repo.register_source(source, policy=access, recorded_by="fixture:operator", rationale="Offline test")
    digest = "b" * 64
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into strategyos_runs
                (run_dir,dataset_root,finding_count,locked_finding_count,total_recoverable_sar,summary_json)
                values ('offline','offline',0,0,0,'{}') returning id"""
            )
            run_id = str(cur.fetchone()[0])
            cur.execute(
                """insert into strategyos_ingestion_batches
                (tenant_id,source_system_id,run_id,batch_label,dataset_root)
                values (%s,%s,%s,'offline','offline') returning id""",
                (tenant, registered["source_system_id"], run_id),
            )
            batch = str(cur.fetchone()[0])
            cur.execute(
                """insert into strategyos_evidence_documents
                (tenant_id, source_system_id, source_path, source_group, file_name, media_type, size_bytes, source_hash)
                values (%s,%s,'offline.json','fixture','offline.json','application/json',2,%s) returning id""",
                (tenant, registered["source_system_id"], digest),
            )
            document = str(cur.fetchone()[0])
    occurrence = EvidenceOccurrence(
        tenant_id=tenant, source_key=source.source_key, artifact_hash=digest,
        source_native_id="fixture:1", received_at=datetime.now(UTC), author_identity="CFO fixture",
        original_uri="https://fixture.invalid/evidence/1", source_native_version="revision-2",
    )
    recorded = repo.record_occurrence(occurrence, evidence_document_id=document, ingestion_batch_id=batch)
    with pytest.raises(ValueError, match="match the occurrence hash"):
        repo.record_occurrence(replace(occurrence, artifact_hash="c" * 64), evidence_document_id=document)
    draft = ClaimDraft(
        tenant_id=tenant, assertion_namespace="fixture", subject_type="business_unit",
        subject_key="test-bu", business_unit="test-bu", metric_key="test.revenue",
        claim_kind=kind, production_method="imported", value_numeric=Decimal("1.25"),
        unit="SAR", currency="SAR", scale=1000000,
        period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
        author_identity="CFO fixture", source_occurrence_keys=(recorded["occurrence_key"],),
    )
    first = repo.record_claim(draft, traceability="present")
    assert not repo.record_claim(draft, traceability="present")["created"]
    q = ClaimQuery(
        tenant_id=tenant, metric_key="test.revenue", purpose="executive_briefing",
        as_of_at=datetime.now(UTC), allowed_claim_kinds=frozenset({kind}), business_unit="test-bu",
    )
    ctx = PolicyContext(tenant_id=tenant, principal_id="fixture-ceo", roles=frozenset({"executive"}), purpose=q.purpose)
    assert not repo.record_claim(draft, traceability="present", context=replace(ctx, purpose=UsePurpose.OPERATIONS))["created"]
    records = repo.query(q, context=ctx)
    assert len(records) == 1
    record = records[0]
    assert record["claim_revision_id"] == first["claim_revision_id"]
    assert Decimal(record["value"]) * Decimal(record["scale"]) == Decimal("1250000")
    assert record["period"]["start"] == "2026-06-01"
    assert record["sources"][0]["origin_category"] == origin
    assert record["sources"][0]["capture_method"] == channel
    assert record["sources"][0]["original_uri"] == "https://fixture.invalid/evidence/1"
    assert record["sources"][0]["source_native_version"] == "revision-2"
    assert record["claim_kind"] == kind
    # Provenance/traceability is not an invented verification assessment.
    assert record["assessments"] == []
    from strategyos_mvp.claim_retrieval import search_claims
    assert search_claims("revenue", query=q, context=ctx, repository=repo,
                         candidates=lambda *a, **k: [first["claim_revision_id"]]) == records
    assert repo.run_source_access(run_id, context=ctx)["allowed"]
    from strategyos_mvp import access_scope, claim_store
    monkeypatch.setattr(claim_store, "ClaimRepository", lambda: repo)
    def legacy_read_allowed():
        token = access_scope.principal_scope.set({
            "tenant_id": tenant, "subject": "fixture-ceo", "role": "executive",
            "_source_read_request": True,
        })
        try:
            return access_scope.source_read_allowed(run_id)
        finally:
            access_scope.principal_scope.reset(token)
    assert legacy_read_allowed()
    if kind != "actual":
        with pytest.raises(ValueError, match="Calculated actuals"):
            repo.record_claim(replace(
                draft, claim_kind="actual", production_method="calculated",
                source_occurrence_keys=(), formula_key="fixture", formula_version="1",
                input_revision_ids=(first["claim_revision_id"],),
            ), traceability="present")
    if kind != "actual":
        assert repo.query(replace(q, allowed_claim_kinds=frozenset({"actual"})), context=ctx) == []
    for purpose in (UsePurpose.EXPORT, UsePurpose.EXTERNAL_MODEL, UsePurpose.QUOTATION):
        assert repo.query(replace(q, purpose=purpose), context=replace(ctx, purpose=purpose)) == []
        assert not repo.run_source_access(run_id, context=replace(ctx, purpose=purpose))["allowed"]
    graph_uri = os.environ.get("STRATEGYOS_NEO4J_E2E_URI")
    if not graph_uri:
        pytest.fail("Cross-source projection proof requires the dedicated local Neo4j service")
    from neo4j import GraphDatabase
    from strategyos_mvp import neo4j_store
    def driver():
        return GraphDatabase.driver(graph_uri, auth=(os.environ["STRATEGYOS_NEO4J_E2E_USER"], os.environ["STRATEGYOS_NEO4J_E2E_PASSWORD"]))
    monkeypatch.setattr(neo4j_store, "_graph_driver", driver)
    projected = repo.projection_record(first["claim_revision_id"], tenant_id=tenant)
    neo4j_store.project_claim_record(projected, "upsert")
    neo4j_store.project_claim_record(projected, "upsert")
    with driver() as graph, graph.session() as session:
        row = session.run(
            "MATCH (c:StrategyOSClaim {tenant_id:$tenant}) RETURN count(c) AS n, collect(c.claim_kind) AS kinds",
            tenant=tenant,
        ).single()
        assert row["n"] == 1
        assert row["kinds"] == [kind]
    # Actual model + actual Qdrant; no hash vector or mocked transport.
    vector_url = os.environ.get("STRATEGYOS_QDRANT_E2E_URL")
    model_path = os.environ.get("STRATEGYOS_EMBEDDING_E2E_MODEL_PATH")
    assert vector_url and model_path, "Dedicated vector service and pinned local model required"
    from strategyos_mvp import vector_store, semantic_embeddings
    monkeypatch.setenv("STRATEGYOS_EMBEDDING_MODEL_PATH", model_path)
    monkeypatch.setattr(vector_store, "CONFIG", replace(vector_store.CONFIG, qdrant_url=vector_url))
    monkeypatch.setattr(vector_store, "VECTOR_SIZE", semantic_embeddings.DIMENSIONS)
    vector_store.project_claim_record(projected, "upsert")
    vector_store.project_claim_record(projected, "upsert")
    assert search_claims("revenue", query=q, context=ctx, repository=repo) == records
    # Permission revocation must apply immediately even to an old revision.
    repo.register_source(source, policy=replace(access, allowed_roles=frozenset({"auditor"})), recorded_by="fixture:operator", rationale="Revoke fixture access")
    assert repo.query(q, context=ctx) == []
    assert not repo.run_source_access(run_id, context=ctx)["allowed"]
    assert not legacy_read_allowed()
    with pytest.raises(ValueError, match="Source policy"):
        repo.record_claim(draft, traceability="present", context=replace(ctx, purpose=UsePurpose.OPERATIONS))
    assert search_claims("revenue", query=q, context=ctx, repository=repo,
                         candidates=lambda *a, **k: [first["claim_revision_id"]]) == []
    assert search_claims("revenue", query=q, context=ctx, repository=repo) == []
    vector_store.project_claim_record(projected, "revoke")
    # A stale projection must not silently substitute a newer revision.
    latest = repo.record_claim(replace(draft, value_numeric=Decimal("2.5")), traceability="present")
    now_query = replace(q, as_of_at=datetime.now(UTC))
    auditor = replace(ctx, roles=frozenset({"auditor"}))
    assert repo.query(now_query, context=auditor, revision_ids=[first["claim_revision_id"]]) == []
    assert repo.query(now_query, context=auditor, revision_ids=[latest["claim_revision_id"]])[0]["value"] == "2.5"
    derived = repo.record_claim(replace(draft, metric_key="test.derived", value_numeric=Decimal("2.5"),
        production_method="calculated", source_occurrence_keys=(), formula_key="identity",
        formula_version="1", input_revision_ids=(latest["claim_revision_id"],)), traceability="present")
    derived_query = replace(now_query, metric_key="test.derived", as_of_at=datetime.now(UTC))
    assert repo.query(derived_query, context=auditor)[0]["claim_revision_id"] == derived["claim_revision_id"]
    repo.assess_claim(ClaimAssessment(
        claim_revision_id=latest["claim_revision_id"], assessment_type="lifecycle",
        result="retracted", rule_version="fixture-v1", assessed_by="fixture:reviewer",
        assessed_at=datetime.now(UTC), reasons=("Fixture withdrawn after the analysis time",),
    ), effect_key=f"retract:{latest['claim_revision_id']}")
    # Historical selection cannot resurrect currently withdrawn evidence.
    assert repo.query(now_query, context=auditor) == []
    assert repo.query(derived_query, context=auditor) == []


def test_repository_rejects_cross_tenant_context(ledger):
    import psycopg
    repo, url, tenant = ledger
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute("insert into strategyos_tenants (slug, display_name) values (%s, 'Other') returning id", (f"other-{uuid4()}",))
            other = str(cur.fetchone()[0])
    q = ClaimQuery(tenant_id=tenant, metric_key="revenue", purpose="analysis", as_of_at=datetime.now(UTC), allowed_claim_kinds=frozenset({"actual"}))
    ctx = PolicyContext(tenant_id=other, principal_id="other", roles=frozenset({"executive"}), purpose="analysis")
    with pytest.raises(ValueError, match="authenticated tenant"):
        repo.query(q, context=ctx)
