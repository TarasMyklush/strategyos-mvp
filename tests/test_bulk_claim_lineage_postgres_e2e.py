"""Legacy bulk reads inherit the exact snapshot's transitive source boundary."""
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from tests.test_cross_source_postgres_e2e import ledger
from strategyos_mvp.source_claims import (
    ClaimAssessment, ClaimDraft, EvidenceOccurrence, PolicyContext,
    SourceAccessPolicy, SourceRegistration, UsePurpose,
)

pytestmark = pytest.mark.integration


def test_bulk_snapshot_cannot_bypass_sources_outside_its_ingestion_batch(ledger):
    import psycopg
    repo, url, tenant = ledger
    inputs = []
    registrations = []
    for number in (1, 2):
        source = SourceRegistration(tenant_id=tenant, source_key=f"input-{number}",
            display_name="Synthetic external-batch input", origin_category="internal_system",
            capture_method="file_upload")
        policy = SourceAccessPolicy(source_key=source.source_key,
            storage_allowed=True, index_allowed=True,
            allowed_roles=frozenset({"executive", "auditor"}),
            allowed_purposes=frozenset({UsePurpose.EXECUTIVE_BRIEFING}))
        registered = repo.register_source(source, policy=policy, recorded_by="fixture", rationale="Test")
        registrations.append((source, policy))
        digest = str(number) * 64
        with psycopg.connect(url) as conn, conn.cursor() as cur:
            cur.execute("""insert into strategyos_evidence_documents
                (tenant_id,source_system_id,source_path,source_group,file_name,media_type,size_bytes,source_hash)
                values (%s,%s,%s,'fixture','input.json','application/json',2,%s) returning id""",
                (tenant, registered["source_system_id"], f"input-{number}.json", digest))
            document = str(cur.fetchone()[0])
        occurrence = repo.record_occurrence(EvidenceOccurrence(tenant_id=tenant,
            source_key=source.source_key, artifact_hash=digest, source_native_id=f"input:{number}"),
            evidence_document_id=document)
        claim = repo.record_claim(ClaimDraft(tenant_id=tenant, assertion_namespace="fixture",
            subject_type="enterprise", subject_key="group", metric_key=f"test.input.{number}",
            claim_kind="actual", production_method="imported", value_numeric=number,
            period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
            unit="SAR", currency="SAR", source_occurrence_keys=(occurrence["occurrence_key"],)),
            traceability="present")
        inputs.append(claim["claim_revision_id"])
    calculated = ClaimDraft(tenant_id=tenant, assertion_namespace="fixture",
        subject_type="enterprise", subject_key="group", metric_key="test.sum",
        claim_kind="actual", production_method="calculated", value_numeric=3,
        period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
        unit="SAR", currency="SAR", formula_key="sum", formula_version="1",
        input_revision_ids=tuple(inputs))
    with pytest.raises(ValueError, match="does not match"):
        repo.record_claim(replace(calculated, value_numeric=999), traceability="present")
    derived = repo.record_claim(calculated, traceability="present")
    run = str(uuid4())
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("""insert into strategyos_analysis_snapshots
            (tenant_id,snapshot_key,as_of_at,policy_version,created_by)
            values (%s,%s,now(),'fixture','fixture') returning id""", (tenant, f"run:{run}"))
        snapshot = cur.fetchone()[0]
        cur.execute("""insert into strategyos_analysis_snapshot_claims
            (snapshot_id,claim_family_id,claim_revision_id,selection_reason)
            select %s,claim_family_id,id,'fixture' from strategyos_claim_revisions where id=%s""",
            (snapshot, derived["claim_revision_id"]))
    context = PolicyContext(tenant_id=tenant, principal_id="fixture", roles=frozenset({"executive"}),
        purpose=UsePurpose.EXECUTIVE_BRIEFING)
    assert repo.run_source_access(run, context=context)["allowed"]
    source, policy = registrations[1]
    repo.register_source(source, policy=replace(policy, allowed_roles=frozenset({"auditor"})),
        recorded_by="fixture", rationale="Withdraw executive source access")
    access = repo.run_source_access(run, context=context)
    assert not access["allowed"] and "source_role_denied" in access["reasons"]
    auditor = replace(context, roles=frozenset({"auditor"}))
    assert repo.run_source_access(run, context=auditor)["allowed"]
    repo.assess_claim(ClaimAssessment(claim_revision_id=inputs[0], assessment_type="lifecycle",
        result="retracted", rule_version="fixture", assessed_by="fixture", assessed_at=datetime.now(UTC),
        reasons=("Withdraw exact input",)), effect_key=f"withdraw:{inputs[0]}")
    access = repo.run_source_access(run, context=auditor)
    assert not access["allowed"] and "bulk_withdrawn_evidence" in access["reasons"]
