from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


PLAN_STATUSES = {"draft", "submitted", "finance_reviewed", "active", "changes_requested", "superseded"}
REQUIRED_TARGETS = {"revenue", "ebitda_margin", "operating_cost", "cash_floor"}
TARGET_UNITS = {
    "revenue": "SAR",
    "ebitda_margin": "percent",
    "operating_cost": "SAR",
    "cash_floor": "SAR",
}


def validate_plan_payload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Normalize a financial plan and return explicit validation exceptions.

    Validation is intentionally independent of persistence so ingestion, APIs and
    tests use the same contract. A plan with exceptions may be saved as a draft,
    but it cannot be submitted or activated.
    """
    normalized: dict[str, Any] = {
        "plan_key": str(payload.get("plan_key") or "group-financial-plan").strip(),
        "title": str(payload.get("title") or "Group financial plan").strip(),
        "reporting_period_key": str(payload.get("reporting_period_key") or "").strip(),
        "period_start": _date_text(payload.get("period_start")),
        "period_end": _date_text(payload.get("period_end")),
        "currency": str(payload.get("currency") or "SAR").strip().upper(),
        "scope": dict(payload.get("scope") or {}) if isinstance(payload.get("scope"), Mapping) else {},
        "source": dict(payload.get("source") or {}) if isinstance(payload.get("source"), Mapping) else {},
        "targets": {},
    }
    exceptions: list[dict[str, str]] = []
    if not normalized["reporting_period_key"]:
        exceptions.append(_exception("reporting_period_key", "Reporting period is required."))
    if not normalized["period_start"] or not normalized["period_end"]:
        exceptions.append(_exception("period", "A complete plan period is required."))
    elif normalized["period_start"] > normalized["period_end"]:
        exceptions.append(_exception("period", "Plan start date must be on or before its end date."))
    if not normalized["scope"].get("entities"):
        exceptions.append(_exception("scope.entities", "At least one governed entity is required."))
    source = normalized["source"]
    if not str(source.get("name") or "").strip() or not str(source.get("reference") or "").strip():
        exceptions.append(_exception("source", "The approved-plan source name and reference are required."))

    raw_targets = payload.get("targets")
    target_items = raw_targets.items() if isinstance(raw_targets, Mapping) else []
    for key, raw in target_items:
        target_key = str(key).strip().lower()
        if target_key not in REQUIRED_TARGETS:
            continue
        item = raw if isinstance(raw, Mapping) else {"value": raw}
        value = _decimal(item.get("value"))
        unit = str(item.get("unit") or TARGET_UNITS[target_key]).strip()
        if value is None or value < 0:
            exceptions.append(_exception(f"targets.{target_key}", f"{target_key.replace('_', ' ').title()} must be a non-negative number."))
            continue
        if unit != TARGET_UNITS[target_key]:
            exceptions.append(_exception(f"targets.{target_key}.unit", f"{target_key.replace('_', ' ').title()} must use {TARGET_UNITS[target_key]}."))
            continue
        if target_key == "ebitda_margin" and value > 100:
            exceptions.append(_exception("targets.ebitda_margin", "EBITDA margin cannot exceed 100%."))
            continue
        normalized["targets"][target_key] = {
            "value": str(value),
            "unit": unit,
            "note": str(item.get("note") or "").strip(),
        }
    for target_key in sorted(REQUIRED_TARGETS - set(normalized["targets"])):
        exceptions.append(_exception(f"targets.{target_key}", f"{target_key.replace('_', ' ').title()} is required."))
    return normalized, exceptions


def plan_comparators(plan: Mapping[str, Any], finance_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return plan values only when period, currency and governed scope align."""
    if str(plan.get("status") or "") != "active":
        return {"aligned": False, "reason": "The plan is not active."}
    finance_period = str(finance_payload.get("reporting_period_key") or "").strip().casefold()
    plan_period = str(plan.get("reporting_period_key") or "").strip().casefold()
    if not finance_period or finance_period != plan_period:
        return {"aligned": False, "reason": "The active plan is not aligned to the current reporting period."}
    finance_currency = str(finance_payload.get("reporting_currency") or "SAR").upper()
    if finance_currency != str(plan.get("currency") or "").upper():
        return {"aligned": False, "reason": "The active plan uses a different reporting currency."}
    finance_scope = finance_payload.get("reporting_scope") if isinstance(finance_payload.get("reporting_scope"), Mapping) else {}
    plan_scope = plan.get("scope") if isinstance(plan.get("scope"), Mapping) else {}
    finance_entities = {str(item).strip().casefold() for item in list(finance_scope.get("entities") or []) if str(item).strip()}
    plan_entities = {str(item).strip().casefold() for item in list(plan_scope.get("entities") or []) if str(item).strip()}
    if not finance_entities or finance_entities != plan_entities:
        return {"aligned": False, "reason": "The active plan is not aligned to the current governed entity scope."}
    targets = plan.get("targets") if isinstance(plan.get("targets"), Mapping) else {}
    values = {key: _float((targets.get(key) or {}).get("value")) for key in REQUIRED_TARGETS}
    if any(values[key] is None for key in REQUIRED_TARGETS):
        return {"aligned": False, "reason": "The active plan does not contain all four CEO targets."}
    return {
        "aligned": True,
        "plan_id": str(plan.get("id") or ""),
        "version": int(plan.get("version") or 0),
        "source": dict(plan.get("source") or {}),
        "components": {
            "revenue_plan": values["revenue"],
            "ebitda_plan": values["revenue"] * values["ebitda_margin"] / 100,
            "operating_cost_plan": values["operating_cost"],
            "board_floor": values["cash_floor"],
        },
    }


def _date_text(value: Any) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text).isoformat() if text else None
    except ValueError:
        return None


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    number = _decimal(value)
    return float(number) if number is not None else None


def _exception(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}
