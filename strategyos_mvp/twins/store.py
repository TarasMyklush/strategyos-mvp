"""JSON-backed persistence layer for digital twin state."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


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

    def _lock_path(self, path: Path) -> Path:
        return path.parent / f".{path.name}.lock"

    @contextmanager
    def _file_lock(self, path: Path):
        lock_path = self._lock_path(path)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _write_file(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.parent / f".{path.name}.{uuid4().hex}.tmp"
        tmp_path.write_text(
            json.dumps(_jsonable(data), indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def _mutate_file(self, path: Path, default: Any, mutator: Any) -> Any:
        with self._file_lock(path):
            current = self._read_file(path, default)
            updated = mutator(copy.deepcopy(current))
            self._write_file(path, updated)
            return copy.deepcopy(updated)


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
        def _save(inboxes: dict[str, Any]) -> dict[str, Any]:
            inboxes[role] = _jsonable(messages)
            return inboxes

        self._mutate_file(self._path, {}, _save)

    def list(self, role: str | None = None) -> Any:
        inboxes = self._read_file(self._path, {})
        if role is None:
            return copy.deepcopy(inboxes)
        return copy.deepcopy(inboxes.get(role, []))

    def append(self, role: str, message: dict[str, Any]) -> None:
        def _append(inboxes: dict[str, Any]) -> dict[str, Any]:
            messages = list(inboxes.get(role, []))
            messages.append(copy.deepcopy(message))
            inboxes[role] = _jsonable(messages)
            return inboxes

        self._mutate_file(self._path, {}, _append)

    def update(self, role: str, message_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        updated_message: dict[str, Any] | None = None

        def _update(inboxes: dict[str, Any]) -> dict[str, Any]:
            nonlocal updated_message
            messages = list(inboxes.get(role, []))
            for index, message in enumerate(messages):
                if message.get("message_id") == message_id:
                    updated = copy.deepcopy(message)
                    updated.update(payload)
                    messages[index] = updated
                    updated_message = copy.deepcopy(updated)
                    break
            inboxes[role] = _jsonable(messages)
            return inboxes

        self._mutate_file(self._path, {}, _update)
        return updated_message

    def consume(self, role: str) -> list[dict[str, Any]]:
        consumed: list[dict[str, Any]] = []

        def _consume(inboxes: dict[str, Any]) -> dict[str, Any]:
            nonlocal consumed
            consumed = copy.deepcopy(inboxes.get(role, []))
            inboxes[role] = []
            return inboxes

        self._mutate_file(self._path, {}, _consume)
        return consumed

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

    def find_by_request_key(self, role: str, request_key: str) -> dict[str, Any] | None:
        for record in self.load(role):
            if str(record.get("request_key") or "") == request_key:
                return copy.deepcopy(record)
        return None

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
        with self._file_lock(self._role_path(role)):
            self._write_file(self._role_path(role), payload)
        return copy.deepcopy(payload)

    def list(self) -> list[dict[str, Any]]:
        return [self._read_file(path, {}) for path in sorted(self.base_path.glob("*.json"))]

    def update(self, role: str, payload: dict[str, Any]) -> dict[str, Any]:
        def _update(state: dict[str, Any]) -> dict[str, Any]:
            state.update(copy.deepcopy(payload))
            return state

        updated = self._mutate_file(self._role_path(role), {}, _update)
        return copy.deepcopy(updated)


class TwinRequestRepository(_JsonRepository):
    def __init__(self, base_path: Path) -> None:
        super().__init__(Path(base_path) / "requests")

    def _role_path(self, role: str) -> Path:
        return self.base_path / f"{role}.json"

    def save(self, role: str, record: dict[str, Any]) -> dict[str, Any]:
        request_id = str(record.get("request_message_id") or "")

        def _save(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
            for index, existing in enumerate(records):
                if str(existing.get("request_message_id") or "") == request_id:
                    records[index] = copy.deepcopy(record)
                    return records
            records.append(copy.deepcopy(record))
            return records

        updated = self._mutate_file(self._role_path(role), [], _save)
        for item in updated:
            if str(item.get("request_message_id") or "") == request_id:
                return copy.deepcopy(item)
        return copy.deepcopy(record)

    def load(self, role: str, request_message_id: str) -> dict[str, Any] | None:
        for record in self._read_file(self._role_path(role), []):
            if str(record.get("request_message_id") or "") == request_message_id:
                return copy.deepcopy(record)
        return None

    def update(self, role: str, request_message_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.load(role, request_message_id)
        if current is None:
            return None
        updated = copy.deepcopy(current)
        updated.update(copy.deepcopy(payload))
        return self.save(role, updated)

    def list(
        self,
        role: str,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        records = [
            copy.deepcopy(record)
            for record in self._read_file(self._role_path(role), [])
            if status is None or record.get("status") == status
        ]
        records.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        if limit is not None:
            return records[:limit]
        return records

    def clear(self) -> None:
        for path in self.base_path.glob("*.json"):
            path.unlink()

    def clear(self) -> None:
        for path in self.base_path.glob("*.json"):
            path.unlink()


class GovernanceRepository(_JsonRepository):
    def __init__(self, base_path: Path) -> None:
        super().__init__(Path(base_path) / "governance")
        self._decisions_path = self.base_path / "decisions.json"
        self._routing_path = self.base_path / "routing.json"
        self._audit_path = self.base_path / "audit.json"

    def _append_record(self, path: Path, record: dict[str, Any]) -> dict[str, Any]:
        def _append(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
            records.append(copy.deepcopy(record))
            return records

        self._mutate_file(path, [], _append)
        return copy.deepcopy(record)

    def save_decision(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._append_record(self._decisions_path, record)

    def save_routing_event(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._append_record(self._routing_path, record)

    def save_audit_entry(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._append_record(self._audit_path, record)

    def find_decision(
        self,
        *,
        role: str,
        item_id: str,
        status: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        for record in self._read_file(self._decisions_path, []):
            if (
                str(record.get("role") or "") == role
                and str(record.get("item_id") or "") == item_id
                and str(record.get("status") or "") == status
                and str(record.get("idempotency_key") or "") == idempotency_key
            ):
                return copy.deepcopy(record)
        return None

    def find_routing_event(
        self,
        *,
        source_role: str,
        item_id: str,
        event_type: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        for record in self._read_file(self._routing_path, []):
            if (
                str(record.get("source_role") or "") == source_role
                and str(record.get("item_id") or "") == item_id
                and str(record.get("event_type") or "") == event_type
                and str(record.get("idempotency_key") or "") == idempotency_key
            ):
                return copy.deepcopy(record)
        return None

    def list_decisions(
        self, role: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        records = self._read_file(self._decisions_path, [])
        filtered = [
            copy.deepcopy(record)
            for record in records
            if role is None or record.get("role") == role
        ]
        filtered.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        if limit is not None:
            return filtered[:limit]
        return filtered

    def list_routing_events(
        self, role: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        records = self._read_file(self._routing_path, [])
        filtered = [
            copy.deepcopy(record)
            for record in records
            if role is None or record.get("source_role") == role
        ]
        filtered.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        if limit is not None:
            return filtered[:limit]
        return filtered

    def list_audit_entries(
        self, role: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        records = self._read_file(self._audit_path, [])
        filtered = [
            copy.deepcopy(record)
            for record in records
            if role is None or record.get("role") == role
        ]
        if limit is not None:
            return filtered[-limit:]
        return filtered

    def history(self, role: str, limit: int = 20) -> list[dict[str, Any]]:
        combined: list[dict[str, Any]] = []
        for record in self.list_decisions(role):
            status = str(record.get("status") or "").lower()
            combined.append({
                "event_id": record.get("event_id"),
                "timestamp": record.get("timestamp"),
                "role": record.get("role"),
                "actor_role": record.get("actor_role"),
                "actor_subject": record.get("actor_subject"),
                "event_type": record.get("event_type", "decision"),
                "result": status.upper(),
                "result_class": "approved" if status == "approved" else "rejected",
                "action": record.get("title") or record.get("item_id") or "Decision",
                "reason": record.get("rationale") or "",
                "item_id": record.get("item_id"),
            })
        for record in self.list_routing_events(role):
            event_type = str(record.get("event_type") or "routing").lower()
            combined.append({
                "event_id": record.get("event_id"),
                "timestamp": record.get("timestamp"),
                "role": record.get("source_role"),
                "actor_role": record.get("actor_role"),
                "actor_subject": record.get("actor_subject"),
                "event_type": event_type,
                "result": "ESCALATED" if event_type == "escalation" else "REDIRECTED",
                "result_class": "escalated",
                "action": record.get("title") or record.get("item_id") or "Routing event",
                "reason": record.get("reason") or "",
                "item_id": record.get("item_id"),
                "target_role": record.get("target_role"),
            })
        combined.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        return combined[:limit]

    def seed_demo_history(self, role: str) -> None:
        if self.list_decisions(role, limit=1) or self.list_routing_events(role, limit=1):
            return
        timestamp = datetime.now(UTC).isoformat()
        if role == "ceo":
            self.save_decision({
                "event_id": "seed-ceo-approval",
                "event_type": "approval",
                "role": "ceo",
                "item_id": "dec-001",
                "title": "Q3 budget reallocation — North America",
                "status": "approved",
                "rationale": "Seeded demo approval trail.",
                "reviewer_notes": "Seeded demo approval trail.",
                "actor_role": "executive",
                "actor_subject": "seed:executive",
                "timestamp": timestamp,
            })
        elif role == "cfo":
            self.save_decision({
                "event_id": "seed-cfo-approval",
                "event_type": "approval",
                "role": "cfo",
                "item_id": "bud-001",
                "title": "Approve Q3 digital campaign budget",
                "status": "approved",
                "rationale": "Seeded demo finance approval trail.",
                "reviewer_notes": "Seeded demo finance approval trail.",
                "actor_role": "operator",
                "actor_subject": "seed:operator",
                "timestamp": timestamp,
            })
        elif role == "group_manager":
            self.save_routing_event({
                "event_id": "seed-gm-routing",
                "event_type": "escalation",
                "source_role": "group_manager",
                "target_role": "cfo",
                "item_id": "inv-001",
                "title": "Plant capacity expansion request",
                "reason": "Seeded demo escalation trail.",
                "actor_role": "bu",
                "actor_subject": "seed:bu",
                "timestamp": timestamp,
            })

    def clear(self) -> None:
        for path in (self._decisions_path, self._routing_path, self._audit_path):
            if path.exists():
                path.unlink()


class CycleHistoryRepository(_JsonRepository):
    def __init__(self, base_path: Path) -> None:
        super().__init__(Path(base_path) / "cycles")
        self._path = self.base_path / "history.json"

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        cycle_id = str(record.get("cycle_id") or "")

        def _save(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
            for index, existing in enumerate(records):
                if str(existing.get("cycle_id") or "") == cycle_id:
                    records[index] = copy.deepcopy(record)
                    return records
            records.append(copy.deepcopy(record))
            return records

        updated = self._mutate_file(self._path, [], _save)
        for item in updated:
            if str(item.get("cycle_id") or "") == cycle_id:
                return copy.deepcopy(item)
        return copy.deepcopy(record)

    def load(self, cycle_id: str) -> dict[str, Any] | None:
        for record in self._read_file(self._path, []):
            if str(record.get("cycle_id") or "") == cycle_id:
                return copy.deepcopy(record)
        return None

    def list(
        self,
        cycle_type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        records = [
            copy.deepcopy(record)
            for record in self._read_file(self._path, [])
            if cycle_type is None or record.get("cycle_type") == cycle_type
        ]
        records.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
        if limit is not None:
            return records[:limit]
        return records

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()


class ReasoningTraceRepository(_JsonRepository):
    def __init__(self, base_path: Path) -> None:
        super().__init__(Path(base_path) / "reasoning")
        self._path = self.base_path / "traces.json"

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        trace_id = str(record.get("trace_id") or "")

        def _save(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
            for index, existing in enumerate(records):
                if str(existing.get("trace_id") or "") == trace_id:
                    records[index] = copy.deepcopy(record)
                    return records
            records.append(copy.deepcopy(record))
            return records

        self._mutate_file(self._path, [], _save)
        return copy.deepcopy(record)

    def load(self, trace_id: str) -> dict[str, Any] | None:
        records = self._read_file(self._path, [])
        for record in records:
            if str(record.get("trace_id") or "") == trace_id:
                return copy.deepcopy(record)
        return None

    def update(self, trace_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.load(trace_id)
        if current is None:
            return None
        updated = copy.deepcopy(current)
        updated.update(copy.deepcopy(payload))
        return self.save(updated)

    def list(
        self,
        role: str | None = None,
        cycle_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        records = self._read_file(self._path, [])
        filtered = [
            copy.deepcopy(record)
            for record in records
            if (role is None or record.get("role") == role)
            and (cycle_id is None or record.get("cycle_id") == cycle_id)
        ]
        filtered.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        if limit is not None:
            return filtered[:limit]
        return filtered

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()


class ExecutionLogRepository(_JsonRepository):
    def __init__(self, base_path: Path) -> None:
        super().__init__(Path(base_path) / "execution")
        self._path = self.base_path / "logs.json"

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        execution_id = str(record.get("execution_id") or "")

        def _save(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
            for index, existing in enumerate(records):
                if str(existing.get("execution_id") or "") == execution_id:
                    records[index] = copy.deepcopy(record)
                    return records
            records.append(copy.deepcopy(record))
            return records

        self._mutate_file(self._path, [], _save)
        return copy.deepcopy(record)

    def load(self, execution_id: str) -> dict[str, Any] | None:
        records = self._read_file(self._path, [])
        for record in records:
            if str(record.get("execution_id") or "") == execution_id:
                return copy.deepcopy(record)
        return None

    def update(self, execution_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.load(execution_id)
        if current is None:
            return None
        updated = copy.deepcopy(current)
        updated.update(copy.deepcopy(payload))
        return self.save(updated)

    def find_by_idempotency_key(
        self,
        execution_type: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        records = self._read_file(self._path, [])
        for record in records:
            if (
                str(record.get("execution_type") or "") == execution_type
                and str(record.get("idempotency_key") or "") == idempotency_key
            ):
                return copy.deepcopy(record)
        return None

    def list(
        self,
        execution_type: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        records = self._read_file(self._path, [])
        filtered = [
            copy.deepcopy(record)
            for record in records
            if (execution_type is None or record.get("execution_type") == execution_type)
            and (status is None or record.get("status") == status)
        ]
        filtered.sort(key=lambda item: str(item.get("started_at") or item.get("timestamp") or ""), reverse=True)
        if limit is not None:
            return filtered[:limit]
        return filtered

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()


@dataclass(frozen=True)
class TwinRepositories:
    kpis: KpiRepository
    inboxes: TwinInboxRepository
    requests: TwinRequestRepository
    investigations: InvestigationRepository
    states: TwinStateRepository
    governance: GovernanceRepository
    cycle_history: CycleHistoryRepository
    reasoning: ReasoningTraceRepository
    execution: ExecutionLogRepository


def build_repositories(base_path: Path | str) -> TwinRepositories:
    root = Path(base_path)
    return TwinRepositories(
        kpis=KpiRepository(root),
        inboxes=TwinInboxRepository(root),
        requests=TwinRequestRepository(root),
        investigations=InvestigationRepository(root),
        states=TwinStateRepository(root),
        governance=GovernanceRepository(root),
        cycle_history=CycleHistoryRepository(root),
        reasoning=ReasoningTraceRepository(root),
        execution=ExecutionLogRepository(root),
    )


def build_app_repositories() -> TwinRepositories:
    return build_repositories(get_app_data_dir())


def build_runtime_repositories() -> TwinRepositories:
    return build_repositories(get_runtime_data_dir())
