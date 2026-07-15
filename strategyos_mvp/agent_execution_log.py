"""The execution log: what the assistants actually did, read back as recorded.

An executive who is asked to act on a finding is entitled to ask "who checked
this, and what did they change their mind about?". The run already answers that
question -- every Analyst/Auditor exchange is written to ``strategyos_agent_events``
as an :class:`~strategyos_mvp.models.AuditEvent`, with the actor, the action, the
challenge and response, the confidence before and after, and the token cost. That
record has never been read back to the surface.

This module does the reading. It derives nothing and infers nothing: an entry
here exists because an agent step happened and was persisted. That is why the
entries carry the ``*_fact`` claim class rather than a derived one -- unlike a
cost lever, which is an argument built on top of facts, an execution entry IS
the fact. If the run recorded no steps, the log says so rather than narrating
the run's status back as though it were activity.

The prior surface (``agent_modules["audit_log"]``) served whichever of two very
different things was available: real persisted events when the database answered,
or three sentences synthesised from workflow status when it did not. Those are
not interchangeable, and presenting the second as an "audit log" overstates what
the run knows. Here the two are separated: real events become entries, and their
absence becomes an explicit, stated absence.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# An executive reading a log wants the last thing that happened first. The
# database query already orders by created_at desc; this module preserves
# whatever order it is handed rather than re-sorting on a timestamp that may be
# absent, so ordering stays the database's decision, not a guess made here.

_CONFIDENCE_NARRATION = {
    "RAISED": "confidence raised",
    "LOWERED": "confidence lowered",
    "UNCHANGED": "confidence held",
}


def _event_field(event: Any, key: str, default: Any = None) -> Any:
    """Read a field from an event however it arrived.

    Events reach this module as plain dicts from the database reader, but the
    same records exist as ``AuditEvent`` dataclasses in-process. Accepting both
    keeps this readable from either side without the caller converting first --
    a dataclass-versus-Mapping mismatch has silently emptied a surface here
    before, so neither shape is assumed.
    """
    if isinstance(event, Mapping):
        if key in event:
            return event.get(key, default)
        nested = event.get("event_json")
        if isinstance(nested, Mapping) and key in nested:
            return nested.get(key, default)
        return default
    return getattr(event, key, default)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _actor_label(actor: Any) -> str:
    """Name the actor the way the rest of the surface names it.

    The stored actor is a token such as ``analyst`` or ``auditor``. The product
    calls these assistants, so the log does too -- an executive should not meet
    a different vocabulary here than on the team page.
    """
    text = _text(actor).replace("_", " ").strip()
    if not text:
        return "Assistant"
    return text.title()


def _confidence_note(event: Any) -> str | None:
    """State the confidence movement, but only when it is real.

    ``confidence_change`` is computed at write time from the before/after pair.
    When either side is missing the change is not meaningful, so nothing is said
    rather than reporting "unchanged" for a step that never held a view.
    """
    before = _text(_event_field(event, "confidence_before"))
    after = _text(_event_field(event, "confidence_after"))
    if not before or not after:
        return None
    change = _text(_event_field(event, "confidence_change")).upper()
    narration = _CONFIDENCE_NARRATION.get(change)
    if not narration:
        return None
    if before == after:
        return f"{narration} at {after}"
    return f"{narration} {before} → {after}"


def _cost_note(event: Any) -> str | None:
    """Report token cost only when the run actually metered it.

    Not every producer fills these in; ``finance_agents`` writes ``None`` for
    deterministic steps that never called a model. A zero would be a lie about a
    step that was never metered, so absent stays absent.
    """
    total = _int_or_none(_event_field(event, "total_tokens"))
    if total is None:
        prompt = _int_or_none(_event_field(event, "prompt_tokens"))
        completion = _int_or_none(_event_field(event, "completion_tokens"))
        if prompt is None and completion is None:
            return None
        total = (prompt or 0) + (completion or 0)
    if total <= 0:
        return None
    return f"{total:,} tokens"


def _entry(event: Any) -> dict[str, Any] | None:
    """Turn one persisted step into one log line, or skip it.

    A step with neither an action nor a detail has nothing to tell the reader;
    rendering an empty row would imply activity that the record does not
    describe.
    """
    action = _text(_event_field(event, "action"))
    detail = _text(_event_field(event, "detail"))
    if not action and not detail:
        return None

    round_no = _int_or_none(_event_field(event, "round_no"))
    entry: dict[str, Any] = {
        "event_id": _text(_event_field(event, "id")) or None,
        "round_no": round_no,
        "actor": _actor_label(_event_field(event, "actor")),
        "action": action.replace("_", " ") or "step recorded",
        "detail": detail,
        "finding_id": _text(_event_field(event, "finding_id")) or None,
        "challenge": _text(_event_field(event, "challenge")) or None,
        "response": _text(_event_field(event, "response")) or None,
        "status": _text(_event_field(event, "status")) or None,
        "occurred_at": _text(
            _event_field(event, "completed_at")
            or _event_field(event, "created_at")
            or _event_field(event, "started_at")
        )
        or None,
        "confidence_note": _confidence_note(event),
        "cost_note": _cost_note(event),
    }
    return entry


def build_execution_log(
    events: Sequence[Any] | None,
    *,
    limit: int = 25,
) -> dict[str, Any]:
    """Return the run's recorded agent steps, or an explicit empty result.

    ``limit`` bounds what is rendered, not what is counted: ``total_count``
    reports every step the run recorded so a truncated view never reads as a
    complete one.
    """
    payload: dict[str, Any] = {
        "entries": [],
        "total_count": 0,
        "status": "unavailable",
        "reason": "",
    }

    rows = list(events or [])
    if not rows:
        payload["reason"] = (
            "This run recorded no assistant steps, so there is no execution log to show."
        )
        return payload

    entries = [entry for entry in (_entry(row) for row in rows) if entry is not None]
    if not entries:
        payload["reason"] = (
            "This run's recorded steps carry no readable detail, so there is no execution log to show."
        )
        return payload

    payload["total_count"] = len(entries)
    payload["entries"] = entries[: max(0, limit)]
    payload["status"] = "available"
    payload["truncated"] = len(entries) > len(payload["entries"])

    actors = []
    for entry in entries:
        if entry["actor"] not in actors:
            actors.append(entry["actor"])
    payload["actors"] = actors

    rounds = [entry["round_no"] for entry in entries if entry["round_no"] is not None]
    payload["round_count"] = len(set(rounds)) if rounds else 0
    return payload
