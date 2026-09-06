"""Run local tests without inheriting application credentials or active run paths."""
from pathlib import Path
import os
import shutil
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
    args = list(sys.argv[1:])
    if "--services" in args:
        args.remove("--services")
        for key in ("STRATEGYOS_POSTGRES_E2E_DATABASE_URL", "STRATEGYOS_NEO4J_E2E_URI", "STRATEGYOS_NEO4J_E2E_USER", "STRATEGYOS_NEO4J_E2E_PASSWORD", "STRATEGYOS_QDRANT_E2E_URL", "STRATEGYOS_EMBEDDING_E2E_MODEL_PATH"):
            if os.environ.get(key):
                env[key] = os.environ[key]
        if not env.get("STRATEGYOS_POSTGRES_E2E_DATABASE_URL") or not env.get("STRATEGYOS_NEO4J_E2E_URI"):
            raise SystemExit("--services requires dedicated Postgres and Neo4j proof endpoints.")
    with tempfile.TemporaryDirectory(prefix="strategyos-tests-") as directory:
        for name in ("outputs", "twins", "twins-runtime"):
            (Path(directory) / name).mkdir()
        env.update({
            "STRATEGYOS_WORKSPACE_ROOT": directory,
            "STRATEGYOS_OUTPUT_ROOT": str(Path(directory) / "outputs"),
            "STRATEGYOS_SOURCE_DATASET": str(repo / "tests/fixtures/01_Synthetic_Dataset"),
            "STRATEGYOS_POC_ROOT": str(repo / "tests/fixtures"),
            "STRATEGYOS_TWINS_DATA_DIR": str(Path(directory) / "twins"),
            "STRATEGYOS_TWINS_RUNTIME_DATA_DIR": str(Path(directory) / "twins-runtime"),
        })
        if "STRATEGYOS_POSTGRES_E2E_DATABASE_URL" in env:
            source = Path(directory) / "source_dataset"
            shutil.copytree(repo / "tests/fixtures/01_Synthetic_Dataset", source)
            env["STRATEGYOS_SOURCE_DATASET"] = str(source)
        return subprocess.call(
            [sys.executable, "-m", "pytest", *(args or ["-q"])],
            cwd=repo, env=env,
        )


if __name__ == "__main__":
    raise SystemExit(main())
