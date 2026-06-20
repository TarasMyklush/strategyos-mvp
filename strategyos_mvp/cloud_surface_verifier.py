from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error, request


LOCAL_HOST_MARKERS = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "strategyos-idp:9000",
)


@dataclass
class HttpResult:
    status: int
    payload: Any


def looks_local(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    return any(marker in normalized for marker in LOCAL_HOST_MARKERS)


def auth_header(*, api_key: str | None = None, authorization: str | None = None) -> dict[str, str]:
    if authorization:
        value = authorization.strip()
        if ":" in value:
            header_name, _, header_value = value.partition(":")
            normalized_name = header_name.strip().lower()
            normalized_value = header_value.strip()
            if normalized_name == "authorization" and normalized_value:
                return {"Authorization": normalized_value}
            if normalized_name == "x-api-key" and normalized_value:
                return {"X-API-Key": normalized_value}
        return {"Authorization": value}
    if api_key:
        value = api_key.strip()
        if ":" in value:
            header_name, _, header_value = value.partition(":")
            if header_name.strip().lower() == "x-api-key" and header_value.strip():
                value = header_value.strip()
        return {"X-API-Key": value}
    return {}


def http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 60,
) -> HttpResult:
    encoded = None
    request_headers = dict(headers or {})
    if body is not None:
        encoded = json.dumps(body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    http_request = request.Request(url, headers=request_headers, data=encoded, method=method)
    try:
        with request.urlopen(http_request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            payload = json.loads(raw) if raw else None
            return HttpResult(status=response.status, payload=payload)
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload: Any = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw
        return HttpResult(status=exc.code, payload=payload)


def _is_demo_subject(payload: dict[str, Any]) -> bool:
    subject = str(payload.get("subject") or "")
    return subject.startswith("demo-role:")


def _looks_local_identity(value: str | None) -> bool:
    normalized = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    if not normalized:
        return False
    return any(marker in normalized for marker in ("local", "localhost", ".local", "local poc"))


def evaluate_surface_contract(
    *,
    anonymous_session: dict[str, Any],
    operator_session: dict[str, Any] | None,
    reviewer_session: dict[str, Any] | None,
    live_anon: HttpResult,
    live_operator: HttpResult | None,
    ready_anon: HttpResult,
    ready_reviewer: HttpResult | None,
    public_contract: dict[str, Any] | None = None,
    public_latest_run: dict[str, Any] | None = None,
    public_findings: dict[str, Any] | None = None,
    public_report_preview: dict[str, Any] | None = None,
    expect_human_review: bool = True,
    expect_nonlocal_idp: bool = True,
    expect_no_demo_roles: bool = True,
) -> list[str]:
    failures: list[str] = []
    operator_session = operator_session or {}
    reviewer_session = reviewer_session or {}

    if anonymous_session.get("authenticated") is not False or anonymous_session.get("role") != "anonymous":
        failures.append("Anonymous /ui/session is not anonymous.")

    if public_contract is not None:
        if public_contract.get("public_safe") is not True:
            failures.append("Anonymous workspace contract is not marked public_safe=true.")
        principal = public_contract.get("principal") or {}
        if principal.get("authenticated") is not False or principal.get("role") != "anonymous":
            failures.append("Anonymous workspace contract principal is not anonymous.")
        surfaces = {
            str(item.get("surface_id") or ""): item
            for item in (public_contract.get("surfaces") or [])
            if isinstance(item, dict)
        }
        for surface_id in ("overview", "cases", "evidence", "reports"):
            route = str((surfaces.get(surface_id) or {}).get("primary_route") or "")
            if not route.startswith("/public/"):
                failures.append(
                    f"Anonymous workspace contract route for {surface_id} is not public-safe: {route!r}."
                )

    if public_latest_run is not None and public_latest_run.get("public_safe") is not True:
        failures.append("/public/runs/latest is not marked public_safe=true.")
    if public_findings is not None and public_findings.get("public_safe") is not True:
        failures.append("/public/runs/latest/findings is not marked public_safe=true.")
    if public_report_preview is not None:
        if public_report_preview.get("public_safe") is not True:
            failures.append("/public/runs/latest/report-preview is not marked public_safe=true.")
        preview_text = str(public_report_preview.get("preview_text") or "")
        if preview_text and "Protected artifact bodies remain behind reviewer/operator authentication" not in preview_text:
            failures.append("Public report preview is missing the protected-artifact boundary note.")

    authenticated_surface_checked = any(
        [operator_session, reviewer_session, live_operator is not None, ready_reviewer is not None]
    )
    if authenticated_surface_checked:
        if operator_session.get("authenticated") is not True or operator_session.get("role") != "operator":
            failures.append("Operator /ui/session did not authenticate as operator.")

        if reviewer_session.get("authenticated") is not True or reviewer_session.get("role") != "reviewer":
            failures.append("Reviewer /ui/session did not authenticate as reviewer.")

    if live_anon.status != 401:
        failures.append(f"Unauthenticated /health/live expected 401, got {live_anon.status}.")
    if live_operator is not None and live_operator.status != 200:
        failures.append(f"Operator /health/live expected 200, got {live_operator.status}.")
    if ready_anon.status != 401:
        failures.append(f"Unauthenticated /health/ready expected 401, got {ready_anon.status}.")
    if ready_reviewer is not None and ready_reviewer.status != 200:
        failures.append(f"Reviewer /health/ready expected 200, got {ready_reviewer.status}.")

    if ready_reviewer is None:
        return failures

    if not isinstance(ready_reviewer.payload, dict):
        failures.append("Reviewer /health/ready did not return JSON payload.")
        return failures

    checks = ready_reviewer.payload.get("checks") or {}
    governance = checks.get("governance") or {}
    auth = checks.get("auth") or {}

    if expect_human_review:
        if operator_session.get("require_human_review") is not True:
            failures.append("Operator /ui/session reports require_human_review=false.")
        if reviewer_session.get("require_human_review") is not True:
            failures.append("Reviewer /ui/session reports require_human_review=false.")
        if governance.get("require_human_review") is not True:
            failures.append("/health/ready governance check reports require_human_review=false.")

    if expect_nonlocal_idp and looks_local(str(auth.get("issuer") or "")):
        failures.append(f"/health/ready auth issuer is still local: {auth.get('issuer')!r}.")

    if expect_no_demo_roles:
        if _is_demo_subject(operator_session):
            failures.append("Operator session is using demo-role authentication.")
        if _is_demo_subject(reviewer_session):
            failures.append("Reviewer session is using demo-role authentication.")

    for role_name, session in (("Operator", operator_session), ("Reviewer", reviewer_session)):
        subject = str(session.get("subject") or "")
        if subject and _looks_local_identity(subject):
            failures.append(f"{role_name} session subject still looks local: {subject!r}.")
        tenant_context = session.get("tenant_context") or {}
        if isinstance(tenant_context, dict):
            tenant_id = str(tenant_context.get("tenant_id") or "")
            tenant_name = str(tenant_context.get("tenant_name") or "")
            workspace_id = str(tenant_context.get("workspace_id") or "")
            if tenant_id and _looks_local_identity(tenant_id):
                failures.append(f"{role_name} session tenant_id still looks local: {tenant_id!r}.")
            if tenant_name and _looks_local_identity(tenant_name):
                failures.append(f"{role_name} session tenant_name still looks local: {tenant_name!r}.")
            if workspace_id and _looks_local_identity(workspace_id):
                failures.append(f"{role_name} session workspace_id still looks local: {workspace_id!r}.")

    return failures


def verify_surface(
    *,
    base_url: str,
    operator_headers: dict[str, str] | None,
    reviewer_headers: dict[str, str] | None,
    expect_human_review: bool = True,
    expect_nonlocal_idp: bool = True,
    expect_no_demo_roles: bool = True,
) -> dict[str, Any]:
    base = base_url.rstrip("/")
    operator_headers = dict(operator_headers or {})
    reviewer_headers = dict(reviewer_headers or {})
    have_operator = bool(operator_headers)
    have_reviewer = bool(reviewer_headers)

    anonymous_session = http_json("GET", f"{base}/ui/session").payload
    operator_session = http_json("GET", f"{base}/ui/session", headers=operator_headers).payload if have_operator else None
    reviewer_session = http_json("GET", f"{base}/ui/session", headers=reviewer_headers).payload if have_reviewer else None
    public_contract = http_json("GET", f"{base}/ui/workspace-contract/latest").payload
    public_latest_run = http_json("GET", f"{base}/public/runs/latest").payload
    public_findings = http_json("GET", f"{base}/public/runs/latest/findings").payload
    public_report_preview = http_json("GET", f"{base}/public/runs/latest/report-preview").payload
    live_anon = http_json("GET", f"{base}/health/live")
    live_operator = http_json("GET", f"{base}/health/live", headers=operator_headers) if have_operator else None
    ready_anon = http_json("GET", f"{base}/health/ready")
    ready_reviewer = http_json("GET", f"{base}/health/ready", headers=reviewer_headers) if have_reviewer else None

    failures = evaluate_surface_contract(
        anonymous_session=anonymous_session or {},
        operator_session=operator_session,
        reviewer_session=reviewer_session,
        live_anon=live_anon,
        live_operator=live_operator,
        ready_anon=ready_anon,
        ready_reviewer=ready_reviewer,
        public_contract=public_contract if isinstance(public_contract, dict) else None,
        public_latest_run=public_latest_run if isinstance(public_latest_run, dict) else None,
        public_findings=public_findings if isinstance(public_findings, dict) else None,
        public_report_preview=public_report_preview if isinstance(public_report_preview, dict) else None,
        expect_human_review=expect_human_review,
        expect_nonlocal_idp=expect_nonlocal_idp,
        expect_no_demo_roles=expect_no_demo_roles,
    )

    return {
        "base_url": base,
        "anonymous_session": anonymous_session,
        "public_workspace_contract": public_contract,
        "public_latest_run": public_latest_run,
        "public_findings": public_findings,
        "public_report_preview": public_report_preview,
        "operator_session": operator_session,
        "reviewer_session": reviewer_session,
        "health_live_anonymous_status": live_anon.status,
        "health_live_operator_status": live_operator.status if live_operator else None,
        "health_ready_anonymous_status": ready_anon.status,
        "health_ready_reviewer_status": ready_reviewer.status if ready_reviewer else None,
        "readiness_payload": ready_reviewer.payload if ready_reviewer else None,
        "authenticated_validation": have_operator and have_reviewer,
        "failures": failures,
        "ok": not failures,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the externally visible governed StrategyOS surface.",
    )
    parser.add_argument("--base-url", default=os.environ.get("TARGET_URL", ""))
    parser.add_argument("--operator-api-key", default=os.environ.get("OPERATOR_API_KEY", ""))
    parser.add_argument(
        "--operator-auth-header",
        default=os.environ.get("OPERATOR_AUTH_HEADER", ""),
    )
    parser.add_argument("--reviewer-api-key", default=os.environ.get("REVIEWER_API_KEY", ""))
    parser.add_argument(
        "--reviewer-auth-header",
        default=os.environ.get("REVIEWER_AUTH_HEADER", ""),
    )
    parser.add_argument(
        "--allow-demo-roles",
        action="store_true",
        help="Do not fail when authenticated sessions use demo-role credentials.",
    )
    parser.add_argument(
        "--allow-local-idp",
        action="store_true",
        help="Do not fail when the externally visible auth issuer is localhost/container-local.",
    )
    parser.add_argument(
        "--allow-review-disabled",
        action="store_true",
        help="Do not fail when the externally visible surface reports require_human_review=false.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.base_url:
        parser.error("--base-url or TARGET_URL is required.")

    operator_headers = auth_header(
        api_key=args.operator_api_key or None,
        authorization=args.operator_auth_header or None,
    )
    reviewer_headers = auth_header(
        api_key=args.reviewer_api_key or None,
        authorization=args.reviewer_auth_header or None,
    )
    if bool(operator_headers) != bool(reviewer_headers):
        parser.error(
            "Provide both operator and reviewer credentials for authenticated validation, or omit both for public-safe-only validation."
        )

    result = verify_surface(
        base_url=args.base_url,
        operator_headers=operator_headers,
        reviewer_headers=reviewer_headers,
        expect_human_review=not args.allow_review_disabled,
        expect_nonlocal_idp=not args.allow_local_idp,
        expect_no_demo_roles=not args.allow_demo_roles,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
