"""Public-safe domain errors (design doc section 8, 11, 15).

Mirrors the FAILURE_CODES taxonomy in models.py. Route handlers in api.py
catch these and map them to HTTPException with a stable `code`, never a raw
exception message -- matching the existing api.py convention of raising
HTTPException(detail="human string") rather than a structured problem
response (no RFC 9457 convention exists elsewhere in this codebase yet, so
PR 3 follows the established pattern instead of introducing a new one).
"""

from __future__ import annotations

from .models import FAILURE_CODES


class AgentDomainError(Exception):
    def __init__(self, code: str, detail_public: str):
        if code not in FAILURE_CODES:
            raise ValueError(f"unknown failure code {code!r}")
        super().__init__(detail_public)
        self.code = code
        self.detail_public = detail_public


class AgentNotPermitted(AgentDomainError):
    def __init__(self, detail_public: str = "This identity is not permitted for this specialist."):
        super().__init__("AGENT_NOT_PERMITTED", detail_public)


class AgentInvalidInput(AgentDomainError):
    def __init__(self, detail_public: str):
        super().__init__("AGENT_INVALID_INPUT", detail_public)


class AgentConflict(AgentDomainError):
    def __init__(self, detail_public: str):
        super().__init__("AGENT_CONFLICT", detail_public)


class FeatureDisabled(Exception):
    def __init__(self, flag_name: str):
        super().__init__(f"{flag_name} is disabled for this deployment.")
        self.flag_name = flag_name
