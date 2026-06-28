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
            "tenant_context": {
                "tenant_id": "local-poc",
                "tenant_name": "StrategyOS Local POC",
                "workspace_id": "local-poc",
            },
        },
        reviewer_session={
            "authenticated": True,
            "role": "reviewer",
            "subject": "http://localhost:8089:reviewer.local",
            "require_human_review": False,
            "tenant_context": {
                "tenant_id": "local-poc",
                "tenant_name": "StrategyOS Local POC",
                "workspace_id": "local-poc",
            },
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
            "tenant_context": {
                "tenant_id": "strategyos-live",
                "tenant_name": "StrategyOS Live",
                "workspace_id": "strategyos-live",
            },
        },
        reviewer_session={
            "authenticated": True,
            "role": "reviewer",
            "subject": "https://idp.strategyos.example.test:reviewer.prod",
            "require_human_review": True,
            "tenant_context": {
                "tenant_id": "strategyos-live",
                "tenant_name": "StrategyOS Live",
                "workspace_id": "strategyos-live",
            },
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


def test_evaluate_surface_contract_rejects_banned_anonymous_payload_content() -> None:
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
        public_latest_run={"status": "ok", "public_safe": True, "run_id": "latest-public"},
        public_findings={
            "status": "ok",
            "public_safe": True,
            "findings": [{"title": "Duplicate payment for invoice INV-1", "case_href": "/public/runs/latest/cases/F-001"}],
        },
        public_evidence_preview={
            "status": "ok",
            "public_safe": True,
            "excerpt": "Protected artifact bodies remain behind reviewer/operator authentication.",
        },
        public_report_preview={
            "status": "ok",
            "public_safe": True,
            "preview_text": "Protected artifact bodies remain behind reviewer/operator authentication; this public preview is a synthesized board-safe status note.",
        },
        public_case_details=[HttpResult(status=200, payload={"status": "ok"})],
    )

    assert any("banned anonymous marker" in failure for failure in failures)


def test_evaluate_surface_contract_rejects_banned_workspace_contract_payload_content() -> None:
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
            "workspace": {
                "summary": "Duplicate payment for invoice INV-1",
            },
        },
        public_latest_run={"status": "ok", "public_safe": True, "run_id": "latest-public"},
        public_findings={"status": "ok", "public_safe": True, "findings": []},
        public_evidence_preview={
            "status": "ok",
            "public_safe": True,
            "excerpt": "Protected artifact bodies remain behind reviewer/operator authentication.",
        },
        public_report_preview={
            "status": "ok",
            "public_safe": True,
            "preview_text": "Protected artifact bodies remain behind reviewer/operator authentication; this public preview is a synthesized board-safe status note.",
        },
        public_case_details=[],
    )

    assert any(failure.startswith("/ui/workspace-contract/latest:") for failure in failures)


def test_evaluate_surface_contract_accepts_allowlist_only_anonymous_payloads() -> None:
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
        public_latest_run={"status": "ok", "public_safe": True, "run_id": "latest-public"},
        public_findings={
            "status": "ok",
            "public_safe": True,
            "findings": [{"title": "Duplicate payment signal", "case_href": None, "evidence_preview_href": None}],
        },
        public_evidence_preview={
            "status": "ok",
            "public_safe": True,
            "excerpt": "Protected artifact bodies remain behind reviewer/operator authentication.",
        },
        public_report_preview={
            "status": "ok",
            "public_safe": True,
            "preview_text": "Protected artifact bodies remain behind reviewer/operator authentication; this public preview is a synthesized board-safe status note.",
        },
        public_case_details=[],
    )

    assert failures == []


def test_auth_header_accepts_full_authorization_header_line() -> None:
    assert auth_header(authorization="Authorization: Bearer token-123") == {
        "Authorization": "Bearer token-123"
    }


def test_auth_header_accepts_full_api_key_header_line() -> None:
    assert auth_header(authorization="X-API-Key: abc123") == {"X-API-Key": "abc123"}
    assert auth_header(api_key="X-API-Key: abc123") == {"X-API-Key": "abc123"}
