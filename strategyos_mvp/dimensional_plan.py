"""Read-only dimensional plan import and deterministic evaluation.

This operator tool validates declared provenance, not business authorization.
It never selects/publishes a run, ratifies a plan, or calls a model/provider.
"""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
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
    member: Name | None = None
    dimensions: dict[Name, Name] | None = None
    weight: Amount = Field(gt=0)
    owner: Name
    tolerance: Amount = Field(ge=0)
    basis: SourceReference
    target_source: SourceReference | None = None
    historical_value: Amount | None = None
    adjustment_percent: Amount | None = None
    effective_weight: Amount | None = None

    @model_validator(mode="after")
    def one_dimension_shape(self):
        if (self.member is None) == (self.dimensions is None):
            raise ValueError("Decomposition allocation requires either one member or a dimensional tuple.")
        return self


class PlanDerivation(Contract):
    kind: Literal["decomposition"]
    engine_version: Literal["weighted-allocation.v1", "history-adjusted-allocation.v1",
                            "weighted-multidimensional-allocation.v1"]
    parent_plan_id: Name
    parent_version: int = Field(ge=1, strict=True)
    parent_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    parent_cell_id: Name | None = None
    parent_metric: Name | None = None
    split_dimension: Name | None = None
    split_dimensions: list[Name] | None = None
    decimal_places: int = Field(ge=0, le=12, strict=True)
    remainder_rule: Literal["final_lexicographic_cell"]
    allocations: list[DecompositionAllocation] = Field(min_length=2, max_length=5000)
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    historical_actual_revision: Name | None = None
    historical_actual_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    historical_source_pack_id: Name | None = None

    @model_validator(mode="after")
    def derivation_shape(self):
        multi = self.engine_version == "weighted-multidimensional-allocation.v1"
        if multi:
            if (not self.parent_metric or not self.split_dimensions or len(self.split_dimensions) < 2 or
                    self.parent_cell_id is not None or self.split_dimension is not None):
                raise ValueError("Multidimensional decomposition requires a parent metric and at least two split dimensions.")
            if len(self.split_dimensions) != len(set(self.split_dimensions)):
                raise ValueError("Multidimensional split dimensions must be unique.")
            if any(item.dimensions is None for item in self.allocations):
                raise ValueError("Multidimensional decomposition requires a dimensional tuple for every allocation.")
        elif (not self.parent_cell_id or not self.split_dimension or self.parent_metric is not None or
              self.split_dimensions is not None or any(item.member is None for item in self.allocations)):
            raise ValueError("Single-dimension decomposition requires one parent cell and split member per allocation.")
        return self


class StructureBinding(Contract):
    config_id: Name
    version: int = Field(ge=1, strict=True)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ConcentrationPolicy(Contract):
    policy_id: Name
    metric: Name
    dimension: Name
    threshold_percent: Amount = Field(gt=0, lt=100)


class PriceVolumePlanRow(Contract):
    member: Name
    cell_id: Name
    planned_price: Amount = Field(ge=0)
    planned_volume: Amount = Field(gt=0)
    price_source: SourceReference
    volume_source: SourceReference


class PriceVolumeMixPolicy(Contract):
    bridge_id: Name
    metric: Name
    mix_dimension: Name
    currency_unit: Name
    price_unit: Name
    volume_unit: Name
    decimal_places: int = Field(default=2, ge=0, le=12, strict=True)
    rows: list[PriceVolumePlanRow] = Field(min_length=2, max_length=5000)


class PriceVolumeActualRow(Contract):
    member: Name
    actual_price: Amount = Field(ge=0)
    actual_volume: Amount = Field(ge=0)
    price_source: SourceReference
    volume_source: SourceReference


