"""Tenant-scoped StrategyOS Authority Matrix and enforcement decisions."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .state_store import database_connection, ensure_data_schema, fetchone_dict, json_blob


RIGHTS = ("none", "view", "analyse", "recommend", "act-with-approval")
RIGHT_RANK = {right: index for index, right in enumerate(RIGHTS)}
DOMAINS = ("finance", "hr", "contracts", "board_materials", "assistant_team")


def default_authority_matrix() -> dict[str, Any]:
    return {
        "policy_id": "authority-matrix",
        "version": 1,
        "section": "§3",
        "status": "published",
        "domains": list(DOMAINS),
        "subjects": [
            {"id": "persona:ceo", "label": "Group CEO", "type": "persona", "rights": {"finance": "analyse", "hr": "analyse", "contracts": "recommend", "board_materials": "analyse", "assistant_team": "analyse"}},
            {"id": "persona:cio", "label": "Group CIO", "type": "persona", "rights": {"finance": "view", "hr": "view", "contracts": "view", "board_materials": "view", "assistant_team": "analyse"}},
            {"id": "persona:gm", "label": "BU General Manager", "type": "persona", "rights": {"finance": "view", "hr": "view", "contracts": "none", "board_materials": "none", "assistant_team": "none"}},
            {"id": "assistant:hermes", "label": "Hermes", "type": "assistant", "rights": {"finance": "recommend", "hr": "view", "contracts": "recommend", "board_materials": "recommend", "assistant_team": "analyse"}},
            {"id": "assistant:atlas", "label": "Atlas", "type": "assistant", "rights": {"finance": "recommend", "hr": "none", "contracts": "analyse", "board_materials": "view", "assistant_team": "none"}},
            {"id": "assistant:minerva", "label": "Minerva", "type": "assistant", "rights": {"finance": "none", "hr": "none", "contracts": "none", "board_materials": "analyse", "assistant_team": "none"}},
            {"id": "assistant:argus", "label": "Argus", "type": "assistant", "rights": {"finance": "analyse", "hr": "none", "contracts": "view", "board_materials": "none", "assistant_team": "none"}},
            {"id": "assistant:iris", "label": "Iris", "type": "assistant", "rights": {"finance": "view", "hr": "view", "contracts": "none", "board_materials": "none", "assistant_team": "none"}},
            {"id": "agent:finance-analyst", "label": "Finance Analyst", "type": "agent", "rights": {"finance": "analyse", "hr": "none", "contracts": "view", "board_materials": "none", "assistant_team": "none"}},
            {"id": "agent:finance-auditor", "label": "Finance Auditor", "type": "agent", "rights": {"finance": "recommend", "hr": "none", "contracts": "analyse", "board_materials": "none", "assistant_team": "none"}},
            {"id": "agent:cash-recovery", "label": "Cash Recovery Agent", "type": "agent", "rights": {"finance": "act-with-approval", "hr": "none", "contracts": "view", "board_materials": "none", "assistant_team": "none"}},
            {"id": "agent:evidence-closure", "label": "Evidence Closure Agent", "type": "agent", "rights": {"finance": "analyse", "hr": "none", "contracts": "analyse", "board_materials": "view", "assistant_team": "none"}},
            {"id": "agent:board-pack", "label": "Board Pack Agent", "type": "agent", "rights": {"finance": "view", "hr": "none", "contracts": "view", "board_materials": "act-with-approval", "assistant_team": "none"}},
            {"id": "agent:runtime-guardrail", "label": "Runtime Guardrail Agent", "type": "agent", "rights": {"finance": "none", "hr": "none", "contracts": "none", "board_materials": "none", "assistant_team": "analyse"}},
        ],
        "approver_chains": {
            "finance_action": ["Group CFO", "Group CEO"],
            "contract_action": ["Legal", "Group CFO", "Group CEO"],
            "board_release": ["Company Secretary", "Group CEO"],
        },
        "updated_at": None,
        "updated_by": "system-default",
    }


def _data_root() -> Path:
    configured = os.getenv("STRATEGYOS_AUTHORITY_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    workspace = os.getenv("STRATEGYOS_WORKSPACE_ROOT")
    base = Path(workspace).expanduser().resolve() if workspace else Path(__file__).resolve().parents[1]
    return base / ".strategyos_mvp_data" / "authority"


def _safe_tenant(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "default"))[:120] or "default"


def _normalize(matrix: Mapping[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(default_authority_matrix())
    payload.update({key: copy.deepcopy(value) for key, value in dict(matrix).items() if key not in {"subjects", "domains"}})
    payload["domains"] = [domain for domain in list(matrix.get("domains") or DOMAINS) if domain in DOMAINS]
    subjects = []
    seen: set[str] = set()
    for raw in list(matrix.get("subjects") or []):
        if not isinstance(raw, Mapping):
            continue
        subject_id = str(raw.get("id") or "").strip().lower()
        if not subject_id or subject_id in seen or ":" not in subject_id:
            continue
        seen.add(subject_id)
        rights = {
            domain: str((raw.get("rights") or {}).get(domain) or "none")
            for domain in payload["domains"]
        }
        if any(right not in RIGHTS for right in rights.values()):
            raise ValueError(f"Invalid authority right for {subject_id}.")
        subjects.append({
            "id": subject_id,
            "label": str(raw.get("label") or subject_id),
            "type": str(raw.get("type") or subject_id.split(":", 1)[0]),
            "rights": rights,
        })
    if not subjects:
        raise ValueError("Authority Matrix requires at least one valid subject.")
    payload["subjects"] = subjects
    payload["version"] = max(1, int(payload.get("version") or 1))
    return payload


def _file_path(tenant_id: str) -> Path:
    return _data_root() / f"{_safe_tenant(tenant_id)}.json"


def _read_file(tenant_id: str) -> dict[str, Any]:
    path = _file_path(tenant_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default_authority_matrix()
    return _normalize(payload)


def _write_file(
    tenant_id: str,
    matrix: Mapping[str, Any],
    *,
    actor: str,
    expected_version: int | None,
) -> dict[str, Any]:
    path = _file_path(tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f".{path.name}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current = _read_file(tenant_id)
        current_version = int(current.get("version") or 1)
        if expected_version is not None and current_version != int(expected_version):
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            raise ValueError("Authority Matrix changed since it was loaded; refresh before saving.")
        normalized = _normalize(matrix)
        normalized["version"] = current_version + 1
        normalized["updated_at"] = datetime.now(UTC).isoformat()
        normalized["updated_by"] = actor
        handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(normalized, stream, indent=2, ensure_ascii=False, sort_keys=True)
            Path(temporary).replace(path)
            audit = path.parent / f"{path.stem}.audit.jsonl"
            with audit.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"at": datetime.now(UTC).isoformat(), "actor": actor, "version": normalized["version"], "matrix": normalized}, ensure_ascii=False) + "\n")
        finally:
            Path(temporary).unlink(missing_ok=True)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return normalized


def get_authority_matrix(tenant_id: str) -> dict[str, Any]:
    connection, skipped = database_connection()
    if skipped is None and connection is not None:
        with connection as conn:
            ensure_data_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """select version, matrix_json, updated_at, updated_by
                       from strategyos_authority_matrices where tenant_key = %s""",
                    (str(tenant_id),),
                )
                row = fetchone_dict(cur)
        if row:
            payload = _normalize(dict(row.get("matrix_json") or {}))
            payload.update({"version": int(row.get("version") or payload["version"]), "updated_at": str(row.get("updated_at") or ""), "updated_by": row.get("updated_by")})
            return payload
    return _read_file(tenant_id)


def save_authority_matrix(tenant_id: str, matrix: Mapping[str, Any], *, actor: str, expected_version: int | None = None) -> dict[str, Any]:
    current = get_authority_matrix(tenant_id)
    if expected_version is not None and int(current.get("version") or 1) != int(expected_version):
        raise ValueError("Authority Matrix changed since it was loaded; refresh before saving.")
    normalized = _normalize(matrix)
    normalized["version"] = int(current.get("version") or 1) + 1
    normalized["updated_at"] = datetime.now(UTC).isoformat()
    normalized["updated_by"] = actor
    connection, skipped = database_connection()
    if skipped is None and connection is not None:
        with connection as conn:
            ensure_data_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """insert into strategyos_authority_matrices (tenant_key, version, matrix_json, updated_by)
                       values (%s, %s, %s::jsonb, %s)
                       on conflict (tenant_key) do update set version = excluded.version,
                           matrix_json = excluded.matrix_json, updated_by = excluded.updated_by, updated_at = now()
                       where strategyos_authority_matrices.version = %s
                       returning version""",
                    (str(tenant_id), normalized["version"], json_blob(normalized), actor, int(current.get("version") or 1)),
                )
                if cur.fetchone() is None:
                    raise ValueError("Authority Matrix changed since it was loaded; refresh before saving.")
                cur.execute(
                    """insert into strategyos_authority_matrix_audit (tenant_key, version, matrix_json, actor)
                       values (%s, %s, %s::jsonb, %s)""",
                    (str(tenant_id), normalized["version"], json_blob(normalized), actor),
                )
            conn.commit()
        return normalized
    return _write_file(
        tenant_id,
        matrix,
        actor=actor,
        expected_version=expected_version,
    )


def authority_decision(matrix: Mapping[str, Any], *, subject_id: str, domain: str, required_right: str) -> dict[str, Any]:
    normalized = _normalize(matrix)
    subject_key = str(subject_id).strip().lower()
    subject = next((item for item in normalized["subjects"] if item["id"] == subject_key), None)
    resolved = str((subject or {}).get("rights", {}).get(domain) or "none")
    required = required_right if required_right in RIGHTS else "view"
    allowed = RIGHT_RANK.get(resolved, 0) >= RIGHT_RANK[required]
    return {
        "allowed": allowed,
        "subject_id": subject_key,
        "subject_label": str((subject or {}).get("label") or subject_key),
        "domain": domain,
        "required_right": required,
        "resolved_right": resolved,
        "policy_id": normalized["policy_id"],
        "policy_version": normalized["version"],
        "matrix_row": f"{normalized['section']}, {subject_key} × {domain}",
        "approver_chain": normalized.get("approver_chains", {}).get(f"{domain.rstrip('s')}_action", []),
    }


def assistant_subject(persona: str | None) -> str:
    key = str(persona or "ceo").strip().lower()
    return {"ceo": "assistant:hermes", "board": "assistant:minerva", "cfo": "assistant:atlas", "bucfo": "assistant:argus", "gm": "assistant:iris", "bu": "assistant:iris"}.get(key, f"assistant:{key}")


def classify_requests(question: str, context: Mapping[str, Any] | None = None) -> list[tuple[str, str]]:
    """Collect every requested domain. Context may add restrictions, never remove them.

    This is an intent gate; source access must independently enforce data scope.
    """
    _, required = classify_request(question, context)
    text = f"{question} {json.dumps(dict(context or {}), ensure_ascii=False, default=str)}".casefold()
    aliases = {
        "finance": ("revenue", "cash", "invoice", "profit", "margin", "payment", "إيراد", "نقد"),
        "hr": ("headcount", "employee", "workforce", "hiring", "salary", "salaries", "payroll", "compensation", "bonus", "bonuses", "remuneration", "hr", "رواتب", "موظف"),
        "contracts": ("contract", "supplier agreement", "renewal", "legal term", "عقد", "عقود"),
        "board_materials": ("board", "director", "مجلس"),
        "assistant_team": ("assistant readiness", "assistant team", "atlas", "iris", "hermes", "minerva"),
    }
    domains = [domain for domain, words in aliases.items() if any(
        re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text) if word.isascii() else word in text
        for word in words
    )]
    return [(domain, required) for domain in domains or [classify_request(question, context)[0]]]


def classify_request(question: str, context: Mapping[str, Any] | None = None) -> tuple[str, str]:
    context_map = dict(context or {})
    governed_context = {
        key: context_map.get(key)
        for key in ("domain", "data_domain", "kpi_key", "topic", "board_state")
        if context_map.get(key) is not None
    }
    text = f"{question} {json.dumps(governed_context, default=str)}".lower()
    if any(token in text for token in ("board", "director", "board pack", "board material")):
        domain = "board_materials"
    elif any(token in text for token in ("contract", "supplier agreement", "renewal", "legal term")):
        domain = "contracts"
    elif any(token in text for token in ("headcount", "employee", "workforce", "turnover", "hiring", "hr ")):
        domain = "hr"
    elif any(token in text for token in ("assistant readiness", "assistant team", "atlas", "iris", "hermes", "nora")):
        domain = "assistant_team"
    else:
        domain = "finance"
    if re.search(r"\b(?:please\s+)?(?:execute|send|approve|release)\b", text) or any(
        phrase in text for phrase in ("post payment", "make payment")
    ):
        required = "act-with-approval"
    elif any(token in text for token in ("recommend", "should we", "what should", "options", "decision")):
        required = "recommend"
    elif any(token in text for token in ("why", "analyse", "analyze", "scenario", "model", "driver", "cause", "forecast")):
        required = "analyse"
    else:
        required = "view"
    return domain, required


def refusal_payload(decision: Mapping[str, Any]) -> dict[str, Any]:
    label = str(decision.get("subject_label") or decision.get("subject_id") or "This assistant")
    domain = str(decision.get("domain") or "requested information").replace("_", " ")
    citation = str(decision.get("matrix_row") or "Authority Matrix §3")
    answer = f"{label} cannot {decision.get('required_right') or 'view'} {domain} — Authority Matrix {citation}."
    return {
        "status": "ok",
        "matched": False,
        "answer": answer,
        "basis": f"Access denied by Authority Matrix version {decision.get('policy_version')}.",
        "citations": [{"source_path": "authority-matrix://published", "locator": citation, "excerpt": f"Resolved right: {decision.get('resolved_right')}; required: {decision.get('required_right')}."}],
        "suggestions": ["Ask the CEO or CIO to review the published Authority Matrix."],
        "response_mode": "authority_refusal",
        "authority_decision": dict(decision),
    }
