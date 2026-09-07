"""Deterministic decomposition of one approved plan cell into accountable cells."""
from decimal import Decimal, ROUND_DOWN, localcontext
from typing import Literal

from pydantic import Field, model_validator

from .dimensional_plan import Amount, Contract, Name, Plan, SourceReference, fingerprint


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
    quantum = Decimal(1).scaleb(-request.decimal_places)
    ordered = sorted(request.allocations, key=lambda item: item.cell_id)
    total_weight = sum((item.weight for item in ordered), Decimal(0))
    with localcontext() as context:
        context.prec = 80
        if parent_cell.target.quantize(quantum) != parent_cell.target:
            raise ValueError("Parent target has more decimal places than the requested precision.")
        amounts = []
        assigned = Decimal(0)
        for item in ordered[:-1]:
            value = (parent_cell.target * item.weight / total_weight).quantize(quantum, rounding=ROUND_DOWN)
            amounts.append(value)
            assigned += value
        amounts.append(parent_cell.target - assigned)
    if any(value.quantize(quantum) != value for value in amounts):
        raise ValueError("Allocation remainder cannot be represented at the requested precision.")

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
            }
            for item in ordered
        ],
    }
    payload["derivation"]["request_hash"] = fingerprint(payload["derivation"])
    return Plan.model_validate(payload)
