from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .data_roles import run_model_role_specs


@dataclass(frozen=True)
class DetectorRoleContract:
    role: str
    attribute_name: str
    default_relative_path: str
    required_columns: tuple[str, ...] = ()
    date_columns: tuple[str, ...] = ()
    column_aliases: dict[str, tuple[str, ...]] | None = None
    expected_sheet_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedDetectorContract:
    role: str
    attribute_name: str
    relative_path: str
    required_columns: tuple[str, ...]
    date_columns: tuple[str, ...]
    resolution: str
    column_mapping: dict[str, str]
    expected_sheet_names: tuple[str, ...] = ()

    def artifact(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "attribute_name": self.attribute_name,
            "relative_path": self.relative_path,
            "required_columns": list(self.required_columns),
            "date_columns": list(self.date_columns),
            "resolution": self.resolution,
            "column_mapping": dict(self.column_mapping),
            "expected_sheet_names": list(self.expected_sheet_names),
        }


def _build_detector_role_contracts() -> tuple[DetectorRoleContract, ...]:
    return tuple(
        DetectorRoleContract(
            role=spec.role,
            attribute_name=str(spec.attribute_name),
            default_relative_path=str(spec.target_path),
            required_columns=spec.required_columns,
            date_columns=spec.date_columns,
            column_aliases=dict(spec.column_aliases),
            expected_sheet_names=spec.expected_sheet_names,
        )
        for spec in run_model_role_specs()
    )


DETECTOR_ROLE_CONTRACTS: tuple[DetectorRoleContract, ...] = _build_detector_role_contracts()


CONTRACTS_BY_ROLE = {contract.role: contract for contract in DETECTOR_ROLE_CONTRACTS}


def refresh_detector_role_contracts() -> None:
    global DETECTOR_ROLE_CONTRACTS, CONTRACTS_BY_ROLE
    DETECTOR_ROLE_CONTRACTS = _build_detector_role_contracts()
    CONTRACTS_BY_ROLE = {
        contract.role: contract for contract in DETECTOR_ROLE_CONTRACTS
    }


