from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Header, HTTPException, Request, status

from .config import CONFIG


app = FastAPI(title="StrategyOS Local Identity Provider")


def _now() -> datetime:
    return datetime.now(UTC)


def _token_store() -> dict[str, dict[str, Any]]:
    store = getattr(app.state, "tokens", None)
    if store is None:
        store = {}
        app.state.tokens = store
    return store


def _configured_users() -> dict[str, dict[str, str]]:
    users: dict[str, dict[str, str]] = {}
    if CONFIG.idp_operator_username and CONFIG.idp_operator_password:
        users[CONFIG.idp_operator_username] = {
            "password": CONFIG.idp_operator_password,
            "role": "operator",
        }
    if CONFIG.idp_reviewer_username and CONFIG.idp_reviewer_password:
        users[CONFIG.idp_reviewer_username] = {
            "password": CONFIG.idp_reviewer_password,
            "role": "reviewer",
        }
    return users


def _require_client(client_id: str | None, client_secret: str | None) -> None:
    if client_id != CONFIG.idp_client_id or client_secret != CONFIG.idp_client_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid identity client is required.",
        )


def _first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _prune_expired_tokens() -> None:
    now = _now()
    expired = [
        token
        for token, payload in _token_store().items()
        if datetime.fromisoformat(str(payload["expires_at"])) <= now
    ]
    for token in expired:
        _token_store().pop(token, None)


def _token_response(token: str, payload: dict[str, Any]) -> dict[str, Any]:
    expires_at = datetime.fromisoformat(str(payload["expires_at"]))
    expires_in = max(int((expires_at - _now()).total_seconds()), 0)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "scope": "openid profile roles",
        "role": payload["role"],
        "subject": payload["sub"],
        "issuer": CONFIG.idp_issuer,
    }


@app.get("/.well-known/openid-configuration")
def openid_configuration() -> dict[str, Any]:
    issuer = (CONFIG.idp_issuer or "http://localhost:8089").rstrip("/")
    return {
        "issuer": issuer,
        "token_endpoint": f"{issuer}/oauth/token",
        "introspection_endpoint": f"{issuer}/oauth/introspect",
        "userinfo_endpoint": f"{issuer}/oauth/userinfo",
        "grant_types_supported": ["password"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_post",
            "client_secret_basic",
        ],
    }


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/oauth/token")
async def issue_token(request: Request) -> dict[str, Any]:
    _prune_expired_tokens()
    params = parse_qs((await request.body()).decode("utf-8"))
    _require_client(_first(params, "client_id"), _first(params, "client_secret"))
    if _first(params, "grant_type") != "password":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only password grant is supported for the local identity provider.",
        )
    username = _first(params, "username")
    password = _first(params, "password")
    user = _configured_users().get(username or "")
    if user is None or password != user["password"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid local identity credentials.",
        )
    token = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(seconds=CONFIG.idp_token_ttl_seconds)
    payload = {
        "active": True,
        "sub": username,
        "preferred_username": username,
        "role": user["role"],
        "roles": [user["role"]],
        "scope": "openid profile roles",
        "iss": CONFIG.idp_issuer,
        "expires_at": expires_at.isoformat(),
    }
    _token_store()[token] = payload
    return _token_response(token, payload)


def _extract_basic_client(authorization: str | None) -> tuple[str | None, str | None]:
    if not authorization:
        return None, None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "basic" or not token:
        return None, None
    try:
        import base64

        decoded = base64.b64decode(token).decode("utf-8")
    except Exception:
        return None, None
    client_id, _, client_secret = decoded.partition(":")
    return client_id or None, client_secret or None


@app.post("/oauth/introspect")
async def introspect_token(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    _prune_expired_tokens()
    params = parse_qs((await request.body()).decode("utf-8"))
    form_client_id = _first(params, "client_id")
    form_client_secret = _first(params, "client_secret")
    basic_client_id, basic_client_secret = _extract_basic_client(authorization)
    _require_client(
        form_client_id or basic_client_id,
        form_client_secret or basic_client_secret,
    )
    token = _first(params, "token")
    payload = _token_store().get(token or "")
    if payload is None:
        return {"active": False}
    return {key: value for key, value in payload.items() if key != "expires_at"}


@app.get("/oauth/userinfo")
def userinfo(authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, Any]:
    _prune_expired_tokens()
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A bearer token is required.",
        )
    payload = _token_store().get(token.strip())
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identity token is invalid or expired.",
        )
    return {
        "sub": payload["sub"],
        "preferred_username": payload["preferred_username"],
        "role": payload["role"],
        "roles": payload["roles"],
        "iss": payload["iss"],
    }