class PriceVolumeMixActual(Contract):
    bridge_id: Name
    currency_unit: Name
    price_unit: Name
    volume_unit: Name
    rows: list[PriceVolumeActualRow] = Field(min_length=2, max_length=5000)


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
    concentration_policies: list[ConcentrationPolicy] = Field(default_factory=list, max_length=50)
    price_volume_mix_policies: list[PriceVolumeMixPolicy] = Field(default_factory=list, max_length=100)
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
        policies = [(policy.metric, policy.dimension) for policy in self.concentration_policies]
        if len(policies) != len(set(policies)):
            raise ValueError("Concentration policies must be unique by metric and dimension.")
        for policy in self.concentration_policies:
            if policy.metric not in self.metrics or policy.dimension not in self.dimensions:
                raise ValueError("Concentration policy references an unknown metric or dimension.")
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
        bridge_ids = [policy.bridge_id for policy in self.price_volume_mix_policies]
        if len(bridge_ids) != len(set(bridge_ids)):
            raise ValueError("Price/volume/mix bridge IDs must be unique.")
        cell_by_id = {cell.id: cell for cell in self.cells}
        bridge_cells = set()
        for policy in self.price_volume_mix_policies:
            if policy.metric not in self.metrics or policy.mix_dimension not in self.dimensions:
                raise ValueError("Price/volume/mix policy references an unknown metric or dimension.")
            if policy.currency_unit != self.metrics[policy.metric].unit:
                raise ValueError("Price/volume/mix currency unit must match its metric unit.")
            members = [row.member for row in policy.rows]
            cells = [row.cell_id for row in policy.rows]
            if len(members) != len(set(members)) or len(cells) != len(set(cells)):
                raise ValueError("Price/volume/mix rows require unique members and cells.")
            if bridge_cells.intersection(cells):
                raise ValueError("A plan cell can belong to only one price/volume/mix bridge.")
            bridge_cells.update(cells)
            scopes = set()
            for row in policy.rows:
                cell = cell_by_id.get(row.cell_id)
                if (cell is None or cell.metric != policy.metric or
                        cell.dimensions.get(policy.mix_dimension) != row.member):
                    raise ValueError("Price/volume/mix row must match its metric, cell and mix member.")
                if row.member not in self.dimensions[policy.mix_dimension]:
                    raise ValueError("Price/volume/mix row references an unknown mix member.")
                if cell.target != row.planned_price * row.planned_volume:
                    raise ValueError("Plan cell target must equal its disclosed price multiplied by volume.")
                scopes.add(tuple(sorted((key, value) for key, value in cell.dimensions.items()
                                        if key != policy.mix_dimension)))
            if len(scopes) != 1:
                raise ValueError("Price/volume/mix rows must share one comparable dimensional scope.")
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
                expected_dimensions = item.dimensions if item.dimensions is not None else {
                    **cell.dimensions, self.derivation.split_dimension: item.member}
                if (cell.dimensions != expected_dimensions or cell.owner != item.owner or
                        cell.tolerance != item.tolerance or cell.source != (item.target_source or item.basis)):
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
    price_volume_mix: list[PriceVolumeMixActual] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_price_volume_mix(self):
        ids = [item.bridge_id for item in self.price_volume_mix]
        if len(ids) != len(set(ids)):
            raise ValueError("Actual price/volume/mix bridge IDs must be unique.")
        for bridge in self.price_volume_mix:
            members = [row.member for row in bridge.rows]
            if len(members) != len(set(members)):
                raise ValueError("Actual price/volume/mix members must be unique.")
        return self


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


def plan_source_references(plan: Plan) -> list[SourceReference]:
    references = [cell.source for cell in plan.cells]
    for bridge in plan.price_volume_mix_policies:
        for row in bridge.rows:
            references.extend((row.price_source, row.volume_source))
    return references


def actual_source_references(actuals: Actuals) -> list[SourceReference]:
    references = [observation.source for observation in actuals.observations]
    for bridge in actuals.price_volume_mix:
        for row in bridge.rows:
            references.extend((row.price_source, row.volume_source))
    return references


