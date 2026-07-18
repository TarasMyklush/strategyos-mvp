from __future__ import annotations

import asyncio
import dataclasses
from functools import lru_cache
import html
import hashlib
import json
import logging
import re
import socket
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, closing
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlparse
from uuid import UUID, uuid4

try:
    from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
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
    executive_board_design,
    executive_persona_design,
)
from .agent_execution_log import build_execution_log
from .executive_presentation import build_executive_presentation
from .executive_read_model import build_executive_read_model
from .assistants import get_orchestrator, list_supported_personas
from .assistants.graph_retrieval import route_graph_question
from .ingestion import load_dataset
from .neo4j_store import check_neo4j_ready, graph_status_for_run
from .ocr import runtime_dependency_status
from .prepare_inputs import prepare_agent_input
from .cost_levers import derive_cost_levers
from .scenario_parser import SCENARIO_SUGGESTIONS, has_scenario_intent as scenario_has_intent, parse_scenario
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
from .twins.persona import TWIN_CATALOG
from .twins.store import build_app_repositories
from .twins.tools import reconcile_message_routing_audit
ANONYMOUS_PUBLIC_RUN_ID = "latest-public"
logger = logging.getLogger(__name__)
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
    "_backing_run_id",
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


class FindingDirectiveRequest(BaseModel):
    finding_id: str
    note: str | None = None


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
    history: list[dict[str, Any]] | None = None


from .twins.api import (
    require_twin_dashboard_access,
    router as twin_router,
    twin_operational_health_payload,
)
from .agent_runtime.api import router as agent_runtime_router

@asynccontextmanager
async def _app_lifespan(_: FastAPI):
    """Reconcile durable Twin audit indexes before serving executive reads."""
    try:
        result = reconcile_message_routing_audit()
        if result["created"]:
            logger.info(
                "Reconciled %s legacy Digital Twin routing audit event(s)",
                result["created"],
            )
    except Exception:
        # Audit reconciliation must fail closed in the UI contract without
        # preventing the rest of the governed application from starting.
        logger.exception("Digital Twin routing audit reconciliation failed")
    yield


app = FastAPI(
    title="StrategyOS MVP API",
    version="0.1.0",
    # A hosted login-only surface must not publish an API catalogue to
    # unauthenticated visitors. Local development keeps the normal docs.
    docs_url=None if CONFIG.login_required else "/docs",
    redoc_url=None if CONFIG.login_required else "/redoc",
    openapi_url=None if CONFIG.login_required else "/openapi.json",
    lifespan=_app_lifespan,
)


@app.middleware("http")
async def prevent_assistant_response_caching(request: Request, call_next: Any) -> Any:
    """A question is part of the answer contract; never reuse a prior reply."""
    response = await call_next(request)
    if request.url.path in {"/assistant/chat", "/qa"}:
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


STATIC_DIR = Path(__file__).with_name("static")
TWINS_STATIC_DIR = Path(__file__).parent / "twins" / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_EXECUTIVE_ASSET_REV_FILES = (
    "executive.css",
    "executive.js",
)


def _asset_revision(*relative_paths: str) -> str:
    digest = hashlib.sha1()
    for relative_path in relative_paths:
        path = STATIC_DIR / relative_path
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def _executive_asset_revision() -> str:
    return _asset_revision(*_EXECUTIVE_ASSET_REV_FILES)
app.include_router(twin_router)
app.include_router(agent_runtime_router)

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
EDGE_LABEL_DISPLAY_MAP: dict[str, str] = {
    "SUPPORTED_BY": "Supported by evidence",
    "INVOLVES_VENDOR": "Involves vendor",
    "HAS_CONTRACT": "Under contract",
    "SAME_BANK_ACCOUNT_AS": "Shared bank account",
    "SAME_TAX_ID_AS": "Shared tax ID",
    "ISSUED_INVOICE": "Issued invoice",
    "ISSUED_PO": "Issued purchase order",
    "MATCHES_PO": "Matches purchase order",
}
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
    if "authenticated" in (principal or {}):
        authenticated = bool((principal or {}).get("authenticated"))
    else:
        authenticated = not bool((principal or {}).get("auth_disabled")) and role not in {
            "anonymous",
            "public",
        }
    return (not authenticated) and not principal_has_any_role(role, *PRODUCT_READ_ROLES)


def _data_management_status_for_run(run_id: str | None = None) -> dict[str, Any]:
    if run_id is not None:
        try:
            run_id = str(UUID(str(run_id)))
        except (TypeError, ValueError):
            return _executive_safe_data_management_status(
                {"status": "invalid_run_id"}
            )
    try:
        status = data_management_status(run_id)
    except TypeError:
        status = data_management_status()
    return _executive_safe_data_management_status(status)


