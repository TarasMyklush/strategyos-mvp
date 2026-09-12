"""Read a specific governed run through the browser; optional candidate assets are disclosed."""
import argparse
import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    base = os.environ['STRATEGYOS_PUBLIC_URL'].rstrip('/')
    users = dict(item.split('=', 1) for item in os.environ['STRATEGYOS_IDP_TEST_USERS'].split(',') if '=' in item)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    candidate = os.getenv('REVIEW_UI_CANDIDATE_ROOT')
    report = {'subject': base, 'run_id': args.run_id, 'candidate_static_root': candidate, 'steps': []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        try:
            if candidate:
                root = Path(candidate)
                for name in ('run-review.js', 'run-review-page.js', 'run-review.css'):
                    page.route('**/static/' + name + '*', lambda route, request, name=name:
                               route.fulfill(content_type='text/css' if name.endswith('.css') else 'text/javascript', body=(root / name).read_text()))
                def html(route):
                    try:
                        response = route.fetch(timeout=60000)
                    except Exception:
                        route.abort()
                        return
                    route.fulfill(response=response, status=200, content_type='text/html', body=(root / 'run-review.html').read_text())
                page.route(re.compile(re.escape(base) + r'/runs/review(?:\?|$)'), html)
            page.goto(base + '/login?manual=true')
            page.locator('#username').fill('reviewer.tester')
            page.locator('#password').fill(users['reviewer.tester'])
            page.get_by_role('button', name='Sign in', exact=True).click()
            page.wait_for_url(lambda url: '/login' not in url)
            page.goto(base + '/runs/review?review_run=' + args.run_id)
            panel = page.get_by_role('region', name='Selected run review', exact=True)
            expect(panel.locator('[data-selected-review-run]')).to_have_text(args.run_id, timeout=60000)
            expect(panel.get_by_text('Findings in this review', exact=True)).to_be_visible(timeout=60000)
            assert panel.locator('details').count() >= 2
            for detail in panel.locator('details').all()[:-2]:
                detail.locator('summary').click()
            visible = panel.inner_text()
            assert 'Quoted evidence' not in visible  # Unit-test fixtures must never leak into the hosted view.
            report['steps'].append({'name': 'Selected run and its own evidence load', 'status': 'passed', 'visible_text': visible})
            expect(page.locator('.review-panel')).to_have_count(0)
            report['steps'].append({'name': 'The selected review has no latest-run approval controls', 'status': 'passed'})
            panel.get_by_role('button', name='Refresh selected run', exact=True).click()
            expect(panel.get_by_text('Findings in this review', exact=True)).to_be_visible()
            report['steps'].append({'name': 'Refresh retains the selected run', 'status': 'passed'})
            page.screenshot(path=str(output / 'selected-review.png'), full_page=True)
            report['status'] = 'passed'
        except Exception as error:
            report['status'] = 'failed'
            report['error_type'] = type(error).__name__
            page.screenshot(path=str(output / 'failure.png'), full_page=True)
            raise
        finally:
            (output / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
            browser.close()
    print(json.dumps({'status': report['status'], 'steps': len(report['steps'])}))


if __name__ == '__main__':
    main()
