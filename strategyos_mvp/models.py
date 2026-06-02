from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


FindingType = Literal[
    "duplicate_payment",
    "entity_resolution_duplicate",
    "off_contract_single_approver",
    "price_variance",
    "missed_early_pay_discount",
    "auto_renewal_escalation",
    "fx_hedge_unapplied",
    "dormant_credit_balance",
    "working_capital_drift",
]


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
    pattern_type: FindingType
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
    status: Literal["draft", "challenged", "locked", "disputed", "approved", "rejected"] = "draft"
    challenges: list[str] = field(default_factory=list)


@dataclass
class AuditEvent:
    round_no: int
    actor: str
    finding_id: str
    action: str
    detail: str


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
