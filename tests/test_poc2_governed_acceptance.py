from dataclasses import replace
import os
from pathlib import Path

import pytest

import strategyos_mvp.source_pack as source_pack_module
from strategyos_mvp.evidence import EvidenceStore
from strategyos_mvp.source_governance import (
    CONTROL_PLANE,
    EVALUATOR_ONLY,
    HISTORIC_CONTEXT,
    RESTRICTED_CONTEXT,
)


DEFAULT_POC2_ROOT = Path(
    "/Users/taras/Desktop/Taras/Sp soft/Enterprise OS/16.07.2026/StrategyOS POC-2"
)


def _poc2_root() -> Path:
    return Path(os.getenv("STRATEGYOS_POC2_ROOT", str(DEFAULT_POC2_ROOT))).expanduser().resolve()


@pytest.mark.skipif(not _poc2_root().exists(), reason="Exact POC-2 source pack is not available locally.")
def test_exact_poc2_pack_has_complete_governed_accounting(tmp_path: Path, monkeypatch):
    poc_root = _poc2_root()
    workspace_root = poc_root.parents[1]
    monkeypatch.setattr(
        source_pack_module,
        "CONFIG",
        replace(
            source_pack_module.CONFIG,
            workspace_root=workspace_root,
            poc_root=poc_root,
            source_dataset=poc_root / "01_Synthetic_Dataset",
            output_root=tmp_path / "outputs",
        ),
    )

    payload = source_pack_module.stage_source_pack_from_path(str(poc_root))
    manifest = {item["relative_path"]: item for item in payload["manifest"]}

    assert payload["manifest_summary"]["file_count"] == 81
    assert payload["manifest_summary"]["pending_extraction_count"] == 0
    assert sum(
        1
        for item in payload["manifest"]
        if item["file_type_hint"] == "pdf" and item["extraction_status"] == "ok"
    ) == 32
    assert payload["file_accounting"]["accounted_file_count"] == 81
    assert payload["file_accounting"]["silent_omission_count"] == 0
    assert payload["control_plane_registry"]["agent_definition_count"] == 2
    assert payload["control_plane_registry"]["task_specification_count"] == 1
    assert payload["control_plane_registry"]["evaluation_material_count"] == 1
    evaluator_entry = next(
        item
        for item in payload["control_plane_registry"]["entries"]
        if item["kind"] == "evaluation_material"
    )
    assert evaluator_entry["content_redacted"] is True
    assert evaluator_entry["headings"] == []

    expected_current_roles = {
        "ap_ledger": "01_Synthetic_Dataset/02_ERP_Extracts/AP_Invoices_H1_2026.xlsx",
        "ar_ledger": "01_Synthetic_Dataset/02_ERP_Extracts/AR_Invoices_H1_2026.xlsx",
        "gl_extract": "01_Synthetic_Dataset/02_ERP_Extracts/GL_Extract_H1_2026.csv",
        "trial_balance": "01_Synthetic_Dataset/02_ERP_Extracts/Trial_Balance_June_2026.xlsx",
        "chart_of_accounts": "01_Synthetic_Dataset/03_Master_Data/Chart_of_Accounts.xlsx",
        "customer_master": "01_Synthetic_Dataset/03_Master_Data/Customer_Master.xlsx",
        "vendor_master": "01_Synthetic_Dataset/03_Master_Data/Vendor_Master.xlsx",
        "purchase_orders": "01_Synthetic_Dataset/05_Purchase_Orders/PO_Log_H1_2026.csv",
        "cash_forecast": "01_Synthetic_Dataset/07_Cash_Forecast/CFO_Cash_Forecast_June_2026.xlsx",
    }
    for role, expected_path in expected_current_roles.items():
        current = [
            item["relative_path"]
            for item in payload["manifest"]
            if item["source_disposition"] == "current_evidence"
            and (item.get("classification") or {}).get("role") == role
        ]
        assert current == [expected_path]

    control_paths = {
        "02_Agent_JDs/Finance_Analyst_JD.md",
        "02_Agent_JDs/Finance_Auditor_JD.md",
        "03_Sample_Tasks/POC_Task_Brief.md",
    }
    for path in control_paths:
        assert manifest[path]["source_disposition"] == CONTROL_PLANE
        assert manifest[path]["classification"]["status"] == "excluded"
        assert manifest[path].get("normalized_path") is None
        assert Path(manifest[path]["governed_path"]).exists()

    readme = manifest["01_Synthetic_Dataset/README.md"]
    assert readme["source_disposition"] == EVALUATOR_ONLY
    assert readme.get("normalized_path") is None
    assert Path(readme["governed_path"]).exists()

    calendar = manifest[
        "01_Synthetic_Dataset/14_CEO_Office/CEO_Calendar_Mizan_Apr-Jul_2026.xlsx"
    ]
    assert calendar["source_disposition"] == RESTRICTED_CONTEXT
    assert "98_Restricted_Context" in calendar["classification"]["normalized_rel_path"]

    ambiguous_history = manifest[
        "01_Synthetic_Dataset/13_Historic_Correspondence/Email_4_BahrFreight_Invoice_Query_May_2024.txt"
    ]
    assert ambiguous_history["classification"]["status"] == "ambiguous"
    assert ambiguous_history["source_disposition"] == HISTORIC_CONTEXT
    assert ambiguous_history["processing_status"] == "indexed_historic_context"
    assert Path(ambiguous_history["normalized_path"]).exists()

    evidence = EvidenceStore.build(Path(payload["normalized_dataset_root"]))
    assert not any(path.startswith("98_Restricted_Context/") for path in evidence.manifest)
    assert not any("Finance_Analyst_JD.md" in path for path in evidence.manifest)
    assert any("Email_4_BahrFreight" in path for path in evidence.manifest)

    assert payload["task_readiness"]["ready_for_run"] is True
    assert payload["task_readiness"]["unconfirmed_roles"] == []
    assert payload["acceptance_readiness"]["status"] == "review_required"
    assert payload["acceptance_readiness"]["control_plane_evidence_leaks"] == []

    quality = payload["source_quality"]
    assert quality["inspected_workbook_count"] == 24
    formula_cells = {
        (item.get("sheet"), item.get("cell"))
        for item in quality["issues"]
        if item["severity"] == "high" and item.get("cell")
    }
    assert formula_cells == {
        ("Cash_Position", "G105"),
        ("Vendor_CF_Forecast", "D7"),
        ("Vendor_CF_Forecast", "I4"),
    }
    reconciliation_codes = {
        item["code"] for item in quality["issues"] if item["severity"] == "medium"
    }
    assert reconciliation_codes == {
        "gl_extract_debit_credit_imbalance",
        "trial_balance_debit_credit_imbalance",
    }
    evidence_conflict_codes = {
        item["code"]
        for item in quality["issues"]
        if item["severity"] == "high" and not item.get("cell")
    }
    assert evidence_conflict_codes == {
        "invoice_ledger_amount_conflict",
        "reference_vendor_identity_conflict",
    }
