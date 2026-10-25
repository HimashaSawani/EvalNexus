from pathlib import Path
import subprocess,sys,tempfile,json,os,shutil,time
ROOT=Path(r'D:\AgentWindTunnel')
REPORT=ROOT/'docs/reports/delivery-2026-10-24'
results={}
results['docker_available']=bool(shutil.which('docker'))
try:
    if results['docker_available']:
        r=subprocess.run(['docker','info'],cwd=ROOT,capture_output=True,text=True,timeout=30)
        results['docker_daemon_ready']=r.returncode==0
    temp=Path(tempfile.mkdtemp(prefix='awt-clean-setup-'))
    subprocess.run([sys.executable,'-m','venv',str(temp)],check=True,timeout=90)
    python=temp/'Scripts/python.exe'
    r=subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'requirements.txt')],cwd=ROOT,capture_output=True,text=True,timeout=240)
    (REPORT/'clean-install.txt').write_text(r.stdout+r.stderr,encoding='utf-8')
    results['installation_returncode']=r.returncode
    if r.returncode==0:
        r=subprocess.run([str(python),'-m','pip','freeze'],capture_output=True,text=True,timeout=30)
        (REPORT/'clean-environment-requirements.txt').write_text(r.stdout,encoding='utf-8')
        env=os.environ.copy()
        env.update(DATABASE_URL='sqlite:///'+str(REPORT/'fresh-setup.db').replace('\\','/'),AWT_EMBEDDED_WORKER='0')
        r=subprocess.run([str(python),'-c','from fastapi.testclient import TestClient; from backend.main import app; c=TestClient(app); assert c.get("/healthz").status_code==200; assert c.get("/readyz").status_code==200; print("Fresh schema, health and readiness passed")'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=60)
        results['fresh_database_returncode']=r.returncode
        results['fresh_database_output']=r.stdout+r.stderr
except Exception as e: results['error']=str(e)
(REPORT/'setup-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print(json.dumps(results,indent=2),flush=True)
