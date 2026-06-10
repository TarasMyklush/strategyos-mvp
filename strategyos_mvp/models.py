from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar, Literal


@dataclass(frozen=True)
class Citation:
    source_path: str
    locator: str
    excerpt: str = ""
    source_hash: str | None = None

    def label(self) -> str:
        return f"{self.source_path} - {self.locator}"


@dataclass
class Finding:
    finding_id: str
    title: str
    pattern_type: str
    vendor_id: str
    vendor_name: str
    leakage_sar: float
    recoverable_sar: float
    recoverable_usd: float
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    classification: str
    rationale: str
    remediation: str
    citations: list[Citation] = field(default_factory=list)
    calculation: dict[str, Any] = field(default_factory=dict)
    status: Literal["draft", "challenged", "locked", "disputed", "approved", "rejected", "blocked"] = "draft"
    challenges: list[str] = field(default_factory=list)


@dataclass
class AuditEvent:
    round_no: int
    actor: str
    finding_id: str
    action: str
    detail: str
    challenge: str | None = None
    response: str | None = None
    status: str = "logged"
    confidence_before: Literal["HIGH", "MEDIUM", "LOW"] | None = None
    confidence_after: Literal["HIGH", "MEDIUM", "LOW"] | None = None
    confidence_change: str = "UNCHANGED"
    started_at: str | None = None
    completed_at: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None


@dataclass
class DataQualityIssue:
    severity: Literal["info", "warning", "critical"]
    source: str
    detail: str


@dataclass
class RunArtifacts:
    run_dir: Path
    case_file_md: Path
    working_capital_md: Path
    qa_transcript_md: Path
    audit_log_json: Path
    manifest_json: Path


CanonicalFinanceEntityType = Literal[
    "supplier_account",
    "buyer_entity",
    "payment",
    "purchase_order",
    "purchase_order_line",
    "goods_receipt",
    "contract_term",
    "credit_note",
    "fx_rate",
    "tax_registration",
]

TenantProfileLifecycleStatus = Literal[
    "draft",
    "candidate",
    "active",
    "deprecated",
    "retired",
]

FXStatus = Literal[
    "native_currency",
    "normalized",
    "missing_rate",
    "fallback_rate_used",
    "manual_override",
]

BackfillRunStatus = Literal[
    "draft",
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
]

CutoverMetricStatus = Literal[
    "pending",
    "within_threshold",
    "outside_threshold",
    "investigate",
]


@dataclass(frozen=True)
class CanonicalLineage:
    tenant_id: str
    source_system_id: str | None = None
    batch_id: str | None = None
    source_document_id: str | None = None
    source_locator: str | None = None
    parser_name: str | None = None
    parser_version: str | None = None
    profile_id: str | None = None
    profile_version: int | None = None
    canonicalization_version: str | None = None


@dataclass(frozen=True)
class CanonicalFinanceEntity:
    entity_id: str
    tenant_id: str
    canonical_key: str
    display_name: str | None = None
    entity_status: str = "active"
    version: int = 1
    effective_from: date | None = None
    effective_to: date | None = None
    lineage: CanonicalLineage | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    entity_type: ClassVar[CanonicalFinanceEntityType]

    def is_effective_on(self, as_of: date) -> bool:
        if self.effective_from and as_of < self.effective_from:
            return False
        if self.effective_to and as_of > self.effective_to:
            return False
        return True


@dataclass(frozen=True)
class SupplierAccount(CanonicalFinanceEntity):
    supplier_name: str | None = None
    supplier_tax_id: str | None = None
    supplier_registration_id: str | None = None
    payment_terms_code: str | None = None
    default_currency: str | None = None
    entity_type: ClassVar[CanonicalFinanceEntityType] = "supplier_account"


@dataclass(frozen=True)
class BuyerEntity(CanonicalFinanceEntity):
    buyer_name: str | None = None
    buyer_tax_id: str | None = None
    legal_entity_code: str | None = None
    reporting_currency: str | None = None
    entity_type: ClassVar[CanonicalFinanceEntityType] = "buyer_entity"


@dataclass(frozen=True)
class Payment(CanonicalFinanceEntity):
    payment_reference: str | None = None
    invoice_reference: str | None = None
    supplier_account_key: str | None = None
    payment_date: date | None = None
    payment_amount: Decimal | None = None
    payment_currency: str | None = None
    entity_type: ClassVar[CanonicalFinanceEntityType] = "payment"


@dataclass(frozen=True)
class PurchaseOrder(CanonicalFinanceEntity):
    po_number: str | None = None
    supplier_account_key: str | None = None
    order_date: date | None = None
    order_status: str | None = None
    total_amount: Decimal | None = None
    currency: str | None = None
    entity_type: ClassVar[CanonicalFinanceEntityType] = "purchase_order"


@dataclass(frozen=True)
class PurchaseOrderLine(CanonicalFinanceEntity):
    purchase_order_key: str | None = None
    line_number: str | None = None
    item_description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    currency: str | None = None
    entity_type: ClassVar[CanonicalFinanceEntityType] = "purchase_order_line"


