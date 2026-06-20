from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from .config import load_config

WorkspaceRole = Literal[
    "anonymous",
    "bu",
    "operator",
    "reviewer",
    "analyst",
    "auditor",
    "executive",
    "tenant_operator",
    "tenant_admin",
    "system",
]

ConnectorKind = Literal["workspace_path", "browser_upload", "validated", "generic"]
IngestionJobStatus = Literal["staged", "validated", "resolved", "failed"]
ArtifactCategory = Literal["report", "evidence", "audit", "graph", "other"]
SurfaceVisibility = Literal["public", "protected", "restricted"]
ConnectorCapability = Literal[
    "stage_source_pack",
    "validate_manifest",
    "confirm_mapping",
    "run_from_validated_snapshot",
]

ROLE_IMPLICATIONS: dict[str, set[str]] = {
    "anonymous": {"anonymous"},
    "bu": {"bu"},
    "operator": {"operator"},
    "reviewer": {"reviewer"},
    "analyst": {"analyst"},
    "auditor": {"auditor", "reviewer"},
    "executive": {"executive"},
    "tenant_operator": {"tenant_operator", "operator", "analyst"},
    "tenant_admin": {
        "tenant_admin",
        "tenant_operator",
        "operator",
        "reviewer",
        "analyst",
        "auditor",
        "executive",
    },
    "system": {"system", "tenant_admin", "tenant_operator", "operator", "reviewer", "analyst", "auditor", "executive"},
}

ARTIFACT_TITLES: dict[str, str] = {
    "case_file": "Case file",
    "case_file_pdf": "Case file PDF",
    "working_capital": "Working capital memo",
    "qa": "Drill-down Q&A",
    "audit_log": "Audit log",
    "citation_audit": "Citation audit",
    "data_quality_json": "Data quality report JSON",
    "data_quality_md": "Data quality report Markdown",
    "knowledge_graph": "Knowledge graph",
}



@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    tenant_name: str
    workspace_id: str


@dataclass(frozen=True)
class IngestionConnector:
    connector_id: str
    kind: ConnectorKind
    display_name: str
    supports_incremental: bool = False
    supports_manual_upload: bool = False
    source_boundary: str = "workspace"
    allowed_roles: tuple[str, ...] = ("operator",)
    capabilities: tuple[ConnectorCapability, ...] = ()


@dataclass(frozen=True)
class IngestionJob:
    ingestion_job_id: str
    tenant_id: str
    connector: IngestionConnector
    source_kind: ConnectorKind
    source_ref: str
    status: IngestionJobStatus
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactContract:
    artifact_key: str
    title: str
    category: ArtifactCategory
    format: str
    path: str
    restricted: bool = False


@dataclass(frozen=True)
class RunReportContracts:
    tenant_id: str
    run_id: str | None
    evidence: list[ArtifactContract] = field(default_factory=list)
    reports: list[ArtifactContract] = field(default_factory=list)


@dataclass(frozen=True)
class CaseSummaryContract:
    case_id: str
    title: str
    status: str
    confidence: str
    owner: str
    recoverable_sar: float
    citation_count: int
    challenged: bool = False
    pattern_label: str | None = None


@dataclass(frozen=True)
class SurfaceContract:
    surface_id: str
    title: str
    visibility: SurfaceVisibility
    audience: tuple[str, ...]
    permitted: bool
    primary_route: str
    public_route: str | None = None
    actions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


INGESTION_CONNECTOR_CATALOG: dict[str, IngestionConnector] = {
    "workspace_path": IngestionConnector(
        connector_id="local.workspace_path",
        kind="workspace_path",
        display_name="Workspace folder connector",
        supports_incremental=False,
        supports_manual_upload=False,
        source_boundary="workspace",
        allowed_roles=("operator", "tenant_operator", "tenant_admin", "system"),
        capabilities=("stage_source_pack", "validate_manifest", "confirm_mapping"),
    ),
    "browser_upload": IngestionConnector(
        connector_id="local.browser_upload",
        kind="browser_upload",
        display_name="Browser upload connector",
        supports_incremental=False,
        supports_manual_upload=True,
        source_boundary="request",
        allowed_roles=("operator", "tenant_operator", "tenant_admin", "system"),
        capabilities=("stage_source_pack", "validate_manifest", "confirm_mapping"),
    ),
    "validated": IngestionConnector(
        connector_id="local.validated_source_pack",
        kind="validated",
        display_name="Validated source-pack snapshot",
        supports_incremental=False,
        supports_manual_upload=False,
        source_boundary="source_pack_cache",
        allowed_roles=("operator", "tenant_operator", "tenant_admin", "system"),
        capabilities=("run_from_validated_snapshot",),
    ),
    "generic": IngestionConnector(
        connector_id="generic.source",
        kind="generic",
        display_name="Generic ingestion connector",
        supports_incremental=False,
        supports_manual_upload=False,
        source_boundary="workspace",
        allowed_roles=("operator", "tenant_operator", "tenant_admin", "system"),
        capabilities=(),
    ),
}


