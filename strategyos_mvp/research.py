"""Governed public-research contracts and the private gateway client.

The gateway never receives the user's question.  This module maps a question to
closed catalogue identifiers and sends only those identifiers over the private
service boundary.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import CONFIG, EXTERNAL_MODE_PUBLIC_RESEARCH


TOPICS: dict[str, tuple[str, tuple[str, ...]]] = {
    "channel_concentration": (
        "market concentration Herfindahl distribution channels",
        ("concentration", "modern trade", "channel mix", "retail channel"),
    ),
    "regulatory_change": (
        "pharmaceutical regulation compliance public guidance",
        ("regulation", "regulatory", "compliance", "law", "legal"),
    ),
    "competitor_activity": (
        "pharmaceutical industry competitive strategy public information",
        ("competitor", "competition", "competitive", "market share"),
    ),
    "market_conditions": (
        "pharmaceutical market conditions public industry benchmarks",
        ("market", "industry benchmark", "external benchmark", "sector"),
    ),
    "management_practice": (
        "corporate management best practice public guidance",
        ("best practice", "general practice", "management practice", "consult practice"),
    ),
}

GEOGRAPHIES = {
    "global": "global",
    "saudi_arabia": "Saudi Arabia",
    "united_arab_emirates": "United Arab Emirates",
    "european_union": "European Union",
    "united_kingdom": "United Kingdom",
    "united_states": "United States",
}

PERIODS = {"current": "current", "2025": "2025", "2026": "2026"}
LANGUAGES = {"en": "English"}


class ResearchDenied(RuntimeError):
    """Raised before transport when public-research policy is not satisfied."""


class ResearchUnavailable(RuntimeError):
    """Raised when an approved gateway request cannot be completed."""


@dataclass(frozen=True)
class PublicResearchRequest:
    topic_id: str
    geography_id: str = "global"
    period_id: str = "current"
    language: str = "en"
    source_set_id: str = "wikipedia_public_v1"

    def as_dict(self) -> dict[str, str]:
        return {
            "topic_id": self.topic_id,
            "geography_id": self.geography_id,
            "period_id": self.period_id,
            "language": self.language,
            "source_set_id": self.source_set_id,
        }


def compile_public_request(question: str) -> PublicResearchRequest:
    """Map private prose to closed public identifiers without copying prose."""
    normalized = " ".join(str(question or "").casefold().split())
    matches = [
        topic_id
        for topic_id, (_, phrases) in TOPICS.items()
        if any(phrase in normalized for phrase in phrases)
    ]
    if not matches:
        raise ResearchDenied(
            "No approved public research topic matches this request."
        )
    # Prefer the most specific catalogues over generic market/practice wording.
    priority = (
        "channel_concentration",
        "regulatory_change",
        "competitor_activity",
        "market_conditions",
        "management_practice",
    )
    topic_id = next(topic for topic in priority if topic in matches)
    geography_id = (
        os.getenv("STRATEGYOS_RESEARCH_GEOGRAPHY_ID", "global").strip().lower()
        or "global"
    )
    period_id = (
        os.getenv("STRATEGYOS_RESEARCH_PERIOD_ID", "current").strip().lower()
        or "current"
    )
    if geography_id not in GEOGRAPHIES or period_id not in PERIODS:
        raise ResearchDenied("The configured public research profile is not approved.")
    return PublicResearchRequest(
        topic_id=topic_id,
        geography_id=geography_id,
        period_id=period_id,
    )


def public_query(payload: Mapping[str, Any]) -> str:
    """Build the provider query inside the gateway from allowlisted values."""
    if set(payload) != {
        "topic_id", "geography_id", "period_id", "language", "source_set_id"
    }:
        raise ResearchDenied("Research request fields do not match the approved contract.")
    topic_id = str(payload.get("topic_id") or "")
    geography_id = str(payload.get("geography_id") or "")
    period_id = str(payload.get("period_id") or "")
    language = str(payload.get("language") or "")
    source_set_id = str(payload.get("source_set_id") or "")
    if (
        topic_id not in TOPICS
        or geography_id not in GEOGRAPHIES
        or period_id not in PERIODS
        or language not in LANGUAGES
        or source_set_id != "wikipedia_public_v1"
    ):
        raise ResearchDenied("Research request contains an unapproved catalogue value.")
    parts = [TOPICS[topic_id][0]]
    if geography_id != "global":
        parts.append(GEOGRAPHIES[geography_id])
    if period_id != "current":
        parts.append(PERIODS[period_id])
    return " ".join(parts)


AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS strategyos_research_audit (
 id uuid PRIMARY KEY,
 tenant_key text NOT NULL,
 subject text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 completed_at timestamptz,
 status text NOT NULL,
 request_sha256 text NOT NULL,
 request_json jsonb NOT NULL,
 destination text NOT NULL,
 gateway_request_id text,
 provider_request_id text,
 result_sha256 text,
 failure_reason text
)
"""


