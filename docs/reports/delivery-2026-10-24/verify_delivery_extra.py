from pathlib import Path
import os, sys, json, time, subprocess, traceback, shutil
import httpx
ROOT = Path(r'D:\AgentWindTunnel')
REPORT = ROOT / 'docs/reports/delivery-2026-10-24'
BASE = 'http://127.0.0.1:8766'
env = os.environ.copy()
env.update(DATABASE_URL='sqlite:///'+str(REPORT / 'restart.db').replace('\\','/'), AWT_EMBEDDED_WORKER='0')
results = {'checks':[], 'live':[], 'limitations':[]}
processes = []
log = (REPORT / 'restart-server.log').open('w', encoding='utf-8')
def start(module, args=[]):
    p = subprocess.Popen([sys.executable,'-m',module]+args, cwd=ROOT, env=env, stdout=log, stderr=log)
    processes.append(p)
    return p
def stop(p):
    if p.poll() is None:
        p.terminate()
        try: p.wait(timeout=10)
        except subprocess.TimeoutExpired: p.kill(); p.wait()
def wait_ready():
    for _ in range(90):
        try:
            if httpx.get(BASE+'/readyz', timeout=2).status_code == 200: return
        except Exception: pass
        time.sleep(.3)
    raise RuntimeError('API did not become ready')
def getrun(rid): return httpx.get(BASE+'/api/runs/'+rid, timeout=10).json()
def wait_status(rid, terminal=True, seconds=120):
    deadline = time.monotonic()+seconds
    while time.monotonic()<deadline:
        data = getrun(rid)
        if data['status'] in (['COMPLETED','FAILED','CANCELLED','PROVIDER_ERROR'] if terminal else ['RUNNING']): return data
        time.sleep(.2)
    raise RuntimeError('Run exceeded bounded verification wait: '+rid)
def queue(scenarios, **extra):
    r = httpx.post(BASE+'/api/runs/queue', json=dict(provider_type='mock',agent_version_id='agent_v2_improved',scenarios=scenarios,**extra), timeout=10)
    r.raise_for_status()
    return r.json()['run_id']
def record(s): results['checks'].append(s); print(s, flush=True)

