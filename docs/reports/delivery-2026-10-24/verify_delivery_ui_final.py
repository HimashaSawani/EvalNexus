from pathlib import Path
import sys, os, subprocess, time, json, traceback, httpx, shutil
from playwright.sync_api import sync_playwright
ROOT=Path(r'D:\AgentWindTunnel'); REPORT=ROOT/'docs/reports/delivery-2026-10-24'
env=os.environ.copy(); env.update(DATABASE_URL='sqlite:///'+str(REPORT/'ui-final.db').replace('\\','/'), AWT_EMBEDDED_WORKER='1')
results={'checks':[],'errors':[],'failed_requests':[]}
def record(s):results['checks'].append(s);print(s,flush=True)
log=(REPORT/'ui-final-server.log').open('w',encoding='utf-8')
proc=subprocess.Popen([sys.executable,'-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8765'],cwd=ROOT,env=env,stdout=log,stderr=log)
try:
    for _ in range(90):
        try:
            if httpx.get('http://127.0.0.1:8765/readyz',timeout=2).status_code==200:break
        except Exception:pass
        time.sleep(.3)
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True)
        page=b.new_page(viewport={'width':1440,'height':1000})
        page.set_default_timeout(60000)
        page.on('pageerror',lambda e:results['errors'].append(str(e)))
        page.on('requestfailed',lambda r:results['failed_requests'].append({'url':r.url,'error':r.failure}))
        page.goto('http://127.0.0.1:8765/#run-history',wait_until='domcontentloaded')
        page.wait_for_function('document.querySelector("#historyTbody").textContent.includes("No historical runs")')
        page.screenshot(path=str(REPORT/'empty-history.png'),full_page=True)
        record('Fresh SQLite database: empty history state visible')
        page.locator('#nav-scenarios').click()
        page.locator('#catalogSearch').fill('no-such-verification-scenario')
        page.wait_for_function('document.querySelector("#catalogTbody").textContent.includes("No scenarios match")')
        record('Catalog empty search state visible')
        page.locator('#nav-test-studio').click()
        page.select_option('#providerSelect','mock')
        page.select_option('#modelSelect','mock-deterministic-v1')
        page.select_option('#agentSelect','agent_v2_improved')
        page.select_option('#suiteSelect','eligible_refund_scenario.json')
        with page.expect_response(lambda r:r.url.endswith('/api/runs/queue') and r.request.method=='POST') as response:
            page.locator('#btnRunTests').click()
        rid=response.value.json()['run_id']
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function('document.querySelector("#panelRunStatusPill").textContent.includes("COMPLETED")',timeout=120000)
        record('After WAL configuration, mock execution survives refresh and completes')
        # A second matching mock run validates the compatibility banner with the final API code.
        data=httpx.post('http://127.0.0.1:8765/api/runs/queue',json={'provider_type':'mock','agent_version_id':'agent_v2_improved','scenarios':'eligible_refund_scenario.json'},timeout=30).json()
        other=data['run_id']
        for _ in range(120):
            actual=httpx.get('http://127.0.0.1:8765/api/runs/'+other,timeout=30).json()
            if actual['status'] in ['COMPLETED','FAILED']:break
            time.sleep(.3)
        assert actual['status']=='COMPLETED'
        page.locator('#nav-comparisons').click()
        page.wait_for_function('(id)=>Array.from(document.querySelector("#compRunBSelect").options).some(o=>o.value===id)',arg=other)
        page.select_option('#compRunASelect',rid);page.select_option('#compRunBSelect',other)
        page.get_by_role('button',name='Compare Runs',exact=False).click()
        page.wait_for_function('document.querySelector("#compCompatibilityBanner").textContent.includes("Runs Compatible")')
        record('Final-code comparison of two identical scenario selections is compatible')
        page.screenshot(path=str(REPORT/'comparison-compatible-final.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        for section in ['overview','test-studio','scenarios','agent-versions','run-history','comparisons','settings']:
            page.get_by_role('button',name='Toggle navigation').click()
            page.locator('#nav-'+section).click()
            page.locator('#view-'+section).wait_for(state='visible')
            assert page.locator('main.workspace').bounding_box()['width']>=380
            record('Mobile navigation and full content width: '+section)
        page.get_by_role('button',name='Toggle navigation').click();page.locator('#nav-test-studio').click()
        page.goto('http://127.0.0.1:8765/#test-studio?run='+rid,wait_until='domcontentloaded')
        page.wait_for_function('document.querySelector("#panelRunStatusPill").textContent.includes("COMPLETED")')
        before=REPORT/'mobile.png'
        if before.exists():shutil.copyfile(before,REPORT/'mobile-before-layout-fix.png')
        page.screenshot(path=str(REPORT/'mobile.png'),full_page=True)
        results['mobile_bounds']=page.locator('main.workspace').bounding_box()
        # Demonstrate visible retry state while a deliberate route failure is active.
        page.route('**/api/runs/*',lambda route:route.abort())
        page.evaluate('(id)=>startPollingRun(id)',rid)
        page.wait_for_function('document.querySelector("#panelRunStatusPill").textContent.includes("Connection error")')
        page.screenshot(path=str(REPORT/'network-error.png'),full_page=True)
        record('Injected network failure produces visible retry state; failed request is expected')
        page.unroute('**/api/runs/*')
        page.wait_for_function('document.querySelector("#panelRunStatusPill").textContent.includes("COMPLETED")')
        record('Polling recovers after network access is restored')
        b.close()
except Exception:
    results['error']=traceback.format_exc();print(results['error'],flush=True)
finally:
    proc.terminate()
    try:proc.wait(timeout=10)
    except subprocess.TimeoutExpired:proc.kill();proc.wait()
    log.close()
    (REPORT/'ui-final-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
