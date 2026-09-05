"""Run local tests without inheriting application credentials or active run paths."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    excluded_prefixes = (
        "STRATEGYOS_", "HATCHET_", "OPENAI_", "ANTHROPIC_", "DEEPSEEK_", "OAUTH2_",
    )
    excluded_keys = {"DATABASE_URL", "REDIS_URL", "NEO4J_URI", "QDRANT_URL"}
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(excluded_prefixes) and key not in excluded_keys
    }
    with tempfile.TemporaryDirectory(prefix="strategyos-tests-") as directory:
        env.update({
            "STRATEGYOS_WORKSPACE_ROOT": directory,
            "STRATEGYOS_OUTPUT_ROOT": str(Path(directory) / "outputs"),
            "STRATEGYOS_SOURCE_DATASET": str(repo / "tests/fixtures/01_Synthetic_Dataset"),
            "STRATEGYOS_POC_ROOT": str(repo / "tests/fixtures"),
            "STRATEGYOS_TWINS_DATA_DIR": str(Path(directory) / "twins"),
            "STRATEGYOS_TWINS_RUNTIME_DATA_DIR": str(Path(directory) / "twins-runtime"),
        })
        return subprocess.call(
            [sys.executable, "-m", "pytest", *(sys.argv[1:] or ["-q"])],
            cwd=repo, env=env,
        )


if __name__ == "__main__":
    raise SystemExit(main())
