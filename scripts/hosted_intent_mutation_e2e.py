#!/usr/bin/env python3
"""Human-style hosted acceptance for the governed Intent mutation lifecycle.

The test creates uniquely named synthetic records through the browser UI. The
records are intentionally append-only evidence of the test; it never modifies a
client record and never calls an external integration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit


def test_users(raw: str) -> dict[str, str]:
    users: dict[str, str] = {}
    for item in raw.split(","):
        username, separator, password = item.partition("=")
        if separator and username.strip() and password:
            users[username.strip()] = password
    return users


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("STRATEGYOS_PUBLIC_URL"))
    parser.add_argument("--output-dir", default="hosted-intent-mutation-e2e")
    args = parser.parse_args()
    if not args.base_url:
        parser.error("--base-url or STRATEGYOS_PUBLIC_URL is required")

    from playwright.sync_api import BrowserContext, Page, expect, sync_playwright

    base_url = args.base_url.rstrip("/") + "/"
    origin = f"{urlsplit(base_url).scheme}://{urlsplit(base_url).netloc}"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    users = test_users(os.environ.get("STRATEGYOS_IDP_TEST_USERS", ""))
    required_users = ("operator.tester", "tenant-admin.tester", "executive.tester")
    missing = [username for username in required_users if username not in users]
    if missing:
        raise RuntimeError("Required hosted test identities are unavailable: " + ", ".join(missing))

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    source_key = f"human-intent-{stamp}"
    structure_id = f"human-structure-{stamp}"
    plan_id = f"human-plan-{stamp}"
    actual_revision = f"human-history-{stamp}"
    advisor_id = f"human-advisor-{stamp}"
    report: dict[str, object] = {
        "subject": base_url,
        "started_at": datetime.now(UTC).isoformat(),
        "mode": "hosted Chromium mutation lifecycle with synthetic append-only records",
        "records": {
            "source_key": source_key,
            "structure_id": structure_id,
            "plan_id": plan_id,
            "actual_revision": actual_revision,
            "advisor_id": advisor_id,
        },
        "steps": [],
    }
    pages: list[Page] = []

    def pass_step(name: str, evidence: dict[str, object] | None = None) -> None:
        report["steps"].append({"name": name, "status": "passed", "evidence": evidence or {}})

    def login(browser, username: str) -> tuple[BrowserContext, Page, dict]:
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale="en-GB",
            timezone_id="Asia/Dubai",
            extra_http_headers={"X-StrategyOS-QA-Plan": plan_id},
        )
        page = context.new_page()
        pages.append(page)
        page.goto(urljoin(base_url, "login?manual=true"), wait_until="domcontentloaded")
        page.locator("#username").fill(username)
        page.locator("#password").fill(users[username])
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url(lambda url: "/login" not in url, timeout=15_000)
        session_response = context.request.get(urljoin(base_url, "ui/session"))
        assert session_response.ok, session_response.text()
        session = session_response.json()
        assert session["authenticated"] is True
        return context, page, session

    def api(context: BrowserContext, method: str, path: str, body: dict | None = None):
        options = {"headers": {"Origin": origin}}
        if body is not None:
            options["data"] = body
        return getattr(context.request, method)(urljoin(base_url, path.lstrip("/")), **options)

    def wait_message(page: Page, text: str) -> None:
        page.locator("#vault-message").filter(has_text=text).wait_for(timeout=20_000)

    def choose_plan(page: Page, version: int) -> None:
        page.locator("#plan-select option").filter(has_text=plan_id).first.wait_for(
            state="attached", timeout=20_000)
        page.locator("#plan-select").select_option(f"{plan_id}:{version}")
        page.locator("#selected-plan:not([hidden])").wait_for(timeout=20_000)
        assert f"{plan_id} · Version {version}" == page.locator("#plan-title").inner_text()

    try:
        with sync_playwright() as playwright, tempfile.TemporaryDirectory() as temp_dir:
            browser = playwright.chromium.launch(headless=True)
            operator_context, operator_page, operator_session = login(browser, "operator.tester")
            admin_context, admin_page, admin_session = login(browser, "tenant-admin.tester")
            executive_context, executive_page, executive_session = login(browser, "executive.tester")
            assert operator_session["role"] == "operator"
            assert admin_session["role"] == "tenant_admin"
            assert executive_session["role"] == "executive"
            tenant_id = operator_session["tenant_context"]["tenant_id"]
            assert admin_session["tenant_context"]["tenant_id"] == tenant_id
            assert executive_session["tenant_context"]["tenant_id"] == tenant_id
            pass_step("Three independent hosted identities authenticate in one tenant", {
                "roles": ["operator", "tenant_admin", "executive"], "tenant_id": tenant_id})

            temp = Path(temp_dir)
            evidence = temp / "evidence.csv"
            evidence.write_text(
                "business_unit,product,region,client,planned,actual,seasonal_factor\n"
                "GROUP,ITEM-A,NORTH,RETAIL,100,40,1\n"
                "GROUP,ITEM-A,SOUTH,INSTITUTION,100,160,1\n"
                "GROUP,ITEM-A,NORTH,HOSPITAL,0,40,1\n"
                "GROUP,ITEM-A,NORTH,PHARMACY,0,60,1\n"
                "GROUP,ITEM-A,SOUTH,HOSPITAL,0,40,2\n"
                "GROUP,ITEM-A,SOUTH,PHARMACY,0,60,1\n",
                encoding="utf-8",
            )
            source_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()

            # Governed source intake is a real prerequisite, so exercise it through the UI.
            operator_page.goto(urljoin(base_url, "sources/intake"), wait_until="domcontentloaded")
            operator_page.locator('input[name="files"]').set_input_files(str(evidence))
            operator_page.locator('input[name="storage_allowed"]').check()
            operator_page.locator("#source-form details summary").click()
            operator_page.locator('input[name="export_allowed"]').check()
            fields = {
                "source_key": source_key,
                "display_name": "Synthetic hosted Intent acceptance evidence",
                "governed_owner": "Kyvern QA",
                "authorization_basis": "Synthetic hosted mutation acceptance authorized for the branch preview.",
                "allowed_roles": "operator, tenant_operator, tenant_admin, reviewer, auditor, executive",
                "allowed_purposes": "operations, analysis, export, executive_briefing",
            }
            for name, value in fields.items():
                operator_page.locator(f'[name="{name}"]').fill(value)
            operator_page.locator('[name="origin_category"]').select_option("internal_system")
            operator_page.get_by_role("button", name="Stage source").click()
            operator_page.locator("#source-result:not([hidden])").wait_for(timeout=30_000)
            operator_page.locator("#source-status").filter(has_text="Source staged").wait_for()
            summary_values = operator_page.locator("#source-summary dd").all_inner_texts()
            source_pack_id = summary_values[-1]
            assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", source_pack_id)
            operator_page.get_by_role("button", name="Register selected file as evidence").click()
            operator_page.locator("#evidence-status").filter(has_text="Evidence registered").wait_for(timeout=20_000)
            operator_page.screenshot(path=output_dir / "01-source-registered.png", full_page=True)
            report["records"]["source_pack_id"] = source_pack_id
            report["records"]["source_sha256"] = source_hash
            pass_step("Operator stages and registers a governed synthetic source through the UI", {
                "source_pack_id": source_pack_id, "sha256": source_hash})

            # Configure the tenant's reusable structure through the guided console.
            operator_page.goto(urljoin(base_url, "plan"), wait_until="domcontentloaded")
            operator_page.locator("#vault-content:not([hidden])").wait_for(timeout=20_000)
            operator_page.locator("#structure-setup summary").click()
            operator_page.locator("#structure-id").fill(structure_id)
            operator_page.locator("#structure-company-en").fill("Synthetic Healthcare Distribution")
            operator_page.locator("#structure-company-ar").fill("توزيع الرعاية الصحية التجريبي")

            unit = operator_page.locator("#structure-business-units .structure-unit").first
            unit.locator('[data-field="key"]').fill("group")
            unit.locator('[data-field="label_en"]').fill("Group")
            unit.locator('[data-field="label_ar"]').fill("المجموعة")

            dimensions = {
                "product": [("item-a", "Item A", "الصنف أ", ""), ("item-b", "Item B", "الصنف ب", "")],
                "region": [("all-regions", "All regions", "كل المناطق", ""),
                           ("north", "North", "الشمال", "all-regions"),
                           ("south", "South", "الجنوب", "all-regions")],
                "client": [("retail", "Retail", "التجزئة", ""),
                           ("institution", "Institution", "مؤسسة", ""),
                           ("hospital", "Hospital", "مستشفى", ""),
                           ("pharmacy", "Pharmacy", "صيدلية", "")],
            }
            while operator_page.locator("#structure-dimensions .structure-dimension").count() < len(dimensions):
                operator_page.get_by_role("button", name="Add dimension").click()
            for index, (key, members) in enumerate(dimensions.items()):
                card = operator_page.locator("#structure-dimensions .structure-dimension").nth(index)
                card.locator(':scope > .vault-controls [data-field="key"]').fill(key)
                card.locator(':scope > .vault-controls [data-field="label_en"]').fill(key.title())
                card.locator(':scope > .vault-controls [data-field="label_ar"]').fill("بُعد " + key)
                while card.locator(".structure-member").count() < len(members):
                    card.get_by_role("button", name="Add member").click()
                for member_index, (member, label_en, label_ar, parent) in enumerate(members):
                    row = card.locator(".structure-member").nth(member_index)
                    row.locator('[data-field="key"]').fill(member)
                    row.locator('[data-field="parent"]').fill(parent)
                    row.locator('[data-field="label_en"]').fill(label_en)
                    row.locator('[data-field="label_ar"]').fill(label_ar)

            mappings = [
                ("business_unit", "business_unit", "", [("GROUP", "group")]),
                ("product", "dimension", "product", [("ITEM-A", "item-a"), ("ITEM-B", "item-b")]),
                ("region", "dimension", "region", [("ALL-REGIONS", "all-regions"), ("NORTH", "north"), ("SOUTH", "south")]),
                ("client", "dimension", "client", [("RETAIL", "retail"), ("INSTITUTION", "institution"),
                                                       ("HOSPITAL", "hospital"), ("PHARMACY", "pharmacy")]),
            ]
            while operator_page.locator("#structure-mappings .structure-mapping").count() < len(mappings):
                operator_page.get_by_role("button", name="Add source mapping").click()
            for index, (source_field, target_type, target_key, values) in enumerate(mappings):
                card = operator_page.locator("#structure-mappings .structure-mapping").nth(index)
                card.locator('[data-field="source_key"]').fill(source_key)
                card.locator('[data-field="source_field"]').fill(source_field)
                card.locator('[data-field="target_type"]').select_option(target_type)
                card.locator('[data-field="target_key"]').fill(target_key)
                while card.locator(".structure-mapping-value").count() < len(values):
                    card.get_by_role("button", name="Add value mapping").click()
                for value_index, (source_value, target) in enumerate(values):
                    row = card.locator(".structure-mapping-value").nth(value_index)
                    row.locator('[data-field="source_value"]').fill(source_value)
                    row.locator('[data-field="target"]').fill(target)
            operator_page.locator("#structure-form").get_by_role("button", name="Save structure version").click()
            operator_page.locator("#structure-status").filter(has_text="Structure saved").wait_for(timeout=20_000)
            operator_page.screenshot(path=output_dir / "02-structure-created.png", full_page=True)
            structure_response = api(operator_context, "get", f"api/intent/dimensional/advisor/structure-configurations/{structure_id}/versions/1")
            assert structure_response.ok, structure_response.text()
            structure = structure_response.json()
            assert structure["readiness"]["status"] == "ready"
            pass_step("Operator saves a complete source-bound organization structure through the UI", {
                "digest": structure["digest"], "dimensions": len(structure["payload"]["dimensions"])})

            admin_page.goto(urljoin(base_url, "plan"), wait_until="domcontentloaded")
            admin_page.locator("#vault-content:not([hidden])").wait_for(timeout=20_000)
            admin_page.locator("#structure-setup summary").click()
            admin_page.locator("#structure-select option").filter(has_text=structure_id).wait_for(
                state="attached", timeout=20_000)
            admin_page.locator("#structure-select").select_option(f"{structure_id}:1")
            admin_page.get_by_role("button", name="Open", exact=True).first.click()
            admin_page.locator("#structure-approve-form:not([hidden])").wait_for(timeout=20_000)
            admin_page.locator("#structure-review-note").fill(
                "Independently reviewed the company, dimensions, hierarchy and registered source mappings.")
            admin_page.get_by_role("button", name="Approve authoritative structure").click()
            admin_page.locator("#structure-status").filter(has_text="approved and authoritative").wait_for(timeout=20_000)
            admin_page.screenshot(path=output_dir / "03-structure-approved.png", full_page=True)
            approved_structure = api(admin_context, "get", f"api/intent/dimensional/advisor/structure-configurations/{structure_id}/versions/1")
            assert approved_structure.ok, approved_structure.text()
            assert approved_structure.json()["authoritative"] is True
            pass_step("A separate tenant administrator approves the authoritative structure through the UI")

            plan = {
                "schema_version": 1, "plan_id": plan_id, "company_id": tenant_id, "version": 1,
                "period": {"start": "2025-06-01", "end": "2025-06-30"},
                "effective_from": "2025-01-01", "effective_to": "2025-12-31", "status": "proposed",
                "business_unit": "group",
                "catalog_visibility": "quality_assurance",
                "structure": {"config_id": structure_id, "version": 1, "digest": structure["digest"]},
                "dimensions": {"product": ["item-a", "item-b"], "region": ["all-regions", "north", "south"],
                               "client": ["retail", "institution", "hospital", "pharmacy"]},
                "metrics": {"revenue": {"unit": "SAR", "aggregation": "sum", "direction": "higher_is_better",
                                           "planned_total": "200", "tolerance": "0"}},
                "cells": [
                    {"id": "regional", "metric": "revenue", "dimensions": {"product": "item-a", "region": "north", "client": "retail"},
                     "owner": "Regional Sales", "target": "100", "tolerance": "0",
                     "source": {"path": "evidence.csv", "locator": "row 2, planned", "sha256": source_hash}},
                    {"id": "institutional", "metric": "revenue", "dimensions": {"product": "item-a", "region": "south", "client": "institution"},
                     "owner": "Institutional Sales", "target": "100", "tolerance": "0",
                     "source": {"path": "evidence.csv", "locator": "row 3, planned", "sha256": source_hash}},
                ],
            }
            actuals = {
                "schema_version": 1, "company_id": tenant_id, "kind": "actual", "revision": actual_revision,
                "period": {"start": "2024-12-01", "end": "2024-12-31"}, "recorded_on": "2024-12-31",
                "observations": [
                    {"metric": "revenue", "dimensions": {"product": "item-a", "region": "north", "client": "hospital"},
                     "unit": "SAR", "value": "40", "source": {"path": "evidence.csv", "locator": "row 4, actual", "sha256": source_hash}},
                    {"metric": "revenue", "dimensions": {"product": "item-a", "region": "north", "client": "pharmacy"},
                     "unit": "SAR", "value": "60", "source": {"path": "evidence.csv", "locator": "row 5, actual", "sha256": source_hash}},
                ],
            }
            plan_file, actuals_file = temp / "plan.json", temp / "actuals.json"
            plan_file.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            actuals_file.write_text(json.dumps(actuals, ensure_ascii=False), encoding="utf-8")

            operator_page.goto(urljoin(base_url, "plan"), wait_until="domcontentloaded")
            operator_page.locator("#vault-content:not([hidden])").wait_for(timeout=20_000)
            operator_page.locator("#import-panel > details > summary").click()
            operator_page.locator("#import-panel > details > details > summary").click()
            operator_page.locator("#plan-pack").fill(source_pack_id)
            operator_page.locator("#plan-file").set_input_files(str(plan_file))
            operator_page.locator("#plan-import-form").get_by_role("button", name="Import proposal").click()
            wait_message(operator_page, "Plan proposal imported")
            assert "Proposed" in operator_page.locator("#plan-metadata").inner_text()
            operator_page.screenshot(path=output_dir / "04-plan-imported.png", full_page=True)
            imported_response = api(operator_context, "get", f"api/intent/dimensional/plans/{plan_id}/versions/1")
            assert imported_response.ok, imported_response.text()
            imported = imported_response.json()
            assert imported["governance_status"] == "proposed"
            pass_step("Operator imports a source-bound plan proposal through the UI", {
                "plan_digest": imported["digest"], "governance_status": "proposed"})

            admin_page.goto(urljoin(base_url, "plan"), wait_until="domcontentloaded")
            admin_page.locator("#vault-content:not([hidden])").wait_for(timeout=20_000)
            choose_plan(admin_page, 1)
            admin_page.locator("#ratifier-panel:not([hidden])").wait_for()
            admin_page.locator("#ratifier-panel summary").click()
            ratifier_subject = executive_session["subject"]
            admin_page.locator("#ratifier-subject").fill(ratifier_subject)
            admin_page.get_by_role("button", name="Load permission").click()
            admin_page.locator("#grant-form:not([hidden])").wait_for(timeout=20_000)
            admin_page.locator("#grant-enabled").check()
            admin_page.get_by_role("button", name="Save permission").click()
            wait_message(admin_page, "Ratification permission updated")
            admin_page.screenshot(path=output_dir / "05-ratifier-granted.png", full_page=True)
            pass_step("Tenant administrator grants plan-scoped ratification permission through the UI", {
                "ratifier_subject": ratifier_subject})

            denied = api(operator_context, "post", f"api/intent/dimensional/plans/{plan_id}/versions/1/ratify", {
                "expected_digest": imported["digest"], "note": "Operator must not ratify the proposal they imported."})
            assert denied.status == 403, (denied.status, denied.text())
            pass_step("Importer ratification is denied", {"http_status": denied.status})

            executive_page.goto(urljoin(base_url, "plan"), wait_until="domcontentloaded")
            executive_page.locator("#vault-content:not([hidden])").wait_for(timeout=20_000)
            choose_plan(executive_page, 1)
            executive_page.locator("#ratify-form:not([hidden])").wait_for()
            executive_page.locator("#review-note").fill(
                "Reviewed the targets, accountable owners, structure binding and supporting source evidence.")
            executive_page.locator("#reviewed").check()
            executive_page.get_by_role("button", name="Ratify reviewed version").click()
            wait_message(executive_page, "This plan version has been ratified")
            assert "Ratified" in executive_page.locator("#plan-metadata").inner_text()
            executive_page.screenshot(path=output_dir / "06-plan-ratified.png", full_page=True)
            ratified = api(executive_context, "get", f"api/intent/dimensional/plans/{plan_id}/versions/1").json()
            assert ratified["governance_status"] == "ratified"
            assert ratified["ratification"]["approved_by"] == ratifier_subject
            pass_step("Independently authorized executive ratifies the reviewed plan through the UI", {
                "approved_by": ratified["ratification"]["approved_by"]})

            operator_page.goto(urljoin(base_url, "plan"), wait_until="domcontentloaded")
            operator_page.locator("#vault-content:not([hidden])").wait_for(timeout=20_000)
            choose_plan(operator_page, 1)
            operator_page.locator("#import-panel > details > summary").click()
            operator_page.locator("#import-panel > details > details > summary").click()
            operator_page.locator("#actual-pack").fill(source_pack_id)
            operator_page.locator("#actual-file").set_input_files(str(actuals_file))
            operator_page.locator("#actual-import-form").get_by_role("button", name="Import actuals").click()
            wait_message(operator_page, "Actual snapshot imported")
            assert operator_page.locator("#actual-select").input_value() == actual_revision
            operator_page.screenshot(path=output_dir / "07-actuals-imported.png", full_page=True)
            pass_step("Operator imports completed historical actuals through the UI", {"revision": actual_revision})

            operator_page.locator("#advisor-form:not([hidden])").wait_for(timeout=20_000)
            advisor_fields = {
                "#advisor-id": advisor_id,
                "#advisor-sponsor": "Chief Executive",
                "#advisor-objective": "Expose client-level revenue drift against the exact plan approved by the board.",
                "#advisor-client-en": "Synthetic Healthcare",
                "#advisor-client-ar": "الرعاية الصحية التجريبية",
                "#advisor-title-en": "Revenue performance review",
                "#advisor-title-ar": "مراجعة أداء الإيرادات",
                "#advisor-metric-en": "Revenue",
                "#advisor-metric-ar": "الإيرادات",
                "#advisor-dimension-en": "Client",
                "#advisor-dimension-ar": "العميل",
            }
            for selector, value in advisor_fields.items():
                operator_page.locator(selector).fill(value)
            operator_page.locator("#advisor-cell").select_option("regional")
            operator_page.locator("#advisor-dimension").select_option("client")
            operator_page.locator("#advisor-actual").select_option(actual_revision)
            operator_page.get_by_role("button", name="Load source-bound mappings").click()
            operator_page.locator("#advisor-save:not([hidden])").wait_for(timeout=20_000)
            allocation_rows = operator_page.locator("#advisor-allocations tbody tr")
            assert allocation_rows.count() == 2
            for index in range(allocation_rows.count()):
                row = allocation_rows.nth(index)
                member = row.locator("td").nth(1).inner_text()
                row.locator('[data-field="adjustment_percent"]').fill("50" if member == "hospital" else "0")
                row.locator('[data-field="owner"]').fill(member.title() + " Channel Lead")
                row.locator('[data-field="tolerance"]').fill("2")
                row.locator('[data-field="label_en"]').fill(member.title())
                row.locator('[data-field="label_ar"]').fill("مستشفى" if member == "hospital" else "صيدلية")
            for index in range(operator_page.locator("#advisor-labels tbody tr").count()):
                row = operator_page.locator("#advisor-labels tbody tr").nth(index)
                term = row.locator("td").first.inner_text()
                row.locator('[data-field="label_en"]').fill(term.replace("-", " ").title())
                row.locator('[data-field="label_ar"]').fill("تسمية " + term)
            operator_page.locator("#advisor-save").click()
            operator_page.locator("#advisor-review:not([hidden])").wait_for(timeout=20_000)
            operator_page.locator("#advisor-readiness").filter(has_text="saved and ready").wait_for()
            operator_page.screenshot(path=output_dir / "08-advisor-configured.png", full_page=True)
            configured_response = api(operator_context, "get", f"api/intent/dimensional/advisor/configurations/{advisor_id}/versions/1")
            assert configured_response.ok, configured_response.text()
            configured = configured_response.json()
            assert configured["readiness"]["status"] == "ready"
            assert configured["approval"] is None
            assert configured["source_bindings"]["plan"]["source_pack_id"] == source_pack_id
            pass_step("Operator saves a complete source-bound bilingual advisor configuration through the UI", {
                "config_digest": configured["digest"], "allocation_count": len(configured["payload"]["allocations"])})

            denied = api(operator_context, "post", f"api/intent/dimensional/advisor/configurations/{advisor_id}/versions/1/approve", {
                "expected_digest": configured["digest"], "note": "The creator must not approve their own advisor configuration."})
            assert denied.status == 403, (denied.status, denied.text())
            pass_step("Advisor configuration creator approval is denied", {"http_status": denied.status})

            executive_page.goto(urljoin(base_url, "plan"), wait_until="domcontentloaded")
            executive_page.locator("#vault-content:not([hidden])").wait_for(timeout=20_000)
            executive_page.locator("#advisor-select option").filter(has_text=advisor_id).wait_for(
                state="attached", timeout=20_000)
            executive_page.locator("#advisor-select").select_option(f"{advisor_id}:1")
            executive_page.locator("#advisor-load-saved").click()
            executive_page.locator("#advisor-approve-form:not([hidden])").wait_for(timeout=20_000)
            executive_page.locator("#advisor-review-note").fill(
                "Independently reviewed every mapping, owner, adjustment, evidence binding and bilingual label.")
            executive_page.get_by_role("button", name="Approve configuration").click()
            executive_page.locator("#advisor-review-metadata").filter(has_text="Approved by").wait_for(timeout=20_000)
            executive_page.screenshot(path=output_dir / "09-advisor-approved.png", full_page=True)
            approved_config = api(executive_context, "get", f"api/intent/dimensional/advisor/configurations/{advisor_id}/versions/1").json()
            assert approved_config["approval"]["approved_by"] == ratifier_subject
            pass_step("A separate executive approves the advisor configuration through the UI")

            operator_page.goto(urljoin(base_url, "plan"), wait_until="domcontentloaded")
            operator_page.locator("#vault-content:not([hidden])").wait_for(timeout=20_000)
            operator_page.locator("#advisor-select option").filter(has_text=advisor_id).wait_for(
                state="attached", timeout=20_000)
            operator_page.locator("#advisor-select").select_option(f"{advisor_id}:1")
            operator_page.locator("#advisor-load-saved").click()
            operator_page.locator("#advisor-publish:not([hidden])").wait_for(timeout=20_000)
            operator_page.locator("#advisor-use-template:not([hidden])").wait_for()
            operator_page.locator("#advisor-use-template").click()
            expect(operator_page.locator("#advisor-readiness")).to_contain_text(
                "board template registered", timeout=20_000)
            operator_page.locator("#advisor-publish").click()
            expect(operator_page.locator("#advisor-readiness")).to_contain_text(
                "Published as plan proposal v2", timeout=20_000)
            operator_page.screenshot(path=output_dir / "10-advisor-published.png", full_page=True)
            published_config = api(operator_context, "get", f"api/intent/dimensional/advisor/configurations/{advisor_id}/versions/1").json()
            assert published_config["publication"]["plan_version"] == 2
            proposal_v2 = api(operator_context, "get", f"api/intent/dimensional/plans/{plan_id}/versions/2").json()
            assert proposal_v2["governance_status"] == "proposed"
            assert proposal_v2["payload"]["derivation"]["engine_version"] == "history-adjusted-allocation.v1"
            pass_step("Operator registers the bilingual board template and publishes the advisor plan proposal through the UI", {
                "published_plan_version": 2, "engine_version": proposal_v2["payload"]["derivation"]["engine_version"]})

            executive_page.goto(urljoin(base_url, "plan"), wait_until="domcontentloaded")
            executive_page.locator("#vault-content:not([hidden])").wait_for(timeout=20_000)
            choose_plan(executive_page, 2)
            executive_page.locator("#review-note").fill(
                "Reviewed the advisor allocations, adjustments, exact reconciliation, owners and evidence lineage.")
            executive_page.locator("#reviewed").check()
            executive_page.get_by_role("button", name="Ratify reviewed version").click()
            wait_message(executive_page, "This plan version has been ratified")
            final_plan = api(executive_context, "get", f"api/intent/dimensional/plans/{plan_id}/versions/2").json()
            assert final_plan["governance_status"] == "ratified"
            assert sum(float(cell["target"]) for cell in final_plan["payload"]["cells"] if cell["id"].startswith("regional-")) == 100.0
            executive_page.screenshot(path=output_dir / "11-advisor-plan-ratified.png", full_page=True)
            pass_step("Executive ratifies the advisor-generated plan version through the UI", {
                "version": 2, "governance_status": "ratified", "decomposed_parent_total": "100.00"})

            seasonal_actuals = json.loads(json.dumps(actuals))
            seasonal_actuals['revision'] = actual_revision + '-seasonal'
            for index, observation in enumerate(seasonal_actuals['observations']):
                observation['dimensions']['region'] = 'south'
                observation['source']['locator'] = f'row {index+6}, actual'
            seasonal_file = temp/'seasonal-history.json'
            seasonal_file.write_text(json.dumps(seasonal_actuals))
            operator_page.goto(urljoin(base_url,'plan'),wait_until='domcontentloaded')
            operator_page.locator('#vault-content:not([hidden])').wait_for(timeout=20000)
            operator_page.locator('#import-panel > details > summary').click()
            operator_page.locator('#import-panel > details > details > summary').click()
            operator_page.locator('#actual-pack').fill(source_pack_id)
            operator_page.locator('#actual-file').set_input_files(seasonal_file)
            operator_page.locator('#actual-import-form button[type="submit"]').click()
            wait_message(operator_page,'Actual snapshot imported')
            pass_step('Operator imports the separately scoped seasonal historical input through the UI')
            choose_plan(operator_page,2)
            operator_page.locator('#decomposition-cell').select_option('institutional')
            operator_page.locator('#decomposition-dimension').select_option('client')
            operator_page.locator('#history-actual').select_option(seasonal_actuals['revision'])
            operator_page.locator('#history-load').click()
            expect(operator_page.locator('#history-create')).to_be_visible(timeout=20000)
            operator_page.locator('#seasonality-enabled').check()
            operator_page.locator('#seasonality-pack').fill(source_pack_id)
            operator_page.locator('#seasonality-path').fill('evidence.csv')
            operator_page.locator('#seasonality-sha').fill(source_hash)
            rows=operator_page.locator('#history-allocations tbody tr')
            for index,member in enumerate(['hospital','pharmacy']):
                rows.nth(index).locator('[data-field="cell_id"]').fill('seasonal-'+member)
                rows.nth(index).locator('[data-field="seasonality_factor"]').fill('2' if index==0 else '1')
                rows.nth(index).locator('[data-field="seasonality_locator"]').fill(f'row {index+6}, seasonal_factor')
            operator_page.locator('#history-create').click()
            wait_message(operator_page,'History-based proposal created as version 3')
            proposed=api(operator_context,'get',f'api/intent/dimensional/plans/{plan_id}/versions/3').json()
            assert proposed['governance_status']=='proposed'
            assert proposed['payload']['derivation']['engine_version']=='history-seasonal-allocation.v1'
            targets={c['id']:c['target'] for c in proposed['payload']['cells']}
            assert targets['seasonal-hospital']=='57.14' and targets['seasonal-pharmacy']=='42.86'
            operator_page.screenshot(path=output_dir/'12-seasonal-proposal.png',full_page=True)
            pass_step('Operator applies evidenced seasonal factors separately from history and adjustments through the UI',{'targets':targets})
            executive_page.goto(urljoin(base_url,'plan'),wait_until='domcontentloaded')
            executive_page.locator('#vault-content:not([hidden])').wait_for(timeout=20000)
            choose_plan(executive_page,3)
            executive_page.locator('#decomposition-lineage > summary').click()
            expect(executive_page.locator('#decomposition-allocations')).to_contain_text('Seasonal factor')
            executive_page.locator('#review-note').fill('Reviewed the seasonal source factors, historical inputs, separate adjustments and exact target reconciliation.')
            executive_page.locator('#reviewed').check()
            executive_page.get_by_role('button',name='Ratify reviewed version').click()
            wait_message(executive_page,'This plan version has been ratified')
            with executive_page.expect_download() as download:
                executive_page.get_by_role('link',name='Seasonal evidence',exact=False).first.click()
            assert hashlib.sha256(Path(download.value.path()).read_bytes()).hexdigest()==source_hash
            pass_step('Executive independently ratifies the seasonal proposal and opens its exact evidence through the UI',{'version':3})

            report["status"] = "passed"
            report["finished_at"] = datetime.now(UTC).isoformat()
            report["summary"] = {
                "passed_steps": len(report["steps"]),
                "browser_personas": 3,
                "ui_mutations": 13,
                "negative_authority_checks": 2,
                "external_integrations_called": 0,
            }
            browser.close()
    except Exception as exc:
        for index, page in enumerate(pages, start=1):
            try:
                page.screenshot(path=output_dir / f"failure-{index}.png", full_page=True)
            except Exception:
                pass
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["finished_at"] = datetime.now(UTC).isoformat()
        (output_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        raise

    (output_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
