"""Shared source-consent gate for evidence-bearing external model calls."""
from .claim_store import ClaimRepository
from .source_claims import PolicyContext, UsePurpose


def evidence_model_access(summary: dict) -> bool:
    context = summary.get("_claim_policy_context") or {}
    run_id = str(summary.get("_backing_run_id") or summary.get("run_id") or "")
    if not run_id or not context.get("tenant_id") or not context.get("principal_id") or not context.get("roles"):
        return False
    try:
        return bool(ClaimRepository().run_source_access(run_id, context=PolicyContext(
            tenant_id=context["tenant_id"], principal_id=context["principal_id"],
            roles=frozenset(context["roles"]), business_units=frozenset(context.get("business_units") or ()),
            purpose=UsePurpose.EXTERNAL_MODEL,
        ))["allowed"])
    except (KeyError, ValueError, RuntimeError):
        return False
