#!/usr/bin/env python3
"""Browser-level acceptance for the governed public-research journey."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin


def preview_password(raw: str, username: str = "executive.tester") -> str:
    for item in raw.split(","):
        candidate, separator, password = item.partition("=")
        if separator and candidate.strip() == username and password:
            return password
    raise RuntimeError(f"{username} is unavailable in STRATEGYOS_IDP_TEST_USERS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("STRATEGYOS_PUBLIC_URL"))
    parser.add_argument("--output-dir", default="hosted-research-ui-acceptance")
    args = parser.parse_args()
    if not args.base_url:
        parser.error("--base-url or STRATEGYOS_PUBLIC_URL is required")

    from playwright.sync_api import expect, sync_playwright

    base_url = args.base_url.rstrip("/") + "/"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    password = preview_password(os.environ.get("STRATEGYOS_IDP_TEST_USERS", ""))
    question = (
        "ProTec concentration in Modern Trade is 87.4%, above the confidential "
        "board limit. What does external benchmark practice suggest?"
    )
    report: dict[str, object] = {
        "subject": base_url,
        "started_at": datetime.now(UTC).isoformat(),
        "steps": [],
    }
    page = None

    def passed(name: str, evidence: dict[str, object] | None = None) -> None:
        report["steps"].append({"name": name, "status": "passed", "evidence": evidence or {}})

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.goto(urljoin(base_url, "app?persona=ceo"), wait_until="domcontentloaded")
            page.wait_for_url(lambda url: "/login" in url, timeout=15_000)
            passed("Anonymous executive route redirects to sign-in")

            username = page.locator("#username")
            if username.evaluate("node => node.tagName") == "SELECT":
                username.select_option("executive.tester")
            else:
                username.fill("executive.tester")
            page.locator("#password").fill(password)
            page.get_by_role("button", name="Sign in").click()
            page.wait_for_url(lambda url: "/login" not in url, timeout=15_000)
            passed("Authorized executive signs in through the hosted UI")

            page.goto(urljoin(base_url, "app?persona=ceo"), wait_until="domcontentloaded")
            # DOMContentLoaded precedes the executive packet and event-handler
            # binding. A visible static launcher is therefore not sufficient
            # proof that the application is interactive yet.
            expect(page.locator("#driver-row")).to_contain_text("Revenue", timeout=45_000)
            # The fixed dock is intentionally replaced by the top-bar launcher
            # between 981px and 1799px. Exercise whichever production control
            # is visible at the configured viewport.
            launcher = page.locator(
                "#topbar-assistant-launch:visible, #chat-launcher:visible"
            ).first
            launcher.wait_for(state="visible", timeout=10_000)
            page.wait_for_function(
                "node => typeof node.onclick === 'function'",
                arg=launcher.element_handle(),
                timeout=10_000,
            )
            launcher.click()
            page.locator("#assistant-drawer.is-open").wait_for(state="visible", timeout=10_000)
            page.locator("#assistant-input").fill(question)
            page.locator("#assistant-form button[type=submit]").click()

            evidence = page.locator(".assistant-research-evidence").last
            evidence.wait_for(state="visible", timeout=45_000)
            message = page.locator("#assistant-messages .assistant-message--assistant").last
            expect(message).to_contain_text("Public research", timeout=10_000)
            expect(evidence).to_contain_text("Research boundary · audited")
            evidence.locator("summary").click()
            page.wait_for_function(
                "node => node.open === true",
                arg=evidence.element_handle(),
                timeout=5_000,
            )
            evidence_text = evidence.inner_text()
            assert "Approved public query:" in evidence_text
            assert "No client evidence was sent" in evidence_text
            assert "Audit " in evidence_text
            for private_canary in ("ProTec", "87.4", "confidential", "board limit", "Modern Trade"):
                assert private_canary.casefold() not in evidence_text.casefold(), evidence_text
            citation_links = message.locator('a[href^="https://en.wikipedia.org/wiki/"]')
            assert citation_links.count() >= 1
            page.screenshot(path=output_dir / "research-boundary.png", full_page=True)
            passed("Hermes renders governed public research with audit evidence and approved citations", {
                "citation_count": citation_links.count(),
                "boundary_text": evidence_text,
            })
            report["status"] = "passed"
            report["summary"] = {
                "passed_steps": len(report["steps"]),
                "citation_count": citation_links.count(),
            }
            browser.close()
    except Exception as exc:
        if page is not None:
            report["failure_url"] = page.url
            try:
                page.screenshot(path=output_dir / "failure.png", full_page=True)
            except Exception:
                pass
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    print(json.dumps(report["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
