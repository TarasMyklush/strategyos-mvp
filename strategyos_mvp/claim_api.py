from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from .auth import require_role
from .claim_store import ClaimRepository
from .source_claims import ClaimKind, ClaimQuery, PolicyContext, UsePurpose


router = APIRouter(prefix="/api/claims", tags=["governed-claims"])


def _timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "as_of must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "as_of must include a timezone.")
    return parsed


@router.get("")
def query_claims(
    metric_key: str = Query(min_length=1, max_length=240),
    claim_kind: list[ClaimKind] = Query(default=[ClaimKind.ACTUAL]),
    purpose: UsePurpose = Query(default=UsePurpose.EXECUTIVE_BRIEFING),
    business_unit: str | None = Query(default=None, max_length=160),
    scenario_key: str | None = Query(default=None, max_length=160),
    as_of: str | None = Query(default=None, max_length=80),
    principal: dict[str, Any] = require_role(
        "executive", "analyst", "auditor", "reviewer", "operator", "tenant_admin", "system"
    ),
) -> dict[str, Any]:
    """Return policy-filtered claims with a UI-ready provenance envelope."""
    tenant_id = str(principal.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Authenticated tenant context is required.")
    role = str(principal.get("role") or "").strip()
    business_units = frozenset(str(item) for item in (principal.get("business_units") or []) if str(item).strip())
    requested_at = _timestamp(as_of)
    try:
        query = ClaimQuery(
            tenant_id=tenant_id,
            metric_key=metric_key,
            purpose=purpose,
            as_of_at=requested_at,
            allowed_claim_kinds=frozenset(claim_kind),
            business_unit=business_unit,
            scenario_key=scenario_key,
        )
        context = PolicyContext(
            tenant_id=tenant_id,
            principal_id=str(principal.get("subject") or "unknown"),
            roles=frozenset({role}),
            purpose=purpose,
            business_units=business_units,
        )
        records = ClaimRepository().query(query, context=context)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {
        "status": "ok",
        "analysis_as_of": requested_at.isoformat(),
        "metric_key": metric_key,
        "claim_kinds": sorted(str(item) for item in query.allowed_claim_kinds),
        "records": records,
    }
