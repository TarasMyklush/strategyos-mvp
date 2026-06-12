from __future__ import annotations

import json
from urllib import error, parse, request
from typing import Any

try:
    from fastapi import Depends, Header, HTTPException, status
except Exception as exc:  # pragma: no cover - optional cloud dependency
    raise RuntimeError(
        "FastAPI is required to run the StrategyOS auth boundary."
    ) from exc

from .config import CONFIG


def extract_api_key(
    x_api_key: str | None = None, authorization: str | None = None
) -> str | None:
    if x_api_key:
        value = x_api_key.strip()
        return value or None
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    value = token.strip()
    return value or None


def extract_bearer_token(authorization: str | None = None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    value = token.strip()
    return value or None


def role_for_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if api_key in CONFIG.operator_api_keys:
        return "operator"
    if api_key in CONFIG.reviewer_api_keys:
        return "reviewer"
    return None


def _introspect_identity_token(token: str) -> dict[str, Any] | None:
    if (
        not CONFIG.idp_introspection_url
        or not CONFIG.idp_client_id
        or not CONFIG.idp_client_secret
    ):
        return None
    payload = parse.urlencode(
        {
            "token": token,
            "client_id": CONFIG.idp_client_id,
            "client_secret": CONFIG.idp_client_secret,
        }
    ).encode("utf-8")
    http_request = request.Request(
        CONFIG.idp_introspection_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    if not result.get("active"):
        return None
    role = result.get("role")
    subject = result.get("sub") or result.get("preferred_username")
    if not role or not subject:
        return None
    issuer = str(result.get("iss") or CONFIG.idp_issuer or "local-idp")
    return {"role": str(role), "subject": f"{issuer}:{subject}"}


def authenticate_request(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    if not CONFIG.api_auth_enabled:
        return {"role": "anonymous", "subject": "auth-disabled", "auth_disabled": True}
    if CONFIG.idp_enabled:
        token = extract_bearer_token(authorization=authorization)
        principal = _introspect_identity_token(token) if token else None
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="A valid identity token is required.",
            )
        return principal
    api_key = extract_api_key(x_api_key=x_api_key, authorization=authorization)
    role = role_for_api_key(api_key)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid API key is required.",
        )
    suffix = api_key[-4:] if api_key and len(api_key) >= 4 else api_key or "unknown"
    return {"role": role, "subject": f"api-key:{role}:{suffix}"}


def authenticate_optional_request(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    if not CONFIG.api_auth_enabled:
        return {
            "role": "anonymous",
            "subject": "auth-disabled",
            "authenticated": False,
            "auth_disabled": True,
        }
    if not x_api_key and not authorization:
        return {
            "role": "anonymous",
            "subject": "anonymous",
            "authenticated": False,
            "auth_disabled": False,
        }
    principal = authenticate_request(x_api_key=x_api_key, authorization=authorization)
    return {
        **principal,
        "authenticated": True,
        "auth_disabled": False,
    }


def require_role(*allowed_roles: str):
    def dependency(
        principal: dict[str, Any] = Depends(authenticate_request),
    ) -> dict[str, Any]:
        if principal.get("auth_disabled"):
            role = allowed_roles[0] if allowed_roles else "anonymous"
            return {**principal, "role": role}
        role = str(principal.get("role"))
        if allowed_roles and role not in allowed_roles:
            raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This identity is not permitted for this endpoint.",
        )
        return principal

    return Depends(dependency)


def require_live_health_access(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    if CONFIG.public_health_enabled:
        return {"role": "public", "subject": "public-health"}
    principal = authenticate_request(x_api_key=x_api_key, authorization=authorization)
    if principal.get("role") != "operator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator access is required for private live health.",
        )
    return principal
