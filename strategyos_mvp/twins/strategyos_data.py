"""StrategyOS-backed twin data bindings for KPI, evidence, board, and run context."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


ROLE_VIEW_STATE: dict[str, dict[str, str]] = {
    "ceo": {"persona": "ceo", "board": "pre", "driver": "board_packet", "principal_role": "executive"},
    "cfo": {"persona": "cfo", "board": "pre", "driver": "cash_pulse", "principal_role": "operator"},
    "group_manager": {"persona": "gm", "board": "pre", "driver": "cash_pulse", "principal_role": "bu"},
    "gm": {"persona": "gm", "board": "pre", "driver": "cash_pulse", "principal_role": "bu"},
}


def _strategyos_api():
    import strategyos_mvp.api as strategyos_api

    return strategyos_api


def _canonical_role(role: str) -> str:
    normalized = str(role or "").strip().lower()
    return "group_manager" if normalized == "gm" else normalized


def _view_state(role: str) -> dict[str, str]:
    canonical = _canonical_role(role)
    return ROLE_VIEW_STATE.get(canonical, ROLE_VIEW_STATE["ceo"])


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _tokenize(text: str) -> set[str]:
    tokens = []
    current = []
    for char in str(text or "").lower():
        if char.isalnum():
            current.append(char)
            continue
        if len(current) >= 3:
            tokens.append("".join(current))
        current = []
    if len(current) >= 3:
        tokens.append("".join(current))
    return set(tokens)


def _normalize_metric_value(value: Any) -> Any:
    if isinstance(value, dict):
        resolved = _safe_int(value.get("resolved"))
        total = _safe_int(value.get("total"))
        return f"{resolved} / {total}" if total else "--"
    return value


def _status_from_metric(card_id: str, value: Any) -> tuple[str, str, list[dict[str, Any]]]:
    gaps: list[dict[str, Any]] = []
    if card_id == "citation_resolution":
        resolved = _safe_int((value or {}).get("resolved") if isinstance(value, dict) else None)
        total = _safe_int((value or {}).get("total") if isinstance(value, dict) else None)
        if total <= 0:
            return "missing", "critical", [{"type": "missing_evidence", "detail": "No StrategyOS citation records are available yet.", "owner": "reviewer"}]
        if resolved < total:
            return "stale", "warning", [{"type": "evidence_gap", "detail": f"{total - resolved} citations remain unresolved.", "owner": "reviewer"}]
        return "current", "healthy", []
    if card_id == "challenged_cases":
        challenged = _safe_int(value)
        if challenged > 0:
            return "stale", "warning", [{"type": "challenged_cases", "detail": f"{challenged} challenged cases still require reviewer closure.", "owner": "reviewer"}]
        return "current", "healthy", []
    if card_id == "board_packet_reports":
        reports = _safe_int(value)
        if reports <= 0:
            return "missing", "critical", [{"type": "board_pack_missing", "detail": "No governed board/report artifacts are surfaced for the latest run.", "owner": "ceo"}]
        return "current", "healthy", []
    if card_id == "plan_health":
        label = str(value or "")
        lowered = label.lower()
        if "awaiting" in lowered or "needs" in lowered or "review" in lowered:
            return "stale", "warning", [{"type": "plan_health_attention", "detail": label or "Plan health requires attention.", "owner": "ceo"}]
        return "current", "healthy", []
    if value in (None, "", "--"):
        return "missing", "critical", [{"type": "missing_metric", "detail": f"StrategyOS metric '{card_id}' is not populated.", "owner": "operator"}]
    return "current", "healthy", []


def load_role_surface(role: str) -> dict[str, Any] | None:
    strategyos_api = _strategyos_api()
    summary = strategyos_api._latest_summary()
    if not isinstance(summary, dict):
        return None

    view_state = _view_state(role)
    findings_payload = strategyos_api._latest_run_findings_payload(
        summary,
        include_run_dir=True,
        public_safe=False,
        view_state={
            "persona": view_state["persona"],
            "board": view_state["board"],
            "driver": view_state["driver"],
        },
    )
    return {
        "summary": summary,
        "findings_payload": findings_payload,
        "report_contracts": strategyos_api._summary_report_contracts(summary),
    }


def _selected_kpi_ids(role: str) -> tuple[str, ...]:
    canonical = _canonical_role(role)
    if canonical == "ceo":
        return (
            "recoverable_value",
            "citation_resolution",
            "challenged_cases",
            "board_packet_reports",
            "plan_health",
        )
    if canonical == "cfo":
        return (
            "recoverable_value",
            "governed_cases",
            "citation_resolution",
            "challenged_cases",
            "board_packet_reports",
        )
    return (
        "governed_cases",
        "citation_resolution",
        "challenged_cases",
        "board_packet_reports",
        "plan_health",
    )


def build_role_kpis(role: str) -> list[dict[str, Any]]:
    surface = load_role_surface(role)
    if surface is None:
        return []

    payload = surface["findings_payload"]
    summary = surface["summary"]
    publication = payload.get("publication") or {}
    plan_health = payload.get("plan_health") or {}
    cards_by_id = {
        str(item.get("card_id") or ""): item
        for item in list(payload.get("kpi_cards") or [])
        if isinstance(item, dict)
    }
    cards_by_id["board_packet_reports"] = {
        "card_id": "board_packet_reports",
        "label": "Board packet reports",
        "value": _safe_int(publication.get("report_count")),
        "unit": "count",
        "trend_hint": "board_packet",
    }
    cards_by_id["plan_health"] = {
        "card_id": "plan_health",
        "label": "Plan health",
        "value": str(plan_health.get("label") or plan_health.get("status") or "Awaiting run"),
        "unit": "state",
        "trend_hint": "plan_health",
    }

    freshness = str(
        summary.get("created_at")
        or (summary.get("latest_pointer") or {}).get("updated_at")
        or summary.get("updated_at")
        or ""
    )
    threshold_map = {
        "citation_resolution": "resolved == total",
        "challenged_cases": 0,
        "board_packet_reports": ">= 1 surfaced report",
        "governed_cases": ">= 1 governed case",
        "recoverable_value": "> 0",
        "plan_health": "review gate cleared",
    }
    owner_map = {
        "recoverable_value": "cfo",
        "governed_cases": "reviewer",
        "citation_resolution": "reviewer",
        "challenged_cases": "reviewer",
        "board_packet_reports": "ceo",
        "plan_health": "ceo",
    }
    results: list[dict[str, Any]] = []
    for card_id in _selected_kpi_ids(role):
        card = cards_by_id.get(card_id)
        if not card:
            continue
        raw_value = card.get("value")
        status, health, gaps = _status_from_metric(card_id, raw_value)
        results.append({
            "node_id": card_id,
            "label": card.get("label") or card_id.replace("_", " ").title(),
            "value": _normalize_metric_value(raw_value),
            "raw_value": raw_value,
            "unit": card.get("unit"),
            "status": status,
            "health": health,
            "threshold": threshold_map.get(card_id),
            "freshness": freshness,
            "trend_hint": card.get("trend_hint"),
            "owner": owner_map.get(card_id),
            "gaps": gaps,
            "source": "strategyos",
        })
    return results


def build_runtime_observations(role: str) -> list[dict[str, Any]]:
    return build_role_kpis(role)


def _score_finding(query_tokens: set[str], finding: dict[str, Any]) -> int:
    haystack = " ".join(
        str(finding.get(key) or "")
        for key in ("title", "pattern_label", "pattern_type", "owner", "finding_id")
    )
    return len(query_tokens & _tokenize(haystack))


def select_evidence_records(findings: Iterable[dict[str, Any]], query: str, limit: int = 3) -> list[dict[str, Any]]:
    records = [item for item in findings if isinstance(item, dict)]
    if not records:
        return []
    tokens = _tokenize(query)
    ranked = sorted(
        records,
        key=lambda item: (_score_finding(tokens, item), _safe_float(item.get("recoverable_sar"))),
        reverse=True,
    )
    selected = ranked[:limit] if any(_score_finding(tokens, item) for item in ranked) else ranked[:limit]
    evidence: list[dict[str, Any]] = []
    for item in selected:
        contracts = item.get("contracts") if isinstance(item.get("contracts"), dict) else {}
        evidence_contract = contracts.get("evidence") if isinstance(contracts.get("evidence"), dict) else {}
        report_contract = contracts.get("report") if isinstance(contracts.get("report"), dict) else {}
        evidence.append({
            "finding_id": item.get("finding_id"),
            "title": item.get("title"),
            "pattern_label": item.get("pattern_label"),
            "owner": item.get("owner"),
            "citation_count": _safe_int(item.get("citation_count")),
            "challenged": bool(item.get("challenged")),
            "case_href": item.get("case_href"),
            "evidence_preview_href": item.get("evidence_preview_href") or evidence_contract.get("preview_href"),
            "evidence_qa_href": (evidence_contract or {}).get("evidence_qa_href"),
            "report_preview_href": item.get("report_preview_href") or report_contract.get("preview_href"),
            "contracts": contracts,
        })
    return evidence


def build_run_context(surface: dict[str, Any] | None) -> dict[str, Any]:
    if surface is None:
        return {
            "available": False,
            "run_id": None,
            "run_dir": None,
            "approval_status": None,
            "current_stage": None,
        }
    summary = surface["summary"]
    payload = surface["findings_payload"]
    publication = payload.get("publication") or {}
    board_portal = payload.get("board_portal") or {}
    return {
        "available": True,
        "run_id": summary.get("run_id") or payload.get("run_id"),
        "run_dir": summary.get("run_dir"),
        "approval_status": summary.get("approval_status") or payload.get("approval_status"),
        "current_stage": summary.get("current_stage"),
        "requires_human_review": bool(summary.get("requires_human_review")),
        "publication_status": publication.get("status") or publication.get("publish_state"),
        "board_state": board_portal.get("presentation_state") or board_portal.get("state"),
        "latest_metric_point": (payload.get("trend") or {}).get("latest_point"),
    }


def build_board_context(surface: dict[str, Any] | None) -> dict[str, Any]:
    if surface is None:
        return {
            "available": False,
            "status": "pending",
            "report_count": 0,
            "evidence_count": 0,
            "preview_route": None,
        }
    payload = surface["findings_payload"]
    publication = payload.get("publication") or {}
    board_portal = payload.get("board_portal") or {}
    board_pack = publication.get("board_pack") or {}
    meeting = board_portal.get("meeting") if isinstance(board_portal.get("meeting"), dict) else {}
    state_detail = board_portal.get("state_detail") if isinstance(board_portal.get("state_detail"), dict) else {}
    return {
        "available": True,
        "status": board_pack.get("status") or publication.get("status") or "pending",
        "presentation_state": board_portal.get("presentation_state") or board_portal.get("state"),
        "publish_state": publication.get("publish_state"),
        "report_count": _safe_int(publication.get("report_count")),
        "evidence_count": _safe_int(publication.get("evidence_count")),
        "preview_route": board_pack.get("preview_route") or publication.get("preview_route"),
        "meeting_title": meeting.get("title") or board_portal.get("state_label") or "Governed board packet",
        "summary": state_detail.get("summary") or board_portal.get("governance_note"),
        "allowed_actions": list(board_pack.get("allowed_actions") or []),
        "deck_release": board_portal.get("deck_release"),
        "supplementary": board_portal.get("supplementary"),
    }


def build_consistency_payload(surface: dict[str, Any] | None) -> dict[str, Any]:
    if surface is None:
        return {"aligned": False, "issues": ["No StrategyOS run is available yet."]}
    summary = surface["summary"]
    payload = surface["findings_payload"]
    publication = payload.get("publication") or {}
    board_portal = payload.get("board_portal") or {}
    report_contracts = surface["report_contracts"] or {}
    issues: list[str] = []
    summary_run_id = str(summary.get("run_id") or "")
    publication_run_id = str(publication.get("run_id") or "")
    board_run_id = str(((board_portal.get("meeting") or {}).get("run_id")) or "")
    if publication_run_id and summary_run_id and publication_run_id != summary_run_id:
        issues.append("Publication run_id does not match the latest StrategyOS run.")
    if board_run_id and summary_run_id and board_run_id != summary_run_id:
        issues.append("Board packet run_id does not match the latest StrategyOS run.")
    if _safe_int(publication.get("report_count")) != len(list(report_contracts.get("reports") or [])):
        issues.append("Publication report_count does not match surfaced report contracts.")
    if _safe_int(publication.get("evidence_count")) != len(list(report_contracts.get("evidence") or [])):
        issues.append("Publication evidence_count does not match surfaced evidence contracts.")
    return {"aligned": not issues, "issues": issues}


def build_surface_payload(role: str, fallback_kpis: dict[str, Any] | None = None) -> dict[str, Any]:
    surface = load_role_surface(role)
    if surface is None:
        return {
            "data_source": "twin_repository_fallback",
            "source_status": "missing",
            "bounded_fallback": True,
            "kpis": fallback_kpis or {},
            "run_context": build_run_context(None),
            "board": build_board_context(None),
            "evidence": [],
            "consistency": build_consistency_payload(None),
            "metrics": {},
            "publication": {},
            "plan_health": {},
        }
    kpis = {item["node_id"]: item for item in build_role_kpis(role)}
    payload = surface["findings_payload"]
    evidence = select_evidence_records(payload.get("findings") or [], "", limit=3)
    return {
        "data_source": "strategyos",
        "source_status": "current_run",
        "bounded_fallback": False,
        "kpis": kpis,
        "run_context": build_run_context(surface),
        "board": build_board_context(surface),
        "evidence": evidence,
        "consistency": build_consistency_payload(surface),
        "metrics": payload.get("metrics") or {},
        "publication": payload.get("publication") or {},
        "plan_health": payload.get("plan_health") or {},
    }


def compose_investigation_payload(role: str, query: str) -> dict[str, Any]:
    surface = load_role_surface(role)
    if surface is None:
        return {
            "data_source": "twin_repository_fallback",
            "source_status": "missing",
            "bounded_fallback": True,
            "response": {
                "summary": "No governed StrategyOS run is available yet. The twin remains bounded to persisted local state until a real run lands.",
                "mode": "bounded_fallback",
            },
            "run_context": build_run_context(None),
            "board": build_board_context(None),
            "evidence": [],
            "consistency": build_consistency_payload(None),
            "linked_finding_ids": [],
        }
    payload = surface["findings_payload"]
    metrics = payload.get("metrics") or {}
    publication = payload.get("publication") or {}
    plan_health = payload.get("plan_health") or {}
    evidence = select_evidence_records(payload.get("findings") or [], query, limit=3)
    run_context = build_run_context(surface)
    board = build_board_context(surface)
    resolved = _safe_int(metrics.get("resolved_count"))
    citations = _safe_int(metrics.get("citation_count"))
    finding_count = _safe_int(payload.get("finding_count") or metrics.get("finding_count"))
    report_count = _safe_int(publication.get("report_count"))
    recoverable = _safe_float(metrics.get("total_recoverable_sar") or payload.get("total_recoverable_sar"))
    lead = evidence[0] if evidence else None
    lead_text = (
        f" Top linked evidence: {lead.get('title')} ({lead.get('finding_id')}, {lead.get('citation_count')} citations)."
        if lead
        else ""
    )
    return {
        "data_source": "strategyos",
        "source_status": "current_run",
        "bounded_fallback": False,
        "response": {
            "summary": (
                f"Latest StrategyOS run {run_context.get('run_id') or 'latest'} is "
                f"{str(run_context.get('approval_status') or 'pending').replace('_', ' ')}. "
                f"It currently carries SAR {recoverable:,.0f} recoverable value across {finding_count} governed cases, "
                f"{resolved}/{citations} citation resolution, and {report_count} surfaced board/report artifacts."
                f" Plan health: {plan_health.get('label') or plan_health.get('status') or 'bounded'}."
                f"{lead_text}"
            ).strip(),
            "mode": "strategyos_live",
            "query": query,
        },
        "run_context": run_context,
        "board": board,
        "evidence": evidence,
        "consistency": build_consistency_payload(surface),
        "linked_finding_ids": [str(item.get("finding_id")) for item in evidence if item.get("finding_id")],
        "publication": publication,
        "metrics": metrics,
    }
