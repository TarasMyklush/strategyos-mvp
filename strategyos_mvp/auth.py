from __future__ import annotations

import hmac
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
from .platform_foundation import principal_has_any_role

DEMO_ROLE_TOKENS = {
    "bu",
    "operator",
    "reviewer",
    "analyst",
    "auditor",
    "executive",
    "tenant_operator",
    "tenant_admin",
    "system",
}
PROXY_EMAIL_HEADERS = (
    "X-Auth-Request-Email",
    "X-Forwarded-Email",
    "X-Auth-Request-Preferred-Username",
)
PROXY_USER_HEADERS = (
    "X-Auth-Request-User",
    "X-Forwarded-User",
)
TRUSTED_PROXY_HEADER_NAME = "X-StrategyOS-Proxy-Auth"


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
    demo_role = demo_role_for_token(api_key)
    if demo_role is not None:
        return demo_role
    if api_key in CONFIG.bu_api_keys:
        return "bu"
    if api_key in CONFIG.tenant_operator_api_keys:
        return "tenant_operator"
    if api_key in CONFIG.tenant_admin_api_keys:
        return "tenant_admin"
    if api_key in CONFIG.system_api_keys:
        return "system"
    if api_key in CONFIG.operator_api_keys:
        return "operator"
    if api_key in CONFIG.reviewer_api_keys:
        return "reviewer"
    return None


def demo_role_for_token(token: str | None) -> str | None:
    if not getattr(CONFIG, "demo_role_login_enabled", False):
        return None
    if token in DEMO_ROLE_TOKENS:
        return token
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
    tenant_id = result.get("tenant_id") or result.get("tenant") or CONFIG.tenant_slug
    return {
        "role": str(role),
        "subject": f"{issuer}:{subject}",
        "tenant_id": str(tenant_id),
    }


