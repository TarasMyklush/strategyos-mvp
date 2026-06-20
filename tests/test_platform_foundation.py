import os
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
from strategyos_mvp.platform_foundation import (
    build_case_summary_contracts,
    build_domain_filter_contracts,
    build_ingestion_connector_catalog,
    build_run_report_contracts,
    build_surface_contract,
    build_switcher_contracts,
    principal_has_any_role,
)


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


def test_source_pack_stage_exposes_tenant_and_ingestion_contracts(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    output_root = tmp_path / "outputs"
    source_dir = workspace_root / "packs" / "demo"
    source_dir.mkdir(parents=True)
    pd.DataFrame(
        [{"Invoice_ID": "INV-1", "Vendor_ID": "V-1", "Amount_SAR": 10.0}]
    ).to_csv(source_dir / "ledger.csv", index=False)

    original = _apply_env(
        {
            "STRATEGYOS_API_AUTH_ENABLED": "true",
            "STRATEGYOS_OPERATOR_API_KEYS": "operator-secret",
            "STRATEGYOS_REVIEWER_API_KEYS": "reviewer-secret",
            "STRATEGYOS_TENANT_SLUG": "tenant-alpha",
            "STRATEGYOS_TENANT_NAME": "Tenant Alpha",
            "STRATEGYOS_WORKSPACE_ROOT": str(workspace_root),
            "STRATEGYOS_OUTPUT_ROOT": str(output_root),
        }
    )
    try:
        client = TestClient(api_module.app)
        response = client.post(
            "/source-packs/from-path",
            headers={"X-API-Key": "operator-secret"},
            json={"folder_path": str(source_dir)},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["tenant_context"] == {
            "tenant_id": "tenant-alpha",
            "tenant_name": "Tenant Alpha",
            "workspace_id": "tenant-alpha",
        }
        assert payload["ingestion_job"]["tenant_id"] == "tenant-alpha"
        assert payload["ingestion_job"]["connector"]["connector_id"] == "local.workspace_path"
        assert payload["ingestion_job"]["connector"]["kind"] == "workspace_path"
        assert payload["ingestion_job"]["metadata"]["source_pack_id"] == payload["source_pack_id"]
        assert payload["ingestion_job"]["source_ref"] == str(source_dir.resolve())
    finally:
        _restore_env(original)


def test_role_implication_supports_broader_tenant_model_direction():
    assert principal_has_any_role("tenant_admin", "operator") is True
    assert principal_has_any_role("tenant_admin", "reviewer") is True
    assert principal_has_any_role("auditor", "reviewer") is True
    assert principal_has_any_role("executive", "operator") is False


def test_ingestion_connector_catalog_marks_role_permissions():
    operator_catalog = build_ingestion_connector_catalog(principal_role="operator")
    reviewer_catalog = build_ingestion_connector_catalog(principal_role="reviewer")

    assert {item["kind"] for item in operator_catalog} == {
        "workspace_path",
        "browser_upload",
        "validated",
    }
    assert all(item["permitted"] is True for item in operator_catalog)
    assert all(item["permitted"] is False for item in reviewer_catalog)
    assert operator_catalog[0]["capabilities"]


def test_report_contracts_split_evidence_from_reports():
    contracts = build_run_report_contracts(
        {
            "case_file": "/tmp/Final consolidated case file.md",
            "citation_audit": "/tmp/StrategyOS Citation Audit.json",
            "knowledge_graph": "/tmp/StrategyOS Knowledge Graph.json",
        },
        tenant_id="tenant-alpha",
        run_id="run-123",
    )

    evidence_keys = {item.artifact_key for item in contracts.evidence}
    report_keys = {item.artifact_key for item in contracts.reports}

    assert evidence_keys == {"citation_audit"}
    assert report_keys == {"case_file", "knowledge_graph"}


def test_case_summary_contracts_normalize_findings_rows():
    contracts = build_case_summary_contracts(
        [
            {
                "finding_id": "F-001",
                "title": "Duplicate payment for invoice INV-1",
                "status": "approved",
                "confidence": "HIGH",
                "owner": "Tamween",
                "recoverable_sar": 1234.5,
                "citation_count": 3,
                "challenged": True,
                "pattern_label": "Duplicate payment",
            }
        ]
    )

    assert contracts[0].case_id == "F-001"
    assert contracts[0].recoverable_sar == 1234.5
    assert contracts[0].challenged is True


def test_surface_contract_builder_captures_route_and_audience():
    contract = build_surface_contract(
        surface_id="overview",
        title="Overview",
        visibility="protected",
        audience=("executive", "reviewer"),
        permitted=True,
        primary_route="/runs/latest",
        public_route="/public/runs/latest",
        actions=("view_summary",),
    )

    assert contract.surface_id == "overview"
    assert contract.public_route == "/public/runs/latest"
    assert contract.audience == ("executive", "reviewer")


def test_switcher_and_domain_filter_contracts_capture_routes_and_counts():
    switcher = build_switcher_contracts(
        options={"group": "Group CEO demo", "tenant-alpha": "Tenant Alpha"},
        active_id="tenant-alpha",
        route_builder=lambda option_id: f"/executive?company={option_id}",
    )
    filters = build_domain_filter_contracts(
        [
            {
                "finding_id": "F-1",
                "recoverable_sar": 1200,
                "citation_count": 2,
                "challenged": True,
                "classification": "CASH (recoverable now)",
            },
            {
                "finding_id": "F-2",
                "recoverable_sar": 400,
                "citation_count": 0,
                "challenged": False,
                "classification": "CASH (recoverable going-forward)",
            },
        ],
        active_filter_id="evidence_qa",
    )

    assert switcher[1].active is True
    assert switcher[1].route == "/executive?company=tenant-alpha"
    evidence_qa = next(item for item in filters if item.filter_id == "evidence_qa")
    assert evidence_qa.case_count == 1
    assert evidence_qa.active is True
    assert evidence_qa.route.endswith("domain=evidence_qa")
