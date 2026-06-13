from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib import error, parse, request

from .config import CONFIG
from .models import Citation, Finding


COLLECTION_NAME = "strategyos_search_chunks"
LEGACY_COLLECTION_NAME = "strategyos_findings"
VECTOR_SIZE = 256
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:\-/.]*")
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120
MAX_INDEX_TEXT = 4_000
MAX_RESULT_TEXT = 700
MAX_SEARCH_LIMIT = 50
MAX_SEARCH_CANDIDATES = 100
INDEXED_FILTER_FIELDS = (
    "run_id",
    "tenant_slug",
    "point_type",
    "finding_id",
    "pattern_type",
    "vendor_id",
    "vendor_name",
    "confidence",
    "source_path",
    "source_hash",
)


@dataclass(frozen=True)
class SearchFilters:
    point_type: tuple[str, ...] = ()
    pattern_type: tuple[str, ...] = ()
    vendor_id: tuple[str, ...] = ()
    vendor_name: tuple[str, ...] = ()
    confidence: tuple[str, ...] = ()
    source_path: tuple[str, ...] = ()
    finding_id: tuple[str, ...] = ()


def check_qdrant_ready() -> dict[str, Any]:
    if not CONFIG.qdrant_url:
        return {"status": "skipped", "reason": "QDRANT_URL is not configured."}
    try:
        payload = _qdrant_request("GET", "/collections")
        collections = payload.get("result", {}).get("collections", [])
        version = _qdrant_version()
        return {
            "status": "ok",
            "url": CONFIG.qdrant_url,
            "collections": len(collections),
            "search_collection": COLLECTION_NAME,
            "legacy_collection": LEGACY_COLLECTION_NAME,
            "qdrant_version": version,
            "native_hybrid_supported": _native_hybrid_supported(version),
            "hybrid_mode": "qdrant_native"
            if _native_hybrid_supported(version)
            else "hybrid_compat",
        }
    except Exception as exc:
        return {"status": "failed", "reason": str(exc)}


def sync_findings_vector_store(
    *,
    run_id: str | None,
    tenant_slug: str,
    findings: list[Finding],
    knowledge_graph_path: Path | None,
) -> dict[str, Any]:
    if not CONFIG.qdrant_url:
        return {"status": "skipped", "reason": "QDRANT_URL is not configured."}
    if not run_id:
        return {"status": "missing", "reason": "Run ID is unavailable."}
    points = _build_points(
        run_id=run_id,
        tenant_slug=tenant_slug,
        findings=findings,
        knowledge_graph_path=knowledge_graph_path,
    )
    if not points:
        return {
            "status": "empty",
            "run_id": run_id,
            "collection": COLLECTION_NAME,
            "point_count": 0,
            "reason": "No findings available to index.",
        }
    _ensure_collection()
    _qdrant_request(
        "PUT",
        f"/collections/{COLLECTION_NAME}/points?wait=true",
        {"points": points},
    )
    status_payload = vector_status_for_run(run_id)
    sample_query = search_run_vectors(run_id, "duplicate payment invoice", limit=1)
    return {
        "status": "synced",
        "run_id": run_id,
        "collection": COLLECTION_NAME,
        "point_count": status_payload.get("point_count", len(points)),
        "point_types": _point_type_counts(points),
        "knowledge_graph_path": str(knowledge_graph_path)
        if knowledge_graph_path
        else None,
        "sample_result": (sample_query.get("results") or [None])[0],
    }


def vector_status_for_run(run_id: str | None) -> dict[str, Any]:
    if not CONFIG.qdrant_url:
        return {"status": "skipped", "reason": "QDRANT_URL is not configured."}
    if not run_id:
        return {"status": "missing", "reason": "Run ID is unavailable."}
    try:
        status_payload = _vector_status_for_collection(
            run_id, COLLECTION_NAME, create=True
        )
        if status_payload.get("status") == "ready":
            return status_payload
        legacy_payload = _vector_status_for_collection(
            run_id, LEGACY_COLLECTION_NAME, create=False
        )
        if legacy_payload.get("status") == "ready":
            legacy_payload["status"] = "ready"
            legacy_payload["mode"] = "legacy"
            legacy_payload["search_collection"] = COLLECTION_NAME
            return legacy_payload
        return status_payload
    except Exception as exc:
        return {"status": "failed", "run_id": run_id, "reason": str(exc)}


