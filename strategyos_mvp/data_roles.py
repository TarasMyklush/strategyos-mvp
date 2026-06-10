from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


DataRoleKind = Literal["structured", "document"]


@dataclass(frozen=True)
class DataRoleSpec:
    role: str
    label: str
    kind: DataRoleKind
    attribute_name: str | None = None
    target_path: str | None = None
    target_folder: str | None = None
    required_columns: tuple[str, ...] = ()
    date_columns: tuple[str, ...] = ()
    column_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    expected_sheet_names: tuple[str, ...] = ()


DATA_ROLE_SPECS: tuple[DataRoleSpec, ...] = (
    DataRoleSpec(
        role="ap_ledger",
        label="AP invoice ledger",
        kind="structured",
        attribute_name="ap",
        target_path="02_ERP_Extracts/AP_Invoices_H1_2026.xlsx",
        required_columns=(
            "Invoice_ID",
            "Vendor_ID",
            "Amount_SAR",
            "Payment_Date",
            "PO_Reference",
        ),
        date_columns=("Invoice_Date", "Due_Date", "Payment_Date"),
        column_aliases={
            "Invoice_ID": (
                "invoice id",
                "invoice number",
                "invoice no",
                "invoice #",
                "inv #",
            ),
            "Vendor_ID": ("vendor id", "supplier id", "supplier code"),
            "Amount_SAR": (
                "amount sar",
                "amount (sar)",
                "invoice amount",
                "gross amount",
            ),
            "Payment_Date": ("payment date", "settlement date", "paid date"),
            "PO_Reference": ("po reference", "po ref", "po number", "purchase order"),
        },
    ),
    DataRoleSpec(
        role="ar_ledger",
        label="AR invoice ledger",
        kind="structured",
        attribute_name="ar",
        target_path="02_ERP_Extracts/AR_Invoices_H1_2026.xlsx",
        required_columns=("Invoice_ID", "Customer_ID", "Amount_SAR", "Collection_Date"),
        date_columns=("Invoice_Date", "Due_Date", "Collection_Date"),
        column_aliases={
            "Invoice_ID": ("invoice id", "invoice number", "invoice no", "invoice #"),
            "Customer_ID": ("customer id", "customer code", "client id"),
            "Amount_SAR": ("amount sar", "amount (sar)", "invoice amount"),
            "Collection_Date": ("collection date", "receipt date", "settlement date"),
        },
    ),
    DataRoleSpec(
        role="gl_extract",
        label="GL extract",
        kind="structured",
        attribute_name="gl",
        target_path="02_ERP_Extracts/GL_Extract_H1_2026.csv",
        required_columns=("Date", "Account", "Debit", "Credit", "Reference"),
        date_columns=("Date",),
        column_aliases={
            "Date": ("posting date", "entry date", "gl date"),
            "Account": ("account code", "gl account"),
            "Debit": ("debit amount",),
            "Credit": ("credit amount",),
            "Reference": (
                "document reference",
                "memo reference",
                "journal reference",
            ),
        },
    ),
    DataRoleSpec(
        role="trial_balance",
        label="Trial balance",
        kind="structured",
        attribute_name="trial_balance",
        target_path="02_ERP_Extracts/Trial_Balance_June_2026.xlsx",
        required_columns=("Account", "Debit_Total", "Credit_Total", "Net"),
        column_aliases={
            "Account": ("account code", "gl account"),
            "Debit_Total": ("debit total", "total debit"),
            "Credit_Total": ("credit total", "total credit"),
            "Net": ("net balance", "closing net"),
        },
    ),
    DataRoleSpec(
        role="vendor_master",
        label="Vendor master",
        kind="structured",
        attribute_name="vendors",
        target_path="03_Master_Data/Vendor_Master.xlsx",
        required_columns=("Vendor_ID", "Vendor_Name", "Tax_ID", "Bank_Account"),
        date_columns=("Created_Date",),
        column_aliases={
            "Vendor_ID": ("vendor id", "supplier id", "supplier code"),
            "Vendor_Name": ("vendor name", "supplier name"),
            "Tax_ID": ("tax id", "vat id", "tax registration number"),
            "Bank_Account": ("bank account", "iban", "bank account number"),
        },
    ),
    DataRoleSpec(
        role="customer_master",
        label="Customer master",
        kind="structured",
        attribute_name="customers",
        target_path="03_Master_Data/Customer_Master.xlsx",
        required_columns=(
            "Customer_ID",
            "Customer_Name",
            "Credit_Limit_SAR",
            "Payment_Terms",
        ),
        column_aliases={
            "Customer_ID": ("customer id", "customer code", "client id"),
            "Customer_Name": ("customer name", "client name"),
            "Credit_Limit_SAR": (
                "credit limit sar",
                "credit limit",
                "customer limit sar",
            ),
            "Payment_Terms": ("payment terms", "terms"),
        },
    ),
    DataRoleSpec(
        role="chart_of_accounts",
        label="Chart of accounts",
        kind="structured",
        attribute_name="coa",
        target_path="03_Master_Data/Chart_of_Accounts.xlsx",
        required_columns=(
            "Account",
            "Account_Description",
            "Type",
            "Normal_Balance",
        ),
        column_aliases={
            "Account": ("account code", "gl account"),
            "Account_Description": ("account description", "description"),
            "Type": ("account type",),
            "Normal_Balance": ("normal balance", "balance side"),
        },
    ),
    DataRoleSpec(
        role="purchase_orders",
        label="Purchase orders",
        kind="structured",
        attribute_name="po",
        target_path="05_Purchase_Orders/PO_Log_H1_2026.csv",
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
    DataRoleSpec(
        role="cash_forecast",
        label="Cash forecast workbook",
        kind="structured",
        attribute_name="cash_forecast",
        target_path="07_Cash_Forecast/CFO_Cash_Forecast_June_2026.xlsx",
        expected_sheet_names=(
            "summary",
            "cash_position",
            "hedges",
            "vendor_cf_forecast",
            "notes",
        ),
    ),
    DataRoleSpec(
        role="bank_statement",
        label="Bank statement",
        kind="document",
        target_folder="01_Bank_Statements",
    ),
    DataRoleSpec(
        role="contract",
        label="Contract",
        kind="document",
        target_folder="04_Contracts",
    ),
    DataRoleSpec(
        role="email_correspondence",
        label="Email correspondence",
        kind="document",
        target_folder="06_Email_Correspondence",
    ),
    DataRoleSpec(
        role="invoice_document",
        label="Invoice document",
        kind="document",
        target_folder="08_Invoices",
    ),
)


_DATA_ROLE_REGISTRY: dict[str, DataRoleSpec] = {
    spec.role: spec for spec in DATA_ROLE_SPECS
}


def register_data_role(spec: DataRoleSpec) -> DataRoleSpec:
    existing = _DATA_ROLE_REGISTRY.get(spec.role)
    if existing is not None and existing != spec:
        raise ValueError(f"Data role '{spec.role}' is already registered.")
    _DATA_ROLE_REGISTRY[spec.role] = spec
    return spec


def registered_data_role_specs() -> tuple[DataRoleSpec, ...]:
    return tuple(_DATA_ROLE_REGISTRY.values())


def run_model_role_specs() -> tuple[DataRoleSpec, ...]:
    return tuple(
        spec
        for spec in registered_data_role_specs()
        if spec.kind == "structured" and spec.target_path
    )


def tabular_role_specs() -> tuple[DataRoleSpec, ...]:
    return tuple(spec for spec in run_model_role_specs() if spec.required_columns)


def document_role_specs() -> tuple[DataRoleSpec, ...]:
    return tuple(
        spec for spec in registered_data_role_specs() if spec.kind == "document"
    )


DATA_ROLES_BY_KEY = _DATA_ROLE_REGISTRY
RUN_MODEL_ROLE_SPECS = run_model_role_specs()
TABULAR_ROLE_SPECS = tabular_role_specs()
DOCUMENT_ROLE_SPECS = document_role_specs()


def data_role(role: str) -> DataRoleSpec:
    return _DATA_ROLE_REGISTRY[str(role)]


def role_labels() -> dict[str, str]:
    return {spec.role: spec.label for spec in registered_data_role_specs()}


def role_target_paths() -> dict[str, str]:
    return {
        spec.role: str(spec.target_path)
        for spec in run_model_role_specs()
        if spec.target_path is not None
    }


def document_target_folders() -> dict[str, str]:
    return {
        spec.role: str(spec.target_folder)
        for spec in document_role_specs()
        if spec.target_folder is not None
    }


def run_model_required_roles() -> tuple[str, ...]:
    return tuple(spec.role for spec in run_model_role_specs())


def tabular_role_columns() -> dict[str, tuple[str, ...]]:
    return {spec.role: spec.required_columns for spec in tabular_role_specs()}


def tabular_role_aliases() -> dict[str, dict[str, tuple[str, ...]]]:
    return {spec.role: dict(spec.column_aliases) for spec in tabular_role_specs()}


def role_attribute_names() -> dict[str, str]:
    return {
        spec.role: str(spec.attribute_name)
        for spec in run_model_role_specs()
        if spec.attribute_name is not None
    }


def role_date_columns() -> dict[str, list[str]]:
    return {
        spec.role: list(spec.date_columns)
        for spec in run_model_role_specs()
        if spec.date_columns
    }


def cash_forecast_sheet_names() -> set[str]:
    return set(data_role("cash_forecast").expected_sheet_names)
