from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .config import CONFIG, ObjectStoreConfig


class ObjectStoreUnavailable(RuntimeError):
    pass


class S3CompatibleStore:
    def __init__(self, config: ObjectStoreConfig = CONFIG.object_store) -> None:
        if not config.enabled:
            raise ObjectStoreUnavailable("S3-compatible object store is not configured.")
        self.config = config
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config as BotoConfig
            except Exception as exc:  # pragma: no cover - optional cloud dependency
                raise ObjectStoreUnavailable("boto3 is required for object-store sync.") from exc
            self._client = boto3.client(
                "s3",
                endpoint_url=self.config.endpoint_url,
                region_name=self.config.region,
                aws_access_key_id=self.config.access_key_id,
                aws_secret_access_key=self.config.secret_access_key,
                config=BotoConfig(s3={"addressing_style": "path" if self.config.force_path_style else "auto"}),
            )
        return self._client

    def key_for(self, relative_key: str) -> str:
        return f"{self.config.prefix}/{relative_key.strip('/')}" if self.config.prefix else relative_key.strip("/")

    def upload_file(self, path: Path, relative_key: str) -> str:
        key = self.key_for(relative_key)
        self.client.upload_file(str(path), self.config.bucket, key)
        return f"s3://{self.config.bucket}/{key}"

    def upload_directory(self, directory: Path, prefix: str) -> list[dict]:
        uploaded = []
        for path in sorted(p for p in directory.rglob("*") if p.is_file()):
            rel = path.relative_to(directory)
            uploaded.append({"path": str(path), "uri": self.upload_file(path, f"{prefix}/{rel}")})
        return uploaded


def sync_artifacts(run_dir: Path, artifact_paths: Iterable[Path]) -> list[dict]:
    if not CONFIG.object_store.enabled:
        return []
    store = S3CompatibleStore()
    uploaded = []
    for path in artifact_paths:
        if path.exists() and path.is_file():
            uploaded.append({"artifact": path.name, "uri": store.upload_file(path, f"runs/{run_dir.name}/{path.name}")})
    return uploaded


def sync_source_files(dataset_root: Path) -> list[dict]:
    if not CONFIG.object_store.enabled or not CONFIG.sync_source_files:
        return []
    return S3CompatibleStore().upload_directory(dataset_root, "source")


def object_store_status() -> dict:
    status = asdict(CONFIG.object_store)
    if status.get("secret_access_key"):
        status["secret_access_key"] = "***"
    if status.get("access_key_id"):
        status["access_key_id"] = "***"
    return status | {"enabled": CONFIG.object_store.enabled}