def search_run_vectors(
    run_id: str | None,
    query: str,
    *,
    limit: int = 5,
    point_type: str | Iterable[str] | None = None,
    pattern_type: str | Iterable[str] | None = None,
    vendor_id: str | Iterable[str] | None = None,
    vendor_name: str | Iterable[str] | None = None,
    confidence: str | Iterable[str] | None = None,
    source_path: str | Iterable[str] | None = None,
    finding_id: str | Iterable[str] | None = None,
) -> dict[str, Any]:
    if not CONFIG.qdrant_url:
        return {"status": "skipped", "reason": "QDRANT_URL is not configured."}
    if not run_id:
        return {"status": "missing", "reason": "Run ID is unavailable."}
    if not query.strip():
        return {
            "status": "missing",
            "reason": "Query is empty.",
            "run_id": run_id,
            "results": [],
        }
    try:
        limit = max(1, min(MAX_SEARCH_LIMIT, int(limit)))
        filters = SearchFilters(
            point_type=_filter_values(point_type, lowercase=True),
            pattern_type=_filter_values(pattern_type),
            vendor_id=_filter_values(vendor_id),
            vendor_name=_filter_values(vendor_name),
            confidence=_filter_values(confidence, uppercase=True),
            source_path=_filter_values(source_path),
            finding_id=_filter_values(finding_id),
        )
        filter_payload = _search_filter(run_id, filters)
        raw_results = _search_collection(
            COLLECTION_NAME,
            query=query,
            filter_payload=filter_payload,
            limit=limit,
            create=True,
        )
        collection = COLLECTION_NAME
        if not raw_results and not _has_filters(filters):
            legacy_results = _search_collection(
                LEGACY_COLLECTION_NAME,
                query=query,
                filter_payload=_run_filter(run_id),
                limit=limit,
                create=False,
            )
            if legacy_results:
                raw_results = legacy_results
                collection = LEGACY_COLLECTION_NAME
        results = _rank_results(run_id, query, raw_results, limit=limit)
        return {
            "status": "ready",
            "run_id": run_id,
            "collection": collection,
            "query": query,
            "limit": limit,
            "mode": "hybrid_compat",
            "filters": _filters_payload(filters),
            "results": results,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "run_id": run_id,
            "collection": COLLECTION_NAME,
            "query": query,
            "filters": {},
            "reason": str(exc),
            "results": [],
        }


