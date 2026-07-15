from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping


PLAN_STATUSES = {"draft", "submitted", "finance_reviewed", "active", "changes_requested", "superseded"}
PLAN_TYPES = {"operating_budget", "strategic_reference"}
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
        "plan_type": str(payload.get("plan_type") or "operating_budget").strip(),
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
    if normalized["plan_type"] not in PLAN_TYPES:
        exceptions.append(_exception("plan_type", "Plan type must be operating budget or strategic reference."))
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
    if normalized["plan_type"] == "operating_budget":
        for target_key in sorted(REQUIRED_TARGETS - set(normalized["targets"])):
            exceptions.append(_exception(f"targets.{target_key}", f"{target_key.replace('_', ' ').title()} is required."))
    elif not normalized["targets"]:
        exceptions.append(_exception("targets", "A strategic reference must contain at least one governed target."))
    return normalized, exceptions


def plan_comparators(plan: Mapping[str, Any], finance_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return plan values only when period, currency and governed scope align."""
    if str(plan.get("status") or "") != "active":
        return {"aligned": False, "reason": "The plan is not active."}
    if str(plan.get("plan_type") or "operating_budget") != "operating_budget":
        return {"aligned": False, "reason": "The active plan is an annual strategic reference, not a like-for-like operating budget."}
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


def extract_approved_plan_candidates(source_pack: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract deterministic plan records only from explicitly approved sources.

    This is deliberately not an LLM extraction path. Activation requires approval
    language, a dated approval, governed scope, and at least one unambiguous target.
    Missing targets remain absent rather than being inferred.
    """
    source_pack_id = str(source_pack.get("source_pack_id") or "").strip()
    candidates: list[dict[str, Any]] = []
    for item in list(source_pack.get("manifest") or []):
        classification = item.get("classification") if isinstance(item.get("classification"), Mapping) else {}
        if classification.get("role") != "approved_strategy_plan":
            continue
        extraction = item.get("text_extraction") if isinstance(item.get("text_extraction"), Mapping) else {}
        page_text = "\n".join(
            str(page.get("extracted_text") or "")
            for page in list(extraction.get("pages") or [])
            if isinstance(page, Mapping)
        )
        text = (page_text or str(extraction.get("raw_text") or extraction.get("extracted_text") or ""))[:160000]
        approval = re.search(
            r"board[- ]approved\s+(?P<date>\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            text,
            re.I,
        )
        if not approval:
            continue
        approval_date = _written_date(approval.group("date"))
        if not approval_date:
            continue
        revenue = _fy2026_revenue_target(text)
        cash_floor = _cash_floor_target(text)
        targets: dict[str, Any] = {}
        if revenue is not None:
            targets["revenue"] = {
                "value": str(revenue),
                "unit": "SAR",
                "note": "Approved FY2026 Group revenue forecast; annual progress reference only.",
            }
        if cash_floor is not None:
            targets["cash_floor"] = {
                "value": str(cash_floor),
                "unit": "SAR",
                "note": "Board-approved Group cash floor.",
            }
        if not targets:
            continue
        relative_path = str(item.get("relative_path") or "")
        source_hash = str(item.get("sha256") or "")
        candidates.append(
            {
                "plan_type": "strategic_reference",
                "plan_key": "group-strategic-plan",
                "title": "Board-approved Group Strategy 2026–2028",
                "reporting_period_key": "FY 2026",
                "period_start": "2026-01-01",
                "period_end": "2026-12-31",
                "currency": "SAR",
                "scope": {"entities": ["Group"]},
                "source": {
                    "name": "Board-approved Group Strategy 2026–2028",
                    "reference": relative_path,
                    "source_pack_id": source_pack_id,
                    "sha256": source_hash,
                    "approval_authority": "Board of Directors",
                    "approval_date": approval_date,
                    "approval_evidence": approval.group(0),
                },
                "targets": targets,
            }
        )
    return candidates


def strategic_references(plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Expose active strategic targets as context, never as period variance."""
    if str(plan.get("status") or "") != "active" or str(plan.get("plan_type") or "") != "strategic_reference":
        return {}
    targets = plan.get("targets") if isinstance(plan.get("targets"), Mapping) else {}
    source = plan.get("source") if isinstance(plan.get("source"), Mapping) else {}
    source_label = str(source.get("name") or source.get("reference") or "")
    result: dict[str, dict[str, str]] = {}
    revenue = _float((targets.get("revenue") or {}).get("value"))
    if revenue is not None and source_label:
        result["revenue"] = {
            "label": "Approved FY2026 Group revenue plan",
            "value": _sar_compact(revenue),
            "numeric_value": revenue,
            "note": "Annual Group progress reference; not a like-for-like H1 variance.",
            "source": source_label,
        }
    cash = _float((targets.get("cash_floor") or {}).get("value"))
    if cash is not None and source_label:
        result["cash_vs_floor"] = {
            "label": "Board-approved Group cash floor",
            "value": _sar_compact(cash),
            "numeric_value": cash,
            "note": "Group floor reference; compare only with a complete Group cash position.",
            "source": source_label,
        }
    return result


def _written_date(value: str) -> str | None:
    for pattern in ("%d %B %Y", "%d %b %Y"):
        try:
            from datetime import datetime
            return datetime.strptime(value.strip(), pattern).date().isoformat()
        except ValueError:
            pass
    return None


def _money_target(text: str, anchor_pattern: str, value_pattern: str) -> Decimal | None:
    match = re.search(anchor_pattern + r"[\s\S]{0,160}?" + value_pattern, text, re.I)
    if not match:
        return None
    value = _decimal(match.group(1).replace(",", ""))
    if value is None:
        return None
    return value * (Decimal("1000000000") if match.group(2).upper() == "B" else Decimal("1000000"))


def _fy2026_revenue_target(text: str) -> Decimal | None:
    # PDF table extraction linearizes the four headings before their four values.
    # Match the table contract and select the value paired with 2026F revenue.
    table = re.search(
        r"GROUP REVENUE 2025A\s+GROUP EBITDA MARGIN\s+2025A\s+2026F REVENUE\s+2028 TARGET"
        r"\s+SAR\s*[\d,.]+\s*[MB]\s+[\d.]+%\s+SAR\s*([\d,.]+)\s*([MB])",
        text,
        re.I,
    )
    if table:
        value = _decimal(table.group(1).replace(",", ""))
        if value is not None:
            return value * (Decimal("1000000000") if table.group(2).upper() == "B" else Decimal("1000000"))
    return _money_target(text, r"2026F\s+REVENUE", r"SAR\s*([\d,.]+)\s*([MB])")


def _cash_floor_target(text: str) -> Decimal | None:
    direct = re.search(r"(?:SAR\s*)?([\d,.]+)\s*([MB])\s+floor", text, re.I)
    if not direct:
        return None
    value = _decimal(direct.group(1).replace(",", ""))
    if value is None:
        return None
    return value * (Decimal("1000000000") if direct.group(2).upper() == "B" else Decimal("1000000"))


def _sar_compact(value: float) -> str:
    if abs(value) >= 1_000_000_000:
        return f"SAR {value / 1_000_000_000:.2f}B"
    return f"SAR {value / 1_000_000:.1f}M"


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
