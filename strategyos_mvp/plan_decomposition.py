"""Deterministic decomposition of one approved plan cell into accountable cells."""
from decimal import Decimal, ROUND_DOWN, localcontext
from typing import Literal

from pydantic import Field, model_validator

from .dimensional_plan import Actuals, Amount, Contract, Name, Plan, SourceReference, fingerprint


class Allocation(Contract):
    cell_id: Name
    member: Name
    weight: Amount = Field(gt=0)
    owner: Name
    tolerance: Amount = Field(ge=0)
    basis: SourceReference


class DecompositionRequest(Contract):
    parent_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    parent_cell_id: Name
    split_dimension: Name
    decimal_places: int = Field(default=2, ge=0, le=12, strict=True)
    allocations: list[Allocation] = Field(min_length=2, max_length=500)

    @model_validator(mode="after")
    def unique_outputs(self):
        ids = [item.cell_id for item in self.allocations]
        members = [item.member for item in self.allocations]
        if len(ids) != len(set(ids)) or len(members) != len(set(members)):
            raise ValueError("Allocation cell IDs and split members must be unique.")
        return self


class HistoricalAllocation(Contract):
    cell_id: Name
    member: Name
    owner: Name
    tolerance: Amount = Field(ge=0)
    adjustment_percent: Amount = Field(default=0, gt=-100, le=100000)


class HistoricalDecompositionRequest(Contract):
    parent_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    parent_cell_id: Name
    split_dimension: Name
    historical_actual_revision: Name
    decimal_places: int = Field(default=2, ge=0, le=12, strict=True)
    allocations: list[HistoricalAllocation] = Field(min_length=2, max_length=500)

    @model_validator(mode="after")
    def unique_outputs(self):
        ids = [item.cell_id for item in self.allocations]
        members = [item.member for item in self.allocations]
        if len(ids) != len(set(ids)) or len(members) != len(set(members)):
            raise ValueError("Historical allocation cell IDs and members must be unique.")
        return self


class ObjectiveAllocation(Contract):
    cell_id: Name
    dimensions: dict[Name, Name] = Field(min_length=1)
    weight: Amount = Field(gt=0)
    owner: Name
    tolerance: Amount = Field(ge=0)
    basis_cell_id: Name


class ObjectiveDecompositionRequest(Contract):
    parent_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    metric: Name
    split_dimensions: list[Name] = Field(min_length=2, max_length=20)
    decimal_places: int = Field(default=2, ge=0, le=12, strict=True)
    allocations: list[ObjectiveAllocation] = Field(min_length=2, max_length=5000)

    @model_validator(mode="after")
    def unique_outputs(self):
        if len(self.split_dimensions) != len(set(self.split_dimensions)):
            raise ValueError("Split dimensions must be unique.")
        ids = [item.cell_id for item in self.allocations]
        tuples = [tuple(sorted(item.dimensions.items())) for item in self.allocations]
        if len(ids) != len(set(ids)) or len(tuples) != len(set(tuples)):
            raise ValueError("Allocation cell IDs and dimensional tuples must be unique.")
        return self


def _allocate(total, weighted, decimal_places):
    quantum = Decimal(1).scaleb(-decimal_places)
    total_weight = sum((item.weight for item in weighted), Decimal(0))
    with localcontext() as context:
        context.prec = 80
        if total.quantize(quantum) != total:
            raise ValueError("Parent target has more decimal places than the requested precision.")
        amounts, assigned = [], Decimal(0)
        for item in weighted[:-1]:
            value = (total * item.weight / total_weight).quantize(quantum, rounding=ROUND_DOWN)
            amounts.append(value); assigned += value
        amounts.append(total - assigned)
    if any(value.quantize(quantum) != value for value in amounts):
        raise ValueError("Allocation remainder cannot be represented at the requested precision.")
    return amounts


