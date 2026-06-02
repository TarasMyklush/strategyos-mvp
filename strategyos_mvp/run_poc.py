from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import CONFIG
from .paths import AGENT_INPUT_DIR, DEFAULT_RUN_DIR
from .prepare_inputs import prepare_agent_input
from .state_store import persist_run_summary
from .storage import sync_artifacts as sync_artifact_files
from .storage import sync_source_files
from .workflow import build_workflow


def run_strategyos_workflow(
    dataset: Path | None = None,
    run_dir: Path = DEFAULT_RUN_DIR,
    skip_prepare: bool = False,
    sync_artifacts: bool | None = None,
) -> dict:
    if skip_prepare:
        dataset_root = dataset or AGENT_INPUT_DIR
    else:
        agent_input, evaluation = prepare_agent_input()
        dataset_root = dataset or agent_input

    run_dir.mkdir(parents=True, exist_ok=True)
    workflow = build_workflow()
    result = workflow.invoke({"dataset_root": dataset_root, "run_dir": run_dir})

    summary = {
        "dataset": str(dataset_root),
        "run_dir": str(run_dir),
        "findings": len(result["findings"]),
        "locked_findings": sum(f.status == "locked" for f in result["findings"]),
        "total_recoverable_sar": round(sum(f.recoverable_sar for f in result["findings"]), 2),
        "artifacts": {k: str(v) for k, v in result["artifacts"].items()},
    }
    summary_path = run_dir / "run_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    do_sync = CONFIG.sync_artifacts if sync_artifacts is None else sync_artifacts
    if do_sync:
        uploaded = sync_artifact_files(run_dir, [Path(p) for p in summary["artifacts"].values()] + [summary_path])
        source_uploads = sync_source_files(dataset_root)
        summary["object_store_uploads"] = uploaded
        summary["source_uploads"] = source_uploads
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["state_store"] = persist_run_summary(summary)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run StrategyOS MVP POC workflow.")
    parser.add_argument("--dataset", type=Path, default=None, help="Dataset root. Defaults to sanitized agent input pack.")
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--skip-prepare", action="store_true", help="Use existing dataset path without preparing input/evaluation folders.")
    parser.add_argument("--sync-artifacts", action="store_true", help="Upload run artifacts to the configured S3-compatible object store.")
    args = parser.parse_args()

    summary = run_strategyos_workflow(
        dataset=args.dataset,
        run_dir=args.run_dir,
        skip_prepare=args.skip_prepare,
        sync_artifacts=args.sync_artifacts or None,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
