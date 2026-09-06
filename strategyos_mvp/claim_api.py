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


def _policy_context(
    principal: dict[str, Any], purpose: UsePurpose
) -> PolicyContext:
    tenant_id = str(principal.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Authenticated tenant context is required.",
        )
    role = str(principal.get("role") or "").strip()
    return PolicyContext(
        tenant_id=tenant_id,
        principal_id=str(principal.get("subject") or "unknown"),
        roles=frozenset({role}),
        purpose=purpose,
        business_units=frozenset(
            str(item)
            for item in (principal.get("business_units") or [])
            if str(item).strip()
        ),
    )


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
    context = _policy_context(principal, purpose)
    requested_at = _timestamp(as_of)
    try:
        query = ClaimQuery(
            tenant_id=context.tenant_id,
            metric_key=metric_key,
            purpose=purpose,
            as_of_at=requested_at,
            allowed_claim_kinds=frozenset(claim_kind),
            business_unit=business_unit,
            scenario_key=scenario_key,
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


@router.get("/snapshots/{run_id}")
def query_run_snapshot(
    run_id: str,
    purpose: UsePurpose = Query(default=UsePurpose.EXECUTIVE_BRIEFING),
    metric_key: str | None = Query(default=None, min_length=1, max_length=240),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: dict[str, Any] = require_role(
        "executive", "analyst", "auditor", "reviewer", "operator", "tenant_admin", "system"
    ),
) -> dict[str, Any]:
    context = _policy_context(principal, purpose)
    try:
        return {
            "status": "ok",
            **ClaimRepository().snapshot(
                f"run:{run_id}",
                context=context,
                metric_keys=[metric_key] if metric_key else None,
                limit=limit,
                offset=offset,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/runs/{run_id}/reconciliation")
def query_run_reconciliation(
    run_id: str,
    principal: dict[str, Any] = require_role(
        "executive", "analyst", "auditor", "reviewer", "operator", "tenant_admin", "system"
    ),
) -> dict[str, Any]:
    context = _policy_context(principal, UsePurpose.ANALYSIS)
    try:
        return {
            "status": "ok",
            "run_id": run_id,
            "reconciliation": ClaimRepository().reconciliation(
                run_id, tenant_id=context.tenant_id
            ),
        }
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
