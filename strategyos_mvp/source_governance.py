from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


CURRENT_EVIDENCE = "current_evidence"
HISTORIC_CONTEXT = "historic_context"
RESTRICTED_CONTEXT = "restricted_context"
CONTROL_PLANE = "control_plane"
EVALUATOR_ONLY = "evaluator_only"
QUARANTINED_CONTEXT = "quarantined_context"
UNSUPPORTED = "unsupported"

HISTORIC_CONTEXT_DIR = "99_Historic_Context"
RESTRICTED_CONTEXT_DIR = "98_Restricted_Context"
QUARANTINED_CONTEXT_DIR = "97_Quarantined_Context"

_CONTROL_PLANE_PARTS = {
    "02_agent_jds",
    "agent_jds",
    "03_sample_tasks",
    "sample_tasks",
}
_HISTORIC_PARTS = {
    "09_historic_erp",
    "10_historic_pos",
    "13_historic_correspondence",
}
_STRATEGIC_HISTORY_PARTS = {
    "11_strategic_analytics",
    "12_group_financials",
}
_RESTRICTED_PARTS = {"14_ceo_office"}
_NON_EVIDENCE_DIRS = {RESTRICTED_CONTEXT_DIR, QUARANTINED_CONTEXT_DIR}
_NON_DETECTOR_DIRS = {
    HISTORIC_CONTEXT_DIR,
    RESTRICTED_CONTEXT_DIR,
    QUARANTINED_CONTEXT_DIR,
}


def _parts(relative_path: str) -> tuple[str, ...]:
    return tuple(part.strip().lower() for part in PurePosixPath(relative_path).parts)


def initial_source_disposition(relative_path: str, *, supported: bool = True) -> str:
    """Return the path-governed disposition before content classification.

    Path semantics are authoritative for control-plane and evaluator files. This
    prevents an agent job description that mentions bank statements from being
    classified as a bank statement and entering the finance evidence set.
    """

    if not supported:
        return UNSUPPORTED
    parts = _parts(relative_path)
    name = parts[-1] if parts else ""
    if any(part in _CONTROL_PLANE_PARTS for part in parts):
        return CONTROL_PLANE
    if name.startswith("readme"):
        return EVALUATOR_ONLY
    if any(part in _RESTRICTED_PARTS for part in parts) or "ceo_calendar" in name:
        return RESTRICTED_CONTEXT
    if any(part in _HISTORIC_PARTS for part in parts):
        return HISTORIC_CONTEXT
    if any(part in _STRATEGIC_HISTORY_PARTS for part in parts):
        return HISTORIC_CONTEXT
    return CURRENT_EVIDENCE


def final_source_disposition(item: dict[str, Any]) -> str:
    """Refine a manifest disposition after content classification."""

    initial = str(
        item.get("source_disposition")
        or initial_source_disposition(
            str(item.get("relative_path") or ""),
            supported=bool(item.get("supported")),
        )
    )
    if initial in {
        UNSUPPORTED,
        CONTROL_PLANE,
        EVALUATOR_ONLY,
        RESTRICTED_CONTEXT,
    }:
        return initial

    classification = item.get("classification") or {}
    status = str(classification.get("status") or "unclassified")
    role = str(classification.get("role") or "")
    # The approved division-to-group plan is a current run input even though it
    # is stored beside multi-year analytics.
    if role == "revenue_plan" and status == "classified":
        return CURRENT_EVIDENCE
    if initial == HISTORIC_CONTEXT:
        return HISTORIC_CONTEXT
    if status == "ambiguous":
        return QUARANTINED_CONTEXT
    if status == "unclassified":
        return HISTORIC_CONTEXT
    return CURRENT_EVIDENCE


def governed_context_path(disposition: str, relative_path: str) -> str:
    source_path = PurePosixPath(relative_path).as_posix().lstrip("/")
    if disposition == HISTORIC_CONTEXT:
        return f"{HISTORIC_CONTEXT_DIR}/{source_path}"
    if disposition == RESTRICTED_CONTEXT:
        return f"{RESTRICTED_CONTEXT_DIR}/{source_path}"
    if disposition == QUARANTINED_CONTEXT:
        return f"{QUARANTINED_CONTEXT_DIR}/{source_path}"
    raise ValueError(f"Disposition '{disposition}' does not use a governed context path.")


def is_agent_evidence_path(relative_path: str) -> bool:
    """Whether a normalized file may enter the general agent evidence store."""

    return not any(part in _NON_EVIDENCE_DIRS for part in PurePosixPath(relative_path).parts)


def is_detector_candidate_path(relative_path: str) -> bool:
    """Whether a file may satisfy a current-period detector data contract."""

    return not any(part in _NON_DETECTOR_DIRS for part in PurePosixPath(relative_path).parts)


def disposition_summary(manifest: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    processing_counts: dict[str, int] = {}
    silent_omissions: list[str] = []
    for item in manifest:
        disposition = str(item.get("source_disposition") or "unassigned")
        processing_status = str(item.get("processing_status") or "")
        counts[disposition] = counts.get(disposition, 0) + 1
        if processing_status:
            processing_counts[processing_status] = processing_counts.get(processing_status, 0) + 1
        else:
            silent_omissions.append(str(item.get("relative_path") or ""))
    return {
        "file_count": len(manifest),
        "accounted_file_count": len(manifest) - len(silent_omissions),
        "silent_omission_count": len(silent_omissions),
        "silent_omissions": silent_omissions,
        "counts_by_disposition": counts,
        "counts_by_processing_status": processing_counts,
    }
