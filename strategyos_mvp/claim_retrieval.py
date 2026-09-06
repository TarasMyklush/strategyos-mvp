"""Semantic ranking is a hint; the ledger is the only returned authority."""
from dataclasses import replace
from typing import Callable

from .claim_store import ClaimRepository
from .source_claims import ClaimQuery, PolicyContext


def vector_candidates(text: str, *, query: ClaimQuery, limit: int) -> list[str]:
    from . import semantic_embeddings
    from .vector_store import CLAIM_PROJECTION_COLLECTION, _qdrant_request

    if not semantic_embeddings.configured():
        raise RuntimeError("Pinned local semantic model is unavailable.")
    filters = [
        {"key": "tenant_id", "match": {"value": query.tenant_id}},
        {"key": "metric_key", "match": {"value": query.metric_key}},
        {"key": "claim_kind", "match": {"any": sorted(str(k) for k in query.allowed_claim_kinds)}},
    ]
    if query.business_unit:
        filters.append({"key": "business_unit", "match": {"value": query.business_unit}})
    result = _qdrant_request("POST", f"/collections/{CLAIM_PROJECTION_COLLECTION}/points/search", {
        "vector": semantic_embeddings.embed(text, query=True), "limit": limit,
        "filter": {"must": filters}, "with_payload": ["claim_revision_id"],
    })
    # Neither scores nor projection text/source labels are evidence returned to callers.
    return [str(row.get("payload", {}).get("claim_revision_id") or "")
            for row in result.get("result", []) if row.get("payload", {}).get("claim_revision_id")]


def search_claims(text: str, *, query: ClaimQuery, context: PolicyContext,
                  limit: int = 10, repository: ClaimRepository | None = None,
                  candidates: Callable | None = None) -> list[dict]:
    if not text.strip() or len(text) > 4000 or not 1 <= limit <= 50:
        raise ValueError("Search requires 1–4000 characters and a limit of 1–50.")
    repo = repository or ClaimRepository()
    if query.tenant_id != context.tenant_id or query.purpose != context.purpose:
        raise ValueError("Search scope must match the authenticated policy context.")
    resolved = repo.resolve_context(context)
    scoped = replace(query, tenant_id=resolved.tenant_id)
    ids = list(dict.fromkeys((candidates or vector_candidates)(text, query=scoped, limit=200)))[:200]
    records = repo.query(scoped, context=resolved, revision_ids=ids)
    authorized = {row["claim_revision_id"]: row for row in records if row.get("indexing_allowed") is True}
    return [authorized[key] for key in ids if key in authorized][:limit]
