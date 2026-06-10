from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from .config import CONFIG
from .models import Finding


COLLECTION_NAME = "strategyos_findings"
VECTOR_SIZE = 256
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:\-/.]*")


def check_qdrant_ready() -> dict[str, Any]:
    if not CONFIG.qdrant_url:
        return {"status": "skipped", "reason": "QDRANT_URL is not configured."}
    try:
        payload = _qdrant_request("GET", "/collections")
        collections = payload.get("result", {}).get("collections", [])
        return {
            "status": "ok",
            "url": CONFIG.qdrant_url,
            "collections": len(collections),
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
            "status": "missing",
            "run_id": run_id,
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
        _ensure_collection()
        count_payload = _qdrant_request(
            "POST",
            f"/collections/{COLLECTION_NAME}/points/count",
            {"filter": _run_filter(run_id), "exact": True},
        )
        point_count = int(count_payload.get("result", {}).get("count", 0))
        if point_count == 0:
            return {
                "status": "missing",
                "run_id": run_id,
                "collection": COLLECTION_NAME,
                "point_count": 0,
            }
        scroll_payload = _qdrant_request(
            "POST",
            f"/collections/{COLLECTION_NAME}/points/scroll",
            {"filter": _run_filter(run_id), "limit": 1, "with_payload": True},
        )
        points = scroll_payload.get("result", {}).get("points", [])
        sample_payload = points[0].get("payload") if points else None
        return {
            "status": "ready",
            "run_id": run_id,
            "collection": COLLECTION_NAME,
            "point_count": point_count,
            "sample_record": _sample_payload(sample_payload),
        }
    except Exception as exc:
        return {"status": "failed", "run_id": run_id, "reason": str(exc)}


def search_run_vectors(
    run_id: str | None, query: str, *, limit: int = 5
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
        _ensure_collection()
        payload = _qdrant_request(
            "POST",
            f"/collections/{COLLECTION_NAME}/points/search",
            {
                "vector": _embed_text(query),
                "limit": max(1, limit),
                "with_payload": True,
                "filter": _run_filter(run_id),
            },
        )
        results = []
        for item in payload.get("result", []):
            point_payload = item.get("payload") or {}
            results.append(
                {
                    "score": item.get("score"),
                    "finding_id": point_payload.get("finding_id"),
                    "title": point_payload.get("title"),
                    "pattern_type": point_payload.get("pattern_type"),
                    "vendor_name": point_payload.get("vendor_name"),
                    "source": point_payload.get("source"),
                }
            )
        return {
            "status": "ready",
            "run_id": run_id,
            "collection": COLLECTION_NAME,
            "query": query,
            "results": results,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "run_id": run_id,
            "collection": COLLECTION_NAME,
            "query": query,
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
    for finding in findings:
        text = _finding_text(finding)
        points.append(
            {
                "id": str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}:{finding.finding_id}")
                ),
                "vector": _embed_text(text),
                "payload": {
                    "run_id": run_id,
                    "tenant_slug": tenant_slug,
                    "finding_id": finding.finding_id,
                    "title": finding.title,
                    "pattern_type": finding.pattern_type,
                    "vendor_id": finding.vendor_id,
                    "vendor_name": finding.vendor_name,
                    "source": str(knowledge_graph_path)
                    if knowledge_graph_path
                    else None,
                    "text": text,
                },
            }
        )
    return points


def _finding_text(finding: Finding) -> str:
    citation_text = " ".join(citation.label() for citation in finding.citations)
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
        "finding_id": payload.get("finding_id"),
        "title": payload.get("title"),
        "pattern_type": payload.get("pattern_type"),
        "vendor_name": payload.get("vendor_name"),
        "source": payload.get("source"),
    }


def _run_filter(run_id: str) -> dict[str, Any]:
    return {"must": [{"key": "run_id", "match": {"value": run_id}}]}


def _ensure_collection() -> None:
    try:
        _qdrant_request("GET", f"/collections/{COLLECTION_NAME}")
    except RuntimeError as exc:
        if "404" not in str(exc):
            raise
        _qdrant_request(
            "PUT",
            f"/collections/{COLLECTION_NAME}",
            {"vectors": {"size": VECTOR_SIZE, "distance": "Cosine"}},
        )


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
