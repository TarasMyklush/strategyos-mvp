"""Acceptance tests for Digital Twin Phase 4 — Full UI.

Verifies:
- CEO dashboard HTML contains all required sections
- CFO dashboard HTML contains financial KPI cards and pending approvals
- GM dashboard HTML contains BU cards and initiative tracker
- All dashboards have conversation view markup
- All dashboards have human override controls
- HTML files exist and are non-empty
"""

from __future__ import annotations

from pathlib import Path

import pytest

TWINS_STATIC = (
    Path(__file__).resolve().parent.parent
    / "strategyos_mvp"
    / "twins"
    / "static"
)


# ===================================================================
# File existence
# ===================================================================


class TestFileExistence:
    """All three dashboard files exist and are non-empty."""

    def test_ceo_html_exists(self):
        assert (TWINS_STATIC / "ceo.html").exists()

    def test_cfo_html_exists(self):
        assert (TWINS_STATIC / "cfo.html").exists()

    def test_gm_html_exists(self):
        assert (TWINS_STATIC / "gm.html").exists()

    def test_ceo_html_non_empty(self):
        content = (TWINS_STATIC / "ceo.html").read_text(encoding="utf-8")
        assert len(content) > 1000

    def test_cfo_html_non_empty(self):
        content = (TWINS_STATIC / "cfo.html").read_text(encoding="utf-8")
        assert len(content) > 1000

    def test_gm_html_non_empty(self):
        content = (TWINS_STATIC / "gm.html").read_text(encoding="utf-8")
        assert len(content) > 1000


# ===================================================================
# Story 4.1 — CEO Dashboard contents
# ===================================================================


class TestCEODashboardSections:
    """CEO dashboard has all required sections."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.html = (TWINS_STATIC / "ceo.html").read_text(encoding="utf-8")

    def test_has_status_bar(self):
        assert "Twin Status Bar" in self.html or "status-bar" in self.html
        assert "Cycles" in self.html
        assert "Last Wake" in self.html

    def test_has_kpi_health(self):
        assert "Oracle-backed financial rings" in self.html
        assert "Revenue attainment ring" in self.html
        assert "EBITDA margin ring" in self.html
        assert "Cash vs board floor" in self.html
        assert "Covenant headroom" in self.html

    def test_has_kpi_status_dots(self):
        assert self.html.count("kpi-dot green") >= 4
        assert self.html.count("kpi-dot") >= 6
        assert self.html.count("kpi-status current") >= 4

    def test_has_investigations(self):
        assert "Active Investigations" in self.html
        assert "progress-bar" in self.html
        assert "Assignee:" in self.html

    def test_has_decision_queue(self):
        assert "Decision Queue" in self.html
        assert "Approve" in self.html or "btn-approve" in self.html
        assert "Reject" in self.html or "btn-reject" in self.html

    def test_has_inbox(self):
        assert "Inbox" in self.html
        assert "CFO Assistant" in self.html
        assert "priority-badge" in self.html

    def test_has_ask_input(self):
        assert "Ask Your Twin" in self.html
        assert "query-input" in self.html
        assert "prompt-suggestions" in self.html

    def test_has_autocomplete(self):
        assert "autocomplete-dropdown" in self.html
        assert "AUTOCOMPLETE_SUGGESTIONS" in self.html

    def test_has_response_panel(self):
        assert "response-box" in self.html
        assert "CEO surface is ready" in self.html

    def test_has_conversation_view(self):
        assert "thread-view" in self.html
        assert "toggleThread" in self.html
        assert "citation-link" in self.html

    def test_has_human_override(self):
        assert "Human Override" in self.html
        assert "Redirect Investigation" in self.html
        assert "audit-log" in self.html
        assert "redirectInvestigation" in self.html
        assert "escalateDecision" in self.html


# ===================================================================
# Story 4.2 — CFO Dashboard contents
# ===================================================================


class TestCFODashboardSections:
    """CFO dashboard has financial KPIs and pending approvals."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.html = (TWINS_STATIC / "cfo.html").read_text(encoding="utf-8")

    def test_has_financial_kpi_cards(self):
        assert "Oracle-first finance cockpit" in self.html
        assert "Revenue attainment" in self.html
        assert "EBITDA margin" in self.html
        assert "Cash vs board floor" in self.html
        assert "Covenant headroom" in self.html
        assert "Cash conversion cycle" in self.html

    def test_has_pending_approvals(self):
        assert "Pending Approvals" in self.html
        assert "Budget" in self.html
        assert "Approve" in self.html
        assert "Reject" in self.html

    def test_has_cash_monitoring(self):
        assert "Oracle ingestion &amp; reconciliation context" in self.html
        assert "cash-bar" in self.html
        assert "Oracle cash vs floor:" in self.html
        assert "Board floor baseline:" in self.html

    def test_has_investigations(self):
        assert "Active Investigations" in self.html
        assert "progress-bar" in self.html
        assert "Assignee:" in self.html

    def test_has_inbox(self):
        assert "Inbox" in self.html
        assert "CEO Assistant" in self.html

    def test_has_ask_input(self):
        assert "Ask Your CFO" in self.html
        assert "query-input" in self.html
        assert "prompt-suggestions" in self.html

    def test_has_conversation_view(self):
        assert "thread-view" in self.html
        assert "toggleThread" in self.html
        assert "citation-link" in self.html

    def test_has_human_override(self):
        assert "Human Override" in self.html
        assert "Redirect Investigation" in self.html
        assert "audit-log" in self.html

    def test_has_status_bar(self):
        assert "status-bar" in self.html
        assert "Cycles" in self.html
        assert "Last Wake" in self.html

    def test_has_kpi_dots(self):
        assert self.html.count("kpi-dot green") >= 4
        assert self.html.count("kpi-dot") >= 5
        assert self.html.count("kpi-status current") >= 4


