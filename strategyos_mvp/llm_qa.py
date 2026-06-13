"""Evidence-grounded LLM Q&A adapter.

The deterministic Q&A engine remains the default. This module is only used when
the caller explicitly selects LLM mode and the model-provider boundary is
enabled in server-side config.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import EXTERNAL_MODE_MODEL_PROVIDER
from .ingestion import DataBundle
from .models import Finding


SYSTEM_PROMPT = """You are StrategyOS evidence Q&A.
Answer only from the JSON evidence supplied by the application.
If the evidence is insufficient, say that and set matched=false.
Return only valid json with keys: matched, answer, basis, citations, suggestions.
Example json output:
{"matched": true, "answer": "SAR 120.00 is recoverable.", "basis": "Finding F-001 in supplied evidence.", "citations": [{"source_path": "ap.xlsx", "locator": "row 2", "excerpt": "duplicate payment", "finding_id": "F-001"}], "suggestions": []}
Do not invent vendors, totals, findings, citations, or source files.
"""


def chat_status(config: Any) -> dict[str, Any]:
    if not getattr(config, "llm_chat_enabled", False):
        return {"enabled": False, "reason": "LLM chat is disabled."}
    if not getattr(config, "model_provider_enabled", False):
        return {
            "enabled": False,
            "reason": "Model-provider use is not enabled.",
        }
    run_policy = getattr(config, "run_policy", None)
    if run_policy is None or not run_policy.allows(EXTERNAL_MODE_MODEL_PROVIDER):
        return {
            "enabled": False,
            "reason": "Run policy does not approve model-provider use.",
        }
    if not getattr(config, "llm_api_key", None):
        return {"enabled": False, "reason": "LLM API key is not configured."}
    if not getattr(config, "llm_model", None):
        return {"enabled": False, "reason": "LLM model is not configured."}
    return {
        "enabled": True,
        "provider": getattr(config, "llm_provider", "deepseek"),
        "model": getattr(config, "llm_model", ""),
    }


def answer_question(
    question: str,
    *,
    bundle: DataBundle,
    findings: list[Finding],
    summary: dict[str, Any],
    config: Any,
) -> dict[str, Any]:
    status = chat_status(config)
    if not status["enabled"]:
        return {
            "matched": False,
            "answer": status["reason"],
            "basis": "LLM chat configuration gate.",
            "citations": [],
            "suggestions": [],
            "llm_status": status,
        }

    evidence = _build_evidence_payload(bundle=bundle, findings=findings, summary=summary)
    provider_response = _call_openai_compatible_chat(
        config=config,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "evidence": evidence,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    parsed = _parse_json_answer(provider_response)
    return {
        "matched": _normalize_bool(parsed.get("matched", True)),
        "answer": str(parsed.get("answer") or "No answer returned."),
        "basis": str(parsed.get("basis") or "LLM answer grounded in supplied run evidence."),
        "citations": _normalize_citations(parsed.get("citations")),
        "suggestions": _normalize_suggestions(parsed.get("suggestions")),
        "llm_status": status,
        "model": status.get("model"),
        "provider": status.get("provider"),
    }


def _build_evidence_payload(
    *,
    bundle: DataBundle,
    findings: list[Finding],
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "run": _run_summary(summary),
        "data": {
            "ap_ledger": _frame_summary(bundle, "ap_ledger", bundle.ap),
            "ar_ledger": _frame_summary(bundle, "ar_ledger", bundle.ar),
            "available_roles": (bundle.run_metadata or {}).get("available_roles", []),
            "data_contracts": bundle.data_contracts or {},
        },
        "findings": [_finding_summary(finding) for finding in findings[:12]],
    }


def _run_summary(summary: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = [
        "run_id",
        "run_mode",
        "status",
        "current_stage",
        "approval_status",
        "total_recoverable_sar",
        "total_recoverable_usd",
        "locked_findings",
        "citation_resolution_rate",
    ]
    return {key: summary.get(key) for key in allowed_keys if key in summary}


def _frame_summary(bundle: DataBundle, role: str, frame: Any) -> dict[str, Any]:
    if frame is None or getattr(frame, "empty", True):
        return {"available": False, "rows": 0}
    contract = (bundle.data_contracts or {}).get(role) or {}
    amount_total = None
    if "Amount_SAR" in frame.columns:
        amount_total = round(float(frame["Amount_SAR"].sum()), 2)
    summary = {
        "available": True,
        "rows": int(len(frame)),
        "columns": [str(column) for column in frame.columns[:24]],
        "amount_sar_total": amount_total,
        "source_path": contract.get("relative_path"),
    }
    name_column = "Vendor_Name" if role == "ap_ledger" else "Customer_Name"
    if name_column in frame.columns and "Amount_SAR" in frame.columns:
        ranked = (
            frame.groupby(name_column)["Amount_SAR"]
            .sum()
            .sort_values(ascending=False)
            .head(5)
        )
        summary["top_parties"] = [
            {"name": str(name), "amount_sar": round(float(value), 2)}
            for name, value in ranked.items()
        ]
    return summary


def _finding_summary(finding: Finding) -> dict[str, Any]:
    return {
        "finding_id": finding.finding_id,
        "title": finding.title,
        "pattern_type": finding.pattern_type,
        "vendor_name": finding.vendor_name,
        "recoverable_sar": round(float(finding.recoverable_sar), 2),
        "confidence": finding.confidence,
        "classification": finding.classification,
        "rationale": finding.rationale,
        "remediation": finding.remediation,
        "citations": [_citation_dict(citation, finding.finding_id) for citation in finding.citations[:4]],
    }


def _citation_dict(citation: Any, finding_id: str | None = None) -> dict[str, Any]:
    if is_dataclass(citation):
        payload = asdict(citation)
    elif isinstance(citation, dict):
        payload = dict(citation)
    else:
        payload = {}
    if finding_id and "finding_id" not in payload:
        payload["finding_id"] = finding_id
    return {
        "source_path": str(payload.get("source_path") or payload.get("source") or ""),
        "locator": str(payload.get("locator") or ""),
        "excerpt": str(payload.get("excerpt") or "")[:600],
        "source_hash": payload.get("source_hash"),
        "finding_id": payload.get("finding_id"),
    }


def _call_openai_compatible_chat(
    *,
    config: Any,
    messages: list[dict[str, str]],
) -> str:
    url = _chat_completions_url(str(config.llm_base_url))
    payload = {
        "model": config.llm_model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
    }
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.llm_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=config.llm_timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"LLM provider returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"LLM provider is unavailable: {exc.reason}") from exc

    parsed = json.loads(body)
    choices = parsed.get("choices") or []
    if not choices:
        raise RuntimeError("LLM provider returned no choices.")
    content = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("LLM provider returned an empty answer.")
    return content


def _chat_completions_url(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return f"{trimmed}/chat/completions"


def _parse_json_answer(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "matched": True,
            "answer": raw,
            "basis": "LLM provider returned plain text instead of JSON.",
            "citations": [],
            "suggestions": [],
        }
    return payload if isinstance(payload, dict) else {}


def _normalize_citations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    citations = []
    for item in value[:8]:
        if isinstance(item, dict):
            citations.append(_citation_dict(item))
    return citations


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "n"}
    return bool(value)


def _normalize_suggestions(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:5] if str(item).strip()]
