"""Governed CEO-agenda extraction from an optional uploaded calendar workbook."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import re
from typing import Any

from openpyxl import load_workbook

from .source_governance import RESTRICTED_CONTEXT_DIR


def derive_calendar_agenda(dataset_root: Path) -> dict[str, Any]:
    root = Path(dataset_root)
    candidates = sorted(path for path in root.rglob("*.xlsx") if "calendar" in path.name.lower() or "agenda" in path.name.lower())
    if not candidates:
        return {"status": "unavailable", "items": [], "reason": "No governed calendar workbook was supplied for this run."}
    path = candidates[0]
    relative_source = path.relative_to(root).as_posix()
    restricted = RESTRICTED_CONTEXT_DIR in path.relative_to(root).parts
    workbook = load_workbook(path, data_only=True, read_only=True)
    sheet = next((item for item in workbook.worksheets if item.title.strip().lower() in {"calendar", "agenda"}), workbook.active)
    rows = iter(sheet.values)
    headers = {_header_key(value): index for index, value in enumerate(next(rows, ())) if value is not None}
    def value(values: tuple[Any, ...], *names: str) -> Any:
        index = next((headers[name] for name in names if name in headers), None)
        return values[index] if index is not None and index < len(values) else None
    items: list[dict[str, Any]] = []
    for raw in rows:
        values = tuple(raw)
        event_date = _date(value(values, "event_date", "date", "meeting_date"))
        title = str(value(values, "title", "event_title", "meeting", "agenda_item") or "").strip()
        event_type = str(value(values, "type", "event_type", "meeting_type", "category") or "").strip()
        if event_date is None or not title or not event_type:
            continue
        prep = str(
            value(values, "prep_needed", "preparation", "prep", "notes_agenda", "notes", "agenda_notes")
            or "No preparation request was supplied."
        ).strip()
        items.append({
            "event_id": f"calendar-{event_date.isoformat()}-{len(items) + 1}",
            "date": event_date.isoformat(),
            "day": event_date.strftime("%a %d %b"),
            "when": str(value(values, "start_time", "start", "time") or event_date.isoformat()),
            "ends_at": str(value(values, "end_time", "end") or "").strip() or None,
            "title": title,
            "type": event_type,
            "prep": prep,
            "attendees": str(value(values, "attendees", "participants") or "").strip() or None,
            "location": str(value(values, "location", "venue") or "").strip() or None,
            "related_bu": str(value(values, "related_bu", "business_unit") or "").strip() or None,
            "evidence_scope": "calendar_agenda_only" if restricted else "governed_calendar",
        })
    items.sort(key=lambda item: str(item.get("date") or ""))
    projection_day = date.today()
    upcoming_items = [item for item in items if str(item.get("date") or "") >= projection_day.isoformat()]
    if upcoming_items:
        projected_items = upcoming_items[:12]
        if len(projected_items) < 12:
            recent_past = [item for item in items if str(item.get("date") or "") < projection_day.isoformat()]
            projected_items.extend(reversed(recent_past[-(12 - len(projected_items)) :]))
        projection_policy = "upcoming_first"
    else:
        projected_items = items[-12:]
        projection_policy = "latest_available"
    return {
        "status": "ready" if items else "unavailable",
        "items": projected_items,
        "total_item_count": len(items),
        "upcoming_item_count": len(upcoming_items),
        "projection_as_of": projection_day.isoformat(),
        "projection_policy": projection_policy,
        "reason": "Calendar workbook contains no complete Event_Date, Title and Type rows." if not items else None,
        "source_file": relative_source,
        "sheet": sheet.title,
        "restricted": restricted,
        "evidence_scope": "calendar_agenda_only" if restricted else "governed_calendar",
    }


def _header_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(value), pattern).date()
        except (TypeError, ValueError):
            continue
    return None