def _build_points(
    *,
    run_id: str,
    tenant_slug: str,
    findings: list[Finding],
    knowledge_graph_path: Path | None,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    citation_records = _citation_records_for_run(run_id, findings)
    for finding in findings:
        text = _finding_text(finding)
        points.append(
            {
                "id": _point_id(run_id, "finding", finding.finding_id),
                "vector": _embed_text(text),
                "payload": {
                    "run_id": run_id,
                    "tenant_slug": tenant_slug,
                    "point_type": "finding",
                    "finding_id": finding.finding_id,
                    "title": finding.title,
                    "pattern_type": finding.pattern_type,
                    "vendor_id": finding.vendor_id,
                    "vendor_name": finding.vendor_name,
                    "confidence": finding.confidence,
                    "recoverable_sar": finding.recoverable_sar,
                    "source": str(knowledge_graph_path)
                    if knowledge_graph_path
                    else None,
                    "source_path": str(knowledge_graph_path)
                    if knowledge_graph_path
                    else None,
                    "locator": None,
                    "excerpt": _first_excerpt(finding.citations),
                    "text": text,
                },
            }
        )
    for record in citation_records:
        citation_text = _citation_text(record)
        if citation_text:
            points.append(
                {
                    "id": _point_id(
                        run_id,
                        "citation",
                        str(record.get("citation_id") or ""),
                        str(record.get("finding_id") or ""),
                        str(record.get("source_hash") or ""),
                        str(record.get("locator") or ""),
                        str(record.get("excerpt") or "")[:120],
                    ),
                    "vector": _embed_text(citation_text),
                    "payload": _citation_payload(
                        record,
                        run_id=run_id,
                        tenant_slug=tenant_slug,
                        point_type="citation",
                        text=citation_text,
                        chunk_index=None,
                    ),
                }
            )
        evidence_text = _evidence_text(record)
        for chunk_index, chunk in enumerate(_chunk_text(evidence_text)):
            points.append(
                {
                    "id": _point_id(
                        run_id,
                        "evidence_chunk",
                        str(record.get("citation_id") or ""),
                        str(record.get("finding_id") or ""),
                        str(record.get("source_hash") or ""),
                        str(record.get("locator") or ""),
                        str(chunk_index),
                    ),
                    "vector": _embed_text(chunk),
                    "payload": _citation_payload(
                        record,
                        run_id=run_id,
                        tenant_slug=tenant_slug,
                        point_type="evidence_chunk",
                        text=chunk,
                        chunk_index=chunk_index,
                    ),
                }
            )
    return points


def _finding_text(finding: Finding) -> str:
    citation_text = " ".join(
        " ".join(part for part in [citation.label(), citation.excerpt] if part)
        for citation in finding.citations
    )
    return " ".join(
        part
        for part in [
            finding.title,
            finding.pattern_type.replace("_", " "),
            finding.vendor_name,
            finding.rationale,
            finding.remediation,
            citation_text,
        ]
        if part
    )


def _citation_records_for_run(
    run_id: str, findings: list[Finding]
) -> list[dict[str, Any]]:
    try:
        from . import state_store

        persisted = state_store.search_citations_for_run(run_id)
    except Exception:
        persisted = []
    if persisted:
        return persisted

    records: list[dict[str, Any]] = []
    for finding in findings:
        for index, citation in enumerate(finding.citations):
            records.append(_citation_record_from_finding(finding, citation, index))
    return records


def _citation_record_from_finding(
    finding: Finding, citation: Citation, index: int
) -> dict[str, Any]:
    return {
        "citation_id": None,
        "citation_index": index,
        "finding_id": finding.finding_id,
        "title": finding.title,
        "pattern_type": finding.pattern_type,
        "vendor_id": finding.vendor_id,
        "vendor_name": finding.vendor_name,
        "confidence": finding.confidence,
        "recoverable_sar": finding.recoverable_sar,
        "evidence_document_id": None,
        "source_path": citation.source_path,
        "source_hash": citation.source_hash,
        "locator": citation.locator,
        "excerpt": citation.excerpt,
        "resolved": None,
        "hash_match": None,
        "resolved_payload": {},
    }


def _citation_payload(
    record: dict[str, Any],
    *,
    run_id: str,
    tenant_slug: str,
    point_type: str,
    text: str,
    chunk_index: int | None,
) -> dict[str, Any]:
    source_path = _text_or_none(record.get("source_path"))
    locator = _text_or_none(record.get("locator"))
    excerpt = _text_or_none(record.get("excerpt"))
    finding_id = _text_or_none(record.get("finding_id"))
    title = _text_or_none(record.get("title")) or (
        f"Evidence for {finding_id}" if finding_id else "Evidence"
    )
    return {
        "run_id": run_id,
        "tenant_slug": tenant_slug,
        "point_type": point_type,
        "finding_id": finding_id,
        "citation_id": _text_or_none(record.get("citation_id")),
        "evidence_document_id": _text_or_none(record.get("evidence_document_id")),
        "title": title,
        "pattern_type": _text_or_none(record.get("pattern_type")),
        "vendor_id": _text_or_none(record.get("vendor_id")),
        "vendor_name": _text_or_none(record.get("vendor_name")),
        "confidence": _text_or_none(record.get("confidence")),
        "recoverable_sar": record.get("recoverable_sar"),
        "source": source_path,
        "source_path": source_path,
        "source_hash": _text_or_none(record.get("source_hash")),
        "locator": locator,
        "excerpt": _truncate(excerpt or text, MAX_RESULT_TEXT),
        "resolved": record.get("resolved"),
        "hash_match": record.get("hash_match"),
        "chunk_index": chunk_index,
        "text": _truncate(text, MAX_INDEX_TEXT),
    }


def _citation_text(record: dict[str, Any]) -> str:
    return _truncate(
        " ".join(
            part
            for part in [
                _text_or_none(record.get("title")),
                _text_or_none(record.get("finding_id")),
                (_text_or_none(record.get("pattern_type")) or "").replace("_", " "),
                _text_or_none(record.get("vendor_name")),
                _text_or_none(record.get("source_path")),
                _text_or_none(record.get("locator")),
                _text_or_none(record.get("excerpt")),
                _resolved_payload_text(record.get("resolved_payload")),
            ]
            if part
        ),
        MAX_INDEX_TEXT,
    )


def _evidence_text(record: dict[str, Any]) -> str:
    return _truncate(
        " ".join(
            part
            for part in [
                _text_or_none(record.get("excerpt")),
                _resolved_payload_text(record.get("resolved_payload")),
            ]
            if part
        ),
        MAX_INDEX_TEXT,
    )


def _resolved_payload_text(value: Any) -> str:
    if not value:
        return ""
    try:
        return json.dumps(value, default=str, sort_keys=True)
    except TypeError:
        return str(value)


def _chunk_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= CHUNK_SIZE:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _embed_text(text: str) -> list[float]:
    vector = [0.0] * VECTOR_SIZE
    tokens = TOKEN_RE.findall(text.lower())
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
        index = int.from_bytes(digest[:8], "big") % VECTOR_SIZE
        sign = 1.0 if digest[8] % 2 == 0 else -1.0
        vector[index] += sign
    magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / magnitude for value in vector]


