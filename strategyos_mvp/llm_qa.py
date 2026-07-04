"""Evidence-grounded LLM Q&A adapter.

The deterministic Q&A engine remains the default. This module is used for
evidence-grounded fallback answers when deterministic coverage is missing and
the model-provider boundary is enabled in server-side config.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, is_dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import EXTERNAL_MODE_MODEL_PROVIDER
from .ingestion import DataBundle
from .models import Finding


logger = logging.getLogger(__name__)


class _EmptyProviderResponseError(RuntimeError):
    """Raised when the provider returns no usable assistant text."""


class _MalformedProviderResponseError(RuntimeError):
    """Raised when the provider returns broken JSON-like assistant text."""


SYSTEM_PROMPT = """You are StrategyOS evidence Q&A.
Answer only from the JSON evidence supplied by the application.
If the evidence is insufficient, say that and set matched=false.
Return only valid json with keys: matched, answer, basis, citations, suggestions.
Example json output:
{"matched": true, "answer": "SAR 120.00 is recoverable.", "basis": "Finding F-001 in supplied evidence.", "citations": [{"source_path": "ap.xlsx", "locator": "row 2", "excerpt": "duplicate payment", "finding_id": "F-001"}], "suggestions": []}
Do not invent vendors, totals, findings, citations, or source files.
"""


PUBLIC_SYSTEM_PROMPT = """You are Hermes on the public StrategyOS executive surface.
Answer as a natural, board-safe CEO assistant using ONLY the supplied public executive packet.
Ground every answer in the visible public packet facts: KPIs, driver cards and movers, findings, developments, week items, board portal, running agents, KG summaries, view state, and other visible public context.
Never invent private ledger details, hidden reviewer evidence, unpublished numbers, or protected source files.
When the user asks for last week or trend context, answer from the packet's visible weekly items, KPI stories, findings, developments, driver cards, board portal, agent status, KG summaries, and public facts.
If exact last-week data is not present in the packet, say that plainly and answer from the nearest visible weekly run-rate or board-safe evidence.
Return only valid json with keys: matched, answer, basis, citations, suggestions.
For citations, prefer source_path='public_packet://latest-public' with locators like 'public_context_packet.kpis[1]' or 'public_context_packet.week[0]'.
Do not fall back to listing allowed prompts unless the public packet is genuinely insufficient.
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


def provider_health_status(config: Any) -> dict[str, Any]:
    status = chat_status(config)
    payload = {
        "enabled": bool(status.get("enabled")),
        "provider": status.get("provider") or getattr(config, "llm_provider", "deepseek"),
        "model": status.get("model") or getattr(config, "llm_model", ""),
    }
    if not status.get("enabled"):
        return {
            "status": "ok",
            **payload,
            "checked": False,
            "reason": status.get("reason") or "LLM chat is disabled.",
        }
    try:
        _call_openai_compatible_chat(
            config=config,
            messages=[
                {
                    "role": "system",
                    "content": "Return exactly the single word ok.",
                },
                {"role": "user", "content": "healthcheck"},
            ],
            temperature=0.0,
            max_tokens=8,
            response_format=None,
        )
    except RuntimeError as exc:
        return {
            "status": "failed",
            **payload,
            "checked": True,
            "reason": str(exc),
        }
    return {
        "status": "ok",
        **payload,
        "checked": True,
        "probe": "chat_completions",
    }


