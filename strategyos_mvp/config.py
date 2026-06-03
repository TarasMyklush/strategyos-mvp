from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE_ROOT = PACKAGE_ROOT.parent


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in {None, ""} else default


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


def env_path(name: str, default: Path) -> Path:
    return Path(env(name, str(default))).expanduser().resolve()


@dataclass(frozen=True)
class ObjectStoreConfig:
    bucket: str | None
    endpoint_url: str | None
    region: str
    access_key_id: str | None
    secret_access_key: str | None
    prefix: str
    force_path_style: bool

    @property
    def enabled(self) -> bool:
        return bool(self.bucket and self.endpoint_url)


@dataclass(frozen=True)
class StrategyOSConfig:
    tenant_slug: str
    tenant_name: str
    source_system_name: str
    workspace_root: Path
    poc_root: Path
    source_dataset: Path
    output_root: Path
    default_run_dir: Path
    agent_input_dir: Path
    evaluation_dir: Path
    object_store: ObjectStoreConfig
    database_url: str | None
    redis_url: str | None
    neo4j_uri: str | None
    neo4j_user: str | None
    neo4j_password: str | None
    ocr_engine: str
    sync_artifacts: bool
    sync_source_files: bool


def load_config() -> StrategyOSConfig:
    workspace_root = env_path("STRATEGYOS_WORKSPACE_ROOT", DEFAULT_WORKSPACE_ROOT)
    poc_root = env_path("STRATEGYOS_POC_ROOT", workspace_root / "strategy os" / "StrategyOS POC")
    output_root = env_path("STRATEGYOS_OUTPUT_ROOT", workspace_root / "outputs")
    return StrategyOSConfig(
        tenant_slug=env("STRATEGYOS_TENANT_SLUG", "local-poc") or "local-poc",
        tenant_name=env("STRATEGYOS_TENANT_NAME", "StrategyOS Local POC") or "StrategyOS Local POC",
        source_system_name=env("STRATEGYOS_SOURCE_SYSTEM_NAME", "Synthetic Finance Dataset") or "Synthetic Finance Dataset",
        workspace_root=workspace_root,
        poc_root=poc_root,
        source_dataset=env_path("STRATEGYOS_SOURCE_DATASET", poc_root / "01_Synthetic_Dataset"),
        output_root=output_root,
        default_run_dir=env_path("STRATEGYOS_RUN_DIR", output_root / "StrategyOS MVP Run"),
        agent_input_dir=env_path("STRATEGYOS_AGENT_INPUT_DIR", output_root / "StrategyOS Agent Input"),
        evaluation_dir=env_path("STRATEGYOS_EVALUATION_DIR", output_root / "StrategyOS Evaluation"),
        object_store=ObjectStoreConfig(
            bucket=env("STRATEGYOS_OBJECT_BUCKET"),
            endpoint_url=env("STRATEGYOS_OBJECT_ENDPOINT"),
            region=env("STRATEGYOS_OBJECT_REGION", "us-east-1") or "us-east-1",
            access_key_id=env("STRATEGYOS_OBJECT_ACCESS_KEY_ID"),
            secret_access_key=env("STRATEGYOS_OBJECT_SECRET_ACCESS_KEY"),
            prefix=(env("STRATEGYOS_OBJECT_PREFIX", "strategyos") or "strategyos").strip("/"),
            force_path_style=env_bool("STRATEGYOS_OBJECT_FORCE_PATH_STYLE", True),
        ),
        database_url=env("DATABASE_URL") or env("STRATEGYOS_DATABASE_URL"),
        redis_url=env("REDIS_URL") or env("STRATEGYOS_REDIS_URL"),
        neo4j_uri=env("NEO4J_URI") or env("STRATEGYOS_NEO4J_URI"),
        neo4j_user=env("NEO4J_USER") or env("STRATEGYOS_NEO4J_USER"),
        neo4j_password=env("NEO4J_PASSWORD") or env("STRATEGYOS_NEO4J_PASSWORD"),
        ocr_engine=(env("STRATEGYOS_OCR_ENGINE", "auto") or "auto").lower(),
        sync_artifacts=env_bool("STRATEGYOS_SYNC_ARTIFACTS", False),
        sync_source_files=env_bool("STRATEGYOS_SYNC_SOURCE_FILES", False),
    )


CONFIG = load_config()
