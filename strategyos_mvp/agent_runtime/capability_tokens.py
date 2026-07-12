"""Short-lived, server-signed task capability tokens (design doc section
13 "Capability token").

No JWT/JOSE library is installed in this project (confirmed before writing
this module), so the token is a minimal HMAC-SHA256-signed, base64url
JSON envelope built from the standard library only -- the same security
property (tamper-evident, server-issued, time-bounded) without adding a
new third-party dependency mid-feature.

Contains: tenant, task, attempt, and agent IDs; allowed tool keys; data
scope/reference IDs; maximum risk class; expiry and nonce. Tool dispatch
(tools.invoke_tool, called from workers.py) verifies it. The token is
never forwarded to an LLM or written into a prompt -- it is only ever
passed to invoke_tool()/ToolExecutionContext construction in workflows.py,
never serialized into a handler's `input` dict (which is what a handler
might pass to an LLM call).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from ..config import CONFIG

DEFAULT_TTL_SECONDS = 300


class CapabilityTokenError(Exception):
    pass


class CapabilityTokenExpired(CapabilityTokenError):
    pass


class CapabilityTokenInvalid(CapabilityTokenError):
    pass


class CapabilityTokenSecretMissing(CapabilityTokenError):
    def __init__(self):
        super().__init__(
            "STRATEGYOS_AGENT_CAPABILITY_TOKEN_SECRET is not configured; "
            "consequential tool dispatch cannot be authorized without it."
        )


@dataclass(frozen=True)
class CapabilityClaims:
    tenant_id: str
    task_id: str
    attempt_no: int
    agent_installation_id: str
    allowed_tool_keys: tuple[str, ...]
    scope_reference_ids: tuple[str, ...]
    max_risk_class: str
    issued_at: int
    expires_at: int
    nonce: str


def _secret_bytes() -> bytes:
    secret = CONFIG.agent_capability_token_secret
    if not secret:
        raise CapabilityTokenSecretMissing()
    return secret.encode("utf-8")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def issue_capability_token(
    *,
    tenant_id: str,
    task_id: str,
    attempt_no: int,
    agent_installation_id: str,
    allowed_tool_keys: tuple[str, ...],
    scope_reference_ids: tuple[str, ...] = (),
    max_risk_class: str = "read_only",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    now = int(time.time())
    claims = {
        "tenant_id": tenant_id,
        "task_id": task_id,
        "attempt_no": attempt_no,
        "agent_installation_id": agent_installation_id,
        "allowed_tool_keys": list(allowed_tool_keys),
        "scope_reference_ids": list(scope_reference_ids),
        "max_risk_class": max_risk_class,
        "issued_at": now,
        "expires_at": now + max(1, int(ttl_seconds)),
        "nonce": uuid.uuid4().hex,
    }
    payload = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64encode(payload)
    signature = hmac.new(_secret_bytes(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    signature_b64 = _b64encode(signature)
    return f"{payload_b64}.{signature_b64}"


def verify_capability_token(token: str) -> CapabilityClaims:
    """Raises CapabilityTokenInvalid/CapabilityTokenExpired on any problem
    -- never returns a partially-trusted result. Signature comparison uses
    hmac.compare_digest to avoid a timing side channel."""
    try:
        payload_b64, signature_b64 = token.split(".", 1)
    except ValueError as exc:
        raise CapabilityTokenInvalid("malformed token") from exc

    expected_signature = hmac.new(_secret_bytes(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    try:
        provided_signature = _b64decode(signature_b64)
    except Exception as exc:
        raise CapabilityTokenInvalid("malformed signature") from exc

    if not hmac.compare_digest(expected_signature, provided_signature):
        raise CapabilityTokenInvalid("signature mismatch")

    try:
        claims_dict = json.loads(_b64decode(payload_b64))
    except Exception as exc:
        raise CapabilityTokenInvalid("malformed payload") from exc

    now = int(time.time())
    if now >= int(claims_dict.get("expires_at", 0)):
        raise CapabilityTokenExpired("token has expired")

    try:
        return CapabilityClaims(
            tenant_id=str(claims_dict["tenant_id"]),
            task_id=str(claims_dict["task_id"]),
            attempt_no=int(claims_dict["attempt_no"]),
            agent_installation_id=str(claims_dict["agent_installation_id"]),
            allowed_tool_keys=tuple(claims_dict["allowed_tool_keys"]),
            scope_reference_ids=tuple(claims_dict.get("scope_reference_ids", ())),
            max_risk_class=str(claims_dict["max_risk_class"]),
            issued_at=int(claims_dict["issued_at"]),
            expires_at=int(claims_dict["expires_at"]),
            nonce=str(claims_dict["nonce"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CapabilityTokenInvalid(f"missing or malformed claim: {exc}") from exc


# risk class ordering for max_risk_class enforcement -- a token scoped to
# read_only must not authorize a prepare/write/restricted tool call even
# if the tool key happens to be in allowed_tool_keys (defense in depth: two
# independent checks, not just an allowlist).
_RISK_CLASS_ORDER = {"read_only": 0, "prepare": 1, "write": 2, "restricted": 3}


def authorize_tool_call(claims: CapabilityClaims, *, tool_key: str, tool_risk_class: str) -> None:
    if tool_key not in claims.allowed_tool_keys:
        raise CapabilityTokenInvalid(f"tool key {tool_key!r} is not in this token's allowed_tool_keys")
    token_ceiling = _RISK_CLASS_ORDER.get(claims.max_risk_class, 0)
    call_risk = _RISK_CLASS_ORDER.get(tool_risk_class, 0)
    if call_risk > token_ceiling:
        raise CapabilityTokenInvalid(
            f"tool {tool_key!r} risk class {tool_risk_class!r} exceeds token's max_risk_class {claims.max_risk_class!r}"
        )
