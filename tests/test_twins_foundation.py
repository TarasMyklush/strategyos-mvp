"""Unit tests for the Digital Twin foundation layer (Phase 0).

Covers persona definitions, protocol validation, state persistence,
conversation history, investigation lifecycle, and tool stubs.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

from strategyos_mvp.twins.persona import (
    ANALYST_TWIN,
    CEO_TWIN,
    CFO_TWIN,
    GROUP_MANAGER_TWIN,
    REVIEWER_TWIN,
    STRATEGY_TWIN,
    TWIN_CATALOG,
    TwinPersona,
    lookup_persona,
)
from strategyos_mvp.twins.protocol import (
    InterTwinMessage,
    TwinResponse,
    validate_message,
    validate_response,
    should_escalate,
)
from strategyos_mvp.twins.memory import (
    TwinState,
    create_twin_state,
    save_state,
    load_state,
    add_to_history,
    add_investigation,
    resolve_investigation,
)
from strategyos_mvp.twins.tools import (
    check_health,
    send_message,
    escalate_to_human,
)


# ===================================================================
# Story 0.1 — TwinPersona model and role definitions
# ===================================================================


class TestPersonaInstantiation:
    """TwinPersona can be instantiated for all 6 roles."""

    def test_ceo_twin_is_frozen_dataclass(self):
        assert isinstance(CEO_TWIN, TwinPersona)
        assert CEO_TWIN.role == "ceo"
        assert CEO_TWIN.display_name == "CEO Twin"
        assert "human" in CEO_TWIN.escalation_path

    def test_cfo_twin_escalates_to_ceo(self):
        assert isinstance(CFO_TWIN, TwinPersona)
        assert CFO_TWIN.role == "cfo"
        assert CFO_TWIN.escalation_path == ("ceo",)

    def test_group_manager_twin_escalates_to_cfo(self):
        assert isinstance(GROUP_MANAGER_TWIN, TwinPersona)
        assert GROUP_MANAGER_TWIN.role == "group_manager"
        assert GROUP_MANAGER_TWIN.escalation_path == ("cfo",)

    def test_strategy_twin_reports_to_ceo(self):
        assert isinstance(STRATEGY_TWIN, TwinPersona)
        assert STRATEGY_TWIN.role == "strategy"
        assert STRATEGY_TWIN.escalation_path == ("ceo",)

    def test_analyst_twin_reports_to_group_manager(self):
        assert isinstance(ANALYST_TWIN, TwinPersona)
        assert ANALYST_TWIN.role == "analyst"
        assert ANALYST_TWIN.escalation_path == ("group_manager",)

    def test_reviewer_twin_reports_to_cfo(self):
        assert isinstance(REVIEWER_TWIN, TwinPersona)
        assert REVIEWER_TWIN.role == "reviewer"
        assert REVIEWER_TWIN.escalation_path == ("cfo",)

    def test_all_personas_have_goals(self):
        for persona in TWIN_CATALOG.values():
            assert len(persona.goals) > 0, f"{persona.role} has no goals"

    def test_all_personas_have_authority(self):
        for persona in TWIN_CATALOG.values():
            assert len(persona.authority) > 0, f"{persona.role} has no authority"

    def test_all_personas_have_communication_style(self):
        for persona in TWIN_CATALOG.values():
            assert len(persona.communication_style) > 0, (
                f"{persona.role} has no communication_style"
            )

    def test_twin_persona_is_frozen(self):
        with pytest.raises(AttributeError):
            CEO_TWIN.role = "something_else"  # type: ignore[misc]


class TestTwinCatalog:
    """TWIN_CATALOG contains all 6 roles."""

    def test_catalog_has_exactly_six_unique_roles(self):
        # 7 keys in catalog: 6 roles + 1 alias (gm → group_manager)
        unique_roles = set(v.display_name for v in TWIN_CATALOG.values())
        assert len(unique_roles) == 6

    def test_catalog_keys(self):
        expected_roles = {"ceo", "cfo", "group_manager", "gm", "strategy", "analyst", "reviewer"}
        assert set(TWIN_CATALOG.keys()) == expected_roles

    def test_catalog_values_are_twin_persona_instances(self):
        for persona in TWIN_CATALOG.values():
            assert isinstance(persona, TwinPersona)

    def test_catalog_contains_ceo(self):
        assert TWIN_CATALOG["ceo"] is CEO_TWIN

    def test_catalog_contains_cfo(self):
        assert TWIN_CATALOG["cfo"] is CFO_TWIN

    def test_catalog_contains_group_manager(self):
        assert TWIN_CATALOG["group_manager"] is GROUP_MANAGER_TWIN

    def test_catalog_contains_strategy(self):
        assert TWIN_CATALOG["strategy"] is STRATEGY_TWIN

    def test_catalog_contains_analyst(self):
        assert TWIN_CATALOG["analyst"] is ANALYST_TWIN

    def test_catalog_contains_reviewer(self):
        assert TWIN_CATALOG["reviewer"] is REVIEWER_TWIN

    def test_lookup_persona_found(self):
        assert lookup_persona("ceo") is CEO_TWIN
        assert lookup_persona("CFO") is CFO_TWIN
        assert lookup_persona("Group_Manager") is GROUP_MANAGER_TWIN

    def test_lookup_persona_not_found(self):
        assert lookup_persona("unknown_role") is None
        assert lookup_persona("") is None

    def test_each_role_owns_kpis(self):
        for role, persona in TWIN_CATALOG.items():
            assert len(persona.kpis_owned) > 0, f"{role} owns no KPIs"


# ===================================================================
# Story 0.2 — InterTwinMessage protocol
# ===================================================================


class TestInterTwinMessageValidation:
    """InterTwinMessage validation catches invalid fields."""

    def _make_valid_message(self, **overrides) -> InterTwinMessage:
        defaults = dict(
            message_id="msg-001",
            sender_role="ceo",
            recipient_role="cfo",
            message_type="data_request",
            priority="high",
            subject="Q2 margin data needed",
            body="Please provide Q2 gross margin breakdown by BU.",
            evidence_citations=("ev/cfo/001",),
            parent_message_id=None,
            deadline_seconds=3600,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="pending",
        )
        defaults.update(overrides)
        return InterTwinMessage(**defaults)

    def test_valid_message_passes(self):
        msg = self._make_valid_message()
        errors = validate_message(msg)
        assert errors == []

    def test_missing_message_id(self):
        errors = validate_message(self._make_valid_message(message_id=""))
        assert any("message_id" in e for e in errors)

    def test_missing_sender_role(self):
        errors = validate_message(self._make_valid_message(sender_role=""))
        assert any("sender_role" in e for e in errors)

    def test_missing_recipient_role(self):
        errors = validate_message(self._make_valid_message(recipient_role=""))
        assert any("recipient_role" in e for e in errors)

    def test_same_sender_and_recipient(self):
        errors = validate_message(
            self._make_valid_message(sender_role="ceo", recipient_role="ceo")
        )
        assert any("must differ" in e for e in errors)

    def test_invalid_message_type(self):
        errors = validate_message(self._make_valid_message(message_type="invalid_type"))
        assert any("message_type" in e for e in errors)

    def test_invalid_priority(self):
        errors = validate_message(self._make_valid_message(priority="ultra"))
        assert any("priority" in e for e in errors)

    def test_missing_subject(self):
        errors = validate_message(self._make_valid_message(subject=""))
        assert any("subject" in e for e in errors)

    def test_missing_body(self):
        errors = validate_message(self._make_valid_message(body=""))
        assert any("body" in e for e in errors)

    def test_invalid_status(self):
        errors = validate_message(self._make_valid_message(status="bogus"))
        assert any("status" in e for e in errors)

    def test_negative_deadline(self):
        errors = validate_message(self._make_valid_message(deadline_seconds=-1))
        assert any("deadline_seconds" in e for e in errors)

    def test_multiple_validation_errors(self):
        msg = InterTwinMessage(
            message_id="",
            sender_role="",
            recipient_role="",
            message_type="bad_type",
            priority="bad_prio",
            subject="",
            body="",
        )
        errors = validate_message(msg)
        assert len(errors) >= 5


class TestTwinResponseValidation:
    """TwinResponse validation works correctly."""

    def test_valid_response_passes(self):
        resp = TwinResponse(
            response_id="resp-001",
            request_message_id="msg-001",
            responder_role="cfo",
            body="Here is the margin breakdown.",
        )
        errors = validate_response(resp)
        assert errors == []

    def test_missing_response_id(self):
        resp = TwinResponse(
            response_id="",
            request_message_id="msg-001",
            responder_role="cfo",
            body="Here is the margin breakdown.",
        )
        errors = validate_response(resp)
        assert any("response_id" in e for e in errors)

    def test_missing_request_message_id(self):
        resp = TwinResponse(
            response_id="resp-001",
            request_message_id="",
            responder_role="cfo",
            body="Here is the margin breakdown.",
        )
        errors = validate_response(resp)
        assert any("request_message_id" in e for e in errors)

    def test_missing_responder_role(self):
        resp = TwinResponse(
            response_id="resp-001",
            request_message_id="msg-001",
            responder_role="",
            body="Here is the margin breakdown.",
        )
        errors = validate_response(resp)
        assert any("responder_role" in e for e in errors)

    def test_missing_body(self):
        resp = TwinResponse(
            response_id="resp-001",
            request_message_id="msg-001",
            responder_role="cfo",
            body="",
        )
        errors = validate_response(resp)
        assert any("body" in e for e in errors)

    def test_invalid_confidence(self):
        resp = TwinResponse(
            response_id="resp-001",
            request_message_id="msg-001",
            responder_role="cfo",
            body="Some data.",
            confidence="certain",
        )
        errors = validate_response(resp)
        assert any("confidence" in e for e in errors)


class TestShouldEscalate:
    """Escalation timeout logic."""

    def test_pending_message_past_deadline_escalates(self):
        created = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
        msg = InterTwinMessage(
            message_id="msg-001",
            sender_role="analyst",
            recipient_role="group_manager",
            message_type="data_request",
            priority="high",
            subject="Data needed",
            body="Need refreshed data.",
            deadline_seconds=3600,
            created_at=created,
            status="pending",
        )
        assert should_escalate(msg) is True

    def test_pending_message_within_deadline_does_not_escalate(self):
        created = datetime.now(timezone.utc).isoformat()
        msg = InterTwinMessage(
            message_id="msg-002",
            sender_role="analyst",
            recipient_role="group_manager",
            message_type="data_request",
            priority="high",
            subject="Data needed",
            body="Need refreshed data.",
            deadline_seconds=3600,
            created_at=created,
            status="pending",
        )
        assert should_escalate(msg) is False

    def test_delivered_message_does_not_escalate_even_past_deadline(self):
        created = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
        msg = InterTwinMessage(
            message_id="msg-003",
            sender_role="analyst",
            recipient_role="group_manager",
            message_type="data_request",
            priority="high",
            subject="Data needed",
            body="Need refreshed data.",
            deadline_seconds=3600,
            created_at=created,
            status="delivered",
        )
        assert should_escalate(msg) is False

    def test_no_created_at_returns_false(self):
        msg = InterTwinMessage(
            message_id="msg-004",
            sender_role="analyst",
            recipient_role="group_manager",
            message_type="data_request",
            priority="high",
            subject="Data needed",
            body="Need refreshed data.",
            deadline_seconds=3600,
            created_at="",
            status="pending",
        )
        assert should_escalate(msg) is False

    def test_malformed_timestamp_returns_false(self):
        msg = InterTwinMessage(
            message_id="msg-005",
            sender_role="analyst",
            recipient_role="group_manager",
            message_type="data_request",
            priority="high",
            subject="Data needed",
            body="Need refreshed data.",
            deadline_seconds=3600,
            created_at="not-a-timestamp",
            status="pending",
        )
        assert should_escalate(msg) is False

    def test_escalate_with_explicit_current_time(self):
        created = "2026-06-24T00:00:00+00:00"
        current = "2026-06-24T02:00:00+00:00"
        msg = InterTwinMessage(
            message_id="msg-006",
            sender_role="analyst",
            recipient_role="group_manager",
            message_type="data_request",
            priority="high",
            subject="Data needed",
            body="Need refreshed data.",
            deadline_seconds=3600,
            created_at=created,
            status="pending",
        )
        assert should_escalate(msg, current_time=current) is True


# ===================================================================
# Story 0.3 — TwinState persistence
# ===================================================================


class TestTwinStateCreation:
    """TwinState creation and initialization."""

    def test_create_ceo_state(self):
        state = create_twin_state("ceo")
        assert state.role == "ceo"
        assert state.twin_id.startswith("ceo_twin_")
        assert state.active_investigations == {}
        assert state.pending_requests == {}
        assert state.conversation_history == []
        assert state.cycle_count == 0
        assert state.last_wake_at is None

    def test_create_cfo_state(self):
        state = create_twin_state("cfo")
        assert state.role == "cfo"
        assert state.twin_id.startswith("cfo_twin_")

    def test_create_unknown_role_raises_keyerror(self):
        with pytest.raises(KeyError):
            create_twin_state("nonexistent_role")


class TestTwinStatePersistence:
    """Save/load roundtrip for TwinState."""

    def test_save_and_load_roundtrip(self, tmp_path: Path):
        original = create_twin_state("ceo")
        original.cycle_count = 42
        original.last_wake_at = "2026-06-24T12:00:00+00:00"
        original.working_memory["last_query"] = "Q2 margin"
        original.pending_requests["msg-001"] = "waiting for CFO"
        add_investigation(original, "inv-001", {"kpi": "margin_q2"})

        path = tmp_path / "ceo_state.json"
        save_state(original, path)

        assert path.exists()
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["role"] == "ceo"
        assert raw["cycle_count"] == 42

        loaded = load_state(path)
        assert loaded.role == "ceo"
        assert loaded.twin_id == original.twin_id
        assert loaded.cycle_count == 42
        assert loaded.last_wake_at == "2026-06-24T12:00:00+00:00"
        assert loaded.working_memory["last_query"] == "Q2 margin"
        assert loaded.pending_requests["msg-001"] == "waiting for CFO"
        assert "inv-001" in loaded.active_investigations

    def test_save_state_creates_valid_json(self, tmp_path: Path):
        state = create_twin_state("analyst")
        path = tmp_path / "analyst_state.json"
        save_state(state, path)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["role"] == "analyst"
        assert isinstance(data["cycle_count"], int)
        assert isinstance(data["active_investigations"], dict)

    def test_load_empty_state(self, tmp_path: Path):
        path = tmp_path / "empty.json"
        path.write_text(
            json.dumps({"twin_id": "", "role": "ceo"}), encoding="utf-8"
        )
        state = load_state(path)
        assert state.role == "ceo"
        assert state.active_investigations == {}


class TestConversationHistory:
    """Conversation history management with cap."""

    def test_add_to_history_prepends(self):
        state = create_twin_state("ceo")
        add_to_history(state, {"role": "user", "content": "first"})
        add_to_history(state, {"role": "user", "content": "second"})
        assert state.conversation_history[0]["content"] == "second"
        assert state.conversation_history[1]["content"] == "first"

    def test_history_capped_at_100(self):
        state = create_twin_state("ceo")
        for i in range(150):
            add_to_history(state, {"index": i})
        assert len(state.conversation_history) == 100
        assert state.conversation_history[0]["index"] == 149
        assert state.conversation_history[99]["index"] == 50


class TestInvestigationLifecycle:
    """Add and resolve investigations."""

    def test_add_investigation(self):
        state = create_twin_state("cfo")
        add_investigation(state, "inv-001", {"kpi": "revenue_q2", "trigger": "manual"})
        assert "inv-001" in state.active_investigations
        entry = state.active_investigations["inv-001"]
        assert entry["status"] == "open"
        assert entry["context"]["kpi"] == "revenue_q2"

    def test_resolve_investigation(self):
        state = create_twin_state("cfo")
        add_investigation(state, "inv-001", {"kpi": "revenue_q2"})
        resolution = {"finding": "Revenue Q2 resolved", "value": 1000000.0}
        resolve_investigation(state, "inv-001", resolution)
        entry = state.active_investigations["inv-001"]
        assert entry["status"] == "resolved"
        assert entry["resolution"]["value"] == 1000000.0
        assert "resolved_at" in entry

    def test_resolve_nonexistent_investigation_raises(self):
        state = create_twin_state("ceo")
        with pytest.raises(KeyError):
            resolve_investigation(state, "inv-nonexistent", {})


# ===================================================================
# Story 0.4 — Tool stubs
# ===================================================================


class TestTools:
    """Tool stubs return expected shapes."""

    def test_check_health_returns_dict_with_status(self):
        result = check_health()
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] in ("healthy", "degraded")

    def test_check_health_has_subsystems(self):
        result = check_health()
        assert "subsystems" in result
        assert "twin_catalog" in result["subsystems"]

    def test_send_message_does_not_crash(self, capsys):
        msg = InterTwinMessage(
            message_id="msg-test",
            sender_role="ceo",
            recipient_role="cfo",
            message_type="notification",
            priority="normal",
            subject="Test message",
            body="Testing the send_message stub.",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        send_message(msg)
        captured = capsys.readouterr()
        assert "TWIN MESSAGE" in captured.out

    def test_escalate_to_human_does_not_crash(self, capsys):
        escalate_to_human("Test escalation", {"key": "value"})
        captured = capsys.readouterr()
        assert "HUMAN ESCALATION" in captured.out
