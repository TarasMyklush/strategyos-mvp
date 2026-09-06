"""Versioned deterministic calculation contracts at the ledger boundary.

Formula names are executable contracts, not arbitrary labels supplied by a model.
No implicit FX, period aggregation, ratio averaging or forecast promotion occurs.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from typing import Any

from .source_claims import ClaimDraft, ProductionMethod


PERCENT_QUANTUM = Decimal("0.000000000001")


def margin_percent(ebitda: Decimal, revenue: Decimal) -> Decimal:
    """Formula v1: percentage, rounded half-even to 12 decimal places.

    This explicitly defines representational precision, including validation of
    historical persisted ratios. It never rounds monetary input components.
    """
    with localcontext() as ctx:
        ctx.prec = 50
        return (ebitda / revenue * Decimal(100)).quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_EVEN)


def validate_persisted_calculation(cur: Any, draft: ClaimDraft) -> None:
    if draft.production_method != ProductionMethod.CALCULATED:
        return
    ids = tuple(draft.input_revision_ids)
    if len(set(ids)) != len(ids):
        raise ValueError("A calculation cannot count the same input revision twice.")
    cur.execute("""select r.id, r.tenant_id, r.claim_kind, r.value_numeric, r.unit,
        r.scale, r.currency, f.metric_key, f.subject_type, f.subject_key,
        f.business_unit, f.period_start, f.period_end, f.scenario_key
        from strategyos_claim_revisions r
        join strategyos_claim_families f on f.id = r.claim_family_id
        where r.id = any(%s::uuid[])""", (list(ids),))
    names = [item.name if hasattr(item, "name") else item[0] for item in cur.description]
    inputs = [dict(row) if isinstance(row, dict) else dict(zip(names, row)) for row in cur.fetchall()]
    validate_calculation(draft, inputs)


def validate_calculation(draft: ClaimDraft, inputs: list[dict[str, Any]]) -> None:
    if draft.production_method != ProductionMethod.CALCULATED:
        return
    ids = tuple(draft.input_revision_ids)
    if len(set(ids)) != len(ids) or set(map(str, ids)) != {str(row["id"]) for row in inputs}:
        raise ValueError("Every unique exact input revision is required.")
    if any(str(row["tenant_id"]) != draft.tenant_id for row in inputs):
        raise ValueError("Calculation inputs must belong to the same tenant.")
    if any(row["claim_kind"] != draft.claim_kind for row in inputs):
        if draft.claim_kind == "actual":
            raise ValueError("Calculated actuals cannot contain forecast, plan or unclassified inputs.")
        raise ValueError("A calculation cannot silently mix actual, plan, forecast or assumption lanes.")
    if draft.formula_version != "1" or draft.formula_key not in {
        "identity", "sum", "ebitda-divided-by-revenue",
    }:
        raise ValueError("An executable, supported formula version is required.")

    def scope(row: dict[str, Any]) -> tuple:
        return (row["subject_type"], row["subject_key"], row.get("business_unit"),
                row.get("period_start"), row.get("period_end"), row.get("scenario_key"))
    target = (draft.subject_type, draft.subject_key, draft.business_unit,
              draft.period_start, draft.period_end, draft.scenario_key)
    if any(scope(row) != target for row in inputs):
        raise ValueError("Calculation scopes and periods must align; an explicit aggregation is required.")
    if draft.formula_key != "identity" and (draft.period_start is None or draft.period_end is None):
        raise ValueError("Calculation periods must be explicit.")

    def number(row: dict[str, Any]) -> Decimal:
        try:
            value, scale = Decimal(str(row["value_numeric"])), Decimal(str(row["scale"]))
            if not value.is_finite() or not scale.is_finite() or scale <= 0:
                raise ValueError("Invalid numeric input")
            return value * scale
        except (ValueError, InvalidOperation):
            raise ValueError("Calculations require finite numerical inputs and explicit positive scales.") from None

    if draft.formula_key == "ebitda-divided-by-revenue":
        indexed = {row["metric_key"]: row for row in inputs}
        if len(inputs) != 2 or set(indexed) != {"ceo.ebitda", "ceo.revenue"}:
            raise ValueError("Margin requires exactly EBITDA and revenue, identified by metric rather than order.")
        if draft.unit != "percent" or draft.currency is not None:
            raise ValueError("Margin is a percent ratio, not currency or percentage-point change.")
        currencies = {row["currency"] for row in inputs}
        if len(currencies) != 1 or None in currencies or any(row["unit"] != row["currency"] for row in inputs):
            raise ValueError("Margin inputs require the same explicit currency; implicit FX is forbidden.")
        revenue = number(indexed["ceo.revenue"])
        if revenue == 0:
            raise ValueError("Margin is unavailable when revenue is zero.")
        expected = margin_percent(number(indexed["ceo.ebitda"]), revenue)
    else:
        if any(row["unit"] != draft.unit or row["currency"] != draft.currency for row in inputs):
            raise ValueError("Input and output units must agree; implicit conversion is forbidden.")
        if draft.formula_key == "identity":
            if len(inputs) != 1:
                raise ValueError("Identity requires exactly one input.")
            expected = number(inputs[0])
        else:
            if not draft.currency or draft.unit != draft.currency:
                raise ValueError("Generic sums accept monetary amounts, not ratios or point changes.")
            # Two providers' copies of the same metric are alternatives, not
            # additive amounts. Distinct metric contributions must be explicit.
            if len({row["metric_key"] for row in inputs}) != len(inputs):
                raise ValueError("Repeated metric candidates cannot be summed as independent contributions.")
            expected = sum((number(row) for row in inputs), Decimal(0))
    actual = draft.value_numeric * draft.scale if draft.value_numeric is not None else None
    if actual is not None and draft.formula_key == "ebitda-divided-by-revenue":
        actual = actual.quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_EVEN)
    if actual != expected:
        raise ValueError("Calculated value does not match its exact inputs and versioned formula.")
