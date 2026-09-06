from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from strategyos_mvp import claim_api


def request(**changes):
    fields=dict(decision="accepted",scope_key="scenario:base",review_due_at=datetime.now(UTC)+timedelta(days=7),
                rationale="Use this CFO estimate for the base scenario",effect_key="test-effect")
    fields.update(changes)
    return claim_api.ForecastReviewRequest(**fields)


def test_review_binds_actor_and_time_at_runtime_and_has_no_execution_side_effect(monkeypatch):
    captured={}
    class Repo:
        def assess_claim(self,assessment,**kwargs):
            captured.update(assessment=assessment,**kwargs)
            return {"assessment_id":"test", "created":True}
    monkeypatch.setattr(claim_api,"ClaimRepository",Repo)
    result=claim_api.review_forecast(str(uuid4()),request(),principal={"tenant_id":"tenant","subject":"ceo","role":"executive"})
    assert captured["assessment"].assessed_by == "ceo"
    assert captured["context"].principal_id == "ceo"
    assert captured["assessment"].assessed_at.tzinfo is not None
    assert result["claim_kind"] == "forecast"
    assert result["outbound_delivery"] is False and result["assignment_created"] is False


@pytest.mark.parametrize("extra",[{"requires_ceo_confirmation":False},{"assessed_by":"CFO"},{"send":True}])
def test_model_payload_cannot_self_authorize(extra):
    with pytest.raises(ValidationError):
        request(**extra)


@pytest.mark.parametrize("error",[KeyError("does not exist"),ValueError("foreign tenant")])
def test_denial_does_not_reveal_foreign_claim_existence(monkeypatch,error):
    class Repo:
        def assess_claim(self,*args,**kwargs): raise error
    monkeypatch.setattr(claim_api,"ClaimRepository",Repo)
    with pytest.raises(HTTPException) as caught:
        claim_api.review_forecast(str(uuid4()),request(),principal={"tenant_id":"tenant","subject":"ceo","role":"executive"})
    assert caught.value.status_code==403
    assert caught.value.detail=="This forecast or review request is not available under your current authority."
