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
def test_external_model_denial_happens_before_retrieval_or_network(monkeypatch, failure):
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
        summary={"run_id": "run-1", "canonical_claim_status": "ready",
                 "_claim_policy_context": {"tenant_id": "tenant-1", "principal_id": "ceo", "roles": ["executive"]}},
    )
    assert result["policy_denied"]
    assert result["citations"] == []
