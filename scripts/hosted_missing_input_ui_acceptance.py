import asyncio,json,os,time
from pathlib import Path
from playwright.async_api import async_playwright,expect

out=Path(os.getenv('MISSING_INPUT_UI_OUTPUT_DIR','hosted-missing-input-ui'))
out.mkdir(parents=True,exist_ok=True)
base=os.environ['STRATEGYOS_PUBLIC_URL'].rstrip('/')
password=next(x.partition('=')[2] for x in os.environ['STRATEGYOS_IDP_TEST_USERS'].split(',') if x.partition('=')[0]=='executive.tester')

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':1100})
        if os.getenv('EXECUTIVE_JS_CANDIDATE'):
            js=Path(os.environ['EXECUTIVE_JS_CANDIDATE']).read_text()
            await page.route('**/static/executive.js*',lambda route:route.fulfill(content_type='text/javascript',body=js))
        await page.goto(base+'/login?manual=true')
        await page.locator('#username').fill('executive.tester');await page.locator('#password').fill(password)
        await page.get_by_role('button',name='Sign in',exact=True).click()
        await page.wait_for_url(lambda u:'/login' not in u)
        async def missing(route):
            try:
                response=await route.fetch(timeout=90000)
            except Exception:
                await route.abort()
                return
            data=await response.json()
            for driver in data.get('executive_diagnostics',{}).get('driver_grid',[]):
                if driver.get('driver_key',driver.get('key'))!='cash_vs_floor':continue
                driver.update(label='Synthetic acceptance KPI',metric='Not calculated',availability='unavailable',
                    missing_inputs=['Synthetic approved comparison input'],formula='Cash balance divided by approved floor',
                    executive_brief=None,provenance=None,trend={},accountable_provider='Fallback owner',
                    source_contract={'provider':'Synthetic Treasury acceptance owner'})
            await route.fulfill(response=response,json=data)
        await page.route('**/runs/latest*',missing)
        await page.goto(base+'/app?persona=ceo')
        card=page.locator('#driver-row [data-driver-key="cash_vs_floor"]')
        await card.wait_for(timeout=60000)
        await page.get_by_role('tab',name='Diagnostics').click()
        await card.click()
        drill=page.locator('#driver-drill')
        await drill.get_by_role('button',name='Show the work',exact=True).click()
        await expect(drill).to_contain_text('Synthetic approved comparison input')
        await expect(drill).to_contain_text('Cash balance divided by approved floor')
        await expect(drill).to_contain_text('Synthetic Treasury acceptance owner')
        async with page.expect_response(lambda r:'/api/outreach/requests' in r.url and r.request.method=='POST') as pending:
            await drill.get_by_role('button',name='Create outreach request',exact=True).click()
        response=await pending.value
        assert response.ok,await response.text()
        record=await response.json()
        assert record['status']=='drafted' and record['approval_required_before_send'] is True
        assert record['connector_enabled'] is False
        assert record['provider']=='Synthetic Treasury acceptance owner',record
        assert record['missing_inputs']==['Synthetic approved comparison input'],record
        await expect(drill).to_contain_text('Outreach request created')
        await drill.screenshot(path=out/'request-created.png')
        (out/'report.json').write_text(json.dumps({'status':'passed','candidate_javascript':os.getenv('EXECUTIVE_JS_CANDIDATE'),'mode':'Browser-local missing-input fixture; real authenticated outreach draft endpoint; no external send','record':record},indent=2))
        print(json.dumps({'status':'passed','request_id':record['request_id']}))
        await browser.close()

asyncio.run(main())
