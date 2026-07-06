from __future__ import annotations

import re
from typing import Any

from .. import graph_queries


_FINDING_ID_RE = re.compile(r"\b(?:FND|F)-\d+\b", re.IGNORECASE)
_VENDOR_ID_RE = re.compile(r"\bV-\d+\b", re.IGNORECASE)


def route_graph_question(run_id: str | None, question: str, *, limit: int = 10) -> dict[str, Any]:
    clean_question = str(question or "").strip()
    if not clean_question:
        return {"matched": False, "answered_by": "", "intent": None}

    graph_status = graph_queries.graph_capability_status(run_id)
    if graph_status.get("status") != "synced":
        return {
            "matched": False,
            "answered_by": "",
            "intent": None,
            "graph_status": graph_status,
        }

    lower_question = clean_question.lower()
    finding_id = _first_match(_FINDING_ID_RE, clean_question)
    vendor_id = _first_match(_VENDOR_ID_RE, clean_question)

    result: dict[str, Any] | None = None
    if finding_id and any(term in lower_question for term in ("evidence", "support", "proof", "backs")):
        result = graph_queries.finding_evidence_chain(run_id, finding_id, limit=limit)
    elif vendor_id and any(term in lower_question for term in ("exposure", "exposed", "findings linked", "findings for", "linked to vendor")):
        result = graph_queries.vendor_finding_exposure(run_id, vendor_id, limit=limit)
    elif any(term in lower_question for term in ("shared evidence", "same evidence", "shared support")):
        result = graph_queries.shared_evidence_findings(run_id, limit=limit)
    elif any(term in lower_question for term in ("contract gap", "contract gaps", "missing contract", "without contract")):
        result = graph_queries.vendor_contract_gaps(run_id, limit=limit)
    elif any(term in lower_question for term in ("collusion", "shared bank", "bank account", "tax id", "vendor cluster")):
        result = graph_queries.vendor_collusion_clusters(run_id, limit=limit)

    if not result or not result.get("available") or not result.get("matched"):
        return {
            "matched": False,
            "answered_by": "",
            "intent": result.get("intent") if result else None,
            "graph_status": graph_status,
        }

    return {
        **result,
        "matched": True,
        "assistant_mode": "graph",
        "answered_by": "graph",
        "graph_status": graph_status,
        "suggestions": result.get("suggestions") or [],
    }


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return None if match is None else match.group(0).upper()
