from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any

from .config import CONFIG, StrategyOSConfig


_FIELD_KIND_ALIASES = {
    "tax_id": "tax_id",
    "supplier_tax_id": "tax_id",
    "buyer_tax_id": "tax_id",
    "tax_registration_number": "tax_registration",
    "tax_registration": "tax_registration",
    "bank_account": "bank_account",
    "iban": "bank_account",
    "bank_account_number": "bank_account",
    "routing_number": "bank_routing",
    "swift": "bank_routing",
}


def normalize_sensitive_identifier(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def sensitive_identifier_kind(field_name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(field_name).strip().lower()).strip("_")
    return _FIELD_KIND_ALIASES.get(normalized, normalized or "identifier")


def tokenize_sensitive_identifier(
    value: Any,
    *,
    field_name: str = "identifier",
    config: StrategyOSConfig = CONFIG,
) -> str | None:
    normalized = normalize_sensitive_identifier(value)
    if normalized is None:
        return None
    key_id = config.sensitive_identifier_active_key_id
    secret = config.sensitive_identifier_hmac_keys.get(key_id)
    if secret is None:
        key_id, secret = next(iter(config.sensitive_identifier_hmac_keys.items()))
    payload = f"{config.tenant_slug}\0{sensitive_identifier_kind(field_name)}\0{normalized}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"hmac:{key_id}:{digest}"


def matches_sensitive_identifier_token(
    token: str | None,
    value: Any,
    *,
    field_name: str = "identifier",
    config: StrategyOSConfig = CONFIG,
) -> bool:
    if token in {None, ""}:
        return False
    return token == tokenize_sensitive_identifier(value, field_name=field_name, config=config)
