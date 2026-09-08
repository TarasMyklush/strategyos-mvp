"""Sector-neutral, declarative organization and dimension configuration."""
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .board_pack import Translation
from .dimensional_plan import Contract, Name


class BusinessUnit(Contract):
    key: Name
    label: Translation
    parent: Name | None = None


class DimensionMember(Contract):
    key: Name
    label: Translation
    parent: Name | None = None


class DimensionDefinition(Contract):
    key: Name
    label: Translation
    members: list[DimensionMember] = Field(min_length=1, max_length=2000)


class MappingValue(Contract):
    source_value: str = Field(min_length=1, max_length=200)
    target: Name

    @field_validator('source_value')
    @classmethod
    def bounded_source_value(cls, value):
        if any(ord(char) < 32 for char in value):
            raise ValueError('Source mapping values must be printable single-line text.')
        return value.strip()


class SourceMapping(Contract):
    source_key: Name
    source_field: str = Field(min_length=1, max_length=160)
    target_type: Literal['business_unit', 'dimension']
    target_key: Name | None = None
    values: list[MappingValue] = Field(min_length=1, max_length=5000)

    @field_validator('source_field')
    @classmethod
    def bounded_source_field(cls, value):
        if any(ord(char) < 32 for char in value):
            raise ValueError('Source field names must be printable single-line text.')
        return value.strip()

    @model_validator(mode='after')
    def target_shape(self):
        if self.target_type == 'dimension' and not self.target_key:
            raise ValueError('A dimension source mapping requires its configured dimension key.')
        if self.target_type == 'business_unit' and self.target_key is not None:
            raise ValueError('A business-unit source mapping does not use a target key.')
        return self


def _validate_tree(kind, nodes):
    keys = [node.key for node in nodes]
    if len(keys) != len(set(keys)):
        raise ValueError(kind + ' keys must be unique.')
    available = set(keys)
    parents = {node.key: node.parent for node in nodes}
    unknown = sorted({parent for parent in parents.values() if parent and parent not in available})
    if unknown:
        raise ValueError(kind + ' parents are not configured: ' + ', '.join(unknown) + '.')
    for key in keys:
        visited, current = set(), key
        while current:
            if current in visited:
                raise ValueError(kind + ' hierarchy contains a cycle at ' + key + '.')
            visited.add(current)
            current = parents.get(current)


class TenantStructureConfiguration(Contract):
    schema_version: Literal[1] = 1
    config_id: Name
    version: int = Field(ge=1, strict=True)
    company: Translation
    business_units: list[BusinessUnit] = Field(min_length=1, max_length=500)
    dimensions: list[DimensionDefinition] = Field(min_length=1, max_length=50)
    source_mappings: list[SourceMapping] = Field(min_length=2, max_length=500)

    @model_validator(mode='after')
    def valid_structure(self):
        _validate_tree('Business-unit', self.business_units)
        dimension_keys = [dimension.key for dimension in self.dimensions]
        if len(dimension_keys) != len(set(dimension_keys)):
            raise ValueError('Dimension keys must be unique.')
        members = {}
        for dimension in self.dimensions:
            _validate_tree('Dimension ' + dimension.key, dimension.members)
            members[dimension.key] = {member.key for member in dimension.members}
        business_units = {unit.key for unit in self.business_units}
        mapped_targets = set()
        mapping_keys = []
        for mapping in self.source_mappings:
            target = ('business_unit', '') if mapping.target_type == 'business_unit' else ('dimension', mapping.target_key)
            mapped_targets.add(target)
            mapping_key = (mapping.source_key, mapping.source_field, *target)
            mapping_keys.append(mapping_key)
            allowed = business_units if mapping.target_type == 'business_unit' else members.get(mapping.target_key or '')
            if allowed is None:
                raise ValueError('Source mapping references an unknown dimension: ' + str(mapping.target_key) + '.')
            source_values = [value.source_value for value in mapping.values]
            if len(source_values) != len(set(source_values)):
                raise ValueError('Source values must be unique within each mapping.')
            unknown = sorted({value.target for value in mapping.values} - allowed)
            if unknown:
                raise ValueError('Source mapping targets are not configured: ' + ', '.join(unknown) + '.')
        if len(mapping_keys) != len(set(mapping_keys)):
            raise ValueError('Source field mappings must be unique for each configured target.')
        required = {('business_unit', ''), *{('dimension', key) for key in dimension_keys}}
        missing = sorted(key or kind for kind, key in required - mapped_targets)
        if missing:
            raise ValueError('Source mappings are required for business units and every dimension: ' + ', '.join(missing) + '.')
        return self
