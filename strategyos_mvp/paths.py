from __future__ import annotations

from pathlib import Path

from .config import CONFIG, PACKAGE_ROOT

WORKSPACE_ROOT: Path = CONFIG.workspace_root
POC_ROOT: Path = CONFIG.poc_root
SOURCE_DATASET: Path = CONFIG.source_dataset
OUTPUT_ROOT: Path = CONFIG.output_root
DEFAULT_RUN_DIR: Path = CONFIG.default_run_dir
AGENT_INPUT_DIR: Path = CONFIG.agent_input_dir
EVALUATION_DIR: Path = CONFIG.evaluation_dir