def _sample_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    return {
        "point_type": payload.get("point_type") or "finding",
        "finding_id": payload.get("finding_id"),
        "title": payload.get("title"),
        "pattern_type": payload.get("pattern_type"),
        "vendor_name": payload.get("vendor_name"),
        "source": payload.get("source") or payload.get("source_path"),
        "source_path": payload.get("source_path"),
        "locator": payload.get("locator"),
    }


def _run_filter(run_id: str) -> dict[str, Any]:
    return {"must": [{"key": "run_id", "match": {"value": run_id}}]}


def _search_filter(run_id: str, filters: SearchFilters) -> dict[str, Any]:
    clauses = list(_run_filter(run_id)["must"])
    for key, values in (
        ("point_type", filters.point_type),
        ("pattern_type", filters.pattern_type),
        ("vendor_id", filters.vendor_id),
        ("vendor_name", filters.vendor_name),
        ("confidence", filters.confidence),
        ("source_path", filters.source_path),
        ("finding_id", filters.finding_id),
    ):
        if not values:
            continue
        clauses.append(_match_clause(key, values))
    return {"must": clauses}


def _match_clause(key: str, values: tuple[str, ...]) -> dict[str, Any]:
    if len(values) == 1:
        return {"key": key, "match": {"value": values[0]}}
    return {"key": key, "match": {"any": list(values)}}


def _ensure_collection(collection_name: str = COLLECTION_NAME) -> None:
    try:
        _qdrant_request("GET", f"/collections/{collection_name}")
    except RuntimeError as exc:
        if "404" not in str(exc):
            raise
        _qdrant_request(
            "PUT",
            f"/collections/{collection_name}",
            {"vectors": {"size": VECTOR_SIZE, "distance": "Cosine"}},
        )
    if collection_name == COLLECTION_NAME:
        _ensure_payload_indexes(collection_name)


def _ensure_payload_indexes(collection_name: str) -> None:
    for field_name in INDEXED_FILTER_FIELDS:
        try:
            _qdrant_request(
                "PUT",
                f"/collections/{collection_name}/index",
                {"field_name": field_name, "field_schema": "keyword"},
            )
        except Exception:
            continue


