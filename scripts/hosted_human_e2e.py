#!/usr/bin/env python3
"""Human-style hosted acceptance for the current Kyvern executive journey."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
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
    parser.add_argument("--output-dir", default="hosted-human-e2e")
    args = parser.parse_args()
    if not args.base_url:
        parser.error("--base-url or STRATEGYOS_PUBLIC_URL is required")

    from playwright.sync_api import expect, sync_playwright

    base_url = args.base_url.rstrip("/") + "/"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    password = preview_password(os.environ.get("STRATEGYOS_IDP_TEST_USERS", ""))
    report: dict[str, object] = {
        "subject": base_url,
        "persona": "executive.tester",
        "started_at": datetime.now(UTC).isoformat(),
        "mode": "human-style Chromium walkthrough of the customer executive journey",
        "steps": [],
    }
    page = None
    browser = None
    playwright = sync_playwright().start()

    def passed(name: str, evidence: dict[str, object] | None = None) -> None:
        report["steps"].append({"name": name, "status": "passed", "evidence": evidence or {}})

    try:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale="en-GB",
            timezone_id="Asia/Dubai",
        )
        if os.getenv('EXECUTIVE_JS_CANDIDATE'):
            candidate_js = Path(os.environ['EXECUTIVE_JS_CANDIDATE']).read_text()
            context.route('**/static/executive.js*', lambda route: route.fulfill(content_type='text/javascript', body=candidate_js))
            report['candidate_javascript'] = os.environ['EXECUTIVE_JS_CANDIDATE']
        page = context.new_page()

        response = page.goto(urljoin(base_url, "plan"), wait_until="domcontentloaded")
        assert response and response.ok
        page.wait_for_url(re.compile(r"/login(?:\?.*)?$"))
        assert page.get_by_role("heading", name="Sign in to Kyvern").is_visible()
        palette = page.evaluate("""() => ({
          background: getComputedStyle(document.body).backgroundColor,
          button: getComputedStyle(document.querySelector('#submit')).backgroundColor,
          heading: getComputedStyle(document.querySelector('h1')).fontFamily
        })""")
        assert palette["background"] == "rgb(244, 242, 237)", palette
        assert palette["button"] == "rgb(126, 156, 139)", palette
        assert "Georgia" in palette["heading"], palette
        page.screenshot(path=output_dir / "01-sign-in.png", full_page=True)
        passed("Protected routes use the frozen customer sign-in palette", palette)

        if page.locator("#username").evaluate("node => node.tagName") == "SELECT":
            page.locator("#username").select_option("executive.tester")
        else:
            page.locator("#username").fill("executive.tester")
        page.locator("#password").fill("deliberately-wrong")
        page.get_by_role("button", name="Sign in").click()
        page.get_by_text("Invalid credentials for this role.").wait_for(timeout=10_000)
        passed("Invalid credentials are rejected without leaving sign-in")

        page.locator("#password").fill(password)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url(lambda url: "/login" not in url, timeout=15_000)
        page.goto(urljoin(base_url, "app?persona=ceo"), wait_until="domcontentloaded")
        session = context.request.get(urljoin(base_url, "ui/session")).json()
        expected_org = session["tenant_context"]["tenant_name"]
        assert expected_org and expected_org != "Executive workspace"
        started = monotonic()
        expect(page.locator("#driver-row")).to_contain_text("Revenue", timeout=5_000)
        expect(page.locator("#driver-row")).to_contain_text("Cash vs floor", timeout=5_000)
        first_content_seconds = monotonic() - started
        assert first_content_seconds < 5
        passed("The group index renders progressively within five seconds", {
            "first_meaningful_content_seconds": round(first_content_seconds, 3)
        })

        page.locator('#driver-row [data-driver-key="cash_vs_floor"]').wait_for(timeout=45_000)
        cards = page.locator("#driver-row [data-driver-key]")
        assert cards.count() == 4
        cash_card = page.locator('#driver-row [data-driver-key="cash_vs_floor"]')
        cash_text = cash_card.inner_text()
        assert "SAR 1.41B" in cash_text, cash_text
        assert "Source traced" in cash_text, cash_text
        cash_card.click()
        drill = page.locator("#driver-drill")
        expect(drill).to_contain_text("SAR 1.20B", timeout=10_000)
        expect(drill).to_contain_text("SAR 0.21B", timeout=10_000)
        expect(drill).to_contain_text("Group Treasury", timeout=10_000)
        assert "No approved budget has been supplied" not in drill.inner_text()
        page.screenshot(path=output_dir / "02-cash-and-scope.png", full_page=True)
        passed("Cash vs floor uses the approved floor, trajectory and accountable provider", {
            "current_cash": "SAR 1.41B", "approved_floor": "SAR 1.20B", "headroom": "SAR 0.21B"
        })

        page.locator("#hero-plan-coverage .granular-intent-summary").wait_for(timeout=20_000)
        coverage = page.locator("#hero-plan-coverage")
        expect(coverage).to_contain_text("FY target SAR 2.54B")
        expect(coverage).to_contain_text("3 reconciled granular stories")
        page.get_by_role("link", name="Open intent and granular drift").click()
        page.wait_for_url(re.compile(r"/plan(?:\?.*)?$"), timeout=10_000)
        page.locator("#vault-content:not([hidden])").wait_for(timeout=20_000)
        passed("The briefing link navigates into the Intent Vault")

        plan_options = page.locator("#plan-select option")
        assert plan_options.count() == 2, plan_options.all_inner_texts()
        option_text = plan_options.nth(1).inner_text()
        assert option_text.startswith("Tamween Pharma Distribution FY2026 revenue plan")
        assert "human-plan-" not in option_text
        page.locator("#plan-select").select_option(index=1)
        page.locator("#selected-plan:not([hidden])").wait_for(timeout=20_000)
        title = page.locator("#plan-title").inner_text()
        assert title.startswith("Tamween Pharma Distribution FY2026 revenue plan")
        metadata = page.locator("#plan-metadata").inner_text()
        assert "Ratified" in metadata and "FY2026" in metadata
        rows = page.locator("#plan-cells tbody tr")
        assert rows.count() == 576
        vault_text = page.locator("#selected-plan").inner_text()
        assert "item-a" not in vault_text.lower()
        assert "https://new.strategyos.live/:" not in vault_text
        assert "SHA-256" not in page.locator("#decomposition-lineage > summary").inner_text()
        page.screenshot(path=output_dir / "03-customer-intent.png", full_page=True)
        passed("The Vault exposes only the human-named FY2026 customer plan", {
            "visible_customer_plans": 1, "cells": rows.count(), "period": "FY2026"
        })

        catalog_response = context.request.get(
            urljoin(base_url, "api/intent/dimensional/catalog?limit=50")
        )
        assert catalog_response.ok, catalog_response.text()
        customer_summary = catalog_response.json()["plans"][0]
        analysis_id = customer_summary["latest_analysis"]["analysis_id"]
        page.goto(urljoin(base_url, "plan?analysis=" + analysis_id), wait_until="domcontentloaded")
        page.locator("#analysis-panel:not([hidden])").wait_for(timeout=30_000)
        stories = page.locator("#analysis-stories .demo-story-card")
        assert stories.count() == 3
        rollup = page.locator("#analysis-rollups tbody tr").first.inner_text()
        assert "1194000000.06" in rollup and "1267999999.96" in rollup, rollup
        assert "288 / 288" in rollup, rollup
        page.screenshot(path=output_dir / "04-granular-drift.png", full_page=True)
        passed("Three governed stories reconcile to complete H1 granular drift", {
            "story_count": 3, "coverage": "288 / 288"
        })

        page.get_by_role("link", name="Executive view").click()
        page.wait_for_url(re.compile(r"/app\?persona=ceo"), timeout=10_000)
        page.locator('#driver-row [data-driver-key="revenue"]').wait_for(timeout=45_000)
        assert page.locator("#persona-label").inner_text() == "Group CEO"
        expect(page.locator("#brand-org")).to_have_text(expected_org)
        page.goto(urljoin(base_url, "outreach"), wait_until="domcontentloaded")
        page.get_by_role("link", name="AI Assistants").click()
        page.wait_for_url(lambda url: "/app" in url and "persona=ceo" in url, timeout=10_000)
        page.locator('#driver-row [data-driver-key="revenue"]').wait_for(timeout=45_000)
        assert page.locator("#persona-label").inner_text() == "Group CEO"
        expect(page.locator("#brand-org")).to_have_text(expected_org)
        page.evaluate("localStorage.setItem('strategyos.executive.persona', 'group-cfo')")
        page.goto(urljoin(base_url, "plan"), wait_until="domcontentloaded")
        page.get_by_role("link", name="Executive view").click()
        page.wait_for_url(re.compile(r"/app(?:\?.*)?$"), timeout=10_000)
        page.locator('#driver-row [data-driver-key="revenue"]').wait_for(timeout=45_000)
        assert page.locator("#persona-label").inner_text() == "Group CEO"
        expect(page.locator("#brand-org")).to_have_text(expected_org)
        assert page.get_by_text("This persona workspace", exact=True).count() == 0
        assert page.evaluate("localStorage.getItem('strategyos.executive.persona')") == "ceo"
        passed("Executive persona survives navigation and stale browser state self-heals")

        page.get_by_role("tab", name="Diagnostics").click()
        context.route("**/assistant/chat", lambda route: route.abort())
        page.locator('#driver-row [data-driver-key="cash_vs_floor"]').click()
        page.locator("[data-kpi-ask-input]").fill("Do I need to intervene on cash headroom?")
        page.locator('#driver-row [data-driver-key="cash_vs_floor"]').click()
        expect(page.locator('[data-kpi-ask-input]')).to_have_value('Do I need to intervene on cash headroom?')
        page.locator("[data-kpi-ask-send]").click()
        page.locator("#assistant-drawer.is-open").wait_for(timeout=10_000)
        assistant_text = page.locator("#assistant-messages")
        expect(assistant_text).to_contain_text("Verified KPI context", timeout=15_000)
        expect(assistant_text).to_contain_text("1,410,000,000", timeout=15_000)
        expect(assistant_text).to_contain_text("1,200,000,000", timeout=15_000)
        expect(assistant_text).to_contain_text("Retry now", timeout=15_000)
        expect(assistant_text.locator('.assistant-message--assistant').last).not_to_contain_text('Source-backed fact')
        assert "loading" not in page.locator("[data-kpi-ask-send]").inner_text().lower()
        page.screenshot(path=output_dir / "05-assistant-service-error.png", full_page=True)
        passed("KPI drafts survive redraws; language outages return authorized KPI context with a retry")
        page.keyboard.press('Escape')

        page.set_viewport_size({"width": 390, "height": 844})
        assert page.locator("#driver-row").is_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
        page.screenshot(path=output_dir / "06-mobile-briefing.png", full_page=True)
        passed("The executive journey remains usable at a 390px viewport")
        report["status"] = "passed"
        report["summary"] = {
            "passed_steps": len(report["steps"]),
            "customer_plan_cells": 576,
            "granular_stories": 3,
            "viewport_widths": [1440, 390],
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
        if browser is not None:
            browser.close()
        playwright.stop()
        report["finished_at"] = datetime.now(UTC).isoformat()
        (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    print(json.dumps(report["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
