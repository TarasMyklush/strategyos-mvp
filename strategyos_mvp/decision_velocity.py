"""Decision timing from independent observed, decided and verified-action events."""
from datetime import datetime, timezone
from statistics import median
from typing import Any, Iterable, Mapping


def _date(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Decision timestamps require an explicit timezone.")
    return parsed


def summarize(records: Iterable[Mapping[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    decision_hours, action_hours, pending, invalid = [], [], [], []
    for record in records:
        try:
            surfaced = _date(record.get("surfaced_at"))
            decided = _date(record.get("decided_at"))
            acted = _date(record.get("first_action_at")) if record.get("action_evidence_verified") else None
            if decided and acted and acted < decided:
                raise ValueError("Action predates the recorded decision.")
            if surfaced and decided:
                if decided < surfaced:
                    raise ValueError("Decision predates its observation.")
                decision_hours.append((decided - surfaced).total_seconds() / 3600)
            if decided and acted:
                if acted < decided:
                    raise ValueError("Action predates the recorded decision.")
                action_hours.append((acted - decided).total_seconds() / 3600)
            start = decided or surfaced
            if start and not acted:
                pending.append({"decision_key": record.get("decision_key"),
                    "state": "awaiting_verified_action" if decided else "awaiting_decision",
                    "age_hours": round(max(0, (now - start).total_seconds() / 3600), 2),
                    "evidence_event_ids": record.get("event_ids", [])})
        except (ValueError, TypeError):
            invalid.append(record.get("decision_key"))
    return {"median_surfaced_to_decided_hours": round(median(decision_hours), 2) if decision_hours else None,
            "median_decided_to_acted_hours": round(median(action_hours), 2) if action_hours else None,
            "decision_sample_count": len(decision_hours), "action_sample_count": len(action_hours),
            "pending": pending, "invalid_chronology": invalid,
            "definition": "Approval records a decision. Only a separately verified first action records execution."}
