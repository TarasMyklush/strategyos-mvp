"""Executive-facing naming and text safety contracts.

The operating model intentionally retains precise source paths, validation
labels and workflow terminology for audit and engineering use.  None of those
implementation details are suitable as CEO copy.  This module is the single
boundary between internal records and executive presentation; renderers should
never invent their own one-off substitutions.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


_ANSWER_KEY_PATTERNS = (
    re.compile(r"\bPLANTED(?:\s+DRIFT)?\b\s*[-—:]?\s*", re.IGNORECASE),
    re.compile(r"\bANSWER[ _-]?KEY\b\s*[-—:]?\s*", re.IGNORECASE),
    re.compile(r"\(\s*Pattern\s+\d+\s*\)", re.IGNORECASE),
    re.compile(r"\bPattern\s+\d+\b\s*[-—:]?\s*", re.IGNORECASE),
)

_INTERNAL_COPY = (
    (re.compile(r"\bthe source pack\b", re.IGNORECASE), "the connected business records"),
    (re.compile(r"\bsource pack\b", re.IGNORECASE), "business records"),
    (re.compile(r"\bcurrent governed run\b", re.IGNORECASE), "current verified review"),
    (re.compile(r"\blatest governed run\b", re.IGNORECASE), "latest verified review"),
    (re.compile(r"\bgoverned run\b", re.IGNORECASE), "verified review"),
    (re.compile(r"\bgoverned artifacts?\b", re.IGNORECASE), "verified records"),
    (re.compile(r"\bserver[- ]resolved\b", re.IGNORECASE), "verified"),
)

_FOLDER_LABELS = {
    "01_bank_statements": "Bank statements",
    "02_erp_extracts": "Finance ledger",
    "07_cash_forecast": "Cash forecast",
    "08_invoices": "Invoices",
    "12_group_financials": "Group financials",
    "14_ceo_office": "CEO calendar",
    "15_budgets_forecasts": "Division budget",
    "16_business_events": "Business events",
    "17_signals": "Business signals",
    "19_document_vault": "Decision documents",
    "20_board_kpis": "Board KPI records",
    "21_initiatives": "Initiative register",
    "24_executive_policy": "Executive policy",
    "99_historic_context": "Historic business context",
}

_DISPLAY_TOKEN_LABELS = {
    "inventory_movements": "Inventory movements",
    "assistant_profiles": "Assistant profiles",
    "board_kpi_glidepaths": "Board KPI glidepaths",
    "remediation_decision_log": "Remediation decision log",
}

_PATH_TOKEN = re.compile(
    r"(?<![\w])(?:\d{2}_[A-Za-z0-9_-]+/)+(?:[A-Za-z0-9_.() -]+\.(?:xlsx|xls|csv|pdf|docx|pptx|txt|json))",
    re.IGNORECASE,
)

_MACHINE_STRING_KEYS = {
    "id",
    "key",
    "run_id",
    "thread_id",
    "finding_id",
    "kpi_id",
    "initiative_id",
    "persona",
    "persona_id",
    "active_persona_id",
    "role",
    "status",
    "status_vs_path",
    "tone",
    "mode",
    "assistant_mode",
    "answered_by",
    "answer_origin",
    "determinism_tier",
    "grounding_status",
    "level",
    "calculation_status",
    "review_status",
    "scenario_type",
    "error_type",
    "source",
    "kind",
    "type",
    "category",
    "unit",
    "route",
    "href",
    "locator",
    "source_path",
    "source_file",
    "file",
}


def _humanize_filename(filename: str) -> str:
    stem = PurePosixPath(filename).stem
    value = re.sub(r"[_-]+", " ", stem)
    value = re.sub(r"\b(?:final|latest|jun|june|h1|q[1-4])\s*20\d{2}\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()
    return value or "Business record"


def executive_source_label(value: Any) -> str:
    """Return a stable, human business label for an internal source path."""

    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return "Business record"
    if raw.startswith("public_packet://"):
        return "Current executive briefing"
    parts = [part for part in raw.split("/") if part]
    filename = parts[-1] if parts else raw
    parent_labels = [
        _FOLDER_LABELS.get(part.casefold())
        for part in parts[:-1]
        if _FOLDER_LABELS.get(part.casefold())
    ]
    file_label = _humanize_filename(filename)
    if re.search(r"(?:^|[_-])INV[-_ ]?\d", filename, re.IGNORECASE):
        invoice_match = re.search(r"(?:^|[_-])(INV[-_ ]?\d[A-Za-z0-9_-]*)", filename, re.IGNORECASE)
        vendor = re.sub(r"^Invoice[_ -]*", "", PurePosixPath(filename).stem, flags=re.IGNORECASE)
        vendor = re.split(r"[_ -]+INV[- ]?", vendor, maxsplit=1, flags=re.IGNORECASE)[0]
        vendor = re.sub(r"[_-]+", " ", vendor).strip()
        invoice_label = invoice_match.group(1).replace("_", "-") if invoice_match else ""
        return f"{vendor or 'Supplier'} invoice {invoice_label}".strip()
    if parent_labels:
        parent = parent_labels[-1]
        if file_label.casefold().startswith(parent.casefold()):
            return file_label
        return f"{file_label} · {parent}"
    return file_label


def executive_display_text(value: Any) -> str:
    """Sanitize and humanize one executive-visible string."""

    text = str(value or "")
    for pattern in _ANSWER_KEY_PATTERNS:
        text = pattern.sub("", text)
    text = _PATH_TOKEN.sub(lambda match: executive_source_label(match.group(0)), text)
    for token, label in {**_FOLDER_LABELS, **_DISPLAY_TOKEN_LABELS}.items():
        text = re.sub(rf"\b{re.escape(token)}\b/?", label, text, flags=re.IGNORECASE)
    for pattern, replacement in _INTERNAL_COPY:
        text = pattern.sub(replacement, text)
    text = re.sub(r"\bthe connected business records was\b", "the connected business records were", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"(?:\s*[—-]\s*){2,}", " — ", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(
        r"(^|[.!?]\s+)([a-z])",
        lambda match: match.group(1) + match.group(2).upper(),
        text,
    )
    return text.strip(" \t\n-—:")


def sanitize_executive_payload(value: Any, *, key: str = "") -> Any:
    """Recursively apply the executive display contract.

    Machine identifiers remain intact. Source-path values are converted to
    business labels only at this presentation boundary; internal run records
    and audit stores are never mutated.
    """

    if isinstance(value, dict):
        sanitized = {
            str(child_key): sanitize_executive_payload(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
        source_value = next(
            (
                value.get(source_key)
                for source_key in ("source_path", "source_file", "file")
                if isinstance(value.get(source_key), str) and value.get(source_key)
            ),
            None,
        )
        if source_value and not sanitized.get("source_label"):
            sanitized["source_label"] = executive_source_label(source_value)
        return sanitized
    if isinstance(value, list):
        return [sanitize_executive_payload(item, key=key) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_executive_payload(item, key=key) for item in value)
    if isinstance(value, str):
        # Structured source references remain resolvable for the evidence
        # service. Their business label travels alongside them and is the only
        # value renderers may show.
        if key in _MACHINE_STRING_KEYS or key.endswith("_id") or key.endswith("_key"):
            return value
        # Presentation sanitization is a trust-boundary filter, not a global
        # prose formatter. Safe strings must remain byte-for-byte stable so
        # nested protocol values (for example evidence_scope or model names)
        # cannot be changed merely because a new field was added upstream.
        return executive_display_text(value) if executive_text_has_internal_leak(value) else value
    return value


def executive_text_has_internal_leak(value: Any) -> bool:
    """CI helper for the chief-of-staff copy gate."""

    text = str(value or "")
    token_pattern = "|".join(
        re.escape(token) for token in (*_FOLDER_LABELS, *_DISPLAY_TOKEN_LABELS)
    )
    return bool(
        re.search(r"\b(?:PLANTED|ANSWER[ _-]?KEY|Pattern\s+\d+)\b", text, re.IGNORECASE)
        or _PATH_TOKEN.search(text)
        or re.search(rf"\b(?:{token_pattern})\b", text, re.IGNORECASE)
        or re.search(r"\b(?:source pack|governed run|server[- ]resolved)\b", text, re.IGNORECASE)
    )
