from __future__ import annotations

import html
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse

from .config import CONFIG


app = FastAPI(title="StrategyOS Local Identity Provider")

LOGIN_RATE_LIMIT_ATTEMPTS = 10
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 60
LOGIN_CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; form-action 'self'"
ROLE_LABELS = {
    "operator": "Operator — launch and manage runs",
    "reviewer": "Reviewer — claim, approve, or reject reviews",
    "bu": "BU Leader — inspect business-unit cases",
    "analyst": "Analyst — inspect findings and evidence",
    "auditor": "Auditor — inspect audit evidence",
    "executive": "Executive — view the executive surface",
    "tenant_operator": "Tenant Operator — manage tenant operations",
    "tenant_admin": "Tenant Admin — manage tenant setup",
    "system": "System — full system verification",
}
ROLE_REDIRECTS = {"executive": "/executive"}
SESSION_COOKIE_NAME = "strategyos_session"


def _now() -> datetime:
    return datetime.now(UTC)


def _token_store() -> dict[str, dict[str, Any]]:
    store = getattr(app.state, "tokens", None)
    if store is None:
        store = {}
        app.state.tokens = store
    return store


def _login_attempt_store() -> dict[str, list[float]]:
    store = getattr(app.state, "login_attempts", None)
    if store is None:
        store = {}
        app.state.login_attempts = store
    return store


def _role_from_test_username(username: str) -> str | None:
    prefix = username.split("@", 1)[0].split(".", 1)[0].strip().lower()
    role = prefix.replace("-", "_")
    if role in ROLE_LABELS:
        return role
    return None


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
    for username, password in CONFIG.idp_test_users.items():
        role = _role_from_test_username(username)
        if role is None:
            continue
        users[username] = {"password": password, "role": role}
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


def _issue_password_token(username: str | None, password: str | None) -> dict[str, Any]:
    user = _configured_users().get(username or "")
    if user is None or not password or not secrets.compare_digest(password, user["password"]):
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


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _enforce_login_rate_limit(request: Request) -> None:
    key = _client_key(request)
    now = time.monotonic()
    window_start = now - LOGIN_RATE_LIMIT_WINDOW_SECONDS
    attempts = [item for item in _login_attempt_store().get(key, []) if item >= window_start]
    if len(attempts) >= LOGIN_RATE_LIMIT_ATTEMPTS:
        _login_attempt_store()[key] = attempts
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please wait a minute and try again.",
        )
    attempts.append(now)
    _login_attempt_store()[key] = attempts


def _role_options_html() -> str:
    users = _configured_users()
    if CONFIG.idp_test_users:
        users = {
            username: payload
            for username, payload in users.items()
            if username in CONFIG.idp_test_users
        }
    rows: list[str] = []
    for username, payload in sorted(users.items(), key=lambda item: item[1]["role"]):
        role = payload["role"]
        label = ROLE_LABELS.get(role, role.replace("_", " ").title())
        rows.append(
            f'<option value="{html.escape(username)}" data-role="{html.escape(role)}">'
            f'{html.escape(label)} · {html.escape(username)}</option>'
        )
    return "\n".join(rows)


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


@app.get("/login", response_class=HTMLResponse)
def login_page() -> HTMLResponse:
    options = _role_options_html()
    html_body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>StrategyOS test login</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: radial-gradient(circle at top, #243b64, #05070d 60%); color: #f6f8ff; }}
    main {{ width: min(92vw, 520px); background: rgba(10, 16, 28, 0.88); border: 1px solid rgba(255,255,255,.14); border-radius: 28px; padding: 32px; box-shadow: 0 24px 80px rgba(0,0,0,.45); }}
    .eyebrow {{ color: #f7c873; font-size: 13px; font-weight: 800; letter-spacing: .09em; text-transform: uppercase; }}
    h1 {{ margin: 12px 0 10px; font-size: clamp(30px, 5vw, 42px); line-height: 1.02; }}
    p {{ color: #b8c2d9; line-height: 1.6; }}
    form {{ display: grid; gap: 16px; margin-top: 22px; }}
    label {{ display: grid; gap: 8px; color: #dce5ff; font-weight: 700; }}
    input, select, button {{ width: 100%; font: inherit; border-radius: 14px; border: 1px solid rgba(255,255,255,.16); padding: 13px 14px; }}
    input, select {{ background: rgba(255,255,255,.08); color: #ffffff; }}
    option {{ color: #0b1220; }}
    button {{ cursor: pointer; border: 0; background: linear-gradient(135deg, #7dd3fc, #a78bfa); color: #07111f; font-weight: 900; }}
    button:disabled {{ opacity: .65; cursor: wait; }}
    .error {{ min-height: 22px; color: #fca5a5; font-weight: 700; }}
    .hint {{ font-size: 13px; color: #95a3bf; }}
    .links {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
    .links a {{ color: #93c5fd; text-decoration: none; }}
  </style>
</head>
<body>
  <main>
    <div class="eyebrow">Temporary test login</div>
    <h1>Sign in to StrategyOS</h1>
    <p>For authorized testers only. This lightweight login is for role testing and will be replaced by production SSO.</p>
    <form id="login-form">
      <label>Role and username
        <select id="username" autocomplete="username" required>{options}</select>
      </label>
      <label>Password
        <input id="password" type="password" autocomplete="current-password" required autofocus />
      </label>
      <button id="submit" type="submit">Sign in</button>
      <div id="error" class="error" role="alert" aria-live="polite"></div>
      <div class="hint">Your authenticated session is kept in a secure browser cookie. Clear site data to switch roles.</div>
    </form>
  </main>
  <script>
    const form = document.getElementById('login-form');
    const username = document.getElementById('username');
    const password = document.getElementById('password');
    const submit = document.getElementById('submit');
    const error = document.getElementById('error');
    form.addEventListener('submit', async (event) => {{
      event.preventDefault();
      error.textContent = '';
      submit.disabled = true;
      try {{
        const response = await fetch('/auth/login', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ username: username.value, password: password.value }})
        }});
        const payload = await response.json().catch(() => ({{}}));
        if (!response.ok) throw new Error(payload.detail || 'Invalid credentials for this role.');
        localStorage.removeItem('strategyos.ui.token');
        window.location.assign(payload.redirect || '/app');
      }} catch (err) {{
        error.textContent = err.message || 'Invalid credentials for this role.';
      }} finally {{
        submit.disabled = false;
      }}
    }});
  </script>
</body>
</html>"""
    return HTMLResponse(
        html_body,
        headers={
            "Content-Security-Policy": LOGIN_CSP,
            "X-Robots-Tag": "noindex, nofollow",
            "Cache-Control": "no-store",
        },
    )


@app.post("/auth/login")
async def login(request: Request) -> JSONResponse:
    _prune_expired_tokens()
    _enforce_login_rate_limit(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password are required.",
        )
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    try:
        payload = _issue_password_token(username, password)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials for this role.",
            ) from exc
        raise
    role = str(payload.get("role") or "")
    payload["redirect"] = ROLE_REDIRECTS.get(role, "/app")
    response = JSONResponse(
        payload,
        headers={
            "Content-Security-Policy": LOGIN_CSP,
            "X-Robots-Tag": "noindex, nofollow",
            "Cache-Control": "no-store",
        },
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=str(payload["access_token"]),
        max_age=CONFIG.idp_token_ttl_seconds,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return response


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
    return _issue_password_token(_first(params, "username"), _first(params, "password"))


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
