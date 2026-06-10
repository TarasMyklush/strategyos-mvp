"""Deterministic data Q&A engine.

Maps a typed finance question to a curated keyword/pattern intent and computes
an exact answer from the run's real data (the in-memory DataBundle and the run's
findings). No LLM is involved: matching is keyword/regex based and every answer
carries a ``basis`` describing exactly how it was computed. Unrecognized
questions return suggestions rather than a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from .ingestion import DataBundle
from .models import Finding


def _normalize(question: str) -> str:
    return " ".join(str(question or "").lower().split())


def _has(text: str, *terms: str) -> bool:
    return all(re.search(rf"\b{re.escape(t)}\b", text) for t in terms)


def _has_any(text: str, *terms: str) -> bool:
    return any(re.search(rf"\b{re.escape(t)}\b", text) for t in terms)


def _sar(value: float) -> str:
    return f"SAR {value:,.2f}"


def _ledger_citation(bundle: DataBundle, role: str, locator: str) -> dict[str, Any]:
    contract = (bundle.data_contracts or {}).get(role) or {}
    source_path = contract.get("relative_path") or str(bundle.dataset_root)
    return {
        "source_path": source_path,
        "locator": locator,
        "excerpt": "",
    }


def _finding_citations(findings: list[Finding], limit: int = 5) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        for citation in finding.citations:
            key = (citation.source_path, citation.locator)
            if key in seen:
                continue
            seen.add(key)
            citations.append(
                {
                    "source_path": citation.source_path,
                    "locator": citation.locator,
                    "excerpt": citation.excerpt,
                    "source_hash": citation.source_hash,
                    "finding_id": finding.finding_id,
                }
            )
            if len(citations) >= limit:
                return citations
    return citations


def _role_available(bundle: DataBundle, role: str) -> bool:
    available = (bundle.run_metadata or {}).get("available_roles")
    if isinstance(available, list):
        return role in available
    # No availability metadata (legacy/full run): treat a non-empty frame as present.
    frame = {"ap_ledger": bundle.ap, "ar_ledger": bundle.ar}.get(role)
    return frame is not None and not frame.empty


def _needs(role: str, label: str) -> dict[str, Any]:
    return {
        "matched": True,
        "answer": f"That question needs the {label}, which was not part of this run.",
        "value": None,
        "unit": None,
        "basis": f"Required role '{role}' is not available in the current run.",
        "available": False,
    }


@dataclass(frozen=True)
class Intent:
    name: str
    matcher: Callable[[str], bool]
    handler: Callable[[str, DataBundle, list[Finding]], dict[str, Any]]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _ledger_for(question: str, bundle: DataBundle) -> tuple[str, pd.DataFrame, str]:
    """Pick AP (payables) or AR (receivables); default AP."""
    if _has_any(question, "receivable", "ar", "customer", "collection", "sales"):
        return "ar_ledger", bundle.ar, "AR"
    return "ap_ledger", bundle.ap, "AP"


def _apply_filters(question: str, frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    notes: list[str] = []
    out = frame
    if "Status" in out.columns:
        if _has(question, "unpaid") or _has(question, "open") or _has(question, "outstanding"):
            out = out[out["Status"].astype(str).str.lower().isin({"open", "unpaid", "outstanding"})]
            notes.append("status=Open")
        elif _has(question, "paid"):
            out = out[out["Status"].astype(str).str.lower().eq("paid")]
            notes.append("status=Paid")
    if "Currency" in out.columns:
        for cur in ("sar", "eur", "usd"):
            if _has(question, cur):
                out = out[out["Currency"].astype(str).str.lower().eq(cur)]
                notes.append(f"currency={cur.upper()}")
                break
    return out, notes


def _handle_invoice_metric(question: str, bundle: DataBundle, findings: list[Finding]) -> dict[str, Any]:
    role, frame, label = _ledger_for(question, bundle)
    if not _role_available(bundle, role):
        return _needs(role, f"{label} invoice ledger")
    frame, notes = _apply_filters(question, frame)
    note_text = (" (" + ", ".join(notes) + ")") if notes else ""

    if _has_any(question, "average", "avg", "mean"):
        value = float(frame["Amount_SAR"].mean()) if len(frame) else 0.0
        return {
            "matched": True,
            "answer": f"The average {label} invoice amount{note_text} is {_sar(value)} across {len(frame):,} invoices.",
            "value": round(value, 2), "unit": "SAR",
            "basis": f"mean of Amount_SAR over {len(frame):,} {label} rows{note_text}.",
            "citations": [_ledger_citation(bundle, role, f"{label} ledger Amount_SAR")],
            "available": True,
        }
    if _has_any(question, "how many", "count", "number of") and not _has(question, "vendor") and not _has(question, "customer"):
        return {
            "matched": True,
            "answer": f"There are {len(frame):,} {label} invoices{note_text}.",
            "value": int(len(frame)), "unit": "invoices",
            "basis": f"row count of the {label} ledger{note_text}.",
            "citations": [_ledger_citation(bundle, role, f"{label} ledger rows")],
            "available": True,
        }
    # default: total amount
    value = float(frame["Amount_SAR"].sum())
    return {
        "matched": True,
        "answer": f"The total {label} invoice amount{note_text} is {_sar(value)} across {len(frame):,} invoices.",
        "value": round(value, 2), "unit": "SAR",
        "basis": f"sum of Amount_SAR over {len(frame):,} {label} rows{note_text}.",
        "citations": [_ledger_citation(bundle, role, f"{label} ledger Amount_SAR")],
        "available": True,
    }


def _parse_top_n(question: str, default: int = 5) -> int:
    m = re.search(r"\btop\s+(\d{1,3})\b", question) or re.search(r"\b(\d{1,3})\s+(?:vendors?|customers?|suppliers?)\b", question)
    if m:
        return max(1, min(50, int(m.group(1))))
    return default


def _handle_top_parties(question: str, bundle: DataBundle, findings: list[Finding]) -> dict[str, Any]:
    if _has_any(question, "customer", "receivable"):
        role, frame, name_col, label = "ar_ledger", bundle.ar, "Customer_Name", "customers"
    else:
        role, frame, name_col, label = "ap_ledger", bundle.ap, "Vendor_Name", "vendors"
    if not _role_available(bundle, role):
        return _needs(role, f"{label} ledger")
    if name_col not in frame.columns:
        return _needs(role, f"{name_col} data")
    n = _parse_top_n(question)
    ranked = frame.groupby(name_col)["Amount_SAR"].sum().sort_values(ascending=False).head(n)
    rows = [{"name": str(k), "amount_sar": round(float(v), 2)} for k, v in ranked.items()]
    listing = "; ".join(f"{r['name']} ({_sar(r['amount_sar'])})" for r in rows)
    return {
        "matched": True,
        "answer": f"Top {len(rows)} {label} by spend: {listing}.",
        "value": rows, "unit": "SAR",
        "basis": f"Amount_SAR grouped by {name_col}, sorted descending, top {n}.",
        "citations": [_ledger_citation(bundle, role, f"{name_col} / Amount_SAR")],
        "available": True,
    }


def _handle_named_party_spend(question: str, bundle: DataBundle, findings: list[Finding]) -> dict[str, Any]:
    # "how much did we pay <vendor>" / "spend for <vendor>"
    m = re.search(r"(?:vendor|supplier|customer|pay|paid|spend(?:ing)?(?:\s+(?:for|to|with))?|for)\s+(.+)", question)
    if not m:
        return {"matched": False}
    needle = m.group(1).strip(" ?.")
    if len(needle) < 3:
        return {"matched": False}
    role, frame, name_col, label = ("ar_ledger", bundle.ar, "Customer_Name", "customer") if _has(question, "customer") else ("ap_ledger", bundle.ap, "Vendor_Name", "vendor")
    if not _role_available(bundle, role) or name_col not in frame.columns:
        return _needs(role, f"{label} ledger")
    hits = frame[frame[name_col].astype(str).str.contains(re.escape(needle), case=False, na=False)]
    if hits.empty:
        return {
            "matched": True,
            "answer": f"No {label} matching '{needle}' was found in this run.",
            "value": 0.0, "unit": "SAR",
            "basis": f"substring match on {name_col} found 0 rows.",
            "citations": [_ledger_citation(bundle, role, name_col)],
            "available": True,
        }
    value = float(hits["Amount_SAR"].sum())
    names = ", ".join(sorted(hits[name_col].astype(str).unique())[:5])
    return {
        "matched": True,
        "answer": f"Total for {label} matching '{needle}' ({names}) is {_sar(value)} across {len(hits):,} invoices.",
        "value": round(value, 2), "unit": "SAR",
        "basis": f"sum of Amount_SAR where {name_col} contains '{needle}' ({len(hits):,} rows).",
        "citations": [_ledger_citation(bundle, role, f"{name_col} / Amount_SAR")],
        "available": True,
    }


def _handle_distinct_parties(question: str, bundle: DataBundle, findings: list[Finding]) -> dict[str, Any]:
    if _has_any(question, "customer"):
        role, frame, col, label = "ar_ledger", bundle.ar, "Customer_ID", "customers"
    else:
        role, frame, col, label = "ap_ledger", bundle.ap, "Vendor_ID", "vendors"
    if not _role_available(bundle, role) or col not in frame.columns:
        return _needs(role, f"{label} ledger")
    n = int(frame[col].nunique())
    return {
        "matched": True,
        "answer": f"There are {n:,} distinct {label} in this run.",
        "value": n, "unit": label,
        "basis": f"distinct count of {col} in the ledger.",
        "citations": [_ledger_citation(bundle, role, col)],
        "available": True,
    }


def _handle_recoverable(question: str, bundle: DataBundle, findings: list[Finding]) -> dict[str, Any]:
    if _has_any(question, "pattern", "by type", "per pattern", "category"):
        by: dict[str, float] = {}
        for f in findings:
            by[f.pattern_type] = by.get(f.pattern_type, 0.0) + float(f.recoverable_sar)
        rows = sorted(({"pattern_type": k, "recoverable_sar": round(v, 2)} for k, v in by.items()), key=lambda r: r["recoverable_sar"], reverse=True)
        listing = "; ".join(f"{r['pattern_type']} ({_sar(r['recoverable_sar'])})" for r in rows)
        return {
            "matched": True,
            "answer": f"Recoverable by pattern: {listing}.",
            "value": rows, "unit": "SAR",
            "basis": "sum of recoverable_sar grouped by finding pattern_type.",
            "citations": _finding_citations(findings),
            "available": True,
        }
    total = sum(float(f.recoverable_sar) for f in findings)
    return {
        "matched": True,
        "answer": f"Total recoverable identified is {_sar(total)} across {len(findings)} findings.",
        "value": round(total, 2), "unit": "SAR",
        "basis": f"sum of recoverable_sar over {len(findings)} findings.",
        "citations": _finding_citations(findings),
        "available": True,
    }


def _handle_findings(question: str, bundle: DataBundle, findings: list[Finding]) -> dict[str, Any]:
    if _has_any(question, "how many", "count", "number of"):
        if _has_any(question, "high", "medium", "low", "confidence"):
            counts = {c: sum(1 for f in findings if f.confidence == c) for c in ("HIGH", "MEDIUM", "LOW")}
            listing = ", ".join(f"{k}: {v}" for k, v in counts.items())
            return {
                "matched": True,
                "answer": f"Findings by confidence — {listing}.",
                "value": counts, "unit": "findings",
                "basis": "count of findings grouped by confidence.",
                "citations": _finding_citations(findings),
                "available": True,
            }
        return {
            "matched": True,
            "answer": f"There are {len(findings)} findings in this run.",
            "value": len(findings), "unit": "findings",
            "basis": "count of findings produced by the run.",
            "citations": _finding_citations(findings),
            "available": True,
        }
    n = _parse_top_n(question, default=5)
    top = sorted(findings, key=lambda f: f.recoverable_sar, reverse=True)[:n]
    rows = [{"finding_id": f.finding_id, "title": f.title, "recoverable_sar": round(float(f.recoverable_sar), 2)} for f in top]
    listing = "; ".join(f"{r['finding_id']} {r['title']} ({_sar(r['recoverable_sar'])})" for r in rows)
    return {
        "matched": True,
        "answer": f"Top {len(rows)} findings by recoverable: {listing}.",
        "value": rows, "unit": "SAR",
        "basis": f"findings sorted by recoverable_sar, top {n}.",
        "citations": _finding_citations(top),
        "available": True,
    }


def _handle_working_capital(question: str, bundle: DataBundle, findings: list[Finding]) -> dict[str, Any]:
    if not (_role_available(bundle, "ap_ledger") and _role_available(bundle, "ar_ledger")):
        return _needs("ar_ledger" if _role_available(bundle, "ap_ledger") else "ap_ledger", "AP and AR ledgers")
    from .skills.finance_controls import compute_working_capital_drifts

    signals = compute_working_capital_drifts(bundle, findings)
    if not signals:
        return {
            "matched": True,
            "answer": "No significant DSO/DPO drift signals were detected in this run.",
            "value": [], "unit": None,
            "basis": "compute_working_capital_drifts returned no qualifying signals.",
            "citations": [
                _ledger_citation(bundle, "ap_ledger", "AP ledger dates"),
                _ledger_citation(bundle, "ar_ledger", "AR ledger dates"),
            ],
            "available": True,
        }
    rows = [
        {
            "metric": s.get("metric"),
            "drift_days": s.get("drift_days"),
            "cash_impact_sar": round(float(s.get("cash_impact_sar", 0.0)), 2),
        }
        for s in signals[:3]
    ]
    listing = "; ".join(f"{r['metric']} drift {r['drift_days']}d, cash impact {_sar(r['cash_impact_sar'])}" for r in rows)
    return {
        "matched": True,
        "answer": f"Top working-capital drift signals: {listing}.",
        "value": rows, "unit": "SAR",
        "basis": "compute_working_capital_drifts (DSO/DPO drift vs trailing baseline).",
        "citations": [
            _ledger_citation(bundle, "ap_ledger", "AP ledger payment timing"),
            _ledger_citation(bundle, "ar_ledger", "AR ledger collection timing"),
        ],
        "available": True,
    }


def _handle_overdue(question: str, bundle: DataBundle, findings: list[Finding]) -> dict[str, Any]:
    role, frame, settle_col, label = _ledger_for(question, bundle)
    settle_col = "Collection_Date" if label == "AR" else "Payment_Date"
    if not _role_available(bundle, role):
        return _needs(role, f"{label} ledger")
    if "Due_Date" not in frame.columns:
        return _needs(role, "Due_Date data")
    settled = frame[settle_col] if settle_col in frame.columns else pd.NaT
    # overdue = no settlement and due date in the past relative to the data's max date
    ref = pd.to_datetime(frame[["Invoice_Date", "Due_Date"]].stack(), errors="coerce").max()
    due = pd.to_datetime(frame["Due_Date"], errors="coerce")
    unsettled = frame[settle_col].isna() if settle_col in frame.columns else pd.Series(True, index=frame.index)
    overdue = frame[(due < ref) & unsettled]
    value = float(overdue["Amount_SAR"].sum())
    return {
        "matched": True,
        "answer": f"There are {len(overdue):,} overdue {label} invoices totalling {_sar(value)} (due before {ref.date() if pd.notna(ref) else 'n/a'} and not yet settled).",
        "value": round(value, 2), "unit": "SAR",
        "basis": f"{label} rows with Due_Date in the past and no {settle_col}.",
        "citations": [_ledger_citation(bundle, role, f"Due_Date / {settle_col}")],
        "available": True,
    }


# ---------------------------------------------------------------------------
# Intent registry (ordered: first match wins)
# ---------------------------------------------------------------------------

INTENTS: tuple[Intent, ...] = (
    Intent("working_capital",
           lambda q: _has_any(q, "dso", "dpo", "working capital", "drift", "days sales", "days payable"),
           _handle_working_capital),
    Intent("overdue",
           lambda q: _has_any(q, "overdue", "late") and _has(q, "invoice"),
           _handle_overdue),
    Intent("recoverable",
           lambda q: _has_any(q, "recoverable", "recovery", "leakage", "savings"),
           _handle_recoverable),
    Intent("findings",
           lambda q: _has(q, "finding") or _has(q, "findings"),
           _handle_findings),
    Intent("top_parties",
           lambda q: _has(q, "top") and _has_any(q, "vendor", "vendors", "supplier", "suppliers", "customer", "customers"),
           _handle_top_parties),
    Intent("distinct_parties",
           lambda q: _has_any(q, "how many", "count", "number of", "distinct") and _has_any(q, "vendor", "vendors", "supplier", "customer", "customers"),
           _handle_distinct_parties),
    Intent("named_party_spend",
           lambda q: _has_any(q, "spend", "spending", "paid", "pay") or (_has_any(q, "vendor", "supplier", "customer") and _has_any(q, "for")),
           _handle_named_party_spend),
    Intent("invoice_metric",
           lambda q: _has(q, "invoice") or _has(q, "invoices"),
           _handle_invoice_metric),
)

SUGGESTIONS: tuple[str, ...] = (
    "What is the total amount of invoices?",
    "How many AP invoices are there?",
    "What is the total amount of unpaid invoices?",
    "Top 5 vendors by spend",
    "How many distinct vendors are there?",
    "What is the total recoverable?",
    "Show recoverable by pattern",
    "How many findings by confidence?",
    "What are the working capital drift signals?",
)


def answer_question(question: str, *, bundle: DataBundle, findings: list[Finding]) -> dict[str, Any]:
    norm = _normalize(question)
    if not norm:
        return {"matched": False, "answer": "Please ask a question.", "suggestions": list(SUGGESTIONS)}
    for intent in INTENTS:
        try:
            if intent.matcher(norm):
                result = intent.handler(norm, bundle, findings)
                if result.get("matched", True) is False:
                    continue
                result.setdefault("matched", True)
                result.setdefault("citations", [])
                result["intent"] = intent.name
                return result
        except Exception as exc:  # defensive: never crash the chat on a bad question
            return {
                "matched": True,
                "answer": "I could not compute that from the current run.",
                "value": None, "unit": None,
                "basis": f"handler '{intent.name}' raised: {exc}",
                "citations": [],
                "available": True,
                "intent": intent.name,
            }
    return {
        "matched": False,
        "answer": "I don't have a deterministic answer for that yet. Try one of these:",
        "citations": [],
        "suggestions": list(SUGGESTIONS),
    }
