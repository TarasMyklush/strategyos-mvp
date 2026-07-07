"""Twin agent runtime — Observe → Orient → Decide → Act loop.

Each TwinRuntime wraps a persona and its persistent state, providing the
core autonomous cycle that powers a digital twin through wake/sleep
lifecycles.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from strategyos_mvp.config import load_config
from strategyos_mvp.twins.memory import (
    TwinState,
    add_investigation,
    add_to_history,
    resolve_investigation,
)
from strategyos_mvp.twins.persona import TwinPersona, lookup_persona
from strategyos_mvp.twins.protocol import (
    InterTwinMessage,
    RequestLifecycle,
    TwinResponse,
    check_escalation,
    escalate_message,
    get_escalation_timeout,
    validate_response,
)
from strategyos_mvp.twins.resolution import KPIResolutionEngine, KPI_TREE
from strategyos_mvp.twins.reasoning import (
    apply_model_guardrails,
    run_structured_reasoning,
)
from strategyos_mvp.twins.store import TwinRepositories, build_runtime_repositories
from strategyos_mvp.twins.strategyos_data import build_surface_payload, compose_investigation_payload
from strategyos_mvp.twins.tools import escalate_to_human, send_message

# ---------------------------------------------------------------------------
# Repository-backed message store
# ---------------------------------------------------------------------------


_DEFAULT_RUNTIME_REPOSITORIES = build_runtime_repositories()
_DEFAULT_RUNTIME_REPOSITORIES.kpis.ensure_seeded(KPI_TREE)


class _InboxProxy:
    """Compatibility wrapper for old tests that inspect `_INBOX.get(...)`."""

    def __init__(self, repositories: TwinRepositories) -> None:
        self._repositories = repositories

    def get(self, recipient_role: str, default: Any = None) -> list[dict[str, Any]]:
        messages = self._repositories.inboxes.load(recipient_role)
        if messages:
            return messages
        return [] if default is None else default


_INBOX = _InboxProxy(_DEFAULT_RUNTIME_REPOSITORIES)


def _deliver_to_inbox(
    recipient_role: str,
    message: dict[str, Any],
    repositories: TwinRepositories | None = None,
) -> None:
    """Place a message dict into the recipient's inbox."""
    repo_set = repositories or _DEFAULT_RUNTIME_REPOSITORIES
    repo_set.inboxes.append(recipient_role, message)


def _read_inbox(
    recipient_role: str,
    repositories: TwinRepositories | None = None,
) -> list[dict[str, Any]]:
    """Read and clear the inbox for a given role."""
    repo_set = repositories or _DEFAULT_RUNTIME_REPOSITORIES
    return repo_set.inboxes.consume(recipient_role)


