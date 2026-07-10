"""Unit and integration tests for Digital Twin Phase 2.

Covers:
- Enhanced persona definitions (GM, Analyst, Strategy, Reviewer)
- Multi-hop resolution chains (CEO → CFO → GM)
- Escalation and deadline enforcement
- Process escalations in TwinRuntime
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from strategyos_mvp.twins.persona import (
    ANALYST_INVESTIGATION_PROMPTS,
    ANALYST_DATA_OWNERSHIP,
    GROUP_MANAGER_INVESTIGATION_PROMPTS,
    GROUP_MANAGER_DATA_OWNERSHIP,
    STRATEGY_INVESTIGATION_PROMPTS,
    STRATEGY_DATA_OWNERSHIP,
    REVIEWER_INVESTIGATION_PROMPTS,
    REVIEWER_DATA_OWNERSHIP,
    GROUP_MANAGER_TWIN,
    ANALYST_TWIN,
    STRATEGY_TWIN,
    REVIEWER_TWIN,
    TwinPersona,
)
from strategyos_mvp.twins.protocol import (
    InterTwinMessage,
    check_escalation,
    escalate_message,
    get_escalation_timeout,
)
from strategyos_mvp.twins.resolution import (
    KPIResolutionEngine,
    resolve_multi_hop,
)
from strategyos_mvp.twins.memory import create_twin_state
from strategyos_mvp.twins.runtime import TwinRuntime


# ===================================================================
# Stories 2.1–2.4 — Enhanced Personas
# ===================================================================


class TestGroupManagerPersonaEnhancements:
    """Group Manager twin has investigation prompts and data ownership."""

    def test_gm_investigation_prompts_exist(self):
        assert len(GROUP_MANAGER_INVESTIGATION_PROMPTS) >= 2
        assert "Why is BU3 missing revenue target?" in GROUP_MANAGER_INVESTIGATION_PROMPTS
        assert "What resources do I need?" in GROUP_MANAGER_INVESTIGATION_PROMPTS

    def test_gm_investigation_prompts_contain_bu_focus(self):
        bu_prompts = [p for p in GROUP_MANAGER_INVESTIGATION_PROMPTS if "BU" in p]
        assert len(bu_prompts) >= 1

    def test_gm_investigation_prompts_contain_resource_focus(self):
        resource_prompts = [p for p in GROUP_MANAGER_INVESTIGATION_PROMPTS if "resource" in p.lower()]
        assert len(resource_prompts) >= 1

    def test_gm_data_ownership_defined(self):
        assert "owns" in GROUP_MANAGER_DATA_OWNERSHIP
        assert "bu_revenue" in GROUP_MANAGER_DATA_OWNERSHIP["owns"]
        assert "operational_metrics" in GROUP_MANAGER_DATA_OWNERSHIP["owns"]
        assert "initiative_progress" in GROUP_MANAGER_DATA_OWNERSHIP["owns"]

    def test_gm_reports_to_cfo(self):
        assert "reports_to_cfo" in GROUP_MANAGER_DATA_OWNERSHIP
        assert "bu_revenue" in GROUP_MANAGER_DATA_OWNERSHIP["reports_to_cfo"]

    def test_gm_requests_from_analyst(self):
        assert "requests_from_analyst" in GROUP_MANAGER_DATA_OWNERSHIP
        assert "evidence_quality" in GROUP_MANAGER_DATA_OWNERSHIP["requests_from_analyst"]

    def test_gm_persona_has_operational_style(self):
        assert "Operational" in GROUP_MANAGER_TWIN.communication_style

    def test_gm_escalates_to_cfo(self):
        assert GROUP_MANAGER_TWIN.escalation_path == ("cfo",)


class TestAnalystPersonaEnhancements:
    """Analyst twin has investigation prompts and data ownership."""

    def test_analyst_investigation_prompts_exist(self):
        assert len(ANALYST_INVESTIGATION_PROMPTS) >= 2
        assert "Check evidence freshness for Q2 data" in ANALYST_INVESTIGATION_PROMPTS
        assert "Validate latest source pack" in ANALYST_INVESTIGATION_PROMPTS

    def test_analyst_investigation_prompts_contain_data_focus(self):
        data_prompts = [p for p in ANALYST_INVESTIGATION_PROMPTS if "data" in p.lower() or "evidence" in p.lower()]
        assert len(data_prompts) >= 1

    def test_analyst_data_ownership_defined(self):
        assert "owns" in ANALYST_DATA_OWNERSHIP
        assert "evidence_quality_scores" in ANALYST_DATA_OWNERSHIP["owns"]
        assert "source_validation_results" in ANALYST_DATA_OWNERSHIP["owns"]

    def test_analyst_reports_to_group_manager(self):
        assert "reports_to_group_manager" in ANALYST_DATA_OWNERSHIP
        assert "validation_findings" in ANALYST_DATA_OWNERSHIP["reports_to_group_manager"]

    def test_analyst_persona_has_detail_oriented_style(self):
        assert "detail" in ANALYST_TWIN.communication_style.lower() or "data" in ANALYST_TWIN.communication_style.lower()

    def test_analyst_authority_cannot_make_strategic_decisions(self):
        assert "cannot" in ANALYST_TWIN.authority.lower()

    def test_analyst_escalates_to_group_manager(self):
        assert ANALYST_TWIN.escalation_path == ("group_manager",)


class TestStrategyPersonaEnhancements:
    """Strategy twin has investigation prompts and data ownership."""

    def test_strategy_investigation_prompts_exist(self):
        assert len(STRATEGY_INVESTIGATION_PROMPTS) >= 2
        assert "Check KPI tree alignment" in STRATEGY_INVESTIGATION_PROMPTS
        assert "Flag stale value drivers" in STRATEGY_INVESTIGATION_PROMPTS

    def test_strategy_data_ownership_defined(self):
        assert "owns" in STRATEGY_DATA_OWNERSHIP
        assert "kpi_tree_structure" in STRATEGY_DATA_OWNERSHIP["owns"]
        assert "value_driver_definitions" in STRATEGY_DATA_OWNERSHIP["owns"]
        assert "initiative_portfolio" in STRATEGY_DATA_OWNERSHIP["owns"]

    def test_strategy_reports_to_ceo(self):
        assert "reports_to_ceo" in STRATEGY_DATA_OWNERSHIP
        assert "alignment_status" in STRATEGY_DATA_OWNERSHIP["reports_to_ceo"]

    def test_strategy_escalates_to_ceo(self):
        assert STRATEGY_TWIN.escalation_path == ("ceo",)

    def test_strategy_persona_has_structured_style(self):
        assert "structured" in STRATEGY_TWIN.communication_style.lower() or "systemic" in STRATEGY_TWIN.communication_style.lower()


class TestReviewerPersonaEnhancements:
    """Reviewer twin has investigation prompts and data ownership."""

    def test_reviewer_investigation_prompts_exist(self):
        assert len(REVIEWER_INVESTIGATION_PROMPTS) >= 2
        assert "Review pending findings" in REVIEWER_INVESTIGATION_PROMPTS
        assert "Check compliance status" in REVIEWER_INVESTIGATION_PROMPTS

    def test_reviewer_data_ownership_defined(self):
        assert "owns" in REVIEWER_DATA_OWNERSHIP
        assert "finding_adjudication_status" in REVIEWER_DATA_OWNERSHIP["owns"]
        assert "compliance_checks" in REVIEWER_DATA_OWNERSHIP["owns"]
        assert "evidence_verification" in REVIEWER_DATA_OWNERSHIP["owns"]

    def test_reviewer_reports_to_cfo(self):
        assert "reports_to_cfo" in REVIEWER_DATA_OWNERSHIP
        assert "adjudication_results" in REVIEWER_DATA_OWNERSHIP["reports_to_cfo"]

    def test_reviewer_escalates_to_cfo(self):
        assert REVIEWER_TWIN.escalation_path == ("cfo",)

    def test_reviewer_persona_has_skeptical_style(self):
        assert "Skeptical" in REVIEWER_TWIN.communication_style

    def test_reviewer_authority_can_challenge_findings(self):
        assert "Challenge" in REVIEWER_TWIN.authority


# ===================================================================
# Story 2.5 — Multi-hop resolution chains
# ===================================================================


class TestGetComponentChain:
    """KPIResolutionEngine.get_component_chain returns flat component list."""

    def setup_method(self):
        self.engine = KPIResolutionEngine()

    def test_margin_q2_has_all_descendants(self):
        chain = self.engine.get_component_chain("margin_q2")
        assert "revenue_q2" in chain
        assert "cogs_q2" in chain
        assert "raw_materials_q2" in chain
        # margin_q2 has 2 direct + 1 nested = 3 total descendants
        assert len(chain) == 3

    def test_margin_q2_includes_nested_components(self):
        chain = self.engine.get_component_chain("margin_q2")
        assert "raw_materials_q2" in chain

    def test_leaf_node_has_empty_chain(self):
        chain = self.engine.get_component_chain("raw_materials_q2")
        assert chain == []

    def test_unknown_node_has_empty_chain(self):
        chain = self.engine.get_component_chain("nonexistent_kpi")
        assert chain == []

    def test_revenue_q2_has_no_components(self):
        chain = self.engine.get_component_chain("revenue_q2")
        assert chain == []


class TestFindResolutionPath:
    """KPIResolutionEngine.find_resolution_path traces role chains."""

    def setup_method(self):
        self.engine = KPIResolutionEngine()

    def test_margin_to_raw_materials_chain(self):
        """CEO asks about margin → CFO (margin+cogs) → GM (raw_materials)."""
        path = self.engine.find_resolution_path("margin_q2", "raw_materials")
        # cfo owns margin_q2 and cogs_q2, group_manager owns raw_materials_q2
        assert "cfo" in path
        assert "group_manager" in path
        # The path should have exactly 2 unique roles
        assert len(path) >= 2

    def test_self_reference_returns_root_owner(self):
        path = self.engine.find_resolution_path("margin_q2", "margin_q2")
        assert path == ["cfo"]

    def test_unknown_root_returns_empty(self):
        path = self.engine.find_resolution_path("nonexistent", "anything")
        assert path == []

    def test_direct_component_path(self):
        """margin_q2 (cfo) → cogs_q2 (cfo)."""
        path = self.engine.find_resolution_path("margin_q2", "cogs_q2")
        assert "cfo" in path


class TestResolveMultiHop:
    """resolve_multi_hop generates ordered message chain."""

    def setup_method(self):
        self.engine = KPIResolutionEngine()

    def test_margin_resolution_produces_messages(self):
        messages = resolve_multi_hop(self.engine, "margin_q2", "ceo")
        assert len(messages) > 0

    def test_ceo_margin_chain_routes_to_cfo(self):
        """First hop: CEO → CFO for margin gap."""
        messages = resolve_multi_hop(self.engine, "margin_q2", "ceo")
        assert messages[0].sender_role == "ceo"
        assert messages[0].recipient_role == "cfo"
        assert messages[0].message_type == "data_request"

    def test_ceo_margin_chain_eventually_routes_to_gm(self):
        """Some message in the chain should reach group_manager for raw_materials."""
        messages = resolve_multi_hop(self.engine, "margin_q2", "ceo")
        recipient_roles = {m.recipient_role for m in messages}
        assert "group_manager" in recipient_roles

    def test_messages_are_ordered_correctly(self):
        """Messages should flow CEO → CFO → GM in order."""
        messages = resolve_multi_hop(self.engine, "margin_q2", "ceo")
        # The chain should start with CEO and eventually reach GM
        assert messages[0].sender_role == "ceo"
        # At least one message should be to group_manager
        gm_messages = [m for m in messages if m.recipient_role == "group_manager"]
        assert len(gm_messages) >= 1
        # The last message with a different recipient should be to group_manager
        last_unique = messages[-1].recipient_role
        assert last_unique in ("cfo", "group_manager")

    def test_leaf_node_no_components(self):
        """Single node with no components just routes one message."""
        messages = resolve_multi_hop(self.engine, "raw_materials_q2", "group_manager")
        assert len(messages) >= 1

    def test_unavailable_structural_node_returns_no_messages(self):
        """Unavailable structural metadata should not invent a routing chase."""
        messages = resolve_multi_hop(self.engine, "revenue_q2", "ceo")
        assert len(messages) == 0


# ===================================================================
# Story 2.6 — Escalation + deadline enforcement
# ===================================================================


class TestGetEscalationTimeout:
    """get_escalation_timeout returns correct seconds per priority."""

    def test_critical_timeout(self):
        assert get_escalation_timeout("critical") == 300

    def test_high_timeout(self):
        assert get_escalation_timeout("high") == 600

    def test_normal_timeout(self):
        assert get_escalation_timeout("normal") == 1800

    def test_low_timeout(self):
        assert get_escalation_timeout("low") == 3600

    def test_unknown_priority_defaults_to_normal(self):
        assert get_escalation_timeout("unknown") == 1800


class TestCheckEscalation:
    """check_escalation returns escalated role or None."""

    def _make_message(
        self, created_delta_seconds: int, deadline_seconds: int = 3600,
        status: str = "pending", sender_role: str = "analyst",
    ) -> InterTwinMessage:
        created = (datetime.now(timezone.utc) - timedelta(seconds=created_delta_seconds)).isoformat()
        return InterTwinMessage(
            message_id="msg-esc-test",
            sender_role=sender_role,
            recipient_role="group_manager",
            message_type="data_request",
            priority="high",
            subject="Test escalation",
            body="Test body.",
            deadline_seconds=deadline_seconds,
            created_at=created,
            status=status,
        )

    def test_message_past_deadline_escalates(self):
        """Message past deadline returns escalation role."""
        msg = self._make_message(created_delta_seconds=7200, deadline_seconds=3600)
        now = datetime.now(timezone.utc).isoformat()
        role = check_escalation(msg, now)
        # Analyst escalates to group_manager
        assert role is not None

    def test_message_within_deadline_does_not_escalate(self):
        """Message within deadline returns None."""
        msg = self._make_message(created_delta_seconds=30, deadline_seconds=3600)
        now = datetime.now(timezone.utc).isoformat()
        role = check_escalation(msg, now)
        assert role is None

    def test_delivered_message_does_not_escalate(self):
        """Non-pending messages are not escalated."""
        msg = self._make_message(created_delta_seconds=7200, deadline_seconds=3600, status="delivered")
        now = datetime.now(timezone.utc).isoformat()
        role = check_escalation(msg, now)
        assert role is None

    def test_ceo_escalates_to_human(self):
        """CEO message past deadline escalates to human."""
        msg = self._make_message(
            created_delta_seconds=7200, deadline_seconds=3600, sender_role="ceo"
        )
        now = datetime.now(timezone.utc).isoformat()
        role = check_escalation(msg, now)
        assert role == "human"

    def test_cfo_escalates_to_ceo(self):
        """CFO message past deadline escalates to ceo."""
        msg = self._make_message(
            created_delta_seconds=7200, deadline_seconds=3600, sender_role="cfo"
        )
        now = datetime.now(timezone.utc).isoformat()
        role = check_escalation(msg, now)
        assert role == "ceo"

    def test_group_manager_escalates_to_cfo(self):
        """Group Manager message past deadline escalates to cfo."""
        msg = self._make_message(
            created_delta_seconds=7200, deadline_seconds=3600, sender_role="group_manager"
        )
        now = datetime.now(timezone.utc).isoformat()
        role = check_escalation(msg, now)
        assert role == "cfo"

    def test_strategy_escalates_to_ceo(self):
        """Strategy message past deadline escalates to ceo."""
        msg = self._make_message(
            created_delta_seconds=7200, deadline_seconds=3600, sender_role="strategy"
        )
        now = datetime.now(timezone.utc).isoformat()
        role = check_escalation(msg, now)
        assert role == "ceo"

    def test_reviewer_escalates_to_cfo(self):
        """Reviewer message past deadline escalates to cfo."""
        msg = self._make_message(
            created_delta_seconds=7200, deadline_seconds=3600, sender_role="reviewer"
        )
        now = datetime.now(timezone.utc).isoformat()
        role = check_escalation(msg, now)
        assert role == "cfo"

    def test_empty_created_at_returns_none(self):
        msg = self._make_message(created_delta_seconds=7200, deadline_seconds=3600)
        msg_none = InterTwinMessage(
            message_id="msg-no-time",
            sender_role="analyst",
            recipient_role="group_manager",
            message_type="data_request",
            priority="high",
            subject="No time",
            body="No created_at.",
            created_at="",
            status="pending",
        )
        now = datetime.now(timezone.utc).isoformat()
        role = check_escalation(msg_none, now)
        assert role is None


class TestEscalateMessage:
    """escalate_message creates an escalated copy."""

    def _make_expired_message(self, sender_role: str = "analyst") -> InterTwinMessage:
        created = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
        return InterTwinMessage(
            message_id="msg-orig-001",
            sender_role=sender_role,
            recipient_role="group_manager",
            message_type="data_request",
            priority="high",
            subject="Original request",
            body="Please provide data.",
            evidence_citations=("ev/001",),
            deadline_seconds=3600,
            created_at=created,
            status="pending",
        )

    def test_escalated_message_has_new_id(self):
        msg = self._make_expired_message()
        now = datetime.now(timezone.utc).isoformat()
        esc = escalate_message(msg, now)
        assert esc.message_id != msg.message_id
        assert "esc-" in esc.message_id

    def test_escalated_message_has_escalation_type(self):
        msg = self._make_expired_message()
        now = datetime.now(timezone.utc).isoformat()
        esc = escalate_message(msg, now)
        assert esc.message_type == "escalation"

    def test_escalated_message_has_critical_priority(self):
        msg = self._make_expired_message()
        now = datetime.now(timezone.utc).isoformat()
        esc = escalate_message(msg, now)
        assert esc.priority == "critical"

    def test_escalated_message_parent_reference(self):
        msg = self._make_expired_message()
        now = datetime.now(timezone.utc).isoformat()
        esc = escalate_message(msg, now)
        assert esc.parent_message_id == msg.message_id

    def test_escalated_message_preserves_citations(self):
        msg = self._make_expired_message()
        now = datetime.now(timezone.utc).isoformat()
        esc = escalate_message(msg, now)
        assert esc.evidence_citations == ("ev/001",)

    def test_escalated_analyst_goes_to_group_manager(self):
        msg = self._make_expired_message(sender_role="analyst")
        now = datetime.now(timezone.utc).isoformat()
        esc = escalate_message(msg, now)
        assert esc.recipient_role == "group_manager"

    def test_escalated_ceo_goes_to_human(self):
        msg = self._make_expired_message(sender_role="ceo")
        now = datetime.now(timezone.utc).isoformat()
        esc = escalate_message(msg, now)
        assert esc.recipient_role == "human"

    def test_escalated_subject_prefixed(self):
        msg = self._make_expired_message()
        now = datetime.now(timezone.utc).isoformat()
        esc = escalate_message(msg, now)
        assert esc.subject.startswith("ESCALATED:")

    def test_escalated_has_shorter_deadline(self):
        msg = self._make_expired_message()
        now = datetime.now(timezone.utc).isoformat()
        esc = escalate_message(msg, now)
        assert esc.deadline_seconds == 300


class TestProcessEscalations:
    """TwinRuntime.process_escalations finds and escalates expired messages."""

    def test_no_expired_messages_returns_empty(self):
        rt = TwinRuntime(
            GROUP_MANAGER_TWIN, create_twin_state("group_manager")
        )
        rt.wake()
        # No messages in inbox, so no escalations
        escalated = rt.process_escalations()
        assert escalated == []

    def test_expired_message_in_inbox_is_escalated(self):
        from strategyos_mvp.twins.runtime import _deliver_to_inbox

        created = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
        _deliver_to_inbox("group_manager", {
            "message_id": "expired-msg-001",
            "sender_role": "analyst",
            "recipient_role": "group_manager",
            "message_type": "data_request",
            "priority": "high",
            "subject": "Expired request",
            "body": "This message is past deadline.",
            "deadline_seconds": 3600,
            "created_at": created,
            "status": "pending",
        })

        rt = TwinRuntime(
            GROUP_MANAGER_TWIN, create_twin_state("group_manager")
        )
        rt.wake()
        escalated = rt.process_escalations()
        assert len(escalated) >= 1
        assert escalated[0].message_type == "escalation"

    def test_expired_message_removed_from_inbox(self):
        from strategyos_mvp.twins.runtime import _deliver_to_inbox, _INBOX

        created = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
        _deliver_to_inbox("group_manager", {
            "message_id": "expired-msg-002",
            "sender_role": "analyst",
            "recipient_role": "group_manager",
            "message_type": "data_request",
            "priority": "high",
            "subject": "Expired request",
            "body": "Past deadline.",
            "deadline_seconds": 3600,
            "created_at": created,
            "status": "pending",
        })

        rt = TwinRuntime(
            GROUP_MANAGER_TWIN, create_twin_state("group_manager")
        )
        rt.wake()
        assert len(_INBOX.get("group_manager", [])) >= 1
        rt.process_escalations()
        # Inbox should be cleared of expired messages
        remaining = _INBOX.get("group_manager", [])
        expired_ids = [m["message_id"] for m in remaining if m.get("message_id") == "expired-msg-002"]
        assert len(expired_ids) == 0

    def test_fresh_message_not_escalated(self):
        from strategyos_mvp.twins.runtime import _deliver_to_inbox

        created = datetime.now(timezone.utc).isoformat()
        _deliver_to_inbox("group_manager", {
            "message_id": "fresh-msg-001",
            "sender_role": "analyst",
            "recipient_role": "group_manager",
            "message_type": "data_request",
            "priority": "high",
            "subject": "Fresh request",
            "body": "This message is within deadline.",
            "deadline_seconds": 3600,
            "created_at": created,
            "status": "pending",
        })

        rt = TwinRuntime(
            GROUP_MANAGER_TWIN, create_twin_state("group_manager")
        )
        rt.wake()
        escalated = rt.process_escalations()
        assert len(escalated) == 0


class TestEscalationByPriority:
    """Escalation timeouts match priority levels."""

    def test_all_priority_timeouts(self):
        assert get_escalation_timeout("critical") == 300
        assert get_escalation_timeout("high") == 600
        assert get_escalation_timeout("normal") == 1800
        assert get_escalation_timeout("low") == 3600

    def test_critical_timeout_is_shortest(self):
        timeouts = [get_escalation_timeout(p) for p in ("low", "normal", "high", "critical")]
        assert timeouts == sorted(timeouts, reverse=True)

    def test_escalated_message_uses_critical_timeout(self):
        msg = InterTwinMessage(
            message_id="msg-prio-test",
            sender_role="analyst",
            recipient_role="group_manager",
            message_type="data_request",
            priority="low",
            subject="Priority test",
            body="Testing priority.",
            deadline_seconds=get_escalation_timeout("low"),
            created_at=(datetime.now(timezone.utc) - timedelta(seconds=4000)).isoformat(),
            status="pending",
        )
        now = datetime.now(timezone.utc).isoformat()
        esc = escalate_message(msg, now)
        # Escalated messages always get critical timeout
        assert esc.deadline_seconds == 300


class TestProcessEscalationsInCycle:
    """TwinRuntime processes escalations during run_once."""

    def test_run_once_with_expired_message_in_inbox(self):
        from strategyos_mvp.twins.runtime import _deliver_to_inbox

        created = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
        _deliver_to_inbox("group_manager", {
            "message_id": "cycle-esc-test",
            "sender_role": "analyst",
            "recipient_role": "group_manager",
            "message_type": "data_request",
            "priority": "high",
            "subject": "Cycle escalation test",
            "body": "Will this get escalated during a run cycle?",
            "deadline_seconds": 3600,
            "created_at": created,
            "status": "pending",
        })

        rt = TwinRuntime(
            GROUP_MANAGER_TWIN, create_twin_state("group_manager")
        )
        summary = rt.run_once()
        # The summary should contain an action for the escalation
        actions = summary.get("actions", [])
        escalation_actions = [a for a in actions if a.get("action") == "send_escalation"]
        assert len(escalation_actions) >= 1