try:
    api = start('uvicorn',['backend.main:app','--host','127.0.0.1','--port','8766'])
    wait_ready()
    rid = queue('eligible_refund_scenario.json')
    time.sleep(2)
    assert getrun(rid)['status'] == 'QUEUED'
    record('Standalone API does not claim jobs when AWT_EMBEDDED_WORKER=0')
    cancelled = queue('dev_suite')
    assert httpx.post(BASE+'/api/runs/'+cancelled+'/cancel').status_code == 200
    worker = start('backend.worker')
    data = wait_status(rid)
    assert data['status'] == 'COMPLETED' and len(data['scenario_runs']) == 1
    assert getrun(cancelled)['status'] == 'CANCELLED'
    record('Standalone worker claims queued jobs; queued cancellation preserved')
    # The repeated mock list provides time to restart the API during execution.
    rid = queue(['eligible_refund_scenario.json']*20)
    wait_status(rid, terminal=False)
    stop(api)
    api = start('uvicorn',['backend.main:app','--host','127.0.0.1','--port','8766'])
    wait_ready()
    data = wait_status(rid)
    assert data['status'] == 'COMPLETED' and len(data['scenario_runs']) == 20
    record('API process restarted during mock execution; standalone worker completed all 20 executions')
    interrupted = queue('dev_suite')
    wait_status(interrupted, terminal=False)
    stop(worker)
    # Start replacement worker; its regular reaper must recover abandoned ownership.
    worker = start('backend.worker')
    data = wait_status(interrupted, seconds=65)
    assert data['status'] == 'FAILED'
    (REPORT / 'interrupted-run.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    record('Terminated worker during mock run; replacement worker reaped abandoned job as FAILED without replay')
    # Browser comparison, history filters, cancellation, missing-run and request failure states.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width':1440,'height':1000})
        console=[]
        page.on('pageerror', lambda e:console.append(str(e)))
        page.goto(BASE+'/#comparisons', wait_until='networkidle')
        page.select_option('#compRunASelect', rid)
        # Same configuration, distinct run.
        other = queue('eligible_refund_scenario.json')
        wait_status(other)
        page.reload(wait_until='networkidle')
        page.select_option('#compRunASelect', rid)
        page.select_option('#compRunBSelect', other)
        page.get_by_role('button', name='Compare Runs', exact=False).click()
        page.locator('#compCompatibilityBanner').wait_for(state='visible')
        record('Browser compatible comparison matrix rendered')
        page.screenshot(path=str(REPORT/'comparison-compatible.png'), full_page=True)
        # Model metadata mismatch using mock provider incurs no paid execution.
        mismatch = queue('eligible_refund_scenario.json',model_name='mock-mismatch-verification')
        wait_status(mismatch)
        page.reload(wait_until='networkidle')
        page.select_option('#compRunASelect', other)
        page.select_option('#compRunBSelect', mismatch)
        page.get_by_role('button', name='Compare Runs', exact=False).click()
        page.wait_for_function('document.querySelector("#compCompatibilityBanner").textContent.includes("mismatch")')
        record('Browser comparison warns about model mismatch')
        page.screenshot(path=str(REPORT/'comparison-mismatch.png'), full_page=True)
        page.goto(BASE+'/#run-history', wait_until='networkidle')
        page.select_option('#historyProviderFilter','mock')
        page.select_option('#historyStatusFilter','CANCELLED')
        page.wait_for_timeout(500)
        assert cancelled in page.locator('#historyTbody').inner_text()
        record('Browser history provider/status filters select cancelled mock run')
        page.goto(BASE+'/#test-studio', wait_until='networkidle')
        page.select_option('#suiteSelect','dev_suite')
        page.locator('#btnRunTests').click()
        page.locator('#btnCancelRun').wait_for(state='visible')
        page.on('dialog', lambda d:d.accept())
        page.locator('#btnCancelRun').click()
        page.wait_for_function('document.querySelector("#panelRunStatusPill").textContent.includes("CANCELLED")', timeout=30000)
        record('Browser cancellation reaches CANCELLED terminal state')
        page.screenshot(path=str(REPORT/'cancelled.png'), full_page=True)
        # Bounded live runs from the actual web controls, project-configured credentials only.
        settings=httpx.get(BASE+'/api/settings').json()
        if os.getenv('AWT_VERIFY_LIVE') == '1' and settings['credentials']['GEMINI_API_KEY']['configured']:
            models=httpx.get(BASE+'/api/models',timeout=45).json()
            available=[m['id'] for m in models if m['provider']=='gemini']
            model='gemini-flash-lite-latest' if 'gemini-flash-lite-latest' in available else available[0] if available else None
            if model:
                for scenario in ['eligible_refund_scenario.json','ineligible_expired_scenario.json','fault_timeout_after_write.json']:
                    page.goto(BASE+'/#test-studio',wait_until='networkidle')
                    page.select_option('#providerSelect','gemini')
                    page.select_option('#modelSelect',model)
                    page.select_option('#agentSelect','agent_v2_improved')
                    page.select_option('#suiteSelect',scenario)
                    with page.expect_response(lambda r:r.url.endswith('/api/runs/queue') and r.request.method=='POST') as queued:
                        page.locator('#btnRunTests').click()
                    liveid=queued.value.json()['run_id']
                    actual=wait_status(liveid,seconds=100)
                    assert not actual['is_mock'] and actual['provider_type']=='gemini'
                    (REPORT / ('live-'+scenario)).write_text(json.dumps(actual,indent=2),encoding='utf-8')
                    sr=actual['scenario_runs']
                    results['live'].append({'run_id':liveid,'scenario':scenario,'status':actual['status'],'scenario_statuses':[s['status'] for s in sr], 'tool_calls':sum(sum(t['event_type']=='TOOL_CALL' for t in s['traces']) for s in sr)})
                    record('Live web execution: '+scenario+' '+actual['status'])
                    errors=json.dumps(actual).lower()
                    if any(x in errors for x in ['quota','resource_exhausted','invalid api key','api_key_invalid','unauthenticated']):
                        results['limitations'].append('Live provider quota/credential error; remaining live runs skipped')
                        break
            else: results['limitations'].append('No Gemini model available in discovery')
        else: results['limitations'].append('Project Gemini credentials unavailable; no live executions attempted')
        results['browser_page_errors']=console
        browser.close()
except Exception:
    results['error']=traceback.format_exc()
    print(results['error'],flush=True)
finally:
    for proc in reversed(processes): stop(proc)
    log.close()
    (REPORT/'extra-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
