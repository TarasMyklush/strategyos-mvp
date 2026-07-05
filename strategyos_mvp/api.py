from __future__ import annotations

import asyncio
import html
import json
import re
import socket
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlparse
from uuid import UUID, uuid4

try:
    from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except Exception as exc:  # pragma: no cover - optional cloud dependency
    raise RuntimeError(
        "FastAPI and pydantic are required to run the StrategyOS API."
    ) from exc

from .auth import (
    authenticate_optional_request,
    require_live_health_access,
    require_role,
)
from .config import CONFIG
from .executive_design import (
    executive_activity_design,
    executive_board_design,
    executive_discover_agents_design,
    executive_persona_design,
    executive_public_assistant_packet,
    executive_running_agents_design,
    executive_subtools_design,
)
from .assistants import get_orchestrator, list_supported_personas
from .ingestion import load_dataset
from .neo4j_store import check_neo4j_ready, graph_status_for_run
from .ocr import runtime_dependency_status
from .prepare_inputs import prepare_agent_input
from .scenario_parser import SCENARIO_SUGGESTIONS, parse_scenario
from .platform_foundation import (
    ARTIFACT_TITLES,
    DomainMetricContract,
    DomainNodeContract,
    PlanHealthContract,
    StrategyIntentContract,
    StrategyKpiNodeContract,
    StrategyReasoningContract,
    ValueDriverContract,
    artifact_contracts_payload,
    build_case_summary_contracts,
    build_domain_filter_contracts,
    build_ingestion_connector_catalog,
    build_run_report_contracts,
    build_surface_contract,
    build_switcher_contracts,
    build_tenant_context,
    principal_has_any_role,
)
from . import qa as qa_engine
from . import llm_qa
from .skills.finance_controls import run_all_finance_skills
from .reviewer_runtime import resume_reviewed_run
from .run_registry import (
    discover_run_history,
    load_latest_run_summary,
    update_run_pointers,
)
from .run_poc import run_strategyos_workflow
from .run_executor import RunExecutionUnavailable, submit_run
from .runtime_governance import annotate_governance_state, local_run_id_for_dir
from .oracle_finance import (
    BUFlexfieldMappingConfig,
    build_oracle_leakage_review_payload,
    build_oracle_pilot_kpi_payload,
    build_oracle_pilot_lineage_payload,
    build_oracle_pilot_readiness_report,
    build_oracle_pilot_reconciliation_report,
    build_oracle_pilot_rollout_report,
    compute_oracle_pilot_kpis,
    compute_oracle_pilot_leakage,
    ingest_oracle_pilot_extracts,
    load_pilot_extract_batch,
    snapshot_summary,
)
from . import state_store
from .state_store import data_management_status, database_connection
from .storage import ObjectStoreUnavailable, S3CompatibleStore, object_store_status
from .source_pack import (
    confirm_source_pack_mapping,
    resolve_source_pack_for_run,
    stage_source_pack_from_path,
    stage_source_pack_uploads,
    validate_source_pack,
)
from .vector_store import (
    check_qdrant_ready,
    search_run_vectors,
    vector_status_for_run,
)


ANONYMOUS_PUBLIC_RUN_ID = "latest-public"
_LLM_PROVIDER_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="strategyos-llm")
_LLM_PROVIDER_SEMAPHORE = asyncio.Semaphore(8)
PUBLIC_EVIDENCE_BOUNDARY_NOTE = (
    "Evidence preview is available only on the protected reviewer/operator surface."
)
ANONYMOUS_PUBLIC_BANNED_KEYS = {
    "vendor_id",
    "vendor_name",
    "finding_id",
    "case_id",
    "citation_id",
    "evidence_document_id",
    "locator",
    "resolved",
    "resolved_payload",
    "source_hash",
    "source_path",
    "node_id",
    "owner",
}


class RunRequest(BaseModel):
    dataset: str | None = None
    source_pack_id: str | None = None
    run_dir: str | None = None
    skip_prepare: bool = False
    sync_artifacts: bool | None = None
    allow_partial_source_pack: bool = False


class ReviewerDecisionRequest(BaseModel):
    comment: str | None = None
    payload: dict[str, Any] | None = None


class SourcePackPathRequest(BaseModel):
    folder_path: str


class SourcePackValidateRequest(BaseModel):
    source_pack_id: str


class SourcePackMappingConfirmRequest(BaseModel):
    source_pack_id: str
    relative_path: str
    role: str | None = None
    column_mapping: dict[str, str] | None = None


class IngestionConnectorsResponse(BaseModel):
    tenant_context: dict[str, str]
    connectors: list[dict[str, Any]]


class OracleBUFlexfieldMappingRequest(BaseModel):
    segment_name: str
    segment_index: int
    value_to_bu: dict[str, str]
    default_bu: str | None = None


class OracleFinanceIngestionRequest(BaseModel):
    extracts: dict[str, list[dict[str, Any]]]
    bu_mapping: OracleBUFlexfieldMappingRequest
    manual_inputs: list[dict[str, Any]] | None = None
    reporting_currency: str | None = "SAR"
    tenant_id: UUID
    batch_id: UUID | None = None
    source_system_id: UUID | None = None


class OraclePilotValidationRequest(BaseModel):
    extracts: dict[str, list[dict[str, Any]]]
    bu_mapping: OracleBUFlexfieldMappingRequest
    manual_inputs: list[dict[str, Any]] | None = None
    reporting_currency: str | None = "SAR"
    reporting_period_key: str
    reporting_cadence: str | None = None
    approval_status: str | None = "pending"
    reviewer_actions: list[dict[str, Any]] | None = None


class QaRequest(BaseModel):
    question: str
    run_id: str | None = None
    mode: str | None = "auto"
    persona: str | None = None
    trace_id: str | None = None
    knowledge_id: str | None = None
    context: dict[str, Any] | None = None
    driver_context: dict[str, Any] | None = None
    assistant_context: dict[str, Any] | None = None
    source: str | None = None
    entrypoint: str | None = None


class AssistantChatRequest(BaseModel):
    question: str
    run_id: str | None = None
    mode: str | None = "auto"
    persona: str | None = None
    trace_id: str | None = None
    knowledge_id: str | None = None
    context: dict[str, Any] | None = None
    driver_context: dict[str, Any] | None = None
    assistant_context: dict[str, Any] | None = None
    source: str | None = None
    entrypoint: str | None = None


from .twins.api import (
    require_twin_dashboard_access,
    router as twin_router,
    twin_operational_health_payload,
)

app = FastAPI(title="StrategyOS MVP API", version="0.1.0")
STATIC_DIR = Path(__file__).with_name("static")
TWINS_STATIC_DIR = Path(__file__).parent / "twins" / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(twin_router)

ARTIFACT_PREVIEW_LIMIT_BYTES = 24_000
ARTIFACT_JSON_PARSE_LIMIT_BYTES = 200_000
ARTIFACT_ACCESS_AUDIT_LOG = "StrategyOS Artifact Access Audit.jsonl"
KNOWLEDGE_GRAPH_ARTIFACT_KEY = "knowledge_graph"
KNOWLEDGE_GRAPH_DEFAULT_VIEW = "findings"
KNOWLEDGE_GRAPH_FULL_LIMIT = 300
KNOWLEDGE_GRAPH_EXPAND_LIMIT = 25
KNOWLEDGE_GRAPH_BASE_EDGE_LABELS = {
    "SUPPORTED_BY",
    "INVOLVES_VENDOR",
    "HAS_CONTRACT",
    "SAME_BANK_ACCOUNT_AS",
    "SAME_TAX_ID_AS",
}
KNOWLEDGE_GRAPH_EXPAND_EDGE_LABELS = {
    "ISSUED_INVOICE",
    "ISSUED_PO",
}
KNOWLEDGE_GRAPH_VISIBLE_EDGE_LABELS = (
    KNOWLEDGE_GRAPH_BASE_EDGE_LABELS
    | KNOWLEDGE_GRAPH_EXPAND_EDGE_LABELS
    | {"MATCHES_PO"}
)
RESTRICTED_ARTIFACT_KEYS = {
    "case_file",
    "case_file_pdf",
    "citation_audit",
    "data_quality_json",
}
RESTRICTED_ARTIFACT_KEY_MARKERS = ("ocr", "citation", "excerpt")
RESTRICTED_ARTIFACT_PATH_MARKERS = (
    "case file",
    "citation audit",
    "ocr",
    "excerpt",
)
PUBLIC_REPORT_ARTIFACT_KEYS = ("working_capital", "summary")
PUBLIC_EVIDENCE_EXCERPT_LIMIT = 600
ORACLE_INGEST_MAX_EXTRACT_BYTES = 2_000_000
ORACLE_INGEST_MAX_MANUAL_INPUT_BYTES = 250_000
UI_LIFECYCLE_STAGES: list[tuple[str, str]] = [
    ("created", "Created"),
    ("ingest", "Ingest"),
    ("analyst", "Analyst"),
    ("auditor", "Auditor"),
    ("evidence_qa", "Evidence QA"),
    ("knowledge_graph", "Knowledge graph"),
    ("awaiting_review", "Awaiting human review"),
    ("writer", "Writer / completed"),
]
UI_LIFECYCLE_STAGE_ALIASES = {
    "governed_review": "awaiting_review",
    "completed": "writer",
}
# Plain-language titles for detector pattern_type values, served alongside
# findings so the business UI never has to render a raw snake_case identifier
# (fix-list item 7). Mirrors PATTERN_LABELS in static/app.js.
PATTERN_LABELS: dict[str, str] = {
    "duplicate_payment": "Duplicate payment",
    "entity_resolution_duplicate": "Duplicate vendor identity",
    "off_contract_single_approver": "Off-contract spend, single approver",
    "price_variance": "Price variance vs PO",
    "missed_early_pay_discount": "Missed early-payment discount",
    "auto_renewal_escalation": "Auto-renewal escalation",
    "fx_hedge_unapplied": "FX hedge not applied",
    "dormant_credit_balance": "Dormant supplier credit",
    "vendor_collusion_ring": "Vendor collusion ring",
}
PRODUCT_READ_ROLES = ("operator", "reviewer", "bu", "analyst", "executive")
SYSTEM_READ_ROLES = (
    "operator",
    "reviewer",
    "analyst",
    "executive",
    "tenant_operator",
    "tenant_admin",
    "system",
)
REVIEW_READ_ROLES = ("operator", "reviewer", "bu")
INVESTIGATION_ROLES = ("operator", "reviewer", "analyst")
REVIEW_WORKFLOW_ROLES = ("operator", "reviewer")
EXECUTIVE_PERSONA_ALIASES = {"pharma": "gm", "distribution": "bucfo"}
EXECUTIVE_PERSONA_IDS = {"ceo", "cfo", "gm", "bucfo", "logistics", "board"}
EXECUTIVE_BOARD_STATES = {"pre", "live", "closed"}


def _principal_prefers_public_safe_surface(principal: dict[str, Any] | None) -> bool:
    role = str((principal or {}).get("role") or "anonymous")
    authenticated = bool((principal or {}).get("authenticated"))
    return (not authenticated) or principal_has_any_role(role, "executive")


def _humanize_pattern_label(pattern_type: Any) -> str:
    key = str(pattern_type or "").strip().lower()
    if not key:
        return ""
    if key in PATTERN_LABELS:
        return PATTERN_LABELS[key]
    return key.replace("_", " ").strip().title()


def _normalize_lifecycle_stage(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "created"
    return UI_LIFECYCLE_STAGE_ALIASES.get(normalized, normalized)


def _requested_executive_view_state(
    *,
    persona: str | None = None,
    board: str | None = None,
    driver: str | None = None,
    company: str | None = None,
    portfolio: str | None = None,
    week: str | None = None,
    agent: str | None = None,
) -> dict[str, str | None]:
    requested_persona = str(persona or "").strip().lower() or None
    requested_persona = EXECUTIVE_PERSONA_ALIASES.get(
        str(requested_persona), requested_persona
    )
    if requested_persona not in EXECUTIVE_PERSONA_IDS:
        requested_persona = None
    requested_board = str(board or "").strip().lower() or None
    if requested_board not in EXECUTIVE_BOARD_STATES:
        requested_board = None
    requested_driver = str(driver or "").strip().lower() or None
    if not requested_driver:
        requested_driver = None
    requested_week = str(week or "").strip().lower() or None
    if not requested_week:
        requested_week = None
    requested_agent = str(agent or "").strip().lower() or None
    if not requested_agent:
        requested_agent = None
    requested_company = str(company or CONFIG.company_slug or "current").strip() or "current"
    requested_portfolio = str(portfolio or CONFIG.portfolio_slug or "all").strip() or "all"
    return {
        "persona": requested_persona,
        "board": requested_board,
        "driver": requested_driver,
        "company": requested_company,
        "portfolio": requested_portfolio,
        "week": requested_week,
        "agent": requested_agent,
    }


def _build_executive_route(
    view_state: dict[str, Any] | None = None,
    *,
    base_route: str = "/app",
) -> str:
    params = {
        key: value
        for key, value in (view_state or {}).items()
        if value not in (None, "")
    }
    if not params:
        return base_route
    query_string = "&".join(
        f"{quote(str(key), safe='')}={quote(str(value), safe='')}"
        for key, value in params.items()
    )
    return f"{base_route}?{query_string}" if query_string else base_route


def _assistant_requested_view_state(
    *,
    persona: str | None,
    assistant_context: dict[str, Any] | None,
    driver_context: dict[str, Any] | None,
) -> dict[str, str | None]:
    assistant_context = assistant_context or {}
    driver_context = driver_context or {}
    return _requested_executive_view_state(
        persona=assistant_context.get("persona") or persona,
        board=assistant_context.get("board_state") or assistant_context.get("board"),
        driver=(
            assistant_context.get("driver_key")
            or assistant_context.get("driver")
            or driver_context.get("key")
            or driver_context.get("driver_key")
        ),
        company=assistant_context.get("company"),
        portfolio=assistant_context.get("portfolio"),
        week=assistant_context.get("week_key") or assistant_context.get("week"),
        agent=assistant_context.get("agent_id") or assistant_context.get("agent"),
    )


def _run_lifecycle_timeline(record: dict[str, Any]) -> list[dict[str, Any]]:
    latest_checkpoint = record.get("latest_checkpoint") or {}
    approval = record.get("approval") or {}
    approval_status = str(
        approval.get("approval_status")
        or record.get("approval_status")
        or latest_checkpoint.get("state_json", {}).get("approval_status")
        or "pending"
    ).lower()
    status = str(record.get("status") or latest_checkpoint.get("status") or "").lower()
    current_stage = _normalize_lifecycle_stage(
        record.get("current_stage")
        or latest_checkpoint.get("stage")
        or latest_checkpoint.get("state_json", {}).get("current_stage")
    )
    if status == "completed":
        current_stage = "writer"

    stage_order = [stage for stage, _label in UI_LIFECYCLE_STAGES]
    try:
        current_index = stage_order.index(current_stage)
    except ValueError:
        current_index = 0
        current_stage = "created"

    timeline: list[dict[str, Any]] = []
    for index, (stage, label) in enumerate(UI_LIFECYCLE_STAGES):
        state = "pending"
        detail = "Not reached yet."
        if index < current_index:
            state = "completed"
            detail = "Completed before the current workflow position."
        elif index == current_index:
            state = "current"
            detail = "Current workflow position."

        if stage == "created":
            detail = (
                f"Run created at {record.get('created_at')}."
                if record.get("created_at")
                else "Run record created."
            )
        elif stage == "awaiting_review":
            if approval_status == "approved":
                state = "completed" if current_stage == "writer" else "current"
                detail = "Reviewer approved the governed pause; operator resume is allowed."
            elif approval_status == "rejected":
                state = "rejected"
                detail = "Reviewer rejected the run; workflow must not resume as completed."
            elif current_stage == "awaiting_review" or status == "awaiting_review":
                state = "blocked"
                detail = "Paused for mandatory reviewer decision."
        elif stage == "writer":
            if current_stage == "writer" or status == "completed":
                state = "completed"
                detail = "Workflow resumed through writer and completed."
            elif approval_status == "approved":
                detail = "Ready for operator resume into writer/completed."
            elif approval_status == "rejected":
                detail = "Blocked until a new approved governed review path exists."

        timeline.append(
            {
                "stage": stage,
                "label": label,
                "state": state,
                "detail": detail,
                "is_current": stage == current_stage,
            }
        )
    return timeline


def _latest_summary() -> dict[str, Any] | None:
    summary = load_latest_run_summary()
    if summary is None:
        return None
    return _with_local_run_identity(summary)


def _latest_run_public_payload(
    summary: dict[str, Any] | None,
    *,
    view_state: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    if summary is None:
        return {"status": "missing", "public_safe": True, "run_id": ANONYMOUS_PUBLIC_RUN_ID}
    effective_view_state = dict(view_state or _requested_executive_view_state())
    public_packet_persona = str(effective_view_state.get("persona") or "ceo")
    assistant_public_context = executive_public_assistant_packet(public_packet_persona)
    summary = _anonymous_public_summary(summary)
    assert summary is not None
    rows = _anonymous_public_finding_payloads(_finding_rows_from_summary(summary))
    audit_summary = _latest_run_audit_summary_payload(summary)
    metrics = _governed_metrics_payload(summary, rows, audit_summary)
    publication = _summary_publication_payload(
        summary,
        principal_role="executive",
        public_safe=True,
    )
    principal = {"role": "executive", "authenticated": False}
    board_portal = _board_portal_payload(
        summary,
        principal_role="executive",
        public_safe=True,
        requested_state=(view_state or {}).get("board"),
    )
    strategy_substrate = _strategy_substrate_payload(summary, rows, audit_summary, principal)
    executive_modes = _executive_modes_payload(
        summary,
        principal,
        strategy_substrate=strategy_substrate,
        board_portal=board_portal,
        publication=publication,
        view_state=view_state,
    )
    drilldown = _drilldown_contract_payload(
        summary,
        principal,
        public_safe=True,
        finding_rows=rows,
        domain_filters=[],
        report_artifacts=list((_summary_report_contracts(summary).get("reports") or [])),
        board_portal=board_portal,
        executive_modes=executive_modes,
    )
    agent_modules = _agent_modules_payload(summary, rows, audit_summary, principal)
    agents = _agents_surface_payload(summary, principal)
    chat = _chat_threads_payload(
        summary,
        principal,
        executive_modes=executive_modes,
        board_portal=board_portal,
        publication=publication,
    )
    return _sanitize_anonymous_public_payload({
        "status": "ok",
        "run_id": summary.get("run_id"),
        "current_stage": summary.get("current_stage"),
        "approval_status": summary.get("approval_status"),
        "requires_human_review": bool(summary.get("requires_human_review")),
        "total_recoverable_sar": metrics["total_recoverable_sar"],
        "locked_findings": metrics["locked_findings"],
        "citation_count": metrics["citation_count"],
        "resolved_count": metrics["resolved_count"],
        "challenged_cases": metrics["challenged_count"],
        "report_count": metrics["report_count"],
        "plan_health": _bounded_plan_health_payload(summary, rows, audit_summary),
        "trend": _trend_card_payload(summary, rows, audit_summary),
        "strategy_substrate": strategy_substrate,
        "publication": publication,
        "board_portal": board_portal,
        "executive_modes": executive_modes,
        "drilldown": drilldown,
        "interaction_contracts": _interaction_contracts_payload(principal, public_safe=True),
        "assistant_public_context": assistant_public_context,
        "agents": agents,
        "agent_modules": agent_modules,
        "chat": chat,
        "role_actions": _role_actions_payload(summary, rows, audit_summary, principal),
        "executive_diagnostics": _executive_diagnostics_payload(
            summary,
            principal=principal,
            board_portal=board_portal,
            executive_modes=executive_modes,
            drilldown=drilldown,
            strategy_substrate=strategy_substrate,
            agent_modules=agent_modules,
            audit_summary=audit_summary,
            finding_rows=rows,
        ),
        "public_safe": True,
    })


def _anonymous_public_summary(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(summary, dict):
        return None
    payload = dict(summary)
    payload["run_id"] = ANONYMOUS_PUBLIC_RUN_ID
    payload.pop("run_dir", None)
    return payload


def _public_latest_run_audit_summary_payload(
    summary: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {"status": "missing", "public_safe": True}
    return {
        "status": "ok",
        "run_id": ANONYMOUS_PUBLIC_RUN_ID,
        "citation_count": None,
        "resolved_count": None,
        "public_safe": True,
    }


def _public_packet_citation(locator: str, excerpt: str = "") -> dict[str, Any]:
    return {
        "source_path": "public_packet://executive_surface",
        "locator": locator,
        "excerpt": excerpt,
    }


def _public_amount_from_text(text: str, *, unit: str = "sar") -> float | None:
    match = re.search(r"(?:SAR|USD)\s*([0-9]+(?:\.[0-9]+)?)\s*([MBK])?", str(text or ""), re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    suffix = str(match.group(2) or "").upper()
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return value * multiplier


def _public_pct_from_text(text: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", str(text or ""))
    return float(match.group(1)) if match else None


def _build_public_safe_assistant_packet(persona_id: str) -> dict[str, Any]:
    persona_key = str(persona_id or "ceo").strip().lower() or "ceo"
    persona = executive_persona_design(persona_key)
    board = executive_board_design()
    activity = executive_activity_design()
    running_agents = executive_running_agents_design()
    board_decks = list(board.get("decks") or [])
    board_meeting = dict(board.get("meeting") or {})
    drivers = list(persona.get("drivers") or [])
    findings = list(persona.get("findings") or [])
    developments = list(persona.get("developments") or [])
    week = list(persona.get("week") or [])

    revenue_driver = next((item for item in drivers if str(item.get("key") or "") in {"revenue", "revq", "urev", "drev"}), {})
    epharmacy_driver = next((item for item in drivers if "pharmacy" in str(item.get("key") or "") or "pharmacy" in str(item.get("label") or "").lower()), {})
    fx_driver = next((item for item in drivers if any(term in str(item.get("key") or "") for term in ("fx", "hedge", "bridge")) or "hedge" in str(item.get("label") or "").lower()), {})
    digital_health_driver = next((item for item in drivers if "digital" in str(item.get("key") or "") or "digital health" in str(item.get("label") or "").lower()), {})
    healthcare_driver = next((item for item in drivers if "healthcare" in str(item.get("key") or "") or "healthcare" in str(item.get("label") or "").lower()), {})

    tamween_dev = next((item for item in developments if "tamween" in str(item.get("title") or "").lower()), {})
    recoverable_finding = next((item for item in findings if "recoverable" in str(item.get("title") or "").lower()), {})
    fx_finding = next((item for item in findings if "fx" in str(item.get("title") or "").lower()), {})
    board_pack = next((item for item in running_agents if "board pack" in str(item.get("name") or "").lower()), {})
    hedge_agent = next((item for item in running_agents if "hedge" in str(item.get("name") or "").lower()), {})
    leakage_agent = next((item for item in running_agents if "leakage" in str(item.get("name") or "").lower()), {})

    facts = {
        "group_recoverable_sar": _public_amount_from_text(
            str(recoverable_finding.get("title") or "") + " " + str(recoverable_finding.get("detail") or "")
        ),
        "tamween_recoverable_sar": _public_amount_from_text(
            str(tamween_dev.get("title") or "") + " " + str(tamween_dev.get("impact") or "")
        ),
        "tamween_margin_uplift_bps": _public_pct_from_text(str(tamween_dev.get("impact") or "")),
        "epharmacy_orders_wow_pct": _public_pct_from_text(
            str(epharmacy_driver.get("sub") or "")
            + " "
            + " ".join(str(item.get("delta") or "") for item in ((epharmacy_driver.get("movers") or {}).get("lifting") or []))
        ),
        "board_pack_progress_pct": _public_pct_from_text(str(activity.get("line") or ""))
        or float(board_pack.get("progress") or 0),
        "fx_margin_drag_sar_per_week": _public_amount_from_text(
            str(fx_driver.get("story") or "")
            + " "
            + " ".join(str(item.get("delta") or "") for item in ((fx_driver.get("movers") or {}).get("dragging") or []))
        ),
        "hedge_coverage_pct": _public_pct_from_text(
            str(fx_driver.get("story") or "")
            + " "
            + str(fx_finding.get("detail") or "")
            + " "
            + str(hedge_agent.get("doing") or "")
        ),
        "hedge_margin_recovery_bps": None,
        "healthcare_occupancy_pct": _public_pct_from_text(str(healthcare_driver.get("value") or "")),
        "digital_health_value_sar": _public_amount_from_text(str(digital_health_driver.get("value") or "")),
    }
    if facts["tamween_margin_uplift_bps"] is None and "bps" in str(tamween_dev.get("impact") or "").lower():
        match = re.search(r"~?\s*([0-9]+(?:\.[0-9]+)?)\s*bps", str(tamween_dev.get("impact") or ""), re.IGNORECASE)
        facts["tamween_margin_uplift_bps"] = float(match.group(1)) if match else None
    hedge_recovery_match = re.search(
        r"recovers?\s*~?\s*([0-9]+(?:\.[0-9]+)?)\s*bps",
        " ".join(
            [
                str(fx_driver.get("story") or ""),
                str(hedge_agent.get("doing") or ""),
                str(fx_finding.get("detail") or ""),
            ]
        ),
        re.IGNORECASE,
    )
    if hedge_recovery_match:
        facts["hedge_margin_recovery_bps"] = float(hedge_recovery_match.group(1))

    kg_nodes = [
        {"id": "driver:revenue", "label": "Revenue", "properties": {"domain": "revenue", "name": revenue_driver.get("label") or "Revenue"}},
        {"id": "driver:epharmacy", "label": "e-Pharmacy", "properties": {"domain": "growth", "name": epharmacy_driver.get("label") or "e-Pharmacy growth"}},
        {"id": "driver:fx", "label": "FX hedge", "properties": {"domain": "margin", "name": fx_driver.get("label") or "FX / hedge coverage"}},
        {"id": "finding:recoverable", "label": "SAR 8.6M recoverable", "properties": {"domain": "leakage", "name": recoverable_finding.get("title") or "SAR 8.6M recoverable"}},
        {"id": "finding:tamween", "label": "Tamween audit", "properties": {"domain": "leakage", "name": tamween_dev.get("title") or "Tamween audit"}},
    ]
    kg_edges = [
        {"source": "driver:epharmacy", "target": "driver:revenue", "label": "LIFTS"},
        {"source": "driver:fx", "target": "driver:revenue", "label": "DRAGS"},
        {"source": "finding:tamween", "target": "finding:recoverable", "label": "CONTRIBUTES_TO"},
        {"source": "finding:recoverable", "target": "driver:fx", "label": "BOARD_DISCUSSION_ALONGSIDE"},
    ]
    assistant_findings = [
        {
            "finding_id": f"public-{index + 1}",
            "title": item.get("title"),
            "pattern_type": "finance_leakage" if "recoverable" in str(item.get("title") or "").lower() else "public_signal",
            "classification": item.get("tag") or "public-safe",
            "rationale": item.get("detail") or item.get("impact") or "",
            "citations": [
                _public_packet_citation(
                    f"personas.{persona_key}.findings[{index}]",
                    str(item.get("detail") or "")[:240],
                )
            ],
        }
        for index, item in enumerate(findings)
    ] + [
        {
            "finding_id": f"public-dev-{index + 1}",
            "title": item.get("title"),
            "pattern_type": "finance_leakage" if "tamween" in str(item.get("title") or "").lower() else "public_signal",
            "classification": item.get("meta") or "public-safe",
            "rationale": item.get("impact") or "",
            "citations": [
                _public_packet_citation(
                    f"personas.{persona_key}.developments[{index}]",
                    str(item.get("impact") or "")[:240],
                )
            ],
        }
        for index, item in enumerate(developments)
    ]
    return {
        "packet_id": f"latest-public:{persona_key}",
        "source": "server_public_executive_packet",
        "persona_id": persona_key,
        "persona": persona,
        "drivers": drivers,
        "findings": findings,
        "developments": developments,
        "week": week,
        "board": board,
        "activity": activity,
        "running_agents": running_agents,
        "board_decks": board_decks,
        "board_meeting": board_meeting,
        "facts": facts,
        "kg_nodes": kg_nodes,
        "kg_edges": kg_edges,
        "assistant_findings": assistant_findings,
        "trace_summary": {
            "truth_basis": [
                "public_packet.persona",
                "public_packet.board",
                "public_packet.activity",
                "public_packet.running_agents",
            ],
            "board_governance": board.get("governance"),
            "board_pack_progress_pct": facts.get("board_pack_progress_pct"),
            "leakage_scan_progress_pct": leakage_agent.get("progress"),
        },
    }


def _anonymous_public_case_title(row: dict[str, Any], *, index: int) -> str:
    label = str(row.get("pattern_label") or row.get("pattern_type") or "Governed case").strip()
    if not label:
        return f"Governed case {index}"
    return f"{label} signal"


def _anonymous_public_finding_payloads(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    report_preview_href = _finding_report_preview_href(public_safe=True)
    for index, row in enumerate(rows, start=1):
        payloads.append(
            {
                "title": _anonymous_public_case_title(row, index=index),
                "pattern_label": row.get("pattern_label") or "Governed signal",
                "classification": row.get("classification"),
                "confidence": row.get("confidence"),
                "recoverable_sar": row.get("recoverable_sar"),
                "citation_count": row.get("citation_count"),
                "challenged": bool(row.get("challenged")),
                "status": row.get("status"),
                "case_href": None,
                "evidence_preview_href": None,
                "report_preview_href": report_preview_href,
                "contracts": {
                    "case": {"href": None},
                    "evidence": {"preview_href": None, "evidence_qa_href": None},
                    "report": {"preview_href": report_preview_href},
                },
            }
        )
    return payloads


def _sanitize_anonymous_public_route(key: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    lowered = value.lower()
    if "/public/runs/latest/cases/" in lowered:
        return None
    if "/public/data/evidence-preview?" in lowered:
        return "/public/data/evidence-preview"
    if key in {"case_href", "case_detail", "sample_case_detail", "detail_route"}:
        return None
    return value


def _sanitize_anonymous_public_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key)
            if normalized_key in ANONYMOUS_PUBLIC_BANNED_KEYS or any(
                token in normalized_key
                for token in ("node_id", "finding_id", "case_id", "vendor_id", "vendor_name")
            ):
                continue
            if normalized_key in {
                "case_href",
                "evidence_preview_href",
                "preview_href",
                "case_detail",
                "sample_case_detail",
                "sample_evidence_preview",
                "evidence_preview",
                "detail_route",
                "route",
            }:
                item = _sanitize_anonymous_public_route(normalized_key, item)
            sanitized[normalized_key] = _sanitize_anonymous_public_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_anonymous_public_payload(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        if "/public/runs/latest/cases/" in lowered:
            return None
        if "/public/data/evidence-preview?" in lowered:
            return "/public/data/evidence-preview"
        if "invoice " in lowered or "inv-" in lowered:
            return "Governed signal"
    return value


def _summary_with_reconciled_metrics(
    summary: dict[str, Any] | None,
    *,
    view_state: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {"status": "missing"}
    rows = _finding_rows_from_summary(summary)
    audit_summary = _latest_run_audit_summary_payload(summary)
    metrics = _governed_metrics_payload(summary, rows, audit_summary)
    publication = _summary_publication_payload(summary, principal_role="operator")
    principal = {"role": "operator", "authenticated": True}
    board_portal = _board_portal_payload(
        summary,
        principal_role="operator",
        requested_state=(view_state or {}).get("board"),
    )
    strategy_substrate = _strategy_substrate_payload(summary, rows, audit_summary, principal)
    executive_modes = _executive_modes_payload(
        summary,
        principal,
        strategy_substrate=strategy_substrate,
        board_portal=board_portal,
        publication=publication,
        view_state=view_state,
    )
    drilldown = _drilldown_contract_payload(
        summary,
        principal,
        public_safe=False,
        finding_rows=rows,
        domain_filters=[],
        report_artifacts=list((_summary_report_contracts(summary).get("reports") or [])),
        board_portal=board_portal,
        executive_modes=executive_modes,
    )
    agent_modules = _agent_modules_payload(summary, rows, audit_summary, principal)
    agents = _agents_surface_payload(summary, principal)
    chat = _chat_threads_payload(
        summary,
        principal,
        executive_modes=executive_modes,
        board_portal=board_portal,
        publication=publication,
    )
    payload = dict(summary)
    payload["total_recoverable_sar"] = metrics["total_recoverable_sar"]
    payload["locked_findings"] = metrics["locked_findings"]
    payload["citation_count"] = metrics["citation_count"]
    payload["resolved_count"] = metrics["resolved_count"]
    payload["challenged_cases"] = metrics["challenged_count"]
    payload["report_count"] = metrics["report_count"]
    payload["plan_health"] = _bounded_plan_health_payload(summary, rows, audit_summary)
    payload["trend"] = _trend_card_payload(summary, rows, audit_summary)
    payload["strategy_substrate"] = strategy_substrate
    payload["publication"] = publication
    payload["board_portal"] = board_portal
    payload["executive_modes"] = executive_modes
    payload["drilldown"] = drilldown
    payload["interaction_contracts"] = _interaction_contracts_payload(principal, public_safe=False)
    payload["agents"] = agents
    payload["agent_modules"] = agent_modules
    payload["chat"] = chat
    payload["role_actions"] = _role_actions_payload(summary, rows, audit_summary, principal)
    payload["executive_diagnostics"] = _executive_diagnostics_payload(
        summary,
        principal=principal,
        board_portal=board_portal,
        executive_modes=executive_modes,
        drilldown=drilldown,
        strategy_substrate=strategy_substrate,
        agent_modules=agent_modules,
        audit_summary=audit_summary,
        finding_rows=rows,
    )
    return payload


def _finding_case_href(case_id: str, *, public_safe: bool) -> str:
    encoded = quote(str(case_id), safe="")
    return (
        f"/public/runs/latest/cases/{encoded}"
        if public_safe
        else f"/runs/latest/cases/{encoded}"
    )


def _finding_evidence_preview_href(
    case_id: str,
    *,
    run_id: str | None,
    public_safe: bool,
) -> str:
    query_parts = [f"finding_id={quote(str(case_id), safe='')}"]
    if run_id:
        query_parts.insert(0, f"run_id={quote(str(run_id), safe='')}")
    base = "/public/data/evidence-preview" if public_safe else "/data/evidence-preview"
    return f"{base}?{'&'.join(query_parts)}"


def _finding_report_preview_href(*, public_safe: bool) -> str:
    if public_safe:
        return "/public/runs/latest/report-preview"
    return "/public/runs/latest/report-preview"


def _finding_case_contract_payloads(
    rows: list[dict[str, Any]],
    *,
    run_id: str | None,
    public_safe: bool,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    contracts = build_case_summary_contracts(rows)
    for row, item in zip(rows, contracts):
        payload = dict(row)
        payload.update(artifact_contracts_payload(item))
        case_id = str(payload.get("case_id") or "")
        if case_id:
            payload["case_href"] = _finding_case_href(case_id, public_safe=public_safe)
            payload["evidence_preview_href"] = _finding_evidence_preview_href(
                case_id,
                run_id=run_id,
                public_safe=public_safe,
            )
        else:
            payload["case_href"] = None
            payload["evidence_preview_href"] = None
        payload["report_preview_href"] = _finding_report_preview_href(
            public_safe=public_safe
        )
        payload["contracts"] = {
            "case": {"href": payload["case_href"]},
            "evidence": {
                "preview_href": payload["evidence_preview_href"],
                "evidence_qa_href": (
                    f"/runs/latest/findings?domain=evidence_qa#case={quote(case_id, safe='')}"
                    if case_id
                    else None
                ),
            },
            "report": {"preview_href": payload["report_preview_href"]},
        }
        payloads.append(payload)
    return payloads


def _latest_case_payload(
    summary: dict[str, Any] | None,
    case_id: str,
    *,
    public_safe: bool,
) -> dict[str, Any]:
    if public_safe:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Anonymous case detail is unavailable on the public surface.",
        )
    run_payload = _latest_run_findings_payload(
        summary,
        include_run_dir=not public_safe,
        public_safe=public_safe,
    )
    if run_payload.get("status") != "ok":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No latest governed run is available.",
        )
    for item in run_payload.get("findings", []) or []:
        if str(item.get("case_id") or item.get("finding_id") or "") == str(case_id):
            return {
                "status": "ok",
                "public_safe": public_safe,
                "run_id": run_payload.get("run_id"),
                "approval_status": run_payload.get("approval_status"),
                "requires_human_review": run_payload.get("requires_human_review"),
                "case": item,
            }
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Case '{case_id}' was not found on the latest run.",
    )


def _with_local_run_identity(summary: dict[str, Any]) -> dict[str, Any]:
    if summary.get("run_id") or not summary.get("run_dir"):
        return summary
    enriched = dict(summary)
    enriched["run_id"] = local_run_id_for_dir(Path(str(summary["run_dir"])))
    checkpoint = enriched.get("local_review_checkpoint")
    if isinstance(checkpoint, dict):
        checkpoint = dict(checkpoint)
        checkpoint["run_id"] = enriched["run_id"]
        enriched["local_review_checkpoint"] = checkpoint
    return enriched


def _latest_summary_path(summary: dict[str, Any]) -> Path | None:
    pointer = summary.get("latest_pointer")
    if isinstance(pointer, dict) and pointer.get("summary_path"):
        return Path(str(pointer["summary_path"])).expanduser().resolve()
    if summary.get("run_dir"):
        return Path(str(summary["run_dir"])).expanduser().resolve() / "run_summary.json"
    return None


def _local_review_checkpoint_for_run(run_id: str) -> dict[str, Any] | None:
    summary = _latest_summary()
    if not summary or str(summary.get("run_id") or "") != str(run_id):
        return None
    checkpoint = summary.get("local_review_checkpoint")
    if not isinstance(checkpoint, dict):
        if not summary.get("requires_human_review"):
            return None
        if str(summary.get("current_stage") or "").lower() != "awaiting_review":
            return None
        checkpoint = {
            "checkpoint_id": f"local-checkpoint:{run_id}:awaiting_review",
            "run_id": run_id,
            "stage": "awaiting_review",
            "status": "awaiting_review",
            "state_json": {
                "run_id": run_id,
                "dataset_root": summary.get("dataset") or summary.get("dataset_root"),
                "source_pack_id": summary.get("source_pack_id"),
                "run_dir": summary.get("run_dir"),
                "workflow_status": summary.get("status"),
                "current_stage": summary.get("current_stage"),
                "requires_human_review": summary.get("requires_human_review"),
                "approval_status": summary.get("approval_status") or "pending",
                "findings": [],
                "audit_events": [],
                "artifact_paths": summary.get("artifacts") or {},
            },
            "summary_json": summary,
            "persistence": "local_synthesized",
        }
    normalized = dict(checkpoint)
    normalized["run_id"] = run_id
    normalized.setdefault("checkpoint_id", f"local-checkpoint:{run_id}:awaiting_review")
    normalized.setdefault("stage", summary.get("current_stage") or "awaiting_review")
    normalized.setdefault("status", summary.get("status") or "awaiting_review")
    normalized.setdefault("state_json", {})
    normalized.setdefault("summary_json", summary)
    normalized["persistence"] = "local"
    return normalized


def _local_approval_status_for_run(run_id: str) -> dict[str, Any] | None:
    summary = _latest_summary()
    if not summary or str(summary.get("run_id") or "") != str(run_id):
        return None
    decision = summary.get("review_decision")
    return {
        "run_id": run_id,
        "run_status": summary.get("status"),
        "current_stage": summary.get("current_stage"),
        "requires_human_review": bool(summary.get("requires_human_review")),
        "approved_at": summary.get("approved_at"),
        "approved_by": summary.get("approved_by"),
        "review_assignment": _local_review_assignment(summary),
        "approval_status": str(summary.get("approval_status") or "pending"),
        "latest_approval": decision if isinstance(decision, dict) else None,
    }


def _local_review_assignment(summary: dict[str, Any]) -> dict[str, Any]:
    assignment = summary.get("review_assignment")
    if not isinstance(assignment, dict):
        assignment = {}
    claimed_by = assignment.get("claimed_by")
    claimed = bool(claimed_by)
    return {
        "claimed": claimed,
        "claimed_by": str(claimed_by) if claimed_by else None,
        "claimed_at": assignment.get("claimed_at"),
    }


def _latest_local_summary_for_run(run_id: str) -> dict[str, Any] | None:
    summary = _latest_summary()
    if not summary or str(summary.get("run_id") or "") != str(run_id):
        return None
    return summary


def _local_run_record_for_run_id(run_id: str) -> dict[str, Any] | None:
    summary = _latest_local_summary_for_run(run_id)
    if not summary:
        return None
    checkpoint = summary.get("local_review_checkpoint")
    return {
        "run_id": run_id,
        "status": summary.get("status"),
        "created_at": summary.get("created_at"),
        "current_stage": summary.get("current_stage"),
        "approval_status": summary.get("approval_status"),
        "review_assignment": _local_review_assignment(summary),
        "latest_checkpoint": checkpoint if isinstance(checkpoint, dict) else None,
        "summary_json": summary,
    }


def _local_checkpoint_record_for_id(checkpoint_id: str) -> dict[str, Any] | None:
    summary = _latest_summary()
    if not summary:
        return None
    checkpoint = summary.get("local_review_checkpoint")
    if not isinstance(checkpoint, dict):
        return None
    if str(checkpoint.get("checkpoint_id") or "") != str(checkpoint_id):
        return None
    return checkpoint


def _local_evidence_preview_for_run(
    run_id: str,
    *,
    citation_id: str | None = None,
    finding_id: str | None = None,
    source_hash: str | None = None,
    locator: str | None = None,
) -> dict[str, Any] | None:
    if citation_id:
        return None
    summary = _latest_local_summary_for_run(run_id)
    if not summary:
        return None
    artifacts = summary.get("artifacts") or {}
    citation_audit_path = artifacts.get("citation_audit")
    if not citation_audit_path:
        return None
    path = Path(str(citation_audit_path)).expanduser().resolve()
    if not path.exists() or not path.is_file():
        return None
    try:
        citation_audit = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    finding_lookup: dict[str, dict[str, Any]] = {}
    checkpoint = summary.get("local_review_checkpoint") or {}
    state_json = checkpoint.get("state_json") or {}
    for item in state_json.get("findings", []) or []:
        if isinstance(item, dict) and item.get("finding_id"):
            finding_lookup[str(item["finding_id"])] = item
    for record in citation_audit.get("records", []) or []:
        if not isinstance(record, dict):
            continue
        if finding_id and str(record.get("finding_id") or "") != str(finding_id):
            continue
        if source_hash and str(record.get("source_hash") or "") != str(source_hash):
            continue
        if locator and str(record.get("locator") or "") != str(locator):
            continue
        finding = finding_lookup.get(str(record.get("finding_id") or ""), {})
        excerpt = str(record.get("excerpt") or "")
        resolved_payload = record.get("resolved_payload") or {}
        preview_kind = "text" if excerpt else "json" if resolved_payload else "metadata"
        return {
            "status": "ok",
            "run_id": run_id,
            "finding_id": record.get("finding_id"),
            "citation_id": None,
            "evidence_document_id": None,
            "title": finding.get("title"),
            "pattern_type": record.get("pattern_type") or finding.get("pattern_type"),
            "vendor_id": finding.get("vendor_id"),
            "vendor_name": finding.get("vendor_name"),
            "confidence": finding.get("confidence"),
            "source_path": record.get("source_path"),
            "source_hash": record.get("source_hash"),
            "locator": record.get("locator"),
            "resolved": record.get("resolved"),
            "hash_match": record.get("hash_match"),
            "preview_kind": preview_kind,
            "excerpt": excerpt,
            "resolved_payload": resolved_payload,
        }
    return None


def _local_pending_review_items() -> list[dict[str, Any]]:
    summary = _latest_summary()
    if not summary:
        return []
    if not summary.get("requires_human_review"):
        return []
    if str(summary.get("status") or "").lower() != "awaiting_review":
        return []
    if str(summary.get("approval_status") or "pending").lower() in {"approved", "rejected"}:
        return []
    run_id = summary.get("run_id")
    if not run_id:
        return []
    checkpoint = _local_review_checkpoint_for_run(str(run_id))
    return [
        {
            "run_id": str(run_id),
            "run_dir": summary.get("run_dir"),
            "dataset_root": summary.get("dataset") or summary.get("dataset_root"),
            "status": summary.get("status"),
            "current_stage": summary.get("current_stage"),
            "requires_human_review": True,
            "checkpoint_id": checkpoint.get("checkpoint_id") if checkpoint else None,
            "checkpoint_stage": "awaiting_review",
            "review_assignment": _local_review_assignment(summary),
            "approval_status": str(summary.get("approval_status") or "pending"),
            "source": "local_summary",
        }
    ]


def _write_local_review_summary(
    summary: dict[str, Any],
    summary_path: Path,
) -> dict[str, Any]:
    summary = annotate_governance_state(summary)
    summary["review_assignment"] = _local_review_assignment(summary)
    summary["pointer_metadata"] = update_run_pointers(summary, summary_path)
    summary["latest_pointer"] = summary["pointer_metadata"]["latest"]
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _mutate_local_review_assignment(
    *,
    run_id: str,
    reviewer_subject: str,
    claim: bool,
) -> dict[str, Any]:
    summary = _latest_summary()
    if not summary or str(summary.get("run_id") or "") != str(run_id):
        return {"status": "missing", "run_id": run_id}
    if str(summary.get("status") or "").lower() != "awaiting_review":
        return {
            "status": "conflict",
            "run_id": run_id,
            "reason": f"Run '{run_id}' is not available for {'claim' if claim else 'unclaim'}.",
            "review_assignment": _local_review_assignment(summary),
        }
    summary_path = _latest_summary_path(summary)
    if summary_path is None:
        return {"status": "missing", "run_id": run_id}

    assignment = _local_review_assignment(summary)
    claimed_by = assignment.get("claimed_by")
    if claim:
        if claimed_by and claimed_by != reviewer_subject:
            return {
                "status": "conflict",
                "run_id": run_id,
                "reason": f"Run '{run_id}' is already claimed by {claimed_by}.",
                "review_assignment": assignment,
            }
        if not claimed_by:
            assignment = {
                "claimed": True,
                "claimed_by": reviewer_subject,
                "claimed_at": datetime.now(UTC).isoformat(),
            }
    else:
        if not claimed_by:
            return {
                "status": "conflict",
                "run_id": run_id,
                "reason": f"Run '{run_id}' is not currently claimed.",
                "review_assignment": assignment,
            }
        if claimed_by != reviewer_subject:
            return {
                "status": "conflict",
                "run_id": run_id,
                "reason": f"Run '{run_id}' is claimed by {claimed_by}; only the current reviewer can unclaim it.",
                "review_assignment": assignment,
            }
        assignment = {"claimed": False, "claimed_by": None, "claimed_at": None}

    summary["review_assignment"] = assignment
    _write_local_review_summary(summary, summary_path)
    return {
        "run_id": run_id,
        "status": str(summary.get("status") or "awaiting_review"),
        "current_stage": summary.get("current_stage"),
        "requires_human_review": bool(summary.get("requires_human_review")),
        "review_assignment": assignment,
    }


def _record_local_reviewer_decision(
    *,
    run_id: str,
    decision: str,
    request: ReviewerDecisionRequest,
    principal: dict[str, Any],
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    summary = _latest_summary()
    if not summary or str(summary.get("run_id") or "") != str(run_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' was not found.",
        )
    if str(summary.get("status") or "").lower() != "awaiting_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run '{run_id}' is not awaiting review.",
        )
    approval_status = str(summary.get("approval_status") or "pending").lower()
    if approval_status in {"approved", "rejected"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run '{run_id}' already has reviewer decision '{approval_status}'.",
        )
    summary_path = _latest_summary_path(summary)
    if summary_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' summary file was not found.",
        )
    reviewer_subject = str(principal.get("subject") or "unknown")
    reviewer_role = str(principal.get("role") or "reviewer")
    assignment = _local_review_assignment(summary)
    claimed_by = assignment.get("claimed_by")
    if reviewer_role == "reviewer" and claimed_by != reviewer_subject:
        detail = (
            f"Run '{run_id}' must be claimed before a reviewer decision can be recorded."
            if claimed_by is None
            else f"Run '{run_id}' is claimed by {claimed_by}."
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    created_at = datetime.now(UTC).isoformat()
    payload = {
        "decision": decision,
        "comment": request.comment,
        "checkpoint": {
            "checkpoint_id": checkpoint.get("checkpoint_id"),
            "stage": checkpoint.get("stage"),
            "status": checkpoint.get("status"),
            "fingerprint": (checkpoint.get("state_json") or {}).get(
                "checkpoint_fingerprint"
            )
            or (checkpoint.get("summary_json") or {}).get("checkpoint_fingerprint"),
            "quantification": (checkpoint.get("state_json") or {}).get(
                "quantification"
            )
            or (checkpoint.get("summary_json") or {}).get("quantification")
            or {},
        },
        **(request.payload or {}),
    }
    result = {
        "approval_id": f"local-approval:{run_id}:{decision}",
        "run_id": run_id,
        "checkpoint_id": checkpoint.get("checkpoint_id"),
        "reviewer": reviewer_subject,
        "reviewer_subject": reviewer_subject,
        "reviewer_role": reviewer_role,
        "decision": decision,
        "comment": request.comment,
        "payload": payload,
        "created_at": created_at,
        "run_status": decision,
        "current_stage": summary.get("current_stage"),
        "persistence": "local",
    }
    summary["status"] = "awaiting_review"
    summary["current_stage"] = "awaiting_review"
    summary["approval_status"] = decision
    summary["review_assignment"] = {
        "claimed": False,
        "claimed_by": None,
        "claimed_at": None,
    }
    if decision == "approved":
        summary["approved_by"] = reviewer_subject
        summary["approved_at"] = created_at
    summary["review_decision"] = {
        "decision": decision,
        "comment": request.comment,
        "reviewer": reviewer_subject,
        "reviewer_subject": reviewer_subject,
        "created_at": created_at,
        "checkpoint_id": checkpoint.get("checkpoint_id"),
        "checkpoint_fingerprint": payload["checkpoint"].get("fingerprint"),
        "quantification": payload["checkpoint"].get("quantification") or {},
        "persistence": "local",
    }
    _write_local_review_summary(summary, summary_path)
    return result


def _sync_run_summary_review_state(
    *,
    checkpoint: dict[str, Any],
    decision_result: dict[str, Any],
) -> None:
    state_json = checkpoint.get("state_json") or {}
    run_dir_value = state_json.get("run_dir")
    if not run_dir_value:
        return
    summary_path = Path(str(run_dir_value)).expanduser().resolve() / "run_summary.json"
    if not summary_path.exists():
        return
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["status"] = "awaiting_review"
    summary["current_stage"] = "awaiting_review"
    summary["approval_status"] = str(
        decision_result.get("decision") or summary.get("approval_status") or "pending"
    )
    if summary["approval_status"] == "approved":
        summary["approved_by"] = decision_result.get("reviewer") or summary.get(
            "approved_by"
        )
        summary["approved_at"] = decision_result.get("created_at") or summary.get(
            "approved_at"
        )
    summary["review_decision"] = {
        "decision": decision_result.get("decision"),
        "comment": decision_result.get("comment"),
        "reviewer": decision_result.get("reviewer"),
        "reviewer_subject": decision_result.get("reviewer_subject"),
        "created_at": decision_result.get("created_at"),
        "checkpoint_id": checkpoint.get("checkpoint_id"),
        "checkpoint_fingerprint": ((decision_result.get("payload") or {}).get("checkpoint") or {}).get(
            "fingerprint"
        ),
        "quantification": ((decision_result.get("payload") or {}).get("checkpoint") or {}).get(
            "quantification"
        )
        or {},
    }
    summary = annotate_governance_state(summary)
    summary["pointer_metadata"] = update_run_pointers(summary, summary_path)
    summary["latest_pointer"] = summary["pointer_metadata"]["latest"]
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def _status_label(value: bool) -> str:
    return "Configured" if value else "Missing"


def _display_role(role: str) -> str:
    labels = {
        "bu": "BU leader",
        "operator": "Operator",
        "reviewer": "Reviewer",
        "analyst": "Analyst",
        "auditor": "Auditor",
        "executive": "Executive",
        "tenant_operator": "Tenant operator",
        "tenant_admin": "Tenant admin",
        "system": "System",
        "anonymous": "Anonymous",
        "public": "Public",
    }
    return labels.get(
        role.strip().lower(), role.replace("_", " ").strip().title() or "Unknown"
    )


def _display_subject(subject: str, role: str) -> str:
    raw = subject.strip()
    if not raw or raw == "anonymous":
        return "Anonymous"
    if raw == "auth-disabled":
        return "Auth disabled"
    if raw.startswith("demo-role:"):
        return _display_role(role)
    if raw.startswith("api-key:"):
        return f"{_display_role(role)} API key"
    if "://" in raw:
        raw = raw.rsplit(":", 1)[-1]
    if raw.endswith(".local"):
        raw = raw[: -len(".local")]
    return raw.replace("_", " ").replace(".", " ").strip().title() or _display_role(
        role
    )


def _display_name_for_principal(role: str, subject: str) -> str:
    normalized_role = role.strip().lower()
    if normalized_role in {
        "operator",
        "reviewer",
        "analyst",
        "auditor",
        "executive",
        "tenant_operator",
        "tenant_admin",
        "system",
    }:
        return _display_role(normalized_role)
    return _display_subject(subject, normalized_role)


def _role_altitude(role: str) -> str:
    normalized = role.strip().lower()
    if normalized in {"anonymous", "public"}:
        return "public"
    if principal_has_any_role(normalized, "system", "tenant_admin"):
        return "system"
    if principal_has_any_role(normalized, "tenant_operator", "operator"):
        return "operations"
    if principal_has_any_role(normalized, "bu", "reviewer"):
        return "review"
    if principal_has_any_role(normalized, "analyst", "auditor"):
        return "analysis"
    if principal_has_any_role(normalized, "executive"):
        return "executive"
    return "workspace"


def _principal_capabilities(role: str) -> dict[str, bool]:
    normalized = role.strip().lower()
    return {
        "can_view_overview": principal_has_any_role(normalized, *PRODUCT_READ_ROLES),
        "can_view_cases": principal_has_any_role(normalized, *PRODUCT_READ_ROLES),
        "can_investigate_evidence": principal_has_any_role(normalized, *INVESTIGATION_ROLES),
        "can_review": principal_has_any_role(normalized, *REVIEW_WORKFLOW_ROLES),
        "can_launch_runs": principal_has_any_role(
            normalized, "operator", "tenant_operator", "system"
        ),
        "can_manage_ingestion": principal_has_any_role(
            normalized, "operator", "tenant_operator", "tenant_admin", "system"
        ),
        "can_view_runtime": principal_has_any_role(normalized, *SYSTEM_READ_ROLES),
        "can_switch_company": principal_has_any_role(
            normalized, *PRODUCT_READ_ROLES, "tenant_admin", "system"
        ),
        "can_switch_portfolio": principal_has_any_role(
            normalized, *PRODUCT_READ_ROLES, "tenant_admin", "system"
        ),
        "can_view_evidence_qa": principal_has_any_role(
            normalized, "bu", "reviewer", "operator", "tenant_admin", "system"
        ),
    }


def _switcher_base_route(principal: dict[str, Any]) -> str:
    role = str(principal.get("role") or "anonymous")
    if _principal_prefers_public_safe_surface(principal) and principal_has_any_role(
        role, "executive"
    ):
        return "/executive"
    return _default_surface_route(principal)


def _company_switcher_payload(principal: dict[str, Any]) -> dict[str, Any]:
    route_base = _switcher_base_route(principal)
    options = build_switcher_contracts(
        options=CONFIG.company_options,
        active_id=CONFIG.company_slug,
        route_builder=lambda option_id: f"{route_base}{'&' if '?' in route_base else '?'}company={quote(option_id, safe='')}",
    )
    return {
        "active_company_id": CONFIG.company_slug,
        "active_company_name": CONFIG.company_name,
        "options": [artifact_contracts_payload(item) for item in options],
    }


def _portfolio_switcher_payload(principal: dict[str, Any]) -> dict[str, Any]:
    route_base = _switcher_base_route(principal)
    options = build_switcher_contracts(
        options=CONFIG.portfolio_options,
        active_id=CONFIG.portfolio_slug,
        route_builder=lambda option_id: f"{route_base}{'&' if '?' in route_base else '?'}portfolio={quote(option_id, safe='')}",
    )
    return {
        "active_portfolio_id": CONFIG.portfolio_slug,
        "active_portfolio_name": CONFIG.portfolio_name,
        "options": [artifact_contracts_payload(item) for item in options],
    }


def _filter_finding_rows(
    rows: list[dict[str, Any]], domain_filter: str | None
) -> list[dict[str, Any]]:
    normalized = str(domain_filter or "finance_integrity").strip().lower()
    if normalized in {"", "all", "finance", "finance_integrity"}:
        return rows
    if normalized == "cash_recovery":
        return [row for row in rows if float(row.get("recoverable_sar") or 0.0) > 0]
    if normalized == "evidence_qa":
        return [
            row
            for row in rows
            if bool(row.get("challenged")) or int(row.get("citation_count") or 0) > 0
        ]
    if normalized == "going_forward":
        return [
            row
            for row in rows
            if "going-forward" in str(row.get("classification") or "").lower()
            or "going forward" in str(row.get("classification") or "").lower()
        ]
    return rows


def _kpi_card_payloads(
    summary: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    audit_summary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    challenged_count = sum(1 for row in rows if row.get("challenged"))
    citation_count = sum(int(row.get("citation_count") or 0) for row in rows)
    resolved_count = int((audit_summary or {}).get("resolved_count") or 0)
    return [
        {
            "card_id": "recoverable_value",
            "label": "Recoverable value",
            "value": float(
                (summary or {}).get("total_recoverable_sar")
                or sum(float(row.get("recoverable_sar") or 0.0) for row in rows)
            ),
            "unit": "SAR",
            "trend_hint": "bounded_finance_snapshot",
        },
        {
            "card_id": "governed_cases",
            "label": "Governed cases",
            "value": len(rows),
            "unit": "count",
            "trend_hint": "case_worklist",
        },
        {
            "card_id": "citation_resolution",
            "label": "Citation resolution",
            "value": {"resolved": resolved_count, "total": citation_count},
            "unit": "count",
            "trend_hint": "evidence_chain",
        },
        {
            "card_id": "challenged_cases",
            "label": "Challenged cases",
            "value": challenged_count,
            "unit": "count",
            "trend_hint": "review_attention",
        },
    ]


def _trend_card_payload(
    summary: dict[str, Any] | None = None,
    rows: list[dict[str, Any]] | None = None,
    audit_summary: dict[str, Any] | None = None,
    *,
    limit: int = 6,
) -> dict[str, Any]:
    history = discover_run_history(limit=limit)
    points = [
        {
            "run_id": item.get("run_id"),
            "label": item.get("created_at") or item.get("run_id"),
            "recoverable_sar": item.get("total_recoverable_sar") or 0,
            "locked_findings": item.get("locked_findings") or item.get("findings") or 0,
            "approval_status": item.get("approval_status"),
        }
        for item in history
    ]
    if summary:
        metrics = _governed_metrics_payload(summary, rows or [], audit_summary)
        current_point = {
            "run_id": summary.get("run_id"),
            "label": summary.get("created_at") or summary.get("run_id") or "latest",
            "recoverable_sar": metrics["total_recoverable_sar"],
            "locked_findings": metrics["locked_findings"],
            "approval_status": summary.get("approval_status"),
            "current_stage": summary.get("current_stage"),
            "source": "latest_summary",
        }
        if not points or str(points[-1].get("run_id") or "") != str(current_point.get("run_id") or ""):
            points.append(current_point)
        else:
            points[-1] = {**points[-1], **current_point}
    latest_point = points[-1] if points else None
    previous_point = points[-2] if len(points) > 1 else None
    recoverable_delta = None
    findings_delta = None
    if latest_point and previous_point:
        recoverable_delta = round(
            float(latest_point.get("recoverable_sar") or 0.0)
            - float(previous_point.get("recoverable_sar") or 0.0),
            2,
        )
        findings_delta = int(latest_point.get("locked_findings") or 0) - int(
            previous_point.get("locked_findings") or 0
        )
    return {
        "count": len(points),
        "points": points,
        "latest_point": latest_point,
        "previous_point": previous_point,
        "delta": {
            "recoverable_sar": recoverable_delta,
            "locked_findings": findings_delta,
        },
        "truth_basis": "reconciled_governed_metrics",
    }


def _governed_next_action(
    summary: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    audit_summary: dict[str, Any] | None,
) -> str:
    if not summary:
        return "run_first_governed_packet"
    metrics = _governed_metrics_payload(summary, rows, audit_summary)
    approval_status = str((summary or {}).get("approval_status") or "pending").lower()
    current_stage = _normalize_lifecycle_stage((summary or {}).get("current_stage"))
    if metrics["challenged_count"]:
        return "close_challenged_cases"
    if approval_status == "rejected":
        return "revise_evidence_and_rerun"
    if approval_status == "approved" and metrics["report_count"] > 1:
        return "prepare_board_pack"
    if current_stage == "awaiting_review" or approval_status in {"pending", "awaiting_review", ""}:
        return "capture_reviewer_decision"
    if metrics["report_count"]:
        return "expand_report_surface"
    return "protect_value_signal"


def _format_sar_brief(value: Any) -> str:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return "--"
    absolute = abs(number)
    if absolute >= 1_000_000:
        return f"SAR {number / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"SAR {round(number / 1_000):,.0f}K"
    return f"SAR {round(number):,}"


def _format_ratio_display(resolved: int | None, total: int | None) -> str:
    if total in (None, 0):
        return "--"
    return f"{int(resolved or 0)} / {int(total)}"


def _governed_metrics_payload(
    summary: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    audit_summary: dict[str, Any] | None,
    *,
    filtered_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    all_rows = list(rows or [])
    view_rows = list(filtered_rows) if filtered_rows is not None else list(all_rows)
    citation_count = sum(int(row.get("citation_count") or 0) for row in all_rows)
    filtered_citation_count = sum(int(row.get("citation_count") or 0) for row in view_rows)
    challenged_count = sum(1 for row in all_rows if row.get("challenged"))
    filtered_challenged_count = sum(1 for row in view_rows if row.get("challenged"))
    resolved_count = int((audit_summary or {}).get("resolved_count") or 0)
    total_recoverable = round(
        sum(float(row.get("recoverable_sar") or 0.0) for row in all_rows),
        2,
    )
    filtered_total_recoverable = round(
        sum(float(row.get("recoverable_sar") or 0.0) for row in view_rows),
        2,
    )
    report_contracts = _summary_report_contracts(summary)
    reports = list(report_contracts.get("reports") or [])
    evidence = list(report_contracts.get("evidence") or [])
    return {
        "total_recoverable_sar": total_recoverable
        if all_rows
        else (summary or {}).get("total_recoverable_sar"),
        "filtered_total_recoverable_sar": filtered_total_recoverable,
        "locked_findings": len(all_rows) if all_rows else (summary or {}).get("locked_findings"),
        "finding_count": len(all_rows),
        "filtered_finding_count": len(view_rows),
        "citation_count": citation_count,
        "filtered_citation_count": filtered_citation_count,
        "resolved_count": resolved_count,
        "challenged_count": challenged_count,
        "filtered_challenged_count": filtered_challenged_count,
        "report_count": len(reports),
        "evidence_count": len(evidence),
        "artifact_count": len((summary or {}).get("artifacts") or {})
        if isinstance(summary, dict)
        else 0,
    }


def _bounded_plan_health_payload(
    summary: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    audit_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    metrics = _governed_metrics_payload(summary, rows, audit_summary)
    challenged_count = metrics["challenged_count"]
    case_count = metrics["finding_count"]
    citation_count = metrics["citation_count"]
    resolved_count = metrics["resolved_count"]
    artifact_count = metrics["artifact_count"]
    approval_status = str((summary or {}).get("approval_status") or "pending").lower()
    if not summary:
        contract = PlanHealthContract(
            status="awaiting_run",
            badge="story mode",
            label="Awaiting governed run",
            summary="No governed finance packet has landed yet, so multi-domain posture stays at substrate level only.",
            boundary="Finance-derived signal only — StrategyOS is composing executive posture from current cases, evidence, release, and runtime boundary data, not a full enterprise strategy compiler.",
            root_label="Governed plan posture",
            root_summary="Finance, evidence, release, and runtime lanes are wired as a truthful substrate; live posture appears after the first governed run.",
            tone="neutral",
            child_ids=("finance", "evidence", "release", "runtime"),
            next_action="run_first_governed_packet",
            governance_status="substrate_only",
            evidence_basis=("workspace_contract", "runtime_boundary"),
        )
        return artifact_contracts_payload(contract)
    if challenged_count:
        status = "needs_reviewer_closure"
        badge = "human gate"
        label = "Needs reviewer closure"
        summary_text = f"{challenged_count} challenged case{'s' if challenged_count != 1 else ''} keep the broader plan readout bounded by evidence closure."
        tone = "warn"
    elif approval_status == "approved" and artifact_count:
        status = "release_posture_clear"
        badge = "release posture"
        label = "Release posture is clear"
        summary_text = "Finance signal, evidence posture, and board-output readiness are aligned enough for a bounded executive release view."
        tone = "ok"
    elif approval_status in {"pending", "awaiting_review", ""}:
        status = "review_gate_visible"
        badge = "bounded KPI layer"
        label = "Review gate visible"
        summary_text = "Value, evidence, and release signals exist, but the workflow is still waiting for human sign-off."
        tone = "neutral"
    else:
        status = "bounded_actionable"
        badge = "bounded KPI layer"
        label = "Finance signal is actionable"
        summary_text = "The current packet supports a truthful next-move readout without claiming portfolio-wide strategic compilation."
        tone = "ok"
    contract = PlanHealthContract(
        status=status,
        badge=badge,
        label=label,
        summary=summary_text,
        boundary="Finance-derived signal only — StrategyOS is composing executive posture from current cases, evidence, release, and runtime boundary data, not a full enterprise strategy compiler.",
        root_label="Governed plan posture",
        root_summary=f"{case_count} governed case{'s' if case_count != 1 else ''}, {_format_ratio_display(resolved_count, citation_count)} citations, and {artifact_count} surfaced artifact{'s' if artifact_count != 1 else ''} currently define the bounded executive plan readout.",
        tone=tone,
        child_ids=("finance", "evidence", "release", "runtime"),
        next_action=_governed_next_action(summary, rows, audit_summary),
        governance_status=approval_status or "pending",
        evidence_basis=(
            "summary.total_recoverable_sar",
            "finding_rows",
            "audit_summary",
            "report_contracts",
        ),
    )
    return artifact_contracts_payload(contract)


def _multi_domain_tree_payload(
    summary: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    audit_summary: dict[str, Any] | None,
    principal: dict[str, Any],
) -> dict[str, Any]:
    challenged_count = sum(1 for row in rows if row.get("challenged"))
    case_count = len(rows)
    citation_count = sum(int(row.get("citation_count") or 0) for row in rows)
    resolved_count = int((audit_summary or {}).get("resolved_count") or 0)
    report_contracts = _summary_report_contracts(summary)
    evidence_artifacts = len(list(report_contracts.get("evidence") or []))
    report_artifacts = len(list(report_contracts.get("reports") or []))
    approval_status = str((summary or {}).get("approval_status") or "pending")
    requires_human_review = bool((summary or {}).get("requires_human_review", CONFIG.require_human_review))
    public_safe = _principal_prefers_public_safe_surface(principal)
    findings_route = "/public/runs/latest/findings" if public_safe else "/runs/latest/findings"
    report_route = "/public/runs/latest/report-preview" if public_safe else "/reviewer/runs/{run_id}"
    nodes = [
        DomainNodeContract(
            domain_id="finance",
            label="Finance spine",
            portfolio_id="finance-diagnostics",
            status="Signal live" if summary else "Awaiting run",
            summary=(
                "Recoverable value and governed cases are the current anchor domain."
                if summary
                else "Value signal appears after the first governed finance run."
            ),
            route=findings_route,
            tone="ok" if summary else "neutral",
            metrics=[
                DomainMetricContract(
                    "recoverable_value",
                    "Recoverable value",
                    _format_sar_brief((summary or {}).get("total_recoverable_sar")),
                    "Bounded to the latest governed finance packet.",
                    "ok" if summary else "neutral",
                ),
                DomainMetricContract(
                    "governed_cases",
                    "Governed cases",
                    str(case_count) if summary else "--",
                    "Case count traced from the current governed run.",
                    "neutral",
                ),
            ],
            children=("finance_value", "finance_cases"),
        ),
        DomainNodeContract(
            domain_id="evidence",
            label="Evidence governance",
            portfolio_id="evidence-governance",
            status="Needs closure" if challenged_count else "Chain visible" if summary else "Awaiting run",
            summary=(
                f"{challenged_count} challenged case{'s' if challenged_count != 1 else ''} are still shaping release safety."
                if challenged_count
                else "Citation resolution and evidence packet posture are part of the executive view now."
                if summary
                else "Evidence posture becomes meaningful once a governed packet exists."
            ),
            route=f"{findings_route}?domain=evidence_qa",
            tone="warn" if challenged_count else "ok" if summary else "neutral",
            metrics=[
                DomainMetricContract(
                    "citation_resolution",
                    "Citation resolution",
                    _format_ratio_display(resolved_count, citation_count),
                    "Resolved versus surfaced citations in the active packet.",
                    "ok" if citation_count and resolved_count == citation_count else "warn" if summary else "neutral",
                ),
                DomainMetricContract(
                    "evidence_artifacts",
                    "Evidence artifacts",
                    str(evidence_artifacts) if summary else "--",
                    "Artifacts available for evidence QA and citation audit.",
                    "neutral",
                ),
            ],
            children=("evidence_citations", "evidence_artifacts"),
        ),
        DomainNodeContract(
            domain_id="release",
            label="Release posture",
            portfolio_id="release-readiness",
            status="Board-safe preview" if summary else "Awaiting run",
            summary=(
                "Approval state and surfaced report artifacts now shape a bounded board-output posture."
                if summary
                else "Report posture appears after the first governed packet lands."
            ),
            route=report_route,
            tone="ok" if approval_status.lower() == "approved" and report_artifacts else "neutral",
            metrics=[
                DomainMetricContract(
                    "approval_state",
                    "Approval state",
                    approval_status.replace("_", " ").title() if summary else "Pending",
                    "Human review remains the release gate." if requires_human_review else "Human gate is optional in this environment.",
                    "ok" if approval_status.lower() == "approved" else "warn" if summary else "neutral",
                ),
                DomainMetricContract(
                    "report_artifacts",
                    "Report artifacts",
                    str(report_artifacts) if summary else "--",
                    "Board-previewable outputs surfaced by the current run.",
                    "neutral",
                ),
            ],
            children=("release_approval", "release_artifacts"),
        ),
        DomainNodeContract(
            domain_id="runtime",
            label="Runtime boundary",
            portfolio_id="runtime-governance",
            status="Protected lane",
            summary="System health, connectors, graph, and vector stores remain in the tenant-admin / system lane so executive posture stays clean.",
            route="/app?lane=system",
            tone="neutral",
            metrics=[
                DomainMetricContract(
                    "runtime_backend",
                    "Run backend",
                    str(CONFIG.runtime_backend or "local"),
                    "Current configured execution backend.",
                    "neutral",
                ),
                DomainMetricContract(
                    "auth_mode",
                    "Auth boundary",
                    str(CONFIG.auth_mode or "disabled").replace("_", " "),
                    "Inspect live dependency and store detail through the protected system lane.",
                    "neutral",
                ),
            ],
            children=("runtime_backend", "runtime_auth"),
        ),
    ]
    plan_health = _bounded_plan_health_payload(summary, rows, audit_summary)
    return {
        "root": {
            "label": plan_health["root_label"],
            "summary": plan_health["root_summary"],
            "status": plan_health["label"],
            "tone": plan_health["tone"],
            "child_ids": list(plan_health["child_ids"]),
        },
        "nodes": [artifact_contracts_payload(item) for item in nodes],
    }


def _strategy_substrate_payload(
    summary: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    audit_summary: dict[str, Any] | None,
    principal: dict[str, Any],
) -> dict[str, Any]:
    boundary = (
        "Finance-derived signal only — StrategyOS is composing a bounded KPI tree, "
        "value-driver map, and strategy intent from governed cases, evidence posture, "
        "publication readiness, and runtime boundary truth; it is not claiming a full "
        "enterprise strategy compiler."
    )
    challenged_count = sum(1 for row in rows if row.get("challenged"))
    case_count = len(rows)
    citation_count = sum(int(row.get("citation_count") or 0) for row in rows)
    resolved_count = int((audit_summary or {}).get("resolved_count") or 0)
    report_contracts = _summary_report_contracts(summary)
    evidence_artifacts = len(list(report_contracts.get("evidence") or []))
    report_artifacts = len(list(report_contracts.get("reports") or []))
    total_recoverable = float((summary or {}).get("total_recoverable_sar") or 0.0)
    approval_status = str((summary or {}).get("approval_status") or "pending").lower()
    requires_human_review = bool(
        (summary or {}).get("requires_human_review", CONFIG.require_human_review)
    )
    public_safe = _principal_prefers_public_safe_surface(principal)
    findings_route = "/public/runs/latest/findings" if public_safe else "/runs/latest/findings"
    evidence_route = f"{findings_route}?domain=evidence_qa"
    review_route = "/reviewer/pending-reviews"
    report_route = "/public/runs/latest/report-preview" if public_safe else "/reviewer/runs/{run_id}"
    runtime_route = "/app?lane=system"
    working_capital_case_count = sum(
        1
        for row in rows
        if re.search(r"discount|credit|fx|price_variance", str(row.get("pattern_type") or ""), re.I)
    )
    vendor_control_case_count = sum(
        1
        for row in rows
        if re.search(r"vendor|contract|renewal|collusion", str(row.get("pattern_type") or ""), re.I)
    )

    if not summary:
        intent = StrategyIntentContract(
            intent_id="bounded-finance-intent",
            label="Convert governed finance signal into executive action",
            status="substrate_only",
            summary="The strategy layer is live only as a truthful substrate. It will not infer plan direction until a governed run lands with cases, evidence posture, and release state.",
            horizon="Current governed workspace only",
            next_decision="Run the first governed packet before treating any KPI branch or value-driver path as actionable.",
            boundary=boundary,
            evidence_basis=("workspace_contract", "runtime_boundary"),
            guardrails=(
                "Do not infer enterprise strategy from an empty governed workspace.",
                "Keep publication posture and runtime posture visible as gates, not outcomes.",
            ),
            focus_areas=(
                "finance-diagnostics",
                "evidence-governance",
                "release-readiness",
                "runtime-governance",
            ),
            confidence="substrate_only",
        )
        kpi_nodes = [
            StrategyKpiNodeContract(
                "value_capture",
                intent.intent_id,
                "Value capture",
                "awaiting_run",
                "--",
                "Recoverable value appears after the first governed run.",
                portfolio_id="finance-diagnostics",
                branch_type="portfolio",
                unit="SAR",
                child_ids=("cash_recovery_signal", "working_capital_signal"),
                driver_ids=("cash_recovery", "case_progression"),
                evidence_basis=("finding_rows.recoverable_sar",),
            ),
            StrategyKpiNodeContract(
                "cash_recovery_signal",
                "value_capture",
                "Cash recovery signal",
                "awaiting_run",
                "--",
                "No governed packet yet.",
                portfolio_id="finance-diagnostics",
                branch_type="leaf",
                unit="cases",
                evidence_basis=("finding_rows.recoverable_sar",),
            ),
            StrategyKpiNodeContract(
                "working_capital_signal",
                "value_capture",
                "Working-capital patterns",
                "awaiting_run",
                "--",
                "Working-capital pattern signal appears after the first governed run.",
                portfolio_id="finance-diagnostics",
                branch_type="leaf",
                unit="cases",
                evidence_basis=("finding_rows.pattern_type",),
            ),
            StrategyKpiNodeContract(
                "evidence_confidence",
                intent.intent_id,
                "Evidence confidence",
                "awaiting_run",
                "--",
                "Citation closure and challenge posture appear after the first governed run.",
                portfolio_id="evidence-governance",
                branch_type="portfolio",
                unit="ratio",
                child_ids=("citation_resolution", "challenge_backlog", "evidence_artifact_cover"),
                driver_ids=("evidence_closure", "challenge_resolution"),
                evidence_basis=("audit_summary",),
            ),
            StrategyKpiNodeContract(
                "citation_resolution",
                "evidence_confidence",
                "Citation resolution",
                "awaiting_run",
                "--",
                "Awaiting citation evidence.",
                portfolio_id="evidence-governance",
                branch_type="leaf",
                unit="ratio",
                evidence_basis=("audit_summary.resolved_count",),
            ),
            StrategyKpiNodeContract(
                "challenge_backlog",
                "evidence_confidence",
                "Challenge backlog",
                "awaiting_run",
                "--",
                "Awaiting challenged-case posture.",
                portfolio_id="evidence-governance",
                branch_type="leaf",
                unit="cases",
                evidence_basis=("finding_rows.challenged",),
            ),
            StrategyKpiNodeContract(
                "evidence_artifact_cover",
                "evidence_confidence",
                "Evidence artifact cover",
                "awaiting_run",
                "--",
                "Evidence artifacts appear after a governed packet lands.",
                portfolio_id="evidence-governance",
                branch_type="leaf",
                unit="artifacts",
                evidence_basis=("report_contracts.evidence",),
            ),
            StrategyKpiNodeContract(
                "release_readiness",
                intent.intent_id,
                "Release readiness",
                "awaiting_run",
                "--",
                "Approval state and surfaced report artifacts are not available yet.",
                portfolio_id="release-readiness",
                branch_type="portfolio",
                unit="status",
                child_ids=("board_pack_readiness", "publication_boundary"),
                driver_ids=("publication_handoff", "board_pack_readiness_driver"),
                evidence_basis=("report_contracts",),
            ),
            StrategyKpiNodeContract(
                "board_pack_readiness",
                "release_readiness",
                "Board-pack readiness",
                "awaiting_run",
                "--",
                "Awaiting governed report artifacts.",
                portfolio_id="release-readiness",
                branch_type="leaf",
                unit="artifacts",
                evidence_basis=("report_contracts.reports",),
            ),
            StrategyKpiNodeContract(
                "publication_boundary",
                "release_readiness",
                "Publication boundary",
                "awaiting_run",
                "--",
                "Publication remains governed even before the first packet lands.",
                portfolio_id="release-readiness",
                branch_type="leaf",
                unit="gate",
                evidence_basis=("summary.approval_status", "runtime_boundary"),
            ),
            StrategyKpiNodeContract(
                "runtime_boundary",
                intent.intent_id,
                "Runtime boundary",
                "protected",
                str(CONFIG.auth_mode or "disabled").replace("_", " "),
                "The operating boundary exists already and remains protected in the system lane.",
                portfolio_id="runtime-governance",
                branch_type="guardrail",
                unit="mode",
                child_ids=("system_truth_lane",),
                driver_ids=("runtime_governance",),
                evidence_basis=("runtime_boundary",),
            ),
            StrategyKpiNodeContract(
                "system_truth_lane",
                "runtime_boundary",
                "System truth lane",
                "protected",
                str(CONFIG.runtime_backend or "local"),
                "Protected runtime, graph, and vector truth stay in the admin/system lane.",
                portfolio_id="runtime-governance",
                branch_type="leaf",
                unit="backend",
                evidence_basis=("runtime_boundary",),
            ),
        ]
        value_drivers = [
            ValueDriverContract(
                "cash_recovery",
                "Cash recovery driver",
                "awaiting_run",
                "--",
                "Will map recoverable value from governed findings once a packet exists.",
                findings_route,
                maps_to=("value_capture", "cash_recovery_signal"),
                portfolio_id="finance-diagnostics",
                depends_on=("case_progression",),
                evidence_basis=("finding_rows.recoverable_sar",),
            ),
            ValueDriverContract(
                "case_progression",
                "Case progression driver",
                "awaiting_run",
                "--",
                "Will map governed case coverage and pattern concentration once a packet exists.",
                findings_route,
                maps_to=("cash_recovery_signal", "working_capital_signal"),
                portfolio_id="finance-diagnostics",
                evidence_basis=("finding_rows", "finding_rows.pattern_type"),
            ),
            ValueDriverContract(
                "evidence_closure",
                "Evidence closure driver",
                "awaiting_run",
                "--",
                "Will map citation resolution and challenge closure once evidence exists.",
                evidence_route,
                maps_to=("evidence_confidence", "citation_resolution", "challenge_backlog"),
                portfolio_id="evidence-governance",
                depends_on=("challenge_resolution",),
                evidence_basis=("audit_summary",),
            ),
            ValueDriverContract(
                "challenge_resolution",
                "Challenge resolution driver",
                "awaiting_run",
                "--",
                "Will map how many challenged cases still bound strategic confidence.",
                review_route,
                maps_to=("challenge_backlog",),
                portfolio_id="evidence-governance",
                evidence_basis=("finding_rows.challenged",),
            ),
            ValueDriverContract(
                "publication_handoff",
                "Publication handoff driver",
                "awaiting_run",
                "--",
                "Will map approval state and board-safe report surfaces after a governed run.",
                report_route,
                maps_to=("release_readiness", "publication_boundary"),
                portfolio_id="release-readiness",
                depends_on=("board_pack_readiness_driver",),
                evidence_basis=("report_contracts",),
            ),
            ValueDriverContract(
                "board_pack_readiness_driver",
                "Board-pack readiness driver",
                "awaiting_run",
                "--",
                "Will map surfaced report count without pretending autonomous publication exists.",
                report_route,
                maps_to=("board_pack_readiness",),
                portfolio_id="release-readiness",
                evidence_basis=("report_contracts.reports",),
            ),
            ValueDriverContract(
                "runtime_governance",
                "Runtime governance driver",
                "protected",
                str(CONFIG.runtime_backend or "local"),
                "Keeps the strategy layer bounded to what the hosted runtime and auth boundary can honestly support now.",
                runtime_route,
                maps_to=("runtime_boundary", "system_truth_lane"),
                portfolio_id="runtime-governance",
                influence="guards",
                evidence_basis=("runtime_boundary",),
            ),
        ]
        reasoning = [
            StrategyReasoningContract(
                reasoning_id="substrate-hold",
                claim="Hold the strategy layer at substrate level until governed evidence exists.",
                status="bounded",
                rationale="No governed run summary is available, so StrategyOS can only expose the operating frame and not a fabricated strategic conclusion.",
                evidence_basis=("workspace_contract", "runtime_boundary"),
                affected_node_ids=("runtime_boundary", "value_capture", "evidence_confidence", "release_readiness"),
                affected_driver_ids=("runtime_governance",),
                recommended_route=runtime_route,
                guardrail="Do not narrate portfolio or enterprise strategy until governed cases, evidence posture, and release posture are present together.",
            )
        ]
        portfolio_views = [
            {
                "portfolio_id": "finance-diagnostics",
                "label": "Finance diagnostics",
                "status": "awaiting_run",
                "summary": "Finance value and working-capital strategy remain dormant until the first governed packet lands.",
                "metric": "--",
                "node_ids": ["value_capture", "cash_recovery_signal", "working_capital_signal"],
                "driver_ids": ["cash_recovery", "case_progression"],
                "reasoning_ids": ["substrate-hold"],
                "route": findings_route,
            },
            {
                "portfolio_id": "evidence-governance",
                "label": "Evidence governance",
                "status": "awaiting_run",
                "summary": "Evidence strategy remains dormant until citation and challenge posture exist.",
                "metric": "--",
                "node_ids": ["evidence_confidence", "citation_resolution", "challenge_backlog", "evidence_artifact_cover"],
                "driver_ids": ["evidence_closure", "challenge_resolution"],
                "reasoning_ids": ["substrate-hold"],
                "route": evidence_route,
            },
            {
                "portfolio_id": "release-readiness",
                "label": "Release readiness",
                "status": "awaiting_run",
                "summary": "Publication strategy remains dormant until approval state and surfaced reports exist.",
                "metric": "--",
                "node_ids": ["release_readiness", "board_pack_readiness", "publication_boundary"],
                "driver_ids": ["publication_handoff", "board_pack_readiness_driver"],
                "reasoning_ids": ["substrate-hold"],
                "route": report_route,
            },
            {
                "portfolio_id": "runtime-governance",
                "label": "Runtime governance",
                "status": "protected",
                "summary": "Runtime governance is the standing guardrail even before the first governed run arrives.",
                "metric": str(CONFIG.runtime_backend or "local"),
                "node_ids": ["runtime_boundary", "system_truth_lane"],
                "driver_ids": ["runtime_governance"],
                "reasoning_ids": ["substrate-hold"],
                "route": runtime_route,
            },
        ]
        return {
            "status": "awaiting_run",
            "boundary": boundary,
            "intent": artifact_contracts_payload(intent),
            "kpi_tree": {
                "root": {
                    "node_id": intent.intent_id,
                    "label": intent.label,
                    "status": intent.status,
                    "summary": intent.summary,
                    "horizon": intent.horizon,
                    "child_ids": [
                        "value_capture",
                        "evidence_confidence",
                        "release_readiness",
                        "runtime_boundary",
                    ],
                },
                "nodes": [artifact_contracts_payload(item) for item in kpi_nodes],
            },
            "value_drivers": [artifact_contracts_payload(item) for item in value_drivers],
            "reasoning": [artifact_contracts_payload(item) for item in reasoning],
            "portfolio_views": portfolio_views,
            "tree_depth": 3,
            "node_count": len(kpi_nodes),
            "driver_count": len(value_drivers),
        }

    value_status = "live" if total_recoverable > 0 else "thin"
    evidence_status = (
        "needs_closure"
        if challenged_count or (citation_count and resolved_count < citation_count)
        else "governed"
    )
    release_status = "clear" if approval_status == "approved" and report_artifacts else "gated"
    runtime_status = "protected"
    next_decision = (
        f"Resolve {challenged_count} challenged case{'s' if challenged_count != 1 else ''} before widening the executive narrative."
        if challenged_count
        else "Keep the board surface in preview mode until reviewer approval is recorded."
        if requires_human_review and approval_status != "approved"
        else "Use the bounded board-safe preview to frame value capture while keeping protected artifacts in governed lanes."
    )
    intent = StrategyIntentContract(
        intent_id="bounded-finance-intent",
        label="Convert governed finance signal into executive action",
        status="bounded_actionable" if total_recoverable > 0 else "bounded_visible",
        summary=(
            f"The latest governed packet exposes {_format_sar_brief(total_recoverable)} across {case_count} governed case{'s' if case_count != 1 else ''}. "
            "StrategyOS can now support a bounded strategy readout: protect value, close evidence gaps, and respect the release gate."
        ),
        horizon="Latest governed run only",
        next_decision=next_decision,
        boundary=boundary,
        evidence_basis=(
            "summary.total_recoverable_sar",
            "finding_rows",
            "audit_summary",
            "report_contracts",
        ),
        guardrails=(
            "Keep strategy claims bounded to the latest governed packet.",
            "Treat approval and runtime truth as gates, not autonomous release authority.",
            "Do not imply enterprise strategy compilation beyond visible finance and publication portfolios.",
        ),
        focus_areas=(
            "finance-diagnostics",
            "evidence-governance",
            "release-readiness",
            "runtime-governance",
        ),
        confidence="backed" if total_recoverable > 0 and citation_count else "bounded",
    )
    kpi_nodes = [
        StrategyKpiNodeContract(
            "value_capture",
            intent.intent_id,
            "Value capture",
            value_status,
            _format_sar_brief(total_recoverable),
            f"{case_count} governed case{'s' if case_count != 1 else ''} currently carry the recoverable value signal.",
            "ok" if total_recoverable > 0 else "neutral",
            portfolio_id="finance-diagnostics",
            branch_type="portfolio",
            unit="SAR",
            child_ids=("cash_recovery_signal", "working_capital_signal"),
            driver_ids=("cash_recovery", "case_progression"),
            evidence_basis=("finding_rows.recoverable_sar",),
        ),
        StrategyKpiNodeContract(
            "cash_recovery_signal",
            "value_capture",
            "Cash recovery signal",
            value_status,
            str(case_count),
            "Tracks how many governed cases are currently feeding the value branch.",
            "ok" if case_count else "neutral",
            portfolio_id="finance-diagnostics",
            branch_type="leaf",
            unit="cases",
            evidence_basis=("finding_rows",),
        ),
        StrategyKpiNodeContract(
            "working_capital_signal",
            "value_capture",
            "Working-capital patterns",
            "live" if working_capital_case_count else "thin",
            str(working_capital_case_count),
            f"{working_capital_case_count} governed case{'s' if working_capital_case_count != 1 else ''} express discount, FX, credit, or pricing posture.",
            "ok" if working_capital_case_count else "neutral",
            portfolio_id="finance-diagnostics",
            branch_type="leaf",
            unit="cases",
            evidence_basis=("finding_rows.pattern_type",),
        ),
        StrategyKpiNodeContract(
            "evidence_confidence",
            intent.intent_id,
            "Evidence confidence",
            evidence_status,
            _format_ratio_display(resolved_count, citation_count),
            f"{challenged_count} challenged case{'s' if challenged_count != 1 else ''} and citation closure define how much strategic weight the packet can bear.",
            "warn" if evidence_status == "needs_closure" else "ok",
            portfolio_id="evidence-governance",
            branch_type="portfolio",
            unit="ratio",
            child_ids=("citation_resolution", "challenge_backlog", "evidence_artifact_cover"),
            driver_ids=("evidence_closure", "challenge_resolution"),
            evidence_basis=("audit_summary", "finding_rows.challenged"),
        ),
        StrategyKpiNodeContract(
            "citation_resolution",
            "evidence_confidence",
            "Citation resolution",
            "governed" if citation_count and resolved_count == citation_count else evidence_status,
            _format_ratio_display(resolved_count, citation_count),
            "Resolution of surfaced citations controls how far the strategy layer can reason.",
            "warn" if evidence_status == "needs_closure" else "ok",
            portfolio_id="evidence-governance",
            branch_type="leaf",
            unit="ratio",
            evidence_basis=("audit_summary.resolved_count",),
        ),
        StrategyKpiNodeContract(
            "challenge_backlog",
            "evidence_confidence",
            "Challenge backlog",
            "needs_closure" if challenged_count else "clear",
            str(challenged_count),
            "Challenged cases explicitly bound report and strategy confidence.",
            "warn" if challenged_count else "ok",
            portfolio_id="evidence-governance",
            branch_type="leaf",
            unit="cases",
            evidence_basis=("finding_rows.challenged",),
        ),
        StrategyKpiNodeContract(
            "evidence_artifact_cover",
            "evidence_confidence",
            "Evidence artifact cover",
            "governed" if evidence_artifacts else "thin",
            str(evidence_artifacts),
            "Evidence artifacts bound how defensible the evidence posture is externally.",
            "ok" if evidence_artifacts else "neutral",
            portfolio_id="evidence-governance",
            branch_type="leaf",
            unit="artifacts",
            evidence_basis=("report_contracts.evidence",),
        ),
        StrategyKpiNodeContract(
            "release_readiness",
            intent.intent_id,
            "Release readiness",
            release_status,
            f"{approval_status.replace('_', ' ').title()} · {report_artifacts} artifact{'s' if report_artifacts != 1 else ''}",
            "Publication remains governed by reviewer approval and surfaced report artifacts.",
            "ok" if release_status == "clear" else "warn",
            portfolio_id="release-readiness",
            branch_type="portfolio",
            unit="status",
            child_ids=("board_pack_readiness", "publication_boundary"),
            driver_ids=("publication_handoff", "board_pack_readiness_driver"),
            evidence_basis=("summary.approval_status", "report_contracts.reports"),
        ),
        StrategyKpiNodeContract(
            "board_pack_readiness",
            "release_readiness",
            "Board-pack readiness",
            "ready" if release_status == "clear" else "preview_only" if report_artifacts else "awaiting_run",
            f"{report_artifacts} surfaced",
            "Tracks whether the current packet can support a bounded board pack versus preview-only status.",
            "ok" if release_status == "clear" else "warn" if report_artifacts else "neutral",
            portfolio_id="release-readiness",
            branch_type="leaf",
            unit="artifacts",
            evidence_basis=("report_contracts.reports",),
        ),
        StrategyKpiNodeContract(
            "publication_boundary",
            "release_readiness",
            "Publication boundary",
            "protected" if requires_human_review else "bounded",
            "Human gate" if requires_human_review else "Optional gate",
            "Publication remains a governed handoff, never an autonomous executive release.",
            "neutral",
            portfolio_id="release-readiness",
            branch_type="leaf",
            unit="gate",
            evidence_basis=("summary.requires_human_review", "runtime_boundary"),
        ),
        StrategyKpiNodeContract(
            "runtime_boundary",
            intent.intent_id,
            "Runtime boundary",
            runtime_status,
            str(CONFIG.auth_mode or "disabled").replace("_", " "),
            "Execution, connectors, graph, and store truth remain protected outside the executive lane.",
            "neutral",
            portfolio_id="runtime-governance",
            branch_type="guardrail",
            unit="mode",
            child_ids=("system_truth_lane",),
            driver_ids=("runtime_governance",),
            evidence_basis=("runtime_boundary",),
        ),
        StrategyKpiNodeContract(
            "system_truth_lane",
            "runtime_boundary",
            "System truth lane",
            runtime_status,
            str(CONFIG.runtime_backend or "local"),
            "Tenant-admin/system workflows own deployment, store, and publication-boundary truth.",
            "neutral",
            portfolio_id="runtime-governance",
            branch_type="leaf",
            unit="backend",
            evidence_basis=("runtime_boundary",),
        ),
    ]
    value_drivers = [
        ValueDriverContract(
            "cash_recovery",
            "Cash recovery driver",
            "active" if total_recoverable > 0 else "thin",
            _format_sar_brief(total_recoverable),
            f"Mapped from {case_count} governed case{'s' if case_count != 1 else ''} in the current packet.",
            findings_route,
            "ok" if total_recoverable > 0 else "neutral",
            ("value_capture", "cash_recovery_signal"),
            "finance-diagnostics",
            "supports",
            ("case_progression",),
            ("finding_rows.recoverable_sar",),
        ),
        ValueDriverContract(
            "case_progression",
            "Case progression driver",
            "active" if case_count else "thin",
            str(case_count),
            f"Maps governed case coverage plus {vendor_control_case_count} vendor-control patterns into bounded execution attention.",
            findings_route,
            "ok" if case_count else "neutral",
            ("cash_recovery_signal", "working_capital_signal"),
            "finance-diagnostics",
            "supports",
            (),
            ("finding_rows", "finding_rows.pattern_type"),
        ),
        ValueDriverContract(
            "evidence_closure",
            "Evidence closure driver",
            "gated" if evidence_status == "needs_closure" else "active",
            _format_ratio_display(resolved_count, citation_count),
            f"Bounded by {challenged_count} challenged case{'s' if challenged_count != 1 else ''} and the current citation resolution ratio.",
            evidence_route,
            "warn" if evidence_status == "needs_closure" else "ok",
            ("evidence_confidence", "citation_resolution", "challenge_backlog"),
            "evidence-governance",
            "supports",
            ("challenge_resolution",),
            ("audit_summary", "finding_rows.challenged"),
        ),
        ValueDriverContract(
            "challenge_resolution",
            "Challenge resolution driver",
            "gated" if challenged_count else "active",
            str(challenged_count),
            "Maps challenged-case clearance into how assertive the executive narrative may become.",
            review_route,
            "warn" if challenged_count else "ok",
            ("challenge_backlog",),
            "evidence-governance",
            "constrains",
            (),
            ("finding_rows.challenged",),
        ),
        ValueDriverContract(
            "publication_handoff",
            "Publication handoff driver",
            "clear" if release_status == "clear" else "gated",
            f"{approval_status.replace('_', ' ').title()} · {report_artifacts} report artifact{'s' if report_artifacts != 1 else ''}",
            "Maps the governed review gate into executive publication posture.",
            review_route if release_status != "clear" else report_route,
            "ok" if release_status == "clear" else "warn",
            ("release_readiness", "publication_boundary"),
            "release-readiness",
            "supports",
            ("board_pack_readiness_driver",),
            ("summary.approval_status", "report_contracts.reports"),
        ),
        ValueDriverContract(
            "board_pack_readiness_driver",
            "Board-pack readiness driver",
            "clear" if report_artifacts else "thin",
            str(report_artifacts),
            "Maps surfaced report count into the bounded board-pack story.",
            report_route,
            "ok" if report_artifacts else "neutral",
            ("board_pack_readiness",),
            "release-readiness",
            "supports",
            (),
            ("report_contracts.reports",),
        ),
        ValueDriverContract(
            "runtime_governance",
            "Runtime governance driver",
            "protected",
            str(CONFIG.runtime_backend or "local"),
            "Keeps the strategy layer bounded to what the hosted runtime and auth boundary can honestly support now.",
            runtime_route,
            "neutral",
            ("runtime_boundary", "system_truth_lane"),
            "runtime-governance",
            "guards",
            (),
            ("runtime_boundary",),
        ),
    ]
    reasoning = [
        StrategyReasoningContract(
            reasoning_id="protect-value",
            claim="Protect the current value signal before broadening strategy claims.",
            status="backed" if total_recoverable > 0 else "thin",
            rationale=f"The latest governed run surfaces {_format_sar_brief(total_recoverable)} across {case_count} cases, so value capture is the only strategy branch with direct quantitative support right now.",
            evidence_basis=("summary.total_recoverable_sar", "finding_rows.recoverable_sar"),
            portfolio_id="finance-diagnostics",
            affected_node_ids=("value_capture", "cash_recovery_signal", "working_capital_signal"),
            affected_driver_ids=("cash_recovery", "case_progression"),
            recommended_route=findings_route,
            guardrail="Keep the executive claim tied to recoverable value already visible in governed cases.",
        ),
        StrategyReasoningContract(
            reasoning_id="close-evidence",
            claim="Keep evidence closure ahead of narrative expansion.",
            status="gated" if evidence_status == "needs_closure" else "backed",
            rationale=(
                f"Citation resolution is {_format_ratio_display(resolved_count, citation_count)} with {challenged_count} challenged case{'s' if challenged_count != 1 else ''}; that evidence posture bounds how assertive the executive layer may be."
            ),
            evidence_basis=("audit_summary.resolved_count", "finding_rows.citation_count", "finding_rows.challenged"),
            portfolio_id="evidence-governance",
            affected_node_ids=("evidence_confidence", "citation_resolution", "challenge_backlog", "evidence_artifact_cover"),
            affected_driver_ids=("evidence_closure", "challenge_resolution"),
            recommended_route=evidence_route,
            guardrail="Do not widen strategy narrative while challenged cases or unresolved citations still dominate the packet.",
        ),
        StrategyReasoningContract(
            reasoning_id="respect-release-gate",
            claim="Treat publication as governed intent, not autonomous release.",
            status="ready" if release_status == "clear" else "gated",
            rationale=(
                f"Approval is {approval_status.replace('_', ' ')} and {report_artifacts} report artifact{'s' if report_artifacts != 1 else ''} are surfaced, so the executive layer can describe release posture but not bypass reviewer or operator controls."
            ),
            evidence_basis=("summary.approval_status", "report_contracts.reports", "runtime_boundary"),
            portfolio_id="release-readiness",
            affected_node_ids=("release_readiness", "board_pack_readiness", "publication_boundary"),
            affected_driver_ids=("publication_handoff", "board_pack_readiness_driver"),
            recommended_route=report_route,
            guardrail="Publication can be narrated only as a handoff across reviewer and operator controls.",
        ),
        StrategyReasoningContract(
            reasoning_id="hold-runtime-boundary",
            claim="Use runtime governance as the hard boundary for every executive recommendation.",
            status="protected",
            rationale=(
                f"The current runtime backend is {CONFIG.runtime_backend or 'local'} with auth mode {str(CONFIG.auth_mode or 'disabled').replace('_', ' ')}, so executive posture must remain descriptive rather than operational."
            ),
            evidence_basis=("runtime_boundary",),
            portfolio_id="runtime-governance",
            affected_node_ids=("runtime_boundary", "system_truth_lane"),
            affected_driver_ids=("runtime_governance",),
            recommended_route=runtime_route,
            guardrail="Runtime truth constrains strategy expression; it never becomes an automation bypass.",
        ),
    ]
    portfolio_views = [
        {
            "portfolio_id": "finance-diagnostics",
            "label": "Finance diagnostics",
            "status": value_status,
            "summary": f"{_format_sar_brief(total_recoverable)} across {case_count} governed case{'s' if case_count != 1 else ''} defines the current bounded value branch.",
            "metric": _format_sar_brief(total_recoverable),
            "node_ids": ["value_capture", "cash_recovery_signal", "working_capital_signal"],
            "driver_ids": ["cash_recovery", "case_progression"],
            "reasoning_ids": ["protect-value"],
            "route": findings_route,
        },
        {
            "portfolio_id": "evidence-governance",
            "label": "Evidence governance",
            "status": evidence_status,
            "summary": f"Citation closure at {_format_ratio_display(resolved_count, citation_count)} with {challenged_count} challenged case{'s' if challenged_count != 1 else ''} bounds strategic confidence.",
            "metric": _format_ratio_display(resolved_count, citation_count),
            "node_ids": ["evidence_confidence", "citation_resolution", "challenge_backlog", "evidence_artifact_cover"],
            "driver_ids": ["evidence_closure", "challenge_resolution"],
            "reasoning_ids": ["close-evidence"],
            "route": evidence_route,
        },
        {
            "portfolio_id": "release-readiness",
            "label": "Release readiness",
            "status": release_status,
            "summary": f"Approval is {approval_status.replace('_', ' ')} with {report_artifacts} surfaced report artifact{'s' if report_artifacts != 1 else ''}; publication remains governed.",
            "metric": f"{approval_status.replace('_', ' ').title()} · {report_artifacts}",
            "node_ids": ["release_readiness", "board_pack_readiness", "publication_boundary"],
            "driver_ids": ["publication_handoff", "board_pack_readiness_driver"],
            "reasoning_ids": ["respect-release-gate"],
            "route": review_route if release_status != "clear" else report_route,
        },
        {
            "portfolio_id": "runtime-governance",
            "label": "Runtime governance",
            "status": runtime_status,
            "summary": f"Runtime backend {CONFIG.runtime_backend or 'local'} and auth mode {str(CONFIG.auth_mode or 'disabled').replace('_', ' ')} remain the non-negotiable operating boundary.",
            "metric": str(CONFIG.runtime_backend or "local"),
            "node_ids": ["runtime_boundary", "system_truth_lane"],
            "driver_ids": ["runtime_governance"],
            "reasoning_ids": ["hold-runtime-boundary"],
            "route": runtime_route,
        },
    ]
    return {
        "status": "ok",
        "boundary": boundary,
        "intent": artifact_contracts_payload(intent),
        "kpi_tree": {
            "root": {
                "node_id": intent.intent_id,
                "label": intent.label,
                "status": intent.status,
                "summary": intent.summary,
                "horizon": intent.horizon,
                "child_ids": [
                    "value_capture",
                    "evidence_confidence",
                    "release_readiness",
                    "runtime_boundary",
                ],
            },
            "nodes": [artifact_contracts_payload(item) for item in kpi_nodes],
        },
        "value_drivers": [artifact_contracts_payload(item) for item in value_drivers],
        "reasoning": [artifact_contracts_payload(item) for item in reasoning],
        "portfolio_views": portfolio_views,
        "tree_depth": 3,
        "node_count": len(kpi_nodes),
        "driver_count": len(value_drivers),
    }


def _role_lane_contracts(principal: dict[str, Any]) -> dict[str, Any]:
    role = str(principal.get("role") or "anonymous")
    return {
        "bu": {
            "primary_route": "/app?lane=review#bu",
            "domain_filters_route": "/runs/latest/findings?domain=finance_integrity",
            "evidence_qa_route": "/runs/latest/findings?domain=evidence_qa",
            "pending_reviews_route": "/bu/pending-reviews",
            "case_route_template": "/bu/runs/{run_id}",
            "active": principal_has_any_role(role, "bu"),
        },
        "reviewer": {
            "primary_route": "/app?lane=review#review",
            "pending_reviews_route": "/reviewer/pending-reviews",
            "evidence_qa_route": "/runs/latest/findings?domain=evidence_qa",
            "approve_route_template": "/reviewer/runs/{run_id}/approve",
            "reject_route_template": "/reviewer/runs/{run_id}/reject",
            "claim_route_template": "/reviewer/runs/{run_id}/claim",
            "active": principal_has_any_role(role, "reviewer"),
        },
        "operator": {
            "primary_route": "/app?lane=operate",
            "launch_route": "/runs",
            "resume_route_template": "/operator/runs/{run_id}/resume",
            "intake_routes": {
                "stage_upload": "/source-packs",
                "stage_path": "/source-packs/from-path",
                "validate": "/source-packs/validate",
                "confirm_mapping": "/source-packs/confirm-mapping",
                "connectors": "/ingestion/connectors",
            },
            "active": principal_has_any_role(role, "operator", "tenant_operator"),
        },
        "tenant_admin": {
            "primary_route": "/app?lane=system",
            "connectors_route": "/ingestion/connectors",
            "runtime_routes": {
                "data_status": "/data/status",
                "report_preview": "/runs/latest/report-preview",
                "review_queue": "/reviewer/pending-reviews",
                "bu_queue": "/bu/pending-reviews",
                "health_ready": "/health/ready",
                "health_config": "/health/config",
                "health_dependencies": "/health/dependencies",
                "run_jobs": "/runs/jobs/{job_id}",
            },
            "active": principal_has_any_role(role, "tenant_admin", "system"),
        },
    }


def _summary_tenant_context(
    summary: dict[str, Any] | None,
    principal: dict[str, Any],
) -> dict[str, str]:
    payload = summary.get("tenant_context") if isinstance(summary, dict) else None
    tenant_context = build_tenant_context(
        tenant_id=(payload or {}).get("tenant_id") if isinstance(payload, dict) else str(principal.get("tenant_id") or CONFIG.tenant_slug),
        tenant_name=(payload or {}).get("tenant_name") if isinstance(payload, dict) else None,
        workspace_id=(payload or {}).get("workspace_id") if isinstance(payload, dict) else None,
    )
    return artifact_contracts_payload(tenant_context)


def _summary_report_contracts(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {"tenant_id": CONFIG.tenant_slug, "run_id": None, "evidence": [], "reports": []}
    payload = summary.get("report_contracts")
    if isinstance(payload, dict):
        return payload
    artifacts = summary.get("artifacts") if isinstance(summary.get("artifacts"), dict) else {}
    tenant_payload = summary.get("tenant_context") if isinstance(summary.get("tenant_context"), dict) else {}
    return artifact_contracts_payload(
        build_run_report_contracts(
            dict(artifacts),
            tenant_id=str(tenant_payload.get("tenant_id") or CONFIG.tenant_slug),
            run_id=str(summary.get("run_id") or "") or None,
        )
    )


def _summary_publication_payload(
    summary: dict[str, Any] | None,
    *,
    principal_role: str | None = None,
    public_safe: bool = False,
) -> dict[str, Any]:
    role = str(principal_role or "anonymous")
    metrics = _governed_metrics_payload(
        summary,
        _finding_rows_from_summary(summary) if isinstance(summary, dict) else [],
        _latest_run_audit_summary_payload(summary) if isinstance(summary, dict) else None,
    )
    report_contracts = _summary_report_contracts(summary)
    reports = list(report_contracts.get("reports") or [])
    evidence = list(report_contracts.get("evidence") or [])
    can_open_paths = principal_has_any_role(role, "operator", "reviewer")
    can_open_restricted = principal_has_any_role(role, "operator", "reviewer")
    visible_reports = _sanitize_contract_list(
        reports,
        include_paths=can_open_paths,
        include_restricted=can_open_restricted,
    )
    restricted_reports = sum(1 for item in reports if item.get("restricted"))
    unrestricted_reports = len(reports) - restricted_reports
    approval_status = str((summary or {}).get("approval_status") or "pending").lower()
    current_stage = _normalize_lifecycle_stage((summary or {}).get("current_stage"))
    run_status = str((summary or {}).get("status") or "").lower()
    if run_status == "completed":
        release_status = "published"
    elif approval_status == "approved":
        release_status = "approved_for_release"
    elif approval_status == "rejected":
        release_status = "blocked"
    elif current_stage == "awaiting_review":
        release_status = "awaiting_review"
    else:
        release_status = "draft"
    if public_safe or principal_has_any_role(role, "executive"):
        allowed_actions = ("view_board_safe_preview",)
    elif principal_has_any_role(role, "bu"):
        allowed_actions = ("view_governed_report_status", "view_report_preview")
    elif principal_has_any_role(role, "reviewer"):
        allowed_actions = (
            "view_governed_report_status",
            "view_report_preview",
            "open_report_artifact",
            "approve_or_reject_release",
        )
    elif principal_has_any_role(role, "operator"):
        allowed_actions = (
            "view_governed_report_status",
            "view_report_preview",
            "open_report_artifact",
            "resume_publication",
        )
    elif principal_has_any_role(role, "tenant_admin", "system"):
        allowed_actions = (
            "inspect_publication_boundary",
            "inspect_artifact_posture",
            "inspect_runtime_release_state",
        )
    else:
        allowed_actions = ("view_report_preview",)
    board_pack_status = (
        "published"
        if release_status == "published"
        else "ready"
        if release_status == "approved_for_release" and len(reports) > 1
        else "preview_only"
        if bool(reports)
        else "pending"
    )
    board_pack_route = (
        "/public/runs/latest/report-preview"
        if public_safe or principal_has_any_role(role, "executive")
        else "/runs/latest/report-preview"
    )
    return {
        "run_id": (summary or {}).get("run_id"),
        "status": release_status,
        "publish_state": release_status,
        "approval_status": approval_status,
        "current_stage": current_stage,
        "requires_human_review": bool((summary or {}).get("requires_human_review")),
        "report_count": len(reports),
        "evidence_count": len(evidence),
        "restricted_report_count": restricted_reports,
        "unrestricted_report_count": unrestricted_reports,
        "challenged_cases": metrics["challenged_count"],
        "has_public_preview": True,
        "preview_route": "/public/runs/latest/report-preview"
        if public_safe or principal_has_any_role(role, "executive")
        else "/runs/latest/report-preview",
        "publish_ready": approval_status == "approved" and bool(reports),
        "available_artifacts": visible_reports,
        "allowed_actions": allowed_actions,
        "approval": {
            "status": approval_status,
            "required": bool((summary or {}).get("requires_human_review")),
            "current_stage": current_stage,
            "resumable": approval_status == "approved"
            and current_stage == "awaiting_review",
            "next_action": _governed_next_action(
                summary,
                _finding_rows_from_summary(summary) if isinstance(summary, dict) else [],
                _latest_run_audit_summary_payload(summary) if isinstance(summary, dict) else None,
            ),
        },
        "board_pack": {
            "status": board_pack_status,
            "safe_for_board": bool(reports)
            and release_status in {"approved_for_release", "published"},
            "preview_route": board_pack_route,
            "detail_route": board_pack_route,
            "report_count": len(reports),
            "evidence_count": len(evidence),
            "restricted_report_count": restricted_reports,
            "unrestricted_report_count": unrestricted_reports,
            "primary_artifact_key": visible_reports[0]["artifact_key"] if visible_reports else None,
            "allowed_actions": (
                "view_board_pack_preview",
                "inspect_board_pack_status",
            )
            if principal_has_any_role(role, "bu", "executive") or public_safe
            else (
                "view_board_pack_preview",
                "inspect_board_pack_status",
                "inspect_board_pack_artifacts",
            ),
        },
    }


def _publication_lifecycle_mode(publication: dict[str, Any] | None) -> str:
    payload = publication or {}
    status = str(payload.get("status") or payload.get("publish_state") or "draft").lower()
    approval_status = str(payload.get("approval_status") or "pending").lower()
    if status == "published":
        return "closed"
    if status == "approved_for_release" or approval_status == "approved":
        return "live"
    return "pre"


def _board_portal_payload(
    summary: dict[str, Any] | None,
    *,
    principal_role: str | None = None,
    public_safe: bool = False,
    requested_state: str | None = None,
) -> dict[str, Any]:
    role = str(principal_role or "anonymous")
    rows = _finding_rows_from_summary(summary) if isinstance(summary, dict) else []
    audit_summary = (
        _latest_run_audit_summary_payload(summary) if isinstance(summary, dict) else None
    )
    publication = _summary_publication_payload(
        summary,
        principal_role=role,
        public_safe=public_safe,
    )
    plan_health = _bounded_plan_health_payload(summary, rows, audit_summary)
    state = "pre"
    if publication.get("status") == "published":
        state = "closed"
    elif publication.get("status") == "approved_for_release" or publication.get(
        "approval_status"
    ) == "approved":
        state = "live"
    presentation_state = (
        str(requested_state or "").strip().lower() if requested_state else ""
    ) or state
    if presentation_state not in EXECUTIVE_BOARD_STATES:
        presentation_state = state
    board_pack = dict(publication.get("board_pack") or {})
    board_design = executive_board_design()
    state_labels = {
        "pre": ("Pre-board", "prepare"),
        "live": ("Live", "in session"),
        "closed": ("Closed", "collective memory"),
    }
    state_label, state_hint = state_labels.get(state, ("Pre-board", "prepare"))
    report_count = int(publication.get("report_count") or 0)
    challenged_count = int(publication.get("challenged_cases") or 0)
    next_action = str((publication.get("approval") or {}).get("next_action") or "")
    state_detail = {
        "pre": {
            "title": "Pre-board preparation",
            "summary": "Prepare the governed packet, tighten supplementary questions, and keep release posture bounded before the room opens.",
            "primary_actions": ["prepare_board_pack", next_action or "capture_reviewer_decision"],
            "secondary_actions": ["inspect_report_preview", "review_supplementary_questions"],
        },
        "live": {
            "title": "Live board session",
            "summary": "Operate only inside the approved packet while questions stay linked to challenged evidence and governed release posture.",
            "primary_actions": [next_action or "capture_reviewer_decision", "inspect_board_pack_status"],
            "secondary_actions": ["open_supplementary_rail", "freeze_live_answers"],
        },
        "closed": {
            "title": "Closed / frozen snapshot",
            "summary": "Keep the board memory frozen and bounded to approved outputs after the session closes.",
            "primary_actions": ["inspect_frozen_snapshot", "review_board_memory"],
            "secondary_actions": ["compare_packet_release", "check_follow_up_obligations"],
        },
    }.get(presentation_state, {})
    lifecycle_flow = []
    for state_id, label, detail in (
        ("pre", "Pre-board", "Prepare governed packet"),
        ("live", "Live", "Run the room inside approved material"),
        ("closed", "Closed", "Freeze memory after the room closes"),
    ):
        lifecycle_flow.append(
            {
                "state_id": state_id,
                "label": label,
                "detail": detail,
                "actual": state_id == state,
                "presented": state_id == presentation_state,
                "publish_state": publication.get("publish_state"),
                "next_action": next_action,
                "allowed_actions": list(board_pack.get("allowed_actions") or ()),
            }
        )
    return {
        "state": state,
        "actual_state": state,
        "requested_state": requested_state,
        "presentation_state": presentation_state,
        "state_label": state_label,
        "state_hint": state_hint,
        "publish_state": publication.get("publish_state"),
        "governance_note": "Nothing reaches the board surface until the governed approval lane clears it.",
        "meeting": {
            "mode": state_hint,
            "title": "Governed board packet",
            "tenant_label": _summary_tenant_context(summary, {"role": role}).get(
                "tenant_name"
            ),
            "run_id": (summary or {}).get("run_id"),
            "design_title": (board_design.get("meeting") or {}).get("title"),
            "when": (board_design.get("meeting") or {}).get("when"),
            "date": (board_design.get("meeting") or {}).get("date"),
            "room": (board_design.get("meeting") or {}).get("room"),
        },
        "deck_release": {
            "status": board_pack.get("status") or "pending",
            "report_count": report_count,
            "preview_route": board_pack.get("preview_route")
            or publication.get("preview_route"),
            "primary_artifact_key": board_pack.get("primary_artifact_key"),
            "allowed_actions": list(board_pack.get("allowed_actions") or ()),
        },
        "supplementary": {
            "status": "open" if state == "pre" else "governed" if state == "live" else "frozen",
            "question_count": challenged_count,
            "next_action": next_action,
            "route": "/reviewer/pending-reviews"
            if principal_has_any_role(role, "bu", "reviewer", "operator", "tenant_admin", "system")
            else publication.get("preview_route"),
            "summary": "Supplementary board questions stay bounded to challenged evidence and governed review posture.",
        },
        "frozen_snapshot": {
            "status": "frozen" if state == "closed" else "live_packet",
            "what_if_ready": state == "closed",
            "board_safe": bool(public_safe or principal_has_any_role(role, "executive")),
            "summary": "Closed meetings retain a bounded frozen snapshot; live organisation data stays outside the board lane.",
        },
        "session_chips": [
            state_label,
            str(publication.get("publish_state") or "draft").replace("_", " "),
            f"{challenged_count} challenged",
        ],
        "lifecycle_flow": lifecycle_flow,
        "state_detail": {
            "state": presentation_state,
            "title": state_detail.get("title") or "Board posture",
            "summary": state_detail.get("summary") or "Board posture is bounded to the governed packet.",
            "primary_actions": state_detail.get("primary_actions") or [],
            "secondary_actions": state_detail.get("secondary_actions") or [],
        },
        "plan_health": {
            "status": plan_health.get("status"),
            "label": plan_health.get("label"),
            "next_action": plan_health.get("next_action"),
        },
        "governance": board_design.get("governance"),
        "kpis": list(board_design.get("kpis") or []),
        "decks": list(board_design.get("decks") or []),
        "supplementary_questions": list(board_design.get("supplementary") or []),
        "live_prompts": list(board_design.get("livePrompts") or []),
        "actions": list(board_design.get("actions") or []),
        "board_summary": board_design.get("summary"),
    }


def _executive_modes_payload(
    summary: dict[str, Any] | None,
    principal: dict[str, Any],
    *,
    strategy_substrate: dict[str, Any],
    board_portal: dict[str, Any],
    publication: dict[str, Any],
    view_state: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    view_state = view_state or _requested_executive_view_state()
    company_id = str(view_state.get("company") or CONFIG.company_slug or "current")
    portfolio_id = str(view_state.get("portfolio") or CONFIG.portfolio_slug or "all")
    rows = _finding_rows_from_summary(summary) if isinstance(summary, dict) else []
    audit_summary = (
        _latest_run_audit_summary_payload(summary) if isinstance(summary, dict) else None
    )
    governed_metrics = _governed_metrics_payload(summary, rows, audit_summary)
    total_recoverable = float(governed_metrics.get("total_recoverable_sar") or 0.0)
    challenged_count = governed_metrics["challenged_count"]
    citation_count = int((audit_summary or {}).get("citation_count") or 0)
    resolved_count = int((audit_summary or {}).get("resolved_count") or 0)
    next_action = str(
        (publication.get("approval") or {}).get("next_action")
        or "capture_reviewer_decision"
    )

    def route_for(**params: str) -> str:
        query_params = {
            "company": company_id,
            "portfolio": portfolio_id,
            **{key: value for key, value in params.items() if value},
        }
        query_string = "&".join(
            f"{quote(key, safe='')}={quote(value, safe='')}"
            for key, value in query_params.items()
            if value
        )
        return f"/executive?{query_string}" if query_string else "/executive"

    personas = [
        {
            "persona_id": "ceo",
            "label": "Group CEO",
            "detail": "Khalid · value, release, board brief",
            "summary": "Frames plan-health, value capture, and board-safe release posture as bounded executive action.",
            "default_driver_key": "board_packet",
            "default_board_state": "pre",
            "assistant": "Hermes",
        },
        {
            "persona_id": "cfo",
            "label": "Group CFO",
            "detail": "Sara · margin, hedge, cash",
            "summary": "Focuses on cash pulse, hedge discipline, and release posture without overstating strategy authority.",
            "default_driver_key": "cash_pulse",
            "default_board_state": "pre",
            "assistant": "Atlas",
        },
        {
            "persona_id": "gm",
            "label": "BU GM",
            "detail": "Lina · growth, service, capacity",
            "summary": "Keeps the governed packet tied to BU growth, service quality, and capacity signal already present in the finance slice.",
            "default_driver_key": "cash_pulse",
            "default_board_state": "pre",
            "assistant": "Iris",
        },
        {
            "persona_id": "bucfo",
            "label": "BU CFO",
            "detail": "Yusuf · leakage, controls, exposure",
            "summary": "Frames governed leakage, controls, and exposure posture for the BU finance slice.",
            "default_driver_key": "owed_upward",
            "default_board_state": "pre",
            "assistant": "Argus",
        },
        {
            "persona_id": "logistics",
            "label": "Logistics",
            "detail": "Vega · cold chain, service, cost",
            "summary": "Keeps service-cost and operational dependency signal visible without turning the executive surface into an ops console.",
            "default_driver_key": "runtime_governance",
            "default_board_state": "closed",
            "assistant": "Vega",
        },
        {
            "persona_id": "board",
            "label": "Board room",
            "detail": "Approved pack and room posture",
            "summary": "Focuses on the governed board packet, supplementary questions, and frozen-snapshot discipline.",
            "default_driver_key": "board_packet",
            "default_board_state": "live",
            "assistant": "Hermes",
        },
    ]
    for item in personas:
        blueprint = executive_persona_design(str(item.get("persona_id") or "ceo"))
        item["assistant_role"] = blueprint.get("assistantRole")
        item["index_label"] = blueprint.get("indexLabel")
        item["quote"] = blueprint.get("quote")
        item["quoted_by"] = blueprint.get("by")
        item["prompt_count"] = len(list(blueprint.get("prompts") or []))
        item["thread_count"] = len(list(blueprint.get("threads") or []))
    requested_persona = str(view_state.get("persona") or "").strip().lower() or "ceo"
    if requested_persona not in {item["persona_id"] for item in personas}:
        requested_persona = "ceo"
    persona_lookup = {item["persona_id"]: item for item in personas}
    active_persona = persona_lookup[requested_persona]
    board_states = []
    for state_id, label, detail, summary_text in (
        (
            "pre",
            "Pre-board",
            "Prepare",
            "Prepare the governed packet and keep release posture explicitly bounded.",
        ),
        (
            "live",
            "Live",
            "In session",
            "Operate inside approved packet truth while supplementary questions stay governed.",
        ),
        (
            "closed",
            "Closed",
            "Memory",
            "Hold a frozen board-safe snapshot after the meeting closes.",
        ),
    ):
        board_states.append(
            {
                "state_id": state_id,
                "label": label,
                "detail": detail,
                "summary": summary_text,
                "route": route_for(board=state_id),
                "publish_state": publication.get("publish_state"),
                "allowed_actions": list(
                    (publication.get("board_pack") or {}).get("allowed_actions") or ()
                ),
                "active": state_id
                == str(
                    view_state.get("board")
                    or board_portal.get("presentation_state")
                    or board_portal.get("state")
                    or "pre"
                ),
            }
        )

    driver_focus = [
        {
            "driver_key": "board_packet",
            "label": "Board packet",
            "metric": f"{int(publication.get('report_count') or 0)} surfaced",
            "detail": "Board lifecycle parity is bounded to approved materials, publication posture, and the next explicit governed action.",
            "portfolio_id": "release-readiness",
            "status": str((publication.get("board_pack") or {}).get("status") or "pending"),
            "route": route_for(driver="board_packet"),
            "active": True,
            "persona_ids": ["ceo", "board"],
        },
            {
                "driver_key": "cash_pulse",
                "label": "Cash pulse",
                "metric": _format_sar_brief(total_recoverable),
                "detail": "Uses latest governed recoverable value as the bounded cash pulse signal for executive switching.",
                "portfolio_id": "finance-diagnostics",
                "status": "live" if total_recoverable > 0 else "thin",
                "route": route_for(driver="cash_pulse"),
                "active": False,
                "persona_ids": ["cfo", "gm"],
            },
        {
            "driver_key": "owed_upward",
            "label": "Owed upward",
            "metric": f"{challenged_count} challenged",
            "detail": "Tracks what still has to move upward through reviewer and board-safe publication discipline before the room can close.",
            "portfolio_id": "evidence-governance",
            "status": "needs_closure" if challenged_count else "clear",
            "route": route_for(driver="owed_upward"),
            "active": False,
            "persona_ids": ["bucfo", "board"],
        },
        {
            "driver_key": "evidence_closure",
            "label": "Evidence closure",
            "metric": _format_ratio_display(resolved_count, citation_count),
            "detail": "Keeps citation closure and challenge posture explicit so drill/gravity views stay bounded to what the packet can support.",
            "portfolio_id": "evidence-governance",
            "status": "needs_closure" if challenged_count else "governed",
            "route": route_for(driver="evidence_closure"),
            "active": False,
            "persona_ids": ["ceo", "cfo", "bucfo", "logistics", "board"],
        }
    ]
    for item in list(strategy_substrate.get("value_drivers") or [])[:4]:
        driver_key = str(item.get("driver_id") or item.get("driver_key") or "driver")
        driver_focus.append(
            {
                "driver_key": driver_key,
                "label": item.get("label") or "Value driver",
                "metric": item.get("metric") or "--",
                "detail": item.get("detail") or "Awaiting driver detail.",
                "portfolio_id": item.get("portfolio_id"),
                "status": item.get("status") or "bounded",
                "route": route_for(driver=driver_key),
                "active": False,
                "persona_ids": [],
            }
        )
    requested_driver = str(view_state.get("driver") or "").strip().lower()
    driver_keys = {str(item.get("driver_key") or "") for item in driver_focus}
    active_driver_key = requested_driver if requested_driver in driver_keys else str(active_persona.get("default_driver_key") or driver_focus[0]["driver_key"] if driver_focus else "board_packet")
    requested_board_state = str(view_state.get("board") or "").strip().lower()
    active_board_state = requested_board_state if requested_board_state in EXECUTIVE_BOARD_STATES else str(board_portal.get("presentation_state") or board_portal.get("state") or active_persona.get("default_board_state") or "pre")
    persona_contracts = [
        {
            **item,
            "route": route_for(
                persona=item["persona_id"],
                board=item["default_board_state"],
                driver=item["default_driver_key"],
            ),
            "active": item["persona_id"] == requested_persona,
        }
        for item in personas
    ]
    for item in driver_focus:
        item["active"] = str(item.get("driver_key") or "") == active_driver_key
    return {
        "route_base": route_for(),
        "company_id": company_id,
        "portfolio_id": portfolio_id,
        "active_persona_id": requested_persona,
        "active_board_state": active_board_state,
        "active_driver_key": active_driver_key,
        "personas": persona_contracts,
        "board_states": board_states,
        "driver_focus": driver_focus,
        "next_action": next_action,
        "state_contract": {
            "query_keys": {
                "persona": "persona",
                "board": "board",
                "driver": "driver",
                "company": "company",
                "portfolio": "portfolio",
                "week": "week",
                "agent": "agent",
            },
            "requested": dict(view_state),
            "truth_basis": "query_scoped_presentation_over_governed_packet",
        },
        "transition_contract": {
            "current": active_board_state,
            "allowed": ["pre", "live", "closed"],
            "sequence": ["pre", "live", "closed"],
            "frozen_snapshot_state": "closed",
        },
    }


def _drilldown_contract_payload(
    summary: dict[str, Any] | None,
    principal: dict[str, Any],
    *,
    public_safe: bool,
    finding_rows: list[dict[str, Any]],
    domain_filters: list[dict[str, Any]],
    report_artifacts: list[dict[str, Any]],
    board_portal: dict[str, Any] | None = None,
    executive_modes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    can_investigate = principal_has_any_role(
        str(principal.get("role") or "anonymous"), *INVESTIGATION_ROLES
    )
    audit_summary = (
        _latest_run_audit_summary_payload(summary) if isinstance(summary, dict) else None
    )
    publication = _summary_publication_payload(
        summary,
        principal_role=str(principal.get("role") or "anonymous"),
        public_safe=public_safe,
    )
    trend = _trend_card_payload(summary, finding_rows, audit_summary)
    run_id = str((summary or {}).get("run_id") or "")
    active_case_id = str((finding_rows[0] or {}).get("finding_id") or "") if finding_rows else ""
    challenged_count = sum(1 for item in finding_rows if item.get("challenged"))
    resolved_count = int((audit_summary or {}).get("resolved_count") or 0)
    citation_count = int((audit_summary or {}).get("citation_count") or 0)
    total_recoverable = round(
        sum(float(item.get("recoverable_sar") or 0.0) for item in finding_rows),
        2,
    )
    latest_point = trend.get("latest_point") or {}
    recoverable_delta = (trend.get("delta") or {}).get("recoverable_sar")
    locked_findings_delta = (trend.get("delta") or {}).get("locked_findings")
    case_route_template = (
        "/public/runs/latest/cases/{finding_id}"
        if public_safe
        else "/runs/latest/cases/{finding_id}"
    )
    evidence_route_template = (
        "/data/evidence-preview?run_id={run_id}&finding_id={finding_id}"
        if can_investigate
        else "/public/data/evidence-preview?run_id={run_id}&finding_id={finding_id}"
    )
    report_preview_route = "/public/runs/latest/report-preview"
    sample_case_route = (
        case_route_template.replace("{finding_id}", quote(active_case_id, safe=""))
        if active_case_id
        else case_route_template
    )
    sample_evidence_route = (
        evidence_route_template.replace("{run_id}", quote(run_id, safe="")).replace(
            "{finding_id}", quote(active_case_id, safe="")
        )
        if active_case_id
        else evidence_route_template
    )
    first_finding = finding_rows[0] if finding_rows else {}
    next_action = str(
        (publication.get("approval") or {}).get("next_action")
        or "capture_reviewer_decision"
    )
    persona_id = str((executive_modes or {}).get("active_persona_id") or "ceo")
    persona_blueprint = executive_persona_design(persona_id)
    board_design = executive_board_design()
    active_driver_key = str((executive_modes or {}).get("active_driver_key") or "")
    active_driver = next(
        (
            item
            for item in list(persona_blueprint.get("drivers") or [])
            if str(item.get("key") or "") == active_driver_key
        ),
        None,
    )
    gravity_assistant = str(
        (board_design.get("assistant") if persona_id == "board" else None)
        or persona_blueprint.get("assistant")
        or persona_id
    ).strip()
    gravity_prompts = (
        list(board_design.get("livePrompts") or [])
        if persona_id == "board"
        else list(persona_blueprint.get("prompts") or [])
    )
    return {
        "status": "ok" if summary else "missing",
        "run_id": run_id or None,
        "default_case_id": active_case_id or None,
        "case_count": len(finding_rows),
        "domain_filter_ids": [item.get("filter_id") for item in domain_filters],
        "report_keys": [item.get("artifact_key") for item in report_artifacts],
        "routes": {
            "case_detail": case_route_template,
            "sample_case_detail": sample_case_route,
            "evidence_preview": evidence_route_template,
            "sample_evidence_preview": sample_evidence_route,
            "report_preview": report_preview_route,
            "qa": "/qa",
        },
        "interactions": [
            {
                "action_id": "select_case",
                "method": "GET",
                "route": case_route_template,
                "audience": ("executive", "bu", "reviewer", "operator"),
            },
            {
                "action_id": "preview_evidence",
                "method": "GET",
                "route": evidence_route_template,
                "audience": ("executive", "bu", "reviewer", "operator"),
            },
            {
                "action_id": "preview_report",
                "method": "GET",
                "route": report_preview_route,
                "audience": ("executive", "bu", "reviewer", "operator"),
            },
            {
                "action_id": "ask_qa",
                "method": "POST",
                "route": "/qa",
                "audience": ("executive", "analyst", "reviewer", "operator"),
                "default_mode": "deterministic",
            },
        ],
        "cash_pulse": {
            "value_sar": total_recoverable,
            "value_display": _format_sar_brief(total_recoverable),
            "delta_sar": recoverable_delta,
            "basis": "governed_findings",
            "route": sample_case_route if active_case_id else report_preview_route,
        },
        "owed_upward": {
            "status": "needs_closure" if challenged_count else "clear",
            "challenge_count": challenged_count,
            "next_action": next_action,
            "route": "/reviewer/pending-reviews",
        },
        "movers": [
            {
                "mover_id": "cash_pulse",
                "label": "Cash pulse",
                "value": _format_sar_brief(total_recoverable),
                "delta": recoverable_delta,
                "direction": "up"
                if (recoverable_delta or 0) > 0
                else "down"
                if (recoverable_delta or 0) < 0
                else "flat",
                "detail": "Recoverable value visible in the current governed packet.",
            },
            {
                "mover_id": "owed_upward",
                "label": "Owed upward",
                "value": str(challenged_count),
                "delta": locked_findings_delta,
                "direction": "up" if challenged_count else "flat",
                "detail": "Open challenged items still constrain what can move upward into board-safe narrative.",
            },
            {
                "mover_id": "board_release",
                "label": "Board release",
                "value": str(publication.get("publish_state") or "draft"),
                "delta": None,
                "direction": "flat",
                "detail": "Publication posture remains governed by approval and board-pack readiness.",
            },
        ],
        "gravity": {
            "assistant": gravity_assistant,
            "quote": persona_blueprint.get("quote")
            or "Keep the room inside the packet; everything else is runtime truth.",
            "by": persona_blueprint.get("by") or "StrategyOS governance boundary",
            "rails": [
                str(publication.get("publish_state") or "draft"),
                _publication_lifecycle_mode(publication),
                f"{challenged_count} challenged",
            ],
            "prompts": gravity_prompts
            or [
                "What is still owed upward before this packet is board-safe?",
                "Which governed case most changes the board-room narrative?",
                "Show the cash pulse without leaving the approved packet.",
            ],
            "sandbox": {
                "persona_id": str((executive_modes or {}).get("active_persona_id") or "ceo"),
                "board_state": str((board_portal or {}).get("presentation_state") or (board_portal or {}).get("state") or _publication_lifecycle_mode(publication)),
                "active_driver_key": str((executive_modes or {}).get("active_driver_key") or "board_packet"),
                "truth_basis": "governed_packet_only",
            },
        },
        "lower_rail": {
            "developments": [
                {
                    "development_id": f"design-{index}",
                    "title": item.get("title") or "Development",
                    "detail": f"{item.get('meta') or ''} · {item.get('impact') or ''}".strip(" ·")
                    or item.get("detail")
                    or "Awaiting development detail.",
                    "chips": [str(item.get("kind") or "update"), str(persona_blueprint.get("assistant") or persona_id)],
                }
                for index, item in enumerate(list(persona_blueprint.get("developments") or [])[:3], start=1)
            ]
            or [
                {
                    "development_id": "packet-focus",
                    "title": "Packet focus",
                    "detail": first_finding.get("title") or "No governed case is in focus yet.",
                    "chips": [f"{len(finding_rows)} case(s)", f"{challenged_count} challenged"],
                }
            ],
            "week_ahead": [
                {
                    "event_id": "prep" if index == 1 else item.get("key") or f"week-{index}",
                    "design_event_id": item.get("key") or f"week-{index}",
                    "label": item.get("title") or "Executive event",
                    "detail": item.get("when") or next_action,
                    "prompt": item.get("prompt") or item.get("title") or next_action,
                    "foot": item.get("prep") or next_action,
                    "urgent": bool(item.get("urgent")),
                }
                for index, item in enumerate(list(persona_blueprint.get("week") or [])[:4], start=1)
            ]
            or [
                {"event_id": "prep", "label": "Board prep", "detail": next_action},
                {"event_id": "closure", "label": "Evidence closure", "detail": _format_ratio_display(resolved_count, citation_count)},
                {"event_id": "room", "label": "Room narrative", "detail": str(latest_point.get("approval_status") or publication.get("publish_state") or "draft")},
            ],
            "cash_pulse": {
                "title": (persona_blueprint.get("cashPulse") or {}).get("title") or "Cash pulse",
                "note": (persona_blueprint.get("cashPulse") or {}).get("note") or "governed finance signal",
                "pillars": list((persona_blueprint.get("cashPulse") or {}).get("pillars") or []),
                "value_display": _format_sar_brief(total_recoverable),
                "basis": "governed_findings",
                "route": sample_case_route if active_case_id else report_preview_route,
            },
            "owed_upward": {
                "title": (persona_blueprint.get("owedUpward") or {}).get("title") or "Owed upward",
                "note": (persona_blueprint.get("owedUpward") or {}).get("note") or "Governed upward commentary",
                "items": list((persona_blueprint.get("owedUpward") or {}).get("items") or [])
                or [
                    {
                        "to": action.get("owner") or "Board lane",
                        "on": action.get("item") or "Board follow-up",
                        "status": "authored" if str((board_portal or {}).get("presentation_state") or "") == "closed" else "pending",
                        "note": f"Due {action.get('due') or 'next board cycle'}.",
                    }
                    for action in list(board_design.get("actions") or [])[:3]
                ],
                "challenge_count": challenged_count,
                "next_action": next_action,
                "route": "/reviewer/pending-reviews",
            },
            "board_state": {
                "actual_state": str((board_portal or {}).get("state") or _publication_lifecycle_mode(publication)),
                "presentation_state": str((board_portal or {}).get("presentation_state") or (board_portal or {}).get("state") or _publication_lifecycle_mode(publication)),
                "publish_state": publication.get("publish_state"),
            },
        },
        "drill": {
            "active_driver": active_driver,
            "selected_driver_key": active_driver_key or None,
            "supports_gravity": True,
            "supports_lower_rail": True,
            "supports_movers": bool(active_driver and active_driver.get("movers")),
        },
    }


def _executive_diagnostics_payload(
    summary: dict[str, Any] | None,
    *,
    principal: dict[str, Any],
    board_portal: dict[str, Any],
    executive_modes: dict[str, Any],
    drilldown: dict[str, Any],
    strategy_substrate: dict[str, Any],
    agent_modules: dict[str, Any],
    audit_summary: dict[str, Any] | None,
    finding_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    plan_health = _bounded_plan_health_payload(summary, finding_rows, audit_summary)
    metrics = _governed_metrics_payload(summary, finding_rows, audit_summary)
    challenged_count = int(metrics.get("challenged_count") or 0)
    citation_count = int(metrics.get("citation_count") or 0)
    resolved_count = int(metrics.get("resolved_count") or 0)
    report_count = int(metrics.get("report_count") or 0)
    approval_status = str((summary or {}).get("approval_status") or "pending").lower()
    citation_ratio = (resolved_count / citation_count) if citation_count else 0.0
    approval_bonus = 16 if approval_status == "approved" else 9 if approval_status == "pending" else 4
    release_bonus = min(report_count * 6, 12)
    challenge_penalty = min(challenged_count * 7, 24)
    hero_score = max(38, min(96, round(58 + (citation_ratio * 18) + approval_bonus + release_bonus - challenge_penalty)))
    persona_id = str(executive_modes.get("active_persona_id") or "ceo")
    persona_label = next(
        (item.get("label") for item in executive_modes.get("personas") or [] if item.get("persona_id") == persona_id),
        "Group CEO",
    )
    active_driver_key = str(executive_modes.get("active_driver_key") or "board_packet")
    public_packet = executive_public_assistant_packet(persona_id)
    persona_blueprint = {
        "health": dict(public_packet.get("health") or {}),
        "assistant": public_packet.get("assistant"),
        "drivers": list(public_packet.get("drivers") or []),
        "findings": list(public_packet.get("findings") or []),
        "developments": list(public_packet.get("developments") or []),
        "week": list(public_packet.get("week") or []),
    }
    board_design = dict(public_packet.get("board_portal") or executive_board_design())
    driver_tiles = []
    persona_drivers = list(persona_blueprint.get("drivers") or [])
    for item in persona_drivers[:4] or list(executive_modes.get("driver_focus") or [])[:4]:
        driver_tiles.append(
            {
                "driver_key": item.get("key") or item.get("driver_key"),
                "label": item.get("label"),
                "metric": item.get("value") or item.get("metric"),
                "status": item.get("vsPlan") or item.get("status"),
                "detail": item.get("story") or item.get("detail"),
                "active": str(item.get("key") or item.get("driver_key") or "") == active_driver_key,
                "portfolio_id": item.get("portfolio_id"),
                "pct": item.get("pct"),
                "sub": item.get("sub"),
            }
        )
    return {
        "hero": {
            "persona_id": persona_id,
            "persona_label": persona_label,
            "score": hero_score,
            "status": plan_health.get("status"),
            "label": plan_health.get("label"),
            "summary": persona_blueprint.get("health", {}).get("headline")
            or plan_health.get("summary"),
            "body": persona_blueprint.get("health", {}).get("body"),
            "score_note": persona_blueprint.get("health", {}).get("scoreNote"),
            "quote": persona_blueprint.get("quote"),
            "quoted_by": persona_blueprint.get("by"),
            "active_driver_key": active_driver_key,
            "board_state": board_portal.get("presentation_state") or board_portal.get("state"),
        },
        "driver_grid": driver_tiles,
        "composition": {
            "cash_pulse": drilldown.get("cash_pulse"),
            "owed_upward": drilldown.get("owed_upward"),
            "gravity": drilldown.get("gravity"),
            "lower_rail": drilldown.get("lower_rail"),
            "board_portal": {
                "state": board_portal.get("state"),
                "presentation_state": board_portal.get("presentation_state"),
                "publish_state": board_portal.get("publish_state"),
                "state_detail": board_portal.get("state_detail"),
                "meeting": board_portal.get("meeting"),
                "governance": board_portal.get("governance") or board_design.get("governance"),
            },
        },
        "agents": {
            "running_count": (agent_modules.get("summary") or {}).get("running_count"),
            "discoverable_count": (agent_modules.get("summary") or {}).get("discoverable_count"),
            "approval_count": (agent_modules.get("summary") or {}).get("approval_count"),
        },
        "persona_blueprint": persona_blueprint,
        "board_packet": board_design,
        "drill": drilldown.get("drill") or {},
        "strategy": {
            "intent": (strategy_substrate.get("intent") or {}).get("label"),
            "driver_count": strategy_substrate.get("driver_count"),
            "node_count": strategy_substrate.get("node_count"),
        },
        "truth_basis": [
            "plan_health",
            "publication",
            "board_portal",
            "drilldown",
            "strategy_substrate",
            "agent_modules",
        ],
    }


def _interaction_contracts_payload(
    principal: dict[str, Any],
    *,
    public_safe: bool,
) -> dict[str, Any]:
    role = str(principal.get("role") or "anonymous")
    can_review = principal_has_any_role(role, *REVIEW_WORKFLOW_ROLES)
    can_read_review = principal_has_any_role(role, *REVIEW_READ_ROLES)
    return {
        "session": {"method": "GET", "route": "/ui/session"},
        "workspace_contract": {"method": "GET", "route": "/ui/workspace-contract/latest"},
        "latest_run": {
            "method": "GET",
            "route": "/public/runs/latest" if public_safe else "/runs/latest",
        },
        "latest_findings": {
            "method": "GET",
            "route": "/public/runs/latest/findings"
            if public_safe
            else "/runs/latest/findings",
        },
        "pending_reviews": {
            "method": "GET",
            "route": "/reviewer/pending-reviews"
            if can_review
            else "/bu/pending-reviews"
            if can_read_review
            else None,
        },
        "report_preview": {"method": "GET", "route": "/public/runs/latest/report-preview"},
        "qa": {"method": "POST", "route": "/qa", "default_mode": "deterministic"},
    }


def _chat_threads_payload(
    summary: dict[str, Any] | None,
    principal: dict[str, Any],
    *,
    executive_modes: dict[str, Any],
    board_portal: dict[str, Any],
    publication: dict[str, Any],
) -> dict[str, Any]:
    def _humanize_chat_token(value: str) -> str:
        text = str(value or "").replace("_", " ").replace("-", " ").strip()
        return " ".join(part.capitalize() for part in text.split()) if text else ""

    persona_id = str(executive_modes.get("active_persona_id") or "ceo")
    persona_label = next(
        (
            item.get("label")
            for item in executive_modes.get("personas") or []
            if item.get("persona_id") == persona_id
        ),
        "Group CEO",
    )
    persona_blueprint = executive_persona_design(persona_id)
    board_design = executive_board_design()
    assistant_name = str(
        (board_design.get("assistant") if persona_id == "board" else None)
        or persona_blueprint.get("assistant")
        or "StrategyOS"
    )
    assistant_role = str(
        persona_blueprint.get("assistantRole")
        or ("board guide" if persona_id == "board" else "assistant")
    )
    active_board_state = str(
        board_portal.get("presentation_state")
        or board_portal.get("state")
        or executive_modes.get("active_board_state")
        or "pre"
    )
    current_stage = _normalize_lifecycle_stage((summary or {}).get("current_stage"))
    challenged_count = int(publication.get("challenged_cases") or 0)
    run_id = str((summary or {}).get("run_id") or "latest")
    active_driver_key = str(executive_modes.get("active_driver_key") or "board_packet")
    starter_threads: list[dict[str, Any]] = []
    for index, item in enumerate(list(persona_blueprint.get("threads") or [])[:3], start=1):
        thread_key = str(item.get("key") or f"thread-{index}")
        starter_threads.append(
            {
                "thread_id": f"{persona_id}:{thread_key}",
                "kind": "starter_prompt",
                "persona_id": persona_id,
                "persona_label": persona_label,
                "assistant": assistant_name,
                "title": item.get("title") or _humanize_chat_token(thread_key),
                "preview": item.get("preview") or "Open this governed thread.",
                "starter_prompt": item.get("preview") or item.get("title") or "",
                "message_count": 0,
                "read_only": False,
                "route": _build_executive_route(
                    {
                        "persona": persona_id,
                        "board": active_board_state,
                        "driver": active_driver_key,
                        "company": executive_modes.get("company_id"),
                        "portfolio": executive_modes.get("portfolio_id"),
                    }
                ),
            }
        )
    workflow_preview = (
        f"Run {run_id} is {str((summary or {}).get('status') or 'governed').replace('_', ' ')}"
        f" at {current_stage.replace('_', ' ')}"
    )
    if challenged_count:
        workflow_preview += f" · {challenged_count} challenged item{'s' if challenged_count != 1 else ''}"
    threads = [
        {
            "thread_id": f"system:{run_id}",
            "kind": "system",
            "persona_id": persona_id,
            "persona_label": persona_label,
            "assistant": assistant_name,
            "title": "Governed run status",
            "preview": workflow_preview,
            "starter_prompt": None,
            "message_count": 1,
            "read_only": True,
            "route": publication.get("preview_route") or "/public/runs/latest/report-preview",
        },
        *starter_threads,
    ]
    board_pack_actions = list((publication.get("board_pack") or {}).get("allowed_actions") or [])
    return {
        "status": "ok" if summary else "awaiting_run",
        "run_id": (summary or {}).get("run_id"),
        "assistant": {
            "assistant_id": assistant_name.lower().replace(" ", "-"),
            "name": assistant_name,
            "role": assistant_role,
            "persona_id": persona_id,
            "persona_label": persona_label,
            "board_state": active_board_state,
        },
        "store": {
            "mode": "client_session",
            "storage_key_prefix": "strategyos.chat.",
            "scope": "run_id",
            "retention_limit": 60,
            "persistence": "sessionStorage",
            "server_memory": False,
        },
        "active_thread_id": threads[0]["thread_id"] if threads else None,
        "threads": threads,
        "starter_prompts": list(persona_blueprint.get("prompts") or [])[:3],
        "a2a": {
            "enabled": True,
            "mode": "derived_handoff_only",
            "items": [
                {
                    "handoff_id": f"action:{index}",
                    "label": str(action_id).replace("_", " ").replace("-", " ").strip().title(),
                    "status": publication.get("approval_status") or "pending",
                    "route": publication.get("preview_route") or "/public/runs/latest/report-preview",
                }
                for index, action_id in enumerate(board_pack_actions, start=1)
            ],
        },
        "contracts": {
            "qa": {"method": "POST", "route": "/qa", "default_mode": "deterministic"},
            "latest_run": {
                "method": "GET",
                "route": "/public/runs/latest"
                if _principal_prefers_public_safe_surface(principal)
                else "/runs/latest",
            },
            "workspace_contract": {"method": "GET", "route": "/ui/workspace-contract/latest"},
            "report_preview": {
                "method": "GET",
                "route": publication.get("preview_route") or "/public/runs/latest/report-preview",
            },
        },
        "notes": [
            "Frontend owns per-run thread history in sessionStorage.",
            "Server seeds assistant identity, starter threads, and governed workflow posture only.",
        ],
    }


def _agents_surface_payload(
    summary: dict[str, Any] | None,
    principal: dict[str, Any],
) -> dict[str, Any]:
    role = str(principal.get("role") or "anonymous")
    authenticated = bool(principal.get("authenticated"))
    rows = _finding_rows_from_summary(summary) if isinstance(summary, dict) else []
    audit_summary = (
        _latest_run_audit_summary_payload(summary) if isinstance(summary, dict) else None
    )
    publication = _summary_publication_payload(summary, principal_role=role)
    plan_health = _bounded_plan_health_payload(summary, rows, audit_summary)
    connectors = build_ingestion_connector_catalog(principal_role=role)
    challenged_count = int((publication or {}).get("challenged_cases") or 0)
    current_stage = _normalize_lifecycle_stage((summary or {}).get("current_stage"))
    approval_status = str((publication or {}).get("approval_status") or "pending").lower()
    release_status = str((publication or {}).get("status") or "draft").lower()
    run_id = str((summary or {}).get("run_id") or "latest")
    created_label = str((summary or {}).get("created_at") or "latest run")
    activity_design = executive_activity_design()
    running_design = executive_running_agents_design()
    discover_design = executive_discover_agents_design()
    subtools_design = executive_subtools_design()
    running = [
        {
            "id": item.get("id") or f"agent-{index}",
            "name": item.get("name") or "Agent",
            "status": item.get("status") or "queued",
            "tag": item.get("tag") or item.get("source") or "native",
            "doing": item.get("doing") or "Awaiting agent detail.",
            "by": item.get("by") or "StrategyOS",
            "progress": item.get("progress") or 0,
            "approval_required": str(item.get("status") or "").lower() == "approval",
            "route": "/reviewer/pending-reviews"
            if str(item.get("status") or "").lower() == "approval"
            else publication.get("preview_route") or "/runs/latest/report-preview",
            "log": list(item.get("log") or [{"t": created_label, "a": item.get("doing") or "Awaiting agent detail."}]),
        }
        for index, item in enumerate(running_design, start=1)
    ]
    native_discovery = [
        {
            "id": f"native-{item.get('id') or index}",
            "name": item.get("name") or "Native agent",
            "source": item.get("source") or "native",
            "glyph": item.get("glyph") or "◌",
            "by": item.get("by") or "StrategyOS",
            "desc": item.get("desc") or "Native agent surface",
            "connector": item.get("connector") or "/runs/latest/findings?domain=evidence_qa",
        }
        for index, item in enumerate(discover_design, start=1)
        if str(item.get("source") or "native").lower() == "native"
    ]
    market_discovery = [
        {
            "id": f"market-{item.get('id') or index}",
            "name": item.get("name") or "Marketplace agent",
            "source": item.get("source") or "market",
            "glyph": item.get("glyph") or "⚡",
            "by": item.get("by") or "Connector catalog",
            "desc": item.get("desc") or "Marketplace agent surface",
            "connector": item.get("connector") or "/ingestion/connectors",
            "permitted": True,
            "capabilities": [],
        }
        for index, item in enumerate(discover_design, start=1)
        if str(item.get("source") or "").lower() == "market"
    ] + [
        {
            "id": f"connector-{item.get('connector_id')}",
            "name": item.get("display_name") or "Connector",
            "source": "market",
            "glyph": "⚡",
            "by": "Connector catalog",
            "desc": "Deploys a governed data-ingestion route into the tenant runtime boundary.",
            "connector": item.get("connector_id") or "/ingestion/connectors",
            "permitted": bool(item.get("permitted")),
            "capabilities": list(item.get("capabilities") or ()),
        }
        for item in connectors
    ]
    return {
        "design_activity": activity_design,
        "status": "ok" if summary else "awaiting_run",
        "activity": {
            "line": activity_design.get("line") or plan_health.get("summary") or "No governed packet is available yet.",
            "metrics": [
                {"k": "running", "v": sum(1 for item in running if item["status"] in {"running", "approval"})},
                {"k": "needs approval", "v": sum(1 for item in running if item["status"] == "approval")},
                {"k": "discoverable", "v": len(native_discovery) + len(market_discovery)},
            ],
            "design_metrics": list(activity_design.get("metrics") or []),
            "log": list(activity_design.get("log") or [
                {"t": created_label, "who": "StrategyOS", "a": plan_health.get("next_action") or "continue_workflow"},
                {"t": run_id, "who": "Runtime", "a": f"Publish state {publication.get('publish_state') or 'draft'}"},
            ]),
        },
        "running": running,
        "discover": {
            "search_placeholder": "Search the agent universe…",
            "deploy_route": "/ingestion/connectors",
            "native": native_discovery,
            "marketplace": market_discovery,
        },
        "sub_agents": [
            {
                "name": item.get("name") or "Subtool",
                "glyph": item.get("glyph") or "⌁",
                "desc": item.get("desc") or "Subtool surface",
            }
            for item in subtools_design
        ],
        "sovereign_note": "Agents remain bounded to the tenant runtime; every action is surfaced through governed routes, not hidden automation.",
        "authenticated": authenticated,
    }


def _tenant_admin_system_payload(
    summary: dict[str, Any] | None,
    principal: dict[str, Any],
    *,
    data_status: dict[str, Any] | None = None,
    graph_status: dict[str, Any] | None = None,
    vector_status: dict[str, Any] | None = None,
    workflow_items: list[dict[str, Any]] | None = None,
    recent_runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    role = str(principal.get("role") or "anonymous")
    rows = _finding_rows_from_summary(summary) if isinstance(summary, dict) else []
    audit_summary = (
        _latest_run_audit_summary_payload(summary) if isinstance(summary, dict) else None
    )
    publication = _summary_publication_payload(summary, principal_role="tenant_admin")
    plan_health = _bounded_plan_health_payload(summary, rows, audit_summary)
    trend = _trend_card_payload(summary, rows, audit_summary)
    connectors = build_ingestion_connector_catalog(principal_role=role)
    permitted_connectors = [item for item in connectors if item.get("permitted")]
    workflow_items = workflow_items or []
    recent_runs = recent_runs or []
    runtime_routes = _role_lane_contracts({"role": "tenant_admin"}).get("tenant_admin", {}).get(
        "runtime_routes", {}
    )
    return {
        "tenant": _summary_tenant_context(summary, principal),
        "connector_posture": {
            "count": len(connectors),
            "permitted_count": len(permitted_connectors),
            "route": "/ingestion/connectors",
            "connectors": connectors,
        },
        "managed_data": {
            "status": (data_status or {}).get("status") or ("ok" if summary else "awaiting_run"),
            "run_id": (summary or {}).get("run_id"),
            "finding_count": len(rows),
            "graph_store": graph_status or {"status": "awaiting_run" if not summary else "summary_only"},
            "vector_store": vector_status or {"status": "awaiting_run" if not summary else "summary_only"},
            "reports": {
                "report_count": publication.get("report_count"),
                "evidence_count": publication.get("evidence_count"),
                "board_pack": publication.get("board_pack"),
            },
        },
        "workflow_posture": {
            "pending_reviews": len(workflow_items),
            "recent_runs": len(recent_runs),
            "current_stage": (summary or {}).get("current_stage"),
            "approval_status": publication.get("approval_status"),
            "next_action": plan_health.get("next_action"),
            "review_queue_route": runtime_routes.get("review_queue") or "/reviewer/pending-reviews",
            "bu_queue_route": runtime_routes.get("bu_queue") or "/bu/pending-reviews",
        },
        "publication_posture": publication,
        "trend": {
            "count": trend.get("count"),
            "latest_point": trend.get("latest_point"),
            "truth_basis": trend.get("truth_basis"),
        },
        "runtime_routes": runtime_routes,
    }


def _record_workflow_summary(record: dict[str, Any] | None) -> dict[str, Any]:
    payload = record or {}
    approval_status = str(
        payload.get("approval_status")
        or (payload.get("approval") or {}).get("approval_status")
        or (payload.get("summary_json") or {}).get("approval_status")
        or "pending"
    ).lower()
    current_stage = _normalize_lifecycle_stage(
        payload.get("current_stage")
        or (payload.get("latest_checkpoint") or {}).get("stage")
        or (payload.get("summary_json") or {}).get("current_stage")
    )
    run_status = str(
        payload.get("status")
        or payload.get("run_status")
        or (payload.get("summary_json") or {}).get("status")
        or "unknown"
    ).lower()
    assignment = payload.get("review_assignment") or {}
    claimed = bool(assignment.get("claimed"))
    if run_status == "completed":
        next_action = "inspect_published_outputs"
    elif approval_status == "approved" and current_stage == "awaiting_review":
        next_action = "operator_resume"
    elif approval_status == "rejected":
        next_action = "revise_evidence_or_rerun"
    elif current_stage == "awaiting_review" and claimed:
        next_action = "review_decision"
    elif current_stage == "awaiting_review":
        next_action = "claim_review"
    else:
        next_action = "continue_workflow"
    return {
        "run_status": run_status,
        "current_stage": current_stage,
        "approval_status": approval_status,
        "claimed": claimed,
        "claimed_by": assignment.get("claimed_by"),
        "requires_human_review": bool(
            payload.get("requires_human_review")
            if payload.get("requires_human_review") is not None
            else (payload.get("summary_json") or {}).get("requires_human_review")
        ),
        "resumable": approval_status == "approved" and current_stage == "awaiting_review",
        "next_action": next_action,
    }


def _agent_modules_payload(
    summary: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    audit_summary: dict[str, Any] | None,
    principal: dict[str, Any],
) -> dict[str, Any]:
    role = str(principal.get("role") or "anonymous")
    public_safe = _principal_prefers_public_safe_surface(principal)
    publication = _summary_publication_payload(
        summary,
        principal_role=role,
        public_safe=public_safe,
    )
    workflow = _record_workflow_summary(summary or {})
    challenged_count = sum(1 for row in rows if row.get("challenged"))
    citation_count = sum(int(row.get("citation_count") or 0) for row in rows)
    modules = [
        {
            "module_id": "cash-recovery-watch",
            "label": "Cash recovery watch",
            "status": "running" if rows else "idle",
            "lane": "executive",
            "summary": f"Tracks recoverable value across {len(rows)} governed case{'s' if len(rows) != 1 else ''}.",
            "route": "/public/runs/latest/findings" if public_safe else "/runs/latest/findings",
            "output_metric": _format_sar_brief(sum(float(row.get("recoverable_sar") or 0.0) for row in rows)),
            "approval_dependency": "none",
        },
        {
            "module_id": "evidence-closure-monitor",
            "label": "Evidence closure monitor",
            "status": "blocked" if challenged_count else "running" if citation_count else "idle",
            "lane": "review",
            "summary": f"Watches citation resolution ({_format_ratio_display(int((audit_summary or {}).get('resolved_count') or 0), citation_count)}) and {challenged_count} challenged case{'s' if challenged_count != 1 else ''}.",
            "route": "/runs/latest/findings?domain=evidence_qa",
            "output_metric": _format_ratio_display(int((audit_summary or {}).get("resolved_count") or 0), citation_count),
            "approval_dependency": "reviewer_release",
        },
        {
            "module_id": "board-pack-compiler",
            "label": "Board-pack compiler",
            "status": str((publication.get("board_pack") or {}).get("status") or "pending"),
            "lane": "executive",
            "summary": "Translates governed report posture into a board-safe packet without exposing restricted artifacts.",
            "route": publication.get("preview_route") or "/public/runs/latest/report-preview",
            "output_metric": f"{publication.get('report_count') or 0} report surfaces",
            "approval_dependency": str((publication.get("approval") or {}).get("next_action") or workflow.get("next_action") or "awaiting_action"),
        },
        {
            "module_id": "runtime-guardrail",
            "label": "Runtime guardrail",
            "status": "protected",
            "lane": "system",
            "summary": "Keeps publication, connector, and store truth bounded to the tenant-admin/system lane.",
            "route": "/data/status",
            "output_metric": str(CONFIG.runtime_backend or "local"),
            "approval_dependency": "system_boundary",
        },
    ]
    discoverable = [
        {
            "module_id": "ceo-brief",
            "label": "CEO brief",
            "route": "/executive?persona=ceo",
            "lane": "executive",
            "permitted": True,
            "summary": "Board-safe Group CEO framing over the latest governed packet.",
        },
        {
            "module_id": "board-room-memory",
            "label": "Board room memory",
            "route": f"/executive?persona=board&board={_publication_lifecycle_mode(publication)}",
            "lane": "executive",
            "permitted": True,
            "summary": "Lets the board portal move between pre-board, live, and closed memory modes.",
        },
        {
            "module_id": "reviewer-gate-console",
            "label": "Reviewer gate console",
            "route": "/reviewer/pending-reviews",
            "lane": "review",
            "permitted": principal_has_any_role(role, "reviewer", "tenant_admin", "system"),
            "summary": "Focused queue for claim, approval, rejection, and evidence closure.",
        },
        {
            "module_id": "operator-resume-relay",
            "label": "Operator resume relay",
            "route": "/app?lane=operate",
            "lane": "operate",
            "permitted": principal_has_any_role(role, "operator", "tenant_operator", "tenant_admin", "system"),
            "summary": "Shows source-pack intake, launch, and post-approval resume semantics.",
        },
        {
            "module_id": "tenant-runtime-watch",
            "label": "System health monitor",
            "route": "/app?lane=system",
            "lane": "system",
            "permitted": principal_has_any_role(role, "tenant_admin", "system"),
            "summary": "Exposes deeper store, connector, and publication-boundary truth.",
        },
    ]
    approvals = [
        {
            "approval_id": "reviewer_release",
            "label": "Reviewer release gate",
            "status": publication.get("approval_status") or "pending",
            "required": bool((publication.get("approval") or {}).get("required", False)),
            "next_action": (publication.get("approval") or {}).get("next_action") or workflow.get("next_action"),
            "route": "/reviewer/pending-reviews",
        },
        {
            "approval_id": "operator_resume",
            "label": "Operator resume",
            "status": "ready" if (publication.get("approval") or {}).get("resumable") else "waiting",
            "required": True,
            "next_action": "operator_resume",
            "route": "/app?lane=operate",
        },
        {
            "approval_id": "board_safe_publication",
            "label": "Board-safe publication",
            "status": str((publication.get("board_pack") or {}).get("status") or "pending"),
            "required": True,
            "next_action": (publication.get("approval") or {}).get("next_action") or "prepare_board_pack",
            "route": publication.get("preview_route") or "/public/runs/latest/report-preview",
        },
    ]
    audit_log = [
        {
            "event_id": "latest-run-stage",
            "title": "Latest run stage",
            "detail": f"Stage {workflow.get('current_stage') or 'created'} with status {workflow.get('run_status') or 'unknown'}.",
        },
        {
            "event_id": "latest-approval-posture",
            "title": "Approval posture",
            "detail": f"Approval is {publication.get('approval_status') or 'pending'} and next action is {str((publication.get('approval') or {}).get('next_action') or workflow.get('next_action') or 'awaiting_action').replace('_', ' ')}.",
        },
        {
            "event_id": "latest-publication-boundary",
            "title": "Publication boundary",
            "detail": f"Board pack is {str((publication.get('board_pack') or {}).get('status') or 'pending').replace('_', ' ')} with {publication.get('report_count') or 0} surfaced report artifact(s).",
        },
    ]
    return {
        "status": "ok" if summary else "awaiting_run",
        "summary": {
            "running_count": len(modules),
            "discoverable_count": len(discoverable),
            "approval_count": len(approvals),
        },
        "running": modules,
        "discoverable": discoverable,
        "approvals": approvals,
        "audit_log": audit_log,
    }


def _role_actions_payload(
    summary: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    audit_summary: dict[str, Any] | None,
    principal: dict[str, Any],
) -> dict[str, Any]:
    role = str(principal.get("role") or "anonymous")
    public_safe = _principal_prefers_public_safe_surface(principal)
    publication = _summary_publication_payload(
        summary,
        principal_role=role,
        public_safe=public_safe,
    )
    lanes = _role_lane_contracts(principal)
    next_action = (publication.get("approval") or {}).get("next_action") or _governed_next_action(
        summary,
        rows,
        audit_summary,
    )
    run_token = quote(str((summary or {}).get("run_id") or "{run_id}"), safe="{}-")

    def action(
        action_id: str,
        label: str,
        route: str,
        *,
        method: str = "GET",
        enabled: bool = True,
        detail: str,
        payload_template: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "action_id": action_id,
            "label": label,
            "route": route,
            "method": method,
            "enabled": enabled,
            "detail": detail,
            "payload_template": payload_template,
        }

    sections = [
        {
            "role_id": "executive",
            "label": "Executive",
            "active": principal_has_any_role(role, "executive") or public_safe,
            "primary_route": "/executive",
            "summary": "Board-safe narrative, lifecycle framing, and bounded publication posture.",
            "actions": [
                action(
                    "view_board_safe_preview",
                    "View board-safe preview",
                    publication.get("preview_route") or "/public/runs/latest/report-preview",
                    detail="Executive surface stays read-only and board-safe.",
                ),
                action(
                    "inspect_board_portal",
                    "Inspect board portal",
                    f"/executive?board={_publication_lifecycle_mode(publication)}",
                    detail=f"Current board mode is {_publication_lifecycle_mode(publication)}.",
                ),
            ],
        },
        {
            "role_id": "bu",
            "label": "BU leader",
            "active": principal_has_any_role(role, "bu"),
            "primary_route": lanes.get("bu", {}).get("primary_route", "/app?lane=review#bu"),
            "summary": "Read-only queue, evidence posture, and governed handoff preparation.",
            "actions": [
                action(
                    "inspect_governed_queue",
                    "Inspect governed queue",
                    lanes.get("bu", {}).get("pending_reviews_route", "/bu/pending-reviews"),
                    detail="BU lane stays read-only by design.",
                ),
                action(
                    "inspect_evidence_qa",
                    "Inspect evidence QA",
                    lanes.get("bu", {}).get("evidence_qa_route", "/runs/latest/findings?domain=evidence_qa"),
                    detail="Use domain QA posture to prepare the reviewer handoff.",
                ),
                action(
                    "read_governed_report_posture",
                    "Read governed report posture",
                    "/runs/latest/report-preview",
                    detail=f"Publication remains {publication.get('status') or 'draft'} with next action {str(next_action).replace('_', ' ')}.",
                ),
            ],
        },
        {
            "role_id": "reviewer",
            "label": "Reviewer",
            "active": principal_has_any_role(role, "reviewer"),
            "primary_route": lanes.get("reviewer", {}).get("primary_route", "/app?lane=review#review"),
            "summary": "Claim the packet, inspect evidence, and record the release decision.",
            "actions": [
                action(
                    "claim_review",
                    "Claim review",
                    f"/reviewer/runs/{run_token}/claim",
                    method="POST",
                    enabled=bool(summary),
                    detail="Claim the governed packet before writing an approval decision.",
                ),
                action(
                    "approve_release",
                    "Approve release",
                    f"/reviewer/runs/{run_token}/approve",
                    method="POST",
                    enabled=bool(summary),
                    detail="Records the reviewer approval that unlocks operator resume.",
                    payload_template={
                        "comment": "Approved for bounded board-safe release posture.",
                        "payload": {"decision_source": "reviewer", "publish_state": "approved_for_release"},
                    },
                ),
                action(
                    "reject_release",
                    "Reject release",
                    f"/reviewer/runs/{run_token}/reject",
                    method="POST",
                    enabled=bool(summary),
                    detail="Rejects the packet and keeps publication blocked until evidence is revised.",
                    payload_template={
                        "comment": "Evidence or challenge posture still needs revision.",
                        "payload": {"decision_source": "reviewer", "publish_state": "blocked"},
                    },
                ),
            ],
        },
        {
            "role_id": "operator",
            "label": "Operator",
            "active": principal_has_any_role(role, "operator", "tenant_operator"),
            "primary_route": lanes.get("operator", {}).get("primary_route", "/app?lane=operate"),
            "summary": "Owns source-pack staging, launch, runtime motion, and post-approval resume.",
            "actions": [
                action(
                    "stage_source_pack",
                    "Stage source pack",
                    "/source-packs/from-path",
                    method="POST",
                    detail="Creates a governed source-pack intake record from a filesystem path.",
                    payload_template={"folder_path": str(CONFIG.workspace_root)},
                ),
                action(
                    "validate_source_pack",
                    "Validate source pack",
                    "/source-packs/validate",
                    method="POST",
                    detail="Validates an already staged source pack before run launch.",
                    payload_template={"source_pack_id": "{source_pack_id}"},
                ),
                action(
                    "resume_run",
                    "Resume approved run",
                    f"/operator/runs/{run_token}/resume",
                    method="POST",
                    enabled=bool((publication.get("approval") or {}).get("resumable")),
                    detail="Only enabled after reviewer approval is recorded at the awaiting-review gate.",
                ),
            ],
        },
        {
            "role_id": "tenant_admin",
            "label": "Tenant admin / system",
            "active": principal_has_any_role(role, "tenant_admin", "system"),
            "primary_route": lanes.get("tenant_admin", {}).get("primary_route", "/app?lane=system"),
            "summary": "Inspect managed data, queue posture, connectors, stores, and publication-boundary truth.",
            "actions": [
                action(
                    "inspect_data_status",
                    "Inspect data status",
                    "/data/status",
                    detail="Shows runtime posture, store readiness, workflow counts, and publication boundary data.",
                ),
                action(
                    "inspect_review_queue",
                    "Inspect review queue",
                    "/reviewer/pending-reviews",
                    detail="Shows the current queue of packets waiting for reviewer action.",
                ),
                action(
                    "inspect_publication_boundary",
                    "Inspect publication boundary",
                    "/runs/latest/report-preview",
                    detail="Keeps report surfaces, approval state, and board-pack readiness aligned before scale.",
                ),
            ],
        },
    ]
    return {
        "viewer_role": role,
        "viewer_display_name": _display_role(role),
        "next_action": next_action,
        "sections": sections,
    }


def _latest_report_preview_payload(
    principal: dict[str, Any],
    artifact_key: str | None = None,
    *,
    view_state: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    role = str(principal.get("role") or "anonymous")
    summary = _latest_summary()
    if summary is None:
        return {
            "status": "missing",
            "artifact_key": artifact_key or "executive_summary",
            "title": "Report preview",
            "preview_kind": "text",
            "preview_text": "No latest governed run is available yet.",
            "public_safe": principal_has_any_role(role, "executive"),
            "trend": _trend_card_payload(),
            "publication": _summary_publication_payload(
                None,
                principal_role=role,
                public_safe=principal_has_any_role(role, "executive"),
            ),
            "board_portal": _board_portal_payload(
                None,
                principal_role=role,
                public_safe=principal_has_any_role(role, "executive"),
            ),
            "agent_modules": _agent_modules_payload(None, [], None, principal),
            "role_actions": _role_actions_payload(None, [], None, principal),
        }
    if principal_has_any_role(role, "executive"):
        payload = _public_report_preview_payload(artifact_key, view_state=view_state)
        rows = _finding_rows_from_summary(summary)
        audit_summary = _latest_run_audit_summary_payload(summary)
        board_portal = _board_portal_payload(
            summary,
            principal_role=role,
            public_safe=True,
            requested_state=(view_state or {}).get("board"),
        )
        strategy_substrate = _strategy_substrate_payload(
            summary,
            rows,
            audit_summary,
            principal,
        )
        executive_modes = _executive_modes_payload(
            summary,
            principal,
            strategy_substrate=strategy_substrate,
            board_portal=board_portal,
            publication=payload["publication"],
            view_state=view_state,
        )
        drilldown = _drilldown_contract_payload(
            summary,
            principal,
            public_safe=True,
            finding_rows=rows,
            domain_filters=[],
            report_artifacts=list((_summary_report_contracts(summary).get("reports") or [])),
            board_portal=board_portal,
            executive_modes=executive_modes,
        )
        agent_modules = _agent_modules_payload(summary, rows, audit_summary, principal)
        payload["publication"] = _summary_publication_payload(
            summary,
            principal_role=role,
            public_safe=True,
        )
        payload["trend"] = _trend_card_payload(summary, rows, audit_summary)
        payload["plan_health"] = _bounded_plan_health_payload(summary, rows, audit_summary)
        payload["strategy_substrate"] = strategy_substrate
        payload["board_portal"] = board_portal
        payload["executive_modes"] = executive_modes
        payload["drilldown"] = drilldown
        payload["interaction_contracts"] = _interaction_contracts_payload(principal, public_safe=True)
        payload["agent_modules"] = agent_modules
        payload["role_actions"] = _role_actions_payload(summary, rows, audit_summary, principal)
        payload["executive_diagnostics"] = _executive_diagnostics_payload(
            summary,
            principal=principal,
            board_portal=board_portal,
            executive_modes=executive_modes,
            drilldown=drilldown,
            strategy_substrate=strategy_substrate,
            agent_modules=agent_modules,
            audit_summary=audit_summary,
            finding_rows=rows,
        )
        return payload

    publication = _summary_publication_payload(summary, principal_role=role)
    report_contracts = _summary_report_contracts(summary)
    reports = list(report_contracts.get("reports") or [])
    rows = _finding_rows_from_summary(summary)
    audit_summary = _latest_run_audit_summary_payload(summary)
    board_portal = _board_portal_payload(
        summary,
        principal_role=role,
        requested_state=(view_state or {}).get("board"),
    )
    strategy_substrate = _strategy_substrate_payload(summary, rows, audit_summary, principal)
    executive_modes = _executive_modes_payload(
        summary,
        principal,
        strategy_substrate=strategy_substrate,
        board_portal=board_portal,
        publication=publication,
        view_state=view_state,
    )
    drilldown = _drilldown_contract_payload(
        summary,
        principal,
        public_safe=False,
        finding_rows=rows,
        domain_filters=[],
        report_artifacts=reports,
        board_portal=board_portal,
        executive_modes=executive_modes,
    )
    agent_modules = _agent_modules_payload(summary, rows, audit_summary, principal)
    if not reports:
        return {
            "status": "missing",
            "run_id": summary.get("run_id"),
            "artifact_key": artifact_key or "report",
            "title": "Report preview",
            "preview_kind": "text",
            "preview_text": "The latest run has not surfaced report artifacts yet.",
            "public_safe": False,
            "available_artifacts": publication["available_artifacts"],
            "publication": publication,
            "board_portal": board_portal,
            "trend": _trend_card_payload(summary, rows, audit_summary),
            "plan_health": _bounded_plan_health_payload(summary, rows, audit_summary),
            "executive_modes": executive_modes,
            "drilldown": drilldown,
            "interaction_contracts": _interaction_contracts_payload(principal, public_safe=False),
            "strategy_substrate": strategy_substrate,
            "agent_modules": agent_modules,
            "role_actions": _role_actions_payload(summary, rows, audit_summary, principal),
            "executive_diagnostics": _executive_diagnostics_payload(
                summary,
                principal=principal,
                board_portal=board_portal,
                executive_modes=executive_modes,
                drilldown=drilldown,
                strategy_substrate=strategy_substrate,
                agent_modules=agent_modules,
                audit_summary=audit_summary,
                finding_rows=rows,
            ),
        }
    selected = next(
        (item for item in reports if item.get("artifact_key") == artifact_key), None
    ) if artifact_key else None
    if selected is None:
        selected = reports[0]
    selected_key = str(selected.get("artifact_key") or artifact_key or "report")
    title = str(selected.get("title") or ARTIFACT_TITLES.get(selected_key, "Report preview"))
    if principal_has_any_role(role, "operator", "reviewer"):
        payload = _run_artifact_payload(str(summary.get("run_id") or ""), selected_key, principal)
        payload["available_artifacts"] = publication["available_artifacts"]
        payload["publication"] = publication
        payload["board_portal"] = board_portal
        payload["trend"] = _trend_card_payload(summary, rows, audit_summary)
        payload["plan_health"] = _bounded_plan_health_payload(summary, rows, audit_summary)
        payload["strategy_substrate"] = strategy_substrate
        payload["executive_modes"] = executive_modes
        payload["drilldown"] = drilldown
        payload["interaction_contracts"] = _interaction_contracts_payload(principal, public_safe=False)
        payload["agent_modules"] = agent_modules
        payload["role_actions"] = _role_actions_payload(summary, rows, audit_summary, principal)
        payload["executive_diagnostics"] = _executive_diagnostics_payload(
            summary,
            principal=principal,
            board_portal=board_portal,
            executive_modes=executive_modes,
            drilldown=drilldown,
            strategy_substrate=strategy_substrate,
            agent_modules=agent_modules,
            audit_summary=audit_summary,
            finding_rows=rows,
        )
        payload["title"] = title
        payload["public_safe"] = False
        return payload

    if not selected.get("restricted"):
        artifact_path = Path(str(selected.get("path") or ""))
        if str(selected.get("path") or ""):
            payload = _read_artifact_payload(
                artifact_key=selected_key,
                artifact_path=artifact_path,
                scope="run",
                run_id=str(summary.get("run_id") or ""),
            )
            payload.pop("path", None)
            payload["available_artifacts"] = publication["available_artifacts"]
            payload["publication"] = publication
            payload["board_portal"] = board_portal
            payload["trend"] = _trend_card_payload(summary, rows, audit_summary)
            payload["plan_health"] = _bounded_plan_health_payload(summary, rows, audit_summary)
            payload["strategy_substrate"] = strategy_substrate
            payload["executive_modes"] = executive_modes
            payload["drilldown"] = drilldown
            payload["interaction_contracts"] = _interaction_contracts_payload(principal, public_safe=False)
            payload["agent_modules"] = agent_modules
            payload["role_actions"] = _role_actions_payload(summary, rows, audit_summary, principal)
            payload["executive_diagnostics"] = _executive_diagnostics_payload(
                summary,
                principal=principal,
                board_portal=board_portal,
                executive_modes=executive_modes,
                drilldown=drilldown,
                strategy_substrate=strategy_substrate,
                agent_modules=agent_modules,
                audit_summary=audit_summary,
                finding_rows=rows,
            )
            payload["title"] = title
            payload["public_safe"] = False
            return payload

    approval_status = str(summary.get("approval_status") or "pending")
    current_stage = _normalize_lifecycle_stage(summary.get("current_stage"))
    preview_lines = [
        f"Run {summary.get('run_id') or 'latest'} is at {current_stage} with approval status {approval_status}.",
        f"{publication['report_count']} report artifact(s) are tracked; {publication['restricted_report_count']} remain protected.",
        "Use reviewer/operator artifact access for restricted bodies; this role gets governed publication posture only.",
    ]
    return {
        "status": "ok",
        "run_id": summary.get("run_id"),
        "artifact_key": selected_key,
        "title": title,
        "preview_kind": "text",
        "preview_text": "\n\n".join(preview_lines),
        "available_artifacts": publication["available_artifacts"],
        "publication": publication,
        "board_portal": board_portal,
        "trend": _trend_card_payload(summary, rows, audit_summary),
        "plan_health": _bounded_plan_health_payload(summary, rows, audit_summary),
        "strategy_substrate": strategy_substrate,
        "executive_modes": executive_modes,
        "drilldown": drilldown,
        "interaction_contracts": _interaction_contracts_payload(principal, public_safe=False),
        "agent_modules": agent_modules,
        "role_actions": _role_actions_payload(summary, rows, audit_summary, principal),
        "executive_diagnostics": _executive_diagnostics_payload(
            summary,
            principal=principal,
            board_portal=board_portal,
            executive_modes=executive_modes,
            drilldown=drilldown,
            strategy_substrate=strategy_substrate,
            agent_modules=agent_modules,
            audit_summary=audit_summary,
            finding_rows=rows,
        ),
        "restricted": bool(selected.get("restricted")),
        "public_safe": False,
    }


def _sanitize_contract_list(
    items: list[dict[str, Any]],
    *,
    include_paths: bool,
    include_restricted: bool,
) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for item in items:
        payload = dict(item)
        if not include_restricted and payload.get("restricted"):
            payload.pop("path", None)
        elif not include_paths:
            payload.pop("path", None)
        sanitized.append(payload)
    return sanitized


def _workspace_surface_contract_payload(
    summary: dict[str, Any] | None,
    principal: dict[str, Any],
    *,
    view_state: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    view_state = view_state or _requested_executive_view_state()
    authenticated = bool(principal.get("authenticated"))
    role = str(principal.get("role") or "anonymous")
    public_safe = _principal_prefers_public_safe_surface(principal)
    effective_summary = _anonymous_public_summary(summary) if public_safe else summary
    tenant_context = _summary_tenant_context(effective_summary, principal)
    finding_rows = _finding_rows_from_summary(summary) if isinstance(summary, dict) else []
    public_finding_rows = _anonymous_public_finding_payloads(finding_rows) if public_safe else finding_rows
    findings = build_case_summary_contracts(public_finding_rows) if isinstance(effective_summary, dict) else []
    report_contracts = _summary_report_contracts(effective_summary)
    audit_summary = _latest_run_audit_summary_payload(effective_summary) if isinstance(effective_summary, dict) else None
    metrics = (
        _governed_metrics_payload(effective_summary, public_finding_rows, audit_summary)
        if isinstance(effective_summary, dict)
        else _governed_metrics_payload(None, [], None)
    )
    can_investigate = principal_has_any_role(role, *INVESTIGATION_ROLES)
    can_review = principal_has_any_role(role, *REVIEW_WORKFLOW_ROLES)
    can_read_review = principal_has_any_role(role, *REVIEW_READ_ROLES)
    can_operate = principal_has_any_role(role, "operator")
    include_paths = can_review or can_operate
    filtered_evidence = _sanitize_contract_list(
        list(report_contracts.get("evidence") or []),
        include_paths=include_paths,
        include_restricted=can_review or can_operate,
    )
    filtered_reports = _sanitize_contract_list(
        list(report_contracts.get("reports") or []),
        include_paths=include_paths,
        include_restricted=can_review or can_operate,
    )
    evidence_route = "/data/evidence-preview" if can_investigate else "/public/data/evidence-preview"
    findings_route = (
        "/public/runs/latest/findings"
        if public_safe
        else "/runs/latest/findings"
        if principal_has_any_role(role, *PRODUCT_READ_ROLES)
        else "/public/runs/latest/findings"
    )
    reports_route = (
        "/reviewer/runs/{run_id}"
        if can_review or can_operate
        else "/bu/runs/{run_id}"
        if principal_has_any_role(role, "bu")
        else "/public/runs/latest/report-preview"
    )
    surfaces = [
        build_surface_contract(
            surface_id="overview",
            title="Overview",
            visibility="public" if public_safe or principal_has_any_role(role, "executive") else "protected",
            audience=("anonymous", "executive", "analyst", "bu", "reviewer", "operator"),
            permitted=True,
            primary_route="/public/runs/latest" if public_safe or principal_has_any_role(role, "executive") else "/runs/latest",
            public_route="/public/runs/latest",
            actions=("view_summary", "view_history"),
        ),
        build_surface_contract(
            surface_id="cases",
            title="Cases",
            visibility="public" if public_safe or principal_has_any_role(role, "executive") else "protected",
            audience=("anonymous", "executive", "analyst", "bu", "reviewer", "operator"),
            permitted=True,
            primary_route=findings_route,
            public_route="/public/runs/latest/findings",
            actions=("list_cases", "view_case_summary"),
        ),
        build_surface_contract(
            surface_id="evidence",
            title="Evidence",
            visibility="public" if public_safe or not can_investigate else "protected",
            audience=("anonymous", "executive", "analyst", "bu", "reviewer", "operator"),
            permitted=True,
            primary_route=evidence_route,
            public_route="/public/data/evidence-preview",
            actions=("preview_evidence",) if not can_investigate else ("preview_evidence", "search_evidence"),
            notes=(
                "Board-safe preview only." if public_safe or principal_has_any_role(role, "executive") else "Protected evidence routes available."
            ,),
        ),
        build_surface_contract(
            surface_id="reports",
            title="Reports",
            visibility="public" if public_safe or principal_has_any_role(role, "executive") else "restricted" if can_review or can_operate else "protected" if principal_has_any_role(role, "bu") else "public",
            audience=("anonymous", "executive", "analyst", "bu", "reviewer", "operator"),
            permitted=True,
            primary_route=reports_route,
            public_route="/public/runs/latest/report-preview",
            actions=("view_report_preview", "view_governed_report_status") if principal_has_any_role(role, "bu") and not (can_review or can_operate) else ("view_report_preview",) if not (can_review or can_operate) else ("view_report_preview", "open_report_artifact"),
        ),
        build_surface_contract(
            surface_id="ingestion",
            title="Ingestion",
            visibility="restricted",
            audience=("operator",),
            permitted=can_operate,
            primary_route="/ingestion/connectors",
            actions=("list_connectors", "stage_source_pack", "validate_source_pack"),
        ),
        build_surface_contract(
            surface_id="workflow",
            title="Workflow",
            visibility="restricted",
            audience=("operator", "reviewer", "bu"),
            permitted=can_operate or can_read_review,
            primary_route="/reviewer/pending-reviews" if can_review else "/bu/pending-reviews" if principal_has_any_role(role, "bu") else "/runs",
            actions=(
                ("launch_run", "resume_run")
                if can_operate and not can_review
                else ("launch_run", "resume_run", "review_decision")
                if can_operate and can_review
                else ("view_review_queue", "view_governed_cases")
                if principal_has_any_role(role, "bu")
                else ("review_decision",)
                if can_review
                else ()
            ),
        ),
    ]
    findings_payload = _finding_case_contract_payloads(
        finding_rows,
        run_id=str(summary.get("run_id") or "") if isinstance(summary, dict) else None,
        public_safe=public_safe,
    ) if not public_safe else _anonymous_public_finding_payloads(finding_rows)
    domain_filters = [
        artifact_contracts_payload(item)
        for item in build_domain_filter_contracts(
            public_finding_rows,
            active_filter_id="finance_integrity",
            base_route=(
                "/public/runs/latest/findings" if public_safe else "/runs/latest/findings"
            ),
        )
    ]
    plan_health = _bounded_plan_health_payload(effective_summary, public_finding_rows, audit_summary)
    domain_tree = _multi_domain_tree_payload(effective_summary, public_finding_rows, audit_summary, principal)
    strategy_substrate = _strategy_substrate_payload(effective_summary, public_finding_rows, audit_summary, principal)
    trend = _trend_card_payload(effective_summary, public_finding_rows, audit_summary)
    board_portal = _board_portal_payload(
        effective_summary,
        principal_role=role,
        public_safe=public_safe,
        requested_state=view_state.get("board"),
    )
    publication = _summary_publication_payload(
        effective_summary,
        principal_role=role,
        public_safe=public_safe,
    )
    executive_modes = _executive_modes_payload(
        effective_summary,
        principal,
        strategy_substrate=strategy_substrate,
        board_portal=board_portal,
        publication=publication,
        view_state=view_state,
    )
    agent_modules = _agent_modules_payload(effective_summary, public_finding_rows, audit_summary, principal)
    chat = _chat_threads_payload(
        effective_summary,
        principal,
        executive_modes=executive_modes,
        board_portal=board_portal,
        publication=publication,
    )
    role_actions = _role_actions_payload(effective_summary, public_finding_rows, audit_summary, principal)
    drilldown = _drilldown_contract_payload(
        effective_summary,
        principal,
        public_safe=public_safe,
        finding_rows=public_finding_rows,
        domain_filters=domain_filters,
        report_artifacts=filtered_reports,
        board_portal=board_portal,
        executive_modes=executive_modes,
    )
    payload = {
        "status": "ok" if summary else "missing",
        "public_safe": public_safe,
        "run_id": effective_summary.get("run_id") if isinstance(effective_summary, dict) else None,
        "tenant_context": tenant_context,
        "principal": {
            "authenticated": authenticated,
            "role": role,
            "subject": str(principal.get("subject") or "anonymous"),
            "display_name": _display_name_for_principal(role, str(principal.get("subject") or "anonymous")),
            "altitude": _role_altitude(role),
            "capabilities": _principal_capabilities(role),
        },
        "surfaces": [artifact_contracts_payload(item) for item in surfaces],
        "company_switcher": _company_switcher_payload(principal),
        "portfolio_switcher": _portfolio_switcher_payload(principal),
        "domain_filters": domain_filters,
        "metrics": metrics,
        "plan_health": plan_health,
        "domain_tree": domain_tree,
        "strategy_substrate": strategy_substrate,
        "kpi_cards": _kpi_card_payloads(effective_summary, public_finding_rows, audit_summary),
        "trend": trend,
        "lanes": _role_lane_contracts(principal),
        "board_portal": board_portal,
        "agent_modules": agent_modules,
        "role_actions": role_actions,
        "executive_modes": executive_modes,
        "drilldown": drilldown,
        "interaction_contracts": _interaction_contracts_payload(
            principal,
            public_safe=public_safe,
        ),
        "chat": chat,
        "executive_diagnostics": _executive_diagnostics_payload(
            effective_summary,
            principal=principal,
            board_portal=board_portal,
            executive_modes=executive_modes,
            drilldown=drilldown,
            strategy_substrate=strategy_substrate,
            agent_modules=agent_modules,
            audit_summary=audit_summary,
            finding_rows=public_finding_rows,
        ),
        "agents": _agents_surface_payload(effective_summary, principal),
        "tenant_admin_system": _tenant_admin_system_payload(effective_summary, principal),
        "cases": {
            "count": len(findings_payload),
            "items": findings_payload,
        },
        "evidence": {
            "count": len(filtered_evidence),
            "artifacts": filtered_evidence,
            "preview_route": evidence_route,
        },
        "reports": {
            "count": len(filtered_reports),
            "artifacts": filtered_reports,
            "preview_route": "/public/runs/latest/report-preview",
            "publication": publication,
        },
        "workflow": {
            "next_action": _governed_next_action(summary, finding_rows, audit_summary),
            "review_queue_route": "/reviewer/pending-reviews" if can_review else "/bu/pending-reviews",
            "read_only": can_read_review and not can_review,
        },
        "system": {
            "runtime_route": "/data/status",
            "health_route": "/health/ready",
            "publication_route": "/runs/latest/report-preview",
            "workflow_route": "/reviewer/pending-reviews",
        },
    }
    return _sanitize_anonymous_public_payload(payload) if public_safe else payload


def _latest_run_audit_summary_payload(summary: dict[str, Any] | None) -> dict[str, Any]:
    if summary is None:
        return {
            "status": "missing",
            "challenged_finding_ids": [],
            "citation_count": None,
            "resolved_count": None,
        }

    citation_payload = _load_summary_artifact_json(summary, "citation_audit")
    citation_summary = (
        citation_payload.get("summary")
        if isinstance(citation_payload, dict)
        and isinstance(citation_payload.get("summary"), dict)
        else {}
    )
    acceptance = summary.get("acceptance") if isinstance(summary.get("acceptance"), dict) else {}
    audit_payload = _load_summary_artifact_json(summary, "audit_log")
    challenged_ids = _challenged_finding_ids_from_audit_log(audit_payload)
    verification = summary.get("audit_verification")
    if not challenged_ids and isinstance(verification, dict):
        raw_ids = verification.get("challenged_finding_ids") or []
        if isinstance(raw_ids, list):
            challenged_ids = sorted(str(item) for item in raw_ids if item)

    return {
        "status": "ok",
        "run_id": summary.get("run_id"),
        "run_dir": summary.get("run_dir"),
        "challenged_finding_ids": challenged_ids,
        "citation_count": citation_summary.get(
            "citation_count", acceptance.get("citation_count")
        ),
        "resolved_count": citation_summary.get(
            "resolved_count", acceptance.get("resolved_citation_count")
        ),
    }


def _workflow_item_payloads(
    items: list[dict[str, Any]],
    *,
    principal_role: str,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    principal = {"role": principal_role, "authenticated": principal_role != "anonymous"}
    for item in items:
        summary = item.get("summary_json") if isinstance(item.get("summary_json"), dict) else item
        finding_rows = _finding_rows_from_summary(summary) if isinstance(summary, dict) else []
        audit_summary = (
            _latest_run_audit_summary_payload(summary) if isinstance(summary, dict) else None
        )
        payloads.append(
            {
                **item,
                "workflow_summary": _record_workflow_summary(item),
                "publication": _summary_publication_payload(
                    summary if isinstance(summary, dict) else None,
                    principal_role=principal_role,
                ),
                "plan_health": _bounded_plan_health_payload(
                    summary if isinstance(summary, dict) else None,
                    finding_rows,
                    audit_summary,
                ),
                "trend": _trend_card_payload(
                    summary if isinstance(summary, dict) else None,
                    finding_rows,
                    audit_summary,
                    limit=4,
                ),
                "board_portal": _board_portal_payload(
                    summary if isinstance(summary, dict) else None,
                    principal_role=principal_role,
                ),
                "agent_modules": _agent_modules_payload(
                    summary if isinstance(summary, dict) else None,
                    finding_rows,
                    audit_summary,
                    principal,
                ),
                "role_actions": _role_actions_payload(
                    summary if isinstance(summary, dict) else None,
                    finding_rows,
                    audit_summary,
                    principal,
                ),
            }
        )
    return payloads


def _health_check(status: str, **details: Any) -> dict[str, Any]:
    payload = {"status": status}
    payload.update(details)
    return payload


def _artifact_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix == ".md":
        return "text/markdown"
    if suffix in {".txt", ".log", ".csv"}:
        return "text/plain"
    return "application/octet-stream"


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _run_artifact_map(record: dict[str, Any]) -> dict[str, str]:
    summary = record.get("summary_json") or {}
    artifacts = summary.get("artifacts") or {}
    return {str(key): str(value) for key, value in artifacts.items()}


def _checkpoint_artifact_map(record: dict[str, Any]) -> dict[str, str]:
    state_json = record.get("state_json") or {}
    artifacts = state_json.get("artifact_paths") or {}
    return {str(key): str(value) for key, value in artifacts.items()}


def _artifact_restriction_reasons(artifact_key: str, artifact_path: Path) -> list[str]:
    key = artifact_key.strip().lower()
    path_text = str(artifact_path).strip().lower()
    name = artifact_path.name.strip().lower()
    reasons: list[str] = []
    if key in RESTRICTED_ARTIFACT_KEYS:
        reasons.append(f"artifact_key:{key}")
    for marker in RESTRICTED_ARTIFACT_KEY_MARKERS:
        if marker in key:
            reasons.append(f"artifact_key_marker:{marker}")
    for marker in RESTRICTED_ARTIFACT_PATH_MARKERS:
        if marker in path_text or marker in name:
            reasons.append(f"artifact_path_marker:{marker}")
    return sorted(set(reasons))


def _artifact_access_audit_log_path() -> Path:
    return CONFIG.output_root / ARTIFACT_ACCESS_AUDIT_LOG


def _audit_artifact_access(
    *,
    principal: dict[str, Any],
    artifact_key: str,
    artifact_path: Path,
    scope: str,
    run_id: str,
    checkpoint_id: str | None,
    allowed: bool,
    restriction_reasons: list[str],
    detail: str,
) -> None:
    audit_record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "artifact_key": artifact_key,
        "artifact_path": str(artifact_path),
        "scope": scope,
        "run_id": run_id,
        "checkpoint_id": checkpoint_id,
        "principal_role": str(principal.get("role") or "unknown"),
        "principal_subject": str(principal.get("subject") or "unknown"),
        "allowed": allowed,
        "restricted": bool(restriction_reasons),
        "restriction_reasons": restriction_reasons,
        "detail": detail,
    }
    log_path = _artifact_access_audit_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(audit_record, sort_keys=True) + "\n")


def _enforce_artifact_access(
    *,
    principal: dict[str, Any],
    artifact_key: str,
    artifact_path: Path,
    scope: str,
    run_id: str,
    checkpoint_id: str | None = None,
    review_assignment: dict[str, Any] | None = None,
) -> None:
    resolved = artifact_path.expanduser().resolve()
    if not _path_is_within(resolved, CONFIG.output_root):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact path falls outside the configured output boundary.",
        )
    if not resolved.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact '{artifact_key}' does not exist on disk.",
        )

    restriction_reasons = _artifact_restriction_reasons(artifact_key, artifact_path)
    if not restriction_reasons:
        _audit_artifact_access(
            principal=principal,
            artifact_key=artifact_key,
            artifact_path=resolved,
            scope=scope,
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            allowed=True,
            restriction_reasons=[],
            detail="Non-restricted artifact preview allowed.",
        )
        return

    role = str(principal.get("role") or "")
    subject = str(principal.get("subject") or "")
    claimed_by = str((review_assignment or {}).get("claimed_by") or "")
    allowed = role == "operator" or (role == "reviewer" and subject and subject == claimed_by)
    detail = (
        "Restricted artifact preview allowed."
        if allowed
        else "Restricted artifact preview denied: operator or claimed reviewer required."
    )
    _audit_artifact_access(
        principal=principal,
        artifact_key=artifact_key,
        artifact_path=resolved,
        scope=scope,
        run_id=run_id,
        checkpoint_id=checkpoint_id,
        allowed=allowed,
        restriction_reasons=restriction_reasons,
        detail=detail,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Restricted artifacts require operator access or the currently claimed reviewer.",
        )


def _read_artifact_payload(
    *,
    artifact_key: str,
    artifact_path: Path,
    scope: str,
    run_id: str,
    checkpoint_id: str | None = None,
) -> dict[str, Any]:
    resolved = artifact_path.expanduser().resolve()
    if not _path_is_within(resolved, CONFIG.output_root):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact path falls outside the configured output boundary.",
        )
    if not resolved.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact '{artifact_key}' does not exist on disk.",
        )

    payload = {
        "status": "ok",
        "artifact_key": artifact_key,
        "scope": scope,
        "run_id": run_id,
        "checkpoint_id": checkpoint_id,
        "path": str(resolved),
        "name": resolved.name,
        "media_type": _artifact_media_type(resolved),
        "size_bytes": resolved.stat().st_size if resolved.is_file() else 0,
        "preview_kind": "unavailable",
        "preview_text": "",
        "preview_json": None,
        "truncated": False,
    }
    if resolved.is_dir():
        payload.update(
            {
                "preview_kind": "directory",
                "preview_text": "Directory artifacts are not previewed in this thin slice.",
            }
        )
        return payload

    size_bytes = int(payload["size_bytes"])
    with resolved.open("rb") as handle:
        raw = handle.read(ARTIFACT_PREVIEW_LIMIT_BYTES + 1)
    truncated = size_bytes > ARTIFACT_PREVIEW_LIMIT_BYTES
    preview_bytes = raw[:ARTIFACT_PREVIEW_LIMIT_BYTES]

    if b"\x00" in preview_bytes:
        payload.update(
            {
                "preview_kind": "binary",
                "preview_text": "Binary artifact preview is unavailable in this thin slice.",
                "truncated": truncated,
            }
        )
        return payload

    preview_text = preview_bytes.decode("utf-8", errors="ignore")
    if truncated:
        preview_text = f"{preview_text}\n\n… preview truncated …"

    suffix = resolved.suffix.lower()
    preview_kind = "text"
    preview_json = None
    if suffix == ".json":
        preview_kind = "json"
        if size_bytes <= ARTIFACT_JSON_PARSE_LIMIT_BYTES:
            try:
                preview_json = json.loads(resolved.read_text(encoding="utf-8"))
            except Exception:
                preview_json = None

    payload.update(
        {
            "preview_kind": preview_kind,
            "preview_text": preview_text,
            "preview_json": preview_json,
            "truncated": truncated,
        }
    )
    return payload


def _run_artifact_payload(
    run_id: str,
    artifact_key: str,
    principal: dict[str, Any],
) -> dict[str, Any]:
    run_record = state_store.get_run_detail(run_id)
    if isinstance(run_record, dict) and run_record.get("status") == "skipped":
        run_record = _local_run_record_for_run_id(run_id) or run_record
    record = _require_store_record(
        run_record,
        missing_detail=f"Run '{run_id}' was not found.",
    )
    assert isinstance(record, dict)
    artifacts = _run_artifact_map(record)
    artifact_path = artifacts.get(artifact_key)
    if artifact_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact '{artifact_key}' was not found for run '{run_id}'.",
        )
    _enforce_artifact_access(
        principal=principal,
        artifact_key=artifact_key,
        artifact_path=Path(artifact_path),
        scope="run",
        run_id=run_id,
        review_assignment=record.get("review_assignment"),
    )
    return _read_artifact_payload(
        artifact_key=artifact_key,
        artifact_path=Path(artifact_path),
        scope="run",
        run_id=run_id,
    )


def _checkpoint_artifact_payload(
    checkpoint_id: str,
    artifact_key: str,
    principal: dict[str, Any],
) -> dict[str, Any]:
    checkpoint_record = state_store.get_checkpoint_detail(checkpoint_id)
    if isinstance(checkpoint_record, dict) and checkpoint_record.get("status") == "skipped":
        checkpoint_record = _local_checkpoint_record_for_id(checkpoint_id) or checkpoint_record
    record = _require_store_record(
        checkpoint_record,
        missing_detail=f"Checkpoint '{checkpoint_id}' was not found.",
    )
    assert isinstance(record, dict)
    artifacts = _checkpoint_artifact_map(record)
    artifact_path = artifacts.get(artifact_key)
    if artifact_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Artifact '{artifact_key}' was not found for checkpoint '{checkpoint_id}'."
            ),
        )
    run_id = str(record.get("run_id") or "")
    run_record = state_store.get_run_detail(run_id)
    if isinstance(run_record, dict) and run_record.get("status") == "skipped":
        run_record = _local_run_record_for_run_id(run_id) or run_record
    run_record = _require_store_record(
        run_record,
        missing_detail=f"Run '{run_id}' was not found.",
    )
    assert isinstance(run_record, dict)
    _enforce_artifact_access(
        principal=principal,
        artifact_key=artifact_key,
        artifact_path=Path(artifact_path),
        scope="checkpoint",
        run_id=run_id,
        checkpoint_id=checkpoint_id,
        review_assignment=run_record.get("review_assignment"),
    )
    return _read_artifact_payload(
        artifact_key=artifact_key,
        artifact_path=Path(artifact_path),
        scope="checkpoint",
        run_id=run_id,
        checkpoint_id=checkpoint_id,
    )


def _resolve_dataset_path(dataset: str | None, *, skip_prepare: bool) -> Path | None:
    if dataset is None:
        return None
    resolved = Path(dataset).expanduser().resolve()
    allowed_roots = [CONFIG.workspace_root]
    if skip_prepare:
        allowed_roots.append(CONFIG.agent_input_dir)
    if not any(_path_is_within(resolved, root) for root in allowed_roots):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Dataset path must stay within the configured workspace boundary"
                " for local MVP execution."
            ),
        )
    return resolved


def _resolve_run_dir_path(run_dir: str | None) -> Path:
    resolved = (
        Path(run_dir).expanduser().resolve() if run_dir else CONFIG.default_run_dir
    )
    if not _path_is_within(resolved, CONFIG.output_root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Run directory must stay within the configured output boundary"
                " for local MVP execution."
            ),
        )
    return resolved


def _parse_network_target(value: str) -> tuple[str, int]:
    parsed = urlparse(value)
    host = parsed.hostname
    port = parsed.port
    if host is None:
        raise ValueError(f"Unable to parse host from '{value}'.")
    if port is None:
        port = 7687 if parsed.scheme.startswith("bolt") else 6379
    return host, port


def _check_postgres() -> dict[str, Any]:
    connection, skipped = database_connection()
    if skipped is not None:
        return _health_check("skipped", reason=skipped.get("reason"))
    assert connection is not None
    try:
        with connection as conn:
            with conn.cursor() as cur:
                cur.execute("select 1")
                cur.fetchone()
        return _health_check("ok")
    except Exception as exc:
        return _health_check("failed", reason=str(exc))


def _check_redis() -> dict[str, Any]:
    if not CONFIG.redis_url:
        return _health_check("skipped", reason="REDIS_URL is not configured.")
    try:
        host, port = _parse_network_target(CONFIG.redis_url)
        with closing(socket.create_connection((host, port), timeout=3)) as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = sock.recv(16)
        if response.startswith(b"+PONG"):
            return _health_check("ok", host=host, port=port)
        return _health_check(
            "failed",
            host=host,
            port=port,
            reason=f"Unexpected Redis response: {response!r}",
        )
    except Exception as exc:
        return _health_check("failed", reason=str(exc))


def _check_neo4j() -> dict[str, Any]:
    return check_neo4j_ready()


def _check_qdrant() -> dict[str, Any]:
    return check_qdrant_ready()


def _check_object_store() -> dict[str, Any]:
    if not CONFIG.object_store.enabled:
        return _health_check("skipped", reason="Object store is not configured.")
    try:
        store = S3CompatibleStore()
        store.client.head_bucket(Bucket=store.config.bucket)
        return _health_check("ok", bucket=store.config.bucket)
    except ObjectStoreUnavailable as exc:
        return _health_check("failed", reason=str(exc))
    except Exception as exc:
        return _health_check("failed", reason=str(exc))


def _check_workspace() -> dict[str, Any]:
    try:
        CONFIG.output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=CONFIG.output_root, prefix="healthcheck-", delete=True
        ):
            pass
        return _health_check("ok", output_root=str(CONFIG.output_root))
    except Exception as exc:
        return _health_check(
            "failed", output_root=str(CONFIG.output_root), reason=str(exc)
        )


def _check_runtime_dependencies() -> dict[str, Any]:
    return runtime_dependency_status()


def _check_run_execution() -> dict[str, Any]:
    if CONFIG.run_execution_mode == "sync":
        return _health_check("ok", execution_mode="sync")
    if CONFIG.run_execution_mode != "hatchet":
        return _health_check(
            "failed",
            execution_mode=CONFIG.run_execution_mode,
            reason="Unsupported run execution mode.",
        )
    try:
        from .hatchet_runtime import hatchet_dependency_status

        status_payload = hatchet_dependency_status(CONFIG)
    except Exception as exc:
        return _health_check("failed", execution_mode="hatchet", reason=str(exc))
    if status_payload.get("status") != "ok":
        return status_payload
    if not CONFIG.database_url:
        return _health_check(
            "failed",
            execution_mode="hatchet",
            reason="Hatchet execution mode requires DATABASE_URL for run job records.",
        )
    return status_payload


def _check_twins() -> dict[str, Any]:
    payload = twin_operational_health_payload()
    status_value = "ok" if payload.get("status") == "healthy" else "failed"
    return {
        "status": status_value,
        **payload,
    }


def _check_auth_boundary() -> dict[str, Any]:
    if not CONFIG.api_auth_enabled:
        return _health_check("skipped", reason="API auth is disabled.")
    if CONFIG.auth_mode == "proxy_oidc":
        missing = []
        if not CONFIG.trust_proxy_auth:
            missing.append("STRATEGYOS_TRUST_PROXY_AUTH")
        if not CONFIG.trusted_proxy_auth_secret:
            missing.append("STRATEGYOS_TRUSTED_PROXY_AUTH_SECRET")
        if not CONFIG.oidc_issuer_url:
            missing.append("OAUTH2_PROXY_OIDC_ISSUER_URL")
        if not CONFIG.oidc_client_id:
            missing.append("OAUTH2_PROXY_CLIENT_ID")
        if not CONFIG.oidc_redirect_url:
            missing.append("OAUTH2_PROXY_REDIRECT_URL")
        if not CONFIG.operator_emails:
            missing.append("STRATEGYOS_OPERATOR_EMAILS")
        if not CONFIG.reviewer_emails:
            missing.append("STRATEGYOS_REVIEWER_EMAILS")
        if missing:
            return _health_check(
                "failed",
                reason=f"Trusted proxy OIDC config is incomplete: {', '.join(missing)}.",
            )
        return _health_check(
            "ok",
            mode="proxy_oidc",
            issuer=CONFIG.oidc_issuer_url,
            redirect_url=CONFIG.oidc_redirect_url,
            operator_identities=len(CONFIG.operator_emails),
            reviewer_identities=len(CONFIG.reviewer_emails),
            public_live_health=CONFIG.public_health_enabled,
        )
    if CONFIG.auth_mode == "identity_provider":
        missing = []
        if not CONFIG.idp_issuer:
            missing.append("STRATEGYOS_IDP_ISSUER")
        if not CONFIG.idp_token_url:
            missing.append("STRATEGYOS_IDP_TOKEN_URL")
        if not CONFIG.idp_introspection_url:
            missing.append("STRATEGYOS_IDP_INTROSPECTION_URL")
        if not CONFIG.idp_client_id:
            missing.append("STRATEGYOS_IDP_CLIENT_ID")
        if not CONFIG.idp_client_secret:
            missing.append("STRATEGYOS_IDP_CLIENT_SECRET")
        if not CONFIG.idp_operator_username or not CONFIG.idp_reviewer_username:
            missing.append("STRATEGYOS_IDP_OPERATOR_USERNAME/STRATEGYOS_IDP_REVIEWER_USERNAME")
        if missing:
            return _health_check(
                "failed",
                reason=f"Local identity provider config is incomplete: {', '.join(missing)}.",
            )
        return _health_check(
            "ok",
            mode="identity-provider",
            issuer=CONFIG.idp_issuer,
            operator_username=CONFIG.idp_operator_username,
            reviewer_username=CONFIG.idp_reviewer_username,
            public_live_health=CONFIG.public_health_enabled,
        )
    if not CONFIG.operator_api_keys:
        return _health_check("failed", reason="STRATEGYOS_OPERATOR_API_KEYS is empty.")
    if not CONFIG.reviewer_api_keys:
        return _health_check("failed", reason="STRATEGYOS_REVIEWER_API_KEYS is empty.")
    return _health_check(
        "ok",
        bu_keys=len(CONFIG.bu_api_keys),
        tenant_operator_keys=len(CONFIG.tenant_operator_api_keys),
        tenant_admin_keys=len(CONFIG.tenant_admin_api_keys),
        system_keys=len(CONFIG.system_api_keys),
        operator_keys=len(CONFIG.operator_api_keys),
        reviewer_keys=len(CONFIG.reviewer_api_keys),
        public_live_health=CONFIG.public_health_enabled,
    )


def _check_governance_boundary() -> dict[str, Any]:
    if not CONFIG.require_human_review:
        return _health_check(
            "ok",
            require_human_review=False,
            reason="Human review gate is disabled.",
        )
    if not CONFIG.api_auth_enabled:
        return _health_check(
            "failed", reason="Human review is enabled but API auth is disabled."
        )
    if CONFIG.auth_mode == "identity_provider":
        auth_boundary = _check_auth_boundary()
        if auth_boundary.get("status") != "ok":
            return _health_check(
                "failed",
                reason=str(auth_boundary.get("reason") or "Identity provider is not configured."),
            )
        return _health_check(
            "ok",
            require_human_review=True,
            auth_mode="identity-provider",
        )
    if CONFIG.auth_mode == "proxy_oidc":
        auth_boundary = _check_auth_boundary()
        if auth_boundary.get("status") != "ok":
            return _health_check(
                "failed",
                reason=str(auth_boundary.get("reason") or "Trusted proxy OIDC is not configured."),
            )
        return _health_check(
            "ok",
            require_human_review=True,
            auth_mode="proxy_oidc",
        )
    if not CONFIG.operator_api_keys or not CONFIG.reviewer_api_keys:
        return _health_check(
            "failed",
            reason="Human review requires both operator and reviewer API keys.",
        )
    return _health_check("ok", require_human_review=True)


def _ui_environment_label() -> str:
    return CONFIG.environment_label.strip() or "Local development"


def _ui_bootstrap(
    *,
    view_state: dict[str, str | None] | None = None,
    entry_route: str = "/app",
) -> dict[str, Any]:
    llm_status = llm_qa.chat_status(CONFIG)
    requested_view_state = dict(view_state or _requested_executive_view_state())
    public_packet_persona = str(requested_view_state.get("persona") or "ceo")
    return {
        "product_name": "StrategyOS",
        "shell_title": "StrategyOS Governed Operations",
        "environment": _ui_environment_label(),
        "workspace_root": str(CONFIG.workspace_root),
        "default_run_dir": str(CONFIG.default_run_dir),
        "output_root": str(CONFIG.output_root),
        "auth_mode": CONFIG.auth_mode,
        "api_auth_enabled": CONFIG.api_auth_enabled,
        "idp_enabled": CONFIG.idp_enabled,
        "require_human_review": CONFIG.require_human_review,
        "public_health_enabled": CONFIG.public_health_enabled,
        "run_execution_mode": CONFIG.run_execution_mode,
        "qa_modes": {
            "auto": {
                "enabled": True,
                "label": "Auto",
                "description": "Deterministic Q&A first; AI fallback when deterministic cannot answer.",
                "llm_fallback": llm_status,
            },
            "deterministic": {"enabled": True},
            "llm": llm_status,
        },
        "executive_route_base": "/app",
        "executive_entry_route": entry_route,
        "assistant_public_context": executive_public_assistant_packet(public_packet_persona),
        "requested_view_state": requested_view_state,
        "route_contracts": {
            "entry": _build_executive_route(view_state, base_route=entry_route),
            "app": "/app",
            "dashboard": "/dashboard",
            "executive": "/executive",
            "workspace_contract": "/ui/workspace-contract/latest",
            "public_latest_run": "/public/runs/latest",
            "public_report_preview": "/public/runs/latest/report-preview",
            "ui_session": "/ui/session",
            "qa": "/qa",
            "view_state_query_keys": {
                "persona": "persona",
                "board": "board",
                "driver": "driver",
                "company": "company",
                "portfolio": "portfolio",
                "week": "week",
                "agent": "agent",
            },
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _dashboard_html() -> str:
    bootstrap_json = (
        json.dumps(_ui_bootstrap())
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    template_path = STATIC_DIR / "index.html"
    html_text = template_path.read_text(encoding="utf-8")
    return html_text.replace("__STRATEGYOS_BOOTSTRAP__", bootstrap_json)


def _homepage_html() -> str:
    template_path = STATIC_DIR / "home.html"
    return template_path.read_text(encoding="utf-8")


def _executive_html(
    *,
    view_state: dict[str, str | None] | None = None,
    entry_route: str = "/app",
) -> str:
    bootstrap_json = (
        json.dumps(_ui_bootstrap(view_state=view_state, entry_route=entry_route))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    template_path = STATIC_DIR / "executive.html"
    html_text = template_path.read_text(encoding="utf-8")
    html_text = html_text.replace("__STRATEGYOS_EXECUTIVE_BOOTSTRAP__", bootstrap_json)
    if view_state and view_state.get("persona") == "ceo":
        lines = html_text.split("\n")
        lines = [
            line
            for line in lines
            if 'id="feedback-btn"' not in line
            and 'id="a2a-report-bug"' not in line
        ]
        html_text = "\n".join(lines)
    return html_text


def _default_surface_route(principal: dict[str, Any]) -> str:
    role = str(principal.get("role") or "anonymous")
    if principal_has_any_role(role, "system") or principal_has_any_role(role, "tenant_admin"):
        return "/app?lane=system"
    if principal_has_any_role(role, "bu"):
        return "/app?lane=review#bu"
    if principal_has_any_role(role, "reviewer"):
        return "/app?lane=review#review"
    if principal_has_any_role(role, "operator"):
        return "/app?lane=operate"
    if principal_has_any_role(role, "executive"):
        return "/app"
    return "/executive"


def _load_summary_artifact_json(
    summary: dict[str, Any],
    artifact_key: str,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    artifacts = summary.get("artifacts") if isinstance(summary, dict) else None
    if not isinstance(artifacts, dict):
        return None
    artifact_path = artifacts.get(artifact_key)
    if not artifact_path:
        return None
    path = Path(str(artifact_path))
    if not path.exists() or not path.is_file():
        return None
    if path.stat().st_size > ARTIFACT_JSON_PARSE_LIMIT_BYTES:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict) or (
        isinstance(payload, list) and all(isinstance(item, dict) for item in payload)
    ):
        return payload
    return None


def _sanitize_summary_for_bu(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {"status": "missing"}
    payload = _summary_with_reconciled_metrics(summary)
    payload.pop("run_dir", None)
    payload.pop("dataset", None)
    payload.pop("artifacts", None)
    payload.pop("report_contracts", None)
    payload.pop("pointer_metadata", None)
    payload.pop("latest_pointer", None)
    checkpoint = payload.get("local_review_checkpoint")
    if isinstance(checkpoint, dict):
        sanitized_checkpoint = dict(checkpoint)
        sanitized_checkpoint.pop("state_json", None)
        sanitized_checkpoint.pop("summary_json", None)
        payload["local_review_checkpoint"] = sanitized_checkpoint
    return payload


def _sanitize_run_record_for_bu(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    payload.pop("run_dir", None)
    payload.pop("dataset", None)
    payload.pop("dataset_root", None)
    payload.pop("artifacts", None)
    summary_json = payload.get("summary_json")
    if isinstance(summary_json, dict):
        payload["summary_json"] = _sanitize_summary_for_bu(summary_json)
    state_json = payload.get("state_json")
    if isinstance(state_json, dict):
        sanitized_state = dict(state_json)
        sanitized_state.pop("dataset_root", None)
        sanitized_state.pop("run_dir", None)
        sanitized_state.pop("artifact_paths", None)
        payload["state_json"] = sanitized_state
    return payload


def _knowledge_graph_path_from_summary(summary: dict[str, Any]) -> Path | None:
    artifacts = summary.get("artifacts") if isinstance(summary, dict) else None
    if not isinstance(artifacts, dict):
        return None
    artifact_path = artifacts.get(KNOWLEDGE_GRAPH_ARTIFACT_KEY)
    if not artifact_path:
        return None
    path = Path(str(artifact_path)).expanduser().resolve()
    allowed_roots = [CONFIG.output_root]
    run_dir = summary.get("run_dir")
    if run_dir:
        allowed_roots.append(Path(str(run_dir)).expanduser().resolve())
    if not any(_path_is_within(path, root) for root in allowed_roots):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge graph artifact path falls outside the configured output or run boundary.",
        )
    if not path.exists() or not path.is_file():
        return None
    return path


def _load_knowledge_graph_artifact(summary: dict[str, Any]) -> tuple[Path | None, dict[str, Any] | None]:
    path = _knowledge_graph_path_from_summary(summary)
    if path is None:
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Knowledge graph artifact could not be read: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Knowledge graph artifact is not a JSON object.",
        )
    return path, payload


def _kg_node_id(node: dict[str, Any]) -> str:
    return str(node.get("id") or "")


def _kg_node_label(node: dict[str, Any]) -> str:
    return str(node.get("label") or "")


def _kg_node_properties(node: dict[str, Any]) -> dict[str, Any]:
    properties = node.get("properties")
    return properties if isinstance(properties, dict) else {}


def _kg_edge_source(edge: dict[str, Any]) -> str:
    return str(edge.get("source") or "")


def _kg_edge_target(edge: dict[str, Any]) -> str:
    return str(edge.get("target") or "")


def _kg_edge_label(edge: dict[str, Any]) -> str:
    return str(edge.get("label") or "")


def _kg_amount(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _kg_display_for_node(
    node: dict[str, Any],
    *,
    invoice_counts: dict[str, int],
) -> dict[str, Any]:
    node_id = _kg_node_id(node)
    label = _kg_node_label(node)
    properties = _kg_node_properties(node)
    display = node_id
    sublabel = label
    if label == "Finding":
        display = str(properties.get("finding_id") or node_id.removeprefix("Finding:"))
        sublabel = str(properties.get("title") or properties.get("pattern_type") or "Finding")
    elif label == "Vendor":
        display = str(properties.get("vendor_name") or properties.get("vendor_id") or node_id.removeprefix("Vendor:"))
        invoice_count = invoice_counts.get(node_id, 0)
        vendor_id = properties.get("vendor_id") or node_id.removeprefix("Vendor:")
        sublabel = f"{vendor_id} - {invoice_count:,} invoices" if invoice_count else str(vendor_id)
    elif label == "Evidence":
        source_path = str(properties.get("source_path") or node_id.removeprefix("Evidence:"))
        display = Path(source_path).name or source_path
        sublabel = source_path
    elif label == "Contract":
        source_path = str(properties.get("source_path") or node_id.removeprefix("Contract:"))
        display = str(properties.get("contract_reference") or Path(source_path).name or "Contract")
        sublabel = str(properties.get("vendor_id") or source_path)
    elif label == "Invoice":
        display = str(properties.get("invoice_id") or node_id.removeprefix("Invoice:"))
        amount = _kg_amount(properties.get("amount_sar"))
        sublabel = f"SAR {amount:,.0f}" if amount else str(properties.get("status") or "Invoice")
    elif label == "PurchaseOrder":
        display = str(properties.get("po_id") or node_id.removeprefix("PurchaseOrder:"))
        amount = _kg_amount(properties.get("total"))
        sublabel = f"SAR {amount:,.0f}" if amount else str(properties.get("status") or "Purchase order")
    return {
        "id": node_id,
        "label": label,
        "display": display,
        "sublabel": sublabel,
        "properties": properties,
        "recoverable_sar": _kg_amount(properties.get("recoverable_sar")),
        "invoice_count": invoice_counts.get(node_id, 0),
    }


def _kg_edge_view(edge: dict[str, Any]) -> dict[str, Any]:
    source = _kg_edge_source(edge)
    target = _kg_edge_target(edge)
    label = _kg_edge_label(edge)
    properties = edge.get("properties")
    return {
        "id": f"{source}|{label}|{target}",
        "source": source,
        "target": target,
        "label": label,
        "properties": properties if isinstance(properties, dict) else {},
    }


def _kg_invoice_counts(edges: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in edges:
        if _kg_edge_label(edge) != "ISSUED_INVOICE":
            continue
        source = _kg_edge_source(edge)
        counts[source] = counts.get(source, 0) + 1
    return counts


def _knowledge_graph_base_node_ids(
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> set[str]:
    selected: set[str] = {
        node_id
        for node_id, node in nodes_by_id.items()
        if _kg_node_label(node) == "Finding"
    }
    first_hop = True
    while first_hop:
        first_hop = False
        for edge in edges:
            label = _kg_edge_label(edge)
            source = _kg_edge_source(edge)
            target = _kg_edge_target(edge)
            if label in {"SUPPORTED_BY", "INVOLVES_VENDOR"} and source in selected:
                for node_id in (source, target):
                    if node_id not in selected:
                        selected.add(node_id)
                        first_hop = True

    vendor_ids = {
        node_id
        for node_id in selected
        if _kg_node_label(nodes_by_id.get(node_id, {})) == "Vendor"
    }
    for edge in edges:
        label = _kg_edge_label(edge)
        source = _kg_edge_source(edge)
        target = _kg_edge_target(edge)
        if label in {"HAS_CONTRACT", "SAME_BANK_ACCOUNT_AS", "SAME_TAX_ID_AS"} and (
            source in vendor_ids or target in vendor_ids
        ):
            selected.add(source)
            selected.add(target)

    contract_ids = {
        node_id
        for node_id in selected
        if _kg_node_label(nodes_by_id.get(node_id, {})) == "Contract"
    }
    for edge in edges:
        if _kg_edge_label(edge) == "SUPPORTED_BY" and _kg_edge_source(edge) in contract_ids:
            selected.add(_kg_edge_target(edge))
    return selected


def _knowledge_graph_expand_node_ids(
    *,
    expand: str | None,
    limit: int,
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    selected: set[str],
) -> dict[str, Any]:
    if not expand:
        return {"node_id": None, "added": 0, "truncated": 0, "limit": limit}
    if expand not in nodes_by_id:
        return {"node_id": expand, "added": 0, "truncated": 0, "limit": limit, "status": "missing"}

    candidates: list[tuple[float, str, str]] = []
    for edge in edges:
        label = _kg_edge_label(edge)
        source = _kg_edge_source(edge)
        target = _kg_edge_target(edge)
        if label not in KNOWLEDGE_GRAPH_EXPAND_EDGE_LABELS:
            continue
        if source != expand and target != expand:
            continue
        other = target if source == expand else source
        other_props = _kg_node_properties(nodes_by_id.get(other, {}))
        amount = _kg_amount(other_props.get("amount_sar") or other_props.get("total"))
        candidates.append((amount, other, label))

    capped = sorted(candidates, key=lambda item: (-item[0], item[1]))[:limit]
    before = len(selected)
    selected.add(expand)
    for _, node_id, _ in capped:
        selected.add(node_id)

    truncated = max(0, len(candidates) - len(capped))
    return {
        "node_id": expand,
        "added": max(0, len(selected) - before),
        "truncated": truncated,
        "limit": limit,
        "status": "expanded",
    }


def _knowledge_graph_payload(
    *,
    summary: dict[str, Any],
    view: str,
    expand: str | None,
    limit: int,
) -> dict[str, Any]:
    graph_path, graph = _load_knowledge_graph_artifact(summary)
    if graph is None:
        return {
            "status": "missing",
            "run_id": summary.get("run_id"),
            "view": view,
            "reason": "Latest run has no knowledge graph artifact.",
            "nodes": [],
            "edges": [],
            "meta": {},
        }

    raw_nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    raw_edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
    nodes_by_id = {_kg_node_id(node): node for node in raw_nodes if _kg_node_id(node)}
    invoice_counts = _kg_invoice_counts(raw_edges)
    normalized_view = (view or KNOWLEDGE_GRAPH_DEFAULT_VIEW).strip().lower()
    bounded_limit = max(1, min(int(limit or KNOWLEDGE_GRAPH_EXPAND_LIMIT), 100))
    if normalized_view not in {"findings", "full"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Knowledge graph view must be 'findings' or 'full'.",
        )

    if normalized_view == "full":
        selected = set(sorted(nodes_by_id)[:KNOWLEDGE_GRAPH_FULL_LIMIT])
        expansion = {"node_id": None, "added": 0, "truncated": 0, "limit": bounded_limit}
        view_truncated = max(0, len(nodes_by_id) - len(selected))
    else:
        selected = _knowledge_graph_base_node_ids(nodes_by_id, raw_edges)
        expansion = _knowledge_graph_expand_node_ids(
            expand=expand,
            limit=bounded_limit,
            nodes_by_id=nodes_by_id,
            edges=raw_edges,
            selected=selected,
        )
        view_truncated = 0

    selected_edges = [
        edge
        for edge in raw_edges
        if _kg_edge_source(edge) in selected
        and _kg_edge_target(edge) in selected
        and _kg_edge_label(edge) in KNOWLEDGE_GRAPH_VISIBLE_EDGE_LABELS
    ]
    selected_nodes = [
        nodes_by_id[node_id]
        for node_id in sorted(selected)
        if node_id in nodes_by_id
    ]
    graph_meta = graph.get("meta") if isinstance(graph.get("meta"), dict) else {}
    return {
        "status": "ok",
        "run_id": summary.get("run_id"),
        "view": normalized_view,
        "graph_path": str(graph_path) if graph_path else None,
        "nodes": [
            _kg_display_for_node(node, invoice_counts=invoice_counts)
            for node in selected_nodes
        ],
        "edges": [_kg_edge_view(edge) for edge in selected_edges],
        "meta": {
            **graph_meta,
            "source_node_count": len(raw_nodes),
            "source_edge_count": len(raw_edges),
            "view_node_count": len(selected_nodes),
            "view_edge_count": len(selected_edges),
            "view_truncated": view_truncated,
        },
        "expansion": expansion,
    }


def _challenged_finding_ids_from_audit_log(
    payload: dict[str, Any] | list[dict[str, Any]] | None,
) -> list[str]:
    if isinstance(payload, dict):
        events = payload.get("events") or payload.get("records") or payload.get("items") or []
    else:
        events = payload or []
    challenged: set[str] = set()
    for item in events:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").lower()
        status_value = str(item.get("status") or "").lower()
        if action != "challenge" and status_value != "challenged":
            continue
        finding_id = item.get("finding_id")
        if finding_id:
            challenged.add(str(finding_id))
    return sorted(challenged)


def readiness_payload() -> dict[str, Any]:
    checks = {
        "postgres": _check_postgres(),
        "redis": _check_redis(),
        "neo4j": _check_neo4j(),
        "qdrant": _check_qdrant(),
        "object_store": _check_object_store(),
        "workspace": _check_workspace(),
        "ocr_runtime": _check_runtime_dependencies(),
        "run_execution": _check_run_execution(),
        "auth": _check_auth_boundary(),
        "governance": _check_governance_boundary(),
        "twins": _check_twins(),
    }
    statuses = [result.get("status") for result in checks.values()]
    if any(status == "failed" for status in statuses):
        overall = "failed"
    elif any(status == "skipped" for status in statuses):
        overall = "degraded"
    else:
        overall = "ok"
    return {
        "status": overall,
        "workspace_root": str(CONFIG.workspace_root),
        "output_root": str(CONFIG.output_root),
        "checks": checks,
    }


def _require_store_record(
    record: dict[str, Any] | list[dict[str, Any]] | None,
    *,
    missing_detail: str,
) -> dict[str, Any] | list[dict[str, Any]]:
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=missing_detail,
        )
    if isinstance(record, dict):
        record_status = record.get("status")
        if record_status == "missing":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=missing_detail,
            )
        if record_status == "skipped":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(record.get("reason") or "State store is unavailable."),
            )
    return record


def _require_store_mutation_result(
    record: dict[str, Any] | None,
    *,
    missing_detail: str,
    conflict_detail: str,
) -> dict[str, Any]:
    result = _require_store_record(record, missing_detail=missing_detail)
    assert isinstance(result, dict)
    if result.get("status") == "conflict":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(result.get("reason") or conflict_detail),
        )
    return result


def _record_reviewer_decision(
    *,
    run_id: str,
    decision: str,
    request: ReviewerDecisionRequest,
    principal: dict[str, Any],
) -> dict[str, Any]:
    checkpoint_record = state_store.latest_checkpoint(run_id)
    local_checkpoint = None
    if isinstance(checkpoint_record, dict) and checkpoint_record.get("status") == "skipped":
        local_checkpoint = _local_review_checkpoint_for_run(run_id)
        checkpoint_record = local_checkpoint
    checkpoint = _require_store_record(
        checkpoint_record,
        missing_detail=f"No checkpoint found for run '{run_id}'.",
    )
    assert isinstance(checkpoint, dict)
    reviewer_subject = str(principal.get("subject") or "unknown")
    reviewer_role = str(principal.get("role") or "reviewer")
    payload = {
        "decision": decision,
        "comment": request.comment,
        "checkpoint": {
            "checkpoint_id": checkpoint.get("checkpoint_id"),
            "stage": checkpoint.get("stage"),
            "status": checkpoint.get("status"),
            "fingerprint": (checkpoint.get("state_json") or {}).get(
                "checkpoint_fingerprint"
            )
            or (checkpoint.get("summary_json") or {}).get("checkpoint_fingerprint"),
            "quantification": (checkpoint.get("state_json") or {}).get(
                "quantification"
            )
            or (checkpoint.get("summary_json") or {}).get("quantification")
            or {},
        },
        **(request.payload or {}),
    }
    if local_checkpoint is not None:
        return _record_local_reviewer_decision(
            run_id=run_id,
            decision=decision,
            request=request,
            principal=principal,
            checkpoint=checkpoint,
        )
    result = _require_store_mutation_result(
        state_store.record_approval(
            run_id,
            str(checkpoint["checkpoint_id"]),
            reviewer_subject,
            reviewer_subject,
            reviewer_role,
            decision,
            request.comment,
            payload,
        ),
        missing_detail=f"Unable to record review decision for run '{run_id}'.",
        conflict_detail=f"Unable to record review decision for run '{run_id}'.",
    )
    _sync_run_summary_review_state(checkpoint=checkpoint, decision_result=result)
    return result


@app.get("/", response_class=HTMLResponse)
def homepage(
    persona: str | None = None,
    board: str | None = None,
    driver: str | None = None,
    company: str | None = None,
    portfolio: str | None = None,
    week: str | None = None,
    agent: str | None = None,
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> Any:
    view_state = _requested_executive_view_state(
        persona=persona,
        board=board,
        driver=driver,
        company=company,
        portfolio=portfolio,
        week=week,
        agent=agent,
    )
    if principal.get("authenticated"):
        default_route = _default_surface_route(principal)
        if default_route != "/executive":
            return RedirectResponse(url=default_route, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return HTMLResponse(_executive_html(view_state=view_state, entry_route="/"))


@app.get("/app", response_class=HTMLResponse)
def dashboard(
    persona: str | None = None,
    board: str | None = None,
    driver: str | None = None,
    company: str | None = None,
    portfolio: str | None = None,
    week: str | None = None,
    agent: str | None = None,
) -> str:
    return _executive_html(
        view_state=_requested_executive_view_state(
            persona=persona,
            board=board,
            driver=driver,
            company=company,
            portfolio=portfolio,
            week=week,
            agent=agent,
        ),
        entry_route="/app",
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_alias(
    persona: str | None = None,
    board: str | None = None,
    driver: str | None = None,
    company: str | None = None,
    portfolio: str | None = None,
    week: str | None = None,
    agent: str | None = None,
) -> str:
    return _executive_html(
        view_state=_requested_executive_view_state(
            persona=persona,
            board=board,
            driver=driver,
            company=company,
            portfolio=portfolio,
            week=week,
            agent=agent,
        ),
        entry_route="/dashboard",
    )


@app.get("/executive", response_class=HTMLResponse)
def executive_cockpit(
    persona: str | None = None,
    board: str | None = None,
    driver: str | None = None,
    company: str | None = None,
    portfolio: str | None = None,
    week: str | None = None,
    agent: str | None = None,
) -> str:
    return _executive_html(
        view_state=_requested_executive_view_state(
            persona=persona,
            board=board,
            driver=driver,
            company=company,
            portfolio=portfolio,
            week=week,
            agent=agent,
        ),
        entry_route="/executive",
    )


@app.get("/architecture", response_class=HTMLResponse)
def architecture_page() -> HTMLResponse:
    """Serve the architecture evolution page."""
    template_path = STATIC_DIR / "architecture.html"
    return HTMLResponse(template_path.read_text(encoding="utf-8"))


@app.get("/guide", response_class=HTMLResponse)
def guide_page() -> HTMLResponse:
    """Serve the non-technical StrategyOS user guide."""
    template_path = STATIC_DIR / "guide.html"
    return HTMLResponse(template_path.read_text(encoding="utf-8"))


@app.get("/plan", response_class=HTMLResponse)
def plan_page() -> HTMLResponse:
    """Serve the Digital Twin execution plan page."""
    template_path = STATIC_DIR / "plan.html"
    return HTMLResponse(template_path.read_text(encoding="utf-8"))


@app.get("/twin/ceo", response_class=HTMLResponse)
def twin_ceo_dashboard(
    principal: dict[str, Any] = require_twin_dashboard_access("ceo"),
) -> HTMLResponse:
    """Serve the CEO twin dashboard."""
    return HTMLResponse((TWINS_STATIC_DIR / "ceo.html").read_text(encoding="utf-8"))


@app.get("/twin/cfo", response_class=HTMLResponse)
def twin_cfo_dashboard(
    principal: dict[str, Any] = require_twin_dashboard_access("cfo"),
) -> HTMLResponse:
    """Serve the CFO twin dashboard."""
    return HTMLResponse((TWINS_STATIC_DIR / "cfo.html").read_text(encoding="utf-8"))


@app.get("/twin/gm", response_class=HTMLResponse)
def twin_gm_dashboard(
    principal: dict[str, Any] = require_twin_dashboard_access("gm"),
) -> HTMLResponse:
    """Serve the Group Manager twin dashboard."""
    return HTMLResponse((TWINS_STATIC_DIR / "gm.html").read_text(encoding="utf-8"))


@app.get("/ui/session")
def ui_session(
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> dict[str, Any]:
    authenticated = bool(principal.get("authenticated"))
    role = str(principal.get("role") or "anonymous")
    subject = str(principal.get("subject") or "anonymous")
    display_role = _display_role(role)
    display_subject = _display_subject(subject, role)
    display_name = _display_name_for_principal(role, subject)
    return {
        "status": "ok",
        "authenticated": authenticated,
        "role": role,
        "subject": subject,
        "display_role": display_role,
        "display_subject": display_subject,
        "display_name": display_name,
        "altitude": _role_altitude(role),
        "capabilities": _principal_capabilities(role),
        "tenant_context": _summary_tenant_context(None, principal),
        "company_switcher": _company_switcher_payload(principal),
        "portfolio_switcher": _portfolio_switcher_payload(principal),
        "auth_disabled": bool(principal.get("auth_disabled", False)),
        "auth_mode": CONFIG.auth_mode,
        "api_auth_enabled": CONFIG.api_auth_enabled,
        "idp_enabled": CONFIG.idp_enabled,
        "public_health_enabled": CONFIG.public_health_enabled,
        "require_human_review": CONFIG.require_human_review,
        "environment": _ui_environment_label(),
        "default_run_dir": str(CONFIG.default_run_dir),
        "output_root": str(CONFIG.output_root),
    }


@app.get("/ui/workspace-contract/latest")
def latest_workspace_contract(
    persona: str | None = None,
    board: str | None = None,
    driver: str | None = None,
    company: str | None = None,
    portfolio: str | None = None,
    week: str | None = None,
    agent: str | None = None,
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> dict[str, Any]:
    return _workspace_surface_contract_payload(
        _latest_summary(),
        principal,
        view_state=_requested_executive_view_state(
            persona=persona,
            board=board,
            driver=driver,
            company=company,
            portfolio=portfolio,
            week=week,
            agent=agent,
        ),
    )


@app.get("/public/runs/latest")
def public_latest_run(
    persona: str | None = None,
    board: str | None = None,
    driver: str | None = None,
    company: str | None = None,
    portfolio: str | None = None,
    week: str | None = None,
    agent: str | None = None,
) -> dict[str, Any]:
    return _latest_run_public_payload(
        _latest_summary(),
        view_state=_requested_executive_view_state(
            persona=persona,
            board=board,
            driver=driver,
            company=company,
            portfolio=portfolio,
            week=week,
            agent=agent,
        ),
    )


@app.get("/public/runs/latest/audit-summary")
def public_latest_run_audit_summary() -> dict[str, Any]:
    return _public_latest_run_audit_summary_payload(_latest_summary())


@app.get("/health")
def health(
    _: dict[str, Any] = Depends(require_live_health_access),
) -> dict[str, Any]:
    return {
        "status": "ok",
        "workspace_root": str(CONFIG.workspace_root),
        "output_root": str(CONFIG.output_root),
        "public_health_enabled": CONFIG.public_health_enabled,
    }


@app.get("/health/live")
def health_live(
    _: dict[str, Any] = Depends(require_live_health_access),
) -> dict[str, Any]:
    return {
        "status": "ok",
        "workspace_root": str(CONFIG.workspace_root),
        "output_root": str(CONFIG.output_root),
        "public_health_enabled": CONFIG.public_health_enabled,
    }


@app.get("/health/ready")
def health_ready(
    _: dict[str, Any] = require_role(*SYSTEM_READ_ROLES),
) -> JSONResponse:
    payload = readiness_payload()
    status_code = 200 if payload["status"] in {"ok", "degraded"} else 503
    return JSONResponse(content=payload, status_code=status_code)


@app.get("/health/config")
def health_config(
    _: dict[str, Any] = require_role(*SYSTEM_READ_ROLES),
) -> dict[str, Any]:
    return {
        "status": "ok",
        "object_store": object_store_status(),
        "ocr_runtime_dependencies": runtime_dependency_status(),
        "database_configured": bool(CONFIG.database_url),
        "redis_configured": bool(CONFIG.redis_url),
        "neo4j_configured": bool(CONFIG.neo4j_uri),
        "auth_mode": CONFIG.auth_mode,
        "api_auth_enabled": CONFIG.api_auth_enabled,
        "require_human_review": CONFIG.require_human_review,
        "twins": twin_operational_health_payload(),
        "llm_chat": llm_qa.chat_status(CONFIG),
        "run_execution": _check_run_execution(),
    }


@app.get("/health/dependencies")
def health_dependencies(
    _: dict[str, Any] = require_role(*SYSTEM_READ_ROLES),
) -> JSONResponse:
    payload = dict(runtime_dependency_status())
    checks = dict(payload.get("checks") or {})
    checks["run_execution"] = _check_run_execution()
    payload["checks"] = checks
    if checks["run_execution"].get("status") == "failed":
        payload["status"] = "failed"
    status_code = 200 if payload["status"] == "ok" else 503
    return JSONResponse(content=payload, status_code=status_code)


def _store_list_or_empty(
    record: dict[str, Any] | list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], str]:
    """List endpoints tolerate an unconfigured local store.

    When the state store is simply not configured (local-only mode, no
    DATABASE_URL), there is genuinely nothing persisted to list, so we return an
    empty list with a ``store_status`` of ``skipped`` rather than a 503. A real
    store error still surfaces as 503 via _require_store_record.
    """
    if isinstance(record, dict) and record.get("status") in {"skipped", "missing"}:
        return [], str(record.get("status"))
    items = _require_store_record(record, missing_detail="Records are unavailable.")
    assert isinstance(items, list)
    return items, "ok"


@app.get("/bu/pending-reviews")
def bu_pending_reviews(
    principal: dict[str, Any] = require_role(*REVIEW_READ_ROLES),
) -> dict[str, Any]:
    items, store_status = _store_list_or_empty(state_store.list_pending_reviews())
    if store_status == "skipped":
        items = _local_pending_review_items()
    role = str(principal.get("role") or "unknown")
    subject = str(principal.get("subject") or "unknown")
    item_payloads = _workflow_item_payloads(items, principal_role=role)
    return {
        "items": item_payloads,
        "store_status": store_status,
        "viewer_role": role,
        "viewer_subject": subject,
        "viewer_display_name": _display_name_for_principal(role, subject),
        "read_only": not principal_has_any_role(role, "reviewer"),
        "workflow_summary": {
            "pending_count": len(item_payloads),
            "claimed_count": sum(
                1
                for item in item_payloads
                if bool((item.get("review_assignment") or {}).get("claimed"))
            ),
        },
    }


@app.get("/bu/runs")
def bu_runs(
    limit: int = 12,
    principal: dict[str, Any] = require_role(*REVIEW_READ_ROLES),
) -> dict[str, Any]:
    items, store_status = _store_list_or_empty(state_store.list_recent_runs(limit=limit))
    if store_status == "skipped":
        items = _local_pending_review_items()
    role = str(principal.get("role") or "unknown")
    subject = str(principal.get("subject") or "unknown")
    return {
        "items": _workflow_item_payloads(items, principal_role=role),
        "store_status": store_status,
        "viewer_role": role,
        "viewer_subject": subject,
        "viewer_display_name": _display_name_for_principal(role, subject),
        "read_only": not principal_has_any_role(role, "reviewer"),
    }


@app.get("/bu/runs/{run_id}")
def bu_run_detail(
    run_id: str,
    principal: dict[str, Any] = require_role(*REVIEW_READ_ROLES),
) -> dict[str, Any]:
    run_record = state_store.get_run_detail(run_id)
    if isinstance(run_record, dict) and run_record.get("status") == "skipped":
        run_record = _local_run_record_for_run_id(run_id) or run_record
    record = _require_store_record(
        run_record,
        missing_detail=f"Run '{run_id}' was not found.",
    )
    assert isinstance(record, dict)
    sanitized = _sanitize_run_record_for_bu(record)
    sanitized["lifecycle_timeline"] = _run_lifecycle_timeline(record)
    sanitized["viewer_role"] = str(principal.get("role") or "unknown")
    sanitized["read_only"] = True
    sanitized["workflow_summary"] = _record_workflow_summary(record)
    summary_source = (
        record.get("summary_json") if isinstance(record.get("summary_json"), dict) else record
    )
    finding_rows = _finding_rows_from_summary(summary_source) if isinstance(summary_source, dict) else []
    audit_summary = (
        _latest_run_audit_summary_payload(summary_source) if isinstance(summary_source, dict) else None
    )
    sanitized["publication"] = _summary_publication_payload(
        summary_source,
        principal_role=str(principal.get("role") or "unknown"),
    )
    sanitized["plan_health"] = _bounded_plan_health_payload(
        summary_source if isinstance(summary_source, dict) else None,
        finding_rows,
        audit_summary,
    )
    sanitized["trend"] = _trend_card_payload(
        summary_source if isinstance(summary_source, dict) else None,
        finding_rows,
        audit_summary,
    )
    sanitized["board_portal"] = _board_portal_payload(
        summary_source if isinstance(summary_source, dict) else None,
        principal_role=str(principal.get("role") or "unknown"),
    )
    sanitized["strategy_substrate"] = _strategy_substrate_payload(
        summary_source if isinstance(summary_source, dict) else None,
        finding_rows,
        audit_summary,
        principal,
    )
    sanitized["agent_modules"] = _agent_modules_payload(
        summary_source if isinstance(summary_source, dict) else None,
        finding_rows,
        audit_summary,
        principal,
    )
    sanitized["role_actions"] = _role_actions_payload(
        summary_source if isinstance(summary_source, dict) else None,
        finding_rows,
        audit_summary,
        principal,
    )
    return sanitized


@app.get("/bu/checkpoints/{checkpoint_id}")
def bu_checkpoint_detail(
    checkpoint_id: str,
    principal: dict[str, Any] = require_role(*REVIEW_READ_ROLES),
) -> dict[str, Any]:
    checkpoint_record = state_store.get_checkpoint_detail(checkpoint_id)
    if isinstance(checkpoint_record, dict) and checkpoint_record.get("status") == "skipped":
        checkpoint_record = _local_checkpoint_record_for_id(checkpoint_id) or checkpoint_record
    record = _require_store_record(
        checkpoint_record,
        missing_detail=f"Checkpoint '{checkpoint_id}' was not found.",
    )
    assert isinstance(record, dict)
    sanitized = _sanitize_run_record_for_bu(record)
    sanitized["viewer_role"] = str(principal.get("role") or "unknown")
    sanitized["read_only"] = True
    return sanitized


@app.get("/bu/runs/{run_id}/artifacts/{artifact_key}")
def bu_run_artifact_preview(
    run_id: str,
    artifact_key: str,
    principal: dict[str, Any] = require_role(*REVIEW_READ_ROLES),
) -> dict[str, Any]:
    return _run_artifact_payload(run_id, artifact_key, principal)


@app.get("/bu/checkpoints/{checkpoint_id}/artifacts/{artifact_key}")
def bu_checkpoint_artifact_preview(
    checkpoint_id: str,
    artifact_key: str,
    principal: dict[str, Any] = require_role(*REVIEW_READ_ROLES),
) -> dict[str, Any]:
    return _checkpoint_artifact_payload(checkpoint_id, artifact_key, principal)


@app.get("/reviewer/pending-reviews")
def pending_reviews(
    principal: dict[str, Any] = require_role(*REVIEW_WORKFLOW_ROLES),
) -> dict[str, Any]:
    items, store_status = _store_list_or_empty(state_store.list_pending_reviews())
    if store_status == "skipped":
        items = _local_pending_review_items()
    role = str(principal.get("role") or "unknown")
    subject = str(principal.get("subject") or "unknown")
    item_payloads = _workflow_item_payloads(items, principal_role=role)
    return {
        "items": item_payloads,
        "store_status": store_status,
        "viewer_role": role,
        "viewer_subject": subject,
        "viewer_display_name": _display_name_for_principal(role, subject),
        "workflow_summary": {
            "pending_count": len(item_payloads),
            "claimed_count": sum(
                1
                for item in item_payloads
                if bool((item.get("review_assignment") or {}).get("claimed"))
            ),
        },
    }


@app.get("/reviewer/runs")
def reviewer_runs(
    limit: int = 12,
    principal: dict[str, Any] = require_role(*REVIEW_WORKFLOW_ROLES),
) -> dict[str, Any]:
    items, store_status = _store_list_or_empty(state_store.list_recent_runs(limit=limit))
    if store_status == "skipped":
        items = _local_pending_review_items()
    role = str(principal.get("role") or "unknown")
    subject = str(principal.get("subject") or "unknown")
    return {
        "items": _workflow_item_payloads(items, principal_role=role),
        "store_status": store_status,
        "viewer_role": role,
        "viewer_subject": subject,
        "viewer_display_name": _display_name_for_principal(role, subject),
    }


@app.get("/reviewer/runs/{run_id}")
def reviewer_run_detail(
    run_id: str,
    _: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    run_record = state_store.get_run_detail(run_id)
    if isinstance(run_record, dict) and run_record.get("status") == "skipped":
        run_record = _local_run_record_for_run_id(run_id) or run_record
    record = _require_store_record(
        run_record,
        missing_detail=f"Run '{run_id}' was not found.",
    )
    assert isinstance(record, dict)
    record["lifecycle_timeline"] = _run_lifecycle_timeline(record)
    record["workflow_summary"] = _record_workflow_summary(record)
    summary_source = (
        record.get("summary_json") if isinstance(record.get("summary_json"), dict) else record
    )
    finding_rows = _finding_rows_from_summary(summary_source) if isinstance(summary_source, dict) else []
    audit_summary = (
        _latest_run_audit_summary_payload(summary_source) if isinstance(summary_source, dict) else None
    )
    record["publication"] = _summary_publication_payload(
        summary_source,
        principal_role="reviewer",
    )
    record["plan_health"] = _bounded_plan_health_payload(
        summary_source if isinstance(summary_source, dict) else None,
        finding_rows,
        audit_summary,
    )
    record["trend"] = _trend_card_payload(
        summary_source if isinstance(summary_source, dict) else None,
        finding_rows,
        audit_summary,
    )
    record["strategy_substrate"] = _strategy_substrate_payload(
        summary_source if isinstance(summary_source, dict) else None,
        finding_rows,
        audit_summary,
        {"role": "reviewer", "authenticated": True},
    )
    return record


@app.get("/reviewer/checkpoints/{checkpoint_id}")
def reviewer_checkpoint_detail(
    checkpoint_id: str,
    _: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    checkpoint_record = state_store.get_checkpoint_detail(checkpoint_id)
    if isinstance(checkpoint_record, dict) and checkpoint_record.get("status") == "skipped":
        checkpoint_record = _local_checkpoint_record_for_id(checkpoint_id) or checkpoint_record
    record = _require_store_record(
        checkpoint_record,
        missing_detail=f"Checkpoint '{checkpoint_id}' was not found.",
    )
    assert isinstance(record, dict)
    return record


@app.get("/reviewer/runs/{run_id}/artifacts/{artifact_key}")
def reviewer_run_artifact_preview(
    run_id: str,
    artifact_key: str,
    principal: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    return _run_artifact_payload(run_id, artifact_key, principal)


@app.get("/reviewer/checkpoints/{checkpoint_id}/artifacts/{artifact_key}")
def reviewer_checkpoint_artifact_preview(
    checkpoint_id: str,
    artifact_key: str,
    principal: dict[str, Any] = require_role("operator", "reviewer"),
) -> dict[str, Any]:
    return _checkpoint_artifact_payload(checkpoint_id, artifact_key, principal)


@app.post("/reviewer/runs/{run_id}/claim")
def claim_run(
    run_id: str,
    principal: dict[str, Any] = require_role("reviewer"),
) -> dict[str, Any]:
    reviewer_subject = str(principal.get("subject") or "unknown")
    claim_record = state_store.claim_pending_review(run_id, reviewer_subject)
    if isinstance(claim_record, dict) and claim_record.get("status") == "skipped":
        claim_record = _mutate_local_review_assignment(
            run_id=run_id,
            reviewer_subject=reviewer_subject,
            claim=True,
        )
    return _require_store_mutation_result(
        claim_record,
        missing_detail=f"Run '{run_id}' was not found.",
        conflict_detail=f"Run '{run_id}' is not available for claim.",
    )


@app.post("/reviewer/runs/{run_id}/unclaim")
def unclaim_run(
    run_id: str,
    principal: dict[str, Any] = require_role("reviewer"),
) -> dict[str, Any]:
    reviewer_subject = str(principal.get("subject") or "unknown")
    unclaim_record = state_store.unclaim_pending_review(run_id, reviewer_subject)
    if isinstance(unclaim_record, dict) and unclaim_record.get("status") == "skipped":
        unclaim_record = _mutate_local_review_assignment(
            run_id=run_id,
            reviewer_subject=reviewer_subject,
            claim=False,
        )
    return _require_store_mutation_result(
        unclaim_record,
        missing_detail=f"Run '{run_id}' was not found.",
        conflict_detail=f"Run '{run_id}' is not currently claimed.",
    )


@app.post("/reviewer/runs/{run_id}/approve")
def approve_run(
    run_id: str,
    request: ReviewerDecisionRequest,
    principal: dict[str, Any] = require_role("reviewer"),
) -> dict[str, Any]:
    return _record_reviewer_decision(
        run_id=run_id,
        decision="approved",
        request=request,
        principal=principal,
    )


@app.post("/reviewer/runs/{run_id}/reject")
def reject_run(
    run_id: str,
    request: ReviewerDecisionRequest,
    principal: dict[str, Any] = require_role("reviewer"),
) -> dict[str, Any]:
    return _record_reviewer_decision(
        run_id=run_id,
        decision="rejected",
        request=request,
        principal=principal,
    )


@app.post("/operator/runs/{run_id}/resume")
def resume_run(
    run_id: str,
    _: dict[str, Any] = require_role("operator"),
) -> dict[str, Any]:
    approval_record = state_store.approval_status_for_run(run_id)
    if isinstance(approval_record, dict) and approval_record.get("status") == "skipped":
        approval_record = _local_approval_status_for_run(run_id)
    approval = _require_store_record(
        approval_record,
        missing_detail=f"Run '{run_id}' was not found.",
    )
    assert isinstance(approval, dict)
    if approval.get("approval_status") != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run '{run_id}' is not approved for resume.",
        )
    current_stage = _normalize_lifecycle_stage(approval.get("current_stage"))
    run_status = str(approval.get("run_status") or "").lower()
    if run_status == "completed" or current_stage == "writer":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run '{run_id}' already completed its writer deliverables.",
        )
    if current_stage != "awaiting_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Run '{run_id}' is at stage '{current_stage or 'unknown'}', not awaiting review."
            ),
        )
    checkpoint_record = state_store.latest_checkpoint(run_id)
    if isinstance(checkpoint_record, dict) and checkpoint_record.get("status") == "skipped":
        checkpoint_record = _local_review_checkpoint_for_run(run_id)
    checkpoint = _require_store_record(
        checkpoint_record,
        missing_detail=f"No checkpoint found for run '{run_id}'.",
    )
    assert isinstance(checkpoint, dict)
    checkpoint_stage = _normalize_lifecycle_stage(checkpoint.get("stage"))
    if checkpoint_stage != "awaiting_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Run '{run_id}' latest checkpoint is '{checkpoint_stage or 'unknown'}', not awaiting review."
            ),
    )
    try:
        return resume_reviewed_run(run_id, checkpoint)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.post("/source-packs")
def create_source_pack(
    files: list[UploadFile] = File(...),
    _: dict[str, Any] = require_role("operator"),
) -> dict[str, Any]:
    return stage_source_pack_uploads(files)


@app.post("/source-packs/from-path")
def create_source_pack_from_path(
    request: SourcePackPathRequest,
    _: dict[str, Any] = require_role("operator"),
) -> dict[str, Any]:
    return stage_source_pack_from_path(request.folder_path)


@app.post("/source-packs/validate")
def validate_source_pack_endpoint(
    request: SourcePackValidateRequest,
    _: dict[str, Any] = require_role("operator"),
) -> dict[str, Any]:
    return validate_source_pack(request.source_pack_id)


@app.post("/source-packs/confirm-mapping")
def confirm_source_pack_mapping_endpoint(
    request: SourcePackMappingConfirmRequest,
    _: dict[str, Any] = require_role("operator"),
) -> dict[str, Any]:
    return confirm_source_pack_mapping(
        request.source_pack_id,
        request.relative_path,
        role=request.role,
        column_mapping=request.column_mapping,
    )


@app.get("/ingestion/connectors", response_model=IngestionConnectorsResponse)
def list_ingestion_connectors(
    principal: dict[str, Any] = require_role(*SYSTEM_READ_ROLES),
) -> dict[str, Any]:
    tenant_context = build_tenant_context(
        tenant_id=str(principal.get("tenant_id") or CONFIG.tenant_slug),
    )
    return {
        "tenant_context": {
            "tenant_id": tenant_context.tenant_id,
            "tenant_name": tenant_context.tenant_name,
            "workspace_id": tenant_context.workspace_id,
        },
        "connectors": build_ingestion_connector_catalog(
            principal_role=str(principal.get("role") or "anonymous")
        ),
    }


@app.post("/finance/oracle/ingest")
def ingest_oracle_finance_snapshot(
    request: OracleFinanceIngestionRequest,
    principal: dict[str, Any] = require_role(
        "operator", "tenant_operator", "tenant_admin", "system"
    ),
) -> dict[str, Any]:
    if not CONFIG.oracle_pilot_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Oracle pilot ingest is disabled by rollout flag.",
        )
    _enforce_oracle_ingest_limits(request)
    tenant_id = _authorized_oracle_ingest_tenant_id(request, principal)
    batch_id = str(request.batch_id) if request.batch_id else None
    source_system_id = str(request.source_system_id) if request.source_system_id else None

    bu_mapping = BUFlexfieldMappingConfig(
        segment_name=request.bu_mapping.segment_name,
        segment_index=request.bu_mapping.segment_index,
        value_to_bu=dict(request.bu_mapping.value_to_bu),
        default_bu=request.bu_mapping.default_bu,
    )
    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(request.extracts),
        bu_mapping=bu_mapping,
        manual_inputs=request.manual_inputs,
        reporting_currency=request.reporting_currency or "SAR",
    )
    persisted = state_store.persist_oracle_canonical_snapshot(
        snapshot,
        tenant_id=tenant_id,
        batch_id=batch_id,
        source_system_id=source_system_id,
    )
    return {
        "status": str(persisted.get("status") or "ok"),
        "tenant_id": tenant_id,
        "batch_id": batch_id,
        "source_system_id": source_system_id,
        "submitted_by": str(principal.get("subject") or principal.get("role") or "operator"),
        "snapshot": snapshot_summary(snapshot),
        "persistence": persisted,
    }


def _authorized_oracle_ingest_tenant_id(
    request: OracleFinanceIngestionRequest,
    principal: Mapping[str, Any],
) -> str:
    requested_tenant_id = str(request.tenant_id)
    principal_tenant_id = str(principal.get("tenant_id") or "").strip()
    principal_role = str(principal.get("role") or "")
    if principal_role == "system":
        return requested_tenant_id
    if not principal_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An authenticated tenant scope is required for Oracle ingest.",
        )
    if not _is_uuid_like(principal_tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Oracle ingest requires a UUID-scoped authenticated tenant identity; "
                "slug-scoped tenant identities cannot safely authorize this write path."
            ),
        )
    if principal_tenant_id != requested_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The requested tenant_id does not match the authenticated tenant scope.",
        )
    return principal_tenant_id


def _is_uuid_like(value: str | None) -> bool:
    if not value:
        return False
    try:
        UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return False
    return True


def _oracle_pilot_rollout_flags() -> dict[str, bool]:
    return {
        "pilot_enabled": bool(CONFIG.oracle_pilot_enabled),
        "ceo_surface_enabled": bool(CONFIG.oracle_pilot_ceo_surface_enabled),
        "cfo_surface_enabled": bool(CONFIG.oracle_pilot_cfo_surface_enabled),
        "rollback_ready": bool(CONFIG.oracle_pilot_rollback_ready),
    }


def _oracle_ingest_payload_bytes(payload: Any) -> int:
    return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def _enforce_oracle_ingest_limits(request: OracleFinanceIngestionRequest) -> None:
    extract_bytes = _oracle_ingest_payload_bytes(request.extracts)
    if extract_bytes > ORACLE_INGEST_MAX_EXTRACT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Oracle ingest extracts exceed {ORACLE_INGEST_MAX_EXTRACT_BYTES} bytes.",
        )
    manual_inputs = request.manual_inputs or []
    manual_input_bytes = _oracle_ingest_payload_bytes(manual_inputs)
    if manual_input_bytes > ORACLE_INGEST_MAX_MANUAL_INPUT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Oracle ingest manual_inputs exceed {ORACLE_INGEST_MAX_MANUAL_INPUT_BYTES} bytes.",
        )


@app.post("/finance/oracle/validate")
def validate_oracle_pilot(
    request: OraclePilotValidationRequest,
    _: dict[str, Any] = require_role(
        "operator", "reviewer", "tenant_operator", "tenant_admin", "system"
    ),
) -> Any:
    bu_mapping = BUFlexfieldMappingConfig(
        segment_name=request.bu_mapping.segment_name,
        segment_index=request.bu_mapping.segment_index,
        value_to_bu=dict(request.bu_mapping.value_to_bu),
        default_bu=request.bu_mapping.default_bu,
    )
    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(request.extracts),
        bu_mapping=bu_mapping,
        manual_inputs=request.manual_inputs,
        reporting_currency=request.reporting_currency or "SAR",
    )
    computation = compute_oracle_pilot_kpis(
        snapshot,
        reporting_period_key=request.reporting_period_key,
        reporting_cadence=request.reporting_cadence,
    )
    review = compute_oracle_pilot_leakage(
        snapshot,
        reporting_period_key=request.reporting_period_key,
        reporting_cadence=request.reporting_cadence,
    )
    reconciliation = build_oracle_pilot_reconciliation_report(
        snapshot,
        computation,
        review,
    )
    lineage = build_oracle_pilot_lineage_payload(
        snapshot,
        computation,
        review,
        reviewer_actions=request.reviewer_actions,
    )
    rollout_controls = build_oracle_pilot_rollout_report(
        rollout_flags=_oracle_pilot_rollout_flags(),
        require_human_review=CONFIG.require_human_review,
    )
    readiness = build_oracle_pilot_readiness_report(
        reconciliation=reconciliation,
        auditability=lineage["auditability"],
        rollout_controls=rollout_controls,
        review=review,
        reviewer_actions=request.reviewer_actions,
        approval_status=str(request.approval_status or "pending"),
        require_human_review=CONFIG.require_human_review,
    )
    payload = {
        "status": "ready" if readiness["passed"] else "blocked",
        "snapshot": snapshot_summary(snapshot),
        "kpi": build_oracle_pilot_kpi_payload(computation),
        "leakage_review": build_oracle_leakage_review_payload(review),
        "reconciliation": reconciliation,
        "lineage": lineage,
        "rollout_controls": rollout_controls,
        "readiness": readiness,
    }
    if readiness["passed"]:
        return payload
    return JSONResponse(content=payload, status_code=status.HTTP_409_CONFLICT)


@app.post("/runs")
def create_run(
    request: RunRequest,
    principal: dict[str, Any] = require_role("operator"),
) -> Any:
    source_pack_id = (request.source_pack_id or "").strip() or None
    if source_pack_id and request.dataset:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run creation accepts either dataset or source_pack_id, not both.",
        )

    dataset = _resolve_dataset_path(request.dataset, skip_prepare=request.skip_prepare)
    run_dir = _resolve_run_dir_path(request.run_dir)
    if source_pack_id:
        resolve_source_pack_for_run(
            source_pack_id, allow_partial=bool(request.allow_partial_source_pack)
        )
    try:
        summary = submit_run(
            dataset=dataset,
            source_pack_id=source_pack_id,
            run_dir=run_dir,
            skip_prepare=request.skip_prepare if source_pack_id is None else True,
            sync_artifacts=request.sync_artifacts,
            allow_partial_source_pack=bool(request.allow_partial_source_pack),
            submitted_by=str(principal.get("subject") or "operator"),
            config=CONFIG,
            sync_runner=run_strategyos_workflow,
        )
    except RunExecutionUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    if summary.get("execution_mode") == "hatchet":
        return JSONResponse(content=summary, status_code=status.HTTP_202_ACCEPTED)
    return summary


@app.get("/runs/jobs/{job_id}")
def run_job_status(
    job_id: str,
    _: dict[str, Any] = require_role(*SYSTEM_READ_ROLES),
) -> dict[str, Any]:
    record = state_store.get_run_job(job_id)
    job = _require_store_record(
        record,
        missing_detail=f"Run job '{job_id}' was not found.",
    )
    assert isinstance(job, dict)
    run_id = job.get("strategyos_run_id")
    if run_id:
        run_detail = state_store.get_run_detail(str(run_id))
        if isinstance(run_detail, dict) and run_detail.get("status") not in {
            "missing",
            "skipped",
            "failed",
        }:
            job["run"] = run_detail
    return job


@app.get("/runs/latest")
def latest_run(
    persona: str | None = None,
    board: str | None = None,
    driver: str | None = None,
    company: str | None = None,
    portfolio: str | None = None,
    week: str | None = None,
    agent: str | None = None,
    principal: dict[str, Any] = require_role(*PRODUCT_READ_ROLES),
) -> dict[str, Any]:
    view_state = _requested_executive_view_state(
        persona=persona,
        board=board,
        driver=driver,
        company=company,
        portfolio=portfolio,
        week=week,
        agent=agent,
    )
    summary = _latest_summary()
    if summary is None:
        if principal_has_any_role(str(principal.get("role") or ""), "executive"):
            return {"status": "missing", "public_safe": True}
        return {"status": "missing", "run_dir": str(CONFIG.default_run_dir)}
    if principal_has_any_role(str(principal.get("role") or ""), "executive"):
        return _latest_run_public_payload(summary, view_state=view_state)
    if principal_has_any_role(str(principal.get("role") or ""), "bu"):
        return _sanitize_summary_for_bu(summary)
    return _summary_with_reconciled_metrics(summary, view_state=view_state)


@app.get("/runs/latest/audit-summary")
def latest_run_audit_summary(
    _: dict[str, Any] = require_role(*PRODUCT_READ_ROLES),
) -> dict[str, Any]:
    return _latest_run_audit_summary_payload(_latest_summary())


def _finding_rows_from_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Assemble one decision-worklist row per finding from the run's knowledge
    graph artifact. Finding nodes already carry id/title/pattern_type/amounts;
    SUPPORTED_BY edges give the citation count; the audit log marks challenged
    findings. Returns rows sorted by recoverable amount, descending."""
    _, graph = _load_knowledge_graph_artifact(summary)
    if not isinstance(graph, dict):
        return []
    raw_nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    raw_edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]

    citation_counts: dict[str, int] = {}
    vendor_by_finding: dict[str, str] = {}
    node_label_by_id = {_kg_node_id(n): _kg_node_label(n) for n in raw_nodes}
    node_props_by_id = {_kg_node_id(n): _kg_node_properties(n) for n in raw_nodes}
    for edge in raw_edges:
        source = _kg_edge_source(edge)
        if not source.startswith("Finding:"):
            continue
        label = _kg_edge_label(edge)
        if label == "SUPPORTED_BY":
            citation_counts[source] = citation_counts.get(source, 0) + 1
        elif label == "INVOLVES_VENDOR":
            target = _kg_edge_target(edge)
            props = node_props_by_id.get(target, {})
            vendor_by_finding.setdefault(
                source,
                str(props.get("vendor_name") or props.get("vendor_id") or ""),
            )

    audit_payload = _load_summary_artifact_json(summary, "audit_log")
    challenged_ids = set(_challenged_finding_ids_from_audit_log(audit_payload))
    verification = summary.get("audit_verification")
    if isinstance(verification, dict):
        for item in verification.get("challenged_finding_ids") or []:
            if item:
                challenged_ids.add(str(item))

    rows: list[dict[str, Any]] = []
    for node in raw_nodes:
        node_id = _kg_node_id(node)
        if node_label_by_id.get(node_id) != "Finding":
            continue
        props = node_props_by_id.get(node_id, {})
        finding_id = str(props.get("finding_id") or node_id.removeprefix("Finding:"))
        pattern_type = str(props.get("pattern_type") or "")
        rows.append(
            {
                "finding_id": finding_id,
                "title": str(props.get("title") or _humanize_pattern_label(pattern_type) or "Finding"),
                "pattern_type": pattern_type,
                "pattern_label": _humanize_pattern_label(pattern_type),
                "confidence": str(props.get("confidence") or ""),
                "status": str(props.get("status") or ""),
                "classification": str(props.get("classification") or ""),
                "recoverable_sar": _kg_amount(props.get("recoverable_sar")),
                "leakage_sar": _kg_amount(props.get("leakage_sar")),
                "owner": vendor_by_finding.get(node_id, ""),
                "citation_count": citation_counts.get(node_id, 0),
                "node_id": node_id,
                "challenged": finding_id in challenged_ids,
            }
        )
    rows.sort(key=lambda row: row["recoverable_sar"], reverse=True)
    return rows


def _latest_run_findings_payload(
    summary: dict[str, Any] | None,
    *,
    include_run_dir: bool,
    public_safe: bool,
    domain_filter: str | None = None,
    view_state: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    if public_safe:
        return _anonymous_public_findings_payload(
            summary,
            domain_filter=domain_filter,
            view_state=view_state,
        )
    principal = {
        "role": "executive" if public_safe else "operator",
        "authenticated": not public_safe,
    }
    if summary is None:
        return {
            "status": "missing",
            "findings": [],
            "total_recoverable_sar": None,
            "requires_human_review": False,
            "approval_status": None,
            "public_safe": public_safe,
            "agent_modules": _agent_modules_payload(None, [], None, principal),
            "role_actions": _role_actions_payload(None, [], None, principal),
        }
    rows = _finding_rows_from_summary(summary)
    filtered_rows = _filter_finding_rows(rows, domain_filter)
    findings_payload = _finding_case_contract_payloads(
        filtered_rows,
        run_id=str(summary.get("run_id") or "") or None,
        public_safe=public_safe,
    )
    audit_summary = _latest_run_audit_summary_payload(summary)
    metrics = _governed_metrics_payload(
        summary,
        rows,
        audit_summary,
        filtered_rows=filtered_rows,
    )
    publication = _summary_publication_payload(
        summary,
        principal_role="executive" if public_safe else "operator",
        public_safe=public_safe,
    )
    board_portal = _board_portal_payload(
        summary,
        principal_role="executive" if public_safe else "operator",
        public_safe=public_safe,
        requested_state=(view_state or {}).get("board"),
    )
    strategy_substrate = _strategy_substrate_payload(summary, rows, audit_summary, principal)
    executive_modes = _executive_modes_payload(
        summary,
        principal,
        strategy_substrate=strategy_substrate,
        board_portal=board_portal,
        publication=publication,
        view_state=view_state,
    )
    drilldown = _drilldown_contract_payload(
        summary,
        principal,
        public_safe=public_safe,
        finding_rows=rows,
        domain_filters=[
            artifact_contracts_payload(item)
            for item in build_domain_filter_contracts(
                rows,
                active_filter_id=str(domain_filter or "finance_integrity"),
                base_route=(
                    "/public/runs/latest/findings"
                    if public_safe
                    else "/runs/latest/findings"
                ),
            )
        ],
        report_artifacts=list(_summary_report_contracts(summary).get("reports") or []),
        board_portal=board_portal,
        executive_modes=executive_modes,
    )
    agent_modules = _agent_modules_payload(summary, rows, audit_summary, principal)
    agents = _agents_surface_payload(summary, principal)
    chat = _chat_threads_payload(
        summary,
        principal,
        executive_modes=executive_modes,
        board_portal=board_portal,
        publication=publication,
    )
    payload = {
        "status": "ok",
        "run_id": summary.get("run_id"),
        "findings": findings_payload,
        "finding_count": metrics["filtered_finding_count"],
        "domain_filter": str(domain_filter or "finance_integrity"),
        "domain_filters": [
            artifact_contracts_payload(item)
            for item in build_domain_filter_contracts(
                rows,
                active_filter_id=str(domain_filter or "finance_integrity"),
                base_route=(
                    "/public/runs/latest/findings"
                    if public_safe
                    else "/runs/latest/findings"
                ),
            )
        ],
        "locked_findings": metrics["locked_findings"],
        "total_recoverable_sar": metrics["total_recoverable_sar"],
        "filtered_total_recoverable_sar": metrics["filtered_total_recoverable_sar"],
        "requires_human_review": bool(summary.get("requires_human_review")),
        "approval_status": summary.get("approval_status"),
        "public_safe": public_safe,
        "metrics": metrics,
        "kpi_cards": _kpi_card_payloads(summary, rows, audit_summary),
        "trend": _trend_card_payload(summary, rows, audit_summary),
        "plan_health": _bounded_plan_health_payload(summary, rows, audit_summary),
        "publication": publication,
        "strategy_substrate": strategy_substrate,
        "drilldown": _drilldown_contract_payload(
            summary,
            principal,
            public_safe=public_safe,
            finding_rows=filtered_rows,
            domain_filters=[
                artifact_contracts_payload(item)
                for item in build_domain_filter_contracts(
                    rows,
                    active_filter_id=str(domain_filter or "finance_integrity"),
                    base_route=(
                        "/public/runs/latest/findings"
                        if public_safe
                        else "/runs/latest/findings"
                    ),
                )
            ],
            report_artifacts=list(
                (_summary_report_contracts(summary).get("reports") or [])
            ),
            board_portal=board_portal,
            executive_modes=executive_modes,
        ),
        "board_portal": board_portal,
        "executive_modes": executive_modes,
        "interaction_contracts": _interaction_contracts_payload(principal, public_safe=public_safe),
        "agents": agents,
        "agent_modules": agent_modules,
        "chat": chat,
        "role_actions": _role_actions_payload(summary, rows, audit_summary, principal),
        "drilldown": drilldown,
        "executive_diagnostics": _executive_diagnostics_payload(
            summary,
            principal=principal,
            board_portal=board_portal,
            executive_modes=executive_modes,
            drilldown=drilldown,
            strategy_substrate=strategy_substrate,
            agent_modules=agent_modules,
            audit_summary=audit_summary,
            finding_rows=rows,
        ),
    }
    if include_run_dir:
        payload["run_dir"] = summary.get("run_dir")
    return payload


def _anonymous_public_findings_payload(
    summary: dict[str, Any] | None,
    *,
    domain_filter: str | None = None,
    view_state: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    principal = {"role": "executive", "authenticated": False}
    if summary is None:
        return {
            "status": "missing",
            "run_id": ANONYMOUS_PUBLIC_RUN_ID,
            "findings": [],
            "finding_count": 0,
            "total_recoverable_sar": None,
            "filtered_total_recoverable_sar": None,
            "requires_human_review": False,
            "approval_status": None,
            "public_safe": True,
            "agent_modules": _agent_modules_payload(None, [], None, principal),
            "role_actions": _role_actions_payload(None, [], None, principal),
        }
    safe_summary = _anonymous_public_summary(summary)
    assert safe_summary is not None
    rows = _finding_rows_from_summary(summary)
    filtered_rows = _filter_finding_rows(rows, domain_filter)
    public_rows = _anonymous_public_finding_payloads(rows)
    filtered_public_rows = _anonymous_public_finding_payloads(filtered_rows)
    audit_summary = _latest_run_audit_summary_payload(safe_summary)
    metrics = _governed_metrics_payload(
        safe_summary,
        public_rows,
        audit_summary,
        filtered_rows=filtered_public_rows,
    )
    publication = _summary_publication_payload(
        safe_summary,
        principal_role="executive",
        public_safe=True,
    )
    board_portal = _board_portal_payload(
        safe_summary,
        principal_role="executive",
        public_safe=True,
        requested_state=(view_state or {}).get("board"),
    )
    strategy_substrate = _strategy_substrate_payload(
        safe_summary,
        filtered_public_rows,
        audit_summary,
        principal,
    )
    executive_modes = _executive_modes_payload(
        safe_summary,
        principal,
        strategy_substrate=strategy_substrate,
        board_portal=board_portal,
        publication=publication,
        view_state=view_state,
    )
    domain_filters = [
        artifact_contracts_payload(item)
        for item in build_domain_filter_contracts(
            rows,
            active_filter_id=str(domain_filter or "finance_integrity"),
            base_route="/public/runs/latest/findings",
        )
    ]
    drilldown = _drilldown_contract_payload(
        safe_summary,
        principal,
        public_safe=True,
        finding_rows=filtered_public_rows,
        domain_filters=domain_filters,
        report_artifacts=list((_summary_report_contracts(safe_summary).get("reports") or [])),
        board_portal=board_portal,
        executive_modes=executive_modes,
    )
    agent_modules = _agent_modules_payload(
        safe_summary,
        filtered_public_rows,
        audit_summary,
        principal,
    )
    agents = _agents_surface_payload(safe_summary, principal)
    chat = _chat_threads_payload(
        safe_summary,
        principal,
        executive_modes=executive_modes,
        board_portal=board_portal,
        publication=publication,
    )
    return _sanitize_anonymous_public_payload({
        "status": "ok",
        "run_id": safe_summary.get("run_id"),
        "findings": filtered_public_rows,
        "finding_count": metrics["filtered_finding_count"],
        "domain_filter": str(domain_filter or "finance_integrity"),
        "domain_filters": domain_filters,
        "locked_findings": metrics["locked_findings"],
        "total_recoverable_sar": metrics["total_recoverable_sar"],
        "filtered_total_recoverable_sar": metrics["filtered_total_recoverable_sar"],
        "requires_human_review": bool(summary.get("requires_human_review")),
        "approval_status": summary.get("approval_status"),
        "public_safe": True,
        "metrics": metrics,
        "kpi_cards": _kpi_card_payloads(safe_summary, filtered_public_rows, audit_summary),
        "trend": _trend_card_payload(safe_summary, filtered_public_rows, audit_summary),
        "plan_health": _bounded_plan_health_payload(safe_summary, filtered_public_rows, audit_summary),
        "publication": publication,
        "strategy_substrate": strategy_substrate,
        "drilldown": drilldown,
        "board_portal": board_portal,
        "executive_modes": executive_modes,
        "interaction_contracts": _interaction_contracts_payload(principal, public_safe=True),
        "agents": agents,
        "agent_modules": agent_modules,
        "chat": chat,
        "role_actions": _role_actions_payload(safe_summary, filtered_public_rows, audit_summary, principal),
        "executive_diagnostics": _executive_diagnostics_payload(
            safe_summary,
            principal=principal,
            board_portal=board_portal,
            executive_modes=executive_modes,
            drilldown=drilldown,
            strategy_substrate=strategy_substrate,
            agent_modules=agent_modules,
            audit_summary=audit_summary,
            finding_rows=filtered_public_rows,
        ),
    })


def _sanitize_public_evidence_preview(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "ok",
        "run_id": ANONYMOUS_PUBLIC_RUN_ID,
        "title": "Governed evidence preview",
        "pattern_label": str(payload.get("pattern_type") or "Governed signal").replace("_", " ").title(),
        "confidence": payload.get("confidence"),
        "source_path": None,
        "source_hash": None,
        "preview_kind": "text",
        "excerpt": PUBLIC_EVIDENCE_BOUNDARY_NOTE,
        "resolved_payload": {},
        "public_safe": True,
    }


def _public_evidence_preview_payload(
    *,
    run_id: str | None,
    finding_id: str | None,
    source_hash: str | None,
    locator: str | None,
) -> dict[str, Any]:
    summary = _latest_summary()
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No latest run is available for the public demo path.",
        )
    latest_run_id = str(summary.get("run_id") or "")
    if not latest_run_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The latest run does not have a public demo identity.",
        )
    if run_id and str(run_id) not in {latest_run_id, ANONYMOUS_PUBLIC_RUN_ID}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Only the latest public demo run is available on the anonymous surface.",
        )
    if not any([finding_id, source_hash, locator]):
        return {
            "status": "ok",
            "run_id": ANONYMOUS_PUBLIC_RUN_ID,
            "title": "Governed evidence preview",
            "pattern_label": "Governed Signal",
            "confidence": None,
            "source_path": None,
            "source_hash": None,
            "preview_kind": "text",
            "excerpt": PUBLIC_EVIDENCE_BOUNDARY_NOTE,
            "resolved_payload": {},
            "public_safe": True,
        }
    payload = state_store.evidence_preview_for_run(
        latest_run_id,
        finding_id=finding_id,
        source_hash=source_hash,
        locator=locator,
    )
    if payload.get("status") == "skipped":
        payload = _local_evidence_preview_for_run(
            latest_run_id,
            finding_id=finding_id,
            source_hash=source_hash,
            locator=locator,
        ) or payload
    if payload.get("status") == "missing":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=payload.get("reason", "Evidence preview was not found."),
        )
    if payload.get("status") == "skipped":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=payload.get("reason", "Evidence preview is unavailable."),
        )
    return _sanitize_public_evidence_preview(payload)


def _public_report_preview_payload(
    artifact_key: str | None = None,
    *,
    view_state: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    principal = {"role": "executive", "authenticated": False}
    summary = _latest_summary()
    if summary is None:
        return _sanitize_anonymous_public_payload({
            "status": "missing",
            "artifact_key": "executive_summary",
            "title": "Executive summary",
            "preview_kind": "text",
            "preview_text": "No latest governed run is available yet.",
            "available_artifacts": [],
            "publication": _summary_publication_payload(
                None,
                principal_role="executive",
                public_safe=True,
            ),
            "board_portal": _board_portal_payload(
                None,
                principal_role="executive",
                public_safe=True,
            ),
            "agent_modules": _agent_modules_payload(None, [], None, principal),
            "role_actions": _role_actions_payload(None, [], None, principal),
            "trend": _trend_card_payload(),
            "plan_health": _bounded_plan_health_payload(None, [], None),
            "public_safe": True,
        })
    summary = _anonymous_public_summary(summary)
    assert summary is not None
    audit = _latest_run_audit_summary_payload(summary)
    findings = _anonymous_public_finding_payloads(_finding_rows_from_summary(summary))
    challenged = len(audit.get("challenged_finding_ids") or [])
    publication = _summary_publication_payload(
        summary,
        principal_role="executive",
        public_safe=True,
    )
    available_artifacts = [
        {
            "artifact_key": key,
            "title": ARTIFACT_TITLES.get(key, key.replace("_", " ").title()),
        }
        for key in PUBLIC_REPORT_ARTIFACT_KEYS
        if isinstance(summary.get("artifacts"), dict) and summary["artifacts"].get(key)
    ]
    selected_key = artifact_key or (available_artifacts[0]["artifact_key"] if available_artifacts else "executive_summary")
    top_finding = findings[0] if findings else None
    preview_lines = [
        f"Latest governed run: {summary.get('run_id') or 'latest'}.",
        f"Recoverable value identified: {summary.get('total_recoverable_sar') or 0:,.2f} SAR.",
        f"Review posture: {summary.get('approval_status') or 'pending'} with {len(findings)} finding(s) and {challenged} challenged item(s).",
    ]
    if top_finding:
        preview_lines.append(
            f"Top case: {top_finding.get('title') or 'Governed signal'} worth {top_finding.get('recoverable_sar') or 0:,.2f} SAR."
        )
    citation_count = audit.get("citation_count")
    resolved_count = audit.get("resolved_count")
    if citation_count is not None or resolved_count is not None:
        preview_lines.append(
            f"Citation chain: {resolved_count if resolved_count is not None else '--'} resolved of {citation_count if citation_count is not None else '--'} total."
        )
    preview_lines.append(
        "Protected artifact bodies remain behind reviewer/operator authentication; this public preview is a synthesized board-safe status note."
    )
    board_portal = _board_portal_payload(
        summary,
        principal_role="executive",
        public_safe=True,
        requested_state=(view_state or {}).get("board"),
    )
    strategy_substrate = _strategy_substrate_payload(summary, findings, audit, principal)
    executive_modes = _executive_modes_payload(
        summary,
        principal,
        strategy_substrate=strategy_substrate,
        board_portal=board_portal,
        publication=publication,
        view_state=view_state,
    )
    drilldown = _drilldown_contract_payload(
        summary,
        principal,
        public_safe=True,
        finding_rows=findings,
        domain_filters=[],
        report_artifacts=list((_summary_report_contracts(summary).get("reports") or [])),
        board_portal=board_portal,
        executive_modes=executive_modes,
    )
    agent_modules = _agent_modules_payload(summary, findings, audit, principal)
    return _sanitize_anonymous_public_payload({
        "status": "ok",
        "run_id": summary.get("run_id"),
        "artifact_key": selected_key,
        "title": ARTIFACT_TITLES.get(selected_key, "Executive summary"),
        "preview_kind": "text",
        "preview_text": "\n\n".join(preview_lines),
        "available_artifacts": available_artifacts,
        "publication": publication,
        "board_portal": board_portal,
        "strategy_substrate": strategy_substrate,
        "executive_modes": executive_modes,
        "drilldown": drilldown,
        "interaction_contracts": _interaction_contracts_payload(principal, public_safe=True),
        "agent_modules": agent_modules,
        "role_actions": _role_actions_payload(summary, findings, audit, principal),
        "trend": _trend_card_payload(summary, findings, audit),
        "plan_health": _bounded_plan_health_payload(summary, findings, audit),
        "executive_diagnostics": _executive_diagnostics_payload(
            summary,
            principal=principal,
            board_portal=board_portal,
            executive_modes=executive_modes,
            drilldown=drilldown,
            strategy_substrate=strategy_substrate,
            agent_modules=agent_modules,
            audit_summary=audit,
            finding_rows=findings,
        ),
        "public_safe": True,
    })


@app.get("/runs/latest/findings")
def latest_run_findings(
    domain: str | None = None,
    persona: str | None = None,
    board: str | None = None,
    driver: str | None = None,
    company: str | None = None,
    portfolio: str | None = None,
    week: str | None = None,
    agent: str | None = None,
    principal: dict[str, Any] = require_role(*PRODUCT_READ_ROLES),
) -> dict[str, Any]:
    """Decision worklist for the latest run: one actionable row per finding
    (plain-language title, recoverable amount, owner, citation count, challenge
    and review status). Powers the business-user findings panel (fix-list 3)."""
    return _latest_run_findings_payload(
        _latest_summary(),
        include_run_dir=not principal_has_any_role(str(principal.get("role") or ""), "executive"),
        public_safe=principal_has_any_role(str(principal.get("role") or ""), "executive"),
        domain_filter=domain,
        view_state=_requested_executive_view_state(
            persona=persona,
            board=board,
            driver=driver,
            company=company,
            portfolio=portfolio,
            week=week,
            agent=agent,
        ),
    )


@app.get("/public/runs/latest/findings")
def public_latest_run_findings(
    domain: str | None = None,
    persona: str | None = None,
    board: str | None = None,
    driver: str | None = None,
    company: str | None = None,
    portfolio: str | None = None,
    week: str | None = None,
    agent: str | None = None,
) -> dict[str, Any]:
    return _latest_run_findings_payload(
        _latest_summary(),
        include_run_dir=False,
        public_safe=True,
        domain_filter=domain,
        view_state=_requested_executive_view_state(
            persona=persona,
            board=board,
            driver=driver,
            company=company,
            portfolio=portfolio,
            week=week,
            agent=agent,
        ),
    )


@app.get("/runs/latest/cases/{case_id}")
def latest_run_case(
    case_id: str,
    principal: dict[str, Any] = require_role(*PRODUCT_READ_ROLES),
) -> dict[str, Any]:
    return _latest_case_payload(
        _latest_summary(),
        case_id,
        public_safe=principal_has_any_role(str(principal.get("role") or ""), "executive"),
    )


@app.get("/public/runs/latest/cases/{case_id}")
def public_latest_run_case(case_id: str) -> dict[str, Any]:
    return _latest_case_payload(_latest_summary(), case_id, public_safe=True)


@app.get("/runs/history")
def runs_history(
    limit: int = 12,
    _: dict[str, Any] = require_role(*PRODUCT_READ_ROLES),
) -> dict[str, Any]:
    """Direction-of-travel history for a CEO view (fix-list item 8): leakage
    identified and recoverable across the most recent runs, oldest first.
    Additive and read-only - scans prior run_summary.json files."""
    bounded = max(1, min(int(limit or 12), 60))
    history = discover_run_history(limit=bounded)
    return {
        "status": "ok" if history else "empty",
        "count": len(history),
        "history": history,
    }


@app.get("/runs/latest/knowledge-graph")
def latest_run_knowledge_graph(
    view: str = KNOWLEDGE_GRAPH_DEFAULT_VIEW,
    expand: str | None = None,
    limit: int = KNOWLEDGE_GRAPH_EXPAND_LIMIT,
    _: dict[str, Any] = require_role(*INVESTIGATION_ROLES),
) -> dict[str, Any]:
    summary = _latest_summary()
    if summary is None:
        return {
            "status": "missing",
            "view": view,
            "reason": "No latest run is available.",
            "nodes": [],
            "edges": [],
            "meta": {},
        }
    return _knowledge_graph_payload(
        summary=summary,
        view=view,
        expand=expand,
        limit=limit,
    )


@app.get("/data/status")
def data_status(
    _: dict[str, Any] = require_role(*SYSTEM_READ_ROLES),
) -> dict[str, Any]:
    status_payload = data_management_status()
    latest_summary = _latest_summary() or {}
    run_id = status_payload.get("run_id")
    if run_id is None:
        run_id = latest_summary.get("run_id")
    status_payload["neo4j"] = graph_status_for_run(str(run_id) if run_id else None)
    status_payload["qdrant"] = vector_status_for_run(str(run_id) if run_id else None)
    workflow_items, workflow_store_status = _store_list_or_empty(
        state_store.list_pending_reviews()
    )
    recent_runs, recent_runs_store_status = _store_list_or_empty(
        state_store.list_recent_runs(limit=5)
    )
    summary_source = latest_summary if latest_summary else None
    principal = {"role": "tenant_admin", "authenticated": True}
    finding_rows = _finding_rows_from_summary(summary_source) if summary_source else []
    audit_summary = _latest_run_audit_summary_payload(summary_source) if summary_source else None
    metrics = _governed_metrics_payload(
        summary_source,
        finding_rows,
        audit_summary,
    )
    status_payload["tenant_context"] = _summary_tenant_context(
        summary_source,
        {"tenant_id": CONFIG.tenant_slug},
    )
    status_payload["metrics"] = metrics
    status_payload["workflow"] = {
        "store_status": workflow_store_status,
        "pending_reviews": len(workflow_items),
        "recent_runs": len(recent_runs),
        "latest": _record_workflow_summary(summary_source or {}),
    }
    status_payload["publication"] = _summary_publication_payload(
        summary_source,
        principal_role="tenant_admin",
    )
    status_payload["plan_health"] = _bounded_plan_health_payload(
        summary_source,
        finding_rows,
        audit_summary,
    )
    status_payload["trend"] = _trend_card_payload(
        summary_source,
        finding_rows,
        audit_summary,
    )
    status_payload["strategy_substrate"] = _strategy_substrate_payload(
        summary_source,
        finding_rows,
        audit_summary,
        {"role": "tenant_admin", "authenticated": True},
    )
    status_payload["agents"] = _agents_surface_payload(
        summary_source,
        {"role": "tenant_admin", "authenticated": True},
    )
    status_payload["board_portal"] = _board_portal_payload(
        summary_source,
        principal_role="tenant_admin",
    )
    status_payload["agent_modules"] = _agent_modules_payload(
        summary_source,
        finding_rows,
        audit_summary,
        principal,
    )
    status_payload["role_actions"] = _role_actions_payload(
        summary_source,
        finding_rows,
        audit_summary,
        principal,
    )
    status_payload["executive_modes"] = _executive_modes_payload(
        summary_source,
        principal,
        strategy_substrate=status_payload["strategy_substrate"],
        board_portal=status_payload["board_portal"],
        publication=status_payload["publication"],
        view_state=_requested_executive_view_state(),
    )
    status_payload["drilldown"] = _drilldown_contract_payload(
        summary_source,
        principal,
        public_safe=False,
        finding_rows=finding_rows,
        domain_filters=[],
        report_artifacts=list((_summary_report_contracts(summary_source).get("reports") or []))
        if summary_source
        else [],
        board_portal=status_payload["board_portal"],
        executive_modes=status_payload["executive_modes"],
    )
    status_payload["interaction_contracts"] = _interaction_contracts_payload(
        principal,
        public_safe=False,
    )
    status_payload["executive_diagnostics"] = _executive_diagnostics_payload(
        summary_source,
        principal=principal,
        board_portal=status_payload["board_portal"],
        executive_modes=status_payload["executive_modes"],
        drilldown=status_payload["drilldown"],
        strategy_substrate=status_payload["strategy_substrate"],
        agent_modules=status_payload["agent_modules"],
        audit_summary=audit_summary,
        finding_rows=finding_rows,
    )
    status_payload["tenant_admin_system"] = _tenant_admin_system_payload(
        summary_source,
        principal,
        data_status=status_payload,
        graph_status=status_payload["neo4j"],
        vector_status=status_payload["qdrant"],
        workflow_items=workflow_items,
        recent_runs=recent_runs,
    )
    status_payload["board_pack"] = status_payload["publication"].get("board_pack")
    status_payload["runtime_posture"] = {
        "run_store_status": recent_runs_store_status,
        "has_latest_run": bool(summary_source),
        "latest_run_id": (summary_source or {}).get("run_id"),
    }
    return status_payload


@app.get("/runs/latest/report-preview")
def latest_report_preview(
    artifact_key: str | None = None,
    persona: str | None = None,
    board: str | None = None,
    driver: str | None = None,
    company: str | None = None,
    portfolio: str | None = None,
    week: str | None = None,
    agent: str | None = None,
    principal: dict[str, Any] = require_role(*PRODUCT_READ_ROLES, "tenant_admin", "system"),
) -> dict[str, Any]:
    return _latest_report_preview_payload(
        principal,
        artifact_key,
        view_state=_requested_executive_view_state(
            persona=persona,
            board=board,
            driver=driver,
            company=company,
            portfolio=portfolio,
            week=week,
            agent=agent,
        ),
    )


@app.get("/data/vector-search")
def vector_search(
    query: str,
    run_id: str | None = None,
    limit: int = 5,
    point_type: str | None = None,
    pattern_type: str | None = None,
    vendor_id: str | None = None,
    vendor_name: str | None = None,
    confidence: str | None = None,
    source_path: str | None = None,
    finding_id: str | None = None,
    _: dict[str, Any] = require_role(*INVESTIGATION_ROLES),
) -> dict[str, Any]:
    if run_id is None:
        latest_summary = _latest_summary() or {}
        run_id = latest_summary.get("run_id")
    filters = {
        "point_type": point_type,
        "pattern_type": pattern_type,
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "confidence": confidence,
        "source_path": source_path,
        "finding_id": finding_id,
    }
    if not any(value for value in filters.values()):
        return search_run_vectors(str(run_id) if run_id else None, query, limit=limit)
    return search_run_vectors(
        str(run_id) if run_id else None,
        query,
        limit=limit,
        **filters,
    )


@app.get("/data/evidence-preview")
def evidence_preview(
    run_id: str,
    point_id: str | None = None,
    citation_id: str | None = None,
    finding_id: str | None = None,
    source_hash: str | None = None,
    locator: str | None = None,
    _: dict[str, Any] = require_role(*INVESTIGATION_ROLES),
) -> dict[str, Any]:
    payload = state_store.evidence_preview_for_run(
        run_id,
        citation_id=citation_id,
        finding_id=finding_id,
        source_hash=source_hash,
        locator=locator,
    )
    if payload.get("status") == "skipped":
        payload = _local_evidence_preview_for_run(
            run_id,
            citation_id=citation_id,
            finding_id=finding_id,
            source_hash=source_hash,
            locator=locator,
        ) or payload
    payload["point_id"] = point_id
    if payload.get("status") == "missing":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=payload.get("reason", "Evidence preview was not found."),
        )
    if payload.get("status") == "skipped":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=payload.get("reason", "Evidence preview is unavailable."),
        )
    return payload


@app.get("/public/data/evidence-preview")
def public_evidence_preview(
    run_id: str | None = None,
    finding_id: str | None = None,
    source_hash: str | None = None,
    locator: str | None = None,
) -> dict[str, Any]:
    return _public_evidence_preview_payload(
        run_id=run_id,
        finding_id=finding_id,
        source_hash=source_hash,
        locator=locator,
    )


@app.get("/public/runs/latest/report-preview")
def public_report_preview(
    artifact_key: str | None = None,
    persona: str | None = None,
    board: str | None = None,
    driver: str | None = None,
    company: str | None = None,
    portfolio: str | None = None,
    week: str | None = None,
    agent: str | None = None,
) -> dict[str, Any]:
    return _public_report_preview_payload(
        artifact_key,
        view_state=_requested_executive_view_state(
            persona=persona,
            board=board,
            driver=driver,
            company=company,
            portfolio=portfolio,
            week=week,
            agent=agent,
        ),
    )


# Cache reloaded Q&A contexts by a stable run key so repeated chat questions do
# not reload the dataset each time. Keyed by (dataset_root, run_mode).
_QA_CONTEXT_CACHE: dict[tuple[str, str, str], dict[str, Any]] = {}


def _load_kg_snapshot(summary: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    artifacts = summary.get("artifacts") or {}
    graph_path = artifacts.get(KNOWLEDGE_GRAPH_ARTIFACT_KEY) or artifacts.get("knowledge_graph")
    if not graph_path:
        return ([], [])
    path = Path(str(graph_path))
    if not path.exists():
        return ([], [])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ([], [])
    nodes = payload.get("nodes") if isinstance(payload, dict) else []
    edges = payload.get("edges") if isinstance(payload, dict) else []
    return (
        nodes if isinstance(nodes, list) else [],
        edges if isinstance(edges, list) else [],
    )


def _qa_summary_for_run(run_id: str | None) -> dict[str, Any]:
    if run_id:
        record = state_store.get_run_detail(run_id)
        if isinstance(record, dict) and record.get("status") == "missing":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run '{run_id}' was not found.",
            )
        if isinstance(record, dict) and record.get("status") == "skipped":
            latest = _latest_summary() or {}
            if str(latest.get("run_id") or "") == str(run_id):
                return latest
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Run lookup is unavailable because the state store is not configured. "
                    "Omit run_id to use the latest local run."
                ),
            )
        if not isinstance(record, dict):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run '{run_id}' was not found.",
            )
        summary = dict(record.get("summary_json") or {})
        if record.get("dataset_root") and not summary.get("dataset"):
            summary["dataset"] = record["dataset_root"]
        if record.get("run_dir") and not summary.get("run_dir"):
            summary["run_dir"] = record["run_dir"]
        summary["run_id"] = run_id
        return summary
    return _latest_summary() or {}


def _resolve_qa_context(run_id: str | None) -> dict[str, Any]:
    """Reload the bundle + findings for a run so Q&A can compute fresh answers.

    Uses the latest run when run_id is omitted. Returns a context dict with the
    bundle, findings, and the resolved run identifiers, or raises HTTPException
    with actionable guidance when no answerable run exists.
    """
    summary = _qa_summary_for_run(run_id)
    resolved_run_id = summary.get("run_id") or run_id
    dataset_root = summary.get("dataset") or summary.get("dataset_root")
    run_mode = str(summary.get("run_mode") or "full")
    if not dataset_root:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed run is available to answer questions yet. Start a run first.",
        )
    cache_run_key = str(resolved_run_id or dataset_root)
    cache_key = (cache_run_key, str(dataset_root), run_mode)
    cached = _QA_CONTEXT_CACHE.get(cache_key)
    if cached is None:
        dataset_path = Path(str(dataset_root))
        if not dataset_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"The run's source data is no longer available at {dataset_root}.",
            )
        try:
            bundle = load_dataset(dataset_path, strict=(run_mode != "partial"))
            findings = run_all_finance_skills(bundle)
            kg_nodes, kg_edges = _load_kg_snapshot(summary)
        except Exception as exc:  # pragma: no cover - defensive reload guard
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not reload the run's data for Q&A: {exc}",
            ) from exc
        cached = {
            "bundle": bundle,
            "findings": findings,
            "kg_nodes": kg_nodes,
            "kg_edges": kg_edges,
        }
        _QA_CONTEXT_CACHE[cache_key] = cached
    return {
        "bundle": cached["bundle"],
        "findings": cached["findings"],
        "kg_nodes": cached.get("kg_nodes") or [],
        "kg_edges": cached.get("kg_edges") or [],
        "summary": summary,
        "run_id": resolved_run_id,
        "run_mode": run_mode,
    }


def _resolve_public_assistant_context(
    run_id: str | None,
    *,
    persona: str | None = None,
    assistant_context: dict[str, Any] | None = None,
    driver_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if run_id and run_id != ANONYMOUS_PUBLIC_RUN_ID:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the latest public demo run is available on the anonymous executive surface.",
        )
    summary = _anonymous_public_summary(_latest_summary())
    if summary is None:
        summary = {
            "run_id": None,
            "run_mode": "no-run",
            "status": "missing",
            "public_safe": True,
        }
        resolved_run_id = None
        run_mode = "no-run"
    else:
        summary["public_safe"] = True
        resolved_run_id = ANONYMOUS_PUBLIC_RUN_ID
        run_mode = "public-safe"
    view_state = _assistant_requested_view_state(
        persona=persona,
        assistant_context=assistant_context,
        driver_context=driver_context,
    )
    public_context_packet = executive_public_assistant_packet(
        str(view_state.get("persona") or persona or "ceo")
    )
    public_context_packet["view_state"] = view_state
    summary["assistant_context_source"] = str(
        public_context_packet.get("packet_id") or "public-executive-context"
    )

    merged_packet = {
        **public_context_packet,
        "source": "server_public_executive_packet",
        "public_safe": True,
        "view_state": view_state,
    }
    synthetic_findings: list[dict[str, Any]] = []
    for index, item in enumerate(list(merged_packet.get("findings") or [])):
        title = str(item.get("title") or "")
        detail = str(item.get("detail") or item.get("impact") or "")
        synthetic_findings.append(
            {
                "finding_id": str(item.get("finding_id") or f"public-finding-{index + 1}"),
                "title": title,
                "detail": detail,
                "pattern_type": str(
                    item.get("pattern_type")
                    or ("finance_leakage" if "recoverable" in title.lower() else "public_signal")
                ),
                "recoverable_sar": float(item.get("recoverable_sar") or 0),
                "source_path": "public_packet://executive_surface/persona",
                "locator": f"public_context_packet.findings[{index}]",
                "citations": [_public_packet_citation(f"findings[{index}]", detail)],
            }
        )

    return {
        "bundle": merged_packet,
        "findings": synthetic_findings,
        "kg_nodes": list(merged_packet.get("kg_nodes") or []),
        "kg_edges": list(merged_packet.get("kg_edges") or []),
        "summary": summary,
        "run_id": resolved_run_id,
        "run_mode": run_mode,
        "public_context_packet": merged_packet,
    }


def _assistant_response_payload(
    *,
    response_mode: str,
    question: str,
    context: dict[str, Any],
    requested_mode: str,
    persona: str | None,
    orchestrated: Any,
    base_result: dict[str, Any] | None = None,
    scenario_result: dict[str, Any] | None = None,
    llm_status: dict[str, Any] | None = None,
    assistant_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trace = dict(getattr(orchestrated, "trace", {}) or {})
    if assistant_context:
        trace["entrypoint_context"] = dict(assistant_context)
    prompt_contracts = trace.get("prompts") or {}
    hallucination_risk = trace.get("hallucination_risk")
    merged_result = dict(base_result or {})
    payload = {
        "status": "ok",
        "run_id": context["run_id"],
        "run_mode": context["run_mode"],
        "mode": response_mode,
        "assistant_mode": orchestrated.mode,
        "requested_mode": requested_mode,
        "question": question,
        "persona": orchestrated.persona,
        "matched": orchestrated.matched,
        "answer": orchestrated.answer,
        "basis": orchestrated.basis,
        "why": orchestrated.basis,
        "citations": list(getattr(orchestrated, "citations", []) or []),
        "suggestions": list(getattr(orchestrated, "suggestions", []) or []),
        "trace": trace,
        "prompt_contracts": prompt_contracts,
        "audit_trail_id": trace.get("audit_trail_id"),
        "hallucination_risk": hallucination_risk,
        "risk_metadata": {
            "decision_mode": "llm" if getattr(orchestrated, "mode", "") == "llm" else "deterministic",
            "hallucination_risk": hallucination_risk,
            "traceable": bool((hallucination_risk or {}).get("traceable")),
        },
        "assistant_route": trace.get("deterministic_boundary", {}).get("selected_mode"),
        "orchestration_mode": orchestrated.mode,
        "llm_status": llm_status,
        "assistant_context": assistant_context or {},
    }
    if merged_result:
        payload.update(merged_result)
        if getattr(orchestrated, "matched", False):
            payload.update(
                {
                    "mode": response_mode,
                    "assistant_mode": orchestrated.mode,
                    "requested_mode": requested_mode,
                    "persona": orchestrated.persona,
                    "matched": orchestrated.matched,
                    "answer": orchestrated.answer,
                    "basis": orchestrated.basis,
                    "why": orchestrated.basis,
                    "citations": list(getattr(orchestrated, "citations", []) or []),
                    "suggestions": list(getattr(orchestrated, "suggestions", []) or []),
                    "trace": trace,
                    "prompt_contracts": prompt_contracts,
                    "audit_trail_id": trace.get("audit_trail_id"),
                    "hallucination_risk": hallucination_risk,
                    "risk_metadata": {
                        "decision_mode": "llm" if getattr(orchestrated, "mode", "") == "llm" else "deterministic",
                        "hallucination_risk": hallucination_risk,
                        "traceable": bool((hallucination_risk or {}).get("traceable")),
                    },
                    "assistant_route": trace.get("deterministic_boundary", {}).get("selected_mode"),
                    "orchestration_mode": orchestrated.mode,
                    "llm_status": llm_status,
                    "assistant_context": assistant_context or {},
                }
            )
    if scenario_result:
        payload.update(scenario_result)
        payload["citations"] = list(scenario_result.get("citations") or payload["citations"])
        payload["suggestions"] = list(scenario_result.get("suggestions") or payload["suggestions"])
        payload["hallucination_risk"] = scenario_result.get("hallucination_risk") or hallucination_risk
        payload["risk_metadata"]["hallucination_risk"] = payload["hallucination_risk"]
        payload["risk_metadata"]["traceable"] = bool((payload["hallucination_risk"] or {}).get("traceable"))
    payload["answer"] = _sanitize_assistant_visible_text(payload.get("answer"))
    return payload


def _sanitize_assistant_visible_text(value: Any) -> str:
    text = llm_qa._clean_visible_answer(value)
    return str(text or "").strip()


async def _llm_answer_question_async(*args: Any, **kwargs: Any) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    async with _LLM_PROVIDER_SEMAPHORE:
        return await loop.run_in_executor(
            _LLM_PROVIDER_EXECUTOR,
            lambda: llm_qa.answer_question(*args, **kwargs),
        )


async def _assistant_chat_response(
    request: AssistantChatRequest | QaRequest,
    *,
    public_safe: bool = False,
) -> dict[str, Any]:
    question = (request.question or "").strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ask a question, e.g. 'Simulate Digital Health flat by end of year'.",
        )
    mode = (request.mode or "auto").strip().lower()
    if mode not in {"auto", "deterministic", "llm"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assistant mode must be 'auto', 'deterministic', or 'llm'.",
        )
    persona = (request.persona or "ceo").strip().lower() or "ceo"
    request_context = dict(getattr(request, "context", None) or {})
    assistant_context = {
        **request_context,
        **dict(getattr(request, "assistant_context", None) or {}),
    }
    if getattr(request, "source", None):
        assistant_context.setdefault("source", str(request.source))
        assistant_context.setdefault("assistant_source", str(request.source))
    if getattr(request, "entrypoint", None):
        assistant_context.setdefault("entrypoint", str(request.entrypoint))
        assistant_context.setdefault("assistant_entrypoint", str(request.entrypoint))
    if persona and not assistant_context.get("active_persona"):
        assistant_context["active_persona"] = persona
    driver_context = request.driver_context or assistant_context.get("driver_context")
    if persona not in set(list_supported_personas()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported assistant persona '{persona}'.",
        )

    try:
        context = (
            _resolve_public_assistant_context(
                request.run_id,
                persona=persona,
                assistant_context=assistant_context,
                driver_context=driver_context,
            )
            if public_safe
            else _resolve_qa_context(request.run_id)
        )
    except HTTPException as exc:
        if persona and request.run_id is None and exc.status_code == status.HTTP_404_NOT_FOUND:
            context = {
                "bundle": None,
                "findings": [],
                "kg_nodes": [],
                "kg_edges": [],
                "summary": {
                    "run_id": None,
                    "run_mode": "no-run",
                    "status": "missing",
                    "public_safe": bool(public_safe),
                },
                "run_id": None,
                "run_mode": "no-run",
                "public_context_packet": {},
            }
        else:
            raise
    if public_safe:
        view_state = _assistant_requested_view_state(
            persona=persona,
            assistant_context=assistant_context,
            driver_context=driver_context,
        )
        context["public_context_packet"] = dict(context.get("public_context_packet") or {})
        context["public_context_packet"]["view_state"] = view_state
    llm_status = llm_qa.chat_status(CONFIG)

    def _public_safe_unmatched_result(reason: str | None = None) -> dict[str, Any]:
        basis = "Shared public executive packet is populated, but this prompt did not match a deterministic public-safe handler."
        answer = (
            "I can answer board-safe questions from the shared public packet, but this prompt did not match a deterministic public-safe handler. "
            "Ask about Tamween recovery, SAR 8.6M evidence, gap widening, e-Pharmacy detail, full-year risk, FX hedge impact, or Digital Health."
        )
        if reason:
            basis = f"{basis} LLM fallback is unavailable: {reason}"
            answer = f"{answer} AI fallback is unavailable right now: {reason}"
        return {
            "matched": False,
            "answer": answer,
            "citations": [_public_packet_citation("facts[0]", "Shared public executive packet")],
            "suggestions": [
                'Project the impact of "Tamween audit: SAR 1.2M recoverable" on the current plan and what I should prepare for the board.',
                "Show evidence for SAR 8.6M recoverable",
                "Why is the gap widening?",
                "Show e-Pharmacy detail",
                "Risk to full-year plan?",
                "Project FX hedge impact on EBITDA margin",
            ],
            "basis": basis,
        }
    orchestrator = get_orchestrator()
    findings_payload = [
        finding.__dict__ if hasattr(finding, "__dict__") else finding
        for finding in context["findings"]
    ]

    scenario_result = None
    if mode in {"auto", "deterministic"}:
        parsed = parse_scenario(
            question,
            {
                "bundle": context["bundle"],
                "findings": findings_payload,
                "kg_nodes": context.get("kg_nodes") or [],
                "kg_edges": context.get("kg_edges") or [],
                "public_context_packet": context.get("public_context_packet") or {},
                "summary": context["summary"],
                "run_id": context["run_id"],
                "run_mode": context["run_mode"],
                "persona": persona,
            },
        )
        scenario_result = parsed.as_dict()
        if parsed.matched:
            orchestrated = orchestrator.process(
                question,
                persona=persona,
                scenario_result=scenario_result,
                driver_context=driver_context,
            )
            return _assistant_response_payload(
                response_mode="deterministic",
                question=question,
                context=context,
                requested_mode=mode,
                persona=persona,
                orchestrated=orchestrated,
                scenario_result=scenario_result,
                llm_status=llm_status,
                assistant_context=assistant_context,
            )

    if public_safe and context.get("public_context_packet"):
        if mode == "llm" and not llm_status["enabled"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=llm_status["reason"],
            )
        if mode != "deterministic" and llm_status["enabled"]:
            try:
                result = await _llm_answer_question_async(
                    question,
                    bundle=context["bundle"],
                    findings=context["findings"],
                    summary=context["summary"],
                    config=CONFIG,
                    public_context_packet=context.get("public_context_packet") or {},
                    persona=persona,
                )
            except RuntimeError as exc:
                if mode == "llm":
                    transport_status = llm_qa.provider_transport_payload(exc)
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail={
                            "message": str(exc),
                            "transport": transport_status,
                        } if transport_status else str(exc),
                    ) from exc
                public_safe_result = _public_safe_unmatched_result(str(exc))
                failure_transport = dict(llm_qa.provider_transport_payload(exc) or {})
                if failure_transport:
                    failure_transport["fallback_used"] = True
                failure_status = {
                    **llm_status,
                    "transport": failure_transport,
                }
                orchestrated = orchestrator.process(
                    question,
                    persona=persona,
                    qa_result={
                        **public_safe_result,
                        "assistant_mode": "qa_engine",
                        "_orchestrator_force_answer": True,
                    },
                    driver_context=request.driver_context,
                )
                payload = _assistant_response_payload(
                    response_mode="deterministic",
                    question=question,
                    context=context,
                    requested_mode=mode,
                    persona=persona,
                    orchestrated=orchestrated,
                    base_result=public_safe_result,
                    llm_status=failure_status,
                    assistant_context=assistant_context,
                )
                payload["llm_fallback_attempted"] = True
                payload["llm_error"] = str(exc)
                payload["trace"]["llm_transport_failed"] = True
                return payload
            orchestrated = orchestrator.process(
                question,
                persona=persona,
                llm_result=result,
                driver_context=driver_context,
            )
            payload = _assistant_response_payload(
                response_mode="llm",
                question=question,
                context=context,
                requested_mode=mode,
                persona=persona,
                orchestrated=orchestrated,
                base_result=result,
                llm_status=result.get("llm_status") or llm_status,
                assistant_context=assistant_context,
            )
            payload["mode"] = "llm"
            payload["llm_fallback_attempted"] = True
            return payload

        public_safe_result = _public_safe_unmatched_result(None if mode == "deterministic" else llm_status.get("reason"))
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            qa_result={
                **public_safe_result,
                "assistant_mode": "qa_engine",
                "_orchestrator_force_answer": True,
            },
            driver_context=request.driver_context,
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=public_safe_result,
            llm_status=llm_status,
            assistant_context=assistant_context,
        )
        payload["llm_fallback_attempted"] = False
        return payload

    if context["bundle"] is None:
        no_run_result = {
            "matched": False,
            "answer": "No completed governed run is available yet. I can still handle supported scenario prompts, or you can start a run for ledger-backed questions.",
            "citations": [],
            "suggestions": list(SCENARIO_SUGGESTIONS),
            "basis": "No completed governed run is available for deterministic ledger-backed Q&A.",
        }
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            qa_result={
                **no_run_result,
                "assistant_mode": "qa_engine",
                "_orchestrator_force_answer": True,
            },
            driver_context=driver_context,
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=no_run_result,
            llm_status=llm_status,
            assistant_context=assistant_context,
        )
        payload["llm_fallback_attempted"] = False
        return payload

    deterministic_result = qa_engine.answer_question(
        question,
        bundle=context["bundle"],
        findings=context["findings"],
    )
    if mode == "deterministic" or deterministic_result.get("matched") is not False:
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            qa_result={**deterministic_result, "assistant_mode": "qa_engine", "_orchestrator_force_answer": True},
            driver_context=driver_context,
        )
        return _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=deterministic_result,
            llm_status=llm_status,
            assistant_context=assistant_context,
        )

    if not llm_status["enabled"]:
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            qa_result=deterministic_result,
            driver_context=driver_context,
        )
        if mode == "llm":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=llm_status["reason"],
            )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=deterministic_result,
            llm_status=llm_status,
        )
        payload["llm_fallback_attempted"] = False
        return payload

    result = await _llm_answer_question_async(
        question,
        bundle=context["bundle"],
        findings=context["findings"],
        summary=context["summary"],
        config=CONFIG,
    )
    orchestrated = orchestrator.process(
        question,
        persona=persona,
        llm_result=result,
        driver_context=driver_context,
    )
    payload = _assistant_response_payload(
        response_mode="llm",
        question=question,
        context=context,
        requested_mode=mode,
        persona=persona,
        orchestrated=orchestrated,
        base_result=result,
        llm_status=llm_status,
        assistant_context=assistant_context,
    )
    payload["mode"] = "llm"
    payload["llm_fallback_attempted"] = True
    return payload


@app.post("/qa")
def data_qa(
    request: QaRequest,
    _: dict[str, Any] = require_role(*PRODUCT_READ_ROLES),
) -> dict[str, Any]:
    question = (request.question or "").strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ask a question, e.g. 'What is the total amount of invoices?'.",
        )
    mode = (request.mode or "auto").strip().lower()
    persona = (request.persona or "").strip().lower() or None
    request_context = request.context or {}
    if persona is None:
        persona = (
            str(request_context.get("active_persona") or request_context.get("persona") or "").strip().lower()
            or None
        )
    if persona is None and str(_.get("role") or "") == "executive":
        persona = "ceo"
    if persona and persona not in set(list_supported_personas()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported assistant persona '{persona}'.",
        )
    driver_context = request.driver_context or request_context.get("driver_context") or {}
    trace_id = (request.trace_id or "").strip() or uuid4().hex
    if mode not in {"auto", "deterministic", "llm"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Q&A mode must be 'auto', 'deterministic', or 'llm'.",
        )
    llm_status = llm_qa.chat_status(CONFIG)
    if mode == "llm" and not llm_status["enabled"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=llm_status["reason"],
        )
    try:
        context = _resolve_qa_context(request.run_id)
    except HTTPException as exc:
        if not (persona and request.run_id is None and exc.status_code == status.HTTP_404_NOT_FOUND):
            raise
        context = {
            "bundle": None,
            "findings": [],
            "kg_nodes": [],
            "kg_edges": [],
            "summary": {
                "run_id": None,
                "run_mode": "no-run",
                "status": "missing",
            },
            "run_id": None,
            "run_mode": "no-run",
        }
    orchestrator = get_orchestrator()

    def _risk_payload(response_mode: str, basis: str, matched: bool, status_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if response_mode == "llm":
            provider = (status_payload or {}).get("provider") or "model_provider"
            model = (status_payload or {}).get("model") or "configured-model"
            return {
                "level": "high",
                "score": 0.6,
                "traceable": True,
                "traceability_gap": "Narrative wording is model-generated; verify it against cited evidence before operational use.",
                "verification_path": basis,
                "factors": [
                    {"name": "llm_generation", "detail": f"Answer composed by {provider}:{model} from supplied evidence."},
                    {"name": "evidence_grounding", "detail": "Citations constrain the narrative but do not make it authoritative."},
                ],
                "mitigations": [
                    "Check cited evidence before acting on the answer.",
                    "Prefer deterministic answers whenever the question is covered by governed calculations.",
                ],
            }
        return {
            "level": "none",
            "score": 0.0,
            "traceable": True,
            "traceability_gap": None,
            "verification_path": basis,
            "factors": [
                {"name": "deterministic_orchestrator", "detail": "Answer came from persona rules, scenario parsing, or deterministic QA over the governed run."},
            ],
            "mitigations": [] if matched else ["Refine the question or use one of the suggested prompts."],
        }

    def _compose_response(
        *,
        response_mode: str,
        base_payload: dict[str, Any],
        orchestrated_payload: Any,
        extra_trace: dict[str, Any],
        extra_payload: dict[str, Any] | None = None,
        status_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trace = {
            **orchestrated_payload.trace,
            "trace_id": trace_id,
            **extra_trace,
        }
        prompt_contracts = trace.get("prompts") or {}
        hallucination_risk = trace.get("hallucination_risk") or _risk_payload(
            response_mode,
            orchestrated_payload.basis,
            orchestrated_payload.matched,
            status_payload,
        )
        payload = {
            "status": "ok",
            "run_id": context["run_id"],
            "run_mode": context["run_mode"],
            "mode": response_mode,
            "assistant_mode": orchestrated_payload.mode,
            "requested_mode": mode,
            "question": question,
            "trace_id": trace_id,
            **base_payload,
            "persona": orchestrated_payload.persona,
            "matched": orchestrated_payload.matched,
            "answer": orchestrated_payload.answer,
            "basis": orchestrated_payload.basis,
            "why": orchestrated_payload.basis,
            "citations": orchestrated_payload.citations,
            "suggestions": orchestrated_payload.suggestions,
            "trace": trace,
            "prompt_contracts": prompt_contracts,
            "audit_trail_id": trace.get("audit_trail_id"),
            "hallucination_risk": hallucination_risk,
            "risk_metadata": {
                "decision_mode": "llm" if response_mode == "llm" else "deterministic",
                "hallucination_risk": hallucination_risk,
                "traceable": bool(hallucination_risk.get("traceable")),
            },
            "assistant_route": trace.get("route"),
            "orchestration_mode": orchestrated_payload.mode,
        }
        if extra_payload:
            payload.update(extra_payload)
        if status_payload is not None:
            payload["llm_status"] = status_payload
        return payload

    findings_payload = [
        finding.__dict__ if hasattr(finding, "__dict__") else finding
        for finding in context["findings"]
    ]

    if mode == "llm":
        if context["bundle"] is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No completed run is available to answer questions yet. Start a run first.",
            )
        try:
            result = llm_qa.answer_question(
                question,
                bundle=context["bundle"],
                findings=context["findings"],
                summary=context["summary"],
                config=CONFIG,
            )
        except RuntimeError as exc:
            transport_status = llm_qa.provider_transport_payload(exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "message": str(exc),
                    "transport": transport_status,
                } if transport_status else str(exc),
            ) from exc
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            llm_result={**result, "assistant_mode": "llm"},
            driver_context=driver_context,
        )
        return _compose_response(
            response_mode="llm",
            base_payload={**result, "deterministic_matched": False},
            orchestrated_payload=orchestrated,
            extra_trace={
                "route": "llm_evidence",
                "knowledge_id": request.knowledge_id,
            },
            status_payload=result.get("llm_status"),
        )

    scenario_result = None
    if mode in {"auto", "deterministic"}:
        parsed = parse_scenario(
            question,
            {
                "bundle": context["bundle"],
                "findings": findings_payload,
                "kg_nodes": context.get("kg_nodes") or [],
                "kg_edges": context.get("kg_edges") or [],
                "summary": context.get("summary") or {},
                "run_id": context["run_id"],
                "run_mode": context["run_mode"],
                "persona": persona,
                "knowledge_id": request.knowledge_id,
            },
        )
        scenario_result = parsed.as_dict()
        if parsed.matched:
            orchestrated = orchestrator.process(
                question,
                persona=persona,
                scenario_result=scenario_result,
                driver_context=driver_context,
            )
            return _compose_response(
                response_mode="deterministic",
                base_payload=scenario_result,
                orchestrated_payload=orchestrated,
                extra_trace={
                    "route": "scenario_deterministic",
                    "scenario_id": scenario_result.get("scenario_id"),
                    "knowledge_id": request.knowledge_id,
                },
                extra_payload={
                    "hallucination_risk": scenario_result.get("hallucination_risk"),
                },
            )

    deterministic_result = None
    if context["bundle"] is not None and mode in {"auto", "deterministic"}:
        deterministic_result = qa_engine.answer_question(
            question, bundle=context["bundle"], findings=context["findings"]
        )
        if mode == "deterministic" or deterministic_result.get("matched") is not False:
            orchestrated = orchestrator.process(
                question,
                persona=persona,
                qa_result={**deterministic_result, "assistant_mode": "qa_engine"},
                driver_context=driver_context,
            )
            return _compose_response(
                response_mode="deterministic",
                base_payload=deterministic_result,
                orchestrated_payload=orchestrated,
                extra_trace={
                    "route": "deterministic_qa",
                    "intent": deterministic_result.get("intent"),
                    "knowledge_id": request.knowledge_id,
                },
            )

    if not llm_status["enabled"]:
        if context["bundle"] is None:
            return _compose_response(
                response_mode="deterministic",
                base_payload={
                    "matched": False,
                    "answer": "I don't have a deterministic answer for that yet. Try one of these:",
                    "citations": [],
                    "suggestions": list(SCENARIO_SUGGESTIONS),
                },
                orchestrated_payload=orchestrator.process(
                    question,
                    persona=persona,
                    qa_result={
                        "matched": False,
                        "answer": "I don't have a deterministic answer for that yet. Try one of these:",
                        "citations": [],
                        "suggestions": list(SCENARIO_SUGGESTIONS),
                    },
                    driver_context=driver_context,
                ),
                extra_trace={
                    "route": "deterministic_unmatched",
                    "knowledge_id": request.knowledge_id,
                },
                extra_payload={"llm_fallback_attempted": False},
                status_payload=llm_status,
            )
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            qa_result={**deterministic_result, "assistant_mode": "qa_engine"},
            driver_context=driver_context,
        )
        return _compose_response(
            response_mode="deterministic",
            base_payload=deterministic_result,
            orchestrated_payload=orchestrated,
            extra_trace={
                "route": "deterministic_unmatched",
                "intent": deterministic_result.get("intent"),
                "knowledge_id": request.knowledge_id,
            },
            extra_payload={"llm_fallback_attempted": False},
            status_payload=llm_status,
        )

    if context["bundle"] is None:
        return _compose_response(
            response_mode="deterministic",
            base_payload={
                "matched": False,
                "answer": "I don't have a deterministic answer for that yet. Try one of these:",
                "citations": [],
                "suggestions": list(SCENARIO_SUGGESTIONS),
            },
            orchestrated_payload=orchestrator.process(
                question,
                persona=persona,
                qa_result={
                    "matched": False,
                    "answer": "I don't have a deterministic answer for that yet. Try one of these:",
                    "citations": [],
                    "suggestions": list(SCENARIO_SUGGESTIONS),
                },
                driver_context=driver_context,
            ),
            extra_trace={
                "route": "deterministic_unmatched",
                "knowledge_id": request.knowledge_id,
            },
            status_payload=llm_status,
        )

    try:
        result = llm_qa.answer_question(
            question,
            bundle=context["bundle"],
            findings=context["findings"],
            summary=context["summary"],
            config=CONFIG,
        )
    except RuntimeError as exc:
        if mode == "llm":
            transport_status = llm_qa.provider_transport_payload(exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "message": str(exc),
                    "transport": transport_status,
                } if transport_status else str(exc),
            ) from exc
        assert deterministic_result is not None
        failure_transport = dict(llm_qa.provider_transport_payload(exc) or {})
        if failure_transport:
            failure_transport["fallback_used"] = True
        llm_failure_status = {
            **llm_status,
            "transport": failure_transport,
        }
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            qa_result={**deterministic_result, "assistant_mode": "qa_engine"},
            driver_context=driver_context,
        )
        return _compose_response(
            response_mode="deterministic",
            base_payload=deterministic_result,
            orchestrated_payload=orchestrated,
            extra_trace={
                "route": "deterministic_after_llm_error",
                "intent": deterministic_result.get("intent"),
                "knowledge_id": request.knowledge_id,
                "llm_transport_failed": True,
            },
            extra_payload={"llm_fallback_attempted": True, "llm_error": str(exc)},
            status_payload=llm_failure_status,
        )
    orchestrated = orchestrator.process(
        question,
        persona=persona,
        llm_result={**result, "assistant_mode": "llm"},
        driver_context=driver_context,
    )
    return _compose_response(
        response_mode="llm",
        base_payload={**result, "deterministic_matched": False if deterministic_result is not None else None},
        orchestrated_payload=orchestrated,
        extra_trace={
            "route": "llm_evidence",
            "knowledge_id": request.knowledge_id,
        },
        status_payload=result.get("llm_status"),
    )


@app.post("/assistant/chat")
async def assistant_chat(
    request: AssistantChatRequest,
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> dict[str, Any]:
    role = str(principal.get("role") or "anonymous")
    authenticated = bool(principal.get("authenticated"))
    persona = (request.persona or "ceo").strip().lower() or "ceo"
    public_safe = _principal_prefers_public_safe_surface(principal)

    if not authenticated:
        if persona not in EXECUTIVE_PERSONA_IDS:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="A valid identity token is required.",
            )
        return await _assistant_chat_response(request, public_safe=True)

    if not principal_has_any_role(role, *PRODUCT_READ_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This identity is not permitted for this endpoint.",
        )

    return await _assistant_chat_response(request, public_safe=bool(public_safe and persona in EXECUTIVE_PERSONA_IDS))


@app.post("/inputs/prepare")
def prepare_inputs(
    _: dict[str, Any] = require_role("operator"),
) -> dict[str, str]:
    agent_input, evaluation = prepare_agent_input()
    return {"agent_input": str(agent_input), "evaluation": str(evaluation)}
