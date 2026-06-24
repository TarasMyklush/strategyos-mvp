"""Twin agent runtime — Observe → Orient → Decide → Act loop.

Each TwinRuntime wraps a persona and its persistent state, providing the
core autonomous cycle that powers a digital twin through wake/sleep
lifecycles.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from strategyos_mvp.twins.memory import (
    TwinState,
    add_investigation,
    add_to_history,
    resolve_investigation,
)
from strategyos_mvp.twins.persona import TwinPersona, lookup_persona
from strategyos_mvp.twins.resolution import KPIResolutionEngine, KPI_TREE
from strategyos_mvp.twins.tools import (
    escalate_to_human,
    query_kpi,
    send_message,
)

# ---------------------------------------------------------------------------
# Global in-memory message store (Phase 1 — no database yet)
# ---------------------------------------------------------------------------

_INBOX: dict[str, list[dict[str, Any]]] = {}
"""Global message inbox keyed by recipient role.

Each entry is a list of message dicts (deserialised InterTwinMessage or
plain notification dicts). Twins read from their own inbox slot during
the Observe phase.
"""


def _deliver_to_inbox(recipient_role: str, message: dict[str, Any]) -> None:
    """Place a message dict into the recipient's inbox."""
    if recipient_role not in _INBOX:
        _INBOX[recipient_role] = []
    _INBOX[recipient_role].append(message)


def _read_inbox(recipient_role: str) -> list[dict[str, Any]]:
    """Read and clear the inbox for a given role."""
    return _INBOX.pop(recipient_role, [])


def _peek_inbox(recipient_role: str) -> int:
    """Return the number of pending messages without consuming them."""
    return len(_INBOX.get(recipient_role, []))


# ---------------------------------------------------------------------------
# TwinRuntime
# ---------------------------------------------------------------------------