def answer_question(
    question: str,
    *,
    bundle: Any,
    findings: list[Any],
    summary: dict[str, Any],
    config: Any,
    public_context_packet: dict[str, Any] | None = None,
    persona: str | None = None,
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

    public_packet = dict(public_context_packet or {})
    public_mode = bool(public_packet)
    evidence = _build_evidence_payload(
        bundle=bundle,
        findings=findings,
        summary=summary,
        public_context_packet=public_packet,
        persona=persona,
    )
    default_basis = (
        "LLM answer grounded in supplied public executive packet."
        if public_mode
        else "LLM answer grounded in supplied run evidence."
    )
    json_messages = [
        {"role": "system", "content": PUBLIC_SYSTEM_PROMPT if public_mode else SYSTEM_PROMPT},
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
    ]
    try:
        provider_response = _call_openai_compatible_chat(
            config=config,
            messages=json_messages,
            response_format={"type": "json_object"},
        )
        parsed = _parse_json_answer(provider_response)
    except (_EmptyProviderResponseError, _MalformedProviderResponseError):
        try:
            provider_response = _call_openai_compatible_chat(
                config=config,
                messages=_plain_text_retry_messages(
                    question=question,
                    evidence=evidence,
                    public_mode=public_mode,
                ),
                response_format=None,
            )
        except _EmptyProviderResponseError as exc:
            raise RuntimeError(
                "LLM provider returned an empty answer after retrying with a plain-text prompt."
            ) from exc
        parsed = {
            "matched": True,
            "answer": _clean_visible_answer(provider_response),
            "basis": default_basis,
            "citations": [],
            "suggestions": [],
        }
    citations = _normalize_citations(parsed.get("citations"))
    if public_mode:
        citations = _normalize_public_packet_citations(citations, packet=public_packet, question=question)
    return {
        "matched": _normalize_bool(parsed.get("matched", True)),
        "answer": _clean_visible_answer(parsed.get("answer")) or "No answer returned.",
        "basis": str(parsed.get("basis") or default_basis),
        "citations": citations,
        "suggestions": _normalize_suggestions(parsed.get("suggestions")),
        "llm_status": status,
        "model": status.get("model"),
        "provider": status.get("provider"),
        "public_safe": public_mode,
    }


def _build_evidence_payload(
    *,
    bundle: Any,
    findings: list[Any],
    summary: dict[str, Any],
    public_context_packet: dict[str, Any] | None = None,
    persona: str | None = None,
) -> dict[str, Any]:
    if public_context_packet:
        return _public_evidence_payload(
            packet=public_context_packet,
            findings=findings,
            summary=summary,
            persona=persona,
        )
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


def _public_evidence_payload(
    *,
    packet: dict[str, Any],
    findings: list[Any],
    summary: dict[str, Any],
    persona: str | None,
) -> dict[str, Any]:
    return {
        "run": _run_summary(summary),
        "public_context": {
            "packet_id": packet.get("packet_id"),
            "persona_id": packet.get("persona_id") or persona,
            "assistant": packet.get("assistant"),
            "public_safe": bool(packet.get("public_safe", True)),
            "source": packet.get("source"),
            "view_state": packet.get("view_state") or {},
            "trace_summary": packet.get("trace_summary") or {},
            "source_boundary": ((packet.get("public_facts") or {}).get("source_boundary")),
        },
        "kpis": list(packet.get("kpis") or []),
        "drivers": list(packet.get("drivers") or []),
        "findings": list(packet.get("findings") or []),
        "public_findings": [_finding_summary(finding) for finding in findings[:12]],
        "developments": list(packet.get("developments") or []),
        "week": list(packet.get("week") or []),
        "board_portal": packet.get("board_portal") or {},
        "agent_activity": packet.get("agent_activity") or packet.get("activity") or {},
        "running_agents": list(packet.get("running_agents") or []),
        "kg_trace": {
            "nodes": list(packet.get("kg_nodes") or []),
            "edges": list(packet.get("kg_edges") or []),
        },
        "public_facts": packet.get("public_facts") or {},
        "facts": list(packet.get("facts") or []),
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


def _finding_summary(finding: Any) -> dict[str, Any]:
    if isinstance(finding, dict):
        return {
            "finding_id": finding.get("finding_id"),
            "title": finding.get("title"),
            "pattern_type": finding.get("pattern_type"),
            "vendor_name": finding.get("vendor_name"),
            "recoverable_sar": round(float(finding.get("recoverable_sar") or 0), 2),
            "confidence": finding.get("confidence"),
            "classification": finding.get("classification"),
            "rationale": finding.get("rationale") or finding.get("detail"),
            "remediation": finding.get("remediation"),
            "citations": [_citation_dict(citation, finding.get("finding_id")) for citation in (finding.get("citations") or [])[:4]],
        }
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
    temperature: float = 0.1,
    max_tokens: int = 900,
    response_format: dict[str, str] | None = None,
) -> str:
    url = _chat_completions_url(str(config.llm_base_url))
    payload = {
        "model": config.llm_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        payload["response_format"] = response_format
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
    content = _extract_provider_text(parsed)
    if not content:
        choice0 = choices[0] if isinstance(choices[0], dict) else {}
        logger.warning(
            "LLM provider returned empty assistant text; payload_shape=%s message=%s choice0=%s",
            _provider_payload_shape(parsed),
            json.dumps((choice0.get("message") or {}), ensure_ascii=False, default=str)[:1200],
            json.dumps(choice0, ensure_ascii=False, default=str)[:1200],
        )
        raise _EmptyProviderResponseError("LLM provider returned an empty answer.")
    return content


def _chat_completions_url(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return f"{trimmed}/chat/completions"


def _parse_json_answer(raw: str) -> dict[str, Any]:
    payload = _maybe_json_object(raw)
    if payload is None:
        if _looks_like_broken_json_answer(raw):
            raise _MalformedProviderResponseError("LLM provider returned malformed JSON output.")
        return {
            "matched": True,
            "answer": raw,
            "basis": "LLM provider returned plain text instead of JSON.",
            "citations": [],
            "suggestions": [],
        }
    if not isinstance(payload, dict):
        return {}
    nested_answer = _maybe_json_object(payload.get("answer"))
    if isinstance(nested_answer, dict) and any(
        key in nested_answer for key in ("answer", "matched", "basis", "citations", "suggestions")
    ):
        merged = dict(payload)
        merged.update({key: value for key, value in nested_answer.items() if value not in (None, "")})
        return merged
    if _looks_like_broken_json_answer(payload.get("answer")):
        raise _MalformedProviderResponseError("LLM provider returned malformed nested JSON output.")
    return payload


def _maybe_json_object(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    decoder = json.JSONDecoder()
    candidates = [text]
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1].strip())
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            payload = _raw_decode_json_object(candidate, decoder=decoder)
            if payload is None:
                continue
        if isinstance(payload, str):
            nested = _maybe_json_object(payload)
            if nested is not None:
                return nested
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _raw_decode_json_object(raw: str, *, decoder: json.JSONDecoder) -> dict[str, Any] | str | None:
    text = str(raw or "")
    for index, char in enumerate(text):
        if char not in '{["':
            continue
        try:
            payload, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, (dict, str)):
            return payload
    return None


def _extract_provider_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if choices:
        first_choice = choices[0] if isinstance(choices[0], dict) else {}
        message = first_choice.get("message") or {}
        structured_content = _extract_structured_provider_text(message.get("content"))
        if structured_content:
            return structured_content
        content = _coerce_provider_content_text(message.get("content"))
        if content:
            return content
        tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
        tool_call_arguments = _extract_tool_call_arguments(tool_calls)
        if tool_call_arguments:
            return tool_call_arguments
        for field in ("text", "output_text", "refusal", "reasoning"):
            value = _coerce_provider_content_text(first_choice.get(field))
            if value:
                return value
            value = _coerce_provider_content_text(message.get(field))
            if value:
                return value
    for field in ("output_text", "text", "content"):
        value = _coerce_provider_content_text(payload.get(field))
        if value:
            return value
    return ""


def _extract_structured_provider_text(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        return text if _maybe_json_object(text) is not None else ""
    if isinstance(value, list):
        for item in value:
            structured = _extract_structured_provider_text(item)
            if structured:
                return structured
        return ""
    if isinstance(value, dict):
        for key in ("text", "content", "output_text", "value"):
            structured = _extract_structured_provider_text(value.get(key))
            if structured:
                return structured
    return ""


def _coerce_provider_content_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            part_text = _coerce_provider_content_text(item)
            if part_text:
                parts.append(part_text)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "output_text", "value", "refusal", "reasoning"):
            part = value.get(key)
            text = _coerce_provider_content_text(part)
            if text:
                return text
    return ""


def _extract_tool_call_arguments(tool_calls: Any) -> str:
    if not isinstance(tool_calls, list):
        return ""
    for item in tool_calls:
        if not isinstance(item, dict):
            continue
        function = item.get("function") or {}
        if not isinstance(function, dict):
            continue
        arguments = function.get("arguments")
        if isinstance(arguments, str) and arguments.strip():
            return arguments.strip()
    return ""


def _provider_payload_shape(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices") or []
    first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first_choice.get("message") or {}
    return {
        "top_level_keys": sorted(str(key) for key in payload.keys()),
        "choice_keys": sorted(str(key) for key in first_choice.keys()),
        "message_keys": sorted(str(key) for key in message.keys()) if isinstance(message, dict) else [],
        "content_type": type(message.get("content")).__name__ if isinstance(message, dict) else None,
    }


def _plain_text_retry_messages(
    *,
    question: str,
    evidence: dict[str, Any],
    public_mode: bool,
) -> list[dict[str, str]]:
    system_prompt = (
        "You are Hermes on the public StrategyOS executive surface. "
        "Answer in plain English using only the supplied public packet. "
        "Do not return JSON. Do not mention hidden or private data."
        if public_mode
        else "Answer using only the supplied evidence. Do not return JSON."
    )
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Question: {question}\n"
                "Give a direct human answer only. If the evidence is insufficient, say so plainly.\n"
                f"Evidence: {json.dumps(evidence, ensure_ascii=False)}"
            ),
        },
    ]


