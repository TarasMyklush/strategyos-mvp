"""Scoped context snapshots (design doc section 5.5).

Builds the immutable context manifest persisted with each task, so a
worker/handler receives a bounded, resolved scope instead of arbitrary
access to the entire application state.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import ContextSnapshot


def build_context_snapshot(
    *,
    tenant_id: str,
    principal_subject: str,
    as_of: str,
    conversation_id: str | None = None,
    run_id: str | None = None,
    finding_id: str | None = None,
    classification: str = "restricted",
    effective_capabilities: tuple[str, ...] = (),
) -> dict[str, Any]:
    snapshot = ContextSnapshot(
        tenant_id=tenant_id,
        principal_subject=principal_subject,
        as_of=as_of,
        conversation_id=conversation_id,
        run_id=run_id,
        finding_id=finding_id,
        classification=classification,  # type: ignore[arg-type]
        effective_capabilities=effective_capabilities,
    )
    payload = asdict(snapshot)
    # asdict() turns tuples into lists for JSON storage; keep dict values as
    # dicts (already the case for source_hashes).
    payload["allowed_evidence_ids"] = list(snapshot.allowed_evidence_ids)
    payload["effective_capabilities"] = list(snapshot.effective_capabilities)
    return payload
