"""Verify complete source facts and comparisons in desktop/mobile chat."""
from decimal import Decimal
import argparse
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    base = os.environ['STRATEGYOS_PUBLIC_URL'].rstrip('/')
    users = dict(item.split('=', 1) for item in os.environ['STRATEGYOS_IDP_TEST_USERS'].split(',') if '=' in item)
    report = {'subject': base, 'mode': 'deployed headless browser; no response or asset overrides', 'checks': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for width in (1440, 390):
                context = browser.new_context(viewport={'width': width, 'height': 1100})
                page = context.new_page()
                page.goto(base + '/login?manual=true')
                page.locator('#username').fill('executive.tester')
                page.locator('#password').fill(users['executive.tester'])
                page.get_by_role('button', name='Sign in', exact=True).click()
                page.wait_for_url(lambda url: '/login' not in url)
                page.goto(base + '/app?persona=ceo', wait_until='domcontentloaded')
                page.locator('#driver-row [data-driver-key="revenue"]').wait_for(timeout=60000)
                launcher = page.locator('#topbar-assistant-launch')
                (launcher if launcher.is_visible() else page.locator('#chat-launcher')).click()
                page.locator('#assistant-input').fill('What are the top three cost drivers in Mizan E-Pharmacy, and which is above plan?')
                with page.expect_response(lambda r: '/assistant/chat' in r.url and r.request.method == 'POST', timeout=75000) as pending:
                    page.locator('#assistant-form').get_by_role('button', name='Send', exact=True).click()
                response = pending.value
                assert response.ok
                payload = response.json()
                answer = page.locator('#assistant-messages .assistant-message--assistant').last
                answer.wait_for()
                (args.output_dir / f'payload-{width}.json').write_text(json.dumps(payload, indent=2))
                (args.output_dir / f'answer-{width}.txt').write_text(answer.inner_text())
                page.screenshot(path=str(args.output_dir / f'chat-{width}.png'), full_page=True)
                facts = payload['fact_cells']
                expect(answer.locator('.assistant-fact-table tbody tr')).to_have_count(len(facts))
                expected_actuals = {'COGS':'182900000', 'LOGISTICS':'42200000', 'PAYROLL':'26200000',
                    'IT & DIGITAL':'13700000', 'MARKETING':'10300000', 'RENT & FACILITIES':'4200000',
                    'UTILITIES & ENERGY':'2200000', 'PROFESSIONAL SERVICES':'1700000',
                    'OTHER OPEX':'1400000', 'INSURANCE':'1100000'}
                expected_plans = {'COGS':'174200000', 'LOGISTICS':'39300000', 'PAYROLL':'25300000'}
                seen = set()
                for fact in facts:
                    assert fact['business_unit'] == 'Mizan E-Pharmacy'
                    assert fact['period']['start'] == '2026-01-01' and fact['period']['end'] == '2026-06-30'
                    assert fact['unit'] == 'SAR'
                    key = (fact['display_name'], fact['claim_kind'])
                    assert key not in seen
                    seen.add(key)
                    values = expected_actuals if fact['claim_kind'] == 'actual' else expected_plans
                    assert Decimal(fact['value']) == Decimal(values[fact['display_name']])
                assert {(label, kind) for label in expected_plans for kind in ('actual','plan')} <= seen
                expect(answer.locator('.assistant-governed-answer li')).to_have_count(3)
                visible = answer.inner_text()
                assert 'More context' not in visible
                for value in ('182,900,000', '174,200,000', '42,200,000', '39,300,000', '26,200,000', '25,300,000', '8,700,000', '2,900,000', '900,000'):
                    assert value in visible, value
                assert len(payload['citations']) == len(facts)
                assert all(c['claim_revision_id'] not in visible for c in payload['citations'])
                assert answer.locator('.assistant-fact-table th').nth(1).evaluate('(e)=>e.getBoundingClientRect().height') > 0
                page.screenshot(path=str(args.output_dir / f'chat-{width}.png'), full_page=True)
                report['checks'].append({'viewport_width': width, 'status': 'passed', 'facts': len(facts), 'comparisons': 3})
                context.close()
        finally:
            (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2))
            browser.close()
    print(json.dumps(report))


if __name__ == '__main__':
    main()
