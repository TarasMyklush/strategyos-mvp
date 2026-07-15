"""The execution log must report what was recorded and nothing else.

Fixtures here use the real ``AuditEvent`` dataclass and the real database row
shape (a flat record carrying a nested ``event_json``). A previous surface on
this codebase passed its unit tests against dict fixtures and then indexed zero
rows in production because the live objects were dataclasses; these tests pin
both shapes deliberately.
"""

from __future__ import annotations

from strategyos_mvp.agent_execution_log import build_execution_log
from strategyos_mvp.models import AuditEvent


def _event(**overrides):
    base = dict(
        round_no=1,
        actor="analyst",
        finding_id="F-001",
        action="raise_finding",
        detail="Duplicate payment to vendor identified in AP ledger.",
        challenge=None,
        response=None,
        status="logged",
        confidence_before="MEDIUM",
        confidence_after="HIGH",
        confidence_change="RAISED",
        started_at="2026-07-15T10:00:00+00:00",
        completed_at="2026-07-15T10:00:04+00:00",
        prompt_tokens=1200,
        completion_tokens=300,
        total_tokens=1500,
        estimated_cost_usd=0.02,
    )
    base.update(overrides)
    return AuditEvent(**base)


def test_empty_run_states_absence_rather_than_inventing_activity():
    payload = build_execution_log([])
    assert payload["status"] == "unavailable"
    assert payload["entries"] == []
    assert "no assistant steps" in payload["reason"]


def test_dataclass_events_are_read_not_skipped():
    """The live objects are dataclasses. Indexing zero of them is the bug."""
    payload = build_execution_log([_event()])
    assert payload["status"] == "available"
    assert payload["total_count"] == 1
    assert payload["entries"][0]["detail"].startswith("Duplicate payment")


def test_database_row_shape_with_nested_event_json_is_read():
    """The database reader returns flat columns plus the full event_json blob."""
    row = {
        "round_no": 2,
        "actor": "auditor",
        "finding_id": "F-002",
        "action": "challenge",
        "detail": "Requested supporting invoice.",
        "created_at": "2026-07-15T10:05:00+00:00",
        "event_json": {
            "confidence_before": "HIGH",
            "confidence_after": "MEDIUM",
            "confidence_change": "LOWERED",
            "total_tokens": 800,
            "challenge": "Where is the invoice?",
        },
    }
    payload = build_execution_log([row])
    entry = payload["entries"][0]
    assert entry["actor"] == "Auditor"
    assert entry["confidence_note"] == "confidence lowered HIGH → MEDIUM"
    assert entry["cost_note"] == "800 tokens"
    assert entry["challenge"] == "Where is the invoice?"


def test_actor_is_labelled_the_way_the_product_speaks():
    payload = build_execution_log([_event(actor="analyst")])
    assert payload["entries"][0]["actor"] == "Analyst"


def test_confidence_note_omitted_when_the_step_held_no_view():
    payload = build_execution_log(
        [_event(confidence_before=None, confidence_after=None, confidence_change="UNCHANGED")]
    )
    assert payload["entries"][0]["confidence_note"] is None


def test_unchanged_confidence_is_reported_at_its_level():
    payload = build_execution_log(
        [_event(confidence_before="HIGH", confidence_after="HIGH", confidence_change="UNCHANGED")]
    )
    assert payload["entries"][0]["confidence_note"] == "confidence held at HIGH"


def test_unmetered_step_reports_no_cost_rather_than_zero():
    """A deterministic step never called a model. Zero would be a lie."""
    payload = build_execution_log(
        [_event(prompt_tokens=None, completion_tokens=None, total_tokens=None)]
    )
    assert payload["entries"][0]["cost_note"] is None


def test_cost_is_summed_when_only_the_parts_were_recorded():
    payload = build_execution_log(
        [_event(prompt_tokens=100, completion_tokens=50, total_tokens=None)]
    )
    assert payload["entries"][0]["cost_note"] == "150 tokens"


def test_step_with_no_action_or_detail_is_not_rendered_as_a_row():
    payload = build_execution_log([_event(action="", detail="")])
    assert payload["status"] == "unavailable"


def test_truncation_never_reads_as_a_complete_view():
    events = [_event(round_no=i, detail=f"Step {i}") for i in range(30)]
    payload = build_execution_log(events, limit=25)
    assert len(payload["entries"]) == 25
    assert payload["total_count"] == 30
    assert payload["truncated"] is True


def test_untruncated_view_says_so():
    payload = build_execution_log([_event()], limit=25)
    assert payload["truncated"] is False


def test_database_order_is_preserved_not_re_sorted():
    """Ordering is the database's decision; this module must not second-guess it."""
    first = _event(detail="First in list", completed_at="2026-07-15T10:00:00+00:00")
    second = _event(detail="Second in list", completed_at="2026-07-15T11:00:00+00:00")
    payload = build_execution_log([first, second])
    assert payload["entries"][0]["detail"] == "First in list"


def test_actors_and_rounds_are_counted_from_the_record():
    events = [
        _event(round_no=1, actor="analyst"),
        _event(round_no=1, actor="auditor"),
        _event(round_no=2, actor="analyst"),
    ]
    payload = build_execution_log(events)
    assert payload["actors"] == ["Analyst", "Auditor"]
    assert payload["round_count"] == 2


def test_payload_reads_the_runs_events_not_an_empty_placeholder(monkeypatch):
    """The bug this pins: 20 events in the database, "no steps" on the surface.

    The first cut attached events only where the read model is built, which is
    not the path the payload the UI reads goes through. Assert against
    _agent_modules_payload itself -- the function every route actually calls.
    """
    import strategyos_mvp.api as api_module

    monkeypatch.setattr(
        api_module.state_store,
        "executive_snapshot_for_run",
        lambda run_id: {
            "status": "ok",
            "agent_events": [
                {
                    "round_no": 1,
                    "actor": "analyst",
                    "finding_id": "F-001",
                    "action": "raise_finding",
                    "detail": "Duplicate payment identified.",
                    "event_json": {"total_tokens": 900},
                }
            ],
        },
    )
    payload = api_module._agent_modules_payload(
        {"run_id": "c0ae93f3-c247-4b4e-8703-455dea985f4c"}, [], None, {"role": "ceo"}
    )
    log = payload["execution_log"]
    assert log["status"] == "available", "events exist in the run but the surface hid them"
    assert log["total_count"] == 1
    assert log["entries"][0]["actor"] == "Analyst"


def test_payload_states_absence_when_the_run_has_no_events(monkeypatch):
    import strategyos_mvp.api as api_module

    monkeypatch.setattr(
        api_module.state_store,
        "executive_snapshot_for_run",
        lambda run_id: {"status": "ok", "agent_events": []},
    )
    payload = api_module._agent_modules_payload({"run_id": "r-1"}, [], None, {"role": "ceo"})
    assert payload["execution_log"]["status"] == "unavailable"


def test_database_failure_does_not_take_the_page_down(monkeypatch):
    """The log is an accountability surface, not a load-bearing one."""
    import strategyos_mvp.api as api_module

    def _boom(run_id):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(api_module.state_store, "executive_snapshot_for_run", _boom)
    payload = api_module._agent_modules_payload({"run_id": "r-1"}, [], None, {"role": "ceo"})
    assert payload["execution_log"]["status"] == "unavailable"
