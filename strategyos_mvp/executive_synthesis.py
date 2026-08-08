"""Refresh-time executive synthesis with durable, evidence-safe caching.

The model provider is optional.  A deterministic correlation pass always
produces distinct WHAT/WHY contracts and substantive development briefings;
when the configured run policy permits the model provider, one bounded batch
call may improve the wording.  Provider output is accepted only when it keeps
the source identifiers and numeric contract intact.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import CONFIG
from . import llm_qa


REFERENCE_RE = re.compile(r"\b(?:EV|SIG|INIT)-[A-Za-z0-9-]+\b", re.IGNORECASE)
FIGURE_RE = re.compile(r"(?:SAR\s*[\d,.]+(?:[KMB])?|[-+]?\d+(?:\.\d+)?\s*%|[-+]?\d+(?:\.\d+)?\s*pts?)", re.IGNORECASE)


def _cache_root() -> Path:
    configured = os.getenv("STRATEGYOS_EXECUTIVE_SYNTHESIS_CACHE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / ".strategyos_mvp_data" / "executive_synthesis"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _fingerprint(payload: dict[str, Any]) -> str:
    relevant = {
        "plan_health": payload.get("plan_health"),
        "initiative_drifts": payload.get("initiative_drifts"),
        "milestone_drifts": payload.get("milestone_drifts"),
        "achievements": payload.get("achievements"),
        "assistant_threads": payload.get("assistant_threads"),
    }
    canonical = json.dumps(_jsonable(relevant), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_cache(key: str) -> dict[str, Any] | None:
    path = _cache_root() / f"{key}.json"
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return cached if isinstance(cached, dict) else None


def _write_cache(key: str, payload: dict[str, Any]) -> None:
    root = _cache_root()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{key}.json"
    handle, temporary = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp", dir=root)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False, sort_keys=True)
        Path(temporary).replace(destination)
    finally:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass


def _references(*values: Any) -> list[str]:
    text = " ".join(json.dumps(value, default=str) if not isinstance(value, str) else value for value in values)
    found = REFERENCE_RE.findall(text)
    return list(dict.fromkeys(item.upper() for item in found))


def _development_inputs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    initiatives = list(payload.get("initiative_drifts") or [])
    milestones = list(payload.get("milestone_drifts") or [])
    developments: list[dict[str, Any]] = []
    for commitment in list((payload.get("plan_health") or {}).get("commitments") or []):
        if not str(commitment.get("status_vs_path") or "").lower().startswith("behind"):
            continue
        kpi_id = str(commitment.get("kpi_id") or commitment.get("name") or "KPI")
        linked = [
            item for item in initiatives
            if str(item.get("kpi_link") or "").strip().lower() == kpi_id.lower()
        ]
        developments.append({"kind": "kpi", "id": kpi_id, "item": commitment, "linked": linked})
    developments.extend(
        {"kind": "initiative", "id": str(item.get("initiative_id") or item.get("title") or f"initiative-{index}"), "item": item, "linked": []}
        for index, item in enumerate(initiatives)
    )
    developments.extend(
        {"kind": "milestone", "id": f"{item.get('initiative_id') or 'INIT'}-{index}", "item": item, "linked": []}
        for index, item in enumerate(milestones)
    )
    return developments


def _deterministic_development(entry: dict[str, Any]) -> dict[str, Any]:
    item = dict(entry.get("item") or {})
    linked = list(entry.get("linked") or [])
    item_id = str(entry.get("id") or "development")
    references = _references(item_id, item, linked)
    actual = item.get("actual")
    checkpoint = item.get("checkpoint")
    unit = str(item.get("unit") or "")
    name = str(item.get("name") or item.get("title") or item.get("milestone") or item_id)
    if actual is not None and checkpoint is not None:
        try:
            gap = float(checkpoint) - float(actual)
            gap_text = f"{abs(gap):g}{unit} {'behind' if gap >= 0 else 'ahead'}"
        except (TypeError, ValueError):
            gap_text = "outside the approved checkpoint"
        what = f"{name} reached {actual}{unit} versus the approved {checkpoint}{unit} checkpoint — {gap_text}."
    else:
        status = str(item.get("status") or item.get("status_vs_path") or "changed")
        what = f"{name} is now {status}."

    if linked:
        driver = linked[0]
        ref = str(driver.get("initiative_id") or (references[0] if references else "the linked initiative"))
        why = f"The variance tracks {driver.get('title') or 'the linked initiative'} ({ref}); {driver.get('note') or 'delivery is behind the operating plan'}."
    else:
        causal = str(item.get("note") or item.get("rationale") or "").strip()
        if causal and causal.lower() not in what.lower():
            why = causal
        elif references:
            why = f"The linked operating record is the current candidate driver; causality still needs confirmation ({references[0]})."
        else:
            why = "Cause is not yet established; the current data contains no distinct evidenced driver."
    if what.strip() == why.strip():
        why = "Cause is not yet established; the current data contains no distinct evidenced driver."
    exposure = item.get("cost_per_week_sar") or (item.get("cost_of_drift") or {}).get("statement")
    briefing_parts = [what, why]
    if exposure:
        briefing_parts.append(f"Exposure: {exposure}.")
    briefing_parts.append("Options: confirm the accountable owner and recovery milestone, or keep the item on watch until the next verified refresh.")
    briefing_parts.append("Related decision: decide whether the variance needs intervention now or remains delegated.")
    return {
        "item_id": item_id,
        "title": name,
        "what": what[:420],
        "why": why[:420],
        "evidence_refs": references,
        "rich_briefing": " ".join(briefing_parts)[:1400],
        "synthesized_by": "deterministic-correlation",
    }


def _deterministic_thread_summary(thread: dict[str, Any]) -> dict[str, Any]:
    turns = list(thread.get("turns") or [])
    participants = " and ".join(str(item) for item in (thread.get("participants") or [])) or "The assistants"
    topic = str(thread.get("topic") or "the current issue")
    first = str((turns[0] if turns else {}).get("text") or "the starting position")
    last = str((turns[-1] if turns else {}).get("text") or "confirm the accountable follow-up")
    text = f"{participants} reviewed {topic.lower()}. They established {first} Next: {last}"
    figures = list(dict.fromkeys(FIGURE_RE.findall(" ".join(str(item.get("text") or "") for item in turns))))[:6]
    return {
        "thread_id": str(thread.get("thread_id") or thread.get("id") or "thread"),
        "executive_summary": text[:520],
        "key_figures": figures,
        "summary_status": str(thread.get("status") or "recorded"),
        "synthesized_by": "deterministic-correlation",
    }


def _provider_batch(developments: list[dict[str, Any]], threads: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not llm_qa.chat_status(CONFIG).get("enabled"):
        return None
    evidence = {"developments": developments, "threads": threads}
    prompt = (
        "Return JSON with development_briefs and thread_summaries. Preserve every item_id/thread_id. "
        "For each development: WHAT states metric from/to or actual versus checkpoint; WHY is a distinct causal chain and names supplied EV-/SIG-/INIT- refs. "
        "If causality is not grounded, say it is not established. Include a concise rich_briefing covering trend, causes, exposure, options and related decision. "
        "For each thread: executive_summary is 2-3 sentences and key_figures contains the supplied material numbers. Never invent evidence.\n"
        + json.dumps(evidence, ensure_ascii=False, default=str)
    )
    try:
        raw = llm_qa._call_openai_compatible_chat(
            config=CONFIG,
            messages=[
                {"role": "system", "content": "You synthesize executive feed items only from supplied JSON. Return valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=3500,
            response_format={"type": "json_object"},
        )
        parsed = llm_qa._maybe_json_object(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _accept_provider_development(candidate: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    what = str(candidate.get("what") or "").strip()
    why = str(candidate.get("why") or "").strip()
    if not what or not why or what == why:
        return fallback
    fallback_numbers = re.findall(r"[-+]?\d+(?:\.\d+)?", fallback["what"])
    if fallback_numbers and not all(number in what for number in fallback_numbers[:2]):
        return fallback
    refs = list(fallback.get("evidence_refs") or [])
    if refs and not any(ref.lower() in why.lower() for ref in refs):
        return fallback
    return {
        **fallback,
        "what": what[:420],
        "why": why[:420],
        "rich_briefing": str(candidate.get("rich_briefing") or fallback["rich_briefing"])[:1400],
        "synthesized_by": "llm-batch-grounded",
    }


def synthesize_strategy_enrichment(payload: dict[str, Any]) -> dict[str, Any]:
    key = _fingerprint(payload)
    cached = _read_cache(key)
    if cached:
        return {**payload, **cached, "synthesis_cache": {"status": "hit", "key": key}}

    development_fallbacks = [_deterministic_development(item) for item in _development_inputs(payload)]
    threads = list((payload.get("assistant_threads") or {}).get("threads") or [])
    thread_fallbacks = [_deterministic_thread_summary(thread) for thread in threads]
    provider = _provider_batch(development_fallbacks, thread_fallbacks)
    provider_developments = {
        str(item.get("item_id")): item
        for item in list((provider or {}).get("development_briefs") or [])
        if isinstance(item, dict)
    }
    briefs = [
        _accept_provider_development(provider_developments.get(item["item_id"], {}), item)
        for item in development_fallbacks
    ]
    provider_threads = {
        str(item.get("thread_id")): item
        for item in list((provider or {}).get("thread_summaries") or [])
        if isinstance(item, dict)
    }
    summaries: list[dict[str, Any]] = []
    for fallback in thread_fallbacks:
        candidate = provider_threads.get(fallback["thread_id"], {})
        summary = str(candidate.get("executive_summary") or "").strip()
        summaries.append({
            **fallback,
            "executive_summary": summary[:520] if summary else fallback["executive_summary"],
            "key_figures": list(candidate.get("key_figures") or fallback["key_figures"])[:6],
            "synthesized_by": "llm-batch-grounded" if summary else fallback["synthesized_by"],
        })
    summary_map = {item["thread_id"]: item for item in summaries}
    enriched_threads = []
    for thread in threads:
        summary = summary_map.get(str(thread.get("thread_id") or thread.get("id") or "thread"), {})
        enriched_threads.append({**thread, **summary})
    synthesized = {
        "development_briefs": briefs,
        "assistant_threads": {**dict(payload.get("assistant_threads") or {}), "threads": enriched_threads},
        "synthesis_generated_at": datetime.now(UTC).isoformat(),
        "synthesis_provider": "llm-batch-grounded" if provider else "deterministic-correlation",
    }
    _write_cache(key, synthesized)
    return {**payload, **synthesized, "synthesis_cache": {"status": "miss", "key": key}}
