"""Independent release grading. Expected facts come from reviewed references.

An answer's own `matched`, tier or confidence flags are never ground truth.
Missing references are ungraded, and never count toward the release threshold.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Sequence

from .claim_contracts import quantities, unsupported_quantities


def grade_answer(reference: Mapping[str, Any], response: Mapping[str, Any],
                 resolve: Callable[[Mapping[str, Any]], bool]) -> dict[str, Any]:
    text = str(response.get("answer") or "")
    expected = reference.get("expected_answer")
    refused = response.get("response_mode") in {"authority_refusal", "refusal"} or not response.get("matched", True)
    if not expected or not reference.get("reviewed_by"):
        return {"status": "ungraded", "correct": False, "refused": refused, "reasons": ["Reviewed reference answer missing."]}
    reasons = []
    if refused:
        reasons.append("Response refused or did not answer the question.")
    required = quantities(str(expected))
    actual = quantities(text)
    if not required.issubset(actual):
        reasons.append("Required numerical facts or units are missing or incorrect.")
    extra = unsupported_quantities(text, {"answer": expected, "allowed_context": reference.get("allowed_context", "")})
    if extra:
        reasons.append("Unsupported numerical claim.")
    patterns = reference.get("required_patterns") or []
    if not patterns:
        reasons.append("Reference has no semantic assertions.")
    elif not all(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
        reasons.append("Required meaning or metric-to-value binding is missing.")
    citations = response.get("citations") or []
    resolved = bool(citations) and all(resolve(citation) for citation in citations)
    required_sources = set(reference.get("required_sources") or [])
    cited_sources = {citation.get("source_path") for citation in citations}
    if not resolved or not required_sources or not required_sources.issubset(cited_sources):
        reasons.append("Required citations are missing or do not resolve.")
    return {"status": "failed" if reasons else "correct", "correct": not reasons,
            "refused": refused, "fabricated_numbers": bool(extra), "citations_resolved": resolved,
            "reasons": reasons}


def release_report(items: Sequence[Mapping[str, Any]], *, release: str, data_hash: str) -> dict[str, Any]:
    correct = sum(bool(item.get("grade", {}).get("correct")) for item in items)
    fabricated = sum(bool(item.get("grade", {}).get("fabricated_numbers")) for item in items)
    themes = sorted({str(item.get("theme")) for item in items if item.get("theme")})
    ids = [str(item.get("id")) for item in items]
    passed = len(items) == 50 and len(set(ids)) == 50 and len(themes) == 18 and correct >= 45 and fabricated == 0
    return {"release": release, "data_hash": data_hash, "question_count": len(items),
            "correct_count": correct, "fabrication_count": fabricated, "themes": themes,
            "passed": bool(passed and release and data_hash), "items": list(items),
            "refused_ids": [item.get("id") for item in items if item.get("grade", {}).get("refused")],
            "failed_ids": [item.get("id") for item in items if not item.get("grade", {}).get("correct")]}
