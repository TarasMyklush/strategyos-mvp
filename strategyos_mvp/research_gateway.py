"""Network-isolated Kyvern gateway for closed-template public research."""
from __future__ import annotations

import json
import re
import uuid
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .research import gateway_token_valid, public_query


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    topic_id: str = Field(max_length=64)
    geography_id: str = Field(max_length=64)
    period_id: str = Field(max_length=32)
    language: str = Field(max_length=8)
    source_set_id: str = Field(max_length=64)


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_provider_open = build_opener(_NoRedirects()).open


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/research")
def research(
    payload: ResearchRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    token = str(authorization or "").removeprefix("Bearer ")
    if not gateway_token_valid(token):
        raise HTTPException(401, "Invalid gateway credential.")
    try:
        query = public_query(payload.model_dump())
    except RuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc
    params = urlencode({
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": "3",
        "prop": "extracts|info",
        "exintro": "1",
        "explaintext": "1",
        "exchars": "700",
        "inprop": "url",
        "format": "json",
        "formatversion": "2",
        "origin": "*",
    })
    provider_url = "https://en.wikipedia.org/w/api.php?" + params
    request = Request(
        provider_url,
        headers={"User-Agent": "KyvernPublicResearch/1.0 (security@kyvern.ai)"},
    )
    try:
        with _provider_open(request, timeout=12) as response:
            provider_request_id = str(response.headers.get("x-request-id") or "")
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(502, "Approved public source is unavailable.") from exc
    pages = ((body.get("query") or {}).get("pages") or []) if isinstance(body, dict) else []
    sources = []
    for page in pages[:3]:
        if not isinstance(page, dict):
            continue
        href = str(page.get("fullurl") or "")
        parsed = urlparse(href)
        if parsed.scheme != "https" or parsed.hostname not in {"en.wikipedia.org"}:
            continue
        excerpt = re.sub(r"\s+", " ", str(page.get("extract") or "")).strip()[:700]
        title = re.sub(r"[\x00-\x1f]", "", str(page.get("title") or "")).strip()[:200]
        if title and href:
            sources.append({"title": title, "url": href, "excerpt": excerpt})
    if not sources:
        raise HTTPException(502, "Approved public source returned no usable evidence.")
    return {
        "status": "completed",
        "gateway_request_id": str(uuid.uuid4()),
        "provider_request_id": provider_request_id or None,
        "query": query,
        "source_set_id": payload.source_set_id,
        "sources": sources,
    }
