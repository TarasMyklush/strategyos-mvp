from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status, File, Form, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from .auth import require_role
from .claim_priority import PriorityDecision
from .claim_store import ClaimRepository
from .source_claims import ClaimAssessment, ClaimDraft, ClaimKind, ClaimQuery, PolicyContext, UsePurpose


router = APIRouter(prefix="/api/claims", tags=["governed-claims"])


class ForecastReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accepted", "rejected"]
    scope_key: str = Field(min_length=1, max_length=160)
    review_due_at: datetime | None = None
    rationale: str = Field(min_length=1, max_length=2000)
    effect_key: str = Field(min_length=1, max_length=160)


class StagedEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_pack_id: str = Field(min_length=1, max_length=160)
    relative_path: str = Field(min_length=1, max_length=1000)


class RecalculationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rationale: str = Field(min_length=1,max_length=2000)
    expected_preview: str | None = Field(default=None,min_length=1,max_length=240)


@router.post('/priority-policies')
def record_source_priority(request: PriorityDecision,
        principal: dict[str,Any] = require_role('tenant_admin')) -> dict[str,Any]:
    from .claim_priority import record_priority,PriorityConflict
    try:
        return record_priority(ClaimRepository(),request,context=_policy_context(principal,UsePurpose.OPERATIONS))
    except PermissionError as exc:
        raise HTTPException(403,str(exc)) from None
    except PriorityConflict as exc:
        raise HTTPException(409,str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None
    except RuntimeError:
        raise HTTPException(503,'Source-priority configuration is temporarily unavailable.') from None


@router.get('/recalculation-queue')
def recalculation_queue(after: str | None = Query(default=None,max_length=36),
        limit: int = Query(default=25,ge=1,le=100),
        principal: dict[str,Any] = require_role('operator','tenant_admin','system')) -> dict[str,Any]:
    try:
        return ClaimRepository().recalculation_queue(
            context=_policy_context(principal,UsePurpose.OPERATIONS),after=after,limit=limit)
    except PermissionError as exc:
        raise HTTPException(403,str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None
    except RuntimeError:
        raise HTTPException(503,'Recalculation queue is temporarily unavailable.') from None


@router.post('/{revision_id}/recalculate')
def recalculate_claim(revision_id: str,request: RecalculationRequest,
        principal: dict[str,Any] = require_role('operator','tenant_admin','system')) -> dict[str,Any]:
    from .claim_recalculation import recalculate, RecalculationConflict
    from psycopg.errors import DeadlockDetected, SerializationFailure
    try:
        return recalculate(ClaimRepository(),revision_id,
            context=_policy_context(principal,UsePurpose.OPERATIONS),
            rationale=request.rationale,expected_preview=request.expected_preview)
    except PermissionError as exc:
        raise HTTPException(403,str(exc)) from None
    except RecalculationConflict as exc:
        raise HTTPException(409,str(exc)) from None
    except (DeadlockDetected,SerializationFailure):
        raise HTTPException(409,'The input revisions changed concurrently. Preview again before recording.') from None
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None
    except RuntimeError:
        raise HTTPException(503,'Recalculation is temporarily unavailable. Retry the same preview to check its receipt.') from None


@router.post('/intake/staged-evidence')
def register_evidence_from_stage(request: StagedEvidenceRequest,
        principal: dict[str, Any] = require_role('operator', 'tenant_admin', 'system')) -> dict[str, Any]:
    from .staged_evidence import register_staged_evidence
    try:
        return register_staged_evidence(request.source_pack_id, request.relative_path,
            context=_policy_context(principal, UsePurpose.OPERATIONS))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except (RuntimeError, KeyError):
        raise HTTPException(503, 'Evidence registration is temporarily unavailable.') from None


@router.post("/{revision_id}/forecast-review")
def review_forecast(revision_id: str, request: ForecastReviewRequest,
                    principal: dict[str, Any] = require_role("executive", "reviewer", "tenant_admin")) -> dict[str, Any]:
    from uuid import UUID
    context = _policy_context(principal, UsePurpose.OPERATIONS)
    try:
        revision_id = str(UUID(revision_id))
        assessment = ClaimAssessment(claim_revision_id=revision_id, assessment_type="forecast_review",
            result=request.decision, rule_version="scoped-forecast-review-v1",
            assessed_by=context.principal_id, assessed_at=datetime.now(UTC),
            scope_key=request.scope_key, valid_until=request.review_due_at, reasons=(request.rationale,))
        if not request.rationale.strip():
            raise ValueError("A review rationale is required.")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        recorded = ClaimRepository().assess_claim(assessment, effect_key=request.effect_key, context=context)
    except (KeyError, ValueError):
        raise HTTPException(403, "This forecast or review request is not available under your current authority.") from None
    except RuntimeError:
        raise HTTPException(503, "Forecast review is temporarily unavailable.") from None
    return {"status":"recorded", **recorded, "claim_kind":"forecast", "scope_key":request.scope_key,
            "review_due_at":request.review_due_at.isoformat() if request.review_due_at else None,
            "outbound_delivery":False, "assignment_created":False,
            "notice":"Recorded for this scope only. This remains a forecast, not an actual."}


@router.post("/intake/workbook")
def intake_mapped_workbook(
    file: UploadFile = File(...),
    occurrence_key: str = Form(min_length=1, max_length=240),
    mapping_json: str = Form(min_length=2, max_length=64000),
    apply: bool = Form(default=False),
    principal: dict[str, Any] = require_role("operator", "tenant_admin", "system"),
) -> dict[str, Any]:
    """Preview by default; apply only an explicit mapping of registered bytes."""
    import hashlib
    from .tabular_claims import TableClaimMapping, read_workbook_rows
    context = _policy_context(principal, UsePurpose.OPERATIONS)
    content = file.file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "Workbook intake is limited to 5 MiB.")
    if not str(file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(422, "Only an XLSX workbook is accepted for mapped intake.")
    try:
        mapping = TableClaimMapping.model_validate_json(mapping_json)
        rows = read_workbook_rows(content, mapping)
        return ClaimRepository().ingest_mapped_table(rows, mapping,
            occurrence_key=occurrence_key, source_hash=hashlib.sha256(content).hexdigest(),
            context=context, apply=apply)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError:
        raise HTTPException(503, "Mapped claim intake is temporarily unavailable.") from None


class TypedClaimIntake(BaseModel):
    """Explicit operator interpretation of evidence; never inferred by a model."""
    model_config = ConfigDict(extra="forbid")
    assertion_namespace: str = Field(min_length=1, max_length=160)
    subject_type: str = Field(min_length=1, max_length=80)
    subject_key: str = Field(min_length=1, max_length=240)
    metric_key: str = Field(min_length=1, max_length=240)
    claim_kind: ClaimKind = ClaimKind.UNKNOWN
    value_numeric: Decimal | None = None
    value_text: str | None = Field(default=None, max_length=16000)
    unit: str | None = Field(default=None, max_length=80)
    scale: Decimal = Decimal(1)
    currency: str | None = Field(default=None, max_length=3)
    business_unit: str | None = Field(default=None, max_length=160)
    period_start: date | None = None
    period_end: date | None = None
    as_of_at: datetime | None = None
    valid_until: datetime | None = None
    author_identity: str | None = Field(default=None, max_length=240)
    scenario_key: str | None = Field(default=None, max_length=160)
    source_occurrence_keys: list[str] = Field(min_length=1, max_length=100)
    assumptions: list[str] = Field(default_factory=list, max_length=50)


@router.post("/intake")
def record_typed_claim(request: TypedClaimIntake,
                       principal: dict[str, Any] = require_role("operator", "tenant_admin", "system")) -> dict[str, Any]:
    context = _policy_context(principal, UsePurpose.OPERATIONS)
    try:
        fields = request.model_dump()
        fields["source_occurrence_keys"] = tuple(fields["source_occurrence_keys"])
        fields["assumptions"] = tuple(fields["assumptions"])
        draft = ClaimDraft(**fields, tenant_id=context.tenant_id, production_method="human_entered",
                           metadata={"recorded_by": context.principal_id, "intake": "explicit_semantic_contract_v1"})
        result = ClaimRepository().record_claim(draft, traceability="present", context=context)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError:
        raise HTTPException(503, "Claim intake is temporarily unavailable.") from None
    return {"status": "ok", **result, "claim_kind": str(draft.claim_kind),
            "review_status": "unreviewed", "outbound_delivery": False}


@router.get("/search")
def search_governed_claims(
    text: str = Query(min_length=1, max_length=4000),
    metric_key: str = Query(min_length=1, max_length=240),
    claim_kind: list[ClaimKind] = Query(default=[ClaimKind.ACTUAL]),
    purpose: UsePurpose = Query(default=UsePurpose.EXECUTIVE_BRIEFING),
    business_unit: str | None = Query(default=None, max_length=160),
    scenario_key: str | None = Query(default=None, max_length=160),
    as_of: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=10, ge=1, le=50),
    forecast_scope_key: str | None = None,
    require_forecast_acceptance: bool = False,
    period_start: date | None = None,
    period_end: date | None = None,
    fiscal_calendar: str | None = None,
    principal: dict[str, Any] = require_role("executive", "bu", "analyst", "auditor", "reviewer", "operator", "tenant_admin", "system"),
) -> dict[str, Any]:
    from .claim_retrieval import search_claims
    context = _policy_context(principal, purpose)
    try:
        query = ClaimQuery(tenant_id=context.tenant_id, metric_key=metric_key,
                           purpose=purpose, as_of_at=_timestamp(as_of),
                           allowed_claim_kinds=frozenset(claim_kind),
                           business_unit=business_unit, scenario_key=scenario_key,
                           forecast_scope_key=forecast_scope_key,
                           require_forecast_acceptance=require_forecast_acceptance,
                           period_start=period_start,period_end=period_end,fiscal_calendar=fiscal_calendar)
        records = search_claims(text, query=query, context=context, limit=limit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError:
        raise HTTPException(503, "Governed semantic search is temporarily unavailable.") from None
    return {"status": "ok", "records": records, "analysis_as_of": query.as_of_at.isoformat(),
            "requires_resolution":any(row.get('comparison',{}).get('requires_resolution') for row in records),
            "authority": "postgresql", "ranking": "local_semantic_candidates"}


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
    if role == "bu" and not principal.get("business_units"):
        raise HTTPException(403, "An explicit business-unit scope is required.")
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
    forecast_scope_key: str | None = None,
    require_forecast_acceptance: bool = False,
    period_start: date | None = None,
    period_end: date | None = None,
    fiscal_calendar: str | None = None,
    principal: dict[str, Any] = require_role(
        "executive", "bu", "analyst", "auditor", "reviewer", "operator", "tenant_admin", "system"
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
            forecast_scope_key=forecast_scope_key,
            require_forecast_acceptance=require_forecast_acceptance,
            period_start=period_start,period_end=period_end,fiscal_calendar=fiscal_calendar,
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
        "requires_resolution":any(row.get('comparison',{}).get('requires_resolution') for row in records),
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
        repository = ClaimRepository()
        access = repository.run_source_access(run_id, context=context)
        # Historical revisions remain inspectable after a newer revision, but
        # source revocation and scope restrictions still protect page metadata.
        if not access.get('allowed') and set(access.get('reasons') or ()) != {'bulk_revised_inputs_require_recompute'}:
            raise HTTPException(403, 'This snapshot is unavailable for this source scope and purpose. Use the claim query for authorized individual evidence.')
        snapshot = repository.snapshot(
                f"run:{run_id}",
                context=context,
                metric_keys=[metric_key] if metric_key else None,
                limit=limit,
                offset=offset,
            )
        if snapshot.get('denied_count'):
            raise HTTPException(403, 'This snapshot page is not available in full. Use the claim query for authorized individual evidence.')
        return {'status': 'ok', **snapshot}
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
        repository = ClaimRepository()
        if not repository.run_source_access(run_id, context=context).get('allowed'):
            raise HTTPException(403, 'Reconciliation is unavailable for this source scope.')
        return {
            "status": "ok",
            "run_id": run_id,
            "reconciliation": repository.reconciliation(
                run_id, tenant_id=context.tenant_id
            ),
        }
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
