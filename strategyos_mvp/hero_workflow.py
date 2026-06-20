from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from . import api as api_module
from . import auth as auth_module
from . import reviewer_runtime as reviewer_runtime_module
from . import run_poc as run_poc_module
from . import source_pack as source_pack_module
from . import state_store as state_store_module
from . import storage as storage_module
from .config import CONFIG, load_config


def _refresh_config() -> None:
    config = load_config()
    for module in (
        api_module,
        auth_module,
        reviewer_runtime_module,
        run_poc_module,
        source_pack_module,
        state_store_module,
        storage_module,
    ):
        module.CONFIG = config


def _auth_header(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _json_response(response: Any, *, step: str) -> dict[str, Any]:
    payload = response.json()
    if response.status_code >= 400:
        raise SystemExit(
            json.dumps(
                {
                    "step": step,
                    "status_code": response.status_code,
                    "payload": payload,
                },
                indent=2,
            )
        )
    return payload


def run_hero_workflow(dataset: Path, *, operator_api_key: str, reviewer_api_key: str) -> dict[str, Any]:
    _refresh_config()
    client = TestClient(api_module.app)
    operator_headers = _auth_header(operator_api_key)
    reviewer_headers = _auth_header(reviewer_api_key)

    stage = _json_response(
        client.post(
            "/source-packs/from-path",
            headers=operator_headers,
            json={"folder_path": str(dataset)},
        ),
        step="stage_source_pack",
    )
    source_pack_id = str(stage["source_pack_id"])

    created_run = _json_response(
        client.post(
            "/runs",
            headers=operator_headers,
            json={"source_pack_id": source_pack_id},
        ),
        step="create_run",
    )
    run_id = str(created_run["run_id"])

    claim = _json_response(
        client.post(f"/reviewer/runs/{run_id}/claim", headers=reviewer_headers),
        step="claim_review",
    )
    approval = _json_response(
        client.post(
            f"/reviewer/runs/{run_id}/approve",
            headers=reviewer_headers,
            json={"comment": "Approved for repeatable hero workflow validation."},
        ),
        step="approve_run",
    )
    resumed = _json_response(
        client.post(f"/operator/runs/{run_id}/resume", headers=operator_headers, json={}),
        step="resume_run",
    )

    findings = _json_response(
        client.get("/runs/latest/findings", headers=operator_headers),
        step="latest_findings",
    )
    top_finding = (findings.get("findings") or [None])[0]
    evidence = None
    if isinstance(top_finding, dict) and top_finding.get("finding_id"):
        evidence = _json_response(
            client.get(
                "/data/evidence-preview",
                headers=operator_headers,
                params={"run_id": run_id, "finding_id": top_finding["finding_id"]},
            ),
            step="evidence_preview",
        )

    case_file = _json_response(
        client.get(
            f"/reviewer/runs/{run_id}/artifacts/case_file",
            headers=operator_headers,
        ),
        step="case_file_preview",
    )
    qa = _json_response(
        client.get(
            f"/reviewer/runs/{run_id}/artifacts/qa",
            headers=operator_headers,
        ),
        step="qa_preview",
    )

    return {
        "dataset": str(dataset),
        "source_pack_id": source_pack_id,
        "task_readiness": stage.get("task_readiness"),
        "run": {
            "created": {
                "run_id": created_run.get("run_id"),
                "status": created_run.get("status"),
                "current_stage": created_run.get("current_stage"),
                "approval_status": created_run.get("approval_status"),
            },
            "claim": claim,
            "approval": approval,
            "resumed": {
                "run_id": resumed.get("run_id"),
                "status": resumed.get("status"),
                "current_stage": resumed.get("current_stage"),
                "approval_status": resumed.get("approval_status"),
                "artifacts": resumed.get("artifacts"),
            },
        },
        "findings": {
            "finding_count": findings.get("finding_count"),
            "total_recoverable_sar": findings.get("total_recoverable_sar"),
            "top_finding": top_finding,
        },
        "evidence_preview": evidence,
        "report_previews": {
            "case_file": {
                "path": case_file.get("path"),
                "preview_kind": case_file.get("preview_kind"),
                "preview_text": case_file.get("preview_text"),
            },
            "qa": {
                "path": qa.get("path"),
                "preview_kind": qa.get("preview_kind"),
                "preview_text": qa.get("preview_text"),
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the repeatable StrategyOS hero workflow through the API boundary."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=CONFIG.source_dataset,
        help="Dataset folder to stage via /source-packs/from-path.",
    )
    parser.add_argument(
        "--operator-api-key",
        default="operator-secret",
        help="Operator API key for local validation.",
    )
    parser.add_argument(
        "--reviewer-api-key",
        default="reviewer-secret",
        help="Reviewer API key for local validation.",
    )
    args = parser.parse_args()

    payload = run_hero_workflow(
        args.dataset.expanduser().resolve(),
        operator_api_key=args.operator_api_key,
        reviewer_api_key=args.reviewer_api_key,
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