def decompose(parent: Plan, request: DecompositionRequest, *, next_version: int) -> Plan:
    """Return a proposal that exactly reconciles to its ratified parent plan.

    Every child gets its own owner, tolerance and allocation-basis evidence. The
    final lexicographic cell receives the disclosed rounding remainder.
    """
    if parent.status != "proposed":
        # Stored governance, rather than imported metadata, proves ratification.
        raise ValueError("Decomposition requires the stored ratified plan payload.")
    if request.split_dimension not in parent.dimensions:
        raise ValueError("The split dimension is not configured on the parent plan.")
    parent_cell = next((cell for cell in parent.cells if cell.id == request.parent_cell_id), None)
    if parent_cell is None:
        raise ValueError("Parent cell not found.")
    if any(item.cell_id == parent_cell.id for item in request.allocations):
        raise ValueError("A decomposed child must use a new cell ID.")
    if next_version <= parent.version:
        raise ValueError("A decomposition must create a later plan version.")
    ordered = sorted(request.allocations, key=lambda item: item.cell_id)
    amounts = _allocate(parent_cell.target, ordered, request.decimal_places)

    payload = parent.model_dump(mode="json")
    payload["version"] = next_version
    payload["status"] = "proposed"
    payload["ratified_by"] = payload["ratified_on"] = payload["ratification"] = None
    payload["cells"] = [cell for cell in payload["cells"] if cell["id"] != parent_cell.id]
    for item, target in zip(ordered, amounts):
        dimensions = dict(parent_cell.dimensions)
        dimensions[request.split_dimension] = item.member
        payload["cells"].append({
            "id": item.cell_id,
            "metric": parent_cell.metric,
            "dimensions": dimensions,
            "owner": item.owner,
            "target": str(target),
            "tolerance": str(item.tolerance),
            "source": item.basis.model_dump(mode="json"),
        })
    members = set(payload["dimensions"][request.split_dimension])
    members.update(item.member for item in ordered)
    payload["dimensions"][request.split_dimension] = sorted(members)
    payload["derivation"] = {
        "kind": "decomposition",
        "engine_version": "weighted-allocation.v1",
        "parent_plan_id": parent.plan_id,
        "parent_version": parent.version,
        "parent_digest": request.parent_digest,
        "parent_cell_id": parent_cell.id,
        "split_dimension": request.split_dimension,
        "decimal_places": request.decimal_places,
        "remainder_rule": "final_lexicographic_cell",
        "allocations": [
            {
                "cell_id": item.cell_id,
                "member": item.member,
                "weight": str(item.weight),
                "owner": item.owner,
                "tolerance": str(item.tolerance),
                "basis": item.basis.model_dump(mode="json"),
                "target_source": item.basis.model_dump(mode="json"),
            }
            for item in ordered
        ],
    }
    payload["derivation"]["request_hash"] = fingerprint(payload["derivation"])
    return Plan.model_validate(payload)


def decompose_objective(parent: Plan, request: ObjectiveDecompositionRequest, *, next_version: int) -> Plan:
    """Replace one complete metric objective with accountable multidimensional cells."""
    if parent.status != "proposed":
        raise ValueError("Decomposition requires the stored ratified plan payload.")
    if request.metric not in parent.metrics:
        raise ValueError("The objective metric is not configured on the parent plan.")
    if any(name not in parent.dimensions for name in request.split_dimensions):
        raise ValueError("Every split dimension must be configured on the parent plan.")
    if next_version <= parent.version:
        raise ValueError("A decomposition must create a later plan version.")
    existing_ids = {cell.id for cell in parent.cells}
    parent_cells = {cell.id: cell for cell in parent.cells if cell.metric == request.metric}
    if not parent_cells:
        raise ValueError("The objective has no parent cells.")
    if any(item.cell_id in existing_ids for item in request.allocations):
        raise ValueError("Objective decomposition cells must use new cell IDs.")
    expected_dimensions = set(parent.dimensions)
    for item in request.allocations:
        if set(item.dimensions) != expected_dimensions:
            raise ValueError("Every objective allocation must supply the exact configured dimensions.")
        if item.basis_cell_id not in parent_cells:
            raise ValueError("Every allocation basis must name a parent cell for the selected objective.")
    for dimension in expected_dimensions - set(request.split_dimensions):
        if len({item.dimensions[dimension] for item in request.allocations}) != 1:
            raise ValueError("Changing a dimension requires declaring it as a split dimension: " + dimension + ".")
    for dimension in request.split_dimensions:
        if len({item.dimensions[dimension] for item in request.allocations}) < 2:
            raise ValueError("Every declared split dimension must contain at least two allocation members: " + dimension + ".")
    ordered = sorted(request.allocations, key=lambda item: item.cell_id)
    total = parent.metrics[request.metric].planned_total
    amounts = _allocate(total, ordered, request.decimal_places)
    payload = parent.model_dump(mode="json")
    payload.update(version=next_version, status="proposed", ratified_by=None, ratified_on=None, ratification=None)
    payload["cells"] = [cell for cell in payload["cells"] if cell["metric"] != request.metric]
    lineage = []
    for item, target in zip(ordered, amounts):
        basis = parent_cells[item.basis_cell_id].source.model_dump(mode="json")
        payload["cells"].append({
            "id": item.cell_id, "metric": request.metric, "dimensions": item.dimensions,
            "owner": item.owner, "target": str(target), "tolerance": str(item.tolerance), "source": basis,
        })
        lineage.append({
            "cell_id": item.cell_id, "dimensions": item.dimensions, "weight": str(item.weight),
            "owner": item.owner, "tolerance": str(item.tolerance), "basis": basis, "target_source": basis,
        })
    for dimension in payload["dimensions"]:
        payload["dimensions"][dimension] = sorted(set(payload["dimensions"][dimension]) |
                                                   {item.dimensions[dimension] for item in ordered})
    payload["derivation"] = {
        "kind": "decomposition", "engine_version": "weighted-multidimensional-allocation.v1",
        "parent_plan_id": parent.plan_id, "parent_version": parent.version,
        "parent_digest": request.parent_digest, "parent_metric": request.metric,
        "split_dimensions": request.split_dimensions, "decimal_places": request.decimal_places,
        "remainder_rule": "final_lexicographic_cell", "allocations": lineage,
    }
    payload["derivation"]["request_hash"] = fingerprint(payload["derivation"])
    return Plan.model_validate(payload)


