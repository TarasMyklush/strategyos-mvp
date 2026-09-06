from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Iterable, Mapping


IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,239}$")


class OriginCategory(StrEnum):
    INTERNAL_SYSTEM = "internal_system"
    PUBLIC_WEB = "public_web"
    LICENSED_EXTERNAL = "licensed_external"
    CORRESPONDENCE = "correspondence"
    UNKNOWN = "unknown"


class CaptureMethod(StrEnum):
    UNKNOWN = "unknown"
    FILE_UPLOAD = "file_upload"
    FOLDER_IMPORT = "folder_import"
    API = "api"
    EMAIL = "email"
    CHAT = "chat"
    MANUAL_ENTRY = "manual_entry"


class ClaimKind(StrEnum):
    ACTUAL = "actual"
    PLAN = "plan"
    FORECAST = "forecast"
    ASSUMPTION = "assumption"
    REPORTED_CLAIM = "reported_claim"
    UNKNOWN = "unknown"


class ProductionMethod(StrEnum):
    IMPORTED = "imported"
    HUMAN_ENTERED = "human_entered"
    EXTRACTED = "extracted"
    CALCULATED = "calculated"


class TraceabilityState(StrEnum):
    PRESENT = "present"
    INCOMPLETE = "incomplete"
    MISSING = "missing"


