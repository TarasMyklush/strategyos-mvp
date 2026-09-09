#!/usr/bin/env python3
"""Ratify and verify the staged FY2026 customer Intent record on branch preview.

This acceptance uses the preview tenant's independent administrator and
executive test identities.  It is idempotent and never edits source bytes or
creates a substitute plan.  The resulting ratification note explicitly records
that this is preview acceptance of synthetic material, not a business approval.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


PLAN_ID = "pd-tw-2026-v1-plan"
ACTUAL_REVISION = "pd-tw-2026-v1-plan-actuals-through-2026-06"
OBJECTIVE = Decimal("2540000000")
REPORTED_PLAN = Decimal("1194000000.06")
REPORTED_ACTUAL = Decimal("1267999999.96")


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
        self.origin = f"{urlsplit(self.base_url).scheme}://{urlsplit(self.base_url).netloc}"
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json", "Origin": self.origin}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(urljoin(self.base_url, path.lstrip("/")), data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc

    def login(self, username: str, password: str) -> dict:
        self.call("POST", "/auth/login", {"username": username, "password": password})
        session = self.call("GET", "/ui/session")
        if not session.get("authenticated"):
            raise RuntimeError(f"Hosted session was not established for {username}")
        return session


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("STRATEGYOS_PUBLIC_URL"))
    parser.add_argument("--output-dir", default="hosted-customer-intent-acceptance")
    args = parser.parse_args()
    if not args.base_url:
        parser.error("--base-url or STRATEGYOS_PUBLIC_URL is required")

    users = test_users(os.environ.get("STRATEGYOS_IDP_TEST_USERS", ""))
    required = ("tenant-admin.tester", "executive.tester")
    missing = [username for username in required if username not in users]
    if missing:
        raise RuntimeError("Required hosted test identities are unavailable: " + ", ".join(missing))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "subject": args.base_url,
        "started_at": datetime.now(UTC).isoformat(),
        "mode": "preview acceptance of the staged synthetic FY2026 customer Intent record",
        "steps": [],
    }

    def passed(name: str, evidence: dict | None = None) -> None:
        report["steps"].append({"name": name, "status": "passed", "evidence": evidence or {}})

    try:
        administrator = Session(args.base_url)
        executive = Session(args.base_url)
        admin_session = administrator.login("tenant-admin.tester", users["tenant-admin.tester"])
        executive_session = executive.login("executive.tester", users["executive.tester"])
        assert admin_session["role"] == "tenant_admin"
        assert executive_session["role"] == "executive"
        assert admin_session["tenant_context"]["tenant_id"] == executive_session["tenant_context"]["tenant_id"]
        passed("Independent administrator and executive preview identities authenticate in one tenant")

        catalog = executive.call("GET", "/api/intent/dimensional/catalog?limit=50")
        customer_plans = [item for item in catalog["plans"] if item["plan_id"] == PLAN_ID]
        assert len(customer_plans) == 1, customer_plans
        assert len(catalog["plans"]) == 1, catalog["plans"]
        summary = customer_plans[0]
        plan = executive.call(
            "GET", f"/api/intent/dimensional/plans/{quote(PLAN_ID)}/versions/{summary['version']}"
        )
        payload = plan["payload"]
        assert payload["display_name"].startswith("Tamween Pharma Distribution FY2026 revenue plan")
        assert payload["period"] == {"start": "2026-01-01", "end": "2026-12-31"}
        assert len(payload["cells"]) == 576
        assert Decimal(payload["metrics"]["revenue"]["planned_total"]) == OBJECTIVE
        assert sum((Decimal(cell["target"]) for cell in payload["cells"]), Decimal()) == OBJECTIVE
        assert all(cell["owner"].strip() for cell in payload["cells"])
        assert {cell["dimensions"]["region"] for cell in payload["cells"]} == {
            "Central", "Eastern", "Southern", "Western"
        }
        assert all("item-a" not in json.dumps(cell).lower() for cell in payload["cells"])
        passed("The only customer plan is the source-bound FY2026 plan of record", {
            "cell_count": 576,
            "objective_sar": str(OBJECTIVE),
            "named_owner_count": 576,
        })

        if plan["governance_status"] == "proposed":
            subject = executive_session["subject"]
            grant = administrator.call(
                "GET", f"/api/intent/dimensional/plans/{quote(PLAN_ID)}/ratifier?subject={quote(subject)}"
            )
            if not grant["enabled"]:
                administrator.call("PUT", f"/api/intent/dimensional/plans/{quote(PLAN_ID)}/ratifier", {
                    "subject": subject, "enabled": True, "expected_revision": grant["revision"],
                })
            executive.call(
                "POST", f"/api/intent/dimensional/plans/{quote(PLAN_ID)}/versions/{plan['version']}/ratify", {
                    "expected_digest": plan["digest"],
                    "note": (
                        "Preview acceptance by an independently authorized executive test identity. "
                        "The staged synthetic targets, owners, structure and source evidence were reviewed."
                    ),
                },
            )
            plan = executive.call(
                "GET", f"/api/intent/dimensional/plans/{quote(PLAN_ID)}/versions/{plan['version']}"
            )
        assert plan["governance_status"] == "ratified"
        assert plan["ratification"]["approved_by"] == executive_session["subject"]
        passed("The staged plan is independently ratified for preview acceptance")

        actuals = executive.call("GET", f"/api/intent/dimensional/actuals/{quote(ACTUAL_REVISION)}")
        assert actuals["payload"]["period"] == {"start": "2026-01-01", "end": "2026-06-30"}
        assert len(actuals["payload"]["observations"]) == 288
        analysis = executive.call("POST", "/api/intent/dimensional/analyses", {
            "plan_id": PLAN_ID,
            "plan_version": plan["version"],
            "actual_revision": ACTUAL_REVISION,
            "as_of": catalog["today"],
        })
        assert len(analysis["granular_stories"]) == 3
        rollup = analysis["rollups"][0]
        assert Decimal(rollup["target"]) == REPORTED_PLAN
        assert Decimal(rollup["actual"]) == REPORTED_ACTUAL
        assert rollup["planned_cells"] == 288 == rollup["measured_cells"]
        for story in analysis["granular_stories"]:
            assert story["complete"] is True
            assert Decimal(story["target"]) == Decimal(rollup["target"])
            assert Decimal(story["actual"]) == Decimal(rollup["actual"])
        passed("Three server-calculated granular stories reconcile to the reported-period totals", {
            "story_dimensions": [story["dimension"] for story in analysis["granular_stories"]],
            "reported_plan_sar": rollup["target"],
            "reported_actual_sar": rollup["actual"],
            "analysis_id": analysis["analysis_hash"],
        })

        refreshed = executive.call("GET", "/api/intent/dimensional/catalog?limit=50")
        refreshed_plan = next(item for item in refreshed["plans"] if item["plan_id"] == PLAN_ID)
        assert refreshed_plan["governance_status"] == "ratified"
        assert len(refreshed_plan["latest_analysis"]["granular_stories"]) == 3
        passed("The compact executive catalog exposes the verified analysis without QA records")

        report["status"] = "passed"
        report["summary"] = {
            "passed_steps": len(report["steps"]),
            "plan_cells": 576,
            "analysis_cells": rollup["planned_cells"],
            "granular_stories": 3,
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