def _executive_safe_data_management_status(status: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(status or {})
    raw_status = str(payload.get("status") or "unavailable").strip().lower()
    if raw_status in {"ready", "ok", "persisted"}:
        payload["status"] = "ready"
        payload["reason"] = payload.get("reason") or "Governed data is backed by the configured state store."
        return payload
    if raw_status in {"skipped", "not_configured"}:
        return {
            "status": "not_configured",
            "reason": "Database backing is not configured for this environment.",
        }
    if raw_status in {"missing", "no_backing_record"}:
        return {
            "status": "no_backing_record",
            "reason": "No database backing record is available for the latest governed run.",
        }
    if raw_status in {"invalid_run_id"}:
        return {
            "status": "unavailable",
            "reason": "Database backing status is unavailable for this public run reference.",
        }
    return {
        "status": "unavailable",
        "reason": "Database backing status is temporarily unavailable.",
    }


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
    assistant_public_context = _build_public_safe_assistant_packet(
        summary,
        persona_id=public_packet_persona,
        finding_rows=rows,
        audit_summary=audit_summary,
        publication=publication,
        board_portal=board_portal,
        strategy_substrate=strategy_substrate,
        agent_modules=agent_modules,
    )
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
    if payload.get("run_id"):
        payload["_backing_run_id"] = payload.get("run_id")
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


def _assistant_metric_label(card_id: str, value: Any) -> str:
    if card_id == "recoverable_value":
        return _format_sar_brief(value)
    if card_id == "citation_resolution" and isinstance(value, dict):
        return _format_ratio_display(value.get("resolved"), value.get("total"))
    if isinstance(value, float):
        return f"{value:.2f}"
    if value is None:
        return "--"
    return str(value)


def _ceo_kpi_knowledge_graph(
    kpi_cards: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Project the CEO graph from the same contract as the four KPI cards.

    The operational Neo4j projection remains useful for finding, vendor and
    invoice investigations.  It is not, however, the source of the CEO finance
    cards.  This graph deliberately starts from those cards and exposes their
    governed calculation components, comparisons, gaps and source extracts so
    the visual surface cannot drift into a technical architecture diagram.
    """

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    edge_ids: set[tuple[str, str, str]] = set()

    def add_node(node: dict[str, Any]) -> None:
        node_id = str(node.get("id") or "").strip()
        if not node_id or node_id in node_ids:
            return
        node_ids.add(node_id)
        nodes.append(node)

    def add_edge(source: str, target: str, label: str) -> None:
        key = (source, target, label)
        if not source or not target or key in edge_ids:
            return
        edge_ids.add(key)
        edges.append({"source": source, "target": target, "label": label})

    for card in list(kpi_cards or [])[:4]:
        key = str(card.get("driver_key") or card.get("key") or "").strip()
        if not key:
            continue
        label = str(card.get("label") or key.replace("_", " ").title())
        metric = str(card.get("metric") or card.get("value") or "Not available")
        brief = card.get("executive_brief") if isinstance(card.get("executive_brief"), dict) else {}
        readout = str(brief.get("readout") or card.get("detail") or "")
        comparison = brief.get("comparison") if isinstance(brief.get("comparison"), dict) else {}
        strategic_reference = brief.get("strategic_reference") if isinstance(brief.get("strategic_reference"), dict) else {}
        coverage = brief.get("coverage") if isinstance(brief.get("coverage"), dict) else {}
        audit = brief.get("audit") if isinstance(brief.get("audit"), dict) else {}
        kpi_id = f"kpi:{key}"
        detail_parts = [metric, readout]
        if comparison:
            detail_parts.append(
                f"{comparison.get('label') or 'Comparator'}: {comparison.get('value') or 'Not supplied'}."
            )
        if coverage:
            detail_parts.append(
                f"Data coverage: {coverage.get('value') or 'Unavailable'}. {coverage.get('note') or ''}"
            )
        add_node(
            {
                "id": kpi_id,
                "label": label,
                "short_label": f"{label} · {metric}",
                "category": "KPI",
                "detail": " ".join(part.strip() for part in detail_parts if part).strip(),
                "hermes_prompt": str(
                    brief.get("decision_question")
                    or f"Explain {label}, its calculation, business drivers and evidence gaps."
                ),
                "properties": {
                    "kpi_key": key,
                    "metric": metric,
                    "availability": card.get("availability"),
                    "formula": card.get("formula"),
                },
                "r": 14,
            }
        )
        focus = [kpi_id]

        # Make the structural relationships between the four headline KPIs
        # explicit.  EBITDA margin is calculated from Revenue and Operating
        # cost rather than represented as an isolated technical node.
        if key == "ebitda_margin":
            add_edge("kpi:revenue", kpi_id, "INPUT_TO")
            add_edge("kpi:operating_cost", kpi_id, "INPUT_TO")
            focus.extend(["kpi:revenue", "kpi:operating_cost"])

        calculation = brief.get("calculation") if isinstance(brief.get("calculation"), dict) else {}
        component_labels: set[str] = set()
        for index, step in enumerate(list(calculation.get("steps") or [])[:8], start=1):
            if not isinstance(step, dict):
                continue
            step_label = str(step.get("label") or f"Calculation component {index}")
            component_labels.add(step_label.strip().lower())
            step_value = str(step.get("value") or "Not supplied")
            component_id = f"component:{key}:{index}"
            add_node(
                {
                    "id": component_id,
                    "label": step_label,
                    "short_label": f"{step_label} · {step_value}",
                    "category": "business_driver",
                    "detail": f"{step_label}: {step_value}. This contributes to {label}.",
                    "hermes_prompt": f"Explain how {step_label} contributes to {label} in business terms.",
                    "properties": {"value": step_value, "kpi_key": key},
                    "r": 9,
                }
            )
            add_edge(component_id, kpi_id, "COMPOSES")
            focus.append(component_id)

        for index, driver in enumerate(list(brief.get("drivers") or [])[:8], start=1):
            if not isinstance(driver, dict):
                continue
            driver_label = str(driver.get("label") or f"Business driver {index}")
            if driver_label.strip().lower() in component_labels:
                continue
            driver_value = str(driver.get("value") or "Not supplied")
            driver_id = f"driver:{key}:{index}"
            add_node(
                {
                    "id": driver_id,
                    "label": driver_label,
                    "short_label": f"{driver_label} · {driver_value}",
                    "category": "business_driver",
                    "detail": f"{driver_label}: {driver_value}. Shown in the CEO explanation of {label}.",
                    "hermes_prompt": f"Explain the contribution of {driver_label} to {label} using the current reporting information.",
                    "properties": {
                        "value": driver_value,
                        "share_pct": driver.get("share_pct"),
                        "kpi_key": key,
                    },
                    "r": 8,
                }
            )
            add_edge(driver_id, kpi_id, "DRIVES")
            focus.append(driver_id)

        if comparison:
            comparator_id = f"comparator:{key}"
            comparator_label = str(comparison.get("label") or "Approved comparator")
            comparator_value = str(comparison.get("value") or "Not supplied")
            add_node(
                {
                    "id": comparator_id,
                    "label": comparator_label,
                    "short_label": f"{comparator_label} · {comparator_value}",
                    "category": "comparator",
                    "detail": str(comparison.get("note") or f"Comparator for {label}: {comparator_value}."),
                    "hermes_prompt": f"What comparator is available for {label}, and what decision can or cannot be made from it?",
                    "properties": {"value": comparator_value, "available": comparison.get("available")},
                    "r": 9,
                }
            )
            add_edge(comparator_id, kpi_id, "COMPARED_WITH")
            focus.append(comparator_id)

        if strategic_reference:
            reference_id = f"strategic-reference:{key}"
            reference_label = str(strategic_reference.get("label") or "Approved strategic reference")
            reference_value = str(strategic_reference.get("value") or "Available")
            add_node(
                {
                    "id": reference_id,
                    "label": reference_label,
                    "short_label": f"{reference_label} · {reference_value}",
                    "category": "comparator",
                    "detail": f"{reference_value}. {strategic_reference.get('note') or ''}",
                    "hermes_prompt": f"Explain how {label} relates to {reference_label} and why a direct comparison may be withheld.",
                    "properties": {"value": reference_value, "source": strategic_reference.get("source")},
                    "r": 10,
                }
            )
            add_edge(reference_id, kpi_id, "STRATEGIC_REFERENCE")
            focus.append(reference_id)

        missing_inputs = list(card.get("missing_inputs") or audit.get("missing_inputs") or [])
        for index, missing in enumerate(missing_inputs[:6], start=1):
            missing_label = str(missing or "Required information")
            gap_id = f"gap:{key}:{index}"
            add_node(
                {
                    "id": gap_id,
                    "label": missing_label,
                    "category": "evidence_gap",
                    "detail": f"{missing_label} is still needed before this comparison is decision-ready.",
                    "hermes_prompt": f"Why is {missing_label} required for {label}, and what remains valid without it?",
                    "properties": {"kpi_key": key, "missing": True},
                    "r": 8,
                }
            )
            add_edge(gap_id, kpi_id, "REQUIRED_FOR")
            focus.append(gap_id)

        source_titles = list(audit.get("source_titles") or [])
        source_files = list(audit.get("source_files") or card.get("source_files") or [])
        for index, source_file in enumerate(source_files[:6], start=1):
            source_title = str(source_titles[index - 1] if index <= len(source_titles) else "Finance source")
            source_id = f"source:{key}:{index}"
            add_node(
                {
                    "id": source_id,
                    "label": source_title,
                    "category": "source",
                    "detail": f"{source_title} supports the current {label} figure.",
                    "hermes_prompt": f"Explain which business values from {source_title} support {label}.",
                    "properties": {"source_file": source_file, "kpi_key": key},
                    "r": 8,
                }
            )
            add_edge(source_id, kpi_id, "SUPPORTS")
            focus.append(source_id)

        questions.append(
            {
                "id": f"question:{key}",
                "label": label,
                "focus": list(dict.fromkeys(focus)),
            }
        )

    return nodes, edges, questions


def _build_public_safe_assistant_packet(
    summary: dict[str, Any] | None,
    *,
    persona_id: str,
    finding_rows: list[dict[str, Any]],
    audit_summary: dict[str, Any] | None,
    publication: dict[str, Any],
    board_portal: dict[str, Any],
    strategy_substrate: dict[str, Any],
    agent_modules: dict[str, Any],
    executive_presentation_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    persona_key = str(persona_id or "ceo").strip().lower() or "ceo"
    db_run_id = (summary or {}).get("_backing_run_id") or (summary or {}).get("run_id")
    if str(db_run_id or "") == ANONYMOUS_PUBLIC_RUN_ID:
        db_run_id = None
    if executive_presentation_payload is None:
        executive_read_model = _executive_read_model_from_available_truth(
            summary,
            finding_rows,
            audit_summary,
            publication,
            agent_modules,
            public_safe=True,
        )
        executive_presentation_payload = build_executive_presentation(executive_read_model)
    db_status = _data_management_status_for_run(str(db_run_id or "") or None)
    metrics = _governed_metrics_payload(summary, finding_rows, audit_summary)
    plan_health = _bounded_plan_health_payload(summary, finding_rows, audit_summary)
    kpi_cards = _kpi_card_payloads(summary, finding_rows, audit_summary)
    kpi_cards.append(
        {
            "card_id": "board_packet_reports",
            "label": "Board packet reports",
            "value": int(publication.get("report_count") or 0),
            "unit": "count",
            "trend_hint": "board_packet",
        }
    )

    # The conversational public packet is evidence-oriented, not a mirror of
    # the CEO's finance-ring surface.  Keeping these cards separate prevents a
    # missing Oracle finance snapshot from turning unrelated board questions
    # into an unavailable-KPI response.  Every value below is still a direct
    # aggregate of the current governed findings/audit data.
    drivers = [
        {
            "driver_key": "cash_recovery_opportunity",
            "key": "cash_recovery_opportunity",
            "label": "Cash recovery opportunity",
            "metric": _format_sar_brief(metrics.get("total_recoverable_sar")),
            "value": _format_sar_brief(metrics.get("total_recoverable_sar")),
            "sub": "Current governed value",
            "status": "Current governed value",
            "detail": "Current governed run; latest governed run cash boundary: recoverable value is summed from persisted governed findings.",
        },
        {
            "driver_key": "cases_in_view",
            "key": "cases_in_view",
            "label": "Cases in view",
            "metric": str(int(metrics.get("finding_count") or 0)),
            "value": str(int(metrics.get("finding_count") or 0)),
            "sub": "Governed cases",
            "status": "Governed cases",
            "detail": "Board review scope from the latest governed run: finding rows persisted for the selected run.",
        },
        {
            "driver_key": "evidence_readiness",
            "key": "evidence_readiness",
            "label": "Evidence readiness: challenged CEO review and next action",
            "metric": _format_ratio_display(metrics.get("resolved_count"), metrics.get("citation_count")),
            "value": _format_ratio_display(metrics.get("resolved_count"), metrics.get("citation_count")),
            "sub": "Citation chain",
            "status": "Citation chain",
            "detail": "Board evidence posture from the latest governed run: challenged items, CEO review, and next action depend on resolved citations over total persisted citations.",
        },
        {
            "driver_key": "items_needing_closure",
            "key": "items_needing_closure",
            "label": "Items needing closure",
            "metric": str(int(metrics.get("challenged_count") or 0)),
            "value": str(int(metrics.get("challenged_count") or 0)),
            "sub": "Reviewer attention",
            "status": "Reviewer attention",
            "detail": "Challenged board items from the latest governed run: persisted challenged items still visible in the review posture.",
        },
    ]

    display_rows = list(finding_rows or [])[:3]
    displayed_recoverable = round(
        sum(float(row.get("recoverable_sar") or 0.0) for row in display_rows),
        2,
    )
    total_recoverable = float(metrics.get("total_recoverable_sar") or 0.0)
    remaining_recoverable = round(max(0.0, total_recoverable - displayed_recoverable), 2)
    reconciliation = {
        "total_recoverable_sar": total_recoverable,
        "displayed_recoverable_sar": displayed_recoverable,
        "remaining_recoverable_sar": remaining_recoverable,
        "total_finding_count": int(metrics.get("finding_count") or len(finding_rows or [])),
        "displayed_finding_count": len(display_rows),
    }

    presentation_sections = executive_presentation_payload.get("sections") or {}
    findings = list((presentation_sections.get("findings") or {}).get("items") or [])
    developments = list((presentation_sections.get("developments") or {}).get("items") or [])
    week = list((presentation_sections.get("week_ahead") or {}).get("items") or [])

    executive_kpis = list(presentation_sections.get("drivers") or [])
    finding_case_index = list((presentation_sections.get("findings") or {}).get("case_index") or [])
    kg_nodes, kg_edges, kg_questions = _ceo_kpi_knowledge_graph(executive_kpis)

    running_agents = list((agent_modules.get("running") or []))
    activity_summary = agent_modules.get("summary") or {}
    activity = {
        "line": (
            f"{int(activity_summary.get('running_count') or 0)} active "
            f"{'module' if int(activity_summary.get('running_count') or 0) == 1 else 'modules'} · "
            f"{int(activity_summary.get('discoverable_count') or 0)} available "
            f"{'service' if int(activity_summary.get('discoverable_count') or 0) == 1 else 'services'} · "
            f"{int(activity_summary.get('approval_count') or 0)} approval "
            f"{'stage' if int(activity_summary.get('approval_count') or 0) == 1 else 'stages'}"
        ),
        "metrics": [
            {"k": "run id", "v": str((summary or {}).get("run_id") or ANONYMOUS_PUBLIC_RUN_ID)},
            {"k": "recoverable", "v": _format_sar_brief(metrics.get("total_recoverable_sar"))},
            {"k": "challenged", "v": str(int(metrics.get("challenged_count") or 0))},
        ],
        # The run's real recorded steps. Bounded for rendering, but the payload
        # carries its own total_count so a trimmed view never reads as complete.
        "execution_log": agent_modules.get("execution_log") or build_execution_log([]),
        "run_posture": list((agent_modules.get("run_posture") or []))[:3],
    }

    facts = [
        f"Plan health: {plan_health.get('label') or plan_health.get('status') or 'unavailable'}.",
        f"Recoverable value: {_format_sar_brief(metrics.get('total_recoverable_sar'))}.",
        f"Citation resolution: {_format_ratio_display(metrics.get('resolved_count'), metrics.get('citation_count'))}.",
    ]

    finance_payload = (summary or {}).get("finance_kpi") or (summary or {}).get("oracle_kpi") or {}
    finance_components = finance_payload.get("components") if isinstance(finance_payload, dict) else {}
    finance_evidence = finance_payload.get("evidence") if isinstance(finance_payload, dict) else {}
    cash_evidence = finance_evidence.get("cash_vs_floor") if isinstance(finance_evidence, dict) else {}

    return {
        "packet_id": f"latest-public:{persona_key}:{str((summary or {}).get('run_id') or ANONYMOUS_PUBLIC_RUN_ID)}",
        "mode": executive_presentation_payload.get("mode") or "live",
        "source": executive_presentation_payload.get("source") or "database",
        "truth_run_id": executive_presentation_payload.get("run_id"),
        "as_of": executive_presentation_payload.get("as_of"),
        "data_status": executive_presentation_payload.get("data_status"),
        "persona_id": persona_key,
        "assistant": "StrategyOS",
        "is_illustrative": False,
        "source_label": (
            "Current governed run payload"
            if db_status.get("status") == "ready"
            else f"Current governed run payload; database status is {db_status.get('status') or 'unknown'}"
        ),
        "data_sources": {
            "run_summary": {
                "status": "ok" if summary else "missing",
                "run_id": (summary or {}).get("run_id"),
                "truth_run_id": executive_presentation_payload.get("run_id"),
            },
            "database": db_status,
        },
        "health": {
            "score": None,
            "headline": ((executive_presentation_payload.get("hero") or {}).get("headline") or plan_health.get("label") or "Governed run unavailable"),
            "body": ((executive_presentation_payload.get("hero") or {}).get("body") or plan_health.get("summary") or db_status.get("reason") or "No governed run is available."),
            "scoreNote": ((executive_presentation_payload.get("hero") or {}).get("score_note") or plan_health.get("badge") or db_status.get("status") or "governed"),
        },
        "drivers": drivers,
        "findings": findings,
        "finding_case_index": finding_case_index,
        "developments": developments,
        "week": week,
        "board_portal": board_portal,
        "agent_activity": activity,
        "activity": activity,
        "running_agents": running_agents,
        "public_facts": {
            "total_recoverable_sar": metrics.get("total_recoverable_sar"),
            "displayed_recoverable_sar": reconciliation["displayed_recoverable_sar"],
            "remaining_recoverable_sar": reconciliation["remaining_recoverable_sar"],
            "total_finding_count": reconciliation["total_finding_count"],
            "displayed_finding_count": reconciliation["displayed_finding_count"],
            "citation_count": metrics.get("citation_count"),
            "resolved_count": metrics.get("resolved_count"),
            "challenged_count": metrics.get("challenged_count"),
            "report_count": publication.get("report_count"),
            "source_boundary": plan_health.get("boundary"),
            "current_cash_sar": (finance_components or {}).get("cash_balance"),
            "current_cash_complete": bool((cash_evidence or {}).get("actual_complete", False)),
        },
        "findings_reconciliation": reconciliation,
        "facts": facts,
        "kg_nodes": kg_nodes,
        "kg_edges": kg_edges,
        "kg_questions": kg_questions,
        "trace_summary": {
            "truth_basis": [
                "executive_read_model",
                "executive_presentation",
                (
                    "database_provenance"
                    if executive_presentation_payload.get("source") == "database"
                    else "governed_artifact_provenance"
                ),
            ],
            "run_id": executive_presentation_payload.get("run_id"),
            "database_status": db_status.get("status"),
        },
        "sections": presentation_sections,
        "provenance_summary": executive_presentation_payload.get("provenance_summary"),
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
    principal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {
            "status": "missing",
            "data_source": "unavailable",
            "data_source_status": "missing",
            "run_source": "current_run",
        }
    principal = dict(principal or {"role": "operator", "authenticated": True})
    principal.setdefault("role", "operator")
    principal.setdefault("authenticated", True)
    principal_role = str(principal.get("role") or "operator")
    rows = _finding_rows_from_summary(summary)
    audit_summary = _latest_run_audit_summary_payload(summary)
    metrics = _governed_metrics_payload(summary, rows, audit_summary)
    publication = _summary_publication_payload(summary, principal_role=principal_role)
    board_portal = _board_portal_payload(
        summary,
        principal_role=principal_role,
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
    payload["status"] = str(payload.get("status") or "ok")
    payload["data_source"] = "actual"
    payload["data_source_status"] = "current_run"
    payload["run_source"] = "current_run"
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
    payload["assistant_public_context"] = _build_public_safe_assistant_packet(
        summary,
        persona_id=str((view_state or {}).get("persona") or executive_modes.get("active_persona_id") or "ceo"),
        finding_rows=rows,
        audit_summary=audit_summary,
        publication=publication,
        board_portal=board_portal,
        strategy_substrate=strategy_substrate,
        agent_modules=agent_modules,
    )
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
    payload["data_source"] = "actual"
    payload["data_source_status"] = "current_run"
    payload["run_source"] = "current_run"
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
    return "/runs/latest/report-preview"


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
    checkpoint_summary = normalized.get("summary_json")
    merged_summary = dict(checkpoint_summary) if isinstance(checkpoint_summary, dict) else {}
    # The local/Hatchet fallback checkpoint is created inside the workflow,
    # before run_poc attaches finance KPIs, calendar agenda, historic context,
    # and the complete source-pack accounting to the outer run summary.  Merge
    # the latest approved summary into the checkpoint presented to resume so
    # writer completion cannot erase those post-processing payloads.
    merged_summary.update(
        {
            key: value
            for key, value in summary.items()
            if key not in {"local_review_checkpoint", "pointer_metadata", "latest_pointer"}
        }
    )
    normalized["summary_json"] = merged_summary
    normalized["persistence"] = "local"
    return normalized


def _checkpoint_with_latest_run_summary(
    run_id: str,
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    """Overlay post-workflow enrichment onto any review checkpoint.

    Hosted execution persists its checkpoint before ``run_poc`` attaches the
    finance KPIs, governed calendar, historic context, and final source-pack
    accounting to ``run_summary.json``.  Unlike the local fallback, a hosted
    checkpoint is returned directly by the state store, so it must receive the
    same latest-summary overlay before writer resume.
    """
    summary = _latest_local_summary_for_run(run_id)
    if not isinstance(summary, dict):
        return checkpoint
    enriched = dict(checkpoint)
    checkpoint_summary = enriched.get("summary_json")
    merged_summary = dict(checkpoint_summary) if isinstance(checkpoint_summary, dict) else {}
    merged_summary.update(
        {
            key: value
            for key, value in summary.items()
            if key not in {"local_review_checkpoint", "pointer_metadata", "latest_pointer"}
        }
    )
    enriched["summary_json"] = merged_summary
    return enriched


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
    if raw.startswith("oidc:"):
        raw = raw.removeprefix("oidc:")
    if "://" in raw:
        raw = raw.rsplit(":", 1)[-1]
    return raw.replace("_", " ").replace(".", " ").strip().title() or _display_role(
        role
    )


def _display_name_for_principal(role: str, subject: str) -> str:
    normalized_role = role.strip().lower()
    normalized_subject = subject.strip()
    if (
        not normalized_subject
        or normalized_subject in {"anonymous", "auth-disabled"}
        or normalized_subject.startswith("demo-role:")
        or normalized_subject.startswith("api-key:")
    ):
        return _display_role(normalized_role)
    return _display_subject(normalized_subject, normalized_role)


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
            "label": "Open challenged cases",
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


def _format_percent_brief(value: Any) -> str:
    """Render a percentage the way it was said: "40%", not "40.0%"."""
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return "--"
    if number == int(number):
        return f"{int(number)}%"
    return f"{number:.1f}%"


def _format_ratio_display(resolved: int | None, total: int | None) -> str:
    if total in (None, 0):
        return "--"
    if resolved is None or int(resolved) < 0 or int(resolved) > int(total):
        return "Needs reconciliation"
    return f"{int(resolved or 0)} / {int(total)}"


def _format_resolution_display(resolved: int | None, total: int | None) -> str:
    if total in (None, 0) or resolved is None:
        return "Resolution unavailable"
    if int(resolved) < 0 or int(resolved) > int(total):
        return "Resolution needs reconciliation"
    return f"{int(resolved)} of {int(total)} citations resolved"


def _governed_metrics_payload(
    summary: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    audit_summary: dict[str, Any] | None,
    *,
    filtered_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    all_rows = list(rows or [])
    view_rows = list(filtered_rows) if filtered_rows is not None else list(all_rows)
    row_citation_count = sum(int(row.get("citation_count") or 0) for row in all_rows)
    audited_citation_count = (audit_summary or {}).get("citation_count")
    citation_count = (
        int(audited_citation_count)
        if audited_citation_count is not None
        else row_citation_count
    )
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


def _board_reconciliation_payload(
    summary: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    audit_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    governed_rows = list(rows or [])
    computed_recoverable = round(
        sum(float(row.get("recoverable_sar") or 0.0) for row in governed_rows),
        2,
    )
    stated_raw = (summary or {}).get("total_recoverable_sar")
    stated_recoverable = round(float(stated_raw), 2) if stated_raw is not None else None
    recoverable_delta = (
        round(computed_recoverable - stated_recoverable, 2)
        if stated_recoverable is not None
        else None
    )
    recoverable_passed = (
        stated_recoverable is not None and abs(recoverable_delta or 0.0) <= 0.01
    )

    citation_total = (audit_summary or {}).get("citation_count")
    citation_resolved = (audit_summary or {}).get("resolved_count")
    citation_passed = (
        citation_total is not None
        and citation_resolved is not None
        and 0 <= int(citation_resolved) <= int(citation_total)
    )

    row_ids = {
        str(row.get("finding_id")) for row in governed_rows if row.get("finding_id")
    }
    open_challenge_ids = {
        str(item)
        for item in ((audit_summary or {}).get("challenged_finding_ids") or [])
        if item
    }
    row_challenge_ids = {
        str(row.get("finding_id"))
        for row in governed_rows
        if row.get("finding_id") and row.get("challenged")
    }
    challenge_passed = bool(
        (audit_summary or {}).get("status") == "ok"
    ) and open_challenge_ids.issubset(row_ids) and row_challenge_ids == open_challenge_ids
    checks = [
        {
            "key": "recoverable_arithmetic",
            "status": "passed" if recoverable_passed else "failed",
            "stated_sar": stated_recoverable,
            "computed_sar": computed_recoverable,
            "delta_sar": recoverable_delta,
        },
        {
            "key": "citation_arithmetic",
            "status": "passed" if citation_passed else "failed",
            "resolved": citation_resolved,
            "total": citation_total,
        },
        {
            "key": "open_challenge_traceability",
            "status": "passed" if challenge_passed else "failed",
            "open_count": len(open_challenge_ids),
            "finding_ids": sorted(open_challenge_ids),
            "finding_row_ids": sorted(row_challenge_ids),
        },
    ]
    passed = all(check["status"] == "passed" for check in checks)
    return {
        "status": "passed" if passed else "blocked",
        "publish_gate_passed": passed,
        "checks": checks,
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
        badge = "needs sign-off"
        label = "Waiting on a reviewer"
        summary_text = f"{challenged_count} case{'s' if challenged_count != 1 else ''} still {'need' if challenged_count != 1 else 'needs'} evidence closed before the full picture can be shown."
        tone = "warn"
    elif approval_status == "approved" and artifact_count:
        status = "release_posture_clear"
        badge = "signed off"
        label = "Approved for release"
        summary_text = "The figures, their evidence, and the board pack are all ready to release."
        tone = "ok"
    elif approval_status in {"pending", "awaiting_review", ""}:
        status = "review_gate_visible"
        badge = "needs sign-off"
        label = "Waiting on a reviewer"
        summary_text = "The figures and their evidence are ready. A reviewer still has to sign them off."
        tone = "neutral"
    else:
        status = "bounded_actionable"
        badge = "ready"
        label = "Figures are ready to act on"
        summary_text = "These figures are ready to act on. They cover this reporting period only."
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


def _lifecycle_hero_contract(
    *,
    persona_id: str,
    persona_label: str,
    board_portal: dict[str, Any],
    plan_health: dict[str, Any],
    publication: dict[str, Any],
    challenged_count: int,
) -> dict[str, str]:
    board_state = str(
        board_portal.get("presentation_state") or board_portal.get("state") or "pre"
    ).lower()
    report_count = int(publication.get("report_count") or 0)
    persona = "CFO" if persona_id in {"cfo", "bucfo"} else persona_label or "executive"
    health_label = str(plan_health.get("label") or "Governed plan posture")
    health_badge = str(plan_health.get("badge") or plan_health.get("status") or "governed")
    if board_state == "closed":
        return {
            "headline": "Board packet is closed and frozen",
            "body": (
                f"{persona} view is now a frozen board-session snapshot with {report_count} {'report' if report_count == 1 else 'reports'}. "
                f"{challenged_count} challenged {'item remains' if challenged_count == 1 else 'items remain'} as follow-up constraints, not pre-board preparation."
            ),
            "score_note": f"closed session · {health_badge}",
            "secondary_fact": health_label,
        }
    if board_state == "live":
        return {
            "headline": "Board session is live on governed material",
            "body": (
                f"{persona} view is operating from the approved board packet. "
                f"{challenged_count} unresolved {'item is' if challenged_count == 1 else 'items are'} visible as live constraints for the room."
            ),
            "score_note": f"live session · {health_badge}",
            "secondary_fact": health_label,
        }
    return {
        "headline": str(plan_health.get("label") or "Board preparation is active"),
        "body": str(
            plan_health.get("summary")
            or f"{challenged_count} challenged {'item needs' if challenged_count == 1 else 'items need'} reviewer closure before the board packet goes live."
        ),
        "score_note": f"pre-board · {health_badge}",
        "secondary_fact": health_label,
    }


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
    report_route = "/public/runs/latest/report-preview" if public_safe else "/runs/latest/report-preview"
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
    report_route = "/public/runs/latest/report-preview" if public_safe else "/runs/latest/report-preview"
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
    finding_rows = _finding_rows_from_summary(summary) if isinstance(summary, dict) else []
    audit_summary = (
        _latest_run_audit_summary_payload(summary) if isinstance(summary, dict) else None
    )
    metrics = _governed_metrics_payload(summary, finding_rows, audit_summary)
    reconciliation = _board_reconciliation_payload(summary, finding_rows, audit_summary)
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
    if reports and not reconciliation["publish_gate_passed"]:
        release_status = "blocked_reconciliation"
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
        "blocked_reconciliation"
        if reports and not reconciliation["publish_gate_passed"]
        else "published"
        if release_status == "published"
        else "ready"
        if release_status == "approved_for_release" and len(reports) > 1
        else "preview_only"
        if bool(reports)
        else "pending"
    )
    board_pack_route = (
        "/public/runs/latest/report-preview"
        if public_safe
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
        if public_safe
        else "/runs/latest/report-preview",
        "publish_ready": approval_status == "approved"
        and bool(reports)
        and reconciliation["publish_gate_passed"],
        "reconciliation": reconciliation,
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
                finding_rows,
                audit_summary,
            ),
        },
        "board_pack": {
            "status": board_pack_status,
            "safe_for_board": bool(reports)
            and release_status in {"approved_for_release", "published"}
            and reconciliation["publish_gate_passed"],
            "reconciliation": reconciliation,
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
    elif publication.get("status") == "approved_for_release":
        state = "live"
    presentation_state = (
        str(requested_state or "").strip().lower() if requested_state else ""
    ) or state
    if presentation_state not in EXECUTIVE_BOARD_STATES:
        presentation_state = state
    board_pack = dict(publication.get("board_pack") or {})
    state_labels = {
        "pre": ("Pre-board", "prepare"),
        "live": ("Live", "in session"),
        "closed": ("Closed", "collective memory"),
    }
    state_label, state_hint = state_labels.get(state, ("Pre-board", "prepare"))
    report_count = int(publication.get("report_count") or 0)
    challenged_count = int(publication.get("challenged_cases") or 0)
    next_action = str((publication.get("approval") or {}).get("next_action") or "")
    pre_summary = (
        "Prepare one board-safe packet for CEO review by resolving open challenged evidence, tightening supplementary answers, and confirming the release posture."
        if challenged_count
        else "Prepare one board-safe packet for CEO review by confirming the reconciled evidence and release posture."
    )
    pre_note = (
        "Keep the packet inside the executive lane until open challenged evidence is closed and supplementary answers are board-ready."
        if challenged_count
        else "No open challenged cases are recorded; keep the packet bounded to the reconciled evidence and approval lane."
    )
    state_detail = {
        "pre": {
            "state": "pre",
            "title": "Pre-board preparation",
            "summary": pre_summary,
            "note": pre_note,
            "primary_actions": ["prepare_board_pack", next_action or "capture_reviewer_decision"],
            "secondary_actions": ["inspect_report_preview", "review_supplementary_questions"],
        },
        "live": {
            "state": "live",
            "title": "Live board session",
            "summary": "Operate only inside the approved packet while questions stay linked to challenged evidence and governed release posture.",
            "note": "Stay inside the approved packet while the room is live and route every answer back to governed evidence.",
            "primary_actions": [next_action or "capture_reviewer_decision", "inspect_board_pack_status"],
            "secondary_actions": ["open_supplementary_rail", "freeze_live_answers"],
        },
        "closed": {
            "state": "closed",
            "title": "Closed / frozen snapshot",
            "summary": "Keep the board memory frozen and bounded to approved outputs after the session closes.",
            "note": "The room is closed now; preserve the frozen record and work follow-ups outside the board surface.",
            "primary_actions": ["inspect_frozen_snapshot", "review_board_memory"],
            "secondary_actions": ["compare_packet_release", "check_follow_up_obligations"],
        },
    }.get(presentation_state, {})
    lifecycle_flow = []
    for state_id, label, detail in (
        ("pre", "Pre-board", "Get the board pack ready"),
        ("live", "Live", "Run the meeting on approved material only"),
        ("closed", "Closed", "Keep the record as it was"),
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
        "governance_note": "Nothing reaches the board until someone has signed it off.",
        "meeting": {
            "mode": state_hint,
            "title": "Board pack",
            "tenant_label": _summary_tenant_context(summary, {"role": role}).get(
                "tenant_name"
            ),
            "run_id": (summary or {}).get("run_id"),
            "design_title": None,
            "when": None,
            "date": None,
            "room": None,
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
            "status": "open" if challenged_count else "clear" if state == "pre" else "governed" if state == "live" else "frozen",
            "question_count": challenged_count,
            "next_action": next_action,
            "route": "/reviewer/pending-reviews"
            if principal_has_any_role(role, "bu", "reviewer", "operator", "tenant_admin", "system")
            else "/executive?panel=supplementary",
            "summary": (
                "Supplementary board questions stay bounded to open challenged evidence and governed review posture."
                if challenged_count
                else "No open challenged-case questions are recorded for this packet."
            ),
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
            f"{challenged_count} open challenge{'s' if challenged_count != 1 else ''}",
        ],
        "lifecycle_flow": lifecycle_flow,
        "state_detail": {
            "state": presentation_state,
            "title": state_detail.get("title") or "Board posture",
            "summary": state_detail.get("summary") or "Board posture is bounded to the governed packet.",
            "note": state_detail.get("note") or "Keep the board packet bounded to governed review posture.",
            "primary_actions": state_detail.get("primary_actions") or [],
            "secondary_actions": state_detail.get("secondary_actions") or [],
        },
        "plan_health": {
            "status": plan_health.get("status"),
            "label": plan_health.get("label"),
            "next_action": plan_health.get("next_action"),
        },
        "governance": "Board posture is governed by current approval, evidence, and publication state only.",
        "kpis": [
            {
                "key": "recoverable_value",
                "label": "Recoverable value",
                "value": _format_sar_brief((summary or {}).get("total_recoverable_sar")),
                "sub": "latest governed run",
                "grounding": {
                    "status": (
                        "grounded"
                        if next(
                            (
                                check.get("status")
                                for check in ((publication.get("reconciliation") or {}).get("checks") or [])
                                if check.get("key") == "recoverable_arithmetic"
                            ),
                            "failed",
                        )
                        == "passed"
                        else "needs_evidence"
                    ),
                    "source": "governed findings reconciliation",
                },
            },
            {
                "key": "challenged_cases",
                "label": "Open challenged cases",
                "value": challenged_count,
                "sub": "current audit state",
                "grounding": {
                    "status": "grounded" if (audit_summary or {}).get("status") == "ok" else "needs_evidence",
                    "source": "governed audit log",
                },
            },
            {
                "key": "citation_resolution",
                "label": "Evidence resolution",
                "value": _format_resolution_display(
                    (audit_summary or {}).get("resolved_count"),
                    (audit_summary or {}).get("citation_count"),
                ),
                "sub": "current audit totals",
                "grounding": {
                    "status": (
                        "grounded"
                        if (audit_summary or {}).get("citation_count") is not None
                        and (audit_summary or {}).get("resolved_count") is not None
                        and 0 <= int((audit_summary or {}).get("resolved_count")) <= int((audit_summary or {}).get("citation_count"))
                        else "needs_evidence"
                    ),
                    "source": "governed citation audit",
                },
            },
            {
                "key": "report_count",
                "label": "Board packet reports",
                "value": report_count,
                "sub": "surfaced artifacts",
                "grounding": {
                    "status": "grounded" if report_count else "needs_evidence",
                    "source": "governed artifact registry",
                },
            },
        ],
        "decks": [],
        "supplementary_questions": [],
        "live_prompts": [],
        "actions": [],
        "board_summary": plan_health.get("summary"),
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
            "detail": "Value, release, board brief",
            "summary": "Frames plan-health, value capture, and board-safe release posture as bounded executive action.",
            "default_driver_key": "board_packet",
            "default_board_state": "pre",
            "assistant": "Hermes",
        },
        {
            "persona_id": "cfo",
            "label": "Group CFO",
            "detail": "Margin, controls, cash",
            "summary": "Focuses on cash pulse, hedge discipline, and release posture without overstating strategy authority.",
            "default_driver_key": "cash_pulse",
            "default_board_state": "pre",
            "assistant": "Atlas",
        },
        {
            "persona_id": "gm",
            "label": "BU GM",
            "detail": "Growth, service, capacity",
            "summary": "Keeps the governed packet tied to BU growth, service quality, and capacity signal already present in the finance slice.",
            "default_driver_key": "cash_pulse",
            "default_board_state": "pre",
            "assistant": "Iris",
        },
        {
            "persona_id": "bucfo",
            "label": "BU CFO",
            "detail": "Leakage, controls, exposure",
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
        # Only persona NAMING (assistant name/role, index label) comes from the
        # design module -- it is product copy. Narrative quotes and fixture
        # prompt/thread inventories stay out of governed payloads entirely.
        item["assistant_role"] = blueprint.get("assistantRole")
        item["index_label"] = blueprint.get("indexLabel")
        item["quote"] = ""
        item["quoted_by"] = ""
        item["prompt_count"] = 0
        item["thread_count"] = 0
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
    report_preview_route = "/public/runs/latest/report-preview" if public_safe else "/runs/latest/report-preview"
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
    persona_blueprint = {}
    board_design = {}
    active_driver_key = str((executive_modes or {}).get("active_driver_key") or "")
    active_driver = None
    gravity_assistant = "StrategyOS"
    gravity_prompts = []
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
                "Which case most changes the board-room story?",
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


def _executive_read_model_from_available_truth(
    summary: dict[str, Any] | None,
    finding_rows: list[dict[str, Any]],
    audit_summary: dict[str, Any] | None,
    publication: dict[str, Any] | None,
    agent_modules: dict[str, Any] | None,
    *,
    public_safe: bool,
) -> dict[str, Any]:
    backing_run_id = str(
        (summary or {}).get("_backing_run_id") or (summary or {}).get("run_id") or ""
    )
    if backing_run_id == ANONYMOUS_PUBLIC_RUN_ID:
        backing_run_id = ""
    database_snapshot = state_store.executive_snapshot_for_run(backing_run_id)
    if database_snapshot.get("status") == "ok":
        database_summary = dict(database_snapshot.get("summary") or {})
        database_rows = list(database_snapshot.get("findings") or [])
        database_audit = dict(database_snapshot.get("audit_summary") or {})
        # The execution log is resolved per run inside _agent_modules_payload,
        # so it arrives already attached and is not re-derived here.
        database_agent_modules = dict(agent_modules or {})
        artifact_map = dict(database_snapshot.get("artifacts") or {})
        tenant_payload = (
            database_summary.get("tenant_context")
            if isinstance(database_summary.get("tenant_context"), dict)
            else {}
        )
        report_contracts = build_run_report_contracts(
            artifact_map,
            tenant_id=str(tenant_payload.get("tenant_id") or CONFIG.tenant_slug),
            run_id=str(database_summary.get("run_id") or "") or None,
        )
        database_publication = {
            "report_count": len(report_contracts.reports),
        }
        if public_safe:
            database_summary = _anonymous_public_summary(database_summary) or database_summary
            database_rows = _anonymous_public_finding_payloads(database_rows)
            # Resolution state is intentionally not disclosed on the anonymous
            # executive surface. Preserve the unknown instead of rendering zero.
            database_audit = _public_latest_run_audit_summary_payload(database_summary)
        return build_executive_read_model(
            database_summary,
            database_rows,
            database_audit,
            database_publication,
            database_agent_modules,
            truth_source="database",
        )

    fallback_reason = str(
        database_snapshot.get("reason")
        or "The database executive snapshot is unavailable."
    )
    return build_executive_read_model(
        summary,
        finding_rows,
        audit_summary,
        publication,
        agent_modules,
        truth_source="governed_artifacts",
        source_status_reason=(
            f"{fallback_reason} Showing the current governed artifact run."
            if summary
            else fallback_reason
        ),
    )


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
    publication = _summary_publication_payload(
        summary,
        principal_role=str(principal.get("role") or "operator"),
        public_safe=_principal_prefers_public_safe_surface(principal),
    )
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
    executive_read_model = _executive_read_model_from_available_truth(
        summary,
        finding_rows,
        audit_summary,
        publication,
        agent_modules,
        public_safe=_principal_prefers_public_safe_surface(principal),
    )
    executive_presentation_payload = build_executive_presentation(executive_read_model)
    public_packet = _build_public_safe_assistant_packet(
        summary,
        persona_id=persona_id,
        finding_rows=finding_rows,
        audit_summary=audit_summary,
        publication=publication,
        board_portal=board_portal,
        strategy_substrate=strategy_substrate,
        agent_modules=agent_modules,
        executive_presentation_payload=executive_presentation_payload,
    )
    persona_blueprint = {
        "health": dict(public_packet.get("health") or {}),
        "assistant": public_packet.get("assistant"),
        "drivers": list(public_packet.get("drivers") or []),
        "findings": list(public_packet.get("findings") or []),
        "developments": list(public_packet.get("developments") or []),
        "week": list(public_packet.get("week") or []),
    }
    board_design = dict(public_packet.get("board_portal") or {})
    lifecycle_hero = _lifecycle_hero_contract(
        persona_id=persona_id,
        persona_label=str(persona_label or ""),
        board_portal=board_portal,
        plan_health=plan_health,
        publication=publication,
        challenged_count=challenged_count,
    )
    driver_tiles = []
    persona_drivers = list(executive_presentation_payload.get("driver_grid") or persona_blueprint.get("drivers") or [])
    for item in persona_drivers[:4] or list(executive_modes.get("driver_focus") or [])[:4]:
        driver_tiles.append(
            {
                "kpi_contract": bool(item.get("kpi_contract")),
                "driver_key": item.get("key") or item.get("driver_key"),
                "label": item.get("label"),
                "metric": item.get("value") or item.get("metric"),
                "status": item.get("vsPlan") or item.get("status"),
                "detail": item.get("story") or item.get("detail"),
                "active": str(item.get("key") or item.get("driver_key") or "") == active_driver_key,
                "portfolio_id": item.get("portfolio_id"),
                "pct": item.get("pct"),
                "ring_pct": item.get("ring_pct"),
                "ring_label": item.get("ring_label"),
                "sub": item.get("sub"),
                "provenance": item.get("provenance"),
                "grounding": item.get("grounding"),
                "availability": item.get("availability"),
                "formula": item.get("formula"),
                "inputs": item.get("inputs"),
                "missing_inputs": item.get("missing_inputs"),
                "comparison": item.get("comparison"),
                "evidence_summary": item.get("evidence_summary"),
                "source_files": item.get("source_files"),
                "trend": item.get("trend"),
                "trend_status": item.get("trend_status"),
                "executive_brief": item.get("executive_brief"),
            }
        )
    presentation_hero = dict(executive_presentation_payload.get("hero") or {})
    return {
        "mode": executive_presentation_payload.get("mode"),
        "source": executive_presentation_payload.get("source"),
        "run_id": executive_presentation_payload.get("run_id"),
        "as_of": executive_presentation_payload.get("as_of"),
        "data_status": executive_presentation_payload.get("data_status"),
        "status_reason": executive_presentation_payload.get("status_reason"),
        "hero": {
            "persona_id": persona_id,
            "persona_label": persona_label,
            "score": presentation_hero.get("score"),
            "status": presentation_hero.get("status") or plan_health.get("status"),
            "label": presentation_hero.get("label") or plan_health.get("label"),
            "summary": presentation_hero.get("summary") or lifecycle_hero.get("headline"),
            "body": presentation_hero.get("body") or lifecycle_hero.get("body"),
            "score_note": presentation_hero.get("score_note") or lifecycle_hero.get("score_note"),
            "secondary_fact": presentation_hero.get("secondary_fact") or lifecycle_hero.get("secondary_fact"),
            "quote": persona_blueprint.get("quote"),
            "quoted_by": persona_blueprint.get("by"),
            "active_driver_key": active_driver_key,
            "board_state": board_portal.get("presentation_state") or board_portal.get("state"),
            "readiness_operands": presentation_hero.get("readiness_operands"),
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
            "executive_read_model",
            "executive_presentation",
            (
                "database_provenance"
                if executive_presentation_payload.get("source") == "database"
                else "governed_artifact_provenance"
            ),
        ],
        "sections": executive_presentation_payload.get("sections") or {},
        "provenance_summary": executive_presentation_payload.get("provenance_summary") or {},
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
        "report_preview": {
            "method": "GET",
            "route": "/public/runs/latest/report-preview" if public_safe else "/runs/latest/report-preview",
        },
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
    # Starter threads derive from the latest governed run's actual findings --
    # never from the design-fixture narrative (which suggested prompts about
    # deals and meetings that exist only in the demo storyline). Scrub titles
    # to the board-safe form for principals on the public-safe surface.
    starter_rows = _finding_rows_from_summary(summary or {})
    if _principal_prefers_public_safe_surface(principal):
        starter_rows = _anonymous_public_finding_payloads(starter_rows)
    starter_threads: list[dict[str, Any]] = []
    for index, row in enumerate(starter_rows[:3], start=1):
        row_title = str(row.get("title") or f"Finding {index}")
        starter_prompt = f"What is driving “{row_title}” and what should we do next?"
        starter_threads.append(
            {
                "thread_id": f"{persona_id}:finding-{index}",
                "kind": "starter_prompt",
                "persona_id": persona_id,
                "persona_label": persona_label,
                "assistant": assistant_name,
                "title": row_title,
                "preview": starter_prompt,
                "starter_prompt": starter_prompt,
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
    preview_status = str((summary or {}).get("status") or "available")
    preview_stage = current_stage.replace("_", " ")
    preview_status_label = preview_status.replace("_", " ")
    if preview_status_label == "missing":
        workflow_preview = "No current governed run is available yet."
    elif preview_status_label == "available":
        workflow_preview = "Board context is available."
    elif preview_status_label == preview_stage:
        workflow_preview = f"Board context is {preview_status_label}."
    else:
        workflow_preview = f"Board context is {preview_status_label} at {preview_stage}."
    if challenged_count:
        workflow_preview += f" · {challenged_count} challenged item{'s' if challenged_count != 1 else ''}"
    threads = [
        {
            "thread_id": f"system:{run_id}",
            "kind": "system",
            "persona_id": persona_id,
            "persona_label": persona_label,
            "assistant": assistant_name,
            "title": "Board status",
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
        "starter_prompts": [
            str(thread.get("starter_prompt") or "")
            for thread in starter_threads
            if str(thread.get("starter_prompt") or "").strip()
        ],
        "a2a": {
            "enabled": True,
            # design doc acceptance criteria: "a2a.mode reports
            # durable_task_handoffs only when real persistence/execution is
            # enabled" -- gated on all three per-PR feature flags being on
            # together (conversations + handoffs + live UI), since that is
            # the full vertical slice the mode name promises. Any single
            # flag off means some part of the chain (durable conversation
            # storage, real typed handoffs, or the live network/approval
            # surface) is still the pre-agent-runtime derived behavior.
            "mode": (
                "durable_task_handoffs"
                if (CONFIG.agent_conversations_enabled and CONFIG.agent_handoffs_enabled and CONFIG.agent_live_ui_enabled)
                else "derived_handoff_only"
            ),
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


def _permitted_twin_surface_route(twin_role: str, principal_role: str) -> str | None:
    routes = {"ceo": "/twin/ceo", "cfo": "/twin/cfo", "group_manager": "/twin/gm"}
    allowed_roles = {
        "ceo": ("executive", "tenant_admin", "system"),
        "cfo": ("operator", "reviewer", "tenant_admin", "system"),
        "group_manager": ("bu", "operator", "tenant_operator", "tenant_admin", "system"),
    }
    if twin_role not in routes or not principal_has_any_role(
        principal_role, *allowed_roles[twin_role]
    ):
        return None
    return routes[twin_role]


def _agents_surface_payload(
    summary: dict[str, Any] | None,
    principal: dict[str, Any],
) -> dict[str, Any]:
    """Return the CEO's read-only view of the real Digital Twin runtime.

    Workflow modules deliberately do not enter this contract. They are governed
    automations and remain available through ``agent_modules``. Calling them
    agents made the UI imply independent personas and conversations that did not
    exist.
    """
    assistant_names = {
        "ceo": "Hermes",
        "cfo": "Atlas",
        "group_manager": "Iris",
    }
    configured_roles = (
        "ceo",
        "cfo",
        "group_manager",
        "strategy",
        "analyst",
        "reviewer",
    )
    configured_role_set = set(configured_roles)
    principal_role = str(principal.get("role") or "anonymous")
    repositories = build_app_repositories()
    states = {str(item.get("role") or ""): item for item in repositories.states.list()}
    inboxes = repositories.inboxes.list()
    all_investigations = repositories.investigations.list()
    cycle_history = repositories.cycle_history.list(limit=50)
    routing_events = repositories.governance.list_routing_events(limit=100)
    twins: list[dict[str, Any]] = []
    pending_request_total = 0
    fulfilled_request_total = 0
    exception_request_total = 0
    acknowledged_request_total = 0
    routing_gap_total = 0
    attention_total = 0
    request_status_by_id: dict[str, str] = {}
    terminal_request_statuses = {"fulfilled", "failed", "expired", "cancelled"}

    for twin_role in configured_roles:
        persona = TWIN_CATALOG[twin_role]
        state = states.get(twin_role) or {}
        investigations = list((all_investigations or {}).get(twin_role) or [])
        active_investigations = [
            item for item in investigations
            if str(item.get("status") or "open").lower()
            not in {"completed", "resolved", "closed", "no_action"}
        ]
        requests = repositories.requests.list(twin_role)
        valid_requests = []
        unroutable_requests = []
        for request_record in requests:
            request_id = str(request_record.get("request_message_id") or "")
            request_status = str(request_record.get("status") or "pending").lower()
            responder_role = str(request_record.get("responder_role") or "")
            is_routable = (
                responder_role in configured_role_set
                and responder_role != twin_role
                and str(request_record.get("routing_status") or "") != "unroutable"
            )
            if not is_routable:
                routing_gap_total += 1
                unroutable_requests.append(request_record)
                continue
            valid_requests.append(request_record)
            if request_id:
                request_status_by_id[request_id] = request_status
            if request_status == "fulfilled":
                fulfilled_request_total += 1
            elif request_status in {"failed", "expired", "cancelled"}:
                exception_request_total += 1
            elif request_status == "acknowledged":
                acknowledged_request_total += 1
        pending_requests = [
            item for item in valid_requests
            if str(item.get("status") or "pending").lower()
            not in terminal_request_statuses
        ]
        pending_request_total += len(pending_requests)
        needs_attention = any(
            str(item.get("status") or "").lower()
            in {"pending_human_review", "blocked_pending_review", "approval"}
            for item in active_investigations
        )
        if needs_attention:
            attention_total += 1
        last_wake = state.get("last_wake_at")
        cycle_count = int(state.get("cycle_count") or 0)
        if not CONFIG.twins_enabled:
            runtime_status = "disabled"
        elif needs_attention:
            runtime_status = "attention"
        elif active_investigations or pending_requests:
            runtime_status = "active"
        elif last_wake or cycle_count:
            runtime_status = "monitoring"
        else:
            runtime_status = "ready"
        current_activity = "Ready to support the next leadership review."
        if active_investigations:
            latest = active_investigations[-1]
            current_activity = str(
                latest.get("query")
                or latest.get("title")
                or latest.get("summary")
                or "Investigating a governed signal."
            )
        elif pending_requests:
            latest = pending_requests[0]
            current_activity = str(latest.get("subject") or "Waiting for another assistant to respond.")
        elif last_wake:
            current_activity = "Monitoring its governed KPIs; no open investigation is recorded."
        current_activity = _executive_twin_activity(current_activity)
        twins.append(
            {
                "twin_id": str(state.get("twin_id") or f"configured:{twin_role}"),
                "role": twin_role,
                "display_name": persona.display_name,
                "assistant_name": assistant_names.get(twin_role),
                "status": runtime_status,
                "last_wake_at": last_wake,
                "cycle_count": cycle_count,
                "active_investigation_count": len(active_investigations),
                "pending_request_count": len(pending_requests),
                "routing_gap_count": len(unroutable_requests),
                "inbox_count": len((inboxes or {}).get(twin_role) or []),
                "current_activity": current_activity,
                "kpis_owned": list(persona.kpis_owned),
                "goals": list(persona.goals),
                "authority": persona.authority,
                "escalation_path": list(persona.escalation_path),
                "route": _permitted_twin_surface_route(twin_role, principal_role),
            }
        )

    collaboration_events = [
        item
        for item in routing_events
        if str(item.get("source_role") or "") in configured_role_set
        and str(item.get("target_role") or "") in configured_role_set
        and (
            str(item.get("event_category") or "") == "inter_twin_message"
            or str(item.get("event_type") or "") in {"message_dispatched", "handoff"}
        )
    ][:20]
    recent_events = []
    for item in collaboration_events:
        item_id = str(item.get("item_id") or "")
        lifecycle_id = str(item.get("request_message_id") or item_id)
        request_status = request_status_by_id.get(lifecycle_id)
        if request_status == "fulfilled":
            lifecycle_status = "resolved"
        elif request_status in {"failed", "expired", "cancelled"}:
            lifecycle_status = "exception"
        elif request_status == "acknowledged":
            lifecycle_status = "acknowledged"
        elif request_status:
            lifecycle_status = "awaiting_response"
        else:
            lifecycle_status = "recorded"
        recent_events.append(
            {
                "event_id": item.get("event_id"),
                "timestamp": item.get("timestamp"),
                "source_role": item.get("source_role"),
                "target_role": item.get("target_role"),
                "event_type": item.get("event_type") or "handoff",
                "message_type": item.get("message_type"),
                "subject": item.get("title") or item.get("reason") or "Governed handoff",
                "status": lifecycle_status,
                "audit_source": item.get("audit_source") or "governance_log",
            }
        )
    completed_cycle_count = sum(
        1 for item in cycle_history if str(item.get("status") or "").lower() == "completed"
    )
    failed_cycle_count = sum(
        1 for item in cycle_history if str(item.get("status") or "").lower() == "failed"
    )
    handoff_word = "handoff" if pending_request_total == 1 else "handoffs"
    if attention_total:
        collaboration_summary = (
            f"{pending_request_total} open {handoff_word}; "
            f"{attention_total} require executive review."
        )
    elif pending_request_total:
        collaboration_summary = (
            f"{pending_request_total} {handoff_word} "
            f"{'is' if pending_request_total == 1 else 'are'} awaiting a leadership-team response. "
            "None is flagged for executive attention."
        )
    else:
        collaboration_summary = "Nothing in the leadership-team workflow requires your attention."
    payload = {
        "contract_version": "digital_twin_network.v1",
        "status": "ok" if CONFIG.twins_enabled else "disabled",
        "label": "Your AI assistants",
        "summary": {
            "configured_count": len(twins),
            "active_count": sum(1 for item in twins if item["status"] in {"active", "monitoring"}),
            "attention_count": attention_total,
            "pending_request_count": pending_request_total,
            "routing_gap_count": routing_gap_total,
            "collaboration_event_count": len(collaboration_events),
        },
        "digital_twins": twins,
        "collaboration": {
            "mode": "typed_inter_twin_protocol",
            "summary": collaboration_summary,
            "open_handoff_count": pending_request_total,
            "pending_request_count": pending_request_total,
            "acknowledged_handoff_count": acknowledged_request_total,
            "resolved_handoff_count": fulfilled_request_total,
            "exception_handoff_count": exception_request_total,
            "executive_attention_count": attention_total,
            "routing_gap_count": routing_gap_total,
            # Kept as diagnostic compatibility data. The CEO UI deliberately
            # does not display it as a second workload because each inbox
            # envelope is the delivery representation of a handoff request.
            "inbox_count": sum(
                len((inboxes or {}).get(role) or []) for role in configured_roles
            ),
            "unroutable_inbox_count": sum(
                len(items or [])
                for role, items in (inboxes or {}).items()
                if role not in configured_role_set and role != "human"
            ),
            "recent_events": recent_events,
        },
        "runtime": {
            "enabled": bool(CONFIG.twins_enabled),
            "mutations_enabled": bool(CONFIG.twins_mutations_enabled),
            "cycle_count": len(cycle_history),
            "completed_cycle_count": completed_cycle_count,
            "failed_cycle_count": failed_cycle_count,
            "source": "persistent_twin_repositories",
        },
        "authenticated": bool(principal.get("authenticated")),
    }
    # Compatibility boundary for non-executive API clients released before the
    # Digital Twin network contract. These lists stay empty by design: workflow
    # modules and data connectors must never be reclassified as agents.
    legacy_connectors = [
        {
            "id": f"connector-{item.get('connector_id')}",
            "name": item.get("display_name") or "Data connector",
            "source": "connector_catalog",
            "connector": item.get("connector_id"),
            "permitted": bool(item.get("permitted")),
        }
        for item in build_ingestion_connector_catalog(
            principal_role=str(principal.get("role") or "anonymous")
        )
    ]
    payload.update(
        {
            "running": [],
            "discover": {"native": [], "marketplace": legacy_connectors},
            "activity": {
                "line": "Leadership-team activity reflects recorded work and decisions needing attention.",
                "metrics": [
                    {"k": "AI leaders", "v": len(twins)},
                    {"k": "working now", "v": payload["summary"]["active_count"]},
                    {"k": "available services", "v": len(legacy_connectors)},
                ],
                "log": recent_events,
            },
        }
    )
    return payload


def _executive_twin_activity(value: Any) -> str:
    """Render persisted runtime activity as readable executive copy."""
    activity = re.sub(
        r"\s*[—–-]\s*unknown[_ ]node\b",
        "",
        str(value or "").strip(),
        flags=re.IGNORECASE,
    )
    activity = re.sub(r"\bunknown[_ ]node\b", "", activity, flags=re.IGNORECASE)
    activity = re.sub(r"\s+", " ", activity.replace("_", " ")).strip(" ·—–-")
    if not activity:
        return "No current governed activity is recorded."
    return activity[0].upper() + activity[1:]


def _resolve_digital_twin_status(
    question: str,
    *,
    summary: dict[str, Any] | None,
    role: str,
    public_safe: bool,
    assistant_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Answer AI-team questions from the same persisted Twin runtime as the UI."""
    if public_safe:
        return None
    normalized = " ".join(str(question or "").lower().split())
    context = dict(assistant_context or {})
    structured_twin = str(
        context.get("twin_role") or context.get("agent_id") or context.get("agent") or ""
    ).strip().lower()
    network_terms = (
        "digital twin",
        "digital twins",
        "ai team",
        "ai assistant",
        "ai assistants",
        "agent network",
        "agents tab",
    )
    asks_about_agents = (
        "agents" in normalized
        and any(token in normalized for token in ("doing", "status", "active", "attention", "blocked"))
    )
    # The surface now labels these "CEO Assistant" etc., so an executive asks
    # using that word. The legacy "twin" terms stay recognised: they are
    # matching vocabulary, not display copy, and users who learned the old
    # label must not lose the answer.
    named_terms = (
        "hermes", "atlas", "iris",
        "ceo assistant", "cfo assistant", "group manager assistant",
        "ceo twin", "cfo twin", "group manager twin",
    )
    if not structured_twin and not any(term in normalized for term in (*network_terms, *named_terms)) and not asks_about_agents:
        return None

    principal = {"role": role, "authenticated": True}
    network = _agents_surface_payload(summary, principal)
    twins = [
        item
        for item in list(network.get("digital_twins") or [])
        if not re.search(
            r"(?:^|_)(?:analyst|auditor|reviewer)(?:$|_)",
            str(item.get("role") or item.get("twin_id") or "").strip().casefold().replace("-", "_"),
        )
    ]
    if not twins:
        return None

    summary_payload = {
        **dict(network.get("summary") or {}),
        "configured_count": len(twins),
        "active_count": sum(
            1 for item in twins if str(item.get("status") or "").casefold() in {"active", "monitoring"}
        ),
        "attention_count": sum(
            1 for item in twins if str(item.get("status") or "").casefold() == "attention"
        ),
        "pending_request_count": sum(int(item.get("pending_request_count") or 0) for item in twins),
    }
    network = {
        **network,
        "digital_twins": twins,
        "summary": summary_payload,
    }

    def twin_matches(item: dict[str, Any]) -> bool:
        role_alias = str(item.get("role") or "").replace("_", " ").lower()
        aliases = {
            str(item.get("display_name") or "").lower(),
            str(item.get("assistant_name") or "").lower(),
            str(item.get("twin_id") or "").lower(),
        }
        if structured_twin and structured_twin in {*aliases, role_alias}:
            return True
        if role_alias and f"{role_alias} twin" in normalized:
            return True
        return any(alias and alias in normalized for alias in aliases)

    selected = [item for item in twins if twin_matches(item)]
    citations = [
        {
            "source_path": "runtime://digital-twin-network",
            "locator": "summary",
            "excerpt": (
                f"{summary_payload.get('configured_count', len(twins))} configured; "
                f"{summary_payload.get('attention_count', 0)} requiring executive attention"
            ),
        }
    ]

    if selected:
        item = selected[0]
        name = str(item.get("assistant_name") or item.get("display_name") or "Assistant")
        role_label = str(item.get("display_name") or item.get("role") or "Assistant")
        status_label = _module_status_label(item.get("status") or "ready")
        attention = str(item.get("status") or "").lower() == "attention"
        executive_action = (
            "It is flagged for executive attention; open its governed workspace and review the recorded escalation."
            if attention
            else "It is not currently flagged for executive intervention. Pending handoffs remain governed assistant-to-assistant dependencies unless an escalation changes the status to Attention."
        )
        answer = (
            f"{name} ({role_label}) is {status_label.lower()}. "
            f"Current activity: {item.get('current_activity') or 'No current governed activity is recorded.'} "
            f"It owns {', '.join(_module_status_label(value) for value in list(item.get('kpis_owned') or [])) or 'no configured KPI domains'}, "
            f"with {int(item.get('active_investigation_count') or 0)} open investigation(s) and "
            f"{int(item.get('pending_request_count') or 0)} pending handoff(s). {executive_action}"
        )
        citations.append(
            {
                "source_path": "runtime://digital-twin-network",
                "locator": f"digital_twins[{item.get('role')}].status",
                "excerpt": f"{name}: {status_label}",
            }
        )
        suggestions = [
            f"What KPIs does {name} own?",
            "Which AI assistant needs executive attention?",
        ]
    else:
        active = int(summary_payload.get("active_count") or 0)
        attention = int(summary_payload.get("attention_count") or 0)
        pending = int(summary_payload.get("pending_request_count") or 0)
        activity_lines = []
        for item in twins:
            name = str(item.get("assistant_name") or item.get("display_name") or _module_status_label(item.get("role")))
            activity_lines.append(
                f"{name}: {_module_status_label(item.get('status') or 'ready')} — {item.get('current_activity') or 'No current governed activity is recorded.'}"
            )
        attention_sentence = (
            f"{attention} AI assistant(s) are explicitly flagged for executive attention."
            if attention
            else "No AI assistant is currently flagged for executive attention."
        )
        answer = (
            f"Your AI team has {len(twins)} configured AI assistants; {active} are active or monitoring. "
            f"{attention_sentence} The network has {pending} pending governed handoff(s); these are not executive approvals unless an assistant is marked Attention. "
            "Current activity — " + " ".join(activity_lines)
        )
        suggestions = [
            "What is Atlas doing now?",
            "Which AI assistant needs executive attention?",
        ]

    return {
        "matched": True,
        "answer": answer,
        "basis": "Current assistant status and collaboration records from the authenticated CEO AI team.",
        "citations": citations,
        "suggestions": suggestions,
        "assistant_mode": "digital_twin_runtime",
        "answered_by": "digital_twin_runtime",
        "digital_twin_network": network,
        "grounding_status": "grounded",
        "_orchestrator_force_answer": True,
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


def _governed_module_state_contract_from_modules(
    modules: list[dict[str, Any]],
    *,
    run_id: str | None,
) -> dict[str, Any]:
    """Serialize module facts once for both executive UI and Hermes."""
    states: list[dict[str, Any]] = []
    for module in modules:
        module_id = str(module.get("module_id") or "").strip()
        if not module_id:
            continue
        states.append(
            {
                "module_id": module_id,
                "label": str(module.get("label") or module_id),
                "lane": str(module.get("lane") or "governed"),
                "status": str(module.get("status") or "unavailable"),
                "current_activity": str(module.get("summary") or "No current activity is recorded."),
                "output": str(module.get("output_metric") or "No output is recorded."),
                "dependency": str(module.get("approval_dependency") or "awaiting_action"),
                "provenance": {
                    "run_id": run_id,
                    "source": "governed_run_publication_and_review_state",
                },
            }
        )
    return {
        "contract_version": "governed_module_state.v1",
        "run_id": run_id,
        "modules": states,
    }


def _run_execution_log(summary: dict[str, Any] | None) -> dict[str, Any]:
    """Read this run's recorded assistant steps straight from the run.

    The events are persisted per run, so they must be looked up per run rather
    than inherited from whatever the caller happened to be holding. An earlier
    cut of this attached the events only where the read model is built, which
    left the payload the UI actually reads reporting "no steps recorded" for a
    run whose database row plainly held twenty of them.

    A run that has not been persisted has no events to read, and the empty
    result says exactly that rather than guessing.
    """
    run_id = str((summary or {}).get("_backing_run_id") or (summary or {}).get("run_id") or "")
    if not run_id or run_id == ANONYMOUS_PUBLIC_RUN_ID:
        return build_execution_log([])
    try:
        snapshot = state_store.executive_snapshot_for_run(run_id)
    except Exception:
        # The log is an accountability surface, not a load-bearing one; a
        # database wobble must not take the executive's page down with it.
        return build_execution_log([])
    if snapshot.get("status") != "ok":
        return build_execution_log([])
    return build_execution_log(list(snapshot.get("agent_events") or []))


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
    row_citation_count = sum(int(row.get("citation_count") or 0) for row in rows)
    audit_citation_count = (audit_summary or {}).get("citation_count")
    citation_count = (
        int(audit_citation_count)
        if audit_citation_count is not None
        else row_citation_count
    )
    resolved_count = (
        int((audit_summary or {}).get("resolved_count"))
        if (audit_summary or {}).get("resolved_count") is not None
        else None
    )
    resolution_display = _format_resolution_display(resolved_count, citation_count)
    modules = [
        {
            "module_id": "cash-recovery-watch",
            "label": "Cash recovery watch",
            "status": "running" if rows else "idle",
            "lane": "executive",
            "summary": f"Tracks recoverable value across {len(rows)} case{'s' if len(rows) != 1 else ''}.",
            "route": "/public/runs/latest/findings" if public_safe else "/runs/latest/findings",
            "output_metric": _format_sar_brief(sum(float(row.get("recoverable_sar") or 0.0) for row in rows)),
            "approval_dependency": "none",
        },
        {
            "module_id": "evidence-closure-monitor",
            "label": "Evidence closure monitor",
            "status": "blocked" if challenged_count else "running" if citation_count else "idle",
            "lane": "review",
            "summary": f"Watches {resolution_display.lower()} and {challenged_count} open challenged case{'s' if challenged_count != 1 else ''}.",
            "route": "/runs/latest/findings?domain=evidence_qa",
            "output_metric": resolution_display,
            "approval_dependency": "reviewer_release",
        },
        {
            "module_id": "board-pack-compiler",
            "label": "Board-pack compiler",
            "status": str((publication.get("board_pack") or {}).get("status") or "pending"),
            "lane": "executive",
            "summary": "Turns the reviewed reports into a board-safe pack, without exposing restricted material.",
            "route": publication.get("preview_route") or "/public/runs/latest/report-preview",
            "output_metric": f"{publication.get('report_count') or 0} report surfaces",
            "approval_dependency": str((publication.get("approval") or {}).get("next_action") or workflow.get("next_action") or "awaiting_action"),
        },
        {
            "module_id": "runtime-guardrail",
            "label": "Runtime guardrail",
            "status": "protected",
            "lane": "system",
            "summary": "Protects publication and company data access. Configuration changes are restricted to system administrators.",
            "route": "/data/status",
            "output_metric": "Guardrails active",
            "approval_dependency": "system_boundary",
        },
    ]
    discoverable = [
        {
            "module_id": "ceo-brief",
            "label": "CEO brief",
            "source": "native",
            "route": "/executive?persona=ceo",
            "lane": "executive",
            "permitted": True,
            "summary": "Board-safe Group CEO framing over the latest governed packet.",
        },
        {
            "module_id": "board-room-memory",
            "label": "Board room memory",
            "source": "native",
            "route": f"/executive?persona=board&board={_publication_lifecycle_mode(publication)}",
            "lane": "executive",
            "permitted": True,
            "summary": "Lets the board portal move between pre-board, live, and closed memory modes.",
        },
        {
            "module_id": "reviewer-gate-console",
            "label": "Reviewer gate console",
            "source": "native",
            "route": "/reviewer/pending-reviews",
            "lane": "review",
            "permitted": principal_has_any_role(role, "reviewer", "tenant_admin", "system"),
            "summary": "Focused queue for claim, approval, rejection, and evidence closure.",
        },
        {
            "module_id": "operator-resume-relay",
            "label": "Operator resume relay",
            "source": "native",
            "route": "/app?lane=operate",
            "lane": "operate",
            "permitted": principal_has_any_role(role, "operator", "tenant_operator", "tenant_admin", "system"),
            "summary": "Tracks paused work and shows when it is safe to resume after approval.",
        },
        {
            "module_id": "tenant-runtime-watch",
            "label": "System health monitor",
            "source": "native",
            "route": "/app?lane=system",
            "lane": "system",
            "permitted": principal_has_any_role(role, "tenant_admin", "system"),
            "summary": "Shows whether data sources, approvals, and publishing checks are healthy.",
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
    # Run posture, NOT an execution log. These three lines restate the run's
    # current stage and approval state; no assistant step is described by any of
    # them. The real per-step record lives in strategyos_agent_events and is
    # attached as "execution_log" by the database read below. Keeping the two
    # apart matters: presenting status prose as an audit trail claims the run
    # knows more about its own work than it has told us.
    run_posture = [
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
            "detail": f"Board pack is {str((publication.get('board_pack') or {}).get('status') or 'pending').replace('_', ' ')} with {publication.get('report_count') or 0} surfaced {'report' if int(publication.get('report_count') or 0) == 1 else 'reports'}.",
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
        "run_posture": run_posture,
        "execution_log": _run_execution_log(summary),
        "state_contract": _governed_module_state_contract_from_modules(
            modules,
            run_id=(summary or {}).get("run_id"),
        ),
    }


def _module_status_label(value: Any) -> str:
    return str(value or "unavailable").replace("_", " ").replace("-", " ").strip().title()


def _module_executive_action(dependency: Any) -> str:
    """Translate a governed dependency key into an executive-safe action.

    This is deliberately dependency-based rather than module-based: every
    module uses the same contract, and a new dependency gets a transparent
    fallback instead of a fabricated action.
    """
    key = str(dependency or "").strip().lower()
    known_actions = {
        "none": "No executive action is currently required.",
        "close_challenged_cases": "Sponsor closure of the challenged cases, then review the release posture.",
        "reviewer_release": "Ensure the reviewer release decision and supporting evidence are complete.",
        "operator_resume": "Confirm the reviewer decision so the operator workflow can resume.",
        "prepare_board_pack": "Review the board-pack readiness and decide whether to proceed with publication.",
        "system_boundary": "No executive action is available; this remains a protected system boundary.",
        "awaiting_action": "Review the current publication posture and take the next governed action shown in the board workflow.",
    }
    if key in known_actions:
        return known_actions[key]
    if not key:
        return "The current governed record does not specify an executive action."
    return f"Required governed action: {_module_status_label(key)}."


def _finance_function_event_sort_key(entry: Mapping[str, Any]) -> tuple[int, float, int]:
    """Return a stable newest-first key for recorded Analyst/Auditor work."""
    try:
        round_no = int(entry.get("round_no"))
    except (TypeError, ValueError):
        round_no = -1
    occurred_at = -1.0
    raw_occurred_at = str(entry.get("occurred_at") or "").strip()
    if raw_occurred_at:
        try:
            occurred_at = datetime.fromisoformat(raw_occurred_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            occurred_at = -1.0
    state_text = f"{entry.get('action') or ''} {entry.get('status') or ''}".casefold()
    if re.search(
        r"\b(?:lock(?:ed)?|resolv(?:e|ed)|approv(?:e|ed)|complet(?:e|ed)|clos(?:e|ed)|accept(?:ed)?|block(?:ed)?|fail(?:ed)?|reject(?:ed)?|max[ _-]?rounds)\b",
        state_text,
    ):
        action_rank = 3
    elif re.search(r"\b(?:response|responded|answer|answered)\b", state_text):
        action_rank = 2
    elif re.search(r"\b(?:challenge|challenged)\b", state_text):
        action_rank = 1
    else:
        action_rank = 0
    return round_no, occurred_at, action_rank


def _resolve_finance_function_review(
    question: str,
    *,
    summary: dict[str, Any] | None,
    assistant_context: dict[str, Any] | None,
    public_safe: bool,
) -> dict[str, Any] | None:
    """Answer the CEO from the persisted Finance Analyst/Auditor audit trail."""
    if public_safe or not isinstance(summary, Mapping):
        return None
    context = dict(assistant_context or {})
    normalized = " ".join(str(question or "").casefold().split())
    entrypoint = str(context.get("entrypoint") or "").strip().casefold()
    source = str(context.get("source") or "").strip().casefold()
    structured_request = entrypoint == "function_review" or source == "functions_workspace"
    typed_request = (
        ("finance analyst" in normalized or "finance auditor" in normalized)
        and any(term in normalized for term in ("review", "status", "stuck", "blocked", "completed", "done", "intervene"))
    )
    if not structured_request and not typed_request:
        return None

    agent_modules = summary.get("agent_modules")
    execution_log = agent_modules.get("execution_log") if isinstance(agent_modules, Mapping) else None
    if not isinstance(execution_log, Mapping) or not list(execution_log.get("entries") or []):
        # Q&A resolves the stored run summary directly, while the executive
        # endpoint decorates that summary with per-run accountability data.
        # Read through the same governed helper so Hermes and the Functions UI
        # can never disagree about whether recorded work exists.
        execution_log = _run_execution_log(dict(summary))
    raw_entries = execution_log.get("entries") if isinstance(execution_log, Mapping) else None
    finance_entries = [
        dict(item)
        for item in list(raw_entries or [])
        if isinstance(item, Mapping)
        and str(item.get("actor") or "").strip().casefold() in {"finance analyst", "finance auditor"}
    ]
    by_finding: dict[str, list[dict[str, Any]]] = {}
    for entry in finance_entries:
        finding_id = str(entry.get("finding_id") or "").strip()
        if finding_id:
            by_finding.setdefault(finding_id, []).append(entry)

    finding_states: list[dict[str, Any]] = []
    for finding_id, entries in sorted(by_finding.items()):
        entries.sort(key=_finance_function_event_sort_key, reverse=True)
        latest = entries[0]
        state_text = f"{latest.get('status') or ''} {latest.get('action') or ''}".casefold()
        if re.search(r"\b(?:locked|resolved|approved|complete|completed|closed|accepted)\b", state_text):
            state = "complete"
        elif re.search(r"\b(?:blocked|stuck|failed|rejected|challenge|challenged)\b", state_text):
            state = "stuck"
        else:
            state = "working"
        finding_states.append(
            {
                "finding_id": finding_id,
                "state": state,
                "latest_actor": str(latest.get("actor") or ""),
                "latest_action": str(latest.get("action") or latest.get("status") or "recorded"),
                "round_count": len({entry.get("round_no") for entry in entries if entry.get("round_no") is not None}),
                "recorded_step_count": len(entries),
            }
        )

    complete_ids = [item["finding_id"] for item in finding_states if item["state"] == "complete"]
    stuck_ids = [item["finding_id"] for item in finding_states if item["state"] == "stuck"]
    working_ids = [item["finding_id"] for item in finding_states if item["state"] == "working"]
    open_ids = [*stuck_ids, *working_ids]
    rounds = {
        entry.get("round_no")
        for entry in finance_entries
        if entry.get("round_no") is not None
    }
    analyst_responses = sum(
        1
        for entry in finance_entries
        if str(entry.get("actor") or "").casefold() == "finance analyst"
        and re.search(r"\b(?:respond|response|answer|answered)\b", f"{entry.get('action') or ''} {entry.get('status') or ''}".casefold())
    )
    auditor_challenges = sum(
        1
        for entry in finance_entries
        if str(entry.get("actor") or "").casefold() == "finance auditor"
        and "challenge" in f"{entry.get('action') or ''} {entry.get('status') or ''}".casefold()
    )

    if not finance_entries:
        overall_state = "Not started"
        completion_sentence = "No Finance Analyst or Finance Auditor work is recorded for this run."
        intervention = "CEO intervention: none can be determined until specialist work is recorded."
    elif stuck_ids:
        overall_state = "Stuck"
        completion_sentence = (
            f"{len(complete_ids)} of {len(finding_states)} findings are complete; "
            f"{len(stuck_ids)} are stuck ({', '.join(stuck_ids[:5])}{'…' if len(stuck_ids) > 5 else ''})."
        )
        intervention = "CEO intervention: review the stuck findings and assign ownership for the unresolved evidence or decision."
    elif working_ids:
        overall_state = "In progress"
        completion_sentence = (
            f"{len(complete_ids)} of {len(finding_states)} findings are complete; "
            f"{len(working_ids)} remain in progress ({', '.join(working_ids[:5])}{'…' if len(working_ids) > 5 else ''})."
        )
        intervention = "CEO intervention: none is currently flagged; monitor the open review until it reaches a recorded lock or exception."
    else:
        overall_state = "Complete"
        completion_sentence = f"All {len(finding_states)} reviewed findings are complete and locked; 0 are open or stuck."
        intervention = "CEO intervention: none is currently required by the recorded review state."

    try:
        recoverable = float(summary.get("total_recoverable_sar") or 0)
    except (TypeError, ValueError):
        recoverable = 0.0
    material_sentence = (
        f"The governed findings identify SAR {recoverable:,.0f} of recoverable value."
        if recoverable
        else "No recoverable-value total is recorded for this run."
    )
    answer = (
        f"Finance review status: {overall_state}. {completion_sentence} "
        f"The Finance Analyst recorded {analyst_responses} audit response(s); the Finance Auditor recorded "
        f"{auditor_challenges} challenge(s) and {len(complete_ids)} final lock(s) across {len(rounds)} review round(s). "
        f"{material_sentence} {intervention}"
    )
    return {
        "matched": True,
        "answer": answer,
        "basis": "Persisted Finance Analyst and Finance Auditor execution events from the current governed run.",
        "citations": [
            {
                "source_path": "governance://finance-function-review",
                "locator": "agent_modules.execution_log",
                "excerpt": (
                    f"{len(finance_entries)} recorded specialist steps; {len(complete_ids)} complete; "
                    f"{len(open_ids)} open or stuck; {len(rounds)} review rounds"
                ),
            }
        ],
        "suggestions": [
            "Show the material findings by recoverable value",
            "Open the Analyst–Auditor audit trail",
            "What should I prepare for the next calendar commitment?",
        ],
        "assistant_mode": "governed_function_review",
        "answered_by": "governed_function_review",
        "grounding_status": "grounded",
        "function_review": {
            "status": overall_state.casefold().replace(" ", "_"),
            "recorded_step_count": len(finance_entries),
            "finding_count": len(finding_states),
            "complete_count": len(complete_ids),
            "stuck_count": len(stuck_ids),
            "working_count": len(working_ids),
            "round_count": len(rounds),
            "findings": finding_states,
        },
        "_orchestrator_force_answer": True,
    }


def _governed_module_state_contract(
    summary: dict[str, Any] | None,
    *,
    role: str,
    public_safe: bool,
) -> dict[str, Any]:
    """Return the single server-side source of truth for visible modules.

    Module state is derived from the same governed run, publication and review
    records that render the executive network.  The browser may nominate a
    module ID, but never supplies the state used in an answer.
    """
    rows = _finding_rows_from_summary(summary) if summary else []
    audit_summary = _latest_run_audit_summary_payload(summary) if summary else None
    modules_payload = _agent_modules_payload(
        summary,
        rows,
        audit_summary,
        {"role": role, "authenticated": not public_safe},
    )
    contract = modules_payload.get("state_contract")
    if isinstance(contract, dict):
        return dict(contract)
    return _governed_module_state_contract_from_modules(
        list(modules_payload.get("running") or []),
        run_id=(summary or {}).get("run_id"),
    )


def _resolve_governed_module_status(
    question: str,
    *,
    summary: dict[str, Any] | None,
    assistant_context: dict[str, Any] | None,
    role: str,
    public_safe: bool,
) -> dict[str, Any] | None:
    """Resolve a module question against the server-side module contract."""
    contract = _governed_module_state_contract(
        summary,
        role=role,
        public_safe=public_safe,
    )
    modules = list(contract.get("modules") or [])
    if not modules:
        return None
    context = dict(assistant_context or {})
    requested_id = str(context.get("module_id") or "").strip().lower()
    question_normalized = " ".join(str(question or "").lower().split())
    selected = next(
        (module for module in modules if str(module.get("module_id") or "").lower() == requested_id),
        None,
    )
    if selected is None:
        # Typed questions may omit structured context. Match only an entire
        # registered module label/ID and only in a module-status question.
        asks_about_module = any(
            token in question_normalized
            for token in (" module", "module ", "doing right now", "is it blocked", "what does it need")
        )
        if not asks_about_module:
            return None
        selected = next(
            (
                module
                for module in modules
                if str(module.get("label") or "").lower() in question_normalized
                or str(module.get("module_id") or "").replace("-", " ") in question_normalized
            ),
            None,
        )
    if selected is None:
        return None

    status = str(selected["status"] or "unavailable").lower()
    dependency = str(selected["dependency"] or "awaiting_action")
    state = _module_status_label(status)
    dependency_label = _module_status_label(dependency)
    if status in {"blocked", "idle", "unavailable", "missing"}:
        blocker = f"It is blocked by: {dependency_label}."
    elif status in {"preview_only", "preview", "pending", "waiting", "draft", "queued"}:
        blocker = f"It is waiting on: {dependency_label}."
    elif dependency.lower() == "none":
        blocker = "It does not report a current blocker."
    else:
        blocker = f"Its current dependency is: {dependency_label}."

    label = str(selected["label"])
    lane = _module_status_label(selected["lane"])
    answer = (
        f"{label} is a governed {lane.lower()} module, not an independent long-running agent. "
        f"Current state: {state}. It is doing this now: {selected['current_activity']} "
        f"Current output: {selected['output']}. {blocker} "
        f"What it needs from you: {_module_executive_action(dependency)}"
    )
    module_id = str(selected["module_id"])
    citations = [
        {
            "source_path": "governance://governed-module-state",
            "locator": f"modules[{module_id}].status",
            "excerpt": f"{label}: {state}",
        },
        {
            "source_path": "governance://governed-module-state",
            "locator": f"modules[{module_id}].dependency",
            "excerpt": dependency_label,
        },
    ]
    return {
        "matched": True,
        "answer": answer,
        "basis": "Server-side governed module-state contract derived from the current run, publication, and review state.",
        "citations": citations,
        "suggestions": [
            f"What must close before {label} can proceed?",
            "Which challenged cases need executive attention?",
        ],
        "assistant_mode": "governed_module",
        "answered_by": "governed_module",
        "module": selected,
        "module_state_contract": contract,
        "grounding_status": "grounded",
        "_orchestrator_force_answer": True,
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
    public_safe = _principal_prefers_public_safe_surface(principal)
    summary = _latest_summary()
    if summary is None:
        return {
            "status": "missing",
            "artifact_key": artifact_key or "executive_summary",
            "title": "Report preview",
            "preview_kind": "text",
            "preview_text": "No latest governed run is available yet.",
            "public_safe": public_safe,
            "trend": _trend_card_payload(),
            "publication": _summary_publication_payload(
                None,
                principal_role=role,
                public_safe=public_safe,
            ),
            "board_portal": _board_portal_payload(
                None,
                principal_role=role,
                public_safe=public_safe,
            ),
            "agent_modules": _agent_modules_payload(None, [], None, principal),
            "role_actions": _role_actions_payload(None, [], None, principal),
        }
    if public_safe:
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
    if role in {"operator", "reviewer", "tenant_operator"}:
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
            try:
                payload = _read_artifact_payload(
                    artifact_key=selected_key,
                    artifact_path=artifact_path,
                    scope="run",
                    run_id=str(summary.get("run_id") or ""),
                )
            except HTTPException as exc:
                if exc.status_code != status.HTTP_404_NOT_FOUND:
                    raise
                return {
                    "status": "missing",
                    "run_id": summary.get("run_id"),
                    "artifact_key": selected_key,
                    "title": title,
                    "preview_kind": "text",
                    "preview_text": str(exc.detail),
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
            else:
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
        f"{publication['report_count']} {'report is' if publication['report_count'] == 1 else 'reports are'} tracked; {publication['restricted_report_count']} remain protected.",
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
        if public_safe
        else "/runs/latest/report-preview"
    )
    surfaces = [
        build_surface_contract(
            surface_id="overview",
            title="Overview",
            visibility="public" if public_safe else "protected",
            audience=("anonymous", "executive", "analyst", "bu", "reviewer", "operator"),
            permitted=True,
            primary_route="/public/runs/latest" if public_safe else "/runs/latest",
            public_route="/public/runs/latest",
            actions=("view_summary", "view_history"),
        ),
        build_surface_contract(
            surface_id="cases",
            title="Cases",
            visibility="public" if public_safe else "protected",
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
                "Board-safe preview only." if public_safe else "Protected evidence routes available."
            ,),
        ),
        build_surface_contract(
            surface_id="reports",
            title="Reports",
            visibility="public" if public_safe else "restricted" if can_review or can_operate else "protected" if principal_has_any_role(role, "bu", "executive") else "public",
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
    historical_challenged_ids = _historically_challenged_finding_ids_from_audit_log(
        audit_payload
    )
    verification = summary.get("audit_verification")
    if not historical_challenged_ids and isinstance(verification, dict):
        raw_ids = verification.get("challenged_finding_ids") or []
        if isinstance(raw_ids, list):
            historical_challenged_ids = sorted(str(item) for item in raw_ids if item)

    return {
        "status": "ok",
        "run_id": summary.get("run_id"),
        "run_dir": summary.get("run_dir"),
        "challenged_finding_ids": challenged_ids,
        "historical_challenged_finding_ids": historical_challenged_ids,
        "closed_challenge_count": max(
            0, len(historical_challenged_ids) - len(challenged_ids)
        ),
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

        status_payload = hatchet_dependency_status(CONFIG, verify_connection=True)
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


def _require_login_if_enabled(principal: dict[str, Any]) -> None:
    """Fail closed on hosted surfaces without changing local fixture behavior."""
    if not CONFIG.login_required:
        return
    if not principal.get("authenticated"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in is required.",
        )
    role = str(principal.get("role") or "")
    if not principal_has_any_role(role, *PRODUCT_READ_ROLES, "tenant_admin", "system"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This identity is not permitted for this endpoint.",
        )


def _login_or_authorized_html(principal: dict[str, Any]) -> RedirectResponse | None:
    """Return the only anonymous HTML surface for the hosted deployment."""
    if not CONFIG.login_required:
        return None
    if not principal.get("authenticated"):
        return RedirectResponse(url="/login", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    _require_login_if_enabled(principal)
    return None


def _ui_bootstrap(
    *,
    view_state: dict[str, str | None] | None = None,
    entry_route: str = "/app",
) -> dict[str, Any]:
    llm_status = llm_qa.chat_status(CONFIG)
    requested_view_state = dict(view_state or _requested_executive_view_state())
    public_packet_persona = str(requested_view_state.get("persona") or "ceo")
    summary = _anonymous_public_summary(_latest_summary())
    rows = _anonymous_public_finding_payloads(_finding_rows_from_summary(summary)) if summary else []
    audit_summary = _latest_run_audit_summary_payload(summary) if summary else None
    principal = {"role": "executive", "authenticated": False}
    publication = _summary_publication_payload(summary, principal_role="executive", public_safe=True) if summary else {}
    board_portal = _board_portal_payload(
        summary,
        principal_role="executive",
        public_safe=True,
        requested_state=requested_view_state.get("board"),
    )
    strategy_substrate = _strategy_substrate_payload(summary, rows, audit_summary, principal)
    agent_modules = _agent_modules_payload(summary, rows, audit_summary, principal)
    return {
        "product_name": "StrategyOS",
        "shell_title": "StrategyOS",
        "environment": _ui_environment_label(),
        "workspace_root": str(CONFIG.workspace_root),
        "default_run_dir": str(CONFIG.default_run_dir),
        "output_root": str(CONFIG.output_root),
        "auth_mode": CONFIG.auth_mode,
        "api_auth_enabled": CONFIG.api_auth_enabled,
        "login_required": CONFIG.login_required,
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
        "assistant_public_context": {} if CONFIG.login_required else _build_public_safe_assistant_packet(
            summary,
            persona_id=public_packet_persona,
            finding_rows=rows,
            audit_summary=audit_summary,
            publication=publication,
            board_portal=board_portal,
            strategy_substrate=strategy_substrate,
            agent_modules=agent_modules,
        ),
        "requested_view_state": requested_view_state,
        "route_contracts": {
            "entry": _build_executive_route(view_state, base_route=entry_route),
            "app": "/app",
            "dashboard": "/dashboard",
            "executive": "/executive",
            "workspace_contract": "/ui/workspace-contract/latest",
            "public_latest_run": "/runs/latest" if CONFIG.login_required else "/public/runs/latest",
            "public_report_preview": "/runs/latest/report-preview" if CONFIG.login_required else "/public/runs/latest/report-preview",
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
    asset_rev = _executive_asset_revision()
    bootstrap_json = (
        json.dumps(_ui_bootstrap(view_state=view_state, entry_route=entry_route))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    template_path = STATIC_DIR / "executive.html"
    html_text = template_path.read_text(encoding="utf-8")
    html_text = html_text.replace("__EXECUTIVE_ASSET_REV__", asset_rev)
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
        return None
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
    narrative = ""
    if label == "Finding":
        display = str(properties.get("finding_id") or node_id.removeprefix("Finding:"))
        sublabel = str(properties.get("title") or properties.get("pattern_type") or "Finding")
        sar = _kg_amount(properties.get("recoverable_sar"))
        pattern = properties.get("pattern_type") or "unknown pattern"
        evidence_count = properties.get("evidence_count") or properties.get("document_count") or 0
        sar_part = f"Recoverable SAR: {sar:,.0f}" if sar else "Recoverable SAR: pending"
        evidence_part = f"Source: {evidence_count} documents" if evidence_count else ""
        parts = [sar_part, f"Pattern: {pattern}"]
        if evidence_part:
            parts.append(evidence_part)
        narrative = " | ".join(parts)
    elif label == "Vendor":
        display = str(properties.get("vendor_name") or properties.get("vendor_id") or node_id.removeprefix("Vendor:"))
        invoice_count = invoice_counts.get(node_id, 0)
        vendor_id = properties.get("vendor_id") or node_id.removeprefix("Vendor:")
        sublabel = f"{vendor_id} - {invoice_count:,} invoices" if invoice_count else str(vendor_id)
        contract_count = properties.get("contract_count", 0)
        finding_count = properties.get("finding_count", 0)
        parts = []
        if invoice_count:
            parts.append(f"{invoice_count} invoices")
        if contract_count:
            parts.append(f"{contract_count} contracts")
        if finding_count:
            parts.append(f"{finding_count} findings linked")
        narrative = " | ".join(parts) if parts else f"Vendor {vendor_id}"
    elif label == "Evidence":
        source_path = str(properties.get("source_path") or node_id.removeprefix("Evidence:"))
        display = Path(source_path).name or source_path
        sublabel = source_path
        file_ext = Path(source_path).suffix.lower() if source_path else ""
        file_type = properties.get("document_type") or properties.get("file_type") or file_ext.lstrip(".") or "document"
        purpose = properties.get("purpose") or properties.get("role") or ""
        narrative = f"{file_type} evidence" + (f" — {purpose}" if purpose else "")
    elif label == "Contract":
        source_path = str(properties.get("source_path") or node_id.removeprefix("Contract:"))
        display = str(properties.get("contract_reference") or Path(source_path).name or "Contract")
        sublabel = str(properties.get("vendor_id") or source_path)
        ref = properties.get("contract_reference") or ""
        vendor = properties.get("vendor_id") or ""
        narrative = f"Contract {ref}" + (f" — vendor {vendor}" if vendor else "") if ref else f"Contract linked to {vendor}" if vendor else "Contract"
    elif label == "Invoice":
        display = str(properties.get("invoice_id") or node_id.removeprefix("Invoice:"))
        amount = _kg_amount(properties.get("amount_sar"))
        sublabel = f"SAR {amount:,.0f}" if amount else str(properties.get("status") or "Invoice")
        status = properties.get("status") or "unknown status"
        vendor = properties.get("vendor_id") or ""
        parts = [f"SAR {amount:,.0f}" if amount else "Amount pending", status]
        if vendor:
            parts.append(f"vendor {vendor}")
        narrative = " | ".join(parts)
    elif label == "PurchaseOrder":
        display = str(properties.get("po_id") or node_id.removeprefix("PurchaseOrder:"))
        amount = _kg_amount(properties.get("total"))
        sublabel = f"SAR {amount:,.0f}" if amount else str(properties.get("status") or "Purchase order")
        status = properties.get("status") or "unknown status"
        vendor = properties.get("vendor_id") or ""
        parts = [f"SAR {amount:,.0f}" if amount else "Total pending", status]
        if vendor:
            parts.append(f"vendor {vendor}")
        narrative = " | ".join(parts)
    return {
        "id": node_id,
        "label": label,
        "display": display,
        "sublabel": sublabel,
        "narrative": narrative,
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
        "display_label": EDGE_LABEL_DISPLAY_MAP.get(label, label),
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

    # Compute narrative summary from raw graph data
    finding_nodes = [n for n in raw_nodes if _kg_node_label(n) == "Finding"]
    vendor_nodes = [n for n in raw_nodes if _kg_node_label(n) == "Vendor"]
    evidence_nodes = [n for n in raw_nodes if _kg_node_label(n) == "Evidence"]
    total_findings = len(finding_nodes)
    total_vendors = len(vendor_nodes)
    total_evidence = len(evidence_nodes)
    total_recoverable = sum(
        _kg_amount(_kg_node_properties(n).get("recoverable_sar")) for n in finding_nodes
    )
    most_significant = ""
    if finding_nodes:
        best = max(
            finding_nodes,
            key=lambda n: _kg_amount(_kg_node_properties(n).get("recoverable_sar")),
        )
        best_props = _kg_node_properties(best)
        best_sar = _kg_amount(best_props.get("recoverable_sar"))
        best_id = best_props.get("finding_id") or _kg_node_id(best)
        most_significant = f"{best_id} (SAR {best_sar:,.0f})" if best_sar else str(best_id)

    narrative_parts = [
        f"{total_findings} finding{'s' if total_findings != 1 else ''} identified",
        f"across {total_evidence} evidence document{'s' if total_evidence != 1 else ''}",
        f"involving {total_vendors} vendor{'s' if total_vendors != 1 else ''}",
        f"with SAR {total_recoverable:,.0f} total recoverable exposure",
    ]
    narrative_summary = " ".join(narrative_parts)
    if most_significant:
        narrative_summary += f". Most significant: {most_significant}"

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
            "narrative_summary": narrative_summary,
            "total_findings": total_findings,
            "total_vendors": total_vendors,
            "total_evidence_documents": total_evidence,
            "total_recoverable_sar": total_recoverable,
            "most_significant_finding": most_significant,
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
        finding_id = item.get("finding_id")
        if not finding_id:
            continue
        normalized_id = str(finding_id)
        if action == "challenge" or status_value == "challenged":
            challenged.add(normalized_id)
        elif action in {"response", "lock", "close", "resolve"} or status_value in {
            "responded",
            "locked",
            "closed",
            "resolved",
        }:
            challenged.discard(normalized_id)
    return sorted(challenged)


def _historically_challenged_finding_ids_from_audit_log(
    payload: dict[str, Any] | list[dict[str, Any]] | None,
) -> list[str]:
    if isinstance(payload, dict):
        events = payload.get("events") or payload.get("records") or payload.get("items") or []
    else:
        events = payload or []
    return sorted(
        {
            str(item.get("finding_id"))
            for item in events
            if isinstance(item, dict)
            and item.get("finding_id")
            and (
                str(item.get("action") or "").lower() == "challenge"
                or str(item.get("status") or "").lower() == "challenged"
            )
        }
    )


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
    login_redirect = _login_or_authorized_html(principal)
    if login_redirect is not None:
        return login_redirect
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
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> Any:
    login_redirect = _login_or_authorized_html(principal)
    if login_redirect is not None:
        return login_redirect
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
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> Any:
    login_redirect = _login_or_authorized_html(principal)
    if login_redirect is not None:
        return login_redirect
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
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> Any:
    login_redirect = _login_or_authorized_html(principal)
    if login_redirect is not None:
        return login_redirect
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
def architecture_page(
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> Any:
    """Serve the architecture evolution page."""
    login_redirect = _login_or_authorized_html(principal)
    if login_redirect is not None:
        return login_redirect
    template_path = STATIC_DIR / "architecture.html"
    return HTMLResponse(template_path.read_text(encoding="utf-8"))


@app.get("/guide", response_class=HTMLResponse)
def guide_page(
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> Any:
    """Serve the non-technical StrategyOS user guide."""
    login_redirect = _login_or_authorized_html(principal)
    if login_redirect is not None:
        return login_redirect
    template_path = STATIC_DIR / "guide.html"
    return HTMLResponse(template_path.read_text(encoding="utf-8"))


@app.get("/plan", response_class=HTMLResponse)
def plan_page(
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> Any:
    """Serve the Digital Twin execution plan page."""
    login_redirect = _login_or_authorized_html(principal)
    if login_redirect is not None:
        return login_redirect
    template_path = STATIC_DIR / "plan.html"
    return HTMLResponse(template_path.read_text(encoding="utf-8"))


def _plan_tracker_payload() -> dict[str, Any]:
    summary = _latest_summary()
    rows = _finding_rows_from_summary(summary) if summary else []
    audit_summary = _latest_run_audit_summary_payload(summary) if summary else None
    plan_health = _bounded_plan_health_payload(summary, rows, audit_summary)
    publication = _summary_publication_payload(summary, principal_role="operator") if summary else {}
    db_status = _data_management_status_for_run(str((summary or {}).get("run_id") or "") or None)
    updated = str(
        (summary or {}).get("created_at")
        or ((summary or {}).get("latest_pointer") or {}).get("updated_at")
        or datetime.now(UTC).date().isoformat()
    )
    challenged_count = sum(1 for row in rows if row.get("challenged"))
    report_count = int(publication.get("report_count") or 0)
    approval_status = str((summary or {}).get("approval_status") or "missing").replace("_", " ")
    blocker_detail = db_status.get("reason") or "State store is unavailable."
    critical_blockers = []
    if db_status.get("status") != "ready":
        critical_blockers.append(
            {
                "id": "DB-UNAVAILABLE",
                "title": "Database-backed tracker truth is unavailable",
                "detail": blocker_detail,
                "status": "open",
            }
        )
    active_action_items = []
    if summary and challenged_count:
        active_action_items.append(
            {
                "id": "REVIEW-GATE",
                "description": f"Close {challenged_count} challenged case(s) before widening the executive surface.",
                "assignee": "Reviewer",
                "status": "in_progress",
                "percentDone": 0,
            }
        )
    if summary and approval_status not in {"approved", "not required"}:
        active_action_items.append(
            {
                "id": "APPROVAL",
                "description": "Capture the next governed reviewer/operator decision for the latest run.",
                "assignee": "Operator",
                "status": "pending",
                "percentDone": 0,
            }
        )
    check_result = "pass" if db_status.get("status") == "ready" else "fail"
    return {
        "updated": updated,
        "liveStatus": {
            "state": (
                f"Current governed run: {plan_health.get('label') or 'Unavailable'}"
                if summary
                else "No governed run is available for /plan."
            ),
            "lastVerified": updated,
            "note": plan_health.get("summary") or blocker_detail,
        },
        "criticalBlockers": critical_blockers,
        "activeActionItems": active_action_items,
        "hostedVerificationState": {
            "summary": (
                "Pass — tracker is backed by current governed data sources."
                if check_result == "pass"
                else "Unavailable — tracker cannot claim DB-backed execution truth in this environment."
            ),
            "lastChecked": updated,
            "checks": [
                {
                    "label": "Database-backed run store availability",
                    "result": check_result,
                    "note": (
                        blocker_detail
                        if check_result == "fail"
                        else f"Run {summary.get('run_id')} is backed by persisted governed data."
                        if summary
                        else "Database is ready, but no governed run has been persisted yet."
                    ),
                },
                {
                    "label": "Latest governed run visibility",
                    "result": "pass" if summary else "fail",
                    "note": (
                        f"Run {summary.get('run_id')} with {report_count} surfaced {'report' if report_count == 1 else 'reports'} and approval posture {approval_status}."
                        if summary
                        else "No governed run is available yet."
                    ),
                },
            ],
        },
        "backlog": {
            "title": "Later hardening / backlog",
            "summary": "Only real remaining work belongs here; static narrative is not used as tracker truth.",
            "rows": [],
        },
        "completedHistory": [],
    }


@app.get("/api/plan/latest")
def latest_plan_tracker(
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> dict[str, Any]:
    _require_login_if_enabled(principal)
    return _plan_tracker_payload()


@app.get("/twin/ceo", response_class=HTMLResponse)
def twin_ceo_dashboard(
    principal: dict[str, Any] = require_twin_dashboard_access("ceo"),
) -> RedirectResponse:
    """Open the live, database-backed CEO twin in the executive network."""
    return RedirectResponse(url="/app?persona=ceo&agent=ceo", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/twin/cfo", response_class=HTMLResponse)
def twin_cfo_dashboard(
    principal: dict[str, Any] = require_twin_dashboard_access("cfo"),
) -> RedirectResponse:
    """Open the live, database-backed CFO twin in the executive network."""
    return RedirectResponse(url="/app?persona=ceo&agent=cfo", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/twin/gm", response_class=HTMLResponse)
def twin_gm_dashboard(
    principal: dict[str, Any] = require_twin_dashboard_access("gm"),
) -> RedirectResponse:
    """Open the live, database-backed Group Manager twin in the executive network."""
    return RedirectResponse(url="/app?persona=ceo&agent=group_manager", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/ui/session")
def ui_session(
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> dict[str, Any]:
    _require_login_if_enabled(principal)
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
    _require_login_if_enabled(principal)
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
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> dict[str, Any]:
    _require_login_if_enabled(principal)
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
def public_latest_run_audit_summary(
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> dict[str, Any]:
    _require_login_if_enabled(principal)
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


@app.post("/executive/findings/request-recovery")
def request_finding_recovery(
    request: FindingDirectiveRequest,
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> dict[str, Any]:
    """Record a CEO's directive to recover a finding, for the reviewer to action.

    This is not an approval -- the reviewer gate still owns the status
    transition. It is the executive putting their intent on the record: "recover
    this", logged to the run's audit trail with who and when, so the request
    reaches the reviewer through the governed flow instead of a UI toast that
    vanishes. A read-only list becomes something the CEO can act on without
    bypassing the review that makes the number defensible.
    """
    if not principal.get("authenticated"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to request recovery.",
        )
    finding_id = str(request.finding_id or "").strip()
    if not finding_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A finding id is required.",
        )
    summary = load_latest_run_summary()
    run_id = str((summary or {}).get("run_id") or "").strip()
    if not run_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No current run is loaded to attach this request to.",
        )
    # Only accept a directive against a finding this run actually holds; never
    # log a request for an id the run cannot show.
    snapshot = state_store.executive_snapshot_for_run(run_id)
    known_ids = {
        str(row.get("finding_id") or "")
        for row in (snapshot.get("findings") or [])
        if isinstance(row, dict)
    }
    if snapshot.get("status") == "ok" and finding_id not in known_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding '{finding_id}' is not part of the current run.",
        )
    # The audit trail renders the actor to the executive. A raw IdP subject
    # ("https://strategyos.live/:executive.tester") is not a name; log the role
    # as a clean label and keep the exact subject in the event payload for the
    # record.
    subject = str(principal.get("subject") or "")
    actor = "Executive"
    note = str(request.note or "").strip()
    detail = f"Executive requested recovery of {finding_id}."
    if note:
        detail = f"{detail} Note: {note}"
    result = state_store.record_executive_directive(
        run_id,
        finding_id=finding_id,
        action="request_recovery",
        actor=actor,
        detail=detail,
        subject=subject,
    )
    if result.get("status") not in {"recorded", "skipped"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(result.get("reason") or "Could not record the recovery request."),
        )
    return {
        "status": "requested",
        "finding_id": finding_id,
        "message": "Recovery requested. Your reviewer will see this on the finding's audit trail.",
    }


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
    checkpoint = _checkpoint_with_latest_run_summary(run_id, checkpoint)
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
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
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
    authenticated = not _principal_prefers_public_safe_surface(principal)
    if summary is None:
        payload = {
            "status": "missing",
            "data_source": "unavailable",
            "data_source_status": "missing",
            "run_source": "current_run",
        }
        if authenticated:
            return payload
        return {**payload, "public_safe": True, "run_dir": str(CONFIG.default_run_dir)}
    if not authenticated:
        return _latest_run_public_payload(summary, view_state=view_state)
    if principal_has_any_role(str(principal.get("role") or ""), "bu"):
        return _sanitize_summary_for_bu(summary)
    return _summary_with_reconciled_metrics(summary, view_state=view_state, principal=principal)


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
    try:
        _, graph = _load_knowledge_graph_artifact(summary)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return []
        raise
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
                "challenged": finding_id in challenged_ids
                or str(props.get("status") or "").lower() == "challenged",
            }
        )
    rows.sort(key=lambda row: row["recoverable_sar"], reverse=True)
    return rows


def _latest_run_findings_payload(
    summary: dict[str, Any] | None,
    *,
    include_run_dir: bool,
    public_safe: bool,
    principal: dict[str, Any] | None = None,
    domain_filter: str | None = None,
    view_state: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    if public_safe:
        return _anonymous_public_findings_payload(
            summary,
            domain_filter=domain_filter,
            view_state=view_state,
        )
    principal = dict(principal or {
        "role": "operator",
        "authenticated": True,
    })
    role = str(principal.get("role") or "operator")
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
        principal_role=role,
        public_safe=public_safe,
    )
    board_portal = _board_portal_payload(
        summary,
        principal_role=role,
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
        f"Review posture: {summary.get('approval_status') or 'pending'} with {len(findings)} {'finding' if len(findings) == 1 else 'findings'} and {challenged} challenged {'item' if challenged == 1 else 'items'}.",
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
        include_run_dir=not _principal_prefers_public_safe_surface(principal),
        public_safe=_principal_prefers_public_safe_surface(principal),
        principal=principal,
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
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> dict[str, Any]:
    _require_login_if_enabled(principal)
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
        public_safe=_principal_prefers_public_safe_surface(principal),
    )


@app.get("/public/runs/latest/cases/{case_id}")
def public_latest_run_case(
    case_id: str,
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> dict[str, Any]:
    _require_login_if_enabled(principal)
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
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> dict[str, Any]:
    _require_login_if_enabled(principal)
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
    principal: dict[str, Any] = Depends(authenticate_optional_request),
) -> dict[str, Any]:
    _require_login_if_enabled(principal)
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
    rows = _anonymous_public_finding_payloads(_finding_rows_from_summary(summary))
    audit_summary = _latest_run_audit_summary_payload(summary)
    principal = {"role": "executive", "authenticated": False}
    publication = _summary_publication_payload(summary, principal_role="executive", public_safe=True)
    board_portal = _board_portal_payload(
        summary,
        principal_role="executive",
        public_safe=True,
        requested_state=view_state.get("board"),
    )
    strategy_substrate = _strategy_substrate_payload(summary, rows, audit_summary, principal)
    agent_modules = _agent_modules_payload(summary, rows, audit_summary, principal)
    public_context_packet = _build_public_safe_assistant_packet(
        summary,
        persona_id=str(view_state.get("persona") or persona or "ceo"),
        finding_rows=rows,
        audit_summary=audit_summary,
        publication=publication,
        board_portal=board_portal,
        strategy_substrate=strategy_substrate,
        agent_modules=agent_modules,
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
    assistant_findings = list(merged_packet.get("finding_case_index") or merged_packet.get("findings") or [])
    for index, item in enumerate(assistant_findings):
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


# ── Claim integrity ────────────────────────────────────────────────────────
#
# The assistant modelled the run's release state in depth but had no concept of
# a *user claim*: every question was treated as a query, never as an assertion
# that might be false. That single gap produced the whole family of executive
# failures -- confirming "the board says we can recover SAR 5 million" against a
# SAR 794,108 baseline, answering "why did revenue drop 12%" (it did not drop)
# by describing the Revenue KPI, and handing over a bare number when told "no
# caveats". Correcting each phrasing would be a patch; the fix is to give the
# assistant the missing concept and apply it at the one chokepoint every answer
# passes through.


_CLAIM_VERB_RE = re.compile(
    r"\b(?:say|says|said|claim|claims|claimed|told|reckon|reckons|think|thinks|"
    r"believe|believes|confirm|confirms|confirmed|assume|assumes|assumed|"
    r"heard|reported|reports|promised?)\b",
    re.IGNORECASE,
)

_CHANGE_CLAIM_RE = re.compile(
    r"\b(?:drop(?:ped)?|fell|fall(?:en)?|decline[ds]?|down|rose|risen|grew|grow|"
    r"increase[ds]?|jump(?:ed)?|up|improve[ds]?|worsen(?:ed)?)\b",
    re.IGNORECASE,
)

_PRESSURE_RE = re.compile(
    r"\b(?:no caveats?|without caveats?|just (?:give|tell)|one number|"
    r"skip the|don'?t hedge|straight answer|simple answer|yes or no)\b",
    re.IGNORECASE,
)

_PROMISE_RE = re.compile(
    r"\b(?:promise|commit(?:ment)?|guarantee|bank on|tell the board|"
    r"announce|pledge)\b",
    re.IGNORECASE,
)


def _extract_user_claims(question: str) -> list[dict[str, Any]]:
    """What did the executive assert as fact, as opposed to ask?

    Only figures presented as established ("the board says we can recover SAR
    5 million", "why did revenue drop 12%") are claims. A hypothetical ("if we
    recover SAR 400,000") asserts nothing and must stay untouched so the
    scenario engine keeps owning it.
    """
    text = str(question or "")
    if not text.strip():
        return []
    norm = " ".join(text.casefold().split())
    # A conditional is a question about a possibility, not a claim of fact.
    if re.search(r"\b(?:if|suppose|assuming|what if|imagine|hypothetical)\b", norm):
        return []

    claims: list[dict[str, Any]] = []
    asserted = bool(_CLAIM_VERB_RE.search(norm)) or bool(_CHANGE_CLAIM_RE.search(norm))
    if not asserted:
        return []

    for amount in _parse_amount_references(text):
        claims.append({"kind": "amount", "value": float(amount)})
    for raw in re.findall(r"(\d+(?:\.\d+)?)\s*%", text):
        try:
            claims.append({"kind": "percent", "value": float(raw)})
        except ValueError:
            continue
    return claims


def _governed_amount_facts(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every headline figure the run can be held to, with its own label."""
    facts: list[dict[str, Any]] = []
    for entity in _governed_entity_index_safe(context):
        amount = entity.get("amount")
        if amount:
            facts.append(
                {
                    "label": str(entity.get("label") or "figure"),
                    "value": float(amount),
                    "kind": entity.get("kind"),
                }
            )
    total = 0.0
    for entity in _governed_entity_index_safe(context):
        if entity.get("kind") == "finding" and entity.get("amount"):
            total += float(entity["amount"])
    if total:
        facts.append({"label": "total recoverable value", "value": total, "kind": "total"})
    return facts


def _claim_contradiction(
    question: str,
    context: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Does the run contradict a figure the executive stated as fact?

    Returns the correction to lead with, or None when nothing is asserted or
    the assertion agrees with the run.
    """
    claims = _extract_user_claims(question)
    if not claims:
        return None
    facts = _governed_amount_facts(context)
    if not facts:
        return None

    for claim in claims:
        if claim["kind"] != "amount":
            continue
        value = claim["value"]
        if value <= 0:
            continue
        # An asserted amount is credible only if some governed figure matches
        # it. Nearest comparable anchors the correction.
        if any(_amounts_match(value, fact["value"]) for fact in facts):
            continue
        recoverable = next((f for f in facts if f["kind"] == "total"), None)
        anchor = recoverable or min(facts, key=lambda f: abs(f["value"] - value))
        return {
            "claimed": value,
            "anchor_label": anchor["label"],
            "anchor_value": anchor["value"],
        }
    return None


def _unverifiable_change_claim(question: str, context: Mapping[str, Any]) -> dict[str, Any] | None:
    """Did the executive assert a movement this run cannot check?

    "Since revenue dropped 40% last quarter, what should I cut?" states a change
    as settled fact. The run reports one period; it holds no prior-period
    comparator, so it can neither confirm nor deny the drop. Answering the
    question as asked accepts the premise by silence and lets a false number
    become the basis of a decision -- which is the failure this layer exists to
    prevent.

    Correcting it with a governed total would be worse: a period-over-period
    movement and a balance are different quantities, and matching them would
    manufacture a contradiction out of a category error. So the honest answer is
    the narrow one -- the run cannot verify this, and here is why.
    """
    claims = [claim for claim in _extract_user_claims(question) if claim["kind"] == "percent"]
    if not claims:
        return None
    if not _CHANGE_CLAIM_RE.search(" ".join(str(question or "").casefold().split())):
        return None
    # Only speak when a governed run is actually loaded; with no run, the
    # ordinary "no evidence" path already says the right thing.
    if not isinstance(context, Mapping):
        return None
    if not context.get("run_id") and not context.get("findings"):
        return None
    period = _governed_reporting_period(context)
    return {"claimed_pct": claims[0]["value"], "period": period}


def _governed_reporting_period(context: Mapping[str, Any]) -> str | None:
    summary = context.get("summary") if isinstance(context, Mapping) else None
    if not isinstance(summary, Mapping):
        return None
    for key in ("finance_kpi", "oracle_kpi"):
        payload = summary.get(key)
        if isinstance(payload, Mapping):
            period = payload.get("reporting_period_key")
            if period:
                return str(period)
    period = summary.get("reporting_period")
    return str(period) if period else None
    return None


def _release_posture(context: Mapping[str, Any]) -> str | None:
    """The governance status any promisable number must carry with it."""
    summary = context.get("summary") if isinstance(context.get("summary"), Mapping) else {}
    if not isinstance(summary, Mapping):
        return None
    if summary.get("requires_human_review"):
        return "not yet approved for release -- the reviewer decision is still open"
    publication = summary.get("publication") if isinstance(summary.get("publication"), Mapping) else {}
    state = str(publication.get("publish_state") or summary.get("approval_status") or "").strip().casefold()
    if state and state not in {"approved", "published", "released"}:
        return f"not yet approved for release (current state: {state})"
    return None


def _apply_claim_integrity(
    payload: dict[str, Any],
    *,
    question: str,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Make the answer honest about the executive's own premise.

    Runs at the single point every answer -- deterministic, scenario or model --
    passes through, so no route can quietly skip it.
    """
    answer = str(payload.get("answer") or "").strip()
    if not answer:
        return payload

    prefix_parts: list[str] = []

    contradiction = _claim_contradiction(question, context)
    if contradiction is not None:
        prefix_parts.append(
            f"That figure is not supported by this run: {_format_sar_brief(contradiction['claimed'])} "
            f"does not match the governed {contradiction['anchor_label']} of "
            f"{_format_sar_brief(contradiction['anchor_value'])}."
        )
        payload["claim_verdict"] = "contradicted"
        payload["claim_checked"] = {
            "claimed_sar": contradiction["claimed"],
            "governed_label": contradiction["anchor_label"],
            "governed_sar": contradiction["anchor_value"],
        }
    else:
        change_claim = _unverifiable_change_claim(question, context)
        if change_claim is not None:
            period = change_claim["period"]
            scope = f" and reports {period} only" if period else ""
            prefix_parts.append(
                f"I cannot confirm that {_format_percent_brief(change_claim['claimed_pct'])} movement: "
                f"this run holds no prior-period comparator{scope}, so the change is neither "
                f"verified nor ruled out here. Treating it as settled would put a number I cannot "
                f"check underneath your decision."
            )
            payload["claim_verdict"] = "unverifiable"
            payload["claim_checked"] = {
                "claimed_pct": change_claim["claimed_pct"],
                "governed_period": period,
            }

    # "No caveats / one number I can promise" may change the shape of an
    # answer, never its truth: a figure still under review must never leave
    # this surface stripped of that fact.
    posture = _release_posture(context)
    asks_to_promise = bool(_PROMISE_RE.search(question or ""))
    pressures = bool(_PRESSURE_RE.search(question or ""))
    if posture and (asks_to_promise or pressures) and re.search(r"\bSAR\b", answer):
        prefix_parts.append(
            f"This figure is {posture}, so it cannot be presented as a commitment."
        )
        payload["claim_verdict"] = payload.get("claim_verdict") or "release_guarded"

    if prefix_parts:
        payload["answer"] = " ".join(prefix_parts) + " " + answer
        # An answer built on a refuted premise has not earned a confidence
        # badge; the label described retrieval, not reasoning.
        if payload.get("claim_verdict") == "contradicted":
            payload["grounding_status"] = "corrected"

    payload["answer"] = _honour_suggestion_promise(
        str(payload.get("answer") or ""),
        suggestions=payload.get("suggestions"),
    )
    return payload


def _honour_suggestion_promise(answer: str, *, suggestions: Any) -> str:
    """An answer must not promise a list it does not carry.

    Several refusals end "Try one of these:" and rely on the caller having
    populated suggestions; when it has not, the executive reads a sentence that
    stops at a colon. Enforced centrally rather than by editing each copy site,
    so a future refusal cannot reintroduce the dangling promise.
    """
    text = str(answer or "").strip()
    if not text.endswith(":"):
        return text
    has_suggestions = isinstance(suggestions, list) and any(
        str(item or "").strip() for item in suggestions
    )
    if has_suggestions:
        return text
    return re.sub(r"\s*(?:Try one of these|Try any of these|Try):\s*$", "", text).strip() or text


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
        "answered_by": getattr(orchestrated, "answered_by", ""),
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
                    "answered_by": getattr(orchestrated, "answered_by", ""),
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
        scenario_risk_level = str((payload["hallucination_risk"] or {}).get("level") or "").lower()
        if not payload.get("grounding_status"):
            if scenario_risk_level == "none" and payload["citations"]:
                payload["grounding_status"] = "grounded"
            elif str(scenario_result.get("scenario_type") or "") == "missing_data":
                payload["grounding_status"] = "needs_evidence"
    answer_is_model_provided = (
        str(payload.get("answered_by") or "").strip().lower() == "llm"
        or str(payload.get("assistant_mode") or "").strip().lower() == "llm"
        or (
            response_mode == "llm"
            and str((base_result or {}).get("answered_by") or "").strip().lower() == "llm"
        )
    )
    if answer_is_model_provided:
        # This is a product contract, not optional explanatory copy. A model
        # answer may synthesize governed evidence, but it is never presented as
        # a governed calculation. Every Hermes surface renders these fields.
        payload["answer_origin"] = "llm"
        payload["answered_by"] = "llm"
        payload["assistant_mode"] = "llm"
        payload["calculation_status"] = "not_calculated"
        payload["review_status"] = "required"
        payload["human_review_required"] = True
        payload["model_answer_disclosure"] = (
            "LLM-provided answer; not a governed calculation; human review required."
        )
    else:
        payload.setdefault("answer_origin", "governed")
        payload.setdefault("human_review_required", False)
    payload["answer"] = _sanitize_assistant_visible_text(payload.get("answer"))
    # Last gate before the executive reads it: correct any premise the run
    # refutes, and never let a figure under review leave as a commitment.
    # Placed here so deterministic, scenario and model answers are all covered.
    payload = _apply_claim_integrity(payload, question=question, context=context)
    return payload


def _public_safe_llm_status() -> dict[str, Any]:
    status_payload = dict(llm_qa.chat_status(CONFIG) or {})
    status_payload["public_safe"] = True
    status_payload["evidence_scope"] = "public_executive_packet_only"
    return status_payload


def _route_keyword_retrieval(run_id: str | None, question: str) -> dict[str, Any]:
    if not CONFIG.vector_routing_enabled:
        return {"matched": False, "answered_by": "", "reason": "vector_routing_disabled"}
    lower_question = str(question or "").lower()
    if not any(term in lower_question for term in ("evidence", "document", "documents", "invoice", "contract", "source", "support", "proof", "finding")):
        return {"matched": False, "answered_by": "", "reason": "question_not_routed"}
    qdrant_status = check_qdrant_ready()
    if qdrant_status.get("status") != "ok":
        return {"matched": False, "answered_by": "", "vector_status": qdrant_status}
    result = search_run_vectors(run_id, question, limit=3)
    if result.get("status") != "ready" or not result.get("results"):
        return {"matched": False, "answered_by": "", "vector_status": result}
    citations = []
    for item in list(result.get("results") or [])[:3]:
        locator = str(item.get("locator") or item.get("finding_id") or item.get("point_id") or "")
        citations.append(
            {
                "source_path": item.get("source_path") or item.get("source") or "qdrant://strategyos_search_chunks",
                "locator": locator,
                "excerpt": item.get("excerpt") or item.get("summary") or item.get("text") or "",
            }
        )
    top = result["results"][0]
    answer = (
        f"Keyword retrieval found {len(result['results'])} supporting record(s). "
        f"Top match: {top.get('title') or top.get('summary') or top.get('finding_id') or 'supporting evidence'}"
    )
    return {
        "matched": True,
        "answer": answer,
        "basis": "Keyword/lexical overlap over run-scoped Qdrant payloads while the embedding backend is hash_fallback.",
        "citations": citations,
        "suggestions": [],
        "assistant_mode": "vector",
        "answered_by": "vector",
        "intent": "keyword_retrieval",
        "vector_status": result,
    }


def _sanitize_assistant_visible_text(value: Any) -> str:
    text = llm_qa._clean_visible_answer(value)
    return str(text or "").strip()


def _assistant_history_from_request(request: AssistantChatRequest | QaRequest) -> list[dict[str, Any]]:
    """Normalize client-supplied chat history for follow-up grounding.

    The executive drawer owns thread history in browser storage.  The backend
    still needs the previous answer payload to resolve follow-ups like
    ``Elaborate on SAR 109.9M`` against the exact KPI row that produced the
    prior answer, rather than re-deriving from a bare amount.
    """
    candidates: Any = getattr(request, "history", None)
    if candidates is None:
        request_context = getattr(request, "context", None)
        if isinstance(request_context, Mapping):
            candidates = request_context.get("history") or request_context.get("messages")
    if candidates is None:
        assistant_context = getattr(request, "assistant_context", None)
        if isinstance(assistant_context, Mapping):
            candidates = assistant_context.get("history") or assistant_context.get("messages")
    if not isinstance(candidates, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in candidates[-8:]:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or item.get("speaker") or "").strip().lower()
        text = str(item.get("text") or item.get("content") or item.get("answer") or "").strip()
        payload = item.get("payload") or item.get("responsePayload") or item.get("response_payload")
        provenance = item.get("assistant_context") or item.get("context") or item.get("provenance")
        if not text and not isinstance(payload, Mapping) and not isinstance(provenance, Mapping):
            continue
        normalized.append(
            {
                "role": role if role in {"user", "assistant", "system"} else "assistant",
                "text": text[:2000],
                "payload": dict(payload) if isinstance(payload, Mapping) else None,
                "assistant_context": dict(provenance) if isinstance(provenance, Mapping) else None,
            }
        )
    return normalized


_EXTERNAL_DECISION_EVIDENCE_PATTERNS = (
    r"\bacquir(?:e|ing|ed|isition)\b",
    r"\bcompetitor\b",
    r"\bmerger\b",
    r"\bmarket share\b",
    r"\bvaluation\b",
    r"\bdue diligence\b",
)


def _unavailable_external_decision_result(
    question: str,
    context: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Fail closed for decisions that need evidence outside a finance run.

    This is a data-capability boundary, not a list of pre-written answers. It
    prevents an external model from mistaking a finance/controls run for market
    or transaction diligence and makes the scope visible to an executive.
    """
    normalized = " ".join(str(question or "").casefold().split())
    if not any(re.search(pattern, normalized) for pattern in _EXTERNAL_DECISION_EVIDENCE_PATTERNS):
        return None
    bundle = context.get("bundle")
    metadata = getattr(bundle, "run_metadata", {}) if bundle is not None else {}
    roles = [str(role) for role in list(metadata.get("available_roles") or []) if str(role)] if isinstance(metadata, Mapping) else []
    summary = context.get("summary") if isinstance(context.get("summary"), Mapping) else {}
    has_finance_kpis = isinstance(summary.get("finance_kpi") or summary.get("oracle_kpi"), Mapping)
    scope: list[str] = []
    if "ap_ledger" in roles:
        scope.append("AP ledger")
    if "ar_ledger" in roles:
        scope.append("AR ledger")
    if "gl_extract" in roles or has_finance_kpis:
        scope.append("GL-derived finance KPIs")
    if "cash_forecast" in roles:
        scope.append("cash-position data")
    scope_text = ", ".join(scope) if scope else "the current governed finance and controls run"
    return {
        "matched": False,
        "answer": (
            "I cannot support that decision from the current governed run. "
            f"It contains {scope_text}, but not market, competitive, valuation, legal, or transaction-diligence evidence. "
            "Provide those approved inputs before asking Hermes for a recommendation."
        ),
        "citations": [],
        "suggestions": [
            "What is driving revenue now?",
            "What needs to change to reach a 60% EBITDA margin?",
            "What evidence is missing for this decision?",
        ],
        "basis": "Governed evidence-scope boundary; no external-decision recommendation was inferred from a finance run.",
        "answered_by": "evidence_scope_boundary",
        "grounding_status": "needs_evidence",
        "_orchestrator_force_answer": True,
    }


def _public_safe_general_answer(question: str) -> dict[str, Any] | None:
    norm = " ".join(str(question or "").lower().split())
    direct_answers = {
        "capital of france": "Paris is the capital of France.",
        "capital city of france": "Paris is the capital of France.",
    }
    for needle, answer in direct_answers.items():
        if needle in norm:
            return {
                "matched": True,
                "answer": f"{answer} That is a general-knowledge answer and is not drawn from the current StrategyOS board packet.",
                "citations": [],
                "suggestions": ["What should I prepare for the board?", "What is driving margin pressure?", "Which challenged items need closure?"],
                "basis": "Deterministic public-safe general-knowledge answer; no model call used.",
            }
    return None


def _assistant_question_is_app_help(question: str) -> bool:
    norm = " ".join(str(question or "").lower().split())
    if not norm:
        return False
    file_terms = (
        "file", "files", "dataset", "data set", "source pack", "sources",
        "zip", "folder", "spreadsheet", "invoice", "ledger",
    )
    workflow_terms = (
        "process", "upload", "ingest", "load", "add", "import", "stage",
        "run", "analyse", "analyze", "start analysis", "new analysis",
        "through the app", "in the app", "using the app",
    )
    if "source pack" in norm or "start analysis" in norm or "new analysis" in norm:
        return True
    return any(term in norm for term in file_terms) and any(term in norm for term in workflow_terms)


def _authenticated_app_help_result(question: str, *, role: str) -> dict[str, Any] | None:
    if not _assistant_question_is_app_help(question):
        return None
    role_name = str(role or "anonymous").strip().lower() or "anonymous"
    can_operate = principal_has_any_role(role_name, "operator")
    if can_operate:
        role_sentence = "Your current role can start this workflow."
    else:
        role_sentence = (
            f"Your current role is {role_name}; it can ask Hermes and view governed outputs, "
            "but file upload and run launch require operator, tenant_operator, tenant_admin, or system access."
        )
    answer = (
        "To process new files in StrategyOS: "
        f"{role_sentence} "
        "Open the operator lane at /app?lane=operate, then use Prepare source pack / Start analysis. "
        "Upload a ZIP source pack or choose a folder from your machine. "
        "StrategyOS stages the files through /source-packs, validates readability, classifies finance roles, "
        "and asks you to confirm spreadsheet column mappings when needed. "
        "When the pack is ready, click Start analysis; if required files are missing, upload the missing files "
        "or enable partial analysis in Advanced settings. "
        "The run then goes to human review; a reviewer approves or rejects it. "
        "After approval, an operator resumes/publishes the run, and the CEO/executive pages read the latest governed run."
    )
    return {
        "matched": True,
        "answer": answer,
        "basis": "Authenticated StrategyOS app workflow help; this is product/runtime guidance, not board-pack evidence.",
        "citations": [
            {
                "source_path": "strategyos://app",
                "locator": "/app?lane=operate -> /source-packs -> /runs -> /reviewer/runs/{run_id}/approve -> /operator/runs/{run_id}/resume",
                "excerpt": "Operator source-pack upload, validation, run launch, review, and publish workflow.",
            }
        ],
        "suggestions": [
            "Which role do I need to upload files?",
            "What files should be in a complete source pack?",
            "What happens after I start analysis?",
        ],
        "assistant_mode": "app_help",
        "answered_by": "app_help",
        "intent": "app_file_processing_help",
        "_orchestrator_force_answer": True,
    }


def _assistant_question_is_calendar_agenda(question: str) -> bool:
    """Return true only for an explicit CEO calendar/meeting request."""
    norm = " ".join(str(question or "").casefold().split())
    if any(term in norm for term in ("calendar", "agenda")):
        return True
    asks_about_meeting = bool(re.search(r"\b(meeting|appointment)\b", norm))
    asks_about_timing = any(
        term in norm
        for term in ("next", "upcoming", "today", "tomorrow", "scheduled", "prepare")
    )
    return asks_about_meeting and asks_about_timing


def _calendar_item_date(item: Mapping[str, Any]) -> date | None:
    raw_date = str(item.get("date") or item.get("event_date") or "").strip()
    if not raw_date:
        match = re.search(r"calendar-(\d{4}-\d{2}-\d{2})-", str(item.get("event_id") or ""))
        raw_date = match.group(1) if match else ""
    try:
        return date.fromisoformat(raw_date)
    except ValueError:
        return None


def _requested_calendar_item_count(question: str, *, default: int = 1) -> int:
    """Return an explicit bounded quantity from a calendar request."""
    norm = " ".join(str(question or "").casefold().split())
    word_numbers = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    quantity_match = re.search(
        r"\b(?:next|upcoming|first)\s+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\b",
        norm,
    )
    if not quantity_match:
        return default
    raw = quantity_match.group(1)
    value = word_numbers.get(raw)
    if value is None:
        try:
            value = int(raw)
        except ValueError:
            return default
    return max(1, min(value, 10))


def _calendar_quick_action_result(
    item: Mapping[str, Any],
    agenda: Mapping[str, Any],
    *,
    action: str,
) -> dict[str, Any]:
    """Turn a governed calendar row into an executable CEO preparation output."""
    title = str(item.get("title") or "Executive commitment")
    item_date = _calendar_item_date(item)
    date_label = item_date.strftime("%a %d %b %Y") if item_date else str(item.get("day") or "Date not supplied")
    when = str(item.get("when") or "").strip()
    due_label = f"before {date_label}" + (f" at {when}" if when and when != str(item.get("date") or "") else "")
    event_type = str(item.get("type") or "Executive commitment")
    prep = str(item.get("prep") or "No preparation note was supplied.")
    related_bu = str(item.get("related_bu") or "").strip()
    attendees = str(item.get("attendees") or "").strip()
    recipient = attendees or (f"{related_bu} leadership" if related_bu else "the meeting sponsor and CEO Office")
    owner_gap = f"The calendar does not name the accountable input owner; confirm ownership with {recipient}."

    if action == "input_request":
        answer = "\n".join(
            [
                f"Draft input request — {title}",
                f"To: {recipient}",
                f"Due: {due_label}",
                "Please provide:",
                "- the exact decision required from the CEO;",
                "- the recommended option and the strongest alternative;",
                "- financial impact, execution risk and dependencies;",
                "- the accountable owner and the next dated milestone.",
                f"Calendar preparation note: {prep}",
                owner_gap,
            ]
        )
        intent = "calendar_input_request"
    else:
        answer = "\n".join(
            [
                f"{title} — CEO preparation brief",
                f"When: {date_label}" + (f" at {when}" if when and when != str(item.get("date") or "") else ""),
                f"Purpose: {event_type}" + (f" · {related_bu}" if related_bu else ""),
                f"Bring: {prep}",
                "Enter with: the decision sought, the recommended option, the downside of delay and a named execution owner.",
                f"Due point: {due_label}",
                owner_gap,
            ]
        )
        intent = "calendar_decision_brief"

    source_file = str(agenda.get("source_file") or "governed calendar workbook")
    sheet = str(agenda.get("sheet") or "Calendar")
    return {
        "matched": True,
        "answer": answer,
        "basis": "The requested preparation action was built from the selected calendar entry.",
        "citations": [
            {
                "source_path": source_file,
                "locator": f"{sheet} / {item.get('event_id') or date_label}",
                "excerpt": f"{title}; {date_label}; preparation: {prep}",
                "evidence_scope": str(item.get("evidence_scope") or agenda.get("evidence_scope") or "governed_calendar"),
            }
        ],
        "suggestions": [],
        "assistant_mode": "governed_calendar",
        "answered_by": "governed_calendar",
        "answer_origin": "governed",
        "intent": intent,
        "calendar_status": "ready",
        "calendar_item_count": int(agenda.get("total_item_count") or len(list(agenda.get("items") or []))),
        "calendar_projection_item_count": len(list(agenda.get("items") or [])),
        "_orchestrator_force_answer": True,
    }


def _governed_calendar_result(
    question: str,
    summary: Mapping[str, Any] | None,
    *,
    today: date | None = None,
    assistant_context: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Answer calendar questions from the run-scoped governed agenda only."""
    action_context = assistant_context if isinstance(assistant_context, Mapping) else {}
    quick_action = (
        str(action_context.get("calendar_action") or "").strip().casefold()
        if str(action_context.get("entrypoint") or "").strip().casefold() == "calendar_quick_action"
        else ""
    )
    if not _assistant_question_is_calendar_agenda(question) and quick_action not in {"brief", "input_request"}:
        return None
    agenda = summary.get("calendar_agenda") if isinstance(summary, Mapping) else None
    if not isinstance(agenda, Mapping):
        agenda = {}
    items = [item for item in list(agenda.get("items") or []) if isinstance(item, Mapping)]
    if str(agenda.get("status") or "").casefold() != "ready" or not items:
        reason = str(agenda.get("reason") or "No governed calendar workbook was supplied for this run.")
        return {
            "matched": True,
            "answer": f"The governed calendar is not available for this run. {reason}",
            "basis": "The run-scoped calendar agenda is unavailable; no schedule was inferred.",
            "citations": [],
            "suggestions": ["Which governed run is currently loaded?", "What should I prepare for the board?"],
            "assistant_mode": "governed_calendar",
            "answered_by": "governed_calendar",
            "answer_origin": "governed",
            "intent": "calendar_agenda",
            "_orchestrator_force_answer": True,
        }

    if quick_action in {"brief", "input_request"}:
        requested_title = " ".join(str(action_context.get("event_title") or "").casefold().split())
        requested_date = str(action_context.get("event_date") or "").strip()
        selected_item = next(
            (
                item
                for item in items
                if " ".join(str(item.get("title") or "").casefold().split()) == requested_title
                and (not requested_date or str(item.get("date") or "") == requested_date)
            ),
            None,
        )
        if selected_item is None:
            return {
                "matched": True,
                "answer": "That calendar commitment is no longer in the current approved agenda. Refresh Calendar before preparing it.",
                "basis": "The selected event could not be matched to the current calendar source.",
                "citations": [],
                "suggestions": [],
                "assistant_mode": "governed_calendar",
                "answered_by": "governed_calendar",
                "answer_origin": "governed",
                "intent": "calendar_item_not_found",
                "_orchestrator_force_answer": True,
            }
        return _calendar_quick_action_result(selected_item, agenda, action=quick_action)

    current_day = today or date.today()
    dated_items = [(item_date, item) for item in items if (item_date := _calendar_item_date(item)) is not None]
    dated_items.sort(key=lambda pair: pair[0])
    norm = " ".join(str(question or "").casefold().split())
    selected: list[tuple[date | None, Mapping[str, Any]]]
    status_sentence = ""
    if "tomorrow" in norm:
        target_day = current_day + timedelta(days=1)
        selected = [pair for pair in dated_items if pair[0] == target_day]
        status_sentence = (
            f"The governed agenda has no item for {target_day.strftime('%d %b %Y')}."
            if not selected
            else f"The governed agenda has {len(selected)} item(s) for tomorrow, {target_day.strftime('%d %b %Y')}."
        )
    elif "today" in norm:
        selected = [pair for pair in dated_items if pair[0] == current_day]
        status_sentence = (
            f"The governed agenda has no item for today, {current_day.strftime('%d %b %Y')}."
            if not selected
            else f"The governed agenda has {len(selected)} item(s) for today, {current_day.strftime('%d %b %Y')}."
        )
    elif any(term in norm for term in ("next", "upcoming")):
        upcoming = [pair for pair in dated_items if pair[0] >= current_day]
        if upcoming:
            requested_count = _requested_calendar_item_count(norm)
            selected = upcoming[:requested_count]
            if requested_count == 1:
                status_sentence = "The next item in the governed agenda is:"
            else:
                status_sentence = (
                    f"The next {len(selected)} item(s) in the governed agenda are:"
                    if len(selected) < requested_count
                    else f"The next {requested_count} items in the governed agenda are:"
                )
        else:
            selected = dated_items[-1:] if dated_items else [(None, items[-1])]
            status_sentence = (
                f"The governed calendar is connected, but it contains no event on or after "
                f"{current_day.strftime('%d %b %Y')}. I will not present a past item as upcoming. "
                "The latest supplied item is:"
            )
    else:
        selected = [(_calendar_item_date(item), item) for item in items[:3]]
        total_item_count = int(agenda.get("total_item_count") or len(items))
        status_sentence = (
            f"The governed calendar is connected with {total_item_count} processed agenda item(s); "
            f"{len(items)} are in the current CEO projection."
        )

    detail_lines: list[str] = []
    citations: list[dict[str, Any]] = []
    source_file = str(agenda.get("source_file") or "governed calendar workbook")
    sheet = str(agenda.get("sheet") or "Calendar")
    for item_date, item in selected:
        title = str(item.get("title") or "Untitled event")
        event_type = str(item.get("type") or "meeting")
        date_label = item_date.strftime("%a %d %b %Y") if item_date else str(item.get("day") or "date not supplied")
        when = str(item.get("when") or "").strip()
        time_suffix = f" at {when}" if when and when not in {date_label, item_date.isoformat() if item_date else ""} else ""
        prep = str(item.get("prep") or "No preparation request was supplied.")
        related_bu = str(item.get("related_bu") or "").strip()
        bu_suffix = f"; related business unit: {related_bu}" if related_bu else ""
        location = str(item.get("location") or "").strip()
        location_suffix = f"; location: {location}" if location else ""
        attendees = str(item.get("attendees") or "").strip()
        attendees_suffix = f"; attendees: {attendees}" if attendees else ""
        ends_at = str(item.get("ends_at") or "").strip()
        if time_suffix and ends_at:
            time_suffix = f"{time_suffix}–{ends_at}"
        detail_lines.append(
            f"{date_label}{time_suffix} — {title} ({event_type}){bu_suffix}{location_suffix}"
            f"{attendees_suffix}. Preparation: {prep}"
        )
        citations.append(
            {
                "source_path": source_file,
                "locator": f"{sheet} / {item.get('event_id') or date_label}",
                "excerpt": f"{title}; {date_label}; preparation: {prep}",
                "evidence_scope": str(item.get("evidence_scope") or agenda.get("evidence_scope") or "governed_calendar"),
            }
        )

    answer = status_sentence
    if detail_lines:
        answer = f"{status_sentence}\n" + "\n".join(f"- {line}" for line in detail_lines)
    return {
        "matched": True,
        "answer": answer,
        "basis": (
            f"Run-scoped governed calendar agenda from {source_file}; "
            "restricted calendar data is used only for calendar/agenda answers."
        ),
        "citations": citations,
        "suggestions": [
            "What preparation is required for the next listed meeting?",
            "What is on my governed agenda today?",
            "Which calendar items relate to a business unit?",
        ],
        "assistant_mode": "governed_calendar",
        "answered_by": "governed_calendar",
        "answer_origin": "governed",
        "intent": "calendar_agenda",
        "calendar_status": "ready",
        "calendar_item_count": int(agenda.get("total_item_count") or len(items)),
        "calendar_projection_item_count": len(items),
        "_orchestrator_force_answer": True,
    }


def _supplemental_grounding_payload(
    *,
    graph_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
    deterministic_result: dict[str, Any] | None = None,
    assistant_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if graph_result and graph_result.get("matched"):
        payload["graph"] = {
            "intent": graph_result.get("intent"),
            "answer": graph_result.get("answer"),
            "basis": graph_result.get("basis"),
            "citations": list(graph_result.get("citations") or [])[:8],
            "value": graph_result.get("value"),
        }
    if retrieval_result and retrieval_result.get("matched"):
        payload["retrieval"] = {
            "intent": retrieval_result.get("intent"),
            "answer": retrieval_result.get("answer"),
            "basis": retrieval_result.get("basis"),
            "citations": list(retrieval_result.get("citations") or [])[:8],
        }
    if deterministic_result and deterministic_result.get("matched") is not False:
        payload["tabular"] = {
            "intent": deterministic_result.get("intent"),
            "answer": deterministic_result.get("answer"),
            "basis": deterministic_result.get("basis"),
            "citations": list(deterministic_result.get("citations") or [])[:8],
        }
    if assistant_history:
        payload["conversation_history"] = [
            {
                "role": item.get("role"),
                "text": item.get("text"),
                "assistant_context": item.get("assistant_context"),
                "payload_reference": (item.get("payload") or {}).get("reference") if isinstance(item.get("payload"), Mapping) else None,
            }
            for item in assistant_history[-6:]
        ]
    return payload


async def _llm_answer_question_async(*args: Any, **kwargs: Any) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    async with _LLM_PROVIDER_SEMAPHORE:
        return await loop.run_in_executor(
            _LLM_PROVIDER_EXECUTOR,
            lambda: llm_qa.answer_question(*args, **kwargs),
        )


def _assistant_question_is_challenge_closure(question: str) -> bool:
    norm = " ".join(str(question or "").lower().split())
    asks_for_audit_status = (
        ("challenged" in norm or "challenge" in norm)
        and any(token in norm for token in ("status", "evidence", "closure", "citation", "resolve", "resolved"))
    ) or "evidence closure" in norm or "citation resolution" in norm
    return (
        "close challenged cases" in norm
        or "close challenge cases" in norm
        or ("challenged" in norm and "evidence" in norm and "next action" in norm)
        or asks_for_audit_status
    )


def _authenticated_challenge_closure_result(
    summary: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {
            "matched": True,
            "answer": "No governed run is available, so there is no supported challenged-case count to close.",
            "basis": "No governed run or audit log is available.",
            "citations": [],
            "suggestions": ["What should I prepare for the board?"],
            "intent": "challenged_case_closure",
            "grounding_status": "needs_evidence",
            "_orchestrator_force_answer": True,
        }

    rows = _finding_rows_from_summary(summary)
    rows_by_id = {
        str(row.get("finding_id")): row for row in rows if row.get("finding_id")
    }
    audit_payload = _load_summary_artifact_json(summary, "audit_log")
    audit_summary = _latest_run_audit_summary_payload(summary)
    open_ids = [str(item) for item in audit_summary.get("challenged_finding_ids") or []]
    historical_ids = [
        str(item)
        for item in audit_summary.get("historical_challenged_finding_ids") or []
    ]
    events = audit_payload if isinstance(audit_payload, list) else (
        (audit_payload or {}).get("events")
        or (audit_payload or {}).get("records")
        or (audit_payload or {}).get("items")
        or []
    )
    challenge_detail: dict[str, str] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        finding_id = str(event.get("finding_id") or "")
        if finding_id and str(event.get("action") or "").lower() == "challenge":
            challenge_detail[finding_id] = str(
                event.get("detail") or event.get("challenge") or "Reviewer evidence challenge."
            )

    citations = [
        {
            "source_path": "governed_audit://audit_log",
            "locator": f"finding_id={finding_id}; action=challenge",
            "excerpt": challenge_detail.get(finding_id) or "Challenge recorded in the governed audit log.",
            "finding_id": finding_id,
        }
        for finding_id in (open_ids or historical_ids)
    ]
    reconciliation = {
        "open_challenge_count": len(open_ids),
        "open_finding_row_count": sum(1 for finding_id in open_ids if finding_id in rows_by_id),
        "historical_challenge_count": len(historical_ids),
        "status": (
            "passed"
            if all(finding_id in rows_by_id for finding_id in open_ids)
            else "blocked"
        ),
    }
    citation_total = audit_summary.get("citation_count")
    citation_resolved = audit_summary.get("resolved_count")
    citation_resolution = _format_resolution_display(citation_resolved, citation_total)

    if not open_ids:
        answer = (
            "There are no open challenged cases in the current governed audit state. "
            f"The audit history records {len(historical_ids)} case"
            f"{'s' if len(historical_ids) != 1 else ''} that were challenged, but their latest recorded states are responded, locked, closed, or resolved. "
            f"Evidence resolution is {citation_resolution.lower()}. "
            "No challenge-closure action is required now; confirm the packet reconciliation and current approval decision before release."
        )
        suggestions = [
            "Show the current packet reconciliation",
            "What still needs reviewer approval?",
        ]
    else:
        lines = []
        case_links = []
        for finding_id in open_ids:
            row = rows_by_id.get(finding_id) or {}
            title = str(row.get("title") or finding_id)
            citation_count = int(row.get("citation_count") or 0)
            needed = challenge_detail.get(finding_id) or "Close the reviewer evidence challenge."
            lines.append(
                f"{finding_id} — {title}: {citation_count} linked citation"
                f"{'s' if citation_count != 1 else ''}; evidence needed: {needed}"
            )
            case_links.append({"finding_id": finding_id, "title": title})
        answer = (
            f"There are {len(open_ids)} open challenged case"
            f"{'s' if len(open_ids) != 1 else ''} in the governed audit state. "
            + " ".join(lines)
            + " Next action: open each case, confirm the cited proof resolves the recorded challenge, then record the reviewer closure before release."
        )
        suggestions = ["Open the challenged cases", "Show the current packet reconciliation"]
        return {
            "matched": True,
            "answer": answer,
            "basis": "Current open challenge state derived from the governed audit log and reconciled to governed finding rows.",
            "citations": citations,
            "suggestions": suggestions,
            "intent": "challenged_case_closure",
            "case_links": case_links,
            "grounding_status": "grounded" if reconciliation["status"] == "passed" else "needs_evidence",
            "reconciliation": reconciliation,
            "_orchestrator_force_answer": True,
        }

    return {
        "matched": True,
        "answer": answer,
        "basis": "Current open challenge state derived from the governed audit log; historical challenges are reported separately from open items.",
        "citations": citations,
        "suggestions": suggestions,
        "intent": "challenged_case_closure",
        "case_links": [],
        "grounding_status": "grounded",
        "reconciliation": reconciliation,
        "citation_resolution": {
            "resolved": citation_resolved,
            "total": citation_total,
            "display": citation_resolution,
        },
        "_orchestrator_force_answer": True,
    }


def _assistant_question_is_release_gate(question: str) -> bool:
    norm = " ".join(str(question or "").casefold().split())
    if not norm:
        return False
    return (
        ("human decision" in norm and any(token in norm for token in ("release", "board pack", "publish")))
        or ("reviewer decision" in norm and any(token in norm for token in ("release", "board pack", "publish", "required", "open")))
        or (any(token in norm for token in ("release", "publish")) and "approval" in norm)
    )


def _governed_release_gate_result(
    summary: dict[str, Any] | None,
    *,
    role: str,
    public_safe: bool,
) -> dict[str, Any]:
    """Explain release from the same publication contract that renders the UI."""
    if not isinstance(summary, dict):
        return {
            "matched": True,
            "answer": "No governed run is available, so there is no current board-pack release decision to make.",
            "basis": "No current governed run or publication contract is available.",
            "citations": [],
            "suggestions": ["Start a governed run"],
            "answered_by": "governed_release_gate",
            "grounding_status": "needs_evidence",
            "_orchestrator_force_answer": True,
        }

    publication = _summary_publication_payload(
        summary,
        principal_role=role,
        public_safe=public_safe,
    )
    approval_status = str(publication.get("approval_status") or "pending").lower()
    current_stage = str(publication.get("current_stage") or summary.get("current_stage") or "unknown").lower()
    requires_review = bool(publication.get("requires_human_review"))
    run_status = str(summary.get("status") or "unknown").lower()
    finding_count = int(summary.get("locked_findings") or summary.get("findings") or 0)
    challenged_count = int(publication.get("challenged_cases") or 0)
    reconciliation = publication.get("reconciliation") if isinstance(publication.get("reconciliation"), dict) else {}

    if run_status == "completed" or str(publication.get("status") or "") == "published":
        answer = "The current board pack is already published; no further human release decision is pending."
        grounding = "grounded"
    elif approval_status == "approved":
        answer = (
            "The reviewer has already approved the current packet. No additional executive decision is required at this gate; "
            "the operator must now resume the governed workflow so the approved outputs can be released."
        )
        grounding = "grounded"
    elif approval_status == "rejected":
        answer = (
            "The reviewer has rejected release. The required action is to revise the cited evidence or rerun the affected analysis, "
            "then return the packet for a new reviewer decision."
        )
        grounding = "grounded"
    elif requires_review or current_stage == "awaiting_review":
        answer = (
            "A human reviewer must decide whether to approve or reject the current board pack. "
            f"The governed packet contains {finding_count} locked finding(s) and {challenged_count} open challenged case(s). "
            "The reviewer must inspect the evidence and reconciliation, then record the release decision. "
            "Approval authorizes the next step but does not bypass governance: an operator must resume the workflow after approval."
        )
        grounding = "grounded"
    else:
        answer = (
            "The packet has not yet reached its mandatory human-review gate. Complete the current governed workflow stage before a reviewer can record a release decision."
        )
        grounding = "needs_evidence"

    citations = [
        {
            "source_path": "governance://publication-contract",
            "locator": "approval_status,current_stage,requires_human_review",
            "excerpt": f"Approval {approval_status}; stage {current_stage}; human review required {requires_review}.",
        },
        {
            "source_path": "governance://board-reconciliation",
            "locator": "publish_gate_passed",
            "excerpt": f"Reconciliation gate passed: {bool(reconciliation.get('publish_gate_passed'))}.",
        },
    ]
    return {
        "matched": True,
        "answer": answer,
        "basis": "Current governed publication, reviewer, and board-reconciliation contract.",
        "citations": citations,
        "suggestions": [
            "What evidence must the reviewer inspect?",
            "Are any challenged cases still open?",
        ],
        "answered_by": "governed_release_gate",
        "assistant_mode": "governed_release_gate",
        "grounding_status": grounding,
        "publication": publication,
        "_orchestrator_force_answer": True,
    }


def _format_ceo_currency_delta(value: Any) -> str:
    """Render a governed movement as executive-readable SAR without changing its value.

    Source packs created before the presentation contract used plain decimal
    strings such as ``+5615726.86 SAR``.  Hermes must keep those persisted runs
    readable as well as formatting newly-derived runs.
    """
    raw = str(value or "").strip()
    normalized = raw.replace("SAR", "").replace(",", "").strip()
    try:
        amount = Decimal(normalized)
    except (InvalidOperation, ValueError):
        return raw or "change recorded"
    sign = "+" if amount > 0 else "-" if amount < 0 else ""
    absolute = abs(amount)
    if absolute >= Decimal("1000000"):
        display = f"{(absolute / Decimal('1000000')):.1f}M"
    elif absolute >= Decimal("1000"):
        display = f"{(absolute / Decimal('1000')):.1f}K"
    else:
        display = f"{absolute:.0f}"
    return f"{sign}SAR {display}"


def _ceo_kpi_question_intent(question: str, requested_intent: str | None = None) -> str:
    """Classify the executive purpose of a KPI question.

    The browser may declare the intent of a governed action, but free-text
    questions must work through the same contract.  Question wording wins when
    it is explicit; the declared intent is only used for short/ambiguous UI
    prompts.  This changes answer shape, never the server-resolved KPI facts.
    """
    norm = " ".join(str(question or "").casefold().split())
    comparison_requested = bool(
        re.search(r"\b(plan|budget|comparator|comparison|compare|variance|versus|vs\.?|target|baseline)\b", norm)
    )
    drivers_requested = bool(
        re.search(r"\b(driver|drivers|driving|drives|composition|concentration|contributor|contributors|movement|moved|make up|come from|comes from|coming from)\b", norm)
    )
    decision_requested = bool(
        re.search(r"\b(attention|action|decision|decide|approve|approval|intervene|escalat|need from me|should i|next step)\b", norm)
    )
    # A CEO will often ask for the plan position, its material driver and the
    # decision in one sentence. Do not let the first matching keyword silently
    # discard the other requested parts.
    if sum((comparison_requested, drivers_requested, decision_requested)) > 1:
        return "briefing"
    if comparison_requested:
        return "comparison"
    if drivers_requested:
        return "drivers"
    if decision_requested:
        return "decision"
    declared = str(requested_intent or "").strip().lower()
    return declared if declared in {"decision", "drivers", "comparison", "overview", "briefing"} else "overview"


def _ceo_kpi_cards(context: Mapping[str, Any], *, public_safe: bool) -> list[dict[str, Any]]:
    """Build the four CEO cards from the same server-resolved truth as the page."""
    summary = context.get("summary") if isinstance(context.get("summary"), Mapping) else {}
    read_model = _executive_read_model_from_available_truth(
        dict(summary),
        [],
        {},
        {"report_count": 0},
        {},
        public_safe=public_safe,
    )
    return [
        dict(item)
        for item in list(build_executive_presentation(read_model).get("driver_grid") or [])
        if isinstance(item, Mapping)
    ]


def _ceo_kpi_inline_result(
    context: Mapping[str, Any],
    *,
    kpi_key: str,
    public_safe: bool,
    question: str = "",
    question_intent: str | None = None,
) -> dict[str, Any]:
    """Answer a CEO KPI conversation from server-resolved truth only.

    The browser supplies a KPI key, never an authoritative KPI value.  Rebuild
    the presentation contract from the resolved run so a stale or manipulated
    browser state cannot change the number Hermes describes.
    """
    cards = _ceo_kpi_cards(context, public_safe=public_safe)
    card = next(
        (item for item in cards if str(item.get("key") or item.get("driver_key") or "") == kpi_key),
        None,
    )
    if not isinstance(card, Mapping):
        return {
            "matched": True,
            "answer": "That figure is not part of the four CEO headline measures. Choose Revenue, EBITDA margin, Operating cost, or Cash vs floor.",
            "basis": "Available CEO headline measures",
            "citations": [],
            "suggestions": ["Explain Revenue", "Explain EBITDA margin", "Explain Operating cost", "Explain Cash vs floor"],
            "answered_by": "governed_kpi",
            "grounding_status": "needs_evidence",
            "_orchestrator_force_answer": True,
        }

    label = str(card.get("label") or "this KPI")
    availability = str(card.get("availability") or "unavailable")
    missing = [str(item) for item in list(card.get("missing_inputs") or []) if str(item)]
    brief = card.get("executive_brief") if isinstance(card.get("executive_brief"), Mapping) else {}
    strategic_reference = brief.get("strategic_reference") if isinstance(brief.get("strategic_reference"), Mapping) else None
    calculation = brief.get("calculation") if isinstance(brief.get("calculation"), Mapping) else {}
    audit = brief.get("audit") if isinstance(brief.get("audit"), Mapping) else {}
    comparison = brief.get("comparison") if isinstance(brief.get("comparison"), Mapping) else {}
    drivers = [item for item in list(brief.get("drivers") or []) if isinstance(item, Mapping)]
    movers = card.get("movers") if isinstance(card.get("movers"), Mapping) else {}
    lifting = [item for item in list(movers.get("lifting") or []) if isinstance(item, Mapping)]
    dragging = [item for item in list(movers.get("dragging") or []) if isinstance(item, Mapping)]
    trend = card.get("trend") if isinstance(card.get("trend"), Mapping) else {}
    has_plan_series = bool(trend.get("has_plan_series"))
    resolved_intent = _ceo_kpi_question_intent(question, question_intent)
    metric = str(card.get("metric") or "available")

    def _composition_sentence() -> str:
        if not drivers:
            return "No component-level breakdown is available for this figure."
        parts: list[str] = []
        ranked: list[tuple[float, str]] = []
        for item in drivers[:8]:
            driver_label = str(item.get("label") or "Component")
            driver_value = str(item.get("value") or "").strip()
            share_text = ""
            try:
                raw_share = item.get("share_pct")
                if raw_share not in (None, ""):
                    share = float(raw_share)
                    share_text = f"{share:.1f}%"
                    if share > 0:
                        ranked.append((share, driver_label))
            except (TypeError, ValueError):
                pass
            display = " · ".join(part for part in (driver_value, share_text) if part)
            parts.append(f"{driver_label} — {display}" if display else driver_label)
        sentence = "Current composition: " + "; ".join(parts) + "."
        if ranked:
            largest_share, largest_label = max(ranked)
            sentence += f" The largest reported contributor is {largest_label} at {largest_share:.1f}%."
        return sentence

    def _largest_component_sentence() -> str:
        ranked: list[tuple[float, str, str]] = []
        for item in drivers:
            try:
                share = float(item.get("share_pct"))
            except (TypeError, ValueError):
                continue
            if share <= 0:
                continue
            ranked.append(
                (
                    share,
                    str(item.get("label") or "Component"),
                    str(item.get("value") or "").strip(),
                )
            )
        if not ranked:
            return "No component-level driver is available for this figure."
        share, component_label, component_value = max(ranked)
        value_suffix = f" — {component_value}" if component_value else ""
        return f"Largest reported contributor: {component_label}{value_suffix} ({share:.1f}%)."

    def _movement_sentence(*, decision_only: bool = False) -> str:
        if not (lifting or dragging):
            return "No category-level movement requiring interpretation is recorded for the available periods."
        parts: list[str] = []
        if dragging:
            prefix = "Movement requiring attention" if decision_only else "Negative movement"
            parts.append(
                prefix + ": " + "; ".join(
                    f"{str(item.get('name') or 'identified group')} ({_format_ceo_currency_delta(item.get('delta'))})"
                    for item in dragging[:2]
                )
            )
        if lifting and not decision_only:
            parts.append(
                "Positive movement: " + "; ".join(
                    f"{str(item.get('name') or 'identified group')} ({_format_ceo_currency_delta(item.get('delta'))})"
                    for item in lifting[:2]
                )
            )
        return ". ".join(parts) + "."

    if availability == "unavailable":
        answer = (
            f"{label} is not available for the current reporting period because the required finance information is incomplete. "
            "No value has been estimated."
        )
        if missing:
            answer += f" Needed to answer this {resolved_intent} question: {'; '.join(missing)}."
        grounding = "needs_evidence"
    else:
        if resolved_intent == "briefing":
            decision_context = str(brief.get("decision_context") or "").strip()
            readout = str(brief.get("readout") or card.get("detail") or "").strip()
            answer = f"Current position: {readout or f'{label} is {metric} for the selected period.'} "
            if comparison.get("available") is True:
                answer += f"Plan position: {comparison.get('value') or 'A like-for-like approved comparator is available'}. "
            elif comparison.get("note"):
                answer += f"Plan position: {comparison.get('note')} "
            answer += _largest_component_sentence() + " "
            answer += f"CEO decision: {decision_context or 'Keep the position delegated unless a governed exception crosses the CEO threshold.'}"
            if missing:
                answer += f" The immediate governance gap is {'; '.join(missing)}."
        elif resolved_intent == "decision":
            decision_context = str(brief.get("decision_context") or "").strip()
            readout = str(brief.get("readout") or card.get("detail") or "").strip()
            accountable_owner = {
                "revenue": "Group CFO and the accountable business-line CEO",
                "ebitda_margin": "Group CFO",
                "operating_cost": "Group CFO and the accountable operating executives",
                "cash_vs_floor": "Group CFO and Group Treasury",
            }.get(kpi_key, "Group CFO")
            answer = (
                f"Current position: {readout or f'{label} is {metric} for the selected period.'} "
                f"Accountable owner: {accountable_owner}. "
                f"Next decision: {decision_context or 'Keep the position delegated unless a governed exception crosses the CEO threshold.'} "
            )
            if dragging:
                answer += _movement_sentence(decision_only=True) + " "
            if missing:
                answer += f"The immediate governance gap is {'; '.join(missing)}. Supply or approve that comparator before treating the figure as a plan variance."
            elif not dragging:
                answer += "No KPI-specific exception requiring executive intervention is recorded in the current governed data."
        elif resolved_intent == "drivers":
            answer = f"{label} is {metric}. {brief.get('readout') or card.get('detail') or ''} "
            answer += _composition_sentence() + " "
            answer += _movement_sentence()
        elif resolved_intent == "comparison":
            answer = f"The current {label.lower()} actual is {metric}. "
            if comparison.get("available") is True:
                answer += f"{comparison.get('value') or 'A like-for-like approved comparator is available'}. {comparison.get('note') or ''}"
            else:
                answer += f"No like-for-like plan variance is stated. {comparison.get('note') or ''} "
                if kpi_key == "revenue" and not has_plan_series:
                    answer += "No period-aligned revenue plan series is connected. "
                if missing:
                    answer += f"Needed for a valid comparison: {'; '.join(missing)}."
            if strategic_reference:
                answer += (
                    f" The {str(strategic_reference.get('label') or 'approved strategic reference').lower()} is "
                    f"{strategic_reference.get('value') or 'available'}, but {strategic_reference.get('note') or 'it is reference-only.'}"
                )
        else:
            answer = (
                f"{label} is {metric}. {brief.get('readout') or card.get('detail') or ''} "
                f"{brief.get('decision_context') or ''}"
            )
        # The current actual and any disclosed evidence gap are governed facts.
        # Missing comparison inputs do not downgrade the available actual.
        grounding = "grounded"
        card_grounding = card.get("grounding") if isinstance(card.get("grounding"), Mapping) else {}
        if str(card_grounding.get("status") or "").lower() in {"needs_evidence", "not_grounded", "partial"}:
            grounding = "needs_evidence"
    source_files = [str(item) for item in list(card.get("source_files") or audit.get("source_files") or []) if str(item)]
    citations = [
        {
            "source_path": source_file,
            "locator": f"CEO {label} evidence",
            "excerpt": f"Governed source used for the current {label} measure.",
        }
        for source_file in source_files[:6]
    ]
    return {
        "matched": True,
        "answer": answer,
        "basis": "Current CEO finance records and approved strategic references",
        "citations": citations,
        "suggestions": [
            f"What needs executive attention for {label}?",
            f"What is driving {label}?",
        ],
        "answered_by": "governed_kpi",
        "grounding_status": grounding,
        "missing_inputs": missing,
        "kpi_question_intent": resolved_intent,
        "kpi": dict(card),
        "_orchestrator_force_answer": True,
    }


def _parse_amount_references(question: str) -> list[float]:
    """Extract monetary references from a follow-up question.

    Only SAR-prefixed or K/M/B-suffixed numbers qualify: a bare "3" in
    "top 3 cases" or the "28.5" inside "28.5%" is not a money reference and
    must not trigger component matching. Comma grouping ("SAR 794,108") is
    accepted.
    """
    text = str(question or "")
    values: list[float] = []
    pattern = (
        r"SAR\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*([kKmMbB])?(?![\d%])"
        r"|\b(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*([kKmMbB])\b(?!%)"
    )
    for match in re.finditer(pattern, text):
        raw_text = match.group(1) or match.group(3)
        suffix = (match.group(2) or match.group(4) or "").lower()
        if not raw_text:
            continue
        raw = float(raw_text.replace(",", ""))
        multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(suffix, 1)
        values.append(raw * multiplier)
    return values


def _parse_display_amount(value: Any) -> float | None:
    text = str(value or "")
    match = re.search(r"(?:SAR\s*)?(\d+(?:\.\d+)?)\s*([kKmMbB])?", text)
    if not match:
        return None
    raw = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(suffix, 1)
    return raw * multiplier


def _amounts_match(left: float, right: float) -> bool:
    tolerance = max(1.0, abs(right) * 0.006)
    return abs(left - right) <= tolerance


def _history_kpi_key(history: list[dict[str, Any]]) -> str | None:
    for item in reversed(history):
        payload = item.get("payload")
        payload_context = payload.get("assistant_context") if isinstance(payload, Mapping) else None
        for source in (item.get("assistant_context"), payload_context):
            if isinstance(source, Mapping):
                key = str(source.get("kpi_key") or source.get("driver_key") or "").strip()
                if key and key != "board_packet":
                    return key
        if isinstance(payload, Mapping):
            kpi = payload.get("kpi")
            if isinstance(kpi, Mapping):
                key = str(kpi.get("key") or kpi.get("driver_key") or "").strip()
                if key:
                    return key
    return None


def _governed_entity_index(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One lookup over every entity the current governed run puts on screen.

    The CEO references what they can see: a finding id ("F-006"), an invoice or
    credit number carried in a finding title, a vendor, a KPI component, or a
    bare amount. Resolving each surface separately is what left findings
    unreachable while KPI rows resolved, so every surface is indexed here once
    and matched by the same rules.
    """
    entities: list[dict[str, Any]] = []

    for raw_row in list(context.get("findings") or []):
        # The chat context carries Finding dataclasses straight from
        # run_all_finance_skills(); other callers pass plain dict rows. Accept
        # both -- an isinstance(Mapping) guard here silently indexed zero
        # findings in production while dict-based tests passed.
        if isinstance(raw_row, Mapping):
            row: Mapping[str, Any] = raw_row
        elif dataclasses.is_dataclass(raw_row) and not isinstance(raw_row, type):
            row = dataclasses.asdict(raw_row)
        elif hasattr(raw_row, "model_dump"):
            row = raw_row.model_dump()
        else:
            continue
        finding_id = str(row.get("finding_id") or row.get("case_id") or "").strip()
        title = str(row.get("title") or "").strip()
        if not finding_id and not title:
            continue
        amount = row.get("recoverable_sar")
        tokens = {finding_id.casefold()} if finding_id else set()
        # Titles carry the document identifiers a CEO quotes back
        # ("INV-2026-0577", "CR-2024-091", "V-1142").
        for doc_id in re.findall(r"\b[A-Z]{1,4}-[0-9]{2,4}-?[0-9]*\b", title):
            tokens.add(doc_id.casefold())
        vendor = str(row.get("vendor_name") or row.get("vendor") or "").strip()
        if vendor:
            tokens.add(vendor.casefold())
        entities.append(
            {
                "kind": "finding",
                "id": finding_id,
                "label": title or finding_id,
                "tokens": {token for token in tokens if token},
                "phrase": title.casefold(),
                "amount": _as_float_or_none(amount),
                "row": dict(row),
            }
        )

    read_model = _executive_read_model_from_available_truth(
        dict(context.get("summary") if isinstance(context.get("summary"), Mapping) else {}),
        [],
        {},
        {"report_count": 0},
        {},
        public_safe=False,
    )
    for card in list(build_executive_presentation(read_model).get("driver_grid") or []):
        if not isinstance(card, Mapping):
            continue
        card_label = str(card.get("label") or "").strip()
        card_key = str(card.get("key") or card.get("driver_key") or "").strip()
        brief = card.get("executive_brief") if isinstance(card.get("executive_brief"), Mapping) else {}
        entities.append(
            {
                "kind": "kpi",
                "id": card_key,
                "label": card_label,
                "tokens": {token for token in {card_key.casefold(), card_label.casefold()} if token},
                "phrase": card_label.casefold(),
                "amount": _parse_display_amount(card.get("metric")),
                "card": dict(card),
                "brief": dict(brief),
            }
        )
        for driver in list(brief.get("drivers") or []):
            if not isinstance(driver, Mapping):
                continue
            driver_label = str(driver.get("label") or "").strip()
            if not driver_label:
                continue
            entities.append(
                {
                    "kind": "kpi_component",
                    "id": f"{card_key}:{driver_label}",
                    "label": driver_label,
                    "tokens": {driver_label.casefold()},
                    "phrase": driver_label.casefold(),
                    "amount": _parse_display_amount(driver.get("value")),
                    "card": dict(card),
                    "brief": dict(brief),
                    "driver": dict(driver),
                }
            )
    return entities


_GOVERNED_IDENTIFIER_RE = re.compile(r"(?<![\w-])[A-Za-z]{1,4}-[0-9]{2,4}-?[0-9]*(?![\w-])")


def _question_is_governed_business_question(
    question: str,
    *,
    context: Mapping[str, Any] | None = None,
) -> bool:
    """Should this question be answered from the customer's governed run?

    The burden of proof runs the safe way round. An earlier version tried to
    prove a question WAS governed -- by identifier, amount, engine claim, or
    the run's own nouns -- and handed everything it could not prove to the
    general-knowledge model, which holds no company data. That is unbounded:
    an executive can phrase a question about their own business in endlessly
    many ways, and every phrasing the checks missed produced "the board packet
    is private company data and is not available in my general knowledge" --
    read, correctly, as the assistant failing to reach its own evidence.

    So: while a governed run is loaded, the governed model owns the question.
    It has the evidence and can say honestly what it does not carry. Only a
    question that is demonstrably general knowledge -- no run loaded, or an
    engine-recognised general topic that names nothing in the business -- may
    reach the general model.
    """
    text = str(question or "").strip()
    if not text:
        return False
    if _question_looks_like_governed_identifier(text):
        return True
    if _parse_amount_references(text):
        return True
    try:
        if scenario_has_intent(text):
            return True
    except Exception:  # pragma: no cover - scoping must never break a chat turn
        pass
    try:
        if qa_engine.claims_question(text):
            return True
    except Exception:  # pragma: no cover - scoping must never break a chat turn
        pass
    if not isinstance(context, Mapping):
        return False
    # No run, nothing governed to protect: a general question is all it can be.
    if not context.get("run_id") and not context.get("findings"):
        return False
    # A run is loaded. Anything that touches this business belongs to the
    # governed model; only clearly external general knowledge may pass.
    return not _question_is_general_knowledge(text)


_GENERAL_KNOWLEDGE_RE = re.compile(
    r"\b(?:capital of|population of|who (?:is|was|won|invented|wrote)|"
    r"what year|when did|where is|translate|meaning of the word|"
    r"weather|joke|poem|recipe|定义)\b",
    re.IGNORECASE,
)


def _question_is_general_knowledge(question: str) -> bool:
    """A question answerable from world knowledge, naming nothing in the run.

    Deliberately narrow. A false positive here sends a question about the
    customer's money to a model with no access to it, which is the failure this
    guard exists to prevent; a false negative merely sends trivia to the
    governed model, which answers it anyway.
    """
    text = " ".join(str(question or "").casefold().split())
    if not text:
        return False
    return bool(_GENERAL_KNOWLEDGE_RE.search(text))


def _question_is_about_the_loaded_run(question: str, context: Mapping[str, Any]) -> bool:
    """True when the question names the governed artifacts this run exposes.

    The subjects come from the run itself -- the artifact/section names the
    context actually carries -- not from a list kept here. Asking about "the
    run" or "the findings" while a run is loaded is a question about that run.
    """
    text = " ".join(str(question or "").casefold().split())
    if not text:
        return False
    subjects: set[str] = set()
    if context.get("run_id"):
        subjects.add("run")
    if context.get("findings"):
        subjects.update({"finding", "findings", "case", "cases"})
    for entity in _governed_entity_index_safe(context):
        # Entity labels are the run's own nouns: KPI names ("Cash vs floor"),
        # component rows, vendors. Their words are what this run is about.
        for word in re.findall(r"[a-z]{3,}", str(entity.get("label") or "").casefold()):
            subjects.add(word)
    summary = context.get("summary")
    if isinstance(summary, Mapping):
        for key in summary.keys():
            token = str(key).strip().casefold()
            # Summary keys are the run's own section names (finance_kpi,
            # publication, ...); their words are legitimate run subjects.
            for word in re.findall(r"[a-z]{4,}", token):
                subjects.add(word)
    return any(re.search(r"\b" + re.escape(subject) + r"\b", text) for subject in subjects)


def _question_asks_for_causation(question: str) -> bool:
    """Does the question ask WHY something moved, rather than WHAT it is?

    The reference resolver can only describe a figure's current composition and
    provenance. A causal or trend question needs attribution the resolver does
    not compute, so claiming it yields a fluent answer to a different question.
    """
    norm = " ".join(str(question or "").casefold().split())
    if not norm:
        return False
    if re.search(r"\bwhy\b", norm):
        return True
    if re.search(r"\bwhat (?:caused|drove|is driving|drives)\b", norm):
        return True
    # "revenue dropped 12%" -- a movement asserted about a figure.
    if _CHANGE_CLAIM_RE.search(norm) and re.search(r"\d", norm):
        return True
    return False


def _governed_entity_index_safe(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    """_governed_entity_index that never raises into a scoping decision."""
    try:
        return _governed_entity_index(context)
    except Exception:  # pragma: no cover - defensive
        return []


def _question_looks_like_governed_identifier(question: str) -> bool:
    """True when the question is about a record id (F-006, INV-2026-0577).

    Such a question carries no finance keyword, so the business-scope check
    routes it to the general-knowledge model, which has no governed evidence
    and will invent plausible finance detail for the id. An identifier that did
    not resolve in the run must fail closed instead.
    """
    return bool(_GOVERNED_IDENTIFIER_RE.search(str(question or "")))


def _as_float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


_PRONOUN_ONLY_RE = re.compile(
    r"^(?:can you |could you |please |now |and |so )*"
    r"(?:show|tell|explain|elaborate|expand|detail|describe|give)?\s*"
    r"(?:me|us)?\s*(?:more\s+)?(?:about\s+|on\s+)?"
    r"\b(it|that|this|those|these|them|the one|the same)\b",
)


def _question_is_reference_followup(question: str) -> bool:
    """A follow-up whose whole subject is a pronoun or a bare 'why'."""
    norm = " ".join(str(question or "").casefold().split()).strip(" ?.!")
    if not norm:
        return False
    if norm in {"why", "why?", "how", "and why", "explain", "elaborate", "more", "tell me more", "go on"}:
        return True
    return bool(_PRONOUN_ONLY_RE.match(norm))


def _history_entity_tokens(history: list[dict[str, Any]]) -> list[str]:
    """Identifiers the assistant most recently put on screen, newest first."""
    tokens: list[str] = []
    for item in reversed(history or []):
        if str(item.get("role") or "") != "assistant":
            continue
        text = str(item.get("text") or "")
        for doc_id in re.findall(r"\b[A-Z]{1,4}-[0-9]{2,4}-?[0-9]*\b", text):
            if doc_id.casefold() not in tokens:
                tokens.append(doc_id.casefold())
    return tokens


def _resolve_governed_entities(
    entities: list[dict[str, Any]],
    *,
    question: str,
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match a question against the entity index: identifier, phrase, amount,
    then pronoun-carried reference from the previous assistant turn."""
    norm = " ".join(str(question or "").casefold().split())
    stripped = norm.strip(" ?.!,")
    matches: list[dict[str, Any]] = []

    for entity in entities:
        for token in entity.get("tokens") or set():
            if not token:
                continue
            # Identifier tokens must match as whole words so "F-006" never
            # matches inside an unrelated string.
            if re.search(r"(?<![\w-])" + re.escape(token) + r"(?![\w-])", norm):
                matches.append(entity)
                break
    if matches:
        return matches

    for entity in entities:
        phrase = entity.get("phrase") or ""
        if len(phrase) >= 8 and phrase in norm:
            matches.append(entity)
    if matches:
        return matches

    amount_refs = _parse_amount_references(question)
    if amount_refs:
        for entity in entities:
            amount = entity.get("amount")
            if amount is None:
                continue
            if any(_amounts_match(ref, amount) for ref in amount_refs):
                matches.append(entity)
        if matches:
            return matches

    if _question_is_reference_followup(stripped):
        for token in _history_entity_tokens(history):
            for entity in entities:
                if token in (entity.get("tokens") or set()):
                    return [entity]
    return []


def _finding_reference_answer(entity: Mapping[str, Any]) -> dict[str, Any]:
    """Answer a governed finding reference with what a CEO must decide on."""
    row = entity.get("row") if isinstance(entity.get("row"), Mapping) else {}
    finding_id = str(entity.get("id") or "")
    title = str(entity.get("label") or finding_id)
    amount = entity.get("amount")
    citation_count = row.get("citation_count") or row.get("citations")
    status_text = str(row.get("status") or row.get("state") or "").strip()
    vendor = str(row.get("vendor_name") or row.get("vendor") or "").strip()

    parts = [f"{finding_id} is {title}." if finding_id else f"{title}."]
    if amount:
        parts.append(f"Recoverable value: {_format_sar_brief(amount)}.")
    if vendor:
        parts.append(f"Counterparty: {vendor}.")
    if status_text:
        parts.append(f"Current status: {humanize_token(status_text) if 'humanize_token' in globals() else status_text}.")
    try:
        if citation_count not in (None, ""):
            parts.append(f"Supporting evidence: {int(citation_count)} citation(s) attached.")
    except (TypeError, ValueError):
        pass
    parts.append("Next step: open this case to review its evidence trail, or ask what it takes to close it before board release.")

    citations = []
    if finding_id:
        citations.append(
            {
                "source_path": "run_artifacts://findings",
                "locator": f"finding_id={finding_id}",
                "excerpt": title,
                "finding_id": finding_id,
            }
        )
    return {
        "matched": True,
        "answer": " ".join(parts),
        "basis": "Resolved a governed finding reference against the current run's finding rows.",
        "citations": citations,
        "suggestions": [
            f"What evidence supports {finding_id}?" if finding_id else "What evidence supports this case?",
            f"What is needed to close {finding_id}?" if finding_id else "What is needed to close this case?",
            "Which cases create the largest recoverable value?",
        ],
        "answered_by": "governed_reference",
        "assistant_mode": "governed_reference",
        "grounding_status": "grounded",
        "reference": {"kind": "finding", "finding_id": finding_id, "label": title, "recoverable_sar": amount},
        "_orchestrator_force_answer": True,
    }


_COST_ACTION_RE = re.compile(
    r"\b(?:decrease|reduce|lower|cut|cutting|save|savings|bring down|"
    r"optimi[sz]e|trim|what can i do|what should i do|how do i improve|"
    r"where can we|how can we)\b",
    re.IGNORECASE,
)

_COST_SUBJECT_RE = re.compile(
    r"\b(?:operating cost|operating costs|opex|cost base|costs?|spend|"
    r"spending|expense|expenses|overhead)\b",
    re.IGNORECASE,
)


def _question_asks_what_to_do_about_cost(question: str) -> bool:
    """Is the executive asking what they could act on, not what a figure is?

    "How can I decrease operating cost?" and "what can I do about opex" are the
    same question. Both need levers; neither is answered by restating the
    total.
    """
    text = " ".join(str(question or "").casefold().split())
    if not text:
        return False
    if not (_COST_ACTION_RE.search(text) and _COST_SUBJECT_RE.search(text)):
        return False
    # "What if we reduce rent expense by 15%?" is not an open question about
    # cost -- the executive already chose the lever AND the size, which is
    # arithmetic the scenario engine does exactly. Answering that with a generic
    # lever list ignores what was asked.
    #
    # Scenario INTENT alone cannot separate the two: "how can I decrease
    # operating cost?" reads as scenario intent too, and it is precisely the
    # open question levers exist for. The stated quantity is what distinguishes
    # a chosen cut from an open ask, so the percentage is the test -- with
    # intent still required, so "costs are 26% of revenue, what can I do?"
    # keeps its levers.
    if scenario_has_intent(text) and re.search(r"\d+(?:\.\d+)?\s*%", text):
        return False
    return True


def _governed_cost_lever_result(
    context: Mapping[str, Any],
    *,
    question: str,
    public_safe: bool,
) -> dict[str, Any] | None:
    """Answer a cost-reduction question from levers the run proves.

    The model never invents the recommendation: cost_levers derives it from the
    GL composition and the reconciled findings, and the prose here only orders
    and narrates what was derived. A lever carries db_derived_lever provenance
    so the surface can show it as advice rather than as a governed fact.
    """
    if public_safe or not _question_asks_what_to_do_about_cost(question):
        return None
    summary = context.get("summary") if isinstance(context.get("summary"), Mapping) else {}
    finance_kpi = summary.get("finance_kpi") if isinstance(summary.get("finance_kpi"), Mapping) else None
    findings = context.get("findings") or []
    try:
        derived = derive_cost_levers(finance_kpi=finance_kpi, findings=findings)
    except Exception:  # pragma: no cover - a lever must never break a chat turn
        return None
    if derived.get("status") != "available":
        return None

    levers = list(derived.get("levers") or [])
    reconciled = [item for item in levers if item.get("kind") == "reconciled_leakage"]
    concentration = [item for item in levers if item.get("kind") == "concentration"]
    gaps = [item for item in levers if item.get("kind") == "missing_comparator"]

    parts: list[str] = []
    if reconciled:
        total = sum(float(item.get("addressable_sar") or 0) for item in reconciled)
        top = "; ".join(
            f"{item['line_item']} ({_format_sar_brief(item['addressable_sar'])})"
            for item in reconciled[:3]
        )
        parts.append(
            f"Start with money this run has already identified: {_format_sar_brief(total)} "
            f"across {len(reconciled)} governed case(s) with evidence attached -- {top}."
        )
    if concentration:
        top = concentration[0]
        others = "; ".join(
            f"{item['line_item']} {item['share_pct']:.1f}%" for item in concentration[1:4]
        )
        parts.append(
            f"Your cost is concentrated: {top['line_item']} is {top['share_pct']:.1f}% of "
            f"{derived['scope_label']} ({_format_sar_brief(top['current_sar'])}), so a 5% reduction "
            f"is {_format_sar_brief(top['addressable_sar'])}."
            + (f" Then {others}." if others else "")
        )
        parts.append(
            "These are sized from your general ledger, not judged against a target: nothing in "
            "this run says any of these lines is too high."
        )
    for gap in gaps:
        parts.append(str(gap.get("benchmark_basis") or ""))

    citations: list[dict[str, Any]] = []
    for item in reconciled[:5]:
        finding_id = (item.get("evidence_ref") or {}).get("finding_id")
        if finding_id:
            citations.append(
                {
                    "source_path": "run_artifacts://findings",
                    "locator": f"finding_id={finding_id}",
                    "excerpt": item["line_item"],
                    "finding_id": finding_id,
                }
            )
    for item in concentration[:5]:
        account = (item.get("evidence_ref") or {}).get("account")
        if account:
            citations.append(
                {
                    "source_path": "run_artifacts://finance_kpi",
                    "locator": f"gl_account={account}",
                    "excerpt": f"{item['line_item']} {_format_sar_brief(item['current_sar'])}",
                }
            )

    return {
        "matched": True,
        "answer": " ".join(part for part in parts if part).strip(),
        "basis": (
            "Levers derived from the run's own general ledger composition and reconciled "
            "findings. Amounts are arithmetic on governed figures, not recommendations "
            "the model formed."
        ),
        "citations": citations[:8],
        "suggestions": [
            "Which cases create the largest recoverable value?",
            f"What is driving {derived['scope_label']}?",
            "What evidence supports the largest case?",
        ],
        "answered_by": "governed_levers",
        "assistant_mode": "governed_levers",
        "grounding_status": "suggested",
        "claim_class": "db_derived_lever",
        "levers": levers,
        "_orchestrator_force_answer": True,
    }


def _governed_reference_result(
    context: Mapping[str, Any],
    *,
    question: str,
    assistant_context: Mapping[str, Any],
    history: list[dict[str, Any]],
    public_safe: bool,
) -> dict[str, Any] | None:
    """Resolve any on-screen governed reference before the LLM fallback runs.

    Scope is deliberately every entity the run exposes -- findings, document
    identifiers carried in finding titles, vendors, KPI cards and their
    component rows -- because an executive quotes whatever the surface showed
    them. An earlier version indexed KPI cards only, which left "F-006" and
    "INV-2026-0577" to the model and produced fabricated finance facts.
    """
    if public_safe:
        return None
    # A what-if that happens to quote an on-screen amount ("If we recover
    # SAR 103.2M, what remains?") must reach the scenario engine, not be
    # answered as a component lookup. _assistant_question_requests_modelling
    # alone is not enough: recovery grammar carries no finance keyword, so the
    # scenario-verb family the recovery engine owns is checked explicitly.
    if _assistant_question_requests_modelling(question):
        return None
    scenario_norm = " ".join(str(question or "").casefold().split())
    if re.search(
        r"\b(?:recover|recovery|recovering|realize|realise|collect|collecting|remains|remaining|what if)\b",
        scenario_norm,
    ):
        return None
    # Naming an entity is necessary to answer from it, not sufficient. This
    # resolver states what a figure IS; it cannot explain causation or trend.
    # "Why did revenue drop 12%?" mentions Revenue, and answering it from the
    # Revenue card produced a confident non sequitur about a drop that never
    # happened. Questions of that shape belong to the engines that model
    # movement, or to an honest "I cannot attribute that".
    if _question_asks_for_causation(question):
        return None

    try:
        entities = _governed_entity_index(context)
    except HTTPException:
        return None
    if not entities:
        return None

    matches = _resolve_governed_entities(entities, question=question, history=history)
    if not matches:
        return None

    finding_match = next((item for item in matches if item.get("kind") == "finding"), None)
    if finding_match is not None:
        return _finding_reference_answer(finding_match)

    # A question about a whole KPI ("What is our revenue?") belongs to the KPI
    # contract, which states the figure on its own terms. This resolver only
    # renders components, so answering a KPI match here described it as a part
    # of whichever card the component search happened to land on -- the source
    # of "SAR 385.1M is Revenue within EBITDA margin". Defer instead.
    # A KPI is its own subject, not a row inside another card. Prod's EBITDA
    # bridge lists "Revenue" as an input, so "What is our revenue?" matches
    # both the Revenue KPI and an EBITDA component labelled "Revenue" -- and
    # answering from the component produced "SAR 385.1M is Revenue within
    # EBITDA margin". When a label names a KPI, that KPI owns the question and
    # the KPI contract answers it. A component only answers when it is not
    # itself a KPI name.
    kpi_labels = {
        str(item.get("label") or "").casefold()
        for item in matches
        if item.get("kind") == "kpi"
    }
    component = next(
        (
            item
            for item in matches
            if item.get("kind") == "kpi_component"
            and str(item.get("label") or "").casefold() not in kpi_labels
        ),
        None,
    )
    if component is None:
        return None

    card = component.get("card") if isinstance(component.get("card"), Mapping) else {}
    brief = component.get("brief") if isinstance(component.get("brief"), Mapping) else {}
    driver = component.get("driver") if isinstance(component.get("driver"), Mapping) else {}
    label = str(card.get("label") or "this KPI")
    driver_label = str(driver.get("label") or "component")
    driver_value = str(driver.get("value") or "").strip()
    share = driver.get("share_pct")
    share_text = ""
    try:
        if share not in (None, ""):
            share_text = f"{float(share):.1f}%"
    except (TypeError, ValueError):
        share_text = str(share or "")
    readout = str(brief.get("readout") or card.get("detail") or "").strip()
    calculation = brief.get("calculation") if isinstance(brief.get("calculation"), Mapping) else {}
    audit = brief.get("audit") if isinstance(brief.get("audit"), Mapping) else {}
    source_files = [
        str(item)
        for item in list(card.get("source_files") or audit.get("source_files") or audit.get("source_titles") or [])
        if str(item)
    ]
    answer = f"{driver_value or 'That amount'} is {driver_label} within {label}."
    if share_text:
        answer += f" It represents {share_text} of the current {label.lower()} composition."
    if readout:
        answer += f" {readout}"
    if calculation.get("formula"):
        answer += f" Calculation basis: {calculation.get('formula')}"
    answer += " Next step: use the same KPI drill-down to compare this component with the other reported contributors or ask for the evidence trail."
    return {
        "matched": True,
        "answer": answer,
        "basis": "Resolved a follow-up reference against current CEO KPI component rows before LLM fallback.",
        "citations": [
            {
                "source_path": source_file,
                "locator": f"CEO {label} component: {driver_label}",
                "excerpt": f"{driver_label} {driver_value} {share_text}".strip(),
            }
            for source_file in source_files[:6]
        ],
        "suggestions": [
            f"Compare {driver_label} with other {label} contributors",
            f"Show the evidence trail for {driver_label}",
            f"What needs executive attention for {label}?",
        ],
        "answered_by": "governed_reference",
        "assistant_mode": "governed_reference",
        "grounding_status": "grounded",
        "reference": {
            "kpi_key": str(card.get("key") or card.get("driver_key") or ""),
            "label": driver_label,
            "value": driver_value,
            "share_pct": share,
        },
        "_orchestrator_force_answer": True,
    }



def _assistant_question_requests_modelling(question: str) -> bool:
    """Let an explicit scenario override passive card/graph context.

    KPI entry points attach their source card to every follow-up. That context is
    useful for ordinary explanation, but it must not trap an explicit modelling
    request inside a canned KPI explanation.
    """
    norm = " ".join(str(question or "").lower().split())
    finance_terms = ("revenue", "cost", "costs", "opex", "cogs", "ebitda", "margin", "cash")
    if not any(term in norm for term in finance_terms):
        return False
    if re.search(r"\b(model|simulate|scenario|project)\b", norm):
        return True
    if re.search(r"\b(if|assume|assuming|what happens|what would happen)\b", norm):
        return True
    if re.search(r"\b(reach|target|achieve|increase|decrease|rise|fall|grow|reduce)\b", norm) and re.search(
        r"\d+(?:\.\d+)?\s*%",
        norm,
    ):
        return True
    # Natural executive phrasing such as "how do we make it 100%?" is still
    # a target calculation.  Without this branch an open Revenue card captures
    # the question as a passive comparison and merely repeats "99.4% of plan".
    # Keep the verbs percentage-gated so ordinary uses of make/get/bring do not
    # turn unrelated finance questions into scenarios.
    if re.search(r"\b(make|get|bring)\s+(?:it|revenue|sales)\b|\bclose\s+the\s+gap\b", norm) and re.search(
        r"\d+(?:\.\d+)?\s*%",
        norm,
    ):
        return True
    return False


def _decimal_references(text: str) -> set[Decimal]:
    """Return CEO-scale decimal references, accepting decimal comma or point."""
    values: set[Decimal] = set()
    for raw in re.findall(r"(?<![\d.])(\d+(?:[.,]\d+))(?![\d.])", str(text or "")):
        try:
            values.add(Decimal(raw.replace(",", ".")))
        except InvalidOperation:
            continue
    return values


def _free_text_ceo_kpi_key(
    question: str,
    context: Mapping[str, Any] | None = None,
    *,
    public_safe: bool = False,
) -> str | None:
    """Route names or uniquely displayed values to the governed KPI contract."""
    if _assistant_question_requests_modelling(question):
        return None
    # The KPI contract states what a figure IS and how it is composed; it does
    # not attribute movement. "Why did revenue drop 12%?" contains "revenue",
    # and answering it from the Revenue card describes a figure while ignoring
    # both the question and the false premise. Guarded here rather than at the
    # call sites because two separate branches consume this key.
    if _question_asks_for_causation(question):
        return None
    # A compound question -- "what is revenue AND the capital of Japan?" -- names
    # a KPI but also carries a second, unrelated ask. The KPI card answers the
    # first half cleanly and silently drops the rest, so the executive never
    # sees their second question acknowledged. When general-knowledge intent
    # rides alongside the KPI term, defer to the reviewed LLM path, which
    # answers every part. A plain "what is revenue?" carries no such intent and
    # still routes here.
    if _question_is_general_knowledge(question):
        return None
    norm = " ".join(str(question or "").casefold().split())
    if any(token in norm for token in ("cash versus floor", "cash-versus-floor", "cash vs floor", "cash floor", "cash position")):
        return "cash_vs_floor"
    if any(token in norm for token in ("ebitda", "operating margin", "margin bridge")):
        return "ebitda_margin"
    if any(token in norm for token in ("operating cost", "operating expense", "opex")):
        return "operating_cost"
    if "revenue" in norm:
        return "revenue"
    references = _decimal_references(question)
    if references and context is not None:
        matches: set[str] = set()
        for card in _ceo_kpi_cards(context, public_safe=public_safe):
            key = str(card.get("key") or card.get("driver_key") or "").strip()
            if not key:
                continue
            # Match only headline displays, never arbitrary component values;
            # ambiguity deliberately falls through to the reviewed LLM path.
            card_values = _decimal_references(
                " ".join(
                    str(card.get(field) or "")
                    for field in ("metric", "value", "pct", "ring_pct")
                )
            )
            if references & card_values:
                matches.add(key)
        if len(matches) == 1:
            return next(iter(matches))
    return None


async def _assistant_chat_response(
    request: AssistantChatRequest | QaRequest,
    *,
    public_safe: bool = False,
    authenticated_role: str | None = None,
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
    conversation_history = _assistant_history_from_request(request)
    if conversation_history:
        assistant_context["history"] = conversation_history
        assistant_context["history_attached"] = True
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

    if not public_safe and _assistant_question_is_challenge_closure(question):
        summary = _latest_summary()
        result = _authenticated_challenge_closure_result(summary)
        challenge_context = {
            "run_id": (summary or {}).get("run_id"),
            "run_mode": str((summary or {}).get("run_mode") or "full"),
        }
        orchestrated = get_orchestrator().process(
            question,
            persona=persona,
            qa_result={
                **result,
                "assistant_mode": "governed_audit",
                "answered_by": "governed_audit",
            },
            driver_context=driver_context,
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=challenge_context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=result,
            llm_status=llm_qa.chat_status(CONFIG),
            assistant_context=assistant_context,
        )
        payload["llm_fallback_attempted"] = False
        return payload

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
        packet = context.get("public_context_packet")
        if not isinstance(packet, dict) or not packet:
            packet = {"source": "empty_packet", "public_safe": True}
        context["public_context_packet"] = dict(packet)
        context["public_context_packet"]["view_state"] = view_state
        # The public packet's conversation view is derived from the same
        # normalized history channel the authenticated path uses, so there is
        # exactly one client->server history contract.
        if conversation_history:
            context["public_context_packet"]["conversation_history"] = [
                {
                    "role": str(item.get("role") or "")[:16],
                    "content": str(item.get("text") or "")[:2400],
                }
                for item in conversation_history[-8:]
                if str(item.get("role") or "") in {"user", "assistant"}
                and str(item.get("text") or "").strip()
            ]
    if conversation_history:
        context["assistant_history"] = conversation_history
    llm_status = _public_safe_llm_status() if public_safe else llm_qa.chat_status(CONFIG)

    calendar_result = (
        None
        if public_safe
        else _governed_calendar_result(
            question,
            context.get("summary"),
            assistant_context=assistant_context,
        )
    )
    if calendar_result is not None:
        orchestrated = get_orchestrator().process(
            question,
            persona=persona,
            qa_result=calendar_result,
            driver_context=driver_context,
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=calendar_result,
            llm_status=llm_status,
            assistant_context=assistant_context,
        )
        payload["llm_fallback_attempted"] = False
        return payload

    if _assistant_question_is_release_gate(question):
        release_result = _governed_release_gate_result(
            context.get("summary"),
            role=authenticated_role or ("executive" if public_safe else "authenticated"),
            public_safe=public_safe,
        )
        orchestrated = get_orchestrator().process(
            question,
            persona=persona,
            qa_result=release_result,
            driver_context=driver_context,
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=release_result,
            llm_status=llm_status,
            assistant_context=assistant_context,
        )
        payload["llm_fallback_attempted"] = False
        return payload

    digital_twin_result = _resolve_digital_twin_status(
        question,
        summary=context.get("summary"),
        role=authenticated_role or ("executive" if public_safe else "authenticated"),
        public_safe=public_safe,
        assistant_context=assistant_context,
    )
    if digital_twin_result is not None:
        orchestrated = get_orchestrator().process(
            question,
            persona=persona,
            qa_result=digital_twin_result,
            driver_context=driver_context,
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=digital_twin_result,
            llm_status=llm_status,
            assistant_context=assistant_context,
        )
        payload["llm_fallback_attempted"] = False
        return payload

    function_review_result = _resolve_finance_function_review(
        question,
        summary=context.get("summary"),
        assistant_context=assistant_context,
        public_safe=public_safe,
    )
    if function_review_result is not None:
        orchestrated = get_orchestrator().process(
            question,
            persona=persona,
            qa_result=function_review_result,
            driver_context=driver_context,
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=function_review_result,
            llm_status=llm_status,
            assistant_context=assistant_context,
        )
        payload["llm_fallback_attempted"] = False
        return payload

    module_result = _resolve_governed_module_status(
        question,
        summary=context.get("summary"),
        assistant_context=assistant_context,
        role=authenticated_role or ("executive" if public_safe else "authenticated"),
        public_safe=public_safe,
    )
    if module_result is not None:
        orchestrated = get_orchestrator().process(
            question,
            persona=persona,
            qa_result=module_result,
            driver_context=driver_context,
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=module_result,
            llm_status=llm_status,
            assistant_context=assistant_context,
        )
        payload["llm_fallback_attempted"] = False
        return payload

    explicit_kpi_key = _free_text_ceo_kpi_key(
        question,
        context,
        public_safe=public_safe,
    )
    contextual_kpi_key = explicit_kpi_key or str(assistant_context.get("kpi_key") or "").strip()
    explicit_modelling_request = _assistant_question_requests_modelling(question)
    if (
        contextual_kpi_key
        and not explicit_modelling_request
        and str(assistant_context.get("entrypoint") or "") in {"ceo_kpi_inline", "knowledge_graph"}
    ):
        kpi_result = _ceo_kpi_inline_result(
            context,
            kpi_key=contextual_kpi_key,
            public_safe=public_safe,
            question=question,
            question_intent=str(assistant_context.get("kpi_question_intent") or "") or None,
        )
        orchestrated = get_orchestrator().process(
            question,
            persona=persona,
            qa_result={**kpi_result, "assistant_mode": "governed_kpi"},
            driver_context={"key": assistant_context.get("kpi_key"), "label": assistant_context.get("kpi_label")},
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=kpi_result,
            llm_status=llm_status,
            assistant_context=assistant_context,
        )
        payload["llm_fallback_attempted"] = False
        return payload

    def _public_safe_unmatched_result(question_text: str, reason: str | None = None) -> dict[str, Any]:
        governed_packet = context.get("public_context_packet")
        if not isinstance(governed_packet, dict):
            governed_packet = {}
        suggestions: list[str] = []
        for item in list(governed_packet.get("drivers") or [])[:2]:
            if isinstance(item, dict):
                label = str(item.get("label") or item.get("key") or "").strip()
                if label:
                    suggestions.append(f"Explain the current {label} signal")
        for item in list(governed_packet.get("findings") or [])[:1]:
            if isinstance(item, dict):
                title = str(item.get("title") or "").strip()
                if title:
                    suggestions.append(f"Why does {title} matter for the board?")
        suggestions.append("What should I prepare for the board?")
        return {
            "matched": False,
            "answer": (
                "I could not match that question to a calculated result in the current reviewed data. "
                "No values were inferred or substituted. Ask about a visible KPI, case, or board decision."
            ),
            "citations": [],
            "suggestions": suggestions[:4],
            "basis": reason or "No calculated result matched the current reviewed data.",
        }

    orchestrator = get_orchestrator()
    findings_payload = [
        finding.__dict__ if hasattr(finding, "__dict__") else finding
        for finding in context["findings"]
    ]

    # "How do I decrease operating cost?" names the KPI, so the reference
    # resolver would claim it and restate the total -- an answer to a different
    # question. Levers run first: they answer what the executive actually asked.
    cost_lever_result = _governed_cost_lever_result(
        context,
        question=question,
        public_safe=public_safe,
    )
    if cost_lever_result is not None:
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            qa_result=cost_lever_result,
            driver_context=driver_context,
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=cost_lever_result,
            llm_status=llm_status,
            assistant_context=assistant_context,
        )
        payload["llm_fallback_attempted"] = False
        return payload

    governed_reference_result = _governed_reference_result(
        context,
        question=question,
        assistant_context=assistant_context,
        history=conversation_history,
        public_safe=public_safe,
    )
    if governed_reference_result is not None:
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            qa_result=governed_reference_result,
            driver_context=driver_context,
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=governed_reference_result,
            llm_status=llm_status,
            assistant_context=assistant_context,
        )
        payload["llm_fallback_attempted"] = False
        return payload

    app_help_result = (
        None
        if public_safe
        else _authenticated_app_help_result(
            question,
            role=authenticated_role or str(assistant_context.get("role") or "authenticated"),
        )
    )
    if app_help_result is not None:
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            qa_result=app_help_result,
            driver_context=driver_context,
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=app_help_result,
            llm_status=llm_status,
            assistant_context=assistant_context,
        )
        payload["llm_fallback_attempted"] = False
        return payload

    # mode="llm" is an explicit request for the governed model path (bundle +
    # findings). Only mode="auto" may fall through to general knowledge, and
    # only for a question no governed component claims.
    if (
        not public_safe
        and mode == "auto"
        and not context.get("run_id")
        and not context.get("findings")
        and not _question_is_governed_business_question(question, context=context)
    ):
        general_status = llm_qa.chat_status(CONFIG)
        if general_status.get("enabled"):
            general_result = await asyncio.get_running_loop().run_in_executor(
                _LLM_PROVIDER_EXECUTOR,
                lambda: llm_qa.answer_general_question(
                    question,
                    config=CONFIG,
                    persona=persona,
                ),
            )
            orchestrated = orchestrator.process(
                question,
                persona=persona,
                llm_result={**general_result, "assistant_mode": "llm", "answered_by": "llm"},
                driver_context=driver_context,
            )
            payload = _assistant_response_payload(
                response_mode="llm",
                question=question,
                context=context,
                requested_mode=mode,
                persona=persona,
                orchestrated=orchestrated,
                base_result=general_result,
                llm_status=general_result.get("llm_status") or general_status,
                assistant_context=assistant_context,
            )
            payload["mode"] = "llm"
            payload["llm_fallback_attempted"] = True
            payload["llm_general_answer"] = True
            return payload
        if mode == "llm":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=general_status.get("reason") or "LLM chat is not configured.",
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
                "public_context_packet": context.get("public_context_packet") or {},
                "summary": context["summary"],
                "run_id": context["run_id"],
                "run_mode": context["run_mode"],
                "persona": persona,
                "assistant_context": assistant_context,
                "assistant_history": conversation_history,
                "driver_context": driver_context,
            },
        )
        scenario_result = parsed.as_dict()
        if public_safe and parsed.matched:
            scenario_result.setdefault("answered_by", "packet")
        public_packet_catchall = (
            public_safe
            and str(scenario_result.get("scenario_id") or "") == "public_exec_governed_packet"
            and mode in {"auto", "llm"}
            and bool(llm_status.get("enabled"))
        )
        if parsed.matched and not public_packet_catchall:
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

    free_text_kpi_key = explicit_kpi_key
    if free_text_kpi_key:
        kpi_result = _ceo_kpi_inline_result(
            context,
            kpi_key=free_text_kpi_key,
            public_safe=public_safe,
            question=question,
        )
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            qa_result={**kpi_result, "assistant_mode": "governed_kpi"},
            driver_context={"key": free_text_kpi_key},
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=kpi_result,
            llm_status=llm_status,
            assistant_context=assistant_context,
        )
        payload["llm_fallback_attempted"] = False
        return payload

    if public_safe and context.get("public_context_packet") is not None:
        if mode != "deterministic" and llm_status.get("enabled"):
            try:
                public_llm_result = await _llm_answer_question_async(
                    question,
                    bundle=context["bundle"],
                    findings=context["findings"],
                    summary=context["summary"],
                    config=CONFIG,
                    public_context_packet=context["public_context_packet"],
                    persona=persona,
                )
            except RuntimeError:
                # The CEO sees a useful board-packet fallback, never provider
                # transport details. The shared UI keeps its retry/cache path.
                public_llm_result = None
            if public_llm_result is not None:
                model_result = {
                    **public_llm_result,
                    "llm_matched": bool(public_llm_result.get("matched")),
                    # A best-effort model answer remains the selected answer
                    # even when its own evidence match is incomplete. The
                    # review contract below carries that uncertainty visibly.
                    "matched": True,
                    "assistant_mode": "llm",
                    "answered_by": "llm",
                    "_orchestrator_force_answer": True,
                }
                orchestrated = orchestrator.process(
                    question,
                    persona=persona,
                    llm_result=model_result,
                    driver_context=request.driver_context,
                )
                payload = _assistant_response_payload(
                    response_mode="llm",
                    question=question,
                    context=context,
                    requested_mode=mode,
                    persona=persona,
                    orchestrated=orchestrated,
                    base_result=model_result,
                    llm_status=public_llm_result.get("llm_status") or llm_status,
                    assistant_context=assistant_context,
                )
                payload["mode"] = "llm"
                payload["llm_fallback_attempted"] = True
                payload["public_packet_only"] = True
                return payload

        if (
            scenario_result
            and scenario_result.get("matched")
            and str(scenario_result.get("scenario_id") or "") == "public_exec_governed_packet"
        ):
            # Provider failure degrades to the already-computed public packet
            # answer. It must not fall through to an unrelated generic reply.
            orchestrated = orchestrator.process(
                question,
                persona=persona,
                scenario_result=scenario_result,
                driver_context=request.driver_context,
            )
            payload = _assistant_response_payload(
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
            payload["llm_fallback_attempted"] = True
            return payload

        public_safe_result = _public_safe_unmatched_result(
            question,
            None if mode == "deterministic" else llm_status.get("reason"),
        )
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            qa_result={
                **public_safe_result,
                "assistant_mode": "packet",
                "answered_by": "packet",
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
        payload["llm_fallback_attempted"] = mode != "deterministic" and bool(llm_status.get("enabled"))
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

    graph_result = route_graph_question(context["run_id"], question)
    retrieval_result = _route_keyword_retrieval(context["run_id"], question)
    if graph_result.get("matched") or retrieval_result.get("matched"):
        selected_result = graph_result if graph_result.get("matched") else retrieval_result
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            graph_result=graph_result,
            retrieval_result=retrieval_result,
            driver_context=driver_context,
        )
        return _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=selected_result,
            llm_status=llm_status,
            assistant_context=assistant_context,
        )
    scope_boundary_result = _unavailable_external_decision_result(question, context)
    if scope_boundary_result is not None:
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            qa_result={**scope_boundary_result, "assistant_mode": "evidence_scope_boundary"},
            driver_context=driver_context,
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=orchestrated,
            base_result=scope_boundary_result,
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
    deterministic_result.setdefault("answered_by", "tabular")
    if mode == "deterministic" or deterministic_result.get("matched") is not False:
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            qa_result={**deterministic_result, "assistant_mode": "qa_engine", "answered_by": deterministic_result.get("answered_by") or "tabular", "_orchestrator_force_answer": True},
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
            qa_result={**deterministic_result, "answered_by": deterministic_result.get("answered_by") or "tabular"},
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

    try:
        result = await _llm_answer_question_async(
            question,
            bundle=context["bundle"],
            findings=context["findings"],
            summary=context["summary"],
            config=CONFIG,
            persona=persona,
            supplemental_evidence=_supplemental_grounding_payload(
                graph_result=graph_result,
                retrieval_result=retrieval_result,
                deterministic_result=deterministic_result,
                assistant_history=conversation_history,
            ),
        )
    except RuntimeError as exc:
        transport_status = dict(llm_qa.provider_transport_payload(exc) or {})
        if mode == "llm":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"message": str(exc), "transport": transport_status} if transport_status else str(exc),
            ) from exc
        if transport_status:
            transport_status["fallback_used"] = True
        failure_status = {**llm_status, "transport": transport_status}
        fallback_result = {
            **deterministic_result,
            "assistant_mode": "qa_engine",
            "answered_by": deterministic_result.get("answered_by") or "tabular",
            "_orchestrator_force_answer": True,
        }
        fallback_orchestrated = orchestrator.process(
            question,
            persona=persona,
            qa_result=fallback_result,
            driver_context=driver_context,
        )
        payload = _assistant_response_payload(
            response_mode="deterministic",
            question=question,
            context=context,
            requested_mode=mode,
            persona=persona,
            orchestrated=fallback_orchestrated,
            base_result=fallback_result,
            llm_status=failure_status,
            assistant_context=assistant_context,
        )
        payload["llm_fallback_attempted"] = True
        payload["llm_error"] = str(exc)
        payload["trace"]["llm_transport_failed"] = True
        return payload
    if result.get("matched") is False:
        grounded_fallback = None
        if graph_result and graph_result.get("matched"):
            grounded_fallback = graph_result
        elif retrieval_result and retrieval_result.get("matched"):
            grounded_fallback = retrieval_result
        elif deterministic_result.get("matched") is not False:
            grounded_fallback = {
                **deterministic_result,
                "assistant_mode": "qa_engine",
                "answered_by": deterministic_result.get("answered_by") or "tabular",
            }
        if grounded_fallback is not None:
            grounded_orchestrated = orchestrator.process(
                question,
                persona=persona,
                graph_result=graph_result,
                retrieval_result=retrieval_result,
                qa_result={
                    **deterministic_result,
                    "assistant_mode": "qa_engine",
                    "answered_by": deterministic_result.get("answered_by") or "tabular",
                },
                driver_context=driver_context,
            )
            payload = _assistant_response_payload(
                response_mode="llm",
                question=question,
                context=context,
                requested_mode=mode,
                persona=persona,
                orchestrated=grounded_orchestrated,
                base_result=grounded_fallback,
                llm_status=result.get("llm_status") or llm_status,
                assistant_context=assistant_context,
            )
            payload["mode"] = "llm"
            payload["llm_fallback_attempted"] = True
            payload["llm_grounded_fallback"] = True
            return payload
    selected_llm_result = {
        **result,
        "llm_matched": bool(result.get("matched")),
        "matched": True,
        "assistant_mode": "llm",
        "answered_by": "llm",
        "_orchestrator_force_answer": True,
    }
    orchestrated = orchestrator.process(
        question,
        persona=persona,
        graph_result=graph_result,
        retrieval_result=retrieval_result,
        qa_result={
            **deterministic_result,
            "assistant_mode": "qa_engine",
            "answered_by": deterministic_result.get("answered_by") or "tabular",
        },
        llm_result=selected_llm_result,
        driver_context=driver_context,
    )
    payload = _assistant_response_payload(
        response_mode="llm",
        question=question,
        context=context,
        requested_mode=mode,
        persona=persona,
        orchestrated=orchestrated,
        base_result=selected_llm_result,
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
    conversation_history = _assistant_history_from_request(request)
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
            "answered_by": orchestrated_payload.answered_by,
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

    graph_result = None
    retrieval_result = None
    deterministic_result = None

    if mode == "llm":
        if context["bundle"] is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No completed run is available to answer questions yet. Start a run first.",
            )
        graph_result = route_graph_question(context["run_id"], question)
        retrieval_result = _route_keyword_retrieval(context["run_id"], question)
        deterministic_result = qa_engine.answer_question(
            question, bundle=context["bundle"], findings=context["findings"]
        )
        deterministic_result.setdefault("answered_by", "tabular")
        try:
            result = llm_qa.answer_question(
                question,
                bundle=context["bundle"],
                findings=context["findings"],
                summary=context["summary"],
                config=CONFIG,
                persona=persona,
                supplemental_evidence=_supplemental_grounding_payload(
                    graph_result=graph_result,
                    retrieval_result=retrieval_result,
                    deterministic_result=deterministic_result,
                ),
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
        if result.get("matched") is False:
            grounded_fallback = None
            if graph_result and graph_result.get("matched"):
                grounded_fallback = graph_result
            elif retrieval_result and retrieval_result.get("matched"):
                grounded_fallback = retrieval_result
            elif deterministic_result.get("matched") is not False:
                grounded_fallback = {
                    **deterministic_result,
                    "assistant_mode": "qa_engine",
                    "answered_by": deterministic_result.get("answered_by") or "tabular",
                }
            if grounded_fallback is not None:
                grounded_orchestrated = orchestrator.process(
                    question,
                    persona=persona,
                    graph_result=graph_result,
                    retrieval_result=retrieval_result,
                    qa_result={
                        **deterministic_result,
                        "assistant_mode": "qa_engine",
                        "answered_by": deterministic_result.get("answered_by") or "tabular",
                    },
                    driver_context=driver_context,
                )
                return _compose_response(
                    response_mode="llm",
                    base_payload={**grounded_fallback, "deterministic_matched": True},
                    orchestrated_payload=grounded_orchestrated,
                    extra_trace={
                        "route": "llm_grounded_fallback",
                        "intent": grounded_fallback.get("intent"),
                        "knowledge_id": request.knowledge_id,
                    },
                    extra_payload={"llm_fallback_attempted": True, "llm_grounded_fallback": True},
                    status_payload=result.get("llm_status") or llm_status,
                )
        orchestrated = orchestrator.process(
            question,
            persona=persona,
            graph_result=graph_result,
            retrieval_result=retrieval_result,
            qa_result={
                **deterministic_result,
                "assistant_mode": "qa_engine",
                "answered_by": deterministic_result.get("answered_by") or "tabular",
            },
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

    if context["bundle"] is not None and mode in {"auto", "deterministic"}:
        graph_result = route_graph_question(context["run_id"], question)
        retrieval_result = _route_keyword_retrieval(context["run_id"], question)
        if graph_result.get("matched") or retrieval_result.get("matched"):
            selected_result = graph_result if graph_result.get("matched") else retrieval_result
            orchestrated = orchestrator.process(
                question,
                persona=persona,
                graph_result=graph_result,
                retrieval_result=retrieval_result,
                driver_context=driver_context,
            )
            route_name = "graph_grounding" if graph_result.get("matched") else "vector_keyword_retrieval"
            return _compose_response(
                response_mode="deterministic",
                base_payload=selected_result,
                orchestrated_payload=orchestrated,
                extra_trace={
                    "route": route_name,
                    "intent": selected_result.get("intent"),
                    "knowledge_id": request.knowledge_id,
                },
            )
        deterministic_result = qa_engine.answer_question(
            question, bundle=context["bundle"], findings=context["findings"]
        )
        deterministic_result.setdefault("answered_by", "tabular")
        if mode == "deterministic" or deterministic_result.get("matched") is not False:
            orchestrated = orchestrator.process(
                question,
                persona=persona,
                qa_result={**deterministic_result, "assistant_mode": "qa_engine", "answered_by": deterministic_result.get("answered_by") or "tabular"},
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
            qa_result={**deterministic_result, "assistant_mode": "qa_engine", "answered_by": deterministic_result.get("answered_by") or "tabular"},
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
            persona=persona,
            supplemental_evidence=_supplemental_grounding_payload(
                graph_result=graph_result,
                retrieval_result=retrieval_result,
                deterministic_result=deterministic_result,
                assistant_history=conversation_history,
            ),
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
        graph_result=graph_result,
        retrieval_result=retrieval_result,
        qa_result={**deterministic_result, "assistant_mode": "qa_engine", "answered_by": deterministic_result.get("answered_by") or "tabular"} if deterministic_result is not None else None,
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
    if CONFIG.login_required:
        _require_login_if_enabled(principal)
        return await _assistant_chat_response(
            request,
            public_safe=False,
            authenticated_role=role,
        )
    persona = (request.persona or "ceo").strip().lower() or "ceo"
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

    return await _assistant_chat_response(request, public_safe=False, authenticated_role=role)


@app.post("/inputs/prepare")
def prepare_inputs(
    _: dict[str, Any] = require_role("operator"),
) -> dict[str, str]:
    agent_input, evaluation = prepare_agent_input()
    return {"agent_input": str(agent_input), "evaluation": str(evaluation)}
