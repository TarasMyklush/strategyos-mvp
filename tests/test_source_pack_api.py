import os
import shutil
from pathlib import Path

from fastapi.testclient import TestClient
import pandas as pd

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
import strategyos_mvp.run_poc as run_poc_module
import strategyos_mvp.source_pack as source_pack_module
import strategyos_mvp.state_store as state_store
import strategyos_mvp.storage as storage
from strategyos_mvp.config import load_config


def _apply_env(env_updates: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in env_updates}
    for key, value in env_updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    api_module.CONFIG = config
    auth_module.CONFIG = config
    run_poc_module.CONFIG = config
    source_pack_module.CONFIG = config
    state_store.CONFIG = config
    storage.CONFIG = config
    return original


def _restore_env(original: dict[str, str | None]):
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    api_module.CONFIG = config
    auth_module.CONFIG = config
    run_poc_module.CONFIG = config
    source_pack_module.CONFIG = config
    state_store.CONFIG = config
    storage.CONFIG = config


def _auth_header(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def test_source_pack_from_path_returns_manifest_and_readiness(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    output_root = tmp_path / "outputs"
    source_dir = workspace_root / "packs" / "demo"
    source_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "Invoice_ID": "INV-1",
                "Vendor_ID": "V-1",
                "Amount_SAR": 100.0,
                "Payment_Date": "2026-01-01",
                "PO_Reference": "PO-1",
            }
        ]
    ).to_excel(source_dir / "finance.xlsx", index=False)
    (source_dir / "notes.pdf").write_bytes(b"%PDF-1.4 fake")
    (source_dir / "ignore.exe").write_bytes(b"binary")

    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_WORKSPACE_ROOT": str(workspace_root),
            "STRATEGYOS_OUTPUT_ROOT": str(output_root),
        }
    )
    try:
        client = TestClient(api_module.app)

        response = client.post(
            "/source-packs/from-path",
            headers=_auth_header("operator-secret"),
            json={"folder_path": str(source_dir)},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["source_kind"] == "workspace_path"
        assert payload["manifest_summary"]["file_count"] == 3
        assert payload["manifest_summary"]["supported_file_count"] == 2
        assert payload["manifest_summary"]["unsupported_file_count"] == 1
        manifest_by_path = {item["relative_path"]: item for item in payload["manifest"]}
        assert manifest_by_path["finance.xlsx"]["file_type_hint"] == "spreadsheet"
        assert manifest_by_path["finance.xlsx"]["classification"]["role"] == "ap_ledger"
        assert manifest_by_path["notes.pdf"]["extraction_status"] == "failed"
        assert manifest_by_path["notes.pdf"]["text_extraction"]["failure_reason"]
        assert manifest_by_path["ignore.exe"]["supported"] is False
        assert payload["task_readiness"]["status"] == "partial"
        assert payload["validation"]["status"] == "partial"
    finally:
        _restore_env(original)


def test_source_pack_from_path_rejects_outside_workspace(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    output_root = tmp_path / "outputs"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir(parents=True)

    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_WORKSPACE_ROOT": str(workspace_root),
            "STRATEGYOS_OUTPUT_ROOT": str(output_root),
        }
    )
    try:
        client = TestClient(api_module.app)

        response = client.post(
            "/source-packs/from-path",
            headers=_auth_header("operator-secret"),
            json={"folder_path": str(outside_dir)},
        )

        assert response.status_code == 400
        assert "workspace boundary" in response.json()["detail"]
    finally:
        _restore_env(original)