@dataclass(frozen=True)
class GoodsReceipt(CanonicalFinanceEntity):
    goods_receipt_number: str | None = None
    purchase_order_key: str | None = None
    receipt_date: date | None = None
    received_quantity: Decimal | None = None
    entity_type: ClassVar[CanonicalFinanceEntityType] = "goods_receipt"


@dataclass(frozen=True)
class ContractTerm(CanonicalFinanceEntity):
    contract_reference: str | None = None
    supplier_account_key: str | None = None
    price_basis: str | None = None
    discount_terms: str | None = None
    entity_type: ClassVar[CanonicalFinanceEntityType] = "contract_term"


@dataclass(frozen=True)
class CreditNote(CanonicalFinanceEntity):
    credit_note_number: str | None = None
    supplier_account_key: str | None = None
    invoice_reference: str | None = None
    credit_amount: Decimal | None = None
    currency: str | None = None
    entity_type: ClassVar[CanonicalFinanceEntityType] = "credit_note"


@dataclass(frozen=True)
class FXRate(CanonicalFinanceEntity):
    source_currency: str = ""
    reporting_currency: str = ""
    rate_source: str = ""
    rate_date: date | None = None
    rate_value: Decimal | None = None
    fallback_allowed: bool = False
    entity_type: ClassVar[CanonicalFinanceEntityType] = "fx_rate"


@dataclass(frozen=True)
class TaxRegistration(CanonicalFinanceEntity):
    party_key: str | None = None
    tax_country_code: str | None = None
    tax_registration_number: str | None = None
    entity_type: ClassVar[CanonicalFinanceEntityType] = "tax_registration"


@dataclass(frozen=True)
class TenantProfileVersion:
    tenant_id: str
    profile_id: str
    version: int
    document_type: str
    lifecycle_status: TenantProfileLifecycleStatus
    field_aliases: dict[str, list[str]] = field(default_factory=dict)
    required_fields: list[str] = field(default_factory=list)
    parser_preference_order: list[str] = field(default_factory=list)
    validation_rules: dict[str, Any] = field(default_factory=dict)
    base_profile_id: str | None = None
    base_profile_version: int | None = None
    approver: str | None = None
    activated_at: datetime | None = None

    def supports_shadow_runs(self) -> bool:
        return self.lifecycle_status in {"candidate", "active", "deprecated"}

    def supports_new_jobs(self) -> bool:
        return self.lifecycle_status == "active"


@dataclass(frozen=True)
class FXNormalization:
    reporting_currency: str
    fx_rate_source: str | None = None
    fx_rate_date: date | None = None
    fx_rate_value: Decimal | None = None
    normalized_total_amount: Decimal | None = None
    normalized_tax_amount: Decimal | None = None
    fx_status: FXStatus = "missing_rate"

    def supports_reporting_total(self) -> bool:
        return self.fx_status in {
            "native_currency",
            "normalized",
            "fallback_rate_used",
            "manual_override",
        } and self.normalized_total_amount is not None


@dataclass(frozen=True)
class BackfillRun:
    tenant_id: str
    backfill_run_id: str
    status: BackfillRunStatus
    batch_id: str | None = None
    legacy_run_id: str | None = None
    parser_name: str | None = None
    parser_version: str | None = None
    profile_id: str | None = None
    profile_version: int | None = None
    canonicalization_version: str | None = None

    def is_terminal(self) -> bool:
        return self.status in {"completed", "failed", "cancelled"}


@dataclass(frozen=True)
class CutoverMetricThreshold:
    max_delta_value: Decimal | None = None
    max_delta_ratio: Decimal | None = None


@dataclass(frozen=True)
class CutoverMetric:
    tenant_id: str
    metric_key: str
    sample_window_label: str
    legacy_value: Decimal | None = None
    canonical_value: Decimal | None = None
    threshold: CutoverMetricThreshold | None = None
    status: CutoverMetricStatus = "pending"
    exclusion_breakdown: dict[str, int] = field(default_factory=dict)

    def delta_value(self) -> Decimal | None:
        if self.legacy_value is None or self.canonical_value is None:
            return None
        return self.canonical_value - self.legacy_value

    def delta_ratio(self) -> Decimal | None:
        delta = self.delta_value()
        if delta is None or self.legacy_value in (None, Decimal("0")):
            return None
        return delta / self.legacy_value

    def within_threshold(self) -> bool | None:
        if self.threshold is None:
            return None
        delta_value = self.delta_value()
        delta_ratio = self.delta_ratio()
        if self.threshold.max_delta_value is not None and delta_value is not None:
            if abs(delta_value) > self.threshold.max_delta_value:
                return False
        if self.threshold.max_delta_ratio is not None and delta_ratio is not None:
            if abs(delta_ratio) > self.threshold.max_delta_ratio:
                return False
        if (
            self.threshold.max_delta_value is None
            and self.threshold.max_delta_ratio is None
        ):
            return None
        return True
