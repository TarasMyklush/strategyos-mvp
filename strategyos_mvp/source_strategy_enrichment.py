"""Normalized executive enrichment sourced from the Legion build dataset.

The source workbooks are presentation-friendly.  This module is the single
machine boundary that turns them into typed, evidence-carrying records for the
CEO surface.  No UI component parses workbook prose or infers missing values.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from openpyxl import load_workbook


def _find(root: Path, name: str) -> Path | None:
    wanted = name.casefold()
    return next((path for path in root.rglob("*") if path.is_file() and path.name.casefold() == wanted), None)


def _records(path: Path | None, sheet_name: str) -> list[dict[str, Any]]:
    if path is None:
        return []
    try:
        book = load_workbook(path, data_only=True, read_only=True)
        sheet = book[sheet_name]
    except Exception:
        return []
    rows = iter(sheet.values)
    headers = [str(value or "").strip() for value in next(rows, ())]
    return [
        {headers[index]: value for index, value in enumerate(row) if index < len(headers)}
        for row in rows
        if any(value is not None and str(value).strip() for value in row)
    ]


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _iso(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    text = str(value or "").strip()
    return text[:10] if text else None


def _relative(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _measurement_status(row: dict[str, Any]) -> str:
    actual = str(row.get("Jun-2026 actual") or "").casefold()
    if not actual.strip():
        return "missing"
    if "est" in actual or row.get("KPI_ID") in {"KPI-03", "KPI-04"}:
        return "estimated"
    return "live"


def _score(actual: float | None, checkpoint: float | None, lower_is_better: bool) -> float | None:
    if actual is None or checkpoint in {None, 0} or actual == 0:
        return None
    raw = checkpoint / actual if lower_is_better else actual / checkpoint
    return max(0.0, min(1.2, raw))


def _cost_of_drift(
    *,
    actual: float | None,
    checkpoint: float | None,
    unit: Any,
    evidence: dict[str, Any],
) -> dict[str, Any] | None:
    """Return a source-safe drift statement without inventing a SAR conversion.

    Some operational KPIs (for example E-Rx volume share) have an observed
    checkpoint gap but no source-backed volume-to-SAR conversion in the
    enrichment pack.  The executive surface must show the quantified operating
    gap and explicitly fail closed on money rather than manufacture a value.
    """

    if actual is None or checkpoint is None:
        return None
    gap = round(abs(checkpoint - actual), 2)
    raw_unit = str(unit or "").strip()
    gap_unit = "percentage points" if raw_unit == "%" else raw_unit or "units"
    return {
        "gap": gap,
        "gap_unit": gap_unit,
        "financial_effect_sar_per_week": None,
        "financial_effect_status": "not_supplied",
        "statement": (
            f"{gap:g} {gap_unit} to the approved checkpoint; "
            "the source pack does not supply a defensible SAR-per-week conversion."
        ),
        "evidence": evidence,
    }


def _plan_health(
    glidepaths: list[dict[str, Any]],
    source_file: str | None,
    finance_kpi: dict[str, Any] | None = None,
) -> dict[str, Any]:
    finance_components = (
        finance_kpi.get("components")
        if isinstance(finance_kpi, dict) and finance_kpi.get("authoritative") is True
        else {}
    )
    finance_evidence = (
        finance_kpi.get("evidence")
        if isinstance(finance_kpi, dict) and isinstance(finance_kpi.get("evidence"), dict)
        else {}
    )
    commitments: list[dict[str, Any]] = []
    for row in glidepaths:
        kpi_id = str(row.get("KPI_ID") or "")
        actual = _number(row.get("Jun-2026 actual"))
        checkpoint = _number(row.get("Jun-2026 checkpoint"))
        comparator_evidence: dict[str, Any] | None = None
        # The supplied KPI-01 glidepath row labels revenue as 2.6% ahead but
        # repeats the H1 actual in its checkpoint cell. The approved group
        # budget is the authoritative H1 comparator already reconciled by the
        # finance engine, so use that actual/plan pair instead of presenting a
        # self-contradictory 100% score.
        if kpi_id == "KPI-01" and isinstance(finance_components, dict):
            revenue_actual = _number(finance_components.get("revenue_actual"))
            revenue_plan = _number(finance_components.get("revenue_plan"))
            if revenue_actual is not None and revenue_plan not in {None, 0}:
                actual = revenue_actual / 1_000_000
                checkpoint = revenue_plan / 1_000_000
                comparator_evidence = dict(
                    finance_evidence.get("revenue") or {}
                ) if isinstance(finance_evidence, dict) else None
        lower_is_better = kpi_id in {"KPI-04", "KPI-10"}
        status = _measurement_status(row)
        score = _score(actual, checkpoint, lower_is_better)
        evidence = {"file": source_file, "sheet": "Glidepaths", "kpi_id": kpi_id}
        commitment = {
            "kpi_id": kpi_id,
            "name": row.get("KPI_Name"),
            "unit": row.get("Unit"),
            "actual": actual,
            "checkpoint": checkpoint,
            "target_2028": _number(row.get("FY2028T")),
            "status_vs_path": row.get("Status vs path"),
            "measurement_status": status,
            "direction": "lower_is_better" if lower_is_better else "higher_is_better",
            "weight": 1.0,
            "score": round(score * 100, 1) if score is not None else None,
            "rationale": row.get("Rationale"),
            "evidence": evidence,
        }
        if comparator_evidence:
            commitment["comparator_evidence"] = comparator_evidence
        if str(row.get("Status vs path") or "").casefold().startswith("behind"):
            commitment["cost_of_drift"] = _cost_of_drift(
                actual=actual,
                checkpoint=checkpoint,
                unit=row.get("Unit"),
                evidence=evidence,
            )
        commitments.append(commitment)
    live = [item for item in commitments if item["measurement_status"] == "live" and item["score"] is not None]
    estimated = [item for item in commitments if item["measurement_status"] == "estimated"]
    score = round(sum(float(item["score"]) for item in live) / len(live), 1) if live else None
    return {
        "score": score,
        "commitment_count": len(commitments),
        "live_count": len(live),
        "estimated_count": len(estimated),
        "missing_count": len(commitments) - len(live) - len(estimated),
        "coverage_label": (
            f"Computed on {len(live)} of {len(commitments)} live board commitments"
            + (f" · {len(estimated)} estimates shown separately" if estimated else "")
        ),
        "weighting": "equal_weight_default",
        "commitments": commitments,
    }


def _thread_payload(path: Path | None, root: Path) -> dict[str, Any]:
    if path is None:
        return {"threads": [], "source_file": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {"threads": []}
    threads = payload.get("threads") if isinstance(payload, dict) else []
    normalized_threads: list[dict[str, Any]] = []
    for raw_thread in threads if isinstance(threads, list) else []:
        if not isinstance(raw_thread, dict):
            continue
        thread = dict(raw_thread)
        normalized_turns: list[dict[str, Any]] = []
        for raw_turn in thread.get("turns") or []:
            if not isinstance(raw_turn, dict):
                continue
            turn = dict(raw_turn)
            turn["evidence_refs"] = _resolving_references(
                turn.get("evidence_ref"),
                root,
            )
            normalized_turns.append(turn)
        thread["turns"] = normalized_turns
        normalized_threads.append(thread)
    return {"threads": normalized_threads, "source_file": _relative(path, root)}


def _resolving_references(value: Any, root: Path) -> list[dict[str, str]]:
    """Convert workbook prose references into file + locator contracts.

    Dataset seed threads intentionally read like human notes. The UI and
    assistant runtime need a deterministic reference shape instead of opaque
    strings such as "Remediation log RD-01/04". This resolver only maps
    records to files that really exist in the current source pack.
    """

    text = str(value or "").strip()
    if not text or text == "—":
        return []
    registry = {
        "remediation": "19_Document_Vault/Remediation_Decision_Log_Jun2026.xlsx",
        "bu_cost": "12_Group_Financials/BU_Cost_Variance_H1_2026.xlsx",
        "business_events": "16_Business_Events/Business_Events_Register_Q4-2025_H1-2026.xlsx",
        "initiatives": "21_Initiatives/Initiative_Register.xlsx",
        "sop": "19_Document_Vault/AP_Controls_SOP_v3_Jun2026.pdf",
        "fx_policy": "19_Document_Vault/FX_Hedging_Policy_v2_Jan2026.docx",
        "signals": "17_Signals/Signals_Register_Jun2026.xlsx",
        "calendar": "14_CEO_Office/CEO_Calendar_Mizan_Apr-Jul_2026.xlsx",
        "glidepaths": "20_Board_KPIs/Board_KPI_Glidepaths.xlsx",
    }
    candidates: list[tuple[str, str]] = []
    for part in (item.strip() for item in text.split(";")):
        lowered = part.casefold()
        filename_match = re.search(r"[\w.-]+\.(?:xlsx|pdf|docx|pptx|txt|csv)", part, re.I)
        file_path: str | None = None
        if filename_match:
            found = _find(root, filename_match.group(0))
            file_path = _relative(found, root)
        if not file_path:
            if "remediation" in lowered or re.search(r"\brd-\d+", lowered):
                file_path = registry["remediation"]
            elif "bu_cost" in lowered or "cost_variance" in lowered:
                file_path = registry["bu_cost"]
            elif "business_event" in lowered or re.search(r"\bev-\d+", lowered):
                file_path = registry["business_events"]
            elif "initiative" in lowered or re.search(r"\binit-\d+", lowered):
                file_path = registry["initiatives"]
            elif "sop" in lowered:
                file_path = registry["sop"]
            elif "hedging_policy" in lowered or "fx_hedging" in lowered:
                file_path = registry["fx_policy"]
            elif "signal" in lowered or re.search(r"\bsig-\d+", lowered):
                file_path = registry["signals"]
            elif "calendar" in lowered or "monday brief" in lowered:
                file_path = registry["calendar"]
            elif "glidepath" in lowered or re.search(r"\bkpi-\d+", lowered):
                file_path = registry["glidepaths"]
        if file_path and (root / file_path).is_file():
            candidates.append((file_path, part))
    seen: set[tuple[str, str]] = set()
    results: list[dict[str, str]] = []
    for file_path, locator in candidates:
        key = (file_path, locator)
        if key in seen:
            continue
        seen.add(key)
        results.append({"file": file_path, "locator": locator})
    return results


def _decision_seeds(threads: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    proposed = next(
        (
            turn
            for thread in threads
            for turn in (thread.get("turns") or [])
            if "PROPOSED DECISION" in str(turn.get("text") or "")
        ),
        None,
    )
    decisions: list[dict[str, Any]] = []
    if proposed:
        decisions.append(
            {
                "key": "apply-june-eur-hedge",
                "title": "Apply hedge coverage to the June EUR payment run",
                "summary": "Atlas identified unused May coverage before the next Servier payment cycle.",
                "decision": "Approve or decline applying HD-2026-019 to the June EUR run.",
                "priority": "watch",
                "raised_by": "Atlas · Group CFO assistant",
                "timing": "Before the June EUR payment run",
                "choices": ["Approve", "Decline"],
                "evidence_refs": _resolving_references(
                    proposed.get("evidence_ref"),
                    root,
                ),
                "status_labels": {
                    "Approve": "Approved for the June payment run",
                    "Decline": "Declined",
                },
            }
        )
    memo = _find(root, "GulfColdChain_Renegotiation_Approval_Memo_Jun2026.pdf")
    if memo:
        decisions.append(
            {
                "key": "cold-chain-renegotiation-mandate",
                "title": "Approve the Gulf Cold-Chain renegotiation mandate",
                "summary": "The uncapped renewal is above the budget assumption; the sourced mandate targets recurring savings.",
                "decision": "Approve the mandate or hold it for further review.",
                "priority": "critical",
                "raised_by": "Sara Al-Mahmoud · Group CFO",
                "timing": "Current review",
                "choices": ["Approve", "Hold"],
                "evidence_refs": [
                    {"file": _relative(memo, root), "locator": "approval memo"},
                    {
                        "file": "17_Signals/Signals_Register_Jun2026.xlsx",
                        "locator": "SIG-2026-11",
                    },
                ],
                "status_labels": {
                    "Approve": "Memo approved",
                    "Hold": "Held for further review",
                },
            }
        )
    return decisions


def _assistant_memory(
    rows: list[dict[str, Any]],
    source_file: str | None,
) -> dict[str, Any] | None:
    """Build one auditable decision-memory sentence from the current log."""

    recovered = [
        row
        for row in rows
        if float(row.get("Recovered to date (SAR)") or 0) > 0
        and str(row.get("Approval status") or "").casefold() == "approved"
    ]
    if not recovered:
        return None
    row = sorted(recovered, key=lambda item: str(item.get("Date") or ""), reverse=True)[0]
    recovered_sar = float(row.get("Recovered to date (SAR)") or 0)
    approved_by = str(row.get("Approved by") or "the accountable executive").strip()
    decision_date = _iso(row.get("Date")) or "date not supplied"
    return {
        "record_id": row.get("ID"),
        "text": (
            f"{row.get('ID')} was approved by {approved_by} on {decision_date}; "
            f"SAR {recovered_sar:,.0f} is recorded as recovered to date."
        ),
        "evidence": {
            "file": source_file,
            "sheet": "Decision_Log",
            "record_id": row.get("ID"),
        },
    }


def _dated(rows: Iterable[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: str(row.get(key) or ""))


def derive_strategy_enrichment(
    dataset_root: Path,
    *,
    finance_kpi: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(dataset_root)
    glidepath_path = _find(root, "Board_KPI_Glidepaths.xlsx")
    actuals_path = _find(root, "KPI_Operational_Actuals_Monthly.xlsx")
    initiatives_path = _find(root, "Initiative_Register.xlsx")
    events_path = _find(root, "Business_Events_Register_Q4-2025_H1-2026.xlsx")
    pulse_path = _find(root, "Daily_Flash_May-Jun_2026.xlsx")
    profiles_path = _find(root, "Assistant_Profiles.xlsx")
    threads_path = _find(root, "A2A_Seed_Threads.json")
    decisions_path = _find(root, "Remediation_Decision_Log_Jun2026.xlsx")
    question_bank_path = _find(root, "CEO_500_Questions_StrategyOS.xlsx")

    glidepaths = _records(glidepath_path, "Glidepaths")
    actuals = _records(actuals_path, "KPI_Actuals_Monthly")
    initiatives = _records(initiatives_path, "Initiative_Register")
    milestones = _records(initiatives_path, "Milestones")
    events = _records(events_path, "Events_Register")
    pulse = _records(pulse_path, "Daily_Flash")
    profiles = _records(profiles_path, "Assistant_Profiles")
    remediation_rows = [
        row
        for row in _records(decisions_path, "Decision_Log")
        if str(row.get("ID") or "").startswith("RD-")
    ]
    question_rows = _records(question_bank_path, "CEO_Question_Bank")
    thread_payload = _thread_payload(threads_path, root)

    achievements = [
        {
            "event_id": row.get("Event_ID"),
            "date": _iso(row.get("Date")),
            "headline": row.get("Display_headline") or row.get("Event"),
            "recognition_target": row.get("Recognition_target"),
            "evidence_refs": _resolving_references(row.get("Evidence"), root),
        }
        for row in events
        if str(row.get("Positive?") or "").upper() == "Y"
    ]
    initiative_drifts = [
        {
            "initiative_id": row.get("INIT_ID"),
            "title": row.get("Initiative"),
            "status": row.get("Status"),
            "owner": row.get("Owner"),
            "kpi_link": row.get("KPI_link"),
            "note": row.get("Latest_note"),
            "evidence_refs": _resolving_references(row.get("Evidence_Ref"), root),
        }
        for row in initiatives
        if str(row.get("Status") or "").casefold() not in {"on-track", "done"}
    ]
    milestone_drifts = [
        {
            "initiative_id": row.get("INIT_ID"),
            "milestone": row.get("Milestone"),
            "due": _iso(row.get("Due")),
            "status": row.get("Status"),
            "evidence_refs": _resolving_references(row.get("Evidence_Ref"), root),
        }
        for row in milestones
        if any(token in str(row.get("Status") or "").casefold() for token in ("late", "missed", "at-risk"))
    ]
    pulse_rows = [
        {
            **{key: value for key, value in row.items() if key != "Date"},
            "Date": _iso(row.get("Date")),
        }
        for row in _dated(pulse, "Date")
    ]
    profile_rows = [
        {
            "persona": row.get("Persona"),
            "assistant_name": row.get("Assistant_name"),
            "named_by": row.get("Named_by"),
            "connected_sources": row.get("Connected_sources"),
            "last_refresh": str(row.get("Last_refresh") or ""),
            "threads_30d": int(row.get("Threads_30d") or 0),
            "readiness_pct": float(row.get("Readiness_pct") or 0),
            "readiness_breakdown": [
                int(value.strip()) for value in str(row.get("Readiness_breakdown (freshness/depth/usage)") or "").split("/")
                if value.strip().isdigit()
            ],
            "note": row.get("Note"),
            "evidence": {
                "file": _relative(profiles_path, root),
                "sheet": "Assistant_Profiles",
                "record_id": row.get("Persona"),
            },
        }
        for row in profiles
    ]
    current_audit_rows = remediation_rows[:8]
    recovery_meter = {
        "identified_sar": round(
            sum(float(row.get("Value (SAR)") or 0) for row in current_audit_rows),
            2,
        ),
        # The locked figure comes from the live Analyst–Auditor run.  This
        # source value is a fallback only; the browser replaces it with the
        # current run's reconciled recoverable total when available.
        "locked_sar_fallback": round(
            sum(
                float(row.get("Value (SAR)") or 0)
                for row in current_audit_rows
                if str(row.get("Approval status") or "").casefold() == "approved"
            ),
            2,
        ),
        "recovered_sar": round(
            sum(float(row.get("Recovered to date (SAR)") or 0) for row in current_audit_rows),
            2,
        ),
        "items": [
            {
                "id": row.get("ID"),
                "title": row.get("Finding / Item"),
                "value_sar": float(row.get("Value (SAR)") or 0),
                "recovered_sar": float(row.get("Recovered to date (SAR)") or 0),
                "status": row.get("Status"),
                "decision": row.get("Decision"),
                "evidence": {
                    "file": _relative(decisions_path, root),
                    "sheet": "Decision_Log",
                    "record_id": row.get("ID"),
                },
            }
            for row in current_audit_rows
        ],
        "evidence": {"file": _relative(decisions_path, root), "sheet": "Decision_Log"},
    }
    question_themes = sorted(
        {str(row.get("Theme") or "").strip() for row in question_rows if row.get("Theme")}
    )

    return {
        "status": "ready" if glidepaths and initiatives and events else "partial",
        "virtual_now": "2026-06-01T08:00:00+03:00",
        "demo_window": {"start": "2026-06-01", "end": "2026-06-07"},
        "plan_health": _plan_health(
            glidepaths,
            _relative(glidepath_path, root),
            finance_kpi,
        ),
        "operational_actuals": {
            "row_count": len(actuals),
            "kpi_ids": sorted({str(row.get("KPI_ID")) for row in actuals if row.get("KPI_ID")}),
            "source_file": _relative(actuals_path, root),
        },
        "initiatives": initiatives,
        "initiative_drifts": initiative_drifts,
        "milestone_drifts": milestone_drifts,
        "achievements": achievements,
        "daily_pulse": pulse_rows,
        "assistant_profiles": profile_rows,
        "assistant_threads": thread_payload,
        "decision_seeds": _decision_seeds(thread_payload["threads"], root),
        "assistant_memory": _assistant_memory(
            current_audit_rows,
            _relative(decisions_path, root),
        ),
        "recovery_meter": recovery_meter,
        "remediation_decisions": remediation_rows,
        "question_bank": {
            "question_count": len(question_rows),
            "theme_count": len(question_themes),
            "themes": question_themes,
            "source_file": _relative(question_bank_path, root),
        },
        "source_files": [
            value for value in (
                _relative(glidepath_path, root),
                _relative(actuals_path, root),
                _relative(initiatives_path, root),
                _relative(events_path, root),
                _relative(pulse_path, root),
                _relative(profiles_path, root),
                _relative(threads_path, root),
                _relative(decisions_path, root),
                _relative(question_bank_path, root),
            ) if value
        ],
    }
