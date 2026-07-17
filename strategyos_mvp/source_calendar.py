"""Governed CEO-agenda extraction from an optional uploaded calendar workbook."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
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
    headers = {str(value or "").strip().lower().replace(" ", "_"): index for index, value in enumerate(next(rows, ())) if value is not None}
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
        prep = str(value(values, "prep_needed", "preparation", "prep") or "No preparation request was supplied.").strip()
        items.append({
            "event_id": f"calendar-{event_date.isoformat()}-{len(items) + 1}",
            "day": event_date.strftime("%a %d %b"),
            "when": str(value(values, "start_time", "time") or event_date.isoformat()),
            "title": title,
            "type": event_type,
            "prep": prep,
            "related_bu": str(value(values, "related_bu", "business_unit") or "").strip() or None,
            "evidence_scope": "calendar_agenda_only" if restricted else "governed_calendar",
        })
    return {
        "status": "ready" if items else "unavailable",
        "items": items[:12],
        "reason": "Calendar workbook contains no complete Event_Date, Title and Type rows." if not items else None,
        "source_file": relative_source,
        "sheet": sheet.title,
        "restricted": restricted,
        "evidence_scope": "calendar_agenda_only" if restricted else "governed_calendar",
    }


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
