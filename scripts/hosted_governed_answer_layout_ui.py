"""Verify complete source facts and comparisons in desktop/mobile chat."""
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
                page.locator('#topbar-assistant-launch').click()
                page.locator('#assistant-input').fill('What are the top three cost drivers in Mizan E-Pharmacy, and which is above plan?')
                with page.expect_response(lambda r: '/assistant/chat' in r.url and r.request.method == 'POST', timeout=75000) as pending:
                    page.locator('#assistant-form').get_by_role('button', name='Send', exact=True).click()
                response = pending.value
                assert response.ok
                payload = response.json()
                answer = page.locator('#assistant-messages .assistant-message--assistant').last
                expect(answer.locator('.assistant-fact-table tbody tr')).to_have_count(6)
                expect(answer.locator('.assistant-governed-answer li')).to_have_count(3)
                visible = answer.inner_text()
                assert 'More context' not in visible
                for value in ('182,900,000', '174,200,000', '42,200,000', '39,300,000', '26,200,000', '25,300,000', '8,700,000', '2,900,000', '900,000'):
                    assert value in visible, value
                assert len(payload['fact_cells']) == 6
                assert all(c['claim_revision_id'] not in visible for c in payload['citations'])
                assert answer.locator('.assistant-fact-table th').nth(1).evaluate('(e)=>e.getBoundingClientRect().height') > 0
                page.screenshot(path=str(args.output_dir / f'chat-{width}.png'), full_page=True)
                report['checks'].append({'viewport_width': width, 'status': 'passed', 'facts': 6, 'comparisons': 3})
                context.close()
        finally:
            (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2))
            browser.close()
    print(json.dumps(report))


if __name__ == '__main__':
    main()
