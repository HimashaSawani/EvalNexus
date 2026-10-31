import os
import sys
import time
import socket
import tempfile
import subprocess
from pathlib import Path
import pytest
import httpx
from playwright.sync_api import sync_playwright


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def live_server_proc():
    port = get_free_port()
    project_root = Path(__file__).resolve().parent.parent

    temp_dir = Path(tempfile.mkdtemp(prefix="awt-e2e-"))
    test_db = temp_dir / "e2e_playwright.db"

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
    ready = False
    for _ in range(60):
        try:
            r = httpx.get(f"{base_url}/readyz", timeout=1.0)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(0.2)

    if not ready:
        proc.kill()
        pytest.fail(f"Uvicorn live server failed to respond on {base_url} within 12 seconds.")

    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=3.0)
    except Exception:
        proc.kill()


def test_playwright_all_sixteen_sections(live_server_proc):
    """
    Automated Playwright browser verification testing that all 16 dashboard sections
    render and navigate cleanly without uncaught JavaScript errors.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        # 1. Overview Section
        page.goto(f"{live_server_proc}/#overview", wait_until="domcontentloaded")
        page.wait_for_selector("#ovTotalRuns", timeout=10000)
        assert page.locator("#ovTotalRuns").is_visible()

        # 2. Test Studio Section
        page.locator("#nav-test-studio").click()
        page.wait_for_selector("#providerSelect", timeout=5000)
        assert page.locator("#providerSelect").is_visible()

        # 3. Scenarios Catalog Section
        page.locator("#nav-scenarios").click()
        page.wait_for_selector("#catalogTbody", timeout=5000)
        assert page.locator("#catalogTbody").is_visible()

        # 4. Agent Versions Section
        page.locator("#nav-agent-versions").click()
        page.wait_for_selector("#agentVersionsGrid", timeout=5000)
        assert page.locator("#agentVersionsGrid").is_visible()

        # 5. Run History Section
        page.locator("#nav-run-history").click()
        page.wait_for_selector("#historyTbody", timeout=5000)
        assert page.locator("#historyTbody").is_visible()

        # 6. Comparisons Section
        page.locator("#nav-comparisons").click()
        page.wait_for_selector("#compRunASelect", timeout=5000)
        assert page.locator("#compRunASelect").is_visible()
        assert page.locator("button:has-text('Compare Runs')").is_visible()

        # 7. Settings & Safety Section
        page.locator("#nav-settings").click()
        page.wait_for_selector("#settingsCredentialsTbody", timeout=5000)
        assert page.locator("#settingsCredentialsTbody").is_visible()

        # 8. Custom Agent Registry Section (Stage 2) - Form Interaction
        page.locator("#nav-custom-agents").click()
        page.wait_for_selector("#customAgentUrl", timeout=5000)
        assert page.locator("#customAgentUrl").is_visible()
        assert page.locator("#btnSaveCustomAgent").is_visible()

        # Test actual user interaction: Register a custom agent
        page.fill("#customAgentName", "Playwright E2E External Agent")
        page.fill("#customAgentUrl", "https://api.test-agent.example.com/v1/generate")
        page.fill("#customAgentHeader", "Authorization")
        page.fill("#customAgentToken", "test-secret-token-12345")
        page.fill("#customAgentTimeout", "10")
        page.locator("#btnSaveCustomAgent").click()
        page.wait_for_selector("#customAgentSaveFeedback", timeout=5000)
        feedback_text = page.locator("#customAgentSaveFeedback").text_content()
        assert "Saved custom agent" in feedback_text or "Error" not in feedback_text

        # 9. Scenario Builder Section (Stage 3) - Form Interaction
        page.locator("#nav-scenario-builder").click()
        page.wait_for_selector("#scenBuilderId", timeout=5000)
        assert page.locator("#scenBuilderId").is_visible()
        assert page.locator("#btnSaveScenario").is_visible()

        # Test actual user interaction: Save a custom scenario
        page.fill("#scenBuilderId", "e2e_ui_custom_scenario_01")
        page.fill("#scenBuilderName", "Playwright E2E Custom Scenario")
        page.locator("#btnSaveScenario").click()
        page.wait_for_selector("#scenBuilderStatus", timeout=5000)
        status_text = page.locator("#scenBuilderStatus").text_content()
        assert "Saved custom scenario" in status_text or "saved" in status_text.lower()

        # 10. Regression Testing & Scorecards Section (Stage 4)
        page.locator("#nav-regression-testing").click()
        page.wait_for_selector("#regBaselineSelect", timeout=5000)
        assert page.locator("#regBaselineSelect").is_visible()
        assert page.locator("#btnRunRegression").is_visible()

        # 11. Failure Analysis Section (Stage 5) - Filter Interaction
        page.locator("#nav-failure-analysis").click()
        page.wait_for_selector("#faCategoryFilter", timeout=5000)
        assert page.locator("#faCategoryFilter").is_visible()
        assert page.locator("#faPolicyCount").is_visible()
        # Test actual user interaction: changing filter selection
        page.select_option("#faCategoryFilter", "BEHAVIORAL_POLICY_VIOLATION")

        # 12. V3 Multi-Agent Workflows Section
        page.locator("#nav-workflows").click()
        page.wait_for_selector("#wfDefinitionJson", timeout=5000)
        assert page.locator("#wfDefinitionJson").is_visible()
        assert page.locator("#btnSaveAndRunWf").is_visible()
        assert page.locator("#wfMetricCount").is_visible()

        # 13. V3 Distributed Nodes & Cluster Concurrency Section
        page.locator("#nav-cluster-nodes").click()
        page.wait_for_selector("#clusterNodesTbody", timeout=5000)
        assert page.locator("#clusterNodesTbody").is_visible()
        assert page.locator("#clusterActiveNodes").is_visible()

        # 14. V3 Trace Explorer & OTel Spans Section
        page.locator("#nav-trace-explorer").click()
        page.wait_for_selector("#traceInputId", timeout=5000)
        assert page.locator("#traceInputId").is_visible()
        assert page.locator("#traceWaterfallContainer").is_visible()

        # 15. V3 Chaos Fault Lab Section
        page.locator("#nav-fault-lab").click()
        page.wait_for_selector("#faultModeSelect", timeout=5000)
        assert page.locator("#faultModeSelect").is_visible()
        assert page.locator("#faultResilienceScore").is_visible()

        # 16. V3 Automated CI/CD Quality Gates Section
        page.locator("#nav-quality-gates").click()
        page.wait_for_selector("#gateMinPassRate", timeout=5000)
        assert page.locator("#gateMinPassRate").is_visible()
        assert page.locator("#gateVerdictBadge").is_visible()

        browser.close()
        assert len(console_errors) == 0, f"Uncaught browser console errors: {console_errors}"
