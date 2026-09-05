"""Company-neutral strategy contract and deterministic compilation.

Unstructured extraction is a proposal, never a ratification. Formula binding
uses a closed vocabulary; source prose is never executable code.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Commitment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    driver: Literal["Growth", "Margin", "Capital", "Resilience", "Sustainability"]
    owner: str = Field(min_length=1)
    approver: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    cadence: Literal["daily", "weekly", "monthly", "quarterly", "annual"]
    direction: Literal["higher_is_better", "lower_is_better"]
    weight: float = Field(gt=0)
    tolerance: float = Field(ge=0)
    target: float
    formula: Literal["source_actual", "sum", "ratio", "variance"]
    bindings: list[str] = Field(min_length=1)
    source: SourceReference


class Amendment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    date: str
    approved_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    affected_commitments: list[str] = Field(min_length=1)
    source: SourceReference


class StrategyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str = Field(min_length=1)
    company_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    title: str
    status: Literal["proposed", "ratified"] = "proposed"
    ratified_by: str | None = None
    ratification: SourceReference | None = None
    commitments: list[Commitment] = Field(min_length=1, max_length=200)
    amendments: list[Amendment] = Field(default_factory=list)

    @model_validator(mode="after")
    def governance(self):
        ids = [item.id for item in self.commitments]
        if len(set(ids)) != len(ids):
            raise ValueError("Commitment IDs must be unique.")
        if self.status == "ratified" and (not self.ratified_by or not self.ratification):
            raise ValueError("Ratification requires an approval identity and source evidence.")
        for amendment in self.amendments:
            if not set(amendment.affected_commitments).issubset(ids):
                raise ValueError("Amendment refers to an unknown commitment.")
        return self


def compile_strategy(raw: dict[str, Any], *, available_bindings: set[str], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = StrategyPlan.model_validate(raw)
    missing = sorted({binding for item in plan.commitments for binding in item.bindings} - available_bindings)
    for item in plan.commitments:
        expected = 2 if item.formula in {"ratio", "variance"} else 1 if item.formula == "source_actual" else None
        if expected and len(item.bindings) != expected:
            raise ValueError(f"{item.id}: {item.formula} requires exactly {expected} bound fields.")
    payload = plan.model_dump(mode="json")
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    prior = {item["id"]: item for item in (previous or {}).get("commitments", [])}
    current = {item["id"]: item for item in payload["commitments"]}
    changed = sorted(key for key in prior.keys() | current.keys() if prior.get(key) != current.get(key))
    return {**payload, "compilation_hash": fingerprint,
            "readiness": "needs_input" if missing else "needs_ratification" if plan.status != "ratified" else "compiled",
            "missing_bindings": missing, "changed_commitments": changed,
            "recompile_required": bool(changed),
            "downstream_invalidations": [{"commitment_id": key, "surfaces": ["diagnostics", "briefing", "drift"]} for key in changed]}


def evaluate_strategy(compiled: dict[str, Any], measurements: dict[str, Any]) -> dict[str, Any]:
    """Evaluate only declared formulas; missing/invalid inputs never become zero.

    The result keeps the plan's approval state. Calculation is not ratification.
    Percent ratios multiply by 100; other ratios retain their declared scale.
    """
    from decimal import Decimal, InvalidOperation
    plan = StrategyPlan.model_validate({key: value for key, value in compiled.items() if key in StrategyPlan.model_fields})
    results = []
    for item in plan.commitments:
        missing = [key for key in item.bindings if key not in measurements or measurements[key] is None]
        reason = None
        actual = None
        try:
            values = []
            for key in item.bindings:
                raw = measurements.get(key)
                if raw is None:
                    continue
                if isinstance(raw, bool):
                    raise ValueError('Boolean values are not financial measurements.')
                number = Decimal(str(raw))
                if not number.is_finite():
                    raise ValueError('Measurements must be finite.')
                values.append(number)
            if missing:
                reason = 'Missing bound measurements: ' + ', '.join(missing)
            elif item.formula == 'source_actual':
                if len(values) != 1:
                    raise ValueError('source_actual requires exactly one field.')
                actual = values[0]
            elif item.formula == 'sum':
                actual = sum(values, Decimal(0))
            elif item.formula in {'ratio', 'variance'}:
                if len(values) != 2:
                    raise ValueError('This formula requires exactly two fields.')
                if item.formula == 'variance':
                    actual = values[0] - values[1]
                elif values[1] == 0:
                    reason = 'The denominator is zero; the ratio is undefined.'
                else:
                    actual = values[0] / values[1] * (100 if item.unit == '%' else 1)
        except (InvalidOperation, ValueError, TypeError) as exc:
            reason = 'Invalid bound measurement: ' + str(exc)
        results.append({'commitment_id': item.id, 'actual': float(actual) if actual is not None else None,
                        'unit': item.unit, 'target': item.target, 'formula': item.formula,
                        'bindings': list(item.bindings), 'source': item.source.model_dump(),
                        'measurement_status': 'calculated' if actual is not None else 'needs_input',
                        'missing_inputs': missing, 'reason': reason})
    return {'plan_id': plan.plan_id, 'company_id': plan.company_id, 'plan_version': plan.version,
            'approval_status': plan.status, 'compilation_hash': compiled.get('compilation_hash'),
            'measurements': results}
