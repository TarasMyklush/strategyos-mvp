"""JSON-backed persistence layer for digital twin state."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_app_data_dir() -> Path:
    configured = os.getenv("STRATEGYOS_TWINS_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return _workspace_root() / ".strategyos_mvp_data" / "twins"


def get_runtime_data_dir() -> Path:
    configured = os.getenv("STRATEGYOS_TWINS_RUNTIME_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(tempfile.gettempdir()) / f"strategyos_twins_runtime_{os.getpid()}"


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


class _JsonRepository:
    def __init__(self, base_path: Path) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _read_file(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return copy.deepcopy(default)
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_file(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_jsonable(data), indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )


class KpiRepository(_JsonRepository):
    def __init__(self, base_path: Path) -> None:
        super().__init__(Path(base_path) / "kpis")
        self._path = self.base_path / "tree.json"

    def ensure_seeded(self, seed_data: dict[str, dict[str, Any]]) -> None:
        if not self._path.exists():
            self.save(seed_data)

    def load(self, kpi_id: str | None = None) -> Any:
        tree = self._read_file(self._path, {})
        if kpi_id is None:
            return tree
        node = tree.get(kpi_id)
        return copy.deepcopy(node) if node is not None else None

    def save(self, tree: dict[str, dict[str, Any]]) -> None:
        self._write_file(self._path, tree)

    def list(self) -> list[dict[str, Any]]:
        tree = self.load()
        return [{"node_id": node_id, **copy.deepcopy(data)} for node_id, data in tree.items()]

    def update(self, kpi_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        tree = self.load()
        current = copy.deepcopy(tree.get(kpi_id, {}))
        current.update(payload)
        tree[kpi_id] = current
        self.save(tree)
        return copy.deepcopy(current)

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()


class TwinInboxRepository(_JsonRepository):
    def __init__(self, base_path: Path) -> None:
        super().__init__(Path(base_path) / "inbox")
        self._path = self.base_path / "messages.json"

    def load(self, role: str) -> list[dict[str, Any]]:
        inboxes = self._read_file(self._path, {})
        return copy.deepcopy(inboxes.get(role, []))

    def save(self, role: str, messages: list[dict[str, Any]]) -> None:
        inboxes = self._read_file(self._path, {})
        inboxes[role] = _jsonable(messages)
        self._write_file(self._path, inboxes)

    def list(self, role: str | None = None) -> Any:
        inboxes = self._read_file(self._path, {})
        if role is None:
            return copy.deepcopy(inboxes)
        return copy.deepcopy(inboxes.get(role, []))

    def append(self, role: str, message: dict[str, Any]) -> None:
        messages = self.load(role)
        messages.append(copy.deepcopy(message))
        self.save(role, messages)

    def update(self, role: str, message_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        messages = self.load(role)
        for index, message in enumerate(messages):
            if message.get("message_id") == message_id:
                updated = copy.deepcopy(message)
                updated.update(payload)
                messages[index] = updated
                self.save(role, messages)
                return updated
        return None

    def consume(self, role: str) -> list[dict[str, Any]]:
        messages = self.load(role)
        self.save(role, [])
        return messages

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()


class InvestigationRepository(_JsonRepository):
    def __init__(self, base_path: Path) -> None:
        super().__init__(Path(base_path) / "investigations")

    def _role_path(self, role: str) -> Path:
        return self.base_path / f"{role}.json"

    def load(self, role: str, investigation_id: str | None = None) -> Any:
        records = self._read_file(self._role_path(role), [])
        if investigation_id is None:
            return records
        for record in records:
            if record.get("id") == investigation_id:
                return copy.deepcopy(record)
        return None

    def save(self, role: str, record: dict[str, Any]) -> dict[str, Any]:
        records = self.load(role)
        record_id = record.get("id")
        for index, existing in enumerate(records):
            if existing.get("id") == record_id:
                records[index] = copy.deepcopy(record)
                self._write_file(self._role_path(role), records)
                return copy.deepcopy(record)
        records.append(copy.deepcopy(record))
        self._write_file(self._role_path(role), records)
        return copy.deepcopy(record)

    def list(self, role: str | None = None) -> Any:
        if role is not None:
            return self.load(role)
        all_records: dict[str, list[dict[str, Any]]] = {}
        for path in sorted(self.base_path.glob("*.json")):
            all_records[path.stem] = self._read_file(path, [])
        return all_records

    def update(self, role: str, investigation_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        record = self.load(role, investigation_id)
        if record is None:
            return None
        updated = copy.deepcopy(record)
        updated.update(payload)
        return self.save(role, updated)

    def clear(self) -> None:
        for path in self.base_path.glob("*.json"):
            path.unlink()


class TwinStateRepository(_JsonRepository):
    def __init__(self, base_path: Path) -> None:
        super().__init__(Path(base_path) / "state")

    def _role_path(self, role: str) -> Path:
        return self.base_path / f"{role}.json"

    def load(self, role: str) -> dict[str, Any] | None:
        path = self._role_path(role)
        if not path.exists():
            return None
        return self._read_file(path, {})

    def save(self, role: str, state: Any) -> dict[str, Any]:
        payload = _jsonable(state)
        self._write_file(self._role_path(role), payload)
        return copy.deepcopy(payload)

    def list(self) -> list[dict[str, Any]]:
        return [self._read_file(path, {}) for path in sorted(self.base_path.glob("*.json"))]

    def update(self, role: str, payload: dict[str, Any]) -> dict[str, Any]:
        state = self.load(role) or {}
        state.update(copy.deepcopy(payload))
        self.save(role, state)
        return state

    def clear(self) -> None:
        for path in self.base_path.glob("*.json"):
            path.unlink()


@dataclass(frozen=True)
class TwinRepositories:
    kpis: KpiRepository
    inboxes: TwinInboxRepository
    investigations: InvestigationRepository
    states: TwinStateRepository


def build_repositories(base_path: Path | str) -> TwinRepositories:
    root = Path(base_path)
    return TwinRepositories(
        kpis=KpiRepository(root),
        inboxes=TwinInboxRepository(root),
        investigations=InvestigationRepository(root),
        states=TwinStateRepository(root),
    )


def build_app_repositories() -> TwinRepositories:
    return build_repositories(get_app_data_dir())


def build_runtime_repositories() -> TwinRepositories:
    return build_repositories(get_runtime_data_dir())
