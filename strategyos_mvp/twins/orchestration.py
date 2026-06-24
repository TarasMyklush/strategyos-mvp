"""Orchestration & Scheduling for the Digital Twin system.

Phase 3 adds scheduled review cycles, event-driven KPI triggers,
governance gates, board packet generation, and cycle audit history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from strategyos_mvp.twins.memory import add_investigation
from strategyos_mvp.twins.persona import lookup_persona
from strategyos_mvp.twins.resolution import KPI_TREE, KPIResolutionEngine
from strategyos_mvp.twins.runtime import TwinRuntime


# ===================================================================
# Story 3.1 — CycleScheduler
# ===================================================================


class CycleScheduler:
    """Scheduled review cycles that wake twins and coordinate their work.

    For now, cycles are callable functions (no actual cron). They will
    be connected to Hatchet / APScheduler in production.

    Args:
        twins: Mapping of role → :class:`TwinRuntime` instance.
    """

    def __init__(self, twins: dict[str, TwinRuntime]) -> None:
        self._twins = dict(twins)
        self._scheduled_cycles: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Review cycles
    # ------------------------------------------------------------------

    def run_daily_standup(self) -> dict[str, Any]:
        """Wake all twins, each checks its KPIs, reports status.

        Returns:
            A summary dict keyed by role, each value being the twin's
            cycle summary.
        """
        results: dict[str, Any] = {}
        for role, twin in self._twins.items():
            summary = twin.run_once()
            results[role] = {
                "role": role,
                "cycle": summary.get("cycle"),
                "wake_at": summary.get("wake_at"),
                "observations": summary.get("observations"),
                "issues": summary.get("issues"),
                "actions": summary.get("actions"),
                "errors": summary.get("errors"),
            }
        return results

    def run_weekly_review(self) -> dict[str, Any]:
        """Deep review: each twin runs full OODA cycle, resolves gaps,
        and generates a report.

        Returns:
            Findings per role with resolution status.
        """
        engine = KPIResolutionEngine()
        findings: dict[str, Any] = {}

        for role, twin in self._twins.items():
            summary = twin.run_once()

            resolved_kpis: list[dict[str, Any]] = []
            for kpi_id in twin.persona.kpis_owned:
                gaps = engine.detect_gaps(kpi_id)
                resolved_kpis.append({
                    "kpi_node_id": kpi_id,
                    "gaps": gaps,
                    "resolved": len(gaps) == 0,
                })

            findings[role] = {
                "role": role,
                "cycle": summary.get("cycle"),
                "wake_at": summary.get("wake_at"),
                "observations": summary.get("observations"),
                "kpi_resolution": resolved_kpis,
                "issues": summary.get("issues"),
                "actions": summary.get("actions"),
                "errors": summary.get("errors"),
            }

        return findings

    def run_monthly_board(self) -> dict[str, Any]:
        """Board packet: compile KPI summaries, risk flags, pending
        decisions, evidence.

        Returns:
            A structured board packet (see :func:`generate_board_packet`).
        """
        return generate_board_packet(self)

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def schedule_cycle(self, cycle_type: str, interval_hours: int) -> None:
        """Register a recurring cycle.

        Args:
            cycle_type: Identifier for the cycle (e.g. ``"daily_standup"``).
            interval_hours: How often the cycle should run.
        """
        self._scheduled_cycles[cycle_type] = interval_hours


# ===================================================================
# Story 3.2 — TriggerEngine
# ===================================================================


class TriggerEngine:
    """Event-driven KPI triggers that detect threshold breaches, stale
    data, and auto-investigate.

    Args:
        kpi_tree: The KPI tree dict (e.g. ``KPI_TREE``) to monitor.
        twins: Mapping of role → :class:`TwinRuntime` for triggering
            investigations on the correct owner twin.
    """

    def __init__(
        self,
        kpi_tree: dict[str, dict[str, Any]],
        twins: dict[str, TwinRuntime],
    ) -> None:
        self._kpi_tree = kpi_tree
        self._twins = twins

    # ------------------------------------------------------------------
    # Threshold checks
    # ------------------------------------------------------------------

    def check_thresholds(self) -> list[dict[str, Any]]:
        """Check all KPIs against their thresholds.

        Returns:
            A list of breached KPI dicts, each with ``node_id``,
            ``value``, ``threshold``, ``severity``, and ``owner``.
        """
        breached: list[dict[str, Any]] = []

        for node_id, node_data in self._kpi_tree.items():
            value = node_data.get("value")
            threshold = node_data.get("threshold")
            alert_below = node_data.get("alert_below")

            if value is None or threshold is None:
                continue
            if not isinstance(value, (int, float)):
                continue

            if value < threshold:
                severity = "critical" if (
                    alert_below is not None
                    and value < alert_below
                ) else "warning"
                breached.append({
                    "node_id": node_id,
                    "value": value,
                    "threshold": threshold,
                    "alert_below": alert_below,
                    "severity": severity,
                    "owner": node_data.get("owner"),
                })

        return breached

    # ------------------------------------------------------------------
    # Staleness checks
    # ------------------------------------------------------------------

    def check_staleness(self, max_age_hours: int = 24) -> list[dict[str, Any]]:
        """Find KPIs with stale data.

        A KPI is flagged stale if its ``status`` is ``"stale"``, its
        ``last_updated`` is older than *max_age_hours*, or its ``status``
        is ``"missing"``.

        Args:
            max_age_hours: Maximum acceptable age of data.

        Returns:
            A list of stale KPI node dicts.
        """
        stale: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        for node_id, node_data in self._kpi_tree.items():
            status = node_data.get("status")
            last_updated = node_data.get("last_updated")

            if status == "stale":
                stale.append({
                    "node_id": node_id,
                    "reason": "status_is_stale",
                    "last_updated": last_updated,
                    "owner": node_data.get("owner"),
                })
                continue

            # Check age via last_updated date
            if last_updated:
                try:
                    updated_at = datetime.fromisoformat(str(last_updated))
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=timezone.utc)
                    age_hours = (now - updated_at).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        stale.append({
                            "node_id": node_id,
                            "reason": "last_updated_exceeded",
                            "last_updated": last_updated,
                            "age_hours": round(age_hours, 1),
                            "owner": node_data.get("owner"),
                        })
                        continue
                except (ValueError, TypeError):
                    pass

            # Missing data is also stale
            if status == "missing":
                stale.append({
                    "node_id": node_id,
                    "reason": "data_missing",
                    "last_updated": last_updated,
                    "owner": node_data.get("owner"),
                })

        return stale

    # ------------------------------------------------------------------
    # Auto-investigation
    # ------------------------------------------------------------------

    def trigger_investigation(
        self, kpi_node_id: str, trigger_reason: str
    ) -> str:
        """Auto-trigger an OODA investigation on the KPI owner twin.

        Args:
            kpi_node_id: The KPI node to investigate.
            trigger_reason: Human-readable reason.

        Returns:
            The investigation ID.

        Raises:
            ValueError: If the KPI node or its owner twin is unknown.
        """
        node_data = self._kpi_tree.get(kpi_node_id)
        if node_data is None:
            raise ValueError(
                f"KPI node {kpi_node_id!r} not found in KPI_TREE"
            )

        owner_role = node_data.get("owner")
        if owner_role is None:
            raise ValueError(
                f"KPI node {kpi_node_id!r} has no owner"
            )

        twin = self._twins.get(owner_role)
        if twin is None:
            raise ValueError(
                f"No TwinRuntime registered for owner role {owner_role!r}"
            )

        inv_id = f"auto-{kpi_node_id}-{uuid.uuid4().hex[:8]}"
        context: dict[str, Any] = {
            "kpi_node_id": kpi_node_id,
            "trigger_reason": trigger_reason,
            "triggered_by": "TriggerEngine",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        add_investigation(twin.state, inv_id, context)
        return inv_id


# ===================================================================
# Story 3.3 — Governance gates
# ===================================================================


@dataclass(frozen=True)
class GovernanceGate:
    """A governance rule that may require approval.

    Attributes:
        role: The twin role this gate applies to.
        action_type: The action type (e.g. ``"approve_budget"``,
            ``"adjust_target"``, ``"escalate_decision"``).
        threshold_value: Values **above** this threshold require
            approval (ignored when *requires_human* is *True*).
        requires_human: If *True*, this action always requires
            human approval regardless of value.
    """

    role: str
    action_type: str
    threshold_value: float = 0.0
    requires_human: bool = False


DEFAULT_GATES: list[GovernanceGate] = [
    # CFO: approve_budget > 100k → requires approval; ≤ 100k → auto
    GovernanceGate(
        role="cfo",
        action_type="approve_budget",
        threshold_value=100_000.0,
    ),
    # GM: adjust_target any → requires CFO (and possibly human) approval
    GovernanceGate(
        role="group_manager",
        action_type="adjust_target",
        requires_human=True,
    ),
    # CEO: escalate_decision any → requires human
    GovernanceGate(
        role="ceo",
        action_type="escalate_decision",
        requires_human=True,
    ),
    # Analyst: prepare_data any → auto
    GovernanceGate(
        role="analyst",
        action_type="prepare_data",
        requires_human=False,
    ),
]


class GovernanceEngine:
    """Manages governance gates and approval chains.

    Args:
        gates: List of :class:`GovernanceGate` rules. Defaults to
            *DEFAULT_GATES*.
    """

    def __init__(
        self, gates: list[GovernanceGate] | None = None
    ) -> None:
        self._gates = list(gates) if gates else list(DEFAULT_GATES)
        self._audit_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Approval checking
    # ------------------------------------------------------------------

    def requires_approval(
        self, role: str, action_type: str, value: float
    ) -> bool:
        """Return *True* if this action requires approval.

        Args:
            role: The twin role performing the action.
            action_type: The action type.
            value: The numeric value of the action.

        Returns:
            *True* if approval is required.
        """
        applicable = [
            g
            for g in self._gates
            if g.role == role and g.action_type == action_type
        ]
        if not applicable:
            return False

        for gate in applicable:
            if gate.requires_human:
                return True
            if gate.threshold_value > 0 and value > gate.threshold_value:
                return True
        return False

    # ------------------------------------------------------------------
    # Approval chain
    # ------------------------------------------------------------------

    def get_approval_chain(
        self, role: str, action_type: str
    ) -> list[str]:
        """Return the chain of roles that must approve this action.

        Bases the chain on the twin's escalation path, with ``"human"``
        appended as the final approver when appropriate.

        Args:
            role: The twin role performing the action.
            action_type: The action type.

        Returns:
            Ordered list of role strings.
        """
        persona = lookup_persona(role)
        if persona is None:
            return []

        chain: list[str] = list(persona.escalation_path)
        # Append human as the final approver if not already present
        if "human" not in chain:
            chain.append("human")
        return chain

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    def log_decision(
        self,
        role: str,
        action_type: str,
        value: float,
        approved: bool,
        approver: str,
    ) -> None:
        """Record a governance decision in the audit trail.

        Args:
            role: The twin role that requested the action.
            action_type: The type of action.
            value: The value associated with the action.
            approved: Whether the action was approved.
            approver: Who approved/denied (role or ``"human"``).
        """
        record: dict[str, Any] = {
            "id": f"gov-{uuid.uuid4().hex[:12]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "action_type": action_type,
            "value": value,
            "approved": approved,
            "approver": approver,
        }
        self._audit_log.append(record)

    def get_audit_log(
        self, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return the most recent audit log entries."""
        return list(self._audit_log[-limit:])


