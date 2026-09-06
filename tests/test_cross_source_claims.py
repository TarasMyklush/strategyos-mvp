"""Connection-free contract tests shared by every intake channel."""
from dataclasses import replace

import pytest

from strategyos_mvp.source_claims import (
    ClaimKind, ProductionMethod, SourceRegistration, UsePurpose, claim_is_eligible,
)
from test_source_claims import actual_draft, context, policy, query, revision


@pytest.mark.parametrize("purpose,flag", [
    (UsePurpose.EXPORT, "export_allowed"),
    (UsePurpose.EXTERNAL_MODEL, "external_model_allowed"),
    (UsePurpose.QUOTATION, "quote_allowed"),
])
def test_special_use_requires_explicit_permission_from_every_source(purpose, flag):
    permitted = policy(allowed_purposes=frozenset({purpose}), **{flag: True})
    denied = replace(permitted, source_key="restricted-provider", **{flag: False})
    args = dict(query=query(purpose=purpose), context=context(purpose=purpose))
    assert claim_is_eligible(revision(), source_policies=[permitted], **args).eligible
    assert not claim_is_eligible(revision(), source_policies=[permitted, denied], **args).eligible


def test_query_cannot_launder_an_external_model_request_as_briefing():
    result = claim_is_eligible(
        revision(), query=query(purpose=UsePurpose.EXTERNAL_MODEL),
        context=context(), source_policies=[policy()],
    )
    assert "purpose_mismatch" in result.reasons


def test_calculation_without_resolved_source_policies_is_denied():
    calculated = revision(actual_draft(
        production_method=ProductionMethod.CALCULATED, source_occurrence_keys=(),
        formula_key="test", formula_version="1", input_revision_ids=("input-1",),
    ))
    assert not claim_is_eligible(
        calculated, query=query(), context=context(), source_policies=[],
    ).eligible


@pytest.mark.parametrize("provider,license_ref", [(None, None), ("Provider", None), (None, "contract:1")])
def test_licensed_source_cannot_bypass_intake_contract(provider, license_ref):
    with pytest.raises(ValueError, match="provider and license"):
        SourceRegistration(
            tenant_id="tenant-1", source_key="research", display_name="Research",
            origin_category="licensed_external", capture_method="file_upload",
            provider_name=provider, license_policy_ref=license_ref,
        )


@pytest.mark.parametrize("kind", [ClaimKind.FORECAST, ClaimKind.PLAN, ClaimKind.REPORTED_CLAIM, ClaimKind.ASSUMPTION])
def test_nonactual_claims_never_substitute_for_actuals(kind):
    candidate = revision(actual_draft(claim_kind=kind, author_identity="CFO"))
    assert not claim_is_eligible(
        candidate, query=query(), context=context(), source_policies=[policy()],
    ).eligible


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("public_packet", [None, {"kpis": [{"name": "Revenue", "value": 123}]}])
def test_external_model_denial_happens_before_retrieval_or_network(monkeypatch, failure, public_packet):
    from strategyos_mvp import claim_store, llm_qa, source_search
    from tests.test_llm_qa import _config

    class Repository:
        def run_source_access(self, run_id, *, context):
            assert run_id == "run-1"
            assert context.purpose == UsePurpose.EXTERNAL_MODEL
            if failure:
                raise RuntimeError("database unavailable")
            return {"allowed": False}

    def forbidden(*args, **kwargs):
        pytest.fail("Denied evidence must never reach retrieval or provider transport")

    monkeypatch.setattr(claim_store, "ClaimRepository", Repository)
    monkeypatch.setattr(source_search, "retrieve", forbidden)
    monkeypatch.setattr(llm_qa, "urlopen", forbidden)
    result = llm_qa.answer_question(
        "Explain revenue", bundle=None, findings=[], config=_config(),
        public_context_packet=public_packet,
        summary={"run_id": "run-1", "canonical_claim_status": "ready",
                 "_claim_policy_context": {"tenant_id": "tenant-1", "principal_id": "ceo", "roles": ["executive"]}},
    )
    assert result["policy_denied"]
    assert result["citations"] == []


def test_policy_refusal_is_not_advice_or_verified_evidence():
    from strategyos_mvp.api import _assistant_response_payload

    result = _assistant_response_payload(
        response_mode="llm", question="Compare strategic alternatives",
        context={"run_id": "run-1", "run_mode": "governed"},
        requested_mode="auto", persona="ceo", orchestrated=None,
        base_result={"policy_denied": True, "answer": "Permission required."},
    )
    assert result["answer_origin"] == "policy"
    assert result["determinism_tier"] == "policy"
    assert not result["matched"]
    assert not result["citations"]
    assert not result["response_sections"]
    assert not result["external_consultation"]["used"]


@pytest.mark.parametrize("summary", [{}, {"run_id": "legacy-run"}, {"tenant_context": {"tenant_id": "tenant"}}])
def test_missing_model_source_context_fails_closed(summary):
    from strategyos_mvp.model_policy import evidence_model_access
    assert not evidence_model_access(summary)


def test_twin_transport_cannot_send_ungoverned_observations(monkeypatch):
    from strategyos_mvp.twins.reasoning import _call_litellm_reasoning
    from strategyos_mvp import llm_qa
    from tests.test_llm_qa import _config
    monkeypatch.setattr(llm_qa, "_post_with_retry", lambda **kwargs: pytest.fail("unauthorized transport"))
    with pytest.raises(RuntimeError, match="Source permission"):
        _call_litellm_reasoning(config=_config(), stage="orient", input_context={"observations": {"private": "data"}})


def test_bu_restricted_principal_cannot_read_unscoped_group_claim():
    result = claim_is_eligible(
        revision(actual_draft(business_unit=None)),
        query=query(business_unit=None),
        context=context(business_units=frozenset({"tamween"})),
        source_policies=[policy()],
    )
    assert not result.eligible
    assert "principal_business_unit_denied" in result.reasons
