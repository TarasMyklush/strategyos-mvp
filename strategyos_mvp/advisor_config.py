"""Versioned, sector-neutral Strategic Advisor client configuration."""
from typing import Literal

from pydantic import Field, model_validator

from .board_pack import PackTemplate, Translation
from .dimensional_plan import Amount, Contract, Name
from .plan_decomposition import HistoricalAllocation, HistoricalDecompositionRequest


class AdvisorAllocation(Contract):
    cell_id: Name
    member: Name
    owner: Name
    tolerance: Amount = Field(ge=0)
    adjustment_percent: Amount = Field(default=0, gt=-100, le=100000)
    label: Translation


class AdvisorConfiguration(Contract):
    schema_version: Literal[1] = 1
    config_id: Name
    version: int = Field(ge=1, strict=True)
    executive_sponsor: Name
    objective: str = Field(min_length=20, max_length=1000)
    plan_id: Name
    plan_version: int = Field(ge=1, strict=True)
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    parent_cell_id: Name
    split_dimension: Name
    historical_actual_revision: Name
    decimal_places: int = Field(default=2, ge=0, le=12, strict=True)
    client: Translation
    board_title: Translation
    metric_label: Translation
    dimension_label: Translation
    additional_labels: dict[Name, Translation] = Field(default_factory=dict, max_length=200)
    allocations: list[AdvisorAllocation] = Field(min_length=2, max_length=500)

    @model_validator(mode="after")
    def unique_allocations(self):
        ids = [item.cell_id for item in self.allocations]
        members = [item.member for item in self.allocations]
        if len(ids) != len(set(ids)) or len(members) != len(set(members)):
            raise ValueError("Advisor allocation cell IDs and members must be unique.")
        return self

    def decomposition_request(self):
        return HistoricalDecompositionRequest(
            parent_digest=self.plan_digest,
            parent_cell_id=self.parent_cell_id,
            split_dimension=self.split_dimension,
            historical_actual_revision=self.historical_actual_revision,
            decimal_places=self.decimal_places,
            allocations=[HistoricalAllocation(**item.model_dump(exclude={"label"})) for item in self.allocations],
        )

    def board_template(self, metric: str):
        labels = dict(self.additional_labels)
        labels.update({metric: self.metric_label, self.split_dimension: self.dimension_label})
        labels.update({item.member: item.label for item in self.allocations})
        return PackTemplate(
            template_id=self.config_id[:80], version=self.version,
            title=self.board_title, client=self.client, labels=labels,
        )
