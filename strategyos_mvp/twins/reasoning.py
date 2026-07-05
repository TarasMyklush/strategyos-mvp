"""Structured twin reasoning with LiteLLM-compatible chat and safe fallback."""

from __future__ import annotations

import json
import inspect
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.request import Request
from uuid import uuid4

from strategyos_mvp import llm_qa
from strategyos_mvp.config import StrategyOSConfig
from strategyos_mvp.twins.store import TwinRepositories

ALLOWED_PRIORITIES = {"critical", "high", "normal", "low"}
ALLOWED_RESOLUTION_HINTS = {"request_data", "respond", "escalate", "redirect", "approve", "modify_state", "noop"}
ALLOWED_ACTIONS = {"send_data_request", "respond_to_message", "escalate", "redirect", "approve", "modify_state", "noop"}
RISKY_MODEL_ACTIONS = {"escalate", "redirect", "approve", "modify_state"}
REVIEW_STATES = {"auto_approved", "needs_review", "pending_human_review", "fallback"}


def run_structured_reasoning(
    *,
    stage: str,
    role: str,
    cycle_id: str,
    input_context: dict[str, Any],
    deterministic_output: list[dict[str, Any]],
    repositories: TwinRepositories,
    config: StrategyOSConfig,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    trace_id = f"reason-{stage}-{uuid4().hex[:12]}"
    timestamp = datetime.now(UTC).isoformat()
    status = llm_qa.chat_status(config)
    trace = {
        "trace_id": trace_id,
        "timestamp": timestamp,
        "role": role,
        "cycle_id": cycle_id,
        "stage": stage,
        "input_context": input_context,
        "evidence_refs": list(input_context.get("evidence_refs") or []),
        "confidence": 0.0,
        "review_state": "fallback",
        "approval_disposition": None,
        "approval_deadline_at": None,
        "provider": status.get("provider"),
        "model": status.get("model"),
    }
    transport_trace: list[dict[str, Any]] = []
    if not status.get("enabled"):
        trace.update({
            "source": "deterministic_fallback",
            "fallback_reason": status.get("reason") or "LLM reasoning is disabled.",
            "output": deterministic_output,
            "raw_output": None,
            "transport": transport_trace,
        })
        repositories.reasoning.save(trace)
        return deterministic_output, trace

    try:
        call_kwargs = {
            "config": config,
            "stage": stage,
            "input_context": input_context,
        }
        if "transport_trace" in inspect.signature(_call_litellm_reasoning).parameters:
            call_kwargs["transport_trace"] = transport_trace
        raw_output = _call_litellm_reasoning(**call_kwargs)
        normalized = _normalize_stage_output(
            stage=stage,
            raw_output=raw_output,
            deterministic_output=deterministic_output,
            trace_id=trace_id,
        )
    except Exception as exc:
        trace.update({
            "source": "deterministic_fallback",
            "fallback_reason": str(exc),
            "output": deterministic_output,
            "raw_output": None,
            "transport": getattr(exc, "transport_status", transport_trace),
        })
        repositories.reasoning.save(trace)
        return deterministic_output, trace

    output_items = list(normalized.get("items") or [])
    if not output_items:
        trace.update({
            "source": "deterministic_fallback",
            "fallback_reason": "Model returned no structured items.",
            "output": deterministic_output,
            "raw_output": raw_output,
            "transport": transport_trace,
        })
        repositories.reasoning.save(trace)
        return deterministic_output, trace

    trace.update({
        "source": "litellm",
        "fallback_reason": None,
        "output": output_items,
        "raw_output": raw_output,
        "confidence": normalized.get("confidence", 0.0),
        "review_state": normalized.get("review_state", "needs_review"),
        "summary": normalized.get("summary", ""),
        "citations": normalized.get("citations", []),
        "transport": transport_trace,
    })
    repositories.reasoning.save(trace)
    return output_items, trace


def apply_model_guardrails(
    *,
    role: str,
    decisions: list[dict[str, Any]],
    repositories: TwinRepositories,
    require_human_review: bool,
) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    guarded: list[dict[str, Any]] = []
    for decision in decisions:
        if str(decision.get("decision_source") or "deterministic") != "model":
            guarded.append({
                **decision,
                "guardrail": {"status": "not_applicable", "reason": "Deterministic decision."},
            })
            continue

        action = str(decision.get("action") or "noop")
        if action not in RISKY_MODEL_ACTIONS:
            guarded.append({
                **decision,
                "guardrail": {"status": "allowed", "reason": "Non-destructive model action."},
            })
            continue

        deadline = (now + timedelta(hours=24)).isoformat()
        rationale = str(decision.get("reason") or decision.get("preliminary_response") or "Model requested guarded action.")
        record = repositories.governance.save_decision({
            "event_id": f"guard-{uuid4().hex[:12]}",
            "event_type": "reasoning_guardrail",
            "role": role,
            "item_id": decision.get("investigation_id") or decision.get("reasoning_trace_id") or f"guard-{uuid4().hex[:8]}",
            "title": f"Model requested {action}",
            "status": "pending_review" if require_human_review else "fallback_required",
            "rationale": rationale,
            "reviewer_notes": rationale,
            "actor_role": "twin_model",
            "actor_subject": f"model:{role}",
            "timestamp": now.isoformat(),
            "proposed_action": action,
            "target_role": decision.get("target_role"),
        })
        trace_id = str(decision.get("reasoning_trace_id") or "")
        if trace_id:
            repositories.reasoning.update(trace_id, {
                "review_state": "pending_human_review" if require_human_review else "fallback",
                "approval_disposition": "pending" if require_human_review else "fallback_required",
                "approval_deadline_at": deadline if require_human_review else None,
            })
        guarded.append({
            **decision,
            "original_action": action,
            "action": "request_human_review" if require_human_review else "noop",
            "requires_human_review": require_human_review,
            "review_record": record,
            "guardrail": {
                "status": "blocked_pending_review" if require_human_review else "fallback_required",
                "reason": f"Model-driven action '{action}' requires governance review.",
            },
        })
    return guarded


def _call_litellm_reasoning(
    *,
    config: StrategyOSConfig,
    stage: str,
    input_context: dict[str, Any],
    transport_trace: list[dict[str, Any]] | None = None,
) -> str:
    url = _chat_completions_url(str(config.llm_base_url))
    payload = {
        "model": config.llm_model,
        "messages": [
            {"role": "system", "content": _system_prompt(stage)},
            {"role": "user", "content": json.dumps(input_context, ensure_ascii=False)},
        ],
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
    body = llm_qa._post_with_retry(
        request=request,
        timeout_seconds=float(getattr(config, "llm_timeout_seconds", 30) or 30),
        provider_label="LiteLLM",
        max_attempts=int(
            getattr(
                config,
                "llm_retry_attempts",
                getattr(config, "llm_transport_max_attempts", 3),
            )
            or 3
        ),
        backoff_seconds=float(
            (
                getattr(config, "llm_retry_backoff_ms", None)
                if getattr(config, "llm_retry_backoff_ms", None) is not None
                else getattr(config, "llm_transport_backoff_seconds", 0.25) * 1000
            )
            / 1000.0
        ),
        max_backoff_seconds=max(
            1.5,
            float(
                (
                    getattr(config, "llm_retry_backoff_ms", None)
                    if getattr(config, "llm_retry_backoff_ms", None) is not None
                    else getattr(config, "llm_transport_backoff_seconds", 0.25) * 1000
                )
                / 1000.0
            )
            * 4,
        ),
        transport_trace=transport_trace,
    )

    parsed = json.loads(body)
    choices = parsed.get("choices") or []
    if not choices:
        raise RuntimeError("LiteLLM provider returned no choices.")
    content = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("LiteLLM provider returned an empty response.")
    return content


def _chat_completions_url(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return f"{trimmed}/chat/completions"


def _system_prompt(stage: str) -> str:
    if stage == "orient":
        return (
            "You are StrategyOS twin orient reasoning via LiteLLM. "
            "Use only supplied JSON context. Return only valid json with keys: "
            "issues, summary, confidence, review_state, citations. "
            "Each issue must be an object with keys: investigation_id, type, priority, "
            "kpi_node_id, detail, owner, resolution_hint, sender, message_id, evidence_refs. "
            "Allowed priority values: critical, high, normal, low. "
            "Allowed resolution_hint values: request_data, respond, escalate, redirect, approve, modify_state, noop."
        )
    return (
        "You are StrategyOS twin decide reasoning via LiteLLM. "
        "Use only supplied JSON context. Return only valid json with keys: decisions, summary, confidence, review_state, citations. "
        "Each decision must be an object with keys: investigation_id, action, target_role, reason, preliminary_response, value, state_updates, evidence_refs. "
        "Allowed action values: send_data_request, respond_to_message, escalate, redirect, approve, modify_state, noop."
    )


def _normalize_stage_output(
    *,
    stage: str,
    raw_output: str,
    deterministic_output: list[dict[str, Any]],
    trace_id: str,
) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        return {"items": [], "summary": "", "confidence": 0.0, "review_state": "fallback", "citations": []}
    if not isinstance(parsed, dict):
        return {"items": [], "summary": "", "confidence": 0.0, "review_state": "fallback", "citations": []}

    key = "issues" if stage == "orient" else "decisions"
    raw_items = parsed.get(key) or []
    items: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items if isinstance(raw_items, list) else []):
        seed = deterministic_output[index] if index < len(deterministic_output) else {}
        if stage == "orient":
            normalized = _normalize_issue(item, seed, trace_id)
        else:
            normalized = _normalize_decision(item, seed, trace_id)
        if normalized is not None:
            items.append(normalized)
    return {
        "items": items,
        "summary": str(parsed.get("summary") or "").strip(),
        "confidence": _clamp_confidence(parsed.get("confidence")),
        "review_state": _normalize_review_state(parsed.get("review_state")),
        "citations": _normalize_refs(parsed.get("citations")),
    }


def _normalize_issue(item: Any, seed: dict[str, Any], trace_id: str) -> dict[str, Any] | None:
    payload = item if isinstance(item, dict) else {}
    priority = str(payload.get("priority") or seed.get("priority") or "normal").lower()
    if priority not in ALLOWED_PRIORITIES:
        priority = "normal"
    resolution_hint = str(payload.get("resolution_hint") or seed.get("resolution_hint") or "noop").lower()
    if resolution_hint not in ALLOWED_RESOLUTION_HINTS:
        resolution_hint = "noop"
    detail = str(payload.get("detail") or seed.get("detail") or "").strip()
    if not detail:
        return None
    return {
        **seed,
        "investigation_id": payload.get("investigation_id") or seed.get("investigation_id"),
        "type": str(payload.get("type") or seed.get("type") or "kpi_gap"),
        "priority": priority,
        "kpi_node_id": payload.get("kpi_node_id") or seed.get("kpi_node_id"),
        "detail": detail,
        "owner": payload.get("owner") or seed.get("owner"),
        "resolution_hint": resolution_hint,
        "sender": payload.get("sender") or seed.get("sender"),
        "message_id": payload.get("message_id") or seed.get("message_id"),
        "evidence_refs": _normalize_refs(payload.get("evidence_refs") or seed.get("evidence_refs")),
        "reasoning_trace_id": trace_id,
        "reasoning_source": "model",
    }


def _normalize_decision(item: Any, seed: dict[str, Any], trace_id: str) -> dict[str, Any] | None:
    payload = item if isinstance(item, dict) else {}
    action = str(payload.get("action") or seed.get("action") or "noop").lower()
    if action not in ALLOWED_ACTIONS:
        action = "noop"
    return {
        **seed,
        "investigation_id": payload.get("investigation_id") or seed.get("investigation_id"),
        "action": action,
        "target_role": payload.get("target_role") or seed.get("target_role"),
        "reason": str(payload.get("reason") or seed.get("reason") or "").strip(),
        "preliminary_response": str(payload.get("preliminary_response") or seed.get("preliminary_response") or "").strip(),
        "value": _safe_float(payload.get("value") if "value" in payload else seed.get("value")),
        "state_updates": payload.get("state_updates") if isinstance(payload.get("state_updates"), dict) else {},
        "evidence_refs": _normalize_refs(payload.get("evidence_refs") or seed.get("evidence_refs")),
        "reasoning_trace_id": trace_id,
        "decision_source": "model",
    }


def _normalize_refs(value: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            refs.append({str(key): item[key] for key in item.keys()})
        elif item is not None:
            refs.append({"reference": str(item)})
    return refs


def _normalize_review_state(value: Any) -> str:
    state = str(value or "needs_review").strip().lower()
    return state if state in REVIEW_STATES else "needs_review"


def _clamp_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
