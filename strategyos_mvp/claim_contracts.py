"""Deterministic numerical claim validation for provider-generated presentation fields."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Any, Iterable

REFERENCE = re.compile(r"\b(?:EV|SIG|INIT|KPI|RD|INV|PO|HD|CT)-[A-Za-z0-9-]+\b", re.I)
QUANTITY = re.compile(
    r"(?<![\w])(?:(SAR|USD|EUR|GBP|AED)\s*)?([-+]?\d[\d,]*(?:\.\d+)?)"
    r"\s*(billion|million|thousand|trillion|[KMB](?![a-z])|%|bps|basis points?|percentage points?|pts?|days?|weeks?|months?|years?|x\b)?",
    re.I,
)
SCALES = {"k": Decimal(1000), "thousand": Decimal(1000), "m": Decimal(1000000),
          "million": Decimal(1000000), "b": Decimal(1000000000), "billion": Decimal(1000000000),
          "trillion": Decimal(1000000000000)}


@dataclass(frozen=True)
class QuantityClaim:
    value: Decimal
    unit: str


def text_fields(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for item in value.values():
            yield from text_fields(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from text_fields(item)
    elif value is not None and not isinstance(value, bool):
        yield str(value)


def quantities(text: str) -> set[QuantityClaim]:
    claims = set()
    text = re.sub(r"(?m)^\s*\d+[.)]\s+", "", text)
    for currency, amount, suffix in QUANTITY.findall(REFERENCE.sub("", text)):
        number = Decimal(amount.replace(",", ""))
        suffix = suffix.casefold().strip()
        if suffix in SCALES:
            number *= SCALES[suffix]
            suffix = ""
        unit = currency.upper() or suffix
        if suffix in {"pt", "pts", "percentage point", "percentage points"}:
            unit = "percentage_points"
        elif suffix in {"bps", "basis point", "basis points"}:
            unit = "basis_points"
        claims.add(QuantityClaim(number, unit))
    return claims


def unsupported_quantities(candidate: Any, approved: Any) -> set[QuantityClaim]:
    allowed = set().union(*(quantities(text) for text in text_fields(approved)))
    requested = set().union(*(quantities(text) for text in text_fields(candidate)))
    return requested - allowed


def claims_supported(candidate: Any, approved: Any) -> bool:
    return not unsupported_quantities(candidate, approved)


def approved_evidence_text(value: Any) -> list[str]:
    """Extract evidence facts without treating client questions/history as evidence."""
    excluded = {"question", "prompt", "history", "conversation_history", "driver_context", "assistant_context"}
    result = []
    if isinstance(value, dict):
        currency = str(value.get("currency") or "").upper()
        for key, item in value.items():
            if str(key).casefold() in excluded:
                continue
            if isinstance(item, (int, float, Decimal)) and not isinstance(item, bool):
                unit = "SAR" if "sar" in str(key).lower() else currency
                if str(key).endswith(("_pct", "_percent")):
                    result.append(f"{item}%")
                elif unit:
                    result.append(f"{unit} {item}")
            result.extend(approved_evidence_text(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            result.extend(approved_evidence_text(item))
    elif value is not None and not isinstance(value, bool):
        result.append(str(value))
    return result