def test_source_pack_upload_preserves_relative_paths_and_support_flags(tmp_path: Path):
    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_WORKSPACE_ROOT": str(tmp_path / "workspace"),
            "STRATEGYOS_OUTPUT_ROOT": str(tmp_path / "outputs"),
        }
    )
    try:
        client = TestClient(api_module.app)

        response = client.post(
            "/source-packs",
            headers=_auth_header("operator-secret"),
            files=[
                ("files", ("folder/AP/report.csv", b"a,b\n1,2\n", "text/csv")),
                ("files", ("folder/docs/scan.png", b"png-binary", "image/png")),
                ("files", ("folder/bin/tool.bin", b"bin", "application/octet-stream")),
            ],
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["source_kind"] == "browser_upload"
        manifest_paths = [item["relative_path"] for item in payload["manifest"]]
        assert "folder/AP/report.csv" in manifest_paths
        assert "folder/docs/scan.png" in manifest_paths
        assert "folder/bin/tool.bin" in manifest_paths
        manifest_by_path = {item["relative_path"]: item for item in payload["manifest"]}
        assert manifest_by_path["folder/docs/scan.png"]["extraction_status"] == "failed"
        assert manifest_by_path["folder/docs/scan.png"]["text_extraction"]["failure_reason"]
        assert manifest_by_path["folder/bin/tool.bin"]["supported"] is False

        validate_response = client.post(
            "/source-packs/validate",
            headers=_auth_header("operator-secret"),
            json={"source_pack_id": payload["source_pack_id"]},
        )
        assert validate_response.status_code == 200
        assert validate_response.json()["source_pack_id"] == payload["source_pack_id"]
    finally:
        _restore_env(original)


def test_source_pack_classification_and_run_creation_execute_end_to_end(tmp_path: Path):
    source_dataset = load_config().source_dataset
    workspace_root = tmp_path / "workspace"
    output_root = tmp_path / "outputs"
    staged_root = workspace_root / "packs" / "renamed-pack"
    staged_root.mkdir(parents=True)

    renamed_files = {
        source_dataset / "02_ERP_Extracts" / "AP_Invoices_H1_2026.xlsx": staged_root / "alpha.xlsx",
        source_dataset / "02_ERP_Extracts" / "AR_Invoices_H1_2026.xlsx": staged_root / "beta.xlsx",
        source_dataset / "02_ERP_Extracts" / "GL_Extract_H1_2026.csv": staged_root / "gamma.csv",
        source_dataset / "02_ERP_Extracts" / "Trial_Balance_June_2026.xlsx": staged_root / "delta.xlsx",
        source_dataset / "03_Master_Data" / "Vendor_Master.xlsx": staged_root / "epsilon.xlsx",
        source_dataset / "03_Master_Data" / "Customer_Master.xlsx": staged_root / "zeta.xlsx",
        source_dataset / "03_Master_Data" / "Chart_of_Accounts.xlsx": staged_root / "eta.xlsx",
        source_dataset / "05_Purchase_Orders" / "PO_Log_H1_2026.csv": staged_root / "theta.csv",
        source_dataset / "07_Cash_Forecast" / "CFO_Cash_Forecast_June_2026.xlsx": staged_root / "iota.xlsx",
    }
    for source, destination in renamed_files.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    (staged_root / "docs").mkdir(exist_ok=True)
    (staged_root / "mail").mkdir(exist_ok=True)
    (staged_root / "docs" / "opaque-document.txt").write_text(
        "Invoice Number: INV-2026-1404\nBill To: Tamween Distribution Co.\nAmount Due: SAR 21,793.20\n",
        encoding="utf-8",
    )
    (staged_root / "mail" / "thread.txt").write_text(
        "From: treasury@tamween.sa\nSubject: Bordeaux Wines payment follow-up\nDear team, please confirm settlement status.\nRegards, Treasury\n",
        encoding="utf-8",
    )

    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_WORKSPACE_ROOT": str(workspace_root),
            "STRATEGYOS_OUTPUT_ROOT": str(output_root),
            "STRATEGYOS_SOURCE_DATASET": str(source_dataset),
            "STRATEGYOS_REQUIRE_HUMAN_REVIEW": "false",
        }
    )
    try:
        client = TestClient(api_module.app)
        staged = client.post(
            "/source-packs/from-path",
            headers=_auth_header("operator-secret"),
            json={"folder_path": str(staged_root)},
        )

        assert staged.status_code == 200
        payload = staged.json()
        assert payload["task_readiness"]["ready_for_run"] is True
        assert payload["validation"]["status"] == "ready"

        normalized_root = Path(payload["normalized_dataset_root"])
        assert (normalized_root / "02_ERP_Extracts" / "AP_Invoices_H1_2026.xlsx").exists()
        assert (normalized_root / "02_ERP_Extracts" / "AR_Invoices_H1_2026.xlsx").exists()
        assert (normalized_root / "02_ERP_Extracts" / "GL_Extract_H1_2026.csv").exists()
        assert (normalized_root / "02_ERP_Extracts" / "Trial_Balance_June_2026.xlsx").exists()
        assert (normalized_root / "03_Master_Data" / "Vendor_Master.xlsx").exists()
        assert (normalized_root / "03_Master_Data" / "Customer_Master.xlsx").exists()
        assert (normalized_root / "03_Master_Data" / "Chart_of_Accounts.xlsx").exists()
        assert (normalized_root / "05_Purchase_Orders" / "PO_Log_H1_2026.csv").exists()
        assert (normalized_root / "07_Cash_Forecast" / "CFO_Cash_Forecast_June_2026.xlsx").exists()

        manifest_by_path = {item["relative_path"]: item for item in payload["manifest"]}
        assert manifest_by_path["docs/opaque-document.txt"]["classification"]["role"] == "invoice_document"
        assert manifest_by_path["mail/thread.txt"]["classification"]["role"] == "email_correspondence"

        run_response = client.post(
            "/runs",
            headers=_auth_header("operator-secret"),
            json={"source_pack_id": payload["source_pack_id"]},
        )

        assert run_response.status_code == 200
        summary = run_response.json()
        assert summary["source_pack_id"] == payload["source_pack_id"]
        assert summary["status"] == "completed"
        assert summary["source_pack"]["source_pack_id"] == payload["source_pack_id"]
        for artifact_key in ["case_file", "case_file_pdf", "working_capital", "qa", "knowledge_graph"]:
            assert Path(summary["artifacts"][artifact_key]).exists()
    finally:
        _restore_env(original)