def normalize_role(role: str | None) -> str:
    normalized = str(role or "anonymous").strip().lower()
    return normalized or "anonymous"


def principal_has_any_role(principal_role: str | None, *allowed_roles: str) -> bool:
    role = normalize_role(principal_role)
    expanded = ROLE_IMPLICATIONS.get(role, {role})
    if not allowed_roles:
        return True
    return any(normalize_role(item) in expanded for item in allowed_roles)


def build_tenant_context(
    *,
    tenant_id: str | None = None,
    tenant_name: str | None = None,
    workspace_id: str | None = None,
) -> TenantContext:
    config = load_config()
    resolved_tenant_id = str(tenant_id or config.tenant_slug)
    return TenantContext(
        tenant_id=resolved_tenant_id,
        tenant_name=str(tenant_name or config.tenant_name),
        workspace_id=str(workspace_id or resolved_tenant_id),
    )


def build_source_pack_connector(source_kind: str) -> IngestionConnector:
    normalized = str(source_kind or "generic").strip().lower()
    if normalized in INGESTION_CONNECTOR_CATALOG:
        return INGESTION_CONNECTOR_CATALOG[normalized]
    fallback = INGESTION_CONNECTOR_CATALOG["generic"]
    return IngestionConnector(
        connector_id=f"generic.{normalized or 'source'}",
        kind=fallback.kind,
        display_name=fallback.display_name,
        supports_incremental=fallback.supports_incremental,
        supports_manual_upload=fallback.supports_manual_upload,
        source_boundary=fallback.source_boundary,
        allowed_roles=fallback.allowed_roles,
        capabilities=fallback.capabilities,
    )


def build_ingestion_connector_catalog(*, principal_role: str | None = None) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for key in ("workspace_path", "browser_upload", "validated"):
        connector = INGESTION_CONNECTOR_CATALOG[key]
        catalog.append(
            {
                **artifact_contracts_payload(connector),
                "permitted": principal_has_any_role(principal_role, *connector.allowed_roles),
            }
        )
    return catalog


def build_source_pack_ingestion_job(
    *,
    source_pack_id: str,
    source_kind: str,
    source_ref: str,
    tenant_id: str,
    metadata: dict[str, Any] | None = None,
) -> IngestionJob:
    connector = build_source_pack_connector(source_kind)
    status: IngestionJobStatus = "validated" if source_kind == "validated" else "staged"
    job_id = sha256(
        f"{tenant_id}\0{source_pack_id}\0{connector.connector_id}\0{source_ref}".encode("utf-8")
    ).hexdigest()[:16]
    return IngestionJob(
        ingestion_job_id=job_id,
        tenant_id=tenant_id,
        connector=connector,
        source_kind=connector.kind,
        source_ref=source_ref,
        status=status,
        created_at=datetime.now(UTC).isoformat(),
        metadata={"source_pack_id": source_pack_id, **(metadata or {})},
    )


def hydrate_tenant_context(payload: Any) -> TenantContext | None:
    if not isinstance(payload, dict):
        return None
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        return None
    config = load_config()
    return TenantContext(
        tenant_id=str(tenant_id),
        tenant_name=str(payload.get("tenant_name") or config.tenant_name),
        workspace_id=str(payload.get("workspace_id") or tenant_id),
    )