def _vector_status_for_collection(
    run_id: str, collection_name: str, *, create: bool
) -> dict[str, Any]:
    if create:
        _ensure_collection(collection_name)
    else:
        try:
            _qdrant_request("GET", f"/collections/{collection_name}")
        except RuntimeError as exc:
            if "404" in str(exc):
                return {
                    "status": "empty",
                    "run_id": run_id,
                    "collection": collection_name,
                    "point_count": 0,
                    "reason": f"Collection '{collection_name}' does not exist.",
                }
            raise
    count_payload = _qdrant_request(
        "POST",
        f"/collections/{collection_name}/points/count",
        {"filter": _run_filter(run_id), "exact": True},
    )
    point_count = int(count_payload.get("result", {}).get("count", 0))
    if point_count == 0:
        return {
            "status": "empty",
            "run_id": run_id,
            "collection": collection_name,
            "point_count": 0,
            "reason": "No vector records have been indexed for this run yet.",
        }
    scroll_payload = _qdrant_request(
        "POST",
        f"/collections/{collection_name}/points/scroll",
        {"filter": _run_filter(run_id), "limit": 1, "with_payload": True},
    )
    points = scroll_payload.get("result", {}).get("points", [])
    sample_payload = points[0].get("payload") if points else None
    return {
        "status": "ready",
        "run_id": run_id,
        "collection": collection_name,
        "point_count": point_count,
        "sample_record": _sample_payload(sample_payload),
    }


def _search_collection(
    collection_name: str,
    *,
    query: str,
    filter_payload: dict[str, Any],
    limit: int,
    create: bool,
) -> list[dict[str, Any]]:
    if create:
        _ensure_collection(collection_name)
    else:
        try:
            _qdrant_request("GET", f"/collections/{collection_name}")
        except RuntimeError as exc:
            if "404" in str(exc):
                return []
            raise
    candidate_limit = min(MAX_SEARCH_CANDIDATES, max(limit * 5, 20))
    payload = _qdrant_request(
        "POST",
        f"/collections/{collection_name}/points/search",
        {
            "vector": _embed_text(query),
            "limit": candidate_limit,
            "with_payload": True,
            "filter": filter_payload,
        },
    )
    return list(payload.get("result", []))


