from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


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


DETECTOR_ROLE_CONTRACTS: tuple[DetectorRoleContract, ...] = (
    DetectorRoleContract(
        role="ap_ledger",
        attribute_name="ap",
        default_relative_path="02_ERP_Extracts/AP_Invoices_H1_2026.xlsx",
        required_columns=("Invoice_ID", "Vendor_ID", "Amount_SAR", "Payment_Date", "PO_Reference"),
        date_columns=("Invoice_Date", "Due_Date", "Payment_Date"),
        column_aliases={
            "Invoice_ID": ("invoice id", "invoice number", "invoice no", "invoice #", "inv #"),
            "Vendor_ID": ("vendor id", "supplier id", "supplier code"),
            "Amount_SAR": ("amount sar", "amount (sar)", "invoice amount", "gross amount"),
            "Payment_Date": ("payment date", "settlement date", "paid date"),
            "PO_Reference": ("po reference", "po ref", "po number", "purchase order"),
        },
    ),
    DetectorRoleContract(
        role="ar_ledger",
        attribute_name="ar",
        default_relative_path="02_ERP_Extracts/AR_Invoices_H1_2026.xlsx",
        required_columns=("Invoice_ID", "Customer_ID", "Amount_SAR", "Collection_Date"),
        date_columns=("Invoice_Date", "Due_Date", "Collection_Date"),
        column_aliases={
            "Invoice_ID": ("invoice id", "invoice number", "invoice no", "invoice #"),
            "Customer_ID": ("customer id", "customer code", "client id"),
            "Amount_SAR": ("amount sar", "amount (sar)", "invoice amount"),
            "Collection_Date": ("collection date", "receipt date", "settlement date"),
        },
    ),
    DetectorRoleContract(
        role="gl_extract",
        attribute_name="gl",
        default_relative_path="02_ERP_Extracts/GL_Extract_H1_2026.csv",
        required_columns=("Date", "Account", "Debit", "Credit", "Reference"),
        date_columns=("Date",),
        column_aliases={
            "Date": ("posting date", "entry date", "gl date"),
            "Account": ("account code", "gl account"),
            "Debit": ("debit amount",),
            "Credit": ("credit amount",),
            "Reference": ("document reference", "memo reference", "journal reference"),
        },
    ),
    DetectorRoleContract(
        role="trial_balance",
        attribute_name="trial_balance",
        default_relative_path="02_ERP_Extracts/Trial_Balance_June_2026.xlsx",
        required_columns=("Account", "Debit_Total", "Credit_Total", "Net"),
        column_aliases={
            "Account": ("account code", "gl account"),
            "Debit_Total": ("debit total", "total debit"),
            "Credit_Total": ("credit total", "total credit"),
            "Net": ("net balance", "closing net"),
        },
    ),
    DetectorRoleContract(
        role="vendor_master",
        attribute_name="vendors",
        default_relative_path="03_Master_Data/Vendor_Master.xlsx",
        required_columns=("Vendor_ID", "Vendor_Name", "Tax_ID", "Bank_Account"),
        date_columns=("Created_Date",),
        column_aliases={
            "Vendor_ID": ("vendor id", "supplier id", "supplier code"),
            "Vendor_Name": ("vendor name", "supplier name"),
            "Tax_ID": ("tax id", "vat id", "tax registration number"),
            "Bank_Account": ("bank account", "iban", "bank account number"),
        },
    ),
    DetectorRoleContract(
        role="customer_master",
        attribute_name="customers",
        default_relative_path="03_Master_Data/Customer_Master.xlsx",
        required_columns=("Customer_ID", "Customer_Name", "Credit_Limit_SAR", "Payment_Terms"),
        column_aliases={
            "Customer_ID": ("customer id", "customer code", "client id"),
            "Customer_Name": ("customer name", "client name"),
            "Credit_Limit_SAR": ("credit limit sar", "credit limit", "customer limit sar"),
            "Payment_Terms": ("payment terms", "terms"),
        },
    ),
    DetectorRoleContract(
        role="chart_of_accounts",
        attribute_name="coa",
        default_relative_path="03_Master_Data/Chart_of_Accounts.xlsx",
        required_columns=("Account", "Account_Description", "Type", "Normal_Balance"),
        column_aliases={
            "Account": ("account code", "gl account"),
            "Account_Description": ("account description", "description"),
            "Type": ("account type",),
            "Normal_Balance": ("normal balance", "balance side"),
        },
    ),
    DetectorRoleContract(
        role="purchase_orders",
        attribute_name="po",
        default_relative_path="05_Purchase_Orders/PO_Log_H1_2026.csv",
        required_columns=("PO_ID", "Vendor_ID", "SKU", "Unit_Price", "Total"),
        date_columns=("PO_Date", "Delivery_Date"),
        column_aliases={
            "PO_ID": ("po id", "purchase order id", "po number"),
            "Vendor_ID": ("vendor id", "supplier id", "supplier code"),
            "SKU": ("sku code", "item sku", "item code"),
            "Unit_Price": ("unit price", "price per unit"),
            "Total": ("po total", "line total", "total amount"),
        },
    ),
    DetectorRoleContract(
        role="cash_forecast",
        attribute_name="cash_forecast",
        default_relative_path="07_Cash_Forecast/CFO_Cash_Forecast_June_2026.xlsx",
        expected_sheet_names=("summary", "cash_position", "hedges", "vendor_cf_forecast", "notes"),
    ),
)


CONTRACTS_BY_ROLE = {contract.role: contract for contract in DETECTOR_ROLE_CONTRACTS}


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
    for path in sorted(dataset_root.rglob("*")):
        if not path.is_file() or path == default_path:
            continue
        if path.suffix.lower() not in {".csv", ".tsv", ".json", ".xls", ".xlsx"}:
            continue
        candidates.append(path)
    return candidates


def resolve_detector_contracts(dataset_root: Path) -> dict[str, ResolvedDetectorContract]:
    resolved: dict[str, ResolvedDetectorContract] = {}
    for contract in DETECTOR_ROLE_CONTRACTS:
        match = _resolve_detector_contract(dataset_root, contract)
        if match is None:
            raise FileNotFoundError(
                f"Could not resolve detector data contract for role '{contract.role}' under '{dataset_root}'."
            )
        resolved[contract.role] = match
    return resolved


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
