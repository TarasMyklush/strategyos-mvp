from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


COMPONENT_KEYS = frozenset(
    {
        "revenue_actual",
        "revenue_plan",
        "cogs_actual",
        "ebitda_actual",
        "ebitda_plan",
        "operating_cost_actual",
        "operating_cost_plan",
        "cash_balance",
        "board_floor",
    }
)

FINANCE_HEADLINE_METRIC_KEYS = frozenset(
    {
        "ceo.revenue",
        "ceo.cogs",
        "ceo.ebitda",
        "ceo.ebitda_margin",
        "ceo.operating_cost",
        "ceo.cash_balance",
        "ceo.cash_floor",
    }
)

EVIDENCE_COMPONENTS: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue_actual", "revenue_plan"),
    "ebitda_margin": ("ebitda_actual", "ebitda_plan", "cogs_actual"),
    "operating_cost": ("operating_cost_actual", "operating_cost_plan"),
    "cash_vs_floor": ("cash_balance", "board_floor"),
}


COMPONENT_CONTRACTS = {
    "revenue_actual": ("ceo.revenue", "actual"),
    "revenue_plan": ("ceo.revenue", "plan"),
    "cogs_actual": ("ceo.cogs", "actual"),
    "ebitda_actual": ("ceo.ebitda", "actual"),
    "ebitda_plan": ("ceo.ebitda", "plan"),
    "operating_cost_actual": ("ceo.operating_cost", "actual"),
    "operating_cost_plan": ("ceo.operating_cost", "plan"),
    "cash_balance": ("ceo.cash_balance", "actual"),
    "board_floor": ("ceo.cash_floor", "plan"),
    "ebitda_margin_actual": ("ceo.ebitda_margin", "actual"),
    "ebitda_margin_plan": ("ceo.ebitda_margin", "plan"),
}


def _normalized_value(record: Mapping[str, Any]) -> str:
    try:
        value = Decimal(str(record.get("value")))
        scale = Decimal(str(record.get("scale")))
        if not value.is_finite() or not scale.is_finite() or scale <= 0:
            raise ValueError("Non-finite value or invalid scale")
        normalized = value * scale
    except (InvalidOperation, ValueError):
        raise ValueError("A financial display claim needs a finite number and positive explicit scale.") from None
    return format(normalized, "f")


def _validate_component(record: Mapping[str, Any], key: str, currency: str) -> None:
    metric, kind = COMPONENT_CONTRACTS[key]
    if record.get("metric_key") != metric or record.get("claim_kind") != kind:
        raise ValueError("Financial claim metric or kind does not match its display component.")
    expected_unit = "percent" if key.startswith("ebitda_margin_") else currency
    if record.get("unit") != expected_unit:
        raise ValueError("Financial claim unit does not match its display component.")
    if expected_unit != "percent" and record.get("currency") != currency:
        raise ValueError("Financial claim currency does not match the reporting currency.")
    if record.get("business_unit") or record.get("scenario") or record.get("scenario_key"):
        raise ValueError("A scoped business-unit or scenario claim cannot become a group headline.")
    _normalized_value(record)


def finance_payload_from_claim_snapshot(
    legacy_payload: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any],
    *,
    reconciliation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Overlay a legacy display projection with authorized immutable claims.

    Trends, movers and explanatory source notes remain presentation material.
    Every headline component is removed and repopulated from the snapshot so a
    denied or absent claim cannot leak through the older run summary.
    """
    payload = dict(legacy_payload or {})
    components = dict(payload.get("components") or {})
    for key in COMPONENT_KEYS:
        components.pop(key, None)

    component_claims: dict[str, dict[str, Any]] = {}
    derived_claims: dict[str, dict[str, Any]] = {}
    currency = str(payload.get("reporting_currency") or "SAR")
    if currency != "SAR":
        raise ValueError("This finance presentation supports SAR only; inspect other currencies in the claim workspace.")
    seen_components: set[str] = set()
    for raw_record in list(snapshot.get("records") or []):
        if not isinstance(raw_record, Mapping):
            continue
        record = dict(raw_record)
        dimensions = record.get("dimensions") if isinstance(record.get("dimensions"), Mapping) else {}
        component_key = str(dimensions.get("component_key") or "").strip()
        if component_key in COMPONENT_CONTRACTS:
            _validate_component(record, component_key, currency)
            if component_key in seen_components:
                raise ValueError("Multiple claims compete for a financial headline; explicit resolution is required.")
            seen_components.add(component_key)
        if component_key in COMPONENT_KEYS:
            normalized = _normalized_value(record)
            if normalized is not None:
                components[component_key] = normalized
                component_claims[component_key] = record
        elif component_key in {"ebitda_margin_actual", "ebitda_margin_plan"}:
            derived_claims[component_key] = record

    # Never compare different reporting periods merely because component names
    # look compatible. Absence remains explicit; no dates are inferred here.
    for actual_key, plan_key in (("revenue_actual", "revenue_plan"),
                                 ("ebitda_actual", "ebitda_plan"),
                                 ("operating_cost_actual", "operating_cost_plan")):
        actual, plan = component_claims.get(actual_key), component_claims.get(plan_key)
        if actual and plan:
            def period(record: Mapping[str, Any]) -> tuple[Any, Any]:
                nested = record.get("period") or {}
                return (nested.get("start", record.get("period_start")),
                        nested.get("end", record.get("period_end")))
            if None in period(actual) or None in period(plan) or period(actual) != period(plan):
                raise ValueError("Actual and plan claim periods do not align.")

    evidence = {
        str(key): dict(value) if isinstance(value, Mapping) else {}
        for key, value in dict(payload.get("evidence") or {}).items()
    }
    for evidence_key, keys in EVIDENCE_COMPONENTS.items():
        item = evidence.setdefault(evidence_key, {})
        linked = [component_claims[key] for key in keys if key in component_claims]
        item["claim_revisions"] = [record["claim_revision_id"] for record in linked]
        item["claim_labels"] = [record["label"] for record in linked]
        item["governed_sources"] = [
            source
            for record in linked
            for source in list(record.get("sources") or [])
            if isinstance(source, Mapping)
        ]

    result = {
        **payload,
        "authoritative": bool(component_claims),
        "derived_from": "governed_claim_snapshot",
        "components": components,
        "component_claims": component_claims,
        "derived_claims": derived_claims,
        "evidence": evidence,
        "claim_snapshot": {
            "snapshot_id": snapshot.get("snapshot_id"),
            "snapshot_key": snapshot.get("snapshot_key"),
            "analysis_as_of": snapshot.get("analysis_as_of"),
            "policy_version": snapshot.get("policy_version"),
            "denied_count": int(snapshot.get("denied_count") or 0),
        },
        "canonical_claim_status": "ready" if component_claims else "no_headline_claims",
    }
    if reconciliation:
        result["claim_reconciliation"] = dict(reconciliation)
    return result
