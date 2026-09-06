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

EVIDENCE_COMPONENTS: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue_actual", "revenue_plan"),
    "ebitda_margin": ("ebitda_actual", "ebitda_plan", "cogs_actual"),
    "operating_cost": ("operating_cost_actual", "operating_cost_plan"),
    "cash_vs_floor": ("cash_balance", "board_floor"),
}


def _normalized_value(record: Mapping[str, Any]) -> str | None:
    value = record.get("value")
    if value is None:
        return None
    try:
        normalized = Decimal(str(value)) * Decimal(str(record.get("scale") or "1"))
    except (InvalidOperation, ValueError):
        return str(value)
    return format(normalized, "f")


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
    for raw_record in list(snapshot.get("records") or []):
        if not isinstance(raw_record, Mapping):
            continue
        record = dict(raw_record)
        dimensions = record.get("dimensions") if isinstance(record.get("dimensions"), Mapping) else {}
        component_key = str(dimensions.get("component_key") or "").strip()
        if component_key in COMPONENT_KEYS:
            normalized = _normalized_value(record)
            if normalized is not None:
                components[component_key] = normalized
                component_claims[component_key] = record
        elif component_key in {"ebitda_margin_actual", "ebitda_margin_plan"}:
            derived_claims[component_key] = record

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
