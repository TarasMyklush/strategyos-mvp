import asyncio, json, os
from pathlib import Path
from playwright.async_api import async_playwright, expect

out=Path(os.getenv('FORMULA_UI_OUTPUT_DIR','hosted-formula-scope-ui'))
out.mkdir(parents=True,exist_ok=True)
password=next(x.partition('=')[2] for x in os.environ['STRATEGYOS_IDP_TEST_USERS'].split(',') if x.partition('=')[0].strip()=='executive.tester')
base=os.environ['STRATEGYOS_PUBLIC_URL'].rstrip('/')

async def main():
    results=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':1100})
        if os.getenv('EXECUTIVE_JS_CANDIDATE'):
            js=Path(os.environ['EXECUTIVE_JS_CANDIDATE']).read_text()
            await page.route('**/static/executive.js*',lambda route:route.fulfill(content_type='text/javascript',body=js))
        await page.goto(base+'/login?manual=true')
        await page.locator('#username').fill('executive.tester')
        await page.locator('#password').fill(password)
        await page.get_by_role('button',name='Sign in',exact=True).click()
        await page.wait_for_url(lambda u:'/login' not in u)
        await page.goto(base+'/app?persona=ceo')
        await page.locator('#driver-row [data-driver-key="cash_vs_floor"]').wait_for(timeout=60000)
        await page.get_by_role('tab',name='Diagnostics').click()
        for key in ['cash_vs_floor','revenue','ebitda_margin','operating_cost']:
            await page.locator(f'#driver-row [data-driver-key="{key}"]').click()
            drill=page.locator('#driver-drill')
            await drill.get_by_role('button',name='Show the work',exact=True).click()
            await expect(drill.locator('.kpi-brief-audit')).to_have_attribute('open','')
            text=await drill.inner_text()
            assert 'Calculation method is not available' not in text,text
            if key!='operating_cost':
                assert 'accountable provider' in text.lower(),text
            assert 'chart scope' in text.lower(),text
            technical=drill.locator('.kpi-technical-provenance')
            await expect(technical).not_to_have_attribute('open','')
            assert 'ANALYSIS SNAPSHOT' not in text,text
            await technical.locator(':scope > summary').click()
            await expect(technical).to_contain_text('Analysis snapshot',ignore_case=True)
            await technical.locator(':scope > summary').click()
            if key=='operating_cost':
                assert 'headline scope' in text.lower() and 'Group H1 position shown above' in text,text
            await drill.screenshot(path=out/(key+'.png'))
            results.append({'case':key,'status':'passed','visible_text':text})
        await browser.close()
    (out/'report.json').write_text(json.dumps({'subject':base,'candidate_javascript':os.getenv('EXECUTIVE_JS_CANDIDATE'),'results':results},indent=2))
    print(json.dumps([{'case':x['case'],'status':x['status']} for x in results]))

asyncio.run(main())