# ===================================================================
# Story 3.4 — Board packet generation
# ===================================================================


def generate_board_packet(
    scheduler: CycleScheduler,
) -> dict[str, Any]:
    """Generate a complete board packet.

    Args:
        scheduler: A :class:`CycleScheduler` with twins registered.

    Returns:
        A structured dict with keys:
        - ``executive_summary`` (CEO twin analysis)
        - ``kpi_dashboard`` (all KPIs with status)
        - ``risk_register`` (high/critical issues)
        - ``pending_decisions`` (items needing human approval)
        - ``evidence_citations`` (KPI evidence references)
    """
    engine = KPIResolutionEngine()
    results = scheduler.run_daily_standup()

    # ---- KPI dashboard -------------------------------------------------
    kpi_dashboard: list[dict[str, Any]] = []
    for node_id, node_data in KPI_TREE.items():
        kpi_dashboard.append({
            "node_id": node_id,
            "value": node_data.get("value"),
            "status": node_data.get("status"),
            "owner": node_data.get("owner"),
            "threshold": node_data.get("threshold"),
            "last_updated": node_data.get("last_updated"),
        })

    # ---- Risk register -------------------------------------------------
    risk_register: list[dict[str, Any]] = []
    for role, result in results.items():
        for issue in result.get("issues", []):
            if issue.get("priority") in ("high", "critical"):
                risk_register.append({
                    "role": role,
                    "issue": issue,
                    "detail": issue.get("detail", ""),
                    "priority": issue.get("priority"),
                })

    # ---- Pending decisions ---------------------------------------------
    pending_decisions: list[dict[str, Any]] = []
    for role, result in results.items():
        for action in result.get("actions", []):
            if action.get("action") in ("escalate", "send_escalation"):
                pending_decisions.append({
                    "role": role,
                    "action": action,
                    "requires_human": True,
                })

    # ---- Evidence citations --------------------------------------------
    evidence_citations: list[str] = [
        f"KPI:{node_id} — {ndata.get('status', 'unknown')}"
        for node_id, ndata in KPI_TREE.items()
    ]

    # ---- Executive summary from CEO ------------------------------------
    ceo_result = results.get("ceo", {})
    executive_summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ceo_cycle": ceo_result.get("cycle", 0),
        "ceo_observations": ceo_result.get("observations", {}),
        "ceo_issues": ceo_result.get("issues", []),
        "ceo_actions": ceo_result.get("actions", []),
    }

    return {
        "executive_summary": executive_summary,
        "kpi_dashboard": kpi_dashboard,
        "risk_register": risk_register,
        "pending_decisions": pending_decisions,
        "evidence_citations": evidence_citations,
    }


