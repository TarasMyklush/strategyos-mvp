from __future__ import annotations

from strategyos_mvp.cloud_surface_verifier import HttpResult, auth_header, evaluate_surface_contract, looks_local


def test_looks_local_detects_local_and_container_hosts() -> None:
    assert looks_local("http://localhost:8089") is True
    assert looks_local("http://strategyos-idp:9000/oauth/introspect") is True
    assert looks_local("https://idp.strategyos.example.test") is False


def test_evaluate_surface_contract_flags_external_governance_drift() -> None:
    failures = evaluate_surface_contract(
        anonymous_session={"authenticated": False, "role": "anonymous"},
        operator_session={
            "authenticated": True,
            "role": "operator",
            "subject": "demo-role:operator",
            "require_human_review": False,
        },
        reviewer_session={
            "authenticated": True,
            "role": "reviewer",
            "subject": "demo-role:reviewer",
            "require_human_review": False,
        },
        live_anon=HttpResult(status=401, payload={"detail": "A valid identity token is required."}),
        live_operator=HttpResult(status=200, payload={"status": "ok"}),
        ready_anon=HttpResult(status=401, payload={"detail": "A valid identity token is required."}),
        ready_reviewer=HttpResult(
            status=200,
            payload={
                "status": "ok",
                "checks": {
                    "governance": {
                        "status": "ok",
                        "require_human_review": False,
                    },
                    "auth": {
                        "status": "ok",
                        "issuer": "http://localhost:8089",
                    },
                },
            },
        ),
    )

    assert any("require_human_review=false" in failure for failure in failures)
    assert any("local" in failure.lower() for failure in failures)
    assert any("demo-role" in failure for failure in failures)


def test_evaluate_surface_contract_accepts_hardened_external_surface() -> None:
    failures = evaluate_surface_contract(
        anonymous_session={"authenticated": False, "role": "anonymous"},
        operator_session={
            "authenticated": True,
            "role": "operator",
            "subject": "https://idp.strategyos.example.test:operator.prod",
            "require_human_review": True,
        },
        reviewer_session={
            "authenticated": True,
            "role": "reviewer",
            "subject": "https://idp.strategyos.example.test:reviewer.prod",
            "require_human_review": True,
        },
        live_anon=HttpResult(status=401, payload={"detail": "A valid identity token is required."}),
        live_operator=HttpResult(status=200, payload={"status": "ok"}),
        ready_anon=HttpResult(status=401, payload={"detail": "A valid identity token is required."}),
        ready_reviewer=HttpResult(
            status=200,
            payload={
                "status": "ok",
                "checks": {
                    "governance": {
                        "status": "ok",
                        "require_human_review": True,
                    },
                    "auth": {
                        "status": "ok",
                        "issuer": "https://idp.strategyos.example.test",
                    },
                },
            },
        ),
    )

    assert failures == []


def test_evaluate_surface_contract_accepts_public_safe_only_validation() -> None:
    failures = evaluate_surface_contract(
        anonymous_session={"authenticated": False, "role": "anonymous"},
        operator_session=None,
        reviewer_session=None,
        live_anon=HttpResult(status=401, payload={"detail": "A valid identity token is required."}),
        live_operator=None,
        ready_anon=HttpResult(status=401, payload={"detail": "A valid identity token is required."}),
        ready_reviewer=None,
        public_contract={
            "status": "ok",
            "public_safe": True,
            "principal": {"authenticated": False, "role": "anonymous"},
            "surfaces": [
                {"surface_id": "overview", "primary_route": "/public/runs/latest"},
                {"surface_id": "cases", "primary_route": "/public/runs/latest/findings"},
                {"surface_id": "evidence", "primary_route": "/public/data/evidence-preview"},
                {"surface_id": "reports", "primary_route": "/public/runs/latest/report-preview"},
            ],
        },
        public_latest_run={"status": "ok", "public_safe": True},
        public_findings={"status": "ok", "public_safe": True},
        public_report_preview={
            "status": "ok",
            "public_safe": True,
            "preview_text": "Protected artifact bodies remain behind reviewer/operator authentication; this public preview is a synthesized board-safe status note.",
        },
    )

    assert failures == []


def test_auth_header_accepts_full_authorization_header_line() -> None:
    assert auth_header(authorization="Authorization: Bearer token-123") == {
        "Authorization": "Bearer token-123"
    }


def test_auth_header_accepts_full_api_key_header_line() -> None:
    assert auth_header(authorization="X-API-Key: abc123") == {"X-API-Key": "abc123"}
    assert auth_header(api_key="X-API-Key: abc123") == {"X-API-Key": "abc123"}