def _rank_results(
    run_id: str,
    query: str,
    raw_results: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for vector_rank, item in enumerate(raw_results, start=1):
        payload = item.get("payload") or {}
        vector_score = _float_or_zero(item.get("score"))
        lexical_score = _lexical_score(query, payload)
        normalized_vector = max(0.0, min(1.0, (vector_score + 1.0) / 2.0))
        fused_score = (0.62 * normalized_vector) + (0.38 * lexical_score)
        point_id = str(item.get("id") or payload.get("point_id") or "")
        ranked.append(
            {
                "point_id": point_id,
                "result_type": payload.get("point_type") or "finding",
                "score": round(fused_score, 6),
                "ranking": {
                    "mode": "hybrid_compat",
                    "vector_score": vector_score,
                    "lexical_score": round(lexical_score, 6),
                    "fused_score": round(fused_score, 6),
                    "vector_rank": vector_rank,
                },
                "finding_id": payload.get("finding_id"),
                "citation_id": payload.get("citation_id"),
                "title": payload.get("title"),
                "pattern_type": payload.get("pattern_type"),
                "vendor_id": payload.get("vendor_id"),
                "vendor_name": payload.get("vendor_name"),
                "confidence": payload.get("confidence"),
                "source": payload.get("source") or payload.get("source_path"),
                "source_path": payload.get("source_path"),
                "source_hash": payload.get("source_hash"),
                "locator": payload.get("locator"),
                "excerpt": payload.get("excerpt"),
                "text": _truncate(str(payload.get("text") or ""), MAX_RESULT_TEXT),
                "summary": _result_summary(payload),
                "open_evidence": _open_evidence_payload(run_id, point_id, payload),
            }
        )
    ranked.sort(
        key=lambda item: (
            item["score"],
            item["ranking"]["lexical_score"],
            -(item["ranking"]["vector_rank"]),
        ),
        reverse=True,
    )
    return ranked[:limit]


def _lexical_score(query: str, payload: dict[str, Any]) -> float:
    query_tokens = set(TOKEN_RE.findall(query.lower()))
    if not query_tokens:
        return 0.0
    text = _searchable_payload_text(payload).lower()
    text_tokens = set(TOKEN_RE.findall(text))
    overlap = len(query_tokens & text_tokens) / len(query_tokens)
    phrase_bonus = 0.22 if query.strip().lower() in text else 0.0
    field_bonus = 0.0
    for field_name in ("title", "finding_id", "vendor_name", "source_path", "locator"):
        value = str(payload.get(field_name) or "").lower()
        if value and any(token in value for token in query_tokens):
            field_bonus += 0.05
    return min(1.0, overlap + phrase_bonus + min(field_bonus, 0.2))


def _searchable_payload_text(payload: dict[str, Any]) -> str:
    return " ".join(
        str(payload.get(key) or "")
        for key in (
            "title",
            "finding_id",
            "pattern_type",
            "vendor_name",
            "source_path",
            "locator",
            "excerpt",
            "text",
        )
    )


def _result_summary(payload: dict[str, Any]) -> str:
    return _truncate(
        " - ".join(
            part
            for part in [
                str(payload.get("vendor_name") or ""),
                str(payload.get("source_path") or ""),
                str(payload.get("locator") or ""),
                str(payload.get("excerpt") or payload.get("text") or ""),
            ]
            if part
        ),
        MAX_RESULT_TEXT,
    )


def _open_evidence_payload(
    run_id: str, point_id: str, payload: dict[str, Any]
) -> dict[str, str] | None:
    params: dict[str, str] = {"run_id": run_id}
    if point_id:
        params["point_id"] = point_id
    for key in ("citation_id", "finding_id", "source_hash", "locator"):
        value = _text_or_none(payload.get(key))
        if value:
            params[key] = value
    if len(params) == 1:
        return None
    return {"href": f"/data/evidence-preview?{parse.urlencode(params)}"}


def _filters_payload(filters: SearchFilters) -> dict[str, list[str]]:
    return {
        key: list(values)
        for key, values in {
            "point_type": filters.point_type,
            "pattern_type": filters.pattern_type,
            "vendor_id": filters.vendor_id,
            "vendor_name": filters.vendor_name,
            "confidence": filters.confidence,
            "source_path": filters.source_path,
            "finding_id": filters.finding_id,
        }.items()
        if values
    }


def _has_filters(filters: SearchFilters) -> bool:
    return any(_filters_payload(filters).values())


def _filter_values(
    value: str | Iterable[str] | None,
    *,
    lowercase: bool = False,
    uppercase: bool = False,
) -> tuple[str, ...]:
    if value is None:
        return ()
    raw_items: list[str] = []
    if isinstance(value, str):
        raw_items.extend(value.split(","))
    else:
        for item in value:
            raw_items.extend(str(item).split(","))
    normalized: list[str] = []
    for item in raw_items:
        text = item.strip()
        if not text or text.lower() == "all":
            continue
        if lowercase:
            text = text.lower()
        if uppercase:
            text = text.upper()
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized)


def _point_type_counts(points: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for point in points:
        point_type = str((point.get("payload") or {}).get("point_type") or "finding")
        counts[point_type] = counts.get(point_type, 0) + 1
    return counts


def _point_id(run_id: str, point_type: str, *parts: str) -> str:
    key = ":".join([run_id, point_type, *(part for part in parts if part)])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _first_excerpt(citations: list[Citation]) -> str | None:
    for citation in citations:
        if citation.excerpt:
            return _truncate(citation.excerpt, MAX_RESULT_TEXT)
    return None


def _truncate(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 15)].rstrip()}... truncated"


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _qdrant_version() -> str | None:
    try:
        payload = _qdrant_request("GET", "/")
    except Exception:
        return None
    version = payload.get("version")
    return str(version) if version else None


def _native_hybrid_supported(version: str | None) -> bool:
    if not version:
        return False
    parts = []
    for part in version.split(".")[:2]:
        try:
            parts.append(int(part))
        except ValueError:
            return False
    while len(parts) < 2:
        parts.append(0)
    major, minor = parts
    return major > 1 or (major == 1 and minor >= 10)


def _qdrant_request(
    method: str, path: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not CONFIG.qdrant_url:
        raise RuntimeError("QDRANT_URL is not configured.")
    url = f"{CONFIG.qdrant_url.rstrip('/')}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=10) as response:
            text = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Qdrant request failed ({exc.code}) for {path}: {detail}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Qdrant request failed for {path}: {exc}") from exc
    if not text:
        return {}
    return json.loads(text)
