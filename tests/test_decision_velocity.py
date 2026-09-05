from datetime import datetime, timezone
from strategyos_mvp.decision_velocity import summarize


def test_approval_is_not_execution_and_open_ages_remain_visible():
    records = [{"decision_key": "a", "surfaced_at": "2026-01-01T08:00:00Z", "decided_at": "2026-01-01T10:00:00Z"},
               {"decision_key": "b", "surfaced_at": "2026-01-01T08:00:00Z", "decided_at": "2026-01-01T12:00:00Z",
                "first_action_at": "2026-01-01T13:00:00Z", "action_evidence_verified": True}]
    result = summarize(records, now=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert result["median_surfaced_to_decided_hours"] == 3
    assert result["median_decided_to_acted_hours"] == 1
    assert result["action_sample_count"] == 1
    assert result["pending"][0]["age_hours"] == 14
    records[1]["action_evidence_verified"] = False
    assert summarize(records)["median_decided_to_acted_hours"] is None


def test_missing_times_are_not_zero_and_invalid_order_does_not_improve_score():
    result = summarize([{"decision_key": "invalid", "surfaced_at": "2026-01-02T00:00:00Z", "decided_at": "2026-01-01T00:00:00Z"}])
    assert result["median_surfaced_to_decided_hours"] is None
    assert result["invalid_chronology"] == ["invalid"]
