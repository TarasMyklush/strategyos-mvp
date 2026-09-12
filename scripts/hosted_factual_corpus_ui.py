"""Collect the fixed factual corpus through the real chat UI for source review.

Collection is not correctness grading. Never infer a factual pass from HTTP 200,
the assistant's own matched flag, or a citation's self-reported resolved flag.
"""
import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--corpus', type=Path, default=Path(__file__).parents[1] / 'docs/assessment/evidence/p0-live-factual-2026-09-09.json')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--release', required=True, help='Deployment SHA, independently attested by the caller before and after the run')
    parser.add_argument('--limit', type=int, help='Harness preflight only; never a full factual gate')
    args = parser.parse_args()
    base = os.environ['STRATEGYOS_PUBLIC_URL'].rstrip('/')
    password = next(x.partition('=')[2] for x in os.environ['STRATEGYOS_IDP_TEST_USERS'].split(',') if x.partition('=')[0].strip() == 'executive.tester')
    corpus = json.loads(args.corpus.read_text())['responses']
    assert len(corpus) == len({x['id'] for x in corpus}) == 50
    assert len({x['theme'] for x in corpus}) == 18
    if args.limit:
        corpus = corpus[:args.limit]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {'subject': base, 'declared_release': args.release, 'started_at': datetime.now(UTC).isoformat(),
              'mode': 'headless UI collection; independent source grading required',
              'full_corpus': args.limit is None, 'factual_gate_passed': False, 'correct_count': None, 'items': []}

    def save():
        (args.output_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1100})
        page = context.new_page()
        page.goto(base + '/login?manual=true')
        page.locator('#username').fill('executive.tester')
        page.locator('#password').fill(password)
        page.get_by_role('button', name='Sign in', exact=True).click()
        page.wait_for_url(lambda u: '/login' not in u)
        page.goto(base + '/app?persona=ceo', wait_until='domcontentloaded')
        page.locator('#driver-row [data-driver-key="revenue"]').wait_for(timeout=60000)
        page.locator('#topbar-assistant-launch').click()
        page.locator('#assistant-drawer.is-open').wait_for()
        for source in corpus:
            item = {k: source[k] for k in ('id', 'theme', 'question')}
            item['grading_status'] = 'ungraded'
            started = monotonic()
            try:
                page.get_by_role('button', name='Start a new conversation').click()
                page.locator('#assistant-input').fill(item['question'])
                with page.expect_response(lambda r: '/assistant/chat' in r.url and r.request.method == 'POST', timeout=75000) as pending:
                    page.locator('#assistant-form').get_by_role('button', name='Send', exact=True).click()
                response = pending.value
                item['http_status'] = response.status
                item['payload'] = response.json()
                page.locator('#assistant-messages .assistant-message--pending').wait_for(state='hidden', timeout=15000)
                answer = page.locator('#assistant-messages .assistant-message--assistant').last
                item['visible_answer'] = answer.inner_text()
                item['citation_checks'] = []
                for citation in item['payload'].get('citations', []):
                    href = citation.get('href') or ''
                    url = urljoin(base + '/', href)
                    check = {'href': href, 'claim_revision_id': citation.get('claim_revision_id'), 'verified': False}
                    if href and urlsplit(url).netloc == urlsplit(base).netloc and urlsplit(url).scheme == 'https':
                        evidence = context.request.get(url, timeout=20000)
                        check['http_status'] = evidence.status
                        if evidence.ok and 'application/json' in evidence.headers.get('content-type', ''):
                            data = evidence.json()
                            record = data.get('record') or {}
                            if citation.get('claim_revision_id'):
                                check['verified'] = record.get('claim_revision_id') == citation['claim_revision_id']
                                check['record'] = record
                            else:
                                check['reason'] = 'Non-claim evidence requires separate source review.'
                    item['citation_checks'].append(check)
                if answer.locator('.assistant-citation-list > summary').count():
                    answer.locator('.assistant-citation-list > summary').click()
                    links = answer.get_by_role('link', name='Open approved fact')
                    if links.count():
                        with context.expect_page(timeout=15000) as popup:
                            links.first.click()
                        evidence_page = popup.value
                        evidence_page.wait_for_load_state('domcontentloaded')
                        item['first_ui_evidence_text'] = evidence_page.locator('body').inner_text()
                        evidence_page.close()
                answer.screenshot(path=args.output_dir / (item['id'] + '.png'))
                item['collection_status'] = 'collected'
            except Exception as error:
                item['collection_status'] = 'failed'
                # Retain the error type without risking request headers in a
                # browser transport exception. Response bodies are saved above.
                item['error_type'] = type(error).__name__
                page.screenshot(path=args.output_dir / (item['id'] + '-failure.png'))
                cancel = page.get_by_role('button', name='Cancel request', exact=True)
                if cancel.is_visible():
                    cancel.click()
            item['seconds'] = round(monotonic() - started, 2)
            report['items'].append(item)
            save()
            print(json.dumps({'id': item['id'], 'collection_status': item['collection_status'], 'seconds': item['seconds']}), flush=True)
        browser.close()
    report['finished_at'] = datetime.now(UTC).isoformat()
    report['collected_count'] = sum(x['collection_status'] == 'collected' for x in report['items'])
    save()


if __name__ == '__main__':
    main()
