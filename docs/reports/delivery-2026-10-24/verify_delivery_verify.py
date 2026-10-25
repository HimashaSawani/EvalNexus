from pathlib import Path
import os, sys, json, subprocess, time, traceback

ROOT = Path(r'D:\AgentWindTunnel')
REPORT = ROOT / 'docs/reports/delivery-2026-10-24'

def replace(path, old, new):
    p = ROOT / path
    s = p.read_text(encoding='utf-8')
    assert old in s, path
    p.write_text(s.replace(old, new), encoding='utf-8')

def fix():
    REPORT.mkdir(parents=True, exist_ok=True)
    replace('backend/main.py', '    _embedded_worker = QueueWorker(worker_id="embedded_api_worker", poll_interval_sec=1.0)', '    if os.getenv("AWT_EMBEDDED_WORKER", "1").lower() not in {"1", "true", "yes"}:\n        yield\n        return\n    _embedded_worker = QueueWorker(poll_interval_sec=1.0)')
    replace('backend/main.py', 'Configured (Verified)', 'Configured (not validated)')
    replace('docker-compose.yml', '      - DATABASE_URL=sqlite:////data/agent_wind_tunnel.db', '      - AWT_EMBEDDED_WORKER=0\n      - DATABASE_URL=sqlite:////data/agent_wind_tunnel.db')
    replace('backend/worker.py', '            if is_cancelled:', '            if is_cancelled or job.status == "CANCELLED" or (run and run.status == "CANCELLED"):')
    replace('backend/runner/agent_runner.py', '        # Query or create Run record', '        # Query or create Run record')
    replace('backend/runner/agent_runner.py', '        scenario_run = ScenarioRun(', '        if run_record.execution_config:\n            execution_config.update(run_record.execution_config)\n\n        scenario_run = ScenarioRun(')
    replace('backend/runner/agent_runner.py', '            scenario_timeout_sec=execution_config["scenario_timeout_sec"]', '            tool_timeout_sec=execution_config.get("tool_timeout_sec", 5.0),\n            scenario_timeout_sec=execution_config["scenario_timeout_sec"]')
    # Keep local configuration outside container build context, including the existing database.
    (ROOT / '.dockerignore').write_text('.env\n.git\n*.db\n**/__pycache__/\n.pytest_cache/\n.venv*/\ndocs/reports/\n', encoding='utf-8')
    # Existing late-write tests remain unchanged; timing failures require separate diagnosis.
    print('Applied worker mode, cancellation finalization, execution configuration and credential-label fixes.', flush=True)

def run_tests():
    env = os.environ.copy()
    env['DATABASE_URL'] = 'sqlite:///' + str(REPORT / 'automated.db').replace('\\', '/')
    env['AWT_EMBEDDED_WORKER'] = '0'
    result = subprocess.run([sys.executable, '-m', 'pytest', 'tests', '-q'], cwd=ROOT, env=env, capture_output=True, text=True)
    (REPORT / 'pytest.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
    print(result.stdout, flush=True)

def browser():
    import httpx
    from playwright.sync_api import sync_playwright
    env = os.environ.copy()
    env['DATABASE_URL'] = 'sqlite:///' + str(REPORT / 'browser.db').replace('\\', '/')
    env['AWT_EMBEDDED_WORKER'] = '1'
    log = (REPORT / 'server.log').open('w', encoding='utf-8')
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8765'], cwd=ROOT, env=env, stdout=log, stderr=log)
    results = {'checks': [], 'console': [], 'network': []}
    def record(s):
        results['checks'].append(s)
        print(s, flush=True)
    try:
        for _ in range(120):
            try:
                if httpx.get('http://127.0.0.1:8765/readyz').status_code == 200: break
            except Exception: pass
            time.sleep(.5)
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            page = b.new_page(viewport={'width':1440,'height':1000}, accept_downloads=True)
            page.on('pageerror', lambda e: results['console'].append(str(e)))
            page.on('requestfailed', lambda r: results['network'].append({'url':r.url,'failure':r.failure}))
            page.goto('http://127.0.0.1:8765', wait_until='networkidle')
            page.screenshot(path=str(REPORT / 'desktop-empty.png'), full_page=True)
            for section in ['overview','test-studio','scenarios','agent-versions','run-history','comparisons','settings']:
                page.locator('#nav-'+section).click()
                page.locator('#view-'+section).wait_for(state='visible')
                record('Navigation: '+section)
            page.locator('#nav-test-studio').click()
            page.select_option('#providerSelect', 'mock')
            page.select_option('#agentSelect', 'agent_v2_improved')
            options = page.locator('#suiteSelect option').evaluate_all('(xs)=>xs.map(x=>({value:x.value,label:x.textContent}))')
            results['suite_options'] = options
            single = next(x['value'] for x in options if x['value'] not in ['dev_suite','smoke_suite'])
            for suite in [single, 'dev_suite']:
                page.select_option('#suiteSelect', suite)
                page.locator('#btnRunTests').click()
                page.wait_for_function('location.hash.includes("run=")')
                runid = page.url.split('run=')[1]
                page.reload(wait_until='networkidle')
                page.wait_for_function('document.querySelector("#panelRunStatusPill").textContent.includes("COMPLETED")', timeout=180000)
                record('Run completed after browser refresh: '+suite+' '+runid)
                data = httpx.get('http://127.0.0.1:8765/api/runs/'+runid).json()
                (REPORT / (runid+'.json')).write_text(json.dumps(data, indent=2), encoding='utf-8')
                results.setdefault('runs',[]).append(runid)
                page.screenshot(path=str(REPORT / 'before-row-click.png'), full_page=True)
                page.locator('#studioScenariosTbody tr td').first.click()
                for tab in ['checks','timeline','db','answer','raw']:
                    page.locator('#tabBtn-'+tab).click()
                    assert page.locator('#detailTabContent').inner_text().strip()
                    record('Detail tab: '+tab+' '+suite)
                page.screenshot(path=str(REPORT / ('run-'+suite.replace('.json','')+'.png')), full_page=True)
            for section in ['run-history','comparisons','settings']:
                page.locator('#nav-'+section).click()
                page.wait_for_timeout(400)
                page.screenshot(path=str(REPORT / (section+'.png')), full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            page.goto('http://127.0.0.1:8765/#test-studio?run='+runid, wait_until='networkidle')
            page.screenshot(path=str(REPORT / 'mobile.png'), full_page=True)
            results['mobile_scroll_width'] = page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
            record('Desktop and 390px viewport screenshots captured')
            b.close()
    except Exception:
        results['error'] = traceback.format_exc()
        print(results['error'], flush=True)
    finally:
        proc.terminate()
        try: proc.wait(timeout=15)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        log.close()
        (REPORT / 'browser-results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')

if __name__ == '__main__':
    {'fix':fix,'tests':run_tests,'browser':browser}[sys.argv[1]]()