def _normalize_column_name(value: str) -> str:
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def _load_preview(path: Path) -> tuple[list[str], list[str]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(path, nrows=5)
        return list(frame.columns), []
    if suffix == ".tsv":
        frame = pd.read_csv(path, sep="\t", nrows=5)
        return list(frame.columns), []
    if suffix == ".json":
        frame = pd.read_json(path)
        return list(frame.columns), []
    workbook = pd.ExcelFile(path)
    first_sheet = workbook.sheet_names[0] if workbook.sheet_names else 0
    frame = pd.read_excel(path, sheet_name=first_sheet, nrows=5)
    return list(frame.columns), list(workbook.sheet_names)


def _match_columns(contract: DetectorRoleContract, columns: list[str]) -> dict[str, str] | None:
    if not contract.required_columns:
        return {}
    normalized = {_normalize_column_name(column): str(column) for column in columns}
    mapping: dict[str, str] = {}
    for required in contract.required_columns:
        direct = normalized.get(_normalize_column_name(required))
        if direct:
            mapping[required] = direct
            continue
        aliases = (contract.column_aliases or {}).get(required, ())
        match = next((normalized.get(_normalize_column_name(alias)) for alias in aliases if normalized.get(_normalize_column_name(alias))), None)
        if match:
            mapping[required] = match
            continue
        return None
    return mapping


def _sheet_names_match(contract: DetectorRoleContract, sheet_names: list[str]) -> bool:
    if not contract.expected_sheet_names:
        return False
    normalized = {_normalize_column_name(name) for name in sheet_names}
    expected = {_normalize_column_name(name) for name in contract.expected_sheet_names}
    return expected.issubset(normalized)


def _candidate_paths(dataset_root: Path, contract: DetectorRoleContract) -> list[Path]:
    default_path = dataset_root / contract.default_relative_path
    candidates: list[Path] = []
    if default_path.exists():
        candidates.append(default_path)
    discovered_paths = sorted(
        dataset_root.rglob("*"),
        key=lambda path: (len(path.relative_to(dataset_root).parts), path.as_posix()),
    )
    for path in discovered_paths:
        if not path.is_file() or path == default_path:
            continue
        if path.suffix.lower() not in {".csv", ".tsv", ".json", ".xls", ".xlsx"}:
            continue
        candidates.append(path)
    return candidates


def resolve_detector_contracts(dataset_root: Path) -> dict[str, ResolvedDetectorContract]:
    resolved, unresolved = resolve_detector_contracts_partial(dataset_root)
    if unresolved:
        raise FileNotFoundError(
            "Could not resolve detector data contracts for roles "
            f"{sorted(unresolved)} under '{dataset_root}'."
        )
    return resolved


def resolve_detector_contracts_partial(
    dataset_root: Path,
) -> tuple[dict[str, ResolvedDetectorContract], list[str]]:
    """Resolve what is present; return (resolved_by_role, unresolved_roles).

    Unlike ``resolve_detector_contracts`` this never raises for a missing role,
    so partial source packs can run only the detectors whose roles are present.
    """
    resolved: dict[str, ResolvedDetectorContract] = {}
    unresolved: list[str] = []
    for contract in DETECTOR_ROLE_CONTRACTS:
        match = _resolve_detector_contract(dataset_root, contract)
        if match is None:
            unresolved.append(contract.role)
            continue
        resolved[contract.role] = match
    return resolved, unresolved


def empty_role_frame(role: str) -> pd.DataFrame:
    """Empty DataFrame carrying a role's canonical required columns.

    Used as the stand-in for an absent role so column reads in quality checks
    and detectors do not KeyError; detectors needing the role are skipped
    upstream via the available-roles set.
    """
    contract = CONTRACTS_BY_ROLE.get(role)
    columns = list(contract.required_columns) if contract else []
    return pd.DataFrame(columns=columns)


def _resolve_detector_contract(dataset_root: Path, contract: DetectorRoleContract) -> ResolvedDetectorContract | None:
    default_path = dataset_root / contract.default_relative_path
    if default_path.exists():
        columns, sheet_names = _load_preview(default_path)
        mapping = _match_columns(contract, columns)
        if contract.role == "cash_forecast" and _sheet_names_match(contract, sheet_names):
            return ResolvedDetectorContract(
                role=contract.role,
                attribute_name=contract.attribute_name,
                relative_path=contract.default_relative_path,
                required_columns=contract.required_columns,
                date_columns=contract.date_columns,
                resolution="default_path",
                column_mapping={},
                expected_sheet_names=contract.expected_sheet_names,
            )
        if mapping is not None:
            return ResolvedDetectorContract(
                role=contract.role,
                attribute_name=contract.attribute_name,
                relative_path=contract.default_relative_path,
                required_columns=contract.required_columns,
                date_columns=contract.date_columns,
                resolution="default_path",
                column_mapping=mapping,
                expected_sheet_names=contract.expected_sheet_names,
            )

    for candidate in _candidate_paths(dataset_root, contract):
        try:
            columns, sheet_names = _load_preview(candidate)
        except Exception:
            continue
        if contract.role == "cash_forecast":
            if not _sheet_names_match(contract, sheet_names):
                continue
            return ResolvedDetectorContract(
                role=contract.role,
                attribute_name=contract.attribute_name,
                relative_path=candidate.relative_to(dataset_root).as_posix(),
                required_columns=contract.required_columns,
                date_columns=contract.date_columns,
                resolution="discovered_by_sheet_names",
                column_mapping={},
                expected_sheet_names=contract.expected_sheet_names,
            )
        mapping = _match_columns(contract, columns)
        if mapping is None:
            continue
        return ResolvedDetectorContract(
            role=contract.role,
            attribute_name=contract.attribute_name,
            relative_path=candidate.relative_to(dataset_root).as_posix(),
            required_columns=contract.required_columns,
            date_columns=contract.date_columns,
            resolution="discovered_by_columns",
            column_mapping=mapping,
            expected_sheet_names=contract.expected_sheet_names,
        )
    return None


def load_structured_role(dataset_root: Path, resolved: ResolvedDetectorContract) -> pd.DataFrame | dict[str, pd.DataFrame]:
    path = dataset_root / resolved.relative_path
    if resolved.role == "cash_forecast":
        return pd.read_excel(path, sheet_name=None)
    if path.suffix.lower() == ".csv":
        frame = pd.read_csv(path)
    elif path.suffix.lower() == ".tsv":
        frame = pd.read_csv(path, sep="\t")
    elif path.suffix.lower() == ".json":
        frame = pd.read_json(path)
    else:
        frame = pd.read_excel(path)
    rename_map = {source: canonical for canonical, source in resolved.column_mapping.items()}
    out = frame.rename(columns=rename_map)
    ordered = [column for column in resolved.required_columns if column in out.columns]
    remainder = [column for column in out.columns if column not in ordered]
    return out.loc[:, ordered + remainder]
