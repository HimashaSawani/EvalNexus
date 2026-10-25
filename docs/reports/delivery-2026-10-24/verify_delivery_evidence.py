from pathlib import Path
import sqlite3,json,subprocess,os
ROOT=Path(r'D:\AgentWindTunnel');REPORT=ROOT/'docs/reports/delivery-2026-10-24'
def rows(c,sql,args=()):
    return [dict(r) for r in c.execute(sql,args)]
def decode(row):
    for k,v in row.items():
        if isinstance(v,str) and v[:1] in ['{','[']:
            try:row[k]=json.loads(v)
            except ValueError:pass
    return row
with sqlite3.connect(REPORT/'restart.db') as c:
    c.row_factory=sqlite3.Row
    jobs=rows(c,'select * from queue_jobs where is_paid=1')
    summary=[]
    for job in jobs:
        run=rows(c,'select * from runs where id=?',(job['run_id'],))[0]
        scenarios=rows(c,'select * from scenario_runs where run_id=?',(job['run_id'],))
        for s in scenarios:
            sid=s['id']
            s['traces']=[decode(r) for r in rows(c,'select * from trace_events where scenario_run_id=? order by seq_num',(sid,))]
            s['checks']=[decode(r) for r in rows(c,'select * from check_results where scenario_run_id=?',(sid,))]
            s['refunds']=rows(c,'select * from refund_requests where scenario_run_id=?',(sid,))
            s['orders']=rows(c,'select * from orders where scenario_run_id=?',(sid,))
        artifact={'job':decode(job),'run':decode(run),'scenarios':scenarios}
        (REPORT/('paid-'+run['id']+'.json')).write_text(json.dumps(artifact,indent=2),encoding='utf-8')
        summary.append({'run_id':run['id'],'selection':job['scenario_ids'],'job_status':job['status'],'run_status':run['status'],'error':job['error_message'],
            'scenarios':[{'id':s['scenario_version_id'],'status':s['status'],'duration_ms':s['duration_ms'],
                'tools':[t['tool_name'] for t in s['traces'] if t['event_type']=='TOOL_CALL'],
                'faults':[t['error_message'] for t in s['traces'] if t['event_type']=='FAULT_INJECTED'],
                'answers':[t['tool_result'] for t in s['traces'] if t['event_type']=='FINAL_ANSWER'],
                'refunds':s['refunds']} for s in scenarios]})
    assert len(summary)<=3
    (REPORT/'paid-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True)
    reaped=rows(c,"select run_id,error_message from queue_jobs where error_message like '%Abandoned%'")
    (REPORT/'recovery-summary.json').write_text(json.dumps(reaped,indent=2),encoding='utf-8')
# Preserve each test result rather than silently losing unsuccessful attempts.
pytest=REPORT/'pytest.txt'
if pytest.exists():
    (REPORT/'pytest-before-final.txt').write_text(pytest.read_text(encoding='utf-8'),encoding='utf-8')