# ===================================================================
# Story 4.3 — GM Dashboard contents
# ===================================================================


class TestGMDashboardSections:
    """GM dashboard has BU cards and initiative tracker."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.html = (TWINS_STATIC / "gm.html").read_text(encoding="utf-8")

    def test_has_bu_cards(self):
        assert "BU Performance Overview" in self.html
        assert "North America" in self.html
        assert "Europe" in self.html
        assert "APAC" in self.html
        assert "Customer NPS" in self.html
        assert "Operational Efficiency" in self.html

    def test_has_initiative_tracker(self):
        assert "Initiative Tracker" in self.html
        assert "on track" in self.html or "on-track" in self.html
        assert "at risk" in self.html or "at-risk" in self.html

    def test_has_resource_requests(self):
        assert "Resource Requests" in self.html
        assert "awaiting CFO" in self.html

    def test_has_escalations(self):
        assert "Escalations" in self.html
        assert "Analyst Assistant" in self.html
        assert "Strategy Assistant" in self.html

    def test_has_investigations(self):
        assert "Active Investigations" in self.html
        assert "progress-bar" in self.html

    def test_has_inbox(self):
        assert "Inbox" in self.html
        assert "CEO Assistant" in self.html
        assert "CFO Assistant" in self.html

    def test_has_ask_input(self):
        assert "Ask Your GM" in self.html
        assert "query-input" in self.html
        assert "prompt-suggestions" in self.html

    def test_has_conversation_view(self):
        assert "thread-view" in self.html
        assert "toggleThread" in self.html
        assert "citation-link" in self.html

    def test_has_human_override(self):
        assert "Human Override" in self.html
        assert "Redirect Investigation" in self.html
        assert "audit-log" in self.html

    def test_has_status_bar(self):
        assert "status-bar" in self.html
        assert "Active Initiatives" in self.html
        assert "Escalations" in self.html

    def test_has_kpi_dots(self):
        assert "kpi-dot green" in self.html
        assert "kpi-dot amber" in self.html


# ===================================================================
# Story 4.4 — Conversation views on all dashboards
# ===================================================================


class TestConversationViews:
    """All dashboards have conversation thread markup."""

    def test_ceo_has_thread_elements(self):
        html = (TWINS_STATIC / "ceo.html").read_text(encoding="utf-8")
        assert "thread-view" in html
        assert "thread-message" in html
        assert "thread-message__role" in html
        assert "thread-message__body" in html
        assert "thread-message__citations" in html
        assert "thread-message__status-badge" in html
        assert "toggleThread" in html
        assert "citation-link" in html
        # Multiple thread sections for different messages
        assert html.count("thread-view") >= 4
        assert html.count("thread-message") >= 6

    def test_cfo_has_thread_elements(self):
        html = (TWINS_STATIC / "cfo.html").read_text(encoding="utf-8")
        assert "thread-view" in html
        assert "thread-message" in html
        assert "thread-message__role" in html
        assert "thread-message__body" in html
        assert "thread-message__citations" in html
        assert "toggleThread" in html
        assert "citation-link" in html
        assert html.count("thread-view") >= 3
        assert html.count("thread-message") >= 4

    def test_gm_has_thread_elements(self):
        html = (TWINS_STATIC / "gm.html").read_text(encoding="utf-8")
        assert "thread-view" in html
        assert "thread-message" in html
        assert "thread-message__role" in html
        assert "thread-message__body" in html
        assert "thread-message__citations" in html
        assert "toggleThread" in html
        assert "citation-link" in html
        assert html.count("thread-view") >= 3
        assert html.count("thread-message") >= 4


# ===================================================================
# Story 4.5 — Human override controls on all dashboards
# ===================================================================


class TestHumanOverride:
    """All dashboards have human override controls."""

    def test_ceo_human_override(self):
        html = (TWINS_STATIC / "ceo.html").read_text(encoding="utf-8")
        assert "Human Override" in html
        assert "Redirect Investigation" in html
        assert "redirect-input" in html
        assert "redirect-target-input" in html
        assert "redirectInvestigation" in html
        assert "Escalate" in html or "escalate-input" in html
        assert "escalateDecision" in html
        assert "audit-log" in html
        assert "audit-entry" in html
        assert "Decision Audit Trail" in html
        assert "addAuditEntry" in html
        # Approve/Reject buttons on decision items
        assert "btn-approve" in html
        assert "btn-reject" in html
        assert "approveDecision" in html
        assert "rejectDecision" in html
        # Console logging stub
        assert "console.log" in html
        assert "Human Override" in html

    def test_cfo_human_override(self):
        html = (TWINS_STATIC / "cfo.html").read_text(encoding="utf-8")
        assert "Human Override" in html
        assert "Redirect Investigation" in html
        assert "redirect-input" in html
        assert "redirectInvestigation" in html
        assert "escalateDecision" in html
        assert "audit-log" in html
        assert "Decision Audit Trail" in html
        assert "btn-approve" in html
        assert "btn-reject" in html
        assert "approveDecision" in html
        assert "rejectDecision" in html
        assert "console.log" in html

    def test_gm_human_override(self):
        html = (TWINS_STATIC / "gm.html").read_text(encoding="utf-8")
        assert "Human Override" in html
        assert "Redirect Investigation" in html
        assert "redirect-input" in html
        assert "redirectInvestigation" in html
        assert "escalateDecision" in html
        assert "audit-log" in html
        assert "Decision Audit Trail" in html
        assert "console.log" in html

    def test_approve_disables_buttons(self):
        """Approve button disables decision after use."""
        html = (TWINS_STATIC / "ceo.html").read_text(encoding="utf-8")
        assert "disabled = true" in html

    def test_reject_disables_buttons(self):
        """Reject button disables decision after use."""
        html = (TWINS_STATIC / "cfo.html").read_text(encoding="utf-8")
        assert "disabled = true" in html

    def test_audit_trail_max_entries(self):
        """Audit trail enforces maximum entry count."""
        html = (TWINS_STATIC / "ceo.html").read_text(encoding="utf-8")
        assert "children.length > 20" in html

    def test_escalate_alerts_on_empty(self):
        """Escalate shows alert when input is empty."""
        html = (TWINS_STATIC / "ceo.html").read_text(encoding="utf-8")
        assert "alert(" in html