def _normalize_email(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def _role_for_proxy_email(email: str | None) -> str | None:
    normalized = _normalize_email(email)
    if normalized is None:
        return None
    if normalized in {_normalize_email(item) for item in CONFIG.bu_emails}:
        return "bu"
    if normalized in {_normalize_email(item) for item in CONFIG.tenant_operator_emails}:
        return "tenant_operator"
    if normalized in {_normalize_email(item) for item in CONFIG.tenant_admin_emails}:
        return "tenant_admin"
    if normalized in {_normalize_email(item) for item in CONFIG.system_emails}:
        return "system"
    if normalized in {_normalize_email(item) for item in CONFIG.operator_emails}:
        return "operator"
    if normalized in {_normalize_email(item) for item in CONFIG.reviewer_emails}:
        return "reviewer"
    return None


def _extract_proxy_header(request_headers: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = request_headers.get(name)
        if value:
            normalized = value.strip()
            if normalized:
                return normalized
    return None


def _proxy_principal_from_headers(request_headers: dict[str, str]) -> dict[str, Any] | None:
    if CONFIG.auth_mode != "proxy_oidc" or not CONFIG.trust_proxy_auth:
        return None
    expected_secret = CONFIG.trusted_proxy_auth_secret
    if not expected_secret:
        return None
    received_secret = _extract_proxy_header(request_headers, TRUSTED_PROXY_HEADER_NAME)
    if not received_secret or not hmac.compare_digest(received_secret, expected_secret):
        return None
    email = _extract_proxy_header(request_headers, *PROXY_EMAIL_HEADERS)
    role = _role_for_proxy_email(email)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This identity is not permitted for this endpoint.",
        )
    subject = _extract_proxy_header(request_headers, *PROXY_USER_HEADERS) or str(email)
    return {
        "role": role,
        "subject": f"oidc:{subject}",
        "tenant_id": CONFIG.tenant_slug,
        "email": email,
        "auth_mode": "proxy_oidc",
    }


def authenticate_request(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_auth_request_email: str | None = Header(default=None, alias="X-Auth-Request-Email"),
    x_auth_request_user: str | None = Header(default=None, alias="X-Auth-Request-User"),
    x_auth_request_preferred_username: str | None = Header(default=None, alias="X-Auth-Request-Preferred-Username"),
    x_forwarded_email: str | None = Header(default=None, alias="X-Forwarded-Email"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_strategyos_proxy_auth: str | None = Header(default=None, alias=TRUSTED_PROXY_HEADER_NAME),
) -> dict[str, Any]:
    if not CONFIG.api_auth_enabled:
        return {
            "role": "anonymous",
            "subject": "auth-disabled",
            "tenant_id": CONFIG.tenant_slug,
            "auth_disabled": True,
        }
    request_headers = {
        "X-Auth-Request-Email": x_auth_request_email or "",
        "X-Auth-Request-User": x_auth_request_user or "",
        "X-Auth-Request-Preferred-Username": x_auth_request_preferred_username or "",
        "X-Forwarded-Email": x_forwarded_email or "",
        "X-Forwarded-User": x_forwarded_user or "",
        TRUSTED_PROXY_HEADER_NAME: x_strategyos_proxy_auth or "",
    }
    proxy_principal = _proxy_principal_from_headers(request_headers)
    if proxy_principal is not None:
        return proxy_principal
    if CONFIG.auth_mode == "proxy_oidc":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A trusted proxy identity is required.",
        )
    if CONFIG.idp_enabled or CONFIG.auth_mode == "identity_provider":
        token = extract_bearer_token(authorization=authorization)
        if getattr(CONFIG, "demo_role_login_enabled", False):
            demo_role = demo_role_for_token(
                extract_api_key(x_api_key=x_api_key, authorization=authorization)
            )
            if demo_role is not None:
                return {
                    "role": demo_role,
                    "subject": f"demo-role:{demo_role}",
                    "tenant_id": CONFIG.tenant_slug,
                    "demo_role_login": True,
                }
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
    if getattr(CONFIG, "demo_role_login_enabled", False) and api_key == role:
        return {
            "role": role,
            "subject": f"demo-role:{role}",
            "tenant_id": CONFIG.tenant_slug,
            "demo_role_login": True,
        }
    suffix = api_key[-4:] if api_key and len(api_key) >= 4 else api_key or "unknown"
    return {
        "role": role,
        "subject": f"api-key:{role}:{suffix}",
        "tenant_id": CONFIG.tenant_slug,
    }


def authenticate_optional_request(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_auth_request_email: str | None = Header(default=None, alias="X-Auth-Request-Email"),
    x_auth_request_user: str | None = Header(default=None, alias="X-Auth-Request-User"),
    x_auth_request_preferred_username: str | None = Header(default=None, alias="X-Auth-Request-Preferred-Username"),
    x_forwarded_email: str | None = Header(default=None, alias="X-Forwarded-Email"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_strategyos_proxy_auth: str | None = Header(default=None, alias=TRUSTED_PROXY_HEADER_NAME),
) -> dict[str, Any]:
    if not CONFIG.api_auth_enabled:
        return {
            "role": "anonymous",
            "subject": "auth-disabled",
            "tenant_id": CONFIG.tenant_slug,
            "authenticated": False,
            "auth_disabled": True,
        }
    has_proxy_identity = any(
        value
        for value in (
            x_auth_request_email,
            x_auth_request_user,
            x_auth_request_preferred_username,
            x_forwarded_email,
            x_forwarded_user,
            x_strategyos_proxy_auth,
        )
    )
    if not x_api_key and not authorization and not has_proxy_identity:
        return {
            "role": "anonymous",
            "subject": "anonymous",
            "tenant_id": CONFIG.tenant_slug,
            "authenticated": False,
            "auth_disabled": False,
        }
    principal = authenticate_request(
        x_api_key=x_api_key,
        authorization=authorization,
        x_auth_request_email=x_auth_request_email,
        x_auth_request_user=x_auth_request_user,
        x_auth_request_preferred_username=x_auth_request_preferred_username,
        x_forwarded_email=x_forwarded_email,
        x_forwarded_user=x_forwarded_user,
        x_strategyos_proxy_auth=x_strategyos_proxy_auth,
    )
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
        if allowed_roles and not principal_has_any_role(role, *allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This identity is not permitted for this endpoint.",
            )
        return principal

    return Depends(dependency)


def require_live_health_access(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_auth_request_email: str | None = Header(default=None, alias="X-Auth-Request-Email"),
    x_auth_request_user: str | None = Header(default=None, alias="X-Auth-Request-User"),
    x_auth_request_preferred_username: str | None = Header(default=None, alias="X-Auth-Request-Preferred-Username"),
    x_forwarded_email: str | None = Header(default=None, alias="X-Forwarded-Email"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_strategyos_proxy_auth: str | None = Header(default=None, alias=TRUSTED_PROXY_HEADER_NAME),
) -> dict[str, Any]:
    if CONFIG.public_health_enabled:
        return {"role": "public", "subject": "public-health"}
    principal = authenticate_request(
        x_api_key=x_api_key,
        authorization=authorization,
        x_auth_request_email=x_auth_request_email,
        x_auth_request_user=x_auth_request_user,
        x_auth_request_preferred_username=x_auth_request_preferred_username,
        x_forwarded_email=x_forwarded_email,
        x_forwarded_user=x_forwarded_user,
        x_strategyos_proxy_auth=x_strategyos_proxy_auth,
    )
    if not principal_has_any_role(
        str(principal.get("role") or ""), "operator", "tenant_admin", "system"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator, tenant admin, or system access is required for private live health.",
        )
    return principal
