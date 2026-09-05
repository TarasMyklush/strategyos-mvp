"""Deterministic numerical claim validation for provider-generated presentation fields."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any, Iterable

REFERENCE = re.compile(r"\b(?:EV|SIG|INIT|KPI|RD|INV|PO|HD|CT)-[A-Za-z0-9-]+\b", re.I)
QUANTITY = re.compile(
    r"(?<![\w])(?:(SAR|USD|EUR|GBP|AED|CHF|JPY|CNY|INR|KWD|QAR|BHD|OMR|CAD|AUD|SGD|HKD)\s*)?([-+]?\d[\d,]*(?:\.\d+)?)"
    r"\s*(billion|million|thousand|trillion|[KMB](?![a-z])|%|bps|basis points?|percentage points?|pts?|days?|weeks?|months?|years?|x\b)?",
    re.I,
)
SCALES = {"k": Decimal(1000), "thousand": Decimal(1000), "m": Decimal(1000000),
          "million": Decimal(1000000), "b": Decimal(1000000000), "billion": Decimal(1000000000),
          "trillion": Decimal(1000000000000)}
TABLE_AMOUNT = re.compile(r"\((SAR|USD|EUR|GBP|AED|CHF|JPY|CNY|INR|KWD|QAR|BHD|OMR|CAD|AUD|SGD|HKD)\s*(K|M|B|million|thousand|billion)?\)\s*:\s*([-+]?\d[\d,]*(?:\.\d+)?)", re.I)
TABLE_DELTA = re.compile(r"(?:^|;)\s*Delta vs budget\s*:\s*([-+]?\d[\d,]*(?:\.\d+)?)(?=\s*(?:;|\n|$))", re.I)


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
    # Indexed workbook rows retain their column headings. A header such as
    # 'Budget (SAR M): 758' explicitly supplies both currency and scale.
    for currency, scale, amount in TABLE_AMOUNT.findall(text):
        claims.add(QuantityClaim(Decimal(amount.replace(',', '')) * SCALES.get(scale.lower(), 1), currency.upper()))
    return claims


def unsupported_quantities(candidate: Any, approved: Any) -> set[QuantityClaim]:
    allowed = set().union(*(quantities(text) for text in text_fields(approved)))
    missing = set()
    for text in text_fields(candidate):
        requested = quantities(text)
        rounded = set()
        for currency, amount, suffix in QUANTITY.findall(REFERENCE.sub('', text)):
            scale = SCALES.get(suffix.casefold().strip())
            if not currency or scale is None:
                continue
            decimal = Decimal(amount.replace(',', ''))
            value = decimal * scale
            quantum = Decimal(10) ** decimal.as_tuple().exponent * scale
            for fact in allowed:
                if fact.unit != currency.upper() or not fact.value:
                    continue
                # Only ordinary display rounding of a same-currency fact is
                # allowed, at the precision explicitly written by the model.
                expected = (fact.value / quantum).quantize(Decimal(1), rounding=ROUND_HALF_UP) * quantum
                if value == expected and abs(value - fact.value) / abs(fact.value) <= Decimal('.005'):
                    rounded.add(QuantityClaim(value, currency.upper()))
        missing.update(requested - allowed - rounded)
    return missing


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
        # The explicitly named delta column inherits a unit only when all
        # monetary headings in this same row agree. Never infer across rows.
        headers = {(currency.upper(), scale.lower()) for currency, scale, _ in TABLE_AMOUNT.findall(str(value))}
        if len(headers) == 1:
            currency, scale = next(iter(headers))
            for amount in TABLE_DELTA.findall(str(value)):
                result.append(f"{currency} {Decimal(amount.replace(',', '')) * SCALES.get(scale, 1)}")
    return result
