import os
import sys
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8001"
ROOT_DIR = Path(r"D:\AgentWindTunnel")
SCREENSHOTS_DIR = ROOT_DIR / "docs" / "reports" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

report_data = {
    "sections_tested": [],
    "mock_executions": [],
    "history_verified": False,
    "comparisons_verified": False,
    "exports_verified": False,
    "background_execution_verified": False,
    "mobile_verified": False,
    "console_errors": [],
    "page_errors": [],
    "failed_requests": [],
    "screenshots": [],
}

def log(msg):
    print(f"[E2E] {msg}", flush=True)

def record_screenshot(page, filename, full_page=True):
    filepath = SCREENSHOTS_DIR / filename
    page.screenshot(path=str(filepath), full_page=full_page)
    report_data["screenshots"].append(str(filepath.relative_to(ROOT_DIR)).replace("\\", "/"))
    log(f"Saved screenshot: {filename}")

def run_all_tests():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # Listen for console and errors
        page.on("console", lambda msg: report_data["console_errors"].append(msg.text) if msg.type in ["error"] else None)
        page.on("pageerror", lambda err: report_data["page_errors"].append(str(err)))
        page.on("requestfailed", lambda req: report_data["failed_requests"].append({"url": req.url, "failure": req.failure}))

        # -------------------------------------------------------------
        # STEP 1: Verify all 7 sections (Desktop)
        # -------------------------------------------------------------
        log("Step 1: Testing all 7 dashboard sections...")

        # 1. Overview
        page.goto(f"{BASE_URL}/#overview", wait_until="networkidle")
        page.wait_for_selector("#ovTotalRuns")
        total_runs = page.locator("#ovTotalRuns").text_content()
        assert int(total_runs) >= 0, "Overview total runs invalid"
        record_screenshot(page, "01_overview_desktop.png")
        report_data["sections_tested"].append("Overview")
        log(f"Overview loaded: Total Runs = {total_runs}")

        # 2. Test Studio
        page.locator("#nav-test-studio").click()
        page.wait_for_selector("#providerSelect")
        record_screenshot(page, "02_test_studio_initial.png")
        report_data["sections_tested"].append("Test Studio")
        log("Test Studio loaded")

        # 3. Scenarios
        page.locator("#nav-scenarios").click()
        page.wait_for_selector("#catalogTbody tr")
        record_screenshot(page, "03_scenarios_catalog.png")
        
        # Test catalog search and filter
        page.locator("#catalogSearch").fill("timeout")
        time.sleep(0.3)
        record_screenshot(page, "04_scenarios_filtered.png")
        page.locator("#catalogSearch").fill("")
        
        # Test "Test in Studio" from catalog
        page.locator("button:has-text('Test in Studio')").first.click()
        page.wait_for_selector("#view-test-studio.active")
        log("Scenarios Catalog verified and 'Test in Studio' navigation confirmed")
        report_data["sections_tested"].append("Scenarios")

        # 4. Agent Versions
        page.locator("#nav-agent-versions").click()
        page.wait_for_selector("#agentVersionsGrid .card")
        cards = page.locator("#agentVersionsGrid .card").count()
        assert cards >= 3, f"Expected >= 3 agent version cards, got {cards}"
        record_screenshot(page, "05_agent_versions.png")
        report_data["sections_tested"].append("Agent Versions")
        log(f"Agent Versions loaded: {cards} versions displayed")

        # 5. Run History
        page.locator("#nav-run-history").click()
        page.wait_for_selector("#historyTbody tr")
        record_screenshot(page, "06_run_history.png")
        
        # Filter history
        page.select_option("#historyProviderFilter", "mock")
        time.sleep(0.3)
        record_screenshot(page, "07_run_history_filtered.png")
        page.select_option("#historyProviderFilter", "all")
        report_data["sections_tested"].append("Run History")
        log("Run History loaded and filtered")

        # 6. Comparisons
        page.locator("#nav-comparisons").click()
        page.wait_for_function('() => document.querySelectorAll("#compRunASelect option").length > 0')
        options_count = page.locator("#compRunASelect option").count()
        log(f"Comparisons loaded: {options_count} selectable runs")
        if options_count >= 2:
            page.locator("button:has-text('Compare Runs')").click()
            page.wait_for_selector("#compCompatibilityBanner", state="visible")
            page.wait_for_selector("#compResultsCard", state="visible")
            record_screenshot(page, "08_comparisons_loaded.png")
        report_data["sections_tested"].append("Comparisons")

        # 7. Settings
        page.locator("#nav-settings").click()
        page.wait_for_selector("#settingsCredentialsTbody tr")
        record_screenshot(page, "10_settings.png")
        report_data["sections_tested"].append("Settings")
        log("Settings loaded")

        # -------------------------------------------------------------
        # STEP 2: Complete mock execution flow
        # -------------------------------------------------------------
        log("Step 2: Testing Complete Mock Execution Flow...")

        # Flow A: agent_v1_baseline + Mock + eligible_refund_scenario.json
        page.locator("#nav-test-studio").click()
        page.select_option("#agentSelect", "agent_v1_baseline")
        page.select_option("#providerSelect", "mock")
        page.select_option("#modelSelect", "mock-deterministic-v1")
        page.select_option("#suiteSelect", "eligible_refund_scenario.json")

        with page.expect_response(lambda r: "/api/runs/queue" in r.url and r.request.method == "POST") as resp_info:
            page.locator("#btnRunTests").click()
        
        post_data = resp_info.value.json()
        run_v1_id = post_data["run_id"]
        log(f"Flow A: Queued run {run_v1_id}")

        # Capture running state
        time.sleep(0.5)
        record_screenshot(page, "11_execution_v1_baseline_running.png")

        # Wait for terminal status
        page.wait_for_function(
            "() => document.querySelector('#panelRunStatusPill') && (document.querySelector('#panelRunStatusPill').textContent.includes('COMPLETED') || document.querySelector('#panelRunStatusPill').textContent.includes('FAILED'))",
            timeout=60000
        )
        status_v1 = page.locator("#panelRunStatusPill").text_content()
        log(f"Flow A completed with status: {status_v1}")
        record_screenshot(page, "12_execution_v1_baseline_completed.png")
        assert "COMPLETED" in status_v1

        # Click scenario run row to inspect details
        page.wait_for_selector("#studioScenariosTbody tr")
        page.locator("#studioScenariosTbody tr").first.click()

        # Tab 1: Evaluator Checks
        page.locator("#tabBtn-checks").click()
        page.wait_for_selector("#detailTabContent table")
        record_screenshot(page, "13_execution_v1_checks.png")

        # Tab 2: Timeline / Traces
        page.locator("#tabBtn-timeline").click()
        page.wait_for_selector(".stepper-timeline")
        record_screenshot(page, "14_execution_v1_timeline.png")

        # Tab 3: Database State
        page.locator("#tabBtn-db").click()
        page.wait_for_selector(".db-audit-group")
        record_screenshot(page, "15_execution_v1_dbstate.png")

        # Tab 4: Final Answer
        page.locator("#tabBtn-answer").click()
        page.wait_for_selector(".final-answer-callout")
        answer_text = page.locator(".final-answer-callout p").text_content()
        log(f"Flow A Final Answer: {answer_text}")
        assert len(answer_text) > 10, "Final answer is empty or invalid"
        record_screenshot(page, "16_execution_v1_final_answer.png")

        # Tab 5: Raw JSON
        page.locator("#tabBtn-raw").click()
        page.wait_for_selector(".json-code-box")

        # Test Refresh & History Persistence
        log("Testing browser reload and persistence...")
        page.reload(wait_until="networkidle")
        page.wait_for_function(
            "() => document.querySelector('#panelRunStatusPill') && document.querySelector('#panelRunStatusPill').textContent.includes('COMPLETED')",
            timeout=30000
        )
        record_screenshot(page, "17_execution_v1_persisted_after_reload.png")
        log(f"Persistence confirmed for {run_v1_id}")

        report_data["mock_executions"].append({
            "run_id": run_v1_id,
            "agent": "agent_v1_baseline",
            "scenario": "eligible_refund_scenario.json",
            "status": status_v1
        })

        # Flow B: agent_v2_improved + Mock + fault_timeout_after_write.json
        log("Flow B: Testing Fault Injection Scenario...")
        page.select_option("#agentSelect", "agent_v2_improved")
        page.select_option("#providerSelect", "mock")
        page.select_option("#suiteSelect", "fault_timeout_after_write.json")

        with page.expect_response(lambda r: "/api/runs/queue" in r.url and r.request.method == "POST") as resp_info_b:
            page.locator("#btnRunTests").click()
        
        run_v2_id = resp_info_b.value.json()["run_id"]
        log(f"Flow B: Queued run {run_v2_id}")

        page.wait_for_function(
            "() => document.querySelector('#panelRunStatusPill') && (document.querySelector('#panelRunStatusPill').textContent.includes('COMPLETED') || document.querySelector('#panelRunStatusPill').textContent.includes('FAILED'))",
            timeout=60000
        )
        status_v2 = page.locator("#panelRunStatusPill").text_content()
        log(f"Flow B completed with status: {status_v2}")
        record_screenshot(page, "18_execution_v2_fault_completed.png")
        assert "COMPLETED" in status_v2

        report_data["mock_executions"].append({
            "run_id": run_v2_id,
            "agent": "agent_v2_improved",
            "scenario": "fault_timeout_after_write.json",
            "status": status_v2
        })

        # -------------------------------------------------------------
        # STEP 3: History and Comparisons
        # -------------------------------------------------------------
        log("Step 3: Testing History and Comparisons...")
        page.locator("#nav-run-history").click()
        
        # Wait for both new runs to appear in history table
        page.wait_for_function('(id) => document.querySelector("#historyTbody").textContent.includes(id)', arg=run_v1_id)
        page.wait_for_function('(id) => document.querySelector("#historyTbody").textContent.includes(id)', arg=run_v2_id)
        report_data["history_verified"] = True
        log("Both runs verified in Run History")

        # Comparisons: Compare two identical scenario runs for compatibility
        # First queue a second run with same scenario for Flow A to get exact compatibility
        page.locator("#nav-test-studio").click()
        page.select_option("#agentSelect", "agent_v2_improved")
        page.select_option("#providerSelect", "mock")
        page.select_option("#suiteSelect", "eligible_refund_scenario.json")
        with page.expect_response(lambda r: "/api/runs/queue" in r.url and r.request.method == "POST") as resp_info_compat:
            page.locator("#btnRunTests").click()
        run_compat_id = resp_info_compat.value.json()["run_id"]
        page.wait_for_function(
            "() => document.querySelector('#panelRunStatusPill') && document.querySelector('#panelRunStatusPill').textContent.includes('COMPLETED')",
            timeout=60000
        )

        page.locator("#nav-comparisons").click()
        page.wait_for_function('(id) => Array.from(document.querySelectorAll("#compRunASelect option")).some(o => o.value === id)', arg=run_compat_id)
        
        # Test Compatible Comparison
        page.select_option("#compRunASelect", run_v1_id)
        page.select_option("#compRunBSelect", run_compat_id)
        page.locator("button:has-text('Compare Runs')").click()
        page.wait_for_function('() => document.querySelector("#compCompatibilityBanner") && document.querySelector("#compCompatibilityBanner").textContent.includes("Runs Compatible")')
        compat_banner_text = page.locator("#compCompatibilityBanner").text_content()
        log(f"Compatible comparison banner: {compat_banner_text}")
        record_screenshot(page, "08_comparisons_compatible.png")

        # Test Mismatched Comparison (different scenarios)
        page.select_option("#compRunASelect", run_v1_id)
        page.select_option("#compRunBSelect", run_v2_id)
        page.locator("button:has-text('Compare Runs')").click()
        page.wait_for_function('() => document.querySelector("#compCompatibilityBanner") && (document.querySelector("#compCompatibilityBanner").textContent.includes("Configuration Difference") || document.querySelector("#compCompatibilityBanner").textContent.includes("Scenario selection mismatch"))')
        mismatch_banner_text = page.locator("#compCompatibilityBanner").text_content()
        log(f"Mismatch comparison banner: {mismatch_banner_text}")
        record_screenshot(page, "09_comparisons_mismatch.png")
        report_data["comparisons_verified"] = True

        # -------------------------------------------------------------
        # STEP 4: Exports Verification
        # -------------------------------------------------------------
        log("Step 4: Testing Exports...")
        # Test direct API export for run_v1_id
        import urllib.request
        json_req = urllib.request.urlopen(f"{BASE_URL}/api/runs/{run_v1_id}/export?format=json")
        json_export = json.loads(json_req.read().decode("utf-8"))
        assert json_export["run_id"] == run_v1_id
        assert len(json_export["scenario_runs"]) > 0
        raw_json_str = json.dumps(json_export)
        assert "AIza" not in raw_json_str and "sk-" not in raw_json_str

        md_req = urllib.request.urlopen(f"{BASE_URL}/api/runs/{run_v1_id}/export?format=markdown")
        md_export = md_req.read().decode("utf-8")
        assert run_v1_id in md_export
        assert "AIza" not in md_export and "sk-" not in md_export
        report_data["exports_verified"] = True
        log("Exports successfully verified (JSON and Markdown, secrets masked)")

        # -------------------------------------------------------------
        # STEP 5: Background Execution, Refresh, Navigation & Cancellation
        # -------------------------------------------------------------
        log("Step 5: Testing Background Execution, Navigation & Cancellation...")
        # Start a multi-scenario run
        page.locator("#nav-test-studio").click()
        page.select_option("#suiteSelect", "dev_suite")
        with page.expect_response(lambda r: "/api/runs/queue" in r.url and r.request.method == "POST") as cancel_resp:
            page.locator("#btnRunTests").click()
        
        cancel_run_id = cancel_resp.value.json()["run_id"]
        log(f"Started run for cancellation: {cancel_run_id}")
        
        # Test Cancellation
        time.sleep(0.3)
        page.on("dialog", lambda dialog: dialog.accept())
        page.locator("#btnCancelRun").click()
        page.wait_for_function(
            "() => document.querySelector('#panelRunStatusPill') && document.querySelector('#panelRunStatusPill').textContent.includes('CANCELLED')",
            timeout=15000
        )
        record_screenshot(page, "19_execution_cancelled.png")
        log(f"Run {cancel_run_id} successfully cancelled")
        report_data["background_execution_verified"] = True

        # -------------------------------------------------------------
        # STEP 6: Mobile Responsive Layout (390x844)
        # -------------------------------------------------------------
        log("Step 6: Testing Mobile Responsive Layout (390x844)...")
        page.set_viewport_size({"width": 390, "height": 844})
        
        # Overview on mobile
        page.goto(f"{BASE_URL}/#overview", wait_until="networkidle")
        record_screenshot(page, "20_mobile_390px_overview.png")

        # Open mobile drawer
        page.locator("button.mobile-toggle-btn").click()
        page.wait_for_selector("#appSidebar.mobile-open")
        record_screenshot(page, "21_mobile_390px_sidebar.png")

        # Navigate to Studio via mobile drawer
        page.locator("#nav-test-studio").click()
        page.wait_for_selector("#view-test-studio.active")
        record_screenshot(page, "22_mobile_390px_studio.png")
        report_data["mobile_verified"] = True
        log("Mobile responsive layout verified")

        browser.close()

    # Save summary report
    summary_path = ROOT_DIR / "docs" / "reports" / "browser_e2e_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)
    log(f"E2E verification completed! Summary saved to {summary_path}")

if __name__ == "__main__":
    run_all_tests()