def _clean_visible_answer(value: Any) -> str:
    if isinstance(value, dict):
        nested_answer = value.get("answer")
        if nested_answer is not None:
            return _clean_visible_answer(nested_answer)
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return " ".join(part for part in (_clean_visible_answer(item) for item in value) if part).strip()
    text = str(value or "").strip()
    if not text:
        return ""
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    nested = _maybe_json_object(text)
    if isinstance(nested, dict):
        nested_answer = nested.get("answer")
        if nested_answer is not None and str(nested_answer).strip() and str(nested_answer).strip() != text:
            return _clean_visible_answer(nested_answer)
    extracted = _extract_answer_field_from_jsonish_text(text)
    if extracted:
        return extracted
    return text


def _looks_like_broken_json_answer(raw: Any) -> bool:
    text = str(raw or "").strip()
    if not text:
        return False
    if _maybe_json_object(text) is not None:
        return False
    jsonish_markers = ('"answer"', '"matched"', '"basis"', '"citations"', '"suggestions"')
    if text.startswith("{") or text.startswith("```"):
        return any(marker in text for marker in jsonish_markers) or text.count('"') >= 2
    return '"answer"' in text and ('{' in text or '```' in text)


def _extract_answer_field_from_jsonish_text(text: str) -> str:
    match = re.search(r'"answer"\s*:\s*"((?:\\.|[^"\\])*)"', str(text or ""), flags=re.DOTALL)
    if not match:
        return ""
    try:
        return json.loads(f'"{match.group(1)}"').strip()
    except json.JSONDecodeError:
        return match.group(1).replace('\\n', '\n').replace('\\"', '"').strip()


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


