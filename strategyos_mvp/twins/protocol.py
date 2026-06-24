"""InterTwinMessage protocol — message types, validation, and escalation logic.

Defines the structured communication protocol between digital twins.
Every twin-to-twin interaction is captured as a typed message with
evidence citations and deadline-based escalation rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

MessageType = Literal[
    "data_request",
    "escalation",
    "approval",
    "notification",
    "status_update",
]

Priority = Literal["low", "normal", "high", "critical"]

Confidence = Literal["high", "medium", "low", "unable"]

MessageStatus = Literal["pending", "delivered", "responded", "escalated", "expired"]

# ---------------------------------------------------------------------------
# Message dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InterTwinMessage:
    """A structured message exchanged between digital twins.

    Attributes:
        message_id: Unique identifier for this message.
        sender_role: Role of the sending twin.
        recipient_role: Role of the receiving twin.
        message_type: Semantic type (data_request, escalation, etc.).
        priority: Urgency level (low → critical).
        subject: Human-readable one-line summary.
        body: Natural-language content of the message.
        evidence_citations: References to StrategyOS evidence artifacts.
        parent_message_id: ID of the message this is a reply to, if any.
        deadline_seconds: Max wait time before auto-escalation.
        created_at: ISO-8601 timestamp of creation.
        status: Delivery lifecycle status.
    """

    message_id: str
    sender_role: str
    recipient_role: str
    message_type: MessageType
    priority: Priority
    subject: str
    body: str
    evidence_citations: tuple[str, ...] = ()
    parent_message_id: str | None = None
    deadline_seconds: int = 3600
    created_at: str = ""
    status: MessageStatus = "pending"


@dataclass(frozen=True)
class TwinResponse:
    """A response from one twin to a prior InterTwinMessage.

    Attributes:
        response_id: Unique identifier for this response.
        request_message_id: The original message this responds to.
        responder_role: Role of the twin providing the response.
        body: Natural-language content of the response.
        evidence_citations: References to StrategyOS evidence artifacts.
        confidence: How confident the responder is in this response.
        data_provided: Structured data keys and values returned.
        gaps_remaining: Aspects that could not be resolved.
        created_at: ISO-8601 timestamp of creation.
    """

    response_id: str
    request_message_id: str
    responder_role: str
    body: str
    evidence_citations: tuple[str, ...] = ()
    confidence: Confidence = "medium"
    data_provided: dict[str, Any] = field(default_factory=dict)
    gaps_remaining: tuple[str, ...] = ()
    created_at: str = ""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_VALID_MESSAGE_TYPES: frozenset[str] = frozenset({
    "data_request",
    "escalation",
    "approval",
    "notification",
    "status_update",
})

_VALID_PRIORITIES: frozenset[str] = frozenset({"low", "normal", "high", "critical"})

_VALID_STATUSES: frozenset[str] = frozenset({
    "pending",
    "delivered",
    "responded",
    "escalated",
    "expired",
})

_VALID_CONFIDENCES: frozenset[str] = frozenset({
    "high",
    "medium",
    "low",
    "unable",
})


def validate_message(msg: InterTwinMessage) -> list[str]:
    """Validate an InterTwinMessage and return a list of errors.

    Args:
        msg: The message to validate.

    Returns:
        A list of human-readable error strings. An empty list means
        the message is valid.
    """
    errors: list[str] = []

    if not msg.message_id:
        errors.append("message_id is required")
    if not msg.sender_role:
        errors.append("sender_role is required")
    if not msg.recipient_role:
        errors.append("recipient_role is required")
    if msg.sender_role == msg.recipient_role:
        errors.append("sender_role and recipient_role must differ")
    if msg.message_type not in _VALID_MESSAGE_TYPES:
        errors.append(
            f"message_type must be one of {sorted(_VALID_MESSAGE_TYPES)}, "
            f"got {msg.message_type!r}"
        )
    if msg.priority not in _VALID_PRIORITIES:
        errors.append(
            f"priority must be one of {sorted(_VALID_PRIORITIES)}, "
            f"got {msg.priority!r}"
        )
    if not msg.subject:
        errors.append("subject is required")
    if not msg.body:
        errors.append("body is required")
    if msg.status not in _VALID_STATUSES:
        errors.append(
            f"status must be one of {sorted(_VALID_STATUSES)}, "
            f"got {msg.status!r}"
        )
    if msg.deadline_seconds < 0:
        errors.append("deadline_seconds must be non-negative")

    return errors


def validate_response(resp: TwinResponse) -> list[str]:
    """Validate a TwinResponse and return a list of errors.

    Args:
        resp: The response to validate.

    Returns:
        A list of human-readable error strings. An empty list means
        the response is valid.
    """
    errors: list[str] = []

    if not resp.response_id:
        errors.append("response_id is required")
    if not resp.request_message_id:
        errors.append("request_message_id is required")
    if not resp.responder_role:
        errors.append("responder_role is required")
    if not resp.body:
        errors.append("body is required")
    if resp.confidence not in _VALID_CONFIDENCES:
        errors.append(
            f"confidence must be one of {sorted(_VALID_CONFIDENCES)}, "
            f"got {resp.confidence!r}"
        )

    return errors


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------


def should_escalate(msg: InterTwinMessage, current_time: str | None = None) -> bool:
    """Determine whether a message should be escalated based on its deadline.

    A message is escalated if its status is ``"pending"`` and the time elapsed
    since ``created_at`` exceeds ``deadline_seconds``.

    Args:
        msg: The message to check.
        current_time: ISO-8601 timestamp for "now". If *None*, uses UTC now.

    Returns:
        *True* if the message should be escalated.
    """
    if msg.status != "pending":
        return False
    if not msg.created_at:
        return False

    if current_time is None:
        now = datetime.now(timezone.utc)
    else:
        now = datetime.fromisoformat(current_time)

    try:
        created = datetime.fromisoformat(msg.created_at)
    except (ValueError, TypeError):
        return False

    elapsed = (now - created).total_seconds()
    return elapsed > msg.deadline_seconds


# ---------------------------------------------------------------------------
# Phase 2 — Enhanced escalation
# ---------------------------------------------------------------------------


def get_escalation_timeout(priority: str) -> int:
    """Return the timeout in seconds for a given priority level.

    Args:
        priority: One of ``"low"``, ``"normal"``, ``"high"``, ``"critical"``.

    Returns:
        Timeout in seconds: critical=300, high=600, normal=1800, low=3600.
    """
    mapping: dict[str, int] = {
        "critical": 300,
        "high": 600,
        "normal": 1800,
        "low": 3600,
    }
    return mapping.get(priority, 1800)


def check_escalation(msg: InterTwinMessage, current_time: str) -> str | None:
    """Check if a message should be escalated based on timeout.

    A pending message past its deadline is escalated to the next role
    in the sender's escalation path (using the sender's persona).

    Args:
        msg: The message to check.
        current_time: ISO-8601 timestamp for "now".

    Returns:
        The escalated role string (e.g. ``"ceo"``) if escalation is
        needed, or *None* if the message is within deadline or not
        pending.
    """
    from strategyos_mvp.twins.persona import TWIN_CATALOG, lookup_persona

    if msg.status != "pending":
        return None
    if not msg.created_at:
        return None

    try:
        now = datetime.fromisoformat(current_time)
    except (ValueError, TypeError):
        return None

    try:
        created = datetime.fromisoformat(msg.created_at)
    except (ValueError, TypeError):
        return None

    elapsed = (now - created).total_seconds()
    if elapsed <= msg.deadline_seconds:
        return None

    # Find the next role in the sender's escalation path
    sender_persona = lookup_persona(msg.sender_role)
    if sender_persona is None:
        return None

    path = sender_persona.escalation_path
    if not path:
        return None

    # Return the first role in the escalation path
    return path[0]


def escalate_message(msg: InterTwinMessage, current_time: str) -> InterTwinMessage:
    """Create an escalated copy of the message.

    The new message is addressed to the next role in the escalation chain,
    has type ``"escalation"``, priority ``"critical"``, and references the
    original as ``parent_message_id``.

    Args:
        msg: The original message that timed out.
        current_time: ISO-8601 timestamp for "now".

    Returns:
        A new :class:`InterTwinMessage` representing the escalated request.
    """
    escalated_role = check_escalation(msg, current_time)
    if escalated_role is None:
        escalated_role = "human"

    new_id = f"esc-{msg.message_id}-{int(datetime.now(timezone.utc).timestamp())}"

    return InterTwinMessage(
        message_id=new_id,
        sender_role=msg.sender_role,
        recipient_role=escalated_role,
        message_type="escalation",
        priority="critical",
        subject=f"ESCALATED: {msg.subject}",
        body=(
            f"Message {msg.message_id} from {msg.sender_role} to "
            f"{msg.recipient_role} has timed out.\n\n"
            f"Original subject: {msg.subject}\n"
            f"Original body: {msg.body}\n"
            f"Deadline: {msg.deadline_seconds}s\n"
            f"Escalated to: {escalated_role}"
        ),
        evidence_citations=msg.evidence_citations,
        parent_message_id=msg.message_id,
        deadline_seconds=300,  # escalated messages have shorter deadlines
        created_at=current_time,
        status="pending",
    )