def _peek_inbox(
    recipient_role: str,
    repositories: TwinRepositories | None = None,
) -> int:
    """Return the number of pending messages without consuming them."""
    repo_set = repositories or _DEFAULT_RUNTIME_REPOSITORIES
    return len(repo_set.inboxes.load(recipient_role))


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

    def __init__(
        self,
        persona: TwinPersona,
        state: TwinState,
        repositories: TwinRepositories | None = None,
    ) -> None:
        self.persona = persona
        self.state = state
        self._repositories = repositories or _DEFAULT_RUNTIME_REPOSITORIES
        self._repositories.kpis.ensure_seeded(KPI_TREE)
        self._resolver = KPIResolutionEngine(repository=self._repositories.kpis)
        self._cycle_summary: dict[str, Any] = {}

    def _persist_state(self) -> None:
        self._repositories.states.save(self.state.role, self.state)

    def _persist_investigation(self, inv_id: str) -> None:
        record = self.state.active_investigations.get(inv_id)
        if record is not None:
            self._repositories.investigations.save(self.state.role, record)

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _normalize_request_record(
        self,
        request_message_id: str,
        payload: Any,
        *,
        requester_role: str | None = None,
    ) -> dict[str, Any]:
        if isinstance(payload, dict):
            normalized = dict(payload)
            normalized.setdefault("request_message_id", request_message_id)
            normalized.setdefault("requester_role", requester_role or self.persona.role)
            normalized.setdefault("responder_role", "unknown")
            normalized.setdefault("status", "pending")
            normalized.setdefault("created_at", self._timestamp())
            normalized.setdefault("updated_at", normalized.get("created_at") or self._timestamp())
            normalized.setdefault("response_message_id", None)
            normalized.setdefault("acknowledged_at", None)
            normalized.setdefault("fulfilled_at", None)
            normalized.setdefault("failed_at", None)
            normalized.setdefault("expired_at", None)
            normalized.setdefault("subject", "")
            normalized.setdefault("data_payload", {})
            normalized.setdefault("gaps_remaining", [])
            normalized.setdefault("evidence_citations", [])
            return normalized
        return asdict(
            RequestLifecycle(
                request_message_id=request_message_id,
                requester_role=requester_role or self.persona.role,
                responder_role="unknown",
                status="pending",
                created_at=self._timestamp(),
                updated_at=self._timestamp(),
                subject=str(payload or ""),
            )
        )

    def _record_pending_request(self, msg: InterTwinMessage) -> dict[str, Any]:
        created_at = msg.created_at or self._timestamp()
        record = asdict(
            RequestLifecycle(
                request_message_id=msg.message_id,
                requester_role=msg.sender_role,
                responder_role=msg.recipient_role,
                status="pending",
                created_at=created_at,
                updated_at=created_at,
                subject=msg.subject,
                evidence_citations=tuple(msg.evidence_citations),
            )
        )
        self.state.pending_requests[msg.message_id] = record
        self._repositories.requests.save(self.persona.role, record)
        return record

    def _update_request_record(
        self,
        request_message_id: str,
        payload: dict[str, Any],
        *,
        role: str | None = None,
    ) -> dict[str, Any] | None:
        target_role = role or self.persona.role
        state_payload = self.state.pending_requests.get(request_message_id)
        if target_role != self.persona.role:
            stored_state = self._repositories.states.load(target_role) or {}
            state_pending = dict(stored_state.get("pending_requests") or {})
            state_payload = state_pending.get(request_message_id)
        if state_payload is None:
            state_payload = self._repositories.requests.load(target_role, request_message_id)
        if state_payload is None:
            return None

        record = self._normalize_request_record(
            request_message_id,
            state_payload,
            requester_role=target_role,
        )
        record.update(payload)
        record["updated_at"] = payload.get("updated_at") or self._timestamp()
        self._repositories.requests.save(target_role, record)

        if target_role == self.persona.role:
            if record.get("status") in {"fulfilled", "failed", "expired"}:
                self.state.pending_requests.pop(request_message_id, None)
            else:
                self.state.pending_requests[request_message_id] = record
            return record

        stored_state = self._repositories.states.load(target_role) or {}
        state_pending = dict(stored_state.get("pending_requests") or {})
        if record.get("status") in {"fulfilled", "failed", "expired"}:
            state_pending.pop(request_message_id, None)
        else:
            state_pending[request_message_id] = record
        stored_state["pending_requests"] = state_pending
        self._repositories.states.save(target_role, stored_state)
        return record

    def _reconcile_response_message(self, message: dict[str, Any]) -> bool:
        request_message_id = str(
            message.get("request_message_id")
            or message.get("parent_message_id")
            or ""
        )
        if not request_message_id:
            return False
        if request_message_id not in self.state.pending_requests and self._repositories.requests.load(
            self.persona.role,
            request_message_id,
        ) is None:
            return False

        response_payload = message.get("response") if isinstance(message.get("response"), dict) else {}
        data_payload = response_payload.get("data_provided") if isinstance(response_payload.get("data_provided"), dict) else {}
        gaps_remaining = list(response_payload.get("gaps_remaining") or [])
        if data_payload:
            status = "fulfilled"
        elif gaps_remaining:
            status = "failed"
        else:
            status = "acknowledged"
        now_iso = str(message.get("created_at") or self._timestamp())
        update_payload: dict[str, Any] = {
            "status": status,
            "response_message_id": message.get("message_id"),
            "data_payload": data_payload,
            "gaps_remaining": gaps_remaining,
            "evidence_citations": list(response_payload.get("evidence_citations") or message.get("evidence_citations") or []),
            "updated_at": now_iso,
        }
        if status == "acknowledged":
            update_payload["acknowledged_at"] = now_iso
        elif status == "fulfilled":
            update_payload["fulfilled_at"] = now_iso
        else:
            update_payload["failed_at"] = now_iso
        updated = self._update_request_record(request_message_id, update_payload)
        if updated is None:
            return False
        self.state.working_memory[f"request:{request_message_id}"] = {
            "status": status,
            "response_message_id": message.get("message_id"),
            "body": response_payload.get("body") or message.get("body"),
            "data": data_payload,
            "gaps_remaining": gaps_remaining,
        }
        add_to_history(
            self.state,
            {
                "role": self.persona.role,
                "action": f"request_{status}",
                "request_message_id": request_message_id,
                "response_message_id": message.get("message_id"),
                "from": message.get("sender_role"),
                "data_payload": data_payload,
                "gaps_remaining": gaps_remaining,
            },
        )
        return True

    def _extract_kpi_node_id(self, message: dict[str, Any]) -> str | None:
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        kpi_node_id = metadata.get("kpi_node_id")
        if kpi_node_id:
            return str(kpi_node_id)
        subject = str(message.get("subject") or "")
        prefix = "Data request: "
        if subject.startswith(prefix):
            return subject[len(prefix):].split(" — ", 1)[0].strip() or None
        return None

    def _build_response_for_message(self, message: dict[str, Any]) -> TwinResponse:
        now_iso = self._timestamp()
        request_message_id = str(message.get("message_id") or "")
        kpi_node_id = self._extract_kpi_node_id(message)
        data_provided: dict[str, Any] = {}
        gaps_remaining: list[str] = []
        confidence = "medium"
        body = "Received and investigating."
        if str(message.get("message_type") or "") == "data_request" and kpi_node_id:
            node = self._resolver.get_node(kpi_node_id)
            if node:
                data_provided = {
                    "kpi_node_id": kpi_node_id,
                    "node": node,
                }
            gaps_remaining = [
                str(gap.get("detail") or gap.get("type") or "unknown_gap")
                for gap in self._resolver.detect_gaps(kpi_node_id)
            ]
            if data_provided and not gaps_remaining:
                confidence = "high"
                body = f"Provided current data for KPI {kpi_node_id}."
            elif data_provided:
                confidence = "medium"
                body = f"Provided current snapshot for KPI {kpi_node_id}; some gaps remain."
            else:
                confidence = "unable"
                body = f"Could not resolve KPI {kpi_node_id}; explicit gaps remain."
        return TwinResponse(
            response_id=f"resp-{request_message_id}",
            request_message_id=request_message_id,
            responder_role=self.persona.role,
            body=body,
            confidence=confidence,
            data_provided=data_provided,
            gaps_remaining=tuple(gaps_remaining),
            created_at=now_iso,
        )

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
            "cycle_id": self._cycle_id,
            "wake_at": self.state.last_wake_at,
            "observations": [],
            "issues": [],
            "decisions": [],
            "actions": [],
            "errors": [],
            "reasoning_trace_ids": [],
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
            node = self._resolver.get_node(kpi_id)
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
        inbox_messages = _read_inbox(self.persona.role, self._repositories)
        observations["inbox"] = [
            message
            for message in inbox_messages
            if not self._reconcile_response_message(message)
        ]

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
        issues = self._build_deterministic_issues(observations)

        reasoning_context = self._reasoning_context(observations=observations, issues=issues)
        resolved_issues, trace = run_structured_reasoning(
            stage="orient",
            role=self.persona.role,
            cycle_id=self._cycle_id,
            input_context=reasoning_context,
            deterministic_output=issues,
            repositories=self._repositories,
            config=load_config(),
        )
        self._cycle_summary["reasoning_trace_ids"].append(trace["trace_id"])

        issues = resolved_issues

        # Register open investigations in state
        for idx, issue in enumerate(issues):
            inv_id = issue.get("investigation_id") or f"{self.persona.role}_issue_{self.state.cycle_count}_{idx}"
            issue["investigation_id"] = inv_id
            add_investigation(self.state, inv_id, issue)
            self._persist_investigation(inv_id)

        self._cycle_summary["issues"] = issues
        return issues

    def _build_deterministic_issues(self, observations: dict[str, Any]) -> list[dict[str, Any]]:
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
                "message": dict(msg),
                "resolution_hint": "respond",
            })

        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        issues.sort(key=lambda i: priority_order.get(i.get("priority", "normal"), 5))
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
        decisions = self._build_deterministic_decisions(issues)

        reasoning_context = self._reasoning_context(
            observations=self._cycle_summary.get("observations", {}),
            issues=issues,
            deterministic_decisions=decisions,
        )
        decided, trace = run_structured_reasoning(
            stage="decide",
            role=self.persona.role,
            cycle_id=self._cycle_id,
            input_context=reasoning_context,
            deterministic_output=decisions,
            repositories=self._repositories,
            config=load_config(),
        )
        self._cycle_summary["reasoning_trace_ids"].append(trace["trace_id"])

        for decision in decided:
            decision.setdefault("reasoning_trace_id", trace["trace_id"])
            decision.setdefault(
                "decision_source",
                "model" if trace.get("source") == "litellm" else "deterministic",
            )

        decisions = apply_model_guardrails(
            role=self.persona.role,
            decisions=decided,
            repositories=self._repositories,
            require_human_review=load_config().require_human_review,
        )

        self._cycle_summary["decisions"] = decisions
        return decisions

    def _build_deterministic_decisions(self, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                    "decision_source": "deterministic",
                })

            elif hint == "respond":
                decisions.append({
                    "investigation_id": inv_id,
                    "action": "respond_to_message",
                    "sender": issue.get("sender"),
                    "message_id": issue.get("message_id"),
                    "message": issue.get("message") or {},
                    "decision_source": "deterministic",
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
                    "decision_source": "deterministic",
                })
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
                        send_message(msg, repositories=self._repositories)
                        self._record_pending_request(msg)
                        action_record["message_id"] = msg.message_id
                        action_record["target"] = msg.recipient_role
                        action_record["request_status"] = "pending"
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

                elif action_type == "send_escalation":
                    msg = dec.get("message")
                    if msg:
                        send_message(msg, repositories=self._repositories)
                        self._record_pending_request(msg)
                        action_record["message_id"] = msg.message_id
                        action_record["target"] = msg.recipient_role
                        action_record["request_status"] = "pending"
                        add_to_history(
                            self.state,
                            {
                                "role": self.persona.role,
                                "action": "sent_escalation",
                                "message_id": msg.message_id,
                                "recipient": msg.recipient_role,
                                "subject": msg.subject,
                            },
                        )

                elif action_type == "respond_to_message":
                    sender = dec.get("sender", "unknown")
                    original_message = dec.get("message") or {}
                    response = self._build_response_for_message(original_message)
                    response_errors = validate_response(response)
                    if response_errors:
                        raise ValueError(f"Invalid twin response: {response_errors}")
                    response_message = InterTwinMessage(
                        message_id=response.response_id,
                        sender_role=self.persona.role,
                        recipient_role=sender,
                        message_type="response",
                        priority="normal",
                        subject=f"Response: {original_message.get('subject') or dec.get('message_id', 'message')}",
                        body=response.body,
                        evidence_citations=tuple(response.evidence_citations),
                        parent_message_id=response.request_message_id,
                        metadata={"request_message_id": response.request_message_id},
                        deadline_seconds=3600,
                        created_at=response.created_at,
                        status="responded",
                    )
                    send_message(
                        response_message,
                        repositories=self._repositories,
                        payload={
                            "response": asdict(response),
                            "request_message_id": response.request_message_id,
                        },
                    )
                    add_to_history(
                        self.state,
                        {
                            "role": self.persona.role,
                            "action": "acknowledged_message",
                            "to": sender,
                            "request_message_id": response.request_message_id,
                            "response_message_id": response.response_id,
                            "response": response.body,
                            "data_provided": response.data_provided,
                            "gaps_remaining": list(response.gaps_remaining),
                        },
                    )
                    action_record["target"] = sender
                    action_record["request_message_id"] = response.request_message_id
                    action_record["response_message_id"] = response.response_id
                    action_record["response"] = response.body
                    action_record["data_provided"] = response.data_provided
                    action_record["gaps_remaining"] = list(response.gaps_remaining)

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

                elif action_type == "request_human_review":
                    action_record["status"] = "pending_human_review"
                    action_record["review_record"] = dec.get("review_record")
                    action_record["reason"] = ((dec.get("guardrail") or {}).get("reason") or "")

                elif action_type == "noop":
                    action_record["status"] = "no_op"

                # Resolve the investigation
                if inv_id and inv_id in self.state.active_investigations:
                    resolution_status = "completed"
                    if action_type == "request_human_review":
                        resolution_status = "pending_human_review"
                    elif action_type == "noop":
                        resolution_status = "no_action"
                    resolve_investigation(
                        self.state,
                        inv_id,
                        {"action_taken": action_type, "status": resolution_status},
                    )
                    self._persist_investigation(inv_id)

            except Exception as exc:
                action_record["error"] = str(exc)
                self._cycle_summary["errors"].append(str(exc))

            actions.append(action_record)

        self._cycle_summary["actions"] = actions

    # ------------------------------------------------------------------
    # Escalation processing (Phase 2)
    # ------------------------------------------------------------------

    def process_escalations(self) -> list[InterTwinMessage]:
        """Check all pending inbox messages for timeout and escalate.

        Scans the twin's inbox for messages whose deadline has expired,
        creates escalation messages addressed to the next role in the
        sending twin's escalation path, and removes the expired messages
        from the inbox.

        Returns:
            A list of escalated :class:`InterTwinMessage` instances.
        """
        escalated: list[InterTwinMessage] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        inbox = self._repositories.inboxes.load(self.persona.role)
        expired_indices: list[int] = []

        for idx, msg_dict in enumerate(inbox):
            # Reconstruct an InterTwinMessage from the inbox dict
            msg = InterTwinMessage(
                message_id=msg_dict.get("message_id", ""),
                sender_role=msg_dict.get("sender_role", ""),
                recipient_role=msg_dict.get("recipient_role", ""),
                message_type=msg_dict.get("message_type", "data_request"),
                priority=msg_dict.get("priority", "normal"),
                subject=msg_dict.get("subject", ""),
                body=msg_dict.get("body", ""),
                deadline_seconds=msg_dict.get("deadline_seconds", 3600),
                created_at=msg_dict.get("created_at", now_iso),
                status=msg_dict.get("status", "pending"),
            )

            escalated_role = check_escalation(msg, now_iso)
            if escalated_role:
                esc_msg = escalate_message(msg, now_iso)
                escalated.append(esc_msg)
                self._update_request_record(
                    msg.message_id,
                    {
                        "status": "expired",
                        "expired_at": now_iso,
                        "response_message_id": esc_msg.message_id,
                        "updated_at": now_iso,
                    },
                    role=msg.sender_role,
                )
                expired_indices.append(idx)

        # Remove expired messages (reverse order to preserve indices)
        for idx in reversed(expired_indices):
            inbox.pop(idx)

        self._repositories.inboxes.save(self.persona.role, inbox)

        return escalated

    # ------------------------------------------------------------------
    # Full cycle
    # ------------------------------------------------------------------

    def run_once(self) -> dict[str, Any]:
        """Execute a complete Observe → Orient → Decide → Act cycle.

        Also calls :meth:`process_escalations` to handle timed-out
        pending messages during the cycle.

        Returns:
            A summary dict with the cycle results, suitable for logging
            or dashboard display.
        """
        self.wake()
        try:
            # Process escalations first — catch expired messages before
            # the inbox is consumed by observe()
            escalated = self.process_escalations()

            observations = self.observe()
            issues = self.orient(observations)
            decisions = self.decide(issues)

            if escalated:
                decisions.extend(
                    {
                        "investigation_id": f"esc-{e.message_id}",
                        "action": "send_escalation",
                        "message": e,
                        "target_role": e.recipient_role,
                    }
                    for e in escalated
                )

            self.act(decisions)
        except Exception as exc:
            self._cycle_summary["errors"].append(str(exc))
        finally:
            self.sleep()
            self._persist_state()

        return dict(self._cycle_summary)

    @property
    def _cycle_id(self) -> str:
        return f"{self.persona.role}-cycle-{max(1, self.state.cycle_count)}"

    def _reasoning_context(
        self,
        *,
        observations: dict[str, Any],
        issues: list[dict[str, Any]],
        deterministic_decisions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        query = str(self.state.working_memory.get("last_query") or "")
        strategyos_payload = (
            compose_investigation_payload(self.persona.role, query)
            if query
            else build_surface_payload(self.persona.role)
        )
        return {
            "role": self.persona.role,
            "cycle_id": self._cycle_id,
            "query": query,
            "observations": observations,
            "issues": issues,
            "deterministic_decisions": deterministic_decisions or [],
            "run_context": strategyos_payload.get("run_context") or {},
            "board": strategyos_payload.get("board") or {},
            "evidence_refs": strategyos_payload.get("evidence") or [],
            "bounded_fallback": bool(strategyos_payload.get("bounded_fallback", False)),
            "data_source": strategyos_payload.get("data_source"),
        }
