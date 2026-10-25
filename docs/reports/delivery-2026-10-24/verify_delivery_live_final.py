import os
if os.getenv('AWT_VERIFY_LIVE') != '1': raise SystemExit('Live verification requires explicit AWT_VERIFY_LIVE=1; no execution performed')
from pathlib import Path
import sqlite3
source=Path(r'D:\AgentWindTunnel\docs\reports\delivery-2026-10-24\verify_delivery_extra.py').read_text(encoding='utf-8').split('\ntry:\n    api =')[0]
exec(source)
results={'live':[],'checks':[],'limitations':[]}
def ledger():
    with sqlite3.connect(REPORT/'restart.db') as c:
        c.row_factory=sqlite3.Row
        return [dict(r) for r in c.execute('select id,run_id,status,scenario_ids,error_message from queue_jobs where is_paid=1')]
try:
    api=start('uvicorn',['backend.main:app','--host','127.0.0.1','--port','8766'])
    wait_ready()
    worker=start('backend.worker')
    deadline=time.monotonic()+65
    while any(r['status'] in ['RUNNING','QUEUED'] for r in ledger()) and time.monotonic()<deadline:
        time.sleep(.5)
    assert not any(r['status'] in ['RUNNING','QUEUED'] for r in ledger()), 'Prior paid attempt has not reached a terminal state'
    if len(ledger())<3:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b=p.chromium.launch(headless=True)
            page=b.new_page(viewport={'width':1440,'height':1000})
            page.set_default_timeout(60000)
            page.goto(BASE+'/#test-studio',wait_until='domcontentloaded')
            page.wait_for_function('document.querySelector("#agentSelect").options.length >= 3')
            page.select_option('#providerSelect','gemini')
            page.select_option('#modelSelect','gemini-flash-lite-latest')
            page.select_option('#agentSelect','agent_v2_improved')
            page.select_option('#suiteSelect','fault_timeout_after_write.json')
            with page.expect_response(lambda r:r.url.endswith('/api/runs/queue') and r.request.method=='POST') as queued:
                page.locator('#btnRunTests').click()
            response=queued.value
            assert response.ok
            lastid=response.json()['run_id']
            record('Third and final live web submission: timeout-after-write '+lastid)
            deadline=time.monotonic()+100
            while time.monotonic()<deadline:
                rows=ledger()
                row=next(r for r in rows if r['run_id']==lastid)
                if row['status'] not in ['RUNNING','QUEUED']:break
                time.sleep(.5)
            assert row['status'] not in ['RUNNING','QUEUED'], 'Paid execution exceeded bounded wait; no retry authorized'
            page.goto(BASE+'/#test-studio?run='+lastid,wait_until='domcontentloaded')
            page.wait_for_function('document.querySelector("#panelRunStatusPill").textContent.includes("COMPLETED") || document.querySelector("#panelRunStatusPill").textContent.includes("FAILED")',timeout=60000)
            page.screenshot(path=str(REPORT/'live-timeout-after-write.png'),full_page=True)
            b.close()
    # Export all submitted paid attempts without making additional provider requests.
    os.environ.update(env)
    sys.path.insert(0,str(ROOT))
    from backend.main import get_run_details
    from backend.database.connection import SessionLocal
    with SessionLocal() as db:
        for row in ledger():
            data=get_run_details(row['run_id'],db)
            (REPORT/('paid-'+row['run_id']+'.json')).write_text(json.dumps(data,indent=2),encoding='utf-8')
            summaries=[]
            for s in data['scenario_runs']:
                answers=[t['result'].get('final_answer') for t in s['traces'] if t['event_type']=='FINAL_ANSWER' and t.get('result')]
                summaries.append({'scenario':s['scenario_version_id'],'status':s['status'],'duration_ms':s['duration_ms'],'tools':[t['tool'] for t in s['traces'] if t['event_type']=='TOOL_CALL'],'faults':[t['error'] for t in s['traces'] if t['event_type']=='FAULT_INJECTED'],'final_answers':answers,'refunds':s['database_state']['refunds']})
            results['live'].append({'run_id':row['run_id'],'status':data['status'],'job_status':row['status'],'error':row['error_message'],'scenarios':summaries})
    assert len(ledger())<=3
    print(json.dumps(results,indent=2),flush=True)
except Exception:
    results['error']=traceback.format_exc()
    print(results['error'],flush=True)
finally:
    for proc in reversed(processes):stop(proc)
    log.close()
    (REPORT/'live-final-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
