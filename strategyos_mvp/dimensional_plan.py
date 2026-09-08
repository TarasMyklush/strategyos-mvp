"""Read-only dimensional plan import and deterministic evaluation.

This operator tool validates declared provenance, not business authorization.
It never selects/publishes a run, ratifies a plan, or calls a model/provider.
"""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from .strategy_compiler import SourceReference

Name = Annotated[str, Field(min_length=1, max_length=160, pattern=r".*\S.*")]
def exact_number(value):
    if isinstance(value, (bool, float)):
        raise ValueError("Use decimal strings or integers, never floating-point amounts.")
    return value


Amount = Annotated[Decimal, BeforeValidator(exact_number), Field(max_digits=28, decimal_places=12, allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Period(Contract):
    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("Period end precedes start.")
        return self


class Metric(Contract):
    unit: Name
    aggregation: Literal["sum"]
    direction: Literal["higher_is_better", "lower_is_better"]
    planned_total: Amount
    tolerance: Amount = Field(ge=0)


class Cell(Contract):
    id: Name
    metric: Name
    dimensions: dict[Name, Name] = Field(min_length=1)
    owner: Name
    target: Amount
    tolerance: Amount = Field(ge=0)
    source: SourceReference


class DecompositionAllocation(Contract):
    cell_id: Name
    member: Name
    weight: Amount = Field(gt=0)
    owner: Name
    tolerance: Amount = Field(ge=0)
    basis: SourceReference
    target_source: SourceReference | None = None
    historical_value: Amount | None = None
    adjustment_percent: Amount | None = None
    effective_weight: Amount | None = None


class PlanDerivation(Contract):
    kind: Literal["decomposition"]
    engine_version: Literal["weighted-allocation.v1", "history-adjusted-allocation.v1"]
    parent_plan_id: Name
    parent_version: int = Field(ge=1, strict=True)
    parent_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    parent_cell_id: Name
    split_dimension: Name
    decimal_places: int = Field(ge=0, le=12, strict=True)
    remainder_rule: Literal["final_lexicographic_cell"]
    allocations: list[DecompositionAllocation] = Field(min_length=2, max_length=500)
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    historical_actual_revision: Name | None = None
    historical_actual_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    historical_source_pack_id: Name | None = None


class StructureBinding(Contract):
    config_id: Name
    version: int = Field(ge=1, strict=True)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class Plan(Contract):
    schema_version: Literal[1]
    plan_id: Name
    company_id: Name
    version: int = Field(ge=1, strict=True)
    period: Period
    effective_from: date
    effective_to: date
    status: Literal["proposed", "ratified"]
    ratified_by: Name | None = None
    ratified_on: date | None = None
    ratification: SourceReference | None = None
    business_unit: Name | None = None
    structure: StructureBinding | None = None
    dimensions: dict[Name, list[Name]] = Field(min_length=1)
    metrics: dict[Name, Metric] = Field(min_length=1)
    cells: list[Cell] = Field(min_length=1, max_length=100000)
    derivation: PlanDerivation | None = None

    @model_validator(mode="after")
    def validate_plan(self):
        if (self.business_unit is None) != (self.structure is None):
            raise ValueError("Business-unit scope and organization-structure binding must be supplied together.")
        if self.effective_to < self.effective_from:
            raise ValueError("Effective dates are reversed.")
        if not (self.effective_from <= self.period.start <= self.period.end <= self.effective_to):
            raise ValueError("Plan period must fit within effective dates.")
        if self.status == "ratified" and not all((self.ratified_by, self.ratified_on, self.ratification)):
            raise ValueError("Ratified imports require identity, date and source evidence.")
        for members in self.dimensions.values():
            if not members or len(members) != len(set(members)):
                raise ValueError("Dimension members must be nonempty and unique.")
        ids, keys = set(), set()
        totals = {metric: Decimal(0) for metric in self.metrics}
        with localcontext() as ctx:
            ctx.prec = 80
            for cell in self.cells:
                validate_dimensions(self, cell.metric, cell.dimensions)
                key = cell_key(cell.metric, cell.dimensions)
                if cell.id in ids or key in keys:
                    raise ValueError("Duplicate cell ID or dimensional tuple.")
                ids.add(cell.id)
                keys.add(key)
                totals[cell.metric] += cell.target
            for metric, definition in self.metrics.items():
                if not any(c.metric == metric for c in self.cells):
                    raise ValueError("Every metric requires plan cells.")
                if totals[metric] != definition.planned_total:
                    raise ValueError(f"{metric}: cell targets do not reconcile to planned_total.")
        if self.derivation:
            if self.derivation.parent_plan_id != self.plan_id or self.derivation.parent_version >= self.version:
                raise ValueError("Decomposition lineage must reference an earlier version of this plan.")
            basis = self.derivation.model_dump(mode="json", exclude={"request_hash"}, exclude_none=True)
            if fingerprint(basis) != self.derivation.request_hash:
                raise ValueError("Decomposition lineage hash mismatch.")
            history = self.derivation.engine_version == "history-adjusted-allocation.v1"
            if history != all((self.derivation.historical_actual_revision,
                               self.derivation.historical_actual_digest,
                               self.derivation.historical_source_pack_id)):
                raise ValueError("Historical decomposition requires a complete actual-snapshot binding.")
            derived = {item.cell_id for item in self.derivation.allocations}
            cells = {cell.id: cell for cell in self.cells}
            if not derived.issubset(cells):
                raise ValueError("Decomposition lineage references missing result cells.")
            for item in self.derivation.allocations:
                cell = cells[item.cell_id]
                if (cell.dimensions.get(self.derivation.split_dimension) != item.member or
                        cell.owner != item.owner or cell.tolerance != item.tolerance or
                        cell.source != (item.target_source or item.basis)):
                    raise ValueError("Decomposition lineage differs from its result cells.")
                if history and not all(value is not None for value in
                                       (item.historical_value, item.adjustment_percent, item.effective_weight)):
                    raise ValueError("Historical allocation lineage is incomplete.")
        return self


class Observation(Contract):
    metric: Name
    dimensions: dict[Name, Name] = Field(min_length=1)
    unit: Name
    value: Amount | None
    source: SourceReference


class Actuals(Contract):
    schema_version: Literal[1]
    company_id: Name
    period: Period
    kind: Literal["actual"]
    revision: Name
    recorded_on: date
    observations: list[Observation] = Field(max_length=100000)


def cell_key(metric, dimensions):
    return metric, tuple(sorted(dimensions.items()))


def validate_dimensions(plan, metric, dimensions):
    if metric not in plan.metrics:
        raise ValueError("Unknown metric.")
    if set(dimensions) != set(plan.dimensions):
        raise ValueError("Every cell must supply the exact configured dimensions.")
    if any(member not in plan.dimensions[name] for name, member in dimensions.items()):
        raise ValueError("Unknown dimension member.")


def verify_source(root: Path, source: SourceReference):
    path = (root / source.path).resolve()
    if Path(source.path).is_absolute() or not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Evidence must resolve to a file inside the source root.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != source.sha256:
        raise ValueError("Evidence hash differs from the declared source.")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def classify(delta, direction, tolerance):
    favorable = delta if direction == "higher_is_better" else -delta
    return "behind" if favorable < -tolerance else "ahead" if favorable > tolerance else "on_plan"


def evaluate(plan: Plan, actuals: Actuals, *, source_root: Path, company_id: str, as_of: date, actual_source_root: Path | None = None) -> dict:
    """Evaluate one explicitly selected snapshot; no implicit latest-version choice.

    Amounts serialize as decimal strings. Null observations stay missing. Extra
    actual cells are disclosed and block complete rollups, never silently dropped.
    """
    if company_id != plan.company_id or company_id != actuals.company_id:
        raise ValueError("Company scope mismatch.")
    if actuals.period != plan.period:
        raise ValueError("Actual and plan periods must match exactly.")
    if as_of < plan.period.end:
        raise ValueError("A full-period comparison requires as_of at or after period end.")
    if actuals.recorded_on > as_of:
        raise ValueError("Actual snapshot was recorded after as_of.")
    if actuals.recorded_on < actuals.period.end:
        raise ValueError("Actual snapshot predates the completed period.")
    if plan.ratified_on and plan.ratified_on > as_of:
        raise ValueError("Ratification is later than the evaluation date.")
    root = source_root.resolve(strict=True)
    actual_root = actual_source_root.resolve(strict=True) if actual_source_root is not None else root
    checked_sources = set()
    def check(source, evidence_root=root):
        key = (str(evidence_root), source.path, source.sha256)
        if key not in checked_sources:
            verify_source(evidence_root, source)
            checked_sources.add(key)
    if plan.ratification:
        check(plan.ratification)
    observed = {}
    for observation in actuals.observations:
        validate_dimensions(plan, observation.metric, observation.dimensions)
        if observation.unit != plan.metrics[observation.metric].unit:
            raise ValueError("Actual unit must match the plan metric; implicit conversion is forbidden.")
        key = cell_key(observation.metric, observation.dimensions)
        if key in observed:
            raise ValueError("Duplicate actual tuple; reconcile detail before import.")
        check(observation.source, actual_root)
        observed[key] = observation
    rows = []
    with localcontext() as ctx:
        ctx.prec = 80
        for cell in sorted(plan.cells, key=lambda c: c.id):
            check(cell.source)
            obs = observed.pop(cell_key(cell.metric, cell.dimensions), None)
            value = obs.value if obs else None
            delta = value - cell.target if value is not None else None
            definition = plan.metrics[cell.metric]
            rows.append({"cell_id": cell.id, "metric": cell.metric, "dimensions": cell.dimensions,
                "owner": cell.owner, "unit": definition.unit, "target": str(cell.target),
                "actual": str(value) if value is not None else None,
                "variance": str(delta) if delta is not None else None,
                "variance_percent": str(delta / abs(cell.target) * 100) if delta is not None and cell.target else None,
                "status": classify(delta, definition.direction, cell.tolerance) if delta is not None else "missing",
                "plan_source": cell.source.model_dump(mode="json"),
                "actual_source": obs.source.model_dump(mode="json") if obs else None})
        rollups = []
        for name, metric in sorted(plan.metrics.items()):
            selected = [row for row in rows if row["metric"] == name]
            missing = [row["cell_id"] for row in selected if row["actual"] is None]
            unplanned = [obs.model_dump(mode="json") for key, obs in sorted(observed.items()) if key[0] == name]
            complete = not missing and not unplanned
            total = sum((Decimal(row["actual"]) for row in selected if row["actual"] is not None), Decimal(0))
            delta = total - metric.planned_total
            status = classify(delta, metric.direction, metric.tolerance) if complete else "incomplete"
            behind = [row["cell_id"] for row in selected if row["status"] == "behind"]
            ahead = [row["cell_id"] for row in selected if row["status"] == "ahead"]
            rollups.append({"metric": name, "unit": metric.unit, "target": str(metric.planned_total),
                "actual": str(total) if complete else None, "variance": str(delta) if complete else None,
                "status": status, "missing_cells": missing, "unplanned_actuals": unplanned,
                "measured_cells": len(selected) - len(missing), "planned_cells": len(selected),
                "offset_detected": complete and status in {"on_plan", "ahead"} and bool(behind) and bool(ahead),
                "behind_cells": behind, "ahead_cells": ahead})
    plan_payload = plan.model_dump(mode="json")
    plan_payload["cells"] = sorted(plan_payload["cells"], key=lambda c: c["id"])
    for members in plan_payload["dimensions"].values():
        members.sort()
    actual_payload = actuals.model_dump(mode="json")
    actual_payload["observations"] = sorted(actual_payload["observations"], key=lambda o: cell_key(o["metric"], o["dimensions"]))
    result = {"schema_version": 1, "formula_version": "cell-variance.v1", "company_id": company_id,
        "plan_id": plan.plan_id, "plan_version": plan.version, "period": plan.period.model_dump(mode="json"),
        "as_of": as_of.isoformat(), "plan_hash": fingerprint(plan_payload), "actuals_hash": fingerprint(actual_payload),
        "approval_status": plan.status, "approval_basis": "imported_metadata_not_authorization_verified",
        "comparison_basis": "imported_ratified_plan" if plan.status == "ratified" else "proposed_plan_preview",
        "cells": rows, "rollups": rollups}
    result["analysis_hash"] = fingerprint(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--actuals", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    try:
        plan = Plan.model_validate_json(args.plan.read_text())
        actuals = Actuals.model_validate_json(args.actuals.read_text())
        result = evaluate(plan, actuals, source_root=args.source_root, company_id=args.company_id, as_of=args.as_of)
    except (ValueError, OSError):
        parser.exit(2, "Invalid dimensional import: check schema, scope, period, reconciliation and source hashes.\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
