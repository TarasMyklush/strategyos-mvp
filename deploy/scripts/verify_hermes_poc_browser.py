"""Live POC UI acceptance: authenticated chat, semantic lookup, labels and citations.

Set STRATEGYOS_IDP_TEST_USERS through the existing secure test-user setup.
HERMES_ONLY optionally narrows the comma-separated case names for a retest.
This creates test conversations in the selected executive tester account.
"""
import json, os, time
from pathlib import Path
from playwright.sync_api import sync_playwright

base = os.environ.get('HERMES_BASE_URL', 'https://new.strategyos.live').rstrip('/')
username = 'executive.tester'
password = next(item.partition('=')[2] for item in os.environ['STRATEGYOS_IDP_TEST_USERS'].split(',') if item.partition('=')[0].strip() == username)
out = Path(os.environ.get('HERMES_UI_OUTPUT_DIR', 'artifacts/hermes-ui-2026-09-10'))
out.mkdir(parents=True, exist_ok=True)
cases = [
    ('ebitda-typo', 'my number for ebidta??', 'fact', '617000000.00'),
    ('gdp', 'whats gdp?', 'general', 'gross domestic product'),
    ('kyiv', 'what is the capital of ukraine?', 'general', 'kyiv'),
    ('ebitda-plain', 'How much did we make before interest, taxes, depreciation and amortisation?', 'fact', '617000000.00'),
    ('ebitda-plan', 'Show actual and budgeted EBITDA for January to June 2026', 'comparison', '608100000.00'),
    ('ebitda-arabic', 'ما قيمة الأرباح قبل الفوائد والضرائب والإهلاك والاستهلاك لدينا؟', 'fact', '617000000.00'),
    ('missing-period', 'What is our EBITDA for 2029?', 'missing', ''),
    ('greeting', 'hello', 'general', ''),
    ('false-number', 'Someone told me our EBITDA was SAR 999 million. What do the records actually say?', 'fact', '617000000.00'),
    ('service-error', 'UI test: provider unavailable', 'service_error', ''),
]
if os.environ.get('HERMES_ONLY'):
    cases = [item for item in cases if item[0] in os.environ['HERMES_ONLY'].split(',')]
results=[]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000},locale='en-GB',timezone_id='Asia/Dubai')
    page=context.new_page()
    page.goto(base+'/app?persona=ceo',wait_until='domcontentloaded')
    page.wait_for_url(lambda u:'/login' in u,timeout=15000)
    field=page.locator('#username')
    if field.evaluate('n => n.tagName') == 'SELECT':field.select_option(username)
    else:field.fill(username)
    page.locator('#password').fill(password)
    page.get_by_role('button',name='Sign in').click()
    page.wait_for_url(lambda u:'/login' not in u,timeout=20000)
    page.goto(base+'/app?persona=ceo',wait_until='domcontentloaded')
    page.locator('#driver-row [data-driver-key="revenue"]').wait_for(timeout=60000)
    page.locator('#topbar-assistant-launch').click()
    page.locator('#assistant-drawer.is-open').wait_for(timeout=10000)
    for slug,question,kind,expected in cases:
        item={'case':slug,'question':question}
        try:
            page.get_by_role('button',name='Start a new conversation').click()
            page.locator('#assistant-input').fill(question)
            if kind == 'service_error':
                # A browser-local fault injection: never disrupt the shared provider.
                page.route('**/assistant/chat', lambda route: route.fulfill(status=200, content_type='application/json',
                    body=json.dumps({'status':'error','answer_status':'service_error','matched':False,
                        'answer':'I could not finish reading the evidence because the language service failed. Please retry.',
                        'determinism_tier':'service_error','citations':[],
                        'llm_status':{'provider':'codex_cli','model':'gpt-5.6-sol'}})))
            started=time.monotonic()
            with page.expect_response(lambda r:'/assistant/chat' in r.url,timeout=75000) as pending:
                page.locator('#assistant-form').get_by_role('button',name='Send').click()
            response=pending.value
            item['seconds']=round(time.monotonic()-started,1)
            assert response.ok, f'HTTP {response.status}: {response.text()[:600]}'
            payload=response.json()
            (out/(slug+'.json')).write_text(json.dumps(payload,ensure_ascii=False,indent=2))
            page.wait_for_function("!document.querySelector('#assistant-messages .assistant-message--pending')",timeout=10000)
            rendered=page.locator('#assistant-messages .assistant-message--assistant').last
            rendered.wait_for(timeout=10000)
            visible=rendered.inner_text()
            item.update(answer=payload.get('answer'),tier=payload.get('determinism_tier'),retrieval=payload.get('retrieval'))
            assert 'Checking the board data' not in visible and 'did not return within' not in visible
            if kind=='service_error':
                assert 'Service unavailable' in visible and 'Source-backed fact' not in visible, visible
                assert rendered.get_by_role('button',name='Retry now',exact=True).is_visible(), visible
                assert not payload.get('citations')
                item['verification']='browser-local fault injection'
                page.unroute('**/assistant/chat')
            elif kind=='general':
                assert payload.get('assistant_scope')=='general',payload.get('assistant_scope')
                assert 'General AI answer' in visible and 'Source-backed fact' not in visible
                assert not payload.get('citations')
                assert expected in visible.casefold(),visible
            elif kind=='missing':
                assert payload.get('matched') is False,visible
                assert payload.get('determinism_tier')=='needs_evidence',visible
                assert 'Evidence unavailable' in visible and 'Source-backed fact' not in visible
                assert not payload.get('citations'),visible
            else:
                facts=payload.get('fact_cells') or []
                assert any(f['metric_key']=='ceo.ebitda' and f['value']==expected for f in facts),visible
                if kind=='comparison':assert any(f['metric_key']=='ceo.ebitda' and f['value']=='617000000.00' for f in facts),visible
                assert 'Source-backed fact' in visible and 'General AI answer' not in visible
                assert payload['matched'] is True and payload['citations']
                assert all(c.get('resolved') and c.get('claim_revision_id') for c in payload['citations'])
                assert payload['retrieval']['facts_considered'] > 80
                assert payload['retrieval']['complete'] is True
                if slug=='ebitda-typo':
                    rendered.locator('.assistant-citation-list > summary').click()
                    with context.expect_page(timeout=15000) as popup:
                        rendered.get_by_role('link',name='Open approved fact').first.click()
                    evidence=popup.value
                    evidence.wait_for_load_state('domcontentloaded')
                    evidence_text=evidence.locator('body').inner_text()
                    item['citation_url']=evidence.url
                    (out/'ebitda-citation.txt').write_text(evidence_text)
                    assert '64327cbb-e7cb-42d7-b6c7-5e915dafe2fa' in evidence_text,evidence_text[:1000]
                    from decimal import Decimal
                    citation_record = json.loads(evidence_text)['record']
                    assert citation_record['metric_key'] == 'ceo.ebitda'
                    assert Decimal(str(citation_record['value'])) * Decimal(str(citation_record['scale'])) == Decimal('617000000')
                    evidence.close()
            status=payload.get('llm_status') or {}
            assert status.get('provider')=='codex_cli' and status.get('model')=='gpt-5.6-sol',status
            item['status']='passed'
        except Exception as error:
            item.update(status='failed',error=str(error)[:1500])
        page.locator('#assistant-drawer').screenshot(path=str(out/(slug+'.png')))
        results.append(item)
        print(json.dumps(item,ensure_ascii=False),flush=True)
    browser.close()
(out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
assert all(item['status']=='passed' for item in results), f'UI acceptance failures; inspect {out / "results.json"}'
