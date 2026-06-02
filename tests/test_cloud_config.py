from pathlib import Path
import os
import tempfile

from strategyos_mvp.config import load_config
from strategyos_mvp.storage import object_store_status, sync_artifacts


def test_default_config_has_local_paths():
    config = load_config()
    assert config.workspace_root.exists()
    assert config.default_run_dir.name == "StrategyOS MVP Run"


def test_object_store_status_redacts_credentials():
    import strategyos_mvp.storage as storage

    original_config = storage.CONFIG
    original_env = {key: os.environ.get(key) for key in [
        "STRATEGYOS_OBJECT_BUCKET",
        "STRATEGYOS_OBJECT_ENDPOINT",
        "STRATEGYOS_OBJECT_ACCESS_KEY_ID",
        "STRATEGYOS_OBJECT_SECRET_ACCESS_KEY",
    ]}
    try:
        os.environ["STRATEGYOS_OBJECT_BUCKET"] = "bucket"
        os.environ["STRATEGYOS_OBJECT_ENDPOINT"] = "http://object-store"
        os.environ["STRATEGYOS_OBJECT_ACCESS_KEY_ID"] = "access"
        os.environ["STRATEGYOS_OBJECT_SECRET_ACCESS_KEY"] = "secret"
        storage.CONFIG = load_config()
        status = object_store_status()
        assert status["enabled"]
        assert status["access_key_id"] == "***"
        assert status["secret_access_key"] == "***"
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        storage.CONFIG = original_config


def test_sync_artifacts_noops_without_object_store():
    with tempfile.TemporaryDirectory() as tmp:
        artifact = Path(tmp) / "artifact.txt"
        artifact.write_text("ok", encoding="utf-8")
        assert sync_artifacts(Path("run"), [artifact]) == []