# ===================================================================
# Story 3.5 — Cycle history + audit
# ===================================================================


@dataclass
class CycleRecord:
    """A record of a completed (or in-progress) cycle.

    Attributes:
        cycle_id: Unique identifier.
        cycle_type: e.g. ``"daily_standup"``, ``"weekly_review"``.
        started_at: ISO-8601 start timestamp.
        completed_at: ISO-8601 completion timestamp, or *None*.
        participants: Roles that participated.
        findings: List of finding dicts.
        decisions: List of decision dicts.
        status: ``"running"``, ``"completed"``, or ``"failed"``.
    """

    cycle_id: str
    cycle_type: str
    started_at: str
    completed_at: str | None = None
    participants: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    status: str = "running"


class CycleHistory:
    """In-memory cycle history with retrieval and filtering.

    In production this would be backed by a database. For now it
    stores records in memory.
    """

    def __init__(self) -> None:
        self._records: dict[str, CycleRecord] = {}

    def record_cycle(self, record: CycleRecord) -> None:
        """Store a cycle record.

        Args:
            record: The :class:`CycleRecord` to store.
        """
        self._records[record.cycle_id] = record

    def get_recent_cycles(
        self, cycle_type: str | None = None, limit: int = 10
    ) -> list[CycleRecord]:
        """Return the most recent cycle records, optionally filtered.

        Args:
            cycle_type: If set, only return cycles of this type.
            limit: Maximum records to return (most recent first).

        Returns:
            A list of :class:`CycleRecord` instances.
        """
        records: list[CycleRecord] = list(self._records.values())
        if cycle_type:
            records = [r for r in records if r.cycle_type == cycle_type]
        records.sort(key=lambda r: r.started_at, reverse=True)
        return records[:limit]

    def get_cycle(self, cycle_id: str) -> CycleRecord | None:
        """Retrieve a specific cycle record by ID.

        Args:
            cycle_id: The cycle identifier.

        Returns:
            The :class:`CycleRecord` or *None*.
        """
        return self._records.get(cycle_id)

    def to_dict(self) -> dict[str, Any]:
        """Serialize all records to a plain dict for persistence."""
        return {
            cid: {
                "cycle_id": rec.cycle_id,
                "cycle_type": rec.cycle_type,
                "started_at": rec.started_at,
                "completed_at": rec.completed_at,
                "participants": list(rec.participants),
                "findings": list(rec.findings),
                "decisions": list(rec.decisions),
                "status": rec.status,
            }
            for cid, rec in self._records.items()
        }
