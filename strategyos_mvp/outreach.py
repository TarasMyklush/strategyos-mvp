"""Typed, sector-neutral outreach workflow for connector-free demonstrations.

The workflow keeps synthetic thread examples read-only and permits executives to
draft tenant-scoped structured data requests. The contract enforces the same
approval, retention and reply-parsing boundaries required by a future mailbox
adapter; no draft can send mail or mutate governed facts.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from .dimensional_plan import Contract, Name
from .config import CONFIG

Status = Literal["drafted", "awaiting_approval", "sent", "replied", "flagged"]
OutcomeKind = Literal["confirmed_commitment", "updated_forecast", "flagged_risk"]


class OutreachControls(Contract):
    mode: Literal["synthetic"] = "synthetic"
    connector_enabled: Literal[False] = False
    mailbox_class: Literal["dedicated_agent"] = "dedicated_agent"
    approval_required_before_send: Literal[True] = True
    delete_capability: Literal[False] = False
    raw_reply_stored: Literal[False] = False
    authority_effect: Literal["none"] = "none"


class AgentIdentity(Contract):
    agent_id: Name
    name: Name
    accountable_role: Name


class Provider(Contract):
    provider_id: Name
    name: Name
    role: Name
    connection_status: Literal["connected", "not_connected"]


class Trigger(Contract):
    kind: Literal["data_source_contract", "executive_question"]
    reference_id: Name
    label: Name
    reason: str = Field(min_length=10, max_length=500)


class KnowledgeProjection(Contract):
    entry_id: Name
    kind: Literal["commitment", "forecast", "risk"]
    subject_ref: Name
    predicate: Name
    value: str = Field(min_length=1, max_length=300)
    unit: Name | None = None
    source_thread_id: Name
    disposition: Literal["synthetic_projection"] = "synthetic_projection"


class StructuredOutcome(Contract):
    kind: OutcomeKind
    summary: str = Field(min_length=10, max_length=500)
    knowledge_entry: KnowledgeProjection

    @model_validator(mode="after")
    def matching_projection(self):
        expected = {
            "confirmed_commitment": "commitment",
            "updated_forecast": "forecast",
            "flagged_risk": "risk",
        }[self.kind]
        if self.knowledge_entry.kind != expected:
            raise ValueError("Reply outcome and knowledge projection kinds must match.")
        return self


class LifecycleEvent(Contract):
    action: Literal[
        "drafted", "approval_requested", "sent", "reasked", "reply_parsed", "flagged"
    ]
    status: Status
    occurred_at: datetime
    actor: Name
    note: str = Field(min_length=4, max_length=300)
    attempt: int | None = Field(default=None, ge=1, le=3, strict=True)
    approved_by: Name | None = None

    @model_validator(mode="after")
    def governed_event(self):
        expected_status = {
            "drafted": "drafted",
            "approval_requested": "awaiting_approval",
            "sent": "sent",
            "reasked": "sent",
            "reply_parsed": "replied",
            "flagged": "flagged",
        }[self.action]
        if self.status != expected_status:
            raise ValueError("Lifecycle action and status do not match.")
        if self.action in {"sent", "reasked"} and not self.approved_by:
            raise ValueError("Synthetic send events require a named approver.")
        if self.action not in {"sent", "reasked"} and self.approved_by is not None:
            raise ValueError("Approval attribution belongs only on send events.")
        if self.action in {"sent", "reasked"} and self.attempt is None:
            raise ValueError("Synthetic send events require an attempt number.")
        if self.action not in {"sent", "reasked"} and self.attempt is not None:
            raise ValueError("Attempt numbers belong only on send events.")
        return self


class OutreachThread(Contract):
    thread_id: Name
    title: Name
    agent: AgentIdentity
    provider_id: Name
    question: str = Field(min_length=10, max_length=500)
    trigger: Trigger
    current_status: Status
    lifecycle: list[LifecycleEvent] = Field(min_length=1, max_length=12)
    outcome: StructuredOutcome | None = None

    @model_validator(mode="after")
    def valid_lifecycle(self):
        if self.lifecycle[0].action != "drafted":
            raise ValueError("Every outreach thread must start as a draft.")
        if self.lifecycle[-1].status != self.current_status:
            raise ValueError("Current status must match the final lifecycle event.")
        rank = {"drafted": 0, "awaiting_approval": 1, "sent": 2, "replied": 3, "flagged": 3}
        ranks = [rank[event.status] for event in self.lifecycle]
        if any(after < before for before, after in zip(ranks, ranks[1:])):
            raise ValueError("Outreach lifecycle cannot move backwards.")
        if any(event.status in {"sent", "replied", "flagged"} for event in self.lifecycle):
            if "awaiting_approval" not in {event.status for event in self.lifecycle}:
                raise ValueError("Outbound contact cannot precede approval request.")
        needs_outcome = self.current_status in {"replied", "flagged"}
        if needs_outcome != (self.outcome is not None):
            raise ValueError("Replied and flagged threads require one structured outcome only.")
        if self.current_status == "flagged" and self.outcome and self.outcome.kind != "flagged_risk":
            raise ValueError("Flagged threads may create only a flagged-risk projection.")
        if self.current_status == "replied" and self.outcome and self.outcome.kind == "flagged_risk":
            raise ValueError("Parsed replies must create a commitment or forecast projection.")
        if self.outcome and self.outcome.knowledge_entry.source_thread_id != self.thread_id:
            raise ValueError("Knowledge projection must point back to its outreach thread.")
        return self


class OutreachPack(Contract):
    schema_version: Literal[1] = 1
    pack_id: Name
    label: Name
    controls: OutreachControls = Field(default_factory=OutreachControls)
    providers: list[Provider] = Field(min_length=1, max_length=100)
    threads: list[OutreachThread] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def complete_catalog(self):
        provider_ids = [item.provider_id for item in self.providers]
        thread_ids = [item.thread_id for item in self.threads]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("Provider IDs must be unique.")
        if len(thread_ids) != len(set(thread_ids)):
            raise ValueError("Thread IDs must be unique.")
        unknown = sorted({item.provider_id for item in self.threads} - set(provider_ids))
        if unknown:
            raise ValueError("Threads reference unknown providers: " + ", ".join(unknown))
        required = {"drafted", "awaiting_approval", "sent", "replied", "flagged"}
        missing = sorted(required - {item.current_status for item in self.threads})
        if missing:
            raise ValueError("Synthetic pack must demonstrate every lifecycle status: " + ", ".join(missing))
        entries = [item.outcome.knowledge_entry.entry_id for item in self.threads if item.outcome]
        if len(entries) != len(set(entries)):
            raise ValueError("Knowledge projection IDs must be unique.")
        return self


class DataRequestCreate(Contract):
    kpi_label: Name
    provider: Name
    formula: str = Field(min_length=3, max_length=1000)
    missing_inputs: list[Name] = Field(min_length=1, max_length=20)
    source_contract_id: Name | None = None


_REQUEST_LOCK = threading.Lock()


class OutreachUnavailable(RuntimeError):
    pass


def _request_store(principal: dict[str, object]) -> Path:
    context = principal.get("tenant_context") if isinstance(principal.get("tenant_context"), dict) else {}
    tenant = str((context or {}).get("tenant_id") or principal.get("tenant_id") or "default")
    safe_tenant = re.sub(r"[^A-Za-z0-9_.-]+", "-", tenant).strip("-")[:100] or "default"
    return CONFIG.output_root / "outreach_requests" / f"{safe_tenant}.json"


def _database_requests(principal: dict[str, object]) -> list[dict[str, object]] | None:
    if not CONFIG.database_url:
        return None
    from . import state_store
    handle, failure = state_store.database_connection()
    if handle is None:
        raise OutreachUnavailable(str((failure or {}).get("reason") or "The request store is unavailable."))
    tenant = str(principal.get("tenant_id") or "").strip()
    try:
        with handle as connection:
            cursor = connection.execute(
                """SELECT payload FROM strategyos_intent_outreach_requests
                   WHERE tenant_key=%s ORDER BY created_at DESC, request_id DESC LIMIT 500""",
                (tenant,),
            )
            return [row[0] for row in cursor.fetchall() if isinstance(row[0], dict)]
    except Exception as exc:
        raise OutreachUnavailable("The governed outreach request store is unavailable.") from exc


def list_data_requests(principal: dict[str, object]) -> list[dict[str, object]]:
    database_records = _database_requests(principal)
    if database_records is not None:
        return database_records
    path = _request_store(principal)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return payload if isinstance(payload, list) else []


def create_data_request(principal: dict[str, object], request: DataRequestCreate) -> dict[str, object]:
    actor = str(principal.get("display_name") or principal.get("role") or "Executive")
    record: dict[str, object] = {
        "request_id": "data-request-" + uuid4().hex,
        "kpi_label": request.kpi_label,
        "provider": request.provider,
        "formula": request.formula,
        "missing_inputs": list(request.missing_inputs),
        "source_contract_id": request.source_contract_id,
        "status": "drafted",
        "created_at": datetime.now(UTC).isoformat(),
        "created_by": actor,
        "approval_required_before_send": True,
        "connector_enabled": False,
    }
    if CONFIG.database_url:
        from . import state_store
        handle, failure = state_store.database_connection()
        if handle is None:
            raise OutreachUnavailable(str((failure or {}).get("reason") or "The request store is unavailable."))
        tenant = str(principal.get("tenant_id") or "").strip()
        try:
            with handle as connection:
                connection.execute(
                    """INSERT INTO strategyos_intent_outreach_requests
                       (tenant_key,request_id,payload,created_by) VALUES (%s,%s,%s::jsonb,%s)""",
                    (tenant, record["request_id"], json.dumps(record, ensure_ascii=False), actor),
                )
            return record
        except Exception as exc:
            raise OutreachUnavailable("The governed outreach request could not be recorded.") from exc

    path = _request_store(principal)
    with _REQUEST_LOCK:
        records = list_data_requests(principal)
        records.append(record)
        records = records[-500:]
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
        temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    return record


DEFAULT_PACK = Path(__file__).parent / "config_packs" / "outreach" / "synthetic-neutral.v1.json"


def load_pack(path: Path = DEFAULT_PACK) -> OutreachPack:
    return OutreachPack.model_validate_json(path.read_text(encoding="utf-8"))


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_catalog(pack: OutreachPack | None = None, *, requests: list[dict[str, object]] | None = None) -> dict[str, object]:
    pack = pack or load_pack()
    payload = pack.model_dump(mode="json")
    status_counts = {status: 0 for status in ("drafted", "awaiting_approval", "sent", "replied", "flagged")}
    for thread in pack.threads:
        status_counts[thread.current_status] += 1
    contacted = {item.provider_id for item in pack.threads if item.current_status != "drafted"}
    responding = {item.provider_id for item in pack.threads if item.current_status == "replied"}
    flagged = {item.provider_id for item in pack.threads if item.current_status == "flagged"}
    payload["coverage"] = {
        "named_provider_count": len(pack.providers),
        "connected_count": sum(item.connection_status == "connected" for item in pack.providers),
        "contacted_count": len(contacted),
        "responding_count": len(responding),
        "flagged_count": len(flagged),
        "status_counts": status_counts,
    }
    payload["catalog_digest"] = hashlib.sha256(_canonical(payload)).hexdigest()
    payload["data_requests"] = list(requests or [])
    return payload


def thread_detail(thread_id: str, pack: OutreachPack | None = None) -> dict[str, object]:
    catalog = build_catalog(pack)
    provider_by_id = {item["provider_id"]: item for item in catalog["providers"]}
    for item in catalog["threads"]:
        if item["thread_id"] == thread_id:
            return {
                "mode": catalog["controls"]["mode"],
                "authority_effect": catalog["controls"]["authority_effect"],
                "catalog_digest": catalog["catalog_digest"],
                "provider": provider_by_id[item["provider_id"]],
                "thread": item,
            }
    raise KeyError(thread_id)


def knowledge_detail(entry_id: str, pack: OutreachPack | None = None) -> dict[str, object]:
    catalog = build_catalog(pack)
    for thread in catalog["threads"]:
        outcome = thread.get("outcome")
        if outcome and outcome["knowledge_entry"]["entry_id"] == entry_id:
            return {
                "mode": catalog["controls"]["mode"],
                "authority_effect": catalog["controls"]["authority_effect"],
                "catalog_digest": catalog["catalog_digest"],
                "entry": outcome["knowledge_entry"],
                "source_thread": {
                    "thread_id": thread["thread_id"],
                    "title": thread["title"],
                    "trigger": thread["trigger"],
                },
            }
    raise KeyError(entry_id)
