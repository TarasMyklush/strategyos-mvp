from __future__ import annotations

import shutil
from pathlib import Path

from .paths import AGENT_INPUT_DIR, EVALUATION_DIR, SOURCE_DATASET


def prepare_agent_input(
    source_dataset: Path = SOURCE_DATASET,
    agent_input_dir: Path = AGENT_INPUT_DIR,
    evaluation_dir: Path = EVALUATION_DIR,
) -> tuple[Path, Path]:
    """Create separated runtime-visible analysis input and human-only evaluation folders."""
    if agent_input_dir.exists():
        shutil.rmtree(agent_input_dir)
    if evaluation_dir.exists():
        shutil.rmtree(evaluation_dir)
    agent_input_dir.mkdir(parents=True, exist_ok=True)
    evaluation_dir.mkdir(parents=True, exist_ok=True)

    for item in source_dataset.iterdir():
        if item.name == "README.md" or item.name.startswith("."):
            continue
        destination = agent_input_dir / item.name
        if item.is_dir():
            shutil.copytree(item, destination, ignore=shutil.ignore_patterns(".DS_Store"))
        else:
            shutil.copy2(item, destination)

    readme = source_dataset / "README.md"
    if readme.exists():
        shutil.copy2(readme, evaluation_dir / "HUMAN_ONLY_validation_readme.md")

    (agent_input_dir / "README_AGENT_INPUT.md").write_text(
        "StrategyOS runtime input pack for deterministic analysis. Validation answer keys and human-only notes are intentionally excluded.\n",
        encoding="utf-8",
    )
    (evaluation_dir / "README_HUMAN_ONLY.md").write_text(
        "Human-only evaluation material. Do not expose this folder to runtime processing or optional model review.\n",
        encoding="utf-8",
    )
    return agent_input_dir, evaluation_dir