def matching_history(parent: Plan, actuals: Actuals, *, parent_cell_id: str, split_dimension: str):
    if actuals.company_id != parent.company_id:
        raise ValueError("Historical actual company scope differs from the plan.")
    if actuals.period.end >= parent.period.start or actuals.recorded_on >= parent.period.start:
        raise ValueError("Historical weights require a completed snapshot before the plan period.")
    parent_cell = next((cell for cell in parent.cells if cell.id == parent_cell_id), None)
    if parent_cell is None:
        raise ValueError("Parent cell not found.")
    if split_dimension not in parent.dimensions:
        raise ValueError("The split dimension is not configured on the parent plan.")
    fixed = {key: value for key, value in parent_cell.dimensions.items() if key != split_dimension}
    matched = {}
    for observation in actuals.observations:
        if (observation.metric != parent_cell.metric or set(observation.dimensions) != set(parent.dimensions) or
                any(observation.dimensions.get(key) != value for key, value in fixed.items())):
            continue
        if observation.unit != parent.metrics[parent_cell.metric].unit:
            raise ValueError("Historical actual unit differs from the plan metric.")
        member = observation.dimensions[split_dimension]
        if member in matched:
            raise ValueError("Historical snapshot has duplicate members for this parent cell.")
        matched[member] = observation
    return parent_cell, matched


def decompose_from_history(parent: Plan, actuals: Actuals, request: HistoricalDecompositionRequest, *,
                           next_version: int, historical_digest: str, historical_source_pack_id: str) -> Plan:
    if actuals.revision != request.historical_actual_revision:
        raise ValueError("Historical actual revision differs from the selected snapshot.")
    parent_cell, history = matching_history(parent, actuals, parent_cell_id=request.parent_cell_id,
                                            split_dimension=request.split_dimension)
    explicit = []
    lineage = []
    for item in request.allocations:
        observation = history.get(item.member)
        if observation is None:
            raise ValueError(f"No historical observation exists for member {item.member}.")
        if observation.value is None:
            raise ValueError(f"Historical observation for member {item.member} is missing, not zero.")
        if observation.value <= 0:
            raise ValueError(f"Historical observation for member {item.member} must be positive for mix allocation.")
        with localcontext() as context:
            context.prec = 80
            effective = observation.value * (Decimal(1) + item.adjustment_percent / Decimal(100))
        if effective <= 0:
            raise ValueError("Historical adjustment must leave every effective weight positive.")
        explicit.append(Allocation(cell_id=item.cell_id, member=item.member, weight=effective,
                                   owner=item.owner, tolerance=item.tolerance, basis=parent_cell.source))
        lineage.append({
            "cell_id": item.cell_id,
            "member": item.member,
            "weight": str(effective),
            "owner": item.owner,
            "tolerance": str(item.tolerance),
            "basis": observation.source.model_dump(mode="json"),
            "target_source": parent_cell.source.model_dump(mode="json"),
            "historical_value": str(observation.value),
            "adjustment_percent": str(item.adjustment_percent),
            "effective_weight": str(effective),
        })
    proposal = decompose(parent, DecompositionRequest(
        parent_digest=request.parent_digest,
        parent_cell_id=request.parent_cell_id,
        split_dimension=request.split_dimension,
        decimal_places=request.decimal_places,
        allocations=explicit,
    ), next_version=next_version)
    payload = proposal.model_dump(mode="json", exclude_none=True)
    derivation = payload["derivation"]
    derivation.update({
        "engine_version": "history-adjusted-allocation.v1",
        "allocations": sorted(lineage, key=lambda value: value["cell_id"]),
        "historical_actual_revision": actuals.revision,
        "historical_actual_digest": historical_digest,
        "historical_source_pack_id": historical_source_pack_id,
    })
    derivation.pop("request_hash")
    derivation["request_hash"] = fingerprint(derivation)
    return Plan.model_validate(payload)
