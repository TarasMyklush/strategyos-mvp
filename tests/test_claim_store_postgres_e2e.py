from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

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
from strategyos_mvp.state_store import ensure_data_schema


pytestmark = pytest.mark.integration


def _connection_factory(url: str):
    def connect():
        import psycopg

        return psycopg.connect(url), None

    return connect


def test_source_occurrence_claim_revision_and_policy_query_round_trip():
    url = os.environ.get("STRATEGYOS_TEST_POSTGRES_URL")
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
