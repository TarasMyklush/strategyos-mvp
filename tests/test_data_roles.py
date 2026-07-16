from strategyos_mvp.data_roles import (
    DATA_ROLE_SPECS,
    document_target_folders,
    role_attribute_names,
    role_date_columns,
    role_labels,
    role_target_paths,
    run_model_required_roles,
    tabular_role_columns,
)
from strategyos_mvp.detector_contracts import DETECTOR_ROLE_CONTRACTS
from strategyos_mvp.source_pack import (
    DOCUMENT_TARGET_FOLDERS,
    ROLE_LABELS,
    ROLE_TARGET_PATHS,
    RUN_MODEL_REQUIRED_ROLES,
    TABULAR_ROLE_COLUMNS,
)


def test_data_role_registry_exposes_current_run_model_roles_in_order():
    assert [spec.role for spec in DATA_ROLE_SPECS] == [
        "ap_ledger",
        "ar_ledger",
        "gl_extract",
        "trial_balance",
        "vendor_master",
        "customer_master",
        "chart_of_accounts",
        "purchase_orders",
        "cash_forecast",
        "calendar",
        "revenue_plan",
        "bank_statement",
        "contract",
        "email_correspondence",
        "invoice_document",
    ]
    # revenue_plan is normalized into the run model but is NOT required to start
    # a run -- a dataset without an approved budget still runs and shows no plan.
    assert run_model_required_roles() == (
        "ap_ledger",
        "ar_ledger",
        "gl_extract",
        "trial_balance",
        "vendor_master",
        "customer_master",
        "chart_of_accounts",
        "purchase_orders",
        "cash_forecast",
    )


def test_legacy_source_pack_constants_are_registry_derived():
    assert ROLE_LABELS == role_labels()
    assert ROLE_TARGET_PATHS == role_target_paths()
    assert DOCUMENT_TARGET_FOLDERS == document_target_folders()
    assert RUN_MODEL_REQUIRED_ROLES == run_model_required_roles()
    assert TABULAR_ROLE_COLUMNS == tabular_role_columns()


def test_ingestion_and_detector_contracts_are_registry_derived():
    assert role_attribute_names()["ap_ledger"] == "ap"
    assert role_attribute_names()["chart_of_accounts"] == "coa"
    assert role_date_columns()["purchase_orders"] == ["PO_Date", "Delivery_Date"]

    contracts_by_role = {contract.role: contract for contract in DETECTOR_ROLE_CONTRACTS}
    assert contracts_by_role["ap_ledger"].default_relative_path == ROLE_TARGET_PATHS["ap_ledger"]
    assert contracts_by_role["ap_ledger"].attribute_name == "ap"
    assert contracts_by_role["cash_forecast"].expected_sheet_names == (
        "summary",
        "cash_position",
        "hedges",
        "vendor_cf_forecast",
        "notes",
    )


def test_revenue_plan_role_is_normalized_but_not_required():
    """The approved-plan role must reach the run model without gating a run.

    A plan file lands in the current-run-model directory so the finance engine
    can read it, but a dataset without one still runs and simply shows no plan
    comparison. This is the fix for a plan that classified as unclassified,
    never copied into the normalized model, so the dashboard said "unavailable".
    """
    from strategyos_mvp.data_roles import (
        run_model_role_specs,
        run_model_required_roles,
        role_target_paths,
    )

    plan = next((s for s in run_model_role_specs() if s.role == "revenue_plan"), None)
    assert plan is not None, "revenue_plan must be normalized into the run model"
    assert "revenue_plan" not in run_model_required_roles(), "a plan must never gate a run"
    assert role_target_paths().get("revenue_plan"), "the plan needs a normalize target path"
