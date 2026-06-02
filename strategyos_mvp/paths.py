from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PACKAGE_ROOT.parent
POC_ROOT = WORKSPACE_ROOT / "strategy os" / "StrategyOS POC"
SOURCE_DATASET = POC_ROOT / "01_Synthetic_Dataset"
OUTPUT_ROOT = WORKSPACE_ROOT / "outputs"
DEFAULT_RUN_DIR = OUTPUT_ROOT / "StrategyOS MVP Run"
AGENT_INPUT_DIR = OUTPUT_ROOT / "StrategyOS Agent Input"
EVALUATION_DIR = OUTPUT_ROOT / "StrategyOS Evaluation"

