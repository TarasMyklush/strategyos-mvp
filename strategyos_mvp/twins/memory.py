"""Twin state persistence — working memory, investigations, and history.

Each twin maintains a persistent TwinState across wake/sleep cycles.
State is serialized to JSON for durability and can be shared across
process restarts.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from strategyos_mvp.twins.persona import TWIN_CATALOG

_MAX_HISTORY = 100


@dataclass
class TwinState:
    """Mutable state for a single digital twin instance.

    Attributes:
        twin_id: Unique identifier for this twin instance.
        role: The twin's role (must match a key in TWIN_CATALOG).
        active_investigations: Mapping of investigation_id → investigation context.
        pending_requests: Mapping of request_message_id → lifecycle record.
        conversation_history: Chronological list of recent message dicts.
        working_memory: Free-form key-value scratchpad for the twin.
        last_wake_at: ISO-8601 timestamp of the last wake cycle, or *None*.
        cycle_count: Number of wake/sleep cycles completed.
    """

    twin_id: str
    role: str
    active_investigations: dict[str, Any] = field(default_factory=dict)
    pending_requests: dict[str, Any] = field(default_factory=dict)
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    working_memory: dict[str, Any] = field(default_factory=dict)
    last_wake_at: str | None = None
    cycle_count: int = 0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_twin_state(role: str) -> TwinState:
    """Create a new TwinState for the given role.

    Generates a twin_id from the role and the current timestamp.

    Args:
        role: The twin role (e.g. ``"ceo"``, ``"cfo"``). Must exist in
            TWIN_CATALOG.

    Returns:
        A new TwinState instance.

    Raises:
        KeyError: If the role is not in TWIN_CATALOG.
    """
    if role not in TWIN_CATALOG:
        raise KeyError(f"Unknown twin role: {role!r}. Valid roles: {list(TWIN_CATALOG)}")

    now = datetime.now(timezone.utc)
    twin_id = f"{role}_twin_{now.strftime('%Y%m%d_%H%M%S%f')}"
    return TwinState(twin_id=twin_id, role=role)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _to_dict(obj: Any) -> Any:
    """Recursively convert a dataclass (or nested dataclasses) to a plain dict."""
    if is_dataclass(obj):
        return {k: _to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


def save_state(state: TwinState, path: Path) -> None:
    """Serialize a TwinState to a JSON file.

    Args:
        state: The twin state to persist.
        path: Filesystem path for the JSON file (parent directory must exist).
    """
    data = _to_dict(state)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_state(path: Path) -> TwinState:
    """Deserialize a TwinState from a JSON file.

    Args:
        path: Path to a previously saved JSON state file.

    Returns:
        A new TwinState instance with the restored data.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    return TwinState(
        twin_id=str(data.get("twin_id", "")),
        role=str(data.get("role", "")),
        active_investigations=dict(data.get("active_investigations", {})),
        pending_requests=dict(data.get("pending_requests", {})),
        conversation_history=list(data.get("conversation_history", [])),
        working_memory=dict(data.get("working_memory", {})),
        last_wake_at=data.get("last_wake_at"),
        cycle_count=int(data.get("cycle_count", 0)),
    )


# ---------------------------------------------------------------------------
# History management
# ---------------------------------------------------------------------------


def add_to_history(state: TwinState, message: dict[str, Any]) -> None:
    """Add a message dict to the conversation history.

    New entries are prepended so the most recent messages appear first.
    The history is capped at ``_MAX_HISTORY`` (100) entries.

    Args:
        state: The twin state to mutate.
        message: A dict representing the message to record.
    """
    state.conversation_history.insert(0, message)
    if len(state.conversation_history) > _MAX_HISTORY:
        state.conversation_history = state.conversation_history[:_MAX_HISTORY]


# ---------------------------------------------------------------------------
# Investigation lifecycle
# ---------------------------------------------------------------------------


def add_investigation(state: TwinState, inv_id: str, context: dict[str, Any]) -> None:
    """Register a new active investigation.

    Args:
        state: The twin state to mutate.
        inv_id: Unique identifier for the investigation.
        context: Initial context dict (e.g. KPI node, trigger reason).
    """
    state.active_investigations[inv_id] = {
        "id": inv_id,
        "status": "open",
        "context": context,
        "findings": [],
        "resolution": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def resolve_investigation(
    state: TwinState, inv_id: str, resolution: dict[str, Any]
) -> None:
    """Close an active investigation with a resolution.

    Args:
        state: The twin state to mutate.
        inv_id: Identifier of the investigation to close.
        resolution: Dict describing the resolution outcome.

    Raises:
        KeyError: If the investigation ID is not found.
    """
    if inv_id not in state.active_investigations:
        raise KeyError(f"Investigation {inv_id!r} not found in state for twin {state.twin_id!r}")

    entry = state.active_investigations[inv_id]
    entry["status"] = "resolved"
    entry["resolution"] = resolution
    entry["resolved_at"] = datetime.now(timezone.utc).isoformat()
