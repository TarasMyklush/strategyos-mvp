from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake
from tests.test_tabular_claims import mapping, row
from strategyos_mvp.source_claims import ClaimAssessment, ClaimQuery, UsePurpose

pytestmark = pytest.mark.integration


def test_scoped_forecast_review_is_authorized_idempotent_and_never_an_actual(ledger):
    repo, operator, occurrence, source, policy = setup_intake(ledger)
    result = repo.ingest_mapped_table([row(Kind="forecast", Value=100, Author="Synthetic CFO")],mapping(),
        occurrence_key=occurrence,source_hash="c"*64,context=operator,apply=True)
    revision = result["claim_revision_ids"][0]
    policy = replace(policy,allowed_roles=frozenset({"executive"}),
                     allowed_purposes=frozenset({UsePurpose.OPERATIONS,UsePurpose.ANALYSIS}))
    repo.register_source(source,policy=policy,recorded_by="fixture",rationale="Explicit synthetic review grant")
    context = replace(operator,roles=frozenset({"executive"}),principal_id="synthetic-ceo")
    now = datetime.now(UTC)
    assessment = ClaimAssessment(claim_revision_id=revision,assessment_type="forecast_review",result="accepted",
        assessed_by=context.principal_id,assessed_at=now,rule_version="scoped-forecast-review-v1",
        scope_key="scenario:base",valid_until=now+timedelta(days=7),reasons=("Synthetic test acceptance",))
    first=repo.assess_claim(assessment,effect_key="test-review",context=context)
    replay=repo.assess_claim(replace(assessment,assessed_at=now+timedelta(seconds=1)),
                             effect_key="test-review",context=context)
    assert first["created"] and not replay["created"]
    assert first["assessment_id"] == replay["assessment_id"]
    query=ClaimQuery(tenant_id=context.tenant_id,metric_key="cost",purpose=UsePurpose.ANALYSIS,
        business_unit="retail",
        as_of_at=datetime.now(UTC),allowed_claim_kinds=frozenset({"forecast"}),
        require_forecast_acceptance=True,forecast_scope_key="scenario:base")
    records=repo.query(query,context=replace(context,purpose=UsePurpose.ANALYSIS))
    assert len(records)==1 and records[0]["claim_kind"]=="forecast"
    assert records[0]["forecast_review"]["eligible_for_scoped_use"]
    assert repo.query(replace(query,forecast_scope_key="scenario:other"),
                      context=replace(context,purpose=UsePurpose.ANALYSIS))==[]
    with pytest.raises(ValueError,match="authority"):
        repo.assess_claim(assessment,effect_key="wrong-role",context=operator)
    with pytest.raises(ValueError,match="different assessment"):
        repo.assess_claim(replace(assessment,result="rejected"),effect_key="test-review",context=context)
    repo.register_source(source,policy=replace(policy,allowed_roles=frozenset({"auditor"})),
                         recorded_by="fixture",rationale="Revoke source before retry")
    with pytest.raises(ValueError,match="does not authorize"):
        repo.assess_claim(assessment,effect_key="test-review",context=context)