class ReviewAction(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class UsePurpose(StrEnum):
    OPERATIONS = "operations"
    EXECUTIVE_BRIEFING = "executive_briefing"
    ANALYSIS = "analysis"
    SCENARIO = "scenario"
    EXPORT = "export"
    EXTERNAL_MODEL = "external_model"
    QUOTATION = "quotation"


def _text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _enum_value(enum_type: type[StrEnum], value: StrEnum | str) -> StrEnum:
    try:
        return enum_type(str(value))
    except ValueError as exc:
        raise ValueError(f"Unsupported {enum_type.__name__}: {value!r}") from exc


def decimal_value(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc
    if not number.is_finite():
        raise ValueError("Claim values must be finite decimals.")
    return number


def stable_key(namespace: str, *parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return f"{namespace}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _identifier(value: Any, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a stable 3–240 character identifier.")
    return normalized


@dataclass(frozen=True)
class SourceRegistration:
    tenant_id: str
    source_key: str
    display_name: str
    origin_category: OriginCategory | str
    capture_method: CaptureMethod | str
    governed_owner: str | None = None
    provider_name: str | None = None
    authorization_basis: str | None = None
    license_policy_ref: str | None = None
    retention_class: str = "client-policy"
    sensitivity_class: str = "client-confidential"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("tenant_id", "source_key", "display_name"):
            if not _text(getattr(self, name)):
                raise ValueError(f"{name} is required.")
        object.__setattr__(self, "source_key", _identifier(self.source_key, field_name="source_key"))
        object.__setattr__(self, "origin_category", _enum_value(OriginCategory, self.origin_category))
        object.__setattr__(self, "capture_method", _enum_value(CaptureMethod, self.capture_method))
        if self.origin_category == OriginCategory.LICENSED_EXTERNAL:
            if not _text(self.provider_name) or not _text(self.license_policy_ref):
                raise ValueError("Licensed sources require a provider and license policy reference.")

    @property
    def fingerprint(self) -> str:
        return stable_key(
            "source-registration",
            self.source_key,
            self.display_name,
            self.origin_category,
            self.capture_method,
            self.governed_owner,
            self.provider_name,
            self.authorization_basis,
            self.license_policy_ref,
            self.retention_class,
            self.sensitivity_class,
            dict(sorted(self.metadata.items())),
        )


@dataclass(frozen=True)
class EvidenceOccurrence:
    tenant_id: str
    source_key: str
    artifact_hash: str
    source_native_id: str
    source_native_version: str = "1"
    original_uri: str | None = None
    author_identity: str | None = None
    published_at: datetime | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    locator: str | None = None
    occurrence_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all(_text(v) for v in (self.tenant_id, self.source_key, self.source_native_id)):
            raise ValueError("tenant_id, source_key and source_native_id are required.")
        if len(self.artifact_hash) != 64 or any(c not in "0123456789abcdef" for c in self.artifact_hash.lower()):
            raise ValueError("artifact_hash must be a SHA-256 hex digest.")
        if self.received_at.tzinfo is None:
            raise ValueError("received_at must include a timezone.")

    @property
    def occurrence_key(self) -> str:
        return stable_key(
            "occurrence",
            self.tenant_id,
            self.source_key,
            self.source_native_id,
            self.source_native_version,
        )


@dataclass(frozen=True)
class ClaimDraft:
    tenant_id: str
    assertion_namespace: str
    subject_type: str
    subject_key: str
    metric_key: str
    claim_kind: ClaimKind | str
    production_method: ProductionMethod | str
    value_numeric: Decimal | str | int | float | None = None
    value_text: str | None = None
    unit: str | None = None
    scale: Decimal | str | int = Decimal("1")
    currency: str | None = None
    business_unit: str | None = None
    dimensions: Mapping[str, Any] = field(default_factory=dict)
    period_start: date | None = None
    period_end: date | None = None
    as_of_at: datetime | None = None
    fiscal_calendar: str | None = None
    timezone: str | None = None
    author_identity: str | None = None
    scenario_key: str | None = None
    valid_until: datetime | None = None
    assumptions: tuple[str, ...] = ()
    source_occurrence_keys: tuple[str, ...] = ()
    formula_key: str | None = None
    formula_version: str | None = None
    input_revision_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "assertion_namespace",
            "subject_type",
            "subject_key",
            "metric_key",
        ):
            if not _text(getattr(self, name)):
                raise ValueError(f"{name} is required.")
        object.__setattr__(
            self,
            "assertion_namespace",
            _identifier(self.assertion_namespace, field_name="assertion_namespace"),
        )
        object.__setattr__(self, "metric_key", _identifier(self.metric_key, field_name="metric_key"))
        object.__setattr__(self, "claim_kind", _enum_value(ClaimKind, self.claim_kind))
        object.__setattr__(self, "production_method", _enum_value(ProductionMethod, self.production_method))
        object.__setattr__(self, "value_numeric", decimal_value(self.value_numeric))
        normalized_scale = decimal_value(self.scale)
        object.__setattr__(
            self, "scale", Decimal("1") if normalized_scale is None else normalized_scale
        )
        if self.scale <= 0:
            raise ValueError("scale must be positive.")
        if self.value_numeric is None and not _text(self.value_text):
            raise ValueError("A claim requires value_numeric or value_text; missing is not a claim value.")
        if self.value_numeric is not None and not _text(self.unit):
            raise ValueError("Numeric claims require an explicit unit.")
        if self.currency:
            currency = self.currency.strip().upper()
            if len(currency) != 3 or not currency.isalpha():
                raise ValueError("currency must be a three-letter code.")
            object.__setattr__(self, "currency", currency)
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("period_end cannot precede period_start.")
        for name in ("as_of_at", "valid_until"):
            stamp = getattr(self, name)
            if stamp is not None and stamp.tzinfo is None:
                raise ValueError(f"{name} must include a timezone.")
        if self.production_method == ProductionMethod.CALCULATED:
            if not self.formula_key or not self.formula_version or not self.input_revision_ids:
                raise ValueError("Calculated claims require a versioned formula and input revisions.")
        elif self.input_revision_ids:
            raise ValueError("Only calculated claims may declare input revisions.")
        if self.claim_kind == ClaimKind.FORECAST and not self.author_identity:
            raise ValueError("Forecasts require an attributable author or provider identity.")

    @property
    def family_key(self) -> str:
        return stable_key(
            "claim-family",
            self.tenant_id,
            self.assertion_namespace,
            self.claim_kind,
            self.subject_type,
            self.subject_key,
            self.metric_key,
            self.business_unit,
            dict(sorted(self.dimensions.items())),
            self.period_start,
            self.period_end,
            self.scenario_key,
        )

    @property
    def fingerprint(self) -> str:
        base = stable_key(
            "claim-revision",
            self.family_key,
            self.claim_kind,
            self.production_method,
            self.value_numeric,
            self.value_text,
            self.unit,
            self.scale,
            self.currency,
            self.as_of_at,
            self.author_identity,
            self.valid_until,
            self.assumptions,
            self.source_occurrence_keys,
            self.formula_key,
            self.formula_version,
            self.input_revision_ids,
        )
        # Preserve legacy fingerprints. A newly versioned mapping changes the
        # extraction revision, not the assertion family or its business meaning.
        if self.metadata.get("mapping_key") and self.metadata.get("mapping_version"):
            mapped = stable_key("mapped-claim-revision", base,
                self.metadata["mapping_key"], self.metadata["mapping_version"])
            engine = self.metadata.get("mapping_engine_version")
            return stable_key("mapped-engine-revision", mapped, engine) if engine else mapped
        return base


@dataclass(frozen=True)
class ClaimRevision:
    revision_id: str
    revision_number: int
    recorded_at: datetime
    draft: ClaimDraft
    traceability: TraceabilityState | str
    supersedes_revision_id: str | None = None

    def __post_init__(self) -> None:
        if self.revision_number < 1:
            raise ValueError("revision_number must be positive.")
        if self.recorded_at.tzinfo is None:
            raise ValueError("recorded_at must include a timezone.")
        object.__setattr__(self, "traceability", _enum_value(TraceabilityState, self.traceability))


@dataclass(frozen=True)
class ClaimAssessment:
    claim_revision_id: str
    assessment_type: str
    result: str
    rule_version: str
    assessed_by: str
    assessed_at: datetime
    reasons: tuple[str, ...] = ()
    scope_key: str | None = None
    evidence_occurrence_keys: tuple[str, ...] = ()
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("claim_revision_id", "assessment_type", "result", "rule_version", "assessed_by"):
            if not _text(getattr(self, name)):
                raise ValueError(f"{name} is required.")
        if self.assessed_at.tzinfo is None:
            raise ValueError("assessed_at must include a timezone.")
        if self.valid_until is not None:
            if self.valid_until.tzinfo is None or self.valid_until <= self.assessed_at:
                raise ValueError("Review expiry must be timezone-aware and after its assessment.")
        if self.assessment_type == "forecast_review":
            if not _text(self.scope_key) or self.result not in {"accepted", "rejected"}:
                raise ValueError("Forecast review requires an explicit scope and accepted/rejected decision.")

    @property
    def fingerprint(self) -> str:
        base = stable_key(
            "claim-assessment",
            self.claim_revision_id,
            self.assessment_type,
            self.result,
            self.rule_version,
            self.assessed_by,
            self.assessed_at,
            self.reasons,
            self.scope_key,
            self.evidence_occurrence_keys,
        )
        return stable_key("expiring-assessment", base, self.valid_until) if self.valid_until else base


@dataclass(frozen=True)
class SourceAccessPolicy:
    source_key: str
    allowed_roles: frozenset[str]
    allowed_purposes: frozenset[UsePurpose | str]
    allowed_business_units: frozenset[str] = frozenset()
    export_allowed: bool = False
    external_model_allowed: bool = False
    quote_allowed: bool = False
    storage_allowed: bool = False
    index_allowed: bool = False

    def __post_init__(self) -> None:
        for name in ("export_allowed", "external_model_allowed", "quote_allowed", "storage_allowed", "index_allowed"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be an explicit boolean.")
        # An empty role set is an explicit deny-all read policy. This permits
        # storage-only quarantine without manufacturing a read authorization.
        object.__setattr__(self, "source_key", _identifier(self.source_key, field_name="source_key"))
        object.__setattr__(
            self,
            "allowed_purposes",
            frozenset(_enum_value(UsePurpose, value) for value in self.allowed_purposes),
        )

    @property
    def fingerprint(self) -> str:
        return stable_key(
            "source-policy",
            self.source_key,
            sorted(self.allowed_roles),
            sorted(str(item) for item in self.allowed_purposes),
            sorted(self.allowed_business_units),
            self.export_allowed,
            self.external_model_allowed,
            self.quote_allowed,
            self.storage_allowed,
            self.index_allowed,
        )


@dataclass(frozen=True)
class PolicyContext:
    tenant_id: str
    principal_id: str
    roles: frozenset[str]
    purpose: UsePurpose | str
    business_units: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not _text(self.tenant_id) or not _text(self.principal_id):
            raise ValueError("Tenant and principal identity are required.")
        if not self.roles:
            raise ValueError("Authenticated roles are required.")
        object.__setattr__(self, "purpose", _enum_value(UsePurpose, self.purpose))


@dataclass(frozen=True)
class ClaimQuery:
    tenant_id: str
    metric_key: str
    purpose: UsePurpose | str
    as_of_at: datetime
    allowed_claim_kinds: frozenset[ClaimKind | str]
    business_unit: str | None = None
    scenario_key: str | None = None
    require_traceability: bool = True
    require_forecast_acceptance: bool = False
    forecast_scope_key: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    fiscal_calendar: str | None = None
    subject_type: str | None = None
    subject_key: str | None = None

    def __post_init__(self) -> None:
        if not _text(self.tenant_id):
            raise ValueError("tenant_id is required.")
        object.__setattr__(self, "metric_key", _identifier(self.metric_key, field_name="metric_key"))
        if self.as_of_at.tzinfo is None:
            raise ValueError("as_of_at must include a timezone.")
        object.__setattr__(self, "purpose", _enum_value(UsePurpose, self.purpose))
        object.__setattr__(
            self,
            "allowed_claim_kinds",
            frozenset(_enum_value(ClaimKind, value) for value in self.allowed_claim_kinds),
        )
        if not self.allowed_claim_kinds or ClaimKind.UNKNOWN in self.allowed_claim_kinds:
            raise ValueError("Queries must request explicit, non-unknown claim kinds.")
        if self.require_forecast_acceptance and not _text(self.forecast_scope_key):
            raise ValueError("Accepted forecast use requires an explicit analysis scope.")
        if self.forecast_scope_key is not None and len(self.forecast_scope_key) > 160:
            raise ValueError("Forecast review scope is limited to 160 characters.")
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError('Exact period selection requires both start and end dates.')
        if self.period_start is not None:
            if type(self.period_start) is not date or type(self.period_end) is not date:
                raise ValueError('Period boundaries must be dates, not timestamps.')
            if self.period_end < self.period_start:
                raise ValueError('Period end cannot precede period start.')
        if self.fiscal_calendar is not None and (not self.fiscal_calendar.strip() or len(self.fiscal_calendar)>160):
            raise ValueError('Fiscal calendar must be an explicit identifier of at most 160 characters.')
        if (self.subject_type is None) != (self.subject_key is None):
            raise ValueError('Subject selection requires both type and key.')
        if self.subject_type is not None and (not self.subject_type.strip() or not self.subject_key.strip()
                or len(self.subject_type)>240 or len(self.subject_key)>240):
            raise ValueError('Subject type and key must be nonempty and at most 240 characters.')


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reasons: tuple[str, ...]


def policy_allows(
    *,
    context: PolicyContext,
    claim: ClaimRevision,
    source_policies: Iterable[SourceAccessPolicy],
) -> EligibilityResult:
    reasons: list[str] = []
    if context.tenant_id != claim.draft.tenant_id:
        reasons.append("tenant_mismatch")
    if (
        context.business_units
        and (not claim.draft.business_unit or claim.draft.business_unit not in context.business_units)
    ):
        reasons.append("principal_business_unit_denied")
    policies = list(source_policies)
    if not policies:
        reasons.append("source_policy_missing")
    for policy in policies:
        if not policy.storage_allowed:
            reasons.append(f"storage_denied:{policy.source_key}")
        if not context.roles.intersection(policy.allowed_roles):
            reasons.append(f"role_denied:{policy.source_key}")
        if context.purpose not in policy.allowed_purposes:
            reasons.append(f"purpose_denied:{policy.source_key}")
        if policy.allowed_business_units:
            requested_bu = claim.draft.business_unit
            if not requested_bu or requested_bu not in policy.allowed_business_units:
                reasons.append(f"business_unit_denied:{policy.source_key}")
        if context.purpose == UsePurpose.EXPORT and not policy.export_allowed:
            reasons.append(f"export_denied:{policy.source_key}")
        if context.purpose == UsePurpose.EXTERNAL_MODEL and not policy.external_model_allowed:
            reasons.append(f"external_model_denied:{policy.source_key}")
        if context.purpose == UsePurpose.QUOTATION and not policy.quote_allowed:
            reasons.append(f"quotation_denied:{policy.source_key}")
    return EligibilityResult(not reasons, tuple(sorted(set(reasons))))


def claim_is_eligible(
    claim: ClaimRevision,
    *,
    query: ClaimQuery,
    context: PolicyContext,
    source_policies: Iterable[SourceAccessPolicy],
    assessments: Iterable[ClaimAssessment] = (),
) -> EligibilityResult:
    assessments = list(assessments)
    reasons: list[str] = []
    if query.purpose != context.purpose:
        reasons.append("purpose_mismatch")
    if claim.draft.tenant_id != query.tenant_id or context.tenant_id != query.tenant_id:
        reasons.append("tenant_mismatch")
    if claim.draft.metric_key != query.metric_key:
        reasons.append("metric_mismatch")
    if claim.draft.claim_kind not in query.allowed_claim_kinds:
        reasons.append("claim_kind_not_requested")
    if query.business_unit != claim.draft.business_unit:
        reasons.append("business_unit_mismatch")
    if query.scenario_key != claim.draft.scenario_key:
        reasons.append("scenario_mismatch")
    if query.subject_type is not None and (query.subject_type != claim.draft.subject_type
            or query.subject_key != claim.draft.subject_key):
        reasons.append('subject_mismatch')
    if query.period_start is not None and (query.period_start != claim.draft.period_start or query.period_end != claim.draft.period_end):
        reasons.append('period_mismatch')
    if query.fiscal_calendar is not None and query.fiscal_calendar != claim.draft.fiscal_calendar:
        reasons.append('fiscal_calendar_mismatch')
    if claim.recorded_at > query.as_of_at:
        reasons.append("not_known_at_query_time")
    if claim.draft.as_of_at and claim.draft.as_of_at > query.as_of_at:
        reasons.append("future_as_of")
    if claim.draft.valid_until and claim.draft.valid_until <= query.as_of_at:
        reasons.append("stale")
    if query.require_traceability and claim.traceability != TraceabilityState.PRESENT:
        reasons.append("traceability_incomplete")
    for assessment in assessments:
        if assessment.claim_revision_id != claim.revision_id:
            continue
        if assessment.assessment_type == "lifecycle" and assessment.result in {
            ReviewAction.RETRACTED,
            ReviewAction.SUPERSEDED,
            ReviewAction.REJECTED,
        }:
            reasons.append(f"lifecycle:{assessment.result}")
    access = policy_allows(context=context, claim=claim, source_policies=source_policies)
    reasons.extend(access.reasons)
    if claim.draft.claim_kind == ClaimKind.FORECAST and query.require_forecast_acceptance:
        review = forecast_use_status(claim, assessments=assessments,
            scope_key=query.forecast_scope_key, at=query.as_of_at)
        if not review["eligible_for_scoped_use"]:
            reasons.append("forecast_review:" + review["status"])
    return EligibilityResult(not reasons, tuple(sorted(set(reasons))))


def forecast_use_status(claim: ClaimRevision, *, assessments: Iterable[ClaimAssessment],
                        scope_key: str | None, at: datetime) -> dict[str, Any]:
    """Review is scoped permission to use an estimate, never a promotion to fact."""
    base = {"claim_kind": str(claim.draft.claim_kind), "scope_key": scope_key,
            "eligible_for_scoped_use": False, "review_due_at": None}
    if claim.draft.claim_kind != ClaimKind.FORECAST:
        return {**base, "status": "not_a_forecast"}
    assessments = list(assessments)
    if any(a.claim_revision_id == claim.revision_id and a.assessment_type == "lifecycle"
           and a.result in {"retracted", "rejected", "superseded"}
           and a.assessed_at <= datetime.now(UTC) for a in assessments):
        return {**base, "status": "forecast_withdrawn"}
    if claim.draft.valid_until and claim.draft.valid_until <= at:
        return {**base, "status": "forecast_expired"}
    if not scope_key:
        return {**base, "status": "scope_required"}
    reviews = [a for a in assessments if a.claim_revision_id == claim.revision_id
        and a.assessment_type == "forecast_review" and a.scope_key == scope_key and a.assessed_at <= at]
    if not reviews:
        return {**base, "status": "not_reviewed_for_scope"}
    latest_at = max(a.assessed_at for a in reviews)
    latest = [a for a in reviews if a.assessed_at == latest_at]
    if len({(a.result, a.valid_until) for a in latest}) != 1:
        return {**base, "status": "conflicting_reviews"}
    review = latest[0]
    base.update(review_due_at=review.valid_until.isoformat() if review.valid_until else None,
                reviewed_by=review.assessed_by, reviewed_at=review.assessed_at.isoformat())
    if review.result != "accepted":
        return {**base, "status": "rejected_for_scope"}
    if review.valid_until is None:
        return {**base, "status": "review_date_not_supplied"}
    if review.valid_until <= at:
        return {**base, "status": "review_expired"}
    return {**base, "status": "accepted_for_scope", "eligible_for_scoped_use": True}


def provenance_view(
    claim: ClaimRevision,
    *,
    source_details: Mapping[str, Mapping[str, Any]] | None = None,
    assessments: Iterable[ClaimAssessment] = (),
    analysis_at: datetime | None = None,
    forecast_scope_key: str | None = None,
) -> dict[str, Any]:
    draft = claim.draft
    source_details = source_details or {}
    assessments = list(assessments)
    assessment_items = [
        {
            "type": item.assessment_type,
            "result": item.result,
            "rule_version": item.rule_version,
            "assessed_by": item.assessed_by,
            "assessed_at": item.assessed_at.isoformat(),
            "scope_key": item.scope_key,
            "valid_until": item.valid_until.isoformat() if item.valid_until else None,
            "reasons": list(item.reasons),
        }
        for item in assessments
        if item.claim_revision_id == claim.revision_id
    ]
    return {
        "claim_revision_id": claim.revision_id,
        "family_key": draft.family_key,
        "revision": claim.revision_number,
        "subject": {"type": draft.subject_type, "key": draft.subject_key},
        "metric_key": draft.metric_key,
        "dimensions": dict(draft.dimensions),
        "label": display_label(claim),
        "claim_kind": draft.claim_kind,
        "production_method": draft.production_method,
        "value": str(draft.value_numeric) if draft.value_numeric is not None else draft.value_text,
        "value_type": "numeric" if draft.value_numeric is not None else "text",
        "unit": draft.unit,
        "scale": str(draft.scale),
        "currency": draft.currency,
        "business_unit": draft.business_unit,
        "period": {
            "start": draft.period_start.isoformat() if draft.period_start else None,
            "end": draft.period_end.isoformat() if draft.period_end else None,
            "as_of": draft.as_of_at.isoformat() if draft.as_of_at else None,
            "valid_until": draft.valid_until.isoformat() if draft.valid_until else None,
            "timezone": draft.timezone,
            "fiscal_calendar": draft.fiscal_calendar,
        },
        "author": draft.author_identity,
        "scenario": draft.scenario_key,
        "forecast_review": forecast_use_status(claim, assessments=assessments,
            scope_key=forecast_scope_key, at=analysis_at or datetime.now(UTC))
            if draft.claim_kind == ClaimKind.FORECAST else None,
        "traceability": claim.traceability,
        "sources": [
            {"occurrence_key": key, **dict(source_details.get(key) or {})}
            for key in (
                draft.source_occurrence_keys
                if draft.source_occurrence_keys
                else tuple(sorted(source_details))
            )
        ],
        "assumptions": list(draft.assumptions),
        "interpretation": {
            key: draft.metadata[key] for key in (
                "mapping_key", "mapping_version", "mapping_engine_version", "mapping_rationale", "recorded_by", "quarantine_reasons"
            ) if key in draft.metadata
        },
        "formula": (
            {"key": draft.formula_key, "version": draft.formula_version, "inputs": list(draft.input_revision_ids)}
            if draft.production_method == ProductionMethod.CALCULATED
            else None
        ),
        "assessments": assessment_items,
    }


def display_label(claim: ClaimRevision) -> str:
    kind = claim.draft.claim_kind
    if kind == ClaimKind.FORECAST:
        author = _text(claim.draft.author_identity)
        return f"Forecast · {author}" if author else "Forecast"
    return {
        ClaimKind.ACTUAL: "Actual",
        ClaimKind.PLAN: "Plan",
        ClaimKind.ASSUMPTION: "Assumption",
        ClaimKind.REPORTED_CLAIM: "Reported claim",
        ClaimKind.UNKNOWN: "Unclassified",
    }[kind]


def explicit_claim_kind(value: Any) -> ClaimKind:
    """Map only explicit source semantics; ambiguity remains unknown."""
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "actual": ClaimKind.ACTUAL,
        "actuals": ClaimKind.ACTUAL,
        "plan": ClaimKind.PLAN,
        "budget": ClaimKind.PLAN,
        "approved_plan": ClaimKind.PLAN,
        "forecast": ClaimKind.FORECAST,
        "estimate": ClaimKind.FORECAST,
        "assumption": ClaimKind.ASSUMPTION,
        "reported_claim": ClaimKind.REPORTED_CLAIM,
    }
    return aliases.get(token, ClaimKind.UNKNOWN)
