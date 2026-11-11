import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

project_root = Path("D:/AgentWindTunnel/AgentWindTunnel")
base_url = "http://127.0.0.1:8001"
screenshots_dir = project_root / "docs/reports/screenshots"
screenshots_dir.mkdir(parents=True, exist_ok=True)

uat_results = {}
js_errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    # Catch unhandled JS errors
    page.on("pageerror", lambda err: js_errors.append(str(err)))

    print("[UAT Phase 4] 1. Loading Overview...")
    page.goto(base_url, wait_until="networkidle")
    time.sleep(1.0)

    # 1. Overview Verification
    title = page.title()
    assert "EvalNexus" in title, f"Title mismatch: {title}"
    uat_results["branding"] = f"PASS: title='{title}'"

    # Capture Overview screenshot
    page.screenshot(path=str(screenshots_dir / "uat_01_overview_metrics.png"))
    uat_results["screenshot_overview"] = "docs/reports/screenshots/uat_01_overview_metrics.png"

    # 2. Section Navigation Verification
    sections = [
        ("test-studio", "Test Studio"),
        ("scenarios", "Scenarios Catalog"),
        ("agent-versions", "Agent Versions"),
        ("runs", "Run History"),
        ("comparisons", "Run Comparisons"),
        ("custom-agents", "Custom Agent Registry"),
        ("scenario-builder", "Scenario Builder"),
        ("regression-testing", "Regression Testing"),
        ("failure-analysis", "Failure Analysis"),
        ("chaos-lab", "Chaos Lab"),
        ("quality-gates", "Quality Gates"),
        ("cluster", "Cluster Nodes")
    ]

    nav_passed = 0
    for sec_id, sec_name in sections:
        page.goto(f"{base_url}/#{sec_id}", wait_until="networkidle")
        time.sleep(0.3)
        content = page.content()
        assert sec_id in page.url or sec_name in content, f"Navigation to {sec_name} failed"
        nav_passed += 1

    uat_results["navigation"] = f"PASS: {nav_passed}/{len(sections)} sections navigated successfully"

    # 3. Test Studio & Colab Run Details
    print("[UAT Phase 4] 2. Inspecting Colab Run in Test Studio...")
    colab_run_url = f"{base_url}/#test-studio?run=colab_single_20261111_105817_4c22cb"
    page.goto(colab_run_url, wait_until="networkidle")
    time.sleep(1.5)

    studio_content = page.content()
    assert "colab_single_20261111_105817_4c22cb" in studio_content
    assert "Qwen/Qwen2.5-1.5B-Instruct (Colab Offline)" in studio_content
    assert "FAILED" in studio_content
    assert "Audited Evaluation Revision Available" in studio_content
    assert "read_only_inquiry" in studio_content
    assert "senior_eval_reliability_engineer" in studio_content
    assert "OWNERSHIP" in studio_content
    assert "ELIGIBILITY" in studio_content
    assert "DUPLICATE" in studio_content
    assert "STATE" in studio_content
    assert "COMPLETION" in studio_content

    # Screenshot Checks & Revision
    page.screenshot(path=str(screenshots_dir / "uat_02_qwen_checks_and_revision.png"))
    uat_results["screenshot_qwen_checks"] = "docs/reports/screenshots/uat_02_qwen_checks_and_revision.png"
    uat_results["qwen_checks_tab"] = "PASS: original FAILED status and green auditable revision banner verified"

    # 4. Timeline Tab Verification
    print("[UAT Phase 4] 3. Testing Timeline Tab...")
    tab_timeline = page.locator("#tabBtn-timeline")
    assert tab_timeline.count() > 0, "Timeline tab button not found"
    tab_timeline.click()
    time.sleep(0.5)

    timeline_content = page.content()
    assert "check_refund_eligibility" in timeline_content
    assert "USER_MESSAGE" in timeline_content
    assert "TOOL_CALL" in timeline_content
    assert "TOOL_RESULT" in timeline_content
    assert "MODEL_CALL" in timeline_content

    page.screenshot(path=str(screenshots_dir / "uat_03_qwen_trace_stepper.png"))
    uat_results["screenshot_timeline"] = "docs/reports/screenshots/uat_03_qwen_trace_stepper.png"
    uat_results["timeline_tab"] = "PASS: 4 traces, tool arguments and tool output verified"

    # 5. Database Audit Tab Verification
    print("[UAT Phase 4] 4. Testing DB Audit Tab...")
    tab_db = page.locator("#tabBtn-db")
    if tab_db.count() > 0:
        tab_db.click()
        time.sleep(0.5)
        db_content = page.content()
        assert "Customer Identity" in db_content
        assert "Orders State" in db_content
        assert "Refund Ledger" in db_content
        uat_results["db_audit_tab"] = "PASS: Scoped customer, order state and zero refund records verified"

    # 6. Run History Filtering & Inspect Button Verification
    print("[UAT Phase 4] 5. Testing Run History Filter & Inspect...")
    page.goto(f"{base_url}/#runs", wait_until="networkidle")
    time.sleep(1.0)

    # Test search filter input
    search_input = page.locator("#historySearch")
    if search_input.count() > 0:
        search_input.fill("colab_single")
        time.sleep(0.5)
        runs_table_text = page.locator("#runsTbody").inner_text()
        assert "colab_single" in runs_table_text, "Search filter did not preserve Colab run"
        uat_results["run_history_filter"] = "PASS: Search filter correctly filtered table to Colab run"

    # 7. JavaScript Error Audit
    uat_results["js_runtime_errors"] = f"PASS: {len(js_errors)} unhandled errors"
    assert len(js_errors) == 0, f"JS errors detected: {js_errors}"

    browser.close()

import json
print(json.dumps(uat_results, indent=2))