def hydrate_ingestion_job(payload: Any) -> IngestionJob | None:
    if not isinstance(payload, dict):
        return None
    config = load_config()
    connector_payload = payload.get("connector")
    if not isinstance(connector_payload, dict):
        return None
    connector = IngestionConnector(
        connector_id=str(connector_payload.get("connector_id") or "generic.source"),
        kind=str(connector_payload.get("kind") or "generic"),
        display_name=str(connector_payload.get("display_name") or "Generic ingestion connector"),
        supports_incremental=bool(connector_payload.get("supports_incremental", False)),
        supports_manual_upload=bool(connector_payload.get("supports_manual_upload", False)),
        source_boundary=str(connector_payload.get("source_boundary") or "workspace"),
        allowed_roles=tuple(connector_payload.get("allowed_roles") or ("operator",)),
        capabilities=tuple(connector_payload.get("capabilities") or ()),
    )
    return IngestionJob(
        ingestion_job_id=str(payload.get("ingestion_job_id") or ""),
        tenant_id=str(payload.get("tenant_id") or config.tenant_slug),
        connector=connector,
        source_kind=str(payload.get("source_kind") or connector.kind),
        source_ref=str(payload.get("source_ref") or ""),
        status=str(payload.get("status") or "staged"),
        created_at=str(payload.get("created_at") or datetime.now(UTC).isoformat()),
        metadata=dict(payload.get("metadata") or {}),
    )


def artifact_contracts_payload(value: RunReportContracts | TenantContext | IngestionJob | Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value


def build_run_report_contracts(
    artifacts: dict[str, Any], *, tenant_id: str, run_id: str | None
) -> RunReportContracts:
    evidence: list[ArtifactContract] = []
    reports: list[ArtifactContract] = []
    for key, raw_path in artifacts.items():
        path = str(raw_path)
        contract = ArtifactContract(
            artifact_key=str(key),
            title=ARTIFACT_TITLES.get(str(key), str(key).replace("_", " ").strip().title()),
            category=_artifact_category(str(key), path),
            format=Path(path).suffix.lower().lstrip(".") or "unknown",
            path=path,
            restricted=_artifact_restricted(str(key), path),
        )
        if contract.category == "evidence":
            evidence.append(contract)
        else:
            reports.append(contract)
    return RunReportContracts(tenant_id=tenant_id, run_id=run_id, evidence=evidence, reports=reports)


def build_case_summary_contracts(
    rows: list[dict[str, Any]],
) -> list[CaseSummaryContract]:
    contracts: list[CaseSummaryContract] = []
    for row in rows:
        contracts.append(
            CaseSummaryContract(
                case_id=str(row.get("finding_id") or row.get("case_id") or ""),
                title=str(row.get("title") or "Case"),
                status=str(row.get("status") or "unknown"),
                confidence=str(row.get("confidence") or "unknown"),
                owner=str(row.get("owner") or ""),
                recoverable_sar=float(row.get("recoverable_sar") or 0.0),
                citation_count=int(row.get("citation_count") or 0),
                challenged=bool(row.get("challenged", False)),
                pattern_label=(
                    str(row.get("pattern_label"))
                    if row.get("pattern_label") is not None
                    else None
                ),
            )
        )
    return contracts


def build_surface_contract(
    *,
    surface_id: str,
    title: str,
    visibility: SurfaceVisibility,
    audience: tuple[str, ...],
    permitted: bool,
    primary_route: str,
    public_route: str | None = None,
    actions: tuple[str, ...] = (),
    notes: tuple[str, ...] = (),
) -> SurfaceContract:
    return SurfaceContract(
        surface_id=surface_id,
        title=title,
        visibility=visibility,
        audience=audience,
        permitted=permitted,
        primary_route=primary_route,
        public_route=public_route,
        actions=actions,
        notes=notes,
    )


def _artifact_category(key: str, path: str) -> ArtifactCategory:
    lowered_key = key.lower()
    lowered_path = path.lower()
    if any(token in lowered_key for token in ("citation", "data_quality")) or any(
        token in lowered_path for token in ("citation", "data quality", "ocr")
    ):
        return "evidence"
    if "graph" in lowered_key or "graph" in lowered_path:
        return "graph"
    if "audit" in lowered_key or "audit" in lowered_path:
        return "audit"
    if any(token in lowered_key for token in ("case_file", "working_capital", "qa")):
        return "report"
    return "other"


def _artifact_restricted(key: str, path: str) -> bool:
    lowered = f"{key} {path}".lower()
    return any(marker in lowered for marker in ("ocr", "citation", "case file", "excerpt"))