class TwinRuntime:
    """Autonomous twin agent with a full Observe → Orient → Decide → Act cycle.

    Typical usage::

        rt = TwinRuntime(CEO_TWIN, create_twin_state("ceo"))
        summary = rt.run_once()

    Args:
        persona: The :class:`TwinPersona` defining this twin's role.
        state: The :class:`TwinState` for this twin instance.
    """

    def __init__(self, persona: TwinPersona, state: TwinState) -> None:
        self.persona = persona
        self.state = state
        self._resolver = KPIResolutionEngine()
        self._cycle_summary: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def wake(self) -> None:
        """Load state from the previous sleep and begin a new cycle.

        Increments the cycle counter and records the wake timestamp
        in working memory.
        """
        self.state.cycle_count += 1
        self.state.last_wake_at = datetime.now(timezone.utc).isoformat()
        self.state.working_memory["wake_at"] = self.state.last_wake_at
        self._cycle_summary = {
            "role": self.persona.role,
            "cycle": self.state.cycle_count,
            "wake_at": self.state.last_wake_at,
            "observations": [],
            "issues": [],
            "decisions": [],
            "actions": [],
            "errors": [],
        }

    def sleep(self) -> None:
        """Finalise the cycle and persist state.

        Updates ``last_wake_at`` and clears transient working memory
        flags. The caller is responsible for calling :func:`save_state`
        to persist to disk.
        """
        self.state.last_wake_at = datetime.now(timezone.utc).isoformat()
        self._cycle_summary["slept_at"] = self.state.last_wake_at

    # ------------------------------------------------------------------
    # OODA steps
    # ------------------------------------------------------------------

    def observe(self) -> dict[str, Any]:
        """Gather observations from the twin's environment.

        Checks:
        1. Owned KPIs via the resolution engine.
        2. Inbox messages from other twins.

        Returns:
            A dict with keys:
            - ``kpis``: list of KPI observation dicts
            - ``inbox``: list of received message dicts
        """
        observations: dict[str, Any] = {"kpis": [], "inbox": []}

        # 1. Check owned KPIs
        for kpi_id in self.persona.kpis_owned:
            node = KPI_TREE.get(kpi_id)
            if node:
                observations["kpis"].append({
                    "node_id": kpi_id,
                    "status": node.get("status", "unknown"),
                    "value": node.get("value"),
                    "owner": node.get("owner"),
                })
            else:
                observations["kpis"].append({
                    "node_id": kpi_id,
                    "status": "unknown",
                    "value": None,
                    "owner": None,
                })

        # 2. Read inbox
        inbox_messages = _read_inbox(self.persona.role)
        observations["inbox"] = inbox_messages

        self._cycle_summary["observations"] = observations
        return observations

    def orient(self, observations: dict[str, Any]) -> list[dict[str, Any]]:
        """Analyse observations and produce a prioritised list of issues.

        For each owned KPI:
        - Runs the resolution engine's gap detection.
        - If gaps are found, each gap becomes an issue.

        For each inbox message:
        - Creates an issue to respond to the sender.

        Args:
            observations: The dict returned by :meth:`observe`.

        Returns:
            A list of issue dicts, each with ``type``, ``priority``,
            ``kpi_node_id`` (if applicable), ``detail``, and
            ``resolution`` hints.
        """
        issues: list[dict[str, Any]] = []

        # KPI gaps
        for kpi_obs in observations.get("kpis", []):
            kpi_id = kpi_obs["node_id"]
            gaps = self._resolver.detect_gaps(kpi_id)
            for gap in gaps:
                priority = "high" if gap.get("type") in (
                    "missing_data", "missing_value"
                ) else "normal"
                issues.append({
                    "type": "kpi_gap",
                    "priority": priority,
                    "kpi_node_id": kpi_id,
                    "detail": gap.get("detail", ""),
                    "owner": gap.get("owner"),
                    "resolution_hint": "request_data",
                })

        # Inbox messages
        for msg in observations.get("inbox", []):
            sender = msg.get("sender_role", "unknown")
            subject = msg.get("subject", "No subject")
            issues.append({
                "type": "inbox_message",
                "priority": msg.get("priority", "normal"),
                "kpi_node_id": None,
                "detail": f"Message from {sender}: {subject}",
                "sender": sender,
                "message_id": msg.get("message_id"),
                "resolution_hint": "respond",
            })

        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        issues.sort(key=lambda i: priority_order.get(i.get("priority", "normal"), 5))

        # Register open investigations in state
        for idx, issue in enumerate(issues):
            inv_id = f"{self.persona.role}_issue_{self.state.cycle_count}_{idx}"
            issue["investigation_id"] = inv_id
            add_investigation(self.state, inv_id, issue)

        self._cycle_summary["issues"] = issues
        return issues

    def decide(self, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Decide on actions for each prioritised issue.

        For each issue:
        - ``request_data``: create a data_request to the KPI owner
        - ``respond``: prepare a response to the inbox sender
        - Unknown resolution hints trigger an escalation.

        Args:
            issues: The list returned by :meth:`orient`.

        Returns:
            A list of decision dicts, each with ``issue`` reference,
            ``action`` type, and the action payload.
        """
        decisions: list[dict[str, Any]] = []

        for issue in issues:
            hint = issue.get("resolution_hint", "")
            inv_id = issue.get("investigation_id", "")

            if hint == "request_data":
                kpi_id = issue.get("kpi_node_id", "")
                if not kpi_id:
                    continue
                gaps = self._resolver.detect_gaps(kpi_id)
                if not gaps:
                    continue
                msg = self._resolver.route_request(
                    kpi_node_id=kpi_id,
                    gap=gaps[0],
                    requestor_role=self.persona.role,
                )
                decisions.append({
                    "investigation_id": inv_id,
                    "action": "send_data_request",
                    "message": msg,
                    "target_role": msg.recipient_role,
                })

            elif hint == "respond":
                decisions.append({
                    "investigation_id": inv_id,
                    "action": "respond_to_message",
                    "sender": issue.get("sender"),
                    "message_id": issue.get("message_id"),
                    "preliminary_response": (
                        f"Acknowledging message {issue.get('message_id')}. "
                        f"Investigating the request."
                    ),
                })

            else:
                # Unknown issue type — escalate
                decisions.append({
                    "investigation_id": inv_id,
                    "action": "escalate",
                    "reason": (
                        f"Unknown issue type {issue.get('type')!r} "
                        f"for {issue.get('kpi_node_id', 'N/A')}"
                    ),
                    "context": issue,
                })

        self._cycle_summary["decisions"] = decisions
        return decisions

    def act(self, decisions: list[dict[str, Any]]) -> None:
        """Execute each decision.

        - ``send_data_request``: send the InterTwinMessage and record
          in pending_requests.
        - ``respond_to_message``: send an acknowledgment message back
          to the original sender.
        - ``escalate``: call :func:`tools.escalate_to_human`.

        Args:
            decisions: The list returned by :meth:`decide`.
        """
        actions: list[dict[str, Any]] = []

        for dec in decisions:
            action_type = dec.get("action", "")
            inv_id = dec.get("investigation_id", "")
            action_record: dict[str, Any] = {
                "action": action_type,
                "investigation_id": inv_id,
            }

            try:
                if action_type == "send_data_request":
                    msg = dec.get("message")
                    if msg:
                        send_message(msg)
                        self.state.pending_requests[msg.message_id] = (
                            f"waiting for {msg.recipient_role}"
                        )
                        action_record["message_id"] = msg.message_id
                        action_record["target"] = msg.recipient_role
                        add_to_history(
                            self.state,
                            {
                                "role": self.persona.role,
                                "action": "sent_data_request",
                                "message_id": msg.message_id,
                                "recipient": msg.recipient_role,
                                "subject": msg.subject,
                            },
                        )
                        # Also deliver to the recipient's inbox
                        _deliver_to_inbox(
                            msg.recipient_role,
                            {
                                "message_id": msg.message_id,
                                "sender_role": msg.sender_role,
                                "recipient_role": msg.recipient_role,
                                "message_type": msg.message_type,
                                "priority": msg.priority,
                                "subject": msg.subject,
                                "body": msg.body,
                            },
                        )

                elif action_type == "respond_to_message":
                    sender = dec.get("sender", "unknown")
                    response_body = dec.get(
                        "preliminary_response",
                        "Received and investigating.",
                    )
                    add_to_history(
                        self.state,
                        {
                            "role": self.persona.role,
                            "action": "acknowledged_message",
                            "to": sender,
                            "response": response_body,
                        },
                    )
                    # Deliver acknowledgment to the original sender's inbox
                    _deliver_to_inbox(
                        sender,
                        {
                            "message_id": f"ack-{dec.get('message_id', 'unknown')}",
                            "sender_role": self.persona.role,
                            "recipient_role": sender,
                            "message_type": "notification",
                            "priority": "normal",
                            "subject": f"Re: {dec.get('message_id', 'message')}",
                            "body": response_body,
                        },
                    )
                    action_record["target"] = sender
                    action_record["response"] = response_body

                elif action_type == "escalate":
                    reason = dec.get("reason", "No reason provided")
                    context = dec.get("context", {})
                    escalate_to_human(reason, context)
                    add_to_history(
                        self.state,
                        {
                            "role": self.persona.role,
                            "action": "escalated_to_human",
                            "reason": reason,
                        },
                    )
                    action_record["reason"] = reason

                # Resolve the investigation
                if inv_id and inv_id in self.state.active_investigations:
                    resolve_investigation(
                        self.state,
                        inv_id,
                        {"action_taken": action_type, "status": "completed"},
                    )

            except Exception as exc:
                action_record["error"] = str(exc)
                self._cycle_summary["errors"].append(str(exc))

            actions.append(action_record)

        self._cycle_summary["actions"] = actions

    # ------------------------------------------------------------------
    # Full cycle
    # ------------------------------------------------------------------

    def run_once(self) -> dict[str, Any]:
        """Execute a complete Observe → Orient → Decide → Act cycle.

        Returns:
            A summary dict with the cycle results, suitable for logging
            or dashboard display.
        """
        self.wake()
        try:
            observations = self.observe()
            issues = self.orient(observations)
            decisions = self.decide(issues)
            self.act(decisions)
        except Exception as exc:
            self._cycle_summary["errors"].append(str(exc))
        finally:
            self.sleep()

        return dict(self._cycle_summary)
