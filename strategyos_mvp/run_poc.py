from __future__ import annotations

import argparse
import json
from pathlib import Path

from .paths import AGENT_INPUT_DIR, DEFAULT_RUN_DIR, EVALUATION_DIR
from .prepare_inputs import prepare_agent_input
from .workflow import build_workflow


def main() -> None:
    parser = argparse.ArgumentParser(description="Run StrategyOS MVP POC workflow.")
    parser.add_argument("--dataset", type=Path, default=None, help="Dataset root. Defaults to sanitized agent input pack.")
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--skip-prepare", action="store_true", help="Use existing dataset path without preparing input/evaluation folders.")
    args = parser.parse_args()

    if args.skip_prepare:
        dataset = args.dataset or AGENT_INPUT_DIR
    else:
        agent_input, evaluation = prepare_agent_input()
        dataset = args.dataset or agent_input

    args.run_dir.mkdir(parents=True, exist_ok=True)
    workflow = build_workflow()
    result = workflow.invoke({"dataset_root": dataset, "run_dir": args.run_dir})

    summary = {
        "dataset": str(dataset),
        "run_dir": str(args.run_dir),
        "findings": len(result["findings"]),
        "locked_findings": sum(f.status == "locked" for f in result["findings"]),
        "total_recoverable_sar": round(sum(f.recoverable_sar for f in result["findings"]), 2),
        "artifacts": {k: str(v) for k, v in result["artifacts"].items()},
    }
    (args.run_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