def _price_volume_mix_bridges(plan, actuals, rows, check_plan, check_actual):
    """Return deterministic, exactly reconciled commercial bridges.

    The ordering is disclosed: volume at planned average price, price at actual
    volume, then mix as the exact reconciliation remainder.  Rounding uses
    half-even at the configured currency precision and only mix absorbs it.
    """
    actual_by_id = {item.bridge_id: item for item in actuals.price_volume_mix}
    row_by_cell = {row["cell_id"]: row for row in rows}
    bridges = []
    for policy in sorted(plan.price_volume_mix_policies, key=lambda item: item.bridge_id):
        basis = actual_by_id.get(policy.bridge_id)
        scope_cell = next(cell for cell in plan.cells if cell.id == policy.rows[0].cell_id)
        scope = {key: value for key, value in scope_cell.dimensions.items() if key != policy.mix_dimension}
        for planned in policy.rows:
            check_plan(planned.price_source)
            check_plan(planned.volume_source)
        if basis is None:
            bridges.append({
                "bridge_id": policy.bridge_id, "metric": policy.metric, "status": "missing_actual_basis",
                "mix_dimension": policy.mix_dimension, "scope": scope, "currency_unit": policy.currency_unit,
                "price_unit": policy.price_unit, "volume_unit": policy.volume_unit,
                "missing_members": sorted(row.member for row in policy.rows),
                "formula_version": "price-volume-mix.v1",
            })
            continue
        if (basis.currency_unit, basis.price_unit, basis.volume_unit) != (
                policy.currency_unit, policy.price_unit, policy.volume_unit):
            raise ValueError("Actual price/volume/mix units must exactly match the approved policy.")
        plan_by_member = {row.member: row for row in policy.rows}
        actual_by_member = {row.member: row for row in basis.rows}
        if set(plan_by_member) != set(actual_by_member):
            raise ValueError("Actual price/volume/mix members must exactly match the approved policy.")
        for actual in basis.rows:
            check_actual(actual.price_source)
            check_actual(actual.volume_source)
        missing_revenue = sorted(row.cell_id for row in policy.rows
                                 if row_by_cell[row.cell_id]["actual"] is None)
        if missing_revenue:
            bridges.append({
                "bridge_id": policy.bridge_id, "metric": policy.metric, "status": "missing_revenue_actuals",
                "mix_dimension": policy.mix_dimension, "scope": scope, "currency_unit": policy.currency_unit,
                "price_unit": policy.price_unit, "volume_unit": policy.volume_unit,
                "missing_cells": missing_revenue, "formula_version": "price-volume-mix.v1",
            })
            continue
        details = []
        with localcontext() as ctx:
            ctx.prec = 80
            planned_revenue = planned_volume = actual_revenue = actual_volume = Decimal(0)
            price_effect_raw = Decimal(0)
            for member in sorted(plan_by_member):
                planned, actual = plan_by_member[member], actual_by_member[member]
                row = row_by_cell[planned.cell_id]
                calculated_actual = actual.actual_price * actual.actual_volume
                if Decimal(row["actual"]) != calculated_actual:
                    raise ValueError("Actual revenue cell must equal its disclosed price multiplied by volume.")
                planned_revenue += planned.planned_price * planned.planned_volume
                planned_volume += planned.planned_volume
                actual_revenue += calculated_actual
                actual_volume += actual.actual_volume
                price_effect_raw += (actual.actual_price - planned.planned_price) * actual.actual_volume
                details.append({
                    "member": member, "cell_id": planned.cell_id,
                    "planned_price": str(planned.planned_price), "planned_volume": str(planned.planned_volume),
                    "actual_price": str(actual.actual_price), "actual_volume": str(actual.actual_volume),
                    "planned_revenue": str(planned.planned_price * planned.planned_volume),
                    "actual_revenue": str(calculated_actual),
                    "plan_revenue_source": row["plan_source"], "actual_revenue_source": row["actual_source"],
                    "plan_price_source": planned.price_source.model_dump(mode="json"),
                    "plan_volume_source": planned.volume_source.model_dump(mode="json"),
                    "actual_price_source": actual.price_source.model_dump(mode="json"),
                    "actual_volume_source": actual.volume_source.model_dump(mode="json"),
                })
            quantum = Decimal(1).scaleb(-policy.decimal_places)
            if planned_revenue.quantize(quantum) != planned_revenue or actual_revenue.quantize(quantum) != actual_revenue:
                raise ValueError("Bridge revenue exceeds the approved currency precision.")
            planned_average_price = planned_revenue / planned_volume
            volume_effect = (planned_average_price * (actual_volume - planned_volume)).quantize(
                quantum, rounding=ROUND_HALF_EVEN)
            price_effect = price_effect_raw.quantize(quantum, rounding=ROUND_HALF_EVEN)
            observed_variance = actual_revenue - planned_revenue
            mix_effect = observed_variance - volume_effect - price_effect
            reconstructed = volume_effect + mix_effect + price_effect
        bridges.append({
            "bridge_id": policy.bridge_id, "metric": policy.metric, "status": "reconciled",
            "mix_dimension": policy.mix_dimension, "scope": scope, "currency_unit": policy.currency_unit,
            "price_unit": policy.price_unit, "volume_unit": policy.volume_unit,
            "decimal_places": policy.decimal_places, "formula_version": "price-volume-mix.v1",
            "calculation_order": ["volume_at_planned_average_price", "price_at_actual_volume",
                                  "mix_as_exact_reconciliation_remainder"],
            "rounding": "half_even; mix absorbs currency rounding remainder",
            "plan": {"revenue": str(planned_revenue), "volume": str(planned_volume),
                     "average_price": str(planned_average_price)},
            "actual": {"revenue": str(actual_revenue), "volume": str(actual_volume)},
            "effects": {"volume": str(volume_effect), "mix": str(mix_effect), "price": str(price_effect),
                        "observed_variance": str(observed_variance),
                        "reconstructed_variance": str(reconstructed)},
            "reconciles": reconstructed == observed_variance, "rows": details,
        })
    unknown = sorted(set(actual_by_id) - {item.bridge_id for item in plan.price_volume_mix_policies})
    if unknown:
        raise ValueError("Actual price/volume/mix data references an unapproved bridge: " + ", ".join(unknown))
    return bridges


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
                "tolerance": str(cell.tolerance),
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
    price_volume_mix = _price_volume_mix_bridges(
        plan, actuals, rows,
        lambda source: check(source, root),
        lambda source: check(source, actual_root),
    )
    plan_payload = plan.model_dump(mode="json")
    plan_payload["cells"] = sorted(plan_payload["cells"], key=lambda c: c["id"])
    plan_payload["price_volume_mix_policies"] = sorted(
        plan_payload["price_volume_mix_policies"], key=lambda item: item["bridge_id"])
    for bridge in plan_payload["price_volume_mix_policies"]:
        bridge["rows"].sort(key=lambda item: item["member"])
    for members in plan_payload["dimensions"].values():
        members.sort()
    actual_payload = actuals.model_dump(mode="json")
    actual_payload["observations"] = sorted(actual_payload["observations"], key=lambda o: cell_key(o["metric"], o["dimensions"]))
    actual_payload["price_volume_mix"] = sorted(
        actual_payload["price_volume_mix"], key=lambda item: item["bridge_id"])
    for bridge in actual_payload["price_volume_mix"]:
        bridge["rows"].sort(key=lambda item: item["member"])
    plan_hash, actual_hash = fingerprint(plan_payload), fingerprint(actual_payload)
    findings = []
    for rollup in rollups:
        if not rollup["offset_detected"]:
            continue
        selected = [row for row in rows if row["metric"] == rollup["metric"] and row["status"] in {"behind", "ahead"}]
        behind_delta = sum((Decimal(row["variance"]) for row in selected if row["status"] == "behind"), Decimal(0))
        ahead_delta = sum((Decimal(row["variance"]) for row in selected if row["status"] == "ahead"), Decimal(0))
        identity = {"type": "offset", "metric": rollup["metric"], "cells": [row["cell_id"] for row in selected],
                    "plan_hash": plan_hash, "actuals_hash": actual_hash}
        findings.append({
            "finding_id": fingerprint(identity), "finding_type": "offset", "metric": rollup["metric"],
            "status": "material_composition_drift", "cells": [{
                "cell_id": row["cell_id"], "dimensions": row["dimensions"], "status": row["status"],
                "variance": row["variance"], "plan_source": row["plan_source"], "actual_source": row["actual_source"],
            } for row in selected],
            "arithmetic": {"actual_minus_plan_behind": str(behind_delta),
                           "actual_minus_plan_ahead": str(ahead_delta),
                           "net_variance": rollup["variance"]},
            "plan_citation": {"plan_id": plan.plan_id, "version": plan.version, "digest": plan_hash},
            "narrative": (rollup["metric"] + " is " + rollup["status"].replace('_', ' ') +
                          " at total, but " + str(len(rollup["behind_cells"])) + " cell(s) are behind and " +
                          str(len(rollup["ahead_cells"])) + " are ahead. Actual minus plan is " +
                          str(behind_delta) + " behind and " + str(ahead_delta) + " ahead; net " +
                          str(rollup["variance"]) + ". Compared with ratified plan " + plan.plan_id +
                          " version " + str(plan.version) + "."),
        })
    for policy in plan.concentration_policies:
        groups = {}
        for row in rows:
            if row["metric"] != policy.metric or row["actual"] is None or Decimal(row["actual"]) <= 0:
                continue
            scope = tuple(sorted((key, value) for key, value in row["dimensions"].items()
                                 if key != policy.dimension))
            groups.setdefault(scope, []).append(row)
        for scope, candidates in sorted(groups.items()):
            if len(candidates) < 2:
                continue
            total = sum((Decimal(row["actual"]) for row in candidates), Decimal(0))
            if total <= 0:
                continue
            top = sorted(candidates, key=lambda row: (-Decimal(row["actual"]), row["cell_id"]))[0]
            share = Decimal(top["actual"]) / total * Decimal(100)
            if share <= policy.threshold_percent:
                continue
            identity = {"type": "concentration", "policy": policy.policy_id, "scope": scope,
                        "cell": top["cell_id"], "plan_hash": plan_hash,
                        "actuals_hash": actual_hash}
            findings.append({
                "finding_id": fingerprint(identity), "finding_type": "concentration", "metric": policy.metric,
                "status": "above_threshold", "policy_id": policy.policy_id,
                "dimension": policy.dimension, "member": top["dimensions"][policy.dimension],
                "scope": dict(scope), "cell_id": top["cell_id"], "actual": top["actual"],
                "scope_total": str(total), "share_percent": str(share),
                "threshold_percent": str(policy.threshold_percent),
                "plan_source": top["plan_source"], "actual_source": top["actual_source"],
                "plan_citation": {"plan_id": plan.plan_id, "version": plan.version, "digest": plan_hash},
                "narrative": (top["dimensions"][policy.dimension] + " provides " + str(share) + "% of " +
                              policy.metric + " for this cell group, above the approved " +
                              str(policy.threshold_percent) + "% threshold. Compared with ratified plan " +
                              plan.plan_id + " version " + str(plan.version) + "."),
            })
    for bridge in price_volume_mix:
        if bridge["status"] != "reconciled":
            continue
        effects = bridge["effects"]
        identity = {"type": "price_volume_mix", "bridge_id": bridge["bridge_id"],
                    "plan_hash": plan_hash, "actuals_hash": actual_hash}
        findings.append({
            "finding_id": fingerprint(identity), "finding_type": "price_volume_mix",
            "metric": bridge["metric"], "status": "reconciled", "bridge_id": bridge["bridge_id"],
            "mix_dimension": bridge["mix_dimension"], "scope": bridge["scope"],
            "currency_unit": bridge["currency_unit"], "price_unit": bridge["price_unit"],
            "volume_unit": bridge["volume_unit"], "formula_version": bridge["formula_version"],
            "calculation_order": bridge["calculation_order"], "rounding": bridge["rounding"],
            "plan": bridge["plan"], "actual": bridge["actual"], "effects": effects,
            "reconciles": bridge["reconciles"],
            "cells": [{"cell_id": row["cell_id"], "member": row["member"],
                       "plan_source": row["plan_revenue_source"],
                       "actual_source": row["actual_revenue_source"]} for row in bridge["rows"]],
            "input_rows": bridge["rows"],
            "plan_citation": {"plan_id": plan.plan_id, "version": plan.version, "digest": plan_hash},
            "narrative": (bridge["metric"] + " actual minus plan is " + effects["observed_variance"] +
                          " " + bridge["currency_unit"] + ": volume " + effects["volume"] +
                          ", mix " + effects["mix"] + ", and price " + effects["price"] +
                          ". The effects reconcile exactly to the observed variance."),
        })
    result = {"schema_version": 1, "formula_version": "cell-variance.v3", "company_id": company_id,
        "plan_id": plan.plan_id, "plan_version": plan.version, "period": plan.period.model_dump(mode="json"),
        "as_of": as_of.isoformat(), "plan_hash": plan_hash, "actuals_hash": actual_hash,
        "approval_status": plan.status, "approval_basis": "imported_metadata_not_authorization_verified",
        "comparison_basis": "imported_ratified_plan" if plan.status == "ratified" else "proposed_plan_preview",
        "cells": rows, "rollups": rollups, "price_volume_mix": price_volume_mix, "findings": findings}
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