def test_source_pack_candidate_mapping_can_be_confirmed_and_canonicalized(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    output_root = tmp_path / "outputs"
    workspace_root.mkdir()
    output_root.mkdir()

    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_WORKSPACE_ROOT": str(workspace_root),
            "STRATEGYOS_OUTPUT_ROOT": str(output_root),
        }
    )
    try:
        client = TestClient(api_module.app)
        response = client.post(
            "/source-packs",
            headers=_auth_header("operator-secret"),
            files=[
                (
                    "files",
                    (
                        "folder/ap-alias.csv",
                        b"Invoice No,Supplier ID,Amount (SAR),Settlement Date,PO Ref\nINV-1,V-1,100,2026-01-01,PO-1\n",
                        "text/csv",
                    ),
                )
            ],
        )

        assert response.status_code == 200
        payload = response.json()
        source = payload["manifest"][0]
        assert source["classification"]["status"] == "candidate"
        assert source["classification"]["role"] == "ap_ledger"
        assert source["classification"]["column_mapping_proposal"]["column_mapping"] == {
            "Amount_SAR": "Amount (SAR)",
            "Invoice_ID": "Invoice No",
            "PO_Reference": "PO Ref",
            "Payment_Date": "Settlement Date",
            "Vendor_ID": "Supplier ID",
        }

        confirmed = client.post(
            "/source-packs/confirm-mapping",
            headers=_auth_header("operator-secret"),
            json={
                "source_pack_id": payload["source_pack_id"],
                "relative_path": source["relative_path"],
            },
        )

        assert confirmed.status_code == 200
        confirmed_source = confirmed.json()["manifest"][0]
        assert confirmed_source["classification"]["status"] == "classified"
        normalized = Path(confirmed.json()["normalized_dataset_root"]) / "02_ERP_Extracts" / "AP_Invoices_H1_2026.xlsx"
        assert normalized.exists()
        frame = pd.read_excel(normalized)
        assert ["Invoice_ID", "Vendor_ID", "Amount_SAR", "Payment_Date", "PO_Reference"] == list(frame.columns[:5])
    finally:
        _restore_env(original)


def test_partial_source_pack_run_uses_baseline_fill_and_labels_summary(tmp_path: Path):
    source_dataset = load_config().source_dataset
    workspace_root = tmp_path / "workspace"
    output_root = tmp_path / "outputs"
    staged_root = workspace_root / "packs" / "partial-pack"
    staged_root.mkdir(parents=True)
    shutil.copy2(
        source_dataset / "02_ERP_Extracts" / "AP_Invoices_H1_2026.xlsx",
        staged_root / "only-ap.xlsx",
    )

    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_WORKSPACE_ROOT": str(workspace_root),
            "STRATEGYOS_OUTPUT_ROOT": str(output_root),
            "STRATEGYOS_SOURCE_DATASET": str(source_dataset),
            "STRATEGYOS_REQUIRE_HUMAN_REVIEW": "false",
        }
    )
    try:
        client = TestClient(api_module.app)
        staged = client.post(
            "/source-packs/from-path",
            headers=_auth_header("operator-secret"),
            json={"folder_path": str(staged_root)},
        )
        assert staged.status_code == 200
        assert staged.json()["task_readiness"]["ready_for_run"] is False

        run_response = client.post(
            "/runs",
            headers=_auth_header("operator-secret"),
            json={
                "source_pack_id": staged.json()["source_pack_id"],
                "allow_partial_source_pack": True,
                "sync_artifacts": False,
            },
        )

        assert run_response.status_code == 200
        summary = run_response.json()
        assert summary["source_pack"]["run_resolution"]["run_mode"] == "partial"
        assert "ar_ledger" in summary["source_pack"]["run_resolution"]["baseline_fallback_roles"]
        assert summary["status"] == "completed"
    finally:
        _restore_env(original)
