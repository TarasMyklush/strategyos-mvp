#!/usr/bin/env python3
"""Process and approve the customer source pack when its cash projection is stale.

The exact registered source pack is discovered from the customer Intent plan,
not supplied as a second copy or a mutable workflow input.  A new governed run
is created only when the currently approved run does not already contain the
expected source-derived cash contract.  The reviewer validates the calculated
payload before approval and the operator resumes the approved checkpoint.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


PLAN_ID = "pd-tw-2026-v1-plan"
EXPECTED_CASH = Decimal("1410000000")
EXPECTED_FLOOR = Decimal("1200000000")
EXPECTED_HEADROOM = Decimal("210000000")
EXPECTED_PROVIDER = "Group Treasury (system feed)"
EXPECTED_TREND = [
    Decimal("1320000000"),
    Decimal("1370000000"),
    Decimal("1410000000"),
]


def test_users(raw: str) -> dict[str, str]:
    users: dict[str, str] = {}
    for item in raw.split(","):
        username, separator, password = item.partition("=")
        if separator and username.strip() and password:
            users[username.strip()] = password
    return users


class Session:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/") + "/"
        split = urlsplit(self.base_url)
        self.origin = f"{split.scheme}://{split.netloc}"
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method: str, path: str, body: dict | None = None, *, timeout: int = 120) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json", "Origin": self.origin}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            urljoin(self.base_url, path.lstrip("/")),
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc

    def login(self, username: str, password: str) -> dict:
        self.call("POST", "/auth/login", {"username": username, "password": password})
        session = self.call("GET", "/ui/session")
        if not session.get("authenticated"):
            raise RuntimeError(f"Hosted session was not established for {username}")
        return session


def _summary(record: dict) -> dict:
    value = record.get("summary_json")
    return value if isinstance(value, dict) else record


def _source_pack_id(record: dict) -> str:
    summary = _summary(record)
    source = summary.get("source_pack")
    if isinstance(source, dict) and source.get("source_pack_id"):
        return str(source["source_pack_id"])
    return str(summary.get("source_pack_id") or "")


def _finance(record: dict) -> dict:
    value = _summary(record).get("finance_kpi")
    return value if isinstance(value, dict) else {}


def _cash_contract(record: dict, *, source_pack_id: str) -> dict:
    finance = _finance(record)
    components = finance.get("components") if isinstance(finance.get("components"), dict) else {}
    actual_complete = finance.get("actual_complete") if isinstance(finance.get("actual_complete"), dict) else {}
    trend = finance.get("trend") if isinstance(finance.get("trend"), dict) else {}
    cash_trend = trend.get("cash_vs_floor") if isinstance(trend.get("cash_vs_floor"), dict) else {}
    actuals = [Decimal(str(value)) for value in cash_trend.get("actual") or []]
    cash = Decimal(str(components["cash_balance"])) if components.get("cash_balance") is not None else None
    floor = Decimal(str(components["board_floor"])) if components.get("board_floor") is not None else None
    headroom = cash - floor if cash is not None and floor is not None else None
    return {
        "matches_source": _source_pack_id(record) == source_pack_id,
        "cash": cash,
        "floor": floor,
        "headroom": headroom,
        "trend": actuals,
        "complete": actual_complete.get("cash_vs_floor") is True,
        "provider": str(
            ((finance.get("kpi_source_contracts") or {}).get("cash_vs_floor") or {}).get("provider") or ""
        ),
    }


def _assert_cash_contract(record: dict, *, source_pack_id: str) -> dict:
    contract = _cash_contract(record, source_pack_id=source_pack_id)
    assert contract["matches_source"] is True, contract
    assert contract["cash"] == EXPECTED_CASH, contract
    assert contract["floor"] == EXPECTED_FLOOR, contract
    assert contract["headroom"] == EXPECTED_HEADROOM, contract
    assert contract["trend"] == EXPECTED_TREND, contract
    assert contract["complete"] is True, contract
    assert contract["provider"] == EXPECTED_PROVIDER, contract
    return contract


def _run_id(payload: dict) -> str:
    for candidate in (
        payload.get("strategyos_run_id"),
        payload.get("run_id"),
        (payload.get("run") or {}).get("run_id") if isinstance(payload.get("run"), dict) else None,
    ):
        if candidate:
            return str(candidate)
    metadata = payload.get("metadata_json")
    if isinstance(metadata, dict):
        receipt = metadata.get("summary_receipt")
        if isinstance(receipt, dict) and receipt.get("run_id"):
            return str(receipt["run_id"])
    return ""


def _wait_for_job(session: Session, job_id: str, *, timeout_seconds: int) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last: dict = {}
    while time.monotonic() < deadline:
        last = session.call("GET", f"/runs/jobs/{quote(job_id)}")
        status = str(last.get("status") or "").lower()
        if status in {"succeeded", "completed"}:
            return last
        if status in {"failed", "cancelled", "canceled"}:
            raise RuntimeError(f"Hosted source run job {job_id} ended as {status}: {last}")
        time.sleep(5)
    raise TimeoutError(f"Hosted source run job {job_id} did not finish within {timeout_seconds} seconds: {last}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("STRATEGYOS_PUBLIC_URL"))
    parser.add_argument("--output-dir", default="hosted-source-finance-acceptance")
    parser.add_argument("--run-timeout-seconds", type=int, default=1200)
    args = parser.parse_args()
    if not args.base_url:
        parser.error("--base-url or STRATEGYOS_PUBLIC_URL is required")

    users = test_users(os.environ.get("STRATEGYOS_IDP_TEST_USERS", ""))
    required = ("operator.tester", "reviewer.tester", "executive.tester")
    missing = [username for username in required if username not in users]
    if missing:
        raise RuntimeError("Required hosted test identities are unavailable: " + ", ".join(missing))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "subject": args.base_url,
        "started_at": datetime.now(UTC).isoformat(),
        "mode": "idempotent governed processing of the registered customer source pack",
        "steps": [],
    }

    def passed(name: str, evidence: dict | None = None) -> None:
        report["steps"].append({"name": name, "status": "passed", "evidence": evidence or {}})

    try:
        operator = Session(args.base_url)
        reviewer = Session(args.base_url)
        executive = Session(args.base_url)
        operator_session = operator.login("operator.tester", users["operator.tester"])
        reviewer_session = reviewer.login("reviewer.tester", users["reviewer.tester"])
        executive_session = executive.login("executive.tester", users["executive.tester"])
        assert operator_session["role"] == "operator"
        assert reviewer_session["role"] == "reviewer"
        assert executive_session["role"] == "executive"
        tenant_ids = {
            operator_session["tenant_context"]["tenant_id"],
            reviewer_session["tenant_context"]["tenant_id"],
            executive_session["tenant_context"]["tenant_id"],
        }
        assert len(tenant_ids) == 1, tenant_ids
        passed("Independent operator, reviewer and executive identities authenticate in one tenant")

        catalog = executive.call("GET", "/api/intent/dimensional/catalog?limit=50")
        plan_summary = next(item for item in catalog["plans"] if item["plan_id"] == PLAN_ID)
        plan = executive.call(
            "GET", f"/api/intent/dimensional/plans/{quote(PLAN_ID)}/versions/{plan_summary['version']}"
        )
        source_pack_id = str(plan.get("source_pack_id") or "")
        assert source_pack_id, plan
        report["source_pack_id"] = source_pack_id
        passed("The finance run is bound to the same registered source pack as the customer plan")

        latest = executive.call("GET", "/runs/latest?persona=ceo&board=pre&driver=cash_vs_floor")
        try:
            contract = _assert_cash_contract(latest, source_pack_id=source_pack_id)
        except (AssertionError, KeyError, ValueError):
            submitted = operator.call("POST", "/runs", {
                "source_pack_id": source_pack_id,
                "skip_prepare": True,
                "sync_artifacts": True,
                "allow_partial_source_pack": True,
            })
            job_id = str(submitted.get("job_id") or "")
            assert job_id, submitted
            report["job_id"] = job_id
            completed_job = _wait_for_job(operator, job_id, timeout_seconds=args.run_timeout_seconds)
            run_id = _run_id(completed_job) or _run_id(submitted)
            assert run_id, completed_job
            report["run_id"] = run_id
            candidate = reviewer.call("GET", f"/reviewer/runs/{quote(run_id)}")
            contract = _assert_cash_contract(candidate, source_pack_id=source_pack_id)
            passed("A fresh governed run calculates the complete cash contract before approval", {
                "run_id": run_id,
                "cash_sar": str(contract["cash"]),
                "floor_sar": str(contract["floor"]),
                "headroom_sar": str(contract["headroom"]),
                "provider": contract["provider"],
            })

            reviewer.call("POST", f"/reviewer/runs/{quote(run_id)}/claim")
            reviewer.call("POST", f"/reviewer/runs/{quote(run_id)}/approve", {
                "comment": (
                    "Preview acceptance of the synthetic 9 September source pack. "
                    "The deterministic cash balance, approved floor, quarterly trajectory and evidence binding were reviewed."
                )
            })
            resumed = operator.call("POST", f"/operator/runs/{quote(run_id)}/resume", timeout=300)
            assert str(resumed.get("status") or "").lower() == "completed", resumed
            passed("A separate reviewer approves the calculated source snapshot and the operator resumes it")
        else:
            passed("The current approved source snapshot already contains the complete cash contract")

        final = executive.call("GET", "/runs/latest?persona=ceo&board=pre&driver=cash_vs_floor")
        final_contract = _assert_cash_contract(final, source_pack_id=source_pack_id)
        passed("The approved executive source snapshot exposes the reconciled cash result", {
            "cash_sar": str(final_contract["cash"]),
            "floor_sar": str(final_contract["floor"]),
            "headroom_sar": str(final_contract["headroom"]),
            "quarterly_actuals_sar": [str(value) for value in final_contract["trend"]],
            "provider": final_contract["provider"],
        })

        report["status"] = "passed"
        report["summary"] = {
            "passed_steps": len(report["steps"]),
            "cash_sar": str(EXPECTED_CASH),
            "floor_sar": str(EXPECTED_FLOOR),
            "headroom_sar": str(EXPECTED_HEADROOM),
        }
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        (output_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    print(json.dumps(report["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
