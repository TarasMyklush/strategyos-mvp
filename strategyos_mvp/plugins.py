from __future__ import annotations

import importlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from types import ModuleType
from typing import Iterable

from .config import CONFIG


@dataclass(frozen=True)
class PluginLoadRecord:
    module: str
    status: str
    loaded_at: str | None = None
    error: str | None = None


_LOADED_MODULES: dict[str, ModuleType] = {}
_LOAD_RECORDS: dict[str, PluginLoadRecord] = {}


def configured_plugin_modules() -> tuple[str, ...]:
    return tuple(CONFIG.plugin_modules)


def load_configured_plugins() -> tuple[PluginLoadRecord, ...]:
    return load_plugin_modules(
        configured_plugin_modules(),
        failure_mode=CONFIG.plugin_failure_mode,
    )


def load_plugin_modules(
    modules: Iterable[str],
    *,
    failure_mode: str = "strict",
) -> tuple[PluginLoadRecord, ...]:
    normalized = tuple(_normalize_modules(modules))
    records: list[PluginLoadRecord] = []
    for module_name in normalized:
        record = _load_plugin_module(module_name, failure_mode=failure_mode)
        records.append(record)
    return tuple(records)


def plugin_status() -> dict[str, object]:
    return {
        "configured_modules": list(configured_plugin_modules()),
        "failure_mode": CONFIG.plugin_failure_mode,
        "records": [asdict(record) for record in _LOAD_RECORDS.values()],
    }


def reset_plugin_loader_for_tests() -> None:
    _LOADED_MODULES.clear()
    _LOAD_RECORDS.clear()


def _normalize_modules(modules: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for module_name in modules:
        item = str(module_name or "").strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _load_plugin_module(module_name: str, *, failure_mode: str) -> PluginLoadRecord:
    if module_name in _LOADED_MODULES:
        record = _LOAD_RECORDS[module_name]
        return PluginLoadRecord(
            module=module_name,
            status="already_loaded",
            loaded_at=record.loaded_at,
            error=record.error,
        )
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        record = PluginLoadRecord(
            module=module_name,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        _LOAD_RECORDS[module_name] = record
        if failure_mode != "permissive":
            raise RuntimeError(
                f"StrategyOS plugin module '{module_name}' failed to load: {record.error}"
            ) from exc
        return record

    record = PluginLoadRecord(
        module=module_name,
        status="loaded",
        loaded_at=datetime.now(UTC).isoformat(),
    )
    _LOADED_MODULES[module_name] = module
    _LOAD_RECORDS[module_name] = record
    return record