def _normalize_public_packet_citations(
    citations: list[dict[str, Any]],
    *,
    packet: dict[str, Any],
    question: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in citations[:8]:
        locator = str(item.get("locator") or "").strip()
        source_path = str(item.get("source_path") or "public_packet://latest-public").strip() or "public_packet://latest-public"
        if locator and not locator.startswith("public_context_packet"):
            locator = f"public_context_packet.{locator.lstrip('.')}"
        normalized.append(
            {
                **item,
                "source_path": source_path,
                "locator": locator,
                "excerpt": str(item.get("excerpt") or _excerpt_for_public_locator(packet, locator))[:600],
            }
        )
    if normalized:
        return normalized
    return _default_public_packet_citations(packet, question)


def _default_public_packet_citations(packet: dict[str, Any], question: str) -> list[dict[str, Any]]:
    lower = str(question or "").lower()
    locators: list[str] = []

    def add(*items: str) -> None:
        for item in items:
            if item and item not in locators:
                locators.append(item)

    add("public_context_packet.facts[0]", "public_context_packet.kpis[0]")
    if any(token in lower for token in ["last week", "this week", "week", "changed"]):
        add("public_context_packet.week[0]", "public_context_packet.developments[0]", "public_context_packet.trace_summary")
    if any(token in lower for token in ["board", "plain english", "summarize"]):
        add("public_context_packet.board_portal.summary", "public_context_packet.board_portal.kpis[0]", "public_context_packet.week[0]")
    if any(token in lower for token in ["margin", "ebitda", "fx", "hedge", "worry"]):
        add("public_context_packet.drivers[1]", "public_context_packet.findings[0]", "public_context_packet.public_facts")
    if any(token in lower for token in ["tamween", "8.6", "recoverable", "evidence"]):
        add("public_context_packet.findings[1]", "public_context_packet.developments[2]", "public_context_packet.public_facts")
    if "digital health" in lower:
        add("public_context_packet.drivers[2]")
    if any(token in lower for token in ["unit", "business unit", "dragging"]):
        add("public_context_packet.drivers[1]", "public_context_packet.drivers[0]")

    return [
        {
            "source_path": "public_packet://latest-public",
            "locator": locator,
            "excerpt": _excerpt_for_public_locator(packet, locator)[:600],
        }
        for locator in locators[:4]
    ]


def _excerpt_for_public_locator(packet: dict[str, Any], locator: str) -> str:
    value = _value_for_public_locator(packet, locator)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _value_for_public_locator(packet: dict[str, Any], locator: str) -> Any:
    if not locator:
        return None
    path = locator
    if path.startswith("public_context_packet."):
        path = path[len("public_context_packet.") :]
    elif path == "public_context_packet":
        return packet
    current: Any = packet
    for part in [segment for segment in path.split(".") if segment]:
        while True:
            bracket_index = part.find("[")
            if bracket_index == -1:
                if part:
                    if not isinstance(current, dict):
                        return None
                    current = current.get(part)
                break
            key = part[:bracket_index]
            if key:
                if not isinstance(current, dict):
                    return None
                current = current.get(key)
            end_index = part.find("]", bracket_index)
            if end_index == -1:
                return None
            try:
                item_index = int(part[bracket_index + 1 : end_index])
            except ValueError:
                return None
            if not isinstance(current, list) or item_index >= len(current):
                return None
            current = current[item_index]
            part = part[end_index + 1 :]
            if not part:
                break
    return current