def _principal() -> Mapping[str, Any]:
    from .access_scope import principal_scope
    principal = principal_scope.get()
    if not principal or principal.get("auth_disabled"):
        raise ResearchDenied("Authenticated tenant scope is required for research.")
    return principal


def _audit_start(payload: Mapping[str, Any]) -> tuple[str, str]:
    from . import state_store
    principal = _principal()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    audit_id = str(uuid.uuid4())
    handle, failure = state_store.database_connection()
    if failure or handle is None:
        raise ResearchDenied("Durable research audit is unavailable.")
    with handle as conn:
        state_store.ensure_auxiliary_schema(conn, AUDIT_SCHEMA)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO strategyos_research_audit
                (id,tenant_key,subject,status,request_sha256,request_json,destination)
                VALUES (%s,%s,%s,'approved',%s,%s::jsonb,%s)""",
                (
                    audit_id,
                    str(principal.get("tenant_id") or CONFIG.tenant_slug),
                    str(principal.get("subject") or ""),
                    hashlib.sha256(canonical.encode()).hexdigest(),
                    canonical,
                    "research-gateway:wikipedia_public_v1",
                ),
            )
        conn.commit()
    return audit_id, canonical


def _audit_finish(
    audit_id: str,
    *,
    status: str,
    result: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    from . import state_store
    principal = _principal()
    result_json = json.dumps(result or {}, sort_keys=True, separators=(",", ":"))
    handle, failure = state_store.database_connection()
    if failure or handle is None:
        raise ResearchUnavailable("Research outcome is uncertain because its audit could not be completed.")
    with handle as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE strategyos_research_audit
                SET status=%s,completed_at=now(),gateway_request_id=%s,
                    provider_request_id=%s,result_sha256=%s,failure_reason=%s
                WHERE id=%s AND tenant_key=%s""",
                (
                    status,
                    str((result or {}).get("gateway_request_id") or "") or None,
                    str((result or {}).get("provider_request_id") or "") or None,
                    hashlib.sha256(result_json.encode()).hexdigest() if result else None,
                    str(reason or "")[:1000] or None,
                    audit_id,
                    str(principal.get("tenant_id") or CONFIG.tenant_slug),
                ),
            )
            if cur.rowcount != 1:
                raise ResearchUnavailable("Research audit record could not be reconciled.")
        conn.commit()


def status() -> dict[str, Any]:
    enabled = os.getenv("STRATEGYOS_RESEARCH_ENABLED", "false").lower() == "true"
    allowed = CONFIG.run_policy.allows(EXTERNAL_MODE_PUBLIC_RESEARCH)
    gateway = os.getenv("STRATEGYOS_RESEARCH_GATEWAY_URL", "").strip()
    token = os.getenv("STRATEGYOS_RESEARCH_GATEWAY_TOKEN", "").strip()
    return {
        "enabled": bool(enabled and allowed and gateway and token),
        "policy_allowed": allowed,
        "gateway_configured": bool(gateway and token),
        "mode": "approved_public_templates",
        "source_set": "wikipedia_public_v1",
    }


def run(question: str) -> dict[str, Any]:
    posture = status()
    if not posture["enabled"]:
        raise ResearchDenied("Governed external research is disabled for this deployment.")
    outbound = compile_public_request(question).as_dict()
    audit_id, canonical = _audit_start(outbound)
    gateway_url = os.environ["STRATEGYOS_RESEARCH_GATEWAY_URL"].rstrip("/")
    token = os.environ["STRATEGYOS_RESEARCH_GATEWAY_TOKEN"]
    request = Request(
        gateway_url + "/v1/research",
        data=canonical.encode(),
        method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=float(os.getenv("STRATEGYOS_RESEARCH_TIMEOUT_SECONDS", "15"))) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict) or result.get("status") != "completed":
            raise ResearchUnavailable("Research gateway returned an invalid result.")
        _audit_finish(audit_id, status="completed", result=result)
        return {**result, "audit_trail_id": audit_id, "outbound_contract": outbound}
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ResearchUnavailable) as exc:
        try:
            _audit_finish(audit_id, status="failed", reason=str(exc))
        except ResearchUnavailable:
            raise
        raise ResearchUnavailable("The approved public research request could not be completed.") from exc


def gateway_token_valid(value: str) -> bool:
    expected = os.getenv("STRATEGYOS_RESEARCH_GATEWAY_TOKEN", "")
    return bool(expected and hmac.compare_digest(value, expected))
