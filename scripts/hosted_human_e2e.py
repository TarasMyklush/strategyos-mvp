#!/usr/bin/env python3
"""Human-style, read-only acceptance walkthrough for the hosted Kyvern demo pack."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin


STORIES = (
    {
        "title": "Institutional client rescues regional misses",
        "rollup": ("300", "295", "-5", "on_plan", "3 / 3"),
        "findings": ("offset", "concentration"),
        "cell_count": 3,
        "evidence_count": 6,
    },
    {
        "title": "Volume growth hides adverse commercial mix",
        "rollup": ("300", "333", "33", "ahead", "2 / 2"),
        "findings": ("offset", "price / volume / mix"),
        "effects": ("Volume 60.00", "Mix -30.00", "Price 3.00", "Observed 33 SAR"),
        "cell_count": 2,
        "evidence_count": 12,
    },
    {
        "title": "Regional miss links to a credit constraint",
        "rollup": ("300", "240", "-60", "behind", "2 / 2"),
        "findings": (),
        "cell_count": 2,
        "evidence_count": 4,
    },
)


def preview_password(raw: str, username: str = "executive.tester") -> str:
    for item in raw.split(","):
        candidate, separator, password = item.partition("=")
        if separator and candidate.strip() == username and password:
            return password
    raise RuntimeError(f"{username} is unavailable in STRATEGYOS_IDP_TEST_USERS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("STRATEGYOS_PUBLIC_URL"))
    parser.add_argument("--output-dir", default="hosted-human-e2e")
    args = parser.parse_args()
    if not args.base_url:
        parser.error("--base-url or STRATEGYOS_PUBLIC_URL is required")

    from playwright.sync_api import sync_playwright

    base_url = args.base_url.rstrip("/") + "/"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    password = preview_password(os.environ.get("STRATEGYOS_IDP_TEST_USERS", ""))
    report: dict[str, object] = {
        "subject": base_url,
        "persona": "executive.tester",
        "started_at": datetime.now(UTC).isoformat(),
        "mode": "read-only Chromium walkthrough",
        "steps": [],
    }

    def pass_step(name: str, evidence: dict[str, object] | None = None) -> None:
        report["steps"].append({"name": name, "status": "passed", "evidence": evidence or {}})

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                accept_downloads=True,
                locale="en-GB",
                timezone_id="Asia/Dubai",
            )
            page = context.new_page()

            response = page.goto(urljoin(base_url, "plan"), wait_until="domcontentloaded")
            assert response and response.ok
            page.wait_for_url(re.compile(r"/login(?:\?.*)?$"))
            assert page.get_by_role("heading", name="Sign in to Kyvern").is_visible()
            pass_step("Protected /plan redirects to customer sign-in", {"url": page.url})

            if page.locator("#username").evaluate("node => node.tagName") == "SELECT":
                page.locator("#username").select_option("executive.tester")
            else:
                page.locator("#username").fill("executive.tester")
            page.locator("#password").fill("deliberately-wrong")
            page.get_by_role("button", name="Sign in").click()
            assert page.get_by_text("Invalid credentials for this role.").is_visible()
            assert re.search(r"/login(?:\?.*)?$", page.url)
            pass_step("Invalid password is rejected without leaving sign-in")

            page.locator("#password").fill(password)
            page.get_by_role("button", name="Sign in").click()
            page.wait_for_url(lambda url: "/login" not in url, timeout=15_000)
            pass_step("Authorized executive preview account signs in", {"landing_url": page.url})

            page.goto(urljoin(base_url, "plan"), wait_until="domcontentloaded")
            page.locator("#demo-pack-panel:not([hidden])").wait_for(timeout=15_000)
            assert page.locator("#demo-pack-title").inner_text() == "Healthcare and pharma distribution decisions"
            assert page.locator("#demo-pack-stories .demo-story-card").count() == 3
            assert page.get_by_text("Synthetic data", exact=True).is_visible()
            assert page.get_by_text("Read only", exact=True).is_visible()
            assert page.get_by_text("No authority effect", exact=True).is_visible()
            page.screenshot(path=output_dir / "01-story-catalog.png", full_page=True)
            pass_step("Configured pack renders three read-only decision stories")

            for index, expected in enumerate(STORIES, start=1):
                button = page.locator("#demo-pack-stories button").nth(index - 1)
                if index == 1:
                    button.focus()
                    button.press("Enter")
                else:
                    button.click()
                page.locator("#demo-story-detail:not([hidden])").wait_for()
                assert page.locator("#demo-story-title").inner_text() == expected["title"]

                rollup_cells = page.locator("#demo-story-rollups tbody tr").first.locator("td")
                values = tuple(rollup_cells.nth(cell).inner_text() for cell in range(1, 6))
                assert values == expected["rollup"], (expected["title"], values)

                findings_text = page.locator("#demo-story-findings").inner_text().lower()
                for finding in expected["findings"]:
                    assert finding in findings_text
                for effect in expected.get("effects", ()):
                    assert effect in page.locator("#demo-story-findings").inner_text()

                cells = page.locator("#demo-story-cells tbody tr")
                assert cells.count() == expected["cell_count"]
                links = page.locator("#demo-story-detail a")
                assert links.count() == expected["evidence_count"]
                evidence_statuses = []
                for evidence_index in range(links.count()):
                    href = links.nth(evidence_index).get_attribute("href")
                    assert href
                    evidence_response = context.request.get(urljoin(base_url, href.lstrip("/")))
                    evidence_statuses.append(evidence_response.status)
                    assert evidence_response.ok
                    assert re.fullmatch(
                        r"[0-9a-f]{64}",
                        evidence_response.headers.get("x-kyvern-source-sha256", ""),
                    )

                first_link = links.first
                with page.expect_download() as download_info:
                    first_link.click()
                download = download_info.value
                download.save_as(output_dir / f"story-{index}-evidence-{download.suggested_filename}")

                board_pages = page.locator("#demo-story-board details")
                assert board_pages.count() >= 2
                for board_index in range(board_pages.count()):
                    board_pages.nth(board_index).locator("summary").click()
                board_text = page.locator("#demo-story-board").inner_text()
                assert re.search(r"[\u0600-\u06ff]", board_text)
                page.screenshot(path=output_dir / f"0{index + 1}-story-{index}.png", full_page=True)
                pass_step(
                    f"Story {index}: {expected['title']}",
                    {
                        "rollup": values,
                        "cells": cells.count(),
                        "evidence_links": links.count(),
                        "evidence_statuses": evidence_statuses,
                        "bilingual_board_pages": board_pages.count(),
                    },
                )
                page.get_by_role("button", name="Back to stories").click()
                assert page.locator("#demo-pack-stories").is_visible()

            page.set_viewport_size({"width": 390, "height": 844})
            assert page.get_by_role("link", name="Intent Vault").is_visible()
            assert page.locator("#demo-pack-stories .demo-story-card").count() == 3
            page.screenshot(path=output_dir / "05-mobile-catalog.png", full_page=True)
            pass_step("Catalog remains usable at a 390px mobile viewport")

            logout_response = page.goto(urljoin(base_url, "auth/logout"), wait_until="domcontentloaded")
            assert logout_response and logout_response.ok
            page.goto(urljoin(base_url, "plan"), wait_until="domcontentloaded")
            page.wait_for_url(re.compile(r"/login(?:\?.*)?$"))
            pass_step("Sign-out clears the session and protects direct /plan access")
            browser.close()
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["finished_at"] = datetime.now(UTC).isoformat()
        (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        raise

    report["status"] = "passed"
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["summary"] = {
        "passed_steps": len(report["steps"]),
        "stories_opened": len(STORIES),
        "evidence_links_verified": sum(item["evidence_count"] for item in STORIES),
        "viewport_widths": [1440, 390],
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
