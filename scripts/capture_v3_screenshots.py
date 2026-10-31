import os
import sys
import time
import socket
import tempfile
import subprocess
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def main():
    port = get_free_port()
    project_root = Path(__file__).resolve().parent.parent

    temp_dir = Path(tempfile.mkdtemp(prefix="awt-screens-"))
    test_db = temp_dir / "screens.db"

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{test_db.as_posix()}"
    env["AWT_EMBEDDED_WORKER"] = "0"
    env["AWT_REQUIRE_AUTH"] = "0"

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(project_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    base_url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            r = httpx.get(f"{base_url}/readyz", timeout=1.0)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.2)

    out_dir = project_root / "docs" / "reports" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1366, "height": 840})
        page = context.new_page()

        # 27. Multi-Agent Workflows
        page.goto(f"{base_url}/#workflows", wait_until="networkidle")
        page.wait_for_selector("#wfDefinitionJson", timeout=5000)
        page.locator("#btnSaveAndRunWf").click()
        time.sleep(1.0)
        page.screenshot(path=str(out_dir / "27_multi_agent_workflows.png"))
        print("Captured 27_multi_agent_workflows.png")

        # 28. Distributed Cluster Nodes
        page.locator("#nav-cluster-nodes").click()
        page.wait_for_selector("#clusterNodesTbody", timeout=5000)
        page.locator("button:has-text('+ Register Node')").click()
        time.sleep(0.8)
        page.screenshot(path=str(out_dir / "28_distributed_cluster_nodes.png"))
        print("Captured 28_distributed_cluster_nodes.png")

        # 29. Trace Explorer & Spans
        page.locator("#nav-trace-explorer").click()
        page.wait_for_selector("#traceInputId", timeout=5000)
        page.fill("#traceInputId", "run_v3_demo_01")
        page.locator("button:has-text('Inspect Spans')").click()
        time.sleep(0.8)
        page.screenshot(path=str(out_dir / "29_trace_explorer_spans.png"))
        print("Captured 29_trace_explorer_spans.png")

        # 30. Chaos Fault Lab
        page.locator("#nav-fault-lab").click()
        page.wait_for_selector("#faultModeSelect", timeout=5000)
        page.locator("button:has-text('Execute Chaos Simulation')").click()
        time.sleep(0.8)
        page.screenshot(path=str(out_dir / "30_chaos_fault_lab.png"))
        print("Captured 30_chaos_fault_lab.png")

        # 31. Automated Quality Gates
        page.locator("#nav-quality-gates").click()
        page.wait_for_selector("#gateMinPassRate", timeout=5000)
        page.locator("button:has-text('Evaluate Gate Rules')").click()
        time.sleep(0.8)
        page.screenshot(path=str(out_dir / "31_automated_quality_gates.png"))
        print("Captured 31_automated_quality_gates.png")

        browser.close()

    proc.terminate()
    try:
        proc.wait(timeout=3.0)
    except Exception:
        proc.kill()
    print("All V3 screenshots captured successfully.")

if __name__ == "__main__":
    main()
